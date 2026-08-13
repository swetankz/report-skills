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


if __name__ == "__main__":
    unittest.main()
