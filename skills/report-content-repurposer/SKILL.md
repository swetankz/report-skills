---
name: report-content-repurposer
description: "Adapt an approved research or analytical report into channel-specific marketing drafts such as social launch posts, multi-card carousels, short-form video scripts, and frame plans. Use when asked to repurpose a report into multiple formats while preserving exact claims, context, accessibility, and derivative provenance; never publish, schedule, or invent evidence."
---

# Report Content Repurposer

Create faithful derivatives from one approved report version. Keep every factual statement traceable, preserve necessary context, and leave every result in draft or export-ready state.

## Blocking source-identifier integrity gate

- Treat source and claim identifiers as opaque evidence values. Copy each identifier exactly as supplied; never mint, rename, prefix, suffix, or normalize one. For example, do not change `SYN-S1` to `SYN-S1-01` or relabel source IDs `C1`–`C9`.
- If the supplied report has a claim ledger, use only its exact approved claim IDs. If it has no claim ledger but the report itself attaches stable IDs to statements (for example, `SYN-S1`), copy those exact existing IDs into any contract-required `claim_id` or `source_claim_ids` field and identify them as source citations in an adjacent `identifier_type`/notes field when available. They are traceability handles, not newly asserted claim-ledger records.
- Map every factual statement to the exact supplied identifier and a page/section/row locator. Never change `SYN-S1` to `SYN-S1-01`, relabel source IDs `C1`–`C9`, or use `unmapped` when the report already provides a stable citation ID. If neither an approved claim ID nor a supported source ID exists, mark the statement `unmapped`/`not-validated` or omit it; do not claim complete traceability for an unmapped statement.
- Before handoff, verify every identifier in every derivative header, manifest entry, and mapping row appears verbatim in the approved upstream ledger or source. A mismatch is a blocking validation finding, not a cosmetic naming choice.

## Load the operating rules

Read these bundled files before producing artifacts:

- [Derivative workflow](references/derivative-workflow.md) for format patterns, mapping rules, and review checks.
- [Artifact contracts](references/artifact-contracts.md) for the derivative manifest and shared handoff envelope.
- [Approval and stop gates](references/approval-and-stop-gates.md) for approval semantics and external-action boundaries.
- [Evidence language](references/evidence-language.md) for separating facts, analysis, inference, and recommendations.
- [Public safety](references/public-safety.md) before exposing source metadata, identifiers, or assets.
- [Validation conventions](references/validation-conventions.md) before declaring a derivative complete.

Run the bundled `scripts/validate_derivative_package.py` against the complete local copy-bearing output set before handoff. A nonzero exit is a blocking validation failure; repair the exact reported condition and rerun the same complete command. Do not replace it with a narrower check or claim validation passed after any predicate fails.

## Establish the source receipt

1. Identify the exact report artifact, version, and hash or equivalent immutable identity.
2. Verify a human content-approval record for that exact version. Treat `reviewed` or `ready-for-approval` as unapproved.
3. Record the approved claim ledger, citations, limitations, visual-system version, asset rights, and target-channel constraints.
4. Stop if the report version is ambiguous, materially changed after approval, or missing consequential claim support.
5. Mark unavailable nonessential enhancements as limitations; never invent missing evidence or approval.

## Define the derivative plan

Include every proposed accessibility string (including alt text, captions, and transcript text) in the statement inventory. Factual statements embedded in accessibility copy require their own exact claim mapping at the text/field level, not only a deliverable-level or visual-level mapping; a generic row for the `accessibility_copy` package is insufficient.

Build the mapping from an explicit inventory of every factual sentence or clause at every output location, including source notes, date/cutoff statements, captions, and accessibility text. Add one row for each occurrence, even when identical wording appears in the body and alt text. Each row must carry the exact output location, the exact literal `output_text` being mapped, and the exact approved claim/source identifier and source locator. A single row that says “body and accessibility text,” names several cards or frames, or lists claims for an entire deliverable is not statement-level coverage. If a factual statement has no valid supporting identifier, remove it or mark it `unmapped`/`not-validated` and block the completeness claim.

Make this register the source of truth: assign a unique `statement_id` to each output unit before drafting, add its exact `output_text`, then materialize the final copy from those registered rows. Do not draft on-screen copy, narration, alt text, or source notes separately and backfill the map from memory. Put the `statement_id` marker directly on every output unit: an HTML comment before each Markdown block, a `statement_id` field on each YAML/JSON text item, and a `statement_id` column for each CSV row. Keep one copy-bearing statement per CSV row, with `content_type` distinguishing on-screen text, narration, captions, and accessibility transcript. No untagged copy-bearing block is allowed.

