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
    "visual_unit_id",
    "related_statement_ids",
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
        self.post_alt = self.post_text
        self.video_text = "This is the on-screen statement."
        self.video_transcript = self.video_text
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
            f"<!-- statement_id: ST-001 -->\n{self.post_text}\n\n"
            f"<!-- statement_id: ST-004 -->\n{self.post_alt}\n",
            encoding="utf-8",
        )
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            common = {
                "frame_id": "VF-01",
                "duration_seconds": "5",
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
            writer.writerow(
                {
                    **common,
                    "content_type": "on_screen_copy",
                    "statement_id": "ST-002",
                    "output_text": self.video_text,
                }
            )
            writer.writerow(
                {
                    **common,
                    "content_type": "accessibility_transcript",
                    "statement_id": "ST-003",
                    "output_text": self.video_transcript,
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
                "visual_unit_id": "post-1",
                "related_statement_ids": "",
            },
            {
                "statement_id": "ST-004",
                "claim_ids": "SYN-S1",
                "source_locator": "complete-report.md#Findings",
                "deliverable_id": "post",
                "output_path": "post.md",
                "output_location": "alternative text for post-1",
                "statement_type": "accessibility_copy",
                "output_text": self.post_alt,
                "status": "used",
                "context_retained": "same claim and qualifier as visible copy",
                "context_omitted": "none",
                "reason": "Accessible equivalent of the post copy.",
                "visual_unit_id": "post-1",
                "related_statement_ids": "ST-001",
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
                "visual_unit_id": "VF-01",
                "related_statement_ids": "",
            },
            {
                "statement_id": "ST-003",
                "claim_ids": "SYN-S1",
                "source_locator": "complete-report.md#Findings",
                "deliverable_id": "video",
                "output_path": "video.csv",
                "output_location": "VF-01.accessibility_transcript",
                "statement_type": "accessibility_copy",
                "output_text": self.video_transcript,
                "status": "used",
                "context_retained": "same statement and qualifier as on-screen copy",
                "context_omitted": "none",
                "reason": "Accessible frame transcript.",
                "visual_unit_id": "VF-01",
                "related_statement_ids": "ST-002",
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
        video.write_text(text.replace("ST-002", "ST-999"), encoding="utf-8")
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv")],
        )
        self.assertTrue(any("absent from declared deliverables" in error for error in errors))
        self.assertTrue(any("unmapped statement ST-999" in error for error in errors))

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
            "post.md,video.csv",
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
            "post.md,video.csv",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("factual statement ST-001 needs claim_ids", result.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_rejects_missing_frame_transcript(self) -> None:
        video = self.root / "video.csv"
        with video.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows = [row for row in rows if row["content_type"] != "accessibility_transcript"]
        with video.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        result = subprocess.run(
            [
                shutil.which("pwsh"),
                "-NoProfile",
                "-File",
                str(POWERSHELL_VALIDATOR_PATH),
                "-ArtifactsRoot",
                str(self.root),
                "-Mapping",
                str(self.mapping),
                "-Deliverables",
                "post.md,video.csv",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("exactly one accessibility_transcript", result.stdout)

    def test_rejects_visual_unit_without_accessibility_mapping(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows = [row for row in rows if row["statement_id"] != "ST-004"]
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("no accessibility_copy mapping row" in error for error in errors))

    def test_rejects_frame_with_no_accessibility_transcript(self) -> None:
        video = self.root / "video.csv"
        with video.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows = [row for row in rows if row["content_type"] != "accessibility_transcript"]
        with video.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("exactly one accessibility_transcript" in error for error in errors))

    def test_rejects_frame_with_missing_or_unknown_content_type(self) -> None:
        video = self.root / "video.csv"
        with video.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["content_type"] = "some_text"
        with video.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("unsupported frame content_type" in error for error in errors))

    def test_rejects_source_metadata_with_unrelated_claim_ids(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["statement_type"] = "source_metadata"
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("source metadata must not be assigned unrelated claim_ids" in error for error in errors))

    def test_rejects_accessibility_mapping_that_omits_visual_statement(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        next(row for row in rows if row["statement_id"] == "ST-003")["related_statement_ids"] = ""
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("must reference every visual statement_id exactly" in error for error in errors))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_rejects_accessibility_relation_that_omits_statement(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        next(row for row in rows if row["statement_id"] == "ST-003")["related_statement_ids"] = ""
        self.write_mapping(rows)
        result = subprocess.run(
            [
                shutil.which("pwsh"),
                "-NoProfile",
                "-File",
                str(POWERSHELL_VALIDATOR_PATH),
                "-ArtifactsRoot",
                str(self.root),
                "-Mapping",
                str(self.mapping),
                "-Deliverables",
                "post.md,video.csv",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("must reference every visual statement_id exactly", result.stdout)

    def test_omitted_recommendation_can_use_exact_source_locator_without_claim_id(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows.append(
            {
                "statement_id": "",
                "claim_ids": "",
                "source_locator": "complete-report.md#Recommendation / stop rule",
                "deliverable_id": "post",
                "output_path": "",
                "output_location": "",
                "statement_type": "recommendation",
                "output_text": "",
                "status": "omitted",
                "context_retained": "none",
                "context_omitted": "stop rule is not reproduced in this short post",
                "reason": "Keep the limited channel space focused on the main pilot recommendation.",
                "visual_unit_id": "",
                "related_statement_ids": "",
            }
        )
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
