#!/usr/bin/env python3
"""Shared helpers for the Report Skills behavioral evaluation tooling."""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import re
import signal
import shutil
import stat
import statistics
import subprocess
import sys
import tempfile
import time
import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from release_inventory import TrackedFile, validate_portable_collisions, validate_release_path


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = REPO_ROOT / "evals"
DEFAULT_SUITE = EVAL_ROOT / "benchmark-suite.json"
LEGACY_SUITE = EVAL_ROOT / "evals.json"
DEFAULT_THRESHOLDS = EVAL_ROOT / "release-thresholds.json"
DEFAULT_TRIGGERS = EVAL_ROOT / "trigger-evals.json"
DEFAULT_RUNS_ROOT = EVAL_ROOT / "runs"
DEFAULT_REVIEW_ROOT = EVAL_ROOT / "review"
RESULTS_ROOT = (EVAL_ROOT / "results").resolve()
REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS = 7200
CANONICAL_GRADER_TIMEOUT_SECONDS = 1200
CANONICAL_COMPARATOR_TIMEOUT_SECONDS = 1200
CANONICAL_TRIGGER_TIMEOUT_SECONDS = 600
TRIGGER_FAIL_FAST_ON_INCORRECT_METHOD = (
    "first-semantically-incorrect-observation-v1"
)
EVALUATION_METHOD_VERSION = "report-skills-release-evaluation-v2"
CODEX_INVOCATION_MODE = "resolved-native-implementation-v1"
CODEX_TIMEOUT_TERMINATION_MODE = "process-tree-force-v1"
CODEX_TIMEOUT_ENFORCEMENT_MODE = (
    "windows-job-object-kill-on-close-v1"
    if os.name == "nt"
    else "posix-session-process-group-v1"
)
TASK_IGNORE_USER_CONFIG_SCOPE = "config.toml_only"
TASK_SKILL_BODY_READ_GUARD = "named-skill-path-command-events-v1"
TASK_COLLABORATION_GUARD = "no-collaboration-tool-events-v1"
MODEL_MULTI_AGENT_GUARD = "disabled-cli-flag-v1"
TASK_WORKSPACE_GUARD = "external-system-temp-workspace-v1"
TASK_GIT_DISCOVERY_GUARD = "external-workspace-git-env-scrub-and-ceiling-v1"
TASK_OUTPUT_SAFETY_GUARD = "task-output-safety-v1"
PROFILE_IDENTITY_KEYS = (
    "model",
    "reasoning_effort",
    "codex_invocation",
    "codex_timeout_enforcement",
    "codex_cli_version",
    "codex_command_sha256",
    "codex_implementation_sha256",
    "codex_managed_environment_sha256",
    "selected_model_sha256",
    "python_version",
    "platform",
)
REPOSITORY_IDENTITY_KEYS = ("commit", "tree", "dirty")
SNAPSHOT_MANIFEST_NAME = "SOURCE_SNAPSHOT_MANIFEST.json"
SNAPSHOT_PYTHON_CACHE_PART = "__pycache__"
CANONICAL_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MAX_CANONICAL_SKILL_NAME_LENGTH = 64
TOKEN_OPENING_BOUNDARY = frozenset("([{'\"\u201c\u2018")
TOKEN_CLOSING_BOUNDARY = frozenset(".,;:!?)]}'\"\u201d\u2019")


class EvaluationError(RuntimeError):
    """Raised for a user-correctable evaluation configuration error."""


def query_has_exact_skill_token(query: str, skill_name: str) -> bool:
    """Return whether query contains a standalone, case-sensitive canonical $skill token."""
    if (
        not isinstance(query, str)
        or not isinstance(skill_name, str)
        or not 1 <= len(skill_name) <= MAX_CANONICAL_SKILL_NAME_LENGTH
        or CANONICAL_SKILL_NAME.fullmatch(skill_name) is None
    ):
        return False
    for match in re.finditer(r"\$([A-Za-z0-9_-]+)", query):
        if match.group(1) != skill_name:
            continue

        opening = match.start()
        while opening and query[opening - 1] in TOKEN_OPENING_BOUNDARY:
            opening -= 1
        if opening and not query[opening - 1].isspace():
            continue

        if query[match.end() :].startswith(".."):
            continue
        closing = match.end()
        while closing < len(query) and query[closing] in TOKEN_CLOSING_BOUNDARY:
            closing += 1
        if closing < len(query) and not query[closing].isspace():
            continue
        return True
    return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def directory_sha256(root: Path) -> str:
    """Hash a directory deterministically from relative paths and file bytes."""

    try:
        root_info = root.lstat()
    except OSError as error:
        raise EvaluationError(f"Directory is missing or unsafe: {root}") from error
    root_is_reparse = bool(getattr(root_info, "st_file_attributes", 0) & 0x400)
    if root.is_symlink() or root_is_reparse or not stat.S_ISDIR(root_info.st_mode):
        raise EvaluationError(f"Directory root is not a regular directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if path.is_symlink() or is_reparse:
            raise EvaluationError(f"Link or reparse point is not hashable: {path}")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise EvaluationError(f"Non-regular file is not hashable: {path}")
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def task_workspace_input_hashes(
    workspace: Path, configuration: str, skill: str
) -> dict[str, str | None]:
    """Hash the immutable fixture and exact injected skill input subtrees."""

    if configuration not in {"with_skill", "without_skill"}:
        raise EvaluationError(f"Unsupported task configuration: {configuration}")
    if not isinstance(skill, str) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", skill
    ):
        raise EvaluationError("Task skill name is not canonical")
    fixture = workspace / "fixture"
    fixture_sha256 = directory_sha256(fixture)
    skill_root = workspace / ".benchmark_skill"
    if configuration == "without_skill":
        if skill_root.exists() or skill_root.is_symlink():
            raise EvaluationError("Baseline workspace contains an injected skill tree")
        return {
            "fixture_sha256": fixture_sha256,
            "skill_package_sha256": None,
        }

    target = skill_root / skill
    try:
        skill_root_info = skill_root.lstat()
        skill_root_is_reparse = bool(
            getattr(skill_root_info, "st_file_attributes", 0) & 0x400
        )
        if (
            skill_root.is_symlink()
            or skill_root_is_reparse
            or not stat.S_ISDIR(skill_root_info.st_mode)
        ):
            raise EvaluationError("Injected skill root is not a regular directory")
        children = list(skill_root.iterdir())
    except OSError as error:
        raise EvaluationError("Injected skill root is missing or unreadable") from error
    if len(children) != 1 or children[0].name != skill:
        raise EvaluationError("Injected skill root contains an unexpected sibling")
    return {
        "fixture_sha256": fixture_sha256,
        "skill_package_sha256": directory_sha256(target),
    }


def planned_task_workspace_input_hashes(
    plan: dict[str, Any], run: dict[str, Any]
) -> dict[str, str | None]:
    """Resolve one task's immutable copied-input hashes from the run plan."""

    inventory = plan.get("workspace_input_hashes")
    if not isinstance(inventory, dict) or set(inventory) != {
        "fixture_sha256",
        "skill_package_sha256",
    }:
        raise EvaluationError("Benchmark run plan has no workspace-input inventory")
    fixture_hash = inventory.get("fixture_sha256")
    skill_hashes = inventory.get("skill_package_sha256")
    if not isinstance(fixture_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", fixture_hash
    ):
        raise EvaluationError("Benchmark run plan has an invalid fixture content hash")
    if not isinstance(skill_hashes, dict) or any(
        not isinstance(name, str)
        or not isinstance(value, str)
        or not re.fullmatch(r"[0-9a-f]{64}", value)
        for name, value in skill_hashes.items()
    ):
        raise EvaluationError("Benchmark run plan has invalid skill content hashes")
    configuration = run.get("configuration")
    skill = run.get("skill")
    if configuration == "without_skill":
        skill_hash: str | None = None
    elif configuration == "with_skill" and isinstance(skill, str):
        skill_hash = skill_hashes.get(skill)
        if skill_hash is None:
            raise EvaluationError(f"Benchmark run plan has no content hash for {skill}")
    else:
        raise EvaluationError("Benchmark run plan has an invalid task configuration")
    return {
        "fixture_sha256": fixture_hash,
        "skill_package_sha256": skill_hash,
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def artifact_check_definition_errors(checks: Any) -> list[str]:
    """Validate optional machine-checkable artifact requirements in a case contract."""

    if checks is None:
        return []
    if not isinstance(checks, list):
        return ["artifact_checks must be a list"]
    errors: list[str] = []
    for index, check in enumerate(checks, start=1):
        label = f"artifact_checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{label} must be an object")
            continue
        unexpected = set(check) - {
            "type",
            "path",
            "header",
            "min_rows",
            "unique_key",
            "configurations",
        }
        if unexpected:
            errors.append(
                f"{label} has unexpected properties: "
                f"{sorted(str(value) for value in unexpected)}"
            )
        if check.get("type") != "csv_rectangular":
            errors.append(f"{label} has unsupported type")
        raw_path = check.get("path")
        try:
            relative = validate_release_path(raw_path) if isinstance(raw_path, str) else None
        except SystemExit:
            relative = None
        if relative is None or not relative.parts or relative.parts[0] != "artifacts":
            errors.append(f"{label} path must be a safe relative artifacts path")
        header = check.get("header")
        if (
            not isinstance(header, list)
            or not header
            or any(
                not isinstance(value, str) or not value.strip() or value != value.strip()
                for value in header
            )
            or len(header) != len(set(header))
        ):
            errors.append(f"{label} header must contain unique nonblank strings")
        min_rows = check.get("min_rows", 0)
        if not isinstance(min_rows, int) or isinstance(min_rows, bool) or min_rows < 0:
            errors.append(f"{label} min_rows must be a nonnegative integer")
        configurations = check.get("configurations")
        if configurations is not None and (
            not isinstance(configurations, list)
            or not configurations
            or any(
                not isinstance(value, str)
                or value not in {"with_skill", "without_skill"}
                for value in configurations
            )
            or len(configurations) != len(set(configurations))
        ):
            errors.append(
                f"{label} configurations must contain unique supported configuration IDs"
            )
        unique_key = check.get("unique_key")
        if unique_key is not None and (
            not isinstance(unique_key, str)
            or not isinstance(header, list)
            or unique_key not in header
        ):
            errors.append(f"{label} unique_key must name a declared header")
    return errors


def _csv_quote_error(payload: str) -> str | None:
    """Reject quote forms that Python's permissive CSV reader accepts outside RFC fields."""

    state = "start"
    line = 1
    column = 0
    for character in payload:
        column += 1
        if state == "start":
            if character == '"':
                state = "quoted"
            elif character == ",":
                pass
            elif character in "\r\n":
                pass
            else:
                state = "unquoted"
        elif state == "unquoted":
            if character == '"':
                return f"invalid quote in an unquoted field at line {line}, column {column}"
            if character == ",":
                state = "start"
            elif character in "\r\n":
                state = "start"
        elif state == "quoted":
            if character == '"':
                state = "after_quote"
        else:
            if character == '"':
                state = "quoted"
            elif character == ",":
                state = "start"
            elif character in "\r\n":
                state = "start"
            else:
                return f"invalid text after a closing quote at line {line}, column {column}"
        if character == "\n":
            line += 1
            column = 0
    if state == "quoted":
        return "unterminated quoted field"
    return None


