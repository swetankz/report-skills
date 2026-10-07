from __future__ import annotations

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


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PORTABILITY = load_module(
    REPO_ROOT / "scripts" / "test_standalone_packages.py", "standalone_portability_contract"
)
SOURCE_FIXTURE = load_module(
    REPO_ROOT / "tests" / "test_repurposer_validation.py", "portable_repurposer_fixture"
)


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class RuntimePathContractTests(unittest.TestCase):
    def make_skill(self, root: Path, *, body: str = "", reference: str = "") -> Path:
        skill = root / "synthetic-skill"
        (skill / "agents").mkdir(parents=True)
        (skill / "references").mkdir()
        (skill / "scripts").mkdir()
        (skill / "SKILL.md").write_text(body, encoding="utf-8")
        (skill / "agents" / "openai.yaml").write_text("interface: {}\n", encoding="utf-8")
        (skill / "references" / "workflow.md").write_text(reference, encoding="utf-8")
        return skill

    def test_benchmark_only_paths_fail_in_bodies_and_operating_references(self) -> None:
        old_paths = (
            ".benchmark_skill/evidence-first-report/scripts/write-register-csv.ps1",
            ".benchmark_skill/editorial-data-storytelling/scripts/write-register-csv.ps1",
            ".benchmark_skill/report-content-repurposer/scripts/validate_derivative_package.ps1",
            r".benchmark_skill\evidence-first-report\scripts\write-register-csv.ps1",
        )
        for old_path in old_paths:
            for location in ("body", "reference"):
                with self.subTest(path=old_path, location=location), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    skill = self.make_skill(root, **{location: f"Run `{old_path}`.\n"})
                    errors = PORTABILITY.validate_isolated_skill(skill, root / "isolated")
                    self.assertTrue(any("benchmark-only runtime path" in error for error in errors), errors)

    def test_bundled_script_declarations_require_regular_installed_targets(self) -> None:
        for declaration in (
            "Use `scripts/missing.ps1`.",
            "Read [helper](scripts/missing.ps1).",
            "python scripts/missing.py input.json",
            r"Use `scripts\missing.ps1`.",
        ):
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as temp:
                skill = self.make_skill(Path(temp), reference=declaration)
                errors = PORTABILITY.validate_runtime_paths(skill)
                self.assertTrue(any("unresolved bundled script" in error for error in errors), errors)
                for target in PORTABILITY.declared_script_targets(declaration):
                    (skill / target).mkdir()
                self.assertTrue(PORTABILITY.validate_runtime_paths(skill))

    def test_rooted_helper_declarations_pass_in_independent_layouts(self) -> None:
        for layout in (Path("plugins/report-skills/skills"), Path(".agents/skills")):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = self.make_skill(
                    root / "source",
                    body="Run [strict writer](scripts/writer.ps1), anchored at the loaded SKILL.md.\n",
                    reference="Use `scripts/writer.ps1` from that same skill directory.\n",
                )
                (source / "scripts" / "writer.ps1").write_text("Write-Output 'synthetic'\n", encoding="utf-8")
                self.assertEqual(PORTABILITY.validate_isolated_skill(source, root / layout), [])
                installed = root / layout / source.name
                self.assertEqual(PORTABILITY.validate_runtime_paths(installed), [])
                self.assertFalse((root / ".benchmark_skill").exists())

    def test_literal_task_relative_helper_commands_fail_even_when_helper_is_bundled(self) -> None:
        commands = (
            "python scripts/summarize_frame_intervals.py <trace-file>",
            "python3 -B './scripts/summarize_frame_intervals.py' trace.json",
            'python.exe "scripts/summarize_frame_intervals.py" trace.json',
            "pwsh -NoProfile -File scripts/writer.ps1 -OutputPath artifacts/register.csv",
            r"powershell.exe -NoProfile -File '.\scripts\writer.ps1'",
            "node scripts/helper.mjs input.json",
        )
        for command in commands:
            for location in ("body", "reference"):
                with self.subTest(command=command, location=location), tempfile.TemporaryDirectory() as temp:
                    skill = self.make_skill(Path(temp), **{location: f"Run `{command}`.\n"})
                    targets = PORTABILITY.declared_script_targets(command)
                    self.assertTrue(targets)
                    for target in targets:
                        (skill / target).write_text("synthetic bundled helper\n", encoding="utf-8")
                    errors = PORTABILITY.validate_runtime_paths(skill)
                    self.assertTrue(any("task-relative helper command" in error for error in errors), errors)
                    self.assertFalse(any("unresolved bundled script" in error for error in errors), errors)

    def test_explicit_rooted_variable_and_absolute_helper_commands_are_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill = self.make_skill(
                Path(temp),
                body="Resolve `scripts/helper.py` from the activated SKILL.md directory.\n",
                reference=(
                    "python \"<absolute-helper-path>\" trace.json\n"
                    "$helper = Join-Path $skillRoot 'scripts/helper.py'\n"
                    "python $helper trace.json\n"
                ),
            )
            (skill / "scripts" / "helper.py").write_text("# synthetic helper\n", encoding="utf-8")
            self.assertEqual(PORTABILITY.validate_runtime_paths(skill), [])

    def test_all_generated_runtime_documents_are_portable(self) -> None:
        for skill in sorted((REPO_ROOT / "skills").iterdir()):
            if skill.is_dir():
                with self.subTest(skill=skill.name), tempfile.TemporaryDirectory() as temp:
                    self.assertEqual(PORTABILITY.validate_isolated_skill(skill, Path(temp)), [])


