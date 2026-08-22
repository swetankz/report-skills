#!/usr/bin/env python3
"""Fail-closed Git inventory helpers for deterministic public release archives."""

from __future__ import annotations

import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable


RAW_EVAL_PREFIXES = (
    PurePosixPath("evals/review"),
    PurePosixPath("evals/runs"),
)
REGULAR_FILE_MODES = {"100644", "100755"}
WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
    *(f"com{number}" for number in "¹²³"),
    *(f"lpt{number}" for number in "¹²³"),
}
WINDOWS_SPECIAL_CHARACTERS = frozenset('<>:"\\|?*')


@dataclass(frozen=True)
class TrackedFile:
    path: PurePosixPath
    mode: str
    object_id: str


def _run_git(repo_root: Path, *arguments: str, text: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=False,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
    )


def _is_within(path: PurePosixPath, prefix: PurePosixPath) -> bool:
    path_parts = tuple(part.casefold() for part in path.parts)
    prefix_parts = tuple(part.casefold() for part in prefix.parts)
    return path_parts[: len(prefix_parts)] == prefix_parts


def validate_release_path(path_text: str) -> PurePosixPath:
    raw_parts = path_text.split("/")
    if (
        not path_text
        or path_text.startswith("/")
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise SystemExit(f"Refusing unsafe tracked release path: {path_text}")
    for part in raw_parts:
        if part.endswith((" ", ".")):
            raise SystemExit(f"Refusing non-portable tracked release path: {path_text}")
        if any(character in WINDOWS_SPECIAL_CHARACTERS for character in part):
            raise SystemExit(f"Refusing non-portable tracked release path: {path_text}")
        if any(ord(character) < 32 for character in part):
            raise SystemExit(f"Refusing non-portable tracked release path: {path_text}")
        device_name = part.split(".", 1)[0].rstrip(" .").casefold()
        if device_name in WINDOWS_RESERVED_NAMES:
            raise SystemExit(f"Refusing Windows-reserved tracked release path: {path_text}")
    relative = PurePosixPath(*raw_parts)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"Refusing unsafe tracked release path: {path_text}")
    return relative


def _portable_path_key(path: PurePosixPath) -> str:
    return "/".join(
        unicodedata.normalize("NFC", part).casefold()
        for part in path.parts
    )


def validate_portable_collisions(inventory: Iterable[TrackedFile]) -> None:
    seen_nodes: dict[str, tuple[PurePosixPath, str]] = {}
    for item in inventory:
        relative = validate_release_path(item.path.as_posix())
        for depth in range(1, len(relative.parts) + 1):
            node = PurePosixPath(*relative.parts[:depth])
            node_type = "file" if depth == len(relative.parts) else "directory"
            key = _portable_path_key(node)
            previous = seen_nodes.get(key)
            if previous is None:
                seen_nodes[key] = (node, node_type)
                continue
            previous_node, previous_type = previous
            if previous_node == node and previous_type == node_type == "directory":
                continue
            label = (
                "colliding tracked release directory paths"
                if previous_type == node_type == "directory"
                else "colliding tracked release paths"
            )
            raise SystemExit(
                f"Refusing {label}: {previous_node.as_posix()} and {node.as_posix()}"
            )


def _parse_tree(payload: bytes) -> list[TrackedFile]:
    files: list[TrackedFile] = []
    for raw_entry in payload.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        if not separator:
            raise SystemExit("Unable to parse the Git release inventory.")
        try:
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
            relative = validate_release_path(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise SystemExit("Unable to decode the Git release inventory.") from error
        if object_type != "blob" or mode not in REGULAR_FILE_MODES:
            raise SystemExit(
                f"Refusing non-regular tracked release entry: {relative.as_posix()} "
                f"({mode} {object_type})."
            )
        if any(_is_within(relative, prefix) for prefix in RAW_EVAL_PREFIXES):
            raise SystemExit(f"Refusing tracked raw evaluation path: {relative.as_posix()}")
        files.append(TrackedFile(relative, mode, object_id))
    validate_portable_collisions(files)
    return sorted(files, key=lambda item: item.path.as_posix())


def tracked_head_inventory(repo_root: Path) -> list[TrackedFile]:
    repo_root = repo_root.resolve()
    root_result = _run_git(repo_root, "rev-parse", "--show-toplevel", text=True)
    if root_result.returncode:
        raise SystemExit("Refusing to package without a readable Git worktree root.")
    resolved_root = Path(root_result.stdout.strip()).resolve()
    if resolved_root != repo_root:
        raise SystemExit(
            f"Refusing parent Git worktree {resolved_root}; expected {repo_root}."
        )

    status_result = _run_git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status_result.returncode:
        raise SystemExit("Unable to verify the release worktree state.")
    if status_result.stdout:
        changed = status_result.stdout.decode("utf-8", errors="replace").splitlines()
        preview = ", ".join(line[3:] if len(line) > 3 else line for line in changed[:5])
        raise SystemExit(f"Refusing to package a dirty release worktree: {preview}")

    tree_result = _run_git(repo_root, "ls-tree", "-r", "-z", "HEAD")
    if tree_result.returncode:
        raise SystemExit("Unable to enumerate regular files from release HEAD.")
    return _parse_tree(tree_result.stdout)


def select_inventory(
    inventory: Iterable[TrackedFile], predicate: Callable[[PurePosixPath], bool]
) -> list[TrackedFile]:
    return [item for item in inventory if predicate(item.path)]


def copy_inventory(repo_root: Path, stage: Path, inventory: Iterable[TrackedFile]) -> None:
    repo_root = repo_root.resolve()
    stage_root = stage.resolve()
    items = list(inventory)
    validate_portable_collisions(items)
    for item in items:
        relative = validate_release_path(item.path.as_posix())
        target = stage_root.joinpath(*relative.parts)
        try:
            target.resolve().relative_to(stage_root)
        except ValueError as error:
            raise SystemExit(f"Refusing release path outside stage: {relative.as_posix()}") from error
        blob_result = _run_git(repo_root, "cat-file", "blob", item.object_id)
        if blob_result.returncode:
            raise SystemExit(f"Unable to read tracked release blob: {item.path.as_posix()}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob_result.stdout)
