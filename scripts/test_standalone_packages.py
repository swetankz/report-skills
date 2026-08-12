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


def validate_isolated_skill(skill: Path, isolated: Path) -> list[str]:
    errors: list[str] = []
    copied = isolated / skill.name
    shutil.copytree(skill, copied)
    required = [copied / "SKILL.md", copied / "agents" / "openai.yaml"]
    for path in required:
        if not path.is_file():
            errors.append(f"{skill.name}: missing {path.relative_to(copied)}")
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

