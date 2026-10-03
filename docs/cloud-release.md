# Cloud release workflow

The release tooling runs on a Linux cloud workspace with Python 3.11 or later,
Git, and an authenticated native Codex CLI. GitHub Actions performs offline
validation; authenticated model evaluation runs in the private cloud workspace.
Moving execution to the cloud does not change either release gate.

## Transfer the current candidate

Push the committed candidate branch from the machine that owns it, then fetch
that branch in the cloud. Cloning `main` does not transfer unpublished fixes.
Record the full commit and tree identifiers and confirm a clean working tree
before spending evaluation tokens:

```bash
git fetch origin
git switch --detach <candidate-commit>
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git status --porcelain=v1 --untracked-files=all
```

Keep raw `evals/runs/` and `evals/review/` material private and ignored. Preserve
prior receipts for diagnosis, but begin fresh cloud runs: the native executable,
operating environment, and prompt-isolation identity differ from a desktop run.
Do not resume a partial desktop run or combine receipts from different hosts.

## Check runtime and access

Inspect the managed environment's supported network policy and credential
readiness before network operations. Preserve its proxy and CA settings. Add
missing destinations or credentials through the environment configuration UI;
do not change proxy routing or copy credential files from another machine.

```bash
python --version
git --version
codex --version
codex login status
```

The existing evaluation runners verify the requested model and reasoning effort
against the live model catalog and run a model-free prompt-isolation probe before
release-defining calls. A successful sign-in or catalog lookup alone does not
prove that a model invocation will succeed. Any separate connectivity smoke test
is diagnostic only and must not be counted as release evidence.

Git fetch/push, a connected GitHub app, and the GitHub CLI are separate access
paths. Check the path that will publish the release. CLI publication needs
authorized repository access plus network access to `api.github.com` and
`uploads.github.com`; artifact verification also needs the GitHub release
download destinations. A connector available in chat does not automatically
provide credentials to `gh` in the cloud shell.

## Validate and freeze

Run the repository's offline matrix in the cloud:

```bash
python scripts/check_generated.py
python scripts/validate_repository.py
python scripts/scan_public_content.py
python scripts/validate_eval_suite.py
python scripts/run_gate1_evidence.py --show-plan
python scripts/run_behavioral_benchmark.py --dry-run
python scripts/run_trigger_evals.py --dry-run
python -m unittest discover -s tests
python scripts/test_standalone_packages.py
```

Validate the complete plugin and all eleven standalone skills with the current
official client validators as required by the release checklist. Complete all
source, harness, packaging, and version changes before freezing the candidate.
The Codex manifest, ZCode manifest, marketplace entry, and `pyproject.toml` must
agree on the version. Existing published tags and assets remain immutable.

## Run and retain evidence

Follow the exact commands and stage order in [Evaluation](evaluation.md), using
new run identifiers on one immutable candidate. Gate 1 retains its tracked
25-call model profile. When final qualification is authorized, Gate 2 requires
96 behavioral tasks, 96 graders, 33 blind comparisons, and 75 trigger
observations under the selected common profile. A failed stage stops the
sequence; diagnose it before starting any fresh attempt.

Keep the cloud workspace and its private evidence available until all downstream
validation completes. A terminated worker, lost workspace, invalid receipt, or
partial run is not a completed gate. Do not add paid model calls to public CI or
upload raw workspaces as public Actions artifacts.

## Build and publish

After the applicable gates pass, build the plugin and history-free source ZIPs
twice from the exact clean candidate and compare all four assets:

```bash
python scripts/create_release_package.py
python scripts/create_source_snapshot.py
mkdir -p .build/cloud-release-first
cp dist/*.zip dist/*.sha256 .build/cloud-release-first/
python scripts/create_release_package.py
python scripts/create_source_snapshot.py
python scripts/verify_release_artifacts.py --compare-directory .build/cloud-release-first
```

These commands create verification candidates without recording publication
authorization. When publication is authorized for the exact version and tag,
build and verify both sets with the same `--authorized-release-tag <tag>`
argument. Validate the extracted source snapshot and installation paths before
publishing. Follow `docs/release-checklist.md` in the exact candidate source tree for tag identity,
sanitized evidence, uploaded asset size/digest checks, and installation smoke
checks. A cloud setup or successful archive build alone is not a release pass.
