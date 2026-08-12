---
name: interactive-report-publisher
description: Build or revise a complete approved report as a runnable, responsive, accessible editorial website while preserving every section, citation, limitation, and evidence visual. Use for chapter navigation, semantic web structure, responsive layouts, citation interfaces, metadata, SEO, local builds, and reduced-motion behavior; do not use for hosting or external deployment.
---

# Interactive Report Publisher

Build a local, publishable web candidate from the complete approved report. Keep implementation and external release as separately authorized operations.

## Load the applicable guidance

- Read [artifact contracts](references/artifact-contracts.md) before accepting inputs or writing `web-candidate.yaml`.
- Read [approval and stop gates](references/approval-and-stop-gates.md) before changing status or considering any external action.
- Read [public safety](references/public-safety.md) before copying sources, assets, paths, metadata, or identifiers.
- Read [evidence language](references/evidence-language.md) before describing build, accessibility, or runtime results.
- Read [validation conventions](references/validation-conventions.md) before claiming a route, viewport, interaction, or build has passed.
- Read [web publication checklist](references/web-publication-checklist.md) for content coverage and implementation acceptance criteria.

## Enforce the boundary

- Own website source, local build verification, responsive behavior, navigation, citations, accessibility, metadata, and optional editorial interaction.
- Preserve the complete approved report, figures, citations, source notes, limitations, and version identity.
- Do not turn the report into a marketing synopsis unless the user explicitly changes the deliverable and approves the content change.
- Do not host, deploy, create a remote resource, push a release, or infer publication authorization.
- Keep the implementation adaptable to the requested runtime; do not require a specific framework, animation library, or hosting provider.

## 1. Verify the release-source receipt

1. Record each input artifact ID, version, hash or commit, status, owner, timestamp, visibility, and rights constraints.
2. Require the exact report version and approved figures intended for conversion; verify that citations and limitations are included.
3. Compare competing candidates by their recorded identity and intended role. Do not infer the canonical source from a familiar folder name, newest-looking filename, or stale summary.
4. Record the chosen source and rejected alternatives with reasons.
5. Stop when source identity, required rights, or framework constraints remain unresolved. If the exact source is verifiable but content approval is absent, proceed only when the user explicitly requests a local working draft; record the missing approval, keep the candidate `working`, and prohibit release or approved-state claims.

## 2. Freeze content coverage

1. Inventory every report section, subsection, table, figure, caption, note, citation, bibliography entry, limitation, and appendix.
2. Create stable content IDs and map each ID to a route, section anchor, and component.
3. Preserve the approved order unless an explicitly approved web adaptation changes it.
4. Keep all factual wording traceable to the source version; do not introduce new claims in interface copy.
5. Fail the content gate when any required content ID is omitted, duplicated without reason, truncated, or detached from its evidence context.

Before rendering, run a quantitative-integrity preflight across the report, figure specifications, and supplied data artifacts. Reproduce material calculations when numerator and denominator are available; compare repeated values, units, populations, periods, and construct definitions. A conflicted or unsupported value must not appear in the website as established fact. Return it upstream for correction, or, for an explicitly requested local working draft, replace the affected presentation with a conspicuous conflict notice that states the competing values and blocks readiness. Do not silently choose or repair a value outside the approved source.

## 3. Select the implementation architecture

1. Honor the user's framework, runtime, browser support, hosting constraints, and existing project conventions.
2. Prefer semantic, progressively enhanced content that remains readable when optional scripting or motion fails.
3. Define routes, chapter anchors, state ownership, asset loading, build command, output directory, and verification commands before broad implementation.
4. Keep data and citation content in inspectable structures rather than burying evidence in animation code.
5. Use relative public paths and environment-safe configuration. Keep credentials and private release metadata out of source.

## 4. Implement the complete editorial experience

