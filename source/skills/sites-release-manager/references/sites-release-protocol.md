# Sites release protocol

## Canonical-source receipt

Record these fields before building or packaging:

```yaml
canonical_source:
  identity: "private-runtime-value"
  source_ref: "exact-ref"
  observed_at: "ISO-8601"
  content_hash: "sha256:value"
  working_tree_state: "clean-or-dirty-or-not-applicable"
  artifact_status: "approved"
  owner: "human-or-system-owner"
validated_candidate:
  source_ref: "exact-ref"
  build_hash: "sha256:value"
  qa_record_ids: []
```

Require a direct match between the canonical source and validated candidate. A deployment from a different ref or changed working tree requires a new build, QA record, and approval.

## Dry-run sequence

1. Resolve canonical source candidates and explain the selection evidence.
2. Check revision identity, working-tree state, upstream/downstream drift, and competing artifacts.
3. Run or verify the declared build for the exact ref.
4. Hash or otherwise identify the output package.
5. Verify expected paths and routes against the local or authorized staged artifact.
6. Check content completeness, citations, accessibility evidence, metadata, rights, and current QA status.
7. Compare intended Sites visibility with the candidate's recorded release intent.
8. Prepare an approval packet and leave the state `awaiting_approval`.

Do not authenticate, upload, deploy, change access, create a project, or modify a remote route during a dry run.

## Approval match

Treat publication approval as valid only when it explicitly identifies:

- Exact source ref and package hash.
- Exact Sites target project.
- Intended access level.
- External actions authorized.
- Approving human, decision time, and scope.

Invalidate approval after any material source, package, target, route, or access change. Do not reuse approval from content, design, QA, packaging, or a previous release.

## Authorized deployment sequence

1. Confirm an authenticated Sites capability and observable target state.
2. Re-run the approval match and freshness checks.
3. Preserve the current remote release or record the supported rollback reference.
4. Submit only the exact approved package.
5. Record the provider response and resulting release identity privately.
6. Verify expected routes and access from the resulting destination.
7. Compare a deployed marker or checksum with the approved package where supported.
8. Record deviations, partial failures, and recovery options accurately.

Do not repair source content during deployment. Return the candidate to its owning skill when a fix is needed.

## Release record

Include at minimum:

```yaml
schema_version: "1.0"
release_state: "awaiting_approval"
publication_approval: null
canonical_source: "private-runtime-value"
source_ref: "exact-ref"
build_hash: "sha256:value"
target_project: "private-runtime-value"
intended_access: "private-or-public"
routes_expected: []
routes_verified: []
deployment_status: null
rollback_reference: null
blockers: []
```

Keep credentials, signed URLs, target IDs, deployment IDs, and private routes out of public artifacts. Use clearly synthetic values in examples.

## Stop conditions

Stop before external mutation when authorization, authentication, canonical identity, exact ref, package identity, current QA, target project, access intent, or rollback expectations are missing or contradictory. Mark runtime-only checks `not-verified` when the required capability cannot be observed.
