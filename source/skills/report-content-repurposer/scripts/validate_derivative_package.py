#!/usr/bin/env python3
"""Validate statement-level coverage in a local derivative package.

The claim-mapping CSV is the inventory of every copy-bearing output unit.
Markdown units use an HTML comment marker, structured text units use a
``statement_id`` field, and CSV deliverables contain one copy unit per row.
This script checks that inventory against the exact local deliverable files.
"""

from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date
import hashlib
import json
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
    "visual_unit_id",
    "related_statement_ids",
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
VIDEO_CONTENT_TYPES = {"on_screen_copy", "narration", "caption", "accessibility_transcript"}
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
                frame_types: dict[str, list[str]] = {}
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
                    if "frame_id" in headers:
                        frame_id = (row.get("frame_id") or "").strip()
                        content_type = (row.get("content_type") or "").strip()
                        for column in CSV_FRAME_COLUMNS:
                            if not (row.get(column) or "").strip():
                                errors.append(f"{path.name}: CSV row {number} has empty frame field {column}")
                        if content_type not in VIDEO_CONTENT_TYPES:
                            errors.append(f"{path.name}: CSV row {number} has unsupported frame content_type {content_type!r}")
                        if frame_id:
                            frame_types.setdefault(frame_id, []).append(content_type)
                        else:
                            errors.append(f"{path.name}: CSV row {number} has an empty frame_id")
                if "frame_id" in headers:
                    for frame_id, content_types in frame_types.items():
                        transcript_count = content_types.count("accessibility_transcript")
                        if transcript_count != 1:
                            errors.append(f"{path.name}: frame {frame_id} needs exactly one accessibility_transcript row")
                        if not any(item in {"on_screen_copy", "narration", "caption"} for item in content_types):
                            errors.append(f"{path.name}: frame {frame_id} has no visual or spoken copy row")
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
        if suffix in {".yaml", ".yml"} and re.search(r"(?m)^source_report:\s*$", text):
            return statements, errors
        errors.append(f"{path.name}: no statement_id fields found")
    return statements, errors


def provenance_hashes(path: Path) -> tuple[set[str], str | None]:
    """Read per-file parent hashes and a manifest's canonical source hash."""
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if "parent_report_hash" not in (reader.fieldnames or []):
                return set(), None
            values = {(row.get("parent_report_hash") or "").strip() for row in reader}
            return {value for value in values if value}, None

    text = path.read_text(encoding="utf-8-sig")
    if suffix == ".md":
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return set(), None
        end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if end is None:
            return set(), None
        header = "\n".join(lines[1:end])
        match = re.search(r"(?m)^\s*parent_report_hash:\s*(.*?)\s*$", header)
        return ({match.group(1).strip().strip("\"'")} if match else set()), None

    if suffix == ".json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            return set(), None

        def collect_hashes(value: object) -> set[str]:
            found: set[str] = set()
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key == "parent_report_hash" and isinstance(nested, str) and nested.strip():
                        found.add(nested.strip())
                    else:
                        found.update(collect_hashes(nested))
            elif isinstance(value, list):
                for nested in value:
                    found.update(collect_hashes(nested))
            return found

        source = document.get("source_report") if isinstance(document, dict) else None
        source_hash = source.get("hash") if isinstance(source, dict) else None
        canonical = source_hash.strip() if isinstance(source_hash, str) and source_hash.strip() else None
        return collect_hashes(document), canonical

    parent_values = {
        match.group(1).strip().strip("\"'")
        for match in re.finditer(r"(?m)^\s*parent_report_hash:\s*(.*?)\s*$", text)
        if match.group(1).strip()
    }
    source_hash = None
    source_section = re.search(
        r"(?ms)^source_report:\s*\r?\n(?P<section>(?:[ \t]+.*(?:\r?\n|$))*)",
        text,
    )
    if source_section:
        hash_match = re.search(r"(?m)^\s+hash:\s*(.*?)\s*$", source_section.group("section"))
        if hash_match:
            source_hash = hash_match.group(1).strip().strip("\"'") or None
    return parent_values, source_hash


def manifest_deliverable_roles(path: Path) -> dict[str, str]:
    """Return manifest deliverable IDs and their requested/supporting role."""
    suffix = path.suffix.casefold()
    if suffix == ".json":
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        deliverables = document.get("deliverables", []) if isinstance(document, dict) else []
        roles = {}
        for item in deliverables:
            if isinstance(item, dict) and item.get("deliverable_id"):
                key = str(item["deliverable_id"]).strip()
                if key in roles:
                    raise ValueError(f"manifest has duplicate deliverable_id {key}")
                roles[key] = str(item.get("role", "")).strip()
        return roles
    if suffix not in {".yaml", ".yml"}:
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {}
    section = re.search(
        r"(?ms)^deliverables:\s*\r?\n(?P<section>(?:[ \t]+.*(?:\r?\n|$))*)",
        text,
    )
    if not section:
        return {}
    section_text = section.group("section")
    starts = list(re.finditer(r"(?m)^\s*-\s*deliverable_id:\s*(.*?)\s*$", section_text))
    roles: dict[str, str] = {}
    for index, match in enumerate(starts):
        deliverable_id = match.group(1).strip().strip("\"'")
        if not deliverable_id:
            continue
        if deliverable_id in roles:
            raise ValueError(f"manifest has duplicate deliverable_id {deliverable_id}")
        end = starts[index + 1].start() if index + 1 < len(starts) else len(section_text)
        entry = section_text[match.end() : end]
        role_match = re.search(r"(?m)^\s*role:\s*[\"']?([^\r\n\"']+)[\"']?\s*$", entry)
        roles[deliverable_id] = role_match.group(1).strip() if role_match else ""
    return roles


