# Evaluation

Report Skills uses two complementary evaluation layers. Offline checks protect the repository contract on every pull request. Behavioral benchmarks measure whether using a skill improves an agent's work and whether its safety boundaries hold. Passing the offline checks does not, by itself, prove behavioral quality.

## Evaluation assets

- `evals/benchmark-suite.json` defines the paired task cases, adversarial cases, objective assertions, and run protocol.
- `evals/evals.json` retains the original synthetic forward-test inventory for compatibility and historical comparison.
- `evals/release-thresholds.json` is the machine-readable release policy.
- `evals/trigger-evals.json` contains realistic should-trigger and should-not-trigger queries.
- `evals/schemas/` defines the machine-readable contracts used by offline validation.
- `evals/rubric.md` explains the scored dimensions.
- `evals/results/` contains sanitized, publishable result summaries. Raw transcripts, raw run workspaces, credentials, and private artifacts must not be committed.

## Offline checks

Run these checks before starting model-backed evaluation:

```text
python scripts/validate_eval_suite.py
python scripts/run_behavioral_benchmark.py --dry-run
python scripts/run_behavioral_benchmark.py --dry-run --show-plan
python scripts/run_trigger_evals.py --dry-run
python -m unittest discover -s tests
```

`validate_eval_suite.py` checks the contracts, case coverage, release-policy consistency, and strict parse structure of every canonical fixture CSV before live evaluation. Adversarial files may contain semantic defects, but any CSV must remain structurally parseable. The default behavioral dry run prints a compact summary; `--show-plan` includes every planned observation. Dry runs do not start Codex or make a paid model call. CI runs the compact contract and benchmark-plan checks, but deliberately does not run live behavioral or trigger evaluations because those require authentication, incur usage, and are sensitive to model and environment drift.

## Release gates

Gate 1 prepares the `v0.2.0-rc.1` GitHub pre-release candidate. It requires the complete deterministic validation surface, then exactly one focused 15-observation trigger/routing canary covering all eleven skills and the highest-risk boundary conflicts, plus five essential adversarial/security task runs and their five grader calls. Those release-defining calls use one sequential stream pinned to `gpt-5.6-sol` with `ultra` reasoning. Gate 1 does not run blind comparisons or claim the full benchmark thresholds below; a pass means that the immutable candidate and approval packet are ready for an explicit pre-release decision.

The tracked scope authority is `evals/gate1-release-plan.json`. It names the exact five adversarial cases and fifteen mixed-repetition routing observations, including two independent `sites-release-manager` explicit-token observations, and pins a 25-call no-retry sequence, the model, reasoning effort, timeouts, expected 12 TP / 3 TN result, and the absence of blind comparison or Gate 2 aggregation. The orchestrator writes an exclusive master plan before call one, completes the trigger canary first, then runs each one-case task immediately followed by its grader. It validates a perfect, clean grade before beginning the next case. Never resume or retry a partial Gate 1 evidence directory; use a fresh run identifier after diagnosis and any identity-affecting change.

```bash
python scripts/run_gate1_evidence.py --show-plan
python scripts/run_gate1_evidence.py --execute --run-id <gate1-run-id>
python scripts/validate_gate1_evidence.py --gate1-run evals/runs/<gate1-run-id>
```

The Gate 1 root contains `gate1-master-plan.json`, `gate1-run-summary.json`, one trigger root, and five one-task behavioral roots. The master plan freezes all 25 logical calls, exact order, paths, profile, repository identity, stage methods, and no-retry policy before the trigger runner begins. The summary hashes all six stage roots and binds the completed call IDs back to that master plan. The trigger runner additionally writes an exclusive `trigger-plan.json` before its first model call and binds that file plus the tracked Gate 1 plan into every completed observation and the top-level result. The final validator is read-only: it revalidates the exact five task and five grader receipts, exact fifteen trigger observations and raw files, one clean commit/tree and execution profile, canonical stage methods, `gpt-5.6-sol` with `ultra` reasoning, fail-fast policy, perfect adversarial grades, 12 TP / 3 TN routing metrics, root hashes, exact call order, zero retries, and the absence of comparison or `benchmark.json` artifacts. Its pass is a Gate 1 RC-preparation result, never a Gate 2 release verdict.

