from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import grade_behavioral_benchmark  # noqa: E402
from evaluation_common import (  # noqa: E402
    lstat_path_entry_exists,
    task_evidence_receipt,
    validate_task_evidence_binding,
    workspace_environment_receipt,
    workspace_environment_receipt_validation_errors,
)


class CleanupReceiptTests(unittest.TestCase):
    def test_task_cleanup_requires_workspace_and_staging_ceiling_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            staging_root = root / "report-skills-task-test"
            workspace = staging_root / "workspace"
            workspace.mkdir(parents=True)
            receipt = workspace_environment_receipt(workspace)

            live_errors = workspace_environment_receipt_validation_errors(
                {"workspace_environment": receipt},
                "task execution",
                require_absent_workspace=True,
                require_absent_ceiling=True,
            )
            self.assertIn(
                "task execution recorded workspace was not cleaned", live_errors
            )
            self.assertIn(
                "task execution recorded ceiling was not cleaned", live_errors
            )

            shutil.rmtree(staging_root)
            self.assertEqual(
                workspace_environment_receipt_validation_errors(
                    {"workspace_environment": receipt},
                    "task execution",
                    require_absent_workspace=True,
                    require_absent_ceiling=True,
                ),
                [],
            )

    def test_task_downstream_binding_checks_recorded_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            run_dir = root / "evidence" / "001"
            (run_dir / "workspace").mkdir(parents=True)
            for name, contents in (
                ("task-output.json", "{}\n"),
                ("transcript.jsonl", "{}\n"),
                ("stderr.txt", ""),
                ("case_contract.json", "{}\n"),
            ):
                (run_dir / name).write_text(contents, encoding="utf-8")

            staging_root = root / "report-skills-task-live"
            staged_workspace = staging_root / "workspace"
            staged_workspace.mkdir(parents=True)
            metadata = {
                "task_evidence": task_evidence_receipt(run_dir),
                "workspace_environment": workspace_environment_receipt(
                    staged_workspace
                ),
            }

            errors = validate_task_evidence_binding(metadata, run_dir)
            self.assertIn(
                "task execution recorded workspace was not cleaned", errors
            )
            self.assertIn("task execution recorded ceiling was not cleaned", errors)

    def test_cleanup_presence_uses_lstat_instead_of_target_exists(self) -> None:
        class DanglingLinkLikeEntry:
            def exists(self) -> bool:
                return False

            def lstat(self) -> object:
                return object()

        entry = DanglingLinkLikeEntry()
        self.assertFalse(entry.exists())
        self.assertTrue(lstat_path_entry_exists(entry))  # type: ignore[arg-type]

    def test_grader_attempt_and_final_validation_require_staging_root_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            staging_root = root / "report-skills-grader-live"
            staging_root.mkdir()
            receipt = workspace_environment_receipt(staging_root)

            attempt_errors = (
                grade_behavioral_benchmark.validate_grader_attempt_binding(
                    {"workspace_environment": receipt},
                    {},
                    {},
                    "001",
                )
            )
            self.assertIn(
                "grader attempt recorded workspace was not cleaned", attempt_errors
            )

            run_dir = root / "runs" / "001"
            run_dir.mkdir(parents=True)
            final_errors = grade_behavioral_benchmark.validate_grader_output_binding(
                {"workspace_environment": receipt},
                run_dir / "grading.json",
                run_dir / "case_contract.json",
                run_dir / "grader_attempt.json",
                run_dir,
            )
            self.assertIn(
                "grader metadata recorded workspace was not cleaned", final_errors
            )


if __name__ == "__main__":
    unittest.main()
