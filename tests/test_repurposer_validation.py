from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
SCRIPT = REPO / "source/skills/report-content-repurposer/scripts/validate_derivative_package.py"
PS_SCRIPT = SCRIPT.with_suffix(".ps1")
SPEC = importlib.util.spec_from_file_location("repurposer_source_contract", SCRIPT)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(VALIDATOR)


class RepurposerSourceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "artifacts"
        self.root.mkdir()
        self.source = self.root.parent / "source.md"
        self.source.write_text(
            "# Synthetic service trial\n\n## Findings\n"
            "A synthetic survey included 40 respondents (`SYN-A`).\n"
            "Booking completion remains uncertain (`SYN-B`).\n\n"
            "## Recommendation\nKeep a human booking path.\n"
            "Measure abandonment.\nStop for harmful disparities.\n",
            encoding="utf-8",
        )
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.mapping = self.root / "claim-mapping.csv"
        self.inventory_path = self.root / "source-inventory.json"
        self.support_path = self.root / "statement-support.csv"
        self.manifest_path = self.root / "derivative-manifest.yaml"
        self.deliverables = [Path("post.md"), Path("derivative-manifest.yaml")]
        self.units = [
            self.unit("SU-title", "source_metadata", 1, "Synthetic service trial", []),
            self.unit("SU-fact", "sourced_fact", 4, "A synthetic survey included 40 respondents (`SYN-A`).", ["SYN-A"]),
            self.unit("SU-analysis", "analysis", 5, "Booking completion remains uncertain (`SYN-B`).", ["SYN-B"]),
            self.unit("SU-human", "safeguard", 8, "Keep a human booking path.", []),
            self.unit("SU-measure", "measurement", 9, "Measure abandonment.", []),
            self.unit("SU-stop", "stop_rule", 10, "Stop for harmful disparities.", []),
        ]
        self.copy = {
            "TITLE": "# Synthetic service trial",
            "BODY": "A synthetic survey included 40 respondents. Booking completion remains uncertain.",
            "REC": "Keep a human booking path.",
            "ALT": "Synthetic service trial. A synthetic survey included 40 respondents. Booking completion remains uncertain. Keep a human booking path.",
        }
        self.rows = []
        for statement_id, kind, claims, locator in [
            ("TITLE", "source_metadata", "", "line:1"),
            ("BODY", "analysis", "SYN-A;SYN-B", "line:4;line:5"),
            ("REC", "recommendation", "", "line:8"),
            ("ALT", "accessibility_copy", "SYN-A;SYN-B", "line:1;line:4;line:5;line:8"),
        ]:
            self.rows.append({
                "statement_id": statement_id, "claim_ids": claims, "source_locator": locator,
                "deliverable_id": "post", "output_path": "post.md", "output_location": statement_id,
                "statement_type": kind, "output_text": self.copy[statement_id], "status": "used",
                "context_retained": "source context", "context_omitted": "none", "reason": "reviewed local draft",
                "visual_unit_id": "POST", "related_statement_ids": "TITLE;BODY;REC" if statement_id == "ALT" else "",
            })
        self.support = []
        for statement_id, source_id, text in [
            ("TITLE", "SU-title", "Synthetic service trial"),
            ("BODY", "SU-fact", "A synthetic survey included 40 respondents."),
            ("BODY", "SU-analysis", "Booking completion remains uncertain."),
            ("REC", "SU-human", "Keep a human booking path."),
            ("ALT", "SU-title", "Synthetic service trial"),
            ("ALT", "SU-fact", "A synthetic survey included 40 respondents."),
            ("ALT", "SU-analysis", "Booking completion remains uncertain."),
            ("ALT", "SU-human", "Keep a human booking path."),
        ]:
            unit = next(unit for unit in self.units if unit["source_unit_id"] == source_id)
            self.support.append({
                "support_id": f"SUP-{len(self.support) + 1}", "statement_id": statement_id,
                "source_unit_id": source_id, "output_text": text, "output_occurrence": "1",
                "claim_ids": ";".join(unit["claim_ids"]), "source_locator": unit["source_locator"],
                "kind": unit["kind"], "metadata_field": unit.get("metadata_field", ""), "reason": "exact source unit reviewed",
            })
        self.inventory = {
            "schema_version": "1.0", "source_report_hash": self.source_hash,
            "review": {"status": "complete", "method": "manual-clause-review", "checks": ["atomic-units", "source-types", "semantic-support", "material-omissions"]},
            "source_units": self.units, "coverage": [],
        }
        for unit in self.units:
            statement_ids = sorted({child["statement_id"] for child in self.support if child["source_unit_id"] == unit["source_unit_id"]})
            self.inventory["coverage"].append({
                "source_unit_id": unit["source_unit_id"], "deliverable_id": "post",
                "status": "used" if statement_ids else "omitted", "statement_ids": statement_ids,
                "context_omitted": "none" if statement_ids else unit["source_text"],
                "reason": "The local draft links to the complete recommendation; materiality manually reviewed.",
            })
        self.flush()

    @staticmethod
    def unit(unit_id: str, kind: str, line: int, quote: str, claims: list[str]) -> dict:
        result = {"source_unit_id": unit_id, "kind": kind, "source_locator": f"line:{line}", "source_text": quote, "claim_ids": claims}
        if kind == "source_metadata":
            result["metadata_field"] = "report_title"
        return result

    def append_source_units(self, line: str, declarations: list[tuple[str, str, str]], *, claims: list[str] | None = None) -> None:
        """Add complete literal source units and separate visible/accessible occurrences."""
        original = self.source.read_text(encoding="utf-8")
        locator = f"line:{len(original.splitlines()) + 1}"
        self.source.write_text(original + line + "\n", encoding="utf-8")
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.inventory["source_report_hash"] = self.source_hash
        fragments = []
        new_units = []
        for field, kind, quote in declarations:
            unit = {"source_unit_id": f"SU-{field}", "kind": kind, "source_locator": locator, "source_text": quote, "claim_ids": claims or []}
            if kind == "source_metadata":
                unit["metadata_field"] = field
            self.units.append(unit)
            new_units.append(unit)
            fragments.append(quote)
        statement = "META" if not any(row["statement_id"] == "META" for row in self.rows) else f"EXTRA-{len(self.rows)}"
        output = " ".join(fragments)
        joined_claims = ";".join(claims or [])
        self.rows.insert(-1, {**self.rows[2], "statement_id": statement, "statement_type": "source_metadata" if not claims else "sourced_fact", "claim_ids": joined_claims, "source_locator": locator, "output_location": statement, "output_text": output})
        self.rows[-1]["related_statement_ids"] += ";" + statement
        self.rows[-1]["output_text"] += " " + output
        for unit in new_units:
            for parent in [statement, "ALT"]:
                self.support.append({"support_id": f"SUP-{len(self.support) + 1}", "statement_id": parent, "source_unit_id": unit["source_unit_id"], "output_text": unit["source_text"], "output_occurrence": "1", "claim_ids": joined_claims, "source_locator": locator, "kind": unit["kind"], "metadata_field": unit.get("metadata_field", ""), "reason": "literal field/source review"})
            self.inventory["coverage"].append({"source_unit_id": unit["source_unit_id"], "deliverable_id": "post", "status": "used", "statement_ids": ["ALT", statement], "context_omitted": "none", "reason": "literal full reproduction"})
        self.flush()

    def replace_title(self, title: str) -> None:
        old = self.units[0]["source_text"]
        self.source.write_text(self.source.read_text(encoding="utf-8").replace(old, title), encoding="utf-8")
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.inventory["source_report_hash"] = self.source_hash
        self.units[0]["source_text"] = title
        for child in self.support:
            if child["source_unit_id"] == "SU-title":
                child["output_text"] = title
        for row in self.rows:
            row["output_text"] = row["output_text"].replace(old, title)
        self.flush()

    @staticmethod
    def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def flush(self) -> None:
        self.write_csv(self.mapping, self.rows, sorted(VALIDATOR.REQUIRED_COLUMNS))
        self.write_csv(self.support_path, self.support, sorted(VALIDATOR.SUPPORT_COLUMNS))
        self.inventory_path.write_text(json.dumps(self.inventory), encoding="utf-8")
        self.manifest_path.write_text(
            f"source_report:\n  hash: '{self.source_hash}'\nsource_inventory: source-inventory.json\nstatement_support: statement-support.csv\ndeliverables:\n  - deliverable_id: post\n    role: requested-format\n",
            encoding="utf-8",
        )
        header = (
            "---\ndeliverable_id: post\nparent_report_id: trial\nparent_report_version: 1.0\n"
            f"parent_report_hash: '{self.source_hash}'\nsource_claim_ids: [SYN-A, SYN-B]\n"
            "transformation_type: local social copy\ndimensions: 1080x1350 specification\naspect_ratio: 4:5\nstatus: draft\n---\n\n"
        )
        body = "\n\n".join(f"<!-- statement_id: {row['statement_id']} -->\n{row['output_text']}" for row in self.rows)
        (self.root / "post.md").write_text(header + body + "\n", encoding="utf-8")

    def cli(self, powershell: bool, *, source: bool = True, structural: bool = False) -> subprocess.CompletedProcess:
        if powershell:
            command = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(PS_SCRIPT), "-ArtifactsRoot", str(self.root), "-Mapping", str(self.mapping), "-Deliverables", ",".join(path.as_posix() for path in self.deliverables)]
            if source:
                command += ["-SourceReport", str(self.source)]
            if structural:
                command.append("-StructuralOnly")
        else:
            command = [sys.executable, str(SCRIPT), "--artifacts-root", str(self.root), "--mapping", str(self.mapping)]
            for path in self.deliverables:
                command += ["--deliverable", path.as_posix()]
            if source:
                command += ["--source-report", str(self.source)]
            if structural:
                command.append("--structural-only")
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)

    def assert_cli(self, expected: int, fragment: str, **kwargs) -> None:
        for powershell in [False, True] if shutil.which("pwsh") else [False]:
            with self.subTest(powershell=powershell):
                result = self.cli(powershell, **kwargs)
                if expected:
                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                else:
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn(fragment.casefold(), (result.stdout + result.stderr).casefold())
                self.assertNotIn("Traceback", result.stderr)

    def test_full_contract_accepts_compound_accessibility_with_atomic_children(self) -> None:
        self.assert_cli(0, "source-inventory records reconcile")

    def test_report_owned_prose_calendar_fields_need_no_borrowed_ids(self) -> None:
        period = "The reporting period runs from September through November 2042"
        cutoff = "and the evidence cutoff is December 1, 2042."
        self.append_source_units(period + " " + cutoff, [("reporting_period", "source_metadata", period), ("evidence_cutoff", "source_metadata", cutoff)])
        self.assert_cli(0, "source-inventory records reconcile")
        for unit in self.units[-2:]:
            unit["kind"] = "sourced_fact"
            unit["claim_ids"] = ["SYN-A"]
            unit.pop("metadata_field")
        for child in self.support[-4:]:
            child.update(kind="sourced_fact", claim_ids="SYN-A", metadata_field="")
        self.flush()
        self.assert_cli(1, "overlaps report-owned field")

    def test_calendar_adapter_accepts_distinct_date_and_month_range_forms(self) -> None:
        variants = [
            ("reporting_period = 2041-11-09 to 2042-01-05;", "evidence_cutoff: 2042-01-06."),
            ("Reporting period: December 2042 through January 2043.", "Evidence cutoff = January 31, 2043."),
            ("Reporting period is February 28, 2044 through March 1, 2044.", "Evidence cutoff: March 2, 2044."),
            ("Reporting period: May 2044 through June 2044 .", "Evidence cutoff: July 1, 2044 ."),
        ]
        for period, cutoff in variants:
            with self.subTest(period=period):
                self.setUp()
                self.append_source_units(period + " " + cutoff, [("reporting_period", "source_metadata", period), ("evidence_cutoff", "source_metadata", cutoff)])
                self.assert_cli(0, "source-inventory records reconcile")

    def test_metadata_field_enum_is_required_on_source_and_support(self) -> None:
        for field in [None, "scope", ["report_title"], {"name": "report_title"}]:
            with self.subTest(source_field=field):
                self.setUp()
                if field is None:
                    self.units[0].pop("metadata_field")
                else:
                    self.units[0]["metadata_field"] = field
                self.flush()
                self.assert_cli(1, "metadata needs a known metadata_field")
        for field in ["", "scope", "evidence_cutoff"]:
            with self.subTest(child_field=field):
                self.setUp()
                self.support[0]["metadata_field"] = field
                self.flush()
                self.assert_cli(1, "must name its exact metadata_field")

    def test_literal_named_metadata_rejects_borrowed_ids_in_all_bindings(self) -> None:
        cutoff = "Evidence cutoff: 2046-04-09."
        self.append_source_units(cutoff, [("evidence_cutoff", "source_metadata", cutoff)])
        self.assert_cli(0, "source-inventory records reconcile")
        self.units[-1]["claim_ids"] = ["SYN-A"]
        self.flush()
        self.assert_cli(1, "metadata must not carry claim_ids")
        self.units[-1]["claim_ids"] = []
        self.support[-1]["claim_ids"] = "SYN-A"
        self.flush()
        self.assert_cli(1, "must match its exact source unit")
        self.support[-1]["claim_ids"] = ""
        self.rows[-2]["claim_ids"] = "SYN-A"
        self.flush()
        self.assert_cli(1, "claim_ids must equal its atomic support claims")

    def test_findings_cannot_be_relabelled_as_administrative_metadata(self) -> None:
        for quote in [
            "In 2048, a synthetic survey recorded 17 of 50 respondents (`SYN-A`).",
            "Evidence cutoff: 62% of synthetic respondents (`SYN-A`).",
            "Evidence cutoff: May 7, 2048 recorded 17 of 50 respondents (`SYN-A`).",
            "Survey evidence cutoff: 2048-05-07 (`SYN-A`).",
        ]:
            with self.subTest(source=quote):
                self.setUp()
                self.append_source_units(quote, [("evidence_cutoff", "source_metadata", quote)])
                self.assert_cli(1, "complete independently resolved source field")

    def test_unknown_unsupported_invalid_or_ambiguous_declarations_fail_closed(self) -> None:
        for quote in [
            "Data horizon: 2045-06-07.",
            "Evidence cutoff: sometime in June 2045.",
            "Evidence cutoff: February 30, 2045.",
            "Evidence cutoff: 2045-13-01.",
        ]:
            with self.subTest(source=quote):
                self.setUp()
                self.append_source_units(quote, [("evidence_cutoff", "source_metadata", quote)])
                self.assert_cli(1, "complete independently resolved source field")
        self.setUp()
        quote = "Reporting period: October 2044 through September 2044."
        self.append_source_units(quote, [("reporting_period", "source_metadata", quote)])
        self.assert_cli(1, "complete independently resolved source field")
        self.setUp()
        cutoff = "Evidence cutoff: 2045-06-07."
        self.append_source_units(cutoff, [("evidence_cutoff", "source_metadata", cutoff)])
        self.append_source_units("Evidence cutoff: 2045-06-08.", [("second-cutoff", "nonfactual", "Evidence cutoff: 2045-06-08.")])
        self.assert_cli(1, "ambiguous source declarations")
        self.setUp()
        self.append_source_units(cutoff, [("evidence_cutoff", "source_metadata", cutoff)])
        self.append_source_units("Evidence cutoff: someday.", [("invalid-cutoff", "nonfactual", "Evidence cutoff: someday.")])
        self.assert_cli(1, "ambiguous source declarations")

    def test_calendar_field_requires_complete_quote_in_source_child_and_parent(self) -> None:
        cutoff = "Evidence cutoff: 2046-04-09."
        self.append_source_units(cutoff, [("evidence_cutoff", "source_metadata", cutoff)])
        self.units[-1]["source_text"] = "2046-04-09"
        self.flush()
        self.assert_cli(1, "complete independently resolved source field")
        self.units[-1]["source_text"] = cutoff
        self.support[-1]["output_text"] = "2046-04-09"
        self.flush()
        self.assert_cli(1, "must reproduce only its literal source field")
        self.support[-1]["output_text"] = cutoff
        self.rows[-2]["output_text"] = "Evidence cutoff: 2046-04-09"
        self.flush()
        self.assert_cli(1, "must preserve its literal field in canonical output")

    def test_exact_report_title_not_invented_subtitle_or_findings_label(self) -> None:
        for title in ["Synthetic [Neighborhood study](https://example.com/research_a)", "Study note: 17 of 50 synthetic respondents"]:
            with self.subTest(title=title):
                self.setUp()
                self.source.write_text(self.source.read_text(encoding="utf-8").replace("Synthetic service trial", title), encoding="utf-8")
                self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
                self.inventory["source_report_hash"] = self.source_hash
                self.units[0]["source_text"] = title
                for child in self.support:
                    if child["source_unit_id"] == "SU-title":
                        child["output_text"] = title
                for row in self.rows:
                    row["output_text"] = row["output_text"].replace("Synthetic service trial", title)
                self.flush()
                self.assert_cli(0, "source-inventory records reconcile")
                self.units[0]["source_locator"] = "line:4"
                self.units[0]["source_text"] = self.units[1]["source_text"]
                self.flush()
                self.assert_cli(1, "complete independently resolved source field")

    def test_explicitly_cited_external_calendar_dates_keep_valid_fact_ids(self) -> None:
        for quote in ["Evidence cutoff: April 8, 2044 (`SYN-A`).", "Evidence cutoff: April 8, 2044. (`SYN-A`)", "Reporting period: 2043-01-01 to 2043-12-31 [SYN-A].", "Reporting period: May 2043 through June 2043. [SYN-A]", "A survey closed on 2044-04-08 (`SYN-A`)."]:
            with self.subTest(source=quote):
                self.setUp()
                self.append_source_units(quote, [("study-date", "sourced_fact", quote)], claims=["SYN-A"])
                self.rows[-1]["claim_ids"] = "SYN-A;SYN-B"
                self.flush()
                self.assert_cli(0, "source-inventory records reconcile")

    def test_named_metadata_does_not_weaken_existing_hash_locator_or_literal_rules(self) -> None:
        cutoff = "Evidence cutoff: 2046-04-09."
        self.append_source_units(cutoff, [("evidence_cutoff", "source_metadata", cutoff)])
        self.inventory["source_report_hash"] = "sha256:other"
        self.units[-1]["source_locator"] = "line:5"
        self.flush()
        self.assert_cli(1, "hash does not match source report bytes")
        self.assert_cli(1, "complete independently resolved source field")

    def test_known_literal_output_cannot_bypass_binding_as_nonfactual_or_unrelated_fact(self) -> None:
        for kind in ["nonfactual", "sourced_fact"]:
            with self.subTest(kind=kind):
                self.setUp()
                cutoff = "Evidence cutoff: 2046-04-09."
                self.append_source_units(cutoff, [("evidence_cutoff", "source_metadata", cutoff)])
                for child in self.support[-2:]:
                    child.update(kind=kind, metadata_field="", source_unit_id="SU-fact" if kind == "sourced_fact" else "", claim_ids="SYN-A" if kind == "sourced_fact" else "", source_locator="line:4" if kind == "sourced_fact" else "")
                self.rows[-2].update(statement_type=kind, claim_ids="SYN-A" if kind == "sourced_fact" else "", source_locator="line:4" if kind == "sourced_fact" else "")
                self.inventory["coverage"][-1].update(status="omitted", statement_ids=[], context_omitted=cutoff, reason="claimed omission")
                if kind == "sourced_fact":
                    self.inventory["coverage"][1]["statement_ids"].append("META")
                self.flush()
                self.assert_cli(1, "needs its metadata_field-bound or exact cited source-unit support")

    def test_every_known_literal_occurrence_needs_its_own_actual_provenance(self) -> None:
        cutoff = "Evidence cutoff: 2046-04-09."
        self.append_source_units(cutoff, [("evidence_cutoff", "source_metadata", cutoff)])
        self.rows[-2]["statement_type"] = "nonfactual"
        for parent in ["META", "ALT"]:
            row = next(row for row in self.rows if row["statement_id"] == parent)
            row["output_text"] += " " + cutoff
            self.support.append({"support_id": f"SUP-unlinked-{parent}", "statement_id": parent, "source_unit_id": "", "output_text": cutoff, "output_occurrence": "2", "claim_ids": "", "source_locator": "", "kind": "nonfactual", "metadata_field": "", "reason": "unlinked literal field"})
        self.flush()
        self.assert_cli(1, "needs its metadata_field-bound or exact cited source-unit support")

    def test_common_title_word_keeps_genuine_longer_fact_provenance_and_word_boundaries(self) -> None:
        for title in ["Pilot", "Report"]:
            with self.subTest(title=title):
                self.setUp()
                self.replace_title(title)
                old = self.units[1]["source_text"]
                new = old.replace("synthetic survey", f"synthetic {title} survey")
                self.source.write_text(self.source.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
                self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
                self.inventory["source_report_hash"] = self.source_hash
                self.units[1]["source_text"] = new
                for child in self.support:
                    if child["source_unit_id"] == "SU-fact":
                        child["output_text"] = child["output_text"].replace("synthetic survey", f"synthetic {title} survey")
                for row in self.rows:
                    row["output_text"] = row["output_text"].replace("synthetic survey", f"synthetic {title} survey")
                note = f"Case{title} design note."
                self.rows.insert(-1, {**self.rows[2], "statement_id": "NOTE", "statement_type": "nonfactual", "claim_ids": "", "source_locator": "", "output_location": "NOTE", "output_text": note})
                self.rows[-1]["related_statement_ids"] += ";NOTE"
                self.rows[-1]["output_text"] += " " + note
                for parent in ["NOTE", "ALT"]:
                    self.support.append({"support_id": f"SUP-note-{parent}", "statement_id": parent, "source_unit_id": "", "output_text": note, "output_occurrence": "1", "claim_ids": "", "source_locator": "", "kind": "nonfactual", "metadata_field": "", "reason": "descriptive design note"})
                self.flush()
                self.assert_cli(0, "source-inventory records reconcile")

    def test_identical_calendar_literal_has_valid_alternative_cited_provenance(self) -> None:
        for field, quote in [("evidence_cutoff", "Evidence cutoff: 2046-04-09."), ("reporting_period", "Reporting period: February 2046 through March 2046.")]:
            with self.subTest(field=field):
                self.setUp()
                self.append_source_units(quote, [(field, "source_metadata", quote)])
                external = quote + " (`SYN-A`)"
                self.append_source_units(external, [("external-date", "sourced_fact", external)], claims=["SYN-A"])
                self.assert_cli(0, "source-inventory records reconcile")

    def test_alternative_literal_support_preserves_child_link_target(self) -> None:
        title = "Synthetic [Neighborhood study](https://example.com/research_a)"
        self.replace_title(title)
        external = title + " is the cited synthetic study (`SYN-A`)."
        self.append_source_units(external, [("external-title", "sourced_fact", external)], claims=["SYN-A"])
        self.assert_cli(0, "source-inventory records reconcile")
        for child in self.support[-2:]:
            child["output_text"] = child["output_text"].replace("/research_a", "/wrong")
        self.flush()
        self.assert_cli(1, "needs its metadata_field-bound or exact cited source-unit support")

    def test_full_cli_requires_source_and_inventory(self) -> None:
        self.assert_cli(1, "required for handoff validation", source=False)
        self.inventory_path.unlink()
        self.assert_cli(1, "required source inventory and statement support cannot be read")

    def test_structural_mode_is_explicit_and_cannot_claim_handoff_pass(self) -> None:
        self.assert_cli(0, "not a handoff pass", source=False, structural=True)
        self.assert_cli(1, "mutually exclusive", source=True, structural=True)

    def test_recommendation_inventory_cannot_drop_measurement_or_stop_rule(self) -> None:
        self.inventory["source_units"] = self.units[:-2]
        self.inventory["coverage"] = self.inventory["coverage"][:-2]
        self.flush()
        self.assert_cli(1, "source line 9 has text missing")
        for result in [self.cli(False)] + ([self.cli(True)] if shutil.which("pwsh") else []):
            self.assertIn("Stop for harmful disparities", result.stdout)

    def test_every_source_unit_needs_each_format_disposition(self) -> None:
        self.inventory["coverage"] = self.inventory["coverage"][:-1]
        self.flush()
        self.assert_cli(1, "SU-stop has no retained/shortened/omitted coverage for post")

    def test_source_quote_hash_and_identifiers_are_bound(self) -> None:
        self.units[1]["claim_ids"] = ["SYN-INVENTED"]
        self.inventory["source_report_hash"] = "sha256:wrong"
        self.flush()
        self.assert_cli(1, "does not occur verbatim in source")

    def test_child_locator_and_accessibility_ids_cannot_borrow_evidence(self) -> None:
        self.support[5]["source_locator"] = "line:5"
        self.support[5]["claim_ids"] = "SYN-B"
        self.flush()
        self.assert_cli(1, "must match its exact source unit")

    def test_duplicate_related_statement_ids_fail(self) -> None:
        self.rows[-1]["related_statement_ids"] += ";BODY"
        self.flush()
        self.assert_cli(1, "duplicate related_statement_ids")

    def test_repeated_clause_needs_its_own_bound_child(self) -> None:
        original_body = self.rows[1]["output_text"]
        self.rows[1]["output_text"] += " Booking completion remains uncertain."
        self.rows[-1]["output_text"] = self.rows[-1]["output_text"].replace(original_body, self.rows[1]["output_text"])
        self.flush()
        self.assert_cli(1, "copy without atomic support records")
        for parent in ["BODY", "ALT"]:
            child = copy.deepcopy(next(child for child in self.support if child["statement_id"] == parent and child["source_unit_id"] == "SU-analysis"))
            child["support_id"] = f"SUP-repeat-{parent}"
            child["output_occurrence"] = "2"
            self.support.append(child)
        self.flush()
        self.assert_cli(0, "source-inventory records reconcile")

    def test_metadata_cannot_gain_interpretive_copy(self) -> None:
        self.support[0]["output_text"] += " shows a successful service"
        self.rows[0]["output_text"] += " shows a successful service"
        self.rows[-1]["output_text"] += " shows a successful service"
        self.flush()
        self.assert_cli(1, "must reproduce only its literal source field")

    def test_metadata_link_targets_preserved_in_both_bindings(self) -> None:
        source_title = "Synthetic [service_trial](https://example.com/official)"
        self.source.write_text(self.source.read_text(encoding="utf-8").replace("Synthetic service trial", source_title), encoding="utf-8")
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.inventory["source_report_hash"] = self.source_hash
        self.units[0]["source_text"] = source_title
        for child in self.support:
            if child["source_unit_id"] == "SU-title":
                child["output_text"] = source_title
        for row in self.rows:
            row["output_text"] = row["output_text"].replace("Synthetic service trial", source_title)
        self.flush()
        self.assert_cli(0, "source-inventory records reconcile")
        self.rows[0]["output_text"] = self.rows[0]["output_text"].replace("/official", "/wrong")
        self.flush()
        self.assert_cli(1, "must preserve its literal field in canonical output")

    def test_duplicate_manifest_identity_cannot_downgrade_format(self) -> None:
        self.manifest_path.write_text(self.manifest_path.read_text(encoding="utf-8") + "  - deliverable_id: post\n    role: supporting-artifact\n", encoding="utf-8")
        self.assert_cli(1, "duplicate deliverable_id")

    def test_copy_header_identity_must_match_manifest_mapping(self) -> None:
        post = self.root / "post.md"
        post.write_text(post.read_text(encoding="utf-8").replace("deliverable_id: post", "deliverable_id: other"), encoding="utf-8")
        self.assert_cli(1, "disagrees with its file header")

    def test_support_headers_records_and_width_are_strict(self) -> None:
        original = self.support_path.read_text(encoding="utf-8")
        for header in ["claim_ids", "CLAIM_IDS", ""]:
            with self.subTest(header=header):
                lines = original.splitlines()
                lines[0] += "," + header
                for index in range(1, len(lines)):
                    lines[index] += ",SYN-INVENTED"
                self.support_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                self.assert_cli(1, "statement support CSV")
        self.support_path.write_text(original + "\n", encoding="utf-8")
        self.assert_cli(1, "statement support")
        self.support_path.write_text(original + "incomplete,row\n", encoding="utf-8")
        self.assert_cli(1, "wrong field count")

    def test_manifest_review_record_pointers_bind_validated_files(self) -> None:
        original = self.manifest_path.read_text(encoding="utf-8")
        for field, path in [("source_inventory", "source-inventory.json"), ("statement_support", "statement-support.csv")]:
            with self.subTest(field=field):
                self.manifest_path.write_text(original.replace(f"{field}: {path}", f"{field}: nonexistent.json"), encoding="utf-8")
                self.assert_cli(1, f"{field} must name the exact validated relative path")

    def test_source_format_keys_do_not_collide_on_delimiters(self) -> None:
        self.units[-2]["source_unit_id"] = "A"
        self.units[-1]["source_unit_id"] = "A::B"
        self.inventory["coverage"][-2]["source_unit_id"] = "A"
        self.inventory["coverage"][-1]["source_unit_id"] = "A::B"
        for row in self.rows:
            row["deliverable_id"] = "C"
        second_rows = copy.deepcopy(self.rows)
        for row in second_rows:
            row["statement_id"] += "-second"
            row["deliverable_id"] = "B::C"
            row["output_path"] = "second.md"
            if row["related_statement_ids"]:
                row["related_statement_ids"] = ";".join(value + "-second" for value in row["related_statement_ids"].split(";"))
        original_support = copy.deepcopy(self.support)
        for child in original_support:
            child["support_id"] += "-second"
            child["statement_id"] += "-second"
        self.support.extend(original_support)
        second_coverage = copy.deepcopy(self.inventory["coverage"])
        for item in self.inventory["coverage"]:
            item["deliverable_id"] = "C"
        for item in second_coverage:
            item["deliverable_id"] = "B::C"
            item["statement_ids"] = [value + "-second" for value in item["statement_ids"]]
        self.inventory["coverage"].extend(second_coverage)
        self.flush()
        first = (self.root / "post.md").read_text(encoding="utf-8")
        (self.root / "post.md").write_text(first.replace("deliverable_id: post", "deliverable_id: C"), encoding="utf-8")
        second = first.replace("deliverable_id: post", "deliverable_id: B::C")
        for row in self.rows:
            second = second.replace(f"statement_id: {row['statement_id']} -->", f"statement_id: {row['statement_id']}-second -->")
        (self.root / "second.md").write_text(second, encoding="utf-8")
        self.rows.extend(second_rows)
        self.write_csv(self.mapping, self.rows, sorted(VALIDATOR.REQUIRED_COLUMNS))
        manifest = self.manifest_path.read_text(encoding="utf-8").replace("deliverable_id: post", "deliverable_id: C")
        self.manifest_path.write_text(manifest + "  - deliverable_id: B::C\n    role: requested-format\n", encoding="utf-8")
        self.deliverables.append(Path("second.md"))
        self.assert_cli(0, "source-inventory records reconcile")
        self.inventory["coverage"] = [item for item in self.inventory["coverage"] if (item["source_unit_id"], item["deliverable_id"]) != ("A", "B::C")]
        self.inventory_path.write_text(json.dumps(self.inventory), encoding="utf-8")
        self.assert_cli(1, "A has no retained/shortened/omitted coverage for B::C")

    def test_oversized_numeric_indices_fail_with_diagnostics(self) -> None:
        self.support[0]["output_occurrence"] = "1" * 5000
        self.flush()
        self.assert_cli(1, "is not a literal fragment")
        self.support[0]["output_occurrence"] = "1"
        self.units[0]["source_locator"] = "line:" + "1" * 5000
        self.flush()
        self.assert_cli(1, "needs an exact line:N locator")

    def test_malformed_json_fields_fail_with_diagnostics(self) -> None:
        original = copy.deepcopy(self.inventory)
        mutations = [
            lambda value: value["review"].update(checks=[{}]),
            lambda value: value["source_units"][0].update(kind={}),
            lambda value: value["source_units"][0].update(source_unit_id=[]),
            lambda value: value["source_units"][0].update(claim_ids=[{}]),
            lambda value: value["coverage"][0].update(source_unit_id={}),
            lambda value: value["coverage"][0].update(statement_ids=[{}]),
            lambda value: value["coverage"][0].update(status=[]),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.inventory = copy.deepcopy(original)
                mutate(self.inventory)
                self.inventory_path.write_text(json.dumps(self.inventory), encoding="utf-8")
                self.assert_cli(1, "validation failed")


if __name__ == "__main__":
    unittest.main()
