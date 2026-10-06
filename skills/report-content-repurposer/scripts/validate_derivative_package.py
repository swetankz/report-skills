#!/usr/bin/env python3
"""Validate statement-level coverage in a local derivative package.

The claim-mapping CSV is the inventory of every copy-bearing output unit.
Markdown units use an HTML comment marker, structured text units use a
``statement_id`` field, and CSV deliverables contain one copy unit per row.
This script checks that inventory against the exact local deliverable files.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Iterable


REQUIRED_COLUMNS = {
    "statement_id",
    "claim_ids",
    "source_locator",
    "deliverable_id",
    "output_path",
    "output_location",
    "statement_type",
    "output_text",
    "status",
    "context_retained",
    "context_omitted",
    "reason",
}
CSV_PROVENANCE_COLUMNS = {
    "parent_report_id",
    "parent_report_version",
    "parent_report_hash",
    "source_claim_ids",
    "transformation_type",
    "dimensions",
    "aspect_ratio",
    "status",
}
CSV_FRAME_COLUMNS = {
    "frame_id",
    "duration_seconds",
    "content_type",
    "visual_source",
    "transformation",
    "transition_intent",
}
MARKDOWN_PROVENANCE_FIELDS = {
    "deliverable_id",
    "parent_report_id",
    "parent_report_version",
    "parent_report_hash",
    "source_claim_ids",
    "transformation_type",
    "dimensions",
    "aspect_ratio",
    "status",
}
MARKDOWN_MARKER = re.compile(r"<!--\s*statement_id:\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*-->")
YAML_MARKER = re.compile(r"(?m)^\s*(?:-\s*)?statement_id:\s*[\"']?([A-Za-z0-9][A-Za-z0-9._-]*)[\"']?\s*$")
JSON_MARKER = re.compile(r'"statement_id"\s*:\s*"([A-Za-z0-9][A-Za-z0-9._-]*)"')


def safe_file(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or any(part in {".", ".."} for part in candidate.parts):
        raise ValueError(f"path must be a safe relative path: {relative!r}")
    target = root / candidate
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes artifacts root: {relative!r}")
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinks are not allowed in artifact paths: {relative!r}")
    if not resolved.is_file():
        raise ValueError(f"artifact is not a regular file: {relative!r}")
    return resolved


def read_mapping(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            headers = set(reader.fieldnames or [])
            missing = sorted(REQUIRED_COLUMNS - headers)
            if missing:
                return [], [f"mapping CSV is missing required columns: {', '.join(missing)}"]
            rows: list[dict[str, str]] = []
            for number, row in enumerate(reader, start=2):
                if None in row:
                    errors.append(f"mapping row {number} has extra fields")
                    continue
                normalized = {key: (value or "").strip() for key, value in row.items() if key is not None}
                if any(value is None for value in row.values()):
                    errors.append(f"mapping row {number} has missing fields")
                rows.append(normalized)
            return rows, errors
    except (OSError, UnicodeError, csv.Error) as exc:
        return [], [f"cannot read mapping CSV: {exc}"]


def read_deliverable(path: Path) -> tuple[dict[str, str], list[str]]:
    """Return statement ID to its exact block text and any structural errors."""
    errors: list[str] = []
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, strict=True)
                headers = set(reader.fieldnames or [])
                needed = {"statement_id", "output_text"}
                if not needed <= headers:
                    return {}, [f"{path.name}: CSV deliverables need statement_id and output_text columns"]
                missing_provenance = sorted(CSV_PROVENANCE_COLUMNS - headers)
                if missing_provenance:
                    errors.append(f"{path.name}: CSV deliverable is missing per-row provenance columns: {', '.join(missing_provenance)}")
                if "frame_id" in headers:
                    missing_frame_fields = sorted(CSV_FRAME_COLUMNS - headers)
                    if missing_frame_fields:
                        errors.append(f"{path.name}: frame CSV is missing production-plan columns: {', '.join(missing_frame_fields)}")
                statements: dict[str, str] = {}
                for number, row in enumerate(reader, start=2):
                    if None in row or any(value is None for value in row.values()):
                        errors.append(f"{path.name}: CSV row {number} has the wrong field count")
                        continue
                    statement_id = (row.get("statement_id") or "").strip()
                    output_text = (row.get("output_text") or "").strip()
                    if not statement_id or not output_text:
                        errors.append(f"{path.name}: CSV row {number} has an empty statement_id or output_text")
                    elif statement_id in statements:
                        errors.append(f"{path.name}: duplicate statement_id {statement_id}")
                    else:
                        statements[statement_id] = output_text
                    for column in CSV_PROVENANCE_COLUMNS:
                        if not (row.get(column) or "").strip():
                            errors.append(f"{path.name}: CSV row {number} has empty provenance field {column}")
                    if (row.get("status") or "").strip() not in {"draft", "ready-for-approval"}:
                        errors.append(f"{path.name}: CSV row {number} has an invalid release status")
                return statements, errors
        except (OSError, UnicodeError, csv.Error) as exc:
            return {}, [f"{path.name}: cannot parse CSV deliverable: {exc}"]

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {}, [f"{path.name}: cannot read deliverable: {exc}"]

    if suffix == ".md":
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            errors.append(f"{path.name}: Markdown deliverables need a YAML provenance header")
        else:
            end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
            if end is None:
                errors.append(f"{path.name}: unterminated YAML provenance header")
                text = ""
            else:
                header = "".join(lines[1:end])
                for field in sorted(MARKDOWN_PROVENANCE_FIELDS):
                    if not re.search(rf"(?m)^\s*{re.escape(field)}:\s*\S.*$", header):
                        errors.append(f"{path.name}: provenance header is missing nonempty {field}")
                status_match = re.search(r"(?m)^\s*status:\s*(\S+)\s*$", header)
                if status_match and status_match.group(1) not in {"draft", "ready-for-approval"}:
                    errors.append(f"{path.name}: provenance header has an invalid release status")
                text = "".join(lines[end + 1 :])
        statements = {}
        for block in re.split(r"\n\s*\n", text):
            content = block.strip()
            if not content:
                continue
            markers = list(MARKDOWN_MARKER.finditer(content))
            if len(markers) != 1:
                errors.append(f"{path.name}: each nonempty Markdown content block needs exactly one statement_id marker")
                continue
            statement_id = markers[0].group(1)
            body = MARKDOWN_MARKER.sub("", content, count=1).strip()
            if statement_id in statements:
                errors.append(f"{path.name}: duplicate statement_id {statement_id}")
            else:
                statements[statement_id] = body
        return statements, errors

    marker_pattern = JSON_MARKER if suffix == ".json" else YAML_MARKER
    if suffix not in {".yaml", ".yml", ".json"}:
        return {}, [f"{path.name}: unsupported deliverable format {suffix or '(no extension)'}"]
    matches = list(marker_pattern.finditer(text))
    if suffix in {".yaml", ".yml"}:
        access_match = re.search(r"(?m)^accessibility_copy:\s*$", text)
        if access_match:
            next_top_level = re.search(r"(?m)^(?!accessibility_copy:)\S[^\r\n]*:\s*(?:\r?$)", text[access_match.end() :])
            access_end = access_match.end() + next_top_level.start() if next_top_level else len(text)
            access_block = text[access_match.end() : access_end]
            item_count = len(re.findall(r"(?m)^\s*-\s+deliverable_id:\s*\S+", access_block))
            item_ids = len(YAML_MARKER.findall(access_block))
            if item_count != item_ids:
                errors.append(f"{path.name}: every accessibility_copy item needs exactly one statement_id")
    statements = {}
    for index, match in enumerate(matches):
        statement_id = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        if statement_id in statements:
            errors.append(f"{path.name}: duplicate statement_id {statement_id}")
        else:
            statements[statement_id] = body
    if not statements:
        errors.append(f"{path.name}: no statement_id fields found")
    return statements, errors


def validate_package(artifacts_root: Path, mapping_path: Path, deliverable_paths: Iterable[Path]) -> list[str]:
    errors: list[str] = []
    try:
        root = artifacts_root.resolve(strict=True)
        mapping = mapping_path.resolve(strict=True)
        if not root.is_dir():
            return ["artifacts root is not a directory"]
        if not mapping.is_file() or not mapping.is_relative_to(root):
            return ["mapping CSV must be a regular file inside the artifacts root"]
    except OSError as exc:
        return [f"cannot resolve artifacts root or mapping CSV: {exc}"]

    rows, row_errors = read_mapping(mapping)
    errors.extend(row_errors)
    expected_ids: dict[str, tuple[str, str]] = {}
    for number, row in enumerate(rows, start=2):
        status = row["status"]
        if status not in {"used", "shortened", "omitted"}:
            errors.append(f"mapping row {number} has unsupported status {status!r}")
            continue
        if status == "omitted":
            if row["statement_id"] or row["output_path"] or row["output_text"]:
                errors.append(f"omitted mapping row {number} must not claim an output statement")
            if not row["claim_ids"] or not row["context_omitted"] or not row["reason"]:
                errors.append(f"omitted mapping row {number} needs claim_ids, context_omitted, and reason")
            continue

        statement_id = row["statement_id"]
        if not statement_id:
            errors.append(f"mapping row {number} is missing statement_id")
            continue
        if statement_id in expected_ids:
            errors.append(f"mapping has duplicate statement_id {statement_id}")
            continue
        if not all(row[key] for key in ("deliverable_id", "output_path", "output_location", "statement_type", "output_text")):
            errors.append(f"mapping row {number} is missing output identity/location/text")
            continue
        if row["statement_type"] in {"sourced_fact", "analysis", "source_metadata"}:
            if not row["claim_ids"] or not row["source_locator"]:
                errors.append(f"mapping row {number} factual statement needs claim_ids and source_locator")
        if row["statement_type"] == "recommendation" and not row["reason"]:
            errors.append(f"mapping row {number} recommendation needs its rationale")
        if status == "shortened" and (not row["context_omitted"] or not row["reason"]):
            errors.append(f"mapping row {number} shortened statement needs omitted context and reason")
        expected_ids[statement_id] = (row["output_path"], row["output_text"])

    declared: dict[str, Path] = {}
    for relative in deliverable_paths:
        try:
            target = safe_file(root, relative.as_posix())
            rel = target.relative_to(root).as_posix()
            if rel in declared:
                errors.append(f"duplicate declared deliverable: {rel}")
            declared[rel] = target
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if not declared:
        errors.append("at least one deliverable must be declared")

    found_ids: dict[str, tuple[str, str]] = {}
    for relative, target in declared.items():
        statements, structural_errors = read_deliverable(target)
        errors.extend(structural_errors)
        for statement_id, body in statements.items():
            if statement_id in found_ids:
                errors.append(f"statement_id {statement_id} appears in more than one deliverable")
            else:
                found_ids[statement_id] = (relative, body)

    for statement_id in sorted(expected_ids.keys() - found_ids.keys()):
        errors.append(f"mapped statement {statement_id} is absent from declared deliverables")
    for statement_id in sorted(found_ids.keys() - expected_ids.keys()):
        errors.append(f"unmapped statement {statement_id} appears in a declared deliverable")
    for statement_id in sorted(expected_ids.keys() & found_ids.keys()):
        expected_path, output_text = expected_ids[statement_id]
        found_path, body = found_ids[statement_id]
        try:
            normalized_expected = Path(expected_path).as_posix()
        except TypeError:
            normalized_expected = expected_path
        if normalized_expected != found_path:
            errors.append(f"statement {statement_id} path mismatch: map={normalized_expected!r}, file={found_path!r}")
        if target.suffix.casefold() == ".md":
            if output_text != body.strip():
                errors.append(f"statement {statement_id} output_text is not the complete marked Markdown block")
        elif target.suffix.casefold() == ".csv":
            if output_text != body:
                errors.append(f"statement {statement_id} output_text does not exactly match its CSV row")
        elif output_text not in body:
            errors.append(f"statement {statement_id} output_text does not match its marked output block")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--deliverable", type=Path, action="append", required=True)
    args = parser.parse_args()
    errors = validate_package(args.artifacts_root, args.mapping, args.deliverable)
    if errors:
        print(f"Derivative traceability validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Derivative traceability validation passed: all declared statement IDs and verbatim output text reconcile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