class InstalledHelperExecutionTests(unittest.TestCase):
    def copy_installed_skill(self, root: Path, layout: Path, name: str) -> Path:
        installed = root / layout / name
        shutil.copytree(REPO_ROOT / "skills" / name, installed)
        self.assertEqual(PORTABILITY.validate_runtime_paths(installed), [])
        self.assertFalse((root / ".benchmark_skill").exists())
        self.assertFalse((root / "source").exists())
        return installed

    def declared_helper(self, installed: Path, filename: str) -> Path:
        # Resolve the declared target from the actual loaded SKILL.md directory,
        # never from the task cwd or a benchmark alias.
        document = installed / "SKILL.md"
        targets = PORTABILITY.declared_script_targets(document.read_text(encoding="utf-8"))
        target = f"scripts/{filename}"
        self.assertIn(target, targets)
        helper = document.parent / target
        self.assertTrue(helper.is_file())
        return helper

    def test_installed_motion_summarizer_uses_task_relative_trace_without_mutating_skill(self) -> None:
        interval_summary = {
            "method": "nearest-rank", "unit": "ms", "sample_count": 5,
            "mean_ms": 36.72, "median_ms": 33.4, "p95_ms": 66.8,
            "max_ms": 66.8, "over_33_4_ms": 2, "over_50_ms": 1,
        }
        timestamp_summary = {
            "method": "nearest-rank", "unit": "ms", "sample_count": 5,
            "mean_ms": 32.0, "median_ms": 30.0, "p95_ms": 60.0,
            "max_ms": 60.0, "over_33_4_ms": 2, "over_50_ms": 1,
        }
        valid = (
            ("intervals.json", json.dumps({"intervals_ms": [16.7, 16.7, 33.4, 50, 66.8]}), interval_summary),
            ("timestamps.csv", "timestamp_ms\n0\n10\n30\n60\n100\n160\n", timestamp_summary),
        )
        invalid = (
            ("boolean.json", '{"intervals_ms": [true, 16]}', "numeric"),
            ("zero.json", '{"intervals_ms": [0, 16]}', "greater than zero"),
            ("nonfinite.json", '{"intervals_ms": [NaN, 16]}', "finite"),
            ("unordered.csv", "timestamp_ms\n0\n10\n10\n", "strictly increasing"),
            ("empty.json", '[]', "at least one interval"),
        )
        for layout in (Path("plugins/report-skills/skills"), Path(".agents/skills")):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                installed = self.copy_installed_skill(root, layout, "motion-performance-qa")
                before = file_hashes(installed)
                helper = self.declared_helper(installed, "summarize_frame_intervals.py")
                task = root / "task"
                task.mkdir()
                for name, content, expected in valid:
                    with self.subTest(trace=name):
                        (task / name).write_text(content, encoding="utf-8")
                        task_before = file_hashes(task)
                        result = subprocess.run(
                            [sys.executable, str(helper), name], cwd=task,
                            capture_output=True, text=True, check=False, timeout=30,
                        )
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(json.loads(result.stdout), expected)
                        self.assertEqual(file_hashes(task), task_before)
                        self.assertEqual(file_hashes(installed), before)
                for name, content, expected_error in invalid:
                    with self.subTest(invalid_trace=name):
                        (task / name).write_text(content, encoding="utf-8")
                        task_before = file_hashes(task)
                        rejected = subprocess.run(
                            [sys.executable, str(helper), name], cwd=task,
                            capture_output=True, text=True, check=False, timeout=30,
                        )
                        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
                        self.assertEqual(rejected.stdout, "")
                        self.assertIn(expected_error, rejected.stderr)
                        self.assertEqual(file_hashes(task), task_before)
                        self.assertEqual(file_hashes(installed), before)
                self.assertFalse((task / "scripts").exists())
                self.assertFalse((task / ".benchmark_skill").exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_installed_csv_writers_use_task_relative_paths_and_preserve_strictness(self) -> None:
        header = ["claim_id", "claim_text"]
        rows = [
            {"claim_id": "C1", "claim_text": 'Comma, quote " and line\nbreak'},
            {"claim_id": "C2", "claim_text": "Second row"},
        ]
        for layout in (Path("plugins/report-skills/skills"), Path(".agents/skills")):
            for name in ("evidence-first-report", "editorial-data-storytelling"):
                with self.subTest(layout=layout, skill=name), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    installed = self.copy_installed_skill(root, layout, name)
                    before = file_hashes(installed)
                    helper = self.declared_helper(installed, "write-register-csv.ps1")
                    task = root / "task"
                    task.mkdir()
                    payload = task / "register-data.json"
                    payload.write_text(json.dumps({"header": header, "rows": rows}), encoding="utf-8")
                    command = [
                        shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(helper),
                        "-InputJsonPath", payload.name, "-OutputPath", "artifacts/register.csv",
                    ]
                    result = subprocess.run(command, cwd=task, capture_output=True, text=True, check=False, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    with (task / "artifacts" / "register.csv").open(encoding="utf-8", newline="") as stream:
                        records = list(csv.reader(stream, strict=True))
                    self.assertEqual(records, [header, *[[row[key] for key in header] for row in rows]])
                    self.assertEqual(file_hashes(installed), before)
                    self.assertFalse((installed / "artifacts").exists())
                    for bad_rows in ([{"claim_id": "C1"}], [{"claim_id": " ", "claim_text": "\t"}]):
                        payload.write_text(json.dumps({"header": header, "rows": bad_rows}), encoding="utf-8")
                        rejected = subprocess.run(command, cwd=task, capture_output=True, text=True, check=False, timeout=30)
                        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
                    self.assertEqual(file_hashes(installed), before)
                    self.assertFalse((task / ".benchmark_skill").exists())

    def test_installed_repurposer_python_validator_preserves_complete_source_contract(self) -> None:
        self.run_repurposer_relocation(powershell=False)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_installed_repurposer_powershell_validator_preserves_complete_source_contract(self) -> None:
        self.run_repurposer_relocation(powershell=True)

    def run_repurposer_relocation(self, *, powershell: bool) -> None:
        for layout in (Path("plugins/report-skills/skills"), Path(".agents/skills")):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                installed = self.copy_installed_skill(root, layout, "report-content-repurposer")
                before = file_hashes(installed)
                if powershell:
                    helper = self.declared_helper(installed, "validate_derivative_package.ps1")
                else:
                    helper = installed / "scripts" / "validate_derivative_package.py"
                    self.assertTrue(helper.is_file())
                # Reuse the existing wholly synthetic, source-complete fixture;
                # copy its local task data, not its repository validator path.
                fixture = SOURCE_FIXTURE.RepurposerSourceContractTests()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                task = root / "task"
                shutil.copytree(fixture.root.parent, task)
                self.assertFalse((task / "source").exists())
                self.assertFalse((task / ".benchmark_skill").exists())
                if powershell:
                    command = [
                        shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(helper),
                        "-ArtifactsRoot", "artifacts", "-Mapping", "artifacts/claim-mapping.csv",
                        "-Deliverables", "post.md,derivative-manifest.yaml", "-SourceReport", "source.md",
                        "-SourceInventory", "artifacts/source-inventory.json",
                        "-StatementSupport", "artifacts/statement-support.csv",
                    ]
                else:
                    command = [
                        sys.executable, str(helper), "--artifacts-root", "artifacts", "--mapping", "artifacts/claim-mapping.csv",
                        "--deliverable", "post.md", "--deliverable", "derivative-manifest.yaml", "--source-report", "source.md",
                        "--source-inventory", "artifacts/source-inventory.json", "--statement-support", "artifacts/statement-support.csv",
                    ]
                task_before = file_hashes(task)
                result = subprocess.run(command, cwd=task, capture_output=True, text=True, check=False, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("source-inventory records reconcile", result.stdout)
                self.assertIn("semantic support remains", result.stdout)
                self.assertEqual(file_hashes(task), task_before)
                self.assertEqual(file_hashes(installed), before)
                # An incorrect source hash must still fail after relocation;
                # portability must not weaken provenance validation.
                source = task / "source.md"
                source.write_text(source.read_text(encoding="utf-8") + "Unregistered synthetic claim.\n", encoding="utf-8")
                rejected = subprocess.run(command, cwd=task, capture_output=True, text=True, check=False, timeout=30)
                self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
                self.assertIn("hash", (rejected.stdout + rejected.stderr).casefold())
                self.assertEqual(file_hashes(installed), before)


if __name__ == "__main__":
    unittest.main()
