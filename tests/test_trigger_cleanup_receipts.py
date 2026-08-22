from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evaluation_common import (  # noqa: E402
    EvaluationError,
    workspace_environment_receipt,
    workspace_environment_receipt_validation_errors,
)
from run_trigger_evals import (  # noqa: E402
    require_trigger_staging_workspace_absent,
)


class TriggerCleanupReceiptTests(unittest.TestCase):
    def test_absent_workspace_is_accepted_while_shared_temp_ceiling_remains(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            ceiling = Path(temp_name)
            workspace = ceiling / "report-skills-trigger-cleaned"
            workspace.mkdir()
            receipt = workspace_environment_receipt(workspace)
            workspace.rmdir()

            require_trigger_staging_workspace_absent(workspace)
            self.assertTrue(ceiling.is_dir())
            self.assertEqual(
                workspace_environment_receipt_validation_errors(
                    {"workspace_environment": receipt},
                    "trigger case__r01",
                    require_absent_workspace=True,
                ),
                [],
            )

    def test_recreated_recorded_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name) / "report-skills-trigger-cleaned"
            workspace.mkdir()
            receipt = workspace_environment_receipt(workspace)
            workspace.rmdir()
            workspace.mkdir()

            with self.assertRaisesRegex(
                EvaluationError, "Trigger staging cleanup did not complete"
            ):
                require_trigger_staging_workspace_absent(workspace)
            self.assertIn(
                "trigger case__r01 recorded workspace was not cleaned",
                workspace_environment_receipt_validation_errors(
                    {"workspace_environment": receipt},
                    "trigger case__r01",
                    require_absent_workspace=True,
                ),
            )

    def test_dangling_link_at_recorded_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            workspace = root / "report-skills-trigger-cleaned"
            workspace.mkdir()
            receipt = workspace_environment_receipt(workspace)
            workspace.rmdir()
            missing_target = root / "removed-target"
            try:
                workspace.symlink_to(missing_target, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlink creation is unavailable")

            self.assertFalse(workspace.exists())
            with self.assertRaisesRegex(
                EvaluationError, "Trigger staging cleanup did not complete"
            ):
                require_trigger_staging_workspace_absent(workspace)
            self.assertIn(
                "trigger case__r01 recorded workspace was not cleaned",
                workspace_environment_receipt_validation_errors(
                    {"workspace_environment": receipt},
                    "trigger case__r01",
                    require_absent_workspace=True,
                ),
            )

    def test_junction_or_directory_link_at_recorded_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            workspace = root / "report-skills-trigger-cleaned"
            workspace.mkdir()
            receipt = workspace_environment_receipt(workspace)
            workspace.rmdir()
            target = root / "replacement-target"
            target.mkdir()

            if os.name == "nt":
                created = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(workspace), str(target)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if created.returncode != 0:
                    self.skipTest("Windows junction creation is unavailable")
            else:
                try:
                    workspace.symlink_to(target, target_is_directory=True)
                except OSError:
                    self.skipTest("directory symlink creation is unavailable")

            try:
                with self.assertRaisesRegex(
                    EvaluationError, "Trigger staging cleanup did not complete"
                ):
                    require_trigger_staging_workspace_absent(workspace)
                self.assertIn(
                    "trigger case__r01 recorded workspace was not cleaned",
                    workspace_environment_receipt_validation_errors(
                        {"workspace_environment": receipt},
                        "trigger case__r01",
                        require_absent_workspace=True,
                    ),
                )
            finally:
                if workspace.is_symlink():
                    workspace.unlink()
                else:
                    os.rmdir(workspace)


if __name__ == "__main__":
    unittest.main()
