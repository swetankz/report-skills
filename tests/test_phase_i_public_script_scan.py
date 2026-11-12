from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_SCRIPT = REPO_ROOT / "scripts" / "scan_public_content.py"
SAFE_SCRIPT = "# Synthetic public script fixture\nWrite-Output 'synthetic public report'\n"
SYNTHETIC_PRIVATE_PATH = "C:" + "\\Users\\synthetic-scanner-person\\report"
SYNTHETIC_TOKEN = "gh" + "p_" + "SYNTHETICNOTAREALTOKEN1234567890"
SENSITIVE_FIXTURES = (
    ("windows-user-path", "$report = '" + SYNTHETIC_PRIVATE_PATH + "'\n", "synthetic-scanner-person"),
    ("github-token", "$fixture = '" + SYNTHETIC_TOKEN + "'\n", SYNTHETIC_TOKEN),
)


def run_scanner(root: Path, *, as_json: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCAN_SCRIPT), "--root", str(root)]
    if as_json:
        command.append("--json")
    return subprocess.run(command, capture_output=True, check=False, text=True, timeout=30)


class PublicScriptScanTests(unittest.TestCase):
    def test_scanner_accepts_safe_powershell_scripts(self) -> None:
        for suffix in (".ps1", ".PS1"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temp_name:
                root = Path(temp_name)
                (root / ("public-script" + suffix)).write_text(SAFE_SCRIPT, encoding="utf-8")

                result = run_scanner(root, as_json=True)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(json.loads(result.stdout), [])

    def test_scanner_rejects_powershell_private_paths_and_tokens(self) -> None:
        for suffix in (".ps1", ".PS1"):
            for category, payload, marker in SENSITIVE_FIXTURES:
                with self.subTest(suffix=suffix, category=category), tempfile.TemporaryDirectory() as temp_name:
                    root = Path(temp_name)
                    script = root / ("public-script" + suffix)
                    script.write_text(SAFE_SCRIPT, encoding="utf-8")
                    safe = run_scanner(root, as_json=True)
                    self.assertEqual(safe.returncode, 0, safe.stdout + safe.stderr)
                    self.assertEqual(json.loads(safe.stdout), [])

                    script.write_text(SAFE_SCRIPT + payload, encoding="utf-8")
                    result = run_scanner(root, as_json=True)

                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        json.loads(result.stdout),
                        [{
                            "category": category,
                            "path": script.name,
                            "line": 3,
                            "detail": "sensitive pattern detected; inspect and redact",
                        }],
                    )
                    self.assertNotIn(marker, result.stdout + result.stderr)
                    self.assertNotIn(payload.strip(), result.stdout + result.stderr)

    def test_scanner_redacts_powershell_text_diagnostics(self) -> None:
        for suffix in (".ps1", ".PS1"):
            for category, payload, marker in SENSITIVE_FIXTURES:
                with self.subTest(suffix=suffix, category=category), tempfile.TemporaryDirectory() as temp_name:
                    root = Path(temp_name)
                    script = root / ("public-script" + suffix)
                    script.write_text(SAFE_SCRIPT + payload, encoding="utf-8")

                    result = run_scanner(root)

                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertIn("Public-safety scan found 1 blocking item(s):", result.stdout)
                    self.assertIn(
                        f"{category}: {script.name}:3 — sensitive pattern detected; inspect and redact",
                        result.stdout,
                    )
                    self.assertNotIn(marker, result.stdout + result.stderr)
                    self.assertNotIn(payload.strip(), result.stdout + result.stderr)

    def test_scanner_preserves_private_powershell_evidence_exclusions(self) -> None:
        for directory in (".build/local-only", "dist/local-only", "evals/runs/local-only", "evals/review/local-only"):
            for suffix in (".ps1", ".PS1"):
                with self.subTest(directory=directory, suffix=suffix), tempfile.TemporaryDirectory() as temp_name:
                    root = Path(temp_name)
                    (root / "safe.ps1").write_text(SAFE_SCRIPT, encoding="utf-8")
                    private = root / directory / ("private-script" + suffix)
                    private.parent.mkdir(parents=True)
                    private.write_text(
                        SAFE_SCRIPT + "".join(payload for _, payload, _ in SENSITIVE_FIXTURES),
                        encoding="utf-8",
                    )

                    excluded = run_scanner(root, as_json=True)

                    self.assertEqual(excluded.returncode, 0, excluded.stdout + excluded.stderr)
                    self.assertEqual(excluded.stderr, "")
                    self.assertEqual(json.loads(excluded.stdout), [])

                    public = root / ("public-script" + suffix)
                    private.replace(public)
                    included = run_scanner(root, as_json=True)

                    self.assertEqual(included.returncode, 1, included.stdout + included.stderr)
                    self.assertEqual(included.stderr, "")
                    self.assertEqual(
                        [(finding["category"], finding["path"], finding["line"]) for finding in json.loads(included.stdout)],
                        [(category, public.name, line) for line, (category, _, _) in enumerate(SENSITIVE_FIXTURES, start=3)],
                    )
                    for _, _, marker in SENSITIVE_FIXTURES:
                        self.assertNotIn(marker, included.stdout + included.stderr)


if __name__ == "__main__":
    unittest.main()
