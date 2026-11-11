"""Blocking CSV regressions through canonical and freshly relocated CLIs."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
WRITERS = ("evidence-first-report", "editorial-data-storytelling")
REPURPOSER = "report-content-repurposer"


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def csv_text(records: list[list[str]]) -> str:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\r\n").writerows(records)
    return stream.getvalue()


class FreshHelperLayouts:
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        temp = tempfile.TemporaryDirectory(prefix="csv-review-")
        cls.addClassCleanup(temp.cleanup)
        cls.workspace = Path(temp.name)
        generated = cls.workspace / "generated"
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/build_skills.py"), "--output", str(generated)],
            cwd=cls.workspace, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        relocated = cls.workspace / "isolated/.agents/skills"
        for name in (*WRITERS, REPURPOSER):
            shutil.copytree(generated / name, relocated / name)
        cls.layouts = {"canonical": ROOT / "source/skills", "relocated": relocated}
        cls.helper_hashes = {}
        for skills in cls.layouts.values():
            for name in (*WRITERS, REPURPOSER):
                directory = skills / name
                cls.helper_hashes[directory] = file_hashes(directory)
                if skills == relocated:
                    for path in (directory / "scripts").iterdir():
                        if path.is_file():
                            canonical = ROOT / "source/skills" / name / "scripts" / path.name
                            if path.read_bytes() != canonical.read_bytes():
                                raise AssertionError(f"Generated helper differs: {path}")
        if (cls.workspace / "isolated/source").exists():
            raise AssertionError("Relocated skills must not have a source checkout")

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            for directory, expected in cls.helper_hashes.items():
                if file_hashes(directory) != expected:
                    raise AssertionError(f"Executing helper mutated its skill: {directory}")
        finally:
            super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        temp = tempfile.TemporaryDirectory(prefix="task-", dir=self.workspace)
        self.addCleanup(temp.cleanup)
        self.task = Path(temp.name)
        self.assertFalse((self.task / "scripts").exists())


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
class WriterExactKeyRegressions(FreshHelperLayouts, unittest.TestCase):
    def run_writer(self, script: Path, payload: dict, output: str) -> subprocess.CompletedProcess[str]:
        input_path = self.task / "register.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        before = input_path.read_bytes()
        result = subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(script),
             "-InputJsonPath", input_path.name, "-OutputPath", output],
            cwd=self.task, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
        self.assertEqual(input_path.read_bytes(), before)
        return result

    def assert_records(self, path: Path, expected: list[list[str]]) -> None:
        with path.open(encoding="utf-8", newline="") as stream:
            self.assertEqual(list(csv.reader(stream, strict=True)), expected)

    def test_exact_lowercase_and_uppercase_keys_preserve_every_value(self) -> None:
        for layout, skills in self.layouts.items():
            for name in WRITERS:
                for header in (["id", "value"], ["ID", "VALUE"]):
                    with self.subTest(layout=layout, skill=name, header=header):
                        rows = [
                            {header[1]: '  retained é 漢字, "quoted"\r\n\nnext  ', header[0]: "A"},
                            {header[0]: "B", header[1]: "last"},
                        ]
                        result = self.run_writer(skills / name / "scripts/write-register-csv.ps1", {"header": header, "rows": rows}, "control.csv")
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("strictly validated 2 CSV records", result.stdout)
                        self.assert_records(self.task / "control.csv", [header, *[[row[key] for key in header] for row in rows]])

    def test_case_only_key_mutation_is_refused_before_output_write(self) -> None:
        for layout, skills in self.layouts.items():
            for name in WRITERS:
                with self.subTest(layout=layout, skill=name):
                    script = skills / name / "scripts/write-register-csv.ps1"
                    control = self.run_writer(script, {"header": ["id", "value"], "rows": [{"id": "A", "value": "retained"}]}, "control.csv")
                    self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
                    self.assert_records(self.task / "control.csv", [["id", "value"], ["A", "retained"]])
                    output = self.task / f"reject-{layout}-{name}/register.csv"
                    result = self.run_writer(script, {"header": ["id", "value"], "rows": [{"ID": "A", "value": "retained"}]}, output.relative_to(self.task).as_posix())
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("exactly the required header fields", result.stderr)
                    self.assertNotIn("Wrote and strictly validated", result.stdout)
                    self.assertFalse(output.exists())
                    self.assertFalse(output.parent.exists())

    def test_nonexact_key_sets_cannot_overwrite_existing_output(self) -> None:
        header = ["id", "value"]
        valid = [{"id": "A", "value": "first"}, {"id": "B", "value": "last"}]
        mutations = {
            "missing": [{"id": "A"}, valid[1]],
            "extra": [{**valid[0], "extra": "unexpected"}, valid[1]],
            "case-alias": [{"id": "A", "ID": "alias"}, valid[1]],
            "later-row": [valid[0], {"ID": "B", "value": "last"}],
            "later-column": [valid[0], {"id": "B", "VALUE": "last"}],
        }
        for layout, skills in self.layouts.items():
            for name in WRITERS:
                script = skills / name / "scripts/write-register-csv.ps1"
                control = self.run_writer(script, {"header": header, "rows": valid}, "existing.csv")
                self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
                output = self.task / "existing.csv"
                self.assert_records(output, [header, ["A", "first"], ["B", "last"]])
                before = output.read_bytes()
                for case, rows in mutations.items():
                    with self.subTest(layout=layout, skill=name, case=case):
                        result = self.run_writer(script, {"header": header, "rows": rows}, output.name)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("exactly the required header fields", result.stderr)
                        self.assertNotIn("Wrote and strictly validated", result.stdout)
                        self.assertEqual(output.read_bytes(), before)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
class FullHandoffSupportCsvRegressions(FreshHelperLayouts, unittest.TestCase):
    def fixture(self):
        spec = importlib.util.spec_from_file_location("review_csv_source_fixture", ROOT / "tests/test_repurposer_validation.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = module.RepurposerSourceContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def run_full_handoff(self, skills: Path, fixture, powershell: bool) -> subprocess.CompletedProcess[str]:
        scripts = skills / REPURPOSER / "scripts"
        if powershell:
            command = [
                shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(scripts / "validate_derivative_package.ps1"),
                "-ArtifactsRoot", "artifacts", "-Mapping", "artifacts/claim-mapping.csv",
                "-Deliverables", ",".join(path.as_posix() for path in fixture.deliverables), "-SourceReport", "source.md",
                "-SourceInventory", "artifacts/source-inventory.json", "-StatementSupport", "artifacts/statement-support.csv",
            ]
        else:
            command = [
                sys.executable, "-B", str(scripts / "validate_derivative_package.py"),
                "--artifacts-root", "artifacts", "--mapping", "artifacts/claim-mapping.csv",
                *[argument for path in fixture.deliverables for argument in ("--deliverable", path.as_posix())],
                "--source-report", "source.md",
                "--source-inventory", "artifacts/source-inventory.json", "--statement-support", "artifacts/statement-support.csv",
            ]
        before = file_hashes(fixture.root.parent)
        result = subprocess.run(command, cwd=fixture.root.parent, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
        self.assertEqual(file_hashes(fixture.root.parent), before)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def assert_handoff_pass(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("source-inventory records reconcile", result.stdout)
        self.assertIn("semantic support remains the documented manual review", result.stdout)
        self.assertNotIn("not a handoff pass", result.stdout)

    def csv_fixture(self, *, unicode_multiline: bool = False):
        # Reuse the complete source contract, changing only the output format.
        # Every output keeps its mapping, atomic support, coverage and provenance.
        fixture = self.fixture()
        if unicode_multiline:
            fixture.replace_title("Synthetic é 漢字 service trial")
            for row in fixture.rows:
                row["reason"] = 'Review é 漢字, "literal"\n\nsecond physical line'
                if row["statement_id"] == "BODY":
                    row["output_text"] = row["output_text"].replace(". Booking", ".\nBooking")
            for child in fixture.support:
                child["reason"] = 'Atomic é 漢字, "literal"\n\nsecond physical line'
        for row in fixture.rows:
            row["output_path"] = "post.csv"
        fixture.flush()
        fields = ["statement_id", "output_text", "parent_report_id", "parent_report_version", "parent_report_hash", "source_claim_ids", "transformation_type", "dimensions", "aspect_ratio", "status"]
        records = [fields]
        for row in fixture.rows:
            output = {
                "statement_id": row["statement_id"], "output_text": row["output_text"],
                "parent_report_id": "trial", "parent_report_version": "1.0", "parent_report_hash": fixture.source_hash,
                "source_claim_ids": "SYN-A;SYN-B", "transformation_type": "local social copy",
                "dimensions": "1080x1350 specification", "aspect_ratio": "4:5", "status": "draft",
            }
            records.append([output[field] for field in fields])
        (fixture.root / "post.csv").write_bytes(csv_text(records).encode("utf-8"))
        fixture.deliverables = [Path("post.csv"), Path("derivative-manifest.yaml")]
        return fixture

    def csv_targets(self, fixture) -> tuple[Path, ...]:
        return fixture.mapping, fixture.support_path, fixture.root / "post.csv"

    def records_with_note(self, target: Path, note: str) -> list[list[str]]:
        with target.open(encoding="utf-8", newline="") as handle:
            records = list(csv.reader(handle, strict=True))
        return [records[0] + ["csv_note"], *[row + [note] for row in records[1:]]]

    def assert_csv_refused(self, result: subprocess.CompletedProcess[str], diagnostic: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("validation failed", result.stdout)
        self.assertRegex(result.stdout, diagnostic)
        self.assertNotIn("source-inventory records reconcile", result.stdout)

    def test_unquoted_support_reason_quote_is_refused_by_full_handoff_cli(self) -> None:
        fixture = self.fixture()
        original = fixture.support_path.read_bytes()
        mutated = original.replace(b"exact source unit reviewed", b'reviewed"unit', 1)
        self.assertNotEqual(mutated, original)
        for layout, skills in self.layouts.items():
            for powershell in (False, True):
                with self.subTest(layout=layout, powershell=powershell):
                    fixture.support_path.write_bytes(original)
                    self.assert_handoff_pass(self.run_full_handoff(skills, fixture, powershell))
                    fixture.support_path.write_bytes(mutated)
                    try:
                        result = self.run_full_handoff(skills, fixture, powershell)
                        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                        self.assertIn("cannot read statement support CSV", result.stdout)
                        self.assertIn("unexpected quote in an unquoted field", result.stdout)
                        self.assertNotIn("source-inventory records reconcile", result.stdout)
                    finally:
                        fixture.support_path.write_bytes(original)

    def test_full_handoff_accepts_quoted_unicode_multiline_csv_and_terminal_endings(self) -> None:
        fixture = self.csv_fixture(unicode_multiline=True)
        for target in self.csv_targets(fixture):
            original = target.read_bytes()
            records = self.records_with_note(target, 'CSV é 漢字, "quote"\n\nretained')
            try:
                for terminal in ("", "\n", "\r\n"):
                    target.write_bytes(("\ufeff" + csv_text(records).removesuffix("\r\n") + terminal).encode("utf-8"))
                    for layout, skills in self.layouts.items():
                        for powershell in (False, True):
                            with self.subTest(target=target.name, layout=layout, powershell=powershell, terminal=repr(terminal)):
                                self.assert_handoff_pass(self.run_full_handoff(skills, fixture, powershell))
            finally:
                target.write_bytes(original)

    def test_full_handoff_rejects_malformed_quotes_and_bare_record_endings(self) -> None:
        fixture = self.csv_fixture()
        for target in self.csv_targets(fixture):
            original = target.read_bytes()
            valid = csv_text(self.records_with_note(target, "reviewed unit"))
            cases = {
                "unquoted-quote": (valid.replace("reviewed unit", 'reviewed"unit', 1), "unexpected quote"),
                "indented-quote": (valid.replace("reviewed unit", ' "reviewed unit"', 1), "unexpected quote"),
                "after-quote": (valid.replace("reviewed unit", '"reviewed unit"junk', 1), "closing quote"),
                "unclosed-quote": (valid.replace("reviewed unit", '"reviewed unit', 1), "quot"),
                "bare-cr": (valid.replace("\r\n", "\r"), "carriage return"),
            }
            try:
                for layout, skills in self.layouts.items():
                    for powershell in (False, True):
                        target.write_bytes(valid.encode("utf-8"))
                        self.assert_handoff_pass(self.run_full_handoff(skills, fixture, powershell))
                        for case, (text, diagnostic) in cases.items():
                            with self.subTest(target=target.name, layout=layout, powershell=powershell, case=case):
                                target.write_bytes(text.encode("utf-8"))
                                self.assert_csv_refused(self.run_full_handoff(skills, fixture, powershell), diagnostic)
            finally:
                target.write_bytes(original)

    def test_full_handoff_rejects_blank_records_width_and_header_mutations(self) -> None:
        fixture = self.csv_fixture()
        for target in self.csv_targets(fixture):
            original = target.read_bytes()
            records = self.records_with_note(target, "reviewed unit")
            headers, first, *rest = records
            valid = csv_text(records)
            cases = {
                "no-header": ("", "header|column"),
                "blank-middle": (csv_text([headers]) + "\r\n" + csv_text(records[1:]), "blank|empty"),
                "blank-tail": (valid + "\r\n", "blank|empty"),
                "whitespace-tail": (valid + " \t\n", "blank|empty|whitespace"),
                "all-empty-record": (csv_text(records + [[""] * len(headers)]), "empty|blank"),
                "all-whitespace-record": (csv_text(records + [[" \t"] * len(headers)]), "empty|blank|whitespace"),
                "missing-field": (csv_text([headers, first[:-1], *rest]), "field count|fields; expected"),
                "extra-field": (csv_text([headers, first + ["extra"], *rest]), "field count|fields; expected"),
                "empty-header": (csv_text([headers + [""], *[row + ["value"] for row in records[1:]]]), "header"),
                "whitespace-header": (csv_text([headers + [" \t"], *[row + ["value"] for row in records[1:]]]), "header"),
                "duplicate-header": (csv_text([headers + [headers[0]], *[row + [row[0]] for row in records[1:]]]), "header"),
                "case-ambiguous-header": (csv_text([headers + [headers[0].upper()], *[row + [row[0]] for row in records[1:]]]), "header"),
                "missing-required-header": (csv_text([["not_a_required_column", *headers[1:]], *records[1:]]), "column"),
            }
            try:
                for layout, skills in self.layouts.items():
                    for powershell in (False, True):
                        target.write_bytes(valid.encode("utf-8"))
                        self.assert_handoff_pass(self.run_full_handoff(skills, fixture, powershell))
                        for case, (text, diagnostic) in cases.items():
                            with self.subTest(target=target.name, layout=layout, powershell=powershell, case=case):
                                target.write_bytes(text.encode("utf-8"))
                                # The unchanged PowerShell mapping path rejects
                                # empty fields at its status guard, before identity.
                                expected = diagnostic
                                if powershell and target == fixture.mapping and case in {"all-empty-record", "all-whitespace-record"}:
                                    expected = "mapping row has unsupported status ''"
                                self.assert_csv_refused(self.run_full_handoff(skills, fixture, powershell), expected)
            finally:
                target.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
