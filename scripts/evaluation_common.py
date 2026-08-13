#!/usr/bin/env python3
"""Shared helpers for the Report Skills behavioral evaluation tooling."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = REPO_ROOT / "evals"
DEFAULT_SUITE = EVAL_ROOT / "benchmark-suite.json"
LEGACY_SUITE = EVAL_ROOT / "evals.json"
DEFAULT_THRESHOLDS = EVAL_ROOT / "release-thresholds.json"
DEFAULT_TRIGGERS = EVAL_ROOT / "trigger-evals.json"
DEFAULT_RUNS_ROOT = EVAL_ROOT / "runs"
DEFAULT_REVIEW_ROOT = EVAL_ROOT / "review"
RESULTS_ROOT = (EVAL_ROOT / "results").resolve()
REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
PROFILE_IDENTITY_KEYS = (
    "model",
    "reasoning_effort",
    "codex_cli_version",
    "codex_command_sha256",
    "codex_implementation_sha256",
    "selected_model_sha256",
    "python_version",
    "platform",
)
REPOSITORY_IDENTITY_KEYS = ("commit", "tree", "dirty")


class EvaluationError(RuntimeError):
    """Raised for a user-correctable evaluation configuration error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def directory_sha256(root: Path) -> str:
    """Hash a directory deterministically from relative paths and file bytes."""

    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_directory_sha256(root: Path) -> str:
    """Hash only Git-tracked files under a release-evaluated directory."""

    relative_root = root.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={REPO_ROOT}",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "--",
            relative_root,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if result.returncode != 0:
        raise EvaluationError(
            f"Cannot list tracked files for {root}: {result.stderr.strip() or result.stdout.strip()}"
        )
    tracked = [line for line in result.stdout.splitlines() if line]
    if not tracked:
        raise EvaluationError(f"No Git-tracked files found under {root}")
    actual = [path for path in sorted(root.rglob("*")) if path.is_file()]
    tracked_paths = [(REPO_ROOT / path).resolve() for path in tracked]
    extras = sorted(path.relative_to(root).as_posix() for path in set(actual) - set(tracked_paths))
    if extras:
        raise EvaluationError(f"Untracked or ignored files affect evaluated directory {root}: {extras}")
    digest = hashlib.sha256()
    for relative, path in sorted(zip(tracked, tracked_paths, strict=True)):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def repository_receipt(require_clean: bool = False) -> dict[str, Any]:
    """Return the exact candidate Git state used by a model-backed run."""

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={REPO_ROOT}", "-C", str(REPO_ROOT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise EvaluationError(f"Cannot record repository state: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout.strip()

    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if root != REPO_ROOT.resolve():
        raise EvaluationError(f"Git root mismatch: expected {REPO_ROOT.resolve()}, got {root}")
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    dirty = bool(status)
    if require_clean and dirty:
        raise EvaluationError("Refusing a release evaluation from a dirty repository; commit or remove candidate changes first")
    return {"root": str(root), "commit": commit, "tree": tree, "dirty": dirty}


def require_pinned_profile(execute: bool, model: str | None, reasoning_effort: str | None) -> None:
    if execute and (not model or not reasoning_effort):
        raise EvaluationError("Live evaluation requires both --model and --reasoning-effort for reproducibility")


