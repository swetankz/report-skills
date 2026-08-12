---
name: report-visual-system
description: Translate an approved long-form report and figure set into an editable, tool-neutral publication system with design tokens, reusable components, page or frame maps, accessibility constraints, and export specifications. Use for report layout systems in Pencil, Penpot, slides, or comparable authoring surfaces; do not use for evidence validation, one-off illustration, or web interaction implementation.
---

# Report Visual System

Create an editable publication system without changing the approved report's meaning, evidence, or completeness.

## Load the applicable guidance

- Read [artifact contracts](references/artifact-contracts.md) before accepting an upstream package or writing `publication-spec.yaml`.
- Read [approval and stop gates](references/approval-and-stop-gates.md) before changing artifact status or acting on an authoring target.
- Read [public safety](references/public-safety.md) before persisting input content, assets, paths, or identifiers.
- Read [evidence language](references/evidence-language.md) before describing validation results.
- Read [validation conventions](references/validation-conventions.md) before claiming a format, export, or editable source is complete.
- Read [publication system protocol](references/publication-system-protocol.md) for the content-coverage, token, component, and export checklists.

## Enforce the boundary

- Own publication structure, visual hierarchy, reusable components, and editable source construction.
- Preserve the approved report, citations, limitations, figures, source notes, and version identity.
- Do not substantively rewrite claims, invent evidence, implement web interactions, deploy, or publish.
- Use a neutral visual direction unless the user supplies an authorized visual identity.
- Treat Pencil, Penpot, slides, and other authoring surfaces as adapters; keep the core specification tool-neutral.
- Apply `pencil-safe-editor` safeguards directly when that skill is unavailable: verify live connectivity and the exact active file before any write, preserve the original, and stop on ambiguity.

## 1. Verify the input receipt

1. Record the report artifact ID, version, hash, approval record, visibility, evidence cutoff, and known limitations.
2. Record every figure artifact ID, version or hash, source relationship, rights state, caption, and alternative text.
3. Resolve referenced source and asset identifiers against every supplied source, asset, or rights register before defaulting a rights field to `unknown`. Carry the supplied rights value and its originating record into the asset and rights manifest; keep evidence-use rights distinct from font, image, export, and redistribution rights.
4. Verify that the approval applies to the exact report version being laid out. Never infer approval from a filename, folder, or prior review.
5. Stop final production when the content is unstable, a required asset is missing, rights are unclear, or the target authoring surface is ambiguous.
6. Permit an explicitly requested exploration only as `working`; label it non-final and do not present it as export-ready.

## 2. Freeze the complete content inventory

1. Inventory front matter, every section and subsection, sidebars, tables, figures, notes, citations, bibliography, limitations, and back matter.
2. Assign stable content IDs and map each one to a planned page, frame, or flow position.
3. Preserve full approved text by default. Do not replace a long-form report with a synopsis or silently omit repeated-looking material.
4. Route any proposed shortening or substantive reordering back for editorial approval and create a new source version before continuing.
5. Record exclusions only when the user explicitly requests them, with the reason and approval scope.

## 3. Define the publication contract

1. Confirm format type, physical or digital dimensions, units, orientation, editability requirement, export targets, and expected reading context.
2. Select the authoring surface from user requirements and available capabilities; do not require a particular vendor.
3. Record accessibility constraints, language and script needs, output color requirements, bleed or safe areas, and production limitations.
4. Write `publication-spec.yaml` with the exact source identities, dimensions, tokens, components, section map, assets, constraints, and export targets.

## 4. Build the visual system

1. Define semantic typography roles, readable line lengths, hierarchy, and fallback behavior.
2. Define color roles with contrast intent; do not use color as the only carrier of meaning.
3. Define spacing, grid, margins, alignment, container, border, and image-treatment tokens.
4. Create reusable components for recurring structures such as chapter openers, evidence callouts, figures, tables, citations, footnotes, recommendations, and limitations.
5. Use auto-layout, constraint, or equivalent responsive authoring primitives where the target surface supports them; avoid brittle coordinate-only repetition.
6. Standardize comparable containers when comparison requires equal visual weight; allow intentional size differences when hierarchy or content meaning requires them.
7. Use signature motifs selectively and only when they reinforce the narrative.
8. Keep charts legible and preserve their registered captions, annotations, units, populations, periods, and provenance.

## 5. Map and author every page or frame

1. Create page or frame templates before composing all sections.
2. Map every content ID and figure ID to a destination; flag unmapped and duplicate placements.
3. Compose for pacing across dense and sparse material without manufacturing unsupported emphasis.
4. Keep citations and source notes reachable from the claims or figures they support.
5. Preserve limitations as first-class report content rather than decorative fine print.
6. Create the editable source only after confirming the intended target and preservation plan.
7. Record the editable source identity and hash after authoring.

## 6. Validate before export

1. Compare the authored content map with the frozen inventory and resolve every omission, unexplained duplicate, and unapproved rewrite.
2. Inspect representative and edge-case pages at the intended output size.
3. Check alignment, spacing, overflow, text clipping, hierarchy, chart clarity, citation legibility, and component consistency.
4. Check accessibility constraints, reading order, alternative-text handoff, and non-color meaning.
5. Produce test exports and inspect the exported artifacts rather than treating authoring-canvas state as proof.
6. Mark unrendered formats or unavailable authoring runtimes `not verified`; do not convert code or structure inspection into a visual pass.
7. Record each observed format, export, environment, and artifact hash.
8. Recommend `visual-hygiene-auditor` for an independent three-pass review; do not silently invoke downstream work outside the user's scope.

## 7. Package the handoff

Produce:

- `publication-spec.yaml`.
- Token definitions and layout rules.
- Component inventory.
- Complete page or frame map.
- Editable authoring source identity and hash.
- Asset and rights manifest.
- Export checklist and observed export evidence.
- Known constraints, blockers, and recommended downstream handoffs.

Set the package to `ready-for-approval` only when the exact source version is approved, all report content is mapped, required assets are cleared, the editable source is identified, and required exports are directly verified. Never set human approval yourself. Any material edit after review creates a new version and invalidates review evidence tied to the prior hash.

## Stop conditions

Stop or return a qualified partial result when:

- The exact report version or approval scope cannot be established.
- The content is not stable enough for the requested final layout.
- A required figure, citation, font, or asset is unavailable or lacks distribution permission.
- The intended authoring target cannot be identified safely.
- Preserving the complete report conflicts with the requested format and no editorial decision resolves the conflict.
- A requested completion claim depends on an unobserved canvas, export, or runtime.

Report the blocker, evidence inspected, safe work completed, and the smallest decision or artifact needed to continue.
