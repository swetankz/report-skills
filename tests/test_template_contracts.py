from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def top_level_template_values(name: str) -> dict[str, object]:
    """Read the JSON-valued top-level entries in our small YAML templates."""
    values = {}
    for line in (REPO_ROOT / "templates" / name).read_text(encoding="utf-8").splitlines():
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if separator and value.strip():
            if key in values:
                raise AssertionError(f"Duplicate top-level key: {key}")
            values[key] = json.loads(value.strip())
    return values


def markdown_tables(name: str) -> list[tuple[list[str], list[dict[str, str]]]]:
    tables = []
    block = []
    text = (REPO_ROOT / "templates" / name).read_text(encoding="utf-8")
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            block.append([cell.strip() for cell in line.strip("|").split("|")])
            continue
        if block:
            header, separator, *rows = block
            if len(header) != len(set(header)) or len(separator) != len(header):
                raise AssertionError("Invalid table header")
            if any(not cell or set(cell) - set("-:") for cell in separator):
                raise AssertionError("Invalid table separator")
            if any(len(row) != len(header) for row in rows):
                raise AssertionError("Invalid table row width")
            tables.append((header, [dict(zip(header, row)) for row in rows]))
            block = []
    return tables


class TemplateContractTests(unittest.TestCase):
    def assert_provenance_row(self, row: dict[str, object]) -> None:
        required = {
            "artifact_id", "classification", "status", "creation_status",
            "relationship_status", "parent_ids", "model", "projection_eligibility",
        }
        self.assertTrue(required <= row.keys())
        for field in required - {"parent_ids", "projection_eligibility"}:
            self.assertIsInstance(row[field], str)
            self.assertTrue(row[field])
        self.assertIsInstance(row["parent_ids"], list)
        self.assertIn(row["relationship_status"], {
            "root", "parent-established", "unresolved-parent", "contested", "not-applicable",
        })
        projection = row["projection_eligibility"]
        self.assertIsInstance(projection, dict)
        self.assertIn(projection["status"], {"include", "exclude", "redact"})
        self.assertTrue(projection["reason"].strip())
        self.assertIn("unknown_fields", row)
        if row["relationship_status"] == "root":
            self.assertEqual(row["parent_ids"], [])
            self.assertTrue(row["evidence"])

    def test_private_provenance_template_has_complete_row_and_safe_projection_state(self) -> None:
        document = json.loads((REPO_ROOT / "templates/provenance-manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(document["public_projection_created"])
        for row in document["artifacts"]:
            self.assert_provenance_row(row)
            self.assertEqual(row["visibility"], "private")
            self.assertEqual(row["projection_eligibility"]["status"], "redact")

    def test_private_provenance_reference_example_obeys_the_same_contract(self) -> None:
        reference = REPO_ROOT / "source/skills/creative-artifact-provenance/references/provenance-schema.md"
        example = reference.read_text(encoding="utf-8").split("```json\n", 1)[1].split("```", 1)[0]
        self.assert_provenance_row(json.loads(example))

    def test_visual_qa_template_covers_every_pass_without_invented_observations(self) -> None:
        coverage, findings = markdown_tables("visual-qa-report.md")
        self.assertEqual({row["pass"] for row in coverage[1]}, {"structural", "optical", "reader-comprehension"})
        self.assertEqual(len(coverage[1]), 3)
        for row in coverage[1]:
            self.assertEqual(row["result"], "not verified")
            self.assertEqual(row["finding IDs"], "none")
            self.assertEqual(row["evidence type/reference"], "none")
        self.assertEqual(findings[1], [])
        self.assertTrue({"severity", "impact", "viewport or format", "evidence and evidence type", "recommended correction", "verification status"} <= set(findings[0]))

    def test_publication_template_keeps_component_coverage_separate_from_section_map(self) -> None:
        document = top_level_template_values("publication-spec.yaml")
        self.assertEqual(document["components"], [])
        self.assertEqual(document["section_map"], [])
        self.assertEqual(document["component_content_map"], [])
        self.assertEqual(document["status"], "working")

    def test_pencil_template_exposes_blocker_handoff_without_claiming_live_state(self) -> None:
        document = top_level_template_values("pencil-edit-record.yaml")
        self.assertEqual(document["observed_state"], "not-verified")
        self.assertEqual(document["requested_state"], "not-verified")
        self.assertTrue(document["blocker_state"])
        self.assertTrue(document["proposed_next_step"])
        self.assertFalse(document["active_file_confirmed"])
        self.assertFalse(document["connectivity_confirmed"])
        self.assertEqual(document["applied_changes"], [])
        self.assertIsNone(document["backup_hash"])
        self.assertIsNone(document["final_hash"])
        self.assertEqual(document["status"], "blocked")

    def test_motion_template_has_unobserved_acceptance_checks_and_separate_findings(self) -> None:
        reduced_motion, measured, findings = markdown_tables("motion-qa-report.md")
        self.assertEqual({row["check"] for row in reduced_motion[1]}, {
            "content visibility", "keyboard/focus and navigation", "loader dismissal",
            "anchored content", "nonessential movement",
        })
        for row in reduced_motion[1]:
            self.assertTrue(row["procedure"])
            self.assertTrue(row["acceptance criterion"])
            self.assertEqual(row["result"], "not verified")
            self.assertEqual(row["evidence"], "none")
        self.assertEqual(measured[1], [])
        self.assertTrue({"environment/build", "evidence reference", "acceptance criterion", "result"} <= set(measured[0]))
        self.assertEqual(findings[1], [])
        self.assertTrue({"observation", "evidence", "diagnosis", "proposed_correction", "verification_status"} <= set(findings[0]))


if __name__ == "__main__":
    unittest.main()
