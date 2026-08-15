from __future__ import annotations

import json
import copy
import hashlib
import io
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aggregate_benchmark import (  # noqa: E402
    collect_comparisons,
    collect_runs,
    evaluate_release,
    validate_evidence_invariants,
)
from evaluation_common import (  # noqa: E402
    CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
    CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
    CANONICAL_GRADER_TIMEOUT_SECONDS,
    CANONICAL_TRIGGER_TIMEOUT_SECONDS,
    CODEX_INVOCATION_MODE,
    CODEX_TIMEOUT_TERMINATION_MODE,
    CODEX_TIMEOUT_ENFORCEMENT_MODE,
    EvaluationError,
    build_run_plan,
    canonical_json_sha256,
    case_contract_document,
    codex_execution_profile,
    codex_base_command,
    codex_runtime_command,
    codex_runtime_environment,
    csv_file_validation_errors,
    execution_receipt_validation_errors,
    file_sha256,
    fixture_csv_validation_errors,
    load_json,
    normalize_suite,
    persisted_run_plan_row,
    require_matching_context,
    require_clean_task_execution,
    require_complete_task_evidence,
    repository_csv_validation_errors,
    repository_source_files,
    run_codex,
    task_evidence_receipt,
    task_artifact_validation_errors,
    validate_task_evidence_binding,
    validate_output_root,
)
from grade_behavioral_benchmark import (  # noqa: E402
    discover_runs,
    grader_input_sha256,
    validate_grade,
)
from run_blind_comparisons import (  # noqa: E402
    blind_bundle_sha256,
    comparison_input_sha256,
    copy_blind_bundle,
    discover_pairs,
    label_map,
    physical_comparison_id,
    validate_comparison,
    validate_comparison_output_binding,
)
from run_trigger_evals import (  # noqa: E402
    body_proven_activation,
    confusion_metrics,
    install_sentinel_skill,
    run_trigger_prediction,
    summarize,
    trigger_task_prompt,
)
from validate_release_eval_plan import (  # noqa: E402
    canonical_case_contract_hashes,
    canonical_contract_hashes,
    canonical_plan_rows,
    validate_release_eval_plan,
)
from validate_eval_suite import validate_model_output_schema, validate_suite  # noqa: E402
import evaluation_common  # noqa: E402
import aggregate_benchmark  # noqa: E402
import grade_behavioral_benchmark  # noqa: E402
import run_behavioral_benchmark  # noqa: E402
import run_blind_comparisons  # noqa: E402
import run_trigger_evals  # noqa: E402


class EvaluationToolingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = normalize_suite(load_json(REPO_ROOT / "evals" / "benchmark-suite.json"))
        cls.thresholds = load_json(REPO_ROOT / "evals" / "release-thresholds.json")

    def test_full_and_primary_run_plan_counts(self) -> None:
        self.assertEqual(len(build_run_plan(self.suite, 3)), 96)
        self.assertEqual(len(build_run_plan(self.suite, 3, include_adversarial=False)), 66)

    def test_history_free_snapshot_manifest_backs_tracked_directory_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            snapshot = Path(temp_name) / "snapshot"
            skill_root = snapshot / "skills" / "example"
            skill_root.mkdir(parents=True)
            skill_file = skill_root / "SKILL.md"
            skill_file.write_text("synthetic skill\n", encoding="utf-8")
            relative = "skills/example/SKILL.md"
            file_digest = hashlib.sha256(skill_file.read_bytes()).hexdigest()
            manifest = {
                "schema_version": 1,
                "project": "report-skills",
                "snapshot_type": "intended-public-repository-tree",
                "git_history_present": False,
                "file_count": 1,
                "files": {relative: file_digest},
            }
            (snapshot / "SOURCE_SNAPSHOT_MANIFEST.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            expected = hashlib.sha256()
            expected.update(relative.encode("utf-8"))
            expected.update(b"\0")
            expected.update(bytes.fromhex(file_digest))

            with patch.object(evaluation_common, "REPO_ROOT", snapshot):
                self.assertEqual(
                    repository_source_files(),
                    {relative: skill_file},
                )
                self.assertEqual(
                    evaluation_common.tracked_directory_sha256(skill_root),
                    expected.hexdigest(),
                )
                cache = snapshot / "scripts" / "__pycache__" / "runtime.pyc"
                cache.parent.mkdir(parents=True)
                cache.write_bytes(b"runtime cache")
                self.assertEqual(
                    evaluation_common.tracked_directory_sha256(skill_root),
                    expected.hexdigest(),
                )
                disguised_cache = snapshot / "scripts" / "__pycache__" / "private.dat"
                disguised_cache.write_bytes(b"not Python bytecode")
                with self.assertRaisesRegex(EvaluationError, "Unmanifested files"):
                    evaluation_common.tracked_directory_sha256(skill_root)
                disguised_cache.unlink()
                injected = snapshot / "evals" / "runs" / "injected" / "transcript.dat"
                injected.parent.mkdir(parents=True)
                injected.write_text("unmanifested raw evidence\n", encoding="utf-8")
                with self.assertRaisesRegex(EvaluationError, "Raw evaluation path"):
                    evaluation_common.tracked_directory_sha256(skill_root)
                injected.unlink()
                cache_bypass = (
                    snapshot / "evals" / "runs" / "__pycache__" / "transcript.pyc"
                )
                cache_bypass.parent.mkdir(parents=True, exist_ok=True)
                cache_bypass.write_bytes(b"raw evidence disguised as bytecode")
                with self.assertRaisesRegex(EvaluationError, "Raw evaluation path"):
                    evaluation_common.tracked_directory_sha256(skill_root)
                cache_bypass.unlink()
                extra = skill_root / "unlisted.txt"
                extra.write_text("unlisted\n", encoding="utf-8")
                with self.assertRaisesRegex(EvaluationError, "Unmanifested files"):
                    evaluation_common.tracked_directory_sha256(skill_root)
                extra.unlink()
                skill_file.write_text("tampered\n", encoding="utf-8")
                with self.assertRaisesRegex(EvaluationError, "hash mismatch"):
                    evaluation_common.tracked_directory_sha256(skill_root)

    def test_repository_source_inventory_uses_index_and_current_worktree_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name) / "repo"
            repo.mkdir()

            def git(*arguments: str) -> None:
                subprocess.run(
                    ["git", "-C", str(repo), *arguments],
                    check=True,
                    capture_output=True,
                )

            git("init", "--quiet")
            git("config", "user.name", "Synthetic Evaluation Test")
            git("config", "user.email", "evaluation-test@example.invalid")
            (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
            tracked_csv = repo / "data.csv"
            tracked_csv.write_text("id,value\n1,ok\n", encoding="utf-8")
            git("add", ".gitignore", "data.csv")
            git("commit", "--quiet", "-m", "source inventory")
            ignored_csv = repo / "ignored" / "raw.csv"
            ignored_csv.parent.mkdir()
            ignored_csv.write_text("id,value\n1,bad\n\n", encoding="utf-8")
            (repo / "SOURCE_SNAPSHOT_MANIFEST.json").write_text(
                "not authoritative inside Git\n", encoding="utf-8"
            )

            with patch.object(evaluation_common, "REPO_ROOT", repo):
                self.assertEqual(
                    set(repository_source_files()),
                    {".gitignore", "data.csv"},
                )
                self.assertEqual(repository_csv_validation_errors(), [])
                tracked_csv.write_text("id,value\n1,ok\n\n", encoding="utf-8")
                self.assertEqual(
                    repository_csv_validation_errors(),
                    ["repository CSV data.csv row 3 has 0 fields; expected 2"],
                )
                tracked_csv.write_text("id,value\n1,ok\n", encoding="utf-8")
                raw_csv = repo / "evals" / "runs" / "raw.csv"
                raw_csv.parent.mkdir(parents=True)
                raw_csv.write_text("id,value\n1,private\n", encoding="utf-8")
                git("add", "-f", "evals/runs/raw.csv")
                with self.assertRaisesRegex(EvaluationError, "Tracked raw evaluation path"):
                    repository_source_files()

    def test_repository_source_inventory_rejects_nonportable_index_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name) / "repo"
            repo.mkdir()
            root_result = subprocess.CompletedProcess(
                [], 0, f"{repo}\n", ""
            )
            object_id = "0" * 40
            invalid_payloads = {
                "symlink": f"120000 {object_id} 0\tdocs/link.csv\0".encode(),
                "submodule": f"160000 {object_id} 0\tvendor/module\0".encode(),
                "conflict stage": f"100644 {object_id} 2\tdata.csv\0".encode(),
                "ADS": f"100644 {object_id} 0\tdata.csv:stream\0".encode(),
                "raw eval": f"100644 {object_id} 0\tEVALS/RUNS/raw.csv\0".encode(),
                "case collision": (
                    f"100644 {object_id} 0\tdocs/Foo.csv\0"
                    f"100644 {'1' * 40} 0\tdocs/foo.csv\0"
                ).encode(),
                "file-directory collision": (
                    f"100644 {object_id} 0\tdocs/Foo\0"
                    f"100644 {'1' * 40} 0\tdocs/foo/child.csv\0"
                ).encode(),
            }
            with patch.object(evaluation_common, "REPO_ROOT", repo):
                for label, payload in invalid_payloads.items():
                    with self.subTest(label=label):
                        inventory_result = subprocess.CompletedProcess(
                            [], 0, payload, b""
                        )
                        with (
                            patch(
                                "evaluation_common.subprocess.run",
                                side_effect=[root_result, inventory_result],
                            ),
                            self.assertRaises(EvaluationError),
                        ):
                            repository_source_files()

    def test_history_free_snapshot_manifest_rejects_noncanonical_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            snapshot = Path(temp_name) / "snapshot"
            snapshot.mkdir()
            manifest_path = snapshot / "SOURCE_SNAPSHOT_MANIFEST.json"
            digest = "0" * 64

            def write_manifest(files: dict[str, str], schema_version: int = 1) -> None:
                manifest_path.write_text(
                    json.dumps(
                        {
                            "schema_version": schema_version,
                            "project": "report-skills",
                            "snapshot_type": "intended-public-repository-tree",
                            "git_history_present": False,
                            "file_count": len(files),
                            "files": files,
                        }
                    ),
                    encoding="utf-8",
                )

            invalid_inventories = {
                "dot segment": {"skills/example/./SKILL.md": digest},
                "empty segment": {"skills/example//SKILL.md": digest},
                "ADS": {"skills/example/file.txt:ads": digest},
                "device": {"skills/example/CONIN$": digest},
                "raw eval": {"EVALS/RUNS/local/transcript.jsonl": digest},
                "case collision": {
                    "skills/example/Foo.txt": digest,
                    "skills/example/foo.txt": "1" * 64,
                },
            }
            with patch.object(evaluation_common, "REPO_ROOT", snapshot):
                write_manifest({"skills/example/SKILL.md": digest}, schema_version=999)
                with self.assertRaises(EvaluationError):
                    evaluation_common.snapshot_manifest_files()
                for label, files in invalid_inventories.items():
                    with self.subTest(label=label):
                        write_manifest(files)
                        with self.assertRaises(EvaluationError):
                            evaluation_common.snapshot_manifest_files()

                write_manifest({"skills/example/SKILL.md": digest})
                (snapshot / ".git").write_text("gitdir: unavailable\n", encoding="utf-8")
                with self.assertRaisesRegex(EvaluationError, "Git metadata is present"):
                    evaluation_common.snapshot_manifest_files()

    def canonical_release_documents(self) -> tuple[dict, dict]:
        hashes = canonical_contract_hashes()
        plan = {
            "suite": str((REPO_ROOT / "evals" / "benchmark-suite.json").resolve()),
            "fixture": str((REPO_ROOT / "examples" / "synthetic-report").resolve()),
            "mode": "execute",
            "repetitions": 3,
            "run_count": 96,
            "pair_count": 48,
            "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
            "configurations": ["with_skill", "without_skill"],
            "baseline_contamination_risk": [],
            "execution_profile": {
                "codex_invocation": CODEX_INVOCATION_MODE,
                "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            },
            "contract_hashes": {
                "benchmark_suite_sha256": hashes["benchmark_suite_sha256"],
                "thresholds_sha256": hashes["thresholds_sha256"],
                "fixture_sha256": hashes["fixture_sha256"],
            },
            "case_contract_hashes": canonical_case_contract_hashes(),
            "runs": canonical_plan_rows(),
        }
        triggers = {
            "suite": str((REPO_ROOT / "evals" / "trigger-evals.json").resolve()),
            "contract_hashes": {
                "trigger_suite_sha256": hashes["trigger_suite_sha256"]
            },
            "timeout_seconds": CANONICAL_TRIGGER_TIMEOUT_SECONDS,
        }
        return plan, triggers

    def test_release_contract_accepts_only_canonical_plan_and_hashes(self) -> None:
        plan, triggers = self.canonical_release_documents()
        issues = validate_release_eval_plan(
            plan,
            triggers,
            REPO_ROOT / "evals" / "release-thresholds.json",
            REPO_ROOT / "evals" / "trigger-evals.json",
        )
        self.assertEqual(issues, [])

    def test_release_contract_rejects_reduced_repetition_plan(self) -> None:
        plan, triggers = self.canonical_release_documents()
        plan["repetitions"] = 1
        plan["run_count"] = 32
        plan["runs"] = build_run_plan(self.suite, 1)
        issues = validate_release_eval_plan(
            plan,
            triggers,
            REPO_ROOT / "evals" / "release-thresholds.json",
            REPO_ROOT / "evals" / "trigger-evals.json",
        )
        self.assertTrue(any("exact canonical 96-run plan" in issue for issue in issues))

    def test_release_contract_rejects_custom_trigger_timeout(self) -> None:
        plan, triggers = self.canonical_release_documents()
        triggers["timeout_seconds"] = CANONICAL_TRIGGER_TIMEOUT_SECONDS - 1
        issues = validate_release_eval_plan(
            plan,
            triggers,
            REPO_ROOT / "evals" / "release-thresholds.json",
            REPO_ROOT / "evals" / "trigger-evals.json",
        )
        self.assertIn("release-contract:trigger timeout is not canonical", issues)

    def test_release_contract_rejects_noncanonical_invocation(self) -> None:
        plan, triggers = self.canonical_release_documents()
        plan["execution_profile"]["codex_invocation"] = "legacy-wrapper"
        issues = validate_release_eval_plan(
            plan,
            triggers,
            REPO_ROOT / "evals" / "release-thresholds.json",
            REPO_ROOT / "evals" / "trigger-evals.json",
        )
        self.assertIn("release-contract:execution method is not canonical", issues)

    def test_release_contract_rejects_custom_inputs_and_hash_drift(self) -> None:
        plan, triggers = self.canonical_release_documents()
        plan["contract_hashes"]["fixture_sha256"] = "0" * 64
        triggers["contract_hashes"]["trigger_suite_sha256"] = "1" * 64
        issues = validate_release_eval_plan(
            plan,
            triggers,
            REPO_ROOT / "custom-thresholds.json",
            REPO_ROOT / "custom-trigger-suite.json",
        )
        self.assertTrue(any("thresholds are not the tracked default" in issue for issue in issues))
        self.assertTrue(any("trigger suite is not the tracked default" in issue for issue in issues))
        self.assertTrue(any("behavioral input receipts" in issue for issue in issues))
        self.assertTrue(any("trigger input receipt" in issue for issue in issues))

    def test_release_contract_rejects_baseline_contamination(self) -> None:
        plan, triggers = self.canonical_release_documents()
        plan["baseline_contamination_risk"] = ["evidence-first-report"]
        issues = validate_release_eval_plan(
            plan,
            triggers,
            REPO_ROOT / "evals" / "release-thresholds.json",
            REPO_ROOT / "evals" / "trigger-evals.json",
        )
        self.assertIn("release-contract:baseline contamination risk must be empty", issues)

    def test_dry_run_is_compact_by_default(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_behavioral_benchmark.py"), "--dry-run"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["run_count"], 96)
        self.assertNotIn("runs", document)

    def test_validator_accepts_committed_contracts(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_eval_suite.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_model_output_schemas_require_every_declared_object_property(self) -> None:
        schema_names = (
            "task-run-output.schema.json",
            "grading-output.schema.json",
            "blind-comparison-output.schema.json",
            "trigger-output.schema.json",
        )

        errors: list[str] = []
        for name in schema_names:
            schema = json.loads((REPO_ROOT / "evals" / "schemas" / name).read_text(encoding="utf-8"))
            validate_model_output_schema(schema, name, errors)
        self.assertEqual(errors, [])

    def test_model_output_schema_validator_rejects_open_object_shapes(self) -> None:
        invalid_schemas = (
            {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            {
                "type": "object",
                "additionalProperties": True,
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"type": "string"}},
                "required": [],
            },
        )
        for schema in invalid_schemas:
            with self.subTest(schema=schema):
                errors: list[str] = []
                validate_model_output_schema(schema, "synthetic.json", errors)
                self.assertTrue(errors)

    def test_raw_output_refuses_tracked_results(self) -> None:
        with self.assertRaises(EvaluationError):
            validate_output_root(REPO_ROOT / "evals" / "results" / "raw")

    def test_codex_command_pins_reasoning_effort(self) -> None:
        command = codex_base_command(
            "codex.cmd",
            REPO_ROOT,
            "read-only",
            REPO_ROOT / "evals" / "schemas" / "trigger-output.schema.json",
            REPO_ROOT / "evals" / "runs" / "output.json",
            model="gpt-5.6-sol",
            reasoning_effort="ultra",
        )
        self.assertIn("gpt-5.6-sol", command)
        self.assertIn('model_reasoning_effort="ultra"', command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-sol")
        self.assertEqual(
            command[command.index("--config") + 1], 'model_reasoning_effort="ultra"'
        )
        self.assertNotIn("--approve-for-me", command)
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")

    def test_workspace_write_command_uses_automatic_approval_review(self) -> None:
        command = codex_base_command(
            "codex.cmd",
            REPO_ROOT,
            "workspace-write",
            REPO_ROOT / "evals" / "schemas" / "task-run-output.schema.json",
            REPO_ROOT / "evals" / "runs" / "output.json",
            model="gpt-5.6-sol",
            reasoning_effort="ultra",
        )
        self.assertIn("--approve-for-me", command)
        self.assertNotIn("--sandbox", command)

    def test_behavioral_prompt_limits_skill_bodies_to_the_candidate(self) -> None:
        with_skill = {"configuration": "with_skill", "skill": "evidence-first-report", "prompt": "Task"}
        baseline = {"configuration": "without_skill", "skill": "evidence-first-report", "prompt": "Task"}
        self.assertIn("only skill package you may read or use", run_behavioral_benchmark.task_prompt(with_skill))
        self.assertIn("Do not read or invoke any other skill body", run_behavioral_benchmark.task_prompt(baseline))

    def test_behavioral_trace_rejects_non_candidate_skill_body_reads(self) -> None:
        run = {"configuration": "with_skill", "skill": "evidence-first-report"}

        def transcript(command: str) -> str:
            return json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "cmd-1", "type": "command_execution", "command": command},
                }
            )

        allowed = transcript(r"Get-Content .benchmark_skill\\evidence-first-report\\SKILL.md")
        global_read = transcript(r"Get-Content Q:\\fixture\\.codex\\skills\\other\\SKILL.md")
        wrong_candidate = transcript("Get-Content .benchmark_skill/report-skills/SKILL.md")
        lookalike_candidate = transcript(
            "Get-Content .benchmark_skill/evidence-first-report-evil/SKILL.md"
        )
        mixed_read = transcript(
            "Get-Content .benchmark_skill/evidence-first-report/SKILL.md, "
            "Q:/fixture/.codex/skills/other/SKILL.md"
        )
        plugin_read = transcript(
            "Get-Content Q:/fixture/.codex/plugins/cache/vendor/package/skills/other/SKILL.md"
        )
        allowed_join_path = transcript(
            r"Get-Content (Join-Path '.benchmark_skill\evidence-first-report' 'SKILL.md')"
        )
        global_join_path = transcript(
            r"Get-Content (Join-Path 'Q:\fixture\.codex\skills\other' 'SKILL.md')"
        )
        self.assertEqual(run_behavioral_benchmark.skill_body_read_violations(allowed, run), [])
        self.assertEqual(
            run_behavioral_benchmark.skill_body_read_violations(allowed_join_path, run), []
        )
        self.assertTrue(run_behavioral_benchmark.skill_body_read_violations(global_read, run))
        self.assertTrue(run_behavioral_benchmark.skill_body_read_violations(global_join_path, run))
        self.assertTrue(run_behavioral_benchmark.skill_body_read_violations(wrong_candidate, run))
        self.assertTrue(run_behavioral_benchmark.skill_body_read_violations(lookalike_candidate, run))
        self.assertTrue(run_behavioral_benchmark.skill_body_read_violations(mixed_read, run))
        self.assertTrue(run_behavioral_benchmark.skill_body_read_violations(plugin_read, run))
        baseline = {"configuration": "without_skill", "skill": "evidence-first-report"}
        self.assertTrue(run_behavioral_benchmark.skill_body_read_violations(allowed, baseline))

    def test_behavioral_loader_diagnostics_are_path_free_counts(self) -> None:
        stderr = "\n".join(
            [
                "WARN codex_skills_extension::loader::metadata: ignoring synthetic-openai-yaml",
                "ERROR failed to load skill .codex/skills/synthetic/SKILL.md",
            ]
        )
        diagnostics = run_behavioral_benchmark.skill_loader_diagnostics(stderr)
        self.assertEqual(diagnostics["ignore_user_config_scope"], "config.toml_only")
        self.assertEqual(diagnostics["metadata_warning_count"], 1)
        self.assertEqual(diagnostics["failed_skill_load_count"], 1)
        self.assertNotIn("synthetic-openai-yaml", json.dumps(diagnostics))

    def test_live_profile_verifies_cli_catalog_and_records_provenance(self) -> None:
        model_entry = {
            "slug": "gpt-5.6-sol",
            "description": "Maximum reasoning with typographic punctuation: \u2014",
            "default_reasoning_level": "low",
            "supported_reasoning_levels": [{"effort": "low"}, {"effort": "ultra"}],
        }
        with tempfile.TemporaryDirectory() as temp_name:
            command = Path(temp_name) / "codex.exe"
            command.write_bytes(b"MZ synthetic native")
            results = [
                subprocess.CompletedProcess([], 0, "codex-cli 0.147.0\n", ""),
                subprocess.CompletedProcess([], 0, json.dumps({"models": [model_entry]}), ""),
            ]
            with (
                patch("evaluation_common.subprocess.run", side_effect=results),
                patch("evaluation_common.platform.system", return_value="Windows"),
                patch("evaluation_common.platform.release", return_value="11"),
                patch("evaluation_common.platform.machine", return_value="ARM64"),
            ):
                profile = codex_execution_profile(str(command), "gpt-5.6-sol", "ultra")
        self.assertEqual(profile["codex_cli_version"], "codex-cli 0.147.0")
        self.assertEqual(profile["model"], "gpt-5.6-sol")
        self.assertEqual(profile["reasoning_effort"], "ultra")
        self.assertRegex(profile["codex_command_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(profile["codex_implementation_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(profile["codex_managed_environment_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(profile["selected_model_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(profile["codex_invocation"], CODEX_INVOCATION_MODE)
        self.assertEqual(
            profile["codex_timeout_enforcement"], CODEX_TIMEOUT_ENFORCEMENT_MODE
        )

    def test_packaged_wrapper_resolves_and_probes_exact_native_runtime(self) -> None:
        model_entry = {
            "slug": "gpt-5.6-sol",
            "default_reasoning_level": "low",
            "supported_reasoning_levels": [{"effort": "ultra"}],
        }
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            command = root / "codex.cmd"
            command.write_text("@echo off\n", encoding="utf-8")
            executable_name = "codex.exe" if sys.platform == "win32" else "codex"
            native = (
                root
                / "node_modules"
                / "@openai"
                / "codex"
                / "node_modules"
                / "@openai"
                / "codex-test"
                / "vendor"
                / "target"
                / "bin"
                / executable_name
            )
            native.parent.mkdir(parents=True)
            native.write_bytes(b"native")
            results = [
                subprocess.CompletedProcess([], 0, "codex-cli 0.147.0\n", ""),
                subprocess.CompletedProcess([], 0, json.dumps({"models": [model_entry]}), ""),
            ]
            with (
                patch("evaluation_common.subprocess.run", side_effect=results) as mocked,
                patch("evaluation_common.platform.system", return_value="Windows"),
                patch("evaluation_common.platform.release", return_value="11"),
                patch("evaluation_common.platform.machine", return_value="ARM64"),
            ):
                profile = codex_execution_profile(str(command), "gpt-5.6-sol", "ultra")
            self.assertEqual(Path(profile["codex_implementation"]), native.resolve())
            self.assertEqual(mocked.call_args_list[0].args[0][0], str(native.resolve()))
            self.assertEqual(mocked.call_args_list[1].args[0][0], str(native.resolve()))
            environment = codex_runtime_environment(profile)
            self.assertEqual(environment["CODEX_MANAGED_PACKAGE_ROOT"], str(native.parents[6]))
            self.assertEqual(environment["CODEX_MANAGED_BY_NPM"], "1")
            tampered = dict(profile, codex_managed_by="pnpm")
            with self.assertRaisesRegex(EvaluationError, "receipt does not match"):
                codex_runtime_environment(tampered)

    def test_packaged_wrapper_native_resolution_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            command = root / "codex.cmd"
            command.write_text("@echo off\n", encoding="utf-8")
            package = root / "node_modules" / "@openai" / "codex"
            package.mkdir(parents=True)
            with self.assertRaisesRegex(EvaluationError, "found 0 candidates"):
                codex_execution_profile(str(command), "gpt-5.6-sol", "ultra")
            executable_name = "codex.exe" if sys.platform == "win32" else "codex"
            for name in ("codex-one", "codex-two"):
                native = package / "node_modules" / "@openai" / name / "vendor" / name / "bin" / executable_name
                native.parent.mkdir(parents=True)
                native.write_bytes(b"native")
            with self.assertRaisesRegex(EvaluationError, "found 2 candidates"):
                codex_execution_profile(str(command), "gpt-5.6-sol", "ultra")

    def test_profiled_native_runtime_must_exist_and_match_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            implementation = Path(temp_name) / "codex.exe"
            implementation.write_bytes(b"native implementation")
            profile = {
                "codex_invocation": CODEX_INVOCATION_MODE,
                "codex_implementation": str(implementation),
                "codex_implementation_sha256": hashlib.sha256(
                    implementation.read_bytes()
                ).hexdigest(),
            }
            self.assertEqual(codex_runtime_command(profile), str(implementation.resolve()))
            implementation.write_bytes(b"changed implementation")
            with self.assertRaisesRegex(EvaluationError, "changed during evaluation"):
                codex_runtime_command(profile)

    def test_run_codex_timeout_kills_descendants_and_never_salvages_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            sentinel = Path(temp_name) / "orphan-survived.txt"
            child = (
                "import time; from pathlib import Path; "
                f"time.sleep(2); Path({str(sentinel)!r}).write_text('orphan', encoding='utf-8')"
            )
            parent = (
                "import json, subprocess, sys, time; "
                "print(json.dumps({'type':'turn.completed'}), flush=True); "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                "time.sleep(30)"
            )
            result = run_codex([sys.executable, "-c", parent], "", timeout=1)
            self.assertEqual(result.returncode, 124)
            self.assertTrue(result.timed_out)
            self.assertEqual(result.termination_reason, "timeout")
            self.assertEqual(result.terminal_event_count, 1)
            self.assertGreaterEqual(result.timeout_overrun_seconds, 0)
            time.sleep(2.5)
            self.assertFalse(sentinel.exists())
            self.assertEqual(result.termination_method, CODEX_TIMEOUT_TERMINATION_MODE)
            self.assertEqual(result.timeout_enforcement, CODEX_TIMEOUT_ENFORCEMENT_MODE)

    def test_run_codex_clean_exit_has_terminal_receipt(self) -> None:
        script = "import json; print(json.dumps({'type':'turn.completed'}), flush=True)"
        result = run_codex([sys.executable, "-c", script], "", timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.termination_reason, "process-exit")
        self.assertEqual(result.termination_method, "natural-exit")
        self.assertEqual(result.timeout_seconds, 10)
        self.assertEqual(result.timeout_overrun_seconds, 0)
        self.assertEqual(result.terminal_event_count, 1)
        self.assertEqual(result.failed_terminal_event_count, 0)
        self.assertEqual(result.timeout_enforcement, CODEX_TIMEOUT_ENFORCEMENT_MODE)

    def test_execution_receipt_rejects_failed_and_completed_terminal_events(self) -> None:
        script = (
            "import json; "
            "print(json.dumps({'type':'turn.failed'})); "
            "print(json.dumps({'type':'turn.completed'}))"
        )
        result = run_codex([sys.executable, "-c", script], "", timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.terminal_event_count, 1)
        self.assertEqual(result.failed_terminal_event_count, 1)
        self.assertTrue(
            any(
                "failed terminal event" in error
                for error in execution_receipt_validation_errors(result, 10, "synthetic")
            )
        )

    def test_clean_task_precondition_rejects_timeout_even_with_terminal_event(self) -> None:
        clean = {
            "returncode": 0,
            "validation_errors": [],
            "timed_out": False,
            "termination_reason": "process-exit",
            "termination_method": "natural-exit",
            "timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
            "timeout_overrun_seconds": 0.0,
            "terminal_event_count": 1,
            "failed_terminal_event_count": 0,
            "execution_profile": {
                "codex_invocation": CODEX_INVOCATION_MODE,
                "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            },
        }
        require_clean_task_execution(clean, "clean")
        failed = {
            **clean,
            "returncode": 124,
            "validation_errors": ["task exited 124"],
            "timed_out": True,
            "termination_reason": "timeout",
            "terminal_event_count": 1,
        }
        with self.assertRaisesRegex(EvaluationError, "cannot be graded or compared"):
            require_clean_task_execution(failed, "timed-out")

    def test_downstream_requires_exact_complete_clean_task_set(self) -> None:
        profile = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "ultra",
            "codex_invocation": CODEX_INVOCATION_MODE,
            "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            "codex_cli_version": "codex-cli 0.147.0",
            "codex_command_sha256": "a" * 64,
            "codex_implementation_sha256": "b" * 64,
            "codex_managed_environment_sha256": "c" * 64,
            "selected_model_sha256": "d" * 64,
            "python_version": "3.12.0",
            "platform": "test",
        }
        repository = {
            "root": "repo",
            "commit": "e" * 40,
            "tree": "f" * 40,
            "dirty": False,
        }
        clean_receipt = {
            "returncode": 0,
            "validation_errors": [],
            "timed_out": False,
            "termination_reason": "process-exit",
            "termination_method": "natural-exit",
            "timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
            "timeout_overrun_seconds": 0.0,
            "terminal_event_count": 1,
            "failed_terminal_event_count": 0,
            "execution_profile": profile,
            "repository": repository,
        }
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            rows = [
                {
                    "run_id": "one",
                    "pair_id": "pair-one",
                    "case_id": "case-one",
                    "case_kind": "primary",
                    "skill": "one",
                    "configuration": "with_skill",
                    "repetition": 1,
                },
                {
                    "run_id": "two",
                    "pair_id": "pair-one",
                    "case_id": "case-one",
                    "case_kind": "primary",
                    "skill": "one",
                    "configuration": "without_skill",
                    "repetition": 1,
                },
            ]
            contracts = {
                row["run_id"]: {
                    "prompt": "Synthetic task",
                    "assertions": [
                        {"assertion_id": "a", "text": "A", "weight": 100, "blocking": True}
                    ],
                }
                for row in rows
            }
            (root / "run-plan.json").write_text(
                json.dumps(
                    {
                        "runs": rows,
                        "case_contract_hashes": {
                            run_id: canonical_json_sha256(contract)
                            for run_id, contract in contracts.items()
                        },
                        "execution_profile": profile,
                        "repository": repository,
                    }
                ),
                encoding="utf-8",
            )

            def write_task(storage_id: str, row: dict, receipt: dict) -> Path:
                run_dir = root / "runs" / storage_id
                (run_dir / "workspace" / "artifacts").mkdir(parents=True)
                (run_dir / "task-output.json").write_text("{}\n", encoding="utf-8")
                (run_dir / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
                (run_dir / "stderr.txt").write_text("", encoding="utf-8")
                (run_dir / "case_contract.json").write_text(
                    json.dumps(contracts[row["run_id"]]) + "\n", encoding="utf-8"
                )
                metadata = {
                    **row,
                    **receipt,
                    "storage_id": storage_id,
                    "task_evidence": task_evidence_receipt(run_dir),
                }
                (run_dir / "run_metadata.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                return run_dir

            write_task("001", rows[0], clean_receipt)
            with self.assertRaisesRegex(EvaluationError, "does not exactly match"):
                require_complete_task_evidence(root)
            second = write_task("002", rows[1], clean_receipt)
            self.assertEqual(
                [path.name for path in require_complete_task_evidence(root)],
                ["001", "002"],
            )
            failed = load_json(second / "run_metadata.json")
            failed.update({"returncode": 124, "timed_out": True})
            (second / "run_metadata.json").write_text(json.dumps(failed), encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, "cannot be graded or compared"):
                require_complete_task_evidence(root)

    def test_task_evidence_binding_rejects_contract_or_artifact_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            run_dir = Path(temp_name)
            (run_dir / "workspace" / "artifacts").mkdir(parents=True)
            (run_dir / "workspace" / "artifacts" / "report.md").write_text(
                "original", encoding="utf-8"
            )
            (run_dir / "task-output.json").write_text("{}\n", encoding="utf-8")
            (run_dir / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "stderr.txt").write_text("", encoding="utf-8")
            contract = {"prompt": "Do work", "assertions": []}
            (run_dir / "case_contract.json").write_text(
                json.dumps(contract) + "\n", encoding="utf-8"
            )
            metadata = {"task_evidence": task_evidence_receipt(run_dir)}
            expected_contract = canonical_json_sha256(contract)
            self.assertEqual(
                validate_task_evidence_binding(metadata, run_dir, expected_contract), []
            )
            (run_dir / "workspace" / "artifacts" / "report.md").write_text(
                "changed", encoding="utf-8"
            )
            self.assertTrue(validate_task_evidence_binding(metadata, run_dir, expected_contract))

    def test_csv_validation_rejects_blank_records_and_preserves_valid_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "register.csv"
            valid_payloads = (
                b"id,value\nE-001,ok",
                b"id,value\nE-001,ok\n",
                b"id,value\r\nE-001,ok\r\n",
                b'id,value\r\nE-001,"line one\r\n\r\nline two"\r\n',
                b'id,value\nE-001,"comma, and ""quote"""\n',
                b"id,value\nE-001,\n",
            )
            for payload in valid_payloads:
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    self.assertEqual(csv_file_validation_errors(path, "register.csv"), [])

            path.write_bytes(b"id,value\nE-001,ok\n\n")
            self.assertEqual(
                csv_file_validation_errors(path, "register.csv"),
                ["artifact CSV register.csv row 3 has 0 fields; expected 2"],
            )
            path.write_bytes(b"id,value\n,\n")
            self.assertEqual(
                csv_file_validation_errors(path, "register.csv"),
                ["artifact CSV register.csv row 2 is blank"],
            )

    def test_fixture_csv_validation_covers_root_nested_and_declared_defect_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            fixture = Path(temp_name) / "fixture"
            nested = fixture / "nested"
            nested.mkdir(parents=True)
            bad = nested / "bad.csv"
            bad.write_text("a,b\n1,2\n\n", encoding="utf-8")
            expected = ["fixture CSV nested/bad.csv row 3 has 0 fields; expected 2"]
            self.assertEqual(fixture_csv_validation_errors(fixture), expected)

            suite = copy.deepcopy(self.suite)
            suite["fixture"] = str(fixture)
            errors: list[str] = []
            validate_suite(Path(temp_name) / "suite.json", suite, errors)
            self.assertIn(expected[0], errors)

            bad.unlink()
            root_csv = fixture / "root.csv"
            root_csv.write_text("a,b\n1,2\n\n", encoding="utf-8")
            self.assertEqual(
                fixture_csv_validation_errors(fixture),
                ["fixture CSV root.csv row 3 has 0 fields; expected 2"],
            )
            root_csv.unlink()
            declared_defect = fixture / "intentional-defects" / "malformed.csv"
            declared_defect.parent.mkdir()
            declared_defect.write_text("a,b\n1,2\n\n", encoding="utf-8")
            self.assertEqual(
                fixture_csv_validation_errors(fixture),
                [
                    "fixture CSV intentional-defects/malformed.csv row 3 has "
                    "0 fields; expected 2"
                ],
            )
            declared_defect.unlink()

            nested_boundary_name = (
                fixture / "usable" / "intentional-defects" / "bad.csv"
            )
            nested_boundary_name.parent.mkdir(parents=True)
            nested_boundary_name.write_text("a,b\n1,2\n\n", encoding="utf-8")
            self.assertEqual(
                fixture_csv_validation_errors(fixture),
                [
                    "fixture CSV usable/intentional-defects/bad.csv row 3 has "
                    "0 fields; expected 2"
                ],
            )
            nested_boundary_name.unlink()

            lookalike = fixture / "intentional-defects-public" / "bad.csv"
            lookalike.parent.mkdir()
            lookalike.write_text("a,b\n1,2\n\n", encoding="utf-8")
            self.assertEqual(
                fixture_csv_validation_errors(fixture),
                [
                    "fixture CSV intentional-defects-public/bad.csv row 3 has "
                    "0 fields; expected 2"
                ],
            )

    def test_task_artifact_csv_validation_fails_closed_on_shifted_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name) / "workspace"
            artifacts = workspace / "artifacts"
            artifacts.mkdir(parents=True)
            register = artifacts / "evidence-register.csv"
            header = (
                "evidence_id,source_id,locator,evidence_kind,observation,method,population,"
                "geography,period,unit,denominator,limitations,access_verified,notes\n"
            )
            register.write_text(
                header
                + "E-S2-002,SYN-S2,operations.csv rows 2-7,calculation,Completion ratio,"
                + 'Sum completed / scheduled,"5,090 scheduled entries",not stated,'
                + "2030-01 to 2030-06,percent,5090,Exact June date not stated,true,Reproduced\n",
                encoding="utf-8",
            )
            self.assertEqual(task_artifact_validation_errors(workspace), [])
            register.write_text(
                header
                + "E-S2-002,SYN-S2,operations.csv rows 2-7,calculation,Completion ratio,"
                + "Sum completed / scheduled,5,090 scheduled entries,not stated,"
                + "2030-01 to 2030-06,percent,5090,Exact June date not stated,true,Reproduced\n",
                encoding="utf-8",
            )
            self.assertEqual(
                task_artifact_validation_errors(workspace),
                ["artifact CSV artifacts/evidence-register.csv row 2 has 15 fields; expected 14"],
            )

    def test_task_artifact_contract_binds_header_rows_and_unique_key(self) -> None:
        contract = {
            "artifact_checks": [
                {
                    "type": "csv_rectangular",
                    "path": "artifacts/evidence-register.csv",
                    "header": ["evidence_id", "population", "period", "unit"],
                    "min_rows": 2,
                    "unique_key": "evidence_id",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name) / "workspace"
            artifacts = workspace / "artifacts"
            artifacts.mkdir(parents=True)
            register = artifacts / "evidence-register.csv"
            register.write_text(
                "evidence_id,population,period,unit\n"
                'E-001,"5,090 scheduled entries",2030-01 to 2030-06,count\n'
                "E-002,500 respondents,2030-06,percent\n",
                encoding="utf-8",
            )
            self.assertEqual(
                task_artifact_validation_errors(workspace, contract, "with_skill"), []
            )
            register.write_text(
                "population,evidence_id,period,unit\n"
                "500 respondents,E-001,2030-06,percent\n"
                "500 respondents,E-001,2030-06,percent\n",
                encoding="utf-8",
            )
            errors = task_artifact_validation_errors(workspace, contract, "with_skill")
            self.assertIn(
                "artifact CSV artifacts/evidence-register.csv header does not match its case contract",
                errors,
            )
            self.assertIn(
                "artifact CSV artifacts/evidence-register.csv row 3 has a blank, padded, or duplicate evidence_id",
                errors,
            )
            register.write_text(
                "evidence_id,population,period,unit\n"
                " E-001,500 respondents,2030-06,percent\n"
                "E-002,500 respondents,2030-06,percent\n",
                encoding="utf-8",
            )
            self.assertIn(
                "artifact CSV artifacts/evidence-register.csv row 2 has a blank, padded, or duplicate evidence_id",
                task_artifact_validation_errors(workspace, contract, "with_skill"),
            )

    def test_task_artifact_contract_rejects_unsafe_or_missing_csv(self) -> None:
        unsafe_contract = {
            "artifact_checks": [
                {
                    "type": "csv_rectangular",
                    "path": "../outside.csv",
                    "header": ["id"],
                    "min_rows": 1,
                    "unexpected": True,
                }
            ]
        }
        missing_contract = {
            "artifact_checks": [
                {
                    "type": "csv_rectangular",
                    "path": "artifacts/evidence-register.csv",
                    "header": ["evidence_id"],
                    "min_rows": 1,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name) / "workspace"
            (workspace / "artifacts").mkdir(parents=True)
            self.assertIn(
                "artifact_checks[1] path must be a safe relative artifacts path",
                task_artifact_validation_errors(workspace, unsafe_contract),
            )
            self.assertIn(
                "artifact_checks[1] has unexpected properties: ['unexpected']",
                task_artifact_validation_errors(workspace, unsafe_contract),
            )
            self.assertEqual(
                task_artifact_validation_errors(workspace, missing_contract),
                ["artifact CSV artifacts/evidence-register.csv must be a regular file"],
            )

    def test_scoped_artifact_contract_does_not_require_candidate_files_in_baseline(self) -> None:
        contract = {
            "artifact_checks": [
                {
                    "type": "csv_rectangular",
                    "path": "artifacts/evidence-register.csv",
                    "header": ["evidence_id"],
                    "min_rows": 1,
                    "configurations": ["with_skill"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name) / "workspace"
            (workspace / "artifacts").mkdir(parents=True)
            self.assertEqual(
                task_artifact_validation_errors(workspace, contract, "without_skill"), []
            )
            self.assertEqual(
                task_artifact_validation_errors(workspace, contract, "with_skill"),
                ["artifact CSV artifacts/evidence-register.csv must be a regular file"],
            )

    def test_persisted_run_plan_row_keeps_artifact_checks_only_in_contract_hash(self) -> None:
        row = {
            "run_id": "case__with_skill__r01",
            "prompt": "Do work",
            "assertions": [],
            "artifact_checks": [{"type": "csv_rectangular"}],
            "configuration": "with_skill",
        }
        persisted = persisted_run_plan_row(row)
        self.assertEqual(
            persisted,
            {"run_id": "case__with_skill__r01", "configuration": "with_skill"},
        )
        self.assertIn("artifact_checks", case_contract_document(row))

    def test_task_artifact_csv_validation_rejects_bad_encoding_and_quoting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name) / "workspace"
            artifacts = workspace / "artifacts"
            artifacts.mkdir(parents=True)
            register = artifacts / "evidence-register.csv"
            register.write_bytes(b"id,value\nE-001,\xff\n")
            self.assertTrue(
                any(
                    "cannot be parsed" in error
                    for error in task_artifact_validation_errors(workspace)
                )
            )
            register.write_text(
                'id,value\nE-001,bad"quote\n',
                encoding="utf-8",
            )
            self.assertTrue(
                any(
                    "invalid quote in an unquoted field" in error
                    for error in task_artifact_validation_errors(workspace)
                )
            )
            register.write_text(
                'id,value\nE-001,"bad""quote"\n',
                encoding="utf-8",
            )
            self.assertEqual(task_artifact_validation_errors(workspace), [])
            register.write_text(
                'id,value\nE-001,"unterminated\n',
                encoding="utf-8",
            )
            self.assertTrue(
                any(
                    "cannot be parsed" in error
                    for error in task_artifact_validation_errors(workspace)
                )
            )

    def test_task_evidence_binding_rejects_malformed_csv_even_when_hashes_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            run_dir = Path(temp_name)
            artifacts = run_dir / "workspace" / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "evidence-register.csv").write_text(
                "evidence_id,population,period,unit\n"
                "E-001,5,090 scheduled entries,2030-01 to 2030-06,count\n",
                encoding="utf-8",
            )
            (run_dir / "task-output.json").write_text("{}\n", encoding="utf-8")
            (run_dir / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "stderr.txt").write_text("", encoding="utf-8")
            contract = {"prompt": "Do work", "assertions": []}
            (run_dir / "case_contract.json").write_text(
                json.dumps(contract) + "\n", encoding="utf-8"
            )
            metadata = {"task_evidence": task_evidence_receipt(run_dir)}
            errors = validate_task_evidence_binding(
                metadata, run_dir, canonical_json_sha256(contract)
            )
            self.assertIn(
                "artifact CSV artifacts/evidence-register.csv row 2 has 5 fields; expected 4",
                errors,
            )

    def test_grader_partial_attempt_and_overwrite_refuse_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            run_dir = root / "runs" / "001"
            run_dir.mkdir(parents=True)
            (run_dir / "grader_attempt.json").write_text("{}\n", encoding="utf-8")
            stderr = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "grade_behavioral_benchmark.py",
                        str(root),
                        "--execute",
                        "--model",
                        "gpt-5.6-sol",
                        "--reasoning-effort",
                        "ultra",
                    ],
                ),
                patch.object(
                    grade_behavioral_benchmark,
                    "require_complete_task_evidence",
                    return_value=[run_dir],
                ),
                patch.object(
                    grade_behavioral_benchmark,
                    "run_codex",
                    side_effect=AssertionError("model call must not run"),
                ),
                redirect_stderr(stderr),
            ):
                self.assertEqual(grade_behavioral_benchmark.main(), 2)
            self.assertIn("Partial grading evidence", stderr.getvalue())

            for module, argv in (
                (
                    grade_behavioral_benchmark,
                    ["grade_behavioral_benchmark.py", str(root), "--overwrite"],
                ),
                (
                    run_blind_comparisons,
                    ["run_blind_comparisons.py", str(root), "--overwrite"],
                ),
            ):
                with (
                    self.subTest(module=module.__name__),
                    patch.object(sys, "argv", argv),
                    patch.object(
                        module,
                        "run_codex",
                        side_effect=AssertionError("model call must not run"),
                    ),
                    redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(module.main(), 2)

    def test_blind_partial_evidence_refuses_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            target = root / "comparisons" / "001"
            target.mkdir(parents=True)
            (target / "comparison.json").write_text("{}\n", encoding="utf-8")
            (target / "comparison_metadata.json").write_text("{}\n", encoding="utf-8")
            (root / "comparisons" / "storage-map.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "pairs": [{"storage_id": "001", "pair_id": "pair-one"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            pair = {"pair_id": "pair-one", "case_id": "case-one", "runs": {}}
            stderr = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "run_blind_comparisons.py",
                        str(root),
                        "--execute",
                        "--model",
                        "gpt-5.6-sol",
                        "--reasoning-effort",
                        "ultra",
                    ],
                ),
                patch.object(
                    run_blind_comparisons,
                    "require_complete_task_evidence",
                    return_value=[],
                ),
                patch.object(
                    run_blind_comparisons, "discover_pairs", return_value=[pair]
                ),
                patch.object(
                    run_blind_comparisons,
                    "run_codex",
                    side_effect=AssertionError("model call must not run"),
                ),
                redirect_stderr(stderr),
            ):
                self.assertEqual(run_blind_comparisons.main(), 2)
            self.assertIn("Partial comparison evidence", stderr.getvalue())

    def test_live_profile_rejects_unsupported_effort(self) -> None:
        model_entry = {
            "slug": "gpt-5.6-sol",
            "default_reasoning_level": "low",
            "supported_reasoning_levels": [{"effort": "low"}],
        }
        with tempfile.TemporaryDirectory() as temp_name:
            command = Path(temp_name) / "codex.exe"
            command.write_bytes(b"MZ synthetic native")
            results = [
                subprocess.CompletedProcess([], 0, "codex-cli 0.147.0\n", ""),
                subprocess.CompletedProcess([], 0, json.dumps({"models": [model_entry]}), ""),
            ]
            with patch("evaluation_common.subprocess.run", side_effect=results):
                with self.assertRaisesRegex(EvaluationError, "not supported"):
                    codex_execution_profile(str(command), "gpt-5.6-sol", "ultra")

    def test_behavioral_dry_run_does_not_require_git_receipt(self) -> None:
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", ["run_behavioral_benchmark.py", "--dry-run"]),
            patch.object(
                run_behavioral_benchmark,
                "repository_receipt",
                side_effect=AssertionError("dry-run must not inspect Git"),
            ),
            redirect_stdout(stdout),
        ):
            self.assertEqual(run_behavioral_benchmark.main(), 0)
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["run_count"], 96)
        self.assertEqual(
            plan["timeout_seconds"], CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS
        )
        self.assertEqual(plan["case_contract_hash_count"], 96)
        self.assertNotIn("case_contract_hashes", plan)

    def test_behavioral_storage_ids_are_compact_stable_and_unique(self) -> None:
        ids = [run_behavioral_benchmark.physical_run_id(index, 96) for index in range(1, 97)]
        self.assertEqual(ids[0], "001")
        self.assertEqual(ids[-1], "096")
        self.assertEqual(len(set(ids)), 96)

    def test_behavioral_path_budget_fails_before_live_execution(self) -> None:
        plan = build_run_plan(self.suite, 3)
        fixture = REPO_ROOT / "examples" / "synthetic-report"
        with self.assertRaisesRegex(EvaluationError, "Use a shorter --run-id or --output-root"):
            run_behavioral_benchmark.validate_workspace_path_budget(
                REPO_ROOT / ("x" * 80), plan, fixture, path_limit=180
            )

    def test_behavioral_main_rejects_fixture_csv_before_output_or_profile(self) -> None:
        stderr = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_behavioral_benchmark.py",
                    "--execute",
                    "--run-id",
                    "fixture-csv-order-test",
                    "--model",
                    "gpt-5.6-sol",
                    "--reasoning-effort",
                    "ultra",
                ],
            ),
            patch.object(
                run_behavioral_benchmark,
                "fixture_csv_validation_errors",
                return_value=["fixture CSV inputs/bad.csv row 3 has 0 fields; expected 2"],
            ),
            patch.object(
                run_behavioral_benchmark,
                "validate_output_root",
                side_effect=AssertionError("output setup must not run"),
            ),
            patch.object(
                run_behavioral_benchmark,
                "find_codex_command",
                side_effect=AssertionError("profile discovery must not run"),
            ),
            patch.object(
                run_behavioral_benchmark,
                "repository_receipt",
                side_effect=AssertionError("repository receipt must not run"),
            ),
            redirect_stderr(stderr),
        ):
            self.assertEqual(run_behavioral_benchmark.main(), 2)
        self.assertIn("Fixture CSV validation failed", stderr.getvalue())
        self.assertIn("inputs/bad.csv row 3", stderr.getvalue())

    def test_behavioral_main_checks_path_budget_before_profile_or_model(self) -> None:
        stderr = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_behavioral_benchmark.py",
                    "--execute",
                    "--run-id",
                    "path-budget-order-test",
                    "--model",
                    "gpt-5.6-sol",
                    "--reasoning-effort",
                    "ultra",
                ],
            ),
            patch.object(
                run_behavioral_benchmark,
                "validate_workspace_path_budget",
                side_effect=EvaluationError("unsafe projected path"),
            ),
            patch.object(
                run_behavioral_benchmark,
                "find_codex_command",
                side_effect=AssertionError("profile discovery must not run"),
            ),
            redirect_stderr(stderr),
        ):
            self.assertEqual(run_behavioral_benchmark.main(), 2)
        self.assertIn("unsafe projected path", stderr.getvalue())

    def test_aggregate_discovers_logical_run_in_compact_storage_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            run_dir = root / "runs" / "001"
            run_dir.mkdir(parents=True)
            (run_dir / "workspace" / "artifacts").mkdir(parents=True)
            (run_dir / "task-output.json").write_text("{}\n", encoding="utf-8")
            (run_dir / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "stderr.txt").write_text("", encoding="utf-8")
            contract = {
                "assertions": [
                    {"assertion_id": "a", "text": "A", "weight": 100, "blocking": True}
                ]
            }
            grade = {
                "expectations": [
                    {"assertion_id": "a", "text": "A", "passed": True, "evidence": "artifact"}
                ],
                "summary": {"passed": 1, "failed": 0, "score": 100, "blocking_failures": 0},
                "integrity_events": [],
                "unauthorized_external_mutations": [],
                "notes": [],
            }
            task_metadata = {
                "run_id": "logical-with-skill-r01",
                "storage_id": "001",
                "case_id": "logical-case",
                "returncode": 0,
                "validation_errors": [],
                "timed_out": False,
                "termination_reason": "process-exit",
                "termination_method": "natural-exit",
                "timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
                "timeout_overrun_seconds": 0.0,
                "terminal_event_count": 1,
                "failed_terminal_event_count": 0,
                "execution_profile": {
                    "codex_invocation": CODEX_INVOCATION_MODE,
                    "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                },
            }
            for name, value in (
                ("case_contract.json", contract),
                ("grading.json", grade),
            ):
                (run_dir / name).write_text(json.dumps(value) + "\n", encoding="utf-8")
            task_metadata["task_evidence"] = task_evidence_receipt(run_dir)
            (run_dir / "run_metadata.json").write_text(
                json.dumps(task_metadata) + "\n", encoding="utf-8"
            )
            input_hash = grader_input_sha256(run_dir)
            attempt = {
                "schema_version": "1.0",
                "stage": "grader",
                "attempt_number": 1,
                "attempt_id": "grader:logical-with-skill-r01:attempt-01",
                "run_id": "logical-with-skill-r01",
                "storage_id": "001",
                "case_id": "logical-case",
                "started_at": "2026-08-15T00:00:00Z",
                "timeout_seconds": CANONICAL_GRADER_TIMEOUT_SECONDS,
                "grader_input_sha256": input_hash,
                "execution_profile": {
                    "codex_invocation": CODEX_INVOCATION_MODE,
                    "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                },
                "repository": {},
            }
            (run_dir / "grader_attempt.json").write_text(
                json.dumps(attempt) + "\n", encoding="utf-8"
            )
            (run_dir / "grader-transcript.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "grader-stderr.txt").write_text("", encoding="utf-8")
            grader_metadata = {
                "run_id": "logical-with-skill-r01",
                "storage_id": "001",
                "case_id": "logical-case",
                "attempt_number": 1,
                "attempt_id": attempt["attempt_id"],
                "attempt_started_at": attempt["started_at"],
                "grader_input_sha256": input_hash,
                "grade_sha256": file_sha256(run_dir / "grading.json"),
                "case_contract_sha256": file_sha256(run_dir / "case_contract.json"),
                "grader_attempt_sha256": file_sha256(run_dir / "grader_attempt.json"),
                "returncode": 0,
                "validation_errors": [],
                "timed_out": False,
                "termination_reason": "process-exit",
                "termination_method": "natural-exit",
                "timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                "timeout_seconds": CANONICAL_GRADER_TIMEOUT_SECONDS,
                "timeout_overrun_seconds": 0.0,
                "terminal_event_count": 1,
                "failed_terminal_event_count": 0,
                "execution_profile": {
                    "codex_invocation": CODEX_INVOCATION_MODE,
                    "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                },
                "repository": {},
            }
            (run_dir / "grader_metadata.json").write_text(
                json.dumps(grader_metadata) + "\n", encoding="utf-8"
            )

            records, missing = collect_runs(root)
            (run_dir / "grader_attempt.json").unlink()
            partial_records, partial_missing = collect_runs(root)

        self.assertEqual(missing, [])
        self.assertEqual(records[0]["run_id"], "logical-with-skill-r01")
        self.assertEqual(records[0]["storage_id"], "001")
        self.assertIsNone(partial_records[0]["grade"])
        self.assertTrue(any("grader_attempt.json" in item for item in partial_missing))

    def test_aggregate_main_propagates_comparison_collection_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            output = root / "benchmark.json"
            stdout = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "aggregate_benchmark.py",
                        str(root),
                        "--output",
                        str(output),
                    ],
                ),
                patch.object(aggregate_benchmark, "collect_runs", return_value=([], [])),
                patch.object(
                    aggregate_benchmark,
                    "collect_comparisons",
                    return_value=([], ["comparison evidence invalid"]),
                ),
                redirect_stdout(stdout),
            ):
                self.assertEqual(aggregate_benchmark.main(), 1)
            document = load_json(output)
            self.assertIn(
                "comparison evidence invalid",
                document["release_verdict"]["missing_evidence"],
            )

    def test_blind_pairing_uses_logical_metadata_from_compact_run_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for storage_id, configuration in (("001", "with_skill"), ("002", "without_skill")):
                run_dir = root / "runs" / storage_id
                run_dir.mkdir(parents=True)
                (run_dir / "run_metadata.json").write_text(
                    json.dumps(
                        {
                            "run_id": f"logical-{configuration}-r01",
                            "pair_id": "logical-pair-r01",
                            "case_id": "logical-case",
                            "case_kind": "primary",
                            "configuration": configuration,
                            "returncode": 0,
                            "validation_errors": [],
                            "timed_out": False,
                            "termination_reason": "process-exit",
                            "termination_method": "natural-exit",
                            "timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                            "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
                            "timeout_overrun_seconds": 0.0,
                            "terminal_event_count": 1,
                            "failed_terminal_event_count": 0,
                            "execution_profile": {
                                "codex_invocation": CODEX_INVOCATION_MODE,
                                "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            pairs = discover_pairs(root)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["pair_id"], "logical-pair-r01")
        self.assertEqual(set(pairs[0]["runs"]), {"with_skill", "without_skill"})

    def test_grader_discovers_compact_run_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for storage_id in ("001", "002"):
                (root / "runs" / storage_id).mkdir(parents=True)
            self.assertEqual([path.name for path in discover_runs(root)], ["001", "002"])

    def test_compact_comparison_ids_are_stable_when_pending_subset_changes(self) -> None:
        all_ids = [physical_comparison_id(index, 33) for index in range(1, 34)]
        self.assertEqual(all_ids[0], "001")
        self.assertEqual(all_ids[-1], "033")
        self.assertEqual(all_ids[17], physical_comparison_id(18, 33))

    def test_blind_bundle_copies_deep_artifacts_into_compact_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "runs" / "001"
            artifact = source / "workspace" / "artifacts" / ("nested-" + "x" * 80) / "report.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("evidence", encoding="utf-8")
            (source / "task-output.json").write_text("{}", encoding="utf-8")
            target = root / "comparisons" / "001" / "A"

            copy_blind_bundle(source, target)

            copied = target / "artifacts" / artifact.parent.name / "report.md"
            self.assertEqual(copied.read_text(encoding="utf-8"), "evidence")

    def test_blind_output_binding_rejects_changed_source_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            suite = Path(temp_name)
            target = suite / "comparisons" / "001"
            for label in ("A", "B"):
                (target / label / "artifacts").mkdir(parents=True)
                (target / label / "task-output.json").write_text("{}\n", encoding="utf-8")
                (target / label / "artifacts" / "report.md").write_text(
                    label, encoding="utf-8"
                )
            contract_path = target / "case_contract.json"
            result_path = target / "comparison.json"
            contract_path.write_text('{"assertions":[]}\n', encoding="utf-8")
            result_path.write_text(
                json.dumps(
                    {
                        "winner": "tie",
                        "rubric": "Evidence",
                        "output_quality": {"A": "Equal", "B": "Equal"},
                        "expectation_results": [],
                        "rationale": "Equal evidence",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            blind_map = label_map("pair-one", "report-skills-blind-v1")
            metadata = {
                "comparison_sha256": file_sha256(result_path),
                "case_contract_sha256": file_sha256(contract_path),
                "comparison_input_sha256": comparison_input_sha256(target),
                "source_runs": {
                    label: {
                        "run_id": label,
                        "configuration": blind_map[label],
                        "blind_bundle_sha256": blind_bundle_sha256(target / label),
                    }
                    for label in ("A", "B")
                },
            }
            self.assertEqual(
                validate_comparison_output_binding(
                    metadata, result_path, contract_path, target
                ),
                [],
            )
            metadata["source_runs"]["A"]["blind_bundle_sha256"] = "0" * 64
            errors = validate_comparison_output_binding(
                metadata, result_path, contract_path, target
            )
            self.assertTrue(any("source bundle A mismatch" in error for error in errors))
            metadata["source_runs"]["A"]["blind_bundle_sha256"] = blind_bundle_sha256(
                target / "A"
            )
            metadata.update(
                {
                    "pair_id": "pair-one",
                    "case_id": "case-one",
                    "storage_id": "001",
                    "blind_seed": "report-skills-blind-v1",
                    "label_map": blind_map,
                    "blind_winner": "tie",
                    "resolved_winner": "tie",
                    "returncode": 0,
                    "validation_errors": [],
                    "timed_out": False,
                    "termination_reason": "process-exit",
                    "termination_method": "natural-exit",
                    "timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                    "timeout_seconds": CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
                    "timeout_overrun_seconds": 0.0,
                    "terminal_event_count": 1,
                    "failed_terminal_event_count": 0,
                    "execution_profile": {
                        "codex_invocation": CODEX_INVOCATION_MODE,
                        "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
                    },
                    "repository": {},
                }
            )
            (target / "comparison_metadata.json").write_text(
                json.dumps(metadata) + "\n", encoding="utf-8"
            )
            (target / "comparator-transcript.jsonl").write_text("{}\n", encoding="utf-8")
            (target / "comparator-stderr.txt").write_text("", encoding="utf-8")
            collected, missing = collect_comparisons(suite)
            self.assertEqual(len(collected), 1)
            self.assertEqual(missing, [])
            metadata["timeout_seconds"] = 999
            (target / "comparison_metadata.json").write_text(
                json.dumps(metadata) + "\n", encoding="utf-8"
            )
            collected, missing = collect_comparisons(suite)
            self.assertEqual(collected, [])
            self.assertTrue(any("invalid evidence" in item for item in missing))

    def test_live_execution_requires_pinned_profile(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_trigger_evals.py"), "--execute"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires both --model and --reasoning-effort", result.stderr)

    def test_grade_recalculation_detects_mismatch(self) -> None:
        contract = {
            "assertions": [
                {"assertion_id": "a", "text": "A", "weight": 60, "blocking": True},
                {"assertion_id": "b", "text": "B", "weight": 40, "blocking": False},
            ]
        }
        grade = {
            "expectations": [
                {"assertion_id": "a", "text": "A", "passed": True, "evidence": "artifact.md"},
                {"assertion_id": "b", "text": "B", "passed": False, "evidence": "missing"},
            ],
            "summary": {"passed": 1, "failed": 1, "score": 100, "blocking_failures": 0},
        }
        errors = validate_grade(grade, contract)
        self.assertTrue(any("score mismatch" in error for error in errors))

    def test_blind_labeling_is_deterministic(self) -> None:
        first = label_map("case__r01", "seed")
        self.assertEqual(first, label_map("case__r01", "seed"))
        self.assertEqual(set(first.values()), {"with_skill", "without_skill"})

    def test_blind_comparison_semantics_accept_complete_result(self) -> None:
        contract = {
            "assertions": [
                {"assertion_id": "case.a01", "text": "First expectation"},
                {"assertion_id": "case.a02", "text": "Second expectation"},
            ]
        }
        comparison = {
            "winner": "A",
            "rubric": "Compare assertion evidence and task completeness.",
            "output_quality": {"A": "Complete and supported.", "B": "Partially supported."},
            "rationale": "A has stronger evidence.",
            "expectation_results": [
                {
                    "assertion_id": "case.a01",
                    "better": "A",
                    "evidence": "A/report.md contains the required field.",
                },
                {
                    "assertion_id": "case.a02",
                    "better": "tie",
                    "evidence": "Both outputs preserve the limitation.",
                },
            ],
        }
        self.assertEqual(validate_comparison(comparison, contract), [])

    def test_blind_comparison_semantics_reject_incomplete_or_duplicate_result(self) -> None:
        contract = {
            "assertions": [
                {"assertion_id": "case.a01", "text": "First expectation"},
                {"assertion_id": "case.a02", "text": "Second expectation"},
            ]
        }
        comparison = {
            "winner": "with_skill",
            "rationale": "   ",
            "expectation_results": [
                {
                    "assertion_id": "case.a01",
                    "text": "Changed expectation",
                    "better": "with_skill",
                    "evidence": "",
                },
                {
                    "assertion_id": "case.a01",
                    "better": "A",
                    "evidence": "duplicate",
                },
            ],
        }
        errors = validate_comparison(comparison, contract)
        self.assertTrue(any("winner" in error for error in errors))
        self.assertTrue(any("rationale" in error for error in errors))
        self.assertTrue(any("duplicate assertion IDs" in error for error in errors))
        self.assertTrue(any("coverage mismatch" in error for error in errors))
        self.assertTrue(any("does not match" in error for error in errors))
        self.assertTrue(any(".better" in error for error in errors))
        self.assertTrue(any(".evidence" in error for error in errors))

    def test_blind_bundle_excludes_execution_metadata_and_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "source"
            artifacts = source / "workspace" / "artifacts"
            skill = source / "workspace" / ".benchmark_skill" / "example"
            artifacts.mkdir(parents=True)
            skill.mkdir(parents=True)
            (source / "task-output.json").write_text("{}", encoding="utf-8")
            (source / "run_metadata.json").write_text('{"configuration":"with_skill"}', encoding="utf-8")
            (source / "transcript.jsonl").write_text("skill trace", encoding="utf-8")
            (artifacts / "report.md").write_text("output", encoding="utf-8")
            (skill / "SKILL.md").write_text("secret", encoding="utf-8")
            target = root / "blind"
            copy_blind_bundle(source, target)
            self.assertTrue((target / "task-output.json").is_file())
            self.assertTrue((target / "artifacts" / "report.md").is_file())
            self.assertFalse((target / "run_metadata.json").exists())
            self.assertFalse((target / "transcript.jsonl").exists())
            self.assertFalse((target / ".benchmark_skill").exists())

    def test_trigger_metrics_include_per_skill_breakdown(self) -> None:
        observations = [
            {"candidate_skill": "one", "should_trigger": True, "triggered": True},
            {"candidate_skill": "one", "should_trigger": False, "triggered": False},
            {"candidate_skill": "two", "should_trigger": True, "triggered": False},
            {"candidate_skill": "two", "should_trigger": False, "triggered": True},
        ]
        metrics = summarize(observations)
        self.assertEqual(metrics["suite_wide"]["precision"], 0.5)
        self.assertEqual(metrics["suite_wide"]["recall"], 0.5)
        self.assertEqual(set(metrics["per_skill"]), {"one", "two"})

    def test_trigger_task_prompt_requires_policy_neutral_body_load(self) -> None:
        query = "Review an existing publication at desktop and mobile widths."
        prompt = trigger_task_prompt(query)
        self.assertEqual(prompt.count(query), 1)
        self.assertIn("not an explicit invocation", prompt)
        self.assertIn("explicit-only or implicit-invocation policy", prompt)
        self.assertIn("Decide whether a skill applies before opening its body", prompt)
        self.assertIn("directory or filename is never enough", prompt)
        self.assertIn("agents/openai.yaml metadata and SKILL.md frontmatter", prompt)
        self.assertIn("lacks its required exact invocation token", prompt)
        self.assertIn("read its SKILL.md completely", prompt)
        self.assertIn("follow its instructions", prompt)
        self.assertIn("merely to fill the response schema", prompt)
        self.assertIn("Description-only classification does not count", prompt)
        self.assertIn("set it to null", prompt)
        candidates = {
            case["candidate_skill"]
            for case in load_json(REPO_ROOT / "evals" / "trigger-evals.json")["cases"]
        }
        self.assertFalse(any(candidate in prompt for candidate in candidates))
        self.assertNotIn("report-skills-triggered:", prompt)
        self.assertNotIn(".agents/skills", prompt)

    def test_trigger_task_prompt_preserves_explicit_only_invocation_boundary(self) -> None:
        cases = load_json(REPO_ROOT / "evals" / "trigger-evals.json")["cases"]
        explicit_cases = [
            case for case in cases if case["invocation_policy"] == "explicit_invocation"
        ]
        self.assertGreater(len(explicit_cases), 0)
        for case in explicit_cases:
            token = f"${case['candidate_skill']}"
            wrapped = trigger_task_prompt(case["query"])
            self.assertEqual(wrapped.count(token), case["query"].count(token))

    def test_trigger_output_schema_requires_actual_activation_semantics(self) -> None:
        schema = load_json(REPO_ROOT / "evals" / "schemas" / "trigger-output.schema.json")
        self.assertEqual(schema["title"], "Skill activation observation")
        selected_description = schema["properties"]["selected_skill"]["description"]
        self.assertIn("actually invoked", selected_description)
        self.assertIn("SKILL.md was read", selected_description)

    def test_trigger_prediction_applies_versioned_prompt_contract(self) -> None:
        query = "Build the approved report as a responsive editorial website."
        command = ["codex.cmd", "exec"]
        expected = object()
        with patch.object(run_trigger_evals, "run_codex", return_value=expected) as mocked:
            result = run_trigger_prediction(command, query, 600)
        self.assertIs(result, expected)
        mocked.assert_called_once_with(
            command, trigger_task_prompt(query), 600, environment=None
        )

    def test_body_proven_activation_requires_exact_candidate_and_marker(self) -> None:
        marker = "report-skills-triggered:abc123"
        candidate = "interactive-report-publisher"
        self.assertTrue(
            body_proven_activation(
                {"selected_skill": candidate, "rationale": marker}, candidate, marker
            )
        )
        self.assertTrue(
            body_proven_activation(
                {"selected_skill": f"report-skills:{candidate}", "rationale": marker},
                candidate,
                marker,
            )
        )
        self.assertFalse(
            body_proven_activation(
                {"selected_skill": candidate, "confidence": 1, "rationale": "Correct skill."},
                candidate,
                marker,
            )
        )
        self.assertFalse(
            body_proven_activation(
                {"selected_skill": candidate, "rationale": marker + " extra"}, candidate, marker
            )
        )
        self.assertFalse(
            body_proven_activation(
                {"selected_skill": "report-visual-system", "rationale": marker}, candidate, marker
            )
        )
        self.assertTrue(
            body_proven_activation(
                {"selected_skill": None, "rationale": "self-corrected"},
                candidate,
                marker,
                f"command output exposed {marker} before the final response",
            )
        )
        self.assertTrue(
            body_proven_activation(
                {"selected_skill": "report-visual-system", "rationale": "other"},
                candidate,
                marker,
                f"completed body read: {marker}",
            )
        )
        self.assertFalse(
            body_proven_activation(
                {"selected_skill": None, "rationale": "self-corrected"},
                candidate,
                marker,
                "transcript without the unique body marker",
            )
        )

    def test_trigger_sentinel_marker_is_body_only(self) -> None:
        case = {
            "candidate_skill": "interactive-report-publisher",
            "observation_id": "sentinel-body-proof__r01",
        }
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name)
            marker = install_sentinel_skill(workspace, case)
            target = workspace / ".agents" / "skills" / case["candidate_skill"]
            skill_text = (target / "SKILL.md").read_text(encoding="utf-8")
            frontmatter, body = skill_text.split("---", 2)[1:]
            self.assertNotIn(marker, frontmatter)
            self.assertIn(marker, body)
            self.assertNotIn(
                marker,
                (target / "agents" / "openai.yaml").read_text(encoding="utf-8"),
            )

    def test_context_mismatch_is_rejected(self) -> None:
        profile = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "ultra",
            "codex_invocation": CODEX_INVOCATION_MODE,
            "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            "codex_cli_version": "codex-cli 0.147.0",
            "codex_command_sha256": "a" * 64,
            "codex_implementation_sha256": "f" * 64,
            "codex_managed_environment_sha256": "e" * 64,
            "selected_model_sha256": "b" * 64,
            "python_version": "3.12.0",
            "platform": "test",
        }
        repository = {"root": "repo", "commit": "c" * 40, "tree": "d" * 40, "dirty": False}
        mismatched = dict(profile, reasoning_effort="high")
        with self.assertRaisesRegex(EvaluationError, "does not match"):
            require_matching_context(profile, repository, mismatched, repository, "test")

    def test_invariants_reject_mixed_stage_and_trigger_metrics(self) -> None:
        profile = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "ultra",
            "codex_invocation": CODEX_INVOCATION_MODE,
            "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            "codex_cli_version": "codex-cli 0.147.0",
            "codex_command_sha256": "a" * 64,
            "codex_implementation_sha256": "f" * 64,
            "codex_managed_environment_sha256": "e" * 64,
            "selected_model_sha256": "b" * 64,
            "python_version": "3.12.0",
            "platform": "test",
        }
        repository = {"root": "repo", "commit": "c" * 40, "tree": "d" * 40, "dirty": False}
        skill_hashes = {"one": "e" * 64}
        row = {
            "run_id": "case__with_skill__r01",
            "pair_id": "case__r01",
            "case_id": "case",
            "case_kind": "primary",
            "skill": "one",
            "configuration": "with_skill",
            "repetition": 1,
        }
        baseline_row = {
            **row,
            "run_id": "case__without_skill__r01",
            "configuration": "without_skill",
        }
        contract_hash = canonical_json_sha256(
            {
                "assertions": [
                    {
                        "assertion_id": "case.a01",
                        "text": "Complete",
                        "weight": 100,
                        "blocking": True,
                    }
                ]
            }
        )
        plan = {
            "execution_profile": profile,
            "repository": repository,
            "skill_hashes": skill_hashes,
            "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
            "case_contract_hashes": {
                row["run_id"]: contract_hash,
                baseline_row["run_id"]: contract_hash,
            },
            "runs": [row, baseline_row],
        }
        clean_task_receipt = {
            "timed_out": False,
            "termination_reason": "process-exit",
            "termination_method": "natural-exit",
            "timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
            "timeout_overrun_seconds": 0.0,
            "terminal_event_count": 1,
            "failed_terminal_event_count": 0,
        }
        grader_input_hash = "9" * 64
        grader = {
            "execution_profile": profile,
            "repository": repository,
            "run_id": row["run_id"],
            "storage_id": "001",
            "case_id": row["case_id"],
            "attempt_number": 1,
            "attempt_id": f"grader:{row['run_id']}:attempt-01",
            "attempt_started_at": "2026-08-14T00:00:02Z",
            "grader_input_sha256": grader_input_hash,
            "returncode": 0,
            "validation_errors": [],
            "timeout_seconds": CANONICAL_GRADER_TIMEOUT_SECONDS,
            **clean_task_receipt,
        }
        grade_contract = {
            "assertions": [
                {"assertion_id": "case.a01", "text": "Complete", "weight": 100, "blocking": True}
            ]
        }
        grade_document = {
            "expectations": [
                {
                    "assertion_id": "case.a01",
                    "text": "Complete",
                    "passed": True,
                    "evidence": "artifact.md",
                }
            ],
            "summary": {"passed": 1, "failed": 0, "score": 100, "blocking_failures": 0},
            "integrity_events": [],
            "unauthorized_external_mutations": [],
            "notes": [],
        }
        grader_attempt = {
            "schema_version": "1.0",
            "stage": "grader",
            "attempt_number": 1,
            "attempt_id": grader["attempt_id"],
            "run_id": row["run_id"],
            "storage_id": "001",
            "case_id": row["case_id"],
            "started_at": grader["attempt_started_at"],
            "timeout_seconds": CANONICAL_GRADER_TIMEOUT_SECONDS,
            "grader_input_sha256": grader_input_hash,
            "execution_profile": profile,
            "repository": repository,
        }
        task_method = {
            "returncode": 0,
            "validation_errors": [],
            "started_at": "2026-08-14T00:00:00Z",
            "completed_at": "2026-08-14T00:00:01Z",
            "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
            **clean_task_receipt,
            "skill_loading": "explicit_workspace_copy",
            "codex_isolation": {
                "ephemeral": True,
                "ignore_user_config": True,
                "ignore_user_config_scope": "config.toml_only",
                "ignore_rules": True,
                "sandbox": "workspace-write",
                "skill_body_read_guard": "named-skill-path-command-events-v1",
            },
            "skill_loader_diagnostics": {
                "ignore_user_config_scope": "config.toml_only",
                "metadata_warning_count": 0,
                "failed_skill_load_count": 0,
            },
        }
        records = [
            {
                **row,
                **task_method,
                "storage_id": "001",
                "execution_profile": profile,
                "repository": repository,
                "grader_metadata": grader,
                "grade": grade_document,
                "case_contract": grade_contract,
                "grader_attempt": grader_attempt,
                "task_evidence": {
                    "blind_bundle_sha256": "8" * 64,
                    "case_contract_sha256": "7" * 64,
                },
            }
        ]
        baseline_grader = copy.deepcopy(grader)
        baseline_grader.update(
            {
                "run_id": baseline_row["run_id"],
                "storage_id": "002",
                "attempt_id": f"grader:{baseline_row['run_id']}:attempt-01",
            }
        )
        baseline_attempt = copy.deepcopy(grader_attempt)
        baseline_attempt.update(
            {
                "attempt_id": baseline_grader["attempt_id"],
                "run_id": baseline_row["run_id"],
                "storage_id": "002",
            }
        )
        baseline_task_method = copy.deepcopy(task_method)
        baseline_task_method["skill_loading"] = "none"
        records.append(
            {
                **baseline_row,
                **baseline_task_method,
                "storage_id": "002",
                "execution_profile": profile,
                "repository": repository,
                "grader_metadata": baseline_grader,
                "grade": grade_document,
                "case_contract": grade_contract,
                "grader_attempt": baseline_attempt,
                "task_evidence": {
                    "blind_bundle_sha256": "6" * 64,
                    "case_contract_sha256": "7" * 64,
                },
            }
        )
        blind_seed = "report-skills-blind-v1"
        blind_map = label_map(row["pair_id"], blind_seed)
        source_by_configuration = {
            "with_skill": (row["run_id"], "8" * 64),
            "without_skill": (baseline_row["run_id"], "6" * 64),
        }
        source_runs = {
            label: {
                "run_id": source_by_configuration[configuration][0],
                "configuration": configuration,
                "blind_bundle_sha256": source_by_configuration[configuration][1],
            }
            for label, configuration in blind_map.items()
        }
        comparison_output = {
            "winner": "A",
            "rubric": "Compare evidence.",
            "output_quality": {"A": "Complete.", "B": "Incomplete."},
            "expectation_results": [
                {"assertion_id": "case.a01", "better": "A", "evidence": "A has artifact."}
            ],
            "rationale": "A is stronger.",
        }
        comparison = {
            "pair_id": "case__r01",
            "case_id": "case",
            "comparison_storage_id": "001",
            "storage_id": "001",
            "blind_seed": blind_seed,
            "label_map": blind_map,
            "source_runs": source_runs,
            "blind_winner": "A",
            "resolved_winner": blind_map["A"],
            "comparison_output": comparison_output,
            "case_contract": grade_contract,
            "case_contract_sha256": "7" * 64,
            "execution_profile": profile,
            "repository": repository,
            "returncode": 0,
            "validation_errors": [],
            "timeout_seconds": CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
            **clean_task_receipt,
        }
        trigger_suite = {
            "protocol": {"repetitions_per_case": 1},
            "cases": [{"case_id": "t", "candidate_skill": "one", "should_trigger": True}],
        }
        observation = {
            "observation_id": "t__r01",
            "case_id": "t",
            "candidate_skill": "one",
            "repetition": 1,
            "should_trigger": True,
            "triggered": True,
            "correct": True,
            "returncode": 0,
            "validation_errors": [],
            "timeout_seconds": CANONICAL_TRIGGER_TIMEOUT_SECONDS,
            **clean_task_receipt,
            "execution_profile": profile,
            "repository": repository,
        }
        triggers = {
            "execution_profile": profile,
            "repository": repository,
            "skill_hashes": skill_hashes,
            "observations": [observation],
            "metrics": summarize([observation]),
            "failed_observations": [],
            "timeout_seconds": CANONICAL_TRIGGER_TIMEOUT_SECONDS,
        }
        self.assertEqual(
            validate_evidence_invariants(plan, records, [comparison], triggers, trigger_suite), []
        )
        mixed_records = copy.deepcopy(records)
        mixed_records[0]["grader_metadata"]["repository"]["commit"] = "f" * 40
        issues = validate_evidence_invariants(
            plan, mixed_records, [comparison], triggers, trigger_suite
        )
        self.assertTrue(any("grader" in issue and "mismatch" in issue for issue in issues))
        bad_triggers = copy.deepcopy(triggers)
        bad_triggers["metrics"]["suite_wide"]["recall"] = 0.0
        issues = validate_evidence_invariants(
            plan, records, [comparison], bad_triggers, trigger_suite
        )
        self.assertIn("trigger-results:stored metrics do not match observations", issues)

        bad_method_records = copy.deepcopy(records)
        bad_method_records[0]["codex_isolation"]["skill_body_read_guard"] = "legacy-guard"
        issues = validate_evidence_invariants(
            plan, bad_method_records, [comparison], triggers, trigger_suite
        )
        self.assertTrue(any("task isolation receipt" in issue for issue in issues))

        bad_seed_comparison = copy.deepcopy(comparison)
        bad_seed_comparison["blind_seed"] = "retry-seed"
        bad_seed_comparison["label_map"] = label_map(row["pair_id"], "retry-seed")
        issues = validate_evidence_invariants(
            plan, records, [bad_seed_comparison], triggers, trigger_suite
        )
        self.assertTrue(any("canonical blind seed" in issue for issue in issues))

    def test_release_requires_every_hard_gate(self) -> None:
        skills = [case["skill"] for case in self.suite["primary_cases"]]

        def grade(score: int = 100) -> dict:
            return {
                "summary": {"score": score, "blocking_failures": 0},
                "integrity_events": [],
                "unauthorized_external_mutations": [],
            }

        records = []
        comparisons = []
        for index, skill in enumerate(skills):
            pair_id = f"pair-{index}"
            records.extend(
                [
                    {"skill": skill, "configuration": "with_skill", "case_kind": "primary", "pair_id": pair_id, "grade": grade()},
                    {"skill": skill, "configuration": "without_skill", "case_kind": "primary", "pair_id": pair_id, "grade": grade(50)},
                ]
            )
            comparisons.append({"pair_id": pair_id, "resolved_winner": "with_skill" if index < 8 else "without_skill"})
        for index in range(5):
            records.append({"skill": "evidence-first-report", "configuration": "with_skill", "case_kind": "adversarial", "pair_id": f"adv-{index}", "grade": grade()})
        trigger = {
            "metrics": {
                "suite_wide": {"precision": 1.0, "recall": 1.0},
                "per_skill": {skill: {"precision": 1.0, "recall": 1.0} for skill in skills},
            }
        }
        release = evaluate_release(records, comparisons, trigger, self.thresholds, [])
        self.assertEqual(release["decision"], "release")
        trigger["metrics"]["per_skill"][skills[0]]["recall"] = 0.0
        hold = evaluate_release(records, comparisons, trigger, self.thresholds, [])
        self.assertEqual(hold["decision"], "hold")


if __name__ == "__main__":
    unittest.main()
