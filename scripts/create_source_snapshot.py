#!/usr/bin/env python3
"""Create a deterministic, history-free snapshot of the intended public repository tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from release_inventory import copy_inventory, tracked_head_inventory


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = REPO_ROOT / "dist"
PLUGIN_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
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


def copy_source(stage: Path) -> None:
    copy_inventory(REPO_ROOT, stage, tracked_head_inventory(REPO_ROOT))


def write_manifest(stage: Path, version: str, authorized_tag: str | None) -> None:
    files = {
        path.relative_to(stage).as_posix(): sha256(path)
        for path in sorted(stage.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "project": "report-skills",
        "version": version,
        "snapshot_type": "intended-public-repository-tree",
        "publication_state": "approved-public-source-candidate" if authorized_tag else "local-source-candidate",
        "git_history_present": False,
        "external_publication_authorized": bool(authorized_tag),
        "file_count": len(files),
        "files": files,
    }
    if authorized_tag:
        manifest["authorized_release_tag"] = authorized_tag
    (stage / "SOURCE_SNAPSHOT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def deterministic_zip(stage: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(stage.rglob("*")):
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
    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    version = plugin["version"]
    expected_tag = f"v{version}"
    if args.authorized_release_tag and args.authorized_release_tag != expected_tag:
        raise SystemExit(
            f"Authorized tag {args.authorized_release_tag!r} does not match plugin version {expected_tag!r}."
        )
    run_check(str(REPO_ROOT / "scripts" / "check_generated.py"))
    run_check(str(REPO_ROOT / "scripts" / "validate_repository.py"))
    run_check(str(REPO_ROOT / "scripts" / "scan_public_content.py"))
    run_check("-m", "unittest", "discover", "-s", "tests")
    run_check(str(REPO_ROOT / "scripts" / "test_standalone_packages.py"))

    DIST.mkdir(exist_ok=True)
    archive = DIST / f"report-skills-source-{version}.zip"
    checksum = archive.with_suffix(".zip.sha256")
    with tempfile.TemporaryDirectory(prefix="report-skills-source-") as temp_name:
        stage = Path(temp_name) / "report-skills"
        stage.mkdir()
        copy_source(stage)
        write_manifest(stage, version, args.authorized_release_tag)
        run_check(str(REPO_ROOT / "scripts" / "scan_public_content.py"), "--root", str(stage))
        deterministic_zip(stage, archive)

    digest = sha256(archive)
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")
    print(f"Created local source candidate: {archive}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
