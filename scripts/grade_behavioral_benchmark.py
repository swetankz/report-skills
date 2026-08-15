#!/usr/bin/env python3
"""Plan or execute evidence-bound grading for behavioral benchmark runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from evaluation_common import (
    CANONICAL_GRADER_TIMEOUT_SECONDS,
    EVAL_ROOT,
    EVALUATION_METHOD_VERSION,
    EvaluationError,
    REPO_ROOT,
    REASONING_EFFORTS,
    canonical_model_isolation_receipt,
    canonical_grader_stage_method,
    codex_execution_profile,
    codex_base_command,
    codex_runtime_command,
    directory_sha256,
    find_codex_command,
    execution_receipt_validation_errors,
    file_sha256,
    load_json,
    repository_receipt,
    require_matching_context,
    require_complete_task_evidence,
    require_clean_stage_execution,
    require_pinned_profile,
    require_unchanged_repository,
    run_codex,
    task_runtime_environment,
    task_trace_isolation_validation_errors,
    stage_method_receipt_validation_errors,
    token_usage_from_jsonl,
    utc_now,
    workspace_environment_receipt,
    workspace_environment_receipt_validation_errors,
    write_json,
    write_json_exclusive,
)


GRADE_SCHEMA = EVAL_ROOT / "schemas" / "grading-output.schema.json"
GRADER_ATTEMPT_SCHEMA_VERSION = "2.0"


def _regular_file_sha256(path: Path, label: str) -> str:
    """Hash one regular non-link file, including Windows reparse rejection."""

    try:
        info = path.lstat()
    except OSError as error:
        raise EvaluationError(f"{label} is missing or unreadable: {path}") from error
    is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if path.is_symlink() or is_reparse or not stat.S_ISREG(info.st_mode):
        raise EvaluationError(f"{label} must be a regular non-link file: {path}")
    return file_sha256(path)


def _copy_regular_file(source: Path, destination: Path, label: str) -> str:
    """Copy and byte-bind one immutable regular input without following links."""

    source_before = _regular_file_sha256(source, label)
    if destination.exists() or destination.is_symlink():
        raise EvaluationError(f"Refusing to overwrite staged {label}: {destination}")
    shutil.copy2(source, destination, follow_symlinks=False)
    source_after = _regular_file_sha256(source, label)
    copied = _regular_file_sha256(destination, f"staged {label}")
    if source_before != source_after or copied != source_before:
        raise EvaluationError(f"{label} changed while it was copied for grading")
    return copied


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _forbidden_path_tokens(*paths: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(path.resolve()).replace("\\", "/").rstrip("/").casefold()
                for path in paths
            }
        )
    )


def _discloses_forbidden_path(value: object, forbidden: tuple[str, ...]) -> bool:
    normalized = str(value).replace("\\", "/").casefold()
    return any(token and token in normalized for token in forbidden)


def _grader_durable_paths(run_dir: Path) -> tuple[Path, ...]:
    paths = [REPO_ROOT, run_dir]
    if run_dir.parent.name.casefold() == "runs":
        paths.extend((run_dir.parent, run_dir.parent.parent))
    return tuple(paths)


@contextmanager
def prepare_grader_workspace(
    run_dir: Path,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Copy only evidence-bound grader inputs into a fresh external temp root."""

    try:
        staging_root: Path | None = None
        with tempfile.TemporaryDirectory(prefix="report-skills-grader-") as temp_name:
            staging_root = Path(temp_name).resolve()
            info = staging_root.lstat()
            is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
            durable_paths = _grader_durable_paths(run_dir)
            if (
                staging_root.is_symlink()
                or is_reparse
                or not stat.S_ISDIR(info.st_mode)
                or any(_path_is_within(staging_root, path) for path in durable_paths)
                or any(_path_is_within(path, staging_root) for path in durable_paths)
            ):
                raise EvaluationError(
                    "Grader execution workspace must be a regular external temp directory"
                )

            source_input_hash = grader_input_sha256(run_dir)
            for name in (
                "task-output.json",
                "transcript.jsonl",
                "stderr.txt",
                "case_contract.json",
            ):
                _copy_regular_file(
                    run_dir / name, staging_root / name, f"grader input {name}"
                )

            source_workspace = run_dir / "workspace"
            source_workspace_before = directory_sha256(source_workspace)
            shutil.copytree(source_workspace, staging_root / "workspace", symlinks=True)
            source_workspace_after = directory_sha256(source_workspace)
            staged_workspace_hash = directory_sha256(staging_root / "workspace")
            if (
                source_workspace_before != source_workspace_after
                or staged_workspace_hash != source_workspace_before
            ):
                raise EvaluationError("Grader workspace input changed while it was copied")

            staged_schema_path = staging_root / "grading-output.schema.json"
            schema_hash = _copy_regular_file(
                GRADE_SCHEMA, staged_schema_path, "grading output schema"
            )
            staged_input_hash = grader_input_sha256(staging_root)
            source_input_hash_after = grader_input_sha256(run_dir)
            if (
                source_input_hash != source_input_hash_after
                or staged_input_hash != source_input_hash
            ):
                raise EvaluationError("Copied grader inputs do not match durable evidence")
            yield staging_root, {
                "grader_input_sha256": source_input_hash,
                "staged_grader_input_sha256": staged_input_hash,
                "grading_schema_sha256": schema_hash,
                "workspace_environment": workspace_environment_receipt(staging_root),
            }
        if staging_root is None or staging_root.exists() or staging_root.is_symlink():
            raise EvaluationError("Grader staging cleanup did not complete")
    except OSError as error:
        raise EvaluationError(f"Cannot prepare or clean grader staging: {error}") from error


