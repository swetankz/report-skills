#!/usr/bin/env python3
"""Plan or execute randomized blind comparisons for paired primary outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any

from evaluation_common import (
    EVAL_ROOT,
    EvaluationError,
    codex_base_command,
    find_codex_command,
    load_json,
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


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--seed", default="report-skills-blind-v1")
    parser.add_argument("--codex-command")
    parser.add_argument("--model")
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
        failed: list[str] = []
        for index, pair in enumerate(pending, 1):
            print(f"[{index}/{len(pending)}] compare {pair['pair_id']}", flush=True)
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
                model=args.model,
            )
            result = run_codex(command, comparison_prompt(pair, contract), args.timeout)
            (target / "comparator-transcript.jsonl").write_text(result.stdout, encoding="utf-8", newline="\n")
            (target / "comparator-stderr.txt").write_text(result.stderr, encoding="utf-8", newline="\n")
            comparison_winner = None
            if result.returncode == 0 and result_path.is_file():
                comparison_winner = load_json(result_path).get("winner")
            resolved = mapping.get(comparison_winner) if comparison_winner in {"A", "B"} else "tie"
            metadata = {
                "pair_id": pair["pair_id"],
                "case_id": pair["case_id"],
                "compared_at": utc_now(),
                "returncode": result.returncode,
                "blind_seed": args.seed,
                "label_map": mapping,
                "blind_winner": comparison_winner,
                "resolved_winner": resolved,
                "wall_clock_seconds": result.wall_clock_seconds,
                "token_usage": token_usage_from_jsonl(result.stdout),
            }
            # Label mapping is kept outside the model-visible comparison.json.
            write_json(target / "comparison_metadata.json", metadata)
            if result.returncode != 0 or not result_path.is_file():
                failed.append(pair["pair_id"])
        print(f"Blind comparisons complete; failures: {len(failed)}")
        return 1 if failed else 0
    except EvaluationError as exc:
        print(f"Blind comparison setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
