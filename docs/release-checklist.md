# Release checklist

The published `v0.1.0` tag is immutable. The next section applies to a later release candidate and does not retroactively alter the original release evidence or tag.

## Next release candidate: evaluation gates

### Offline contract checks

- [ ] `python scripts/validate_eval_suite.py` passes.
- [ ] `python scripts/run_behavioral_benchmark.py --dry-run` expands every required case, configuration, and repetition without making a model call.
- [ ] `python scripts/run_trigger_evals.py --dry-run` expands every required trigger query and repetition without making a model call.
- [ ] Repository unit, generation, standalone-package, and public-safety checks pass.
- [ ] CI contains no authenticated, paid, or live model-evaluation step.

### Behavioral quality and safety

- [ ] Every primary task case has three fresh `with_skill` runs and three matched `without_skill` runs.
- [ ] Every skill's `with_skill` median is at least 85/100.
- [ ] Every case in every repetition has zero blocking failures.
- [ ] Adversarial safety pass rate is 100%.
- [ ] All required output pairs receive blind comparison; `with_skill` wins at least 70%, with ties counted as non-wins.
- [ ] Trigger precision and recall are each at least 90% suite-wide and per skill across three repetitions per query.
- [ ] Fabricated evidence, approval, runtime observation, and provenance events total zero.
- [ ] Unauthorized external mutations total zero.
- [ ] Every wall-clock or token overhead ratio above 2x baseline has a concrete quality or safety justification recorded as an advisory finding.

### Evidence and approval

- [ ] The aggregate record identifies the candidate commit, skill hashes, model and environment, repetitions, variance, and final gate decision.
- [ ] Only sanitized aggregate evidence is proposed for publication; raw transcripts and workspaces remain local unless separately reviewed for public safety and rights.
- [ ] The exact new version, tag, commit, assets, destination, and external actions receive explicit human approval.

See [Evaluation](evaluation.md) for the protocol and definitions.

---

The sections below retain the `v0.1.0` preparation checklist as a historical record.

## Documentation

- [x] Root documentation and skill catalogue agree with the generated inventory.
- [x] Limitations and experimental adapters are explicit.
- [x] Publisher, intentional no-public-contact policy, license, repository, and homepage values are final.

## Generation and structure

- [x] Two consecutive builds are byte-for-byte identical.
- [x] Generated `skills/` matches canonical generation.
- [x] Plugin validation passes.
- [x] All eleven skill validations pass.
- [x] Standalone package checks pass after the source repository is removed.

## Behavior

- [x] Every skill scores at least 85/100 on its synthetic rubric.
- [x] The complete orchestrated synthetic workflow passes.
- [x] Every adversarial case stops safely.
- [x] No unresolved high- or critical-severity skill finding remains.

## Public safety and rights

- [x] Current tree passes the public-safety scanner.
- [ ] Intended Git history passes secret and private-content review.
- [x] Every bundled template and synthetic fixture has a recorded origin and redistribution status.
- [x] No private report artifact, path, identifier, or provider output is included.

## Candidate identity

- [ ] Working tree is clean.
- [x] The deterministic full-source snapshot records and validates the intended first-commit tree.
- [ ] Candidate commit, version, tag, and checksums are recorded.
- [x] Changelog and release limitations match the candidate.
- [x] Exact repository account, visibility, branch, and proposed external actions are shown to the user.

## Approval and publication

- [x] User explicitly approves repository creation and the exact push scope.
- [ ] Remote identity, visibility, branch, and commit are verified after upload.
- [ ] Complete-plugin installation from the release tag passes.
- [ ] Every skill subpath resolves; representative smoke tests pass.
- [ ] Release assets and checksums match the approved candidate.
