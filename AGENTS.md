# Repository agent policy

## Graphify-assisted development

Graphify is an optional local navigation and impact-analysis sidecar. Repository
source, deterministic validators, immutable evaluation receipts, and explicit
human approvals remain authoritative.

- Before querying an existing graph, run `graphify check-update .`. If freshness
  cannot be confirmed, refresh it or treat it as stale and use repository source.
  When it is current, use `graphify query`, `path`, `explain`, or `affected`
  before broad codebase searches for architecture or cross-file impact questions.
- Refresh a local code-only graph after code changes with `graphify update .`.
  Use `graphify cluster-only . --no-label` when community structure must also be
  refreshed. These operations do not require a model.
- Treat every Graphify result as advisory. It may guide investigation or the
  order of deterministic checks, but it must never waive, prune, or satisfy a
  mandatory release or semantic evaluation gate.
- Never copy `AGENTS.md`, `.codex/`, `.agents/rules/graphify.md`,
  `.agents/skills/graphify/`, `.agents/workflows/graphify.md`, or `graphify-out/`
  into a release-defining model workspace. Project Graphify guidance and graph
  state must not appear in model traces or evidence receipts.
- Do not run Graphify semantic extraction, model-backed labeling, installation,
  upgrades, or Git-hook changes without explicit authorization. The tested local
  contributor version is `graphifyy==0.9.48`.
- Generated Graphify adapters, hooks, graphs, caches, and reports are local and
  ignored. Follow `docs/graphify.md` to reproduce them.
