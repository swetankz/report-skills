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

## Phase III runtime-compatibility update (v57 history)

Method `report-skills-release-evaluation-v57` superseded the v56 preparation
identity above. Codex 0.166.0 renders a typed `additional_tools`
item with developer role but no message content. The model-free preflight must
validate that declaration separately, not discard it or treat it as an empty
text message. The ordered profile receipt now binds complete tool declarations
alongside real developer-message content. Unknown variants, malformed reviewed
envelopes, duplicate tool identities/JSON keys, nonfinite JSON values, duplicated
sentinel material, and known collaboration declarations fail closed. The native
cell waiter is distinguished from agent waiting by its reviewed parameter shape.

This update does not certify opaque or deferred tools as harmless, authorize MCP,
browser or plugin operations, waive the official plugin-validator gap, or change
release thresholds, model settings, task coverage, deadlines or capacity-only
retry limits. Fresh clean-commit anchors and fresh future Gate 2 evidence are
required; model-free diagnostics are not behavioral qualification. The earlier
offline matrix below describes its original preparation revision, not a v57 pass.

## Phase III literal provenance guard repair (v58 history)

The prior offline candidate used `report-skills-release-evaluation-v58` and
`named-skill-path-command-events-v5`. A command-text guard could mistake the
literal `.benchmark_skill/*` pattern in a provenance-role comparison for a second
skill reference, even when the command referenced only the allowed candidate
`SKILL.md`. The repair recognizes a bounded simple-variable PowerShell `-like`
classifier with an exact single-quoted pattern and literal label branch. Only
that data operand is masked for this guard; every other path/command reference
and every independent boundary check remains visible.

Actual wildcard IO, baseline skill access, other-skill reads, chained references,
interpolation, dynamic execution and unsupported lexical/envelope forms do not
gain an exception. This is not a general PowerShell parser. Prompt/tool probe
identities, release thresholds, model/effort/tier, observation coverage,
deadlines and capacity-only retries are unchanged.

Saved traces are used only as unexecuted regression data. Their original receipts
remain immutable and diagnostic: replay is not a model observation, qualification
pass, evidence migration or permission to resume the stopped campaign. A reviewed
clean v58 candidate, fresh private profile evidence and separately approved usage
are required before another live qualification run. No fresh pass is claimed by
this offline repair or the older validation matrix below.

## Current local readiness update (v62)

The active preparation method is `report-skills-release-evaluation-v62`. A fresh
clean-checkout Gate 2 preparation passed the v61 behavioral task matrix, then its
grading phase stopped at attempt 18 when the grader trace guard rejected a pure
PowerShell numeric range endpoint (`[math]::Floor($lines.Length / 2)`) as parent
traversal. Method v62 narrowly recognizes pure, non-nested numeric `math::Floor`
endpoints built from integers and `Count`/`Length` array arithmetic, adjacent to the
range operator; it does not recognize path-bearing, command-bearing, dynamic or
substituted endpoint expressions. The earlier v61 campaign remains failed/incomplete
and cannot provide qualification evidence or be reused.

## Current local readiness update (v61)

Method v61 accepts attribution reports naming a fixture/source/instruction/prompt
and fabrication demand when the clause contains no directly attributed evaluator or
output action (`we`, `I`, `our`, `my`, `package`, or `output` before a
fabrication/approval/compliance action). It corrects the observed v60 false positive
a truthful report about `source-instruction-injection` demanding invented approval.
It is not a general untrusted-source exemption and does not grant publication
authority; affirmative evaluator/output actions remain independently rejected, while
clauses already covered by the existing negation/refusal guard remain permitted.

This is a fresh method identity because any guard change invalidates v60 receipt
reuse. The v60 campaign remains failed/incomplete and is preserved unchanged.

Method v60:

