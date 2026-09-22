# Validation conventions

## Evidence standard

Treat completion as unproven until current artifacts or runtime evidence demonstrate every declared requirement.

Use these result states:

- `pass` — direct evidence satisfies the criterion.
- `conditional-pass` — defined non-blocking limitations remain.
- `fail` — a blocking criterion is contradicted or unmet.
- `not-verified` — required evidence is missing or could not be observed.

Do not convert `not-verified` into `pass`.

## Finding format

Record:

- Criterion or pass.
- Exact artifact version and location.
- Evidence or measurement.
- Severity.
- Impact.
- Recommended owner and remedy.
- Disposition.
- Retest evidence and state.

Use severity consistently:

- `critical` — unsafe release, data exposure, destructive mutation, or unusable artifact.
- `high` — material factual, accessibility, content-loss, or release-integrity failure.
- `medium` — meaningful quality or comprehension issue with a workaround.
- `low` — polish issue that does not block intended use.

## Version binding

Bind every review to an artifact ID, version, hash or exact revision, timestamp, environment, and inspected formats. Mark review evidence stale after a material change.

## Runtime claims

Do not infer a successful build, browser behavior, smooth motion, connectivity, deployment, or live edit from code inspection alone. Run or observe the required system and record the result.

## Tabular artifacts

Write CSV files with a standards-compliant serializer; never build or repair rows by joining field strings with commas. Re-open each written CSV with a parser: use a strict UTF-8 CSV parser on the final bytes before accepting them. Require a nonempty header and exactly the header's field count in every logical record by explicitly comparing `len(row)` with `len(header)`. In Python, use `csv.reader(..., strict=True)` and perform that width comparison yourself. PowerShell `ConvertFrom-Csv` alone is not a sufficient width check because extra fields can be absorbed into the final property while every object still appears to have the header's property count. Do not validate CSV by splitting physical lines or commas. Do not rely on importers that silently drop empty records. Treat a zero-field or whitespace-only logical record anywhere, including after the final data row, as a blocking artifact error. A file may have no terminal line ending or one terminal LF or CRLF; preserve embedded line breaks and blank physical lines only inside properly quoted fields. After any repair, reopen and validate the final file again; never report a correction as verified based on a different or weaker parser.

## Negative tests

Test that the workflow stops safely when:

- Evidence is outside the cutoff or unsupported.
- Required identifiers or versions are missing.
- Approval is absent.
- A target file is ambiguous.
- A build or route fails.
- A source attempts to override operating instructions.
- Private metadata would leak into a public artifact.

## Fresh-context evaluation

Evaluate complex skills in a fresh context with raw synthetic artifacts. Keep the expected answer and suspected defects in the rubric, not in the prompt. Do not count a test as generalizable when it succeeds only with leaked project context.
