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
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation_common import (
    CANONICAL_COMPARATOR_TIMEOUT_SECONDS,
    EVAL_ROOT,
    EVALUATION_METHOD_VERSION,
    EvaluationError,
    REPO_ROOT,
    REASONING_EFFORTS,
    canonical_blind_comparator_stage_method,
    canonical_model_isolation_receipt,
    codex_execution_profile,
    codex_base_command,
    codex_runtime_command,
    canonical_json_sha256,
    directory_sha256,
    find_codex_command,
    execution_receipt_validation_errors,
    file_sha256,
    load_json,
    repository_receipt,
    require_matching_context,
    require_model_invocation_isolation,
    require_clean_task_execution,
    require_complete_task_evidence,
    require_clean_stage_execution,
    require_pinned_profile,
    require_unchanged_repository,
    run_codex,
    task_runtime_environment,
    task_trace_isolation_validation_errors,
    stage_method_receipt_validation_errors,
    token_usage_from_jsonl,
    utc_now,
    workspace_environment_receipt,
    workspace_environment_receipt_validation_errors,
    write_json,
    write_json_exclusive,
)


COMPARISON_SCHEMA = EVAL_ROOT / "schemas" / "blind-comparison-output.schema.json"
CANONICAL_BLIND_SEED = "report-skills-blind-v1"
COMPARISON_STAGING_SCHEMA_VERSION = "1.0"


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
success from claims without artifacts. Work only in this isolated comparison
workspace. Do not inspect its parent, run Git, inspect repository metadata,
delegate, use collaboration tools, or access a network or live service. Return
one expectation comparison per assertion. Your final response must match the
supplied JSON schema.
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

    try:
        bundle_info = bundle.lstat()
    except OSError as error:
        raise EvaluationError(f"Blind bundle is missing or unsafe: {bundle}") from error
    bundle_is_reparse = bool(
        getattr(bundle_info, "st_file_attributes", 0) & 0x400
    )
    if (
        bundle.is_symlink()
        or bundle_is_reparse
        or not stat.S_ISDIR(bundle_info.st_mode)
    ):
        raise EvaluationError(f"Blind bundle is not a regular directory: {bundle}")
    output = bundle / "task-output.json"
    artifacts = bundle / "artifacts"
    if not artifacts.is_dir():
        raise EvaluationError(f"Incomplete blind bundle: {bundle}")
    return canonical_json_sha256(
        {
            "task-output.json": regular_file_sha256(
                output, "blind task output"
            ),
            "artifacts": directory_sha256(artifacts),
        }
    )


def regular_file_sha256(path: Path, label: str) -> str:
    """Hash one regular, non-linked file without following a reparse point."""

    try:
        info = path.lstat()
    except OSError as error:
        raise EvaluationError(f"{label} is missing or unsafe: {path}") from error
    is_reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if path.is_symlink() or is_reparse or not stat.S_ISREG(info.st_mode):
        raise EvaluationError(f"{label} is not a regular file: {path}")
    return file_sha256(path)


def copy_regular_file(source: Path, destination: Path, label: str) -> None:
    """Copy one regular file while refusing links and pre-existing targets."""

    regular_file_sha256(source, label)
    if destination.exists() or destination.is_symlink():
        raise EvaluationError(f"Refusing to overwrite {label}: {destination}")
    shutil.copy2(source, destination, follow_symlinks=False)


