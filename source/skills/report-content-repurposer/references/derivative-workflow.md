# Derivative workflow

## Source and claim mapping

Build a derivative claim bank before writing. For each candidate statement, record:

- Approved `claim_id` and exact approved wording.
- Claim type: sourced fact, analysis, inference, or recommendation.
- Necessary qualifier, denominator, population, period, and uncertainty.
- Citation or stable source note permitted in the destination format.
- Approved figure or asset and its rights status.
- Intended channel location and shortened wording.

Reject a shortened statement when the missing context changes its meaning. Do not upgrade analysis or inference into fact.

## Statement-level traceability

Give every output unit one canonical mapping row with its exact location and full `output_text`. A unit may contain several clauses. Record their atomic support separately in `statement-support.csv`, using one child row for each clause occurrence; repeated body and accessibility text needs distinct child rows. Do not combine separate cards, frames or fields under one canonical statement ID.

Each visual unit has exactly one canonical `accessibility_copy` row. Its child support rows map every factual clause independently, while the canonical row carries the union of child claim IDs and lists each related visual statement ID exactly once. This preserves a single complete alt string or transcript without sacrificing atomic evidence mapping.

Before handoff, split every deliverable into atomic factual clauses and trace each exact output location to the claim that supports it. Include headlines, subheads, card-by-card copy, captions, calls to action that make factual promises, on-screen text, narration, and quantitative labels. Include the exact approved report title visibly in every requested format. Preserve the source's population wording; do not upgrade “respondents” to “residents” or infer a population attribute. Before drafting, inventory every recommendation, safeguard, stop rule, and required support path; for each deliverable, retain each material item or create a distinct omitted row with its exact source locator, the omitted context, and the reason. A package-level source list or a claim-by-deliverable coverage matrix is not proof that every statement is mapped.

Check recommendations separately from findings. Do not attach a source claim to a recommendation unless that claim actually supports it. Remove unsupported factual clauses; label a genuine recommendation as a recommendation and record its rationale instead of making it appear source-backed.

## Reviewed source contract

Use one consolidated `source-inventory.json` and one `statement-support.csv` for the package. These support records are not consumer formats and do not belong in the validator's `Deliverables` list. Pass their paths separately; both CLIs require them whenever `SourceReport` is supplied and default to those filenames inside `ArtifactsRoot`.

Build the source inventory before adapting the copy. Quote every nonblank source prose line completely across one or more atomic units, including recommendation actions, safeguards, support paths, measurement items, stop rules, analysis and limitations. The validator checks literal line coverage, so omitting a source line or quoting only the first recommendation sentence fails. Markdown headings are structural and excluded from the prose-coverage check; quote any heading reused as copy, including the required report title. Do not misclassify prose as structural content. For other source formats, use an inspectable approved text transcription as the source receipt and record its relationship to the original.

Each source unit contains:

- `source_unit_id`: unique local inventory key, not a new claim/source ID.
- `kind`: `sourced_fact`, `analysis`, `recommendation`, `safeguard`, `stop_rule`, `measurement`, `source_metadata` or `nonfactual`.
- `source_locator`: exact one-based `line:N` in the supplied source file.
- `source_text`: literal nonempty substring occurring exactly once on that line. Split compounds into atomic clauses; include citation syntax in a quoted unit so no substantive line characters disappear.
- `claim_ids`: exact supplied IDs, as a unique JSON array. Facts/analysis require IDs; recommendations, safeguards, measurements and stop rules may have none when their source assigns none. The narrowly bound report-owned metadata fields below have none. Identifier occurrence in the source is checked mechanically; whether an ID supports its clause is manually reviewed.
- `metadata_field`: required on `source_metadata` units, exactly `report_title`, `reporting_period` or `evidence_cutoff`; absent or empty on other kinds. This label cannot establish that arbitrary prose is administrative metadata.

### Report-owned literal metadata boundary

The only consumer-copy metadata exception is a complete literal field owned by the approved report: its title, reporting period or evidence cutoff. Resolve that field independently from the exact source bytes, not from an inventory-authored registry. Bind its complete unchanged `source_text` and exact `line:N` to the source hash; every report-owned output/support occurrence names the same `metadata_field`, contains the complete literal field, and carries no claim IDs. Do not borrow a nearby evidence ID for a report-owned cutoff or period. A title or date followed by an interpretation needs a separate supported unit; metadata is not evidence for that interpretation.