1. Use semantic landmarks, one coherent heading hierarchy, descriptive links, and navigable chapter anchors.
2. Provide visible keyboard focus, logical focus order, skip navigation where useful, and keyboard-operable controls.
3. Preserve figure titles, units, populations, periods, captions, source notes, provenance, and useful alternative text.
4. Keep citations reachable from supported claims and provide a complete bibliography or source interface.
5. Surface limitations clearly and at a readable size.
6. Implement responsive layouts from content needs; avoid a desktop composition merely scaled down for small screens.
7. Use two-column compositions only when they improve comparison or reading context; define a clear reading order and deliberate stacked behavior.
8. Prevent horizontal overflow, clipped text, occluded anchors, and fixed elements that block content at every required viewport.
9. Add metadata, canonical intent, share metadata where requested, structured data when justified, and meaningful document titles and descriptions.
10. Use interactions only when they clarify navigation, comparison, sequence, or evidence. Keep reading possible without them.

## 5. Implement motion safely when requested

1. Treat meaningful motion as optional enhancement, not as a prerequisite for accessing content.
2. Implement `prefers-reduced-motion` behavior that leaves all content visible, removes nonessential transforms and auto-motion, and cannot trap the loader.
3. Establish initial visual states before the first reveal to prevent flashes and hidden-content failures.
4. Wait for required fonts and important assets before measuring layout-dependent motion.
5. Initialize scroll-linked measurements and required refreshes while any loader still covers the page, then dismiss the loader only when the first reveal is ready.
6. Request `motion-performance-qa` for measurement when meaningful motion exists. Do not claim smoothness from code inspection or local intuition.

## 6. Build and verify the exact candidate

1. Run the declared build from the recorded source ref.
2. Record the command, environment, output location, exit status, source ref, and build artifact hash.
3. Serve or open the built candidate locally and inspect the runtime; a successful build proves compilation only.
4. Verify every expected route and chapter anchor, including direct loads and an invalid-route behavior.
5. Inspect the declared viewport matrix for layout, overflow, navigation, figures, citations, focus, and reading order.
6. Exercise keyboard interaction, reduced motion, internal and external links, and any interactive figures.
7. Check runtime console output and network or asset failures.
8. Record which checks used direct observation, measurement, static inspection, or inference.
9. Mark unavailable browsers, devices, routes, or behaviors `not verified`; never broaden a narrow observation into a comprehensive pass.
10. Distinguish an artifact failure from a test-infrastructure failure in every record. When the browser, server, driver, or capture tool fails before the artifact can be observed, assign affected checks `not-verified`, not `fail`, and keep the candidate, summary, and detailed validation records consistent.
11. Keep browser profiles, caches, crash dumps, temporary servers, and driver state outside website source, build output, candidate records, and retained QA evidence. Use a uniquely scoped temporary directory when a tool requires a profile, retain only declared screenshots, traces, logs, or DOM captures, and verify the handoff package contains no browser state or crash byproducts.

## 7. Write the candidate record

Produce:

- Runnable website source.
- `web-candidate.yaml`.
- Route, chapter, and complete content maps.
- Citation and bibliography interface record.
- Accessibility and responsive verification evidence.
- Build command, source ref, artifact path, and build hash.
- Known limitations, failures, and unverified environments.

Keep `external_deployment_authorized: false` unless a separate explicit record states otherwise; even with authorization, hand deployment to the designated release skill or user. Set `ready-for-approval` only when the complete content map passes, the exact build is identified, and all required local checks are directly verified. Never set human approval yourself.

## Stop conditions

Stop or return a qualified partial result when:

- The exact approved source version cannot be established.
- Conversion would omit report content, citations, figures, or limitations.
- Required assets, fonts, libraries, or source material lack permission.
- The implementation request silently changes a complete report into a synopsis.
- A required build or runtime cannot be observed.
- A consequential quantitative conflict cannot be corrected upstream or visibly quarantined in a blocked local draft.
- Browser state, crash material, credentials, or unrelated runtime byproducts remain inside the handoff package.
- The request crosses into hosting or external deployment without separately scoped authorization.

Report the blocker, evidence inspected, local work completed, and the smallest input or decision needed to continue.