def copy_prepared_blind_bundle(source: Path, target: Path) -> None:
    """Copy a previously blinded A/B bundle into an isolated model workspace."""

    try:
        source_info = source.lstat()
    except OSError as error:
        raise EvaluationError(f"Blind bundle is missing or unsafe: {source}") from error
    source_is_reparse = bool(
        getattr(source_info, "st_file_attributes", 0) & 0x400
    )
    if (
        source.is_symlink()
        or source_is_reparse
        or not stat.S_ISDIR(source_info.st_mode)
    ):
        raise EvaluationError(f"Blind bundle is not a regular directory: {source}")
    target.mkdir()
    copy_regular_file(
        source / "task-output.json",
        target / "task-output.json",
        "blind task output",
    )
    artifacts = source / "artifacts"
    directory_sha256(artifacts)
    shutil.copytree(artifacts, target / "artifacts", symlinks=True)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def prepare_comparison_workspace(
    target: Path, intended_input_sha256: str
) -> tuple[Path, Path, Path, dict[str, Any], str, str]:
    """Stage only blinded inputs and the output schema outside durable evidence."""

    staging_root = Path(
        tempfile.mkdtemp(prefix="report-skills-comparator-")
    ).resolve()
    workspace = staging_root / "workspace"
    try:
        if _is_relative_to(staging_root, REPO_ROOT.resolve()) or _is_relative_to(
            staging_root, target.parent.parent.resolve()
        ):
            raise EvaluationError(
                "Comparator staging workspace must be outside the candidate and evidence trees"
            )
        workspace.mkdir()
        copy_prepared_blind_bundle(target / "A", workspace / "A")
        copy_prepared_blind_bundle(target / "B", workspace / "B")
        copy_regular_file(
            target / "case_contract.json",
            workspace / "case_contract.json",
            "comparison case contract",
        )
        staged_schema = workspace / "comparison-output.schema.json"
        copy_regular_file(
            COMPARISON_SCHEMA,
            staged_schema,
            "comparison output schema",
        )
        staged_input_sha256 = comparison_input_sha256(workspace)
        if staged_input_sha256 != intended_input_sha256:
            raise EvaluationError(
                "Staged comparison inputs do not match the durable intended bundle"
            )
        staged_schema_sha256 = regular_file_sha256(
            staged_schema, "staged comparison output schema"
        )
        if staged_schema_sha256 != regular_file_sha256(
            COMPARISON_SCHEMA, "comparison output schema"
        ):
            raise EvaluationError(
                "Staged comparison output schema does not match the candidate"
            )
        receipt = workspace_environment_receipt(workspace)
    except BaseException:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    return (
        staging_root,
        workspace,
        staged_schema,
        receipt,
        staged_input_sha256,
        staged_schema_sha256,
    )


