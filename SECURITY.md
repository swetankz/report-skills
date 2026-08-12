# Security

Do not include secrets, signed URLs, private deployment identifiers, browser state, personal paths, or private source material in issues, examples, fixtures, or pull requests.

Run `python scripts/scan_public_content.py` before sharing a candidate. If sensitive material enters unpublished Git history, stop release work and remove it from the complete unpublished history before any public push. If it has already become public, rotate affected credentials immediately and publish an appropriate remediation; rewriting history does not undo exposure.

Public contact details are intentionally omitted. Use GitHub Private Vulnerability Reporting when available, and never disclose sensitive details in a public issue.
