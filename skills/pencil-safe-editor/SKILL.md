---
name: pencil-safe-editor
description: "Explicit invocation only: activate this skill only when the user's request contains the exact token `$pencil-safe-editor`; topical requests without that token must not activate it. Verify and preserve a specific Pencil design before applying structured edits to it. Use when a user asks to create, recover, or modify components, tokens, frames, or layouts in a `.pen` file and the live editor or supported authoring connection must be checked; stop without writing whenever connectivity, active-target identity, preservation, or edit authorization is ambiguous."
---

# Pencil Safe Editor

Protect the intended Pencil artifact before changing it. Treat file identity, live connectivity, preservation, authorization, and post-edit evidence as mandatory parts of the edit.

## Load the operating rules

Read these bundled files before interacting with a Pencil target:

- [Pencil edit protocol](references/pencil-edit-protocol.md) for the target receipt, preservation sequence, write transaction, and verification matrix.
- [Artifact contracts](references/artifact-contracts.md) for `pencil-edit-record.yaml` and shared handoff fields.
- [Approval and stop gates](references/approval-and-stop-gates.md) before applying or expanding any edit.
- [Public safety](references/public-safety.md) before recording file paths, node identifiers, screenshots, or editor state.
- [Validation conventions](references/validation-conventions.md) before claiming the edit succeeded.

## Classify the request

Distinguish among read-only diagnosis, edit planning, authorized editing, and recovery. Do not turn a critique or troubleshooting request into an edit. Keep recovery non-destructive and preserve all plausible originals until the intended artifact is established.

## Establish the target receipt

1. Record the intended `.pen` identity supplied or confirmed by the user.
2. Query the live editor or supported authoring capability for connectivity and active-target identity.
3. Compare exact resolved identities, not only display names or recent-file labels.
4. Record the observation time, original hash or equivalent version identity, requested changes, and current save state.
5. Stop without writing if connectivity is unavailable, multiple targets are plausible, the active target differs, or identity evidence is indirect.

Never switch to a different board merely because it appears newer or visually similar. Request clarification when exact identity cannot be discovered safely.

## Preserve the original

1. Choose a recoverable preservation method appropriate to the environment: verified duplicate, backup, version snapshot, or source-control state.
2. Preserve the original before the first risky write.
3. Record backup identity, location privately, hash or version, and restoration method.
4. Verify that the preserved state is readable and distinct from the edit target.
5. Stop if preservation fails or would overwrite another artifact.

For a genuinely new file with no prior state, record that fact explicitly and verify the intended creation target before writing.

## Plan and apply structured edits

1. Convert the request into an ordered edit plan covering tokens, components, frames, layout constraints, content, and export implications.
2. Identify exact target nodes or structures before mutation.
3. Use small, inspectable batches and validate after each high-risk change.
4. Preserve reusable components, tokens, constraints, and hierarchy instead of flattening the design.
5. Record applied changes and any deviation from the approved plan.
6. Stop if the active target changes, the connection resets, state becomes ambiguous, or an edit would exceed authorization.

## Verify the result

1. Reconfirm the active file after edits.
2. Record final hash or version identity.
3. Inspect the requested structures and representative rendered regions.
4. Check for missing nodes, detached components, broken constraints, overflow, unexpected style changes, and save failures.
5. Compare the result with the requested change list and record each item as applied, not applied, or not verified.
6. Preserve the backup until the user accepts the edited artifact or a documented retention rule permits removal.

## Required output

Produce `pencil-edit-record.yaml` with connectivity evidence, exact target receipt, original and backup identities, requested and applied changes, validation evidence, final identity, blockers, and status.

Keep runtime file paths, board identifiers, screenshots, and private design content in private records. Use sanitized relative labels only in a public summary. Never present a disconnected, ambiguous, or wrong-target attempt as a successful edit.
