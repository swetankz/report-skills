# Pencil edit protocol

## Pre-edit receipt

Record at minimum:

```yaml
schema_version: "1.0"
intended_file: "private-runtime-value"
observed_active_file: "private-runtime-value"
observed_at: "ISO-8601"
connectivity_confirmed: false
active_file_confirmed: false
original_hash: null
original_save_state: "unknown"
backup_path: null
backup_hash: null
requested_changes: []
applied_changes: []
validation: []
status: "blocked"
```

Keep exact paths and editor identifiers private. Use clearly synthetic labels in public fixtures.

## Write authorization matrix

| Connectivity | Target match | Preservation | Edit authority | Action |
|---|---|---|---|---|
| Confirmed | Exact | Verified | Explicit | Apply only the requested edit plan |
| Confirmed | Exact | Verified | Missing or review-only | Inspect and plan; do not write |
| Confirmed | Different | Any | Any | Stop; do not switch or write |
| Confirmed | Ambiguous | Any | Any | Stop and request exact target identity |
| Missing | Any | Any | Any | Stop; perform only offline diagnosis |
| Confirmed | Exact | Failed | Any risky edit | Stop; preserve before writing |

Never weaken these conditions because a change appears small.

## Preservation sequence

1. Observe source save state and version identity.
2. Create a recoverable duplicate, backup, snapshot, or source-control checkpoint.
3. Confirm the preserved artifact exists and can be distinguished from the active target.
4. Record its version or hash.
5. Establish the restoration method before editing.

Do not overwrite an older backup whose retention status is unknown. Do not use a screenshot as the only preservation method for an editable artifact.

## Edit transaction

1. Freeze the target receipt for the planned batch.
2. Resolve exact nodes, components, token groups, or frames.
3. Apply the smallest coherent batch.
4. Re-read affected structure and inspect representative visual output.
5. Record changes and validation evidence.
6. Reconfirm target identity before the next batch.

Pause when the editor reconnects, reloads, opens another file, changes the active target, or returns incomplete state. Re-establish the full receipt before resuming.

## Validation matrix

Verify only the dimensions relevant to the request, and label unobserved dimensions `not-verified`:

- Target identity and saved final version.
- Requested node, component, token, and layout changes.
- Component relationships and reusable structure.
- Constraints, auto layout, spacing, alignment, and overflow.
- Typography, color, image, and content integrity.
- Representative export or render behavior when requested.
- Backup readability and restoration path.

Record pre-edit, post-edit, and comparison evidence. A successful tool response alone does not prove the intended board changed correctly.

## Recovery

Prefer restoring from the preserved artifact or version record. Require explicit authorization before overwriting the edited file with the backup. Preserve both versions when the correct recovery target remains uncertain.
