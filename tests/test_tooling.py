from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_skills.py"
SCAN_SCRIPT = REPO_ROOT / "scripts" / "scan_public_content.py"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "create_release_package.py"
SOURCE_SNAPSHOT_SCRIPT = REPO_ROOT / "scripts" / "create_source_snapshot.py"
EXPECTED_SKILLS = {
    "report-skills",
    "evidence-first-report",
    "editorial-data-storytelling",
    "report-visual-system",
    "interactive-report-publisher",
    "visual-hygiene-auditor",
    "motion-performance-qa",
    "report-content-repurposer",
    "sites-release-manager",
    "pencil-safe-editor",
    "creative-artifact-provenance",
}
EXPLICIT_ONLY = {"report-skills", "sites-release-manager", "pencil-safe-editor"}


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ToolingTests(unittest.TestCase):
    def test_plugin_and_tooling_versions_match(self) -> None:
        plugin = json.loads(
            (REPO_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], project["project"]["version"])

    def test_skill_map_has_exact_inventory(self) -> None:
        mapping = json.loads((REPO_ROOT / "source" / "skill-map.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(mapping["skills"]), EXPECTED_SKILLS)

    def test_generator_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            first = Path(temp_name) / "first"
            second = Path(temp_name) / "second"
            for output in (first, second):
                result = subprocess.run(
                    [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(tree_hashes(first), tree_hashes(second))

    def test_generated_packages_have_no_parent_traversal(self) -> None:
        for skill in sorted(EXPECTED_SKILLS):
            root = REPO_ROOT / "skills" / skill
            self.assertTrue(root.is_dir(), skill)
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.casefold() in {".md", ".yaml", ".yml", ".json", ".py"}:
                    self.assertNotIn("../", path.read_text(encoding="utf-8"), path.as_posix())

    def test_explicit_only_skills_publish_activation_boundary(self) -> None:
        for tree in (REPO_ROOT / "source" / "skills", REPO_ROOT / "skills"):
            for skill in sorted(EXPLICIT_ONLY):
                text = (tree / skill / "SKILL.md").read_text(encoding="utf-8")
                description = next(
                    line for line in text.splitlines() if line.startswith("description:")
                )
                self.assertTrue(description.startswith('description: "'), skill)
                self.assertTrue(description.endswith('"'), skill)
                self.assertIn("Explicit invocation only:", description, skill)
                self.assertIn(f"${skill}", description, skill)
                self.assertIn(
                    "topical requests without that token must not activate it",
                    description,
                    skill,
                )
                metadata = (tree / skill / "agents" / "openai.yaml").read_text(
                    encoding="utf-8"
                )
                short_description = next(
                    line.strip()
                    for line in metadata.splitlines()
                    if line.strip().startswith("short_description:")
                )
                self.assertIn('short_description: "Explicit-only:', short_description, skill)
                self.assertIn(f"${skill}", short_description, skill)

    def test_scanner_detects_sensitive_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            private_path = "C:" + "\\Users\\sample-person\\report"
            secret_assignment = "access_" + "token='synthetic-but-secret-value'"
            (root / "unsafe.txt").write_text(
                f"private path {private_path}\n{secret_assignment}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("windows-user-path", result.stdout)
            self.assertIn("assigned-secret", result.stdout)

    def test_scanner_allows_approved_public_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "metadata.md").write_text(
                "Author: Swetank Gawde\nRepository: https://github.com/swetankz/report-skills\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scanner_allows_declared_placeholder_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            fixture = root / "intentional-defects"
            fixture.mkdir()
            (fixture / "draft.md").write_text("TODO: synthetic defect\nTBD: synthetic defect\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scanner_ignores_uncommitted_evaluation_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            raw = root / "evals" / "runs" / "local-observation"
            raw.mkdir(parents=True)
            private_path = "C:" + "\\Users\\sample-person\\private"
            (raw / "transcript.json").write_text(
                json.dumps({"workspace": private_path}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scanner_ignores_its_copied_pattern_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(SCAN_SCRIPT, scripts / "scan_public_content.py")
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_authorization_tag_must_match_version(self) -> None:
        for script in (RELEASE_SCRIPT, SOURCE_SNAPSHOT_SCRIPT):
            result = subprocess.run(
                [sys.executable, str(script), "--authorized-release-tag", "v9.9.9"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0, script.name)
            self.assertIn("does not match plugin version", result.stdout + result.stderr)

    def test_evaluation_inventory_matches_skills(self) -> None:
        evaluations = json.loads((REPO_ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual({case["skill"] for case in evaluations["cases"]}, EXPECTED_SKILLS)
        self.assertGreaterEqual(len(evaluations["adversarial_cases"]), 3)

    def test_asset_license_ledger_covers_bundled_assets(self) -> None:
        ledger_path = REPO_ROOT / "docs" / "asset-license-ledger.csv"
        with ledger_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        recorded = [row["path"] for row in rows]
        expected = {
            path.relative_to(REPO_ROOT).as_posix()
            for root in (REPO_ROOT / "templates", REPO_ROOT / "examples" / "synthetic-report")
            for path in root.rglob("*")
            if path.is_file() and path.name != "README.md"
        }
        self.assertEqual(len(recorded), len(set(recorded)), "asset ledger contains duplicate paths")
        self.assertEqual(expected - set(recorded), set(), "asset ledger omits bundled assets")
        for row in rows:
            self.assertEqual(row["redistribution_allowed"], "yes", row["path"])
            self.assertEqual(row["license"], "MIT", row["path"])

    def test_forward_test_result_meets_release_threshold(self) -> None:
        result = json.loads(
            (REPO_ROOT / "evals" / "results" / "forward-test-2026-08-12.json").read_text(encoding="utf-8")
        )
        self.assertEqual({item["skill"] for item in result["skills"]}, EXPECTED_SKILLS)
        self.assertTrue(all(item["score"] >= 85 for item in result["skills"]))
        self.assertTrue(all(item["result"].startswith("pass") for item in result["skills"]))
        self.assertTrue(all(item["result"] == "pass" for item in result["adversarial_cases"]))
        self.assertEqual(result["blocking_rule_failures"], 0)
        self.assertEqual(result["unresolved_high_or_critical_skill_findings"], 0)
        self.assertEqual(result["external_actions_performed"], 0)


if __name__ == "__main__":
    unittest.main()
