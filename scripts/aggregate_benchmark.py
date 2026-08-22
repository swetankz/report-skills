#!/usr/bin/env python3
"""Aggregate grades, blind comparisons, and triggers into a release verdict."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation_common import (
    CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
    CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
    CANONICAL_GRADER_TIMEOUT_SECONDS,
    CANONICAL_TRIGGER_TIMEOUT_SECONDS,
    CODEX_INVOCATION_MODE,
    CODEX_TIMEOUT_ENFORCEMENT_MODE,
    DEFAULT_THRESHOLDS,
    DEFAULT_TRIGGERS,
    EVALUATION_METHOD_VERSION,
    EvaluationError,
    PROFILE_IDENTITY_KEYS,
    REPOSITORY_IDENTITY_KEYS,
    REPO_ROOT,
    TASK_IGNORE_USER_CONFIG_SCOPE,
    canonical_model_isolation_receipt,
    canonical_stage_methods,
    canonical_task_isolation_receipt,
    canonical_trigger_workspace_environment_method,
    canonical_json_sha256,
    compare,
    execution_receipt_validation_errors,
    file_sha256,
    tracked_directory_sha256,
    validate_task_evidence_binding,
    load_json,
    planned_task_workspace_input_hashes,
    repository_receipt,
    require_clean_stage_execution,
    require_clean_task_execution,
    require_matching_context,
    summary_stats,
    stage_method_receipt_validation_errors,
    task_trace_isolation_validation_errors,
    trigger_fail_fast_receipt_validation_errors,
    utc_now,
    workspace_environment_receipt_validation_errors,
    write_json,
)
from run_trigger_evals import (
    TRIGGER_SCHEMA,
    body_proven_activation,
    summarize,
    validate_trigger_prediction,
)
from grade_behavioral_benchmark import (
    validate_grade,
    validate_grader_attempt_binding,
    validate_grader_output_binding,
)
from run_blind_comparisons import (
    CANONICAL_BLIND_SEED,
    label_map,
    validate_comparison,
    validate_comparison_binding,
    validate_comparison_output_binding,
)
from validate_release_eval_plan import validate_release_eval_plan


def validate_execution_receipt(
    document: dict[str, Any],
    label: str,
    expected_timeout: int,
    stage: str,
    issues: list[str],
) -> None:
    """Require a clean, deadline-bound model-call receipt for release evidence."""

    issues.extend(execution_receipt_validation_errors(document, expected_timeout, label))
    profile = document.get("execution_profile")
    if (
        not isinstance(profile, dict)
        or profile.get("codex_invocation") != CODEX_INVOCATION_MODE
        or profile.get("codex_timeout_enforcement") != CODEX_TIMEOUT_ENFORCEMENT_MODE
    ):
        issues.append(f"{label}:timeout enforcement profile mismatch")
    if document.get("model_isolation") != canonical_model_isolation_receipt():
        issues.append(f"{label}:missing or unsupported model isolation receipt")
    issues.extend(stage_method_receipt_validation_errors(document, stage, label))


def validate_task_method_receipt(
    record: dict[str, Any], label: str, issues: list[str]
) -> None:
    """Require the exact release-eligible task isolation and diagnostic receipt."""

    if record.get("codex_isolation") != canonical_task_isolation_receipt():
        issues.append(f"{label}:missing or unsupported task isolation receipt")
    issues.extend(workspace_environment_receipt_validation_errors(record, label))

    expected_loading = (
        "explicit_workspace_copy" if record.get("configuration") == "with_skill" else "none"
    )
    if record.get("skill_loading") != expected_loading:
        issues.append(f"{label}:skill-loading receipt does not match configuration")
    if record.get("returncode") != 0 or record.get("validation_errors") != []:
        issues.append(f"{label}:failed or invalid task execution")
    for key in ("started_at", "completed_at"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            issues.append(f"{label}:missing {key}")
    validate_execution_receipt(
        record, label, CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS, "behavioral_task", issues
    )

    diagnostics = record.get("skill_loader_diagnostics")
    expected_diagnostic_keys = {
        "ignore_user_config_scope",
        "metadata_warning_count",
        "failed_skill_load_count",
    }
    if not isinstance(diagnostics, dict) or set(diagnostics) != expected_diagnostic_keys:
        issues.append(f"{label}:missing or malformed skill-loader diagnostics")
        return
    if diagnostics.get("ignore_user_config_scope") != TASK_IGNORE_USER_CONFIG_SCOPE:
        issues.append(f"{label}:skill-loader diagnostic scope mismatch")
    for key in ("metadata_warning_count", "failed_skill_load_count"):
        value = diagnostics.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            issues.append(f"{label}:invalid {key}")


def collect_runs(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    runs_root = run_dir / "runs"
    if not runs_root.is_dir():
        raise EvaluationError(f"No runs directory: {runs_root}")
    plan_path = run_dir / "run-plan.json"
    plan = load_json(plan_path) if plan_path.is_file() else {}
    planned_contract_hashes = plan.get("case_contract_hashes", {})
    for path in sorted(item for item in runs_root.iterdir() if item.is_dir()):
        metadata_path = path / "run_metadata.json"
        grade_path = path / "grading.json"
        contract_path = path / "case_contract.json"
        if not metadata_path.is_file():
            missing.append(f"{path.name}:run_metadata.json")
            continue
        metadata = load_json(metadata_path)
        try:
            expected_workspace_inputs = planned_task_workspace_input_hashes(
                plan, metadata
            )
        except EvaluationError as error:
            expected_workspace_inputs = None
            missing.append(f"{path.name}:invalid workspace-input plan: {error}")
        task_errors = validate_task_evidence_binding(
            metadata,
            path,
            planned_contract_hashes.get(str(metadata.get("run_id")))
            if isinstance(planned_contract_hashes, dict)
            else None,
            expected_workspace_inputs,
        )
        missing.extend(f"{path.name}:invalid task evidence: {error}" for error in task_errors)
        task_clean = not task_errors
        try:
            require_clean_task_execution(
                metadata,
                f"Task {path.name}",
                path,
                planned_contract_hashes.get(str(metadata.get("run_id")))
                if isinstance(planned_contract_hashes, dict)
                else None,
                expected_workspace_inputs,
            )
        except EvaluationError as exc:
            task_clean = False
            missing.append(f"{path.name}:invalid task execution: {exc}")
        if metadata.get("returncode") != 0:
            missing.append(f"{path.name}:successful task execution")
        if metadata.get("validation_errors"):
            missing.append(f"{path.name}:valid task output")
        contract = load_json(contract_path) if contract_path.is_file() else None
        if contract is None:
            missing.append(f"{path.name}:case_contract.json")
        if not grade_path.is_file():
            missing.append(f"{path.name}:grading.json")
            records.append(
                {
                    **metadata,
                    "grade": None,
                    "grader_metadata": None,
                    "case_contract": contract,
                    "grader_attempt": None,
                }
            )
            continue
        grader_metadata_path = path / "grader_metadata.json"
        attempt_path = path / "grader_attempt.json"
        transcript_path = path / "grader-transcript.jsonl"
        stderr_path = path / "grader-stderr.txt"
        grader_metadata = None
        attempt = None
        required_stage_paths = (
            grader_metadata_path,
            attempt_path,
            transcript_path,
            stderr_path,
        )
        absent_stage_paths = [item.name for item in required_stage_paths if not item.is_file()]
        if absent_stage_paths:
            missing.extend(f"{path.name}:{name}" for name in absent_stage_paths)
        else:
            grader_metadata = load_json(grader_metadata_path)
            attempt = load_json(attempt_path)
            if grader_metadata.get("returncode") != 0:
                missing.append(f"{path.name}:successful grader execution")
            if grader_metadata.get("validation_errors"):
                missing.append(f"{path.name}:valid grade")
        grade = load_json(grade_path)
        grade_errors: list[str] = (
            ["partial grader evidence"] if absent_stage_paths else []
        )
        if not task_clean:
            grade_errors.append("task evidence is not release-eligible")
        if contract is not None:
            grade_errors.extend(validate_grade(grade, contract))
        if grader_metadata is not None and attempt is not None:
            try:
                require_clean_stage_execution(
                    grader_metadata,
                    CANONICAL_GRADER_TIMEOUT_SECONDS,
                    f"Grader {path.name}",
                    "grader",
                )
            except EvaluationError as exc:
                grade_errors.append(str(exc))
            grade_errors.extend(
                validate_grader_attempt_binding(attempt, grader_metadata, metadata, path.name)
            )
            grade_errors.extend(
                validate_grader_output_binding(
                    grader_metadata,
                    grade_path,
                    contract_path,
                    attempt_path,
                    path,
                )
            )
        if grade_errors:
            missing.extend(f"{path.name}:invalid grade evidence: {error}" for error in grade_errors)
            grade = None
        records.append(
            {
                **metadata,
                "grade": grade,
                "grader_metadata": grader_metadata,
                "case_contract": contract,
                "grader_attempt": attempt,
            }
        )
    return records, missing


def collect_comparisons(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    root = run_dir / "comparisons"
    if not root.is_dir():
        return [], []
    comparisons: list[dict[str, Any]] = []
    missing: list[str] = []
    for target in sorted(path for path in root.iterdir() if path.is_dir()):
        result_path = target / "comparison.json"
        metadata_path = target / "comparison_metadata.json"
        contract_path = target / "case_contract.json"
        transcript_path = target / "comparator-transcript.jsonl"
        stderr_path = target / "comparator-stderr.txt"
        required = (result_path, metadata_path, contract_path, transcript_path, stderr_path)
        absent = [path.name for path in required if not path.is_file()]
        if absent:
            missing.extend(f"comparison {target.name}:{name}" for name in absent)
            continue
        metadata = load_json(metadata_path)
        comparison = load_json(result_path)
        contract = load_json(contract_path)
        errors = validate_comparison(comparison, contract)
        try:
            require_clean_stage_execution(
                metadata,
                CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
                f"Comparator {target.name}",
                "blind_comparator",
            )
        except EvaluationError as exc:
            errors.append(str(exc))
        seed = metadata.get("blind_seed")
        if not isinstance(seed, str) or not seed:
            errors.append("comparison metadata blind_seed mismatch")
        elif seed != CANONICAL_BLIND_SEED:
            errors.append("comparison metadata does not use the canonical blind seed")
        else:
            errors.extend(
                validate_comparison_binding(
                    metadata,
                    comparison,
                    pair_id=str(metadata.get("pair_id")),
                    case_id=str(metadata.get("case_id")),
                    storage_id=target.name,
                    seed=seed,
                    source_runs=metadata.get("source_runs")
                    if isinstance(metadata.get("source_runs"), dict)
                    else {},
                )
            )
        errors.extend(
            validate_comparison_output_binding(
                metadata, result_path, contract_path, target
            )
        )
        if errors:
            missing.extend(
                f"comparison {target.name}:invalid evidence: {error}" for error in errors
            )
            continue
        comparisons.append(
            {
                **metadata,
                "comparison_output": comparison,
                "case_contract": contract,
                "comparison_storage_id": target.name,
            }
        )
    return comparisons, missing


def load_trigger_results(path: Path | None) -> dict[str, Any] | None:
    if path and path.is_file():
        return load_json(path)
    return None


def validate_trigger_file_bindings(
    trigger_results: dict[str, Any] | None,
    results_path: Path | None,
    trigger_suite: dict[str, Any] | None = None,
) -> list[str]:
    """Rehash raw trigger files and rederive every activation observation."""

    if trigger_results is None or results_path is None:
        return []
    observations = trigger_results.get("observations")
    if not isinstance(observations, list):
        return ["trigger-results:observations is not a list"]
    if not isinstance(trigger_suite, dict):
        return ["trigger-results:canonical trigger suite is required for binding"]
    errors: list[str] = []
    errors.extend(
        stage_method_receipt_validation_errors(
            trigger_results, "trigger", "trigger-results"
        )
    )
    errors.extend(
        trigger_fail_fast_receipt_validation_errors(
            trigger_results, "trigger-results"
        )
    )
    if trigger_results.get(
        "workspace_environment_method"
    ) != canonical_trigger_workspace_environment_method():
        errors.append(
            "trigger-results:missing or unsupported workspace-environment method"
        )
    expected_trigger_schema_sha256 = file_sha256(TRIGGER_SCHEMA)
    if (
        trigger_results.get("trigger_schema_sha256")
        != expected_trigger_schema_sha256
    ):
        errors.append("trigger-results:trigger output schema hash mismatch")
    results_directory = results_path.parent
    root = results_directory / "trigger-observations"
    file_hashes = trigger_results.get("observation_file_hashes")
    if not isinstance(file_hashes, dict):
        errors.append("trigger-results:observation file hashes are missing")
        file_hashes = {}
    cases = {
        str(case.get("case_id")): case
        for case in trigger_suite.get("cases", [])
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    }
    observed_ids: list[str] = []

    def is_real_directory(path: Path) -> bool:
        try:
            info = path.lstat()
        except OSError:
            return False
        return (
            not path.is_symlink()
            and not bool(getattr(info, "st_file_attributes", 0) & 0x400)
            and stat.S_ISDIR(info.st_mode)
        )

    def is_regular_file(path: Path, expected_parent: Path) -> bool:
        try:
            info = path.lstat()
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        return (
            not path.is_symlink()
            and not bool(getattr(info, "st_file_attributes", 0) & 0x400)
            and stat.S_ISREG(info.st_mode)
            and resolved.parent == expected_parent
        )

    if not is_real_directory(results_directory) or not is_real_directory(root):
        return ["trigger-results:observation root is missing or unsafe"]
    try:
        results_directory_resolved = results_directory.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return ["trigger-results:observation root is missing or unsafe"]
    if root_resolved.parent != results_directory_resolved:
        return ["trigger-results:observation root escapes the results directory"]

    for observation in observations:
        if not isinstance(observation, dict):
            errors.append("trigger-results:malformed observation")
            continue
        observation_id = observation.get("observation_id")
        if not isinstance(observation_id, str) or re.fullmatch(
            r"[a-z0-9][a-z0-9-]*__r[0-9]{2,}", observation_id
        ) is None:
            errors.append("trigger-results:unsafe observation id")
            continue
        observed_ids.append(observation_id)
        errors.extend(
            stage_method_receipt_validation_errors(
                observation, "trigger", f"trigger {observation_id}"
            )
        )
        directory = root / observation_id
        if not is_real_directory(directory):
            errors.append(f"trigger {observation_id}:observation directory is missing or unsafe")
            continue
        try:
            directory_resolved = directory.resolve(strict=True)
        except (OSError, RuntimeError):
            errors.append(f"trigger {observation_id}:observation directory is missing or unsafe")
            continue
        if directory_resolved.parent != root_resolved:
            errors.append(f"trigger {observation_id}:observation directory escapes its root")
            continue
        prediction = directory / "prediction.json"
        transcript = directory / "transcript.jsonl"
        stderr = directory / "stderr.txt"
        observation_path = directory / "observation.json"
        for key, path in (
            ("prediction_sha256", prediction),
            ("transcript_sha256", transcript),
            ("stderr_sha256", stderr),
        ):
            if (
                not is_regular_file(path, directory_resolved)
                or observation.get(key) != file_sha256(path)
            ):
                errors.append(f"trigger {observation_id}:{key} mismatch")
        if observation.get("staged_prediction_sha256") != observation.get(
            "prediction_sha256"
        ):
            errors.append(
                f"trigger {observation_id}:staged and persisted prediction hashes differ"
            )
        for key in (
            "trigger_schema_sha256",
            "staged_trigger_schema_sha256",
            "post_execution_trigger_schema_sha256",
        ):
            if observation.get(key) != expected_trigger_schema_sha256:
                errors.append(f"trigger {observation_id}:{key} mismatch")
        sentinel_skill_sha256 = observation.get("sentinel_skill_sha256")
        post_sentinel_skill_sha256 = observation.get(
            "post_execution_sentinel_skill_sha256"
        )
        if (
            not isinstance(sentinel_skill_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sentinel_skill_sha256) is None
            or post_sentinel_skill_sha256 != sentinel_skill_sha256
        ):
            errors.append(
                f"trigger {observation_id}:staged sentinel skill hash mismatch"
            )
        if observation.get("staging_cleanup_completed") is not True:
            errors.append(f"trigger {observation_id}:staging cleanup receipt is invalid")
        if not is_regular_file(observation_path, directory_resolved):
            errors.append(f"trigger {observation_id}:observation.json is missing or unsafe")
        else:
            if file_hashes.get(observation_id) != file_sha256(observation_path):
                errors.append(f"trigger {observation_id}:observation file hash mismatch")
            try:
                persisted_observation = load_json(observation_path)
            except EvaluationError as error:
                errors.append(f"trigger {observation_id}:{error}")
            else:
                if persisted_observation != observation:
                    errors.append(
                        f"trigger {observation_id}:result observation differs from observation.json"
                    )
        errors.extend(
            f"trigger {observation_id}:{error}"
            for error in task_trace_isolation_validation_errors(
                transcript, "trigger trace"
            )
        )
        errors.extend(
            workspace_environment_receipt_validation_errors(
                observation,
                f"trigger {observation_id}",
                require_absent_workspace=True,
            )
        )
        case_id = observation.get("case_id")
        case = cases.get(str(case_id))
        repetition = observation.get("repetition")
        if (
            case is None
            or isinstance(repetition, bool)
            or not isinstance(repetition, int)
            or repetition < 1
            or observation_id != f"{case_id}__r{repetition:02d}"
            or observation.get("candidate_skill") != case.get("candidate_skill")
            or not isinstance(observation.get("should_trigger"), bool)
            or observation.get("should_trigger") != case.get("should_trigger")
        ):
            errors.append(f"trigger {observation_id}:suite-case binding mismatch")
            continue
        if not is_regular_file(
            prediction, directory_resolved
        ) or not is_regular_file(transcript, directory_resolved):
            continue
        try:
            prediction_document = load_json(prediction)
            transcript_text = transcript.read_text(encoding="utf-8")
        except (EvaluationError, OSError, UnicodeDecodeError) as error:
            errors.append(f"trigger {observation_id}:cannot load raw prediction: {error}")
            continue
        errors.extend(
            f"trigger {observation_id}:{error}"
            for error in validate_trigger_prediction(prediction_document)
        )
        marker = "report-skills-triggered:" + hashlib.sha256(
            observation_id.encode("utf-8")
        ).hexdigest()[:24]
        triggered = body_proven_activation(
            prediction_document,
            str(case["candidate_skill"]),
            marker,
            transcript_text,
        )
        expected_evidence = (
            "body_only_sentinel" if triggered else "sentinel_not_observed"
        )
        if (
            not isinstance(observation.get("triggered"), bool)
            or observation.get("triggered") != triggered
        ):
            errors.append(f"trigger {observation_id}:triggered result mismatch")
        expected_correct = triggered == case["should_trigger"]
        if (
            not isinstance(observation.get("correct"), bool)
            or observation.get("correct") != expected_correct
        ):
            errors.append(f"trigger {observation_id}:correct result mismatch")
        if observation.get("selected_skill") != prediction_document.get(
            "selected_skill"
        ):
            errors.append(f"trigger {observation_id}:selected skill mismatch")
        if observation.get("activation_evidence") != expected_evidence:
            errors.append(f"trigger {observation_id}:activation evidence mismatch")
    if set(file_hashes) != set(observed_ids):
        errors.append("trigger-results:observation file hash inventory mismatch")
    duplicate_observation_ids = sorted(
        observation_id
        for observation_id, count in Counter(observed_ids).items()
        if count != 1
    )
    if duplicate_observation_ids:
        errors.append(
            "trigger-results:duplicate observation ids "
            + repr(duplicate_observation_ids)
        )
    return errors


def gate_value(gates: dict[str, Any], name: str) -> tuple[str, float]:
    gate = gates.get(name)
    if not isinstance(gate, dict):
        raise EvaluationError(f"Missing release threshold: {name}")
    return str(gate["operator"]), float(gate["value"])


def evidence_identity(
    document: dict[str, Any], label: str, issues: list[str]
) -> tuple[Any, ...] | None:
    profile = document.get("execution_profile")
    repository = document.get("repository")
    if not isinstance(profile, dict) or not isinstance(repository, dict):
        issues.append(f"{label}:missing evaluation identity")
        return None
    if profile.get("codex_invocation") != CODEX_INVOCATION_MODE:
        issues.append(f"{label}:unsupported Codex invocation method")
        return None
    if profile.get("codex_timeout_enforcement") != CODEX_TIMEOUT_ENFORCEMENT_MODE:
        issues.append(f"{label}:unsupported timeout enforcement method")
        return None
    profile_identity = tuple(profile.get(key) for key in PROFILE_IDENTITY_KEYS)
    commit = repository.get("commit")
    tree = repository.get("tree")
    if not all(isinstance(value, str) and value.strip() for value in profile_identity):
        issues.append(f"{label}:incomplete execution profile")
        return None
    for key in (
        "codex_command_sha256",
        "codex_implementation_sha256",
        "codex_managed_environment_sha256",
        "selected_model_sha256",
        "model_isolation_prompt_probe_sha256",
    ):
        value = profile.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            issues.append(f"{label}:invalid {key}")
            return None
    if not all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40,64}", value)
        for value in (commit, tree)
    ):
        issues.append(f"{label}:invalid repository commit/tree")
        return None
    if repository.get("dirty") is not False:
        issues.append(f"{label}:dirty repository receipt")
        return None
    repository_identity = tuple(repository.get(key) for key in REPOSITORY_IDENTITY_KEYS)
    if not isinstance(repository.get("root"), str) or not repository["root"].strip():
        issues.append(f"{label}:missing repository root")
        return None
    return (*profile_identity, *repository_identity)


def validate_evidence_invariants(
    plan: dict[str, Any],
    records: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    trigger_results: dict[str, Any] | None,
    trigger_suite: dict[str, Any],
) -> list[str]:
    """Return non-compensable evidence identity and coverage failures."""

    issues: list[str] = []
    issues.extend(
        stage_method_receipt_validation_errors(
            plan, "behavioral_task", "run-plan"
        )
    )
    anchor = evidence_identity(plan, "run-plan", issues)
    if anchor is None:
        return issues
    expected_skill_hashes = plan.get("skill_hashes")
    if not isinstance(expected_skill_hashes, dict) or not expected_skill_hashes:
        issues.append("run-plan:missing skill hashes")
    elif any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in expected_skill_hashes.values()
    ):
        issues.append("run-plan:invalid skill hashes")

    planned_rows = plan.get("runs", [])
    if not isinstance(planned_rows, list):
        return [*issues, "run-plan:runs is not a list"]
    planned_counts = Counter(str(item.get("run_id")) for item in planned_rows)
    duplicate_planned = sorted(run_id for run_id, count in planned_counts.items() if count != 1)
    if duplicate_planned:
        issues.append(f"run-plan:duplicate run ids {duplicate_planned}")
    planned_by_id = {str(item.get("run_id")): item for item in planned_rows}
    observed_counts = Counter(str(item.get("run_id")) for item in records)
    records_by_id = {str(item.get("run_id")): item for item in records}
    duplicate_observed = sorted(run_id for run_id, count in observed_counts.items() if count != 1)
    if duplicate_observed:
        issues.append(f"runs:duplicate run ids {duplicate_observed}")
    missing_runs = sorted(set(planned_by_id) - set(observed_counts))
    extra_runs = sorted(set(observed_counts) - set(planned_by_id))
    if missing_runs:
        issues.append(f"runs:missing planned ids {missing_runs}")
    if extra_runs:
        issues.append(f"runs:unplanned ids {extra_runs}")

    binding_fields = (
        "pair_id",
        "case_id",
        "case_kind",
        "skill",
        "configuration",
        "repetition",
    )
    planned_timeout = plan.get("timeout_seconds")
    planned_contract_hashes = plan.get("case_contract_hashes")
    if not isinstance(planned_contract_hashes, dict):
        issues.append("run-plan:missing case-contract hashes")
        planned_contract_hashes = {}
    for record in records:
        run_id = str(record.get("run_id"))
        if evidence_identity(record, f"task {run_id}", issues) != anchor:
            issues.append(f"task {run_id}:evaluation identity mismatch")
        validate_task_method_receipt(record, f"task {run_id}", issues)
        if record.get("timeout_seconds") != planned_timeout:
            issues.append(f"task {run_id}:timeout does not match run-plan")
        planned = planned_by_id.get(run_id)
        if planned and any(record.get(field) != planned.get(field) for field in binding_fields):
            issues.append(f"task {run_id}:run-plan binding mismatch")
        contract = record.get("case_contract")
        expected_contract_hash = planned_contract_hashes.get(run_id)
        if (
            not isinstance(contract, dict)
            or not isinstance(expected_contract_hash, str)
            or canonical_json_sha256(contract) != expected_contract_hash
        ):
            issues.append(f"task {run_id}:case contract does not match run-plan")
        grader = record.get("grader_metadata")
        if not isinstance(grader, dict):
            issues.append(f"grader {run_id}:missing metadata")
        else:
            if evidence_identity(grader, f"grader {run_id}", issues) != anchor:
                issues.append(f"grader {run_id}:evaluation identity mismatch")
            if grader.get("returncode") != 0 or grader.get("validation_errors"):
                issues.append(f"grader {run_id}:failed or invalid")
            validate_execution_receipt(
                grader,
                f"grader {run_id}",
                CANONICAL_GRADER_TIMEOUT_SECONDS,
                "grader",
                issues,
            )
            grade = record.get("grade")
            contract = record.get("case_contract")
            attempt = record.get("grader_attempt")
            if not isinstance(grade, dict) or not isinstance(contract, dict):
                issues.append(f"grader {run_id}:missing grade or case contract")
            else:
                issues.extend(
                    f"grader {run_id}:{error}" for error in validate_grade(grade, contract)
                )
            if not isinstance(attempt, dict):
                issues.append(f"grader {run_id}:missing durable attempt receipt")
            else:
                issues.extend(
                    f"grader {run_id}:{error}"
                    for error in validate_grader_attempt_binding(
                        attempt,
                        grader,
                        record,
                        str(record.get("storage_id")),
                    )
                )

    expected_pair_rows: dict[str, dict[str, Any]] = {}
    for item in planned_rows:
        if item.get("case_kind") != "primary":
            continue
        pair_id = str(item.get("pair_id"))
        expected_pair_rows.setdefault(pair_id, {})[str(item.get("configuration"))] = item
    expected_pairs = set(expected_pair_rows)
    comparison_counts = Counter(str(item.get("pair_id")) for item in comparisons)
    duplicate_pairs = sorted(pair_id for pair_id, count in comparison_counts.items() if count != 1)
    if duplicate_pairs:
        issues.append(f"comparisons:duplicate pair ids {duplicate_pairs}")
    missing_pairs = sorted(expected_pairs - set(comparison_counts))
    extra_pairs = sorted(set(comparison_counts) - expected_pairs)
    if missing_pairs:
        issues.append(f"comparisons:missing pair ids {missing_pairs}")
    if extra_pairs:
        issues.append(f"comparisons:unplanned pair ids {extra_pairs}")
    blind_seeds: set[str] = set()
    for comparison in comparisons:
        pair_id = str(comparison.get("pair_id"))
        if evidence_identity(comparison, f"comparison {pair_id}", issues) != anchor:
            issues.append(f"comparison {pair_id}:evaluation identity mismatch")
        if comparison.get("returncode") != 0:
            issues.append(f"comparison {pair_id}:failed execution")
        if comparison.get("validation_errors"):
            issues.append(f"comparison {pair_id}:invalid output")
        validate_execution_receipt(
            comparison,
            f"comparison {pair_id}",
            CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
            "blind_comparator",
            issues,
        )
        expected_rows = expected_pair_rows.get(pair_id, {})
        expected_case_ids = {
            str(item.get("case_id")) for item in expected_rows.values()
        }
        if len(expected_case_ids) != 1 or comparison.get("case_id") not in expected_case_ids:
            issues.append(f"comparison {pair_id}:case binding mismatch")
        seed = comparison.get("blind_seed")
        if not isinstance(seed, str) or not seed:
            issues.append(f"comparison {pair_id}:missing blind seed")
            continue
        blind_seeds.add(seed)
        expected_label_map = label_map(pair_id, seed)
        source_runs = {
            label: {
                "run_id": str(expected_rows[configuration].get("run_id")),
                "configuration": configuration,
                "blind_bundle_sha256": (
                    records_by_id.get(
                        str(expected_rows[configuration].get("run_id")), {}
                    ).get("task_evidence", {})
                ).get("blind_bundle_sha256"),
            }
            for label, configuration in expected_label_map.items()
            if configuration in expected_rows
        }
        comparison_output = comparison.get("comparison_output")
        contract = comparison.get("case_contract")
        if not isinstance(comparison_output, dict) or not isinstance(contract, dict):
            issues.append(f"comparison {pair_id}:missing comparison output or contract")
            continue
        expected_contract_hashes = {
            planned_contract_hashes.get(str(item.get("run_id")))
            for item in expected_rows.values()
        }
        if (
            len(expected_contract_hashes) != 1
            or None in expected_contract_hashes
            or canonical_json_sha256(contract) not in expected_contract_hashes
        ):
            issues.append(f"comparison {pair_id}:case contract does not match run-plan")
        source_contract_file_hashes = {
            records_by_id.get(str(item.get("run_id")), {})
            .get("task_evidence", {})
            .get("case_contract_sha256")
            for item in expected_rows.values()
        }
        if (
            len(source_contract_file_hashes) != 1
            or None in source_contract_file_hashes
            or comparison.get("case_contract_sha256") not in source_contract_file_hashes
        ):
            issues.append(f"comparison {pair_id}:case contract does not match source tasks")
        issues.extend(
            f"comparison {pair_id}:{error}"
            for error in validate_comparison(comparison_output, contract)
        )
        issues.extend(
            f"comparison {pair_id}:{error}"
            for error in validate_comparison_binding(
                comparison,
                comparison_output,
                pair_id=pair_id,
                case_id=next(iter(expected_case_ids)) if len(expected_case_ids) == 1 else "",
                storage_id=str(comparison.get("comparison_storage_id")),
                seed=seed,
                source_runs=source_runs,
            )
        )
    if blind_seeds != {CANONICAL_BLIND_SEED}:
        issues.append(
            "comparisons:expected the canonical blind seed "
            f"{CANONICAL_BLIND_SEED}, got {sorted(blind_seeds)}"
        )

    if trigger_results is None:
        return issues
    trigger_identity = evidence_identity(trigger_results, "trigger-results", issues)
    if trigger_identity != anchor:
        issues.append("trigger-results:evaluation identity mismatch")
    if trigger_results.get("model_isolation") != canonical_model_isolation_receipt():
        issues.append("trigger-results:missing or unsupported model isolation receipt")
    issues.extend(
        stage_method_receipt_validation_errors(
            trigger_results, "trigger", "trigger-results"
        )
    )
    issues.extend(
        trigger_fail_fast_receipt_validation_errors(
            trigger_results, "trigger-results"
        )
    )
    if trigger_results.get(
        "workspace_environment_method"
    ) != canonical_trigger_workspace_environment_method():
        issues.append(
            "trigger-results:missing or unsupported workspace-environment method"
        )
    if trigger_results.get("skill_hashes") != expected_skill_hashes:
        issues.append("trigger-results:skill hashes do not match run-plan")
    if trigger_results.get("timeout_seconds") != CANONICAL_TRIGGER_TIMEOUT_SECONDS:
        issues.append("trigger-results:noncanonical timeout")
    observations = trigger_results.get("observations", [])
    if not isinstance(observations, list):
        return [*issues, "trigger-results:observations is not a list"]
    repetitions = int(trigger_suite.get("protocol", {}).get("repetitions_per_case", 3))
    expected_observations = {
        f"{case['case_id']}__r{repetition:02d}": {
            "case_id": case["case_id"],
            "candidate_skill": case["candidate_skill"],
            "repetition": repetition,
            "should_trigger": case["should_trigger"],
        }
        for case in trigger_suite.get("cases", [])
        for repetition in range(1, repetitions + 1)
    }
    observation_counts = Counter(str(item.get("observation_id")) for item in observations)
    duplicate_observations = sorted(
        observation_id for observation_id, count in observation_counts.items() if count != 1
    )
    if duplicate_observations:
        issues.append(f"triggers:duplicate observation ids {duplicate_observations}")
    missing_observations = sorted(set(expected_observations) - set(observation_counts))
    extra_observations = sorted(set(observation_counts) - set(expected_observations))
    if missing_observations:
        issues.append(f"triggers:missing observation ids {missing_observations}")
    if extra_observations:
        issues.append(f"triggers:unplanned observation ids {extra_observations}")
    for observation in observations:
        observation_id = str(observation.get("observation_id"))
        if evidence_identity(observation, f"trigger {observation_id}", issues) != anchor:
            issues.append(f"trigger {observation_id}:evaluation identity mismatch")
        expected = expected_observations.get(observation_id)
        if expected and any(observation.get(field) != value for field, value in expected.items()):
            issues.append(f"trigger {observation_id}:suite binding mismatch")
        if observation.get("returncode") != 0 or observation.get("validation_errors"):
            issues.append(f"trigger {observation_id}:failed or invalid prediction")
        validate_execution_receipt(
            observation,
            f"trigger {observation_id}",
            CANONICAL_TRIGGER_TIMEOUT_SECONDS,
            "trigger",
            issues,
        )
        issues.extend(
            workspace_environment_receipt_validation_errors(
                observation,
                f"trigger {observation_id}",
                require_absent_workspace=True,
            )
        )
        if observation.get("correct") is not (
            observation.get("triggered") == observation.get("should_trigger")
        ):
            issues.append(f"trigger {observation_id}:incorrect correctness flag")
    if summarize(observations) != trigger_results.get("metrics"):
        issues.append("trigger-results:stored metrics do not match observations")
    if trigger_results.get("failed_observations"):
        issues.append("trigger-results:failed observations")
    return issues


def evaluate_release(
    records: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    trigger_results: dict[str, Any] | None,
    thresholds: dict[str, Any],
    missing: list[str],
    expected_skills: set[str] | None = None,
    expected_pairs: set[str] | None = None,
    expected_trigger_observations: int | None = None,
) -> dict[str, Any]:
    gates = thresholds.get("hard_gates", {})
    grades = [record for record in records if record.get("grade")]
    observed_skills = {
        record["skill"]
        for record in records
        if record.get("configuration") == "with_skill" and record.get("case_kind") == "primary"
    }
    expected_skills = expected_skills or observed_skills
    per_skill_scores: dict[str, list[float]] = defaultdict(list)
    for record in grades:
        if record.get("configuration") == "with_skill" and record.get("case_kind") == "primary":
            per_skill_scores[record["skill"]].append(float(record["grade"]["summary"]["score"]))
    per_skill = {skill: summary_stats(values) for skill, values in sorted(per_skill_scores.items())}
    op, expected = gate_value(gates, "per_skill_median_score")
    skill_failures = sorted(expected_skills - set(per_skill))
    skill_failures.extend(
        skill for skill, stats in per_skill.items() if not compare(op, float(stats["median"]), expected)
    )
    skill_failures = sorted(set(skill_failures))

    with_skill = [record for record in grades if record.get("configuration") == "with_skill"]
    blocking = sum(int(record["grade"]["summary"].get("blocking_failures", 0)) for record in with_skill)
    adversarial = [record for record in with_skill if record.get("case_kind") == "adversarial"]
    adversarial_passed = sum(record["grade"]["summary"].get("blocking_failures", 0) == 0 and record["grade"]["summary"].get("score", 0) >= 100 for record in adversarial)
    adversarial_rate = adversarial_passed / len(adversarial) if adversarial else None
    integrity_events = sum(len(record["grade"].get("integrity_events", [])) for record in with_skill)
    mutations = sum(len(record["grade"].get("unauthorized_external_mutations", [])) for record in with_skill)

    wins = sum(item.get("resolved_winner") == "with_skill" for item in comparisons)
    blind_rate = wins / len(comparisons) if comparisons else None

    actuals: dict[str, Any] = {
        "per_skill_median_score": {"per_skill": per_skill, "failing_skills": skill_failures},
        "blocking_failures": blocking,
        "adversarial_pass_rate": adversarial_rate,
        "blind_with_skill_win_rate": blind_rate,
        "integrity_events": integrity_events,
        "unauthorized_external_mutations": mutations,
        "trigger_precision": None,
        "trigger_recall": None,
    }
    if trigger_results:
        suite_metrics = trigger_results.get("metrics", {}).get("suite_wide", {})
        per_skill_trigger = trigger_results.get("metrics", {}).get("per_skill", {})
        actuals["trigger_precision"] = {"suite_wide": suite_metrics.get("precision"), "per_skill": {skill: data.get("precision") for skill, data in per_skill_trigger.items()}}
        actuals["trigger_recall"] = {"suite_wide": suite_metrics.get("recall"), "per_skill": {skill: data.get("recall") for skill, data in per_skill_trigger.items()}}

    results: dict[str, Any] = {}
    results["per_skill_median_score"] = {"passed": bool(per_skill) and not skill_failures, "actual": actuals["per_skill_median_score"], "threshold": expected}
    for name in ("blocking_failures", "adversarial_pass_rate", "blind_with_skill_win_rate", "integrity_events", "unauthorized_external_mutations"):
        operator, target = gate_value(gates, name)
        actual = actuals[name]
        results[name] = {"passed": actual is not None and compare(operator, actual, target), "actual": actual, "operator": operator, "threshold": target}
    for name in ("trigger_precision", "trigger_recall"):
        operator, target = gate_value(gates, name)
        actual = actuals[name]
        values = [] if actual is None else [actual["suite_wide"], *actual["per_skill"].values()]
        results[name] = {"passed": bool(values) and all(value is not None and compare(operator, value, target) for value in values), "actual": actual, "operator": operator, "threshold": target}

    missing_evidence = list(missing)
    if len(grades) != len(records):
        missing_evidence.append("one or more run grades")
    expected_pairs = expected_pairs or {
        record["pair_id"]
        for record in records
        if record.get("case_kind") == "primary" and record.get("configuration") in {"with_skill", "without_skill"}
    }
    observed_pairs = {item.get("pair_id") for item in comparisons}
    if expected_pairs - observed_pairs:
        missing_evidence.append(f"blind comparisons for {len(expected_pairs - observed_pairs)} primary pairs")
    if trigger_results is None:
        missing_evidence.append("trigger results")
    else:
        observations = trigger_results.get("observations", [])
        if trigger_results.get("failed_observations"):
            missing_evidence.append("successful trigger observations")
        if expected_trigger_observations is not None and len(observations) != expected_trigger_observations:
            missing_evidence.append(
                f"trigger observations {len(observations)}/{expected_trigger_observations}"
            )
        trigger_skills = set(trigger_results.get("metrics", {}).get("per_skill", {}))
        if expected_skills - trigger_skills:
            missing_evidence.append(f"per-skill trigger metrics for {sorted(expected_skills - trigger_skills)}")
    incomplete = bool(missing_evidence)
    all_pass = all(result["passed"] for result in results.values())
    decision = "release" if all_pass and not incomplete else ("incomplete" if incomplete else "hold")
    return {"decision": decision, "complete": not incomplete, "all_hard_gates_pass": all_pass, "hard_gates": results, "missing_evidence": sorted(set(missing_evidence))}


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--trigger-results", type=Path)
    parser.add_argument("--trigger-suite", type=Path, default=DEFAULT_TRIGGERS)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        run_dir = args.run_dir.resolve()
        records, missing = collect_runs(run_dir)
        plan_path = run_dir / "run-plan.json"
        if plan_path.is_file():
            plan = load_json(plan_path)
            current_repository = repository_receipt(require_clean=True)
            require_matching_context(
                plan.get("execution_profile", {}),
                plan.get("repository", {}),
                plan.get("execution_profile", {}),
                current_repository,
                "Aggregation",
            )
            planned = plan.get("runs", [])
            planned_ids = {item["run_id"] for item in planned}
            observed_ids = {record.get("run_id") for record in records}
            missing.extend(f"{run_id}:run directory" for run_id in sorted(planned_ids - observed_ids))
            expected_skills = {
                item["skill"] for item in planned
                if item.get("case_kind") == "primary" and item.get("configuration") == "with_skill"
            }
            expected_pairs = {
                item["pair_id"] for item in planned if item.get("case_kind") == "primary"
            }
            current_skill_hashes = {
                skill: tracked_directory_sha256(REPO_ROOT / "skills" / skill)
                for skill in sorted({item["skill"] for item in planned})
            }
            if plan.get("skill_hashes") != current_skill_hashes:
                missing.append("run-plan:skill hashes do not match the candidate checkout")
        else:
            plan = {}
            missing.append("run-plan.json")
            expected_skills = set()
            expected_pairs = set()
        comparisons, comparison_missing = collect_comparisons(run_dir)
        missing.extend(comparison_missing)
        triggers = load_trigger_results(args.trigger_results)
        thresholds = load_json(args.thresholds)
        trigger_suite = load_json(args.trigger_suite)
        missing.extend(
            validate_trigger_file_bindings(
                triggers, args.trigger_results, trigger_suite
            )
        )
        trigger_repetitions = int(trigger_suite.get("protocol", {}).get("repetitions_per_case", 3))
        expected_trigger_observations = len(trigger_suite.get("cases", [])) * trigger_repetitions
        missing.extend(
            validate_evidence_invariants(plan, records, comparisons, triggers, trigger_suite)
        )
        missing.extend(
            validate_release_eval_plan(plan, triggers, args.thresholds, args.trigger_suite)
        )
        release = evaluate_release(
            records,
            comparisons,
            triggers,
            thresholds,
            missing,
            expected_skills,
            expected_pairs,
            expected_trigger_observations,
        )
        blind_seeds = {
            str(item.get("blind_seed"))
            for item in comparisons
            if isinstance(item.get("blind_seed"), str) and item.get("blind_seed")
        }
        blind_seed = next(iter(blind_seeds)) if len(blind_seeds) == 1 else None

        grouped: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        for record in records:
            if record.get("grade"):
                metrics = grouped[record["skill"]][record["configuration"]]
                metrics["score"].append(float(record["grade"]["summary"]["score"]))
                if isinstance(record.get("wall_clock_seconds"), (int, float)):
                    metrics["wall_clock_seconds"].append(float(record["wall_clock_seconds"]))
                tokens = record.get("token_usage", {}).get("total_tokens")
                if isinstance(tokens, int):
                    metrics["total_tokens"].append(float(tokens))
        variance = {
            skill: {
                config: {metric: summary_stats(values) for metric, values in metrics.items()}
                for config, metrics in configs.items()
            }
            for skill, configs in sorted(grouped.items())
        }
        efficiency_limit = float(
            thresholds.get("advisories", {}).get("efficiency", {}).get("warning_value", 2.0)
        )
        efficiency: dict[str, Any] = {"warning_ratio": efficiency_limit, "per_skill": {}, "suite": {}}
        for skill, configs in variance.items():
            efficiency["per_skill"][skill] = {}
            for metric in ("wall_clock_seconds", "total_tokens"):
                with_value = configs.get("with_skill", {}).get(metric, {}).get("median")
                baseline = configs.get("without_skill", {}).get(metric, {}).get("median")
                ratio = with_value / baseline if with_value is not None and baseline not in {None, 0} else None
                efficiency["per_skill"][skill][metric] = {
                    "with_skill_to_baseline_ratio": ratio,
                    "warning": ratio is not None and ratio > efficiency_limit,
                }
        for metric in ("wall_clock_seconds", "total_tokens"):
            with_values = [
                value
                for record in records
                if record.get("configuration") == "with_skill"
                for value in [
                    record.get("wall_clock_seconds")
                    if metric == "wall_clock_seconds"
                    else record.get("token_usage", {}).get("total_tokens")
                ]
                if isinstance(value, (int, float))
            ]
            baseline_values = [
                value
                for record in records
                if record.get("configuration") == "without_skill"
                for value in [
                    record.get("wall_clock_seconds")
                    if metric == "wall_clock_seconds"
                    else record.get("token_usage", {}).get("total_tokens")
                ]
                if isinstance(value, (int, float))
            ]
            with_median = summary_stats(with_values)["median"]
            baseline_median = summary_stats(baseline_values)["median"]
            ratio = with_median / baseline_median if with_median is not None and baseline_median not in {None, 0} else None
            efficiency["suite"][metric] = {
                "with_skill_to_baseline_ratio": ratio,
                "warning": ratio is not None and ratio > efficiency_limit,
            }
        output = {
            "schema_version": "1.0",
            "evaluation_method_version": EVALUATION_METHOD_VERSION,
            "generated_at": utc_now(),
            "run_dir": str(run_dir),
            "run_count": len(records),
            "graded_run_count": sum(record.get("grade") is not None for record in records),
            "blind_comparison_count": len(comparisons),
            "evaluation_receipt": {
                "evaluation_method_version": EVALUATION_METHOD_VERSION,
                "stage_methods": canonical_stage_methods(),
                "execution_profile": plan.get("execution_profile"),
                "repository": plan.get("repository"),
                "skill_hashes": plan.get("skill_hashes"),
                "workspace_input_hashes": plan.get("workspace_input_hashes"),
                "repetitions": plan.get("repetitions"),
                "blind_seed": blind_seed,
                "timeouts_seconds": {
                    "behavioral_task": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
                    "grader": CANONICAL_GRADER_TIMEOUT_SECONDS,
                    "blind_comparator": CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
                    "trigger": CANONICAL_TRIGGER_TIMEOUT_SECONDS,
                },
                "behavioral_method": {
                    **canonical_task_isolation_receipt(),
                },
                "model_isolation": canonical_model_isolation_receipt(),
                "contract_hashes": {
                    **(plan.get("contract_hashes") or {}),
                    **((triggers or {}).get("contract_hashes") or {}),
                },
            },
            "variance": variance,
            "advisories": {"efficiency": efficiency},
            "release_verdict": release,
        }
        output_path = args.output or (run_dir / "benchmark.json")
        write_json(output_path, output)
        print(json.dumps({"benchmark": str(output_path), "decision": release["decision"], "complete": release["complete"], "all_hard_gates_pass": release["all_hard_gates_pass"]}, indent=2))
        return 0 if release["decision"] == "release" else 1
    except EvaluationError as exc:
        print(f"Aggregation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
