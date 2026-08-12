#!/usr/bin/env python3
"""Generate self-contained Report Skills packages from canonical source."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "source"
SOURCE_SKILLS = SOURCE_ROOT / "skills"
SHARED_ROOT = SOURCE_ROOT / "shared"
TEMPLATE_ROOT = REPO_ROOT / "templates"
MAP_PATH = SOURCE_ROOT / "skill-map.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "skills"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_files(root: Path) -> list[Path]:
    return sorted(
        (path.relative_to(root) for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.as_posix(),
    )


def load_map() -> dict:
    try:
        data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {MAP_PATH}: {exc}") from exc
    if data.get("version") != 1 or not isinstance(data.get("skills"), dict):
        raise SystemExit("source/skill-map.yaml must declare version 1 and a skills object")
    return data


def validate_source_entry(name: str, config: dict) -> Path:
    source_dir = SOURCE_SKILLS / name
    if not source_dir.is_dir():
        raise SystemExit(f"Missing canonical skill source: {source_dir}")
    for required in ("SKILL.md", "agents/openai.yaml"):
        if not (source_dir / required).is_file():
            raise SystemExit(f"Missing {required} for {name}")
    for reference in config.get("shared_references", []):
        if Path(reference).name != reference or not (SHARED_ROOT / reference).is_file():
            raise SystemExit(f"Invalid shared reference for {name}: {reference}")
    for template in config.get("templates", []):
        if Path(template).name != template or not (TEMPLATE_ROOT / template).is_file():
            raise SystemExit(f"Invalid template for {name}: {template}")
    return source_dir


def source_hashes() -> dict[str, str]:
    paths: list[Path] = [MAP_PATH]
    for root in (SHARED_ROOT, SOURCE_SKILLS, TEMPLATE_ROOT):
        paths.extend(path for path in root.rglob("*") if path.is_file())
    unique = sorted(set(paths), key=lambda path: path.relative_to(REPO_ROOT).as_posix())
    return {
        path.relative_to(REPO_ROOT).as_posix(): sha256(path)
        for path in unique
    }


def generate_tree(destination: Path) -> None:
    mapping = load_map()
    destination.mkdir(parents=True, exist_ok=False)
    generated: dict[str, list[str]] = {}

    for name, config in sorted(mapping["skills"].items()):
        source_dir = validate_source_entry(name, config)
        target_dir = destination / name
        shutil.copytree(source_dir, target_dir)

        references_dir = target_dir / "references"
        references_dir.mkdir(parents=True, exist_ok=True)
        for reference in sorted(config.get("shared_references", [])):
            shutil.copy2(SHARED_ROOT / reference, references_dir / reference)

        templates = sorted(config.get("templates", []))
        if templates:
            template_target = target_dir / "assets" / "templates"
            template_target.mkdir(parents=True, exist_ok=True)
            for template in templates:
                shutil.copy2(TEMPLATE_ROOT / template, template_target / template)

        generated[name] = [path.as_posix() for path in relative_files(target_dir)]

    manifest = {
        "schema_version": 1,
        "map_version": mapping["version"],
        "skills": generated,
        "source_hashes": source_hashes(),
    }
    (destination / ".generation-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def compare_trees(expected: Path, actual: Path) -> list[str]:
    differences: list[str] = []
    expected_files = relative_files(expected)
    actual_files = relative_files(actual) if actual.is_dir() else []
    expected_set = {path.as_posix() for path in expected_files}
    actual_set = {path.as_posix() for path in actual_files}
    for missing in sorted(expected_set - actual_set):
        differences.append(f"missing generated file: {missing}")
    for extra in sorted(actual_set - expected_set):
        differences.append(f"unexpected generated file: {extra}")
    for common in sorted(expected_set & actual_set):
        if sha256(expected / common) != sha256(actual / common):
            differences.append(f"generated file differs: {common}")
    return differences


def replace_default_output(generated: Path) -> None:
    target = DEFAULT_OUTPUT.resolve()
    expected_target = (REPO_ROOT / "skills").resolve()
    if target != expected_target or target.parent != REPO_ROOT.resolve():
        raise SystemExit("Refusing to replace an output outside the repository skills directory")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(generated, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare canonical generation with committed skills")
    parser.add_argument("--output", type=Path, help="Generate into a new, empty custom directory")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="report-skills-build-") as temp_name:
        generated = Path(temp_name) / "skills"
        generate_tree(generated)

        if args.check:
            differences = compare_trees(generated, DEFAULT_OUTPUT)
            if differences:
                print("Generated skills are out of date:")
                for difference in differences:
                    print(f"- {difference}")
                return 1
            print("Generated skills match canonical source.")
            return 0

        if args.output:
            output = args.output.resolve()
            if output.exists() and any(output.iterdir()):
                raise SystemExit(f"Custom output must be absent or empty: {output}")
            if output.exists():
                output.rmdir()
            shutil.copytree(generated, output)
            print(f"Generated Report Skills at {output}")
            return 0

        replace_default_output(generated)
        print(f"Generated {len(load_map()['skills'])} skills at {DEFAULT_OUTPUT}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

