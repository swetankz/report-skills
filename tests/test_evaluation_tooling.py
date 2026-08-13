from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aggregate_benchmark import evaluate_release  # noqa: E402
from evaluation_common import (  # noqa: E402
    EvaluationError,
    build_run_plan,
    load_json,
    normalize_suite,
    validate_output_root,
)
from grade_behavioral_benchmark import validate_grade  # noqa: E402
from run_blind_comparisons import copy_blind_bundle, label_map  # noqa: E402
from run_trigger_evals import confusion_metrics, summarize  # noqa: E402


class EvaluationToolingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = normalize_suite(load_json(REPO_ROOT / "evals" / "benchmark-suite.json"))
        cls.thresholds = load_json(REPO_ROOT / "evals" / "release-thresholds.json")

    def test_full_and_primary_run_plan_counts(self) -> None:
        self.assertEqual(len(build_run_plan(self.suite, 3)), 96)
        self.assertEqual(len(build_run_plan(self.suite, 3, include_adversarial=False)), 66)

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