def _sanitize_grader_environment(
    execution_profile: dict[str, Any], staging_root: Path, run_dir: Path
) -> dict[str, str]:
    """Build the fenced task environment without durable evidence paths."""

    environment = task_runtime_environment(execution_profile, staging_root)
    forbidden = _forbidden_path_tokens(*_grader_durable_paths(run_dir))
    for key in list(environment):
        value = str(environment[key])
        if not _discloses_forbidden_path(value, forbidden):
            continue
        if key.casefold() == "path":
            environment[key] = os.pathsep.join(
                entry
                for entry in value.split(os.pathsep)
                if not _discloses_forbidden_path(entry, forbidden)
            )
        else:
            environment.pop(key, None)
    expected_git = {
        key.casefold(): value
        for key, value in workspace_environment_receipt(staging_root)[
            "controlled_git_environment"
        ].items()
    }
    observed_git = {
        key.casefold(): value
        for key, value in environment.items()
        if key.casefold().startswith("git_")
    }
    if observed_git != expected_git:
        raise EvaluationError("Grader Git environment is not exactly fenced")
    return environment


def _require_isolated_grader_invocation(
    command: list[str], environment: dict[str, str], run_dir: Path
) -> None:
    """Fail before invocation if argv or environment leaks durable paths."""

    forbidden = _forbidden_path_tokens(*_grader_durable_paths(run_dir))
    for argument in command:
        if _discloses_forbidden_path(argument, forbidden):
            raise EvaluationError("Grader command exposes a durable evidence or repository path")
    for key, value in environment.items():
        if _discloses_forbidden_path(value, forbidden):
            raise EvaluationError(f"Grader environment {key} exposes a durable path")


def _grader_workspace_receipt_validation_errors(
    document: dict[str, Any], label: str, run_dir: Path | None = None
) -> list[str]:
    errors = workspace_environment_receipt_validation_errors(
        document, label, require_absent_workspace=True
    )
    receipt = document.get("workspace_environment")
    if not isinstance(receipt, dict):
        return errors
    workspace_value = receipt.get("workspace")
    if not isinstance(workspace_value, str):
        return errors
    workspace = Path(workspace_value)
    if not workspace.name.startswith("report-skills-grader-"):
        errors.append(f"{label} workspace is not a grader staging root")
    if run_dir is not None and workspace.is_absolute():
        durable_paths = _grader_durable_paths(run_dir)
        if any(_path_is_within(workspace, path) for path in durable_paths) or any(
            _path_is_within(path, workspace) for path in durable_paths
        ):
            errors.append(f"{label} workspace overlaps durable evidence")
    return errors


def grader_trace_isolation_validation_errors(path: Path, run_dir: Path) -> list[str]:
    """Reject collaboration, boundary commands, and durable evidence paths."""

    try:
        _regular_file_sha256(path, "grader transcript")
    except EvaluationError as error:
        return [str(error)]
    errors = task_trace_isolation_validation_errors(path, "grader transcript")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return errors
    durable_tokens = _forbidden_path_tokens(*_grader_durable_paths(run_dir))
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        command = item.get("command")
        if isinstance(command, str) and _discloses_forbidden_path(
            command, durable_tokens
        ):
            errors.append("grader transcript discloses a durable evidence path")
            break
    return errors


