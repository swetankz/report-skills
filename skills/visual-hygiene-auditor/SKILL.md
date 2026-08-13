---
name: visual-hygiene-auditor
description: Audit a visual publication or reachable build through three separately evidenced passes for structure, optical quality, and reader comprehension. Use to review report layouts, websites, slides, or exported pages across declared formats and viewports, produce severity-ranked findings, and recheck authorized fixes; do not use for factual review or deployment. Do not use when the primary task is specialized motion lifecycle or animation-performance diagnosis, such as loader and reveal sequencing, motion initialization, reduced-motion behavior, or frame pacing; route that work to motion-performance-qa.
---

# Visual Hygiene Auditor

Audit the exact artifact through three distinct passes. Treat review as read-only unless the user separately authorizes implementation changes.

## Load the applicable guidance

- Read [artifact contracts](references/artifact-contracts.md) before accepting an artifact or writing `visual-qa-report.md`.
- Read [approval and stop gates](references/approval-and-stop-gates.md) before changing status or applying fixes.
- Read [public safety](references/public-safety.md) before storing screenshots, paths, private copy, or runtime identifiers.
- Read [evidence language](references/evidence-language.md) before assigning a verdict or describing a finding.
- Read [validation conventions](references/validation-conventions.md) before claiming a format, viewport, or behavior has passed.
- Read [three-pass audit protocol](references/three-pass-audit-protocol.md) for pass-specific checks, severity, evidence, and retest rules.

## Enforce the boundary

- Own presentation review across structure, optical clarity, and reader comprehension.
- Keep argument, source, and factual review with the report authoring workflow.
- Route specialized loader, reveal, motion-runtime, and animation-performance measurement to `motion-performance-qa`.
- Do not deploy, publish, or describe a partial review as comprehensive.
- Do not alter the artifact when the user requests review, critique, audit, or diagnosis only.
- Preserve the exact artifact version and hash throughout a review pass.

## 1. Establish the review receipt

1. Record artifact ID, version, hash, format, source ref, status, known limitations, and review timestamp.
2. Declare the required format, page, route, state, browser, device, and viewport matrix.
3. Freeze the target during observation. If it changes, close the prior evidence against its old hash and start a new review record.
4. Confirm the intended audience, reading context, design rules, and acceptance criteria.
5. Classify available evidence: editable source, rendered export, live build, screenshot, measurement, or user report.
6. Narrow the audit explicitly when a required format or runtime cannot be inspected.

## 2. Capture baseline evidence

1. Inspect the actual rendered artifact at every available required format and viewport.
2. Capture page, route, viewport, state, timestamp, environment, and artifact hash with each screenshot or measurement.
3. Use DOM or layout measurements for overflow and geometry when a live web build is available.
4. Use exported pages for print or slide conclusions; do not treat an authoring canvas alone as export proof.
5. Record unavailable evidence as `not verified` instead of guessing from source code or adjacent viewports.

## 3. Run the structural pass

Inspect and record:

- Grid and alignment continuity.
- Spacing rhythm, margins, padding, and section boundaries.
- Container sizing and consistency across comparable elements.
- Text, image, chart, table, and page overflow.
- Component variants, repeated patterns, and state consistency.
- Breakpoint transitions, stacking order, and sticky or fixed obstruction.
- Missing, duplicated, clipped, or displaced content.

Use measurements where geometry determines the finding. Distinguish an observed defect from a suspected implementation cause.

## 4. Run the optical pass

Inspect and record:

- Typography hierarchy, line length, leading, weight, contrast, and density.
- Optical alignment, baseline relationships, whitespace distribution, and visual balance.
- Chart legibility, labels, annotation hierarchy, provenance visibility, and color dependence.
- Image treatment, cropping, resolution, and caption relationship.
- Emphasis, repetition, and decorative motifs relative to narrative importance.
- Citation, footnote, limitation, and metadata legibility.

Do not equate token consistency with optical quality; inspect the rendered result.

## 5. Run the reader-comprehension pass

Inspect and record:

- Entry point, orientation, chapter navigation, and progress cues.
- Reading order, information scent, and transitions between evidence and interpretation.
- Pacing across dense and sparse sections.
- Cognitive load, competing calls for attention, and interruption by decoration or motion.
- Comprehension after columns stack or layouts paginate.
- Ability to locate citations, source context, limitations, and next actions.
- Keyboard, focus, zoom, and responsive behavior when included in scope.

Base comprehension claims on walkthrough evidence, not personal preference alone. Label expert inference as inference when no reader study exists.

## 6. Write actionable findings

For every finding, record:

- Pass: `structural`, `optical`, or `reader`.
- Exact page, route, component, state, and viewport.
- Observation and evidence reference.
- Impact and severity.
- Recommended remedy.
- Owner skill or discipline.
- Disposition and verification state.

Separate direct observation, measurement, inference, and unverified hypothesis. Do not describe a likely cause as proven without causal evidence.

## 7. Set scoped verdicts

1. Assign `pass`, `conditional-pass`, `fail`, or `not-verified` to each observed format and viewport.
2. Set the overall verdict to the most serious unresolved required-scope result.
3. Use `pass` only when every blocking requirement in the declared scope was observed and passed.
4. Use `conditional-pass` only when remaining findings are explicitly non-blocking and documented.
5. Use `not-verified` when evidence is missing or too indirect; absence of a visible defect is not proof.
6. Reserve `comprehensive` for reviews covering the complete required matrix and all three passes.

## 8. Recheck authorized corrections

1. Apply fixes only when the user clearly authorizes implementation within the affected artifact.
2. Record the new artifact version and hash after any correction.
3. Reproduce the original defect against the old evidence, then inspect the new artifact under the same conditions.
4. Recheck adjacent layouts or states for regressions.
5. Record fixed, partially fixed, unchanged, regressed, or not verified with fresh evidence.
6. Never reuse a prior pass verdict for a materially changed artifact.

## 9. Deliver the audit record

Produce `visual-qa-report.md` containing:

- Artifact ID, version, hash, reviewed formats, reviewed viewports, review time, and verdict.
- Scope and unavailable evidence.
- Three separately documented passes.
- Severity-ranked findings with evidence and owners.
- Authorized changes, if any.
- Retest records and remaining limitations.

Recommend the appropriate downstream owner without silently performing deployment, factual review, or unrequested implementation.

## Stop conditions

Stop or qualify the result when:

- The artifact identity or version cannot be fixed for review.
- Required formats, routes, or viewports cannot be inspected.
- Evidence is too partial to support the requested breadth of claim.
- A requested causal or performance conclusion lacks measurement.
- Fix authorization is absent for a review-only request.

Report what was observed, what remains unverified, and the evidence needed to complete the requested scope.
