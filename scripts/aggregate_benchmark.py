#!/usr/bin/env python3
"""Aggregate grades, blind comparisons, and triggers into a release verdict."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation_common import (
    DEFAULT_THRESHOLDS,
    DEFAULT_TRIGGERS,
    EvaluationError,
    PROFILE_IDENTITY_KEYS,
    REPOSITORY_IDENTITY_KEYS,
    REPO_ROOT,
    compare,
    tracked_directory_sha256,
    load_json,
    repository_receipt,
    require_matching_context,
    summary_stats,
    utc_now,
    write_json,
)
from run_trigger_evals import summarize
from validate_release_eval_plan import validate_release_eval_plan


def collect_runs(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    runs_root = run_dir / "runs"
    if not runs_root.is_dir():
        raise EvaluationError(f"No runs directory: {runs_root}")
    for path in sorted(item for item in runs_root.iterdir() if item.is_dir()):
        metadata_path = path / "run_metadata.json"
        grade_path = path / "grading.json"
        if not metadata_path.is_file():
            missing.append(f"{path.name}:run_metadata.json")
            continue
        metadata = load_json(metadata_path)
        if metadata.get("returncode") != 0:
            missing.append(f"{path.name}:successful task execution")
        if metadata.get("validation_errors"):
            missing.append(f"{path.name}:valid task output")
        if not grade_path.is_file():
            missing.append(f"{path.name}:grading.json")
            records.append({**metadata, "grade": None, "grader_metadata": None})
            continue
        grader_metadata_path = path / "grader_metadata.json"
        grader_metadata = None
        if not grader_metadata_path.is_file():
            missing.append(f"{path.name}:grader_metadata.json")
        else:
            grader_metadata = load_json(grader_metadata_path)
            if grader_metadata.get("returncode") != 0:
                missing.append(f"{path.name}:successful grader execution")
            if grader_metadata.get("validation_errors"):
                missing.append(f"{path.name}:valid grade")
        records.append(
            {**metadata, "grade": load_json(grade_path), "grader_metadata": grader_metadata}
        )
    return records, missing


def collect_comparisons(run_dir: Path) -> list[dict[str, Any]]:
    root = run_dir / "comparisons"
    if not root.is_dir():
        return []
    return [load_json(path) for path in sorted(root.glob("*/comparison_metadata.json"))]


def load_trigger_results(path: Path | None) -> dict[str, Any] | None:
    if path and path.is_file():
        return load_json(path)
    return None


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
    profile_identity = tuple(profile.get(key) for key in PROFILE_IDENTITY_KEYS)
    commit = repository.get("commit")
    tree = repository.get("tree")
    if not all(isinstance(value, str) and value.strip() for value in profile_identity):
        issues.append(f"{label}:incomplete execution profile")
        return None
    for key in (
        "codex_command_sha256",
        "codex_implementation_sha256",
        "selected_model_sha256",
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
    for record in records:
        run_id = str(record.get("run_id"))
        if evidence_identity(record, f"task {run_id}", issues) != anchor:
            issues.append(f"task {run_id}:evaluation identity mismatch")
        planned = planned_by_id.get(run_id)
        if planned and any(record.get(field) != planned.get(field) for field in binding_fields):
            issues.append(f"task {run_id}:run-plan binding mismatch")
        grader = record.get("grader_metadata")
        if not isinstance(grader, dict):
            issues.append(f"grader {run_id}:missing metadata")
        else:
            if evidence_identity(grader, f"grader {run_id}", issues) != anchor:
                issues.append(f"grader {run_id}:evaluation identity mismatch")
            if grader.get("returncode") != 0 or grader.get("validation_errors"):
                issues.append(f"grader {run_id}:failed or invalid")

    expected_pairs = {
        str(item.get("pair_id"))
        for item in planned_rows
        if item.get("case_kind") == "primary"
    }
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
    for comparison in comparisons:
        pair_id = str(comparison.get("pair_id"))
        if evidence_identity(comparison, f"comparison {pair_id}", issues) != anchor:
            issues.append(f"comparison {pair_id}:evaluation identity mismatch")
        if comparison.get("returncode") != 0:
            issues.append(f"comparison {pair_id}:failed execution")
        if comparison.get("validation_errors"):
            issues.append(f"comparison {pair_id}:invalid output")

    if trigger_results is None:
        return issues
    trigger_identity = evidence_identity(trigger_results, "trigger-results", issues)
    if trigger_identity != anchor:
        issues.append("trigger-results:evaluation identity mismatch")
    if trigger_results.get("skill_hashes") != expected_skill_hashes:
        issues.append("trigger-results:skill hashes do not match run-plan")
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
        comparisons = collect_comparisons(run_dir)
        triggers = load_trigger_results(args.trigger_results)
        thresholds = load_json(args.thresholds)
        trigger_suite = load_json(args.trigger_suite)
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
            "generated_at": utc_now(),
            "run_dir": str(run_dir),
            "run_count": len(records),
            "graded_run_count": sum(record.get("grade") is not None for record in records),
            "blind_comparison_count": len(comparisons),
            "evaluation_receipt": {
                "execution_profile": plan.get("execution_profile"),
                "repository": plan.get("repository"),
                "skill_hashes": plan.get("skill_hashes"),
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