Exact known-field output cannot evade provenance by using an unlinked `nonfactual` child or an unrelated factual source unit while its metadata coverage says omitted. Every complete literal occurrence needs its own bound metadata child, or an alternative factual/analysis child whose exact cited source-unit quote and output fragment independently contain that same literal field. For example, a common title word inside a genuinely supported longer finding, or an identically worded calendar field in an explicitly cited external study, retains that finding's genuine IDs. Source quote membership is a bounded literal check, not proof that those IDs support the statement; manually review that provenance ambiguity and record the result. Matching preserves spelling/link targets and excludes substrings inside larger words; it does not classify paraphrases or arbitrary prose automatically.

The bundled Markdown/text adapter mechanically recognizes the first level-one Markdown heading as `report_title`. Calendar declarations must begin a source line (or follow another recognized calendar declaration on that line), with the explicit label `reporting period`/`reporting_period` or `evidence cutoff`/`evidence_cutoff`, optionally preceded by `the` or `and the`. Use `:`, `=`, `is`, or `runs from` after the label. Cutoffs accept valid `YYYY-MM-DD` or English `Month D, YYYY` dates. Periods accept two such dates separated by `to`/`through`, or `Month [YYYY] to/through Month YYYY`; a missing first year means the same final year. The field ends at a period/semicolon, the next recognized declaration, or end of line. The complete literal field includes its label, connective and punctuation; output layout may change, but spelling, punctuation, case and link targets must not. Duplicate declarations for a field are ambiguous and block reconciliation. Unsupported dates, labels or narrative do not become metadata; a proposed metadata unit without a recognized unique source binding fails. Use an inspectable approved transcription with explicit source-owned fields or block the adaptation rather than inventing a registry entry.

This adapter is not general semantic fact extraction. A leading recognized calendar label is only a mechanical candidate: manually verify report ownership, classification and meaning. Calendar statements with an immediately attached explicit source citation (before or after terminal punctuation) remain evidence-bearing facts, not IDless fields; retain their genuine supporting IDs. Findings, metrics, percentages, denominators, populations, analytical scope, external study dates and interpretations cannot use the metadata exception. All source prose, including unrecognized or nonfactual text, still requires literal inventory coverage, classifications and semantic review. Other operational metadata (version, parent hash, draft/publication state and dimensions) remain structured provenance, not consumer-facing metadata copy.

The JSON envelope contains `schema_version: "1.0"`, the computed `source_report_hash`, `source_units`, `coverage`, and `review`. Set `review.status: "complete"` and `review.method: "manual-clause-review"` only after actually reviewing all source and output clauses; `review.checks` records `atomic-units`, `source-types`, `semantic-support` and `material-omissions`. These are review records, not human approval or an automatic semantic verdict. A quoted whole paragraph does not substitute for the required atomic review.

Create exactly one `coverage` record for every source-unit/requested-format pair. Record `source_unit_id`, `deliverable_id`, `status`, `statement_ids`, `context_omitted` and `reason`. For `used` or `shortened`, `statement_ids` must list exactly all canonical output occurrences supported by that unit, including accessibility occurrences. For `used`, set `context_omitted: "none"`. For `shortened`, quote the literal omitted source fragment and explain why shortening preserves meaning. For `omitted`, leave `statement_ids` empty, quote the unit's complete `source_text` in `context_omitted`, and give a reason. Do not omit material safeguards merely to fit a channel; preserve them or block that adaptation when removing them changes the recommendation.

For example, a source stop rule intentionally excluded from one short-format draft still needs this coverage record:

```json
{
  "source_unit_id": "SU-STOP",
  "deliverable_id": "launch-post",
  "status": "omitted",
  "statement_ids": [],
  "context_omitted": "Stop the pilot for harmful disparities.",
  "reason": "The draft directs readers to the complete recommendation; omission requires semantic review."
}
```

The atomic support table uses this header:

```text
support_id,statement_id,source_unit_id,output_text,output_occurrence,claim_ids,source_locator,kind,metadata_field,reason
```

Each child has a unique `support_id`, its canonical parent `statement_id`, a literal output fragment and a one-based `output_occurrence` selecting that fragment's occurrence in the normalized parent text. Repeated identical clauses need separate children with distinct occurrences; one child cannot cover them all. Its kind, locator and semicolon-separated IDs must match its inventoried source unit exactly. Add children separately for every occurrence in accessibility copy. Every alphanumeric word in canonical copy must be covered by a child fragment; prose separators may differ. A genuinely nonfactual child may leave `source_unit_id`, IDs and locator empty only with `kind: nonfactual` and a rationale, inside a `nonfactual` or `accessibility_copy` parent. Use separate canonical rows for nonfactual headings instead of hiding them inside factual rows. Metadata values retain exact spelling and link targets in both the child and canonical output.

