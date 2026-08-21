# Installation

Use the latest stable [GitHub release](https://github.com/swetankz/report-skills/releases) for normal installation. Release tags and assets are immutable; `main` is the moving development branch. Install a GitHub pre-release only when intentionally evaluating a release candidate.

## Complete plugin

Choose a release and download its versioned plugin package and SHA-256 sidecar:

- `report-skills-<version>.zip`
- `report-skills-<version>.zip.sha256`

Verify the SHA-256 value, extract the package, and use the extracted root as the Codex plugin source. Its manifest exposes every directory under `skills/`.

## One skill

Use an immutable release-tag subpath `skills/<skill-name>` through the Codex skill installer. Supply repository `swetankz/report-skills`, the selected release tag, and the skill path. For example:

`https://github.com/swetankz/report-skills/tree/<release-tag>/skills/evidence-first-report`

Each folder is self-contained and must work after the rest of the repository is removed.

## Multiple selected skills

Pass multiple `skills/<skill-name>` paths to the skill installer when the complete plugin is unnecessary. Pin every path to the same published release tag. Do not copy `source/` as a runtime dependency; it exists for maintainers and generation only.

## Immutable release

For reproducible installation, record the release tag and asset checksum. Release verification covers the published asset, its checksum, the complete plugin package, and representative standalone skill subpaths.

## Validation after installation

- Confirm the installed folder contains `SKILL.md` and `agents/openai.yaml`.
- Confirm every local link and script resolves without the source repository.
- Invoke the skill explicitly through its default prompt.
- Confirm sensitive skills stop without approval or verified live state.
