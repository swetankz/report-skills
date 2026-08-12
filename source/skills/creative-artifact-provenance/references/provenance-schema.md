# Provenance schema

## Classifications

- `provider-original`: File returned directly by an external generation provider.
- `authoring-source`: Editable source created in an authoring tool.
- `export`: File produced directly from an authoring source without substantive creative transformation.
- `local-derivative`: File transformed locally from one or more parents.
- `diagnostic`: Render or capture made for inspection, troubleshooting, or validation.
- `final-deliverable`: Approved output selected for delivery; it may also descend from another classification.

Choose the classification from evidence, not filename, folder, resolution, or appearance.

## Private record

Record fields when known and authorized:

```json
{
  "artifact_id": "synthetic-artifact-001",
  "classification": "local-derivative",
  "status": "succeeded",
  "provider": "Synthetic Provider",
  "tool": "Synthetic Tool",
  "model": "synthetic-model",
  "job_id": "synthetic-job-001",
  "execution_id": null,
  "path": "private-runtime-value",
  "url": null,
  "mime_type": "image/png",
  "width": 1200,
  "height": 1500,
  "duration_seconds": null,
  "sha256": "synthetic-hash",
  "parent_ids": ["synthetic-artifact-000"],
  "transformations": ["crop", "annotation"],
  "role": "draft-creative",
  "visibility": "private",
  "rights_status": "synthetic-owned",
  "unknown_fields": [],
  "evidence": ["synthetic-receipt"],
  "notes": null
}
```

Use runtime values only in private records. Use reserved example domains and clearly synthetic identifiers in public fixtures.

## Field-state semantics

- `known`: Supported by observed file metadata, a provider receipt, authoring record, or reproducible transformation log.
- `unknown`: Not established from available evidence; explain the gap.
- `contested`: Two or more evidence items conflict; preserve the conflict.
- `not-applicable`: The field does not apply to this classification.
- `withheld`: Known privately but intentionally absent from a public projection.

Do not use `unknown` to conceal a value or `withheld` to imply a value exists without private evidence.

## Lineage validation

- Require unique artifact identifiers.
- Require every listed parent to exist in the same manifest or a declared external register.
- Reject self-parenting and cycles.
- Order transformations from parent state to child state.
- Keep provider-job status separate from local-render status.
- Require every final deliverable to reach a known origin or a documented lineage gap.
- Record hashes as observations, not permanent identity guarantees when files may change.

## Public projection

Create a new manifest with public artifact identifiers. Include only approved relative public paths, safe descriptive metadata, permitted origin labels, transformations, parent public identifiers, dimensions, role, visibility, and rights status.

Omit private path values, private or signed URLs, credentials, provider job and execution IDs, project IDs, unpublished artifacts, and private notes. Record only the omitted field names and concise reasons under `withheld_fields`.

Validate the projection independently for dangling public parents, accidental private values, inconsistent classifications, and rights restrictions. Do not publish the private-to-public identifier map unless explicitly authorized.