`source_metadata` children reproduce only the complete independently bound literal field described above. Their `metadata_field` must exactly match the source unit; other child kinds leave it empty. Missing/unknown fields fail, and adding a field name to a factual unit does not convert it into metadata. A title plus an interpretive subhead is two units. Operational version, draft/publication state, dimensions and parent hash belong in structured metadata; do not invent a source field or use a vague locator such as `structured provenance`. A canonical row's claim-ID set must equal the union of its child IDs.

The validator checks inventory hash, source quotes and line coverage, identifier occurrence, per-format dispositions, child-to-output binding, metadata field identity and accessibility relations. It does not parse natural language to prove atomicity, entailment or materiality. Reread the complete source and final outputs, perform that review, and record its findings separately; a structural pass alone cannot establish semantic completeness or readiness.

## Format patterns

Do not calculate or substitute a new percentage or rate when the approved report already states the figure; preserve the supplied number and qualifiers. Accessibility text and transcripts must reproduce the complete linked visible/spoken copy verbatim (formatting may differ), then may add concise visual description. Do not paraphrase away a synthetic qualifier, source population, denominator, recommendation step, or safeguard; the validator checks verbatim parity against every linked visual statement.

### Single 4:5 post

Specify headline, one primary finding, necessary context, source note, call to action, alternative text, dimensions, and safe-area requirements. Prefer one defensible idea over a dense miniature report.

### Carousel

Use a coherent sequence:

1. State the reader promise without clickbait.
2. Establish scope or baseline.
3. Develop the evidence across focused cards.
4. Include material qualification or limitation where it affects interpretation.
5. Synthesize the finding without adding a new conclusion.
6. End with the approved call to action and source route.

Map each factual card to one or more approved claims. Do not use the final card to repair misleading earlier cards.

### Launch creative

Separate the report's documented finding from promotional language. Preserve the approved title convention, report version, release state, destination, and rights-cleared visual system. Describe an unreleased report as forthcoming or available for review, not published.

### Video frames

Record frame identifier, duration, on-screen copy, narration or caption copy, approved claim identifiers, visual source, transformation, transition intent, and accessibility transcript. Treat frames as a production plan unless rendered media is actually produced and inspected.

## Derivative manifest fields

Every requested-format file must carry its own parent identity, source claim IDs, transformation type, proposed dimensions/aspect ratio, and status. Put these fields on every data row of a CSV or other row-oriented file; a package manifest entry is not per-file metadata. If the format makes repeated columns invalid, use a same-stem sidecar and link the relative sidecar path from the deliverable. Every manifest deliverable entry must have a role: `requested-format` only for a consumer format explicitly asked for, `supporting-artifact` for checklists, validation records, and other internal support files. The validator requires the exact approved title and visual accessibility coverage for requested formats, not for support records.

The canonical mapping schema adds `source_locator` and full verbatim `output_text` to the fields below. Child support supplies exact clause locators within a compound output. Classify report-derived facts in source notes as `sourced_fact` or `analysis`, never as `source_metadata`; metadata copy must consist only of literal inventoried fields.

Use unique `statement_id` markers on every copy unit: `<!-- statement_id: ST-001 -->` before each Markdown block, a `statement_id` field for every YAML/JSON text item, and a `statement_id` column for each CSV copy row. Markdown files also need a populated YAML front-matter header containing all per-file provenance fields. A CSV video plan uses one row per frame-copy unit (for example, `on_screen_copy`, `narration`, or `accessibility_transcript`) with frame ID, duration, content type, exact text, visual source, transformation, transition intent, and provenance columns repeated on each row. Every evidence-bearing factual copy row needs a nonempty exact supporting claim/source ID and source locator; if none exists, omit the factual text or block completion. Report-owned literal title/period/cutoff copy instead uses the narrow IDless `source_metadata` binding above. Any finding, analytical scope or external study date remains evidence-bearing, even if it mentions a period or cutoff; its child support identifies the exact supporting source ID and locator. Other provenance values (report version, draft/publication status, dimensions and parent hash) remain structured metadata. Never attach unrelated claim IDs to metadata. Draft the source inventory and canonical statement register first, then materialize copy from those rows.