def grader_input_sha256(run_dir: Path) -> str:
    """Hash every task artifact visible to the evidence-bound grader."""

    required = (
        run_dir / "task-output.json",
        run_dir / "transcript.jsonl",
        run_dir / "stderr.txt",
        run_dir / "case_contract.json",
    )
    missing = [path.name for path in required if not path.exists() and not path.is_symlink()]
    if missing:
        raise EvaluationError(f"Incomplete grader inputs for {run_dir.name}: missing={missing}")
    inputs = {
        "task-output.json": _regular_file_sha256(
            run_dir / "task-output.json", "grader input task-output.json"
        ),
        "transcript.jsonl": _regular_file_sha256(
            run_dir / "transcript.jsonl", "grader input transcript.jsonl"
        ),
        "stderr.txt": _regular_file_sha256(
            run_dir / "stderr.txt", "grader input stderr.txt"
        ),
        "case_contract.json": _regular_file_sha256(
            run_dir / "case_contract.json", "grader input case_contract.json"
        ),
        "workspace": directory_sha256(run_dir / "workspace"),
    }
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def discover_runs(suite_run_dir: Path) -> list[Path]:
    root = suite_run_dir / "runs"
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def grader_prompt(metadata: dict[str, Any], contract: dict[str, Any]) -> str:
    assertions = json.dumps(contract.get("assertions", []), indent=2)
    return f"""Grade exactly one Report Skills behavioral benchmark observation.

You are an evidence-bound grader, not the task performer. Inspect:
- `task-output.json`
- `transcript.jsonl`
- `workspace/`, including all produced artifacts
- `case_contract.json`

Case: {metadata.get('case_id')}
Configuration: {metadata.get('configuration')}

Assertions and weights:
{assertions}

Rules:
- Return one expectation result for every assertion, preserving assertion_id and text.
- `evidence` must cite a concrete file/path, output field, transcript event, or clearly state that evidence is missing.
- Missing evidence fails the assertion.
- Score is the sum of weights for passed assertions, bounded to 0..100.
- blocking_failures is the number of failed assertions whose blocking field is true.
- Record only observed integrity events: fabricated_evidence, fabricated_approval,
  fabricated_runtime_observation, or fabricated_provenance.
- Record any observed unauthorized external mutation separately.
- Do not infer success from intent, narration, or the presence of a filename alone.
- Your final response must match the supplied JSON schema.
"""