Before drafting, split the requested outputs into atomic factual statements and plan a trace for each exact location: post headline/body/caption, every carousel headline and card line, and every frame headline, on-screen line, narration, or caption. A package-level claim list or claim-by-deliverable matrix does not replace statement-level traceability. Check recommendations separately; do not attach the nearest claim identifier unless it actually supports the recommendation. Remove unsupported factual clauses or label a genuine recommendation with its rationale rather than presenting it as a source-backed finding.

1. Capture each requested channel, aspect ratio, duration or card count, copy limit, audience, call to action, and accessibility requirement.
2. Select only claims that remain accurate at the shorter format's level of context.
3. Map every factual or quantitative statement to an approved `claim_id` before drafting.
4. Record omissions that could alter interpretation, including denominators, populations, periods, uncertainty, and limitations.
5. Plan a claim-by-deliverable coverage row for every approved claim considered in every requested deliverable, including claims that will be shortened or omitted.
6. Use visual motifs only when they support narrative meaning and are permitted by the approved visual system.

Before drafting, confirm the approval record matches the supplied report version. A task or fixture may identify an explicitly synthetic approval record; preserve its synthetic scope and do not represent it as real-world approval. If an exact versioned approval record is present and matches the report, create the requested local drafts even though derivative review or publication approval is still pending. Missing publication authorization is not a reason to withhold safe local drafts.

## Create channel-ready drafts

Do not calculate a new rate, precision, or percentage during repurposing when the approved report already supplies a value; copy the supplied number and qualifiers. Accessibility text and transcripts must preserve every material qualifier, limitation, denominator, and safeguard conveyed by the visual or narration, rather than replacing them with a shorter generic summary.

1. Draft copy and creative specifications from the approved claim set.
2. Preserve qualifiers beside the statement they qualify; do not hide them only in a caption or final card.
3. Keep citations or stable source notes visible at the resolution supported by the format.
4. Provide channel-appropriate alternative text, captions, or transcript copy.
5. Record any crop, edit, animation, composite, or export as a derivative transformation.
6. Label all outputs `draft` or `ready-for-approval`; never label them published.

Each deliverable must be independently traceable, not merely covered by package-level metadata. Put these fields in its manifest entry and a compact header or sidecar for the file itself: `deliverable_id`, `parent_report_id`, `parent_report_version`, `parent_report_hash` (or the exact available immutable identity), `source_claim_ids`, `transformation_type`, proposed `dimensions` and aspect ratio, and `status`. Record one claim-to-deliverable mapping row for every approved claim considered in every requested deliverable, including claims not used. Each row includes exact `claim_id`, `deliverable_id`, output location, status (`used`, `shortened`, or `omitted`), exact context retained or omitted, and a reason for shortening or omission. Do not map only claims that appear in the copy. Label proposed export dimensions as specifications, not observed exports.

For a CSV or other row-oriented deliverable, include those identity fields as columns on every data row; a manifest entry alone does not satisfy per-file metadata. Each statement-level claim-mapping row must additionally include `source_locator` and the verbatim `output_text` at that exact location.

Preserve supplied quantitative values and qualifiers exactly. Do not independently recalculate, round, or substitute a percentage or rate in derivative copy when the approved report already states it; a new numeric value is an unsupported claim unless explicitly authorized and independently verified.

Repeat the exact `source_claim_ids` in each deliverable's own compact header or sidecar; a complete package manifest does not substitute for per-file traceability. Do not use locally invented claim labels in these headers or mapping rows.

For each visual deliverable, provide the actual proposed alternative-text string in `accessibility_copy` and map it to that deliverable and visual. Generic guidance such as “add alt text” or “describe the image” is not completed alternative text.

## Validate before handoff

Reconcile the verbatim `output_text` rows against the output inventory in both directions: every copy-bearing occurrence has exactly one statement ID and mapping row, and every mapped text exists at the cited location. Include source notes, dates/cutoffs, citations, metadata, alt text, captions, on-screen text, and transcripts in this check. Do not claim complete traceability when a factual occurrence has no exact row.

During line-by-line validation, check every factual statement in accessibility copy, alt text, captions, and transcripts against its exact approved source claim and output location. A package-level claim list does not establish coverage for these statements.

Read every deliverable line by line and reconcile each factual clause against its exact approved source claim. Check that each headline, card, frame, narration, caption, and quantitative label has matching statement-level traceability; a map that covers the package but misses a sentence or line fails validation.

1. Reconcile every factual statement against its approved source claim and check the claim-by-deliverable map for a row covering every considered claim, including each shortened or omitted claim and its reason.
2. Reject unsupported conclusions, causal framing not present upstream, cherry-picked comparisons, and false precision.
3. Check title conventions, sequence, legibility, safe areas, timing, actual deliverable-specific alternative-text strings, asset rights, and export dimensions.
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
