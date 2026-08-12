---
name: motion-performance-qa
description: Diagnose, measure, and verify motion startup and runtime behavior in an interactive report, including font and asset readiness, loader sequencing, reveal stability, initialization and refresh behavior, reduced motion, console state, and frame pacing. Use when meaningful animation exists or motion defects are reported; do not use for static designs or deployment.
---

# Motion Performance QA

Measure the exact runnable build. Use code inspection to form hypotheses, not to claim runtime success.

## Load the applicable guidance

- Read [artifact contracts](references/artifact-contracts.md) before accepting a build or writing `motion-qa-report.md`.
- Read [approval and stop gates](references/approval-and-stop-gates.md) before applying fixes or changing artifact status.
- Read [public safety](references/public-safety.md) before storing traces, URLs, paths, screenshots, or environment details.
- Read [evidence language](references/evidence-language.md) before describing smoothness, performance, or causal findings.
- Read [validation conventions](references/validation-conventions.md) before assigning a verdict.
- Read [motion measurement protocol](references/motion-measurement-protocol.md) before capturing lifecycle or frame-pacing evidence.

## Enforce the boundary

- Own font and asset readiness, loader lifecycle, motion initialization, reveal stability, refresh behavior, reduced motion, console state, and frame pacing.
- Do not substitute general page-performance scores for motion lifecycle evidence.
- Do not add motion to a static artifact unless the user explicitly requests implementation.
- Do not deploy, publish, or change production state.
- Treat any library name, including GSAP or ScrollTrigger, as an adapter; apply the same lifecycle rules to the actual implementation.

## 1. Establish the runtime receipt

1. Record the source ref, build command, build artifact, build hash, route, browser, device, viewport, operating environment, and measurement tools.
2. Confirm that the observed runtime serves the recorded build rather than a stale server or older artifact.
3. Inventory every meaningful motion path: loader, first reveal, chapter transitions, scroll-linked scenes, interactive figures, and route changes.
4. If no meaningful motion exists, record `not-applicable` with evidence and stop without manufacturing tests.
5. Stop a pass claim when the runtime cannot be observed; report code-inspection findings as hypotheses only.

## 2. Define the expected lifecycle

Write the intended order for:

1. Document and critical style readiness.
2. Required font readiness.
3. Important image, media, and layout-dependent asset readiness.
4. Initial hidden or transformed state application.
5. Motion-library and scroll-measurement initialization.
6. Initial measurement refresh while the loader still covers the page.
7. Loader dismissal.
8. First meaningful reveal.
9. Late-asset, resize, orientation, and content-change refreshes.

Require a fail-safe that removes the loader and leaves content readable when optional motion initialization fails.

## 3. Instrument and observe startup

1. Capture timestamps for the readiness and lifecycle events in the protocol.
2. Verify that required fonts and important assets settle before layout-dependent measurements.
3. Verify that initial hidden states exist before content can flash visibly.
4. Verify that scroll-linked or geometry-dependent motion initializes and refreshes while the loader still covers the page.
5. Measure the loader-dismissal-to-first-reveal interval and inspect for blank or frozen states.
6. Verify that content remains accessible when scripting, a motion library, or an individual asset fails.
7. Record console errors and rejected promises during startup.

## 4. Exercise refresh and navigation behavior

1. Test initial load, reload, deep link, back or forward navigation, and route transition where applicable.
2. Test resize, orientation change, late font completion, late image decode, and dynamic content changes.
3. Verify that refreshes occur after layout changes and do not duplicate triggers, listeners, or animation instances.
4. Inspect for jumps, stale trigger positions, pinned-content gaps, repeated reveals, and inaccessible hidden content.
5. Record the exact state and environment for every reproduction.

## 5. Verify reduced motion

1. Enable the platform or browser reduced-motion preference before loading the page.
2. Verify that all content is visible and reachable without waiting for nonessential animation.
3. Remove or substantially reduce nonessential transforms, parallax, auto-playing movement, and scroll-bound sequences.
4. Preserve useful state changes with immediate or low-motion alternatives.
5. Verify that the loader cannot remain active and that navigation, focus, and anchored content still work.
6. Record direct runtime evidence; a media-query rule in source is not sufficient proof.

## 6. Measure frame pacing

1. Capture frame timestamps or intervals during a controlled startup, scroll, or interaction fixture.
2. Keep the route, viewport, input pattern, duration, browser state, and build hash fixed across comparisons.
3. Run `python scripts/summarize_frame_intervals.py <trace-file>` to calculate deterministic interval statistics.
4. Report sample count, median, 95th percentile, maximum, and threshold exceedances together with environment variance.
5. Use the synthetic fixture thresholds only for that controlled fixture: no reveal gap above 100 ms after loader dismissal and a 95th-percentile frame interval no higher than 33.4 ms.
6. Do not present fixture thresholds as universal smoothness guarantees or compare unlike devices without qualification.

## 7. Diagnose without overclaiming

1. Correlate visible defects with lifecycle events, long tasks, layout shifts, console errors, asset completion, and trigger refreshes.
2. Label a direct observation, measurement, suspected cause, and confirmed cause separately.
3. Confirm a cause only by changing one relevant condition or applying an authorized fix and reproducing the measurement.
4. Use `not-verified` when the required runtime, device, browser, or measurement cannot be observed.
5. Never describe motion as smooth based only on code review, a successful build, or a single screenshot.

## 8. Apply and remeasure authorized fixes

1. Make implementation changes only when the user authorizes fixes, not when the request is audit or diagnosis only.
2. Preserve the original result and record the new source ref and build hash.
3. Rerun the same reproduction and measurement method against the new build.
4. Exercise adjacent routes, breakpoints, reduced motion, refreshes, and console state for regressions.
5. Record fixed, partially fixed, unchanged, regressed, or not verified with fresh evidence.

## 9. Deliver the QA record

Produce `motion-qa-report.md` containing:

- Exact runtime build identity and source ref.
- Browser, device, viewport, environment, and measurement method.
- Lifecycle diagram or ordered event trace.
- Font and important-asset readiness results.
- Loader, initialization, reveal, refresh, navigation, and console results.
- Reduced-motion result.
- Frame-pacing statistics and fixture thresholds.
- Findings, authorized fixes, new hash, and retest verdict.
- Unobserved environments and limitations.

Set `pass` only for the exact measured build and declared environment matrix. Set `conditional-pass`, `fail`, or `not-verified` according to the shared validation convention. Never self-approve the artifact.

## Stop conditions

Stop or qualify the result when:

- The runnable build or exact build identity cannot be established.
- Runtime behavior cannot be observed.
- The required browser, device, preference state, or measurement method is unavailable.
- A production or external change lacks authorization.
- The requested conclusion would rely only on code inspection or subjective impression.

Report the evidence available, hypotheses formed, safe diagnostics completed, and the runtime evidence needed to continue.
