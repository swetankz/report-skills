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

Inventory source notes, dates/cutoffs, citations, captions, and metadata as well as main creative copy. Create one mapping row per factual occurrence; repeated text in the body and alt text needs separate rows. Put the exact output location and verbatim `output_text` in each row, with the exact approved claim/source identifier and source locator. Do not group multiple cards, frames, or fields under a generic location. If a factual statement has no valid supporting identifier, remove it or mark it `unmapped`/`not-validated` and block any completeness claim.

Include every proposed accessibility string (alt text, captions, and transcripts) in the atomic statement inventory. Map each factual clause within it to the exact supporting claim and exact text/field location; a mapping that merely names the visual or `accessibility_copy` package does not count.

Before handoff, split every deliverable into atomic factual clauses and trace each exact output location to the claim that supports it. Include headlines, subheads, card-by-card copy, captions, calls to action that make factual promises, on-screen text, narration, and quantitative labels. A package-level source list or a claim-by-deliverable coverage matrix is not proof that every statement is mapped.

Check recommendations separately from findings. Do not attach a source claim to a recommendation unless that claim actually supports it. Remove unsupported factual clauses; label a genuine recommendation as a recommendation and record its rationale instead of making it appear source-backed.

## Format patterns

Do not calculate or substitute a new percentage or rate when the approved report already states the figure; preserve the supplied number and qualifiers. Accessibility text and transcripts must retain material qualifiers, limitations, denominators, and safeguards from the corresponding visual/narration rather than compressing them away.

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

Every deliverable file must carry its own parent identity, source claim IDs, transformation type, proposed dimensions/aspect ratio, and status. Put these fields on every data row of a CSV or other row-oriented file; a package manifest entry is not per-file metadata. If the format makes repeated columns invalid, use a same-stem sidecar and link the relative sidecar path from the deliverable.

The statement-level mapping schema adds `source_locator` and verbatim `output_text` to the fields below. Include one distinct row per factual occurrence at its exact location; do not bundle several outputs or accessibility strings into one row.

Use unique `statement_id` markers on every copy unit: `<!-- statement_id: ST-001 -->` before each Markdown block, a `statement_id` field for every YAML/JSON text item, and a `statement_id` column for each CSV copy row. Markdown files also need a populated YAML front-matter header containing all per-file provenance fields. A CSV video plan uses one row per frame-copy unit (for example, `on_screen_copy`, `narration`, or `accessibility_transcript`) with frame ID, duration, content type, exact text, visual source, transformation, transition intent, and provenance columns repeated on each row. Every factual copy row needs a nonempty exact claim/source ID and source locator; if none exists, omit the factual text or block completion. Provenance values such as report version, cutoff, draft/publication status, dimensions, and parent hash belong in structured metadata, not consumer-facing copy; never attach unrelated claim IDs to metadata. If the actual copy states a source fact about scope or cutoff, map that sentence to its exact source ID and locator. The statement register is drafted first and is the source from which those copy units are materialized.

Treat each post/card/frame as a visual unit. Add `visual_unit_id` and semicolon-separated `related_statement_ids` columns to the mapping. Every visual copy row uses its visual's unit ID; one `accessibility_copy` row for that unit lists every visible/spoken statement ID exactly once. In video CSVs, the unit ID is the exact `frame_id`, and every frame must have exactly one `accessibility_transcript` row. That row is mapped as `accessibility_copy` and lists all visible copy, narration, and captions for its frame. Check the transcript's meaning against each linked statement: identifier coverage alone cannot establish that an alt description retained a recommendation, qualifier, or safeguard.

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

From the workspace root, run the validator over every copy-bearing deliverable and its map, for example:

```text
pwsh -NoProfile -File .benchmark_skill/report-content-repurposer/scripts/validate_derivative_package.ps1 -ArtifactsRoot artifacts -Mapping artifacts/claim-mapping.csv -Deliverables "launch-post.md,carousel.md,video-frames.csv,derivative-manifest.yaml"
```

Adjust the deliverable list to include every file containing output copy. A nonzero exit blocks a `pass`; repair the issue and rerun the same full command.

Before handoff, verify factual statements in each accessibility string individually, not only whether an accessibility field exists.

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
