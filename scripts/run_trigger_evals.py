#!/usr/bin/env python3
"""Plan or execute repeated, fresh-context skill triggering evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation_common import (
    DEFAULT_TRIGGERS,
    EVAL_ROOT,
    EvaluationError,
    REPO_ROOT,
    REASONING_EFFORTS,
    baseline_contamination_paths,
    codex_execution_profile,
    codex_base_command,
    directory_sha256,
    file_sha256,
    find_codex_command,
    load_json,
    parse_skill_description,
    repository_receipt,
    require_pinned_profile,
    require_unchanged_repository,
    run_codex,
    timestamp_id,
    token_usage_from_jsonl,
    tracked_directory_sha256,
    utc_now,
    validate_output_root,
    write_json,
)


TRIGGER_SCHEMA = EVAL_ROOT / "schemas" / "trigger-output.schema.json"


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


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_TRIGGERS)
    parser.add_argument("--output-root", type=Path, default=EVAL_ROOT / "runs")
    parser.add_argument("--run-id")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--case", action="append", dest="cases", help="Restrict to one or more case IDs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show-plan", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--codex-command")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--allow-tracked-output", action="store_true")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Choose either --dry-run or --execute, not both")
    try:
        require_pinned_profile(args.execute, args.model, args.reasoning_effort)
        suite = load_json(args.suite)
        repetitions = args.repetitions or suite.get("protocol", {}).get("repetitions_per_case", 3)
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
        summary = {
            "mode": "execute" if args.execute else "dry-run",
            "cases": len({item["case_id"] for item in plan}),
            "repetitions": repetitions,
            "observation_count": len(plan),
            "skill_hashes": skill_hashes,
            "contract_hashes": {"trigger_suite_sha256": file_sha256(args.suite)},
            "execution_profile": {"model": args.model, "reasoning_effort": args.reasoning_effort},
        }
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
            with tempfile.TemporaryDirectory(prefix="report-skills-trigger-") as temp_name:
                workspace = Path(temp_name)
                marker = install_sentinel_skill(workspace, case)
                require_unchanged_repository(repo_receipt)
                command = codex_base_command(
                    command_name,
                    workspace,
                    "read-only",
                    TRIGGER_SCHEMA,
                    output_path,
                    execution_profile["model"],
                    execution_profile["reasoning_effort"],
                )
                result = run_codex(command, case["query"], args.timeout)
            require_unchanged_repository(repo_receipt)
            (observation_dir / "transcript.jsonl").write_text(result.stdout, encoding="utf-8", newline="\n")
            validation_errors: list[str] = []
            if result.returncode != 0:
                validation_errors.append(f"trigger prediction exited {result.returncode}")
            if not output_path.is_file():
                validation_errors.append("prediction.json was not produced")
            prediction = load_json(output_path) if not validation_errors else {}
            selected = prediction.get("selected_skill")
            selected_matches = selected in {
                case["candidate_skill"],
                f"report-skills:{case['candidate_skill']}",
            }
            triggered = selected_matches and prediction.get("rationale") == marker
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
                "token_usage": token_usage_from_jsonl(result.stdout),
                "execution_profile": execution_profile,
                "repository": repo_receipt,
            }
            write_json(observation_dir / "observation.json", observation)
            observations.append(observation)
            if validation_errors:
                failed.append(case["observation_id"])
        require_unchanged_repository(repo_receipt)
        result_doc = {
            "schema_version": "1.0",
            "completed_at": utc_now(),
            "suite": str(args.suite.resolve()),
            "skill_hashes": skill_hashes,
            "contract_hashes": summary["contract_hashes"],
            "execution_profile": execution_profile,
            "repository": repo_receipt,
            "observations": observations,
            "metrics": summarize(observations),
            "failed_observations": failed,
        }
        write_json(target / "trigger-results.json", result_doc)
        print(f"Trigger results: {target / 'trigger-results.json'}")
        return 1 if failed else 0
    except EvaluationError as exc:
        print(f"Trigger evaluation setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
