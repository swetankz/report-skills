#!/usr/bin/env python3
"""Scan the public repository candidate for private or unsafe material."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
TEXT_EXTENSIONS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".py", ".toml", ".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".svg"
}
BLOCKED_BINARY_EXTENSIONS = {".pen", ".pdf", ".docx", ".pptx", ".zip", ".7z", ".mov", ".mp4", ".webm", ".ttf", ".otf", ".woff", ".woff2"}
SKIP_DIRS = {".git", ".build", "__pycache__", ".venv", "dist"}
SKIP_PREFIXES = {("evals", "runs"), ("evals", "review")}
INTENTIONAL_DEFECT_PARTS = {"intentional-defects"}
PATTERNS = {
    "windows-user-path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+", re.IGNORECASE),
    "unix-user-path": re.compile(r"/(?:Users|home)/[^/\s]+/"),
    "file-uri": re.compile(r"file://", re.IGNORECASE),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "openai-style-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    "assigned-secret": re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
    "signed-url": re.compile(r"(?i)https?://[^\s]+[?&](?:signature|sig|token|x-amz-signature)="),
    "uuid": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE),
    "private-project-term": re.compile(r"(?i)\b(?:Winjit|h1ai\+ux|InVision)\b|UX\s*(?:&|and)\s*AI\s+in\s+2026"),
    "release-placeholder": re.compile(r"<(?:owner|repo|path)>|\[TODO:", re.IGNORECASE),
    "line-placeholder": re.compile(r"(?im)^\s*(?:[-*]\s*)?(?:TODO|TBD|FIXME|XXX)(?:\s*:|\s*$)"),
}


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    line: int
    detail: str


def text_files(root: Path):
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        copied_scanner = relative.as_posix() == "scripts/scan_public_content.py"
        if not path.is_file() or path.resolve() == SELF or copied_scanner:
            continue
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if tuple(relative.parts[:2]) in SKIP_PREFIXES:
            continue
        yield path


def scan(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in text_files(root):
        relative = path.relative_to(root)
        suffix = path.suffix.casefold()
        if suffix in BLOCKED_BINARY_EXTENSIONS:
            findings.append(Finding("blocked-binary", relative.as_posix(), 0, f"blocked extension {suffix}"))
            continue
        if path.stat().st_size > 5 * 1024 * 1024:
            findings.append(Finding("large-file", relative.as_posix(), 0, "file exceeds 5 MiB"))
        if suffix not in TEXT_EXTENSIONS and path.name not in {"LICENSE"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("unapproved-binary", relative.as_posix(), 0, "non-text file is not allowlisted"))
            continue
        intentional_defect = bool(INTENTIONAL_DEFECT_PARTS & set(relative.parts))
        for category, pattern in PATTERNS.items():
            if intentional_defect and category in {"line-placeholder"}:
                continue
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                detail = "sensitive pattern detected; inspect and redact"
                findings.append(Finding(category, relative.as_posix(), line, detail))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan(root)
    if args.as_json:
        print(json.dumps([asdict(finding) for finding in findings], indent=2))
    elif findings:
        print(f"Public-safety scan found {len(findings)} blocking item(s):")
        for finding in findings:
            location = f":{finding.line}" if finding.line else ""
            print(f"- {finding.category}: {finding.path}{location} — {finding.detail}")
    else:
        print("Public-safety scan passed.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
