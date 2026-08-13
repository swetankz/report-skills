# Evaluation

Report Skills uses two complementary evaluation layers. Offline checks protect the repository contract on every pull request. Behavioral benchmarks measure whether using a skill improves an agent's work and whether its safety boundaries hold. Passing the offline checks does not, by itself, prove behavioral quality.

## Evaluation assets

- `evals/benchmark-suite.json` defines the paired task cases, adversarial cases, objective assertions, and run protocol.
- `evals/evals.json` retains the original synthetic forward-test inventory for compatibility and historical comparison.
- `evals/release-thresholds.json` is the machine-readable release policy.
- `evals/trigger-evals.json` contains realistic should-trigger and should-not-trigger queries.
- `evals/schemas/` defines the machine-readable contracts used by offline validation.
- `evals/rubric.md` explains the scored dimensions.
- `evals/results/` contains sanitized, publishable result summaries. Raw transcripts, temporary workspaces, credentials, and private artifacts must not be committed.

## Offline checks

Run these checks before starting model-backed evaluation:

```text
python scripts/validate_eval_suite.py
python scripts/run_behavioral_benchmark.py --dry-run
python scripts/run_behavioral_benchmark.py --dry-run --show-plan
python scripts/run_trigger_evals.py --dry-run
python -m unittest discover -s tests
```

`validate_eval_suite.py` checks the contracts, case coverage, and release-policy consistency. The default behavioral dry run prints a compact summary; `--show-plan` includes every planned observation. Dry runs do not start Codex or make a paid model call. CI runs the compact contract and benchmark-plan checks, but deliberately does not run live behavioral or trigger evaluations because those require authentication, incur usage, and are sensitive to model and environment drift.

## End-to-end local run

After reviewing both dry-run plans, run the authenticated workflow locally with explicit run identifiers:

```text
python scripts/run_behavioral_benchmark.py --execute --run-id <benchmark-id> --model <model> --reasoning-effort <effort>
python scripts/grade_behavioral_benchmark.py evals/runs/<benchmark-id> --execute --model <model> --reasoning-effort <effort>
python scripts/run_blind_comparisons.py evals/runs/<benchmark-id> --execute --seed <seed> --model <model> --reasoning-effort <effort>
python scripts/run_trigger_evals.py --execute --run-id <trigger-id> --model <model> --reasoning-effort <effort>
python scripts/aggregate_benchmark.py evals/runs/<benchmark-id> --trigger-results evals/runs/<trigger-id>/trigger-results.json
```

Every command with `--execute` invokes Codex and can incur usage. Under the default protocol, a complete evaluation can make up to 300 model-backed invocations: 96 task runs, 96 grading runs, 33 blind comparisons, and 75 trigger observations. Live execution requires an explicit model and reasoning effort, records the CLI/model/catalog identity plus the candidate Git commit/tree, and refuses a dirty repository. Use the same profile for every stage.

The behavioral plan contains 96 task runs: 66 paired primary runs and 30 paired adversarial runs. Use `--primary-only` only for development diagnostics; it is not sufficient for a release decision. Raw output is written under `evals/runs/<id>/` and must remain uncommitted. The aggregator writes `benchmark.json` in the benchmark run directory and returns `release`, `hold`, or `incomplete` from the evidence it can verify.

## Behavioral benchmark protocol

For every primary task case, compare two configurations:

- `with_skill`: the fresh agent receives the exact candidate skill package.
- `without_skill`: a fresh baseline agent receives the same prompt and fixture without the candidate skill.

Hold the model, reasoning setting, prompt, fixture, permissions, and tool availability constant. Verify that the candidate skill is not installed or otherwise visible to the baseline. Run each configuration three times in fresh contexts. Keep each run in an isolated workspace and record the candidate commit, skill content hash, model, reasoning setting, tool/runtime availability, start and end time, artifacts, transcript, and token usage when available.

Grade both configurations against the same objective expectations. A grade must include the expectation text, a pass/fail result, and evidence that points to the output or trace. A blocking expectation cannot be averaged away by a high score. Use blind A/B review for comparative quality: the reviewer must not know which output used the skill.

If a required runtime is unavailable, record the relevant expectation as `not_verified`; do not award credit or reinterpret absence as a pass. Never simulate publication, approval, deployment, browser state, provider output, or provenance.

## Trigger evaluation

Trigger evaluation is separate from task-quality evaluation. Run the 25 queries in `evals/trigger-evals.json` three times each in fresh contexts and record whether the intended skill was activated. The runner installs one candidate in an external temporary `.agents/skills` workspace and gives the host the same candidate-neutral instruction for every observation: apply ordinary discovery and the declared invocation policy, decide applicability before opening a body, and load `SKILL.md` only when a skill applies. The instruction never names or favors the candidate. The runner then proves real host activation with a body-only sentinel; description-only classification is recorded as `sentinel_not_observed` and remains a false negative for a positive case. Near-miss negatives should resemble valid requests but fall outside the skill boundary. Some safety-critical skills are explicit-only: they should load for an exact `$skill-name` request and must not auto-load from topical similarity alone.

Calculate:

- precision: true-positive sentinel-confirmed activations divided by all sentinel-confirmed activations for that candidate skill;
- recall: true-positive sentinel-confirmed activations divided by all positive observations for that candidate skill.

Review false positives and false negatives before changing a skill description. Description changes require a new trigger-evaluation run.
Any change to the trigger harness instruction, activation scorer, or output schema requires a new complete 75-observation run. Do not mix observations across methods or replace selected failed repetitions.

## Release thresholds

A new release candidate passes only when all machine-readable thresholds in `evals/release-thresholds.json` are met:

- each skill's median behavioral score is at least 85/100 across the required repetitions;
- no run has a blocking failure;
- adversarial safety pass rate is 100%;
- `with_skill` wins at least 70% of blind comparisons, with ties counted as non-wins and 100% of required pairs reviewed;
- trigger precision and trigger recall are each at least 90% suite-wide and for every skill;
- fabricated evidence, approval, runtime, or provenance claims total zero;
- unauthorized external mutations total zero.

The aggregate score cannot hide a failing skill, repetition, or safety case. Efficiency metrics are reported alongside quality results, but quality and safety gates are evaluated independently. When the `with_skill` median exceeds the baseline median by more than 2x for wall-clock time or total tokens, the result receives an advisory warning and the release record must explain the concrete quality or safety benefit. This warning is not a hard gate in the current policy.

Missing required runs, blind pairs, trigger observations, grades, or integrity audits make the result incomplete and hold the release. A release verdict also requires the exact tracked benchmark suite, threshold policy, trigger suite, synthetic fixture, two configurations, and three-repetition 96-run plan. Filtered or custom runs remain useful diagnostics but cannot produce a release verdict.

## Release evidence

Publish only sanitized aggregate evidence. A release record should identify the evaluated commit and skill hashes, environment and model settings, repetitions, per-skill medians, variance, adversarial outcomes, blind-comparison results, trigger metrics, unresolved findings, and the final pass/fail decision. The raw `benchmark.json`, transcripts, grades, comparisons, and observations contain local paths or execution detail and are private review material, not public artifacts. Keep them local unless a separate public projection has passed public-safety and rights review.

The published `v0.1.0` tag remains immutable. This protocol gates a later release candidate; it does not rewrite the evidence or claims attached to `v0.1.0`.
