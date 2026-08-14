#!/usr/bin/env python3
"""Validate the Report Skills plugin, canonical map, and standalone packages."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"
SOURCE_SKILLS = REPO_ROOT / "source" / "skills"
MAP_PATH = REPO_ROOT / "source" / "skill-map.yaml"
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
FORBIDDEN_SKILL_DOCS = {"README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md"}


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) < 4 or lines[0].strip() != "---":
        raise ValueError("missing opening YAML delimiter")
    try:
        closing = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError("missing closing YAML delimiter") from exc
    values: dict[str, str] = {}
    for raw in lines[1:closing]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            raise ValueError(f"invalid frontmatter line: {raw}")
        key, value = raw.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values, text


def local_markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1).strip().split("#", 1)[0]
        if not target or re.match(r"^(?:https?://|mailto:|#)", target):
            continue
        targets.append(target)
    return targets


def validate_plugin(errors: list[str]) -> None:
    path = REPO_ROOT / ".codex-plugin" / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"plugin manifest cannot be read: {exc}")
        return
    if data.get("name") != "report-skills":
        errors.append("plugin name must be report-skills")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(data.get("version", ""))):
        errors.append("plugin version must use strict semantic versioning")
    project_path = REPO_ROOT / "pyproject.toml"
    try:
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))
        project_version = str(project.get("project", {}).get("version", ""))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"pyproject.toml cannot be read: {exc}")
    else:
        if project_version != str(data.get("version", "")):
            errors.append(
                "plugin and pyproject versions must match: "
                f"{data.get('version')!r} != {project_version!r}"
            )
    for key in ("description",):
        if not str(data.get(key, "")).strip():
            errors.append(f"plugin {key} is required")
    if not str(data.get("author", {}).get("name", "")).strip():
        errors.append("plugin author.name is required")
    if data.get("skills") not in {"./skills", "./skills/"}:
        errors.append("plugin skills must resolve to ./skills/")
    interface = data.get("interface", {})
    for key in ("displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities", "defaultPrompt"):
        if not interface.get(key):
            errors.append(f"plugin interface.{key} is required")
    for unsupported in ("hooks",):
        if unsupported in data:
            errors.append(f"unsupported plugin field: {unsupported}")
    for companion, filename in (("apps", ".app.json"), ("mcpServers", ".mcp.json")):
        if companion in data and not (REPO_ROOT / filename).exists():
            errors.append(f"plugin declares {companion} without {filename}")


def validate_skill(name: str, root: Path, errors: list[str], injected_targets: set[str] | None = None) -> None:
    injected_targets = injected_targets or set()
    prefix = root.relative_to(REPO_ROOT).as_posix()
    skill_path = root / "SKILL.md"
    if not skill_path.is_file():
        errors.append(f"{prefix}: missing SKILL.md")
        return
    try:
        frontmatter, text = parse_frontmatter(skill_path)
    except ValueError as exc:
        errors.append(f"{prefix}/SKILL.md: {exc}")
        return
    if set(frontmatter) != {"name", "description"}:
        errors.append(f"{prefix}/SKILL.md: frontmatter must contain only name and description")
    if frontmatter.get("name") != name:
        errors.append(f"{prefix}/SKILL.md: name must match folder")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append(f"{prefix}: invalid skill name")
    description = frontmatter.get("description", "")
    if not description or len(description) > 1024 or "<" in description or ">" in description:
        errors.append(f"{prefix}/SKILL.md: invalid description")
    if name in EXPLICIT_ONLY and (
        not description.startswith("Explicit invocation only:") or f"${name}" not in description
    ):
        errors.append(
            f"{prefix}/SKILL.md: explicit-only description must state the activation boundary and exact ${name} token"
        )
    if len(text.splitlines()) > 500:
        errors.append(f"{prefix}/SKILL.md: exceeds 500 lines")
    for target in local_markdown_targets(text):
        if ".." in Path(target).parts or re.match(r"^[A-Za-z]:[\\/]", target) or target.startswith(("/", "\\")):
            errors.append(f"{prefix}/SKILL.md: unsafe local reference {target}")
            continue
        if not (root / target).is_file() and target.replace("\\", "/") not in injected_targets:
            errors.append(f"{prefix}/SKILL.md: missing local reference {target}")
    for forbidden in FORBIDDEN_SKILL_DOCS:
        if any(path.name.casefold() == forbidden.casefold() for path in root.rglob("*")):
            errors.append(f"{prefix}: forbidden skill-level document {forbidden}")
    for path in root.rglob("*"):
        if path.is_symlink():
            errors.append(f"{prefix}: symlink is not allowed: {path.relative_to(root)}")
    metadata_path = root / "agents" / "openai.yaml"
    if not metadata_path.is_file():
        errors.append(f"{prefix}: missing agents/openai.yaml")
    else:
        metadata = metadata_path.read_text(encoding="utf-8")
        prompt = re.search(r'^\s*default_prompt:\s*["\'](.+)["\']\s*$', metadata, re.MULTILINE)
        short = re.search(r'^\s*short_description:\s*["\'](.+)["\']\s*$', metadata, re.MULTILINE)
        if not prompt or f"${name}" not in prompt.group(1):
            errors.append(f"{prefix}/agents/openai.yaml: default_prompt must mention ${name}")
        if not short or not 25 <= len(short.group(1)) <= 64:
            errors.append(f"{prefix}/agents/openai.yaml: short_description must be 25-64 characters")
        implicit_false = bool(re.search(r"^\s*allow_implicit_invocation:\s*false\s*$", metadata, re.MULTILINE))
        if name in EXPLICIT_ONLY and not implicit_false:
            errors.append(f"{prefix}/agents/openai.yaml: sensitive skill must disable implicit invocation")


def validate_repository_links(errors: list[str]) -> None:
    documents = [
        *(REPO_ROOT / name for name in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md")),
        *(REPO_ROOT / "docs").glob("*.md"),
        *(REPO_ROOT / "examples").rglob("*.md"),
    ]
    for path in sorted(set(documents)):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw_target in local_markdown_targets(text):
            target = raw_target.strip("<>")
            if re.match(r"^[A-Za-z]:[\\/]", target) or target.startswith(("/", "\\")):
                errors.append(f"{path.relative_to(REPO_ROOT).as_posix()}: unsafe absolute link {raw_target}")
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(REPO_ROOT.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(REPO_ROOT).as_posix()}: link leaves repository {raw_target}")
                continue
            if not resolved.exists():
                errors.append(f"{path.relative_to(REPO_ROOT).as_posix()}: broken local link {raw_target}")


def main() -> int:
    errors: list[str] = []
    validate_plugin(errors)
    validate_repository_links(errors)
    mapping_config: dict[str, dict] = {}
    try:
        mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        mapping_config = mapping.get("skills", {})
        mapped = set(mapping_config)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read skill map: {exc}")
        mapped = set()
    if mapped != EXPECTED_SKILLS:
        errors.append(f"skill map inventory mismatch: expected {sorted(EXPECTED_SKILLS)}, got {sorted(mapped)}")
    source_names = {path.name for path in SOURCE_SKILLS.iterdir() if path.is_dir()} if SOURCE_SKILLS.is_dir() else set()
    generated_names = {path.name for path in SKILLS_ROOT.iterdir() if path.is_dir()} if SKILLS_ROOT.is_dir() else set()
    if source_names != EXPECTED_SKILLS:
        errors.append(f"canonical skill inventory mismatch: {sorted(source_names)}")
    if generated_names != EXPECTED_SKILLS:
        errors.append(f"generated skill inventory mismatch: {sorted(generated_names)}")
    for name in sorted(EXPECTED_SKILLS & source_names):
        config = mapping_config.get(name, {})
        injected = {
            *(f"references/{reference}" for reference in config.get("shared_references", [])),
            *(f"assets/templates/{template}" for template in config.get("templates", [])),
        }
        validate_skill(name, SOURCE_SKILLS / name, errors, injected)
    for name in sorted(EXPECTED_SKILLS & generated_names):
        validate_skill(name, SKILLS_ROOT / name, errors)

    check = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_skills.py"), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    if check.returncode:
        errors.append(check.stdout.strip() or check.stderr.strip() or "generated check failed")

    if errors:
        print(f"Repository validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Repository validation passed for the plugin and all 11 skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
