#!/usr/bin/env python3
"""Plan or execute randomized blind comparisons for paired primary outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation_common import (
    CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
    EVAL_ROOT,
    EvaluationError,
    REASONING_EFFORTS,
    codex_execution_profile,
    codex_base_command,
    codex_runtime_command,
    codex_runtime_environment,
    canonical_json_sha256,
    directory_sha256,
    find_codex_command,
    execution_receipt_validation_errors,
    file_sha256,
    load_json,
    repository_receipt,
    require_matching_context,
    require_clean_task_execution,
    require_complete_task_evidence,
    require_clean_stage_execution,
    require_pinned_profile,
    require_unchanged_repository,
    run_codex,
    token_usage_from_jsonl,
    utc_now,
    write_json,
    write_json_exclusive,
)


COMPARISON_SCHEMA = EVAL_ROOT / "schemas" / "blind-comparison-output.schema.json"
CANONICAL_BLIND_SEED = "report-skills-blind-v1"


def physical_comparison_id(index: int, total: int) -> str:
    """Return a stable compact folder id derived from the complete pair list."""
    if index < 1 or total < index:
        raise EvaluationError(f"Invalid comparison index {index} of {total}")
    return f"{index:0{max(3, len(str(total)))}d}"


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
        require_clean_task_execution(metadata, f"Task {run_dir.name}")
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
    """Revalidate persisted comparison schema and semantic assertion coverage."""

    errors: list[str] = []
    valid_labels = {"A", "B", "tie"}
    expected_root_keys = {
        "winner",
        "rubric",
        "output_quality",
        "expectation_results",
        "rationale",
    }
    if set(comparison) != expected_root_keys:
        errors.append(
            f"comparison fields mismatch: expected {sorted(expected_root_keys)}, "
            f"got {sorted(comparison)}"
        )
    if comparison.get("winner") not in valid_labels:
        errors.append("winner must be exactly A, B, or tie")
    if not isinstance(comparison.get("rubric"), str) or not comparison["rubric"].strip():
        errors.append("rubric must not be empty")
    output_quality = comparison.get("output_quality")
    if (
        not isinstance(output_quality, dict)
        or set(output_quality) != {"A", "B"}
        or any(
            not isinstance(output_quality.get(label), str)
            or not output_quality[label].strip()
            for label in ("A", "B")
        )
    ):
        errors.append("output_quality must contain nonempty A and B assessments")
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
        if set(item) != {"assertion_id", "better", "evidence"}:
            errors.append(f"expectation_results[{index}] fields mismatch")
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


def validate_comparison_binding(
    metadata: dict[str, Any],
    comparison: dict[str, Any],
    *,
    pair_id: str,
    case_id: str,
    storage_id: str,
    seed: str,
    source_runs: dict[str, dict[str, str]],
) -> list[str]:
    """Recompute the blinded label and winner binding from canonical inputs."""

    errors: list[str] = []
    expected_map = label_map(pair_id, seed)
    expected = {
        "pair_id": pair_id,
        "case_id": case_id,
        "storage_id": storage_id,
        "blind_seed": seed,
        "label_map": expected_map,
        "blind_winner": comparison.get("winner"),
        "source_runs": source_runs,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            errors.append(f"comparison metadata {key} mismatch")
    for label, configuration in expected_map.items():
        source = source_runs.get(label) if isinstance(source_runs, dict) else None
        if (
            not isinstance(source, dict)
            or source.get("configuration") != configuration
            or not isinstance(source.get("run_id"), str)
            or not source["run_id"]
            or not isinstance(source.get("blind_bundle_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", source["blind_bundle_sha256"])
        ):
            errors.append(f"comparison source_runs {label} mismatch")
    winner = comparison.get("winner")
    resolved = expected_map.get(winner) if winner in {"A", "B"} else "tie"
    if metadata.get("resolved_winner") != resolved:
        errors.append("comparison metadata resolved_winner mismatch")
    return errors


def comparison_input_sha256(target: Path) -> str:
    """Hash the exact A/B bundles and contract visible to the blind judge."""

    required_dirs = (target / "A", target / "B")
    if any(not path.is_dir() for path in required_dirs) or not (
        target / "case_contract.json"
    ).is_file():
        raise EvaluationError(f"Incomplete comparison inputs in {target}")
    inputs = {
        "A": blind_bundle_sha256(target / "A"),
        "B": blind_bundle_sha256(target / "B"),
        "case_contract.json": file_sha256(target / "case_contract.json"),
    }
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def blind_bundle_sha256(bundle: Path) -> str:
    """Hash the judge-visible task output and artifact directory."""

    output = bundle / "task-output.json"
    artifacts = bundle / "artifacts"
    if not output.is_file() or not artifacts.is_dir():
        raise EvaluationError(f"Incomplete blind bundle: {bundle}")
    return canonical_json_sha256(
        {
            "task-output.json": file_sha256(output),
            "artifacts": directory_sha256(artifacts),
        }
    )


def validate_comparison_output_binding(
    metadata: dict[str, Any], result_path: Path, contract_path: Path, target: Path
) -> list[str]:
    """Verify that comparator metadata binds the exact result and contract bytes."""

    errors: list[str] = []
    for key, path in (
        ("comparison_sha256", result_path),
        ("case_contract_sha256", contract_path),
    ):
        if not path.is_file():
            errors.append(f"missing {path.name}")
            continue
        if metadata.get(key) != file_sha256(path):
            errors.append(f"comparison metadata {key} mismatch")
    try:
        actual_input_hash = comparison_input_sha256(target)
    except (EvaluationError, OSError) as exc:
        errors.append(f"cannot hash comparison inputs: {exc}")
    else:
        if metadata.get("comparison_input_sha256") != actual_input_hash:
            errors.append("comparison metadata comparison_input_sha256 mismatch")
    source_runs = metadata.get("source_runs")
    if not isinstance(source_runs, dict):
        errors.append("comparison metadata source_runs mismatch")
    else:
        for label in ("A", "B"):
            source = source_runs.get(label)
            try:
                actual_bundle_hash = blind_bundle_sha256(target / label)
            except (EvaluationError, OSError) as exc:
                errors.append(f"cannot hash blind bundle {label}: {exc}")
                continue
            if (
                not isinstance(source, dict)
                or source.get("blind_bundle_sha256") != actual_bundle_hash
            ):
                errors.append(f"comparison source bundle {label} mismatch")
    return errors


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--seed", default=CANONICAL_BLIND_SEED)
    parser.add_argument("--codex-command")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--timeout", type=int, default=CANONICAL_COMPARATOR_TIMEOUT_SECONDS)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def copy_blind_bundle(source: Path, target: Path) -> None:
    """Copy only judgeable outputs; omit metadata, traces, and injected skills."""
    target.mkdir(parents=True)
    output = source / "task-output.json"
    if output.is_symlink() or not output.is_file():
        raise EvaluationError(f"Missing or unsafe blind task output: {output}")
    if output.is_file():
        shutil.copy2(output, target / output.name)
    artifacts = source / "workspace" / "artifacts"
    if not artifacts.is_dir() or artifacts.is_symlink():
        raise EvaluationError(f"Missing or unsafe blind artifact directory: {artifacts}")
    destination = target / "artifacts"
    destination.mkdir()
    pending = [(artifacts, destination)]
    file_count = 0
    total_size = 0
    while pending:
        current_source, current_target = pending.pop()
        with os.scandir(current_source) as entries:
            for entry in entries:
                source_path = Path(entry.path)
                target_path = current_target / entry.name
                info = entry.stat(follow_symlinks=False)
                is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
                if entry.is_symlink() or is_reparse:
                    raise EvaluationError(f"Link or reparse point in blind artifacts: {source_path}")
                if stat.S_ISDIR(info.st_mode):
                    target_path.mkdir()
                    pending.append((source_path, target_path))
                elif stat.S_ISREG(info.st_mode):
                    file_count += 1
                    total_size += info.st_size
                    if file_count > 10000 or total_size > 1024 * 1024 * 1024:
                        raise EvaluationError("Blind artifact bundle exceeds safe copy limits")
                    shutil.copy2(source_path, target_path, follow_symlinks=False)
                else:
                    raise EvaluationError(f"Non-regular blind artifact: {source_path}")


def main() -> int:
    args = make_parser().parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Choose either --dry-run or --execute, not both")
    try:
        if args.overwrite:
            raise EvaluationError(
                "--overwrite is not allowed for evidence-bound comparisons; use a fresh benchmark run"
            )
        require_pinned_profile(args.execute, args.model, args.reasoning_effort)
        suite_run_dir = args.run_dir.resolve()
        require_complete_task_evidence(suite_run_dir)
        pairs = discover_pairs(suite_run_dir)
        if not pairs:
            raise EvaluationError("No complete primary with_skill/without_skill pairs found")
        comparison_root = suite_run_dir / "comparisons"
        storage_ids = {
            str(pair["pair_id"]): physical_comparison_id(index, len(pairs))
            for index, pair in enumerate(pairs, 1)
        }
        storage_map_document = {
            "schema_version": "1.0",
            "pairs": [
                {
                    "storage_id": storage_ids[str(pair["pair_id"])],
                    "pair_id": pair["pair_id"],
                }
                for pair in pairs
            ],
        }
        storage_map_path = comparison_root / "storage-map.json"
        if storage_map_path.is_file():
            if load_json(storage_map_path) != storage_map_document:
                raise EvaluationError(
                    "Existing comparison storage map does not match the complete pair plan"
                )
        elif comparison_root.exists():
            raise EvaluationError(
                "Partial comparison evidence exists without storage-map.json; "
                "use a fresh benchmark run"
            )
        pending: list[dict[str, Any]] = []
        existing: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for pair in pairs:
            target = comparison_root / storage_ids[str(pair["pair_id"])]
            result_path = target / "comparison.json"
            metadata_path = target / "comparison_metadata.json"
            if not target.exists():
                pending.append(pair)
                continue
            contract_path = target / "case_contract.json"
            transcript_path = target / "comparator-transcript.jsonl"
            stderr_path = target / "comparator-stderr.txt"
            required_files = (
                result_path,
                metadata_path,
                contract_path,
                transcript_path,
                stderr_path,
            )
            if (
                any(not path.is_file() for path in required_files)
                or not (target / "A").is_dir()
                or not (target / "B").is_dir()
            ):
                raise EvaluationError(
                    f"Partial comparison evidence exists for {pair['pair_id']}; "
                    "use a fresh benchmark run"
                )
            comparison_metadata = load_json(metadata_path)
            require_clean_stage_execution(
                comparison_metadata,
                CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
                f"Comparator {pair['pair_id']}",
            )
            comparison = load_json(result_path)
            errors = validate_comparison(comparison, load_json(contract_path))
            mapping = label_map(str(pair["pair_id"]), args.seed)
            source_runs = {
                label: {
                    "run_id": str((source_metadata := load_json(
                        pair["runs"][configuration] / "run_metadata.json"
                    )).get("run_id")),
                    "configuration": configuration,
                    "blind_bundle_sha256": source_metadata.get("task_evidence", {}).get(
                        "blind_bundle_sha256"
                    ),
                }
                for label, configuration in mapping.items()
            }
            errors.extend(
                validate_comparison_binding(
                    comparison_metadata,
                    comparison,
                    pair_id=str(pair["pair_id"]),
                    case_id=str(pair["case_id"]),
                    storage_id=storage_ids[str(pair["pair_id"])],
                    seed=args.seed,
                    source_runs=source_runs,
                )
            )
            errors.extend(
                validate_comparison_output_binding(
                    comparison_metadata, result_path, contract_path, target
                )
            )
            if errors:
                raise EvaluationError(
                    f"Existing comparison for {pair['pair_id']} is invalid: {errors}"
                )
            existing.append((pair, comparison_metadata))
        plan = {
            "suite_run_dir": str(suite_run_dir),
            "mode": "execute" if args.execute else "dry-run",
            "complete_pairs": len(pairs),
            "pending_comparisons": len(pending),
            "timeout_seconds": args.timeout,
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
        for pair, comparison_metadata in existing:
            require_matching_context(
                execution_profile,
                repo_receipt,
                comparison_metadata.get("execution_profile", {}),
                comparison_metadata.get("repository", {}),
                f"Existing comparison {pair['pair_id']}",
            )
        comparison_root.mkdir(parents=True, exist_ok=True)
        if not storage_map_path.is_file():
            write_json_exclusive(storage_map_path, storage_map_document)
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
            storage_id = storage_ids[str(pair["pair_id"])]
            target = comparison_root / storage_id
            target.mkdir(parents=True, exist_ok=True)
            mapping = label_map(pair["pair_id"], args.seed)
            source_runs = {
                label: {
                    "run_id": str((source_metadata := load_json(
                        pair["runs"][configuration] / "run_metadata.json"
                    )).get("run_id")),
                    "configuration": configuration,
                    "blind_bundle_sha256": source_metadata.get("task_evidence", {}).get(
                        "blind_bundle_sha256"
                    ),
                }
                for label, configuration in mapping.items()
            }
            for label, config in mapping.items():
                copy_blind_bundle(pair["runs"][config], target / label)
            shutil.copy2(pair["runs"][mapping["A"]] / "case_contract.json", target / "case_contract.json")
            contract = load_json(target / "case_contract.json")
            result_path = target / "comparison.json"
            command = codex_base_command(
                codex_runtime_command(execution_profile),
                cwd=target,
                sandbox="read-only",
                output_schema=COMPARISON_SCHEMA,
                output_message=result_path,
                model=execution_profile["model"],
                reasoning_effort=execution_profile["reasoning_effort"],
            )
            require_unchanged_repository(repo_receipt)
            result = run_codex(
                command,
                comparison_prompt(pair, contract),
                args.timeout,
                environment=codex_runtime_environment(execution_profile),
            )
            require_unchanged_repository(repo_receipt)
            (target / "comparator-transcript.jsonl").write_text(result.stdout, encoding="utf-8", newline="\n")
            (target / "comparator-stderr.txt").write_text(result.stderr, encoding="utf-8", newline="\n")
            validation_errors = execution_receipt_validation_errors(
                result, args.timeout, "comparator"
            )
            comparison_winner = None
            if not result_path.is_file():
                validation_errors.append("comparison.json was not produced")
            elif not validation_errors:
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
                "storage_id": storage_id,
                "case_id": pair["case_id"],
                "compared_at": utc_now(),
                "returncode": result.returncode,
                "validation_errors": validation_errors,
                "blind_seed": args.seed,
                "label_map": mapping,
                "source_runs": source_runs,
                "blind_winner": comparison_winner,
                "resolved_winner": resolved,
                "comparison_sha256": file_sha256(result_path) if result_path.is_file() else None,
                "case_contract_sha256": file_sha256(target / "case_contract.json"),
                "comparison_input_sha256": comparison_input_sha256(target),
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
                "execution_profile": execution_profile,
                "repository": repo_receipt,
            }
            # Label mapping is kept outside the model-visible comparison.json.
            write_json(target / "comparison_metadata.json", metadata)
            if validation_errors:
                failed.append(pair["pair_id"])
                break
        require_unchanged_repository(repo_receipt)
        print(f"Blind comparisons complete; failures: {len(failed)}")
        return 1 if failed else 0
    except EvaluationError as exc:
        print(f"Blind comparison setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
