# Public-safety rules

Apply these rules to examples, generated packages, logs, evaluation fixtures, and release artifacts.

## Exclude

- Absolute local paths, usernames, home directories, clipboard paths, and temporary locations.
- Passwords, access tokens, API keys, private keys, signed URLs, session data, or authentication query parameters.
- Live deployment project IDs, private routes, access-control metadata, or hosting configuration.
- Browser profiles, cookies, histories, login databases, local state, or secure preferences.
- Real provider job IDs, unpublished outputs, account balances, or private provider URLs.
- Private report prose, claims, citations, tables, charts, screenshots, PDFs, websites, and QA captures.
- Private `.pen` files, recovery copies, design migrations, or editable project sources.
- Personal or project-specific brand rules, typography, motifs, metadata, and assets.
- Third-party publications, reference media, fonts, binaries, or assets without redistribution permission.
- Unresolved placeholders in release material.

## Use synthetic fixtures

- Label all fictional organizations, data, evidence, identities, jobs, and destinations as synthetic.
- Use reserved example domains.
- Use opaque synthetic identifiers.
- Use neutral visual tokens.
- Keep intentionally defective inputs under an explicitly named test-fixture path.
- Keep corrected expected outputs separate from defective inputs.

## Protect provenance

Maintain a complete private record when the work requires operational identifiers, but create a redacted public projection. Remove private paths, signed URLs, tokens, personal identifiers, and live job or project IDs from the projection.

Do not replace unknown metadata with plausible values. Use `unknown` and explain the gap.

## Check rights

Record origin, creator, license, redistribution permission, and modification state for included assets. Exclude any asset whose distribution status cannot be established.

Do not assume a repository license grants rights to third-party or excluded material.

## Scan before release

Scan canonical source, generated packages, fixtures, assets, archives, and the complete intended Git history. Make the scanner fail on blocking findings and report the file and location without printing a complete possible secret.

