#!/usr/bin/env python3
"""Validate behavioral benchmark, threshold, trigger, and output contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evaluation_common import (
    DEFAULT_THRESHOLDS,
    DEFAULT_TRIGGERS,
    EVAL_ROOT,
    EvaluationError,
    REPO_ROOT,
    build_run_plan,
    configuration_ids,
    configured_repetitions,
    load_json,
    normalize_suite,
    resolve_suite,
    suite_cases,
    suite_fixture,
)


REQUIRED_GATES = {
    "per_skill_median_score",
    "blocking_failures",
    "adversarial_pass_rate",
    "blind_with_skill_win_rate",
    "trigger_precision",
    "trigger_recall",
    "integrity_events",
    "unauthorized_external_mutations",
}
MODEL_OUTPUT_SCHEMAS = {
    "task-run-output.schema.json",
    "grading-output.schema.json",
    "blind-comparison-output.schema.json",
    "trigger-output.schema.json",
}


def validate_model_output_schema(
    value: Any, schema_name: str, errors: list[str], location: str = "$"
) -> None:
    """Enforce the strict object shape required by Codex structured outputs."""
    if isinstance(value, dict):
        properties = value.get("properties")
        if value.get("type") == "object":
            if value.get("additionalProperties") is not False:
                errors.append(
                    f"{schema_name}{location}: object schemas must set additionalProperties to false"
                )
            if not isinstance(properties, dict):
                errors.append(f"{schema_name}{location}: object schemas must declare properties")
            else:
                required = value.get("required", [])
                if not isinstance(required, list) or set(required) != set(properties):
                    errors.append(
                        f"{schema_name}{location}: every declared object property must be required; "
                        f"required={sorted(required) if isinstance(required, list) else required}, "
                        f"properties={sorted(properties)}"
                    )
        for key, child in value.items():
            validate_model_output_schema(child, schema_name, errors, f"{location}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_model_output_schema(child, schema_name, errors, f"{location}/{index}")


def validate_suite(path: Path, suite: dict[str, Any], errors: list[str]) -> None:
    repetitions = configured_repetitions(suite)
    if repetitions < 3:
        errors.append("suite protocol must require at least three repetitions per configuration")
    configs = configuration_ids(suite)
    if set(configs) != {"with_skill", "without_skill"}:
        errors.append(f"suite configurations must be with_skill and without_skill, got {configs}")
    cases = suite_cases(suite)
    primary = suite.get("primary_cases", [])
    adversarial = suite.get("adversarial_cases", [])
    if len(primary) != 11 or len({case.get("skill") for case in primary}) != 11:
        errors.append("suite must contain exactly 11 primary cases covering 11 unique skills")
    if len(adversarial) != 5:
        errors.append("suite must contain exactly 5 adversarial cases")
    legacy_path = path.parent / "evals.json"
    if legacy_path.is_file() and path.name != "evals.json":
        legacy_ids = {case.get("case_id") for case in load_json(legacy_path).get("adversarial_cases", [])}
        if {case.get("case_id") for case in adversarial} != legacy_ids:
            errors.append("benchmark adversarial case IDs must exactly match evals.json")
    ids = [str(case.get("case_id", "")) for case in cases]
    if any(not case_id for case_id in ids):
        errors.append("every benchmark case needs a case_id")
    if len(ids) != len(set(ids)):
        errors.append("benchmark case_id values must be unique")
    if not suite.get("primary_cases"):
        errors.append("suite must include primary_cases")
    if not suite.get("adversarial_cases"):
        errors.append("suite must include adversarial_cases")
    all_assertion_ids: list[str] = []
    for case in cases:
        prefix = str(case.get("case_id", "unknown"))
        skill = case.get("skill")
        if not isinstance(skill, str) or not (REPO_ROOT / "skills" / skill / "SKILL.md").is_file():
            errors.append(f"{prefix}: skill package does not exist: {skill}")
        if not str(case.get("prompt", "")).strip():
            errors.append(f"{prefix}: prompt is required")
        assertions = case.get("assertions", [])
        if not isinstance(assertions, list) or not assertions:
            errors.append(f"{prefix}: at least one assertion is required")
            continue
        assertion_ids = [item.get("assertion_id") for item in assertions if isinstance(item, dict)]
        all_assertion_ids.extend(str(value) for value in assertion_ids if value)
        if len(assertion_ids) != len(set(assertion_ids)) or any(not value for value in assertion_ids):
            errors.append(f"{prefix}: assertion_id values must be present and unique")
        total = 0.0
        blocking_count = 0
        for assertion in assertions:
            if not isinstance(assertion, dict):
                errors.append(f"{prefix}: every assertion must be an object")
                continue
            weight = assertion.get("weight")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
                errors.append(f"{prefix}/{assertion.get('assertion_id')}: weight must be positive")
            else:
                total += float(weight)
            if not isinstance(assertion.get("blocking"), bool):
                errors.append(f"{prefix}/{assertion.get('assertion_id')}: blocking must be boolean")
            elif assertion["blocking"]:
                blocking_count += 1
            if not str(assertion.get("text", "")).strip():
                errors.append(f"{prefix}/{assertion.get('assertion_id')}: text is required")
        if abs(total - 100.0) > 0.01:
            errors.append(f"{prefix}: assertion weights must sum to 100, got {total:g}")
        if blocking_count == 0:
            errors.append(f"{prefix}: at least one assertion must be blocking")
    if len(all_assertion_ids) != len(set(all_assertion_ids)):
        errors.append("assertion_id values must be unique across the complete benchmark suite")
    fixture = suite_fixture(path, suite)
    if not fixture.is_dir():
        errors.append(f"suite fixture does not exist: {fixture}")


def validate_thresholds(data: dict[str, Any], errors: list[str]) -> None:
    gates = data.get("hard_gates")
    if not isinstance(gates, dict):
        errors.append("release thresholds must contain hard_gates")
        return
    missing = REQUIRED_GATES - set(gates)
    if missing:
        errors.append(f"release thresholds missing hard gates: {sorted(missing)}")
    for name, gate in gates.items():
        if not isinstance(gate, dict):
            errors.append(f"hard gate {name} must be an object")
            continue
        if gate.get("operator") not in {">=", ">", "==", "<=", "<"}:
            errors.append(f"hard gate {name} has unsupported operator")
        if not isinstance(gate.get("value"), (int, float)) or isinstance(gate.get("value"), bool):
            errors.append(f"hard gate {name} needs a numeric value")
        if gate.get("compensable") is not False:
            errors.append(f"hard gate {name} must be non-compensable")
    for name in ("trigger_precision", "trigger_recall"):
        if set(gates.get(name, {}).get("required_breakdowns", [])) != {"suite_wide", "per_skill"}:
            errors.append(f"hard gate {name} must require suite_wide and per_skill breakdowns")


def validate_triggers(data: dict[str, Any], skills: set[str], errors: list[str]) -> None:
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("trigger evals must contain cases")
        return
    repetitions = data.get("protocol", {}).get("repetitions_per_case", 0)
    if not isinstance(repetitions, int) or repetitions < 3:
        errors.append("trigger evals must require at least three repetitions per case")
    ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        errors.append("trigger case_id values must be present and unique")
    positives = negatives = 0
    covered: set[str] = set()
    by_skill: dict[str, dict[str, int]] = {
        skill: {"positive": 0, "negative": 0} for skill in skills
    }
    policies = data.get("protocol", {}).get("invocation_policies", {})
    implicit = set(policies.get("implicit_selection", {}).get("skills", []))
    explicit_only = set(policies.get("explicit_invocation", {}).get("skills", []))
    if implicit & explicit_only or implicit | explicit_only != skills:
        errors.append("trigger invocation-policy lists must be disjoint and cover every skill")
    for case in cases:
        if not isinstance(case, dict):
            errors.append("every trigger case must be an object")
            continue
        candidate = case.get("candidate_skill")
        if candidate not in skills:
            errors.append(f"trigger {case.get('case_id')}: unknown candidate_skill {candidate}")
        else:
            covered.add(candidate)
        if not isinstance(case.get("should_trigger"), bool):
            errors.append(f"trigger {case.get('case_id')}: should_trigger must be boolean")
        elif case["should_trigger"]:
            positives += 1
            if candidate in by_skill:
                by_skill[candidate]["positive"] += 1
        else:
            negatives += 1
            if candidate in by_skill:
                by_skill[candidate]["negative"] += 1
        if not str(case.get("query", "")).strip():
            errors.append(f"trigger {case.get('case_id')}: query is required")
        policy = case.get("invocation_policy")
        names_candidate = case.get("query_names_candidate_skill")
        exact_name_present = f"${candidate}" in str(case.get("query", ""))
        if names_candidate is not exact_name_present:
            errors.append(f"trigger {case.get('case_id')}: query_names_candidate_skill does not match the literal query")
        if candidate in explicit_only:
            if policy != "explicit_invocation":
                errors.append(f"trigger {case.get('case_id')}: explicit-only skill has wrong invocation policy")
            if case.get("should_trigger") is not exact_name_present:
                errors.append(f"trigger {case.get('case_id')}: explicit selection must equal exact-name presence")
        elif candidate in skills:
            if policy != "implicit_selection":
                errors.append(f"trigger {case.get('case_id')}: implicit skill has wrong invocation policy")
            if names_candidate is not False:
                errors.append(f"trigger {case.get('case_id')}: implicit-selection query must not name the skill")
    if positives == 0 or negatives == 0:
        errors.append("trigger evals require both positive and negative examples")
    if covered != skills:
        errors.append(f"trigger evals must cover every skill; missing {sorted(skills - covered)}")
    if len(cases) != 25 or len(cases) != data.get("expected_case_count"):
        errors.append("trigger evals must contain exactly the declared 25 cases")
    for skill, counts in sorted(by_skill.items()):
        expected = {"positive": 1, "negative": 2 if skill in explicit_only else 1}
        if counts != expected:
            errors.append(f"trigger distribution for {skill} must be {expected}, got {counts}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--triggers", type=Path, default=DEFAULT_TRIGGERS)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    errors: list[str] = []
    try:
        suite_path = resolve_suite(args.suite)
        suite = normalize_suite(load_json(suite_path))
        validate_suite(suite_path, suite, errors)
        thresholds = load_json(args.thresholds)
        validate_thresholds(thresholds, errors)
        triggers = load_json(args.triggers)
        skills = {case["skill"] for case in suite.get("primary_cases", [])}
        validate_triggers(triggers, skills, errors)
        for schema in sorted((EVAL_ROOT / "schemas").glob("*.json")):
            try:
                schema_data = json.loads(schema.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"invalid schema JSON {schema.name}: {exc}")
            else:
                if schema.name in MODEL_OUTPUT_SCHEMAS:
                    validate_model_output_schema(schema_data, schema.name, errors)
        plan = build_run_plan(suite, configured_repetitions(suite, thresholds))
        expected = len(suite_cases(suite)) * 2 * configured_repetitions(suite, thresholds)
        if len(plan) != expected:
            errors.append(f"run plan mismatch: expected {expected}, got {len(plan)}")
    except EvaluationError as exc:
        errors.append(str(exc))
    if errors:
        print(f"Evaluation contract validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "Evaluation contracts passed: "
        f"{len(suite.get('primary_cases', []))} primary cases, "
        f"{len(suite.get('adversarial_cases', []))} adversarial cases, "
        f"{len(triggers.get('cases', []))} trigger cases, {len(plan)} paired-configuration observations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
