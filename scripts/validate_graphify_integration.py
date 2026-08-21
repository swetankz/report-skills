#!/usr/bin/env python3
"""Validate the portable boundary around the optional local Graphify sidecar."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPHIFY_VERSION = "0.9.48"
LOCAL_PATHSPECS = (
    ".agents/rules/graphify.md",
    ".agents/skills/graphify",
    ".agents/workflows/graphify.md",
    ".codex/hooks.json",
    ".codex/skills/graphify",
    "graphify-out",
)
LOCAL_PREFIXES = (
    (".agents", "skills", "graphify"),
    (".codex", "skills", "graphify"),
    ("graphify-out",),
)
LOCAL_FILES = {
    (".agents", "rules", "graphify.md"),
    (".agents", "workflows", "graphify.md"),
    (".codex", "hooks.json"),
}
IGNORE_PROBES = (
    ".agents/rules/graphify.md",
    ".agents/skills/graphify/SKILL.md",
    ".agents/workflows/graphify.md",
    ".codex/hooks.json",
    ".codex/skills/graphify/SKILL.md",
    "graphify-out/graph.json",
)
REQUIRED_GITIGNORE = {
    "/.agents/rules/graphify.md",
    "/.agents/skills/graphify/",
    "/.agents/workflows/graphify.md",
    "/.codex/hooks.json",
    "/.codex/skills/graphify/",
    "/graphify-out/",
}
REQUIRED_GRAPHIFYIGNORE = {
    ".agents/rules/graphify.md",
    ".agents/skills/graphify/",
    ".agents/workflows/graphify.md",
    ".codex/hooks.json",
    ".codex/skills/graphify/",
    "evals/review/",
    "evals/runs/",
    "graphify-out/",
}
DISALLOWED_GRAPH_PREFIXES = (
    ".agents/",
    ".build/",
    ".codex/",
    ".git/",
    "dist/",
    "evals/review/",
    "evals/runs/",
    "graphify-out/",
)
EXPECTED_RECEIPT = {
    "cli_command": "graphify",
    "install_command": "uv tool install graphifyy==0.9.48",
    "integration_mode": "local-advisory-sidecar",
    "package": {
        "distributions": [
            {
                "filename": "graphifyy-0.9.48-py3-none-any.whl",
                "sha256": "4f745d72d6c5165ef7132bf8b2819ef59707aa70cd99efd3a4fbc8c4ba43b4b9",
            },
            {
                "filename": "graphifyy-0.9.48.tar.gz",
                "sha256": "14eaac83804866940ccb34491ca69ab62b2b51e346f88356c5211a3d8cd5e41e",
            },
        ],
        "name": "graphifyy",
        "pypi_release": "https://pypi.org/project/graphifyy/0.9.48/",
        "version": "0.9.48",
    },
    "schema_version": 1,
    "source": {
        "commit": "b2cd36267456c166788c95be6e68574064a92a42",
        "repository": "https://github.com/Graphify-Labs/graphify",
        "tag": "v0.9.48",
    },
}
WINDOWS_RESERVED = {
    "aux", "clock$", "com1", "com2", "com3", "com4", "com5", "com6",
    "com7", "com8", "com9", "con", "lpt1", "lpt2", "lpt3", "lpt4",
    "lpt5", "lpt6", "lpt7", "lpt8", "lpt9", "nul", "prn",
}


def raw_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def normalized_lines(path: Path) -> set[str]:
    return {
        line.strip().replace("\\", "/")
        for line in raw_lines(path)
        if line.strip() and not line.lstrip().startswith("#")
    }


def protected_negation_errors(path: Path) -> list[str]:
    errors: list[str] = []
    for number, raw in enumerate(raw_lines(path), start=1):
        line = raw.strip().replace("\\", "/")
        if not line.startswith("!"):
            continue
        first = line[1:].lstrip("/").split("/", 1)[0].casefold()
        if first in {".agents", ".codex", "graphify-out"}:
            errors.append(
                f"{path.name}:{number} must not negate a protected Graphify exclusion"
            )
    return errors


def exact_git_root(root: Path) -> Path | None:
    probe = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        text=True,
    )
    if probe.returncode != 0:
        return None
    git_root = Path(probe.stdout.strip()).resolve()
    return git_root if git_root == root.resolve() else None


def is_local_graphify_path(relative: Path) -> bool:
    parts = tuple(part.casefold() for part in relative.parts)
    if parts in LOCAL_FILES:
        return True
    return any(parts[: len(prefix)] == prefix for prefix in LOCAL_PREFIXES)


def local_graphify_artifact_paths(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and is_local_graphify_path(path.relative_to(root))
    )


def tracked_local_paths(root: Path, git_root: Path) -> list[str]:
    result = subprocess.run(
        [
            "git", "-c", f"safe.directory={git_root}", "-C", str(git_root),
            "ls-files", "-z", "--", *LOCAL_PATHSPECS,
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ["<git-index-check-failed>"]
    return sorted(
        value.decode("utf-8", errors="replace").replace("\\", "/")
        for value in result.stdout.split(b"\0")
        if value
    )


def effective_gitignore_errors(root: Path, git_root: Path) -> list[str]:
    errors: list[str] = []
    for relative in IGNORE_PROBES:
        result = subprocess.run(
            [
                "git", "-c", f"safe.directory={git_root}", "-C", str(git_root),
                "check-ignore", "--no-index", "--quiet", "--", relative,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f".gitignore does not effectively exclude {relative}")
    return errors


def version_pin_errors(path: Path, root: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"{path.relative_to(root).as_posix()} cannot be read: {error}"]
    versions = set(re.findall(r"\bgraphifyy==([0-9]+\.[0-9]+\.[0-9]+)\b", text))
    if versions != {GRAPHIFY_VERSION}:
        return [
            f"{path.relative_to(root).as_posix()} must contain only the tested pin "
            f"graphifyy=={GRAPHIFY_VERSION}"
        ]
    return []


def receipt_errors(root: Path) -> list[str]:
    path = root / "docs" / "graphify-receipt.json"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"docs/graphify-receipt.json cannot be read: {error}"]
    if receipt != EXPECTED_RECEIPT:
        return ["docs/graphify-receipt.json does not match the approved Graphify receipt"]
    return []


def portable_source_path(value: Any) -> str | None:
    if value is None:
        return None
    source = unicodedata.normalize("NFC", str(value).replace("\\", "/"))
    parts = PurePosixPath(source).parts
    if not source or source.startswith("/") or re.match(r"^[A-Za-z]:/", source):
        return None
    for part in parts:
        if part in {"", ".", ".."} or part != part.rstrip(" ."):
            return None
        if re.search(r"[<>:\"|?*\x00-\x1f]", part):
            return None
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED:
            return None
    return source


def graph_validation_errors(root: Path) -> list[str]:
    graph_path = root / "graphify-out" / "graph.json"
    if not graph_path.is_file():
        return []
    errors: list[str] = []
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"graphify-out/graph.json cannot be read: {error}"]
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list) or not nodes:
        errors.append("graphify-out/graph.json must contain nodes")
        nodes = []
    if not isinstance(links, list) or not links:
        errors.append("graphify-out/graph.json must contain links")
        links = []
    node_ids = [str(node.get("id", "")) for node in nodes if isinstance(node, dict)]
    if any(not node_id for node_id in node_ids):
        errors.append("Graphify nodes must have non-empty ids")
    if len(node_ids) != len(set(node_ids)):
        errors.append("Graphify node ids must be unique")
    known_ids = set(node_ids)
    exact_links: set[str] = set()
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            errors.append(f"Graphify link {index} is not an object")
            continue
        source = str(link.get("source", ""))
        target = str(link.get("target", ""))
        if source not in known_ids or target not in known_ids:
            errors.append(f"Graphify link {index} has a dangling endpoint")
        if source == target:
            errors.append(f"Graphify link {index} is a self-loop")
        signature = json.dumps(link, sort_keys=True, separators=(",", ":"))
        if signature in exact_links:
            errors.append(f"Graphify link {index} is an exact duplicate")
        exact_links.add(signature)
    folded_prefixes = tuple(prefix.casefold() for prefix in DISALLOWED_GRAPH_PREFIXES)
    for item in [*nodes, *links]:
        if not isinstance(item, dict) or item.get("source_file") in (None, ""):
            continue
        source_file = portable_source_path(item.get("source_file"))
        if source_file is None:
            errors.append("Graphify source_file values must be relative portable paths")
            continue
        if source_file.casefold().startswith(folded_prefixes):
            errors.append(f"Graphify indexed excluded local path: {source_file}")
    built_at_commit = str(graph.get("built_at_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{7,40}", built_at_commit):
        errors.append("Graphify built_at_commit must be a Git object id")
    return errors


def local_adapter_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in (Path(".agents/skills/graphify"), Path(".codex/skills/graphify")):
        adapter = root / relative
        if not adapter.exists():
            continue
        version_path = adapter / ".graphify_version"
        try:
            version = version_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            errors.append(f"{version_path.relative_to(root).as_posix()} cannot be read: {error}")
            continue
        if version != GRAPHIFY_VERSION:
            errors.append(
                f"{version_path.relative_to(root).as_posix()} is {version!r}; "
                f"expected {GRAPHIFY_VERSION}"
            )
    return errors


def validate_graphify_integration(
    root: Path = REPO_ROOT, *, include_local_state: bool = False
) -> list[str]:
    """Return deterministic integration errors without installing or calling Graphify."""

    root = root.resolve()
    errors: list[str] = []
    gitignore = normalized_lines(root / ".gitignore")
    missing_gitignore = sorted(REQUIRED_GITIGNORE - gitignore)
    if missing_gitignore:
        errors.append(f".gitignore is missing Graphify exclusions: {missing_gitignore}")
    errors.extend(protected_negation_errors(root / ".gitignore"))
    graphifyignore = normalized_lines(root / ".graphifyignore")
    missing_graphifyignore = sorted(REQUIRED_GRAPHIFYIGNORE - graphifyignore)
    if missing_graphifyignore:
        errors.append(f".graphifyignore is missing exclusions: {missing_graphifyignore}")
    errors.extend(protected_negation_errors(root / ".graphifyignore"))
    try:
        policy = (root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"AGENTS.md cannot be read: {error}")
    else:
        for required in (
            "Graphify result as advisory",
            "must never waive, prune, or satisfy",
            "Never copy `AGENTS.md`, `.codex/`",
            "graphify check-update .",
        ):
            if required not in policy:
                errors.append(f"AGENTS.md is missing Graphify safety clause: {required}")
    errors.extend(version_pin_errors(root / "AGENTS.md", root))
    errors.extend(version_pin_errors(root / "docs" / "graphify.md", root))
    errors.extend(receipt_errors(root))
    git_root = exact_git_root(root)
    if git_root is None:
        local_paths = local_graphify_artifact_paths(root)
        if local_paths:
            errors.append(
                "non-Git archive or staged copy contains local Graphify artifacts: "
                f"{local_paths}"
            )
    else:
        tracked = tracked_local_paths(root, git_root)
        if tracked:
            errors.append(f"local Graphify artifacts must not be tracked: {tracked}")
        errors.extend(effective_gitignore_errors(root, git_root))
    if include_local_state:
        errors.extend(local_adapter_errors(root))
        errors.extend(graph_validation_errors(root))
    return errors


def main() -> int:
    errors = validate_graphify_integration(include_local_state=True)
    if errors:
        print(f"Graphify integration validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Graphify integration validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
