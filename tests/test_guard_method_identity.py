"""Identity regressions for the offline literal-comparison guard repair."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluation_common as ec


class GuardMethodIdentityTests(unittest.TestCase):
    def test_repaired_guard_uses_fresh_method_and_guard_identities(self):
        self.assertEqual(ec.EVALUATION_METHOD_VERSION, "report-skills-release-evaluation-v61")
        self.assertEqual(ec.TASK_SKILL_BODY_READ_GUARD, "named-skill-path-command-events-v5")

    def test_host_boundary_guard_identity_is_rebound_in_task_receipts(self):
        self.assertEqual(ec.TASK_OUTPUT_SAFETY_GUARD, "task-output-and-host-boundary-safety-v13")
        self.assertEqual(ec.canonical_task_isolation_receipt()["task_output_safety_guard"], ec.TASK_OUTPUT_SAFETY_GUARD)
        self.assertEqual(ec.canonical_behavioral_task_stage_method()["isolation"]["task_output_safety_guard"], ec.TASK_OUTPUT_SAFETY_GUARD)

    def test_gate1_plan_and_stage_receipt_match_the_active_method(self):
        plan = json.loads((ROOT / "evals" / "gate1-release-plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["evaluation_method_version"], ec.EVALUATION_METHOD_VERSION)
        self.assertEqual(
            ec.canonical_behavioral_task_stage_method()["evaluation_method_version"],
            ec.EVALUATION_METHOD_VERSION,
        )

    def test_current_documentation_matches_method_without_relabelling_history(self):
        evaluation = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
        active = re.search(r"The active method is `([^`]+)`", evaluation)
        self.assertIsNotNone(active)
        self.assertEqual(active.group(1), ec.EVALUATION_METHOD_VERSION)
        checklist = (ROOT / "docs" / "release-checklist.md").read_text(encoding="utf-8")
        current = re.search(r"All new evidence uses evaluation method (v\d+)", checklist)
        self.assertIsNotNone(current)
        self.assertEqual(current.group(1), ec.EVALUATION_METHOD_VERSION.rsplit("-", 1)[1])
        self.assertIn("Method v57 carries forward", evaluation)


if __name__ == "__main__":
    unittest.main()
