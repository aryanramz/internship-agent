# Threat model — v0.4

## Assets and trust zones

- **Private assets:** master profile (PII), resume/letters, database, OAuth tokens, recruiter messages and application status.
- **Untrusted data:** job descriptions, linked job URLs, XML/JSON/RSS feeds, Gmail alert text, external job records and browser page content.
- **Trusted runtime (initial MVP):** the user's local machine running the CLI. The MCP server is a *development interface*, not a secure internet endpoint.
- **External services:** ATS hosts, Gmail, Google Sheets, ChatGPT clients; each has independent authentication and terms.

## Attack scenarios and controls

| Risk | Current protection | Remaining risk / required action |
|---|---|---|
| Job posting prompt injection | Descriptions stored as data, not executed by the backend | ChatGPT orchestration must treat all retrieved text as untrusted; do not follow embedded instructions |
| Credential/PII leak via GitHub | Ignore private directories, use fictional examples, hygiene scanner in CI | Developer must review `git diff --cached` and use independent secret scanning |
| SSRF through feed URL | HTTPS-only/public-host validation; no IP-literal endpoints; automatic redirects refused | DNS rebinding isn't fully addressed; use network egress policy before internet hosting |
| OAuth overprivilege | Gmail read-only; separate Sheets grant; tokens stored locally | Sheets write scope is broad; use dedicated test account/sheet, rotate/revoke grants as necessary |
| Accidental application submission | No submission automation; state transition requires explicit approval and evidence | Confirmation evidence is operator-provided, not independently verified |
| Duplicate or incorrect Sheet changes | Agent IDs, dry-run, ownership checks, confirmation phrase, pre-write re-read | Google multi-request update isn't atomic; concurrent writes/timeouts require reconciliation |
| Public MCP exposure | Documentation warns against public tunneling | No production auth, per-user permissions, rate limits, or audited deployment; keep private |
| Source/platform terms | Public feeds and authorized imports only | Operator is responsible for source-specific restrictions and rate limits |

## Release checklist

- [ ] No `config/profile.json`, `config/sources.json`, `data/`, `.env`, personal files or generated documents staged
- [ ] No client secrets, OAuth tokens, personal spreadsheet IDs, email addresses or recruiter PII in documentation/tests
- [ ] `python scripts/check_repo_hygiene.py` passes
- [ ] `python -m pytest -q` passes without network access
- [ ] Any new network adapter uses verified public endpoints and bounded responses
- [ ] Any new write or communication integration is opt-in, idempotent when possible, and auditable
- [ ] No unauthenticated remote MCP exposure

## Production readiness blockers

Requires explicit authenticated access control, scoped user identities, secrets-management policy, HTTPS termination, request tracing with PII redaction, stronger SSRF/DNS protection, integration test environment, source rate-limit backoff, and secure user action confirmation. Do **not** claim the project meets production security standards today.
