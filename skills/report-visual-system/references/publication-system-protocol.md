# Publication System Protocol

Use these checklists to produce and verify the editable publication package.

## Input receipt

Record:

- Report artifact ID, version, hash, status, and approval record.
- Figure IDs, hashes, rights state, captions, and alternative text.
- Evidence cutoff, limitations, visibility, and permitted destinations.
- Target format, dimensions, units, authoring surface, and export targets.

Resolve each referenced source or asset ID through any supplied source, asset, or rights register. Preserve the exact rights value and the record that supplied it. Do not say rights metadata was absent when an applicable register contains it. Keep permission to cite or analyze evidence separate from permission to redistribute an image, font, editable file, or export.

Treat a name, modification date, or folder position as identification evidence, not as proof of canonical status.

## Content coverage table

Maintain one row per approved content unit:

```text
content_id,content_type,source_location,destination,source_hash,placement_status,change_status,notes
```

Use `placement_status` values `mapped`, `placed`, `verified`, or `blocked`. Record any wording change as `change_status: approval-required` until the exact revised report version is approved.

## Required token groups

- Typography: families, fallback stack, roles, sizes, line heights, weights, tracking, and measure.
- Color: semantic roles, foreground/background pairs, chart roles, and contrast intent.
- Spacing: base unit, scale, inset, stack, gutter, and section rhythm.
- Layout: grid, margins, columns, alignment anchors, max widths, and safe areas.
- Components: borders, radii, dividers, image treatments, and state variants where relevant.

Keep tokens semantic. Avoid encoding a private brand or one-off page coordinate as a reusable role.

## Minimum component inventory

- Cover and publication metadata.
- Contents or navigation aid.
- Chapter and section openers.
- Body copy, lists, quotations, and callouts.
- Figures, tables, captions, annotations, and source notes.
- Evidence, inference, recommendation, and limitation treatments.
- Citations, footnotes, bibliography, and closing matter.

Add variants only when the content contract requires them.

## Publication specification shape

```yaml
schema_version: "1.0"
source_report:
  artifact_id: "synthetic-report"
  version: "1.0"
  hash: "sha256:synthetic-value"
format:
  type: "pages-or-slides"
  width: 1600
  height: 900
  units: "px"
authoring_surface: "tool-neutral"
tokens:
  typography: {}
  color: {}
  spacing: {}
  layout: {}
components: []
section_map: []
assets: []
accessibility_constraints: []
export_targets: []
```

Replace synthetic values with private runtime values only in the user's private output. Keep public examples fictional and reserved.

## Verification matrix

For each required format, record:

- Exact editable-source and export hashes.
- Renderer or authoring environment.
- Dimensions and page or frame count.
- Content coverage result.
- Text clipping and overflow result.
- Citation, figure, and limitation presence.
- Accessibility and reading-order result.
- Visual evidence location.
- Verdict: `pass`, `conditional-pass`, `fail`, or `not-verified`.

Use `not-verified` when the format was not directly rendered or inspected. A successful file write proves file creation only.
