#!/usr/bin/env python3
"""Bind release aggregation to the canonical evaluation contract and inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evaluation_common import (
    CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS,
    CANONICAL_TRIGGER_TIMEOUT_SECONDS,
    CODEX_INVOCATION_MODE,
    CODEX_TIMEOUT_ENFORCEMENT_MODE,
    DEFAULT_SUITE,
    DEFAULT_THRESHOLDS,
    DEFAULT_TRIGGERS,
    EVALUATION_METHOD_VERSION,
    EvaluationError,
    build_run_plan,
    canonical_json_sha256,
    canonical_behavioral_task_stage_method,
    canonical_trigger_stage_method,
    canonical_trigger_workspace_environment_method,
    case_contract_document,
    configuration_ids,
    configured_repetitions,
    directory_sha256,
    file_sha256,
    load_json,
    normalize_suite,
    persisted_run_plan_row,
    suite_fixture,
    tracked_directory_sha256,
    trigger_fail_fast_receipt_validation_errors,
)


CANONICAL_RUN_COUNT = 96
CANONICAL_PAIR_COUNT = 48
CANONICAL_PRIMARY_CASE_COUNT = 11
CANONICAL_ADVERSARIAL_CASE_COUNT = 5
CANONICAL_REPETITIONS = 3
CANONICAL_CONFIGURATIONS = ["with_skill", "without_skill"]
CANONICAL_TRIGGER_SCHEMA = DEFAULT_TRIGGERS.parent / "schemas" / "trigger-output.schema.json"


def canonical_contract_hashes() -> dict[str, str]:
    suite = normalize_suite(load_json(DEFAULT_SUITE))
    fixture = suite_fixture(DEFAULT_SUITE, suite)
    return {
        "benchmark_suite_sha256": file_sha256(DEFAULT_SUITE),
        "thresholds_sha256": file_sha256(DEFAULT_THRESHOLDS),
        "fixture_sha256": tracked_directory_sha256(fixture),
        "trigger_suite_sha256": file_sha256(DEFAULT_TRIGGERS),
    }


def canonical_plan_rows() -> list[dict[str, Any]]:
    suite = normalize_suite(load_json(DEFAULT_SUITE))
    thresholds = load_json(DEFAULT_THRESHOLDS)
    repetitions = configured_repetitions(suite, thresholds)
    configurations = configuration_ids(suite)
    primary_count = len(suite.get("primary_cases", []))
    adversarial_count = len(suite.get("adversarial_cases", []))
    if (
        primary_count != CANONICAL_PRIMARY_CASE_COUNT
        or adversarial_count != CANONICAL_ADVERSARIAL_CASE_COUNT
        or repetitions != CANONICAL_REPETITIONS
        or configurations != CANONICAL_CONFIGURATIONS
    ):
        raise EvaluationError(
            "Canonical evaluation assets no longer match the release contract: "
            f"primary={primary_count}, adversarial={adversarial_count}, "
            f"repetitions={repetitions}, configurations={configurations}"
        )
    rows = build_run_plan(suite, repetitions, configurations=configurations)
    if len(rows) != CANONICAL_RUN_COUNT:
        raise EvaluationError(
            f"Canonical evaluation plan must contain {CANONICAL_RUN_COUNT} runs, got {len(rows)}"
        )
    return [persisted_run_plan_row(row) for row in rows]


def canonical_case_contract_hashes() -> dict[str, str]:
    suite = normalize_suite(load_json(DEFAULT_SUITE))
    thresholds = load_json(DEFAULT_THRESHOLDS)
    rows = build_run_plan(
        suite,
        configured_repetitions(suite, thresholds),
        configurations=configuration_ids(suite),
    )
    return {
        row["run_id"]: canonical_json_sha256(case_contract_document(row)) for row in rows
    }


def canonical_workspace_input_hashes() -> dict[str, Any]:
    suite = normalize_suite(load_json(DEFAULT_SUITE))
    fixture = suite_fixture(DEFAULT_SUITE, suite)
    skills = sorted(
        {
            row["skill"]
            for row in build_run_plan(
                suite,
                configured_repetitions(suite, load_json(DEFAULT_THRESHOLDS)),
                configurations=configuration_ids(suite),
            )
        }
    )
    return {
        "fixture_sha256": directory_sha256(fixture),
        "skill_package_sha256": {
            skill: directory_sha256(DEFAULT_SUITE.parents[1] / "skills" / skill)
            for skill in skills
        },
    }


def _same_resolved_path(value: Any, expected: Path) -> bool:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return False
    try:
        return Path(value).resolve() == expected.resolve()
    except (OSError, RuntimeError):
        return False


def validate_release_eval_plan(
    plan: dict[str, Any],
    trigger_results: dict[str, Any] | None,
    thresholds_path: Path,
    trigger_suite_path: Path,
) -> list[str]:
    """Return non-compensable reasons an evaluation is diagnostic-only."""

    issues: list[str] = []
    canonical_hashes = canonical_contract_hashes()
    canonical_suite = normalize_suite(load_json(DEFAULT_SUITE))
    canonical_fixture = suite_fixture(DEFAULT_SUITE, canonical_suite)
    expected_rows = canonical_plan_rows()
    expected_case_contract_hashes = canonical_case_contract_hashes()
    expected_workspace_inputs = canonical_workspace_input_hashes()

    if not _same_resolved_path(plan.get("suite"), DEFAULT_SUITE):
        issues.append("release-contract:benchmark suite is not the tracked default")
    if not _same_resolved_path(plan.get("fixture"), canonical_fixture):
        issues.append("release-contract:fixture is not the canonical fixture")
    if not _same_resolved_path(thresholds_path, DEFAULT_THRESHOLDS):
        issues.append("release-contract:thresholds are not the tracked default")
    if not _same_resolved_path(trigger_suite_path, DEFAULT_TRIGGERS):
        issues.append("release-contract:trigger suite is not the tracked default")

    expected_behavioral_hashes = {
        key: canonical_hashes[key]
        for key in ("benchmark_suite_sha256", "thresholds_sha256", "fixture_sha256")
    }
    if plan.get("contract_hashes") != expected_behavioral_hashes:
        issues.append("release-contract:behavioral input receipts do not match canonical SHA256 values")

    if (
        plan.get("evaluation_method_version") != EVALUATION_METHOD_VERSION
        or plan.get("stage_method") != canonical_behavioral_task_stage_method()
    ):
        issues.append("release-contract:behavioral evaluation method is not canonical")

    if (
        plan.get("mode") != "execute"
        or plan.get("repetitions") != CANONICAL_REPETITIONS
        or plan.get("configurations") != CANONICAL_CONFIGURATIONS
        or plan.get("run_count") != CANONICAL_RUN_COUNT
        or plan.get("pair_count") != CANONICAL_PAIR_COUNT
        or plan.get("timeout_seconds") != CANONICAL_BEHAVIORAL_TIMEOUT_SECONDS
        or plan.get("runs") != expected_rows
        or plan.get("case_contract_hashes") != expected_case_contract_hashes
        or plan.get("workspace_input_hashes") != expected_workspace_inputs
    ):
        issues.append("release-contract:behavioral plan is not the exact canonical 96-run plan")
    if plan.get("baseline_contamination_risk") != []:
        issues.append("release-contract:baseline contamination risk must be empty")
    profile = plan.get("execution_profile")
    if (
        not isinstance(profile, dict)
        or profile.get("codex_invocation") != CODEX_INVOCATION_MODE
        or profile.get("codex_timeout_enforcement") != CODEX_TIMEOUT_ENFORCEMENT_MODE
    ):
        issues.append("release-contract:execution method is not canonical")

    if trigger_results is not None:
        if (
            trigger_results.get("evaluation_method_version")
            != EVALUATION_METHOD_VERSION
            or trigger_results.get("stage_method") != canonical_trigger_stage_method()
        ):
            issues.append(
                "release-contract:trigger evaluation method is not canonical"
            )
        if not _same_resolved_path(trigger_results.get("suite"), DEFAULT_TRIGGERS):
            issues.append("release-contract:trigger results did not use the tracked default suite")
        expected_trigger_hashes = {
            "trigger_suite_sha256": canonical_hashes["trigger_suite_sha256"]
        }
        if trigger_results.get("contract_hashes") != expected_trigger_hashes:
            issues.append("release-contract:trigger input receipt does not match the canonical SHA256")
        if trigger_results.get("timeout_seconds") != CANONICAL_TRIGGER_TIMEOUT_SECONDS:
            issues.append("release-contract:trigger timeout is not canonical")
        if trigger_fail_fast_receipt_validation_errors(
            trigger_results, "trigger-results", expected=False
        ):
            issues.append(
                "release-contract:Gate 2 trigger fail-fast policy is not canonical"
            )
        if trigger_results.get("trigger_schema_sha256") != file_sha256(
            CANONICAL_TRIGGER_SCHEMA
        ):
            issues.append(
                "release-contract:trigger output schema receipt is not canonical"
            )
        if trigger_results.get(
            "workspace_environment_method"
        ) != canonical_trigger_workspace_environment_method():
            issues.append(
                "release-contract:trigger workspace-environment method is not canonical"
            )

    return issues
