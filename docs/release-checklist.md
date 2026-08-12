# Release checklist

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
