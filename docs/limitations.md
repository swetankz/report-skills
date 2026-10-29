# Limitations

- The system improves traceability and review discipline but cannot guarantee factual accuracy without adequate accessible evidence.
- Internal academic-style review is not external academic peer review.
- Tool-dependent skills can only claim runtime, browser, deployment, or editor behavior that was directly observed.
- `interactive-report-publisher` creates a release candidate but never authorizes deployment.
- `report-skills`, `sites-release-manager`, and `pencil-safe-editor` are explicit-only and require the exact `$report-skills`, `$sites-release-manager`, or `$pencil-safe-editor` token, respectively; topical wording alone does not activate them.
- `sites-release-manager` is OpenAI Sites-specific; a dry run is the default when approval or authenticated tooling is absent.
- `pencil-safe-editor` is Pencil-specific and performs no write when connectivity or active-file identity is ambiguous.
- Motion thresholds in synthetic evaluations are fixture-specific, not universal performance guarantees.
- Synthetic examples demonstrate behavior and are not real-world evidence.
- A generated standalone skill intentionally duplicates selected shared references; maintainers edit only canonical source.
- Version `0.2.0` is unreleased and requires fresh qualification. Earlier RC receipts do not establish the current candidate's quality or installation support.
- Tag-based installation and actual plugin-ZIP installation must be verified for each release. Current candidate checks remain pending as described in the [installation validation status](installation.md#platform-validation-status); later installer or platform changes require retesting.
- ZCode packaging includes the skill catalog and intended activation contract; candidate-specific end-to-end behavior has not yet been established. Host-specific skills (`sites-release-manager` for OpenAI Sites, `pencil-safe-editor` for Pencil) require the corresponding tools to be available in the client that runs them.
- Original bundled material is licensed under MIT by Swetank Gawde. Third-party and private material remains excluded.
