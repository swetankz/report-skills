# Release preparation: v0.2.0

Prepared on 2026-10-29 from GitHub `main` at
`373ba105e788def469ca3069c6441e3995827161`.

This record covers baseline reconciliation, scope, blocker review, narrow repairs,
and offline validation. It is not a qualification receipt or publication approval.
The published `v0.1.0` and `v0.2.0-rc.1` identities remain unchanged.

## Scope

The candidate retains all eleven skills, the existing three explicit-only
invocation policies, both Codex and ZCode metadata formats, Python 3.11+, and the
plugin/standalone distribution paths. Stable `v0.2.0` remains the target. A further
public RC is optional and requires its own Gate 1 evidence and approval.

Windows, macOS, and Linux installation instructions remain available. Instructions
are not proof of end-to-end installation on every client/platform. The support
matrix in [Installation](installation.md) distinguishes recorded observations
from pending verification. Sites and Pencil features require their corresponding
host integrations; an unavailable integration must be reported as not verified.

This phase does not start live evaluations, capture a qualification profile,
merge a release candidate, create tags, or publish release assets. Existing
historical campaign approvals and budgets do not authorize a fresh campaign.

## Baseline reconciliation

| Earlier work | Disposition | Reason |
| --- | --- | --- |
| Local v22 skill fixes for CSVs, mutation accounting, canonical repairs, and provenance routing | Retain current main implementations | Main already incorporates or supersedes the substantive fixes and includes newer validators and helpers. |
| Local v22 alternate absolute/root-expanded trigger reads | Defer | Conflicts with the current exact workspace-relative trigger read contract; no routing policy change is needed for these offline repairs. |
| v52 reviewer inspection guidance | Carry forward narrowly | Explain restrictions already enforced by the grader/comparator trace validators; preserve static-versus-rendered evidence distinctions. |
| Later fixture filename inventory correction | Carry forward narrowly | Recognize a complete fixture-only metadata listing without permitting content reads, dynamic roots, or compound commands. |
| Windows awake integrations | Defer | Introduces native lifecycle, power-policy, and receipt dependencies requiring a separate runtime decision and native verification. |
| Historical lifetime invocation ledger | Defer | Embeds an old campaign's consumed attempts and budget; inappropriate for a fresh qualification scope. |
| Draft PR #5 packaging fix | Already incorporated on main | Both client manifests and the marketplace descriptor are packaged and independently required by the verifier. Cloud migration is outside this phase. |

The combined changes use evaluation method `report-skills-release-evaluation-v56`
to avoid reusing any earlier method identity. They do not adopt all changes from
the intervening unpublished branches. All earlier raw runs remain diagnostics.

## Blocker register

The historical [v35 full evaluation](../evals/results/gate2-5363af9-v35.md)
completed with a hold verdict. Its failures guide investigation but do not prove
that the current candidate still exhibits the same failures.

