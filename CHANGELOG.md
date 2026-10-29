# Changelog

The project follows pre-1.0 semantic versioning. Earlier releases are preserved as development milestones; they were not production deployments.

## Unreleased

- Reconciled the master architecture/roadmap against merged `develop`, live evidence and open PR #8; added a component matrix, dependency-aware issues, release acceptance/versioning policy and precise next ATS/registry PR scope. No backend behavior, version, release or endpoint activation changed.
- Corrected stale MCP import-tool documentation, recorded the operator's final Sheets credential-reuse preview, and kept pending ChatGPT qualification separate from completed local MCP work.
- Validated MCP SDK 2.3.0 stdio discovery/invocation with modern and legacy protocol negotiation using separate fictional records.
- Restricted the initial MCP registry to read-only summaries, rankings and previews; added actual read-only SQLite access and removed import-time database creation and HTTP startup.
- Added typed structured results, bounded inputs, sanitized tool errors and minimal preview output; write/Google/file tools remain unavailable in MCP.
- Documented zero-cost ChatGPT connectivity options and the Tailscale Personal/Funnel plus local OAuth architecture. Gateway/startup implementation is pending in PR #8; no external endpoint is activated.
- Added exact Sheets previews, metadata-only local audit and an opt-in synthetic tracker runner; recorded operator-reported successful basic live OAuth/write/idempotency checks.
- Decoupled Google credentials from the database with private per-user defaults, explicit overrides and nondestructive legacy-token adoption.
- Replaced raw Sheets failures with actionable authorization, worksheet, sharing and request messages; uncertain writes direct the operator back to preview.
- Strengthened exact-header, duplicate-ID, manual-row, terminal-status and partial-write recovery coverage; refuse a full read window before writes.
- Validated credential-free Greenhouse ingestion and repeat-run deduplication against a public board.
- Fixed entity-encoded Greenhouse descriptions and publication dates; skip explicit passed deadlines and reject malformed snapshots before ingestion.
- Added structured discovery errors for unavailable resources, blocked redirects, rate limits, transport and payload failures.
- Added synthetic HTTP replay integration tests and a default-skipped live check, with documented request/privacy limits.

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
