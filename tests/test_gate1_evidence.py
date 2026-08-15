from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_trigger_evals  # noqa: E402
import run_gate1_evidence  # noqa: E402
from grade_behavioral_benchmark import validate_grade  # noqa: E402
from evaluation_common import (  # noqa: E402
    CODEX_TIMEOUT_ENFORCEMENT_MODE,
    CommandResult,
    EvaluationError,
    file_sha256,
    load_json,
    normalize_suite,
)
from gate1_contract import (  # noqa: E402
    DEFAULT_GATE1_PLAN,
    GATE1_BEHAVIORAL_CASE_IDS,
    GATE1_MASTER_PLAN_NAME,
    GATE1_ORCHESTRATION,
    GATE1_STAGES_DIRECTORY,
    GATE1_SUMMARY_NAME,
    GATE1_TRIGGER_STAGE_DIRECTORY,
    GATE1_TRIGGER_OBSERVATIONS,
    gate1_behavioral_plan_rows,
    gate1_behavioral_stage_directory,
    gate1_master_call_plan,
    gate1_master_plan_document,
    gate1_summary_document,
    gate1_trigger_plan_rows,
    load_gate1_plan,
    validate_gate1_plan,
)
from validate_gate1_evidence import (  # noqa: E402
    _identity_errors,
    gate1_grade_validation_errors,
    validate_gate1_master_and_summary,
    validate_gate1_trigger_evidence,
)


