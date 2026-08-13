#!/usr/bin/env python3
"""Shared helpers for the Report Skills behavioral evaluation tooling."""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
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


class EvaluationError(RuntimeError):
    """Raised for a user-correctable evaluation configuration error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


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
