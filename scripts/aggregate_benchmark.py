#!/usr/bin/env python3
"""Aggregate grades, blind comparisons, and triggers into a release verdict."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation_common import (
    DEFAULT_THRESHOLDS,
    DEFAULT_TRIGGERS,
    EvaluationError,
    compare,
    load_json,
    summary_stats,
    utc_now,
    write_json,
)


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
        if not grade_path.is_file():
            missing.append(f"{path.name}:grading.json")
            records.append({**metadata, "grade": None})
            continue
        grader_metadata = path / "grader_metadata.json"
        if not grader_metadata.is_file():
            missing.append(f"{path.name}:grader_metadata.json")
        elif load_json(grader_metadata).get("validation_errors"):
            missing.append(f"{path.name}:valid grade")
        records.append({**metadata, "grade": load_json(grade_path)})
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
        else:
            missing.append("run-plan.json")
            expected_skills = set()
            expected_pairs = set()
        for record in records:
            grader_metadata = run_dir / "runs" / str(record.get("run_id")) / "grader_metadata.json"
            if grader_metadata.is_file() and load_json(grader_metadata).get("validation_errors"):
                missing.append(f"{record.get('run_id')}:invalid grade")
        comparisons = collect_comparisons(run_dir)
        triggers = load_trigger_results(args.trigger_results)
        thresholds = load_json(args.thresholds)
        trigger_suite = load_json(args.trigger_suite)
        trigger_repetitions = int(trigger_suite.get("protocol", {}).get("repetitions_per_case", 3))
        expected_trigger_observations = len(trigger_suite.get("cases", [])) * trigger_repetitions
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
