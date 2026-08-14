# Changelog

All notable repository-level changes are documented here.

## 0.2.0 — 2026-08-14

- Resolve and profile exactly one native Codex implementation, reproduce the package wrapper's managed environment, and bind every model-backed call to kill-on-timeout process-tree handling plus canonical stage-specific timeout and termination receipts. Failed calls stop their stage and cannot be graded, compared, resumed, or salvaged from terminal-looking output.

- Add reproducible paired behavioral, blind-comparison, adversarial, and activation evaluation contracts for all eleven skills.
- Bind live evaluation evidence to a clean commit and tree, tracked skill and fixture hashes, canonical contract hashes, and one explicit model, reasoning, CLI, and runtime profile.
- Bind every task contract and persisted task artifact set before downstream review; use immutable grader-attempt receipts, input/output hashes, source-bound blind bundles, one deterministic blind seed, and independent aggregate-time grade/comparison revalidation so partial or altered evidence cannot be retried or change a release gate.
- Parse every produced CSV artifact before grading and reject rows whose field count does not match the header, so visually reconstructable but structurally corrupted registers cannot satisfy a release gate.
- Add release thresholds, schemas, runners, aggregation, focused tests, CI contract checks, and public methodology documentation while keeping raw transcripts local and untracked.
- Validate every model-facing object schema against the strict structured-output requirement before live evaluation.
- Allow task agents to create local benchmark artifacts through automatic approval review constrained to the isolated `workspace-write` sandbox.
- Add a defense-in-depth check that rejects named `SKILL.md` path references outside the injected candidate when they are visible in top-level command events, and record path-free local loader diagnostics.
- Require metadata-policy-checked, body-proven skill activation and clarify adjacent skill boundaries found through repeated fresh-context trigger tests.
- Store observations and blind-comparison bundles under compact physical directories while retaining canonical logical identities, and fail before model calls if a copied fixture or injected-skill input would exceed the safe Windows path budget.
- Build both public archives from a clean-HEAD, regular-Git-blob allowlist; reject tracked raw evaluation trees and non-regular entries while excluding ignored or untracked local material.
- Preserve tracked fixture and skill hashing in the history-free source snapshot through its verified file manifest, so extracted validation does not depend on a `.git` directory.

## 0.1.0 — 2026-08-13

- Establish one plugin containing an explicit `report-skills` orchestrator and ten standalone specialists.
- Add canonical-source generation for self-contained skill packages.
- Add shared artifact, approval, evidence-language, safety, and validation contracts.
- Add synthetic examples, deterministic validation, and public-safety checks.
- Add fresh-context base-case and adversarial evaluation definitions for all eleven skills.
- Add durable router checkpoints, operational-versus-scenario timestamp rules, rights-register resolution, and consistent runtime `not-verified` semantics from forward-test findings.
- Keep external publication behind an explicit human approval gate.
