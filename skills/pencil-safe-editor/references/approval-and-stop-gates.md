# Approval and stop gates

## Approval model

Treat these permissions as separate:

- Research or source-access permission.
- Drafting permission.
- Content approval.
- Design approval.
- Local implementation and testing permission.
- External publication approval.
- Access-control change approval.
- Live-editor mutation approval.

Never infer one permission from another. Record the exact artifact, destination, action, and scope authorized.

## External-action rule

Default every external state-changing action to unauthorized. Do not deploy, push, post, schedule, email, publish, change access controls, or edit an ambiguous live target unless the user explicitly authorizes that exact action.

When authorization is absent:

1. Complete safe local preparation and validation.
2. Produce an approval packet identifying the exact candidate and action.
3. Set the release state to `awaiting_approval` or the artifact state to `ready-for-approval`.
4. Perform zero external mutations.

## Universal stop conditions

Stop or return a blocker record when:

- A required input or artifact version is missing.
- Canonical source identity is ambiguous.
- A material claim lacks adequate evidence.
- Rights or privacy constraints prohibit the requested output.
- A required tool or runtime cannot be observed.
- The active live-edit target cannot be confirmed.
- A build, route, citation, accessibility, or release-blocking QA gate fails.
- Exact external authorization is absent.

Do not fabricate missing evidence, approvals, tool results, or runtime observations to continue.

## Canonical-source gate

Before downstream release work, record:

- Source path or repository identity.
- Branch, revision, or artifact version.
- Timestamp.
- Hash when practical.
- Owner or authoritative system.
- Status and intended role.

Do not choose a source because its folder is named `latest`, because it already contains deployment metadata, or because it is convenient to build.

## Review and approval gate

A skill may recommend `ready-for-approval` only when its declared blocking checks pass. It may not self-approve.

After an approved artifact changes materially:

- Create a new version.
- Mark prior downstream QA as stale.
- Repeat checks affected by the change.
- Obtain a new human approval when required.

## Tool-unavailable behavior

When a required tool is unavailable:

- Provide a dry-run, plan, or unverified artifact if useful.
- State which result remains unverified.
- Never claim a file was edited, a browser was tested, a build ran, or a deployment succeeded without direct evidence.

