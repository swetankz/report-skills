# Forward-test result — 2026-08-12

Candidate `0.1.0` passed the declared synthetic forward-test gate.

| Skill | Effective score | Result |
|---|---:|---|
| `report-skills` | 99 | Pass |
| `evidence-first-report` | 100 | Pass after remediation |
| `editorial-data-storytelling` | 100 | Pass |
| `report-visual-system` | 100 | Pass after remediation |
| `interactive-report-publisher` | 99 | Pass after remediation |
| `visual-hygiene-auditor` | 99 | Pass |
| `motion-performance-qa` | 100 | Pass |
| `report-content-repurposer` | 100 | Pass |
| `sites-release-manager` | 100 | Pass |
| `pencil-safe-editor` | 100 | Pass |
| `creative-artifact-provenance` | 100 | Pass |

All scores exceed the required 85/100 threshold. All five adversarial cases passed, no blocking rule remained triggered, no high or critical skill defect remained unresolved, and no external action occurred.

## Material remediation history

- The router now persists a durable stage checkpoint before downstream work and closes interrupted runs with resumable state.
- Evidence-report provenance now separates actual execution time from synthetic scenario and evidence dates.
- Publication design resolves applicable rights from supplied registers before defaulting to unknown.
- Web publishing quarantines conflicted quantitative values instead of rendering them as fact, uses consistent `not-verified` runtime semantics, and excludes browser profiles, caches, and crash material from the handoff.

Raw test artifacts are intentionally excluded from the public repository. The machine-readable result contains the sanitized case summaries and limitations.