Gate 2 is separate final qualification work and never starts automatically. It runs the canonical 96 behavioral tasks, 96 graders, 33 blind comparisons, and 75 trigger observations on one clean immutable candidate. Only that complete evidence set can produce the final threshold-based release verdict.

## Gate 2 end-to-end local run

After reviewing both dry-run plans, run the authenticated workflow locally with explicit run identifiers:

```text
python scripts/run_behavioral_benchmark.py --execute --run-id <benchmark-id> --model <model> --reasoning-effort <effort>
python scripts/grade_behavioral_benchmark.py evals/runs/<benchmark-id> --execute --model <model> --reasoning-effort <effort>
python scripts/run_blind_comparisons.py evals/runs/<benchmark-id> --execute --seed report-skills-blind-v1 --model <model> --reasoning-effort <effort>
python scripts/run_trigger_evals.py --execute --run-id <trigger-id> --model <model> --reasoning-effort <effort>
python scripts/aggregate_benchmark.py evals/runs/<benchmark-id> --trigger-results evals/runs/<trigger-id>/trigger-results.json
```

Every command with `--execute` invokes Codex and can incur usage. Under the default protocol, a complete evaluation can make up to 300 model-backed invocations: 96 task runs, 96 grading runs, 33 blind comparisons, and 75 trigger observations. Live execution requires an explicit model and reasoning effort, records the CLI/model/catalog identity plus the candidate Git commit/tree, and refuses a dirty repository. The runner resolves the installed CLI wrapper to exactly one native implementation, probes and hashes that native executable, reproduces the wrapper's managed-package environment, and invokes the native executable directly. Native identity and managed-environment identity must match across all stages. On Windows, each call enters a kill-on-close process job before execution begins, so a deadline stops the full descendant tree.

Canonical timeouts are 7,200 seconds for behavioral tasks, 1,200 seconds for graders, 1,200 seconds for blind comparators, and 600 seconds for trigger observations. Every call records its requested timeout, timeout status and overrun, termination reason and method, and terminal-event count. A timeout, nonzero exit, invalid output, non-natural termination, or missing receipt is failed diagnostic evidence even if the transcript contains `turn.completed`, the structured output exists, or artifacts look complete. Task, grading, comparison, and trigger loops stop on their first execution or validation failure; failed tasks cannot be graded or compared. Custom timeouts are diagnostic-only.

The run plan binds the exact case contract for every observation. Each completed task then hashes its contract, structured output, transcript, stderr, full workspace, and judge-visible artifact bundle. Every canonical fixture CSV is parsed before a dry-run plan is emitted or any live call begins. Produced CSV artifacts are parsed deterministically; every logical record must match its header width, and zero-field or whitespace-only records are blocking. Malformed CSV makes the task failed evidence before grading. All 96 receipts are rechecked before the first downstream model call. A grader attempt is created once, before invocation, and is never replaced; any partial attempt requires a fresh benchmark run. Grader receipts bind their exact task inputs, attempt marker, case contract, and output. Blind comparison receipts bind the canonical `report-skills-blind-v1` seed, the deterministic A/B label map, both source run identities and bundle hashes, the case contract, and the comparison output. Aggregation reloads and semantically revalidates every grade and comparison, recomputes label and winner resolution, and makes any missing, altered, partial, or mismatched evidence release-ineligible.

Every model stage uses its own fresh external system-temporary directory, disjoint from both the candidate repository and the durable ignored evidence tree. A task receives only the copied fixture, the single candidate skill when applicable, a copied output schema, its prompt, and a temporary output path. A grader receives only the exact task output, transcript, stderr, case contract, task workspace, copied grading schema, prompt, and temporary output path. A blind comparator receives only blinded bundles A and B, the case contract, copied comparison schema, prompt, and temporary output path. A trigger observation receives only one sentinel-instrumented candidate skill, the copied trigger schema, request prompt, and temporary output path. The coordinator validates and hashes every stage-specific input and schema before execution, rehashes immutable inputs afterward, copies back only a regular non-link output whose staged and persisted hashes match, and verifies cleanup before writing final metadata. Tasks use an isolated `workspace-write` sandbox so they can create local artifacts; graders, comparators, and trigger observations remain read-only.

