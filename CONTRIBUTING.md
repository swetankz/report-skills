# Contributing

## Authoring model

Edit canonical material under `source/`. Do not hand-edit generated files under `skills/`.

1. Update the relevant canonical skill or shared reference.
2. Update `source/skill-map.yaml` when resources change.
3. Run the generator.
4. Run repository, safety, and unit validation.
5. Add or update a synthetic evaluation when behavior changes.

## Skill requirements

- Keep frontmatter to `name` and `description`.
- Put trigger contexts in the description.
- Use imperative instructions and direct one-level reference links.
- Keep each skill independently usable.
- Do not add a README or changelog inside a skill directory.
- Never add credentials, private artifacts, or real project examples.

## Review requirements

Behavioral changes need standalone and router-level evaluation. Changes affecting publication, deployment, live editors, or provenance need negative tests that prove missing approval or ambiguous state causes a safe stop.

## Graph-assisted development

Contributors may use Graphify for local code navigation and change-impact analysis. Graphify output is advisory, remains untracked, and cannot replace any required validator, evaluation, or approval. See [Graphify contributor workflow](docs/graphify.md).
