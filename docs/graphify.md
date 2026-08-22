# Graphify contributor workflow

Graphify is an optional local development tool for navigating relationships and
estimating change impact across Report Skills. It is not a plugin dependency,
runtime feature, evaluator, release gate, or source of release evidence.

## Reproducible local setup

The tested contributor version is `graphifyy==0.9.48`. Install or upgrade it
only with the repository owner's approval:

```text
uv tool install graphifyy==0.9.48
```

Install the assistant adapter outside the repository for the tool being used:

```text
graphify install --platform codex
graphify install --platform antigravity-windows
```

The repository-owned `AGENTS.md` is the project-specific Codex policy. Do not
run the Codex project installer in the canonical worktree because it can rewrite
that tracked file. Project-scoped installers may also create local files under
`.codex/` or `.agents/`; the known paths are ignored and must not be force-added
to Git. Re-run `python scripts/validate_graphify_integration.py` after any local
adapter installation.

The exact package, source tag, commit, and distribution hashes are recorded in
the [Graphify integration receipt](graphify-receipt.json).

## Build a zero-model-token code graph

From the repository root, run:

```text
graphify extract . --code-only
graphify cluster-only . --no-label
graphify diagnose multigraph --graph graphify-out/graph.json --json
python scripts/validate_graphify_integration.py
```

`--code-only` uses local AST extraction and `--no-label` avoids model-backed
community naming. The graph, manifest, report, visualization, and cache stay in
the ignored `graphify-out/` directory.

After code changes, refresh the local graph without a model call:

```text
graphify check-update .
graphify update .
graphify cluster-only . --no-label
```

Use `graphify update . --force` only after an intentional refactor deletes
enough code for Graphify's shrink guard to stop the update.

## Focused navigation

Prefer bounded queries over reading the complete graph or repository:

```text
graphify check-update .
graphify query "How is Gate 1 evidence validated?" --budget 1200
graphify affected "run_codex" --depth 2
graphify path "run_gate1_evidence" "validate_gate1_evidence"
graphify explain "canonical_model_isolation_receipt"
```

Use the result to locate likely code and tests, then confirm every conclusion
against repository source. If `graphify check-update .` cannot confirm freshness,
refresh the graph or skip it. A stale or inferred edge is never sufficient proof.

## Evaluation and release boundary

- Graphify may guide investigation and the order of deterministic checks.
- It cannot remove, reduce, pass, or substitute for a canonical check.
- Release-defining model subprocesses receive only their explicitly staged
  inputs. They must not receive root `AGENTS.md`, `.codex/`, the local Graphify
  skill, or `graphify-out/`.
- Graphify state must not appear in traces, receipts, approval packets, release
  archives, or source snapshots.
- Any candidate source, prompt, harness, model, reasoning level, evaluation
  method, or commit change still invalidates the affected evidence exactly as
  specified by the evaluation protocol.
- Model-backed semantic extraction or labeling needs separate authorization and
  must run outside the release-defining evaluation stream.

Graphify is maintained by Graphify Labs and distributed under its upstream
Apache-2.0 and MIT licensing terms. See the [official Graphify repository](https://github.com/Graphify-Labs/graphify) and [documentation](https://graphify.com/docs).
