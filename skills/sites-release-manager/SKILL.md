---
name: sites-release-manager
description: "Prepare, compare, package, and, only with exact explicit authorization, deploy a validated artifact through Sites while preserving access controls and verifying routes. Use for Sites-specific dry runs, stale-source detection, release preparation, or explicitly approved deployment of a known revision; do not use for generic hosting or inferred publication."
---

# Sites Release Manager

Treat every invocation as a dry run until an explicit publication approval matches the exact source, revision, target project, access intent, and external action. Never combine release preparation with silent content or code fixes.

## Load the operating rules

Read these bundled files before any release work:

- [Sites release protocol](references/sites-release-protocol.md) for source resolution, dry-run checks, deployment gates, and release records.
- [Artifact contracts](references/artifact-contracts.md) for the Sites release record and shared artifact envelope.
- [Approval and stop gates](references/approval-and-stop-gates.md) before interpreting any approval.
- [Public safety](references/public-safety.md) before handling project identifiers, routes, URLs, access settings, or logs.
- [Validation conventions](references/validation-conventions.md) before reporting a release state.

## Select the operating mode

Use one of two modes:

- **Dry run:** Inspect, resolve, build, compare, package, and verify the local or staged candidate without external mutation. Use this mode by default.
- **Authorized deployment:** Deploy only when the user explicitly authorizes Sites publication for the exact release packet in scope and an authenticated Sites capability is available.

Explicit invocation of this skill does not itself authorize deployment.

## Resolve the canonical source

1. Enumerate plausible candidates without changing them.
2. Record the selected source path or repository identity, exact ref, timestamp, hash or commit, status, and owner.
3. Compare the selected source with the version that received build and QA approval.
4. Detect uncommitted changes, stale checkouts, mismatched artifacts, newer competing candidates, and conflicting summaries.
5. Stop when canonical identity cannot be proved. Do not select a familiar or newest-looking folder by inference.

## Build and verify the candidate

1. Use the declared build command for the selected revision.
2. Record the build artifact, build hash, toolchain identity, exit status, and current QA evidence.
3. Verify expected routes locally or in an already authorized staging environment.
4. Check that the artifact preserves approved content, citations, accessibility behavior, metadata, and access-control intent.
5. Distinguish successful packaging from successful external release.
6. Return `blocked` when the build, required route, source match, QA evidence, or rights check fails.

## Prepare the approval packet

Present the exact canonical source, ref, build hash, target Sites project, intended access level, expected routes, rollback reference, and proposed external actions. Keep live target identifiers in private runtime records.

When exact approval is absent, set `release_state: awaiting_approval`, leave `publication_approval: null`, and stop before every external mutation.

## Execute an authorized deployment

Proceed only when all required fields match the approval packet and an authenticated Sites release capability is available.

1. Recheck source identity and build hash immediately before deployment.
2. Recheck target project and access setting without broadening visibility.
3. Deploy only the verified package; do not rebuild from another checkout.
4. Capture the deployment response without exposing credentials or sensitive identifiers.
5. Verify all required routes, artifact identity, access behavior, and visible release version.
6. Record rollback or recovery information supported by the environment.
7. Mark `released` only when external evidence confirms the exact approved artifact is live.

If post-deployment verification fails, report the actual state and follow only a separately authorized recovery action. Never claim success from an accepted deployment request alone.

## Required output

Produce `sites-release-record.yaml` containing the canonical-source receipt, build identity, dry-run checks, approval state, access intent, routes, deployment evidence when applicable, blockers, and rollback note.

Keep this skill experimental when no public Sites integration contract or observable test environment is available. Mark tool-dependent results `not-verified`; do not simulate them.
