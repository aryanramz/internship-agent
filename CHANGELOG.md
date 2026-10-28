# Changelog

The project follows pre-1.0 semantic versioning. Earlier releases are preserved as development milestones; they were not production deployments.

## [0.4.0] — 2026-10-27

- Repackaged as a GitHub-ready open-source software project with MIT license, contribution/security policies, CI workflow and engineering roadmap.
- Added fictional, reproducible offline pipeline demo and independent tests.
- Separated public example profile from private local configuration and removed personal tracker identifiers from docs/tests.
- Hardened public endpoint retrieval to reject local/IP-literal hosts and refuse redirects as SSRF defense-in-depth.
- Added repository privacy checks for staged/committed personal artifacts.

## [0.3.0] — 2026-10-27

- Gmail job-alert lead staging and manually reviewed import.
- Optional Google OAuth Sheets reconciliation with preview, explicit confirmation, ownership and conflict checks.

## [0.2.0] — 2026-10-27

- Extended job source readers, structured imports and ATS-board discovery suggestions.

## [0.1.0] — 2026-10-27

- Local SQLite job/application ledger, fit scoring, conservative DOCX documents and MCP adapter scaffolding.