def manifest_contract_paths(path: Path) -> dict[str, object]:
    """Read the manifest's declared package-relative review records."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.casefold() == ".json":
        document = json.loads(text)
        return {key: document.get(key) for key in ("source_inventory", "statement_support")} if isinstance(document, dict) else {}
    pointers = {}
    for key in ("source_inventory", "statement_support"):
        matches = list(re.finditer(rf"(?m)^{key}:\s*(.*?)\s*$", text))
        pointers[key] = matches[0].group(1).strip().strip("\"'") if len(matches) == 1 else None
    return pointers


def normalized_prose(text: str) -> str:
    """Normalize light Markdown while retaining every word and qualifier."""
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*`_~]", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


SUPPORT_COLUMNS = {"support_id", "statement_id", "source_unit_id", "output_text", "output_occurrence", "claim_ids", "source_locator", "kind", "metadata_field", "reason"}
SOURCE_KINDS = {"sourced_fact", "analysis", "recommendation", "safeguard", "stop_rule", "measurement", "source_metadata", "nonfactual"}
METADATA_FIELDS = {"report_title", "reporting_period", "evidence_cutoff"}
MONTH_NAMES = "January February March April May June July August September October November December".split()
MONTH_PATTERN = "(?:" + "|".join(MONTH_NAMES) + ")"
DATE_PATTERN = rf"(?:[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}|{MONTH_PATTERN} [0-9]{{1,2}}, [0-9]{{4}})"
PERIOD_PATTERN = rf"(?:{DATE_PATTERN} (?:through|to) {DATE_PATTERN}|{MONTH_PATTERN}(?: [0-9]{{4}})? (?:through|to) {MONTH_PATTERN} [0-9]{{4}})"
METADATA_LABEL = r"(?:reporting[ _]period|evidence[ _]cutoff)"


def calendar_value(value: str, field: str) -> bool:
    """Validate supported calendar syntax, not the semantics of arbitrary prose."""
    def day(text: str) -> date:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            return date.fromisoformat(text)
        match = re.fullmatch(rf"({MONTH_PATTERN}) ([0-9]{{1,2}}), ([0-9]{{4}})", text, re.I)
        if not match:
            raise ValueError("unsupported date")
        month = next(index for index, name in enumerate(MONTH_NAMES, 1) if name.casefold() == match.group(1).casefold())
        return date(int(match.group(3)), month, int(match.group(2)))

    try:
        if field == "evidence_cutoff":
            day(value)
            return True
        first, last = re.split(r" (?:through|to) ", value, flags=re.I)
        if re.fullmatch(DATE_PATTERN, first, re.I) and re.fullmatch(DATE_PATTERN, last, re.I):
            return day(first) <= day(last)
        last_match = re.fullmatch(rf"({MONTH_PATTERN}) ([0-9]{{4}})", last, re.I)
        first_match = re.fullmatch(rf"({MONTH_PATTERN})(?: ([0-9]{{4}}))?", first, re.I)
        if not first_match or not last_match:
            return False
        first_month = next(index for index, name in enumerate(MONTH_NAMES, 1) if name.casefold() == first_match.group(1).casefold())
        last_month = next(index for index, name in enumerate(MONTH_NAMES, 1) if name.casefold() == last_match.group(1).casefold())
        first_year, last_year = int(first_match.group(2) or last_match.group(2)), int(last_match.group(2))
        return date(first_year, first_month, 1) <= date(last_year, last_month, calendar.monthrange(last_year, last_month)[1])
    except (ValueError, StopIteration):
        return False


def report_metadata_bindings(lines: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Resolve source-owned fields through an explicit, narrow syntax adapter.

    No inventory declaration can create a binding. Unrecognized narrative is
    not classified automatically; a requested metadata binding fails closed
    when its calendar syntax is unsupported, invalid or ambiguous.
    """
    candidates: dict[str, list[dict]] = {}
    declarations: dict[str, int] = {}
    errors = []
    title_found = False
    label = re.compile(rf"(?:and )?(?:the )?(?P<label>{METADATA_LABEL})(?: runs from | is |[ \t]*[:=][ \t]*)", re.I)
    boundary = rf"(?=[ \t]*(?:[.;]|$|and (?:the )?{METADATA_LABEL}\b))"
    for index, line in enumerate(lines):
        title = re.match(r"^\s*#\s+(.*?)\s*$", line)
        if title and not title_found:
            title_found = True
            candidates["report_title"] = [{"source_locator": f"line:{index + 1}", "source_text": title.group(1), "start": title.start(1), "end": title.end(1)}]
            declarations["report_title"] = 1
        position = len(line) - len(line.lstrip())
        while position < len(line):
            field_match = label.match(line, position)
            if not field_match:
                break
            field = field_match.group("label").casefold().replace(" ", "_")
            declarations[field] = declarations.get(field, 0) + 1
            value_pattern = PERIOD_PATTERN if field == "reporting_period" else DATE_PATTERN
            value_match = re.match(rf"(?P<value>{value_pattern})(?![0-9A-Za-z])", line[field_match.end():], re.I)
            if not value_match or not calendar_value(value_match.group("value"), field):
                break
            value_end = field_match.end() + value_match.end()
            # An explicitly cited external study date remains sourced evidence,
            # not an IDless administrative field. Unsupported narrative never
            # creates a metadata binding; a declared metadata unit then fails.
            if re.match(r"[ \t]*(?:\(\s*`?[\w][\w.-]*`?\s*\)|\[[^\]]+\])", line[value_end:]):
                declarations[field] -= 1
                break
            ending = re.match(boundary + r"(?:[ \t]*[.;])?", line[value_end:], re.I)
            if not ending:
                break
            end = value_end + ending.end()
            if re.match(r"[ \t]*(?:\(\s*`?[\w][\w.-]*`?\s*\)|\[[^\]]+\])", line[end:]):
                declarations[field] -= 1
                break
            candidates.setdefault(field, []).append({"source_locator": f"line:{index + 1}", "source_text": line[position:end], "start": position, "end": end})
            position = end
            while position < len(line) and line[position].isspace():
                position += 1
    bindings = {}
    for field, count in declarations.items():
        values = candidates.get(field, [])
        if count > 1:
            errors.append(f"report-owned metadata {field} has ambiguous source declarations")
        elif len(values) == 1:
            bindings[field] = values[0]
    return bindings, errors


