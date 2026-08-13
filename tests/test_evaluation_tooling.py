from __future__ import annotations

import json
import copy
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aggregate_benchmark import evaluate_release, validate_evidence_invariants  # noqa: E402
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
from grade_behavioral_benchmark import validate_grade  # noqa: E402
from run_blind_comparisons import copy_blind_bundle, label_map, validate_comparison  # noqa: E402
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
        records = [{**row, "execution_profile": profile, "repository": repository, "grader_metadata": grader}]
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
