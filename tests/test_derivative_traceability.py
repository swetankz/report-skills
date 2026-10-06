from __future__ import annotations

import csv
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = (
    REPO_ROOT
    / "source"
    / "skills"
    / "report-content-repurposer"
    / "scripts"
    / "validate_derivative_package.py"
)
POWERSHELL_VALIDATOR_PATH = (
    REPO_ROOT
    / "source"
    / "skills"
    / "report-content-repurposer"
    / "scripts"
    / "validate_derivative_package.ps1"
)
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("validate_derivative_package", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(VALIDATOR)


MAPPING_FIELDS = [
    "statement_id",
    "claim_ids",
    "source_locator",
    "deliverable_id",
    "output_path",
    "output_location",
    "statement_type",
    "output_text",
    "status",
    "context_retained",
    "context_omitted",
    "reason",
]
VIDEO_FIELDS = [
    "frame_id",
    "duration_seconds",
    "content_type",
    "statement_id",
    "output_text",
    "visual_source",
    "transformation",
    "transition_intent",
    "parent_report_id",
    "parent_report_version",
    "parent_report_hash",
    "source_claim_ids",
    "transformation_type",
    "dimensions",
    "aspect_ratio",
    "status",
]


class DerivativeTraceabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "artifacts"
        self.root.mkdir()
        self.mapping = self.root / "claim-mapping.csv"
        self.post_text = "A synthetic survey found 62 percent stated willingness."
        self.video_text = "This is the on-screen statement."
        self.manifest_text = "A frame reports that 405 of 500 respondents required a human option."
        (self.root / "post.md").write_text(
            "---\n"
            "deliverable_id: post\n"
            "parent_report_id: synthetic-report\n"
            "parent_report_version: 1.0\n"
            "parent_report_hash: unknown\n"
            "source_claim_ids: [SYN-S1]\n"
            "transformation_type: concise social copy\n"
            "dimensions: 1080x1350 specification\n"
            "aspect_ratio: 4:5\n"
            "status: draft\n"
            "---\n\n"
            f"<!-- statement_id: ST-001 -->\n{self.post_text}\n",
            encoding="utf-8",
        )
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerow(
                {
                    "frame_id": "VF-01",
                    "duration_seconds": "5",
                    "content_type": "on_screen_copy",
                    "statement_id": "ST-002",
                    "output_text": self.video_text,
                    "visual_source": "synthetic survey data",
                    "transformation": "numeric emphasis",
                    "transition_intent": "cut from title",
                    "parent_report_id": "synthetic-report",
                    "parent_report_version": "1.0",
                    "parent_report_hash": "unknown",
                    "source_claim_ids": "SYN-S1",
                    "transformation_type": "typeset frame",
                    "dimensions": "1080x1920 specification",
                    "aspect_ratio": "9:16",
                    "status": "draft",
                }
            )
        (self.root / "manifest.yaml").write_text(
            "accessibility_copy:\n"
            "  - deliverable_id: video\n"
            "    statement_id: ST-003\n"
            f"    text: {self.manifest_text}\n",
            encoding="utf-8",
        )
        rows = [
            {
                "statement_id": "ST-001",
                "claim_ids": "SYN-S1",
                "source_locator": "complete-report.md#Findings",
                "deliverable_id": "post",
                "output_path": "post.md",
                "output_location": "body paragraph 1",
                "statement_type": "sourced_fact",
                "output_text": self.post_text,
                "status": "used",
                "context_retained": "stated willingness",
                "context_omitted": "none",
                "reason": "Within the short post format.",
            },
            {
                "statement_id": "ST-002",
                "claim_ids": "SYN-S1",
                "source_locator": "complete-report.md#Findings",
                "deliverable_id": "video",
                "output_path": "video.csv",
                "output_location": "VF-01.on_screen_copy",
                "statement_type": "sourced_fact",
                "output_text": self.video_text,
                "status": "used",
                "context_retained": "survey scope",
                "context_omitted": "none",
                "reason": "Single-frame copy.",
            },
            {
                "statement_id": "ST-003",
                "claim_ids": "SYN-S1",
                "source_locator": "complete-report.md#Findings",
                "deliverable_id": "video",
                "output_path": "manifest.yaml",
                "output_location": "accessibility_copy[ST-003].text",
                "statement_type": "sourced_fact",
                "output_text": self.manifest_text,
                "status": "used",
                "context_retained": "human-option denominator",
                "context_omitted": "none",
                "reason": "Accessibility text for the visual.",
            },
        ]
        self.write_mapping(rows)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_mapping(self, rows: list[dict[str, str]]) -> None:
        with self.mapping.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MAPPING_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_accepts_exact_marked_statements_and_per_row_csv_provenance(self) -> None:
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv"), Path("manifest.yaml")],
        )
        self.assertEqual([], errors)

    def test_rejects_unmapped_or_mismatched_output(self) -> None:
        video = self.root / "video.csv"
        text = video.read_text(encoding="utf-8")
        video.write_text(text.replace("ST-002", "ST-004"), encoding="utf-8")
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv"), Path("manifest.yaml")],
        )
        self.assertTrue(any("absent from declared deliverables" in error for error in errors))
        self.assertTrue(any("unmapped statement ST-004" in error for error in errors))

    def test_rejects_csv_missing_provenance(self) -> None:
        video = self.root / "video.csv"
        video.write_text(
            "statement_id,output_text\nST-002,This is the on-screen statement.\n",
            encoding="utf-8",
        )
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv"), Path("manifest.yaml")],
        )
        self.assertTrue(any("per-row provenance columns" in error for error in errors))

    def test_rejects_unmarked_markdown_copy(self) -> None:
        post = self.root / "post.md"
        post.write_text(
            f"<!-- statement_id: ST-001 -->\n{self.post_text}\n\nUnmarked factual sentence.\n",
            encoding="utf-8",
        )
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv"), Path("manifest.yaml")],
        )
        self.assertTrue(any("each nonempty Markdown content block" in error for error in errors))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_accepts_the_same_fixture(self) -> None:
        command = [
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(POWERSHELL_VALIDATOR_PATH),
            "-ArtifactsRoot",
            str(self.root),
            "-Mapping",
            str(self.mapping),
            "-Deliverables",
            "post.md,video.csv,manifest.yaml",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("validation passed", result.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_rejects_factual_row_without_claim_id(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["claim_ids"] = ""
        self.write_mapping(rows)
        command = [
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(POWERSHELL_VALIDATOR_PATH),
            "-ArtifactsRoot",
            str(self.root),
            "-Mapping",
            str(self.mapping),
            "-Deliverables",
            "post.md,video.csv,manifest.yaml",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("factual statement ST-001 needs claim_ids", result.stdout)


if __name__ == "__main__":
    unittest.main()
