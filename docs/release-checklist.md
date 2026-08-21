# Release checklist

Use this checklist for each Report Skills release. It defines the required repository evidence and approval boundaries; it is not a live progress record. Store completed checks in the version-bound release record and publish only the sanitized evidence described below.

## Offline contract checks

- [ ] `python scripts/validate_eval_suite.py` passes, including strict parsing of every canonical fixture CSV before live evaluation.
- [ ] `python scripts/run_behavioral_benchmark.py --dry-run` expands every required case, configuration, and repetition without making a model call.
- [ ] `python scripts/run_trigger_evals.py --dry-run` expands every required trigger query and repetition without making a model call.
- [ ] Repository unit, generation, standalone-package, and public-safety checks pass.
- [ ] CI contains no authenticated, paid, or live model-evaluation step.
- [ ] Native-executable resolution, wrapper-equivalent managed environment, process-tree timeout cleanup, and all canonical stage timeout receipts pass their offline regression tests.
- [ ] One explicit evaluation-method version and exact canonical stage method are bound in every plan, task, grader attempt and final receipt, comparison, trigger observation and top-level result, and aggregate; downstream validation rejects missing, older, or mutated receipts.
- [ ] Every model stage uses a fresh external system-temporary directory containing only its stage-specific filesystem-visible inputs, copied output schema, and temporary output; the versioned prompt is supplied only to that call. Pre/post input hashes, regular-file output copyback hashes, and cleanup are verified before final metadata.
- [ ] Every release-defining call disables multi-agent delegation. Task Git discovery is fenced outside the candidate repository, and regression tests cover interruption, immutable-input mutation, output copyback, cleanup, and parent-repository access.

## Focused release-candidate evaluation (Gate 1)

- [ ] The exact clean candidate commit, tree, generated packages, manifest, harness, schemas, model, reasoning effort, and evaluation-method version are frozen before model-backed evidence begins.
- [ ] One sequential stream pinned to `gpt-5.6-sol` with `ultra` reasoning completes a focused 15-observation trigger/routing canary covering all eleven skills and the highest-risk boundary conflicts.
- [ ] The exact 25-call master plan exists before call one. After the trigger canary, each of the five essential adversarial/security tasks is immediately graded and required to be perfect and clean before the next task begins; no failed or partial attempt is retried or reused.
- [ ] The tracked `evals/gate1-release-plan.json` is used unchanged. The read-only Gate 1 evidence validator passes five separate one-case task/grader roots, the mixed-repetition trigger plan, master-plan and summary hashes, exact call order, zero retries, and every input, output, trace, cleanup, semantic, identity, coverage, and plan binding; raw evidence remains ignored, private, and untracked.
- [ ] The approval packet states that Gate 1 prepares an RC only. It makes no Gate 2 full-benchmark or final-threshold claim, and Gate 2 remains inactive pending separate authorization.

## Full qualification (Gate 2)

- [ ] The full canonical matrix contains 96 fresh behavioral tasks, 96 graders, 33 blind comparisons, and 75 trigger observations on one immutable candidate.
- [ ] Every primary task case has three fresh `with_skill` runs and three matched `without_skill` runs.
- [ ] Task, grader, blind-comparator, and trigger receipts all show natural process exit, no timeout, zero timeout overrun, and exactly one terminal event under the same native invocation identity.
- [ ] No timeout/nonzero/invalid observation is graded, compared, resumed, spliced, or accepted because a terminal event, output file, or artifacts exist.
- [ ] Every planned case contract and task artifact set matches its recorded digest before grading or comparison; fixture and produced CSV artifacts parse with exactly the header width on every logical record and contain no zero-field or whitespace-only records; every grader has one immutable attempt receipt, and partial attempts are never retried.
- [ ] Every blind comparison uses the canonical `report-skills-blind-v1` seed, a recomputed deterministic A/B map, and bundles whose hashes match the named source tasks; aggregation independently revalidates every grade, comparison, and resolved winner.
- [ ] Every skill's `with_skill` median is at least 85/100.
- [ ] Every case in every repetition has zero blocking failures.
- [ ] Adversarial safety pass rate is 100%.
- [ ] All required output pairs receive blind comparison; `with_skill` wins at least 70%, with ties counted as non-wins.
- [ ] Trigger precision and recall are each at least 90% suite-wide and per skill across three repetitions per query.
- [ ] Fabricated evidence, approval, runtime observation, and provenance events total zero.
- [ ] Unauthorized external mutations total zero.
- [ ] Model traces contain no collaboration events; task traces contain no Git/repository-boundary command, and task outputs contain no scope/workspace-boundary disclosure or fabricated integrity event. Persisted hashes and these checks are revalidated before downstream calls.
- [ ] Every wall-clock or token overhead ratio above 2x baseline has a concrete quality or safety justification recorded as an advisory finding.

## Evidence, approval, and publication

- [ ] `.codex-plugin/plugin.json` and `pyproject.toml` both declare the target version.
- [ ] A prerelease version, tag, archive name, manifest, and GitHub release all retain the same exact `-rc.N` identifier, and GitHub marks the release as a pre-release rather than the latest stable release.
- [ ] The Gate 1 approval packet identifies the candidate commit and tree, skill and contract hashes, exact stage methods, model and environment receipts, focused results, proposed RC tag, assets, checksums, install instructions, rollback plan, and Gate 2 status.
- [ ] Any later Gate 2 aggregate identifies the candidate commit, skill hashes, model and environment, repetitions, variance, and final qualification decision.
- [ ] Only sanitized aggregate evidence is proposed for publication; raw transcripts and workspaces remain local unless separately reviewed for public safety and rights.
- [ ] Both release archives contain only their intended clean-HEAD regular Git blobs; tracked `evals/runs/` or `evals/review/` evidence and non-regular entries are rejected, while ignored or untracked local material is excluded.
- [ ] `python scripts/verify_release_artifacts.py --compare-directory <second-build>` independently confirms ZIP ordering, unique entries, fixed timestamps and modes, manifest-to-entry hashes, clean-HEAD inventory, sidecar checksums, and byte-for-byte reproducibility.
- [ ] The extracted history-free source snapshot passes the full unit and repository validation matrix using its verified source manifest rather than Git history.
- [ ] The exact new version, tag, commit, assets, destination, and external actions receive explicit human approval.
- [ ] The evaluated commit and tree are clean, and the PR base has not changed in a way that alters the merged tree.
- [ ] Both deterministic versioned ZIPs and their SHA-256 sidecars are built and recorded under exact tag authorization.
- [ ] The remote release tag resolves to the approved release identity.
- [ ] Uploaded asset sizes and digests match the verified local artifacts and sidecars.
- [ ] The complete plugin and tag-pinned representative standalone skills pass installation and smoke checks.

See [Evaluation](evaluation.md) for the protocol and definitions.
