from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_skills.py"
SCAN_SCRIPT = REPO_ROOT / "scripts" / "scan_public_content.py"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "create_release_package.py"
SOURCE_SNAPSHOT_SCRIPT = REPO_ROOT / "scripts" / "create_source_snapshot.py"
RELEASE_INVENTORY_SCRIPT = REPO_ROOT / "scripts" / "release_inventory.py"
VERIFY_RELEASE_SCRIPT = REPO_ROOT / "scripts" / "verify_release_artifacts.py"
EXPECTED_SKILLS = {
    "report-skills",
    "evidence-first-report",
    "editorial-data-storytelling",
    "report-visual-system",
    "interactive-report-publisher",
    "visual-hygiene-auditor",
    "motion-performance-qa",
    "report-content-repurposer",
    "sites-release-manager",
    "pencil-safe-editor",
    "creative-artifact-provenance",
}
EXPLICIT_ONLY = {"report-skills", "sites-release-manager", "pencil-safe-editor"}


def load_script_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
    )


def initialize_git_repo(repo: Path) -> None:
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Synthetic Release Test")
    git(repo, "config", "user.email", "release-test@example.invalid")


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ToolingTests(unittest.TestCase):
    def test_plugin_and_tooling_versions_match(self) -> None:
        plugin = json.loads(
            (REPO_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], project["project"]["version"])

    def test_skill_map_has_exact_inventory(self) -> None:
        mapping = json.loads((REPO_ROOT / "source" / "skill-map.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(mapping["skills"]), EXPECTED_SKILLS)

    def test_generator_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            first = Path(temp_name) / "first"
            second = Path(temp_name) / "second"
            for output in (first, second):
                result = subprocess.run(
                    [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(tree_hashes(first), tree_hashes(second))

    def test_generated_packages_have_no_parent_traversal(self) -> None:
        for skill in sorted(EXPECTED_SKILLS):
            root = REPO_ROOT / "skills" / skill
            self.assertTrue(root.is_dir(), skill)
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.casefold() in {".md", ".yaml", ".yml", ".json", ".py"}:
                    self.assertNotIn("../", path.read_text(encoding="utf-8"), path.as_posix())

    def test_explicit_only_skills_publish_activation_boundary(self) -> None:
        for tree in (REPO_ROOT / "source" / "skills", REPO_ROOT / "skills"):
            for skill in sorted(EXPLICIT_ONLY):
                text = (tree / skill / "SKILL.md").read_text(encoding="utf-8")
                description = next(
                    line for line in text.splitlines() if line.startswith("description:")
                )
                self.assertTrue(description.startswith('description: "'), skill)
                self.assertTrue(description.endswith('"'), skill)
                self.assertIn("Explicit invocation only:", description, skill)
                self.assertIn(f"${skill}", description, skill)
                self.assertIn(
                    "topical requests without that token must not activate it",
                    description,
                    skill,
                )
                metadata = (tree / skill / "agents" / "openai.yaml").read_text(
                    encoding="utf-8"
                )
                short_description = next(
                    line.strip()
                    for line in metadata.splitlines()
                    if line.strip().startswith("short_description:")
                )
                self.assertIn('short_description: "Explicit-only:', short_description, skill)
                self.assertIn(f"${skill}", short_description, skill)

    def test_evidence_report_records_a_disposition_for_every_review_pass(self) -> None:
        required_instruction = (
            "Create at least one `revision-log.md` entry linked to a finding from each "
            "of the three passes. If a pass warrants no artifact change, record a "
            "verified no-change disposition with its evidence instead of inventing a revision."
        )
        for tree in (REPO_ROOT / "source" / "skills", REPO_ROOT / "skills"):
            text = (tree / "evidence-first-report" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(required_instruction, text)

    def test_evidence_report_withholds_incomplete_quantitative_claims(self) -> None:
        required_instructions = (
            "Where a supplied source- or dataset-level period demonstrably applies",
            "Never substitute the report window, cutoff, publication date, or retrieval date",
            (
                "If no defensible evidence period exists, treat the quantitative support as "
                "incomplete and withhold the quantitative claim from the draft"
            ),
        )
        for path in (
            REPO_ROOT / "source" / "skills" / "evidence-first-report" / "references" / "evidence-model.md",
            REPO_ROOT / "skills" / "evidence-first-report" / "references" / "evidence-model.md",
        ):
            text = path.read_text(encoding="utf-8")
            for instruction in required_instructions:
                self.assertIn(instruction, text)

    def test_evidence_report_registers_derived_quantities_from_reviews(self) -> None:
        evidence_instructions = (
            (
                "Treat every computed or comparative number as a quantitative claim, including "
                "totals, rates, ranges, differences, durations, date intervals, and relative-time "
                "statements."
            ),
            (
                "This rule also applies to quantitative wording introduced during any review "
                "or revision."
            ),
            (
                "Before the wording enters the draft, register every input under source and "
                "evidence identifiers and record the reproducible calculation with an explicit "
                "unit, population (use `not applicable` only when genuinely inapplicable), and period."
            ),
            (
                "Otherwise omit the number or retain it only as an unresolved blocker without "
                "asserting it."
            ),
        )
        for path in (
            REPO_ROOT / "source" / "skills" / "evidence-first-report" / "references" / "evidence-model.md",
            REPO_ROOT / "skills" / "evidence-first-report" / "references" / "evidence-model.md",
        ):
            text = path.read_text(encoding="utf-8")
            for instruction in evidence_instructions:
                self.assertIn(instruction, text)

        review_instruction = (
            "After every review pass, rescan changed prose for newly introduced numbers, "
            "date comparisons, durations, and other computed quantities. Update the source, "
            "evidence, and claim registers before accepting the revision, or remove the "
            "quantitative wording when it is not fully registered."
        )
        for tree in (REPO_ROOT / "source" / "skills", REPO_ROOT / "skills"):
            text = (tree / "evidence-first-report" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(review_instruction, text)

    def test_evidence_report_requires_csv_round_trip_validation(self) -> None:
        required_instructions = (
            "Write every register with a CSV serializer or equivalent standards-compliant escaping",
            "Quote fields containing a comma, double quote, carriage return, or line break",
            "Re-open each written CSV with a parser",
            "require every data row to have exactly the header's column count",
            "Treat any mismatch as a blocking artifact error",
        )
        for path in (
            REPO_ROOT / "source" / "skills" / "evidence-first-report" / "references" / "evidence-model.md",
            REPO_ROOT / "skills" / "evidence-first-report" / "references" / "evidence-model.md",
        ):
            text = path.read_text(encoding="utf-8")
            for instruction in required_instructions:
                self.assertIn(instruction, text)
        expected_header = (
            "claim_id,claim_text,claim_type,importance,status,source_ids,evidence_ids,"
            "location,quantitative,cutoff_status,conflict_status,confidence,review_notes"
        )
        for path in (
            REPO_ROOT / "templates" / "claim-ledger.csv",
            REPO_ROOT / "skills" / "evidence-first-report" / "assets" / "templates" / "claim-ledger.csv",
        ):
            self.assertEqual(path.read_text(encoding="utf-8").strip(), expected_header)

    def test_shipped_csv_fixtures_and_templates_are_rectangular(self) -> None:
        paths = sorted(
            {
                *(REPO_ROOT / "examples" / "synthetic-report" / "inputs").rglob("*.csv"),
                *(REPO_ROOT / "templates").glob("*.csv"),
                *(REPO_ROOT / "skills").glob("*/assets/templates/*.csv"),
            }
        )
        self.assertGreaterEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path.relative_to(REPO_ROOT).as_posix()):
                with path.open("r", encoding="utf-8", newline="") as handle:
                    rows = list(csv.reader(handle, strict=True))
                self.assertTrue(rows, "CSV must contain a header")
                width = len(rows[0])
                self.assertGreater(width, 0, "CSV header must not be empty")
                for row_number, row in enumerate(rows[1:], start=2):
                    self.assertEqual(len(row), width, f"row {row_number} width")
                    self.assertTrue(
                        any(value.strip() for value in row),
                        f"row {row_number} must not be logically blank",
                    )

    def test_shared_validation_conventions_reject_blank_csv_records(self) -> None:
        required = (
            "Write CSV files with a standards-compliant serializer",
            "Require a nonempty header and exactly the header's field count in every logical record",
            "Treat a zero-field or whitespace-only logical record anywhere",
            "one terminal LF or CRLF",
            "preserve embedded line breaks and blank physical lines only inside properly quoted fields",
            "Do not rely on importers that silently drop empty records",
        )
        paths = [REPO_ROOT / "source" / "shared" / "validation-conventions.md"]
        paths.extend(
            sorted((REPO_ROOT / "skills").glob("*/references/validation-conventions.md"))
        )
        self.assertEqual(len(paths), len(EXPECTED_SKILLS) + 1)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for instruction in required:
                self.assertIn(instruction, text)

    def test_benchmark_schema_declares_contract_bound_artifact_checks(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "evals" / "schemas" / "benchmark-suite.schema.json").read_text(
                encoding="utf-8"
            )
        )
        artifact_schema = schema["$defs"]["artifactCheck"]
        self.assertFalse(artifact_schema["additionalProperties"])
        self.assertEqual(artifact_schema["properties"]["type"]["const"], "csv_rectangular")
        for case_type in ("primaryCase", "adversarialCase"):
            self.assertEqual(
                schema["$defs"][case_type]["properties"]["artifact_checks"]["items"]["$ref"],
                "#/$defs/artifactCheck",
            )
        suite = json.loads(
            (REPO_ROOT / "evals" / "benchmark-suite.json").read_text(encoding="utf-8")
        )
        evidence_case = next(
            case for case in suite["primary_cases"] if case["case_id"] == "evidence-report"
        )
        self.assertEqual(len(evidence_case["artifact_checks"]), 3)
        self.assertTrue(
            all(
                check["configurations"] == ["with_skill"]
                for check in evidence_case["artifact_checks"]
            )
        )

    def test_evidence_report_reviewer_identity_requires_execution_evidence(self) -> None:
        required_instructions = (
            "reviewer` must name only an actor evidenced by the execution record",
            "Do not claim a sub-agent, independent reviewer, human, peer, or external reviewer",
            "identify it as self-review and disclose that the pass was not independent",
            "use `not-verified` if actor provenance cannot be established",
        )
        for path in (
            REPO_ROOT / "source" / "skills" / "evidence-first-report" / "references" / "review-and-release-protocol.md",
            REPO_ROOT / "skills" / "evidence-first-report" / "references" / "review-and-release-protocol.md",
        ):
            text = path.read_text(encoding="utf-8")
            for instruction in required_instructions:
                self.assertIn(instruction, text)
        for path in (
            REPO_ROOT / "templates" / "review-log.md",
            REPO_ROOT / "skills" / "evidence-first-report" / "assets" / "templates" / "review-log.md",
        ):
            template = path.read_text(encoding="utf-8")
            self.assertIn("Reviewer provenance: `not-verified`", template)
            self.assertIn("disclose self-review rather than claiming independence", template)

    def test_scanner_detects_sensitive_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            private_path = "C:" + "\\Users\\sample-person\\report"
            secret_assignment = "access_" + "token='synthetic-but-secret-value'"
            (root / "unsafe.txt").write_text(
                f"private path {private_path}\n{secret_assignment}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("windows-user-path", result.stdout)
            self.assertIn("assigned-secret", result.stdout)

    def test_scanner_allows_approved_public_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "metadata.md").write_text(
                "Author: Swetank Gawde\nRepository: https://github.com/swetankz/report-skills\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scanner_allows_declared_placeholder_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            fixture = root / "intentional-defects"
            fixture.mkdir()
            (fixture / "draft.md").write_text("TODO: synthetic defect\nTBD: synthetic defect\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scanner_ignores_uncommitted_evaluation_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            raw = root / "evals" / "runs" / "local-observation"
            raw.mkdir(parents=True)
            private_path = "C:" + "\\Users\\sample-person\\private"
            (raw / "transcript.json").write_text(
                json.dumps({"workspace": private_path}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scanner_ignores_its_copied_pattern_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(SCAN_SCRIPT, scripts / "scan_public_content.py")
            result = subprocess.run(
                [sys.executable, str(SCAN_SCRIPT), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_authorization_tag_must_match_version(self) -> None:
        for script in (RELEASE_SCRIPT, SOURCE_SNAPSHOT_SCRIPT):
            result = subprocess.run(
                [sys.executable, str(script), "--authorized-release-tag", "v9.9.9"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0, script.name)
            self.assertIn("does not match plugin version", result.stdout + result.stderr)

    def test_plugin_package_markdown_links_close_over_the_selected_inventory(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "test_release_inventory_link_closure"
        )
        with mock.patch.dict(sys.modules, {"release_inventory": inventory_module}):
            release_module = load_script_module(
                RELEASE_SCRIPT, "test_create_release_package_link_closure"
            )

        self.assertIn("docs/evaluation.md", release_module.DOC_FILES)
        self.assertNotIn("docs/release-checklist.md", release_module.DOC_FILES)
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            stage = root / "stage"
            stage.mkdir()
            (stage / "README.md").write_text(
                "See the [evaluation protocol](docs/evaluation.md).\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                SystemExit, "missing packaged local Markdown target"
            ):
                release_module.validate_packaged_local_links(stage)

            evaluation = stage / "docs" / "evaluation.md"
            evaluation.parent.mkdir()
            evaluation.write_text("# Evaluation\n", encoding="utf-8")
            release_module.validate_packaged_local_links(stage)

            (stage / "README.md").write_text(
                "[Outside](../outside.md)\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                SystemExit, "packaged local Markdown target leaves the archive"
            ):
                release_module.validate_packaged_local_links(stage)

    def test_release_artifact_verifier_checks_manifest_and_zip_metadata(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "test_release_inventory_verifier"
        )
        with mock.patch.dict(sys.modules, {"release_inventory": inventory_module}):
            verifier = load_script_module(
                VERIFY_RELEASE_SCRIPT, "test_verify_release_artifacts"
            )

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            archive = root / "report-skills-0.2.0.zip"
            payload = b"public source\n"
            manifest = {
                "schema_version": 1,
                "plugin": "report-skills",
                "version": "0.2.0",
                "publication_state": "local-candidate",
                "external_publication_authorized": False,
                "files": {"README.md": hashlib.sha256(payload).hexdigest()},
            }

            def write_archive(path: Path, timestamp: tuple[int, ...]) -> None:
                with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as output:
                    for name, content in (
                        ("README.md", payload),
                        (
                            "RELEASE_MANIFEST.json",
                            (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8"),
                        ),
                    ):
                        info = zipfile.ZipInfo(name, date_time=timestamp)
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.external_attr = 0o100644 << 16
                        output.writestr(info, content)

            write_archive(archive, (1980, 1, 1, 0, 0, 0))
            sidecar = archive.with_suffix(".zip.sha256")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")

            self.assertEqual(verifier.verify_sidecar(archive, sidecar), digest)
            result = verifier.verify_archive(
                archive,
                "RELEASE_MANIFEST.json",
                ["README.md"],
                "0.2.0",
                None,
            )
            self.assertEqual(result["entry_count"], 2)
            self.assertFalse(result["publication_authorized"])

            manifest["plugin"] = "wrong-plugin"
            write_archive(archive, (1980, 1, 1, 0, 0, 0))
            with self.assertRaisesRegex(SystemExit, "plugin identity mismatch"):
                verifier.verify_archive(
                    archive,
                    "RELEASE_MANIFEST.json",
                    ["README.md"],
                    "0.2.0",
                    None,
                )

            manifest["plugin"] = "report-skills"
            write_archive(archive, (2026, 8, 15, 0, 0, 0))
            with self.assertRaisesRegex(SystemExit, "Non-deterministic ZIP timestamp"):
                verifier.verify_archive(
                    archive,
                    "RELEASE_MANIFEST.json",
                    ["README.md"],
                    "0.2.0",
                    None,
                )

            source_archive = root / "report-skills-source-0.2.0.zip"
            source_manifest = {
                "schema_version": 1,
                "project": "report-skills",
                "version": "0.2.0",
                "snapshot_type": "intended-public-repository-tree",
                "publication_state": "local-source-candidate",
                "git_history_present": False,
                "external_publication_authorized": False,
                "files": {"README.md": hashlib.sha256(payload).hexdigest()},
            }
            with zipfile.ZipFile(
                source_archive, "w", compression=zipfile.ZIP_DEFLATED
            ) as output:
                for name, content in (
                    ("README.md", payload),
                    (
                        "SOURCE_SNAPSHOT_MANIFEST.json",
                        (json.dumps(source_manifest, sort_keys=True) + "\n").encode(
                            "utf-8"
                        ),
                    ),
                ):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    output.writestr(info, content)
            with self.assertRaisesRegex(SystemExit, "file count mismatch"):
                verifier.verify_archive(
                    source_archive,
                    "SOURCE_SNAPSHOT_MANIFEST.json",
                    ["README.md"],
                    "0.2.0",
                    None,
                )

    def test_release_builders_sort_zip_entries_by_posix_name(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "test_release_inventory_zip_order"
        )
        with mock.patch.dict(sys.modules, {"release_inventory": inventory_module}):
            modules = (
                load_script_module(RELEASE_SCRIPT, "test_release_zip_order"),
                load_script_module(SOURCE_SNAPSHOT_SCRIPT, "test_source_zip_order"),
            )
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            stage = root / "stage"
            stage.mkdir()
            for relative in ("z.txt", "docs/a.txt", "A.txt", ".meta/data.json"):
                path = stage / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative + "\n", encoding="utf-8")
            expected = sorted(
                path.relative_to(stage).as_posix()
                for path in stage.rglob("*")
                if path.is_file()
            )
            for index, module in enumerate(modules):
                archive = root / f"archive-{index}.zip"
                module.deterministic_zip(stage, archive)
                with zipfile.ZipFile(archive, "r") as source:
                    self.assertEqual(source.namelist(), expected)

    def test_release_inventory_uses_clean_head_and_ignores_local_artifacts(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "test_release_inventory_clean"
        )
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            repo = root / "repo"
            first = root / "first"
            second = root / "second"
            initialize_git_repo(repo)
            (repo / ".gitignore").write_text(
                "/.coverage\n/evals/runs/\n/evals/review/\n**/private.txt\n",
                encoding="utf-8",
            )
            (repo / "README.md").write_text("tracked public source\n", encoding="utf-8")
            git(repo, "add", ".gitignore", "README.md")
            git(repo, "commit", "--quiet", "-m", "public source")

            ignored_files = (
                repo / ".coverage",
                repo / "evals" / "runs" / "local" / "transcript.jsonl",
                repo / "evals" / "review" / "local" / "notes.json",
                repo / "skills" / "example" / "private.txt",
            )
            for path in ignored_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private local material\n", encoding="utf-8")

            inventory = inventory_module.tracked_head_inventory(repo)
            self.assertEqual(
                {item.path.as_posix() for item in inventory},
                {".gitignore", "README.md"},
            )
            inventory_module.copy_inventory(repo, first, inventory)
            inventory_module.copy_inventory(repo, second, inventory)
            self.assertEqual(tree_hashes(first), tree_hashes(second))
            self.assertEqual(set(tree_hashes(first)), {".gitignore", "README.md"})

    def test_release_inventory_rejects_tracked_raw_evaluation_paths(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "test_release_inventory_raw"
        )
        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name) / "repo"
            initialize_git_repo(repo)
            (repo / ".gitignore").write_text(
                "/EVALS/RUNS/\n/EVALS/REVIEW/\n", encoding="utf-8"
            )
            (repo / "README.md").write_text("public source\n", encoding="utf-8")
            run_raw = repo / "EVALS" / "RUNS" / "local" / "transcript.jsonl"
            review_raw = repo / "EVALS" / "REVIEW" / "local" / "notes.json"
            run_raw.parent.mkdir(parents=True)
            review_raw.parent.mkdir(parents=True)
            run_raw.write_text("raw run evidence\n", encoding="utf-8")
            review_raw.write_text("raw review evidence\n", encoding="utf-8")
            git(repo, "add", ".gitignore", "README.md")
            git(
                repo,
                "add",
                "-f",
                "EVALS/RUNS/local/transcript.jsonl",
                "EVALS/REVIEW/local/notes.json",
            )
            git(repo, "commit", "--quiet", "-m", "unsafe source")

            with self.assertRaisesRegex(SystemExit, "EVALS/REVIEW/local/notes.json"):
                inventory_module.tracked_head_inventory(repo)

    def test_release_inventory_rejects_nonregular_entries_and_allows_lookalikes(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "test_release_inventory_modes"
        )
        object_id = b"0" * 40
        allowed = inventory_module._parse_tree(
            b"100644 blob " + object_id + b"\tevals/runs-public/result.json\0"
        )
        self.assertEqual(allowed[0].path.as_posix(), "evals/runs-public/result.json")
        with self.assertRaisesRegex(SystemExit, "non-regular tracked release entry"):
            inventory_module._parse_tree(
                b"120000 blob " + object_id + b"\tdocs/symlink.md\0"
            )
        with self.assertRaisesRegex(SystemExit, "colliding tracked release paths"):
            inventory_module._parse_tree(
                b"100644 blob "
                + object_id
                + b"\tdocs/Foo.txt\0"
                + b"100644 blob "
                + (b"1" * 40)
                + b"\tdocs/foo.txt\0"
            )
        for first_directory, second_directory in (
            ("Foo", "foo"),
            ("caf\u00e9", "cafe\u0301"),
        ):
            with self.subTest(
                first_directory=first_directory,
                second_directory=second_directory,
            ):
                with self.assertRaisesRegex(
                    SystemExit, "colliding tracked release directory paths"
                ):
                    inventory_module._parse_tree(
                        (
                            f"100644 blob {'0' * 40}\tdocs/{first_directory}/a.txt\0"
                            f"100644 blob {'1' * 40}\tdocs/{second_directory}/b.txt\0"
                        ).encode("utf-8")
                    )
        with self.assertRaisesRegex(SystemExit, "colliding tracked release paths"):
            inventory_module._parse_tree(
                b"100644 blob "
                + object_id
                + b"\tdocs/Foo\0"
                + b"100644 blob "
                + (b"1" * 40)
                + b"\tdocs/foo/child.txt\0"
            )
        for unsafe_path in (
            r"evals\runs\leak.json",
            r"..\..\escape.txt",
            r"C:\escape.txt",
            r"\\server\share\escape.txt",
            "docs/name:stream",
            "docs/CON.txt",
            "docs/CONIN$",
            "docs/CONOUT$.txt",
            "docs/CON .txt",
            "docs/NUL .txt",
            "docs/COM\u00b9.txt",
            "docs/LPT\u00b3.txt",
            "docs/trailing-dot.",
        ):
            with self.subTest(unsafe_path=unsafe_path):
                with self.assertRaisesRegex(SystemExit, "tracked release path"):
                    inventory_module._parse_tree(
                        b"100644 blob "
                        + object_id
                        + b"\t"
                        + unsafe_path.encode("utf-8")
                        + b"\0"
                    )

    def test_release_inventory_rejects_dirty_worktree(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "test_release_inventory_dirty"
        )
        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name) / "repo"
            initialize_git_repo(repo)
            readme = repo / "README.md"
            readme.write_text("committed\n", encoding="utf-8")
            git(repo, "add", "README.md")
            git(repo, "commit", "--quiet", "-m", "clean source")
            readme.write_text("modified\n", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "README.md"):
                inventory_module.tracked_head_inventory(repo)

    def test_plugin_inventory_uses_only_selected_tracked_blobs(self) -> None:
        inventory_module = load_script_module(
            RELEASE_INVENTORY_SCRIPT, "release_inventory"
        )
        with mock.patch.dict(sys.modules, {"release_inventory": inventory_module}):
            release_module = load_script_module(
                RELEASE_SCRIPT, "test_create_release_package"
            )
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            repo = root / "repo"
            stage = root / "stage"
            initialize_git_repo(repo)
            (repo / ".gitignore").write_text("**/private.txt\n", encoding="utf-8")
            tracked = {
                ".codex-plugin/plugin.json": "{}\n",
                "skills/example/SKILL.md": "---\nname: example\n---\n",
                **{path: "public\n" for path in release_module.ROOT_FILES},
                **{path: "public\n" for path in release_module.DOC_FILES},
            }
            for relative, content in tracked.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            git(repo, "add", ".gitignore", *tracked)
            git(repo, "commit", "--quiet", "-m", "plugin source")
            for relative in (
                ".codex-plugin/private.txt",
                "skills/example/private.txt",
            ):
                path = repo / relative
                path.write_text("private local material\n", encoding="utf-8")

            with mock.patch.object(release_module, "REPO_ROOT", repo):
                release_module.copy_candidate(stage)

            self.assertEqual(
                set(tree_hashes(stage)),
                set(tracked),
            )

    def test_evaluation_inventory_matches_skills(self) -> None:
        evaluations = json.loads((REPO_ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual({case["skill"] for case in evaluations["cases"]}, EXPECTED_SKILLS)
        self.assertGreaterEqual(len(evaluations["adversarial_cases"]), 3)

    def test_asset_license_ledger_covers_bundled_assets(self) -> None:
        ledger_path = REPO_ROOT / "docs" / "asset-license-ledger.csv"
        with ledger_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        recorded = [row["path"] for row in rows]
        expected = {
            path.relative_to(REPO_ROOT).as_posix()
            for root in (REPO_ROOT / "templates", REPO_ROOT / "examples" / "synthetic-report")
            for path in root.rglob("*")
            if path.is_file() and path.name != "README.md"
        }
        self.assertEqual(len(recorded), len(set(recorded)), "asset ledger contains duplicate paths")
        self.assertEqual(expected - set(recorded), set(), "asset ledger omits bundled assets")
        for row in rows:
            self.assertEqual(row["redistribution_allowed"], "yes", row["path"])
            self.assertEqual(row["license"], "MIT", row["path"])

    def test_forward_test_result_meets_release_threshold(self) -> None:
        result = json.loads(
            (REPO_ROOT / "evals" / "results" / "forward-test-2026-08-12.json").read_text(encoding="utf-8")
        )
        self.assertEqual({item["skill"] for item in result["skills"]}, EXPECTED_SKILLS)
        self.assertTrue(all(item["score"] >= 85 for item in result["skills"]))
        self.assertTrue(all(item["result"].startswith("pass") for item in result["skills"]))
        self.assertTrue(all(item["result"] == "pass" for item in result["adversarial_cases"]))
        self.assertEqual(result["blocking_rule_failures"], 0)
        self.assertEqual(result["unresolved_high_or_critical_skill_findings"], 0)
        self.assertEqual(result["external_actions_performed"], 0)


if __name__ == "__main__":
    unittest.main()
