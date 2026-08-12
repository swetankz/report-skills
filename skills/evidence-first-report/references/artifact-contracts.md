# Artifact contracts

Use versioned, inspectable artifacts at every handoff. Accept equivalent user-provided formats when they contain the required information; do not require exact filenames.

## Common envelope

Record these fields when a structured workflow is useful:

```yaml
schema_version: "1.0"
artifact_id: "stable-identifier"
artifact_type: "evidence-package"
version: "0.1"
status: "working"
source_skill: "evidence-first-report"
created_at: "ISO-8601 timestamp"
input_versions: []
evidence_cutoff: null
visibility: "private"
approvals: []
blockers: []
```

Use the actual execution clock for `created_at`, `updated_at`, review, validation, retrieval, and observation provenance when it is observable. Reporting-period dates, publication dates, the evidence cutoff, and `last_fact_checked` are evidence metadata, not operational timestamps. In a synthetic scenario, keep an in-world date in `scenario_as_of` or `synthetic_test_clock`; never copy it into provenance fields without an explicit simulated-clock declaration. Use `not-verified` when the operational time cannot be observed.

## Status rules

- Use `working` while an artifact is incomplete.
- Use `reviewed` only after a defined review occurs.
- Use `ready-for-approval` when stated validation gates pass but no human has approved it.
- Use `approved` only when an explicit human decision identifies the exact version or hash and its scope.
- Use `blocked` when a required condition is missing.
- Use `released` only when verified external release evidence exists.

Create a new version after any material change. Invalidate review or approval that applies only to an older version.

## Approval record

```yaml
approval_type: "content-approval"
artifact_id: "report-v1"
artifact_version: "1.0"
artifact_hash: "sha256:synthetic-value"
decision: "approved"
decided_by: "human-identifier"
decided_at: "ISO-8601 timestamp"
scope: "content only; no publication authorization"
```

Never invent an approval, approver, scope, version, or hash.

## Canonical artifacts

- Workflow manifest: scope, stages, selected skills, versions, gates, blockers, and external-action state.
- Evidence package: source register, claim ledger, report, citations, limitations, and review records.
- Visualization package: verified values, claim mappings, figure specifications, captions, alt text, and provenance.
- Publication design package: tokens, components, layouts, editable source identity, and asset manifest.
- Web release candidate: source refs, build identity, routes, content map, and local QA evidence.
- Visual QA report: three-pass findings, evidence, severity, retest state, and exact artifact identity.
- Motion QA report: runtime identity, lifecycle evidence, measurements, reduced-motion result, and verdict.
- Derivative package: approved source identity, claim mappings, formats, and publication state.
- Sites release record: approval, exact build, access policy, routes, deployment status, and rollback reference.
- Pencil edit record: target confirmation, original and backup hashes, edits, final hash, and validation.
- Creative provenance manifest: origins, classifications, transformations, parent-child lineage, rights, and public projection.

## Handoff checks

Before accepting an upstream artifact:

1. Confirm artifact type and schema version.
2. Confirm the referenced version or hash.
3. Inspect blockers, limitations, visibility, and rights.
4. Confirm the approval state required for the intended action.
5. Record accepted input versions in the new artifact.
6. Stop or qualify the work when required information is missing.

Do not silently modify a frozen upstream artifact. Record a requested correction and return it to its owning stage.
