#!/usr/bin/env python3
"""Verify deterministic local Report Skills release archives and sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Any, Iterable

from release_inventory import tracked_head_inventory, validate_release_path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = REPO_ROOT / "dist"
PLUGIN_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_ZIP_MODE = 0o100644


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def verify_sidecar(archive: Path, sidecar: Path) -> str:
    require(archive.is_file(), f"Missing release archive: {archive}")
    require(sidecar.is_file(), f"Missing release checksum: {sidecar}")
    fields = sidecar.read_text(encoding="utf-8").strip().split()
    require(
        len(fields) == 2 and fields[1] == archive.name,
        f"Invalid checksum sidecar format: {sidecar.name}",
    )
    expected = fields[0]
    require(
        len(expected) == 64 and all(character in "0123456789abcdef" for character in expected),
        f"Invalid checksum digest: {sidecar.name}",
    )
    actual = sha256_file(archive)
    require(actual == expected, f"Checksum mismatch: {archive.name}")
    return actual


def verify_archive(
    archive: Path,
    manifest_name: str,
    expected_tracked_paths: Iterable[str],
    version: str,
    authorized_tag: str | None,
) -> dict[str, Any]:
    with zipfile.ZipFile(archive, "r") as source:
        infos = source.infolist()
        names = [info.filename for info in infos]
        require(len(names) == len(set(names)), f"Duplicate ZIP entry: {archive.name}")
        require(names == sorted(names), f"ZIP entries are not sorted: {archive.name}")
        for info in infos:
            validate_release_path(info.filename)
            require(not info.is_dir(), f"Directory ZIP entry is forbidden: {info.filename}")
            require(
                info.date_time == FIXED_ZIP_TIMESTAMP,
                f"Non-deterministic ZIP timestamp: {info.filename}",
            )
            require(
                info.compress_type == zipfile.ZIP_DEFLATED,
                f"Unexpected ZIP compression: {info.filename}",
            )
            require(
                info.external_attr >> 16 == FIXED_ZIP_MODE,
                f"Unexpected ZIP file mode: {info.filename}",
            )

        require(manifest_name in names, f"Missing archive manifest: {manifest_name}")
        manifest = json.loads(source.read(manifest_name).decode("utf-8"))
        require(manifest.get("schema_version") == 1, f"Archive manifest schema mismatch: {archive.name}")
        require(manifest.get("version") == version, f"Archive version mismatch: {archive.name}")
        if manifest_name == "RELEASE_MANIFEST.json":
            require(
                manifest.get("plugin") == "report-skills",
                f"Archive plugin identity mismatch: {archive.name}",
            )
        else:
            require(
                manifest.get("project") == "report-skills",
                f"Archive project identity mismatch: {archive.name}",
            )
            require(
                manifest.get("snapshot_type") == "intended-public-repository-tree",
                f"Archive snapshot type mismatch: {archive.name}",
            )
            require(
                manifest.get("git_history_present") is False,
                f"Archive history state mismatch: {archive.name}",
            )
        expected_authorized = bool(authorized_tag)
        expected_state = (
            "approved-public-candidate" if authorized_tag else "local-candidate"
        )
        if manifest_name == "SOURCE_SNAPSHOT_MANIFEST.json":
            expected_state = (
                "approved-public-source-candidate"
                if authorized_tag
                else "local-source-candidate"
            )
        require(
            manifest.get("external_publication_authorized") is expected_authorized,
            f"Archive authorization state mismatch: {archive.name}",
        )
        require(
            manifest.get("publication_state") == expected_state,
            f"Archive publication state mismatch: {archive.name}",
        )
        if authorized_tag:
            require(
                manifest.get("authorized_release_tag") == authorized_tag,
                f"Archive authorized tag mismatch: {archive.name}",
            )
        else:
            require(
                "authorized_release_tag" not in manifest,
                f"Local archive unexpectedly records release authorization: {archive.name}",
            )

        file_hashes = manifest.get("files")
        require(isinstance(file_hashes, dict), f"Archive manifest files are invalid: {archive.name}")
        if manifest_name == "SOURCE_SNAPSHOT_MANIFEST.json":
            require(
                manifest.get("file_count") == len(file_hashes),
                f"Archive manifest file count mismatch: {archive.name}",
            )
        payload_names = set(names) - {manifest_name}
        require(
            set(file_hashes) == payload_names,
            f"Archive manifest entry set mismatch: {archive.name}",
        )
        for name, expected_hash in sorted(file_hashes.items()):
            require(
                isinstance(expected_hash, str) and sha256_bytes(source.read(name)) == expected_hash,
                f"Archive manifest hash mismatch: {name}",
            )

    expected_names = set(expected_tracked_paths) | {manifest_name}
    require(set(names) == expected_names, f"Clean-HEAD inventory mismatch: {archive.name}")
    return {
        "filename": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": sha256_file(archive),
        "entry_count": len(names),
        "manifest": manifest_name,
        "publication_authorized": bool(authorized_tag),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DIST)
    parser.add_argument("--compare-directory", type=Path)
    parser.add_argument("--authorized-release-tag")
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

    from create_release_package import plugin_inventory

    specs = (
        (
            f"report-skills-{version}.zip",
            "RELEASE_MANIFEST.json",
            [item.path.as_posix() for item in plugin_inventory()],
        ),
        (
            f"report-skills-source-{version}.zip",
            "SOURCE_SNAPSHOT_MANIFEST.json",
            [item.path.as_posix() for item in tracked_head_inventory(REPO_ROOT)],
        ),
    )
    results: list[dict[str, Any]] = []
    asset_names: list[str] = []
    for archive_name, manifest_name, expected_paths in specs:
        archive = args.directory / archive_name
        sidecar = archive.with_suffix(".zip.sha256")
        digest = verify_sidecar(archive, sidecar)
        result = verify_archive(
            archive,
            manifest_name,
            expected_paths,
            version,
            args.authorized_release_tag,
        )
        require(result["sha256"] == digest, f"Archive digest drift: {archive_name}")
        results.append(result)
        asset_names.extend((archive.name, sidecar.name))

    if args.compare_directory:
        for name in asset_names:
            first = args.directory / name
            second = args.compare_directory / name
            require(second.is_file(), f"Missing comparison asset: {second}")
            require(
                sha256_file(first) == sha256_file(second),
                f"Non-reproducible release asset: {name}",
            )

    receipt = {
        "schema_version": 1,
        "version": version,
        "authorized_release_tag": args.authorized_release_tag,
        "assets": results,
        "asset_names": sorted(asset_names),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "zlib": zlib.ZLIB_VERSION,
        },
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