def _normalized_path_text(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()


def scrub_and_validate_comparison_environment(
    execution_profile: dict[str, Any],
    workspace: Path,
    command: list[str],
    forbidden_paths: tuple[Path, ...],
) -> dict[str, str]:
    """Build the Git-fenced environment and remove durable path disclosures."""

    require_model_invocation_isolation(command, "Comparator model invocation")
    environment = task_runtime_environment(execution_profile, workspace)
    forbidden = tuple(
        _normalized_path_text(str(path.resolve())) for path in forbidden_paths
    )

    def discloses(value: object) -> bool:
        normalized = _normalized_path_text(str(value))
        return any(path and path in normalized for path in forbidden)

    for key in list(environment):
        if discloses(environment[key]):
            environment.pop(key, None)
    disclosed_args = [str(value) for value in command if discloses(value)]
    disclosed_environment = [
        key for key, value in environment.items() if discloses(value)
    ]
    if disclosed_args or disclosed_environment:
        raise EvaluationError(
            "Comparator model context discloses the candidate or durable evidence tree"
        )
    return environment


def clean_comparison_staging(staging_root: Path) -> None:
    """Remove comparator staging completely before final metadata is written."""

    try:
        shutil.rmtree(staging_root)
    except OSError as error:
        raise EvaluationError(
            f"Cannot clean comparator staging directory: {error}"
        ) from error
    if staging_root.exists():
        raise EvaluationError("Comparator staging directory still exists after cleanup")


def comparison_trace_isolation_validation_errors(
    path: Path, target: Path
) -> list[str]:
    """Reject collaboration, boundary commands, and the durable suite path."""

    errors = task_trace_isolation_validation_errors(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return errors
    durable_suite = _normalized_path_text(str(target.parent.parent.resolve()))
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        command = item.get("command")
        if isinstance(command, str) and durable_suite in _normalized_path_text(command):
            errors.append("comparator trace discloses the durable suite path")
            break
    return errors


def validate_comparison_output_binding(
    metadata: dict[str, Any], result_path: Path, contract_path: Path, target: Path
) -> list[str]:
    """Verify exact staged inputs, copied output, isolation receipt, and cleanup."""

    errors: list[str] = []
    errors.extend(
        stage_method_receipt_validation_errors(
            metadata, "blind_comparator", "comparison metadata"
        )
    )
    for key, path in (
        ("comparison_sha256", result_path),
        ("case_contract_sha256", contract_path),
        ("comparator_transcript_sha256", target / "comparator-transcript.jsonl"),
        ("comparator_stderr_sha256", target / "comparator-stderr.txt"),
    ):
        try:
            actual_sha256 = regular_file_sha256(path, path.name)
        except EvaluationError as error:
            errors.append(str(error))
            continue
        if metadata.get(key) != actual_sha256:
            errors.append(f"comparison metadata {key} mismatch")
    try:
        actual_comparison_sha256 = regular_file_sha256(
            result_path, "persisted comparison output"
        )
    except EvaluationError:
        actual_comparison_sha256 = None
    if metadata.get("staged_comparison_sha256") != actual_comparison_sha256:
        errors.append("comparison metadata staged_comparison_sha256 mismatch")
    try:
        actual_input_hash = comparison_input_sha256(target)
    except (EvaluationError, OSError) as exc:
        errors.append(f"cannot hash comparison inputs: {exc}")
    else:
        if metadata.get("comparison_input_sha256") != actual_input_hash:
            errors.append("comparison metadata comparison_input_sha256 mismatch")
        if metadata.get("staged_comparison_input_sha256") != actual_input_hash:
            errors.append(
                "comparison metadata staged_comparison_input_sha256 mismatch"
            )
        if (
            metadata.get("post_execution_staged_comparison_input_sha256")
            != actual_input_hash
        ):
            errors.append(
                "comparison metadata post-execution staged input mismatch"
            )
    try:
        expected_schema_sha256 = regular_file_sha256(
            COMPARISON_SCHEMA, "comparison output schema"
        )
    except EvaluationError as error:
        errors.append(str(error))
    else:
        if metadata.get("comparison_schema_sha256") != expected_schema_sha256:
            errors.append("comparison metadata comparison_schema_sha256 mismatch")
    if metadata.get("comparison_staging_schema_version") != (
        COMPARISON_STAGING_SCHEMA_VERSION
    ):
        errors.append("comparison staging receipt version mismatch")
    if metadata.get("staging_cleanup_completed") is not True:
        errors.append("comparison staging cleanup receipt is invalid")
    errors.extend(
        workspace_environment_receipt_validation_errors(metadata, "comparison")
    )
    workspace_receipt = metadata.get("workspace_environment")
    if isinstance(workspace_receipt, dict):
        workspace_value = workspace_receipt.get("workspace")
        if isinstance(workspace_value, str):
            staged_workspace = Path(workspace_value)
            if staged_workspace.exists() or staged_workspace.is_symlink():
                errors.append("comparison staging workspace was not cleaned")
            try:
                if _is_relative_to(
                    staged_workspace.resolve(), target.parent.parent.resolve()
                ):
                    errors.append(
                        "comparison staging workspace is inside the durable suite tree"
                    )
            except (OSError, RuntimeError):
                errors.append("comparison staging workspace path is invalid")
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
    errors.extend(
        comparison_trace_isolation_validation_errors(
            target / "comparator-transcript.jsonl", target
        )
    )
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
        if args.execute and args.timeout != CANONICAL_COMPARATOR_TIMEOUT_SECONDS:
            raise EvaluationError(
                "Release comparison requires the canonical "
                f"{CANONICAL_COMPARATOR_TIMEOUT_SECONDS}-second timeout"
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
                "blind_comparator",
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
            copy_regular_file(
                pair["runs"][mapping["A"]] / "case_contract.json",
                target / "case_contract.json",
                "comparison case contract",
            )
            contract = load_json(target / "case_contract.json")
            result_path = target / "comparison.json"
            intended_input_sha256 = comparison_input_sha256(target)
            (
                staging_root,
                comparison_workspace,
                staged_schema,
                workspace_receipt,
                staged_input_sha256,
                staged_schema_sha256,
            ) = prepare_comparison_workspace(target, intended_input_sha256)
            staged_result_path = comparison_workspace / "comparison.json"
            try:
                command = codex_base_command(
                    codex_runtime_command(execution_profile),
                    cwd=comparison_workspace,
                    sandbox="read-only",
                    output_schema=staged_schema,
                    output_message=staged_result_path,
                    model=execution_profile["model"],
                    reasoning_effort=execution_profile["reasoning_effort"],
                )
                environment = scrub_and_validate_comparison_environment(
                    execution_profile,
                    comparison_workspace,
                    command,
                    (REPO_ROOT, suite_run_dir, target),
                )
                require_unchanged_repository(repo_receipt)
                result = run_codex(
                    command,
                    comparison_prompt(pair, contract),
                    args.timeout,
                    environment=environment,
                )
                require_unchanged_repository(repo_receipt)
                transcript_path = target / "comparator-transcript.jsonl"
                stderr_path = target / "comparator-stderr.txt"
                transcript_path.write_text(
                    result.stdout, encoding="utf-8", newline="\n"
                )
                stderr_path.write_text(result.stderr, encoding="utf-8", newline="\n")
                validation_errors = execution_receipt_validation_errors(
                    result, args.timeout, "comparator"
                )
                validation_errors.extend(
                    comparison_trace_isolation_validation_errors(
                        transcript_path, target
                    )
                )
                try:
                    post_execution_staged_input_sha256 = comparison_input_sha256(
                        comparison_workspace
                    )
                except (EvaluationError, OSError) as error:
                    post_execution_staged_input_sha256 = None
                    validation_errors.append(
                        f"cannot rehash staged comparison inputs: {error}"
                    )
                else:
                    if post_execution_staged_input_sha256 != intended_input_sha256:
                        validation_errors.append(
                            "staged comparison inputs changed during model execution"
                        )
                try:
                    post_execution_schema_sha256 = regular_file_sha256(
                        staged_schema, "staged comparison output schema"
                    )
                except EvaluationError as error:
                    validation_errors.append(str(error))
                else:
                    if post_execution_schema_sha256 != staged_schema_sha256:
                        validation_errors.append(
                            "staged comparison output schema changed during model execution"
                        )
                staged_comparison_sha256: str | None = None
                if not staged_result_path.exists() and not staged_result_path.is_symlink():
                    validation_errors.append("comparison.json was not produced")
                else:
                    try:
                        staged_comparison_sha256 = regular_file_sha256(
                            staged_result_path, "staged comparison output"
                        )
                    except EvaluationError as error:
                        validation_errors.append(str(error))
                    else:
                        copy_regular_file(
                            staged_result_path,
                            result_path,
                            "persisted comparison output",
                        )
                        persisted_comparison_sha256 = regular_file_sha256(
                            result_path, "persisted comparison output"
                        )
                        if persisted_comparison_sha256 != staged_comparison_sha256:
                            raise EvaluationError(
                                "Persisted comparison output does not match staging"
                            )
                try:
                    post_execution_durable_input_sha256 = comparison_input_sha256(
                        target
                    )
                except (EvaluationError, OSError) as error:
                    validation_errors.append(
                        f"cannot rehash durable comparison inputs: {error}"
                    )
                else:
                    if post_execution_durable_input_sha256 != intended_input_sha256:
                        validation_errors.append(
                            "durable comparison inputs changed during model execution"
                        )
                comparison_winner = None
                if staged_comparison_sha256 is not None and not validation_errors:
                    try:
                        comparison = load_json(result_path)
                    except EvaluationError as exc:
                        validation_errors.append(str(exc))
                    else:
                        comparison_winner = comparison.get("winner")
                        validation_errors.extend(
                            validate_comparison(comparison, contract)
                        )
            finally:
                clean_comparison_staging(staging_root)
            require_unchanged_repository(repo_receipt)
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
                "comparison_sha256": (
                    regular_file_sha256(result_path, "persisted comparison output")
                    if result_path.is_file() and not result_path.is_symlink()
                    else None
                ),
                "staged_comparison_sha256": staged_comparison_sha256,
                "case_contract_sha256": regular_file_sha256(
                    target / "case_contract.json", "comparison case contract"
                ),
                "comparison_input_sha256": intended_input_sha256,
                "staged_comparison_input_sha256": staged_input_sha256,
                "post_execution_staged_comparison_input_sha256": (
                    post_execution_staged_input_sha256
                ),
                "comparison_schema_sha256": staged_schema_sha256,
                "comparison_staging_schema_version": (
                    COMPARISON_STAGING_SCHEMA_VERSION
                ),
                "staging_cleanup_completed": True,
                "workspace_environment": workspace_receipt,
                "comparator_transcript_sha256": file_sha256(
                    target / "comparator-transcript.jsonl"
                ),
                "comparator_stderr_sha256": file_sha256(
                    target / "comparator-stderr.txt"
                ),
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
                "model_isolation": canonical_model_isolation_receipt(),
                "evaluation_method_version": EVALUATION_METHOD_VERSION,
                "stage_method": canonical_blind_comparator_stage_method(),
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
