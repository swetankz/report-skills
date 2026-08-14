# Installation

## Complete plugin

After the `v0.2.0` GitHub release and its assets are published, download the immutable plugin package and checksum. Until then, use the latest version present on the repository's Releases page.

- `https://github.com/swetankz/report-skills/releases/download/v0.2.0/report-skills-0.2.0.zip`
- `https://github.com/swetankz/report-skills/releases/download/v0.2.0/report-skills-0.2.0.zip.sha256`

Verify the SHA-256 value, extract the package, and use the extracted root as the Codex plugin source. Its manifest exposes every directory under `skills/`.

## One skill

After publication, use the immutable release-tag subpath `skills/<skill-name>` through the Codex skill installer. Supply repository `swetankz/report-skills`, ref `v0.2.0`, and the selected path. For example, the evidence skill is available at:

`https://github.com/swetankz/report-skills/tree/v0.2.0/skills/evidence-first-report`

Each folder is self-contained and must work after the rest of the repository is removed.

## Multiple selected skills

Pass multiple `skills/<skill-name>` paths to the skill installer when the complete plugin is unnecessary. Pin all paths to `v0.2.0`. Do not copy `source/` as a runtime dependency; it exists for maintainers and generation only.

## Immutable release

`main` is the moving development branch. Use `v0.2.0` for reproducible installation only after that tag and its assets exist. Release verification covers the published asset, its checksum, the complete plugin package, and representative standalone skill subpaths.

## Validation after installation

- Confirm the installed folder contains `SKILL.md` and `agents/openai.yaml`.
- Confirm every local link and script resolves without the source repository.
- Invoke the skill explicitly through its default prompt.
- Confirm sensitive skills stop without approval or verified live state.