Treat each post/card/frame as a visual unit. Add `visual_unit_id` and semicolon-separated `related_statement_ids` columns to the mapping. Every visual copy row uses its visual's unit ID; one `accessibility_copy` row for that unit lists every visible/spoken statement ID exactly once, repeats every associated claim ID, and has an exact source locator. Its text reproduces every linked statement verbatim so no qualifier, recommendation, or safeguard can disappear. In video CSVs, the unit ID is the exact `frame_id`, and every frame must have exactly one `accessibility_transcript` row. That row is mapped as `accessibility_copy` and lists all visible copy, narration, and captions for its frame.

Use this front matter in each Markdown derivative and replace every placeholder with the exact available value (use `unknown` only when the source truly does not supply an immutable hash):

```yaml
---
deliverable_id: "launch-post-4x5"
parent_report_id: "synthetic-report"
parent_report_version: "1.0"
parent_report_hash: "unknown"
source_claim_ids: ["SYN-S1", "SYN-S2"]
transformation_type: "concise social launch copy"
dimensions: "1080x1350 specification"
aspect_ratio: "4:5"
status: "draft"
---
```

When the approved source file is present, compute its SHA-256 once and reuse that exact hash in the manifest, every Markdown header, and every row of every CSV deliverable. The validator must receive the source file path so it can compare the source bytes with the manifest and derivative metadata; a manifest hash that disagrees with the file, or an `unknown` derivative hash while the file is available, blocks completion.

From the workspace root, run the validator over every copy-bearing deliverable and its map, for example:

```text
pwsh -NoProfile -File .benchmark_skill/report-content-repurposer/scripts/validate_derivative_package.ps1 -ArtifactsRoot artifacts -Mapping artifacts/claim-mapping.csv -Deliverables "launch-post.md,carousel.md,video-frames.csv,derivative-manifest.yaml" -SourceReport fixture/inputs/complete-report.md -SourceInventory artifacts/source-inventory.json -StatementSupport artifacts/statement-support.csv
```

Adjust the deliverable list to include every file containing output copy. A nonzero exit blocks a `pass`; repair the issue and rerun the same full command.

The manifest's `source_inventory` and `statement_support` fields must name the exact records checked by that command, relative to the artifacts root. Supplying alternate records does not override these package pointers.

Before handoff, verify factual statements in each accessibility string individually, not only whether an accessibility field exists. Each accessibility mapping row must include all claim IDs from its linked visual rows plus an exact source locator, and its text must preserve the linked statements' material qualifiers and recommendation safeguards.

The claim mapping is a claim-by-deliverable coverage table, not just a list of claims used:

```text
statement_id,claim_ids,source_locator,deliverable_id,output_path,output_location,statement_type,output_text,status,context_retained,context_omitted,reason,visual_unit_id,related_statement_ids
```

Create a row for every approved claim considered for every requested deliverable. Use `used`, `shortened`, or `omitted`; explain the retained or omitted context and the reason for every shortened or omitted claim. A claim absent from a draft still needs an explicit `omitted` row. An omitted recommendation/safeguard may use an exact source locator instead of a claim ID when the report does not assign it a claim ID. For each visual deliverable, provide the actual alternative-text string with its `deliverable_id` and visual location; instructions to write alt text later do not count.

Include at minimum:

```yaml
schema_version: "1.0"
status: "working"
source_report:
  artifact_id: "synthetic-report"
  version: "1.0"
  hash: "sha256:synthetic-value"
  content_approval_record: "synthetic-content-approval"
source_inventory: "source-inventory.json"
statement_support: "statement-support.csv"
visual_system_version: "1.0"
requested_channels: []
deliverables: []
claim_mappings: []
transformations: []
accessibility_copy: []
limitations: []
publication_authorized: false
```

Use project-specific values only in private runtime artifacts. Use clearly synthetic values in public examples.

## Review checklist

- Verify all facts and numbers against approved claim text.
- Keep scope, time period, population, units, and uncertainty visible where material.
- Check that comparisons share compatible definitions and baselines.
- Confirm citations remain usable after export.
- Confirm every asset has permission and a recorded transformation.
- Inspect text size, contrast, crop, sequence, safe areas, timing, captions, and alternative text.
- Record the report version and derivative status on every handoff.
- Return `blocked` when a claim, source version, approval, or asset right cannot be established.
- Return `ready-for-approval` only after all required checks pass.
- Keep `publication_authorized` false and perform no external distribution.
