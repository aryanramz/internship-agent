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
| OAuth overprivilege / storage | Gmail read-only; separate Sheets grant; shared per-user credential store, atomic private-file writes, explicit account overrides | Sheets scope is broad; JSON is not vault-encrypted. Windows relies on user-profile ACLs, POSIX on 0700/0600; protect override directories and revoke unneeded grants |
| Accidental application submission | No submission automation; state transition requires explicit approval and evidence | Confirmation evidence is operator-provided, not independently verified |
| Duplicate or incorrect Sheet changes | Agent IDs, dry-run, ownership checks, confirmation phrase, pre-write re-read | Google multi-request update isn't atomic; concurrent writes/timeouts require reconciliation |
| Public MCP exposure | Strict JWT checks retained; loopback-bound gateway pins HTTPS Host/Origin and public resource, exact OAuth/login/asset paths, client/callback/S256/resource/scope; strips forwarded identity, sanitizes errors and bounds requests; no tunnel | Actual Funnel TLS/header behavior, ChatGPT linking/refresh and native Windows task recovery remain live gates. No public route is active |
| Provider/admin/DB access through proxy | One fixed loopback upstream/realm, no generic proxy or folder mount, no admin/master/account/management routes; Keycloak local cache avoids LAN cluster listeners; PostgreSQL restricted to loopback | Trusted local configuration and OS account/ACLs remain required; provider security updates and backups are operator responsibilities |
| MCP mutation or file exfiltration | Exactly three read-only tools; existing SQLite opened `mode=ro` / `query_only`; no Google, approval, submission, generation or arbitrary file tools | Local process/host must be trusted. Selected results are shared with the client, and job text remains untrusted |
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

## ChatGPT cloud boundary — local qualification only

The [connection architecture](MCP_CONNECTION_OPTIONS.md) conditionally selects
Personal Funnel transport; [local OAuth findings](MCP_OAUTH_COMPATIBILITY.md)
determine whether Keycloak can be the issuer. The [HTTP adapter](MCP_HTTP_VALIDATION.md)
and [narrow HTTPS gateway](MCP_EXTERNAL_CONNECTIVITY.md) remain bound to loopback;
Funnel is disabled. Funnel is public reachability, not caller authorization. Any future access
must validate issuer, audience, expiry, signature, read scope and the authorized
local user; admin routes must remain private. MCP credentials are separate from
Google OAuth tokens. ChatGPT receives necessary access/refresh credentials and
requested tool results, while local files remain on the PC. No unauthenticated
private-data endpoint, API billing, paid hosting or metered resource is authorized.
