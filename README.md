# Report Skills

Report Skills is a modular, evidence-led research-to-publication system packaged for Codex and ZCode. One plugin provides an end-to-end orchestrator and ten independently installable specialist skills, with shared skill bodies for both clients. Version `0.2.0` is unreleased and awaits fresh qualification; client and platform validation is recorded in the [installation guide](docs/installation.md#platform-validation-status).

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

`report-skills`, `sites-release-manager`, and `pencil-safe-editor` are explicit-only. Invoke them with the exact tokens `$report-skills`, `$sites-release-manager`, and `$pencil-safe-editor`; a topical request without the corresponding token does not activate the skill. Both client packages carry this activation contract; end-to-end verification in each client remains a release requirement.

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
python scripts/validate_eval_suite.py
python scripts/run_behavioral_benchmark.py --dry-run
python scripts/run_trigger_evals.py --dry-run
python -m unittest discover -s tests
```

Also validate every `skills/*` folder with the current Codex skill validator and validate the repository root with the current Codex plugin validator.

## Evaluation

Repository CI validates evaluation contracts and expands benchmark plans without starting a model. The evaluation suite supports focused routing and adversarial canaries, paired behavioral runs, schema-constrained grading, blind comparison, trigger coverage, and full release qualification. Live model evaluation stays outside public CI because it requires authentication and incurs usage. See the [evaluation protocol and release thresholds](docs/evaluation.md).

## Installation

The canonical repository is [swetankz/report-skills](https://github.com/swetankz/report-skills). Install from the [latest published GitHub release](https://github.com/swetankz/report-skills/releases) rather than the moving `main` development branch.

Use a published stable release for normal installation when one is available. GitHub pre-releases are opt-in candidates for evaluation and do not establish final qualification. The current `0.2.0` metadata identifies the intended stable version, not a published or qualified release. See the [installation guide](docs/installation.md) for the documented paths and their validation status.

### ZCode

The repository includes a ZCode marketplace descriptor. For a version-pinned candidate, use the verified release ZIP as a local marketplace directory and follow the [ZCode installation steps](docs/installation.md#install-in-zcode). Adding the GitHub repository directly follows a moving development source unless the client records an exact release ref. ZCode installation and activation still need candidate-specific end-to-end validation.

### Codex

For the complete suite, download the versioned `report-skills-<version>.zip` archive and its SHA-256 sidecar, verify the checksum, extract it, and use the extracted root as the Codex plugin source. For one specialist, give Codex's skill installer the repository `swetankz/report-skills`, a published release tag, and path `skills/<skill-name>`.

## Safety boundary

Public examples are synthetic. This repository must not contain private report content, credentials, live deployment identifiers, browser profiles, personal paths, private design files, unpublished provider artifacts, third-party source publications, or brand-specific assets.

No skill treats drafting, design, testing, or packaging approval as authorization to publish. External release always requires explicit human approval for the exact candidate and destination.

## Releases and reproducibility

Report Skills is MIT-licensed and maintained by Swetank Gawde. Published versions, assets, checksums, and release notes are available on [GitHub Releases](https://github.com/swetankz/report-skills/releases). Public contact details are intentionally omitted; see [Security](SECURITY.md) for responsible reporting guidance.

Maintainers can reproduce two deterministic artifacts after validation: `scripts/create_release_package.py` builds the installable plugin package, and `scripts/create_source_snapshot.py` builds a history-free snapshot of the public repository tree. Run `scripts/verify_release_artifacts.py` against two clean builds to verify checksums, archive metadata, manifests, inventories, and byte-for-byte reproducibility. Each release publishes both ZIPs with their SHA-256 sidecars.
