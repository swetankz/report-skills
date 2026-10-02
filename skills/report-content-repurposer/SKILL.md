---
name: report-content-repurposer
description: "Create source-traceable, draft-only social posts, carousels, launch creatives, and video-frame plans from an explicitly approved report version. Use when adapting validated report content to channel-specific formats while preserving claim context, citations, visual rules, accessibility copy, and derivative provenance; never use it to publish, schedule, or invent evidence."
---

# Report Content Repurposer

Create faithful derivatives from one approved report version. Keep every factual statement traceable, preserve necessary context, and leave every result in draft or export-ready state.

## Load the operating rules

Read these bundled files before producing artifacts:

- [Derivative workflow](references/derivative-workflow.md) for format patterns, mapping rules, and review checks.
- [Artifact contracts](references/artifact-contracts.md) for the derivative manifest and shared handoff envelope.
- [Approval and stop gates](references/approval-and-stop-gates.md) for approval semantics and external-action boundaries.
- [Evidence language](references/evidence-language.md) for separating facts, analysis, inference, and recommendations.
- [Public safety](references/public-safety.md) before exposing source metadata, identifiers, or assets.
- [Validation conventions](references/validation-conventions.md) before declaring a derivative complete.

## Establish the source receipt

1. Identify the exact report artifact, version, and hash or equivalent immutable identity.
2. Verify a human content-approval record for that exact version. Treat `reviewed` or `ready-for-approval` as unapproved.
3. Record the approved claim ledger, citations, limitations, visual-system version, asset rights, and target-channel constraints.
4. Stop if the report version is ambiguous, materially changed after approval, or missing consequential claim support.
5. Mark unavailable nonessential enhancements as limitations; never invent missing evidence or approval.

## Define the derivative plan

1. Capture each requested channel, aspect ratio, duration or card count, copy limit, audience, call to action, and accessibility requirement.
2. Select only claims that remain accurate at the shorter format's level of context.
3. Map every factual or quantitative statement to an approved `claim_id` before drafting.
4. Record omissions that could alter interpretation, including denominators, populations, periods, uncertainty, and limitations.
5. Use visual motifs only when they support narrative meaning and are permitted by the approved visual system.

Before drafting, confirm the approval record matches the supplied report version. A task or fixture may identify an explicitly synthetic approval record; preserve its synthetic scope and do not represent it as real-world approval. If an exact versioned approval record is present and matches the report, create the requested local drafts even though derivative review or publication approval is still pending. Missing publication authorization is not a reason to withhold safe local drafts.

## Create channel-ready drafts

1. Draft copy and creative specifications from the approved claim set.
2. Preserve qualifiers beside the statement they qualify; do not hide them only in a caption or final card.
3. Keep citations or stable source notes visible at the resolution supported by the format.
4. Provide channel-appropriate alternative text, captions, or transcript copy.
5. Record any crop, edit, animation, composite, or export as a derivative transformation.
6. Label all outputs `draft` or `ready-for-approval`; never label them published.

Each deliverable must be independently traceable, not merely covered by package-level metadata. Put these fields in its manifest entry and a compact header or sidecar for the file itself: `deliverable_id`, `parent_report_id`, `parent_report_version`, `parent_report_hash` (or the exact available immutable identity), `source_claim_ids`, `transformation_type`, proposed `dimensions` and aspect ratio, and `status`. Record a claim-to-format/card/frame map plus any context omitted or shortened. Label proposed export dimensions as specifications, not observed exports.

## Validate before handoff

1. Reconcile every factual statement against its approved source claim.
2. Reject unsupported conclusions, causal framing not present upstream, cherry-picked comparisons, and false precision.
3. Check title conventions, sequence, legibility, safe areas, timing, accessibility copy, asset rights, and export dimensions.
4. Confirm that the source report identity and visual-system version appear in `derivative-manifest.yaml`.
5. Set `publication_authorized: false` in the manifest. A separate publication approval does not belong to this skill's output.
6. Return the drafts, manifest, claim mapping, export checklist, limitations, and unresolved approval needs.

## Enforce the publication boundary

Do not post, publish, upload, schedule, email, or call a publishing API. Do not interpret a request to create exports, launch assets, or ready-to-post copy as permission to distribute them. Hand off any requested external action as a separately authorized next step.

## Required output

Produce:

- `derivative-manifest.yaml`
- Channel-specific draft copy and creative artifacts or specifications
- Claim-to-derivative mapping
- Accessibility copy
- Export checklist
- Validation findings and unresolved limitations

When the request is review-only, report findings without changing the supplied artifacts.
