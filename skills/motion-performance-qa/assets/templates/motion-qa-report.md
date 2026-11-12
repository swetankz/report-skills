# Motion QA report

## Runtime identity

- Artifact ID: `synthetic-web-candidate-001`
- Version: `0.1`
- Build hash: `sha256:synthetic-value`
- Verdict: `not-verified`

## Environment

Record browser, device, viewport, runtime, measurement method, and observed timestamp.

## Lifecycle

Record font and asset readiness, loader coverage, motion initialization, reveal, refresh, resize, deep-link, and cleanup behavior.

## Reduced-motion validation

- Route/build: `not-verified`
- Setup: enable `prefers-reduced-motion: reduce` in browser emulation or the OS before a clean reload of the recorded route/build.

| check | procedure | acceptance criterion | result | evidence |
|---|---|---|---|---|
| content visibility | Reload and inspect the complete route. | Required content remains visible and readable. | not verified | none |
| keyboard/focus and navigation | Navigate controls and links with the keyboard. | Focus remains visible and controls and navigation work. | not verified | none |
| loader dismissal | Observe a clean startup. | The loader dismisses and does not trap reading or input. | not verified | none |
| anchored content | Follow each tested anchor. | Its content is visible and unobscured. | not verified | none |
| nonessential movement | Exercise the recorded scroll and interaction sequence. | Nonessential movement is absent or reduced without losing meaning. | not verified | none |

These are proposed checks, not observed results. Record the exact route, build, preference setup and evidence when executing them.

## Measurements

Record reveal gap, frame intervals, long tasks, console state, thresholds, and environment variance.

## Measured verification results

Add one row per runtime-dependent conclusion. Keep unavailable measurements `not verified` and retain the exact environment/build and evidence for each observed result.

| measurement or check | environment/build | evidence reference | acceptance criterion | result |
|---|---|---|---|---|

## Findings and retest

Add only evidence-supported findings. Keep a suspected cause separate from a proposed fix; a proposal does not authorize implementation.

| finding ID | observation | evidence | diagnosis | proposed_correction | verification_status | severity | authorized changes | recheck state |
|---|---|---|---|---|---|---|---|---|

Use `proposed_correction: none` with a reason when no supported correction is available. Record the new build hash before claiming an authorized fix was retested.