def id_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def literal_metadata(text: str) -> str:
    """Allow heading/line-wrap layout, preserving field values and link targets."""
    return re.sub(r"\s+", " ", re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)).strip()


def literal_field_pattern(quote: str) -> str:
    """Exact field spelling/link targets, never a substring of a larger word."""
    literal = literal_metadata(quote)
    return (r"(?<!\w)" if literal and (literal[0].isalnum() or literal[0] == "_") else "") + re.escape(literal) + (r"(?!\w)" if literal and (literal[-1].isalnum() or literal[-1] == "_") else "")


def bounded_index(value: str, limit: int) -> int:
    """Reject oversized indices before integer conversion."""
    if not re.fullmatch(r"[1-9][0-9]*", value) or len(value) > len(str(limit)):
        return 0
    number = int(value)
    return number if number <= limit else 0


def validate_source_contract(
    root: Path,
    mapping_path: Path,
    deliverable_paths: Iterable[Path],
    source_report_path: Path,
    inventory_path: Path,
    support_path: Path,
) -> list[str]:
    """Reconcile a manually reviewed source inventory, not infer semantic support.

    Literal line coverage prevents an inventory silently excluding source prose.
    Clause boundaries, classifications, entailment and materiality still require
    the declared manual review. A structurally valid inventory is not approval.
    """
    errors: list[str] = []
    try:
        root = root.resolve(strict=True)
        inventory_file = safe_file(root, inventory_path.absolute().relative_to(root).as_posix())
        support_file = safe_file(root, support_path.absolute().relative_to(root).as_posix())
        if source_report_path.is_symlink() or not source_report_path.is_file():
            return ["source report must be a regular non-link file"]
        source = source_report_path.read_text(encoding="utf-8-sig")
        source_hash = f"sha256:{hashlib.sha256(source_report_path.read_bytes()).hexdigest()}"
        inventory = json.loads(inventory_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"required source inventory and statement support cannot be read: {exc}"]
    if not isinstance(inventory, dict) or inventory.get("schema_version") != "1.0":
        return ["source inventory must use schema_version 1.0"]
    if inventory.get("source_report_hash") != source_hash:
        errors.append("source inventory hash does not match source report bytes")
    review = inventory.get("review", {})
    checks = {"atomic-units", "source-types", "semantic-support", "material-omissions"}
    recorded_checks = review.get("checks", []) if isinstance(review, dict) else []
    valid_checks = isinstance(recorded_checks, list) and all(isinstance(check, str) for check in recorded_checks)
    if not isinstance(review, dict) or review.get("status") != "complete" or review.get("method") != "manual-clause-review" or not valid_checks or not checks <= set(recorded_checks):
        errors.append("source inventory needs complete manual-clause-review of atomic-units, source-types, semantic-support and material-omissions")
    source_lines = source.splitlines()
    metadata_bindings, metadata_errors = report_metadata_bindings(source_lines)
    errors.extend(metadata_errors)
    metadata_units: set[str] = set()
    covered = [set() for _ in source_lines]
    units: dict[str, dict] = {}
    raw_units = inventory.get("source_units", [])
    if not isinstance(raw_units, list) or not raw_units:
        errors.append("source inventory needs nonempty source_units")
        raw_units = []
    for unit in raw_units:
        if not isinstance(unit, dict):
            errors.append("source inventory unit must be an object")
            continue
        unit_id = unit.get("source_unit_id", "")
        if not isinstance(unit_id, str) or not unit_id or unit_id in units:
            errors.append("source inventory has empty or duplicate source_unit_id")
            continue
        kind, quote, locator = unit.get("kind"), unit.get("source_text"), unit.get("source_locator", "")
        claims = unit.get("claim_ids", [])
        if not isinstance(kind, str) or kind not in SOURCE_KINDS or not isinstance(quote, str) or not quote:
            errors.append(f"source unit {unit_id} needs a supported kind and literal source_text")
            continue
        if not isinstance(claims, list) or any(not isinstance(claim, str) or not claim for claim in claims) or len(set(claims)) != len(claims):
            errors.append(f"source unit {unit_id} needs a unique claim_ids array")
            continue
        units[unit_id] = unit
        if kind in {"sourced_fact", "analysis"} and not claims:
            errors.append(f"source unit {unit_id} factual/analysis support needs exact claim_ids")
        if kind == "source_metadata" and claims:
            errors.append(f"source unit {unit_id} metadata must not carry claim_ids")
        metadata_field = unit.get("metadata_field", "")
        if kind == "source_metadata":
            binding = metadata_bindings.get(metadata_field) if isinstance(metadata_field, str) else None
            if not isinstance(metadata_field, str) or metadata_field not in METADATA_FIELDS:
                errors.append(f"source unit {unit_id} metadata needs a known metadata_field")
            elif metadata_field in metadata_units:
                errors.append(f"source inventory repeats metadata_field {metadata_field}")
            elif not binding or locator != binding["source_locator"] or quote != binding["source_text"]:
                errors.append(f"source unit {unit_id} metadata must match its complete independently resolved source field")
            if isinstance(metadata_field, str):
                metadata_units.add(metadata_field)
        elif not isinstance(metadata_field, str) or metadata_field:
            errors.append(f"source unit {unit_id} metadata_field is only allowed on source_metadata")
        for claim in claims:
            if not re.search(rf"(?<![\w.-]){re.escape(claim)}(?![\w.-])", source):
                errors.append(f"source unit {unit_id} claim_id {claim} does not occur verbatim in source")
        match = re.fullmatch(r"line:([1-9][0-9]*)", locator) if isinstance(locator, str) else None
        line_number = bounded_index(match.group(1), len(source_lines)) if match else 0
        if not 1 <= line_number <= len(source_lines):
            errors.append(f"source unit {unit_id} needs an exact line:N locator")
            continue
        line = source_lines[line_number - 1]
        start = line.find(quote)
        if start < 0 or line.find(quote, start + 1) >= 0:
            errors.append(f"source unit {unit_id} source_text must occur exactly once at {locator}")
            continue
        for field, binding in metadata_bindings.items():
            if locator == binding["source_locator"] and start < binding["end"] and start + len(quote) > binding["start"]:
                if kind != "source_metadata" or metadata_field != field or quote != binding["source_text"]:
                    errors.append(f"source unit {unit_id} overlaps report-owned field {field}; require its complete IDless source_metadata binding")
        covered[line_number - 1].update(range(start, start + len(quote)))
    for index, line in enumerate(source_lines):
        # Markdown headings organize source prose; their wording is still quoted
        # when reused (notably the required visible report title).
        if not line.strip() or re.match(r"^\s*#{1,6}\s", line):
            continue
        if any(not char.isspace() and offset not in covered[index] for offset, char in enumerate(line)):
            errors.append(f"source line {index + 1} has text missing from the upstream inventory: {line[:100]}")

    rows, mapping_errors = read_mapping(mapping_path)
    errors.extend(mapping_errors)
    mapped = {row["statement_id"]: row for row in rows if row["status"] != "omitted"}
    formats: set[str] = set()
    roles: dict[str, str] = {}
    declared: dict[str, Path] = {}
    for relative in deliverable_paths:
        try:
            target = safe_file(root, relative.as_posix())
            declared[relative.as_posix()] = target
            entry_roles = manifest_deliverable_roles(target)
            if entry_roles:
                pointers = manifest_contract_paths(target)
                for key, checked_file in (("source_inventory", inventory_file), ("statement_support", support_file)):
                    pointer = pointers.get(key)
                    expected_path = checked_file.relative_to(root).as_posix()
                    if not isinstance(pointer, str) or pointer.replace("\\", "/") != expected_path:
                        errors.append(f"manifest {relative.as_posix()} {key} must name the exact validated relative path {expected_path}")
            if roles.keys() & entry_roles.keys():
                errors.append("declared manifests repeat deliverable_id entries")
            roles.update(entry_roles)
            formats.update(key for key, role in entry_roles.items() if role == "requested-format")
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if not formats:
        errors.append("source reconciliation needs explicit requested-format manifest entries")
    format_paths: dict[str, set[str]] = {}
    for statement_id, row in mapped.items():
        if row["deliverable_id"] not in roles:
            errors.append(f"output statement {statement_id} references an absent manifest deliverable_id")
        if row["deliverable_id"] in formats:
            format_paths.setdefault(row["deliverable_id"], set()).add(row["output_path"])
        target = declared.get(row["output_path"])
        if target and target.suffix.casefold() == ".md":
            match = re.search(r"(?m)^deliverable_id:\s*(.*?)\s*$", target.read_text(encoding="utf-8-sig").split("---", 2)[1] if "---" in target.read_text(encoding="utf-8-sig") else "")
            if not match or match.group(1).strip().strip("\"'") != row["deliverable_id"]:
                errors.append(f"output statement {statement_id} deliverable_id disagrees with its file header")
    for format_id in formats:
        if len(format_paths.get(format_id, set())) != 1:
            errors.append(f"requested format {format_id} must bind exactly one copy-bearing output file")
    try:
        with support_file.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            headers = next(reader, [])
            if any(not header.strip() for header in headers) or len({header.casefold() for header in headers}) != len(headers) or not SUPPORT_COLUMNS <= set(headers):
                return errors + ["statement support CSV is missing required columns"]
            support_rows = []
            for number, values in enumerate(reader, 2):
                if len(values) != len(headers) or not any(value.strip() for value in values):
                    errors.append(f"statement support row {number} has the wrong field count")
                    continue
                support_rows.append(dict(zip(headers, (value.strip() for value in values))))
    except (OSError, UnicodeError, csv.Error) as exc:
        return errors + [f"cannot read statement support CSV: {exc}"]
    supports: dict[str, list[dict[str, str]]] = {}
    seen_support_ids: set[str] = set()
    occurrence_bindings: set[tuple[str, str, int]] = set()
    uses: dict[tuple[str, str], set[str]] = {}
    for child in support_rows:
        support_id, statement_id = child["support_id"], child["statement_id"]
        if not support_id or support_id in seen_support_ids:
            errors.append("statement support has empty or duplicate support_id")
        seen_support_ids.add(support_id)
        parent = mapped.get(statement_id)
        if parent is None:
            errors.append(f"support {support_id} has no canonical output statement {statement_id}")
            continue
        if child["kind"] != "source_metadata" and child["metadata_field"]:
            errors.append(f"support {support_id} metadata_field is only allowed on source_metadata")
        supports.setdefault(statement_id, []).append(child)
        fragment = normalized_prose(child["output_text"])
        occurrences = list(re.finditer(re.escape(fragment), normalized_prose(parent["output_text"]))) if fragment else []
        occurrence = bounded_index(child["output_occurrence"], len(occurrences))
        binding = (statement_id, fragment, occurrence)
        if not occurrence or occurrence > len(occurrences):
            errors.append(f"support {support_id} output_text is not a literal fragment of {statement_id}")
        elif binding in occurrence_bindings:
            errors.append(f"support {support_id} repeats an output occurrence binding")
        occurrence_bindings.add(binding)
        if child["kind"] == "nonfactual" and not child["source_unit_id"]:
            if child["claim_ids"] or child["source_locator"] or not child["reason"]:
                errors.append(f"nonfactual support {support_id} needs rationale and no evidence values")
            if parent["statement_type"] not in {"nonfactual", "accessibility_copy"}:
                errors.append(f"support {support_id} cannot classify factual or metadata output as nonfactual")
            continue
        unit = units.get(child["source_unit_id"])
        if unit is None:
            errors.append(f"support {support_id} references an absent source_unit_id")
            continue
        if child["kind"] != unit.get("kind") or child["source_locator"] != unit.get("source_locator") or set(id_list(child["claim_ids"])) != set(unit.get("claim_ids", [])):
            errors.append(f"support {support_id} kind, locator and claim_ids must match its exact source unit")
        if parent["statement_type"] == "source_metadata" and child["kind"] != "source_metadata":
            errors.append(f"metadata statement {statement_id} contains non-metadata support")
        if child["kind"] == "source_metadata" and (child["metadata_field"] not in METADATA_FIELDS or child["metadata_field"] != unit.get("metadata_field")):
            errors.append(f"metadata support {support_id} must name its exact metadata_field")
        if child["kind"] == "source_metadata" and literal_metadata(child["output_text"]) != literal_metadata(unit["source_text"]):
            errors.append(f"metadata support {support_id} must reproduce only its literal source field")
        if child["kind"] == "source_metadata" and literal_metadata(child["output_text"]) not in literal_metadata(parent["output_text"]):
            errors.append(f"metadata support {support_id} must preserve its literal field in canonical output")
        uses.setdefault((child["source_unit_id"], parent["deliverable_id"]), set()).add(statement_id)
    for statement_id, parent in mapped.items():
        children = supports.get(statement_id, [])
        text = normalized_prose(parent["output_text"])
        positions: set[int] = set()
        child_claims: set[str] = set()
        child_spans: list[tuple[dict, int, int]] = []
        for child in children:
            fragment = normalized_prose(child["output_text"])
            matches = list(re.finditer(re.escape(fragment), text)) if fragment else []
            occurrence = bounded_index(child["output_occurrence"], len(matches))
            if 1 <= occurrence <= len(matches):
                match = matches[occurrence - 1]
                positions.update(range(match.start(), match.end()))
                child_spans.append((child, match.start(), match.end()))
            child_claims.update(id_list(child["claim_ids"]))
        if any(char.isalnum() and index not in positions for index, char in enumerate(text)):
            errors.append(f"statement {statement_id} has copy without atomic support records")
        if set(id_list(parent["claim_ids"])) != child_claims:
            errors.append(f"statement {statement_id} claim_ids must equal its atomic support claims")
        # Reserve exact known field occurrences without guessing at paraphrases.
        # A shared title word or identical external date may instead have its
        # own literal, genuinely cited source-unit provenance; nearby IDs alone
        # do not qualify. Semantic support of those IDs remains manual review.
        literal_parent = literal_metadata(parent["output_text"])
        for field, source_binding in metadata_bindings.items():
            pattern = literal_field_pattern(source_binding["source_text"])
            field_text = normalized_prose(source_binding["source_text"])
            for occurrence in re.finditer(pattern, literal_parent):
                prefix = literal_parent[:occurrence.start()]
                start = len(normalized_prose(prefix)) + (1 if prefix.endswith(" ") and normalized_prose(prefix) else 0)
                end = start + len(field_text)
                supported = False
                for child, child_start, child_end in child_spans:
                    unit = units.get(child["source_unit_id"])
                    if not unit or child_start > start or child_end < end:
                        continue
                    if child["kind"] == "source_metadata" and child["metadata_field"] == field and unit.get("kind") == "source_metadata" and unit.get("metadata_field") == field:
                        supported = True
                    elif child["kind"] in {"sourced_fact", "analysis"} and unit.get("kind") == child["kind"] and unit.get("claim_ids") and re.search(pattern, literal_metadata(unit["source_text"])) and re.search(pattern, literal_metadata(child["output_text"])):
                        supported = True
                if not supported:
                    errors.append(f"statement {statement_id} literal field {field} needs its metadata_field-bound or exact cited source-unit support")
    coverage: dict[tuple[str, str], dict] = {}
    raw_coverage = inventory.get("coverage", [])
    if not isinstance(raw_coverage, list):
        raw_coverage = []
        errors.append("source inventory coverage must be an array")
    for entry in raw_coverage:
        if not isinstance(entry, dict):
            errors.append("source coverage entry must be an object")
            continue
        unit_id, format_id = entry.get("source_unit_id"), entry.get("deliverable_id")
        if not isinstance(unit_id, str) or not isinstance(format_id, str):
            errors.append("source coverage needs string source_unit_id and deliverable_id")
            continue
        key = (unit_id, format_id)
        if key[0] not in units or key[1] not in formats or key in coverage:
            errors.append("source coverage has unknown or duplicate source-unit/format pair")
            continue
        coverage[key] = entry
        actual = uses.get(key, set())
        stated = entry.get("statement_ids", [])
        if not isinstance(stated, list) or any(not isinstance(item, str) for item in stated) or len(set(stated)) != len(stated):
            errors.append(f"source coverage {key} needs unique statement_ids")
            continue
        status = entry.get("status")
        if not isinstance(status, str):
            errors.append(f"source coverage {key} has unsupported status")
            continue
        omitted = entry.get("context_omitted", "")
        if status == "omitted":
            if stated or actual or omitted != units[key[0]]["source_text"] or not entry.get("reason"):
                errors.append(f"omitted source coverage {key} needs no output, its complete source_text and a reason")
        elif status in {"used", "shortened"}:
            if not actual or set(stated) != actual:
                errors.append(f"source coverage {key} must list exactly its supported output statements")
            if status == "used" and omitted != "none":
                errors.append(f"used source coverage {key} needs context_omitted none")
            if status == "shortened" and (not isinstance(omitted, str) or not omitted or omitted == "none" or omitted not in units[key[0]]["source_text"] or not entry.get("reason")):
                errors.append(f"shortened source coverage {key} needs literal omitted source text and a reason")
        else:
            errors.append(f"source coverage {key} has unsupported status")
    for unit_id in units:
        for format_id in formats:
            if (unit_id, format_id) not in coverage:
                errors.append(f"source unit {unit_id} has no retained/shortened/omitted coverage for {format_id}")
    return errors


