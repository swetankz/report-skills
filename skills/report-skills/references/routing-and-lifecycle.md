# Routing and lifecycle

Use this reference to build the stage plan and `workflow-manifest.yaml`.

## Routing matrix

| Need | Specialist | Minimum accepted input | Primary output |
|---|---|---|---|
| Source-backed analytical report | `evidence-first-report` | Topic, audience, cutoff, evidence or authorized access | Evidence and report package |
| Evidence charts or diagrams | `editorial-data-storytelling` | Validated claims and reproducible source data | Visualization package |
| Editable publication system | `report-visual-system` | Approved report and figure set | Publication design package |
| Responsive editorial website | `interactive-report-publisher` | Complete report, figures, and publication rules | Local web release candidate |
| Structural, optical, and reader QA | `visual-hygiene-auditor` | Observable artifact and target formats | Visual QA report |
| Loader, reveal, and motion QA | `motion-performance-qa` | Runnable motion artifact and observable runtime | Motion QA report |
| Social or video derivatives | `report-content-repurposer` | Approved report version and format brief | Derivative package |
| Sites release preparation or release | `sites-release-manager` | Canonical-source receipt, current QA, access intent, exact authorization | Sites release record |
| Safe Pencil editing | `pencil-safe-editor` | Live connection, exact active file, requested edits | Pencil edit record |
| Generated or exported file lineage | `creative-artifact-provenance` | Artifact inventory and available origin metadata | Creative provenance manifest |

## Default dependency order

Use this order only when the user requests the complete lifecycle:

1. Establish scope, evidence cutoff, access, privacy, rights, and outputs.
2. Produce or validate the evidence-led report.
3. Produce evidence visuals from validated findings.
4. Build the editable publication system when requested.
5. Build the local interactive publication when requested.
6. Run visual QA and motion QA when motion exists.
7. Create derivatives only from the approved report version.
8. Prepare release only from the exact validated canonical source.
9. Perform an external release only after separate explicit authorization.

Start later when a valid upstream artifact already exists. Reopen an earlier stage when a downstream check exposes a source, claim, version, or approval defect.

## Workflow manifest fields

Record at minimum:

| Field | Requirement |
|---|---|
| `schema_version` | Use the supported artifact-contract version. |
| `workflow_id` | Use a stable identifier that contains no private information. |
| `topic` | State the report subject. |
| `audience` | State the intended readers. |
| `purpose` | State the decision or communication purpose. |
| `reporting_period` | Record start and end dates when applicable. |
| `evidence_cutoff` | Record the inclusive cutoff date or explain why none applies. |
| `visibility` | Record the most restrictive applicable visibility. |
| `requested_outputs` | List exact requested deliverables. |
| `evidence_defects` | List every supplied defect with source, finding, disposition, and affected stages. |
| `selected_skills` | List only skills required by the plan. |
| `stages` | Record skill, inputs, outputs, status, blockers, and dependencies. |
| `approval_gates` | Record gate type, artifact version, state, and decision evidence. |
| `external_actions` | Default every action to unauthorized. |

## Stage record

For each stage, record:

- `stage_id`, `skill`, `status`, and dependency stage identifiers.
- `input_contracts` naming exact upstream artifact identifiers, types, versions, locations, and hashes when available. Populate these contracts even when the stage is blocked or not started; use availability or acceptance state to distinguish pending from accepted inputs.
- Accepted input artifact identifiers, versions, and hashes after actual acceptance.
- Expected and actual output artifact identifiers and versions.
- Blocking and non-blocking findings without collapsing their detail.
- Required approval type and whether it is absent, pending, or explicitly granted.
- Skip reason when the stage is not required.

## Durable checkpoint rule

Update the producing stage before beginning additional downstream work whenever an artifact is created, accepted, blocked, replaced, or invalidated. At each checkpoint:

- Move created artifacts from `expected_outputs` to `actual_outputs` with version and hash when available.
- Replace stale `working` state with the most accurate current state when pausing: `reviewed`, `ready-for-approval`, or `blocked` when their definitions are satisfied; otherwise retain `working` and add the exact continuation point.
- Record the next eligible stage, unmet prerequisites, and any downstream invalidation.
- Mark runtime, browser, provider, or external outcomes `not-verified` unless they were directly observed.

If a long workflow cannot finish in one run, stop at the smallest complete auditable handoff. Do not start another stage until the current stage's artifacts and state are durably recorded. A resumable partial workflow is valid; a stale manifest that omits already-created artifacts is not.

## Completion logic

Call a stage complete only when its specialist acceptance criteria and downstream handoff contract are satisfied. Call the workflow complete only when every requested deliverable has a verified artifact and every blocking gate passes. Return partial completion when useful artifacts exist but required work remains.

Never convert `ready-for-approval` into `approved`. Never convert a local release candidate into `released` without verified external release evidence.
