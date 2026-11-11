"""Standalone CSV contracts, including generated helpers outside the checkout."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
MOTION = "motion-performance-qa"
REPURPOSER = "report-content-repurposer"
WRITERS = ("evidence-first-report", "editorial-data-storytelling")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def csv_text(records: list[list[str]], ending: str = "\r\n") -> str:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator=ending).writerows(records)
    return stream.getvalue()


class HelperLayouts:
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        temp = tempfile.TemporaryDirectory(prefix="csv-")
        cls.addClassCleanup(temp.cleanup)
        cls.workspace = Path(temp.name)
        builder = load_module(ROOT / "scripts/build_skills.py", "phase_i_csv_builder")
        generated = cls.workspace / "generated"
        builder.generate_tree(generated)
        relocated = cls.workspace / "isolated/.agents/skills"
        for name in (MOTION, REPURPOSER, *WRITERS):
            shutil.copytree(generated / name, relocated / name)
        cls.layouts = {"canonical": ROOT / "source/skills", "relocated": relocated}
        cls.task = cls.workspace / "task"
        cls.task.mkdir()
        cls.helpers = {}
        cls.before = {}
        for layout, skills in cls.layouts.items():
            for name, filename in ((MOTION, "summarize_frame_intervals.py"), (REPURPOSER, "validate_derivative_package.py")):
                path = skills / name / "scripts" / filename
                cls.helpers[layout, name] = load_module(path, f"phase_i_csv_{layout}_{name.replace('-', '_')}")
            for name in (MOTION, REPURPOSER, *WRITERS):
                for path in (skills / name / "scripts").iterdir():
                    if path.is_file():
                        cls.before[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        assert not (cls.workspace / "isolated/source").exists()
        assert not (cls.task / "scripts").exists()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            for path, digest in cls.before.items():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise AssertionError(f"Helper changed while executing: {path}")
        finally:
            super().tearDownClass()

    def put_csv(self, text: str) -> Path:
        path = self.task / "input.csv"
        path.write_bytes(text.encode("utf-8"))
        return path


class MotionCsvContracts(HelperLayouts, unittest.TestCase):
    def test_valid_controls(self) -> None:
        for layout in self.layouts:
            helper = self.helpers[layout, MOTION]
            for terminal in ("", "\n", "\r\n"):
                with self.subTest(layout=layout, terminal=repr(terminal)):
                    text = '\ufeffinterval_ms,note\r\n16.7,"quote "" and comma,\n\ninside"\r\n33.4,last' + terminal
                    self.assertEqual(helper.load_csv(self.put_csv(text)), ("intervals", [16.7, 33.4]))
            self.assertEqual(helper.load_csv(self.put_csv("timestamp_ms\n0\n10\n30\n")), ("timestamps", [0, 10, 30]))
            self.assertEqual(helper.load_csv(self.put_csv("interval_ms,timestamp_ms\n16.7,33.4\n")), ("intervals", [16.7]))

    def test_rejects_invalid_records_before_numeric_projection(self) -> None:
        cases = {
            "missing-field": "interval_ms,note\n16.7\n",
            "extra-field": "interval_ms,note\n16.7,ok,extra\n",
            "blank-middle": "interval_ms\n16.7\n\n33.4\n",
            "blank-tail": "interval_ms\n16.7\n\n",
            "whitespace-tail": "interval_ms\n16.7\n \t\n",
            "empty-header": "interval_ms,\n16.7,ok\n",
            "whitespace-header": "interval_ms, \t\n16.7,ok\n",
            "duplicate-header": "interval_ms,note,note\n16.7,one,two\n",
            "case-ambiguous-header": "interval_ms,note,NOTE\n16.7,one,two\n",
        }
        for layout in self.layouts:
            helper = self.helpers[layout, MOTION]
            self.assertEqual(helper.load_csv(self.put_csv("interval_ms,note\n16.7,ok\n")), ("intervals", [16.7]))
            for case, text in cases.items():
                with self.subTest(layout=layout, case=case):
                    with self.assertRaisesRegex(ValueError, "CSV"):
                        helper.load_csv(self.put_csv(text))

    def test_rejects_malformed_quotes_and_bare_record_endings(self) -> None:
        cases = {
            "unquoted-quote": 'interval_ms,note\n16.7,bad"quote\n',
            "unclosed-quote": 'interval_ms,note\n16.7,"unclosed\n',
            "after-quote": 'interval_ms,note\n16.7,"closed"junk\n',
            "indented-quote": 'interval_ms,note\n16.7, "indented"\n',
            "bare-cr": 'interval_ms,note\r16.7,ok\r',
        }
        for layout, skills in self.layouts.items():
            helper = self.helpers[layout, MOTION]
            self.assertEqual(helper.load_csv(self.put_csv("interval_ms,note\n16.7,ok\n")), ("intervals", [16.7]))
            for case, text in cases.items():
                with self.subTest(layout=layout, case=case):
                    path = self.put_csv(text)
                    with self.assertRaisesRegex(ValueError, "CSV"):
                        helper.load_csv(path)
                    result = subprocess.run([sys.executable, str(skills / MOTION / "scripts/summarize_frame_intervals.py"), path.name], cwd=self.task, capture_output=True, text=True, check=False, timeout=30)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("error:", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)


class RepurposerCsvContracts(HelperLayouts, unittest.TestCase):
    def mapping_records(self, helper) -> list[list[str]]:
        headers = sorted(helper.REQUIRED_COLUMNS) + ["note"]
        row = {key: "value" for key in headers}
        row.update(statement_id="ST-1", output_text='Quoted "copy", with\n\nblank physical line', note="  retained  ")
        return [headers, [row[key] for key in headers]]

    def deliverable_records(self, helper) -> list[list[str]]:
        headers = ["statement_id", "output_text", *sorted(helper.CSV_PROVENANCE_COLUMNS)]
        row = {key: "synthetic" for key in headers}
        row.update(statement_id="ST-1", output_text='Quoted "copy", with\n\nblank physical line', status="draft")
        return [headers, [row[key] for key in headers]]

    def invalid_record_cases(self, records: list[list[str]]) -> dict[str, str]:
        headers, row = records
        return {
            "blank-middle": csv_text([headers]) + "\r\n" + csv_text([row]),
            "blank-tail": csv_text(records) + "\r\n",
            "whitespace-tail": csv_text(records) + " \t\n",
            "all-empty-record": csv_text(records + [[""] * len(headers)]),
            "all-whitespace-record": csv_text(records + [[" \t"] * len(headers)]),
            "missing-field": csv_text([headers, row[:-1]]),
            "extra-field": csv_text([headers, row + ["extra"]]),
            "empty-header": csv_text([headers + [""], row + ["value"]]),
            "whitespace-header": csv_text([headers + [" \t"], row + ["value"]]),
            "duplicate-header": csv_text([headers + [headers[0]], row + [row[0]]]),
            "case-ambiguous-header": csv_text([headers + [headers[0].upper()], row + [row[0]]]),
        }

    def test_mapping_rejects_invalid_logical_records_and_headers(self) -> None:
        for layout in self.layouts:
            helper = self.helpers[layout, REPURPOSER]
            records = self.mapping_records(helper)
            rows, errors = helper.read_mapping(self.put_csv(csv_text(records)))
            self.assertEqual(errors, [])
            self.assertEqual(len(rows), 1)
            for case, text in self.invalid_record_cases(records).items():
                with self.subTest(layout=layout, case=case):
                    _, errors = helper.read_mapping(self.put_csv(text))
                    self.assertTrue(errors, f"Invalid mapping CSV accepted: {case}")

    def test_deliverable_rejects_invalid_logical_records_and_headers(self) -> None:
        for layout in self.layouts:
            helper = self.helpers[layout, REPURPOSER]
            records = self.deliverable_records(helper)
            statements, errors = helper.read_deliverable(self.put_csv(csv_text(records)))
            self.assertEqual(errors, [])
            self.assertEqual(len(statements), 1)
            for case, text in self.invalid_record_cases(records).items():
                with self.subTest(layout=layout, case=case):
                    _, errors = helper.read_deliverable(self.put_csv(text))
                    self.assertTrue(errors, f"Invalid deliverable CSV accepted: {case}")

    def test_rejects_malformed_quotes_and_bare_record_endings(self) -> None:
        for layout in self.layouts:
            helper = self.helpers[layout, REPURPOSER]
            for kind, records, read in (("mapping", self.mapping_records(helper), helper.read_mapping), ("deliverable", self.deliverable_records(helper), helper.read_deliverable)):
                headers, row = records
                records = [headers + ["csv_note"], row + ["note"]]
                self.assertEqual(read(self.put_csv(csv_text(records)))[1], [])
                prefix = csv_text(records).removesuffix("note\r\n")
                cases = {
                    "unquoted-quote": prefix + 'bad"quote\r\n',
                    "indented-quote": prefix + ' "indented"\r\n',
                    "unclosed-quote": prefix + '"unclosed\r\n',
                    "after-quote": prefix + '"closed"junk\r\n',
                    "bare-cr": csv_text(records).replace("\r\n", "\r"),
                }
                for case, text in cases.items():
                    with self.subTest(layout=layout, kind=kind, case=case):
                        _, errors = read(self.put_csv(text))
                        self.assertTrue(errors, f"Malformed CSV accepted: {case}")
                        self.assertIn("CSV", " ".join(errors))

    def test_valid_controls(self) -> None:
        for layout in self.layouts:
            helper = self.helpers[layout, REPURPOSER]
            for terminal in ("", "\n", "\r\n"):
                with self.subTest(layout=layout, terminal=repr(terminal)):
                    records = self.mapping_records(helper)
                    text = "\ufeff" + csv_text(records).removesuffix("\r\n") + terminal
                    rows, errors = helper.read_mapping(self.put_csv(text))
                    self.assertEqual(errors, [])
                    self.assertEqual(rows, [dict(zip(records[0], (value.strip() for value in records[1])))])
                    records = self.deliverable_records(helper)
                    text = csv_text(records).removesuffix("\r\n") + terminal
                    statements, errors = helper.read_deliverable(self.put_csv(text))
                    self.assertEqual(errors, [])
                    self.assertEqual(statements, {"ST-1": records[1][1]})


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
class RepurposerParityContracts(HelperLayouts, unittest.TestCase):
    """Shared mapping/deliverable guards; not proof of identical CSV dialects."""

    def fixture(self):
        module = load_module(ROOT / "tests/test_derivative_traceability.py", "phase_i_csv_parity_fixture")
        fixture = module.DerivativeTraceabilityTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    def run_validator(self, skills: Path, fixture, powershell: bool) -> subprocess.CompletedProcess:
        scripts = skills / REPURPOSER / "scripts"
        if powershell:
            command = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(scripts / "validate_derivative_package.ps1"), "-StructuralOnly", "-ArtifactsRoot", str(fixture.root), "-Mapping", str(fixture.mapping), "-Deliverables", "post.md,video.csv"]
        else:
            command = [sys.executable, str(scripts / "validate_derivative_package.py"), "--structural-only", "--artifacts-root", str(fixture.root), "--mapping", str(fixture.mapping), "--deliverable", "post.md", "--deliverable", "video.csv"]
        return subprocess.run(command, cwd=fixture.root.parent, capture_output=True, text=True, check=False, timeout=30)

    def test_shared_terminal_and_quoted_newline_controls(self) -> None:
        fixture = self.fixture()
        for target in (fixture.mapping, fixture.root / "video.csv"):
            original = target.read_bytes()
            records = list(csv.reader(io.StringIO(original.decode("utf-8"), newline=""), strict=True))
            records = [records[0] + ["csv_note"], *[row + ['comma, "quote"\n\nembedded'] for row in records[1:]]]
            try:
                for terminal in ("", "\n", "\r\n"):
                    target.write_bytes((csv_text(records).removesuffix("\r\n") + terminal).encode("utf-8"))
                    for layout, skills in self.layouts.items():
                        for powershell in (False, True):
                            with self.subTest(target=target.name, layout=layout, powershell=powershell, terminal=repr(terminal)):
                                result = self.run_validator(skills, fixture, powershell)
                                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                                self.assertIn("not a handoff pass", result.stdout)
            finally:
                target.write_bytes(original)

    def test_shared_empty_record_width_and_header_refusals(self) -> None:
        fixture = self.fixture()
        for target in (fixture.mapping, fixture.root / "video.csv"):
            original = target.read_bytes()
            records = list(csv.reader(io.StringIO(original.decode("utf-8"), newline=""), strict=True))
            cases = {
                "blank-middle": csv_text(records[:1]) + "\n" + csv_text(records[1:]),
                "blank-tail": csv_text(records) + "\n",
                "all-empty": csv_text(records + [[""] * len(records[0])]),
                "all-whitespace": csv_text(records + [[" \t"] * len(records[0])]),
                "missing-field": csv_text([records[0], records[1][:-1], *records[2:]]),
                "extra-field": csv_text([records[0], records[1] + ["extra"], *records[2:]]),
                "empty-header": csv_text([records[0] + [""], *[row + ["value"] for row in records[1:]]]),
                "duplicate-header": csv_text([records[0] + [records[0][0]], *[row + [row[0]] for row in records[1:]]]),
                "ambiguous-header": csv_text([records[0] + [records[0][0].upper()], *[row + [row[0]] for row in records[1:]]]),
            }
            try:
                for layout, skills in self.layouts.items():
                    for powershell in (False, True):
                        target.write_bytes(original)
                        control = self.run_validator(skills, fixture, powershell)
                        self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
                        for case, text in cases.items():
                            with self.subTest(target=target.name, layout=layout, powershell=powershell, case=case):
                                target.write_bytes(text.encode("utf-8"))
                                result = self.run_validator(skills, fixture, powershell)
                                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                                self.assertNotIn("Traceback", result.stderr)
            finally:
                target.write_bytes(original)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
class WriterReadbackContracts(HelperLayouts, unittest.TestCase):
    def fault_wrapper(self) -> Path:
        # Shadow only the serializer in a fresh synthetic process. The deployed
        # writer itself remains byte-identical and must catch valid-shaped loss.
        wrapper = self.task / "serializer-fault.ps1"
        wrapper.write_text('''param([string]$Writer, [string]$InputJsonPath, [string]$OutputPath)
function ConvertTo-Csv {
    [CmdletBinding()]
    param([Parameter(ValueFromPipeline = $true)]$InputObject, [switch]$NoTypeInformation)
    begin { $items = [System.Collections.Generic.List[object]]::new() }
    process { $items.Add($InputObject) }
    end {
        $serialized = @($items.ToArray() | Microsoft.PowerShell.Utility\\ConvertTo-Csv -NoTypeInformation)
        switch ($env:PHASE_I_CSV_FAULT) {
            'drop' { $serialized = @($serialized[0], $serialized[1]) }
            'extra' { $serialized += $serialized[2] }
            'first-cell' { $serialized[1] = $serialized[1].Replace('"A"', '"a"') }
            'last-cell' { $serialized[2] = $serialized[2].Replace('"last"', '"LAST"') }
            'swap' { $serialized = @($serialized[0], $serialized[2], $serialized[1]) }
            'width' { $serialized[2] += ',"extra"' }
            'empty-record' { $serialized += '' }
            'all-empty-record' { $serialized += '"",""' }
            'whitespace-record' { $serialized += '" "," "' }
            'unquoted-quote' { $serialized[2] = '"B",bad"quote' }
            'after-quote' { $serialized[2] = '"B","last"junk' }
            'unclosed-quote' { $serialized[2] = '"B","unclosed' }
        }
        $serialized
    }
}
& $Writer -InputJsonPath $InputJsonPath -OutputPath $OutputPath
''', encoding="utf-8")
        return wrapper

    def assert_fault_refused(self, modes: tuple[str, ...], diagnostic: str) -> None:
        payload = {"header": ["id", "value"], "rows": [{"id": "A", "value": "first"}, {"id": "B", "value": "last"}]}
        wrapper = self.fault_wrapper()
        for layout, skills in self.layouts.items():
            for name in WRITERS:
                script = skills / name / "scripts/write-register-csv.ps1"
                control = self.run_writer(script, payload, wrapper=wrapper)
                self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
                self.assert_records([["id", "value"], ["A", "first"], ["B", "last"]])
                for mode in modes:
                    with self.subTest(layout=layout, skill=name, fault=mode):
                        result = self.run_writer(script, payload, wrapper=wrapper, fault=mode)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertNotIn("Wrote and strictly validated", result.stdout)
                        self.assertIn(diagnostic, result.stderr)

    def test_readback_rejects_changed_data_row_count(self) -> None:
        self.assert_fault_refused(("drop", "extra"), "data-row count")

    def test_readback_rejects_changed_values_in_every_row_and_column(self) -> None:
        self.assert_fault_refused(("first-cell", "last-cell", "swap"), "data field")

    def test_existing_strict_readback_rejects_malformed_serializer_output(self) -> None:
        self.assert_fault_refused(("width", "empty-record", "all-empty-record", "whitespace-record", "unquoted-quote", "after-quote", "unclosed-quote"), "CSV")

    def run_writer(self, script: Path, payload: dict, *, wrapper: Path | None = None, fault: str = "") -> subprocess.CompletedProcess:
        input_path = self.task / "register.json"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        command = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(wrapper or script)]
        if wrapper:
            command += ["-Writer", str(script)]
        command += ["-InputJsonPath", input_path.name, "-OutputPath", "register.csv"]
        env = os.environ.copy()
        env["PHASE_I_CSV_FAULT"] = fault
        return subprocess.run(command, cwd=self.task, env=env, capture_output=True, text=True, check=False, timeout=30)

    def assert_records(self, expected: list[list[str]]) -> None:
        with (self.task / "register.csv").open(encoding="utf-8", newline="") as stream:
            self.assertEqual(list(csv.reader(stream, strict=True)), expected)

    def test_rejects_empty_or_ambiguous_header_names(self) -> None:
        cases = [
            {"header": ["id", ""], "rows": [{"id": "A", "": "value"}]},
            {"header": ["id", " \t"], "rows": [{"id": "A", " \t": "value"}]},
            {"header": ["id", "id"], "rows": [{"id": "A"}]},
            {"header": ["id", "ID"], "rows": [{"id": "A", "ID": "B"}]},
        ]
        for layout, skills in self.layouts.items():
            for name in WRITERS:
                script = skills / name / "scripts/write-register-csv.ps1"
                control = self.run_writer(script, {"header": ["id"], "rows": [{"id": "A"}]})
                self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
                for payload in cases:
                    with self.subTest(layout=layout, skill=name, header=payload["header"]):
                        result = self.run_writer(script, payload)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("header", result.stderr.casefold())

    def test_valid_controls(self) -> None:
        cases = [
            ({"header": ["value"], "rows": [{"value": 0}]}, [["value"], ["0"]]),
            ({"header": ["id", "value"], "rows": [{"id": "A", "value": 'quote " and comma,\n\ninside'}, {"id": "B", "value": None}]}, [["id", "value"], ["A", 'quote " and comma,\n\ninside'], ["B", ""]]),
            ({"header": ["id", "false", "true", "number", "empty"], "rows": [{"id": "é", "false": False, "true": True, "number": 1.25, "empty": ""}]}, [["id", "false", "true", "number", "empty"], ["é", "False", "True", "1.25", ""]]),
        ]
        for layout, skills in self.layouts.items():
            for name in WRITERS:
                for payload, expected in cases:
                    with self.subTest(layout=layout, skill=name, header=payload["header"]):
                        script = skills / name / "scripts/write-register-csv.ps1"
                        result = self.run_writer(script, payload)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("Wrote and strictly validated", result.stdout)
                        self.assert_records(expected)


if __name__ == "__main__":
    unittest.main()