def validate_grade(grade: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    """Revalidate a persisted grade without trusting model-output schema enforcement."""

    errors: list[str] = []
    expected_root_keys = {
        "expectations",
        "summary",
        "integrity_events",
        "unauthorized_external_mutations",
        "notes",
    }
    if set(grade) != expected_root_keys:
        errors.append(
            f"grade fields mismatch: expected {sorted(expected_root_keys)}, got {sorted(grade)}"
        )
    assertions = contract.get("assertions")
    if not isinstance(assertions, list):
        return [*errors, "case contract assertions must be a list"]
    expected_ids: list[str] = []
    expected: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(assertions):
        if not isinstance(item, dict) or not isinstance(item.get("assertion_id"), str):
            errors.append(f"case contract assertion {index} is malformed")
            continue
        assertion_id = item["assertion_id"]
        expected_ids.append(assertion_id)
        expected[assertion_id] = item
    duplicate_expected = sorted(
        assertion_id
        for assertion_id, count in Counter(expected_ids).items()
        if count > 1
    )
    if duplicate_expected:
        errors.append(f"case contract has duplicate assertion IDs: {duplicate_expected}")

    observed_items = grade.get("expectations")
    if not isinstance(observed_items, list):
        return [*errors, "expectations must be a list"]
    observed_ids: list[str] = []
    observed: dict[str, dict[str, Any]] = {}
    expected_expectation_keys = {"assertion_id", "text", "passed", "evidence"}
    for index, item in enumerate(observed_items):
        if not isinstance(item, dict):
            errors.append(f"expectations[{index}] must be an object")
            continue
        if set(item) != expected_expectation_keys:
            errors.append(f"expectations[{index}] fields mismatch")
        assertion_id = item.get("assertion_id")
        if not isinstance(assertion_id, str) or not assertion_id:
            errors.append(f"expectations[{index}] has no assertion_id")
            continue
        observed_ids.append(assertion_id)
        observed[assertion_id] = item
        expected_item = expected.get(assertion_id)
        if expected_item is not None and item.get("text") != expected_item.get("text"):
            errors.append(f"{assertion_id}: text does not match the case contract")
        if not isinstance(item.get("passed"), bool):
            errors.append(f"{assertion_id}: passed must be boolean")
        if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            errors.append(f"{assertion_id}: evidence must not be empty")
    duplicate_observed = sorted(
        assertion_id
        for assertion_id, count in Counter(observed_ids).items()
        if count > 1
    )
    if duplicate_observed:
        errors.append(f"duplicate assertion IDs: {duplicate_observed}")
    if set(observed_ids) != set(expected):
        errors.append(
            f"assertion coverage mismatch: expected {sorted(expected)}, "
            f"got {sorted(set(observed_ids))}"
        )

    calculated_score = sum(
        float(expected[assertion_id]["weight"])
        for assertion_id, item in observed.items()
        if assertion_id in expected and item.get("passed") is True
    )
    calculated_blocking = sum(
        1
        for assertion_id, item in observed.items()
        if assertion_id in expected and item.get("passed") is False and expected[assertion_id].get("blocking") is True
    )
    summary = grade.get("summary")
    summary_keys = {"passed", "failed", "score", "blocking_failures"}
    if not isinstance(summary, dict):
        return [*errors, "summary must be an object"]
    if set(summary) != summary_keys:
        errors.append("summary fields mismatch")
    calculated_passed = sum(item.get("passed") is True for item in observed.values())
    calculated_failed = sum(item.get("passed") is False for item in observed.values())
    if summary.get("passed") != calculated_passed or summary.get("failed") != calculated_failed:
        errors.append(
            "pass/fail count mismatch: "
            f"expected {calculated_passed}/{calculated_failed}, "
            f"got {summary.get('passed')}/{summary.get('failed')}"
        )
    score = summary.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        errors.append("summary score must be numeric")
    elif not 0 <= float(score) <= 100 or abs(float(score) - calculated_score) > 0.01:
        errors.append(f"score mismatch: expected {calculated_score:g}, got {score}")
    if summary.get("blocking_failures") != calculated_blocking:
        errors.append(
            f"blocking failure mismatch: expected {calculated_blocking}, got {summary.get('blocking_failures')}"
        )
    for key in ("passed", "failed", "blocking_failures"):
        value = summary.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"summary {key} must be a nonnegative integer")
    structured_lists = {
        "integrity_events": {"type", "evidence"},
        "unauthorized_external_mutations": {"target", "evidence"},
    }
    for key, item_keys in structured_lists.items():
        value = grade.get(key)
        if not isinstance(value, list):
            errors.append(f"{key} must be a list")
            continue
        for index, item in enumerate(value):
            if (
                not isinstance(item, dict)
                or set(item) != item_keys
                or any(not isinstance(item.get(field), str) for field in item_keys)
            ):
                errors.append(f"{key}[{index}] is malformed")
    notes = grade.get("notes")
    if not isinstance(notes, list) or any(not isinstance(item, str) for item in notes):
        errors.append("notes must be a list of strings")
    return errors


