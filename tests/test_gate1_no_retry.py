from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import evaluation_common
import run_behavioral_benchmark
from validate_gate1_evidence import gate1_task_no_retry_validation_errors


class Gate1NoRetryTests(unittest.TestCase):
    def run_synthetic_task(self, *, capacity_failure: bool, no_retries: bool):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            fixture = root / "fixture"
            fixture.mkdir()
            (fixture / "brief.txt").write_text("fixture", encoding="utf-8")
            run = {
                "run_id": "synthetic__without_skill__r01",
                "pair_id": "synthetic__r01",
                "case_id": "synthetic",
                "case_kind": "primary",
                "skill": "evidence-first-report",
                "configuration": "without_skill",
                "repetition": 1,
                "prompt": "Create a local artifact.",
                "assertions": [],
                "artifact_checks": [],
            }

            def fake_run(command, _prompt, timeout, environment=None):
                if capacity_failure:
                    return evaluation_common.CommandResult(
                        returncode=1,
                        wall_clock_seconds=1.0,
                        stdout=json.dumps({"type": "turn.failed", "error": {
                            "message": "Selected model is at capacity"
                        }}) + "\n",
                        stderr="unexpected status 503 Service Unavailable\n",
                        timeout_seconds=timeout,
                        terminal_event_count=0,
                        failed_terminal_event_count=1,
                        timeout_enforcement=evaluation_common.CODEX_TIMEOUT_ENFORCEMENT_MODE,
                    )
                output = Path(command[command.index("--output-last-message") + 1])
                output.write_text(json.dumps({
                    "status": "completed",
                    "summary": "Synthetic task completed safely.",
                    "artifacts": [],
                    "integrity_events": [],
                    "external_mutations": [],
                    "workspace_boundary_accesses": [],
                    "not_verified": [],
                }) + "\n", encoding="utf-8")
                return evaluation_common.CommandResult(
                    returncode=0,
                    wall_clock_seconds=1.0,
                    stdout=json.dumps({"type": "turn.completed"}) + "\n",
                    stderr="",
                    timeout_seconds=timeout,
                    terminal_event_count=1,
                    failed_terminal_event_count=0,
                    timeout_enforcement=evaluation_common.CODEX_TIMEOUT_ENFORCEMENT_MODE,
                )

            with (
                patch.object(run_behavioral_benchmark, "require_unchanged_repository"),
                patch.object(run_behavioral_benchmark, "codex_runtime_command", return_value="codex"),
                patch.object(evaluation_common, "codex_runtime_environment", return_value={}),
                patch.object(run_behavioral_benchmark, "run_codex", side_effect=fake_run) as native,
                patch.object(run_behavioral_benchmark.time, "sleep") as sleep,
            ):
                metadata = run_behavioral_benchmark.run_one(
                    root / "suite", run, fixture,
                    {"model": "gpt-6.1-sol", "reasoning_effort": "ultra"},
                    {"commit": "a" * 40, "tree": "b" * 40, "dirty": False},
                    evaluation_common.CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS, "001",
                    {"fixture_sha256": evaluation_common.directory_sha256(fixture),
                     "skill_package_sha256": None},
                    no_capacity_retries=no_retries,
                )
            persisted = json.loads((root / "suite/runs/001/run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata, persisted)
            return metadata, native.call_count, sleep.call_count

    def test_gate1_capacity_failure_launches_once_and_fails_closed(self):
        metadata, native_calls, sleeps = self.run_synthetic_task(capacity_failure=True, no_retries=True)
        self.assertEqual(native_calls, 1)
        self.assertEqual(sleeps, 0)
        self.assertEqual(metadata["capacity_retry_limit"], 0)
        self.assertTrue(metadata["validation_errors"])
        self.assertEqual(len(metadata["retry_attempts"]), 1)
        self.assertIs(metadata["retry_attempts"][0]["retry_scheduled"], False)
        self.assertIsNone(metadata["retry_attempts"][0]["retry_delay_seconds"])
        self.assertEqual(evaluation_common.behavioral_task_retry_receipt_validation_errors(
            metadata, evaluation_common.CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS, "task"
        ), [])
        self.assertTrue(gate1_task_no_retry_validation_errors(metadata, "task"))

    def test_successful_gate1_task_has_empty_failure_ledger(self):
        metadata, native_calls, sleeps = self.run_synthetic_task(capacity_failure=False, no_retries=True)
        self.assertEqual((native_calls, sleeps), (1, 0))
        self.assertEqual(metadata["validation_errors"], [])
        self.assertEqual(metadata["retry_attempts"], [])
        self.assertEqual(gate1_task_no_retry_validation_errors(metadata, "task"), [])

    def test_gate2_default_capacity_retry_budget_is_unchanged(self):
        metadata, native_calls, sleeps = self.run_synthetic_task(capacity_failure=True, no_retries=False)
        self.assertEqual((native_calls, sleeps), (3, 2))
        self.assertNotIn("capacity_retry_limit", metadata)
        self.assertEqual([attempt["retry_scheduled"] for attempt in metadata["retry_attempts"]], [True, True, False])
        self.assertEqual(evaluation_common.behavioral_task_retry_receipt_validation_errors(
            metadata, evaluation_common.CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS, "task"
        ), [])
        tampered = copy.deepcopy(metadata)
        tampered["capacity_retry_limit"] = 0
        self.assertTrue(evaluation_common.behavioral_task_retry_receipt_validation_errors(
            tampered, evaluation_common.CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS, "task"
        ))

    def test_explicit_retry_limit_rejects_bool(self):
        metadata, _, _ = self.run_synthetic_task(capacity_failure=False, no_retries=True)
        metadata["capacity_retry_limit"] = False
        self.assertTrue(evaluation_common.behavioral_task_retry_receipt_validation_errors(
            metadata, evaluation_common.CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS, "task"
        ))


if __name__ == "__main__":
    unittest.main()
