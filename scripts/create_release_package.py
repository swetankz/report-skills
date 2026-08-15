#!/usr/bin/env python3
"""Create a deterministic, locally validated Report Skills plugin archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from release_inventory import copy_inventory, select_inventory, tracked_head_inventory


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = REPO_ROOT / "dist"
MANIFEST_PATH = REPO_ROOT / ".codex-plugin" / "plugin.json"
ROOT_FILES = ["README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md"]
DOC_FILES = [
    "docs/architecture.md",
    "docs/skill-catalogue.md",
    "docs/installation.md",
    "docs/limitations.md",
    "docs/asset-license-ledger.csv",
]
PUBLIC_FILES = {PurePosixPath(path) for path in ROOT_FILES + DOC_FILES}
PLUGIN_PREFIXES = {".codex-plugin", "skills"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_check(*arguments: str) -> None:
    result = subprocess.run([sys.executable, *arguments], cwd=REPO_ROOT, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def plugin_inventory():
    inventory = tracked_head_inventory(REPO_ROOT)
    selected = select_inventory(
        inventory,
        lambda path: path in PUBLIC_FILES or (path.parts and path.parts[0] in PLUGIN_PREFIXES),
    )
    selected_paths = {item.path for item in selected}
    missing = sorted(path.as_posix() for path in PUBLIC_FILES - selected_paths)
    if missing:
        raise SystemExit(f"Required tracked plugin release files are missing: {missing}")
    for prefix in sorted(PLUGIN_PREFIXES):
        if not any(item.path.parts and item.path.parts[0] == prefix for item in selected):
            raise SystemExit(f"Tracked plugin release tree is missing: {prefix}/")
    return selected


def copy_candidate(stage: Path) -> None:
    copy_inventory(REPO_ROOT, stage, plugin_inventory())


def write_release_manifest(stage: Path, version: str, authorized_tag: str | None) -> None:
    files = {
        path.relative_to(stage).as_posix(): sha256(path)
        for path in sorted(
            stage.rglob("*"), key=lambda item: item.relative_to(stage).as_posix()
        )
        if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "plugin": "report-skills",
        "version": version,
        "publication_state": "approved-public-candidate" if authorized_tag else "local-candidate",
        "external_publication_authorized": bool(authorized_tag),
        "files": files,
    }
    if authorized_tag:
        manifest["authorized_release_tag"] = authorized_tag
    (stage / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def deterministic_zip(stage: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(
            stage.rglob("*"), key=lambda item: item.relative_to(stage).as_posix()
        ):
            if not path.is_file():
                continue
            relative = path.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--authorized-release-tag",
        help="Record explicit authorization for this exact immutable release tag.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plugin = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    version = plugin["version"]
    expected_tag = f"v{version}"
    if args.authorized_release_tag and args.authorized_release_tag != expected_tag:
        raise SystemExit(
            f"Authorized tag {args.authorized_release_tag!r} does not match plugin version {expected_tag!r}."
        )
    run_check(str(REPO_ROOT / "scripts" / "check_generated.py"))
    run_check(str(REPO_ROOT / "scripts" / "validate_repository.py"))
    run_check(str(REPO_ROOT / "scripts" / "scan_public_content.py"))
    run_check(str(REPO_ROOT / "scripts" / "test_standalone_packages.py"))

    DIST.mkdir(exist_ok=True)
    archive = DIST / f"report-skills-{version}.zip"
    checksum = archive.with_suffix(".zip.sha256")
    with tempfile.TemporaryDirectory(prefix="report-skills-release-") as temp_name:
        stage = Path(temp_name) / "report-skills"
        stage.mkdir()
        copy_candidate(stage)
        write_release_manifest(stage, version, args.authorized_release_tag)
        run_check(str(REPO_ROOT / "scripts" / "scan_public_content.py"), "--root", str(stage))
        deterministic_zip(stage, archive)
    checksum.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8", newline="\n")
    print(f"Created local release candidate: {archive}")
    print(f"SHA-256: {sha256(archive)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
