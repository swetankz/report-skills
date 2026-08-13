#!/usr/bin/env python3
"""Plan or execute randomized blind comparisons for paired primary outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation_common import (
    EVAL_ROOT,
    EvaluationError,
    REASONING_EFFORTS,
    codex_execution_profile,
    codex_base_command,
    find_codex_command,
    load_json,
    repository_receipt,
    require_matching_context,
    require_pinned_profile,
    require_unchanged_repository,
    run_codex,
    token_usage_from_jsonl,
    utc_now,
    write_json,
)


COMPARISON_SCHEMA = EVAL_ROOT / "schemas" / "blind-comparison-output.schema.json"


def discover_pairs(suite_run_dir: Path) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    runs_root = suite_run_dir / "runs"
    if not runs_root.is_dir():
        return []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        metadata_path = run_dir / "run_metadata.json"
        if not metadata_path.is_file():
            continue
        metadata = load_json(metadata_path)
        if metadata.get("case_kind") != "primary":
            continue
        pair = grouped.setdefault(
            str(metadata["pair_id"]),
            {"pair_id": metadata["pair_id"], "case_id": metadata["case_id"], "runs": {}},
        )
        pair["runs"][metadata["configuration"]] = run_dir
    return [pair for pair in grouped.values() if set(pair["runs"]) == {"with_skill", "without_skill"}]


def label_map(pair_id: str, seed: str) -> dict[str, str]:
    digest = hashlib.sha256(f"{seed}:{pair_id}".encode()).digest()
    rng = random.Random(digest)
    configs = ["with_skill", "without_skill"]
    rng.shuffle(configs)
    return {"A": configs[0], "B": configs[1]}


def comparison_prompt(pair: dict[str, Any], contract: dict[str, Any]) -> str:
    assertions = json.dumps(contract.get("assertions", []), indent=2)
    return f"""Blindly compare two outputs for benchmark pair {pair['pair_id']}.

Inspect `A/` and `B/`, including task-output.json and produced artifacts. The
configuration labels and execution traces have been hidden. The shared case
contract is at `case_contract.json`.

Case assertions:
{assertions}