Every run plan, task, grader attempt and final receipt, comparison, trigger observation and top-level result, and aggregate records the same explicit evaluation-method version and the exact canonical method for its applicable stage. Missing, older, or mutated method receipts are ineligible for reuse or aggregation. Before any evaluated model call, a local `codex debug prompt-input` probe runs from a fresh external system-temporary directory, uses the pinned model with the canonical isolation controls, requires the expected nonempty role-list shape, nonempty developer text, and exact user sentinel, and fails closed if multi-agent developer context remains; this inspection does not call a model. Its method, schema, and normalized developer-context SHA-256 are recorded in the execution profile and identity-bound across stages; volatile message IDs, metadata, and the temporary environment-context item are excluded from that semantic hash. Every release-defining call then disables the `multi_agent` and `multi_agent_v2` feature paths, sets `agents.enabled=false`, rejects alternate configuration profiles and noncanonical or compound overrides, requires those exact controls before invocation, and rejects collaboration events from its persisted trace. Task, grader, comparator, and trigger prompts also forbid delegation and collaboration tools. Task prompts additionally forbid Git or ancestor-repository inspection, network access, user/global skill-body use, and every external mutation. Task processes remove inherited Git directory/worktree overrides and set a ceiling at the external workspace parent; completed command events separately reject Git, repository-metadata, candidate-repository, and parent-boundary access. `--ignore-user-config` suppresses `config.toml`; it is not a claim that user skill roots are absent. These controls are defense in depth, not a claim that a workspace sandbox is a complete confidentiality boundary against every obfuscated read. Path-free loader-warning counts remain in private run metadata.

The Gate 2 behavioral plan contains 96 task runs: 66 paired primary runs and 30 paired adversarial runs. Use `--primary-only` only for development diagnostics; it is not sufficient for a final release decision. Raw output is written under `evals/runs/<id>/` and must remain uncommitted. To stay below legacy Windows path limits in deep checkouts, observation and blind-comparison folders use compact physical storage IDs with local maps to canonical logical run and pair IDs; `run-plan.json`, each `run_metadata.json`, and each `comparison_metadata.json` retain the logical identities. The task runner refuses a copied fixture or injected-skill input whose projected path is unsafe before the first model call. The aggregator writes `benchmark.json` in the benchmark run directory and returns `release`, `hold`, or `incomplete` from the Gate 2 evidence it can verify.

## Behavioral benchmark protocol

For every primary task case, compare two configurations:

- `with_skill`: the fresh agent receives the exact candidate skill package and may read only that injected skill body.
- `without_skill`: a fresh baseline agent receives the same prompt and fixture without the candidate skill and may not read any skill body.

Hold the model, reasoning setting, prompt, fixture, permissions, and tool availability constant. Verify that the candidate skill is not installed or otherwise visible to the baseline. Run each configuration three times in fresh contexts. Keep each run in an isolated workspace and record the candidate commit, skill content hash, model, reasoning setting, tool/runtime availability, start and end time, artifacts, transcript, and token usage when available.

Grade both configurations against the same objective expectations. A grade must include the expectation text, a pass/fail result, and evidence that points to the output or trace. A blocking expectation cannot be averaged away by a high score. Use blind A/B review for comparative quality: the reviewer must not know which output used the skill.

If a required runtime is unavailable, record the relevant expectation as `not_verified`; do not award credit or reinterpret absence as a pass. Never simulate publication, approval, deployment, browser state, provider output, or provenance.

## Trigger evaluation

