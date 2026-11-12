"""Keep approved release dispositions distinct from checks that actually ran."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseDispositionTests(unittest.TestCase):
    def test_plugin_validator_gap_carries_the_approved_version_scoped_disposition(self):
        preparation = (ROOT / "docs" / "release-preparation.md").read_text(encoding="utf-8")
        rows = [line for line in preparation.splitlines() if line.startswith("| VERIFY-01 |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("NOT RUN—unavailable in audited tooling", rows[0])
        self.assertIn("v0.2.0 GitHub-only", rows[0])
        self.assertIn("not a validator pass", rows[0])
        self.assertIn("Maintainer-disposed", rows[0])


if __name__ == "__main__":
    unittest.main()
