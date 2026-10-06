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

Run the bundled PowerShell validator `scripts/validate_derivative_package.ps1` against the complete local copy-bearing output set, the exact approved source-report file, `source-inventory.json`, and `statement-support.csv` before handoff. Read the source-contract schema in [Derivative workflow](references/derivative-workflow.md): it reconciles every substantive source line and every inventoried source unit with each requested format, including omitted recommendations, measurements and stop rules. The Python counterpart is available when Python is installed. A nonzero exit or unavailable required interpreter is not a pass: repair the exact reported condition or mark validation `not-verified`, then rerun the same complete command. Structural reconciliation does not establish semantic support; complete and record the separate manual clause review before declaring readiness.

## Establish the source receipt

1. Identify the exact report artifact, version, and hash or equivalent immutable identity.
2. Verify a human content-approval record for that exact version. Treat `reviewed` or `ready-for-approval` as unapproved.
3. Record the approved claim ledger, citations, limitations, visual-system version, asset rights, and target-channel constraints.
4. Stop if the report version is ambiguous, materially changed after approval, or missing consequential claim support.
5. Mark unavailable nonessential enhancements as limitations; never invent missing evidence or approval.

## Define the derivative plan

Before adapting copy, quote the complete source into atomic `source_units` in `source-inventory.json`, with exact `line:N` locators and source identifiers. Classify recommendations, safeguards, stop rules and measurements even when they have no claim ID. Inventory every nonblank prose line, including limitations and source notes; a self-selected claim list is insufficient. Manually review clause boundaries, classifications, semantic support and material omissions. Record a used/shortened/omitted disposition for every source unit in every requested format.

Keep one canonical claim-mapping row and `statement_id` for each output unit, including exactly one accessibility string/transcript per visual unit. In the consolidated `statement-support.csv`, add a child record for each atomic clause occurrence within that output, repeating it separately for body and accessibility copy. Each child identifies its parent `statement_id`, literal output fragment, source unit, exact locator and approved IDs. A compound output row carries the union of its children's IDs; the children establish clause-level support. Recommendations may use an exact source unit without a claim ID; factual/analysis clauses need supported IDs. Reserve `source_metadata` for exact inventoried source fields, including the required visible title; separate titles from interpretive subheads. Keep operational version, hash, dimensions and publication state in structured metadata. Do not classify a report-derived fact or interpretation as metadata to bypass evidence requirements.

Make this register the source of truth: assign a unique `statement_id` to each output unit before drafting, add its exact `output_text`, then materialize the final copy from those registered rows. Do not draft on-screen copy, narration, alt text, or source notes separately and backfill the map from memory. Put the `statement_id` marker directly on every output unit: an HTML comment before each Markdown block, a `statement_id` field on each YAML/JSON text item, and a `statement_id` column for each CSV row. Keep one copy-bearing statement per CSV row, with `content_type` distinguishing on-screen text, narration, captions, and accessibility transcript. No untagged copy-bearing block is allowed.

Plan atomic support for each post headline/body/caption, carousel line, and frame headline/on-screen line/narration/caption. Check recommendations separately; do not attach the nearest claim identifier unless it supports the recommendation. A visual description or nonfactual phrase needs its own child classification and rationale rather than a borrowed claim ID. The source inventory and child records supplement the canonical output map; they do not create extra accessibility output rows.

1. Capture each requested channel, aspect ratio, duration or card count, copy limit, audience, call to action, and accessibility requirement.
2. Select only claims that remain accurate at the shorter format's level of context.
3. Map every factual or quantitative statement to an approved `claim_id` before drafting.
4. Record omissions that could alter interpretation, including denominators, populations, periods, uncertainty, and limitations.
5. Plan a claim-by-deliverable coverage row for every approved claim considered in every requested deliverable, including claims that will be shortened or omitted.
6. Use visual motifs only when they support narrative meaning and are permitted by the approved visual system.

Before drafting, confirm the approval record matches the supplied report version. A task or fixture may identify an explicitly synthetic approval record; preserve its synthetic scope and do not represent it as real-world approval. If an exact versioned approval record is present and matches the report, create the requested local drafts even though derivative review or publication approval is still pending. Missing publication authorization is not a reason to withhold safe local drafts.

## Create channel-ready drafts

