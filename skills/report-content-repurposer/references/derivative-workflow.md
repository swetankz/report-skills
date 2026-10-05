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

Include every proposed accessibility string (alt text, captions, and transcripts) in the atomic statement inventory. Map each factual clause within it to the exact supporting claim and exact text/field location; a mapping that merely names the visual or `accessibility_copy` package does not count.

Before handoff, split every deliverable into atomic factual clauses and trace each exact output location to the claim that supports it. Include headlines, subheads, card-by-card copy, captions, calls to action that make factual promises, on-screen text, narration, and quantitative labels. A package-level source list or a claim-by-deliverable coverage matrix is not proof that every statement is mapped.

Check recommendations separately from findings. Do not attach a source claim to a recommendation unless that claim actually supports it. Remove unsupported factual clauses; label a genuine recommendation as a recommendation and record its rationale instead of making it appear source-backed.

## Format patterns

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

Before handoff, verify factual statements in each accessibility string individually, not only whether an accessibility field exists.

The claim mapping is a claim-by-deliverable coverage table, not just a list of claims used:

```text
claim_id,deliverable_id,output_location,status,context_retained,context_omitted,reason
```

Create a row for every approved claim considered for every requested deliverable. Use `used`, `shortened`, or `omitted`; explain the retained or omitted context and the reason for every shortened or omitted claim. A claim absent from a draft still needs an explicit `omitted` row. For each visual deliverable, provide the actual alternative-text string with its `deliverable_id` and visual location; instructions to write alt text later do not count.

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
