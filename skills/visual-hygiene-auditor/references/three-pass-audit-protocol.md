# Three-Pass Audit Protocol

Keep the three passes separate so a polished surface cannot hide a structural or comprehension failure.

## Scope record

Declare:

```text
artifact_id,artifact_version,artifact_hash,format,route_or_page,state,viewport,environment,evidence_method
```

List required matrix entries and mark each `observed`, `not-available`, or `out-of-scope`. Never silently drop a required entry.

## Pass 1: structural

- Measure alignment anchors, grids, margins, gaps, padding, and comparable container dimensions.
- Detect document and component overflow, clipping, overlap, occlusion, and unintended scroll regions.
- Compare repeated component variants and responsive state transitions.
- Trace missing or displaced content to the exact page, route, component, and state.

## Pass 2: optical

- Inspect hierarchy, line measure, leading, weight, contrast, density, and whitespace.
- Inspect optical alignment and balance after structural values are correct.
- Inspect chart labels, scales, annotations, captions, source notes, and non-color meaning.
- Inspect image crop, resolution, caption association, and decorative competition.

## Pass 3: reader

- Walk the artifact in intended reading order.
- Test orientation, navigation, pacing, evidence-to-interpretation transitions, and limitation discovery.
- Recheck comprehension after responsive stacking, pagination, or state changes.
- Exercise keyboard, focus, zoom, and control behavior when the medium supports them.
- Label expert judgment as inference unless supported by direct reader evidence.

## Finding record

Use one record per issue:

```yaml
finding_id: "VH-001"
pass: "structural"
location: "route, component, state, viewport"
observation: "directly observed condition"
evidence: "capture or measurement reference"
inference: null
severity: "high"
remedy: "specific corrective action"
owner: "responsible skill or discipline"
disposition: "open"
verification: "not-retested"
```

## Severity

- `critical`: Prevents access to essential content or creates an unsafe release condition.
- `high`: Breaks comprehension, navigation, required responsive behavior, or essential evidence legibility.
- `medium`: Materially degrades clarity or consistency without blocking the core task.
- `low`: Local polish issue with limited reader impact.

Rank impact, not implementation effort or reviewer preference.

## Verdict rules

- `pass`: Observe and pass every blocking item in the declared matrix.
- `conditional-pass`: Leave only documented non-blocking findings.
- `fail`: Leave a blocking defect in an observed required scope.
- `not-verified`: Lack sufficient direct evidence for the requested scope.

Do not use a narrow screenshot, source-code review, or successful build to prove broader responsive or behavioral quality.

## Retest record

Record old and new hashes, the original reproduction conditions, fresh evidence, regression scope, and disposition. A material edit invalidates prior results for affected areas. Reuse unchanged evidence only when the unchanged scope is explicitly demonstrated.
