# Web Publication Checklist

Use this checklist against the exact built candidate, not an older development server or source directory.

## Canonical-source receipt

Record:

```text
artifact_id,version,source_ref,hash,status,owner,timestamp,intended_role,approval_record
```

Treat source selection and build success as separate decisions. Reject a candidate whose build hash cannot be tied to the reviewed source ref.

## Complete-content map

Maintain one row per approved content unit:

```text
content_id,source_location,route,anchor,component,rendered_status,citation_status,notes
```

Require every row to be rendered and traceable. Treat a deliberate exclusion as a content change requiring an explicit record.

## Quantitative-integrity preflight

- Inventory material numbers across report prose, figures, captions, tables, and supplied data.
- Recompute a value when its numerator and denominator are supplied; record the transformation and rounding.
- Compare repeated values only when unit, population, period, denominator, and construct match.
- Block an unsupported or conflicting value from appearing as fact. Request an upstream correction, or show an explicit conflict notice in a blocked local working draft.
- Do not silently repair, average, select, or reinterpret a value outside the approved source.

## Semantic and accessibility checks

- Use `main`, navigation, header, footer, figure, table, and complementary landmarks according to content meaning.
- Keep a coherent heading outline and stable anchor targets.
- Preserve keyboard access, visible focus, logical focus movement, control names, and error feedback.
- Preserve meaningful image and figure alternatives; avoid repeating adjacent captions verbatim when that adds no value.
- Keep source notes, limitations, and citations readable and reachable.
- Verify zoom and reflow expectations in the supported browser matrix.
- Ensure reduced motion reveals all content and cannot leave an overlay active.

## Responsive checks

Declare exact viewport widths and heights before testing. At each viewport, inspect:

- Horizontal overflow at the document and component levels.
- Text clipping, overlap, line length, and minimum useful control size.
- Navigation access, sticky-element obstruction, and anchor offsets.
- Tables, code, charts, captions, citations, and long unbroken strings.
- Reading order and comprehension after columns stack.

Record untested widths as `not-verified`; do not interpolate a pass from neighboring widths.

## Metadata and routing checks

- Verify unique title and description values.
- Verify language, viewport, favicon or icon only when supplied, and canonical intent.
- Verify social metadata only when requested and supplied safely.
- Verify expected routes, direct route loads, fragment links, and invalid-route behavior.
- Verify that robots or indexing settings match the declared release intent without deploying.

## QA artifact hygiene

- Store browser profiles, caches, crash dumps, temporary server state, and driver state in a uniquely scoped temporary directory outside source, build output, and retained evidence.
- Retain only declared evidence such as screenshots, traces, console logs, or DOM captures that is necessary for the verification record.
- Scan the final handoff and fail packaging when browser-state or crash byproducts remain.

## Web candidate shape

```yaml
schema_version: "1.0"
source_report: {}
source_design: {}
source_figures: []
source_ref: "exact-local-ref-or-commit"
build_command: "declared command"
build_artifact: "relative/path"
build_hash: "sha256:synthetic-value"
routes: []
content_map: []
citation_checks: []
viewport_checks: []
accessibility_checks: []
reduced_motion: "implemented-or-not-applicable"
external_deployment_authorized: false
```

## Evidence rules

- Treat source inspection as implementation evidence, not runtime proof.
- Treat a successful build as compilation evidence, not layout or accessibility proof.
- Treat a screenshot as evidence for its exact viewport and moment, not for keyboard, motion, or route behavior.
- Treat direct interaction and measurements as evidence only for the recorded build hash and environment.
- Invalidate the affected checks after a material source or dependency change and retest the new build.
