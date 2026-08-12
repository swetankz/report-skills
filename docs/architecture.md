# Architecture

## Distribution model

Report Skills is one Codex plugin with eleven sibling skill directories. `report-skills` is an explicit orchestrator; it is not a physical container for the specialists.

Every specialist can be copied or installed independently because its generated folder contains its own `SKILL.md`, UI metadata, references, templates, scripts, and required assets.

## Authoring model

```text
source/shared/              canonical cross-skill rules
source/skills/<name>/       canonical skill-specific material
source/skill-map.yaml       explicit distribution composition
templates/                  canonical interoperable templates
scripts/build_skills.py     deterministic generator
skills/<name>/              committed standalone distribution
```

The generator copies only mapped shared references and templates into each package. No generated skill references a parent or sibling directory.

## Workflow model

```text
report-skills
  -> evidence-first-report
  -> editorial-data-storytelling
  -> report-visual-system
  -> interactive-report-publisher
  -> visual-hygiene-auditor
  -> motion-performance-qa when motion exists
  -> report-content-repurposer after content approval
  -> creative-artifact-provenance whenever creative files appear
  -> pencil-safe-editor before Pencil writes
  -> sites-release-manager after explicit publication approval
```

This is a routing model, not a required linear sequence. Any specialist may start from an equivalent valid user artifact.

## State model

Artifacts progress through `working`, `reviewed`, `ready-for-approval`, `approved`, `blocked`, and `released` states. Skills may recommend readiness but cannot self-approve. External publication requires a separate explicit human authorization identifying the exact artifact and destination.

## Canonical-source rule

Do not infer the latest artifact from path names or existing deployment metadata. Record an exact path or repository identity, version or revision, timestamp, status, and hash when practical before downstream QA or release.

## Validation model

The repository validates four layers:

1. Canonical source and map completeness.
2. Deterministic generated packages.
3. Standalone skill structure and references.
4. Synthetic behavior, adversarial stops, and public safety.

