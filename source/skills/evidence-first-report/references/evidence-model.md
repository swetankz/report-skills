# Evidence model

Use these rules to register sources, atomic evidence, and claims before drafting.

## Source assessment

Assess fitness for the specific claim rather than assigning credibility from reputation alone.

| Tier | Typical use | Required caution |
|---|---|---|
| 1 | Primary data, official record, direct method, or original study | Inspect method, scope, definitions, and revisions. |
| 2 | Peer-reviewed synthesis or transparent authoritative analysis | Check coverage, recency, and dependence on primary evidence. |
| 3 | Credible secondary reporting or practitioner analysis | Corroborate consequential claims with stronger or independent evidence. |
| 4 | Lead, commentary, promotional claim, or unverifiable summary | Use for context or discovery, not sole support for consequential claims. |

Record access and rights separately from evidence tier. A strong source that cannot be inspected does not become verified merely because its citation looks credible.

## Source register

Use these columns:

```text
source_id,title,author_or_publisher,publication_date,retrieval_date,url_or_identifier,source_type,evidence_tier,cutoff_status,access_status,rights_status,notes
```

Use `in-cutoff`, `post-cutoff-exception`, or `excluded-post-cutoff` for cutoff status. Explain every exception in `notes`.

## Evidence register

Use these columns:

```text
evidence_id,source_id,locator,evidence_kind,observation,method,population,geography,period,unit,denominator,limitations,access_verified,notes
```

Keep `observation` concise and faithful. Use `locator` to let a reviewer reopen the exact support. Record `not stated` when the source omits a material field; do not infer it.
Where a supplied source- or dataset-level period demonstrably applies to row-level, subgroup, aggregate, or derived evidence, carry it into every affected evidence record and separately state any missing finer-grained dates. Never substitute the report window, cutoff, publication date, or retrieval date. If no defensible evidence period exists, treat the quantitative support as incomplete and withhold the quantitative claim from the draft or record it only as an unresolved blocker without asserting the value.

Write every register with a CSV serializer or equivalent standards-compliant escaping. Quote fields containing a comma, double quote, carriage return, or line break, and double embedded quotes. Re-open each written CSV with a parser and require every data row to have exactly the header's column count. Treat any mismatch as a blocking artifact error: do not draft from the malformed register or mark the package ready.

## Claim ledger

Use these columns:

```text
claim_id,claim_text,claim_type,importance,status,source_ids,evidence_ids,location,quantitative,cutoff_status,conflict_status,confidence,review_notes
```

Use these claim types:

- `sourced-fact`: represent directly supported source content.
- `analysis`: derive meaning through an explicit, reproducible comparison or calculation.
- `inference`: state a reasoned interpretation that exceeds direct observation and requires qualification.
- `recommendation`: propose an action based on evidence plus stated values or constraints.

Use `proposed`, `supported`, `qualified`, `contested`, `unsupported`, or `removed` for claim status. Never use confidence as a substitute for evidence.

## Quantitative support

For every reported number, capture:

- The exact source value and locator.
- Unit, denominator, population, geography, and period.
- Transformation or calculation, including rounding.
- Whether uncertainty, sampling error, or confidence bounds apply.
- Whether the comparison uses compatible definitions and timeframes.

Treat a percentage without a defined base as incomplete. Treat a change without a baseline and interval as incomplete. Preserve appropriate significant digits.

Treat every computed or comparative number as a quantitative claim, including totals, rates, ranges, differences, durations, date intervals, and relative-time statements. This rule also applies to quantitative wording introduced during any review or revision. Before the wording enters the draft, register every input under source and evidence identifiers and record the reproducible calculation with an explicit unit, population (use `not applicable` only when genuinely inapplicable), and period. Otherwise omit the number or retain it only as an unresolved blocker without asserting it.

## Conflict handling

Set `conflict_status` to `none`, `resolved`, or `unresolved`. Record all affected source and evidence identifiers. Resolve only through an explainable difference in definition, method, population, period, version, or source fitness. Keep an unresolved conflict visible in the draft and limitations.

## Cutoff handling

Use publication date for cutoff eligibility unless the research design establishes a different explicit rule. Record undated sources as uncertain rather than silently placing them inside the cutoff. Never let later knowledge rewrite an as-of-date conclusion without a disclosed exception.