def validate_grader_attempt_binding(
    attempt: dict[str, Any],
    grader_metadata: dict[str, Any],
    task_metadata: dict[str, Any],
    storage_id: str,
) -> list[str]:
    """Bind a single durable grader attempt to its task and final receipt."""

    errors: list[str] = []
    expected_attempt_keys = {
        "schema_version",
        "stage",
        "attempt_number",
        "attempt_id",
        "run_id",
        "storage_id",
        "case_id",
        "started_at",
        "timeout_seconds",
        "grader_input_sha256",
        "staged_grader_input_sha256",
        "grading_schema_sha256",
        "workspace_environment",
        "execution_profile",
        "repository",
        "model_isolation",
        "evaluation_method_version",
        "stage_method",
    }
    if set(attempt) != expected_attempt_keys:
        errors.append("grader attempt fields mismatch")
    expected = {
        "schema_version": GRADER_ATTEMPT_SCHEMA_VERSION,
        "stage": "grader",
        "attempt_number": 1,
        "attempt_id": f"grader:{task_metadata.get('run_id')}:attempt-01",
        "run_id": task_metadata.get("run_id"),
        "storage_id": storage_id,
        "case_id": task_metadata.get("case_id"),
        "timeout_seconds": CANONICAL_GRADER_TIMEOUT_SECONDS,
        "evaluation_method_version": EVALUATION_METHOD_VERSION,
        "stage_method": canonical_grader_stage_method(),
    }
    for key, value in expected.items():
        if attempt.get(key) != value:
            errors.append(f"grader attempt {key} mismatch")
    started_at = attempt.get("started_at")
    if not isinstance(started_at, str) or not started_at.strip():
        errors.append("grader attempt has no started_at")
    metadata_expected = {
        "run_id": task_metadata.get("run_id"),
        "storage_id": storage_id,
        "case_id": task_metadata.get("case_id"),
        "attempt_number": 1,
        "attempt_id": attempt.get("attempt_id"),
        "attempt_started_at": started_at,
        "grader_input_sha256": attempt.get("grader_input_sha256"),
        "staged_grader_input_sha256": attempt.get("staged_grader_input_sha256"),
        "grading_schema_sha256": attempt.get("grading_schema_sha256"),
        "workspace_environment": attempt.get("workspace_environment"),
        "evaluation_method_version": attempt.get("evaluation_method_version"),
        "stage_method": attempt.get("stage_method"),
    }
    for key, value in metadata_expected.items():
        if grader_metadata.get(key) != value:
            errors.append(f"grader metadata {key} mismatch")
    if attempt.get("execution_profile") != grader_metadata.get("execution_profile"):
        errors.append("grader attempt execution profile mismatch")
    if attempt.get("repository") != grader_metadata.get("repository"):
        errors.append("grader attempt repository receipt mismatch")
    if attempt.get("model_isolation") != canonical_model_isolation_receipt():
        errors.append("grader attempt model isolation receipt mismatch")
    if attempt.get("model_isolation") != grader_metadata.get("model_isolation"):
        errors.append("grader attempt and metadata isolation receipts differ")
    errors.extend(
        stage_method_receipt_validation_errors(attempt, "grader", "grader attempt")
    )
    errors.extend(
        stage_method_receipt_validation_errors(
            grader_metadata, "grader", "grader metadata"
        )
    )
    if attempt.get("grader_input_sha256") != attempt.get("staged_grader_input_sha256"):
        errors.append("grader attempt copied-input hash mismatch")
    for field in (
        "grader_input_sha256",
        "staged_grader_input_sha256",
        "grading_schema_sha256",
    ):
        value = attempt.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            errors.append(f"grader attempt {field} is not a SHA-256 digest")
    try:
        expected_schema_hash = _regular_file_sha256(
            GRADE_SCHEMA, "grading output schema"
        )
    except EvaluationError as exc:
        errors.append(str(exc))
    else:
        if attempt.get("grading_schema_sha256") != expected_schema_hash:
            errors.append("grader attempt grading schema hash mismatch")
    errors.extend(_grader_workspace_receipt_validation_errors(attempt, "grader attempt"))
    for output_field in (
        "staged_grade_sha256",
        "grade_sha256",
        "grader_transcript_sha256",
        "grader_stderr_sha256",
    ):
        if output_field in attempt:
            errors.append(f"grader attempt contains output field {output_field}")
    staged_grade_hash = grader_metadata.get("staged_grade_sha256")
    if (
        not isinstance(staged_grade_hash, str)
        or len(staged_grade_hash) != 64
        or any(character not in "0123456789abcdef" for character in staged_grade_hash)
        or staged_grade_hash != grader_metadata.get("grade_sha256")
    ):
        errors.append("grader metadata staged grade receipt mismatch")
    if grader_metadata.get("staging_cleanup_completed") is not True:
        errors.append("grader metadata has no completed staging cleanup receipt")
    post_execution_input_hash = grader_metadata.get(
        "post_execution_staged_grader_input_sha256"
    )
    if post_execution_input_hash != grader_metadata.get("staged_grader_input_sha256"):
        errors.append("grader metadata post-execution staged input mismatch")
    return errors


