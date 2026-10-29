# Threat model — local workflow baseline

Current versus planned controls are reconciled in [CAPABILITIES.md](CAPABILITIES.md)
against develop `3a79f555617453fc68dd51d36a9d1e51eabd2dcc`. Gateway/startup
work in [PR #8](https://github.com/aryanramz/internship-agent/pull/8) is unmerged;
it must not be counted as deployed protection or activated by this roadmap.

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
| Public MCP exposure | Stdio entry point unchanged; separate authenticated HTTP PoC fixes binding/resource/Host/Origin to loopback, pins public signing keys and validates owner/client/scope/expiry/audience per invocation; exact route allowlist; no tunnel | Future public proxy/OAuth route isolation, rate limits, persistence and actual authenticated ChatGPT calls remain unqualified. No external exposure is implemented |
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

The merged loopback HTTP adapter already validates pinned tokens and owner/client/
resource/scope per invocation. Production exposure still needs reviewed routing,
HTTPS qualification, operational identity/secret management, redacted observability,
stronger SSRF/DNS controls, source backoff and qualified user-action confirmation.
Do not claim production security readiness from local tests.

Planned dashboard mutations must enforce local session/Host/Origin/CSRF and
explicit confirmation; unattended runs cannot inherit permission to submit, send
mail or write Sheets. Browser/recruiter workflows must bind concrete approved
actions to verified facts and reconcile uncertain outcomes before retrying.
These are requirements for Issues #14–#18, not implemented controls. Optional AI
must not invent facts or upgrade untrusted content into authorization. Core local
operation remains independent of optional MCP/Google/identity infrastructure.

## ChatGPT cloud boundary — local qualification only

The selected [connection architecture](MCP_CONNECTION_OPTIONS.md) uses Personal
Funnel transport and local Keycloak, subject to staged qualification; the
[OAuth findings](MCP_OAUTH_COMPATIBILITY.md) record interoperability limits.
The [HTTP adapter](MCP_HTTP_VALIDATION.md)
is implemented only on loopback. Funnel is public reachability, not caller authorization. Future access
must validate issuer, audience, expiry, signature, read scope and the authorized
local user; admin routes must remain private. MCP credentials are separate from
Google OAuth tokens. ChatGPT receives necessary access/refresh credentials and
requested tool results, while local files remain on the PC. No unauthenticated
private-data endpoint, API billing, paid hosting or metered resource is authorized.
