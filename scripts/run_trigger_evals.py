#!/usr/bin/env python3
"""Plan or execute repeated, fresh-context skill triggering evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import stat
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation_common import (
    CANONICAL_TRIGGER_TIMEOUT_SECONDS,
    DEFAULT_SUITE,
    DEFAULT_TRIGGERS,
    EVAL_ROOT,
    EVALUATION_METHOD_VERSION,
    EvaluationError,
    REPO_ROOT,
    REASONING_EFFORTS,
    TRIGGER_FAIL_FAST_ON_INCORRECT_METHOD,
    baseline_contamination_paths,
    canonical_model_isolation_receipt,
    canonical_trigger_stage_method,
    canonical_trigger_workspace_environment_method,
    codex_execution_profile,
    codex_base_command,
    codex_runtime_command,
    directory_sha256,
    file_sha256,
    execution_receipt_validation_errors,
    find_codex_command,
    lstat_path_entry_exists,
    load_json,
    normalize_suite,
    parse_skill_description,
    repository_receipt,
    require_isolated_model_invocation,
    require_pinned_profile,
    require_unchanged_repository,
    run_codex,
    timestamp_id,
    task_runtime_environment,
    task_trace_isolation_validation_errors,
    token_usage_from_jsonl,
    tracked_directory_sha256,
    utc_now,
    validate_output_root,
    workspace_environment_receipt,
    write_json,
    write_json_exclusive,
)
from gate1_contract import (
    DEFAULT_GATE1_PLAN,
    gate1_trigger_plan_rows,
    load_gate1_plan,
)
from validate_eval_suite import validate_triggers


TRIGGER_SCHEMA = EVAL_ROOT / "schemas" / "trigger-output.schema.json"
def regular_trigger_file_sha256(path: Path, label: str) -> str:
    """Hash one regular non-link trigger staging file."""

    try:
        info = path.lstat()
    except OSError as error:
        raise EvaluationError(f"{label} is missing or unreadable: {path}") from error
    is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if path.is_symlink() or is_reparse or not stat.S_ISREG(info.st_mode):
        raise EvaluationError(f"{label} must be a regular non-link file: {path}")
    return file_sha256(path)


def require_trigger_staging_workspace_absent(workspace: Path | None) -> None:
    """Fail closed unless the exact trigger staging entry is absent."""

    if workspace is None:
        raise EvaluationError("Trigger staging cleanup did not complete")
    try:
        workspace_present = lstat_path_entry_exists(workspace)
    except (OSError, ValueError) as error:
        raise EvaluationError(
            "Trigger staging cleanup could not be verified"
        ) from error
    if workspace_present:
        raise EvaluationError("Trigger staging cleanup did not complete")


def validate_trigger_prediction(prediction: Any) -> list[str]:
    """Revalidate the exact trigger-output schema without trusting CLI enforcement."""

    if not isinstance(prediction, dict):
        return ["trigger prediction must be an object"]
    expected_keys = {"selected_skill", "confidence", "rationale"}
    errors: list[str] = []
    if set(prediction) != expected_keys:
        errors.append("trigger prediction fields do not match the canonical schema")
    selected = prediction.get("selected_skill")
    if selected is not None and not isinstance(selected, str):
        errors.append("trigger prediction selected_skill must be a string or null")
    confidence = prediction.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
    ):
        errors.append("trigger prediction confidence must be a finite number from 0 to 1")
    if not isinstance(prediction.get("rationale"), str):
        errors.append("trigger prediction rationale must be a string")
    return errors


def prepare_trigger_staging_root(
    raw_workspace: Path, durable_paths: tuple[Path, ...]
) -> Path:
    """Require one real external temp root disjoint from candidate and evidence."""

    try:
        info = raw_workspace.lstat()
        workspace = raw_workspace.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise EvaluationError("Trigger staging workspace is missing or unsafe") from error
    is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if raw_workspace.is_symlink() or is_reparse or not stat.S_ISDIR(info.st_mode):
        raise EvaluationError(
            "Trigger staging workspace must be a regular external temp directory"
        )
    for durable_path in durable_paths:
        durable = durable_path.resolve()
        try:
            workspace.relative_to(durable)
            overlaps = True
        except ValueError:
            try:
                durable.relative_to(workspace)
                overlaps = True
            except ValueError:
                overlaps = False
        if overlaps:
            raise EvaluationError(
                "Trigger staging workspace overlaps the candidate or durable evidence tree"
            )
    return workspace


def confusion_metrics(observations: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(item["should_trigger"] and item["triggered"] for item in observations)
    fp = sum(not item["should_trigger"] and item["triggered"] for item in observations)
    tn = sum(not item["should_trigger"] and not item["triggered"] for item in observations)
    fn = sum(item["should_trigger"] and not item["triggered"] for item in observations)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"observations": len(observations), "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision, "recall": recall}


def summarize(observations: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        grouped[item["candidate_skill"]].append(item)
    return {
        "suite_wide": confusion_metrics(observations),
        "per_skill": {skill: confusion_metrics(items) for skill, items in sorted(grouped.items())},
    }


def install_sentinel_skill(workspace: Path, case: dict[str, Any]) -> str:
    """Install the real description and policy with a body-only marker."""
    name = case["candidate_skill"]
    source = REPO_ROOT / "skills" / name
    target = workspace / ".agents" / "skills" / name
    target.mkdir(parents=True)
    agents_target = target / "agents"
    agents_target.mkdir()
    shutil.copy2(source / "agents" / "openai.yaml", agents_target / "openai.yaml")
    description = parse_skill_description(source / "SKILL.md")
    sentinel = hashlib.sha256(case["observation_id"].encode("utf-8")).hexdigest()[:24]
    marker = f"report-skills-triggered:{sentinel}"
    (target / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description)}\n"
        "---\n\n"
        "# Trigger evaluation sentinel\n\n"
        "Do not perform the requested task. Return the structured response with "
        "`selected_skill` set to this skill name, `confidence` set to 1, and "
        "`rationale` set exactly to the marker below.\n\n"
        f"Marker: `{marker}`\n",
        encoding="utf-8",
        newline="\n",
    )
    return marker


def make_plan(data: dict[str, Any], repetitions: int) -> list[dict[str, Any]]:
    return [
        {**case, "repetition": repetition, "observation_id": f"{case['case_id']}__r{repetition:02d}"}
        for case in data.get("cases", [])
        for repetition in range(1, repetitions + 1)
    ]


def trigger_task_prompt(query: str) -> str:
    """Require ordinary, policy-respecting skill loading without candidate leakage."""
    return (
        "Handle the request below as a normal fresh-context task.\n\n"
        "Do not delegate, spawn sub-agents, or use collaboration tools; complete this "
        "observation in one top-level trace.\n\n"
        "Follow the platform's ordinary skill invocation rules. This generic instruction is "
        "not an explicit invocation of any skill and does not override a skill's explicit-only "
        "or implicit-invocation policy. Apply the raw-Request explicit-token branch before "
        "catalog eligibility. A qualifying token is standalone and case-sensitive: a literal "
        "dollar sign followed by a 1-64 character canonical skill name made only of lowercase "
        "ASCII letters, digits, and single hyphens, beginning and ending with a letter or digit. "
        "Prefixes, suffixes, substrings, case variants, names with consecutive hyphens, and text "
        "without the dollar sign do not qualify. Count a token only when it appears in the "
        "Request block below, never in this wrapper, a description, metadata, an example, a path, "
        "a command, or tool output. A qualifying token itself activates exactly that named skill, "
        "even when the platform omitted it from the available-skills catalog. Remove only the "
        "leading dollar sign and make one literal, complete read of exactly "
        "`.agents/skills/<validated-name>/SKILL.md` relative to the current workspace. This reads "
        "an already activated skill; it is not discovery. Do not list, glob, search, recurse, "
        "normalize, case-fold, guess, inspect siblings, parse agents/openai.yaml or frontmatter, "
        "use a partial or line-count read, or try another path or root. If that exact read is "
        "missing, declined, fails, or is incomplete, fail closed to no activation without a "
        "retry or alternate lookup. Without a qualifying raw-Request token, use only skills the "
        "platform declares available in this fresh context; the platform has already applied "
        "their invocation policies and supplied their pre-activation names and descriptions. An "
        "unlisted skill is then ineligible. Do not list, search, enumerate, or probe the workspace "
        "`.agents/skills` tree, and do not use it to access an unlisted skill. Decide applicability "
        "from the Request and the platform-declared description before opening the body. If a "
        "declared skill clearly applies, activate it and only then read its SKILL.md completely at "
        "the exact path provided by the platform. Otherwise fail closed to no activation. Do not "
        "inspect or invoke a "
        "skill merely "
        "to fill the response schema. Do not inspect process lists, command lines, environment "
        "variables, parent directories, Git metadata, or repository metadata.\n\n"
        "If the request activates a skill under those ordinary rules, invoke it, read its "
        "SKILL.md completely, and follow its instructions before returning the structured "
        "response. Set selected_skill only "
        "to a skill actually invoked and read in this turn; if no skill was activated, set it "
        "to null. Description-only classification does not count as activation.\n\n"
        f"Request:\n{query}"
    )


def body_proven_activation(
    prediction: dict[str, Any], candidate_skill: str, marker: str, transcript: str = ""
) -> bool:
    """Count any candidate-body marker exposure as activation, even after self-correction."""
    selected = prediction.get("selected_skill")
    selected_matches = selected in {
        candidate_skill,
        f"report-skills:{candidate_skill}",
    }
    return marker in transcript or (
        selected_matches and prediction.get("rationale") == marker
    )


def run_trigger_prediction(
    command: list[str],
    query: str,
    timeout: int,
    environment: dict[str, str] | None = None,
) -> Any:
    """Run one prediction through the versioned, candidate-neutral prompt contract."""
    return run_codex(command, trigger_task_prompt(query), timeout, environment=environment)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_TRIGGERS)
    parser.add_argument("--output-root", type=Path, default=EVAL_ROOT / "runs")
    parser.add_argument("--run-id")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--case", action="append", dest="cases", help="Restrict to one or more case IDs")
    parser.add_argument(
        "--observation-plan",
        type=Path,
        help="Exact tracked Gate 1 mixed-repetition observation plan",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show-plan", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--codex-command")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--timeout", type=int, default=CANONICAL_TRIGGER_TIMEOUT_SECONDS)
    parser.add_argument(
        "--fail-fast-on-incorrect",
        action="store_true",
        help="Stop after the first semantically incorrect trigger observation",
    )
    parser.add_argument("--allow-tracked-output", action="store_true")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Choose either --dry-run or --execute, not both")
    try:
        if args.execute and args.timeout != CANONICAL_TRIGGER_TIMEOUT_SECONDS:
            raise EvaluationError(
                "Release trigger execution requires the canonical "
                f"{CANONICAL_TRIGGER_TIMEOUT_SECONDS}-second timeout"
            )
        require_pinned_profile(args.execute, args.model, args.reasoning_effort)
        suite = load_json(args.suite)
        benchmark_suite = normalize_suite(load_json(DEFAULT_SUITE))
        known_skills = {
            case["skill"]
            for case in benchmark_suite.get("primary_cases", [])
            if isinstance(case, dict) and isinstance(case.get("skill"), str)
        }
        trigger_errors: list[str] = []
        validate_triggers(suite, known_skills, trigger_errors)
        if trigger_errors:
            raise EvaluationError(
                "Trigger suite validation failed:\n- " + "\n- ".join(trigger_errors)
            )
        gate1_plan: dict[str, Any] | None = None
        gate1_plan_sha256: str | None = None
        if args.observation_plan:
            if args.cases or args.repetitions is not None:
                raise EvaluationError(
                    "--observation-plan is mutually exclusive with --case and --repetitions"
                )
            if args.observation_plan.resolve() != DEFAULT_GATE1_PLAN.resolve():
                raise EvaluationError(
                    "Gate 1 trigger execution requires the tracked gate1-release-plan.json"
                )
            if args.suite.resolve() != DEFAULT_TRIGGERS.resolve():
                raise EvaluationError(
                    "Gate 1 trigger execution requires the canonical trigger suite"
                )
            gate1_plan = load_gate1_plan(args.observation_plan)
            gate1_plan_sha256 = file_sha256(args.observation_plan)
            if args.execute and (
                args.model != gate1_plan["model"]
                or args.reasoning_effort != gate1_plan["reasoning_effort"]
            ):
                raise EvaluationError(
                    "Gate 1 trigger execution requires gpt-5.6-sol with ultra reasoning"
                )
            if not args.fail_fast_on_incorrect:
                raise EvaluationError(
                    "Gate 1 trigger execution requires --fail-fast-on-incorrect"
                )
            repetitions: int | None = None
            plan = gate1_trigger_plan_rows(gate1_plan, suite)
        else:
            repetitions = args.repetitions or suite.get(
                "protocol", {}
            ).get("repetitions_per_case", 3)
            plan = make_plan(suite, repetitions)
        if args.cases:
            selected = set(args.cases)
            known = {item["case_id"] for item in suite.get("cases", [])}
            unknown = selected - known
            if unknown:
                raise EvaluationError(f"Unknown trigger case IDs: {sorted(unknown)}")
            plan = [item for item in plan if item["case_id"] in selected]
        if not plan:
            raise EvaluationError("The trigger filters produced an empty plan")
        hash_directory = tracked_directory_sha256 if args.execute else directory_sha256
        skill_hashes = {
            skill: hash_directory(REPO_ROOT / "skills" / skill)
            for skill in sorted({item["candidate_skill"] for item in plan})
        }
        trigger_schema_sha256 = regular_trigger_file_sha256(
            TRIGGER_SCHEMA, "trigger output schema"
        )
        summary = {
            "mode": "execute" if args.execute else "dry-run",
            "evaluation_method_version": EVALUATION_METHOD_VERSION,
            "stage_method": canonical_trigger_stage_method(),
            "cases": len({item["case_id"] for item in plan}),
            "repetitions": repetitions,
            "observation_count": len(plan),
            "timeout_seconds": args.timeout,
            "fail_fast_on_incorrect": args.fail_fast_on_incorrect,
            "fail_fast_on_incorrect_method": (
                TRIGGER_FAIL_FAST_ON_INCORRECT_METHOD
            ),
            "skill_hashes": skill_hashes,
            "contract_hashes": {"trigger_suite_sha256": file_sha256(args.suite)},
            "trigger_schema_sha256": trigger_schema_sha256,
            "execution_profile": {"model": args.model, "reasoning_effort": args.reasoning_effort},
        }
        if gate1_plan_sha256 is not None:
            summary["gate1_release_plan_sha256"] = gate1_plan_sha256
            summary["planned_observation_ids"] = [
                item["observation_id"] for item in plan
            ]
        if not args.execute:
            if args.show_plan:
                summary["observations"] = [{"observation_id": item["observation_id"], "candidate_skill": item["candidate_skill"], "should_trigger": item["should_trigger"]} for item in plan]
            print(json.dumps(summary, indent=2))
            return 0
        output_root = validate_output_root(args.output_root, args.allow_tracked_output)
        target = output_root / (args.run_id or timestamp_id("triggers"))
        if target.exists():
            raise EvaluationError(f"Refusing to overwrite trigger run: {target}")
        contamination = baseline_contamination_paths({item["candidate_skill"] for item in plan})
        if contamination:
            raise EvaluationError(
                "Target skills are already installed in a user discovery root; remove or disable them "
                "before measuring isolated host activation: " + ", ".join(contamination)
            )
        command_name = find_codex_command(args.codex_command)
        execution_profile = codex_execution_profile(
            command_name, str(args.model), str(args.reasoning_effort)
        )
        repo_receipt = repository_receipt(require_clean=True)
        summary["execution_profile"] = execution_profile
        summary["repository"] = repo_receipt
        target.mkdir(parents=True)
        trigger_plan_sha256: str | None = None
        if gate1_plan_sha256 is not None:
            trigger_plan_document = {
                "schema_version": "1.0",
                "gate": "gate1-rc-preparation",
                "created_at": utc_now(),
                "gate1_release_plan": str(DEFAULT_GATE1_PLAN.resolve()),
                "gate1_release_plan_sha256": gate1_plan_sha256,
                "evaluation_method_version": EVALUATION_METHOD_VERSION,
                "stage_method": canonical_trigger_stage_method(),
                "suite": str(args.suite.resolve()),
                "contract_hashes": summary["contract_hashes"],
                "trigger_schema_sha256": trigger_schema_sha256,
                "timeout_seconds": args.timeout,
                "fail_fast_on_incorrect": args.fail_fast_on_incorrect,
                "fail_fast_on_incorrect_method": (
                    TRIGGER_FAIL_FAST_ON_INCORRECT_METHOD
                ),
                "planned_observations": [
                    {
                        "observation_id": item["observation_id"],
                        "case_id": item["case_id"],
                        "candidate_skill": item["candidate_skill"],
                        "repetition": item["repetition"],
                        "should_trigger": item["should_trigger"],
                    }
                    for item in plan
                ],
                "execution_profile": execution_profile,
                "repository": repo_receipt,
                "model_isolation": canonical_model_isolation_receipt(),
            }
            trigger_plan_path = target / "trigger-plan.json"
            write_json_exclusive(trigger_plan_path, trigger_plan_document)
            trigger_plan_sha256 = regular_trigger_file_sha256(
                trigger_plan_path, "Gate 1 trigger plan"
            )
        observations: list[dict[str, Any]] = []
        failed: list[str] = []
        for index, case in enumerate(plan, 1):
            print(f"[{index}/{len(plan)}] {case['observation_id']}", flush=True)
            require_unchanged_repository(repo_receipt)
            observation_dir = target / "trigger-observations" / case["observation_id"]
            observation_dir.mkdir(parents=True)
            output_path = observation_dir / "prediction.json"
            # Keep the host-discovery workspace outside this repository. If it
            # is nested here, Codex can namespace the candidate by the parent
            # plugin/repository and invalidate the public `$skill-name` test.
            staging_validation_errors: list[str] = []
            staged_schema_sha256: str | None = None
            post_execution_schema_sha256: str | None = None
            sentinel_skill_sha256: str | None = None
            post_execution_sentinel_skill_sha256: str | None = None
            staged_prediction_sha256: str | None = None
            workspace: Path | None = None
            with tempfile.TemporaryDirectory(prefix="report-skills-trigger-") as temp_name:
                workspace = prepare_trigger_staging_root(
                    Path(temp_name), (REPO_ROOT, output_root, target)
                )
                staged_schema = workspace / ".evaluation" / "trigger-output.schema.json"
                staged_prediction = workspace / ".evaluation" / "prediction.json"
                staged_schema.parent.mkdir()
                schema_source_before = regular_trigger_file_sha256(
                    TRIGGER_SCHEMA, "trigger output schema"
                )
                shutil.copy2(TRIGGER_SCHEMA, staged_schema, follow_symlinks=False)
                schema_source_after = regular_trigger_file_sha256(
                    TRIGGER_SCHEMA, "trigger output schema"
                )
                staged_schema_sha256 = regular_trigger_file_sha256(
                    staged_schema, "staged trigger output schema"
                )
                if not (
                    schema_source_before
                    == schema_source_after
                    == staged_schema_sha256
                    == trigger_schema_sha256
                ):
                    raise EvaluationError(
                        "Copied trigger output schema does not match the candidate"
                    )
                marker = install_sentinel_skill(workspace, case)
                sentinel_skill = (
                    workspace / ".agents" / "skills" / case["candidate_skill"]
                )
                sentinel_skill_sha256 = directory_sha256(sentinel_skill)
                require_unchanged_repository(repo_receipt)
                command = codex_base_command(
                    codex_runtime_command(execution_profile),
                    workspace,
                    "read-only",
                    staged_schema,
                    staged_prediction,
                    execution_profile["model"],
                    execution_profile["reasoning_effort"],
                )
                trigger_environment = task_runtime_environment(
                    execution_profile, workspace
                )
                require_isolated_model_invocation(
                    command,
                    trigger_environment,
                    (REPO_ROOT, output_root, target, observation_dir),
                    "Trigger model invocation",
                )
                workspace_environment = workspace_environment_receipt(workspace)
                result = run_trigger_prediction(
                    command,
                    case["query"],
                    args.timeout,
                    environment=trigger_environment,
                )
                require_unchanged_repository(repo_receipt)
                try:
                    current_schema_sha256 = regular_trigger_file_sha256(
                        TRIGGER_SCHEMA, "trigger output schema"
                    )
                    post_execution_schema_sha256 = regular_trigger_file_sha256(
                        staged_schema, "staged trigger output schema"
                    )
                except EvaluationError as error:
                    staging_validation_errors.append(str(error))
                else:
                    if not (
                        current_schema_sha256
                        == post_execution_schema_sha256
                        == staged_schema_sha256
                        == trigger_schema_sha256
                    ):
                        staging_validation_errors.append(
                            "trigger output schema changed during model execution"
                        )
                try:
                    post_execution_sentinel_skill_sha256 = directory_sha256(
                        sentinel_skill
                    )
                except EvaluationError as error:
                    staging_validation_errors.append(
                        f"cannot rehash staged sentinel skill: {error}"
                    )
                else:
                    if (
                        post_execution_sentinel_skill_sha256
                        != sentinel_skill_sha256
                    ):
                        staging_validation_errors.append(
                            "staged sentinel skill changed during model execution"
                        )
                if staged_prediction.exists() or staged_prediction.is_symlink():
                    try:
                        staged_prediction_sha256 = regular_trigger_file_sha256(
                            staged_prediction, "staged prediction.json"
                        )
                    except EvaluationError as error:
                        staging_validation_errors.append(str(error))
                    else:
                        shutil.copy2(
                            staged_prediction,
                            output_path,
                            follow_symlinks=False,
                        )
            require_trigger_staging_workspace_absent(workspace)
            staging_cleanup_completed = True
            require_unchanged_repository(repo_receipt)
            (observation_dir / "transcript.jsonl").write_text(result.stdout, encoding="utf-8", newline="\n")
            (observation_dir / "stderr.txt").write_text(
                result.stderr, encoding="utf-8", newline="\n"
            )
            validation_errors = execution_receipt_validation_errors(
                result, args.timeout, "trigger prediction"
            )
            validation_errors.extend(staging_validation_errors)
            validation_errors.extend(
                task_trace_isolation_validation_errors(
                    observation_dir / "transcript.jsonl", "trigger trace"
                )
            )
            persisted_prediction_sha256: str | None = None
            prediction: dict[str, Any] = {}
            if not output_path.exists() and not output_path.is_symlink():
                validation_errors.append("prediction.json was not produced")
            else:
                try:
                    persisted_prediction_sha256 = regular_trigger_file_sha256(
                        output_path, "persisted prediction.json"
                    )
                except EvaluationError as error:
                    validation_errors.append(str(error))
                else:
                    if persisted_prediction_sha256 != staged_prediction_sha256:
                        validation_errors.append(
                            "staged and persisted prediction hashes differ"
                        )
                    try:
                        prediction = load_json(output_path)
                    except EvaluationError as error:
                        validation_errors.append(str(error))
                    else:
                        validation_errors.extend(
                            validate_trigger_prediction(prediction)
                        )
            triggered = body_proven_activation(
                prediction, case["candidate_skill"], marker, result.stdout
            )
            observation = {
                "observation_id": case["observation_id"],
                "case_id": case["case_id"],
                "candidate_skill": case["candidate_skill"],
                "repetition": case["repetition"],
                "should_trigger": case["should_trigger"],
                "triggered": triggered,
                "correct": triggered == case["should_trigger"],
                "selected_skill": prediction.get("selected_skill"),
                "activation_evidence": "body_only_sentinel" if triggered else "sentinel_not_observed",
                "returncode": result.returncode,
                "validation_errors": validation_errors,
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
                "transcript_sha256": file_sha256(observation_dir / "transcript.jsonl"),
                "stderr_sha256": file_sha256(observation_dir / "stderr.txt"),
                "prediction_sha256": persisted_prediction_sha256,
                "staged_prediction_sha256": staged_prediction_sha256,
                "trigger_schema_sha256": trigger_schema_sha256,
                "staged_trigger_schema_sha256": staged_schema_sha256,
                "post_execution_trigger_schema_sha256": (
                    post_execution_schema_sha256
                ),
                "sentinel_skill_sha256": sentinel_skill_sha256,
                "post_execution_sentinel_skill_sha256": (
                    post_execution_sentinel_skill_sha256
                ),
                "staging_cleanup_completed": staging_cleanup_completed,
                "execution_profile": execution_profile,
                "repository": repo_receipt,
                "model_isolation": canonical_model_isolation_receipt(),
                "evaluation_method_version": EVALUATION_METHOD_VERSION,
                "stage_method": canonical_trigger_stage_method(),
                "workspace_environment": workspace_environment,
            }
            if trigger_plan_sha256 is not None:
                observation["gate1_release_plan_sha256"] = gate1_plan_sha256
                observation["trigger_plan_sha256"] = trigger_plan_sha256
            write_json(observation_dir / "observation.json", observation)
            observations.append(observation)
            if validation_errors or (
                args.fail_fast_on_incorrect and not observation["correct"]
            ):
                failed.append(case["observation_id"])
                break
        require_unchanged_repository(repo_receipt)
        result_doc = {
            "schema_version": "1.0",
            "evaluation_method_version": EVALUATION_METHOD_VERSION,
            "stage_method": canonical_trigger_stage_method(),
            "completed_at": utc_now(),
            "suite": str(args.suite.resolve()),
            "skill_hashes": skill_hashes,
            "contract_hashes": summary["contract_hashes"],
            "trigger_schema_sha256": trigger_schema_sha256,
            "execution_profile": execution_profile,
            "repository": repo_receipt,
            "model_isolation": canonical_model_isolation_receipt(),
            "workspace_environment_method": (
                canonical_trigger_workspace_environment_method()
            ),
            "timeout_seconds": args.timeout,
            "fail_fast_on_incorrect": args.fail_fast_on_incorrect,
            "fail_fast_on_incorrect_method": (
                TRIGGER_FAIL_FAST_ON_INCORRECT_METHOD
            ),
            "observations": observations,
            "observation_file_hashes": {
                item["observation_id"]: file_sha256(
                    target
                    / "trigger-observations"
                    / item["observation_id"]
                    / "observation.json"
                )
                for item in observations
            },
            "metrics": summarize(observations),
            "failed_observations": failed,
        }
        if trigger_plan_sha256 is not None:
            result_doc["gate1_release_plan_sha256"] = gate1_plan_sha256
            result_doc["trigger_plan_sha256"] = trigger_plan_sha256
        write_json(target / "trigger-results.json", result_doc)
        print(f"Trigger results: {target / 'trigger-results.json'}")
        return 1 if failed else 0
    except EvaluationError as exc:
        print(f"Trigger evaluation setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