Choose A, B, or tie based on evidence quality, task completeness, instruction
following, safety, and assertion satisfaction. Do not reward verbosity or infer
success from claims without artifacts. Return one expectation comparison per
assertion. Your final response must match the supplied JSON schema.
"""


def validate_comparison(
    comparison: dict[str, Any], contract: dict[str, Any]
) -> list[str]:
    """Validate semantic coverage that the output schema cannot express."""

    errors: list[str] = []
    valid_labels = {"A", "B", "tie"}
    if comparison.get("winner") not in valid_labels:
        errors.append("winner must be exactly A, B, or tie")
    if not isinstance(comparison.get("rationale"), str) or not comparison["rationale"].strip():
        errors.append("rationale must not be empty")

    assertions = contract.get("assertions", [])
    expected_ids = [
        item.get("assertion_id")
        for item in assertions
        if isinstance(item, dict) and isinstance(item.get("assertion_id"), str)
    ]
    expected_counts = Counter(expected_ids)
    duplicate_expected = sorted(
        assertion_id for assertion_id, count in expected_counts.items() if count > 1
    )
    if duplicate_expected:
        errors.append(f"case contract has duplicate assertion IDs: {duplicate_expected}")
    expected = {
        item["assertion_id"]: item
        for item in assertions
        if isinstance(item, dict) and isinstance(item.get("assertion_id"), str)
    }

    results = comparison.get("expectation_results")
    if not isinstance(results, list):
        errors.append("expectation_results must be a list")
        return errors

    observed_ids: list[str] = []
    observed_items: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            errors.append(f"expectation_results[{index}] must be an object")
            continue
        observed_items.append((index, item))
        assertion_id = item.get("assertion_id")
        if not isinstance(assertion_id, str) or not assertion_id.strip():
            errors.append(f"expectation_results[{index}] has no assertion_id")
        else:
            observed_ids.append(assertion_id)
        if item.get("better") not in valid_labels:
            errors.append(
                f"expectation_results[{index}].better must be exactly A, B, or tie"
            )
        if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            errors.append(f"expectation_results[{index}].evidence must not be empty")

    observed_counts = Counter(observed_ids)
    duplicate_observed = sorted(
        assertion_id for assertion_id, count in observed_counts.items() if count > 1
    )
    if duplicate_observed:
        errors.append(f"duplicate assertion IDs: {duplicate_observed}")
    if set(observed_ids) != set(expected):
        errors.append(
            "assertion coverage mismatch: "
            f"expected {sorted(expected)}, got {sorted(set(observed_ids))}"
        )

    for index, item in observed_items:
        assertion_id = item.get("assertion_id")
        expected_item = expected.get(assertion_id)
        if expected_item is not None and "text" in item and item.get("text") != expected_item.get("text"):
            errors.append(f"expectation_results[{index}].text does not match {assertion_id}")
    return errors


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--seed", default="report-skills-blind-v1")
    parser.add_argument("--codex-command")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def copy_blind_bundle(source: Path, target: Path) -> None:
    """Copy only judgeable outputs; omit metadata, traces, and injected skills."""
    target.mkdir(parents=True)
    output = source / "task-output.json"
    if output.is_file():
        shutil.copy2(output, target / output.name)
    artifacts = source / "workspace" / "artifacts"
    if artifacts.is_dir():
        shutil.copytree(artifacts, target / "artifacts")


def main() -> int:
    args = make_parser().parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Choose either --dry-run or --execute, not both")
    try:
        require_pinned_profile(args.execute, args.model, args.reasoning_effort)
        suite_run_dir = args.run_dir.resolve()
        pairs = discover_pairs(suite_run_dir)
        if not pairs:
            raise EvaluationError("No complete primary with_skill/without_skill pairs found")
        comparison_root = suite_run_dir / "comparisons"
        pending = [pair for pair in pairs if args.overwrite or not (comparison_root / pair["pair_id"] / "comparison.json").is_file()]
        plan = {
            "suite_run_dir": str(suite_run_dir),
            "mode": "execute" if args.execute else "dry-run",
            "complete_pairs": len(pairs),
            "pending_comparisons": len(pending),
            "pair_ids": [pair["pair_id"] for pair in pending],
        }
        if not args.execute:
            print(json.dumps(plan, indent=2))
            return 0
        codex_command = find_codex_command(args.codex_command)
        execution_profile = codex_execution_profile(
            codex_command, str(args.model), str(args.reasoning_effort)
        )
        repo_receipt = repository_receipt(require_clean=True)
        run_plan = load_json(suite_run_dir / "run-plan.json")
        require_matching_context(
            run_plan.get("execution_profile", {}),
            run_plan.get("repository", {}),
            execution_profile,
            repo_receipt,
            "Blind comparison",
        )
        failed: list[str] = []
        for index, pair in enumerate(pending, 1):
            print(f"[{index}/{len(pending)}] compare {pair['pair_id']}", flush=True)
            require_unchanged_repository(repo_receipt)
            for configuration, source in pair["runs"].items():
                metadata = load_json(source / "run_metadata.json")
                require_matching_context(
                    execution_profile,
                    repo_receipt,
                    metadata.get("execution_profile", {}),
                    metadata.get("repository", {}),
                    f"Task {pair['pair_id']} {configuration}",
                )
            target = comparison_root / pair["pair_id"]
            if target.exists() and args.overwrite:
                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
            mapping = label_map(pair["pair_id"], args.seed)
            for label, config in mapping.items():
                copy_blind_bundle(pair["runs"][config], target / label)
            shutil.copy2(pair["runs"][mapping["A"]] / "case_contract.json", target / "case_contract.json")
            contract = load_json(target / "case_contract.json")
            result_path = target / "comparison.json"
            command = codex_base_command(
                codex_command,
                cwd=target,
                sandbox="read-only",
                output_schema=COMPARISON_SCHEMA,
                output_message=result_path,
                model=execution_profile["model"],
                reasoning_effort=execution_profile["reasoning_effort"],
            )
            require_unchanged_repository(repo_receipt)
            result = run_codex(command, comparison_prompt(pair, contract), args.timeout)
            require_unchanged_repository(repo_receipt)
            (target / "comparator-transcript.jsonl").write_text(result.stdout, encoding="utf-8", newline="\n")
            (target / "comparator-stderr.txt").write_text(result.stderr, encoding="utf-8", newline="\n")
            validation_errors: list[str] = []
            comparison_winner = None
            if result.returncode != 0:
                validation_errors.append(f"comparator exited {result.returncode}")
            if not result_path.is_file():
                validation_errors.append("comparison.json was not produced")
            else:
                try:
                    comparison = load_json(result_path)
                except EvaluationError as exc:
                    validation_errors.append(str(exc))
                else:
                    comparison_winner = comparison.get("winner")
                    validation_errors.extend(validate_comparison(comparison, contract))
            resolved = mapping.get(comparison_winner) if comparison_winner in {"A", "B"} else "tie"
            metadata = {
                "pair_id": pair["pair_id"],
                "case_id": pair["case_id"],
                "compared_at": utc_now(),
                "returncode": result.returncode,
                "validation_errors": validation_errors,
                "blind_seed": args.seed,
                "label_map": mapping,
                "blind_winner": comparison_winner,
                "resolved_winner": resolved,
                "wall_clock_seconds": result.wall_clock_seconds,
                "token_usage": token_usage_from_jsonl(result.stdout),
                "execution_profile": execution_profile,
                "repository": repo_receipt,
            }
            # Label mapping is kept outside the model-visible comparison.json.
            write_json(target / "comparison_metadata.json", metadata)
            if validation_errors:
                failed.append(pair["pair_id"])
        require_unchanged_repository(repo_receipt)
        print(f"Blind comparisons complete; failures: {len(failed)}")
        return 1 if failed else 0
    except EvaluationError as exc:
        print(f"Blind comparison setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
