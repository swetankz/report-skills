# Visual QA report

## Artifact identity

- Artifact ID: `synthetic-candidate-001`
- Version: `0.1`
- Hash: `sha256:synthetic-value`
- Formats observed: none
- Viewports observed: none
- Verdict: `not-verified`

## Pass coverage

| pass | inspected scope | evidence type/reference | result | finding IDs |
|---|---|---|---|---|
| structural | not inspected | none | not verified | none |
| optical | not inspected | none | not verified | none |
| reader-comprehension | not inspected | none | not verified | none |

Update each result from inspected evidence. An unobserved pass stays `not verified`; `no findings` requires an actual inspection.

## Structural pass

Record alignment, spacing, overflow, component consistency, route integrity, and responsive structure.

## Optical pass

Record typography, density, hierarchy, chart clarity, contrast, balance, and optical alignment.

## Reader-comprehension pass

Record comprehension, pacing, cognitive load, navigation, interaction, and responsive reading behavior.

## Findings

Populate one row per actual finding; leave this table empty until evidence supports a finding.

| ID | pass | severity | artifact/location | viewport or format | evidence and evidence type | impact | recommended correction | owner | disposition | verification status |
|---|---|---|---|---|---|---|---|---|---|---|

Use severity `critical`, `high`, `medium`, or `low` for findings. Repeat severity, evidence, recommended correction, and verification status in each finding-linked revision-log entry. Also record structural, optical, and reader-comprehension pass coverage in `revision-log.md`; an evidence-backed no-change record has `finding_id: none`, `severity: not-applicable`, and `disposition: no-change`. Uninspected coverage remains `not verified`, not an assertion of no defects.