The earlier v59 draft's passing offline suite did not clear independent technical
review. Three blocking findings led to corrections to keyword/CR process-command
detection, exact-case writer row keys and strict statement-support CSV parsing.
Preserve those earlier results and failed review verdicts; only renewed checks
and review bound to corrected bytes can clear local readiness. This preparation
identity grants no new model use, freeze, installation or publication authority.
The named-skill command guard remains `named-skill-path-command-events-v5`.
The host-boundary guard is `task-output-and-host-boundary-safety-v13`: ordinary
`Get-Process` invocation detection also covers command-position `return`, `throw`
and `exit` pipelines and CR/CRLF statement boundaries, while unrelated guards
and the older conservative property-word rule remain intact. Tested inert-data
controls remain allowed; unsupported forms and known property-word false
positives are not presented as complete parsing or confinement.
Both behavioral configurations receive identical PowerShell helper guidance:
descriptive multi-word names, definition and invocation in the same script,
and explicit function-script-block calls such as
`& ${function:Get-LocalArtifactDigest} $path`. Command discovery, alias inspection
or alteration, and command/session-history recovery remain prohibited.

This addresses the alias-resolution mechanism reproduced in synthetic native
controls. It does not establish the original failed process's history provenance,
prove a checker false positive, or guarantee a future model outcome. The stopped
v58 baseline observation and campaign remain failed; their receipts are not
altered or reused. This phase makes no fresh qualification or installed-activation
claim and grants no new evaluated-use or publication authority.

The release-readiness review covers all eleven skills, linked resources,
documentation, CI and release tooling, not just this helper prerequisite.
The integrated local repairs add PowerShell `.ps1` text to public-safety scanning,
validate standalone Python CSV syntax and logical records before projection,
and make both CSV writers compare row count and every parsed value
field-for-field with structured input. Exact ordinal case-sensitive row-key
sets are checked before projection or output writes. Python full-handoff
statement-support CSVs use the same strict reader as mapping and deliverable
CSVs; malformed support records cannot bypass the lexical checks. The
release-verification CLI compares
every archive payload with independent hashes of exact Git blobs, rather than
trusting a self-consistent archive-authored manifest. Names-only helper checks
remain structural-only; history-free extracted-source manifest validation is a
separate check. The PowerShell CSV validator adds field-aware lexical checks and
strict UTF-8 decoding, removes only an optional UTF-8 signature, and parses the
same decoded snapshot that passed validation. Valid quoted embedded line breaks
remain literal data; malformed quoting, bare-CR record endings and invalid
encoding are refused. Canonical and relocated helper tests establish the recorded
synthetic corpus, not universal CSV equivalence.

Local readiness requires combined full-suite and independent-review gates bound
to the same complete source inventory. Keep their exact results and limitations
in a separate candidate-bound receipt; this preparation narrative is not an
acceptance receipt or a final release-readiness pass.

Actual candidate-ZIP installation/activation, reproducible release builds,
clean-candidate profile binding, complete fresh qualification and GitHub
publication verification remain separately evidenced phases. Freeze/commit,
evaluated-use, profile/runtime changes and remote writes retain their explicit
approval gates. No release threshold or existing unavailable-check disposition
is relaxed by local readiness work.

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
| VERIFY-01 | Official plugin validation is **NOT RUN—unavailable in audited tooling**. The maintainer approved this disposition for **v0.2.0 GitHub-only**; it is not a validator pass, and repository/per-skill validation is not a substitute. | Retain this release/channel-scoped disposition and every other gate. Run the official plugin validator when available; do not extend this exception to other releases or distribution channels. | Maintainer-disposed; check remains NOT RUN |

The hard thresholds in `evals/release-thresholds.json` are unchanged. No offline
test resolves the open quality, safety, comparison, or trigger qualification
items. A later source, method, profile, or candidate identity change invalidates
affected evidence under the [evaluation protocol](evaluation.md).

## Offline validation (historical preparation)

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
| Official plugin validator | Unavailable in the historical audit; see the approved scoped VERIFY-01 disposition above |
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
