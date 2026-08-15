#!/usr/bin/env python3
"""Run the exact no-retry, semantically fail-fast Gate 1 evidence sequence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from evaluation_common import (
    DEFAULT_SUITE,
    DEFAULT_THRESHOLDS,
    DEFAULT_TRIGGERS,
    EVAL_ROOT,
    REPO_ROOT,
    EvaluationError,
    codex_execution_profile,
    file_sha256,
    find_codex_command,
    load_json,
    normalize_suite,
    repository_receipt,
    require_unchanged_repository,
    timestamp_id,
    utc_now,
    validate_output_root,
    write_json_exclusive,
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
    gate1_master_call_plan,
    gate1_master_plan_document,
    gate1_summary_document,
    load_gate1_plan,
)
from validate_gate1_evidence import (
    validate_gate1_behavioral_case_evidence,
    validate_gate1_evidence,
    validate_gate1_trigger_evidence,
)


def _run_stage_command(command: list[str], label: str) -> None:
    """Run one synchronous stage command and stop on any nonzero result."""

    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise EvaluationError(f"{label} failed with exit code {result.returncode}")


def _common_profile_arguments(codex_command: str) -> list[str]:
    return [
        "--codex-command",
        codex_command,
        "--model",
        GATE1_MODEL,
        "--reasoning-effort",
        GATE1_REASONING_EFFORT,
    ]


def run_gate1_model_sequence(
    plan: dict[str, Any],
    benchmark_suite: dict[str, Any],
    trigger_suite: dict[str, Any],
    gate1_root: Path,
    codex_command: str,
    execution_profile: dict[str, Any],
    repository: dict[str, Any],
    completed_call_ids: list[str],
) -> None:
    """Execute trigger, then five task/grader pairs with semantic checks between pairs."""

    stages_root = gate1_root / GATE1_STAGES_DIRECTORY
    trigger_root = stages_root / GATE1_TRIGGER_STAGE_DIRECTORY
    python = str(Path(sys.executable).resolve())
    profile_arguments = _common_profile_arguments(codex_command)
    trigger_command = [
        python,
        str((REPO_ROOT / "scripts" / "run_trigger_evals.py").resolve()),
        "--execute",
        "--observation-plan",
        str(DEFAULT_GATE1_PLAN.resolve()),
        "--fail-fast-on-incorrect",
        "--output-root",
        str(stages_root),
        "--run-id",
        GATE1_TRIGGER_STAGE_DIRECTORY,
        *profile_arguments,
    ]
    _run_stage_command(trigger_command, "Gate 1 trigger canary")
    require_unchanged_repository(repository)
    trigger_issues = validate_gate1_trigger_evidence(
        plan,
        trigger_root / "trigger-results.json",
        execution_profile,
        repository,
    )
    if trigger_issues:
        raise EvaluationError(
            "Gate 1 trigger canary is not release-eligible:\n- "
            + "\n- ".join(trigger_issues)
        )
    calls = gate1_master_call_plan(plan, benchmark_suite, trigger_suite)
    completed_call_ids.extend(
        str(call["call_id"]) for call in calls if call["stage"] == "trigger"
    )

    for index, case_id in enumerate(GATE1_BEHAVIORAL_CASE_IDS, 1):
        stage_name = gate1_behavioral_stage_directory(index)
        behavioral_root = stages_root / stage_name
        row = gate1_behavioral_case_plan_row(plan, benchmark_suite, case_id)
        task_command = [
            python,
            str((REPO_ROOT / "scripts" / "run_behavioral_benchmark.py").resolve()),
            "--execute",
            "--suite",
            str(DEFAULT_SUITE.resolve()),
            "--thresholds",
            str(DEFAULT_THRESHOLDS.resolve()),
            "--configuration",
            "with_skill",
            "--repetitions",
            "1",
            "--case",
            case_id,
            "--output-root",
            str(stages_root),
            "--run-id",
            stage_name,
            *profile_arguments,
        ]
        _run_stage_command(task_command, f"Gate 1 task {case_id}")
        require_unchanged_repository(repository)
        completed_call_ids.append(f"task:{row['run_id']}")

        grader_command = [
            python,
            str((REPO_ROOT / "scripts" / "grade_behavioral_benchmark.py").resolve()),
            str(behavioral_root),
            "--execute",
            *profile_arguments,
        ]
        _run_stage_command(grader_command, f"Gate 1 grader {case_id}")
        require_unchanged_repository(repository)
        case_issues = validate_gate1_behavioral_case_evidence(
            plan,
            behavioral_root,
            case_id,
            execution_profile,
            repository,
        )
        if case_issues:
            raise EvaluationError(
                f"Gate 1 grade for {case_id} is not perfect and clean:\n- "
                + "\n- ".join(case_issues)
            )
        completed_call_ids.append(f"grader:{row['run_id']}")

    expected_call_ids = [str(call["call_id"]) for call in calls]
    if completed_call_ids != expected_call_ids:
        raise EvaluationError("Gate 1 completed-call order differs from the master plan")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_GATE1_PLAN)
    parser.add_argument("--output-root", type=Path, default=EVAL_ROOT / "runs")
    parser.add_argument("--run-id")
    parser.add_argument("--codex-command")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--show-plan", action="store_true")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    gate1_root: Path | None = None
    master_sha256: str | None = None
    completed_call_ids: list[str] = []
    try:
        if args.plan.resolve() != DEFAULT_GATE1_PLAN.resolve():
            raise EvaluationError(
                "Gate 1 orchestration requires the tracked gate1-release-plan.json"
            )
        plan = load_gate1_plan(args.plan)
        benchmark_suite = normalize_suite(load_json(DEFAULT_SUITE))
        trigger_suite = load_json(DEFAULT_TRIGGERS)
        calls = gate1_master_call_plan(plan, benchmark_suite, trigger_suite)
        if not args.execute:
            result: dict[str, Any] = {
                "mode": "dry-run",
                "gate": "gate1-rc-preparation",
                "model": GATE1_MODEL,
                "reasoning_effort": GATE1_REASONING_EFFORT,
                "model_call_count": len(calls),
                "trigger_calls": 15,
                "behavioral_task_calls": 5,
                "grader_calls": 5,
                "retry_policy": plan["orchestration"]["retry_policy"],
            }
            if args.show_plan:
                result["calls"] = calls
            print(json.dumps(result, indent=2))
            return 0

        output_root = validate_output_root(args.output_root)
        run_id = args.run_id or timestamp_id("gate1")
        gate1_root = output_root / run_id
        if gate1_root.exists() or gate1_root.is_symlink():
            raise EvaluationError(f"Refusing to resume or overwrite Gate 1 run: {gate1_root}")
        codex_command = find_codex_command(args.codex_command)
        execution_profile = codex_execution_profile(
            codex_command, GATE1_MODEL, GATE1_REASONING_EFFORT
        )
        repository = repository_receipt(require_clean=True)
        gate1_root.mkdir(parents=True)
        master = gate1_master_plan_document(
            plan,
            benchmark_suite,
            trigger_suite,
            execution_profile,
            repository,
            utc_now(),
        )
        master_path = gate1_root / GATE1_MASTER_PLAN_NAME
        write_json_exclusive(master_path, master)
        master_sha256 = file_sha256(master_path)

        run_gate1_model_sequence(
            plan,
            benchmark_suite,
            trigger_suite,
            gate1_root,
            codex_command,
            execution_profile,
            repository,
            completed_call_ids,
        )
        require_unchanged_repository(repository)
        summary = gate1_summary_document(
            plan,
            benchmark_suite,
            trigger_suite,
            gate1_root,
            master_sha256,
            execution_profile,
            repository,
            utc_now(),
        )
        write_json_exclusive(gate1_root / GATE1_SUMMARY_NAME, summary)
        issues = validate_gate1_evidence(plan, gate1_root, repository)
        if issues:
            raise EvaluationError(
                "Final Gate 1 validation failed:\n- " + "\n- ".join(issues)
            )
        print(
            json.dumps(
                {
                    "gate": "gate1-rc-preparation",
                    "valid": True,
                    "model_calls": 25,
                    "retries": 0,
                    "evidence_root": str(gate1_root),
                    "master_plan_sha256": master_sha256,
                },
                indent=2,
            )
        )
        return 0
    except EvaluationError as error:
        if gate1_root is not None and gate1_root.is_dir():
            failure_path = gate1_root / "gate1-failure.json"
            if not failure_path.exists() and not failure_path.is_symlink():
                write_json_exclusive(
                    failure_path,
                    {
                        "schema_version": "1.0",
                        "gate": "gate1-rc-preparation",
                        "failed_at": utc_now(),
                        "error": str(error),
                        "master_plan_sha256": master_sha256,
                        "validated_completed_call_ids": completed_call_ids,
                        "retry_allowed": False,
                        "discard_entire_root": True,
                    },
                )
        print(f"Gate 1 orchestration failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