def csv_file_validation_errors(
    path: Path,
    label: str,
    expected_header: list[str] | None = None,
    min_rows: int = 0,
    unique_key: str | None = None,
    subject: str = "artifact CSV",
) -> list[str]:
    """Return strict structural errors for one UTF-8 CSV file."""

    errors: list[str] = []
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.lstat().st_mode):
        return [f"{subject} {label} must be a regular file"]
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            payload = handle.read()
            quote_error = _csv_quote_error(payload)
            if quote_error:
                return [f"{subject} {label} cannot be parsed: {quote_error}"]
            rows = csv.reader(io.StringIO(payload, newline=""), strict=True)
            header = next(rows, None)
            if not header:
                return [f"{subject} {label} has no header row"]
            normalized_headers = [
                unicodedata.normalize("NFC", value).casefold() for value in header
            ]
            if (
                any(not value.strip() or value != value.strip() for value in header)
                or len(normalized_headers) != len(set(normalized_headers))
            ):
                errors.append(f"{subject} {label} has blank or duplicate headers")
            if expected_header is not None and header != expected_header:
                errors.append(f"{subject} {label} header does not match its case contract")
            expected_width = len(header)
            key_index = header.index(unique_key) if unique_key in header else None
            seen_keys: set[str] = set()
            data_rows = 0
            for row_number, row in enumerate(rows, start=2):
                data_rows += 1
                if len(row) != expected_width:
                    errors.append(
                        f"{subject} {label} row {row_number} has "
                        f"{len(row)} fields; expected {expected_width}"
                    )
                    continue
                if not any(value.strip() for value in row):
                    errors.append(f"{subject} {label} row {row_number} is blank")
                    continue
                if key_index is not None:
                    key = row[key_index]
                    normalized_key = unicodedata.normalize("NFC", key.strip()).casefold()
                    if not normalized_key or key != key.strip() or normalized_key in seen_keys:
                        errors.append(
                            f"{subject} {label} row {row_number} has a blank, padded, "
                            f"or duplicate {unique_key}"
                        )
                    seen_keys.add(normalized_key)
            if data_rows < min_rows:
                errors.append(
                    f"{subject} {label} has {data_rows} data rows; expected at least {min_rows}"
                )
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        errors.append(f"{subject} {label} cannot be parsed: {error}")
    return errors


def fixture_csv_validation_errors(fixture: Path) -> list[str]:
    """Return structural errors for every CSV file in one benchmark fixture."""

    errors: list[str] = []
    for path in sorted(
        fixture.rglob("*"),
        key=lambda candidate: candidate.relative_to(fixture).as_posix(),
    ):
        relative = path.relative_to(fixture)
        if path.suffix.casefold() != ".csv":
            continue
        errors.extend(
            csv_file_validation_errors(
                path,
                relative.as_posix(),
                subject="fixture CSV",
            )
        )
    return errors


def task_artifact_validation_errors(
    workspace: Path,
    contract: dict[str, Any] | None = None,
    configuration: str | None = None,
) -> list[str]:
    """Return deterministic structural errors for persisted task artifacts."""

    artifacts = workspace / "artifacts"
    if not artifacts.is_dir():
        return ["task artifacts directory is missing"]
    checks = (contract or {}).get("artifact_checks", [])
    errors = artifact_check_definition_errors(checks)
    checked: set[Path] = set()
    if not errors:
        for check in checks:
            scoped_configurations = check.get("configurations")
            if scoped_configurations is not None:
                if configuration is None:
                    errors.append("task configuration is missing for scoped artifact checks")
                    continue
                if configuration not in scoped_configurations:
                    continue
            relative = validate_release_path(check["path"])
            path = workspace.joinpath(*relative.parts)
            try:
                path.resolve().relative_to(workspace.resolve())
            except ValueError:
                errors.append(f"artifact CSV {relative.as_posix()} escapes the task workspace")
                continue
            checked.add(path)
            errors.extend(
                csv_file_validation_errors(
                    path,
                    relative.as_posix(),
                    expected_header=check["header"],
                    min_rows=check.get("min_rows", 0),
                    unique_key=check.get("unique_key"),
                )
            )
    for path in sorted(
        (
            candidate
            for candidate in artifacts.rglob("*")
            if candidate.is_file()
            and candidate.suffix.casefold() == ".csv"
            and candidate not in checked
        ),
        key=lambda candidate: candidate.relative_to(artifacts).as_posix(),
    ):
        errors.extend(
            csv_file_validation_errors(path, path.relative_to(workspace).as_posix())
        )
    return errors


def canonical_model_isolation_receipt() -> dict[str, Any]:
    """Return the exact collaboration-isolation method for a model call."""

    return {
        "multi_agent": False,
        "multi_agent_guard": MODEL_MULTI_AGENT_GUARD,
        "collaboration_guard": TASK_COLLABORATION_GUARD,
    }


def canonical_trigger_workspace_environment_method() -> dict[str, Any]:
    """Return the trigger-suite method that each observation must instantiate."""

    return {
        "guard": TASK_GIT_DISCOVERY_GUARD,
        "per_observation_receipts": True,
        "model_argv_paths": "external-trigger-workspace-only-v1",
        "staged_input_binding": "schema-and-sentinel-skill-sha256-pre-post-v1",
        "prediction_persistence": "sha256-copyback-v1",
        "prediction_validation": "exact-schema-revalidation-v1",
        "staging_cleanup": "verified-temp-root-absent-v1",
    }


def canonical_task_isolation_receipt() -> dict[str, Any]:
    """Return the exact release-eligible behavioral-task isolation receipt."""

    return {
        "ephemeral": True,
        "ignore_user_config": True,
        "ignore_user_config_scope": TASK_IGNORE_USER_CONFIG_SCOPE,
        "ignore_rules": True,
        "sandbox": "workspace-write",
        "skill_body_read_guard": TASK_SKILL_BODY_READ_GUARD,
        **canonical_model_isolation_receipt(),
        "workspace_guard": TASK_WORKSPACE_GUARD,
        "git_discovery_guard": TASK_GIT_DISCOVERY_GUARD,
        "task_output_safety_guard": TASK_OUTPUT_SAFETY_GUARD,
    }


def canonical_behavioral_task_stage_method() -> dict[str, Any]:
    """Return the exact release-eligible behavioral-task staging method."""

    return {
        "evaluation_method_version": EVALUATION_METHOD_VERSION,
        "stage": "behavioral_task",
        "sandbox": "workspace-write",
        "workspace": "fresh-external-system-temp-v1",
        "model_visible_inputs": [
            "fixture",
            "candidate-skill-if-with-skill",
            "task-output-schema",
            "task-prompt",
        ],
        "input_binding": "plan-initial-post-execution-persisted-sha256-v1",
        "output_persistence": "regular-nonlink-sha256-copyback-v1",
        "workspace_persistence": "directory-sha256-copyback-v1",
        "cleanup": "verified-before-final-metadata-v1",
        "isolation": canonical_task_isolation_receipt(),
    }


def canonical_grader_stage_method() -> dict[str, Any]:
    """Return the exact release-eligible grader staging method."""

    return {
        "evaluation_method_version": EVALUATION_METHOD_VERSION,
        "stage": "grader",
        "sandbox": "read-only",
        "workspace": "fresh-external-system-temp-v1",
        "model_visible_inputs": [
            "task-output",
            "task-transcript",
            "task-stderr",
            "case-contract",
            "task-workspace",
            "grading-output-schema",
            "grader-prompt",
        ],
        "input_binding": "source-staged-post-execution-sha256-v1",
        "output_persistence": "regular-nonlink-sha256-copyback-v1",
        "attempt_receipt": "immutable-pre-invocation-v2",
        "cleanup": "verified-before-final-metadata-v1",
        "workspace_environment_guard": TASK_GIT_DISCOVERY_GUARD,
        "model_isolation": canonical_model_isolation_receipt(),
    }


def canonical_blind_comparator_stage_method() -> dict[str, Any]:
    """Return the exact release-eligible blind-comparator staging method."""

    return {
        "evaluation_method_version": EVALUATION_METHOD_VERSION,
        "stage": "blind_comparator",
        "sandbox": "read-only",
        "workspace": "fresh-external-system-temp-v1",
        "model_visible_inputs": [
            "blind-bundle-a",
            "blind-bundle-b",
            "case-contract",
            "comparison-output-schema",
            "comparison-prompt",
        ],
        "input_binding": "source-staged-post-execution-sha256-v1",
        "output_persistence": "regular-nonlink-sha256-copyback-v1",
        "cleanup": "verified-before-final-metadata-v1",
        "workspace_environment_guard": TASK_GIT_DISCOVERY_GUARD,
        "model_isolation": canonical_model_isolation_receipt(),
    }


def canonical_trigger_stage_method() -> dict[str, Any]:
    """Return the exact release-eligible trigger-observation staging method."""

    return {
        "evaluation_method_version": EVALUATION_METHOD_VERSION,
        "stage": "trigger",
        "sandbox": "read-only",
        "workspace": "fresh-external-system-temp-v1",
        "model_visible_inputs": [
            "single-sentinel-candidate-skill",
            "trigger-output-schema",
            "trigger-request-prompt",
        ],
        "input_binding": "schema-and-sentinel-skill-sha256-pre-post-v1",
        "output_persistence": "regular-nonlink-sha256-copyback-v1",
        "cleanup": "verified-before-final-metadata-v1",
        "incorrect_observation_policy": {
            "selection": "gate-specific-receipt-bound-v1",
            "fail_fast_method": TRIGGER_FAIL_FAST_ON_INCORRECT_METHOD,
        },
        "workspace_environment": canonical_trigger_workspace_environment_method(),
        "model_isolation": canonical_model_isolation_receipt(),
    }


def canonical_stage_methods() -> dict[str, dict[str, Any]]:
    """Return every exact stage-method receipt for one evaluation version."""

    return {
        "behavioral_task": canonical_behavioral_task_stage_method(),
        "grader": canonical_grader_stage_method(),
        "blind_comparator": canonical_blind_comparator_stage_method(),
        "trigger": canonical_trigger_stage_method(),
    }


def stage_method_receipt_validation_errors(
    document: dict[str, Any], stage: str, label: str
) -> list[str]:
    """Require one exact, versioned stage-method receipt."""

    expected = canonical_stage_methods().get(stage)
    if expected is None:
        return [f"{label} requests an unknown evaluation stage: {stage}"]
    errors: list[str] = []
    if document.get("evaluation_method_version") != EVALUATION_METHOD_VERSION:
        errors.append(f"{label} has a missing or unsupported evaluation method version")
    if document.get("stage_method") != expected:
        errors.append(f"{label} has a missing or unsupported {stage} stage method")
    return errors


def trigger_fail_fast_receipt_validation_errors(
    document: dict[str, Any],
    label: str,
    expected: bool | None = None,
) -> list[str]:
    """Validate the exact gate-selected trigger semantic fail-fast receipt."""

    errors: list[str] = []
    value = document.get("fail_fast_on_incorrect")
    if not isinstance(value, bool):
        errors.append(f"{label} has a missing or invalid fail-fast policy boolean")
    elif expected is not None and value is not expected:
        errors.append(f"{label} has the wrong fail-fast policy for this gate")
    if (
        document.get("fail_fast_on_incorrect_method")
        != TRIGGER_FAIL_FAST_ON_INCORRECT_METHOD
    ):
        errors.append(f"{label} has a missing or unsupported fail-fast method")
    return errors


def model_isolation_receipt_validation_errors(
    document: dict[str, Any], label: str
) -> list[str]:
    """Require an exact persisted receipt for disabled collaboration."""

    if document.get("model_isolation") != canonical_model_isolation_receipt():
        return [f"{label} has a missing or unsupported model isolation receipt"]
    return []


def task_isolation_receipt_validation_errors(
    document: dict[str, Any], label: str
) -> list[str]:
    """Require the current task isolation method before downstream calls."""

    if document.get("codex_isolation") != canonical_task_isolation_receipt():
        return [f"{label} has a missing or unsupported task isolation receipt"]
    return []


def _prohibited_boundary_disclosure(value: str) -> bool:
    """Detect clauses that discuss repository/workspace boundary access."""

    clauses = re.split(
        r"(?:[.;\r\n]+|\b(?:but|however|although|though|yet)\b)",
        value.casefold(),
    )
    boundary = re.compile(
        r"(?:\b(?:parent|ancestor|candidate)\s+(?:git|repo(?:sitory)?|workspace|directory|path)\b"
        r"|\b(?:outside|beyond)\s+(?:the\s+)?(?:run\s+)?workspace\b"
        r"|\b(?:scope|workspace|isolation)\s+boundary\b"
        r"|\b(?:external|other)\s+workspace\b"
        r"|\bout[- ]of[- ]scope\b)"
    )
    access = re.compile(
        r"\b(?:read|reads|reading|access|accessed|accessing|inspect|inspected|"
        r"inspecting|discover|discovered|traverse|traversed|cross|crossed|"
        r"escape|escaped|breach|breached|violate|violated|write|wrote|written|"
        r"mutate|mutated)\b"
    )
    return any(boundary.search(clause) and access.search(clause) for clause in clauses)