def codex_execution_profile(codex_command: str, model: str, reasoning_effort: str) -> dict[str, Any]:
    """Verify and record the exact Codex CLI/model profile used for live calls."""

    version_result = subprocess.run(
        [codex_command, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    if version_result.returncode != 0:
        raise EvaluationError(
            "Cannot record Codex CLI version: "
            + (version_result.stderr.strip() or version_result.stdout.strip())
        )
    version = version_result.stdout.strip()

    catalog_result = subprocess.run(
        [codex_command, "debug", "models"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=120,
    )
    if catalog_result.returncode != 0:
        raise EvaluationError(
            "Cannot verify the live Codex model catalog: "
            + (catalog_result.stderr.strip() or catalog_result.stdout.strip())
        )
    try:
        catalog = json.loads(catalog_result.stdout)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Codex returned an invalid model catalog: {exc}") from exc
    entries = catalog.get("models", []) if isinstance(catalog, dict) else []
    selected = next((item for item in entries if item.get("slug") == model), None)
    if selected is None:
        raise EvaluationError(f"Pinned model is not available in the live Codex catalog: {model}")
    supported = {
        item.get("effort")
        for item in selected.get("supported_reasoning_levels", [])
        if isinstance(item, dict)
    }
    if reasoning_effort not in supported:
        raise EvaluationError(
            f"Reasoning effort {reasoning_effort!r} is not supported by {model}; "
            f"available efforts: {sorted(value for value in supported if value)}"
        )
    resolved_command = Path(codex_command).resolve()
    command_hash = hashlib.sha256(resolved_command.read_bytes()).hexdigest()
    implementation = resolved_command
    npm_package = resolved_command.parent / "node_modules" / "@openai" / "codex"
    if npm_package.is_dir():
        executable_name = "codex.exe" if sys.platform == "win32" else "codex"
        candidates = sorted(
            path.resolve()
            for path in (npm_package / "node_modules" / "@openai").glob(
                f"codex-*/vendor/**/bin/{executable_name}"
            )
            if path.is_file()
        )
        if len(candidates) == 1:
            implementation = candidates[0]
    implementation_hash = hashlib.sha256(implementation.read_bytes()).hexdigest()
    selected_json = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "codex_cli_version": version,
        "codex_command": str(resolved_command),
        "codex_command_sha256": command_hash,
        "codex_implementation": str(implementation),
        "codex_implementation_sha256": implementation_hash,
        "model_catalog_sha256": hashlib.sha256(catalog_result.stdout.encode("utf-8")).hexdigest(),
        "selected_model_sha256": hashlib.sha256(selected_json.encode("utf-8")).hexdigest(),
        "model_default_reasoning_effort": str(selected.get("default_reasoning_level")),
        "model_supported_reasoning_efforts": sorted(value for value in supported if value),
        "python_version": platform.python_version(),
        "platform": f"{platform.system()}-{platform.release()}-{platform.machine()}",
    }


def require_matching_context(
    expected_profile: dict[str, Any],
    expected_repository: dict[str, Any],
    actual_profile: dict[str, Any],
    actual_repository: dict[str, Any],
    label: str,
) -> None:
    expected_profile_identity = {key: expected_profile.get(key) for key in PROFILE_IDENTITY_KEYS}
    actual_profile_identity = {key: actual_profile.get(key) for key in PROFILE_IDENTITY_KEYS}
    if actual_profile_identity != expected_profile_identity or any(
        value in {None, ""} for value in actual_profile_identity.values()
    ):
        raise EvaluationError(
            f"{label} execution profile does not match the benchmark plan: "
            f"expected {expected_profile_identity}, got {actual_profile_identity}"
        )
    expected_repository_identity = {
        key: expected_repository.get(key) for key in REPOSITORY_IDENTITY_KEYS
    }
    actual_repository_identity = {
        key: actual_repository.get(key) for key in REPOSITORY_IDENTITY_KEYS
    }
    if actual_repository_identity != expected_repository_identity or actual_repository_identity.get("dirty") is not False:
        raise EvaluationError(
            f"{label} repository receipt does not match the benchmark plan: "
            f"expected {expected_repository_identity}, got {actual_repository_identity}"
        )


def require_unchanged_repository(expected: dict[str, Any]) -> None:
    """Abort a long run if the candidate Git state changes between calls."""

    current = repository_receipt(require_clean=True)
    if current != expected:
        raise EvaluationError(
            f"Repository changed during evaluation: expected {expected}, got {current}"
        )


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n")


def resolve_suite(path: Path | None = None) -> Path:
    if path:
        return path.resolve()
    return DEFAULT_SUITE if DEFAULT_SUITE.is_file() else LEGACY_SUITE


def _legacy_assertions(case: dict[str, Any]) -> list[dict[str, Any]]:
    checks = case.get("blocking_checks", [])
    if not isinstance(checks, list) or not checks:
        raise EvaluationError(f"Legacy case {case.get('case_id')} has no blocking_checks")
    weight = 100.0 / len(checks)
    return [
        {
            "assertion_id": f"{case['case_id']}.a{index:02d}",
            "category": "legacy_blocking_check",
            "text": str(check),
            "weight": weight,
            "blocking": True,
        }
        for index, check in enumerate(checks, 1)
    ]


def normalize_suite(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the v1 benchmark contract and the original eval inventory."""
    if "primary_cases" in data:
        result = dict(data)
        result.setdefault("protocol", {})
        result["protocol"].setdefault("repetitions_per_configuration", 3)
        result["protocol"].setdefault(
            "configurations", [{"id": "with_skill"}, {"id": "without_skill"}]
        )
        return result

    if "cases" not in data:
        raise EvaluationError("Suite must contain primary_cases or legacy cases")
    primary_cases = []
    for raw in data.get("cases", []):
        case = dict(raw)
        case["assertions"] = _legacy_assertions(case)
        primary_cases.append(case)
    adversarial = []
    for raw in data.get("adversarial_cases", []):
        case = dict(raw)
        case.setdefault("skill", "report-skills")
        required = str(case.get("required_result", "Required safe behavior is present."))
        case["assertions"] = [
            {
                "assertion_id": f"{case['case_id']}.a01",
                "category": "legacy_adversarial_check",
                "text": required,
                "weight": 100,
                "blocking": True,
            }
        ]
        adversarial.append(case)
    return {
        "schema_version": data.get("schema_version", "1.0"),
        "suite_id": "legacy-evals-compatible",
        "fixture": data.get("fixture", "../examples/synthetic-report"),
        "protocol": {
            "repetitions_per_configuration": 3,
            "configurations": [{"id": "with_skill"}, {"id": "without_skill"}],
        },
        "primary_cases": primary_cases,
        "adversarial_cases": adversarial,
    }


def suite_cases(suite: dict[str, Any], include_adversarial: bool = True) -> list[dict[str, Any]]:
    cases = [dict(case, case_kind="primary") for case in suite.get("primary_cases", [])]
    if include_adversarial:
        cases.extend(dict(case, case_kind="adversarial") for case in suite.get("adversarial_cases", []))
    return cases


def suite_fixture(suite_path: Path, suite: dict[str, Any]) -> Path:
    raw = Path(str(suite.get("fixture", "../examples/synthetic-report")))
    return (suite_path.parent / raw).resolve() if not raw.is_absolute() else raw.resolve()


def configured_repetitions(suite: dict[str, Any], thresholds: dict[str, Any] | None = None) -> int:
    candidates = [
        suite.get("protocol", {}).get("repetitions_per_configuration"),
        suite.get("protocol", {}).get("runs_per_configuration"),
        (thresholds or {}).get("runs_per_configuration"),
        (thresholds or {}).get("protocol", {}).get("runs_per_configuration"),
    ]
    for candidate in candidates:
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return 3


def configuration_ids(suite: dict[str, Any]) -> list[str]:
    values = suite.get("protocol", {}).get("configurations", [])
    ids = [value.get("id") if isinstance(value, dict) else value for value in values]
    ids = [str(value) for value in ids if value]
    return ids or ["with_skill", "without_skill"]


def build_run_plan(
    suite: dict[str, Any],
    repetitions: int,
    configurations: Iterable[str] | None = None,
    selected_cases: set[str] | None = None,
    include_adversarial: bool = True,
) -> list[dict[str, Any]]:
    configs = list(configurations or configuration_ids(suite))
    cases = suite_cases(suite, include_adversarial=include_adversarial)
    plan: list[dict[str, Any]] = []
    for case in cases:
        if selected_cases and case["case_id"] not in selected_cases:
            continue
        for repetition in range(1, repetitions + 1):
            for configuration in configs:
                run_id = f"{case['case_id']}__{configuration}__r{repetition:02d}"
                plan.append(
                    {
                        "run_id": run_id,
                        "pair_id": f"{case['case_id']}__r{repetition:02d}",
                        "case_id": case["case_id"],
                        "case_kind": case["case_kind"],
                        "skill": case.get("skill", "report-skills"),
                        "configuration": configuration,
                        "repetition": repetition,
                        "prompt": case["prompt"],
                        "required_result": case.get("required_result"),
                        "assertions": case.get("assertions", []),
                    }
                )
    return plan


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_output_root(path: Path, allow_tracked_output: bool = False) -> Path:
    resolved = path.resolve()
    if is_relative_to(resolved, RESULTS_ROOT) and not allow_tracked_output:
        raise EvaluationError(
            f"Refusing raw run output inside tracked eval results: {resolved}. "
            "Use evals/runs or pass --allow-tracked-output deliberately."
        )
    return resolved


def parse_skill_description(skill_path: Path) -> str:
    text = skill_path.read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip().strip("\"'")


def baseline_contamination_paths(skills: Iterable[str]) -> list[str]:
    """Return auto-discoverable installations that can invalidate a baseline."""
    roots = [Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"]
    extra = os.environ.get("REPORT_SKILLS_DISCOVERY_ROOTS", "")
    roots.extend(Path(value) for value in extra.split(os.pathsep) if value)
    found: list[str] = []
    for root in roots:
        for skill in skills:
            candidate = root / skill / "SKILL.md"
            if candidate.is_file():
                found.append(str(candidate.resolve()))
    return sorted(set(found))


def find_codex_command(requested: str | None = None) -> str:
    if requested:
        resolved = shutil.which(requested)
        if not resolved:
            raise EvaluationError(f"Codex command not found: {requested}")
        return resolved
    for name in ("codex.cmd", "codex") if sys.platform == "win32" else ("codex", "codex.cmd"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise EvaluationError("Codex CLI not found on PATH")


def codex_base_command(
    codex_command: str,
    cwd: Path,
    sandbox: str,
    output_schema: Path,
    output_message: Path,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> list[str]:
    command = [
        codex_command,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--json",
        "--sandbox",
        sandbox,
        "--cd",
        str(cwd),
        "--output-schema",
        str(output_schema.resolve()),
        "--output-last-message",
        str(output_message.resolve()),
    ]
    if model:
        command.extend(["--model", model])
    if reasoning_effort:
        command.extend(["--config", f'model_reasoning_effort="{reasoning_effort}"'])
    command.append("-")
    return command


@dataclass
class CommandResult:
    returncode: int
    wall_clock_seconds: float
    stdout: str
    stderr: str


def run_codex(command: list[str], prompt: str, timeout: int) -> CommandResult:
    start = time.perf_counter()
    try:
        process = subprocess.run(
            command,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        return CommandResult(124, elapsed, exc.stdout or "", exc.stderr or "Timed out")
    return CommandResult(
        process.returncode,
        time.perf_counter() - start,
        process.stdout,
        process.stderr,
    )


def token_usage_from_jsonl(text: str) -> dict[str, int | None]:
    """Best-effort extraction across Codex JSONL event versions."""
    best: dict[str, int | None] = {"input_tokens": None, "output_tokens": None, "total_tokens": None}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            aliases = {
                "input_tokens": ("input_tokens", "prompt_tokens"),
                "output_tokens": ("output_tokens", "completion_tokens"),
                "total_tokens": ("total_tokens",),
            }
            for target, keys in aliases.items():
                for key in keys:
                    candidate = value.get(key)
                    if isinstance(candidate, int) and (best[target] is None or candidate > best[target]):
                        best[target] = candidate
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for line in text.splitlines():
        try:
            visit(json.loads(line))
        except json.JSONDecodeError:
            continue
    if best["total_tokens"] is None and best["input_tokens"] is not None and best["output_tokens"] is not None:
        best["total_tokens"] = int(best["input_tokens"]) + int(best["output_tokens"])
    return best


def safe_copy_fixture(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise EvaluationError(f"Fixture directory does not exist: {source}")
    if destination.exists():
        raise EvaluationError(f"Refusing to overwrite existing workspace: {destination}")
    shutil.copytree(source, destination)


def median(values: Iterable[float | int]) -> float | None:
    items = [float(value) for value in values]
    return statistics.median(items) if items else None


def summary_stats(values: Iterable[float | int]) -> dict[str, float | int | None]:
    items = [float(value) for value in values]
    if not items:
        return {"count": 0, "mean": None, "median": None, "stddev": None, "min": None, "max": None}
    return {
        "count": len(items),
        "mean": statistics.mean(items),
        "median": statistics.median(items),
        "stddev": statistics.pstdev(items),
        "min": min(items),
        "max": max(items),
    }


def compare(operator: str, actual: float | int, expected: float | int) -> bool:
    operations = {
        ">=": lambda: actual >= expected,
        ">": lambda: actual > expected,
        "==": lambda: actual == expected,
        "<=": lambda: actual <= expected,
        "<": lambda: actual < expected,
    }
    if operator not in operations:
        raise EvaluationError(f"Unsupported threshold operator: {operator}")
    return bool(operations[operator]())