Do not calculate a new rate, precision, or percentage during repurposing when the approved report already supplies a value; copy the supplied number and qualifiers. Preserve the report's exact approved title, including synthetic/study qualifiers, as visible copy in every requested format; the title in a manifest or alt text alone does not satisfy this. Preserve the source's population and construct wording exactly (for example, do not turn “respondents” into “residents” unless the report explicitly says the sample consists of residents). Before drafting, list every recommendation, safeguard, stop rule, and required support path from the source; for each requested derivative, either retain each material item or add an explicit `omitted` coverage row with the exact source locator, omitted context, and reason. Accessibility strings must reproduce the complete copy text of every linked visual statement verbatim (formatting may differ), then add concise visual description where helpful; do not paraphrase away synthetic qualifiers, population/denominator wording, recommendation steps, or safeguards. Treat each post/card/frame as a visual unit: its accessibility-copy mapping row must identify that unit and list every visible/spoken copy `statement_id` it represents. Video plans must contain exactly one `accessibility_transcript` copy row per frame, mapped as `accessibility_copy` to that frame ID; include all of that frame's visible copy, narration, and captions in its related-ID list. The validator enforces verbatim copy parity and claim-ID carry-through.

1. Draft copy and creative specifications from the approved claim set.
2. Preserve qualifiers beside the statement they qualify; do not hide them only in a caption or final card.
3. Keep citations or stable source notes visible at the resolution supported by the format.
4. Provide channel-appropriate alternative text, captions, or transcript copy.
5. Record any crop, edit, animation, composite, or export as a derivative transformation.
6. Label all outputs `draft` or `ready-for-approval`; never label them published.

Each deliverable must be independently traceable, not merely covered by package-level metadata. Mark each manifest entry with `role: requested-format` for an output format explicitly requested by the user or `role: supporting-artifact` for checklists, validation records, and internal sidecars; do not silently promote supporting files into requested consumer formats. If the source file is available, compute its SHA-256 once, record that exact value as `source_report.hash`, and copy the identical `parent_report_hash` into every Markdown header and every row of each row-oriented output; use `unknown` only when the report file and another immutable identity are genuinely unavailable. Pass the exact source file to the bundled validator so it can compare file bytes with the manifest and all derivative hashes. Put these fields in each manifest entry and in the deliverable itself: `deliverable_id`, `parent_report_id`, `parent_report_version`, `parent_report_hash`, `source_claim_ids`, `transformation_type`, proposed `dimensions` and aspect ratio, and `status`. For Markdown, use a YAML front-matter header with all fields populated. Record one claim-to-deliverable mapping row for every approved claim considered in every requested deliverable, including claims not used. Each row includes exact claim/source identifier or locator, `deliverable_id`, output location, status (`used`, `shortened`, or `omitted`), exact context retained or omitted, and a reason for shortening or omission. Do not map only claims that appear in the copy. Label proposed export dimensions as specifications, not observed exports.

For a CSV or other row-oriented deliverable, include those identity fields as columns on every data row; a manifest entry alone does not satisfy per-file metadata. For a video plan, retain `frame_id`, `duration_seconds`, `visual_source`, `transformation`, and `transition_intent`; use one row per frame-copy unit with a `content_type`, unique `statement_id`, and exact `output_text`. Every frame has exactly one `accessibility_transcript` row, and each frame copy mapping uses its `frame_id` as `visual_unit_id`. Each canonical claim-mapping row includes `source_locator` and the verbatim `output_text` at that exact location.

Preserve supplied quantitative values and qualifiers exactly. Do not independently recalculate, round, or substitute a percentage or rate in derivative copy when the approved report already states it; a new numeric value is an unsupported claim unless explicitly authorized and independently verified.

Repeat the exact `source_claim_ids` in each deliverable's own compact header or sidecar; a complete package manifest does not substitute for per-file traceability. Do not use locally invented claim labels in these headers or mapping rows.

For each visual deliverable, provide the actual proposed alternative-text string in `accessibility_copy` and map it to that deliverable and visual. Include `visual_unit_id` and semicolon-separated `related_statement_ids` in every mapping row: each visual unit's accessibility row must reference every visible/spoken copy ID for that unit, exactly once. Generic guidance such as “add alt text” or “describe the image” is not completed alternative text.

## Validate before handoff

Reconcile canonical output rows with the final files in both directions, then reconcile their child support fragments and every source-unit/format disposition. Include source notes, citations, titles, alt text, captions, on-screen text and transcripts. A validator pass proves structural reconciliation with the declared inventory. Independently reread the source and outputs to verify that units are atomic, classifications and IDs support their exact clauses, and omissions do not change meaning; report that review separately. Do not claim semantic completeness from the validator alone.

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
- Complete source inventory with per-format coverage and atomic statement-support records
- Accessibility copy
- Export checklist
- Validation findings and unresolved limitations

When the request is review-only, report findings without changing the supplied artifacts.
