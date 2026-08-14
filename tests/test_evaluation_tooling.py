from __future__ import annotations

import json
import copy
import hashlib
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aggregate_benchmark import collect_runs, evaluate_release, validate_evidence_invariants  # noqa: E402
from evaluation_common import (  # noqa: E402
    EvaluationError,
    build_run_plan,
    codex_execution_profile,
    codex_base_command,
    load_json,
    normalize_suite,
    require_matching_context,
    validate_output_root,
)
from grade_behavioral_benchmark import discover_runs, validate_grade  # noqa: E402
from run_blind_comparisons import (  # noqa: E402
    copy_blind_bundle,
    discover_pairs,
    label_map,
    physical_comparison_id,
    validate_comparison,
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
    canonical_contract_hashes,
    canonical_plan_rows,
    validate_release_eval_plan,
)
from validate_eval_suite import validate_model_output_schema  # noqa: E402
import evaluation_common  # noqa: E402
import run_behavioral_benchmark  # noqa: E402
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
            "configurations": ["with_skill", "without_skill"],
            "baseline_contamination_risk": [],
            "contract_hashes": {
                "benchmark_suite_sha256": hashes["benchmark_suite_sha256"],
                "thresholds_sha256": hashes["thresholds_sha256"],
                "fixture_sha256": hashes["fixture_sha256"],
            },
            "runs": canonical_plan_rows(),
        }
        triggers = {
            "suite": str((REPO_ROOT / "evals" / "trigger-evals.json").resolve()),
            "contract_hashes": {
                "trigger_suite_sha256": hashes["trigger_suite_sha256"]
            },
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
            command = Path(temp_name) / "codex.cmd"
            command.write_text("@echo off\n", encoding="utf-8")
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
        self.assertRegex(profile["selected_model_sha256"], r"^[0-9a-f]{64}$")

    def test_live_profile_rejects_unsupported_effort(self) -> None:
        model_entry = {
            "slug": "gpt-5.6-sol",
            "default_reasoning_level": "low",
            "supported_reasoning_levels": [{"effort": "low"}],
        }
        with tempfile.TemporaryDirectory() as temp_name:
            command = Path(temp_name) / "codex.cmd"
            command.write_text("@echo off\n", encoding="utf-8")
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
        self.assertEqual(json.loads(stdout.getvalue())["run_count"], 96)

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
            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "run_id": "logical-with-skill-r01",
                        "storage_id": "001",
                        "returncode": 0,
                        "validation_errors": [],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "grading.json").write_text("{}", encoding="utf-8")
            (run_dir / "grader_metadata.json").write_text(
                json.dumps({"returncode": 0, "validation_errors": []}), encoding="utf-8"
            )

            records, missing = collect_runs(root)

        self.assertEqual(missing, [])
        self.assertEqual(records[0]["run_id"], "logical-with-skill-r01")
        self.assertEqual(records[0]["storage_id"], "001")

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
            "rationale": "A has stronger evidence.",
            "expectation_results": [
                {
                    "assertion_id": "case.a01",
                    "better": "A",
                    "evidence": "A/report.md contains the required field.",
                },
                {
                    "assertion_id": "case.a02",
                    "text": "Second expectation",
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
        mocked.assert_called_once_with(command, trigger_task_prompt(query), 600)

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
            "codex_cli_version": "codex-cli 0.147.0",
            "codex_command_sha256": "a" * 64,
            "codex_implementation_sha256": "f" * 64,
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
            "codex_cli_version": "codex-cli 0.147.0",
            "codex_command_sha256": "a" * 64,
            "codex_implementation_sha256": "f" * 64,
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
        plan = {
            "execution_profile": profile,
            "repository": repository,
            "skill_hashes": skill_hashes,
            "runs": [row],
        }
        grader = {"execution_profile": profile, "repository": repository, "returncode": 0, "validation_errors": []}
        task_method = {
            "started_at": "2026-08-14T00:00:00Z",
            "completed_at": "2026-08-14T00:00:01Z",
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
                "execution_profile": profile,
                "repository": repository,
                "grader_metadata": grader,
            }
        ]
        comparison = {"pair_id": "case__r01", "execution_profile": profile, "repository": repository, "returncode": 0}
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