| ID | Finding and current action | Acceptance condition | Status |
| --- | --- | --- | --- |
| PREP-01 | Old local checkout diverges from main; candidate starts from the verified main commit and carries only reviewed patches. | One named branch, explicit patch disposition, no replacement of current skills by the older tree. | Addressed in preparation |
| PREP-02 | Provenance, publication, visual QA, motion QA, and Pencil templates lag their skill contracts. Synchronize canonical assets and regenerate packages. | Template data/structure regressions and generated-package checks pass; examples do not claim unobserved work. | Addressed; offline checks passed |
| PREP-03 | Sites mutation-accounting wording conflicts with the router/schema on invoked operations. | Instructions distinguish actual invocations from proposals, refusals, and actions never started; failed or unverified outcomes are recorded honestly. | Addressed; offline checks passed |
| PREP-04 | Review prompts omit enforced inspection boundaries; filename filtering can be mistaken for a skill-body read. | Reviewer contract tests and filename-positive/negative regressions pass without weakening other trace guards. | Addressed; offline checks passed |
| PREP-05 | Changelog/current-method and support wording can imply qualification or platform coverage not established. | Documentation identifies unreleased status, current method, and unverified client/platform flows. | Addressed; offline checks passed |
| QUAL-01 | Historical medians below 85 for provenance, interactive publishing, repurposing, router, Sites release, and visual hygiene. Main has later handoff, evidence, provenance, and derivative-validation changes; this phase repairs stale templates. | Fresh complete Gate 2 evidence gives every skill a median of at least 85 with zero blocking failures. | Open: fresh qualification required |
| QUAL-02 | Historical fabricated-evidence event and 36 blockers. Current traceability, disclosure, schema, and validation guards require fresh behavioral verification. | Zero fabricated evidence/approval/runtime/provenance events, zero unauthorized external mutations, and 100% adversarial safety. | Open: fresh qualification required |
| QUAL-03 | Historical blind win rate was 22/33 (66.7%). | All 33 required comparisons valid; with-skill wins at least 70%, ties counted as non-wins. | Open: fresh qualification required |
| QUAL-04 | Historical motion trigger recall was 66.7%. | All 75 fresh trigger observations complete; precision and recall at least 90% overall and for every skill. | Open: fresh qualification required |
| DIST-01 | Full plugin-ZIP marketplace installation and complete macOS/Linux/client combinations lack recorded release evidence. | Clean-install and representative workflow receipts for claimed support, or accurately limited support claims. | Open: installation phase |
| DIST-02 | Reproducible release artifacts and public release identity are not yet approved. | Double builds, extracted-source validation, exact hashes, final approval, remote asset verification, and tag-pinned installation checks. | Open: packaging/publication phases |
| VERIFY-01 | The official skill validator is available, but the installed Codex CLI has no plugin-validation command and no standalone official plugin validator was found in the installed tooling. | Run the current official plugin validator against this exact repository root once that tool is available; keep its result distinct from repository validation. | Open: validator unavailable |

The hard thresholds in `evals/release-thresholds.json` are unchanged. No offline
test resolves the open quality, safety, comparison, or trigger qualification
items. A later source, method, profile, or candidate identity change invalidates
affected evidence under the [evaluation protocol](evaluation.md).

## Offline validation

The combined candidate was regenerated and independently reviewed. Local checks
use Windows and Python 3.12.13. No model-backed evaluation is part of this matrix.

| Check | Result |
| --- | --- |
| Generate packages, then `scripts/check_generated.py` | Passed: all eleven packages |
| `scripts/validate_repository.py` | Passed: plugin metadata and all eleven skills |
| `scripts/scan_public_content.py` | Passed |
| `scripts/validate_eval_suite.py` | Passed: eleven primary cases, five adversarial cases, 25 trigger cases |
| Behavioral and trigger `--dry-run` plans | Passed: 96 behavioral and 75 trigger observations; zero live calls |
| `scripts/run_gate1_evidence.py --show-plan` | Passed: 25 logical calls planned; zero live calls |
| `scripts/test_standalone_packages.py` | Passed: eleven isolated packages |
| `scripts/validate_graphify_integration.py` | Passed: optional local tooling remains outside release evidence |
| Official Skill Creator `quick_validate.py` | Passed: all eleven skills; PyYAML 6.0.3 used only in ignored validation tooling |
| Full unit suite | Passed locally; three environment-dependent skips |
| Independent source and contract review | Passed after fixing a source-only documentation link that would have broken plugin archive link closure |
| Official plugin validator | Unavailable; VERIFY-01 remains open |
| GitHub `validate` and `windows-process-lifecycle` | Required on the draft PR; use the checks attached to its exact head commit for the current result |

Repository/plugin metadata validation is not represented as a pass of the
unavailable official plugin validator. Local diagnostics are ignored and not
qualification evidence. This preparation record accompanies the source change;
the final GitHub check results must be read on the exact proposed commit.

## Next decision

After offline preparation, review this candidate and the remaining installation
work. Then approve one qualification environment, immutable candidate identity,
runtime/model profile, and usage budget. Full Gate 2 remains 300 logical calls;
the optional Gate 1 remains a separate 25-call stream. Do not resume or splice
prior candidate evidence into either stream.
