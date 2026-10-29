# OAuth compatibility decision — staged proof of concept

Checked 2026-10-28. **Choose local Keycloak for the next qualification stage;
keep Tailscale Personal + Funnel as the preferred transport candidate.** This
does not authorize exposing a development server. No tunnel, public route,
hosting subscription, payment method or Platform API key was created.

## Registration and standards

Keycloak's [ChatGPT CIMD warning](https://www.keycloak.org/securing-apps/mcp-authz-server#chatgpt-integration)
says it cannot process the plural authentication-method field. The current
[OpenAI authentication guide](https://developers.openai.com/plugins/build/auth)
describes publishing both plural choices and a legacy singular preference. These
documents disagree; this work does not claim CIMD interoperability.

Use a **predefined OAuth client**, authorization code and enforced PKCE S256.
Pre-registration is allowed by the [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
and explicitly supported in [ChatGPT custom-server settings](https://developers.openai.com/api/docs/guides/custom-mcp-server).
This avoids CIMD parsing entirely. Supplying client credentials identifies the
client during code exchange; it does not mean using the client-credentials grant.
The local experiment exercised both a public client and a confidential client
using `client_secret_basic`, each with S256. An eventual connection must use the
exact callback shown by that ChatGPT connection, with no wildcard redirects.

Pre-registration alone does not implement audience/resource binding. Keycloak's
[MCP guide](https://www.keycloak.org/securing-apps/mcp-authz-server) labels resource
indicators experimental. Without that feature, a scope/audience mapper does not
validate the OAuth `resource` parameter. The selected local experiment enables
`resource-indicators`, registers the resource URL on a separate resource client,
and maps only that resource audience to the dedicated read client. This is a
standards-based flow with the tested checks below, not a claim of complete
OAuth/MCP conformance or actual ChatGPT compatibility.

## Real local provider experiments

Official distributions were downloaded and checked against their published
SHA256 values. Keycloak 26.8.1 used installed Java 25, an in-memory development
database, a newly generated realm, fictional user, generated random password and
ephemeral clients. HTTP and management listeners were bound to `127.0.0.1` only.
Pocket ID 2.19.1 used its native Windows binary, separate SQLite database and an
isolated first-user bootstrap session. Its HTTP and internal actor listener were
also bound to loopback. Both provider processes were stopped after testing.

| Observed check | Keycloak 26.8.1 | Pocket ID 2.19.1 |
|---|---|---|
| Predefined client, code + S256, state round-trip, signed JWT verified against provider JWKS | Passed | Passed |
| Wrong PKCE verifier | `400 invalid_grant` | `400 invalid_grant` |
| Attempt to downgrade to plain PKCE | Rejected; no code | Not tested |
| Different registered resource in code exchange | `400 invalid_target` | **200; request resource ignored, original audience retained** |
| Correct online refresh | 200; refresh token rotated | 200; refresh token rotated |
| Different resource in refresh | `400 invalid_target` | **200; request resource ignored, original audience retained** |
| Static confidential client with Basic authentication + S256 | Passed | Not tested |
| Request excluded `offline_access` scope | `invalid_scope`; no code | Not tested |

An unknown Keycloak authorization resource could produce a code, but its exchange
was rejected with `invalid_target`; no access token was issued. Do not describe
this as rejection at the authorization endpoint.

Keycloak's final successful grant requested `openid email profile internship:read`.
Its access token had exactly the MCP URL as `aud`, a user `sub`, the configured
client in `azp`, RS256 signature, JOSE `typ=JWT` and payload `typ=Bearer`. The actual
provider token/JWKS were then accepted by the real HTTP adapter for discovery and
**all three tools**, using fictional records and an in-process HTTP client.
Database/profile bytes remained unchanged. No token or signing key is included in
this document or a committed fixture.

The experiment caught two compatibility details:

- Keycloak publishes both signing and encryption keys. The adapter loads only
  pinned public RS256 verification keys and ignores encryption keys; a token
  naming an encryption key is rejected. A regression test covers this behavior.
- A custom realm import that replaces scope definitions must actually define
  the `basic` subject mapper, not just reference a missing scope. The experiment
  added `oidc-sub-mapper` and real email/profile mappers, then verified `sub` in
  the resulting access token. The owner check must never be weakened to accept
  a missing subject.

These were developer-run provider experiments, separate from the offline CI
suite. Pocket ID's bootstrap session does **not** prove passkey sign-in, and
neither provider experiment proves ChatGPT sign-in, refresh behavior or HTTPS
routing. Windows startup persistence was not configured.

## Why Keycloak remains conditional

The [offline-refresh audience bug](https://github.com/keycloak/keycloak/issues/53261)
and [proposed fix](https://github.com/keycloak/keycloak/pull/53642) were still open
when checked. This experiment excluded `offline_access` from client scopes and
confirmed a request for it fails. Only ordinary online refresh was qualified.
If ChatGPT requires offline access, stop and resolve that incompatibility; do not
enable the affected flow or relax audience validation. Online sessions can expire
and require the user to sign in again.

The next local configuration must retain:

- A dedicated realm, owner subject and exact registered client; code flow only,
  enforced S256, no implicit/password/service-account grant or open registration.
- The explicit MCP resource client (`resource_url`), one audience mapper and the
  `internship:read` scope. No account-management or additional resource audiences.
- Working subject/OIDC scopes, excluded offline access, short access-token
  lifetime and refresh rotation. Store any confidential-client secret locally
  and enter it only through the user's ChatGPT OAuth configuration.
- A persistent production-mode local provider setup before external testing.
  The in-memory development realm and generated test user are disposable proof
  fixtures, not an internet deployment template.

## Simpler alternative and cost decision

[Pocket ID](https://pocket-id.org/docs/guides/apis) is a materially simpler open-source
option: one native Windows executable with SQLite and passkey-oriented login.
Its default filesystem backend failed image bootstrap on this Windows runtime;
the documented database file backend allowed the experiment to continue. More
decisively, the observed token/refresh resource mismatch behavior fails this
project's strict request-binding gate. Its `openid` grant also added the UserInfo
issuer to `aud`, which the current single-resource verifier intentionally refuses.
It is not selected despite its smaller operational footprint. This observation
does not claim it issued a token for the attacker's requested audience.

Both candidates can run entirely on the existing PC without a paid identity
service. Keycloak adds Java, local storage and maintenance; no hosted database
is required for this experiment. The preferred transport's existing
[Personal pricing and no-billing-details evidence](MCP_CONNECTION_OPTIONS.md#costs-accounts-and-persistence)
still applies, subject to personal-use terms and later rechecking. No Secure MCP
Tunnel free-price assumption, paid domain, API credits or paid hosting is used.

## Exposure gate

Local [adapter/authentication checks](MCP_HTTP_VALIDATION.md) pass. There is still
no external reverse proxy or service configuration. Before enabling Funnel, a
separate reviewed routing stage must qualify exact public HTTPS issuer/resource
URLs, callback and discovery, OAuth login/assets/token paths, and denial of
Keycloak admin/master realm, management, filesystem, database, Google credentials
and every write-capable tool. Never forward the whole Keycloak port or a folder.

Then prove one authenticated call from the operator's actual Plus custom plugin
using synthetic data, followed by token refresh/rejection and restart checks.
Until that succeeds, **Issue #3 remains open** and local stdio is the fallback.