def validate_package(
    artifacts_root: Path,
    mapping_path: Path,
    deliverable_paths: Iterable[Path],
    source_report_path: Path | None = None,
) -> list[str]:
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
    expected_ids: dict[str, dict[str, str]] = {}
    mapped_rows: list[dict[str, str]] = []
    allowed_statement_types = {"sourced_fact", "analysis", "recommendation", "source_metadata", "nonfactual", "accessibility_copy"}
    for number, row in enumerate(rows, start=2):
        status = row["status"]
        if status not in {"used", "shortened", "omitted"}:
            errors.append(f"mapping row {number} has unsupported status {status!r}")
            continue
        if status == "omitted":
            if row["statement_id"] or row["output_path"] or row["output_text"]:
                errors.append(f"omitted mapping row {number} must not claim an output statement")
            if not row["deliverable_id"] or not row["output_location"]:
                errors.append(f"omitted mapping row {number} needs its deliverable_id and omitted output_location")
            if (not row["claim_ids"] and not row["source_locator"]) or not row["context_omitted"] or not row["reason"]:
                errors.append(f"omitted mapping row {number} needs claim_ids or source_locator, context_omitted, and reason")
            if row["statement_type"] not in allowed_statement_types:
                errors.append(f"omitted mapping row {number} needs a supported statement_type")
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
        if row["statement_type"] not in allowed_statement_types:
            errors.append(f"mapping row {number} has unsupported statement_type {row['statement_type']!r}")
        if row["statement_type"] in {"sourced_fact", "analysis"}:
            if not row["claim_ids"] or not row["source_locator"]:
                errors.append(f"mapping row {number} factual statement needs claim_ids and source_locator")
        if row["statement_type"] == "source_metadata":
            if not row["source_locator"]:
                errors.append(f"mapping row {number} source metadata needs its exact metadata-field locator")
            if row["claim_ids"]:
                errors.append(f"mapping row {number} source metadata must not be assigned unrelated claim_ids")
        if row["statement_type"] == "recommendation" and not row["reason"]:
            errors.append(f"mapping row {number} recommendation needs its rationale")
        if row["statement_type"] == "accessibility_copy" and (not row["visual_unit_id"] or not row["related_statement_ids"]):
            errors.append(f"mapping row {number} accessibility copy needs visual_unit_id and related_statement_ids")
        if row["statement_type"] == "accessibility_copy" and not row["source_locator"]:
            errors.append(f"mapping row {number} accessibility copy needs an exact source locator")
        if row["statement_type"] in {"sourced_fact", "analysis", "recommendation", "nonfactual"} and not row["visual_unit_id"]:
            errors.append(f"mapping row {number} visual content needs visual_unit_id")
        if row["output_path"].casefold().endswith(".md") and row["statement_type"] != "accessibility_copy" and not row["visual_unit_id"]:
            errors.append(f"mapping row {number} Markdown copy needs visual_unit_id")
        if status == "shortened" and (not row["context_omitted"] or not row["reason"]):
            errors.append(f"mapping row {number} shortened statement needs omitted context and reason")
        if not row["context_retained"] or not row["context_omitted"]:
            errors.append(f"mapping row {number} needs explicit context_retained and context_omitted (use 'none' when empty)")
        expected_ids[statement_id] = {
            "output_path": row["output_path"],
            "output_text": row["output_text"],
            "statement_type": row["statement_type"],
            "visual_unit_id": row["visual_unit_id"],
            "related_statement_ids": row["related_statement_ids"],
            "output_location": row["output_location"],
        }
        mapped_rows.append(row)

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

    manifest_source_hashes: set[str] = set()
    provenance_by_path: dict[str, set[str]] = {}
    manifest_roles: dict[str, str] = {}
    for relative, target in declared.items():
        try:
            parent_values, source_hash = provenance_hashes(target)
            provenance_by_path[relative] = parent_values
            entry_roles = manifest_deliverable_roles(target)
            if manifest_roles.keys() & entry_roles.keys():
                errors.append("declared manifests repeat deliverable_id entries")
            manifest_roles.update(entry_roles)
            if source_hash:
                manifest_source_hashes.add(source_hash)
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            errors.append(f"{relative}: cannot read report-hash provenance: {exc}")
    source_hash_from_file: str | None = None
    approved_title: str | None = None
    if source_report_path is not None:
        try:
            if source_report_path.is_symlink():
                return ["source report must be a regular non-link file"]
            source_file = source_report_path.resolve(strict=True)
            if not source_file.is_file():
                return ["source report must be a regular non-link file"]
            source_hash_from_file = f"sha256:{hashlib.sha256(source_file.read_bytes()).hexdigest()}"
            try:
                source_text = source_file.read_text(encoding="utf-8-sig")
            except UnicodeError:
                source_text = ""
            title_match = re.search(r"(?m)^#\s+(.+?)\s*#*\s*$", source_text)
            approved_title = title_match.group(1).strip() if title_match else None
        except OSError as exc:
            return [f"cannot read source report for hash verification: {exc}"]
        for declared_hash in manifest_source_hashes:
            if declared_hash.casefold() != source_hash_from_file.casefold():
                errors.append(f"manifest source hash {declared_hash!r} does not match source report bytes")

    if len(manifest_source_hashes) > 1:
        errors.append("declared manifests disagree on the canonical source-report hash")
    elif source_hash_from_file or (manifest_source_hashes and next(iter(manifest_source_hashes)).casefold() != "unknown"):
        canonical_hash = source_hash_from_file or next(iter(manifest_source_hashes))
        for relative, values in provenance_by_path.items():
            for value in values:
                if value.casefold() != canonical_hash.casefold():
                    errors.append(f"{relative}: parent_report_hash {value!r} does not match manifest source hash")
    manifest_deliverables = set(manifest_roles)
    for deliverable_id, role in manifest_roles.items():
        if role not in {"requested-format", "supporting-artifact"}:
            errors.append(f"manifest deliverable {deliverable_id} needs role requested-format or supporting-artifact")
    requested_format_ids = {
        deliverable_id for deliverable_id, role in manifest_roles.items() if role == "requested-format"
    }
    visual_scope_ids = requested_format_ids or manifest_deliverables
    if approved_title:
        requested_formats: dict[str, list[dict[str, str]]] = {}
        for row in mapped_rows:
            if row["status"] == "omitted" or row["output_path"] not in declared:
                continue
            if Path(row["output_path"]).name.casefold().startswith("derivative-manifest"):
                continue
            if visual_scope_ids and row["deliverable_id"] not in visual_scope_ids:
                continue
            requested_formats.setdefault(row["deliverable_id"], []).append(row)
        format_ids = visual_scope_ids or set(requested_formats)
        for deliverable_id in sorted(format_ids):
            format_rows = requested_formats.get(deliverable_id, [])
            visible_copy = "\n".join(
                row["output_text"]
                for row in format_rows
                if row["statement_type"] != "accessibility_copy"
            )
            if approved_title not in visible_copy:
                errors.append(f"deliverable {deliverable_id} must include the exact approved report title as visible copy")

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
        expected = expected_ids[statement_id]
        expected_path, output_text = expected["output_path"], expected["output_text"]
        found_path, body = found_ids[statement_id]
        try:
            normalized_expected = Path(expected_path).as_posix()
        except TypeError:
            normalized_expected = expected_path
        if normalized_expected != found_path:
            errors.append(f"statement {statement_id} path mismatch: map={normalized_expected!r}, file={found_path!r}")
        extension = declared[found_path].suffix.casefold()
        if extension == ".md":
            if output_text != body.strip():
                errors.append(f"statement {statement_id} output_text is not the complete marked Markdown block")
        elif extension == ".csv":
            if output_text != body:
                errors.append(f"statement {statement_id} output_text does not exactly match its CSV row")
        elif output_text not in body:
            errors.append(f"statement {statement_id} output_text does not match its marked output block")

    visual_units: dict[tuple[str, str], set[str]] = {}
    accessibility_rows: dict[str, list[dict[str, str]]] = {}
    for row in mapped_rows:
        if visual_scope_ids and row["deliverable_id"] not in visual_scope_ids:
            continue
        unit = row["visual_unit_id"]
        if not unit:
            continue
        unit_key = (row["output_path"], unit)
        if row["statement_type"] == "accessibility_copy":
            accessibility_rows.setdefault("::".join(unit_key), []).append(row)
        else:
            visual_units.setdefault(unit_key, set()).add(row["statement_id"])
    for unit_key, statement_ids in visual_units.items():
        unit_path, unit = unit_key
        key = "::".join(unit_key)
        access_rows = accessibility_rows.get(key, [])
        if not access_rows:
            errors.append(f"visual unit {unit} in {unit_path} has no accessibility_copy mapping row")
            continue
        if len(access_rows) != 1:
            errors.append(f"visual unit {unit} in {unit_path} needs exactly one accessibility_copy mapping row")
        for access_row in access_rows:
            related_list = id_list(access_row["related_statement_ids"])
            related = set(related_list)
            if len(related_list) != len(related):
                errors.append(f"accessibility_copy for visual unit {unit} has duplicate related_statement_ids")
            if related != statement_ids:
                errors.append(f"accessibility_copy for visual unit {unit} must reference every visual statement_id exactly")
            access_text = normalized_prose(access_row["output_text"])
            for source_statement_id in statement_ids:
                source_text = normalized_prose(expected_ids[source_statement_id]["output_text"])
                if source_text and source_text not in access_text:
                    errors.append(f"accessibility_copy for visual unit {unit} must preserve statement {source_statement_id} verbatim")
            required_claim_ids = {
                claim.strip()
                for source_row in mapped_rows
                if source_row["statement_id"] in statement_ids
                for claim in source_row["claim_ids"].split(";")
                if claim.strip()
            }
            access_claim_ids = {claim.strip() for claim in access_row["claim_ids"].split(";") if claim.strip()}
            if not required_claim_ids <= access_claim_ids:
                missing_claim_ids = ";".join(sorted(required_claim_ids - access_claim_ids))
                errors.append(f"accessibility_copy for visual unit {unit} must carry all related claim_ids: {missing_claim_ids}")
    for key, access_rows in accessibility_rows.items():
        if key not in {"::".join(key_parts) for key_parts in visual_units}:
            errors.append(f"accessibility_copy mapping {access_rows[0]['statement_id']} has no matching visual copy unit")

    rows_by_statement = {row["statement_id"]: row for row in mapped_rows}
    for relative, target in declared.items():
        if target.suffix.casefold() != ".csv":
            continue
        try:
            with target.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, strict=True)
                if "frame_id" not in (reader.fieldnames or []):
                    continue
                for number, output_row in enumerate(reader, start=2):
                    frame_id = (output_row.get("frame_id") or "").strip()
                    statement_id = (output_row.get("statement_id") or "").strip()
                    content_type = (output_row.get("content_type") or "").strip()
                    mapped = rows_by_statement.get(statement_id)
                    if not mapped or not frame_id:
                        continue
                    if mapped["visual_unit_id"] != frame_id:
                        errors.append(f"{relative}: mapping for {statement_id} must use frame_id {frame_id} as visual_unit_id")
                    if content_type == "accessibility_transcript" and mapped["statement_type"] != "accessibility_copy":
                        errors.append(f"{relative}: accessibility_transcript {statement_id} must be mapped as accessibility_copy")
                    if content_type != "accessibility_transcript" and mapped["statement_type"] == "accessibility_copy":
                        errors.append(f"{relative}: accessibility_copy {statement_id} must use accessibility_transcript content_type")
        except (OSError, UnicodeError, csv.Error) as exc:
            errors.append(f"{relative}: cannot cross-check frame mapping: {exc}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--deliverable", type=Path, action="append", required=True)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--source-inventory", type=Path)
    parser.add_argument("--statement-support", type=Path)
    parser.add_argument("--structural-only", action="store_true")
    args = parser.parse_args()
    if args.structural_only and (args.source_report or args.source_inventory or args.statement_support):
        parser.error("structural-only is mutually exclusive with source-report, source-inventory and statement-support")
    if not args.structural_only and args.source_report is None:
        parser.error("source-report is required for handoff validation")
    errors = validate_package(args.artifacts_root, args.mapping, args.deliverable, args.source_report)
    if args.source_report is not None:
        errors.extend(validate_source_contract(
            args.artifacts_root, args.mapping, args.deliverable, args.source_report,
            args.source_inventory or args.artifacts_root / "source-inventory.json",
            args.statement_support or args.artifacts_root / "statement-support.csv",
        ))
    if errors:
        print(f"Derivative traceability validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    if args.structural_only:
        print("Structural checks passed only; source completeness and semantic support NOT VERIFIED; not a handoff pass.")
    else:
        print("Derivative traceability validation passed: declared output and source-inventory records reconcile; semantic support remains the documented manual review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
