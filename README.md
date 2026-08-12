# Report Skills

Report Skills is a modular, evidence-led research-to-publication system for Codex. One plugin provides an end-to-end orchestrator and ten independently installable specialist skills.

## Skills

- `report-skills` — coordinate the complete workflow and approval gates.
- `evidence-first-report` — create traceable source-backed analytical reports.
- `editorial-data-storytelling` — turn verified findings into truthful evidence visuals.
- `report-visual-system` — build editable long-form publication systems.
- `interactive-report-publisher` — create complete accessible report websites.
- `visual-hygiene-auditor` — audit structure, optical quality, and reader comprehension.
- `motion-performance-qa` — validate loader, motion startup, reduced motion, and frame pacing.
- `report-content-repurposer` — create traceable derivatives from approved reports.
- `sites-release-manager` — prepare and, with explicit approval, release an exact candidate through OpenAI Sites.
- `pencil-safe-editor` — verify and preserve the active Pencil document before edits.
- `creative-artifact-provenance` — record creative artifact origin, status, and lineage.

## Architecture

`source/` is the maintained authoring source. `scripts/build_skills.py` generates complete packages under `skills/`. Generated packages are committed so each GitHub subpath is self-contained.

The router sequences work but does not replace specialist judgment. Every specialist accepts equivalent user-provided inputs and can run without the router or sibling skills.

## Local validation

Run with Python 3.11 or later:

```text
python scripts/build_skills.py
python scripts/check_generated.py
python scripts/validate_repository.py
python scripts/scan_public_content.py
python -m unittest discover -s tests
```

Also validate every `skills/*` folder with the current Codex skill validator and validate the repository root with the current Codex plugin validator.

## Installation

The canonical repository is [swetankz/report-skills](https://github.com/swetankz/report-skills). Pin installations to the immutable [`v0.1.0`](https://github.com/swetankz/report-skills/releases/tag/v0.1.0) release rather than the moving `main` development branch.

For the complete suite, download `report-skills-0.1.0.zip` and its checksum from the release, verify the SHA-256 value, extract it, and use the extracted root as the Codex plugin source. For one specialist, give Codex's skill installer the repository `swetankz/report-skills`, ref `v0.1.0`, and path `skills/<skill-name>`. See the [installation guide](docs/installation.md).

## Safety boundary

Public examples are synthetic. This repository must not contain private report content, credentials, live deployment identifiers, browser profiles, personal paths, private design files, unpublished provider artifacts, third-party source publications, or brand-specific assets.

No skill treats drafting, design, testing, or packaging approval as authorization to publish. External release always requires explicit human approval for the exact candidate and destination.

## Project status

Version `0.1.0` is the initial public MIT-licensed release by Swetank Gawde. The immutable release tag is `v0.1.0`. Public contact details are intentionally omitted; see [Security](SECURITY.md) for responsible reporting guidance.

Maintainers can reproduce two deterministic artifacts after validation: `scripts/create_release_package.py` builds the installable plugin package, and `scripts/create_source_snapshot.py` builds a history-free snapshot of the public repository tree. The `v0.1.0` release publishes both ZIPs with SHA-256 sidecars.
