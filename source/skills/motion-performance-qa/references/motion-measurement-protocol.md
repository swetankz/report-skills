# Motion Measurement Protocol

Use one trace per exact build, route, viewport, preference state, and controlled interaction.

## Runtime identity

Record:

```text
source_ref,build_hash,route,browser_version,device,viewport,device_scale_factor,os,power_state,reduced_motion,trace_duration
```

Record material extensions, throttling, background load, and automation because they can change measurements.

## Lifecycle events

Capture monotonic timestamps where available for:

- Navigation start and document readiness.
- Critical stylesheet completion.
- Required font readiness.
- Important image or media decode completion.
- Initial-state application.
- Motion initialization.
- Geometry or scroll-trigger refresh.
- Loader dismissal start and completion.
- First meaningful reveal start and completion.
- Late-asset and resize refreshes.
- Initialization failure and fail-safe completion.

Calculate the loader-dismissal-to-first-reveal gap from clearly defined event boundaries. Preserve the raw trace with the summarized result.

## Controlled frame fixture

1. Fix the route, viewport, browser state, build hash, and input pattern.
2. Warm or cold start consistently and record the choice.
3. Capture `requestAnimationFrame` timestamps or equivalent frame intervals for the declared interval.
4. Exclude samples only through a predeclared rule and report exclusions.
5. Repeat enough runs to expose variance; keep each run separate before summarizing across runs.

Accepted input for `scripts/summarize_frame_intervals.py`:

- JSON array of interval values in milliseconds.
- JSON object with `intervals_ms` or `timestamps_ms`.
- CSV with an `interval_ms` or `timestamp_ms` column.

The script uses the nearest-rank 95th percentile and reports threshold counts. Record that method when comparing results.

## Reduced-motion fixture

- Set reduced motion before navigation.
- Verify loader removal, content visibility, focus, navigation, and anchors.
- Verify that nonessential transforms, parallax, and auto-motion are absent or substantially reduced.
- Verify that disabling motion does not disable meaning or interaction.

## Evidence hierarchy

- Runtime measurement: supports a scoped performance statement for the recorded environment.
- Direct runtime observation: supports a scoped behavior statement, not numeric performance.
- Trace or console correlation: supports a causal hypothesis until an intervention confirms it.
- Source inspection: supports an implementation finding, not runtime success.
- Screenshot: supports a visual state at one moment, not timing or smoothness.

## Fixture thresholds

For the repository's controlled synthetic fixture only:

- Fail a reveal gap greater than 100 ms after loader dismissal.
- Fail a 95th-percentile frame interval greater than 33.4 ms.

Always report sample count, median, 95th percentile, maximum, threshold exceedances, run count, and environment variance. Do not generalize these fixture limits to every product or device.

## Retest rule

Tie every verdict to the exact build hash. After a material change, rebuild, record the new hash, repeat the same fixture, and inspect adjacent lifecycle and reduced-motion behavior for regression.
