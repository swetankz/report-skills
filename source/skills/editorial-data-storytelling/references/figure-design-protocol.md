# Figure design protocol

Use this protocol to choose and validate an evidence-bearing figure.

## Form selection

| Question | Preferred starting form | Main risk to check |
|---|---|---|
| How did a value change over ordered time? | Line chart | Irregular intervals, missing periods, or definition changes |
| How do discrete groups compare? | Bar or dot plot | Truncated baselines, unstable ordering, or incompatible groups |
| How are values distributed? | Histogram, density, box, or strip plot | Hidden sample size, bin sensitivity, or over-smoothed data |
| How do two measures relate? | Scatterplot | Unsupported causal interpretation or hidden confounders |
| How does a coherent total divide? | Stacked bar or simple part-to-whole form | Undefined total, excessive categories, or incompatible parts |
| What occurred in sequence? | Timeline | Treating sequence as causation |
| How do concepts, flows, or systems compare? | Annotated diagram or comparison model | Presenting an analytical construct as measured fact |

Prefer a table when exact lookup matters more than pattern recognition. Prefer prose when the evidence contains only one or two values and a figure adds no comprehension.

## Transformation record

Record:

- Source file, table, query, or endpoint and its version or retrieval state.
- Included and excluded rows, fields, populations, dates, and categories.
- Filters, joins, groupings, aggregations, missing-value treatment, and outlier rules.
- Formula for every rate, index, percentage, change, or normalized value.
- Unit conversion, rounding, displayed precision, and uncertainty method.
- Tool, script, notebook, or query needed to repeat the result.

Keep raw, transformed, and displayed values distinguishable. Never overwrite source data to make it match the presentation.

## Encoding guardrails

- Start bar lengths at zero unless a clearly disclosed analytical reason requires another baseline.
- Show axis units, scale type, interval, and direction.
- Avoid three-dimensional area or volume effects for quantitative comparison.
- Avoid dual axes unless the relationship and both scales are necessary, explicit, and resistant to misreading.
- Preserve zero, negative, missing, and suppressed values as distinct states.
- Display uncertainty, sample size, or coverage when it materially affects interpretation.
- Use consistent definitions and intervals across comparisons.
- Use restrained precision that matches the source and method.
- Do not use area, saturation, or animation to exaggerate small differences.
- Test whether aspect ratio or cropped ranges change the apparent conclusion.

## Editorial annotation

Write:

- A descriptive title that remains true without the surrounding article.
- One takeaway that matches the linked claim and uncertainty.
- A caption that defines the measure, population, geography, period, and important exclusions.
- Annotations for discontinuities, methodology changes, missing data, and meaningful reference points.
- A source note with stable identifiers and a concise transformation statement.

Keep interpretation separate from directly observed values. Label scenarios, forecasts, models, and illustrative diagrams explicitly.

## Accessibility

- Meet the applicable contrast requirement in the delivered medium.
- Pair color with labels, shapes, patterns, position, or direct annotation.
- Keep text legible at the requested output size and zoom state.
- Preserve a logical reading order in interactive and exported formats.
- Provide a data table when the figure or reader context benefits from exact access.
- Write alternative text with the figure type, subject, scale, pattern, exceptions, and essential values.
- Avoid motion as the only way to reveal evidence; support reduced motion when interaction exists.

## Validation gate

Require all of these before `ready-for-approval`:

- Every visible value reproduces from the registered source and transformation.
- Every figure links to at least one registered claim and source.
- Unit, population, geography, period, and denominator are present when applicable.
- Title, takeaway, caption, annotations, and alternative text do not exceed the evidence.
- Encoding and uncertainty checks pass.
- The final requested rendering is observed, or unobserved properties are marked `not-verified`.
- Rights, visibility, and provenance constraints remain attached.

Block the figure when missing data or context could materially change the reader's conclusion.
