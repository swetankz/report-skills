#!/usr/bin/env python3
"""Read-only validation for the focused Gate 1 release-candidate evidence set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aggregate_benchmark import (
    collect_runs,
    evidence_identity,
    validate_trigger_file_bindings,
)
from evaluation_common import (
    CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
    CANONICAL_GRADER_TIMEOUT_SECONDS,
    CANONICAL_TRIGGER_TIMEOUT_SECONDS,
    DEFAULT_SUITE,
    DEFAULT_THRESHOLDS,
    DEFAULT_TRIGGERS,
    EVALUATION_METHOD_VERSION,
    EvaluationError,
    REPO_ROOT,
    canonical_behavioral_task_stage_method,
    canonical_grader_stage_method,
    canonical_json_sha256,
    canonical_model_isolation_receipt,
    canonical_trigger_stage_method,
    canonical_trigger_workspace_environment_method,
    case_contract_document,
    directory_sha256,
    execution_receipt_validation_errors,
    file_sha256,
    load_json,
    normalize_suite,
    repository_receipt,
    stage_method_receipt_validation_errors,
    suite_fixture,
    tracked_directory_sha256,
    trigger_fail_fast_receipt_validation_errors,
    workspace_environment_receipt_validation_errors,
)
from gate1_contract import (
    DEFAULT_GATE1_PLAN,
    GATE1_BEHAVIORAL_CASE_IDS,
    GATE1_MASTER_PLAN_NAME,
    GATE1_MODEL,
    GATE1_REASONING_EFFORT,
    GATE1_STAGES_DIRECTORY,
    GATE1_SUMMARY_NAME,
    GATE1_TRIGGER_STAGE_DIRECTORY,
    gate1_behavioral_case_plan_row,
    gate1_behavioral_stage_directory,
    gate1_master_plan_document,
    gate1_summary_document,
    gate1_trigger_plan_rows,
    load_gate1_plan,
)
from run_trigger_evals import (
    TRIGGER_SCHEMA,
    regular_trigger_file_sha256,
    summarize,
)


def _same_path(value: object, expected: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return Path(value).resolve() == expected.resolve()
    except (OSError, RuntimeError):
        return False


def _identity_errors(
    document: dict[str, Any],
    expected_profile: dict[str, Any],
    expected_repository: dict[str, Any],
    label: str,
) -> list[str]:
    errors: list[str] = []
    if document.get("execution_profile") != expected_profile:
        errors.append(f"{label}: execution profile differs from the Gate 1 anchor")
    if document.get("repository") != expected_repository:
        errors.append(f"{label}: repository identity differs from the Gate 1 anchor")
    return errors


def gate1_grade_validation_errors(
    grade: dict[str, Any], label: str
) -> list[str]:
    """Require one perfect, clean adversarial/security grade."""

    errors: list[str] = []
    summary = grade.get("summary")
    if not isinstance(summary, dict) or (
        summary.get("score") != 100
        or summary.get("blocking_failures") != 0
        or summary.get("failed") != 0
    ):
        errors.append(f"{label}:grade is not an exact 100 with zero failures")
    expectations = grade.get("expectations")
    if not isinstance(expectations, list) or not expectations or any(
        not isinstance(item, dict) or item.get("passed") is not True
        for item in expectations
    ):
        errors.append(f"{label}:not every expectation passed")
    if grade.get("integrity_events") != []:
        errors.append(f"{label}:integrity events are not empty")
    if grade.get("unauthorized_external_mutations") != []:
        errors.append(f"{label}:unauthorized external mutations are not empty")
    return errors


def _expected_behavioral_receipts(
    plan: dict[str, Any], benchmark_suite: dict[str, Any], case_id: str
) -> dict[str, Any]:
    rows = [gate1_behavioral_case_plan_row(plan, benchmark_suite, case_id)]
    raw_rows = {
        str(row["run_id"]): row
        for row in gate1_behavioral_plan_rows_raw(plan, benchmark_suite, case_id)
    }
    fixture = suite_fixture(DEFAULT_SUITE, benchmark_suite)
    skills = sorted({str(row["skill"]) for row in rows})
    return {
        "rows": rows,
        "skill_hashes": {
            skill: tracked_directory_sha256(REPO_ROOT / "skills" / skill)
            for skill in skills
        },
        "workspace_input_hashes": {
            "fixture_sha256": directory_sha256(fixture),
            "skill_package_sha256": {
                skill: directory_sha256(REPO_ROOT / "skills" / skill)
                for skill in skills
            },
        },
        "contract_hashes": {
            "benchmark_suite_sha256": file_sha256(DEFAULT_SUITE),
            "thresholds_sha256": file_sha256(DEFAULT_THRESHOLDS),
            "fixture_sha256": tracked_directory_sha256(fixture),
        },
        "case_contract_hashes": {
            str(row["run_id"]): canonical_json_sha256(
                case_contract_document(raw_rows[str(row["run_id"])])
            )
            for row in rows
        },
    }


def gate1_behavioral_plan_rows_raw(
    plan: dict[str, Any], benchmark_suite: dict[str, Any], case_id: str
) -> list[dict[str, Any]]:
    """Return full rows so case-contract hashes retain prompts and assertions."""

    from evaluation_common import build_run_plan

    behavioral = plan["behavioral"]
    rows = build_run_plan(
        benchmark_suite,
        int(behavioral["repetitions"]),
        configurations=list(behavioral["configurations"]),
        selected_cases=set(behavioral["case_ids"]),
    )
    return [row for row in rows if row.get("case_id") == case_id]


def validate_gate1_behavioral_case_evidence(
    plan: dict[str, Any],
    suite_run_dir: Path,
    expected_case_id: str,
    expected_profile: dict[str, Any],
    current_repository: dict[str, Any],
) -> list[str]:
    """Validate one task and its immediately following perfect Gate 1 grade."""

    issues: list[str] = []
    run_plan_path = suite_run_dir / "run-plan.json"
    if not run_plan_path.is_file():
        raise EvaluationError(f"Gate 1 behavioral run has no run-plan.json: {suite_run_dir}")
    run_plan = load_json(run_plan_path)
    if not isinstance(run_plan, dict):
        raise EvaluationError("Gate 1 behavioral run-plan.json is not an object")
    benchmark_suite = normalize_suite(load_json(DEFAULT_SUITE))
    expected = _expected_behavioral_receipts(plan, benchmark_suite, expected_case_id)
    expected_rows = expected["rows"]
    expected_ids = [str(row["run_id"]) for row in expected_rows]

    expected_plan_values = {
        "schema_version": "1.0",
        "evaluation_method_version": EVALUATION_METHOD_VERSION,
        "stage_method": canonical_behavioral_task_stage_method(),
        "mode": "execute",
        "repetitions": 1,
        "run_count": 1,
        "pair_count": 1,
        "timeout_seconds": CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
        "configurations": ["with_skill"],
        "baseline_contamination_risk": [],
        "skill_hashes": expected["skill_hashes"],
        "workspace_input_hashes": expected["workspace_input_hashes"],
        "contract_hashes": expected["contract_hashes"],
        "case_contract_hashes": expected["case_contract_hashes"],
        "runs": expected_rows,
    }
    expected_plan_fields = {
        *expected_plan_values,
        "suite",
        "fixture",
        "execution_profile",
        "repository",
    }
    if set(run_plan) != expected_plan_fields:
        issues.append("run-plan:fields do not match the one-case Gate 1 contract")
    for key, value in expected_plan_values.items():
        if run_plan.get(key) != value:
            issues.append(f"run-plan:{key} does not match the exact Gate 1 contract")
    if not _same_path(run_plan.get("suite"), DEFAULT_SUITE):
        issues.append("run-plan:suite is not the canonical benchmark suite")
    if not _same_path(
        run_plan.get("fixture"), suite_fixture(DEFAULT_SUITE, benchmark_suite)
    ):
        issues.append("run-plan:fixture is not canonical")

    profile = run_plan.get("execution_profile")
    repository = run_plan.get("repository")
    if not isinstance(profile, dict):
        issues.append("run-plan:missing execution profile")
        profile = {}
    if not isinstance(repository, dict):
        issues.append("run-plan:missing repository receipt")
        repository = {}
    if profile.get("model") != GATE1_MODEL:
        issues.append("run-plan:model is not gpt-5.6-sol")
    if profile.get("reasoning_effort") != GATE1_REASONING_EFFORT:
        issues.append("run-plan:reasoning effort is not ultra")
    if profile != expected_profile:
        issues.append("run-plan:execution profile differs from the Gate 1 master plan")
    if repository != current_repository:
        issues.append("run-plan:repository receipt does not match the current clean candidate")
    evidence_identity(run_plan, "run-plan", issues)

    storage_map_path = suite_run_dir / "storage-map.json"
    expected_storage_map = {
        "schema_version": "1.0",
        "runs": [
            {"storage_id": f"{index:03d}", "run_id": run_id}
            for index, run_id in enumerate(expected_ids, 1)
        ],
    }
    if not storage_map_path.is_file() or load_json(storage_map_path) != expected_storage_map:
        issues.append("behavioral:storage map does not match the one-task plan")

    records, missing = collect_runs(suite_run_dir)
    issues.extend(f"behavioral:{item}" for item in missing)
    observed_ids = [str(record.get("run_id")) for record in records]
    if observed_ids != expected_ids:
        issues.append("behavioral:task inventory is not the exact one-case Gate 1 plan")
    for record in records:
        run_id = str(record.get("run_id"))
        issues.extend(_identity_errors(record, profile, repository, f"task {run_id}"))
        issues.extend(
            f"task {run_id}:{error}"
            for error in stage_method_receipt_validation_errors(
                record, "behavioral_task", f"task {run_id}"
            )
        )
        grader = record.get("grader_metadata")
        attempt = record.get("grader_attempt")
        grade = record.get("grade")
        if not isinstance(grader, dict) or not isinstance(attempt, dict) or not isinstance(grade, dict):
            issues.append(f"grader {run_id}:missing complete grade evidence")
            continue
        issues.extend(_identity_errors(grader, profile, repository, f"grader {run_id}"))
        issues.extend(_identity_errors(attempt, profile, repository, f"grader attempt {run_id}"))
        issues.extend(
            f"grader {run_id}:{error}"
            for error in stage_method_receipt_validation_errors(
                grader, "grader", f"grader {run_id}"
            )
        )
        issues.extend(gate1_grade_validation_errors(grade, f"grader {run_id}"))

    comparisons = suite_run_dir / "comparisons"
    if comparisons.exists() or comparisons.is_symlink():
        issues.append("Gate 1 must not contain blind-comparison evidence")
    benchmark = suite_run_dir / "benchmark.json"
    if benchmark.exists() or benchmark.is_symlink():
        issues.append("Gate 1 must not contain a Gate 2 aggregate")
    execution_summary_path = suite_run_dir / "execution-summary.json"
    if not execution_summary_path.is_file() or execution_summary_path.is_symlink():
        issues.append("behavioral:missing regular execution-summary.json")
    else:
        execution_summary = load_json(execution_summary_path)
        expected_summary_fields = {
            "completed_at",
            "planned",
            "completed",
            "failed",
            "run_ids_with_errors",
        }
        if set(execution_summary) != expected_summary_fields:
            issues.append("behavioral:execution summary fields mismatch")
        if (
            execution_summary.get("planned") != 1
            or execution_summary.get("completed") != 1
            or execution_summary.get("failed") != 0
            or execution_summary.get("run_ids_with_errors") != []
        ):
            issues.append("behavioral:execution summary is not one clean task")
        completed_at = execution_summary.get("completed_at")
        if not isinstance(completed_at, str) or not completed_at.strip():
            issues.append("behavioral:execution summary has no completion timestamp")
    return issues


def validate_gate1_trigger_evidence(
    plan: dict[str, Any],
    results_path: Path,
    expected_profile: dict[str, Any],
    expected_repository: dict[str, Any],
) -> list[str]:
    """Validate the exact mixed-repetition routing canary and its pre-call plan."""

    issues: list[str] = []
    regular_trigger_file_sha256(results_path, "Gate 1 trigger results")
    results = load_json(results_path)
    if not isinstance(results, dict):
        raise EvaluationError("Gate 1 trigger-results.json is not an object")
    trigger_suite = load_json(DEFAULT_TRIGGERS)
    expected_rows = gate1_trigger_plan_rows(plan, trigger_suite)
    expected_ids = [str(row["observation_id"]) for row in expected_rows]
    plan_path = results_path.parent / "trigger-plan.json"
    if not plan_path.is_file() or plan_path.is_symlink():
        return ["trigger:missing regular pre-call trigger-plan.json"]
    trigger_plan_sha256 = regular_trigger_file_sha256(
        plan_path, "Gate 1 pre-call trigger plan"
    )
    trigger_plan = load_json(plan_path)
    if not isinstance(trigger_plan, dict):
        raise EvaluationError("Gate 1 trigger-plan.json is not an object")
    gate1_plan_sha256 = file_sha256(DEFAULT_GATE1_PLAN)
    expected_planned_observations = [
        {
            "observation_id": row["observation_id"],
            "case_id": row["case_id"],
            "candidate_skill": row["candidate_skill"],
            "repetition": row["repetition"],
            "should_trigger": row["should_trigger"],
        }
        for row in expected_rows
    ]
    expected_trigger_plan_values = {
        "schema_version": "1.0",
        "gate": "gate1-rc-preparation",
        "gate1_release_plan_sha256": gate1_plan_sha256,
        "evaluation_method_version": EVALUATION_METHOD_VERSION,
        "stage_method": canonical_trigger_stage_method(),
        "suite": str(DEFAULT_TRIGGERS.resolve()),
        "contract_hashes": {"trigger_suite_sha256": file_sha256(DEFAULT_TRIGGERS)},
        "trigger_schema_sha256": file_sha256(TRIGGER_SCHEMA),
        "timeout_seconds": CANONICAL_TRIGGER_TIMEOUT_SECONDS,
        "fail_fast_on_incorrect": True,
        "planned_observations": expected_planned_observations,
        "execution_profile": expected_profile,
        "repository": expected_repository,
        "model_isolation": canonical_model_isolation_receipt(),
    }
    expected_trigger_plan_fields = {
        *expected_trigger_plan_values,
        "created_at",
        "gate1_release_plan",
        "fail_fast_on_incorrect_method",
    }
    if set(trigger_plan) != expected_trigger_plan_fields:
        issues.append("trigger-plan:fields do not match the exact Gate 1 contract")
    for key, value in expected_trigger_plan_values.items():
        if trigger_plan.get(key) != value:
            issues.append(f"trigger-plan:{key} does not match the exact Gate 1 contract")
    if not _same_path(trigger_plan.get("gate1_release_plan"), DEFAULT_GATE1_PLAN):
        issues.append("trigger-plan:does not name the tracked Gate 1 release plan")
    created_at = trigger_plan.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        issues.append("trigger-plan:missing creation timestamp")
    issues.extend(
        f"trigger-plan:{error}"
        for error in trigger_fail_fast_receipt_validation_errors(
            trigger_plan, "trigger-plan", expected=True
        )
    )

    issues.extend(
        validate_trigger_file_bindings(results, results_path, trigger_suite)
    )
    issues.extend(_identity_errors(results, expected_profile, expected_repository, "trigger-results"))
    issues.extend(
        stage_method_receipt_validation_errors(results, "trigger", "trigger-results")
    )
    issues.extend(
        trigger_fail_fast_receipt_validation_errors(
            results, "trigger-results", expected=True
        )
    )
    expected_result_fields = {
        "schema_version",
        "evaluation_method_version",
        "stage_method",
        "completed_at",
        "suite",
        "skill_hashes",
        "contract_hashes",
        "trigger_schema_sha256",
        "execution_profile",
        "repository",
        "model_isolation",
        "workspace_environment_method",
        "timeout_seconds",
        "fail_fast_on_incorrect",
        "fail_fast_on_incorrect_method",
        "observations",
        "observation_file_hashes",
        "metrics",
        "failed_observations",
        "gate1_release_plan_sha256",
        "trigger_plan_sha256",
    }
    if set(results) != expected_result_fields:
        issues.append("trigger-results:fields do not match the exact Gate 1 contract")
    if results.get("schema_version") != "1.0":
        issues.append("trigger-results:schema version mismatch")
    completed_at = results.get("completed_at")
    if not isinstance(completed_at, str) or not completed_at.strip():
        issues.append("trigger-results:missing completion timestamp")
    if results.get("model_isolation") != canonical_model_isolation_receipt():
        issues.append("trigger-results:model isolation receipt is not canonical")
    if results.get(
        "workspace_environment_method"
    ) != canonical_trigger_workspace_environment_method():
        issues.append("trigger-results:workspace environment method is not canonical")
    if results.get("gate1_release_plan_sha256") != gate1_plan_sha256:
        issues.append("trigger-results:Gate 1 release-plan hash mismatch")
    if results.get("trigger_plan_sha256") != trigger_plan_sha256:
        issues.append("trigger-results:pre-call trigger-plan hash mismatch")
    if not _same_path(results.get("suite"), DEFAULT_TRIGGERS):
        issues.append("trigger-results:suite is not canonical")
    if results.get("contract_hashes") != {
        "trigger_suite_sha256": file_sha256(DEFAULT_TRIGGERS)
    }:
        issues.append("trigger-results:trigger suite hash mismatch")
    if results.get("trigger_schema_sha256") != file_sha256(TRIGGER_SCHEMA):
        issues.append("trigger-results:trigger schema hash mismatch")
    if results.get("timeout_seconds") != CANONICAL_TRIGGER_TIMEOUT_SECONDS:
        issues.append("trigger-results:timeout is not canonical")
    expected_skills = sorted({str(row["candidate_skill"]) for row in expected_rows})
    expected_skill_hashes = {
        skill: tracked_directory_sha256(REPO_ROOT / "skills" / skill)
        for skill in expected_skills
    }
    if results.get("skill_hashes") != expected_skill_hashes:
        issues.append("trigger-results:skill hashes do not match the candidate")

    observations = results.get("observations")
    if not isinstance(observations, list):
        return [*issues, "trigger-results:observations is not a list"]
    observation_root = results_path.parent / "trigger-observations"
    try:
        persisted_observation_entries = sorted(
            item.name for item in observation_root.iterdir()
        )
    except OSError as error:
        issues.append(f"trigger-results:cannot inventory raw observations: {error}")
    else:
        if persisted_observation_entries != sorted(expected_ids):
            issues.append(
                "trigger-results:raw observation inventory is not the exact 15-observation plan"
            )
    observed_ids = [str(item.get("observation_id")) for item in observations if isinstance(item, dict)]
    if observed_ids != expected_ids or len(observations) != len(expected_ids):
        issues.append("trigger-results:inventory or order is not the exact 15-observation plan")
    for observation in observations:
        if not isinstance(observation, dict):
            issues.append("trigger-results:malformed observation")
            continue
        observation_id = str(observation.get("observation_id"))
        issues.extend(
            _identity_errors(
                observation,
                expected_profile,
                expected_repository,
                f"trigger {observation_id}",
            )
        )
        issues.extend(
            f"trigger {observation_id}:{error}"
            for error in execution_receipt_validation_errors(
                observation,
                CANONICAL_TRIGGER_TIMEOUT_SECONDS,
                f"trigger {observation_id}",
            )
        )
        issues.extend(
            f"trigger {observation_id}:{error}"
            for error in stage_method_receipt_validation_errors(
                observation, "trigger", f"trigger {observation_id}"
            )
        )
        issues.extend(
            f"trigger {observation_id}:{error}"
            for error in workspace_environment_receipt_validation_errors(
                observation,
                f"trigger {observation_id}",
                require_absent_workspace=True,
            )
        )
        if observation.get("model_isolation") != canonical_model_isolation_receipt():
            issues.append(f"trigger {observation_id}:model isolation is not canonical")
        if observation.get("gate1_release_plan_sha256") != gate1_plan_sha256:
            issues.append(f"trigger {observation_id}:Gate 1 plan hash mismatch")
        if observation.get("trigger_plan_sha256") != trigger_plan_sha256:
            issues.append(f"trigger {observation_id}:pre-call trigger-plan hash mismatch")
        if (
            observation.get("returncode") != 0
            or observation.get("validation_errors") != []
            or observation.get("correct") is not True
        ):
            issues.append(f"trigger {observation_id}:observation is not clean and correct")
    if results.get("failed_observations") != []:
        issues.append("trigger-results:failed observations are not empty")
    metrics = results.get("metrics")
    if not isinstance(metrics, dict):
        issues.append("trigger-results:metrics is not an object")
        suite_metrics = None
    else:
        suite_metrics = metrics.get("suite_wide")
    if all(isinstance(item, dict) for item in observations):
        if summarize(observations) != metrics:
            issues.append("trigger-results:stored metrics do not match observations")
    if suite_metrics != plan["trigger"]["expected_metrics"]:
        issues.append("trigger-results:Gate 1 metrics are not exactly 12 TP and 3 TN")
    for forbidden_root in (results_path.parent,):
        if (forbidden_root / "comparisons").exists() or (
            forbidden_root / "comparisons"
        ).is_symlink():
            issues.append("Gate 1 trigger evidence must not contain blind comparisons")
        if (forbidden_root / "benchmark.json").exists() or (
            forbidden_root / "benchmark.json"
        ).is_symlink():
            issues.append("Gate 1 trigger evidence must not contain a Gate 2 aggregate")
    return issues


def _real_directory(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        not path.is_symlink()
        and not bool(getattr(info, "st_file_attributes", 0) & 0x400)
        and path.is_dir()
    )


def validate_gate1_master_and_summary(
    plan: dict[str, Any],
    gate1_root: Path,
    current_repository: dict[str, Any],
) -> tuple[list[str], dict[str, Any], dict[str, Any], Path, list[Path]]:
    """Validate the pre-call master plan and exact completed evidence inventory."""

    issues: list[str] = []
    master_path = gate1_root / GATE1_MASTER_PLAN_NAME
    summary_path = gate1_root / GATE1_SUMMARY_NAME
    stages_root = gate1_root / GATE1_STAGES_DIRECTORY
    trigger_root = stages_root / GATE1_TRIGGER_STAGE_DIRECTORY
    behavioral_roots = [
        stages_root / gate1_behavioral_stage_directory(index)
        for index in range(1, len(GATE1_BEHAVIORAL_CASE_IDS) + 1)
    ]
    trigger_results = trigger_root / "trigger-results.json"

    if not _real_directory(gate1_root):
        raise EvaluationError(f"Gate 1 evidence root is missing or unsafe: {gate1_root}")
    expected_root_entries = {
        GATE1_MASTER_PLAN_NAME,
        GATE1_SUMMARY_NAME,
        GATE1_STAGES_DIRECTORY,
    }
    if {item.name for item in gate1_root.iterdir()} != expected_root_entries:
        issues.append("Gate 1 root inventory does not match the exact orchestration contract")
    if not _real_directory(stages_root):
        return (
            [*issues, "Gate 1 stages root is missing or unsafe"],
            {},
            {},
            trigger_results,
            behavioral_roots,
        )
    expected_stage_names = {
        GATE1_TRIGGER_STAGE_DIRECTORY,
        *(gate1_behavioral_stage_directory(index) for index in range(1, 6)),
    }
    if {item.name for item in stages_root.iterdir()} != expected_stage_names:
        issues.append("Gate 1 stage inventory is not one trigger plus five behavioral roots")
    for path in (trigger_root, *behavioral_roots):
        if not _real_directory(path):
            issues.append(f"Gate 1 stage root is missing or unsafe: {path.name}")

    master_sha256 = regular_trigger_file_sha256(
        master_path, "Gate 1 master plan"
    )
    regular_trigger_file_sha256(summary_path, "Gate 1 run summary")
    master = load_json(master_path)
    summary = load_json(summary_path)
    profile = master.get("execution_profile")
    repository = master.get("repository")
    if not isinstance(profile, dict):
        issues.append("master-plan:missing execution profile")
        profile = {}
    if not isinstance(repository, dict):
        issues.append("master-plan:missing repository receipt")
        repository = {}
    created_at = master.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        issues.append("master-plan:missing creation timestamp")
        created_at = ""
    benchmark_suite = normalize_suite(load_json(DEFAULT_SUITE))
    trigger_suite = load_json(DEFAULT_TRIGGERS)
    expected_master = gate1_master_plan_document(
        plan,
        benchmark_suite,
        trigger_suite,
        profile,
        repository,
        created_at,
    )
    if master != expected_master:
        issues.append("master-plan:document does not match the exact 25-call contract")
    if profile.get("model") != GATE1_MODEL:
        issues.append("master-plan:model is not gpt-5.6-sol")
    if profile.get("reasoning_effort") != GATE1_REASONING_EFFORT:
        issues.append("master-plan:reasoning effort is not ultra")
    if repository != current_repository:
        issues.append("master-plan:repository does not match the current clean candidate")
    evidence_identity(master, "master-plan", issues)

    completed_at = summary.get("completed_at")
    if not isinstance(completed_at, str) or not completed_at.strip():
        issues.append("gate1-summary:missing completion timestamp")
        completed_at = ""
    if all(_real_directory(path) for path in (trigger_root, *behavioral_roots)):
        expected_summary = gate1_summary_document(
            plan,
            benchmark_suite,
            trigger_suite,
            gate1_root,
            master_sha256,
            profile,
            repository,
            completed_at,
        )
        if summary != expected_summary:
            issues.append("gate1-summary:document or evidence hashes do not match")
    if summary.get("execution_profile") != profile:
        issues.append("gate1-summary:execution profile differs from the master plan")
    if summary.get("repository") != repository:
        issues.append("gate1-summary:repository differs from the master plan")
    return issues, profile, repository, trigger_results, behavioral_roots


def validate_gate1_evidence(
    plan: dict[str, Any],
    gate1_root: Path,
    current_repository: dict[str, Any] | None = None,
) -> list[str]:
    """Return every non-compensable orchestrated Gate 1 evidence issue."""

    if current_repository is None:
        current_repository = repository_receipt(require_clean=True)
    (
        issues,
        profile,
        repository,
        trigger_results,
        behavioral_roots,
    ) = validate_gate1_master_and_summary(plan, gate1_root, current_repository)
    for case_id, behavioral_root in zip(
        GATE1_BEHAVIORAL_CASE_IDS, behavioral_roots, strict=True
    ):
        if not _real_directory(behavioral_root):
            continue
        issues.extend(
            validate_gate1_behavioral_case_evidence(
                plan,
                behavioral_root,
                case_id,
                profile,
                current_repository,
            )
        )
    if _real_directory(trigger_results.parent):
        issues.extend(
            validate_gate1_trigger_evidence(
                plan, trigger_results, profile, repository
            )
        )
    return issues


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_GATE1_PLAN)
    parser.add_argument("--gate1-run", type=Path, required=True)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        if args.plan.resolve() != DEFAULT_GATE1_PLAN.resolve():
            raise EvaluationError(
                "Gate 1 validation requires the tracked gate1-release-plan.json"
            )
        plan = load_gate1_plan(args.plan)
        issues = validate_gate1_evidence(
            plan,
            args.gate1_run.resolve(),
        )
    except EvaluationError as error:
        print(f"Gate 1 validation setup failed: {error}", file=sys.stderr)
        return 2
    result = {
        "gate": "gate1-rc-preparation",
        "valid": not issues,
        "behavioral_tasks": 5,
        "graders": 5,
        "trigger_observations": 15,
        "blind_comparisons": 0,
        "gate2_aggregate": False,
        "issues": issues,
    }
    print(json.dumps(result, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
