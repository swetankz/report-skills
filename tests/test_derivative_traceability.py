from __future__ import annotations

import csv
import hashlib
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
            "-StructuralOnly",
            "-ArtifactsRoot",
            str(self.root),
            "-Mapping",
            str(self.mapping),
            "-Deliverables",
            "post.md,video.csv",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Structural checks passed", result.stdout)

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
            "-StructuralOnly",
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
                "-StructuralOnly",
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

    def test_rejects_used_mapping_row_with_blank_context_disposition(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["context_omitted"] = ""
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("needs explicit context_retained and context_omitted" in error for error in errors))

    def test_rejects_accessibility_mapping_that_omits_visual_statement(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        next(row for row in rows if row["statement_id"] == "ST-003")["related_statement_ids"] = ""
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("must reference every visual statement_id exactly" in error for error in errors))

    def test_accessibility_copy_inherits_claim_ids_from_related_visual_copy(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        next(row for row in rows if row["statement_id"] == "ST-003")["claim_ids"] = ""
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("must carry all related claim_ids: SYN-S1" in error for error in errors))

    def test_rejects_accessibility_copy_that_drops_visual_qualifier(self) -> None:
        shortened = "A synthetic survey found willingness."
        post = self.root / "post.md"
        post.write_text(post.read_text(encoding="utf-8").replace(self.post_alt, shortened), encoding="utf-8")
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        next(row for row in rows if row["statement_id"] == "ST-004")["output_text"] = shortened
        self.write_mapping(rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, [Path("post.md"), Path("video.csv")])
        self.assertTrue(any("must preserve statement ST-001 verbatim" in error for error in errors))

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
                "-StructuralOnly",
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

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_rejects_accessibility_copy_without_related_claim_id(self) -> None:
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        next(row for row in rows if row["statement_id"] == "ST-003")["claim_ids"] = ""
        self.write_mapping(rows)
        result = subprocess.run(
            [
                shutil.which("pwsh"),
                "-NoProfile",
                "-File",
                str(POWERSHELL_VALIDATOR_PATH),
                "-StructuralOnly",
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
        self.assertIn("must carry related claim_id SYN-S1", result.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_rejects_accessibility_copy_that_drops_visual_qualifier(self) -> None:
        shortened = "A synthetic survey found willingness."
        post = self.root / "post.md"
        post.write_text(post.read_text(encoding="utf-8").replace(self.post_alt, shortened), encoding="utf-8")
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        next(row for row in rows if row["statement_id"] == "ST-004")["output_text"] = shortened
        self.write_mapping(rows)
        result = subprocess.run(
            [
                shutil.which("pwsh"),
                "-NoProfile",
                "-File",
                str(POWERSHELL_VALIDATOR_PATH),
                "-StructuralOnly",
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
        self.assertIn("must preserve statement ST-001 verbatim", result.stdout)

    def test_validator_requires_matching_report_hash_across_package_files(self) -> None:
        source_report = self.root.parent / "complete-report.md"
        source_report.write_text("Synthetic approved report source.\n", encoding="utf-8")
        source_hash = f"sha256:{hashlib.sha256(source_report.read_bytes()).hexdigest()}"
        manifest = self.root / "hash-manifest.yaml"
        manifest.write_text(
            "source_report:\n"
            "  artifact_id: synthetic-report\n"
            "  version: '1.0'\n"
            f"  hash: '{source_hash}'\n"
            "manifest_note:\n"
            "  statement_id: ST-005\n"
            '  text: "Hash provenance note."\n',
            encoding="utf-8",
        )
        with (self.root / "post.md").open("r+", encoding="utf-8") as handle:
            text = handle.read().replace("parent_report_hash: unknown", f'parent_report_hash: "{source_hash}"')
            handle.seek(0)
            handle.write(text)
            handle.truncate()
        with (self.root / "video.csv").open("r", encoding="utf-8", newline="") as handle:
            video_rows = list(csv.DictReader(handle))
        for row in video_rows:
            row["parent_report_hash"] = source_hash
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(video_rows)
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            mapping_rows = list(csv.DictReader(handle))
        mapping_rows.append(
            {
                "statement_id": "ST-005",
                "claim_ids": "",
                "source_locator": "hash-manifest.yaml#source_report.hash",
                "deliverable_id": "manifest",
                "output_path": "hash-manifest.yaml",
                "output_location": "manifest_note.text",
                "statement_type": "source_metadata",
                "output_text": "Hash provenance note.",
                "status": "used",
                "context_retained": "exact immutable source hash",
                "context_omitted": "none",
                "reason": "Private provenance note.",
                "visual_unit_id": "",
                "related_statement_ids": "",
            }
        )
        self.write_mapping(mapping_rows)
        deliverables = [Path("post.md"), Path("video.csv"), Path("hash-manifest.yaml")]
        self.assertEqual([], VALIDATOR.validate_package(self.root, self.mapping, deliverables, source_report))

        video_rows[0]["parent_report_hash"] = "unknown"
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(video_rows)
        errors = VALIDATOR.validate_package(self.root, self.mapping, deliverables, source_report)
        self.assertTrue(any("does not match manifest source hash" in error for error in errors))

        for row in video_rows:
            row["parent_report_hash"] = source_hash
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(video_rows)
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(source_hash, "unknown"), encoding="utf-8")
        errors = VALIDATOR.validate_package(self.root, self.mapping, deliverables, source_report)
        self.assertTrue(any("manifest source hash 'unknown' does not match source report bytes" in error for error in errors))

    def test_non_copy_manifest_can_be_declared_for_hash_reconciliation(self) -> None:
        manifest = self.root / "derivative-manifest.yaml"
        manifest.write_text(
            "source_report:\n"
            "  artifact_id: synthetic-report\n"
            "  version: '1.0'\n"
            "  hash: unknown\n",
            encoding="utf-8",
        )
        deliverables = [Path("post.md"), Path("video.csv"), Path("derivative-manifest.yaml")]
        errors = VALIDATOR.validate_package(self.root, self.mapping, deliverables)
        self.assertEqual([], errors)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_allows_non_copy_manifest_for_hash_reconciliation(self) -> None:
        manifest = self.root / "derivative-manifest.yaml"
        manifest.write_text(
            "source_report:\n"
            "  artifact_id: synthetic-report\n"
            "  version: '1.0'\n"
            "  hash: unknown\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                shutil.which("pwsh"),
                "-NoProfile",
                "-File",
                str(POWERSHELL_VALIDATOR_PATH),
                "-StructuralOnly",
                "-ArtifactsRoot",
                str(self.root),
                "-Mapping",
                str(self.mapping),
                "-Deliverables",
                "post.md,video.csv,derivative-manifest.yaml",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_validator_requires_exact_report_title_as_visible_copy_in_each_format(self) -> None:
        source_report = self.root.parent / "complete-report.md"
        source_report.write_text("# Exact Approved Report Title\n\nSynthetic source.\n", encoding="utf-8")
        source_hash = f"sha256:{hashlib.sha256(source_report.read_bytes()).hexdigest()}"
        post = self.root / "post.md"
        post.write_text(post.read_text(encoding="utf-8").replace("parent_report_hash: unknown", f'parent_report_hash: "{source_hash}"'), encoding="utf-8")
        post.write_text(post.read_text(encoding="utf-8").replace(self.post_alt, "Exact Approved Report Title"), encoding="utf-8")
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            mapping_rows = list(csv.DictReader(handle))
        next(row for row in mapping_rows if row["statement_id"] == "ST-004")["output_text"] = "Exact Approved Report Title"
        self.write_mapping(mapping_rows)
        with (self.root / "video.csv").open("r", encoding="utf-8", newline="") as handle:
            video_rows = list(csv.DictReader(handle))
        for row in video_rows:
            row["parent_report_hash"] = source_hash
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(video_rows)
        (self.root / "derivative-manifest.yaml").write_text(
            "source_report:\n"
            "  artifact_id: synthetic-report\n"
            f"  hash: '{source_hash}'\n"
            "deliverables:\n"
            "  - deliverable_id: post\n"
            "    role: requested-format\n"
            "  - deliverable_id: video\n"
            "    role: requested-format\n"
            "  - deliverable_id: checklist\n"
            "    role: supporting-artifact\n",
            encoding="utf-8",
        )
        errors = VALIDATOR.validate_package(
            self.root,
            self.mapping,
            [Path("post.md"), Path("video.csv"), Path("derivative-manifest.yaml")],
            source_report,
        )
        self.assertTrue(any("deliverable post must include the exact approved report title" in error for error in errors))
        self.assertTrue(any("deliverable video must include the exact approved report title" in error for error in errors))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_requires_exact_report_title_as_visible_copy(self) -> None:
        source_report = self.root.parent / "complete-report.md"
        source_report.write_text("# Exact Approved Report Title\n\nSynthetic source.\n", encoding="utf-8")
        source_hash = f"sha256:{hashlib.sha256(source_report.read_bytes()).hexdigest()}"
        post = self.root / "post.md"
        post.write_text(post.read_text(encoding="utf-8").replace("parent_report_hash: unknown", f'parent_report_hash: "{source_hash}"'), encoding="utf-8")
        post.write_text(post.read_text(encoding="utf-8").replace(self.post_alt, "Exact Approved Report Title"), encoding="utf-8")
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            mapping_rows = list(csv.DictReader(handle))
        next(row for row in mapping_rows if row["statement_id"] == "ST-004")["output_text"] = "Exact Approved Report Title"
        self.write_mapping(mapping_rows)
        with (self.root / "video.csv").open("r", encoding="utf-8", newline="") as handle:
            video_rows = list(csv.DictReader(handle))
        for row in video_rows:
            row["parent_report_hash"] = source_hash
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(video_rows)
        (self.root / "derivative-manifest.yaml").write_text(
            "source_report:\n"
            "  artifact_id: synthetic-report\n"
            f"  hash: '{source_hash}'\n"
            "deliverables:\n"
            "  - deliverable_id: post\n"
            "    role: requested-format\n"
            "  - deliverable_id: video\n"
            "    role: requested-format\n"
            "  - deliverable_id: checklist\n"
            "    role: supporting-artifact\n",
            encoding="utf-8",
        )
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
                "post.md,video.csv,derivative-manifest.yaml",
                "-SourceReport",
                str(source_report),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("deliverable post must include the exact approved report title", result.stdout)
        self.assertIn("deliverable video must include the exact approved report title", result.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is not installed")
    def test_powershell_validator_rejects_report_hash_drift(self) -> None:
        source_report = self.root.parent / "complete-report.md"
        source_report.write_text("Synthetic approved report source.\n", encoding="utf-8")
        source_hash = f"sha256:{hashlib.sha256(source_report.read_bytes()).hexdigest()}"
        manifest = self.root / "hash-manifest.yaml"
        manifest.write_text(
            "source_report:\n"
            "  artifact_id: synthetic-report\n"
            "  version: '1.0'\n"
            f"  hash: '{source_hash}'\n"
            "manifest_note:\n"
            "  statement_id: ST-005\n"
            '  text: "Hash provenance note."\n',
            encoding="utf-8",
        )
        with (self.root / "post.md").open("r+", encoding="utf-8") as handle:
            text = handle.read().replace("parent_report_hash: unknown", f'parent_report_hash: "{source_hash}"')
            handle.seek(0)
            handle.write(text)
            handle.truncate()
        with (self.root / "video.csv").open("r", encoding="utf-8", newline="") as handle:
            video_rows = list(csv.DictReader(handle))
        for row in video_rows:
            row["parent_report_hash"] = source_hash
        video_rows[0]["parent_report_hash"] = "unknown"
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(video_rows)
        with self.mapping.open("r", encoding="utf-8", newline="") as handle:
            mapping_rows = list(csv.DictReader(handle))
        mapping_rows.append(
            {
                "statement_id": "ST-005",
                "claim_ids": "",
                "source_locator": "hash-manifest.yaml#source_report.hash",
                "deliverable_id": "manifest",
                "output_path": "hash-manifest.yaml",
                "output_location": "manifest_note.text",
                "statement_type": "source_metadata",
                "output_text": "Hash provenance note.",
                "status": "used",
                "context_retained": "exact immutable source hash",
                "context_omitted": "none",
                "reason": "Private provenance note.",
                "visual_unit_id": "",
                "related_statement_ids": "",
            }
        )
        self.write_mapping(mapping_rows)
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
                "post.md,video.csv,hash-manifest.yaml",
                "-SourceReport",
                str(source_report),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("does not match manifest source hash", result.stdout)

        for row in video_rows:
            row["parent_report_hash"] = source_hash
        with (self.root / "video.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=VIDEO_FIELDS)
            writer.writeheader()
            writer.writerows(video_rows)
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(source_hash, "unknown"), encoding="utf-8")
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
                "post.md,video.csv,hash-manifest.yaml",
                "-SourceReport",
                str(source_report),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("manifest source hash 'unknown' does not match source report bytes", result.stdout)

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
                "output_location": "recommendation coverage inventory",
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

    def test_omitted_coverage_requires_deliverable_and_inventory_location(self) -> None:
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
        self.assertTrue(any("needs its deliverable_id and omitted output_location" in error for error in errors))

        if shutil.which("pwsh"):
            result = subprocess.run(
                [
                    shutil.which("pwsh"),
                    "-NoProfile",
                    "-File",
                    str(POWERSHELL_VALIDATOR_PATH),
                    "-StructuralOnly",
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
            self.assertIn("needs its deliverable_id and omitted output_location", result.stdout)


if __name__ == "__main__":
    unittest.main()