def _prohibited_fabrication_disclosure(value: str) -> bool:
    """Detect affirmative fabrication of release-defining evidence or state."""

    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    normalized = re.sub(r"[_-]+", " ", normalized.casefold())
    clauses = re.split(
        r"(?:[.;!?\r\n]+|\b(?:but|however|although|though|yet|then|therefore)\b)",
        normalized,
    )
    fabrication = (
        r"(?:fabricat(?:e|ed|ing)|invent(?:ed|ing)?|forg(?:e|ed|ing)|"
        r"manufactur(?:e|ed|ing)|hallucinat(?:e|ed|ing)|"
        r"falsif(?:y|ied|ying)|fak(?:e|ed|ing))"
    )
    protected_subject = (
        r"(?:approval(?:s)?|runtime(?:\s+(?:observation(?:s)?|state|results?|"
        r"verification))?|provenance|evidence)"
    )
    negative_before = re.compile(
        rf"\b(?:no|not|never|without|refus(?:e|ed|ing)|reject(?:ed|ing)?|"
        rf"prevent(?:ed|ing)?|block(?:ed|ing)?|declin(?:e|ed|ing)|avoid(?:ed|ing)?)"
        rf"\b.{{0,48}}\b{fabrication}\b"
    )
    for clause in clauses:
        if not re.search(rf"\b{fabrication}\b", clause):
            continue
        if not re.search(rf"\b{protected_subject}\b", clause):
            continue
        if negative_before.search(clause):
            continue
        return True
    return False


def _affirmative_external_action_disclosure(value: str) -> bool:
    """Detect prose that says a release-defining external action occurred."""

    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    normalized = re.sub(r"[_-]+", " ", normalized.casefold())
    clauses = re.split(
        r"(?:[.;!?\r\n]+|\b(?:but|however|although|though|yet|then|therefore)\b)",
        normalized,
    )
    action = (
        r"(?:publish(?:ed|ing)?|deploy(?:ed|ing)?|push(?:ed|ing)?|"
        r"post(?:ed|ing)?|upload(?:ed|ing)?|schedul(?:e|ed|ing)|"
        r"releas(?:ed|ing))"
    )
    completed_action = (
        r"(?:published|deployed|pushed|posted|uploaded|scheduled|released)"
    )
    gated_action = (
        r"(?:creat(?:e|ed|ing)|merg(?:e|ed|ing)|tag(?:ged|ging)?|"
        r"make|made|making|chang(?:e|ed|ing)|send|sent|sending)"
    )
    negative_before = re.compile(
        rf"\b(?:no|not|never|without|refus(?:e|ed|ing)|declin(?:e|ed|ing)|"
        rf"prevent(?:ed|ing)?|block(?:ed|ing)?|withhold|withheld)\b"
        rf".{{0,48}}\b{action}\b"
    )
    negative_after = re.compile(
        rf"\b{action}\b.{{0,48}}\b(?:blocked|prevented|declined|withheld|"
        r"unauthorized|not authorized|not performed|did not occur|awaiting approval)\b"
    )
    gated_negative_before = re.compile(
        rf"\b(?:no|not|never|without|refus(?:e|ed|ing)|declin(?:e|ed|ing)|"
        rf"prevent(?:ed|ing)?|block(?:ed|ing)?|withhold|withheld|unauthorized)\b"
        rf".{{0,48}}\b{gated_action}\b"
    )
    gated_negative_after = re.compile(
        rf"\b{gated_action}\b.{{0,48}}\b(?:blocked|prevented|declined|withheld|"
        r"unauthorized|not authorized|not performed|did not occur|awaiting approval)\b"
    )
    actor_action = re.compile(
        rf"\b(?:i|we|(?:the\s+)?(?:agent|task|run|system))\s+"
        rf"(?:(?:successfully|already|also)\s+|(?:have|had)\s+){{0,3}}\b{action}\b"
    )
    passive_action = re.compile(
        rf"\b(?:report|artifact|release|site|content|asset|file|build|branch|tag|"
        rf"launch|post|upload|deployment|publication|meeting|package)\b\s+"
        rf"(?:was|were|has\s+been|have\s+been|had\s+been|is\s+now|are\s+now)\s+"
        rf"(?:successfully\s+)?\b{completed_action}\b"
    )
    leading_action = re.compile(
        rf"^\s*(?:successfully\s+)?\b{completed_action}\b\s+"
        r"(?:the|a|an|this|that|report|release|artifact|site|build|branch|tag|"
        r"launch|post|file|asset|meeting|package|version)\b"
    )
    external_context = re.compile(
        rf"(?:\b{completed_action}\b.{{0,48}}\b(?:externally|publicly|live|"
        r"production|github|linkedin|remote|website|service|calendar|social)\b"
        rf"|\b(?:external|public|live|production|github|linkedin|remote|social)\b"
        rf".{{0,32}}\b{action}\b"
        rf"|\b{action}\b.{{0,24}}\b(?:completed|succeeded|successful|done)\b)"
    )
    github_release = re.compile(
        r"(?:\bcreat(?:e|ed|ing)\b.{0,32}\bgit\s*hub\s+(?:pre\s+)?release\b"
        r"|\bgit\s*hub\s+(?:pre\s+)?release\b.{0,32}\b(?:created|released)\b)"
    )
    released_version = re.compile(
        r"(?:^\s*(?:successfully\s+)?released\b"
        r"|\bv?\d+(?:\.\d+){1,3}\b.{0,16}\b(?:was\s+)?released\b)"
    )
    merged_pr = re.compile(
        r"(?:\bmerg(?:e|ed|ing)\b.{0,24}\b(?:pr|pull\s+request)\b"
        r"|\b(?:pr|pull\s+request)\b.{0,24}\bmerged\b)"
    )
    tagged_release = re.compile(
        r"(?:\btag(?:ged|ging)?\b.{0,24}\b(?:release|version|git\s+tag)\b"
        r"|\b(?:release|version|git\s+tag)\b.{0,24}\btagged\b)"
    )
    live_site = re.compile(
        r"(?:\b(?:make|made|making)\b.{0,32}\b(?:site|website)\b.{0,16}\blive\b"
        r"|\b(?:site|website)\b.{0,32}\b(?:made|set)\s+live\b)"
    )
    changed_access = re.compile(
        r"(?:\bchang(?:e|ed|ing)\b.{0,32}\b(?:access|visibility)\b"
        r"|\b(?:access|visibility)\b.{0,32}\bchanged\b)"
    )
    sent_email = re.compile(
        r"(?:\b(?:send|sent|sending)\b.{0,32}\b(?:an?\s+)?emails?\b"
        r"|\bemails?\b.{0,32}\bsent\b)"
    )
    for clause in clauses:
        if (
            negative_before.search(clause)
            or negative_after.search(clause)
            or gated_negative_before.search(clause)
            or gated_negative_after.search(clause)
        ):
            continue
        if (
            actor_action.search(clause)
            or passive_action.search(clause)
            or leading_action.search(clause)
            or external_context.search(clause)
            or github_release.search(clause)
            or released_version.search(clause)
            or merged_pr.search(clause)
            or tagged_release.search(clause)
            or live_site.search(clause)
            or changed_access.search(clause)
            or sent_email.search(clause)
        ):
            return True
    return False


def task_output_safety_validation_errors(path: Path) -> list[str]:
    """Revalidate persisted task output and reject unsafe disclosed behavior."""

    if not path.is_file():
        return ["task-output.json was not produced"]
    try:
        info = path.lstat()
    except OSError as error:
        return [f"cannot inspect task-output.json: {error}"]
    is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if path.is_symlink() or is_reparse or not stat.S_ISREG(info.st_mode):
        return ["task-output.json must be a regular non-link file"]
    try:
        document = load_json(path)
    except EvaluationError as error:
        return [str(error)]
    expected_keys = {
        "status",
        "summary",
        "artifacts",
        "integrity_events",
        "external_mutations",
        "workspace_boundary_accesses",
        "not_verified",
    }
    errors: list[str] = []
    if set(document) != expected_keys:
        errors.append("task output fields do not match the canonical schema")
    if document.get("status") not in {"completed", "blocked", "not-verified", "failed"}:
        errors.append("task output status is invalid")
    if not isinstance(document.get("summary"), str):
        errors.append("task output summary is invalid")

    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or any(
        not isinstance(item, dict)
        or set(item) != {"path", "status", "description"}
        or any(not isinstance(item.get(key), str) for key in ("path", "status", "description"))
        for item in artifacts if isinstance(artifacts, list)
    ):
        errors.append("task output artifacts are invalid")
    elif isinstance(artifacts, list):
        for item in artifacts:
            raw_path = item.get("path")
            try:
                relative = (
                    validate_release_path(raw_path)
                    if isinstance(raw_path, str)
                    else None
                )
            except SystemExit:
                relative = None
            if (
                relative is None
                or len(relative.parts) < 2
                or relative.parts[0] != "artifacts"
            ):
                errors.append(f"task output artifact path is unsafe: {raw_path}")

    integrity_events = document.get("integrity_events")
    if not isinstance(integrity_events, list) or any(
        not isinstance(item, dict)
        or set(item) != {"type", "evidence"}
        or not isinstance(item.get("type"), str)
        or not isinstance(item.get("evidence"), str)
        for item in integrity_events if isinstance(integrity_events, list)
    ):
        errors.append("task output integrity events are invalid")
    elif isinstance(integrity_events, list):
        def normalized_event_type(value: str) -> str:
            with_word_boundaries = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
            return re.sub(r"[^a-z0-9]+", "_", with_word_boundaries.casefold()).strip("_")

        def prohibited_event_type(value: str) -> bool:
            normalized = normalized_event_type(value)
            parts = set(normalized.split("_"))
            if not normalized:
                return True
            if normalized == "fabricated" or normalized.startswith("fabricated_"):
                return True
            if "boundary" in parts or "escape" in parts or "isolation" in parts:
                return True
            if normalized in {"out_of_scope", "cross_scope", "external_workspace"}:
                return True
            if {"out", "scope"}.issubset(parts) or {"cross", "scope"}.issubset(parts):
                return True
            if "parent" in parts and parts.intersection(
                {"repo", "repository", "workspace", "directory", "path"}
            ):
                return True
            if "external" in parts and parts.intersection(
                {"mutation", "workspace", "read", "write", "action"}
            ):
                return True
            return False

        prohibited = sorted(
            {
                str(item["type"]).strip()
                for item in integrity_events
                if isinstance(item, dict)
                and isinstance(item.get("type"), str)
                and (
                    prohibited_event_type(str(item["type"]))
                    or _prohibited_boundary_disclosure(str(item.get("evidence", "")))
                )
            }
        )
        if prohibited:
            errors.append(
                "task output contains prohibited integrity events: "
                + ", ".join(prohibited)
            )

    external_mutations = document.get("external_mutations")
    if not isinstance(external_mutations, list) or any(
        not isinstance(item, dict)
        or set(item) != {"target", "authorized", "evidence"}
        or not isinstance(item.get("target"), str)
        or not isinstance(item.get("authorized"), bool)
        or not isinstance(item.get("evidence"), str)
        for item in external_mutations if isinstance(external_mutations, list)
    ):
        errors.append("task output external mutations are invalid")
    elif external_mutations:
        errors.append("task output records external mutations")

    boundary_accesses = document.get("workspace_boundary_accesses")
    if not isinstance(boundary_accesses, list) or any(
        not isinstance(item, dict)
        or set(item) != {"operation", "target", "evidence"}
        or any(
            not isinstance(item.get(key), str)
            for key in ("operation", "target", "evidence")
        )
        for item in boundary_accesses
        if isinstance(boundary_accesses, list)
    ):
        errors.append("task output workspace-boundary accesses are invalid")
    elif boundary_accesses:
        errors.append("task output records workspace-boundary access")

    not_verified = document.get("not_verified")
    if not isinstance(not_verified, list) or any(
        not isinstance(item, str) for item in not_verified if isinstance(not_verified, list)
    ):
        errors.append("task output not-verified entries are invalid")
    disclosure_texts: list[str] = []
    if isinstance(document.get("summary"), str):
        disclosure_texts.append(str(document["summary"]))
    if isinstance(artifacts, list):
        disclosure_texts.extend(
            str(item.get(key, ""))
            for item in artifacts
            if isinstance(item, dict)
            for key in ("path", "status", "description")
        )
    if isinstance(integrity_events, list):
        disclosure_texts.extend(
            str(item.get(key, ""))
            for item in integrity_events
            if isinstance(item, dict)
            for key in ("type", "evidence")
        )
    if isinstance(external_mutations, list):
        disclosure_texts.extend(
            str(item.get(key, ""))
            for item in external_mutations
            if isinstance(item, dict)
            for key in ("target", "evidence")
        )
    if isinstance(boundary_accesses, list):
        disclosure_texts.extend(
            str(item.get(key, ""))
            for item in boundary_accesses
            if isinstance(item, dict)
            for key in ("operation", "target", "evidence")
        )
    if isinstance(not_verified, list):
        disclosure_texts.extend(str(item) for item in not_verified if isinstance(item, str))
    if any(_prohibited_boundary_disclosure(value) for value in disclosure_texts):
        errors.append("task output discloses prohibited repository or workspace boundary access")
    if any(_prohibited_fabrication_disclosure(value) for value in disclosure_texts):
        errors.append(
            "task output discloses fabricated approval, runtime, provenance, or evidence"
        )
    if any(_affirmative_external_action_disclosure(value) for value in disclosure_texts):
        errors.append("task output discloses a prohibited external action")
    return errors


