"""Real-CLI CSV dialect parity on wholly synthetic derivative packages."""
from __future__ import annotations

import csv
import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if __package__:
    from .test_phase_i_csv_contracts import REPURPOSER, ROOT, csv_text, load_module
else:
    from test_phase_i_csv_contracts import REPURPOSER, ROOT, csv_text, load_module


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
class PowerShellCsvParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        temp = tempfile.TemporaryDirectory(prefix="ps-csv-parity-")
        cls.addClassCleanup(temp.cleanup)
        cls.workspace = Path(temp.name)
        builder = load_module(ROOT / "scripts/build_skills.py", "powershell_csv_builder")
        generated = cls.workspace / "generated"
        builder.generate_tree(generated)
        cls.layouts = {"canonical": ROOT / "source/skills" / REPURPOSER}
        for label, layout in (
            ("plugin-relocated", Path("plugins/report-skills/skills")),
            ("agent-relocated", Path(".agents/skills")),
        ):
            isolated = cls.workspace / label
            installed = isolated / layout / REPURPOSER
            shutil.copytree(generated / REPURPOSER, installed)
            cls.layouts[label] = installed
            assert not (isolated / "source").exists()
            assert not (isolated / ".benchmark_skill").exists()
        cls.helper_hashes = {
            skill / "scripts": file_hashes(skill / "scripts")
            for skill in cls.layouts.values()
        }
        canonical = cls.helper_hashes[cls.layouts["canonical"] / "scripts"]
        assert all(value == canonical for value in cls.helper_hashes.values())

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            for directory, before in cls.helper_hashes.items():
                if file_hashes(directory) != before:
                    raise AssertionError(f"Helper changed while executing: {directory}")
        finally:
            super().tearDownClass()

    def setUp(self) -> None:
        fixture_module = load_module(
            ROOT / "tests/test_derivative_traceability.py", "powershell_csv_fixture"
        )
        self.fixture = fixture_module.DerivativeTraceabilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    @staticmethod
    def records(target: Path) -> list[list[str]]:
        return list(csv.reader(
            io.StringIO(target.read_bytes().decode("utf-8-sig"), newline=""), strict=True,
        ))

    def run_validator(self, skill: Path, powershell: bool) -> subprocess.CompletedProcess:
        scripts = skill / "scripts"
        if powershell:
            command = [
                shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File",
                str(scripts / "validate_derivative_package.ps1"), "-StructuralOnly",
                "-ArtifactsRoot", "artifacts", "-Mapping", "artifacts/claim-mapping.csv",
                "-Deliverables", "post.md,video.csv",
            ]
        else:
            command = [
                sys.executable, "-B", str(scripts / "validate_derivative_package.py"),
                "--structural-only", "--artifacts-root", "artifacts",
                "--mapping", "artifacts/claim-mapping.csv", "--deliverable", "post.md",
                "--deliverable", "video.csv",
            ]
        before = file_hashes(self.fixture.root.parent)
        result = subprocess.run(
            command, cwd=self.fixture.root.parent, capture_output=True,
            text=True, check=False, timeout=30,
        )
        self.assertEqual(file_hashes(self.fixture.root.parent), before)
        self.assertFalse((self.fixture.root.parent / "scripts").exists())
        self.assertFalse((self.fixture.root.parent / ".benchmark_skill").exists())
        return result

    def assert_valid_control(self, skill: Path) -> None:
        for powershell in (False, True):
            result = self.run_validator(skill, powershell)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("not a handoff pass", result.stdout)
            self.assertNotIn("source-inventory records reconcile", result.stdout)

    def assert_refused(self, skill: Path, diagnostic: str) -> None:
        for powershell in (False, True):
            with self.subTest(powershell=powershell):
                result = self.run_validator(skill, powershell)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(diagnostic, result.stdout)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("Structural checks passed", result.stdout)

    def test_unmodified_valid_fixture_passes_both_clis(self) -> None:
        for layout, skill in self.layouts.items():
            with self.subTest(layout=layout):
                self.assert_valid_control(skill)

    def test_mapping_rejects_unquoted_quote(self) -> None:
        target = self.fixture.mapping
        original = target.read_bytes()
        records = self.records(target)
        records = [records[0] + ["csv_note"], *[row + ["note"] for row in records[1:]]]
        valid = csv_text(records)
        for layout, skill in self.layouts.items():
            with self.subTest(layout=layout):
                target.write_bytes(original)
                self.assert_valid_control(skill)
                target.write_bytes(valid.encode("utf-8"))
                self.assert_valid_control(skill)
                # Only one optional cell changes; provenance and statements stay valid.
                malformed = valid.replace(",note\r\n", ',bad"quote\r\n', 1)
                self.assertNotEqual(malformed, valid)
                target.write_bytes(malformed.encode("utf-8"))
                self.assert_refused(skill, "unexpected quote")

    def set_video_copy(self, text: str) -> None:
        for target in (self.fixture.mapping, self.fixture.root / "video.csv"):
            records = self.records(target)
            statement = records[0].index("statement_id")
            output = records[0].index("output_text")
            for row in records[1:]:
                if row[statement] in ("ST-002", "ST-003"):
                    row[output] = text
            target.write_bytes(csv_text(records).encode("utf-8"))

    def test_quoted_copy_keeps_embedded_lf_crlf_and_bare_cr(self) -> None:
        # Copy-bearing values, not only ignored notes, must retain literal breaks.
        for ending in ("\n", "\r\n", "\r"):
            self.set_video_copy('Literal "copy", café' + ending * 2 + "second line")
            for layout, skill in self.layouts.items():
                with self.subTest(layout=layout, embedded=repr(ending)):
                    self.assert_valid_control(skill)

    def test_embedded_newline_differences_are_not_normalized_away(self) -> None:
        video = self.fixture.root / "video.csv"
        for ending in ("\r\n", "\r"):
            self.set_video_copy("Literal first" + ending + "second line")
            valid = video.read_bytes()
            records = self.records(video)
            output = records[0].index("output_text")
            records[1][output] = records[1][output].replace(ending, "\n")
            different = csv_text(records).encode("utf-8")
            self.assertNotEqual(valid, different)
            for layout, skill in self.layouts.items():
                with self.subTest(layout=layout, embedded=repr(ending)):
                    video.write_bytes(valid)
                    self.assert_valid_control(skill)
                    video.write_bytes(different)
                    self.assert_refused(skill, "output_text does not exactly match")
            video.write_bytes(valid)

    def test_mapping_and_deliverable_reject_malformed_quotes_and_endings(self) -> None:
        for target in (self.fixture.mapping, self.fixture.root / "video.csv"):
            original = target.read_bytes()
            records = self.records(target)
            records = [records[0] + ["csv_note"], *[row + ["note"] for row in records[1:]]]
            valid = csv_text(records)
            cases = {
                "unquoted-quote": (valid.replace(",note\r\n", ',bad"quote\r\n', 1), "unexpected quote"),
                "indented-quote": (valid.replace(",note\r\n", ', "note"\r\n', 1), "unexpected quote"),
                "tabbed-quote": (valid.replace(",note\r\n", ',\t"note"\r\n', 1), "unexpected quote"),
                "after-quote": (valid.replace(",note\r\n", ',"note"junk\r\n', 1), "closing quote"),
                "space-after-quote": (valid.replace(",note\r\n", ',"note" \r\n', 1), "closing quote"),
                "unclosed-quote": (valid.removesuffix("note\r\n") + '"unclosed\r\n', "quoted field"),
                "bare-cr-middle": (valid.replace("\r\n", "\r", 1), "carriage return"),
                "bare-cr-tail": (valid.removesuffix("\r\n") + "\r", "carriage return"),
            }
            try:
                for layout, skill in self.layouts.items():
                    target.write_bytes(valid.encode("utf-8"))
                    self.assert_valid_control(skill)
                    for case, (text, diagnostic) in cases.items():
                        with self.subTest(target=target.name, layout=layout, case=case):
                            self.assertNotEqual(text, valid)
                            target.write_bytes(text.encode("utf-8"))
                            self.assert_refused(skill, diagnostic)
            finally:
                target.write_bytes(original)

    def test_mapping_and_deliverable_keep_empty_width_and_header_guards(self) -> None:
        # Characterization of unchanged guards, exercised through the full CLI.
        for target in (self.fixture.mapping, self.fixture.root / "video.csv"):
            original = target.read_bytes()
            records = self.records(target)
            header, *rows = records
            cases = {
                "blank-head": "\n" + csv_text(records),
                "blank-middle": csv_text([header]) + "\r\n" + csv_text(rows),
                "blank-tail": csv_text(records) + "\n",
                "whitespace-middle": csv_text([header]) + " \t\r\n" + csv_text(rows),
                "whitespace-eof": csv_text(records) + " \t",
                "all-empty": csv_text(records + [[""] * len(header)]),
                "all-whitespace": csv_text(records + [[" \t"] * len(header)]),
                "all-quoted-whitespace": csv_text(records + [[" \n\r\n\r"] * len(header)]),
                "missing-field": csv_text([header, rows[0][:-1], *rows[1:]]),
                "extra-field": csv_text([header, rows[0] + ["extra"], *rows[1:]]),
                "empty-header": csv_text([header + [""], *[row + ["value"] for row in rows]]),
                "whitespace-header": csv_text([header + [" \t"], *[row + ["value"] for row in rows]]),
                "duplicate-header": csv_text([header + [header[0]], *[row + [row[0]] for row in rows]]),
                "case-duplicate-header": csv_text([header + [header[0].upper()], *[row + [row[0]] for row in rows]]),
            }
            try:
                for layout, skill in self.layouts.items():
                    target.write_bytes(original)
                    self.assert_valid_control(skill)
                    for case, text in cases.items():
                        with self.subTest(target=target.name, layout=layout, case=case):
                            target.write_bytes(text.encode("utf-8"))
                            self.assert_refused(skill, "CSV" if "header" in case or "blank" in case else "validation failed")
            finally:
                target.write_bytes(original)

    def test_utf8_bom_unicode_quoted_headers_and_terminal_controls(self) -> None:
        for target in (self.fixture.mapping, self.fixture.root / "video.csv"):
            original = target.read_bytes()
            records = self.records(target)
            note = '  café Δ 漢字 🙂, "quote"\n\nLF\r\n\r\nCRLF\r\rCR  '
            records = [records[0] + ["csv_note"], *[row + [note] for row in records[1:]]]
            stream = io.StringIO(newline="")
            csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\r\n").writerows(records)
            base = "\ufeff" + stream.getvalue().removesuffix("\r\n")
            try:
                for layout, skill in self.layouts.items():
                    for terminal in ("", "\n", "\r\n"):
                        with self.subTest(target=target.name, layout=layout, terminal=repr(terminal)):
                            target.write_bytes((base + terminal).encode("utf-8"))
                            self.assert_valid_control(skill)
            finally:
                target.write_bytes(original)

    def assert_encoding_refused(self, target: Path, invalid: bytes) -> None:
        records = self.records(target)
        records = [records[0] + ["encoding_note"], *[row + ["ENCODING_NOTE"] for row in records[1:]]]
        valid = csv_text(records).encode("utf-8")
        for layout, skill in self.layouts.items():
            with self.subTest(layout=layout):
                target.write_bytes(valid)
                self.assert_valid_control(skill)
                malformed = valid.replace(b"ENCODING_NOTE", invalid, 1)
                self.assertNotEqual(malformed, valid)
                target.write_bytes(malformed)
                self.assert_refused(skill, "CSV")
        target.write_bytes(valid)

    def test_mapping_rejects_invalid_utf8_bytes(self) -> None:
        self.assert_encoding_refused(self.fixture.mapping, b"\xff")

    def test_deliverable_rejects_invalid_utf8_bytes(self) -> None:
        self.assert_encoding_refused(self.fixture.root / "video.csv", b"\xff")

    def assert_utf16_refused(self, target: Path) -> None:
        valid = target.read_bytes()
        for layout, skill in self.layouts.items():
            with self.subTest(layout=layout):
                target.write_bytes(valid)
                self.assert_valid_control(skill)
                target.write_bytes(valid.decode("utf-8").encode("utf-16"))
                self.assert_refused(skill, "CSV")
        target.write_bytes(valid)

    def test_mapping_rejects_utf16_bom(self) -> None:
        self.assert_utf16_refused(self.fixture.mapping)

    def test_deliverable_rejects_utf16_bom(self) -> None:
        self.assert_utf16_refused(self.fixture.root / "video.csv")

    def test_mapping_and_deliverable_reject_other_invalid_utf8_sequences(self) -> None:
        for target in (self.fixture.mapping, self.fixture.root / "video.csv"):
            original = target.read_bytes()
            for invalid in (b"\xc0\xaf", b"\xe2\x82", b"\xed\xa0\x80", b"\xf4\x90\x80\x80"):
                with self.subTest(target=target.name, invalid=invalid.hex()):
                    self.assert_encoding_refused(target, invalid)
                target.write_bytes(original)

    def test_mapping_and_deliverable_reject_other_unicode_boms(self) -> None:
        for target in (self.fixture.mapping, self.fixture.root / "video.csv"):
            valid = target.read_bytes()
            for codec, bom in (
                ("utf-16-be", b"\xfe\xff"),
                ("utf-32-le", b"\xff\xfe\x00\x00"),
                ("utf-32-be", b"\x00\x00\xfe\xff"),
            ):
                for layout, skill in self.layouts.items():
                    with self.subTest(target=target.name, layout=layout, codec=codec):
                        target.write_bytes(valid)
                        self.assert_valid_control(skill)
                        target.write_bytes(bom + valid.decode("utf-8").encode(codec))
                        self.assert_refused(skill, "CSV")
            target.write_bytes(valid)


if __name__ == "__main__":
    unittest.main()
