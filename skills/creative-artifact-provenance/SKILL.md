---
name: creative-artifact-provenance
description: "Inventory and reconcile the origin, status, transformations, parent relationships, and deliverable role of generated, authored, exported, diagnostic, and final creative files. Use when distinguishing provider outputs from local derivatives, auditing missing metadata, building lineage manifests, or producing a sanitized public provenance projection without exposing private paths, URLs, job identifiers, or operational records."
---

# Creative Artifact Provenance

Build evidence-backed lineage for creative files. Preserve the difference between what is known, unknown, not applicable, and deliberately withheld.

## Load the operating rules

Read these bundled files before creating or publishing a manifest:

- [Provenance schema](references/provenance-schema.md) for classifications, field states, lineage validation, and public projection.
- [Artifact contracts](references/artifact-contracts.md) for the shared provenance manifest shape and handoff envelope.
- [Public safety](references/public-safety.md) before recording paths, URLs, provider metadata, identifiers, or rights information.
- [Validation conventions](references/validation-conventions.md) before declaring the inventory or lineage complete.

## Establish scope and disclosure level

1. Identify every supplied artifact and the directories, records, or provider receipts authorized for inspection.
2. Decide whether the requested output is a private operational record, a public projection, or both.
3. Keep the private record and public projection as separate artifacts. Never sanitize by overwriting the private source record.
4. Record visibility and rights status before copying metadata into another artifact.

## Inventory evidence

1. Assign a stable artifact identifier that does not depend solely on a mutable path.
2. Record observed file identity, MIME type, dimensions or duration, hash when available, creation evidence, and intended role.
3. Record provider, tool, model, job or execution identifier, and status only when supported by a receipt, metadata, or directly observed runtime evidence.
4. Classify each artifact as `provider-original`, `authoring-source`, `export`, `local-derivative`, `diagnostic`, or `final-deliverable`.
5. Use `unknown` with an explanation when origin or metadata cannot be established. Never infer a provider, model, job, success state, or parent from filename similarity alone.

## Build lineage

1. Record parent identifiers for every export, derivative, diagnostic, composite, and final deliverable.
2. Record each transformation in order, including crop, resize, color edit, compositing, annotation, re-encoding, export, and diagnostic rendering.
3. Distinguish provider completion from local processing. A successful local composite does not prove the provider job succeeded.
4. Distinguish a diagnostic render from a provider original and from a final deliverable.
5. Preserve an unbroken path from every final deliverable to its known origins; record a documented gap instead of fabricating a link.

## Validate the private record

1. Detect duplicate identifiers, missing parents, cycles, contradictory statuses, impossible dimensions, and final files without lineage.
2. Reconcile conflicting metadata by retaining each evidence item and marking the field contested.
3. Confirm rights and visibility before describing an artifact as distributable.
4. Report inventory coverage, lineage coverage, unresolved fields, and evidence limitations.

## Create a public projection

1. Start from the validated private manifest.
2. Assign stable public identifiers and map only permitted parent relationships.
3. Remove absolute paths, private URLs, signed URLs, provider job IDs, execution IDs, project identifiers, unpublished artifacts, credentials, personal data, and private notes.
4. Include safe descriptive metadata, transformations, dimensions, role, rights status, and permitted provider or model names only when disclosure is authorized.
5. List field names and reasons under `withheld_fields` without copying their values.
6. Keep `unknown_fields` distinct from `withheld_fields`; do not present redaction as missing evidence.
7. Re-run lineage and public-safety validation against the projection itself.

## Required output

Produce a private `provenance-manifest.json` unless the request is explicitly public-only and no private metadata is supplied. When public disclosure is requested, also produce a separate sanitized projection and human-readable summary. Include missing-metadata warnings, contradictions, lineage gaps, disclosure decisions, and validation results.

Do not publish, upload, or distribute any artifact. Do not replace report-body citations, evidence registers, or figure-data provenance with creative-file lineage.
