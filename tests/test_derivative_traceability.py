from __future__ import annotations

import csv
import importlib.util
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
    "content_type",
    "statement_id",
    "output_text",
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
        (self.root / "post.md").write_text(
            f"<!-- statement_id: ST-001 -->\n{self.post_text}\n",
            encoding="utf-8",
        )
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerow(
                {
                    "frame_id": "VF-01",
                    "content_type": "on_screen_copy",
                    "statement_id": "ST-002",
                    "output_text": self.video_text,
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
            [Path("post.md"), Path("video.csv")],
        )
        self.assertEqual([], errors)

    def test_rejects_unmapped_or_mismatched_output(self) -> None:
        video = self.root / "video.csv"
        text = video.read_text(encoding="utf-8")
        video.write_text(text.replace("ST-002", "ST-003"), encoding="utf-8")
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv")],
        )
        self.assertTrue(any("absent from declared deliverables" in error for error in errors))
        self.assertTrue(any("unmapped statement ST-003" in error for error in errors))

    def test_rejects_csv_missing_provenance(self) -> None:
        video = self.root / "video.csv"
        video.write_text(
            "statement_id,output_text\nST-002,This is the on-screen statement.\n",
            encoding="utf-8",
        )
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv")],
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
            [Path("post.md"), Path("video.csv")],
        )
        self.assertTrue(any("each nonempty Markdown content block" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