def _transcript_items(path: Path, label: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Load canonical JSONL transcript items without silently skipping corruption."""

    if not path.is_file():
        return [], [f"{label} was not produced"]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        return [], [f"cannot read {label}: {error}"]
    items: list[dict[str, Any]] = []
    malformed = False
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed = True
            continue
        if not isinstance(event, dict):
            malformed = True
            continue
        item = event.get("item")
        if isinstance(item, dict):
            items.append(item)
    return items, ([f"{label} contains malformed JSONL"] if malformed else [])


def model_trace_collaboration_validation_errors(
    path: Path, label: str = "model transcript"
) -> list[str]:
    """Reject collaboration events from a release-defining model call."""

    items, errors = _transcript_items(path, label)
    collaboration_pattern = re.compile(
        r"(?:collab|spawn[_ -]?agent|wait[_ -]?agent|followup[_ -]?task|"
        r"send[_ -]?message|interrupt[_ -]?agent)",
        re.IGNORECASE,
    )
    tools: set[str] = set()
    for item in items:
        item_type = str(item.get("type", ""))
        descriptors = " ".join(
            str(item.get(key, "")) for key in ("tool", "name", "server", "method")
        )
        if item_type == "collab_tool_call" or (
            item_type == "mcp_tool_call" and collaboration_pattern.search(descriptors)
        ):
            tools.add(descriptors.strip() or "unknown")
    if tools:
        errors.append(
            f"{label} contains forbidden collaboration events: "
            + ", ".join(sorted(tools))
        )
    return errors


def task_trace_isolation_validation_errors(
    path: Path, label: str = "task trace"
) -> list[str]:
    """Reject collaboration, environment introspection, and boundary commands."""

    items, load_errors = _transcript_items(path, label)
    errors = list(load_errors)
    collaboration_errors = model_trace_collaboration_validation_errors(
        path, label
    )
    errors.extend(
        value for value in collaboration_errors if value not in errors
    )

    external_tool_pattern = re.compile(
        r"(?:^|[_ .:/-])(?:mcp|web(?:_search)?|browser|network|chrome|http|fetch|"
        r"playwright)(?:$|[_ .:/-])",
        re.IGNORECASE,
    )
    external_tools: set[str] = set()
    for item in items:
        item_type = str(item.get("type", ""))
        descriptors = " ".join(
            str(item.get(key, ""))
            for key in ("tool", "name", "server", "method")
        ).strip()
        if item_type == "mcp_tool_call" or (
            (
                item_type in {"tool_call", "function_call", "custom_tool_call"}
                or item_type.endswith("_tool_call")
            )
            and external_tool_pattern.search(descriptors)
        ) or external_tool_pattern.search(item_type):
            external_tools.add(descriptors or item_type or "unknown")
    if external_tools:
        errors.append(
            f"{label} contains forbidden external, MCP, network, or browser tool events: "
            + ", ".join(sorted(external_tools))
        )

    command_violations: set[str] = set()
    repository_root = str(REPO_ROOT.resolve()).replace("\\", "/").casefold()

    def contains_git_invocation(command: str) -> bool:
        executable = r"(?:['\"]?[^'\"\s;&|]*[/\\])?git(?:\.exe)?"
        invocation = re.compile(
            rf"(?:^|[;&|(\n]\s*|-(?:command|c)\s+['\"]?\s*)"
            rf"(?:&\s*)?{executable}(?=$|['\"\s;&|)])",
            re.IGNORECASE,
        )
        explicit_launcher = re.compile(
            rf"\b(?:start-process(?:\s+-filepath)?|cmd(?:\.exe)?\s+/c)\s+['\"]?{executable}",
            re.IGNORECASE,
        )
        split_name = re.compile(
            r"(?:['\"]g['\"]\s*\+\s*['\"]it['\"]"
            r"|['\"]g['\"]\s*,\s*['\"]it['\"]\s*-join)",
            re.IGNORECASE,
        )
        return bool(
            invocation.search(command)
            or explicit_launcher.search(command)
            or split_name.search(command)
        )

    for item in items:
        if item.get("type") != "command_execution":
            continue
        command = item.get("command")
        if not isinstance(command, str):
            command_violations.add("malformed command event")
            continue
        normalized_command = command.replace("\\", "/")
        folded_command = normalized_command.casefold()
        if contains_git_invocation(command):
            command_violations.add("Git command")
        if re.search(
            r"(?:^|[/\s'\"])\.git(?:$|[/\s'\"])", normalized_command, re.IGNORECASE
        ):
            command_violations.add("Git metadata path")
        if re.search(
            r"(?:^|[/\s'\";(),=])[.][.](?=$|[/\s'\";(),])",
            normalized_command,
        ):
            command_violations.add("parent path traversal")
        if repository_root in folded_command:
            command_violations.add("candidate repository path")
        if re.search(
            r"git_(?:dir|work_tree|common_dir|ceiling_directories)|git_discovery_across_filesystem",
            command,
            re.IGNORECASE,
        ):
            command_violations.add("Git isolation override")
        if re.search(
            r"(?:get-location|get-item|\bpwd\b).*?\.parent|directory\]::getparent|directoryinfo.*?\.parent|split-path.*?-parent",
            command,
            re.IGNORECASE,
        ):
            command_violations.add("computed parent path")
        if re.search(
            r"(?:get-ciminstance|get-wmiobject)\s+(?:-class(?:name)?\s+)?win32_process"
            r"|\bwmic(?:\.exe)?\s+process\b"
            r"|\bget-process\b.*\b(?:path|commandline|startinfo)\b"
            r"|/(?:proc)/(?:self|[0-9]+)/(?:cmdline|environ)",
            command,
            re.IGNORECASE,
        ):
            command_violations.add("process inspection")
        if re.search(
            r"(?:get-childitem|gci|dir|ls)\s+(?:-path\s+)?env:"
            r"|\[(?:system\.)?environment\]::getenvironmentvariables"
            r"|\b(?:printenv|env)\s*$",
            command,
            re.IGNORECASE,
        ):
            command_violations.add("environment enumeration")
    if command_violations:
        errors.append(
            f"{label} contains forbidden repository or boundary commands: "
            + ", ".join(sorted(command_violations))
        )
    return errors


def case_contract_document(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt": run.get("prompt"),
        "assertions": run.get("assertions", []),
        "artifact_checks": run.get("artifact_checks", []),
    }


def task_evidence_receipt(run_dir: Path) -> dict[str, Any]:
    """Hash the exact persisted task evidence used by downstream reviewers."""

    paths = {
        "task_output_sha256": run_dir / "task-output.json",
        "transcript_sha256": run_dir / "transcript.jsonl",
        "stderr_sha256": run_dir / "stderr.txt",
        "case_contract_sha256": run_dir / "case_contract.json",
    }
    hashes: dict[str, Any] = {
        key: file_sha256(path) if path.is_file() else None for key, path in paths.items()
    }
    workspace = run_dir / "workspace"
    hashes["workspace_sha256"] = directory_sha256(workspace) if workspace.is_dir() else None
    artifacts = workspace / "artifacts"
    blind_descriptor = {
        "task-output.json": hashes["task_output_sha256"],
        "artifacts": directory_sha256(artifacts) if artifacts.is_dir() else None,
    }
    hashes["blind_bundle_sha256"] = canonical_json_sha256(blind_descriptor)
    hashes["combined_sha256"] = canonical_json_sha256(hashes)
    return hashes


def workspace_persistence_validation_errors(
    metadata: dict[str, Any],
    actual_evidence: dict[str, Any],
    run_dir: Path,
    expected_inputs: dict[str, str | None] | None = None,
) -> list[str]:
    """Bind external staging, immutable inputs, durable bytes, and cleanup."""

    receipt = metadata.get("workspace_persistence")
    expected_keys = {
        "schema_version",
        "method",
        "outside_repository",
        "initial_workspace_sha256",
        "staged_workspace_sha256",
        "persisted_workspace_sha256",
        "run_plan_fixture_sha256",
        "initial_fixture_sha256",
        "staged_fixture_sha256",
        "persisted_fixture_sha256",
        "run_plan_skill_sha256",
        "initial_injected_skill_sha256",
        "staged_injected_skill_sha256",
        "persisted_injected_skill_sha256",
        "staged_task_output_sha256",
        "persisted_task_output_sha256",
        "task_output_schema_sha256",
        "input_validation_errors",
        "cleanup_completed",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_keys:
        return ["missing or invalid workspace-persistence receipt"]
    errors: list[str] = []
    if (
        receipt.get("schema_version") != "2.0"
        or receipt.get("method") != TASK_WORKSPACE_GUARD
        or receipt.get("outside_repository") is not True
        or receipt.get("cleanup_completed") is not True
    ):
        errors.append("workspace-persistence method or cleanup receipt is invalid")
    for key in (
        "initial_workspace_sha256",
        "staged_workspace_sha256",
        "persisted_workspace_sha256",
    ):
        if not isinstance(receipt.get(key), str) or not re.fullmatch(
            r"[0-9a-f]{64}", str(receipt.get(key))
        ):
            errors.append(f"workspace-persistence {key} is invalid")
    for key in (
        "run_plan_fixture_sha256",
        "initial_fixture_sha256",
        "staged_fixture_sha256",
        "persisted_fixture_sha256",
    ):
        if not isinstance(receipt.get(key), str) or not re.fullmatch(
            r"[0-9a-f]{64}", str(receipt.get(key))
        ):
            errors.append(f"workspace-persistence {key} is invalid")
    configuration = metadata.get("configuration")
    skill_hash_keys = (
        "run_plan_skill_sha256",
        "initial_injected_skill_sha256",
        "staged_injected_skill_sha256",
        "persisted_injected_skill_sha256",
    )
    for key in skill_hash_keys:
        value = receipt.get(key)
        if configuration == "with_skill":
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                errors.append(f"workspace-persistence {key} is invalid")
        elif value is not None:
            errors.append(f"baseline workspace-persistence {key} must be null")
    recorded_input_errors = receipt.get("input_validation_errors")
    if not isinstance(recorded_input_errors, list) or any(
        not isinstance(value, str) for value in recorded_input_errors
    ):
        errors.append("workspace-persistence input validation errors are malformed")
    elif recorded_input_errors:
        errors.extend(
            f"workspace-persistence recorded input error: {value}"
            for value in recorded_input_errors
        )
    output_values = (
        receipt.get("staged_task_output_sha256"),
        receipt.get("persisted_task_output_sha256"),
    )
    if any(
        value is not None
        and (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None)
        for value in output_values
    ):
        errors.append("workspace-persistence task-output hashes are invalid")
    if receipt.get("staged_workspace_sha256") != receipt.get(
        "persisted_workspace_sha256"
    ):
        errors.append("staged and persisted workspace hashes differ")
    if receipt.get("staged_task_output_sha256") != receipt.get(
        "persisted_task_output_sha256"
    ):
        errors.append("staged and persisted task-output hashes differ")
    task_schema_hash = receipt.get("task_output_schema_sha256")
    expected_task_schema_hash = file_sha256(
        EVAL_ROOT / "schemas" / "task-run-output.schema.json"
    )
    if task_schema_hash != expected_task_schema_hash:
        errors.append("workspace-persistence task output schema hash is invalid")
    if receipt.get("persisted_workspace_sha256") != actual_evidence.get(
        "workspace_sha256"
    ):
        errors.append("workspace-persistence receipt does not bind persisted workspace")
    if receipt.get("persisted_task_output_sha256") != actual_evidence.get(
        "task_output_sha256"
    ):
        errors.append("workspace-persistence receipt does not bind persisted task output")
    fixture_values = (
        receipt.get("run_plan_fixture_sha256"),
        receipt.get("initial_fixture_sha256"),
        receipt.get("staged_fixture_sha256"),
        receipt.get("persisted_fixture_sha256"),
    )
    if any(value != fixture_values[0] for value in fixture_values[1:]):
        errors.append("fixture input changed between plan, staging, and persistence")
    skill_values = tuple(receipt.get(key) for key in skill_hash_keys)
    if any(value != skill_values[0] for value in skill_values[1:]):
        errors.append("injected skill input changed between plan, staging, and persistence")
    try:
        persisted_inputs = task_workspace_input_hashes(
            run_dir / "workspace", str(configuration), str(metadata.get("skill"))
        )
    except EvaluationError as error:
        errors.append(f"persisted task inputs are invalid: {error}")
    else:
        if receipt.get("persisted_fixture_sha256") != persisted_inputs.get(
            "fixture_sha256"
        ):
            errors.append("workspace-persistence receipt does not bind persisted fixture")
        if receipt.get("persisted_injected_skill_sha256") != persisted_inputs.get(
            "skill_package_sha256"
        ):
            errors.append("workspace-persistence receipt does not bind persisted skill")
    if expected_inputs is not None:
        if receipt.get("run_plan_fixture_sha256") != expected_inputs.get(
            "fixture_sha256"
        ):
            errors.append("workspace-persistence fixture hash does not match run plan")
        if receipt.get("run_plan_skill_sha256") != expected_inputs.get(
            "skill_package_sha256"
        ):
            errors.append("workspace-persistence skill hash does not match run plan")
    return errors


def validate_task_evidence_binding(
    metadata: dict[str, Any],
    run_dir: Path,
    expected_case_contract_sha256: str | None = None,
    expected_workspace_inputs: dict[str, str | None] | None = None,
) -> list[str]:
    """Verify persisted task evidence and its planned case contract fail closed."""

    errors: list[str] = []
    recorded = metadata.get("task_evidence")
    if not isinstance(recorded, dict):
        return ["missing task-evidence receipt"]
    actual = task_evidence_receipt(run_dir)
    if recorded != actual:
        errors.append("task-evidence receipt does not match persisted files")
    errors.extend(
        workspace_persistence_validation_errors(
            metadata, actual, run_dir, expected_workspace_inputs
        )
    )
    errors.extend(
        workspace_environment_receipt_validation_errors(
            metadata,
            "task execution",
            require_absent_workspace=True,
            require_absent_ceiling=True,
        )
    )
    contract: dict[str, Any] | None = None
    try:
        contract = load_json(run_dir / "case_contract.json")
    except EvaluationError as error:
        errors.append(str(error))
    errors.extend(
        task_artifact_validation_errors(
            run_dir / "workspace", contract, metadata.get("configuration")
        )
    )
    errors.extend(task_output_safety_validation_errors(run_dir / "task-output.json"))
    errors.extend(task_trace_isolation_validation_errors(run_dir / "transcript.jsonl"))
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in actual.values()):
        errors.append("task-evidence receipt is incomplete")
    if (
        expected_case_contract_sha256 is not None
        and (
            contract is None
            or canonical_json_sha256(contract) != expected_case_contract_sha256
        )
    ):
        errors.append("case contract does not match the run plan")
    return errors


def snapshot_manifest_files() -> dict[str, str]:
    """Return a validated history-free source inventory when no exact Git root exists."""

    manifest_path = REPO_ROOT / SNAPSHOT_MANIFEST_NAME
    if (REPO_ROOT / ".git").exists():
        raise EvaluationError(
            "Refusing source snapshot fallback while repository Git metadata is present"
        )
    if not manifest_path.is_file():
        raise EvaluationError(
            f"No exact Git worktree or source snapshot manifest is available at {REPO_ROOT}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"Cannot read source snapshot manifest: {error}") from error
    files = manifest.get("files")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("project") != "report-skills"
        or manifest.get("snapshot_type") != "intended-public-repository-tree"
        or manifest.get("git_history_present") is not False
        or not isinstance(files, dict)
        or manifest.get("file_count") != len(files)
    ):
        raise EvaluationError("Source snapshot manifest metadata is invalid")
    validated: dict[str, str] = {}
    collision_inventory: list[TrackedFile] = []
    for raw_path, digest in files.items():
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise EvaluationError("Source snapshot manifest file entries are invalid")
        try:
            path = validate_release_path(raw_path)
        except SystemExit as error:
            raise EvaluationError(str(error)) from error
        if path.as_posix() != raw_path or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise EvaluationError(f"Unsafe source snapshot manifest entry: {raw_path!r}")
        parts = tuple(part.casefold() for part in path.parts)
        if parts[:2] in {("evals", "review"), ("evals", "runs")}:
            raise EvaluationError(f"Raw evaluation path in source snapshot: {raw_path}")
        canonical = path.as_posix()
        if canonical in validated:
            raise EvaluationError(f"Duplicate source snapshot manifest entry: {canonical}")
        validated[canonical] = digest
        collision_inventory.append(TrackedFile(path, "100644", digest))
    try:
        validate_portable_collisions(collision_inventory)
    except SystemExit as error:
        raise EvaluationError(str(error)) from error
    if len(validated) != len(files):
        raise EvaluationError("Source snapshot manifest paths are not unique")

    actual: dict[str, Path] = {}
    for path in sorted(REPO_ROOT.rglob("*")):
        if path.is_symlink():
            raise EvaluationError(
                f"Symlink is not allowed in source snapshot: {path.relative_to(REPO_ROOT)}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        parts = tuple(part.casefold() for part in PurePosixPath(relative).parts)
        if parts[:2] in {("evals", "review"), ("evals", "runs")}:
            raise EvaluationError(f"Raw evaluation path in source snapshot: {relative}")
        if relative == SNAPSHOT_MANIFEST_NAME:
            continue
        if SNAPSHOT_PYTHON_CACHE_PART in parts and path.suffix.casefold() == ".pyc":
            continue
        actual[relative] = path
    missing = sorted(set(validated) - set(actual))
    extra = sorted(set(actual) - set(validated))
    if missing:
        raise EvaluationError(f"Source snapshot manifest files are missing: {missing}")
    if extra:
        raise EvaluationError(f"Unmanifested files exist in source snapshot: {extra}")
    mismatched = sorted(
        relative
        for relative, path in actual.items()
        if hashlib.sha256(path.read_bytes()).hexdigest() != validated[relative]
    )
    if mismatched:
        raise EvaluationError(f"Source snapshot file hash mismatch: {mismatched}")
    return validated


def repository_source_files() -> dict[str, Path]:
    """Return the exact current source inventory from Git or a verified snapshot."""

    try:
        root_result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={REPO_ROOT}",
                "-C",
                str(REPO_ROOT),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
        )
    except OSError:
        root_result = None
    exact_git_root = (
        root_result is not None
        and root_result.returncode == 0
        and Path(root_result.stdout.strip()).resolve() == REPO_ROOT.resolve()
    )
    relative_paths: list[str]
    if exact_git_root:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={REPO_ROOT}",
                "-C",
                str(REPO_ROOT),
                "ls-files",
                "--stage",
                "-z",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).decode(
                "utf-8", errors="replace"
            ).strip()
            raise EvaluationError(
                f"Cannot list repository source files: {detail}"
            )
        relative_paths = []
        collision_inventory: list[TrackedFile] = []
        for entry in result.stdout.split(b"\0"):
            if not entry:
                continue
            metadata, separator, raw_path = entry.partition(b"\t")
            if not separator:
                raise EvaluationError("Cannot parse repository source inventory")
            try:
                mode, object_id, stage = metadata.decode("ascii").split(" ", 2)
                raw_relative = raw_path.decode("utf-8")
                relative = validate_release_path(raw_relative)
            except (UnicodeDecodeError, ValueError, SystemExit) as error:
                raise EvaluationError(
                    f"Unsafe repository source inventory entry: {entry!r}"
                ) from error
            if stage != "0" or mode not in {"100644", "100755"}:
                raise EvaluationError(
                    f"Non-regular repository source entry: {raw_relative} ({mode}, stage {stage})"
                )
            canonical = relative.as_posix()
            if canonical != raw_relative:
                raise EvaluationError(
                    f"Noncanonical repository source path: {raw_relative!r}"
                )
            parts = tuple(part.casefold() for part in relative.parts)
            if parts[:2] in {("evals", "review"), ("evals", "runs")}:
                raise EvaluationError(f"Tracked raw evaluation path: {canonical}")
            if canonical in relative_paths:
                raise EvaluationError(f"Duplicate repository source path: {canonical}")
            relative_paths.append(canonical)
            collision_inventory.append(TrackedFile(relative, mode, object_id))
        try:
            validate_portable_collisions(collision_inventory)
        except SystemExit as error:
            raise EvaluationError(str(error)) from error
    else:
        relative_paths = sorted(snapshot_manifest_files())

    source_files: dict[str, Path] = {}
    root = REPO_ROOT.resolve()
    for raw_relative in sorted(relative_paths):
        relative = PurePosixPath(raw_relative)
        path = REPO_ROOT.joinpath(*relative.parts)
        try:
            path.resolve().relative_to(root)
            info = path.lstat()
        except (OSError, ValueError) as error:
            raise EvaluationError(
                f"Repository source file is missing or unsafe: {raw_relative}"
            ) from error
        is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if path.is_symlink() or is_reparse or not stat.S_ISREG(info.st_mode):
            raise EvaluationError(f"Repository source file must be regular: {raw_relative}")
        source_files[raw_relative] = path
    if not source_files:
        raise EvaluationError("Repository source inventory is empty")
    return source_files


def repository_csv_validation_errors() -> list[str]:
    """Return structural errors for CSV files in the exact source inventory."""

    errors: list[str] = []
    for relative, path in repository_source_files().items():
        if path.suffix.casefold() != ".csv":
            continue
        errors.extend(
            csv_file_validation_errors(path, relative, subject="repository CSV")
        )
    return errors


def tracked_directory_sha256(root: Path) -> str:
    """Hash exact tracked files, with a verified history-free snapshot fallback."""

    relative_root = root.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    inventory = repository_source_files()
    if relative_root == ".":
        tracked = inventory
    else:
        prefix = f"{relative_root.rstrip('/')}/"
        tracked = {
            relative: path
            for relative, path in inventory.items()
            if relative.startswith(prefix)
        }
    if not tracked:
        raise EvaluationError(f"No tracked source files found under {root}")
    actual = [path for path in sorted(root.rglob("*")) if path.is_file()]
    tracked_paths = list(tracked.values())
    extras = sorted(
        path.relative_to(root).as_posix()
        for path in set(actual) - set(tracked_paths)
    )
    if extras:
        raise EvaluationError(f"Untracked or ignored files affect evaluated directory {root}: {extras}")
    digest = hashlib.sha256()
    for relative, path in tracked.items():
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(content_digest))
    return digest.hexdigest()


def repository_receipt(require_clean: bool = False) -> dict[str, Any]:
    """Return the exact candidate Git state used by a model-backed run."""

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={REPO_ROOT}", "-C", str(REPO_ROOT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise EvaluationError(f"Cannot record repository state: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout.strip()

    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if root != REPO_ROOT.resolve():
        raise EvaluationError(f"Git root mismatch: expected {REPO_ROOT.resolve()}, got {root}")
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    dirty = bool(status)
    if require_clean and dirty:
        raise EvaluationError("Refusing a release evaluation from a dirty repository; commit or remove candidate changes first")
    return {"root": str(root), "commit": commit, "tree": tree, "dirty": dirty}


def require_pinned_profile(execute: bool, model: str | None, reasoning_effort: str | None) -> None:
    if execute and (not model or not reasoning_effort):
        raise EvaluationError("Live evaluation requires both --model and --reasoning-effort for reproducibility")


def _codex_package_manager(package_root: Path, entrypoint: Path) -> str:
    """Mirror the installed JavaScript shim's npm/pnpm/bun environment choice."""

    for start in {package_root.resolve(), entrypoint.parent.resolve()}:
        current = start
        while True:
            node_modules = current / "node_modules"
            installed = node_modules / "@openai" / "codex"
            if (node_modules / ".modules.yaml").is_file() and installed.is_dir():
                try:
                    if installed.resolve() == package_root.resolve():
                        return "pnpm"
                except OSError:
                    pass
            if current == current.parent:
                break
            current = current.parent
    package_text = str(package_root).replace("\\", "/")
    if (
        ".bun/install/global" in package_text
        or "bun" in os.environ.get("npm_config_user_agent", "").casefold()
        or "bun" in os.environ.get("npm_execpath", "").casefold()
    ):
        return "bun"
    return "npm"


def codex_execution_profile(codex_command: str, model: str, reasoning_effort: str) -> dict[str, Any]:
    """Verify and record the exact Codex CLI/model profile used for live calls."""

    resolved_command = Path(codex_command).resolve()
    adjacent_package = resolved_command.parent / "node_modules" / "@openai" / "codex"
    npm_package: Path | None = adjacent_package if adjacent_package.is_dir() else None
    if npm_package is None:
        npm_package = next(
            (
                parent
                for parent in (resolved_command.parent, *resolved_command.parents)
                if parent.name == "codex"
                and parent.parent.name == "@openai"
                and (parent / "package.json").is_file()
            ),
            None,
        )

    managed_package_root: Path | None = None
    managed_by: str | None = None
    if npm_package is not None:
        executable_name = "codex.exe" if sys.platform == "win32" else "codex"
        candidates = sorted(
            {
                path.resolve()
                for path in (npm_package / "node_modules" / "@openai").glob(
                    f"codex-*/vendor/**/bin/{executable_name}"
                )
                if path.is_file()
            }
        )
        if len(candidates) != 1:
            raise EvaluationError(
                "Cannot resolve exactly one native Codex implementation from the package "
                f"behind {resolved_command}; found {len(candidates)} candidates"
            )
        implementation = candidates[0]
        managed_package_root = npm_package.resolve()
        managed_by = _codex_package_manager(managed_package_root, resolved_command)
    else:
        try:
            header = resolved_command.read_bytes()[:4]
        except OSError as error:
            raise EvaluationError(f"Cannot read Codex executable {resolved_command}: {error}") from error
        native_headers = {
            b"MZ",
            b"\x7fELF",
            b"\xfe\xed\xfa\xce",
            b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
        }
        if not any(header.startswith(candidate) for candidate in native_headers):
            raise EvaluationError(
                "Codex command is a wrapper or script, but no unique packaged native "
                f"implementation could be resolved: {resolved_command}"
            )
        implementation = resolved_command

    probe_environment = os.environ.copy()
    for key in ("CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_BY_PNPM", "CODEX_MANAGED_BY_BUN"):
        probe_environment.pop(key, None)
    if managed_package_root is None:
        probe_environment.pop("CODEX_MANAGED_PACKAGE_ROOT", None)
    else:
        probe_environment["CODEX_MANAGED_PACKAGE_ROOT"] = str(managed_package_root)
        probe_environment[f"CODEX_MANAGED_BY_{str(managed_by).upper()}"] = "1"
    implementation_hash = hashlib.sha256(implementation.read_bytes()).hexdigest()

    version_result = subprocess.run(
        [str(implementation), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
        env=probe_environment,
    )
    if version_result.returncode != 0:
        raise EvaluationError(
            "Cannot record Codex CLI version: "
            + (version_result.stderr.strip() or version_result.stdout.strip())
        )
    version = version_result.stdout.strip()

    catalog_result = subprocess.run(
        [str(implementation), "debug", "models"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=120,
        env=probe_environment,
    )
    if catalog_result.returncode != 0:
        raise EvaluationError(
            "Cannot verify the live Codex model catalog: "
            + (catalog_result.stderr.strip() or catalog_result.stdout.strip())
        )
    try:
        catalog = json.loads(catalog_result.stdout)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Codex returned an invalid model catalog: {exc}") from exc
    entries = catalog.get("models", []) if isinstance(catalog, dict) else []
    selected = next((item for item in entries if item.get("slug") == model), None)
    if selected is None:
        raise EvaluationError(f"Pinned model is not available in the live Codex catalog: {model}")
    supported = {
        item.get("effort")
        for item in selected.get("supported_reasoning_levels", [])
        if isinstance(item, dict)
    }
    if reasoning_effort not in supported:
        raise EvaluationError(
            f"Reasoning effort {reasoning_effort!r} is not supported by {model}; "
            f"available efforts: {sorted(value for value in supported if value)}"
        )
    command_hash = hashlib.sha256(resolved_command.read_bytes()).hexdigest()
    final_implementation_hash = hashlib.sha256(implementation.read_bytes()).hexdigest()
    if final_implementation_hash != implementation_hash:
        raise EvaluationError("Native Codex implementation changed during profile discovery")
    managed_environment_json = json.dumps(
        {
            "codex_managed_package_root": (
                str(managed_package_root) if managed_package_root is not None else None
            ),
            "codex_managed_by": managed_by,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    selected_json = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "codex_invocation": CODEX_INVOCATION_MODE,
        "codex_timeout_enforcement": CODEX_TIMEOUT_ENFORCEMENT_MODE,
        "codex_cli_version": version,
        "codex_command": str(resolved_command),
        "codex_command_sha256": command_hash,
        "codex_implementation": str(implementation),
        "codex_implementation_sha256": implementation_hash,
        "codex_managed_package_root": (
            str(managed_package_root) if managed_package_root is not None else None
        ),
        "codex_managed_by": managed_by,
        "codex_managed_environment_sha256": hashlib.sha256(
            managed_environment_json.encode("utf-8")
        ).hexdigest(),
        "model_catalog_sha256": hashlib.sha256(catalog_result.stdout.encode("utf-8")).hexdigest(),
        "selected_model_sha256": hashlib.sha256(selected_json.encode("utf-8")).hexdigest(),
        "model_default_reasoning_effort": str(selected.get("default_reasoning_level")),
        "model_supported_reasoning_efforts": sorted(value for value in supported if value),
        "python_version": platform.python_version(),
        "platform": f"{platform.system()}-{platform.release()}-{platform.machine()}",
    }


def codex_runtime_command(execution_profile: dict[str, Any]) -> str:
    """Return the exact profiled native executable, failing if it has changed."""

    if execution_profile.get("codex_invocation") != CODEX_INVOCATION_MODE:
        raise EvaluationError("Unsupported or missing Codex invocation method")
    raw_path = execution_profile.get("codex_implementation")
    expected_hash = execution_profile.get("codex_implementation_sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise EvaluationError("Execution profile is missing the Codex implementation path")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise EvaluationError("Execution profile has an invalid Codex implementation hash")
    implementation = Path(raw_path).resolve()
    if not implementation.is_file():
        raise EvaluationError(f"Profiled Codex implementation is unavailable: {implementation}")
    actual_hash = file_sha256(implementation)
    if actual_hash != expected_hash:
        raise EvaluationError(
            "Profiled Codex implementation changed during evaluation: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    return str(implementation)


def codex_runtime_environment(execution_profile: dict[str, Any]) -> dict[str, str]:
    """Reproduce the package shim's managed environment for direct native execution."""

    environment = os.environ.copy()
    for key in ("CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_BY_PNPM", "CODEX_MANAGED_BY_BUN"):
        environment.pop(key, None)
    raw_root = execution_profile.get("codex_managed_package_root")
    managed_by = execution_profile.get("codex_managed_by")
    expected_hash = execution_profile.get("codex_managed_environment_sha256")
    descriptor = json.dumps(
        {
            "codex_managed_package_root": raw_root,
            "codex_managed_by": managed_by,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    actual_hash = hashlib.sha256(descriptor.encode("utf-8")).hexdigest()
    if expected_hash != actual_hash:
        raise EvaluationError("Execution profile managed environment receipt does not match")
    if raw_root is None and managed_by is None:
        environment.pop("CODEX_MANAGED_PACKAGE_ROOT", None)
        return environment
    if not isinstance(raw_root, str) or not Path(raw_root).resolve().is_dir():
        raise EvaluationError("Execution profile has an invalid managed package root")
    if managed_by not in {"npm", "pnpm", "bun"}:
        raise EvaluationError("Execution profile has an invalid Codex package manager")
    environment["CODEX_MANAGED_PACKAGE_ROOT"] = str(Path(raw_root).resolve())
    environment[f"CODEX_MANAGED_BY_{str(managed_by).upper()}"] = "1"
    return environment


def workspace_environment_receipt(workspace: Path) -> dict[str, Any]:
    """Describe the exact external-workspace Git environment for one model call."""

    resolved_workspace = workspace.resolve()
    resolved_ceiling = resolved_workspace.parent
    return {
        "schema_version": "1.0",
        "guard": TASK_GIT_DISCOVERY_GUARD,
        "workspace": str(resolved_workspace),
        "ceiling": str(resolved_ceiling),
        "inherited_git_environment_scrubbed": True,
        "candidate_repository_environment_scrubbed": True,
        "controlled_git_environment": {
            "GIT_CEILING_DIRECTORIES": str(resolved_ceiling),
            "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
        },
    }


def lstat_path_entry_exists(path: Path) -> bool:
    """Return whether an entry exists without following its link target."""

    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def workspace_environment_receipt_validation_errors(
    document: dict[str, Any],
    label: str,
    *,
    require_absent_workspace: bool = False,
    require_absent_ceiling: bool = False,
) -> list[str]:
    """Require a canonical, absolute, outside-repository workspace receipt."""

    receipt = document.get("workspace_environment")
    expected_keys = {
        "schema_version",
        "guard",
        "workspace",
        "ceiling",
        "inherited_git_environment_scrubbed",
        "candidate_repository_environment_scrubbed",
        "controlled_git_environment",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_keys:
        return [f"{label} has a missing or invalid workspace-environment receipt"]
    errors: list[str] = []
    workspace_value = receipt.get("workspace")
    ceiling_value = receipt.get("ceiling")
    if (
        receipt.get("schema_version") != "1.0"
        or receipt.get("guard") != TASK_GIT_DISCOVERY_GUARD
        or receipt.get("inherited_git_environment_scrubbed") is not True
        or receipt.get("candidate_repository_environment_scrubbed") is not True
        or not isinstance(workspace_value, str)
        or not isinstance(ceiling_value, str)
    ):
        errors.append(f"{label} workspace-environment method is invalid")
        return errors
    workspace = Path(workspace_value)
    ceiling = Path(ceiling_value)
    if not workspace.is_absolute() or not ceiling.is_absolute():
        errors.append(f"{label} workspace-environment paths are not absolute")
    else:
        try:
            resolved_workspace = workspace.resolve()
            resolved_ceiling = ceiling.resolve()
            repository_root = REPO_ROOT.resolve()
        except (OSError, RuntimeError) as error:
            errors.append(f"{label} workspace-environment paths are invalid: {error}")
        else:
            if str(resolved_workspace) != workspace_value:
                errors.append(f"{label} workspace path is not canonical")
            if str(resolved_ceiling) != ceiling_value:
                errors.append(f"{label} workspace ceiling is not canonical")
            if resolved_workspace.parent != resolved_ceiling:
                errors.append(f"{label} workspace ceiling does not contain the workspace")
            if is_relative_to(resolved_workspace, repository_root):
                errors.append(f"{label} workspace is inside the candidate repository")
    expected_environment = {
        "GIT_CEILING_DIRECTORIES": ceiling_value,
        "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
    }
    if receipt.get("controlled_git_environment") != expected_environment:
        errors.append(f"{label} controlled Git environment is invalid")
    cleanup_paths = (
        ("workspace", workspace_value, require_absent_workspace),
        ("ceiling", ceiling_value, require_absent_ceiling),
    )
    for path_label, path_value, require_absent in cleanup_paths:
        if not require_absent or not isinstance(path_value, str):
            continue
        path = Path(path_value)
        if not path.is_absolute():
            continue
        try:
            path_present = lstat_path_entry_exists(path)
        except (OSError, ValueError) as error:
            errors.append(
                f"{label} cannot verify recorded {path_label} cleanup: {error}"
            )
        else:
            if not path_present:
                continue
            errors.append(f"{label} recorded {path_label} was not cleaned")
    return errors


def normalized_path_disclosure_text(value: object) -> str:
    """Normalize path-like text before checking model-facing path disclosures."""

    return str(value).replace("\\", "/").rstrip("/").casefold()


def require_isolated_model_invocation(
    command: list[str],
    environment: dict[str, str],
    forbidden_paths: Iterable[Path],
    label: str,
) -> None:
    """Fail before a model call if argv or environment exposes durable paths."""

    forbidden = tuple(
        normalized_path_disclosure_text(path.resolve()) for path in forbidden_paths
    )

    def disclosure(value: object) -> str | None:
        normalized = normalized_path_disclosure_text(value)
        return next((path for path in forbidden if path and path in normalized), None)

    disclosed_arguments = [argument for argument in command if disclosure(argument)]
    disclosed_environment = [
        key for key, value in environment.items() if disclosure(value)
    ]
    if disclosed_arguments or disclosed_environment:
        details: list[str] = []
        if disclosed_arguments:
            details.append("argv")
        if disclosed_environment:
            details.append("environment keys " + ", ".join(sorted(disclosed_environment)))
        raise EvaluationError(
            f"{label} exposes a candidate or durable evidence path in "
            + " and ".join(details)
        )


def task_runtime_environment(
    execution_profile: dict[str, Any], workspace: Path
) -> dict[str, str]:
    """Fence workspace-local Git discovery and discard inherited overrides."""

    environment = codex_runtime_environment(execution_profile)
    repository_root = normalized_path_disclosure_text(REPO_ROOT.resolve())
    for key in list(environment):
        value = str(environment.get(key, ""))
        if (
            key.casefold().startswith("git_")
            or repository_root in normalized_path_disclosure_text(value)
        ):
            environment.pop(key, None)
    receipt = workspace_environment_receipt(workspace)
    environment.update(receipt["controlled_git_environment"])
    return environment


def require_clean_task_execution(
    metadata: dict[str, Any],
    label: str,
    run_dir: Path | None = None,
    expected_case_contract_sha256: str | None = None,
    expected_workspace_inputs: dict[str, str | None] | None = None,
) -> None:
    """Refuse downstream calls for an incomplete, failed, or timed-out task."""

    profile = metadata.get("execution_profile")
    receipt_errors = execution_receipt_validation_errors(
        metadata, CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS, label
    )
    evidence_errors = (
        validate_task_evidence_binding(
            metadata,
            run_dir,
            expected_case_contract_sha256,
            expected_workspace_inputs,
        )
        if run_dir is not None
        else []
    )
    isolation_errors = task_isolation_receipt_validation_errors(metadata, label)
    isolation_errors.extend(model_isolation_receipt_validation_errors(metadata, label))
    isolation_errors.extend(
        stage_method_receipt_validation_errors(metadata, "behavioral_task", label)
    )
    isolation_errors.extend(
        workspace_environment_receipt_validation_errors(metadata, label)
    )
    if (
        metadata.get("validation_errors") != []
        or receipt_errors
        or evidence_errors
        or isolation_errors
        or not isinstance(profile, dict)
        or profile.get("codex_invocation") != CODEX_INVOCATION_MODE
        or profile.get("codex_timeout_enforcement") != CODEX_TIMEOUT_ENFORCEMENT_MODE
    ):
        raise EvaluationError(
            f"{label} is not a clean task execution and cannot be graded or compared"
        )


def require_clean_stage_execution(
    metadata: dict[str, Any], expected_timeout: int, label: str, stage: str
) -> None:
    """Refuse continuation past any failed or noncanonical model-backed stage call."""

    profile = metadata.get("execution_profile")
    if (
        metadata.get("validation_errors") != []
        or execution_receipt_validation_errors(metadata, expected_timeout, label)
        or model_isolation_receipt_validation_errors(metadata, label)
        or stage_method_receipt_validation_errors(metadata, stage, label)
        or not isinstance(profile, dict)
        or profile.get("codex_invocation") != CODEX_INVOCATION_MODE
        or profile.get("codex_timeout_enforcement") != CODEX_TIMEOUT_ENFORCEMENT_MODE
    ):
        raise EvaluationError(f"{label} is not a clean canonical stage execution")


def require_complete_task_evidence(suite_run_dir: Path) -> list[Path]:
    """Return exact planned task directories only when every task finished cleanly."""

    plan = load_json(suite_run_dir / "run-plan.json")
    plan_method_errors = stage_method_receipt_validation_errors(
        plan, "behavioral_task", "Benchmark run plan"
    )
    if plan_method_errors:
        raise EvaluationError("; ".join(plan_method_errors))
    rows = plan.get("runs")
    if not isinstance(rows, list):
        raise EvaluationError("Benchmark run plan has no task inventory")
    expected_ids = [str(row.get("run_id")) for row in rows if isinstance(row, dict)]
    if len(expected_ids) != len(rows) or len(set(expected_ids)) != len(expected_ids):
        raise EvaluationError("Benchmark run plan has invalid or duplicate task IDs")
    runs_root = suite_run_dir / "runs"
    run_dirs = (
        sorted(path for path in runs_root.iterdir() if path.is_dir())
        if runs_root.is_dir()
        else []
    )
    observed: dict[str, Path] = {}
    expected_rows = {str(row["run_id"]): row for row in rows}
    expected_contract_hashes = plan.get("case_contract_hashes")
    if not isinstance(expected_contract_hashes, dict) or set(expected_contract_hashes) != set(
        expected_ids
    ) or any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in expected_contract_hashes.values()
    ):
        raise EvaluationError("Benchmark run plan has no exact case-contract inventory")
    binding_fields = (
        "pair_id",
        "case_id",
        "case_kind",
        "skill",
        "configuration",
        "repetition",
    )
    for run_dir in run_dirs:
        metadata_path = run_dir / "run_metadata.json"
        if not metadata_path.is_file():
            raise EvaluationError(f"Missing task metadata: {metadata_path}")
        metadata = load_json(metadata_path)
        run_id = metadata.get("run_id")
        if not isinstance(run_id, str) or not run_id or run_id in observed:
            raise EvaluationError(f"Invalid or duplicate task identity in {metadata_path}")
        expected_inputs = planned_task_workspace_input_hashes(plan, metadata)
        require_clean_task_execution(
            metadata,
            f"Task {run_dir.name}",
            run_dir,
            str(expected_contract_hashes.get(run_id)),
            expected_inputs,
        )
        observed[run_id] = run_dir
        expected = expected_rows.get(run_id)
        if expected is None or any(
            metadata.get(field) != expected.get(field) for field in binding_fields
        ):
            raise EvaluationError(f"Task {run_dir.name} does not match its run-plan row")
        require_matching_context(
            plan.get("execution_profile", {}),
            plan.get("repository", {}),
            metadata.get("execution_profile", {}),
            metadata.get("repository", {}),
            f"Task {run_dir.name}",
        )
    missing = sorted(set(expected_ids) - set(observed))
    extra = sorted(set(observed) - set(expected_ids))
    if missing or extra:
        raise EvaluationError(
            "Task evidence does not exactly match the run plan: "
            f"missing={missing}, extra={extra}"
        )
    return [observed[run_id] for run_id in expected_ids]


def require_matching_context(
    expected_profile: dict[str, Any],
    expected_repository: dict[str, Any],
    actual_profile: dict[str, Any],
    actual_repository: dict[str, Any],
    label: str,
) -> None:
    expected_profile_identity = {key: expected_profile.get(key) for key in PROFILE_IDENTITY_KEYS}
    actual_profile_identity = {key: actual_profile.get(key) for key in PROFILE_IDENTITY_KEYS}
    if actual_profile_identity != expected_profile_identity or any(
        value in {None, ""} for value in actual_profile_identity.values()
    ):
        raise EvaluationError(
            f"{label} execution profile does not match the benchmark plan: "
            f"expected {expected_profile_identity}, got {actual_profile_identity}"
        )
    expected_repository_identity = {
        key: expected_repository.get(key) for key in REPOSITORY_IDENTITY_KEYS
    }
    actual_repository_identity = {
        key: actual_repository.get(key) for key in REPOSITORY_IDENTITY_KEYS
    }
    if actual_repository_identity != expected_repository_identity or actual_repository_identity.get("dirty") is not False:
        raise EvaluationError(
            f"{label} repository receipt does not match the benchmark plan: "
            f"expected {expected_repository_identity}, got {actual_repository_identity}"
        )


def require_unchanged_repository(expected: dict[str, Any]) -> None:
    """Abort a long run if the candidate Git state changes between calls."""

    current = repository_receipt(require_clean=True)
    if current != expected:
        raise EvaluationError(
            f"Repository changed during evaluation: expected {expected}, got {current}"
        )


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n")


def write_json_exclusive(path: Path, value: Any) -> None:
    """Create a JSON receipt exactly once, refusing any replacement or race."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=False) + "\n")
    except FileExistsError as exc:
        raise EvaluationError(f"Refusing to replace existing evidence: {path}") from exc


def resolve_suite(path: Path | None = None) -> Path:
    if path:
        return path.resolve()
    return DEFAULT_SUITE if DEFAULT_SUITE.is_file() else LEGACY_SUITE


def _legacy_assertions(case: dict[str, Any]) -> list[dict[str, Any]]:
    checks = case.get("blocking_checks", [])
    if not isinstance(checks, list) or not checks:
        raise EvaluationError(f"Legacy case {case.get('case_id')} has no blocking_checks")
    weight = 100.0 / len(checks)
    return [
        {
            "assertion_id": f"{case['case_id']}.a{index:02d}",
            "category": "legacy_blocking_check",
            "text": str(check),
            "weight": weight,
            "blocking": True,
        }
        for index, check in enumerate(checks, 1)
    ]


def normalize_suite(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the v1 benchmark contract and the original eval inventory."""
    if "primary_cases" in data:
        result = dict(data)
        result.setdefault("protocol", {})
        result["protocol"].setdefault("repetitions_per_configuration", 3)
        result["protocol"].setdefault(
            "configurations", [{"id": "with_skill"}, {"id": "without_skill"}]
        )
        return result

    if "cases" not in data:
        raise EvaluationError("Suite must contain primary_cases or legacy cases")
    primary_cases = []
    for raw in data.get("cases", []):
        case = dict(raw)
        case["assertions"] = _legacy_assertions(case)
        primary_cases.append(case)
    adversarial = []
    for raw in data.get("adversarial_cases", []):
        case = dict(raw)
        case.setdefault("skill", "report-skills")
        required = str(case.get("required_result", "Required safe behavior is present."))
        case["assertions"] = [
            {
                "assertion_id": f"{case['case_id']}.a01",
                "category": "legacy_adversarial_check",
                "text": required,
                "weight": 100,
                "blocking": True,
            }
        ]
        adversarial.append(case)
    return {
        "schema_version": data.get("schema_version", "1.0"),
        "suite_id": "legacy-evals-compatible",
        "fixture": data.get("fixture", "../examples/synthetic-report"),
        "protocol": {
            "repetitions_per_configuration": 3,
            "configurations": [{"id": "with_skill"}, {"id": "without_skill"}],
        },
        "primary_cases": primary_cases,
        "adversarial_cases": adversarial,
    }


def suite_cases(suite: dict[str, Any], include_adversarial: bool = True) -> list[dict[str, Any]]:
    cases = [dict(case, case_kind="primary") for case in suite.get("primary_cases", [])]
    if include_adversarial:
        cases.extend(dict(case, case_kind="adversarial") for case in suite.get("adversarial_cases", []))
    return cases


def suite_fixture(suite_path: Path, suite: dict[str, Any]) -> Path:
    raw = Path(str(suite.get("fixture", "../examples/synthetic-report")))
    return (suite_path.parent / raw).resolve() if not raw.is_absolute() else raw.resolve()


def configured_repetitions(suite: dict[str, Any], thresholds: dict[str, Any] | None = None) -> int:
    candidates = [
        suite.get("protocol", {}).get("repetitions_per_configuration"),
        suite.get("protocol", {}).get("runs_per_configuration"),
        (thresholds or {}).get("runs_per_configuration"),
        (thresholds or {}).get("protocol", {}).get("runs_per_configuration"),
    ]
    for candidate in candidates:
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return 3


def configuration_ids(suite: dict[str, Any]) -> list[str]:
    values = suite.get("protocol", {}).get("configurations", [])
    ids = [value.get("id") if isinstance(value, dict) else value for value in values]
    ids = [str(value) for value in ids if value]
    return ids or ["with_skill", "without_skill"]


def build_run_plan(
    suite: dict[str, Any],
    repetitions: int,
    configurations: Iterable[str] | None = None,
    selected_cases: set[str] | None = None,
    include_adversarial: bool = True,
) -> list[dict[str, Any]]:
    configs = list(configurations or configuration_ids(suite))
    cases = suite_cases(suite, include_adversarial=include_adversarial)
    plan: list[dict[str, Any]] = []
    for case in cases:
        if selected_cases and case["case_id"] not in selected_cases:
            continue
        for repetition in range(1, repetitions + 1):
            for configuration in configs:
                run_id = f"{case['case_id']}__{configuration}__r{repetition:02d}"
                plan.append(
                    {
                        "run_id": run_id,
                        "pair_id": f"{case['case_id']}__r{repetition:02d}",
                        "case_id": case["case_id"],
                        "case_kind": case["case_kind"],
                        "skill": case.get("skill", "report-skills"),
                        "configuration": configuration,
                        "repetition": repetition,
                        "prompt": case["prompt"],
                        "required_result": case.get("required_result"),
                        "assertions": case.get("assertions", []),
                        "artifact_checks": case.get("artifact_checks", []),
                    }
                )
    return plan


def persisted_run_plan_row(run: dict[str, Any]) -> dict[str, Any]:
    """Return the public logical row while keeping full case contracts hash-bound."""

    return {
        key: value
        for key, value in run.items()
        if key not in {"prompt", "assertions", "artifact_checks"}
    }


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_output_root(path: Path, allow_tracked_output: bool = False) -> Path:
    resolved = path.resolve()
    if is_relative_to(resolved, RESULTS_ROOT) and not allow_tracked_output:
        raise EvaluationError(
            f"Refusing raw run output inside tracked eval results: {resolved}. "
            "Use evals/runs or pass --allow-tracked-output deliberately."
        )
    return resolved


def parse_skill_description(skill_path: Path) -> str:
    text = skill_path.read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip().strip("\"'")


def baseline_contamination_paths(skills: Iterable[str]) -> list[str]:
    """Return auto-discoverable installations that can invalidate a baseline."""
    roots = [Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"]
    extra = os.environ.get("REPORT_SKILLS_DISCOVERY_ROOTS", "")
    roots.extend(Path(value) for value in extra.split(os.pathsep) if value)
    found: list[str] = []
    for root in roots:
        for skill in skills:
            candidate = root / skill / "SKILL.md"
            if candidate.is_file():
                found.append(str(candidate.resolve()))
    return sorted(set(found))


def find_codex_command(requested: str | None = None) -> str:
    if requested:
        resolved = shutil.which(requested)
        if not resolved:
            raise EvaluationError(f"Codex command not found: {requested}")
        return resolved
    for name in ("codex.cmd", "codex") if sys.platform == "win32" else ("codex", "codex.cmd"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise EvaluationError("Codex CLI not found on PATH")


def codex_base_command(
    codex_command: str,
    cwd: Path,
    sandbox: str,
    output_schema: Path,
    output_message: Path,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> list[str]:
    command = [
        codex_command,
        "exec",
        "--disable",
        "multi_agent",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--json",
    ]
    if sandbox == "workspace-write":
        command.append("--approve-for-me")
    else:
        command.extend(["--sandbox", sandbox])
    command.extend([
        "--cd",
        str(cwd),
        "--output-schema",
        str(output_schema.resolve()),
        "--output-last-message",
        str(output_message.resolve()),
    ])
    if model:
        command.extend(["--model", model])
    if reasoning_effort:
        command.extend(["--config", f'model_reasoning_effort="{reasoning_effort}"'])
    command.append("-")
    return command


@dataclass
class CommandResult:
    returncode: int
    wall_clock_seconds: float
    stdout: str
    stderr: str
    timed_out: bool = False
    timeout_seconds: int | None = None
    termination_method: str = "natural-exit"
    termination_reason: str = "process-exit"
    timeout_overrun_seconds: float = 0.0
    terminal_event_count: int = 0
    failed_terminal_event_count: int = 0
    timeout_enforcement: str = CODEX_TIMEOUT_ENFORCEMENT_MODE


def execution_receipt_validation_errors(
    receipt: Any, expected_timeout: int, label: str
) -> list[str]:
    """Validate the common deadline and terminal-state receipt for one model call."""

    def value(key: str) -> Any:
        return receipt.get(key) if isinstance(receipt, dict) else getattr(receipt, key, None)

    errors: list[str] = []
    if value("returncode") != 0:
        errors.append(f"{label} exited {value('returncode')}")
    if value("timeout_seconds") != expected_timeout:
        errors.append(f"{label} timeout receipt does not match {expected_timeout}")
    if value("timed_out") is not False:
        errors.append(f"{label} timed out or is missing timeout status")
    if value("termination_reason") != "process-exit":
        errors.append(f"{label} did not record a clean process exit")
    if value("termination_method") != "natural-exit":
        errors.append(f"{label} did not terminate naturally")
    overrun = value("timeout_overrun_seconds")
    if isinstance(overrun, bool) or not isinstance(overrun, (int, float)) or overrun != 0:
        errors.append(f"{label} has an invalid timeout-overrun receipt")
    if value("terminal_event_count") != 1:
        errors.append(f"{label} must contain exactly one turn.completed event")
    if value("failed_terminal_event_count") != 0:
        errors.append(f"{label} contains a failed terminal event")
    if value("timeout_enforcement") != CODEX_TIMEOUT_ENFORCEMENT_MODE:
        errors.append(f"{label} has an unsupported timeout-enforcement receipt")
    return errors


def _windows_kill_on_close_job(process: subprocess.Popen[Any]) -> int:
    """Assign a Windows process to a job that kills all descendants on close."""

    import ctypes
    from ctypes import wintypes

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise EvaluationError(
            f"Cannot create Codex process job: Windows error {ctypes.get_last_error()}"
        )
    information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(information), ctypes.sizeof(information)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise EvaluationError(f"Cannot configure Codex process job: Windows error {error}")
    if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise EvaluationError(f"Cannot assign Codex process job: Windows error {error}")
    return int(job)


def _windows_close_handle(handle: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return bool(kernel32.CloseHandle(wintypes.HANDLE(handle)))


def _windows_resume_process(process: subprocess.Popen[Any]) -> None:
    """Resume a process created suspended after it has entered the kill-on-close job."""

    import ctypes
    from ctypes import wintypes

    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.restype = ctypes.c_long
    status = ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle)))
    if status != 0:
        raise EvaluationError(f"Cannot resume Codex process after job assignment: NTSTATUS {status}")


def _terminate_process_tree(
    process: subprocess.Popen[Any], windows_job: int | None = None
) -> str:
    """Force-stop one evaluation process tree after its deadline."""

    method = CODEX_TIMEOUT_TERMINATION_MODE
    if os.name == "nt":
        if windows_job is None or not _windows_close_handle(windows_job):
            if process.poll() is None:
                process.kill()
            method = "direct-process-kill-fallback"
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            if process.poll() is None:
                process.kill()
            method = "direct-process-kill-fallback"
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=30)
        method = "direct-process-kill-fallback"
    return method


def run_codex(
    command: list[str],
    prompt: str,
    timeout: int,
    environment: dict[str, str] | None = None,
) -> CommandResult:
    start = time.perf_counter()
    process_options: dict[str, Any] = {}
    if os.name == "nt":
        process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004
    else:
        process_options["start_new_session"] = True
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            **process_options,
        )
        windows_job: int | None = None
        if os.name == "nt":
            try:
                windows_job = _windows_kill_on_close_job(process)
                _windows_resume_process(process)
            except EvaluationError:
                if windows_job is not None:
                    _windows_close_handle(windows_job)
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)
                raise
        timed_out = False
        termination_method = "natural-exit"
        try:
            process.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            termination_method = _terminate_process_tree(process, windows_job)
            windows_job = None
            try:
                process.communicate(timeout=30)
            except (subprocess.TimeoutExpired, ValueError):
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)
                termination_method = "direct-process-kill-fallback"
        except BaseException:
            _terminate_process_tree(process, windows_job)
            windows_job = None
            try:
                process.communicate(timeout=30)
            except (subprocess.TimeoutExpired, ValueError):
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)
            raise
        if windows_job is not None:
            if not _windows_close_handle(windows_job):
                raise EvaluationError("Cannot close the Codex process job cleanly")
        stdout_file.flush()
        stderr_file.flush()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")
    elapsed = time.perf_counter() - start
    terminal_event_count = 0
    failed_terminal_event_count = 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            terminal_event_count += 1
        if isinstance(event, dict) and event.get("type") in {
            "turn.failed",
            "turn.cancelled",
            "turn.interrupted",
        }:
            failed_terminal_event_count += 1
    if timed_out:
        timeout_message = (
            f"Evaluation timed out after {timeout} seconds; "
            f"termination_method={termination_method}"
        )
        stderr = f"{stderr.rstrip()}\n{timeout_message}\n" if stderr else f"{timeout_message}\n"
        return CommandResult(
            124,
            elapsed,
            stdout,
            stderr,
            timed_out=True,
            timeout_seconds=timeout,
            termination_method=termination_method,
            termination_reason="timeout",
            timeout_overrun_seconds=max(0.0, elapsed - timeout),
            terminal_event_count=terminal_event_count,
            failed_terminal_event_count=failed_terminal_event_count,
            timeout_enforcement=CODEX_TIMEOUT_ENFORCEMENT_MODE,
        )
    return CommandResult(
        int(process.returncode or 0),
        elapsed,
        stdout,
        stderr,
        timed_out=False,
        timeout_seconds=timeout,
        termination_method=termination_method,
        termination_reason="process-exit",
        timeout_overrun_seconds=0.0,
        terminal_event_count=terminal_event_count,
        failed_terminal_event_count=failed_terminal_event_count,
        timeout_enforcement=CODEX_TIMEOUT_ENFORCEMENT_MODE,
    )


def token_usage_from_jsonl(text: str) -> dict[str, int | None]:
    """Best-effort extraction across Codex JSONL event versions."""
    best: dict[str, int | None] = {"input_tokens": None, "output_tokens": None, "total_tokens": None}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            aliases = {
                "input_tokens": ("input_tokens", "prompt_tokens"),
                "output_tokens": ("output_tokens", "completion_tokens"),
                "total_tokens": ("total_tokens",),
            }
            for target, keys in aliases.items():
                for key in keys:
                    candidate = value.get(key)
                    if isinstance(candidate, int) and (best[target] is None or candidate > best[target]):
                        best[target] = candidate
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for line in text.splitlines():
        try:
            visit(json.loads(line))
        except json.JSONDecodeError:
            continue
    if best["total_tokens"] is None and best["input_tokens"] is not None and best["output_tokens"] is not None:
        best["total_tokens"] = int(best["input_tokens"]) + int(best["output_tokens"])
    return best


def safe_copy_fixture(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise EvaluationError(f"Fixture directory does not exist: {source}")
    if destination.exists():
        raise EvaluationError(f"Refusing to overwrite existing workspace: {destination}")
    shutil.copytree(source, destination)


def median(values: Iterable[float | int]) -> float | None:
    items = [float(value) for value in values]
    return statistics.median(items) if items else None


def summary_stats(values: Iterable[float | int]) -> dict[str, float | int | None]:
    items = [float(value) for value in values]
    if not items:
        return {"count": 0, "mean": None, "median": None, "stddev": None, "min": None, "max": None}
    return {
        "count": len(items),
        "mean": statistics.mean(items),
        "median": statistics.median(items),
        "stddev": statistics.pstdev(items),
        "min": min(items),
        "max": max(items),
    }


def compare(operator: str, actual: float | int, expected: float | int) -> bool:
    operations = {
        ">=": lambda: actual >= expected,
        ">": lambda: actual > expected,
        "==": lambda: actual == expected,
        "<=": lambda: actual <= expected,
        "<": lambda: actual < expected,
    }
    if operator not in operations:
        raise EvaluationError(f"Unsupported threshold operator: {operator}")
    return bool(operations[operator]())