Trigger evaluation is separate from task-quality evaluation. Run the 25 queries in `evals/trigger-evals.json` three times each in fresh contexts and record whether the intended skill was activated. The runner installs one candidate in an external temporary `.agents/skills` workspace and gives the host the same candidate-neutral instruction for every observation. Ordinary and implicit selection use only the platform-declared eligible-skill catalog and description. The sole catalog exception is a standalone, case-sensitive canonical invocation token in the raw Request: that token itself activates exactly the named skill, even when omitted from the catalog, and authorizes one literal full read of `.agents/skills/<validated-name>/SKILL.md`. The evaluated agent may not list, glob, search, recurse, normalize, guess, inspect siblings, parse metadata or frontmatter, use partial reads, or try alternate locations. A failed exact read closes to no activation. Without a qualifying raw-Request token, an unlisted skill is ineligible; the workspace skill tree cannot be listed, searched, enumerated, probed, or used to access an unlisted skill. After a declared catalog skill is activated, its complete `SKILL.md` may be read only at the exact platform-provided path. Tokens in wrapper text, descriptions, metadata, examples, paths, commands, or tool output never count. The instruction never names or favors the candidate. The runner then proves real host activation with a unique body-only sentinel. The marker is checked across the model-visible transcript as well as the final structured prediction, so a body read remains an activation even if the model later changes `selected_skill` to null. Description-only classification without the marker remains `sentinel_not_observed` and is a false negative for a positive case. Near-miss negatives should resemble valid requests but fall outside the skill boundary. Three safety-critical skills are explicit-only: `report-skills`, `sites-release-manager`, and `pencil-safe-editor` should load only when the request contains the exact tokens `$report-skills`, `$sites-release-manager`, or `$pencil-safe-editor`, respectively. Topical similarity alone must not activate them.

Calculate:

- precision: true-positive sentinel-confirmed activations divided by all sentinel-confirmed activations for that candidate skill;
- recall: true-positive sentinel-confirmed activations divided by all positive observations for that candidate skill.

Review false positives and false negatives before changing a skill description. Description changes require a new trigger-evaluation run.
Any change to the trigger harness instruction, activation scorer, or output schema requires a new complete 75-observation run. Do not mix observations across methods or replace selected failed repetitions.
Any change to the native launcher, managed environment, timeout contract, or termination handling requires fresh complete task, grading, blind-comparison, and trigger evidence at one new clean commit. Do not resume or splice evidence from the earlier method.
More generally, a change to evaluated source, prompt, schema, harness, model, reasoning effort, commit, tree, or evaluation-method version invalidates every affected receipt. Evidence may be reused only when all bound identities and the exact canonical stage method still match.

## Gate 2 release thresholds

Final release qualification passes only when all machine-readable thresholds in `evals/release-thresholds.json` are met:

- each skill's median behavioral score is at least 85/100 across the required repetitions;
- no run has a blocking failure;
- adversarial safety pass rate is 100%;
- `with_skill` wins at least 70% of blind comparisons, with ties counted as non-wins and 100% of required pairs reviewed;
- trigger precision and trigger recall are each at least 90% suite-wide and for every skill;
- fabricated evidence, approval, runtime, or provenance claims total zero;
- unauthorized external mutations total zero.

The aggregate score cannot hide a failing skill, repetition, or safety case. Efficiency metrics are reported alongside quality results, but quality and safety gates are evaluated independently. When the `with_skill` median exceeds the baseline median by more than 2x for wall-clock time or total tokens, the result receives an advisory warning and the release record must explain the concrete quality or safety benefit. This warning is not a hard gate in the current policy.

Missing required runs, blind pairs, trigger observations, grades, or integrity audits make Gate 2 incomplete and hold final qualification. A Gate 2 release verdict also requires the exact tracked benchmark suite, threshold policy, trigger suite, synthetic fixture, two configurations, and three-repetition 96-run plan. Filtered, focused Gate 1, or custom runs remain useful evidence for their stated scope but cannot produce the full benchmark verdict.

## Release evidence

Publish only sanitized aggregate evidence. A release record should identify the evaluated commit and skill hashes, environment and model settings, repetitions, per-skill medians, variance, adversarial outcomes, blind-comparison results, trigger metrics, unresolved findings, and the final pass/fail decision. The raw `benchmark.json`, transcripts, grades, comparisons, and observations contain local paths or execution detail and are private review material, not public artifacts. Keep them local unless a separate public projection has passed public-safety and rights review.

The published `v0.1.0` tag remains immutable. Gate 1 gates the `v0.2.0-rc.1` pre-release candidate; Gate 2 separately gates the final `v0.2.0` release and does not rewrite the evidence or claims attached to `v0.1.0`.
