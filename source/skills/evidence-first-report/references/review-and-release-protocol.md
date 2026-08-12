# Review and release protocol

Use this protocol after the claim ledger supports a complete draft.

## Citation discipline

- Cite sourced facts and quantitative claims near the text they support.
- Prefer direct, stable source URLs or identifiers over search-result links.
- Include a precise locator for paginated, time-based, tabular, or long-form sources.
- Attribute secondary reporting accurately; do not imply direct access to an underlying study that was not inspected.
- Keep a short quotation within applicable rights and quotation limits; prefer paraphrase when wording is not analytically necessary.
- Mark inaccessible or unresolved destinations as limitations rather than inventing a working link.
- Keep a bibliography or source register entry consistent with each inline citation.

## Academic-style review

Check:

- Whether the research question, scope, and method align.
- Whether source selection is adequate and source limitations are visible.
- Whether the argument follows from registered claims.
- Whether counterevidence and conflicts receive fair treatment.
- Whether analysis and inference remain distinguishable from sourced fact.
- Whether recommendations follow from evidence plus stated decision criteria.
- Whether limitations constrain the conclusions appropriately.

## Factual review

Reopen evidence and verify:

- Names, dates, terminology, source versions, and attribution.
- Numbers, calculations, units, denominators, populations, periods, and rounding.
- Claim-to-source and claim-to-evidence mappings.
- Quotations and locators.
- Cutoff compliance and approved exceptions.
- Causal, comparative, universal, and superlative wording.
- Citation availability and identifier accuracy.

Mark an item `not-verified` when it could not be observed. Never convert an access failure into a pass.

## Reader review

Check:

- Whether the intended reader can identify the question and why it matters.
- Whether key terms are introduced before use.
- Whether sections have clear claims and transitions.
- Whether context accompanies unfamiliar quantities and comparisons.
- Whether findings, implications, and recommendations are easy to distinguish.
- Whether the executive layer remains faithful to the full analysis.
- Whether limitations are understandable without specialist knowledge.

Keep page composition, typography, optical alignment, and responsive behavior outside this pass.

## Review log fields

Record:

```text
review_id,pass,reviewed_artifact,artifact_version,location,severity,finding,evidence,required_action,status,reviewer,reviewed_at
```

## Revision log fields

Record:

```text
revision_id,review_id,artifact_version,claim_ids,location,change_summary,reason,verification,status,updated_at
```

Preserve rejected review findings with their rationale. Recheck claim mappings and citations after every material change.

`reviewed_at`, `updated_at`, `created_at`, validation time, retrieval time, and observation time are operational provenance. Use the actual execution clock when observable. Do not substitute an evidence cutoff, source publication date, reporting-period date, or `last_fact_checked`. If a synthetic fixture needs an in-world date, add `scenario_as_of` or `synthetic_test_clock` and retain the real operational timestamp separately; otherwise mark the operational time `not-verified`.

## Readiness gate

Set `ready-for-approval` only when:

- Required files exist and carry exact version identity.
- All quantitative and consequential claims satisfy their evidence rules.
- No blocking factual conflict, missing citation, or unresolved placeholder remains.
- All three review passes are complete and their revisions are verified.
- The limitations statement reflects residual uncertainty and access gaps.
- Rights, visibility, and public-safety constraints are preserved.

Return `blocked` with specific missing evidence or authority when these conditions cannot be met. Never infer human approval or publication authorization.