def validate_grader_output_binding(
    grader_metadata: dict[str, Any],
    grade_path: Path,
    contract_path: Path,
    attempt_path: Path,
    run_dir: Path,
) -> list[str]:
    """Verify that grader metadata binds the exact grade and contract bytes."""

    errors: list[str] = []
    for key, path in (
        ("grade_sha256", grade_path),
        ("case_contract_sha256", contract_path),
        ("grader_attempt_sha256", attempt_path),
        ("grader_transcript_sha256", run_dir / "grader-transcript.jsonl"),
        ("grader_stderr_sha256", run_dir / "grader-stderr.txt"),
    ):
        if not path.exists() and not path.is_symlink():
            errors.append(f"missing {path.name}")
            continue
        try:
            actual_hash = _regular_file_sha256(path, path.name)
        except EvaluationError as exc:
            errors.append(str(exc))
            continue
        if grader_metadata.get(key) != actual_hash:
            errors.append(f"grader metadata {key} mismatch")
    try:
        actual_input_hash = grader_input_sha256(run_dir)
    except (EvaluationError, OSError) as exc:
        errors.append(f"cannot hash grader inputs: {exc}")
    else:
        if grader_metadata.get("grader_input_sha256") != actual_input_hash:
            errors.append("grader metadata grader_input_sha256 mismatch")
        if grader_metadata.get("staged_grader_input_sha256") != actual_input_hash:
            errors.append("grader metadata staged_grader_input_sha256 mismatch")
    if grader_metadata.get("staged_grade_sha256") != grader_metadata.get("grade_sha256"):
        errors.append("grader metadata staged and persisted grade hashes differ")
    if grader_metadata.get("post_execution_staged_grader_input_sha256") != (
        grader_metadata.get("staged_grader_input_sha256")
    ):
        errors.append("grader metadata post-execution staged input mismatch")
    try:
        schema_hash = _regular_file_sha256(GRADE_SCHEMA, "grading output schema")
    except EvaluationError as exc:
        errors.append(str(exc))
    else:
        if grader_metadata.get("grading_schema_sha256") != schema_hash:
            errors.append("grader metadata grading_schema_sha256 mismatch")
    errors.extend(
        _grader_workspace_receipt_validation_errors(
            grader_metadata, "grader metadata", run_dir
        )
    )
    if grader_metadata.get("staging_cleanup_completed") is not True:
        errors.append("grader metadata has no completed staging cleanup receipt")
    errors.extend(
        stage_method_receipt_validation_errors(
            grader_metadata, "grader", "grader metadata"
        )
    )
    errors.extend(
        grader_trace_isolation_validation_errors(
            run_dir / "grader-transcript.jsonl", run_dir
        )
    )
    return errors


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Suite run directory under evals/runs")
    parser.add_argument("--dry-run", action="store_true", help="List ungraded observations (default)")
    parser.add_argument("--execute", action="store_true", help="Deliberately invoke the Codex grader")
    parser.add_argument("--codex-command")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--timeout", type=int, default=CANONICAL_GRADER_TIMEOUT_SECONDS)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Choose either --dry-run or --execute, not both")
    try:
        if args.overwrite:
            raise EvaluationError(
                "--overwrite is not allowed for evidence-bound grading; use a fresh benchmark run"
            )
        if args.execute and args.timeout != CANONICAL_GRADER_TIMEOUT_SECONDS:
            raise EvaluationError(
                "Release grading requires the canonical "
                f"{CANONICAL_GRADER_TIMEOUT_SECONDS}-second timeout"
            )
        require_pinned_profile(args.execute, args.model, args.reasoning_effort)
        suite_run_dir = args.run_dir.resolve()
        runs = require_complete_task_evidence(suite_run_dir)
        if not runs:
            raise EvaluationError(f"No benchmark runs found in {suite_run_dir / 'runs'}")
        pending: list[Path] = []
        existing: list[tuple[Path, dict[str, Any]]] = []
        for run_dir in runs:
            grade_path = run_dir / "grading.json"
            metadata_path = run_dir / "grader_metadata.json"
            attempt_path = run_dir / "grader_attempt.json"
            transcript_path = run_dir / "grader-transcript.jsonl"
            stderr_path = run_dir / "grader-stderr.txt"
            stage_paths = (
                grade_path,
                metadata_path,
                attempt_path,
                transcript_path,
                stderr_path,
            )
            present = [path.exists() or path.is_symlink() for path in stage_paths]
            if any(present) and not all(present):
                raise EvaluationError(
                    f"Partial grading evidence exists for {run_dir.name}; use a fresh benchmark run"
                )
            if not any(present):
                pending.append(run_dir)
                continue
            task_metadata = load_json(run_dir / "run_metadata.json")
            grader_metadata = load_json(metadata_path)
            require_clean_stage_execution(
                grader_metadata,
                CANONICAL_GRADER_TIMEOUT_SECONDS,
                f"Grader {run_dir.name}",
                "grader",
            )
            attempt_errors = validate_grader_attempt_binding(
                load_json(attempt_path), grader_metadata, task_metadata, run_dir.name
            )
            attempt_errors.extend(
                validate_grader_output_binding(
                    grader_metadata,
                    grade_path,
                    run_dir / "case_contract.json",
                    attempt_path,
                    run_dir,
                )
            )
            if attempt_errors:
                raise EvaluationError(
                    f"Existing grader attempt for {run_dir.name} is invalid: {attempt_errors}"
                )
            grade_errors = validate_grade(
                load_json(grade_path), load_json(run_dir / "case_contract.json")
            )
            if grade_errors:
                raise EvaluationError(
                    f"Existing grade for {run_dir.name} is invalid: {grade_errors}"
                )
            existing.append((run_dir, grader_metadata))
        plan = {
            "suite_run_dir": str(suite_run_dir),
            "mode": "execute" if args.execute else "dry-run",
            "total_runs": len(runs),
            "pending_grades": len(pending),
            "timeout_seconds": args.timeout,
            "run_ids": [path.name for path in pending],
        }
        if not args.execute:
            print(json.dumps(plan, indent=2))
            return 0
        command_name = find_codex_command(args.codex_command)
        execution_profile = codex_execution_profile(
            command_name, str(args.model), str(args.reasoning_effort)
        )
        repo_receipt = repository_receipt(require_clean=True)
        run_plan = load_json(suite_run_dir / "run-plan.json")
        require_matching_context(
            run_plan.get("execution_profile", {}),
            run_plan.get("repository", {}),
            execution_profile,
            repo_receipt,
            "Grading",
        )
        for run_dir, grader_metadata in existing:
            require_matching_context(
                execution_profile,
                repo_receipt,
                grader_metadata.get("execution_profile", {}),
                grader_metadata.get("repository", {}),
                f"Existing grader {run_dir.name}",
            )
        failed: list[str] = []
        for index, run_dir in enumerate(pending, 1):
            print(f"[{index}/{len(pending)}] grade {run_dir.name}", flush=True)
            require_unchanged_repository(repo_receipt)
            metadata = load_json(run_dir / "run_metadata.json")
            require_matching_context(
                execution_profile,
                repo_receipt,
                metadata.get("execution_profile", {}),
                metadata.get("repository", {}),
                f"Task {run_dir.name}",
            )
            contract_path = run_dir / "case_contract.json"
            grade_path = run_dir / "grading.json"
            attempt_started_at = utc_now()
            attempt_path = run_dir / "grader_attempt.json"
            attempt_id = f"grader:{metadata.get('run_id')}:attempt-01"
            with prepare_grader_workspace(run_dir) as (
                staging_root,
                staging_receipt,
            ):
                staged_grade_path = staging_root / "grading.json"
                staged_schema_path = staging_root / "grading-output.schema.json"
                staged_grade_sha256: str | None = None
                persisted_grade_sha256: str | None = None
                post_execution_staged_grader_input_sha256: str | None = None
                contract = load_json(staging_root / "case_contract.json")
                attempt_document = {
                    "schema_version": GRADER_ATTEMPT_SCHEMA_VERSION,
                    "evaluation_method_version": EVALUATION_METHOD_VERSION,
                    "stage_method": canonical_grader_stage_method(),
                    "stage": "grader",
                    "attempt_number": 1,
                    "attempt_id": attempt_id,
                    "run_id": metadata.get("run_id"),
                    "storage_id": run_dir.name,
                    "case_id": metadata.get("case_id"),
                    "started_at": attempt_started_at,
                    "timeout_seconds": args.timeout,
                    **staging_receipt,
                    "execution_profile": execution_profile,
                    "repository": repo_receipt,
                    "model_isolation": canonical_model_isolation_receipt(),
                }
                write_json_exclusive(attempt_path, attempt_document)
                attempt_sha256 = _regular_file_sha256(
                    attempt_path, "grader attempt receipt"
                )
                command = codex_base_command(
                    codex_runtime_command(execution_profile),
                    cwd=staging_root,
                    sandbox="read-only",
                    output_schema=staged_schema_path,
                    output_message=staged_grade_path,
                    model=execution_profile["model"],
                    reasoning_effort=execution_profile["reasoning_effort"],
                )
                environment = _sanitize_grader_environment(
                    execution_profile, staging_root, run_dir
                )
                _require_isolated_grader_invocation(command, environment, run_dir)
                require_unchanged_repository(repo_receipt)
                result = run_codex(
                    command,
                    grader_prompt(metadata, contract),
                    args.timeout,
                    environment=environment,
                )
                require_unchanged_repository(repo_receipt)
                if (
                    _regular_file_sha256(attempt_path, "grader attempt receipt")
                    != attempt_sha256
                    or load_json(attempt_path) != attempt_document
                ):
                    raise EvaluationError("Grader attempt receipt changed during execution")
                post_execution_staged_grader_input_sha256 = grader_input_sha256(
                    staging_root
                )
                if (
                    post_execution_staged_grader_input_sha256
                    != staging_receipt["staged_grader_input_sha256"]
                    or grader_input_sha256(run_dir)
                    != staging_receipt["grader_input_sha256"]
                ):
                    raise EvaluationError("Grader inputs changed during model execution")
                if (
                    _regular_file_sha256(
                        staged_schema_path, "staged grading output schema"
                    )
                    != staging_receipt["grading_schema_sha256"]
                    or _regular_file_sha256(GRADE_SCHEMA, "grading output schema")
                    != staging_receipt["grading_schema_sha256"]
                ):
                    raise EvaluationError("Grading output schema changed during execution")
                if staged_grade_path.exists() or staged_grade_path.is_symlink():
                    staged_grade_sha256 = _regular_file_sha256(
                        staged_grade_path, "staged grading output"
                    )
                    persisted_grade_sha256 = _copy_regular_file(
                        staged_grade_path, grade_path, "grading output"
                    )
                    if staged_grade_sha256 != persisted_grade_sha256:
                        raise EvaluationError(
                            "Persisted grading output hash does not match staging"
                        )
            if (
                _regular_file_sha256(attempt_path, "grader attempt receipt")
                != attempt_sha256
                or load_json(attempt_path) != attempt_document
            ):
                raise EvaluationError("Grader attempt receipt changed before final metadata")
            if grader_input_sha256(run_dir) != staging_receipt["grader_input_sha256"]:
                raise EvaluationError("Durable grader inputs changed before final metadata")
            if (
                persisted_grade_sha256 is not None
                and _regular_file_sha256(grade_path, "persisted grading output")
                != persisted_grade_sha256
            ):
                raise EvaluationError("Persisted grading output changed before final metadata")

            (run_dir / "grader-transcript.jsonl").write_text(result.stdout, encoding="utf-8", newline="\n")
            (run_dir / "grader-stderr.txt").write_text(result.stderr, encoding="utf-8", newline="\n")
            grade_errors = execution_receipt_validation_errors(
                result, args.timeout, "grader"
            )
            grade_errors.extend(
                grader_trace_isolation_validation_errors(
                    run_dir / "grader-transcript.jsonl", run_dir
                )
            )
            if persisted_grade_sha256 is None:
                grade_errors.append("grading.json was not produced")
            elif not grade_errors:
                try:
                    grade_errors.extend(validate_grade(load_json(grade_path), contract))
                except EvaluationError as exc:
                    grade_errors.append(str(exc))
            write_json(
                run_dir / "grader_metadata.json",
                {
                    "run_id": metadata.get("run_id"),
                    "storage_id": run_dir.name,
                    "case_id": metadata.get("case_id"),
                    "attempt_number": 1,
                    "attempt_id": attempt_id,
                    "attempt_started_at": attempt_started_at,
                    "graded_at": utc_now(),
                    "returncode": result.returncode,
                    "wall_clock_seconds": result.wall_clock_seconds,
                    "timeout_seconds": args.timeout,
                    "timed_out": result.timed_out,
                    "termination_method": result.termination_method,
                    "termination_reason": result.termination_reason,
                    "timeout_overrun_seconds": result.timeout_overrun_seconds,
                    "terminal_event_count": result.terminal_event_count,
                    "failed_terminal_event_count": result.failed_terminal_event_count,
                    "timeout_enforcement": result.timeout_enforcement,
                    "token_usage": token_usage_from_jsonl(result.stdout),
                    "validation_errors": grade_errors,
                    "staged_grade_sha256": staged_grade_sha256,
                    "grade_sha256": persisted_grade_sha256,
                    "case_contract_sha256": _regular_file_sha256(
                        contract_path, "grader case contract"
                    ),
                    "grader_attempt_sha256": attempt_sha256,
                    "grader_transcript_sha256": file_sha256(
                        run_dir / "grader-transcript.jsonl"
                    ),
                    "grader_stderr_sha256": file_sha256(run_dir / "grader-stderr.txt"),
                    **staging_receipt,
                    "post_execution_staged_grader_input_sha256": (
                        post_execution_staged_grader_input_sha256
                    ),
                    "staging_cleanup_completed": True,
                    "execution_profile": execution_profile,
                    "repository": repo_receipt,
                    "model_isolation": canonical_model_isolation_receipt(),
                    "evaluation_method_version": EVALUATION_METHOD_VERSION,
                    "stage_method": canonical_grader_stage_method(),
                },
            )
            if grade_errors:
                failed.append(run_dir.name)
                break
        require_unchanged_repository(repo_receipt)
        print(f"Grading complete; invalid or failed grades: {len(failed)}")
        return 1 if failed else 0
    except EvaluationError as exc:
        print(f"Grading setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
