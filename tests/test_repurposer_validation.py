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
                "kind": unit["kind"], "reason": "exact source unit reviewed",
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
        return {"source_unit_id": unit_id, "kind": kind, "source_locator": f"line:{line}", "source_text": quote, "claim_ids": claims}

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
