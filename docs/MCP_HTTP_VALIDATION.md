# Local authenticated HTTP MCP proof of concept

Status checked 2026-10-28. The staged local proof of concept is authorized;
**no Funnel, external endpoint, Windows service or ChatGPT connection was configured.**
Issue #3 stays open until a real authenticated ChatGPT invocation succeeds.

## Implemented boundary

`internship_agent.mcp_http` reuses the existing three tools:
`application_summary`, `rank_jobs`, `preview_application`. Stdio remains available
through `internship_agent.mcp_server`. There are no discovery/import, approval,
submission, document generation, Google, arbitrary file or write tools.

The HTTP entry point binds only `127.0.0.1`; there is no `--host` switch. Its
resource identifier must be `http://127.0.0.1:PORT/mcp`. Public HTTPS resource
identifiers require the separate explicitly configured [Phase 3 gateway](MCP_EXTERNAL_CONNECTIVITY.md);
the original local CLI still refuses them. The only adapter routes are `/mcp`
and `/.well-known/oauth-protected-resource/mcp`. Metadata is public and contains
only the configured resource, issuer and scope. Every MCP request needs OAuth.
This is the SDK resource-server integration, not a home-made OAuth issuer.

Tokens must satisfy all of these checks:

- RS256 signature from a pinned public JWKS, with unique key IDs and RSA >=2048
  bits. Private JWKs, unknown signing keys, other token algorithms, critical/key-location
  headers and tokens longer than 16 KiB are refused. Provider encryption keys are
  ignored, never used for signatures. No token-supplied URL is fetched.
- Exact configured issuer and a single exact resource audience (string or
  singleton array), required integer expiration/issued-at and valid optional
  not-before time, with no expiration grace period.
- Exact owner `sub`, the registered client (`client_id` or Keycloak `azp`, both
  must agree if present), and the `internship:read` scope.
- An access-token type: RFC 9068 `at+jwt`, or Keycloak `JWT` with payload
  `typ=Bearer`. An ordinary ID token cannot substitute for an access token.

The SDK checks each HTTP request. A second verifier call immediately before
**every** `tools/call` checks the current request token again, including expiry;
session state or a prior successful request cannot authorize a later call.
The adapter is stateless and does not cache authorization decisions.

Exact Host/Origin checks cover metadata too. Forwarded headers do not override
them; Uvicorn proxy trust is disabled. Query parameters, duplicate authentication
headers, unlisted routes and request bodies above 64 KiB are refused. Access logs
are disabled so query strings do not enter them. Token verification errors return
generic challenges/errors without raw tokens, claims, filesystem paths or library
tracebacks. SQLite remains opened read-only; tests verify unchanged DB/profile bytes.

## Reproduce without credentials

Local verification: **184 passed, 3 skipped live tests, 22 subtests passed** in the
full suite. The HTTP/authentication file contributes 36 tests; seven repository
privacy tests cover ignored/force-added artifacts. Compilation, dependency checks
and patch whitespace checks passed. An independent review found no important
code/security findings and separately passed all 43 HTTP/privacy tests. This is
bounded local validation, not certification of an internet deployment.

```powershell
python -m pip install -e '.[test,google,mcp]'
python -m pytest -q tests/test_mcp_http.py tests/test_mcp_readonly.py
```

Tests generate ephemeral RSA keys in memory and use separate temporary fictional
databases/profiles. Real SDK Streamable HTTP clients exercise both modern and
legacy protocol modes through an in-process ASGI transport. No external network,
OpenAI account, Google grant, tunnel or personal application tracker is used.

For a separate local provider experiment, keep configuration in ignored
`config/mcp-auth.json` and public signing keys in ignored `config/mcp-jwks.json`:

```json
{
  "issuer": "http://127.0.0.1:8180/realms/synthetic",
  "resource": "http://127.0.0.1:8765/mcp",
  "owner_subject": "synthetic-owner-subject",
  "client_id": "synthetic-chatgpt-client",
  "jwks_path": "mcp-jwks.json"
}
```

These are illustrative identifiers, not credentials or a functional provider
configuration. Use the actual issuer/client/subject and **public** JWKS from the
isolated provider. Relative JWKS paths resolve against the configuration file.
Never put an access token, refresh token, client secret or private signing key
in this file or a committed fixture. No Google OAuth file is involved.

```powershell
python -m internship_agent.mcp_http --auth-config config/mcp-auth.json --data data/mcp-http-test --profile data/mcp-http-test/profile.json
```

The database must already exist and contain fictional records. A missing database
fails startup without creating it. A trusted local MCP client obtains its own
short-lived provider token; do not paste tokens into chat, issue comments, command
arguments or logs. This localhost URL cannot be reached by ChatGPT cloud.

## Recovery and limits

- A 401/403 means the token is absent, invalid, expired or lacks the configured
  identity/scope. Reauthorize locally; do not disable validation or broaden the
  audience/owner allowlist to make an error disappear.
- Unknown signing keys fail closed. Verify new public keys through the trusted
  provider, replace the pinned JWKS atomically and restart. There is no automatic
  network JWKS refresh. Keep existing keys only for the intended overlap period.
- Owner/client/issuer/resource changes require explicit local configuration and
  restart. A lost bearer token is usable until expiry; this JWT-only stage has no
  introspection/revocation lookup or sender-constrained tokens. Stop the service
  and remove/revoke trust if immediate isolation is needed.
- HTTP startup errors are deliberately generic. Check the local file locations
  and configuration without printing credential contents. Existing stdio and CLI
  workflows remain the fallback.
- Per-user OAuth sign-in, public HTTPS routing, Keycloak administration isolation
  at a future proxy, rate limiting, restart persistence and actual ChatGPT refresh
  behavior still need external-stage qualification. No development identity
  server, test password or local bootstrap configuration is suitable for exposure.

See [OAuth compatibility findings](MCP_OAUTH_COMPATIBILITY.md) and the
[connection architecture](MCP_CONNECTION_OPTIONS.md) before the next stage.
