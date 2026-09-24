from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
class SkillCsvWriterTests(unittest.TestCase):
    def run_writer(self, directory: Path, payload: dict) -> subprocess.CompletedProcess[str]:
        input_path = directory / "register-data.json"
        output_path = directory / "artifacts" / "register.csv"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        script = ROOT / "source" / "skills" / "evidence-first-report" / "scripts" / "write-register-csv.ps1"
        return subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(script),
                "-InputJsonPath",
                str(input_path),
                "-OutputPath",
                str(output_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_writer_round_trips_commas_quotes_and_embedded_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            header = ["claim_id", "claim_text"]
            payload = {
                "header": header,
                "rows": [
                    {"claim_id": "C1", "claim_text": 'Comma, quote " and line\nbreak'},
                    {"claim_id": "C2", "claim_text": "Second row"},
                ],
            }
            result = self.run_writer(directory, payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            with (directory / "artifacts" / "register.csv").open(
                "r", encoding="utf-8", newline=""
            ) as stream:
                records = list(csv.reader(stream, strict=True))
            self.assertEqual(records[0], header)
            self.assertEqual(records[1], ["C1", 'Comma, quote " and line\nbreak'])
            self.assertEqual(records[2], ["C2", "Second row"])
            self.assertTrue(all(len(row) == len(header) for row in records))

    def test_writer_rejects_mismatched_and_whitespace_only_rows(self) -> None:
        cases = (
            {"header": ["a", "b"], "rows": [{"a": "only one field"}]},
            {"header": ["a", "b"], "rows": [{"a": " ", "b": "\t"}]},
        )
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp_dir:
                result = self.run_writer(Path(temp_dir), payload)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