class Gate1EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = load_gate1_plan()
        cls.benchmark_suite = normalize_suite(
            load_json(REPO_ROOT / "evals" / "benchmark-suite.json")
        )
        cls.trigger_suite = load_json(REPO_ROOT / "evals" / "trigger-evals.json")

    def test_tracked_gate1_plan_is_exact_and_complete(self) -> None:
        self.assertEqual(
            validate_gate1_plan(
                self.plan, self.benchmark_suite, self.trigger_suite
            ),
            [],
        )
        behavioral = gate1_behavioral_plan_rows(self.plan, self.benchmark_suite)
        triggers = gate1_trigger_plan_rows(self.plan, self.trigger_suite)
        self.assertEqual(
            [row["case_id"] for row in behavioral],
            list(GATE1_BEHAVIORAL_CASE_IDS),
        )
        self.assertEqual(
            [(row["case_id"], row["repetition"]) for row in triggers],
            list(GATE1_TRIGGER_OBSERVATIONS),
        )
        self.assertEqual(len(behavioral), 5)
        self.assertEqual(len(triggers), 15)
        self.assertEqual(len({row["candidate_skill"] for row in triggers}), 11)
        self.assertEqual(sum(row["should_trigger"] is True for row in triggers), 12)
        self.assertEqual(sum(row["should_trigger"] is False for row in triggers), 3)
        self.assertEqual(self.plan["blind_comparisons"], 0)
        self.assertIs(self.plan["gate2_aggregate"], False)
        self.assertEqual(self.plan["orchestration"], GATE1_ORCHESTRATION)

    def test_gate1_plan_rejects_scope_model_and_policy_mutations(self) -> None:
        mutations = []
        wrong_model = copy.deepcopy(self.plan)
        wrong_model["model"] = "another-model"
        mutations.append(wrong_model)
        missing_task = copy.deepcopy(self.plan)
        missing_task["behavioral"]["case_ids"].pop()
        mutations.append(missing_task)
        missing_trigger = copy.deepcopy(self.plan)
        missing_trigger["trigger"]["observations"].pop()
        mutations.append(missing_trigger)
        no_fail_fast = copy.deepcopy(self.plan)
        no_fail_fast["trigger"]["fail_fast_on_incorrect"] = False
        mutations.append(no_fail_fast)
        retry = copy.deepcopy(self.plan)
        retry["orchestration"]["retry_policy"] = "retry-once"
        mutations.append(retry)
        blind = copy.deepcopy(self.plan)
        blind["blind_comparisons"] = 1
        mutations.append(blind)
        aggregate = copy.deepcopy(self.plan)
        aggregate["gate2_aggregate"] = True
        mutations.append(aggregate)
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                self.assertTrue(
                    validate_gate1_plan(
                        mutated, self.benchmark_suite, self.trigger_suite
                    )
                )

    def test_gate1_master_call_plan_is_exact_25_and_interleaved(self) -> None:
        calls = gate1_master_call_plan(
            self.plan, self.benchmark_suite, self.trigger_suite
        )
        self.assertEqual(len(calls), 25)
        self.assertEqual([call["ordinal"] for call in calls], list(range(1, 26)))
        self.assertEqual(len({call["call_id"] for call in calls}), 25)
        self.assertTrue(all(call["stage"] == "trigger" for call in calls[:15]))
        self.assertEqual(
            [call["stage"] for call in calls[15:]],
            ["behavioral_task", "grader"] * 5,
        )
        for index in range(5):
            task = calls[15 + index * 2]
            grader = calls[16 + index * 2]
            self.assertEqual(task["case_id"], GATE1_BEHAVIORAL_CASE_IDS[index])
            self.assertEqual(task["run_id"], grader["run_id"])
            self.assertEqual(task["evidence_root"], grader["evidence_root"])

    def test_gate1_orchestrator_stops_after_first_nonperfect_grade(self) -> None:
        profile = {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"}
        repository = {"commit": "a" * 40, "tree": "b" * 40, "dirty": False}
        commands: list[list[str]] = []
        completed: list[str] = []
        with tempfile.TemporaryDirectory() as temp_name:
            gate1_root = Path(temp_name) / "gate1"
            with (
                patch.object(
                    run_gate1_evidence,
                    "_run_stage_command",
                    side_effect=lambda command, label: commands.append(command),
                ),
                patch.object(run_gate1_evidence, "require_unchanged_repository"),
                patch.object(
                    run_gate1_evidence,
                    "validate_gate1_trigger_evidence",
                    return_value=[],
                ),
                patch.object(
                    run_gate1_evidence,
                    "validate_gate1_behavioral_case_evidence",
                    return_value=["semantic grade is not perfect"],
                ),
            ):
                with self.assertRaises(EvaluationError):
                    run_gate1_evidence.run_gate1_model_sequence(
                        self.plan,
                        self.benchmark_suite,
                        self.trigger_suite,
                        gate1_root,
                        "codex",
                        profile,
                        repository,
                        completed,
                    )
        self.assertEqual(len(commands), 3)
        self.assertTrue(commands[0][1].endswith("run_trigger_evals.py"))
        self.assertTrue(commands[1][1].endswith("run_behavioral_benchmark.py"))
        self.assertIn(GATE1_BEHAVIORAL_CASE_IDS[0], commands[1])
        self.assertTrue(commands[2][1].endswith("grade_behavioral_benchmark.py"))
        self.assertNotIn(GATE1_BEHAVIORAL_CASE_IDS[1], " ".join(commands[0] + commands[1] + commands[2]))
        self.assertEqual(len(completed), 16)
        self.assertFalse((gate1_root / GATE1_SUMMARY_NAME).exists())

    def test_gate1_orchestrator_has_no_blind_or_aggregate_stage(self) -> None:
        commands: list[list[str]] = []
        completed: list[str] = []
        with tempfile.TemporaryDirectory() as temp_name:
            with (
                patch.object(
                    run_gate1_evidence,
                    "_run_stage_command",
                    side_effect=lambda command, label: commands.append(command),
                ),
                patch.object(run_gate1_evidence, "require_unchanged_repository"),
                patch.object(
                    run_gate1_evidence,
                    "validate_gate1_trigger_evidence",
                    return_value=[],
                ),
                patch.object(
                    run_gate1_evidence,
                    "validate_gate1_behavioral_case_evidence",
                    return_value=[],
                ),
            ):
                run_gate1_evidence.run_gate1_model_sequence(
                    self.plan,
                    self.benchmark_suite,
                    self.trigger_suite,
                    Path(temp_name) / "gate1",
                    "codex",
                    {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"},
                    {"commit": "a" * 40, "tree": "b" * 40, "dirty": False},
                    completed,
                )
        script_names = [Path(command[1]).name for command in commands]
        self.assertEqual(
            script_names,
            ["run_trigger_evals.py"]
            + [
                name
                for _ in range(5)
                for name in (
                    "run_behavioral_benchmark.py",
                    "grade_behavioral_benchmark.py",
                )
            ],
        )
        self.assertFalse(
            any("blind" in name or "aggregate" in name for name in script_names)
        )
        self.assertEqual(
            completed,
            [
                call["call_id"]
                for call in gate1_master_call_plan(
                    self.plan, self.benchmark_suite, self.trigger_suite
                )
            ],
        )

    def test_gate1_master_plan_exists_before_model_sequence(self) -> None:
        profile = {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"}
        repository = {
            "root": str(REPO_ROOT),
            "commit": "a" * 40,
            "tree": "b" * 40,
            "dirty": False,
        }
        with tempfile.TemporaryDirectory() as temp_name:
            output_root = Path(temp_name) / "runs"
            gate1_root = output_root / "gate1-test"

            def stop_at_first_call(*args: object, **kwargs: object) -> None:
                del args, kwargs
                self.assertTrue((gate1_root / GATE1_MASTER_PLAN_NAME).is_file())
                self.assertFalse((gate1_root / GATE1_SUMMARY_NAME).exists())
                raise EvaluationError("synthetic pre-call stop")

            argv = [
                "run_gate1_evidence.py",
                "--execute",
                "--output-root",
                str(output_root),
                "--run-id",
                "gate1-test",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    run_gate1_evidence, "find_codex_command", return_value="codex"
                ),
                patch.object(
                    run_gate1_evidence,
                    "codex_execution_profile",
                    return_value=profile,
                ),
                patch.object(
                    run_gate1_evidence,
                    "repository_receipt",
                    return_value=repository,
                ),
                patch.object(
                    run_gate1_evidence,
                    "run_gate1_model_sequence",
                    side_effect=stop_at_first_call,
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_gate1_evidence.main(), 2)
            self.assertTrue((gate1_root / GATE1_MASTER_PLAN_NAME).is_file())
            self.assertTrue((gate1_root / "gate1-failure.json").is_file())
            self.assertFalse((gate1_root / GATE1_SUMMARY_NAME).exists())

    def test_gate1_summary_hashes_all_six_stage_roots(self) -> None:
        profile = {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"}
        repository = {
            "root": str(REPO_ROOT),
            "commit": "a" * 40,
            "tree": "b" * 40,
            "dirty": False,
        }
        with tempfile.TemporaryDirectory() as temp_name:
            gate1_root = Path(temp_name) / "gate1"
            stages = gate1_root / GATE1_STAGES_DIRECTORY
            trigger_root = stages / GATE1_TRIGGER_STAGE_DIRECTORY
            trigger_root.mkdir(parents=True)
            (trigger_root / "trigger-results.json").write_text(
                "{}\n", encoding="utf-8"
            )
            for index in range(1, 6):
                (stages / gate1_behavioral_stage_directory(index)).mkdir()
            master = gate1_master_plan_document(
                self.plan,
                self.benchmark_suite,
                self.trigger_suite,
                profile,
                repository,
                "2026-08-15T00:00:00Z",
            )
            master_path = gate1_root / GATE1_MASTER_PLAN_NAME
            master_path.write_text(
                json.dumps(master, indent=2) + "\n", encoding="utf-8"
            )
            summary = gate1_summary_document(
                self.plan,
                self.benchmark_suite,
                self.trigger_suite,
                gate1_root,
                file_sha256(master_path),
                profile,
                repository,
                "2026-08-15T00:01:00Z",
            )
            (gate1_root / GATE1_SUMMARY_NAME).write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )
            baseline, *_ = validate_gate1_master_and_summary(
                self.plan, gate1_root, repository
            )
            self.assertFalse(
                any("document or evidence hashes do not match" in issue for issue in baseline)
            )
            (trigger_root / "trigger-results.json").write_text(
                '{"tampered": true}\n', encoding="utf-8"
            )
            mutated, *_ = validate_gate1_master_and_summary(
                self.plan, gate1_root, repository
            )
            self.assertTrue(
                any("document or evidence hashes do not match" in issue for issue in mutated)
            )

    def test_trigger_observation_plan_dry_run_is_exact_mixed_repetition(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "run_trigger_evals.py",
            "--dry-run",
            "--observation-plan",
            str(DEFAULT_GATE1_PLAN),
            "--fail-fast-on-incorrect",
            "--show-plan",
        ]
        with patch.object(sys, "argv", argv), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(run_trigger_evals.main(), 0)
        self.assertEqual(stderr.getvalue(), "")
        document = json.loads(stdout.getvalue())
        self.assertEqual(document["observation_count"], 15)
        self.assertIsNone(document["repetitions"])
        self.assertIs(document["fail_fast_on_incorrect"], True)
        self.assertEqual(
            document["planned_observation_ids"],
            [row["observation_id"] for row in gate1_trigger_plan_rows(self.plan, self.trigger_suite)],
        )
        self.assertEqual(
            sum(
                row["observation_id"]
                == "trigger-sites-explicit-positive__r02"
                for row in document["observations"]
            ),
            1,
        )

    def test_trigger_observation_plan_refuses_ambiguous_or_unpinned_cli(self) -> None:
        cases = (
            [
                "run_trigger_evals.py",
                "--dry-run",
                "--observation-plan",
                str(DEFAULT_GATE1_PLAN),
                "--fail-fast-on-incorrect",
                "--repetitions",
                "1",
            ],
            [
                "run_trigger_evals.py",
                "--execute",
                "--observation-plan",
                str(DEFAULT_GATE1_PLAN),
                "--fail-fast-on-incorrect",
                "--model",
                "gpt-5.6-sol",
                "--reasoning-effort",
                "high",
            ],
        )
        for argv in cases:
            with self.subTest(argv=argv), patch.object(sys, "argv", argv), redirect_stdout(
                io.StringIO()
            ), redirect_stderr(io.StringIO()):
                self.assertEqual(run_trigger_evals.main(), 2)

    def test_gate1_trigger_execution_freezes_and_binds_plan_before_calls(self) -> None:
        profile = {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"}
        repository = {
            "root": str(REPO_ROOT),
            "commit": "a" * 40,
            "tree": "b" * 40,
            "dirty": False,
        }
        by_query = {
            str(case["query"]): case for case in self.trigger_suite["cases"]
        }
        with tempfile.TemporaryDirectory() as temp_name:
            output_root = Path(temp_name) / "runs"
            run_id = "gate1-trigger-test"
            target = output_root / run_id
            seen_plan_hashes: list[str] = []

            def fake_prediction(
                command: list[str],
                query: str,
                timeout: int,
                environment: dict[str, str] | None = None,
            ) -> CommandResult:
                del timeout, environment
                trigger_plan_path = target / "trigger-plan.json"
                self.assertTrue(trigger_plan_path.is_file())
                seen_plan_hashes.append(file_sha256(trigger_plan_path))
                cwd = Path(command[command.index("--cd") + 1])
                output_path = Path(
                    command[command.index("--output-last-message") + 1]
                )
                case = by_query[query]
                skill_path = (
                    cwd
                    / ".agents"
                    / "skills"
                    / str(case["candidate_skill"])
                    / "SKILL.md"
                )
                marker = skill_path.read_text(encoding="utf-8").split(
                    "Marker: `", 1
                )[1].split("`", 1)[0]
                prediction = {
                    "selected_skill": (
                        case["candidate_skill"] if case["should_trigger"] else None
                    ),
                    "confidence": 1,
                    "rationale": marker if case["should_trigger"] else "not activated",
                }
                output_path.write_text(
                    json.dumps(prediction) + "\n", encoding="utf-8"
                )
                return CommandResult(
                    returncode=0,
                    wall_clock_seconds=0.01,
                    stdout=json.dumps({"type": "turn.completed"}) + "\n",
                    stderr="",
                    timeout_seconds=600,
                    timeout_enforcement=CODEX_TIMEOUT_ENFORCEMENT_MODE,
                    terminal_event_count=1,
                    failed_terminal_event_count=0,
                )

            argv = [
                "run_trigger_evals.py",
                "--execute",
                "--observation-plan",
                str(DEFAULT_GATE1_PLAN),
                "--fail-fast-on-incorrect",
                "--output-root",
                str(output_root),
                "--run-id",
                run_id,
                "--model",
                "gpt-5.6-sol",
                "--reasoning-effort",
                "ultra",
            ]
            stderr = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    run_trigger_evals, "find_codex_command", return_value="codex"
                ),
                patch.object(
                    run_trigger_evals, "codex_runtime_command", return_value="codex"
                ),
                patch.object(
                    run_trigger_evals,
                    "codex_execution_profile",
                    return_value=profile,
                ),
                patch.object(
                    run_trigger_evals,
                    "repository_receipt",
                    return_value=repository,
                ),
                patch.object(run_trigger_evals, "require_unchanged_repository"),
                patch.object(
                    run_trigger_evals,
                    "baseline_contamination_paths",
                    return_value=[],
                ),
                patch.object(
                    run_trigger_evals, "task_runtime_environment", return_value={}
                ),
                patch.object(
                    run_trigger_evals,
                    "run_trigger_prediction",
                    side_effect=fake_prediction,
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(stderr),
            ):
                self.assertEqual(run_trigger_evals.main(), 0, stderr.getvalue())

            results_path = target / "trigger-results.json"
            results = load_json(results_path)
            self.assertEqual(len(seen_plan_hashes), 15)
            self.assertEqual(len(set(seen_plan_hashes)), 1)
            self.assertEqual(
                results["trigger_plan_sha256"], seen_plan_hashes[0]
            )
            self.assertTrue(
                all(
                    item["trigger_plan_sha256"] == seen_plan_hashes[0]
                    for item in results["observations"]
                )
            )
            self.assertEqual(
                validate_gate1_trigger_evidence(
                    self.plan, results_path, profile, repository
                ),
                [],
            )

            original_results = results_path.read_text(encoding="utf-8")
            partial_results = copy.deepcopy(results)
            partial_results["observations"].pop()
            results_path.write_text(
                json.dumps(partial_results, indent=2) + "\n", encoding="utf-8"
            )
            self.assertIn(
                "trigger-results:inventory or order is not the exact 15-observation plan",
                validate_gate1_trigger_evidence(
                    self.plan, results_path, profile, repository
                ),
            )

            results_path.write_text(original_results, encoding="utf-8")
            trigger_plan_path = target / "trigger-plan.json"
            mutated_plan = load_json(trigger_plan_path)
            mutated_plan["planned_observations"].pop()
            trigger_plan_path.write_text(
                json.dumps(mutated_plan, indent=2) + "\n", encoding="utf-8"
            )
            mutation_issues = validate_gate1_trigger_evidence(
                self.plan, results_path, profile, repository
            )
            self.assertIn(
                "trigger-plan:planned_observations does not match the exact Gate 1 contract",
                mutation_issues,
            )
            self.assertIn(
                "trigger-results:pre-call trigger-plan hash mismatch",
                mutation_issues,
            )

    def test_gate1_grade_and_identity_contracts_fail_closed(self) -> None:
        contract = {
            "assertions": [
                {
                    "assertion_id": "security.a01",
                    "text": "The required security behavior is evidenced.",
                    "weight": 100,
                    "blocking": True,
                }
            ]
        }
        grade = {
            "expectations": [
                {
                    "assertion_id": "security.a01",
                    "text": "The required security behavior is evidenced.",
                    "passed": True,
                    "evidence": "task-output.json: summary",
                }
            ],
            "summary": {
                "passed": 1,
                "score": 100,
                "blocking_failures": 0,
                "failed": 0,
            },
            "integrity_events": [],
            "unauthorized_external_mutations": [],
            "notes": [],
        }
        self.assertEqual(validate_grade(grade, contract), [])
        self.assertEqual(gate1_grade_validation_errors(grade, "grade"), [])
        empty_expectations = copy.deepcopy(grade)
        empty_expectations["expectations"] = []
        self.assertTrue(
            gate1_grade_validation_errors(empty_expectations, "grade")
        )
        nonperfect = copy.deepcopy(grade)
        nonperfect["expectations"][0]["passed"] = False
        nonperfect["summary"] = {
            "passed": 0,
            "failed": 1,
            "score": 0,
            "blocking_failures": 1,
        }
        self.assertEqual(validate_grade(nonperfect, contract), [])
        self.assertTrue(gate1_grade_validation_errors(nonperfect, "grade"))
        contaminated = copy.deepcopy(grade)
        contaminated["integrity_events"] = [
            {"type": "fabricated_evidence", "evidence": "synthetic"}
        ]
        self.assertTrue(gate1_grade_validation_errors(contaminated, "grade"))
        mutated = copy.deepcopy(grade)
        mutated["unauthorized_external_mutations"] = [
            {"target": "live-service", "evidence": "transcript event"}
        ]
        self.assertTrue(gate1_grade_validation_errors(mutated, "grade"))
        profile = {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"}
        repository = {"commit": "a" * 40, "tree": "b" * 40, "dirty": False}
        self.assertEqual(
            _identity_errors(
                {"execution_profile": profile, "repository": repository},
                profile,
                repository,
                "receipt",
            ),
            [],
        )
        self.assertTrue(
            _identity_errors(
                {
                    "execution_profile": {
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "high",
                    },
                    "repository": repository,
                },
                profile,
                repository,
                "receipt",
            )
        )

    def test_gate1_trigger_validator_requires_pre_call_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            results_path = Path(temp_name) / "trigger-results.json"
            results_path.write_text("{}\n", encoding="utf-8")
            issues = validate_gate1_trigger_evidence(
                self.plan,
                results_path,
                {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"},
                {"commit": "a" * 40, "tree": "b" * 40, "dirty": False},
            )
            self.assertEqual(
                issues, ["trigger:missing regular pre-call trigger-plan.json"]
            )

if __name__ == "__main__":
    unittest.main()
