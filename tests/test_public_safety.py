from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_SCRIPT = REPO_ROOT / "scripts" / "scan_public_content.py"


def run_scanner(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
        capture_output=True,
        check=False,
        text=True,
    )


class PublicSafetyTests(unittest.TestCase):
    def test_scanner_rejects_git_tracked_raw_evaluation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            for relative in (
                Path("evals/runs/release-run/transcript.json"),
                Path("evals/review/release-run/feedback.json"),
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"local": "raw evaluation evidence"}), encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={root}",
                    "-C",
                    str(root),
                    "add",
                    "-f",
                    "--",
                    "evals/runs",
                    "evals/review",
                ],
                check=True,
            )

            result = run_scanner(root)

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("tracked-raw-eval-artifact"), 2)
            self.assertIn("evals/runs/release-run/transcript.json", result.stdout)
            self.assertIn("evals/review/release-run/feedback.json", result.stdout)

    def test_scanner_ignores_untracked_local_raw_evaluation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            raw = root / "evals" / "runs" / "local-only" / "transcript.json"
            raw.parent.mkdir(parents=True)
            private_path = "C:" + "\\Users\\sample-person\\private"
            raw.write_text(
                json.dumps({"workspace": private_path}),
                encoding="utf-8",
            )

            result = run_scanner(root)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Public-safety scan passed", result.stdout)

    def test_scanner_ignores_untracked_local_graphify_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            private_path = "C:" + "\\Users\\sample-person\\private"
            placeholder = "<" + "path>"
            files = {
                Path(".codex/hooks.json"): private_path,
                Path(".codex/skills/graphify/SKILL.md"): f"Use {placeholder} locally.",
                Path(".agents/rules/graphify.md"): f"Use {placeholder} locally.",
                Path(".agents/skills/graphify/SKILL.md"): f"Use {placeholder} locally.",
                Path(".agents/workflows/graphify.md"): f"Use {placeholder} locally.",
                Path("graphify-out/graph.json"): json.dumps({"root": private_path}),
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            result = run_scanner(root)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Public-safety scan passed", result.stdout)

    def test_scanner_rejects_tracked_local_graphify_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            paths = (
                Path(".codex/hooks.json"),
                Path(".codex/skills/graphify/SKILL.md"),
                Path(".agents/rules/graphify.md"),
                Path(".agents/skills/graphify/SKILL.md"),
                Path(".agents/workflows/graphify.md"),
                Path("graphify-out/graph.json"),
            )
            for relative in paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("local Graphify state\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={root}",
                    "-C",
                    str(root),
                    "add",
                    "-f",
                    "--",
                    *(path.as_posix() for path in paths),
                ],
                check=True,
            )

            result = run_scanner(root)

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("tracked-local-graphify-artifact"), 6)

    def test_scanner_rejects_graphify_artifacts_in_non_git_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            artifact = root / "graphify-out" / "graph.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n", encoding="utf-8")

            result = run_scanner(root)

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("local-graphify-artifact-outside-worktree", result.stdout)
            self.assertIn("graphify-out/graph.json", result.stdout)


if __name__ == "__main__":
    unittest.main()
