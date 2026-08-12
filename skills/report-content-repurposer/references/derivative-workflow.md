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
