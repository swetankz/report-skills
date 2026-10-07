#!/usr/bin/env python3
"""Copy each generated skill into isolation and validate local resolution."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BENCHMARK_PATH_PATTERN = re.compile(r"\.benchmark_skill[/\\]", re.IGNORECASE)
SCRIPT_TARGET_PATTERN = re.compile(
    r"(?<![\w./\\-])(?:\./|\.\\)?(?P<target>scripts[/\\](?:[A-Za-z0-9_.-]+[/\\])*"
    r"[A-Za-z0-9_.-]+\.(?:ps1|py|sh|bash|js|mjs|cjs|cmd|bat))\b"
)
UNROOTED_HELPER_COMMAND_PATTERN = re.compile(
    r"(?<![\w./\\-])(?:python(?:3(?:\.\d+)?)?|py|pwsh|powershell|node|bash|sh)"
    r"(?:\.exe)?\s+(?:-[A-Za-z][A-Za-z0-9-]*\s+)*[\"']?(?:\./|\.\\)?"
    r"(?P<target>scripts[/\\](?:[A-Za-z0-9_.-]+[/\\])*"
    r"[A-Za-z0-9_.-]+\.(?:ps1|py|sh|bash|js|mjs|cjs|cmd|bat))\b",
    re.IGNORECASE,
)


def declared_script_targets(text: str) -> set[str]:
    """Find literal bundled helper targets in prose, links, and commands."""
    return {match.group("target").replace("\\", "/") for match in SCRIPT_TARGET_PATTERN.finditer(text)}


def validate_runtime_paths(skill_root: Path) -> list[str]:
    """Check runtime documents against only their independently installed skill."""
    errors: list[str] = []
    root = skill_root.resolve()
    documents = [skill_root / "SKILL.md", *sorted((skill_root / "references").rglob("*.md"))]
    for document in documents:
        if not document.is_file():
            continue
        relative = document.relative_to(skill_root).as_posix()
        text = document.read_text(encoding="utf-8")
        if BENCHMARK_PATH_PATTERN.search(text):
            errors.append(f"{skill_root.name}: benchmark-only runtime path in {relative}")
        # This bounded syntax check rejects literal interpreter invocations that
        # resolve a helper against the task cwd. It is not a prose/data-flow
        # parser and cannot establish that every variable command is rooted.
        for match in UNROOTED_HELPER_COMMAND_PATTERN.finditer(text):
            errors.append(
                f"{skill_root.name}: task-relative helper command in {relative}: {match.group('target')}"
            )
        for target in sorted(declared_script_targets(text)):
            candidate = skill_root / target
            try:
                candidate.resolve().relative_to(root)
            except (OSError, ValueError):
                errors.append(f"{skill_root.name}: bundled script leaves isolated package: {target}")
                continue
            if candidate.is_symlink() or not candidate.is_file():
                errors.append(f"{skill_root.name}: unresolved bundled script in {relative}: {target}")
    return errors


def validate_isolated_skill(skill: Path, isolated: Path) -> list[str]:
    errors: list[str] = []
    copied = isolated / skill.name
    shutil.copytree(skill, copied)
    required = [copied / "SKILL.md", copied / "agents" / "openai.yaml"]
    for path in required:
        if not path.is_file():
            errors.append(f"{skill.name}: missing {path.relative_to(copied)}")
    errors.extend(validate_runtime_paths(copied))
    for path in copied.rglob("*"):
        if path.is_symlink():
            errors.append(f"{skill.name}: symlink remains in isolated package")
        if not path.is_file() or path.suffix.casefold() not in {".md", ".yaml", ".yml", ".json", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "../" in text or "..\\" in text:
            errors.append(f"{skill.name}: parent traversal in {path.relative_to(copied)}")
        if path.name == "SKILL.md":
            for match in LINK_PATTERN.finditer(text):
                target = match.group(1).strip().split("#", 1)[0]
                if not target or re.match(r"^(?:https?://|mailto:|#)", target):
                    continue
                if not (copied / target).is_file():
                    errors.append(f"{skill.name}: unresolved isolated reference {target}")
    return errors


def main() -> int:
    skills = sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir())
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="report-skills-isolated-") as temp_name:
        isolated = Path(temp_name)
        for skill in skills:
            errors.extend(validate_isolated_skill(skill, isolated))
    if errors:
        print(f"Standalone validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Standalone validation passed for {len(skills)} isolated skills.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
