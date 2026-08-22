from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_behavioral_benchmark as behavioral  # noqa: E402
import run_trigger_evals as trigger  # noqa: E402
from evaluation_common import (  # noqa: E402
    canonical_behavioral_task_stage_method,
    canonical_trigger_stage_method,
)
from validate_graphify_integration import (  # noqa: E402
    EXPECTED_RECEIPT,
    validate_graphify_integration,
)


class GraphifyIntegrationTests(unittest.TestCase):
    def make_portable_fixture(self, root: Path) -> None:
        (root / "docs").mkdir()
        (root / ".gitignore").write_text(
            "/.agents/rules/graphify.md\n"
            "/.agents/skills/graphify/\n"
            "/.agents/workflows/graphify.md\n"
            "/.codex/hooks.json\n"
            "/.codex/skills/graphify/\n"
            "/graphify-out/\n",
            encoding="utf-8",
        )
        (root / ".graphifyignore").write_text(
            ".agents/rules/graphify.md\n"
            ".agents/skills/graphify/\n"
            ".agents/workflows/graphify.md\n"
            ".codex/hooks.json\n"
            ".codex/skills/graphify/\n"
            "evals/review/\n"
            "evals/runs/\n"
            "graphify-out/\n",
            encoding="utf-8",
        )
        (root / "AGENTS.md").write_text(
            "Graphify result as advisory.\n"
            "It must never waive, prune, or satisfy required checks.\n"
            "Never copy `AGENTS.md`, `.codex/` into model workspaces.\n"
            "Run graphify check-update . before queries.\n"
            "Use graphifyy==0.9.48.\n",
            encoding="utf-8",
        )
        (root / "docs" / "graphify.md").write_text(
            "Use graphifyy==0.9.48 locally.\n", encoding="utf-8"
        )
        (root / "docs" / "graphify-receipt.json").write_text(
            json.dumps(EXPECTED_RECEIPT, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def initialize_git(self, root: Path) -> None:
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)

    def test_portable_policy_without_local_graph_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.make_portable_fixture(root)

            self.assertEqual(validate_graphify_integration(root), [])

    def test_missing_ignore_and_isolation_clause_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.make_portable_fixture(root)
            (root / ".gitignore").write_text("/graphify-out/\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("Use graphifyy==0.9.48.\n", encoding="utf-8")

            errors = validate_graphify_integration(root)

            self.assertTrue(any(".gitignore" in error for error in errors))
            self.assertTrue(any("safety clause" in error for error in errors))

    def test_protected_ignore_negation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.make_portable_fixture(root)
            with (root / ".gitignore").open("a", encoding="utf-8") as handle:
                handle.write("!/graphify-out/graph.json\n")

            errors = validate_graphify_integration(root)

            self.assertTrue(any("must not negate" in error for error in errors))

    def test_receipt_version_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.make_portable_fixture(root)
            receipt = json.loads((root / "docs" / "graphify-receipt.json").read_text())
            receipt["package"]["version"] = "0.9.49"
            (root / "docs" / "graphify-receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )

            errors = validate_graphify_integration(root)

            self.assertTrue(any("approved Graphify receipt" in error for error in errors))

    def test_non_git_archive_rejects_local_graphify_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.make_portable_fixture(root)
            hook = root / ".codex" / "hooks.json"
            hook.parent.mkdir()
            hook.write_text("{}\n", encoding="utf-8")

            errors = validate_graphify_integration(root)

            self.assertTrue(any("non-Git archive" in error for error in errors))

    def test_local_adapter_version_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.make_portable_fixture(root)
            self.initialize_git(root)
            adapter = root / ".codex" / "skills" / "graphify"
            adapter.mkdir(parents=True)
            (adapter / ".graphify_version").write_text("0.9.47\n", encoding="utf-8")

            errors = validate_graphify_integration(root, include_local_state=True)

            self.assertTrue(any("expected 0.9.48" in error for error in errors))

    def test_local_graph_rejects_dangling_and_case_variant_excluded_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.make_portable_fixture(root)
            self.initialize_git(root)
            output = root / "graphify-out"
            output.mkdir()
            (output / "graph.json").write_text(
                json.dumps(
                    {
                        "built_at_commit": "0123456789abcdef",
                        "nodes": [
                            {"id": "one", "source_file": "EVALS/RUNS/private.py"}
                        ],
                        "links": [
                            {"source": "one", "target": "missing", "relation": "calls"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            errors = validate_graphify_integration(root, include_local_state=True)

            self.assertTrue(any("excluded local path" in error for error in errors))
            self.assertTrue(any("dangling endpoint" in error for error in errors))

    def test_behavioral_staging_excludes_project_graphify_state(self) -> None:
        run = {"configuration": "with_skill", "skill": "evidence-first-report"}
        staging_root, workspace = behavioral.prepare_workspace(
            run, REPO_ROOT / "examples" / "synthetic-report"
        )
        try:
            for relative in (
                "AGENTS.md",
                ".codex",
                ".agents/skills/graphify",
                ".agents/rules/graphify.md",
                ".agents/workflows/graphify.md",
                "graphify-out",
            ):
                self.assertFalse((workspace / relative).exists(), relative)
            self.assertTrue(
                (workspace / ".benchmark_skill/evidence-first-report/SKILL.md").is_file()
            )
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    def test_trigger_staging_contains_only_requested_sentinel_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="report-skills-trigger-test-") as temp_name:
            workspace = Path(temp_name)
            case = {
                "candidate_skill": "evidence-first-report",
                "observation_id": "graphify-isolation-test",
            }
            trigger.install_sentinel_skill(workspace, case)

            self.assertFalse((workspace / "AGENTS.md").exists())
            self.assertFalse((workspace / ".codex").exists())
            self.assertFalse((workspace / ".agents/skills/graphify").exists())
            self.assertFalse((workspace / "graphify-out").exists())
            skill_dirs = sorted(
                path.name for path in (workspace / ".agents" / "skills").iterdir()
            )
            self.assertEqual(skill_dirs, ["evidence-first-report"])

    def test_canonical_stage_receipts_do_not_claim_graphify_evidence(self) -> None:
        methods = [
            canonical_behavioral_task_stage_method(),
            canonical_trigger_stage_method(),
        ]

        self.assertNotIn("graphify", json.dumps(methods).casefold())


if __name__ == "__main__":
    unittest.main()
