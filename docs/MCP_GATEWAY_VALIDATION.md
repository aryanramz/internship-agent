# Phase 3 qualification evidence

Verified locally on 2026-10-28 using **Keycloak 26.8.1**, **PostgreSQL 17.11**,
Python 3.12, the actual gateway CLI and fictional application records. Official
provider distributions were checked against publisher SHA256 values. PostgreSQL
was unpacked into an isolated test directory; no service, firewall or account
configuration was installed. Every password/client secret was generated locally
for the fictional fixture and remains unpublished.

The final developer-run integration harness exited zero with **30 recorded
outcomes and no failures**. These are real local provider/proxy checks, separate
from the offline automated suite. Requests used a fictional public HTTPS Host
while connecting to loopback; they did **not** exercise actual TLS, public DNS,
Funnel, ChatGPT, a real profile or Google authorization.

| Actual runtime check | Result |
|---|---|
| Production-mode provider against persistent PostgreSQL; HTTP/management/DB loopback | Passed |
| Fixed HTTPS issuer/discovery, code + PKCE S256, predefined confidential Basic client | Passed |
| Exact callback issuer/state, signed token with single resource audience, owner/client | Passed |
| Six real Keycloak login assets through the narrow gateway | 6 × 200 |
| UserInfo with matching subject and verified fictional email | 200 |
| Plain-PKCE downgrade | Provider rejected; gateway rejected before forwarding |
| Wrong PKCE verifier | 400 `invalid_grant` |
| Online refresh rotation; exact audience retained | Passed |
| Three tool descriptors and all three read-only invocations | 200 |
| Missing and invalid MCP tokens | 401 |
| Admin/master/account/filesystem/credential/admin-asset/introspection routes | 7 × 404 |
| Gateway process restart with existing token | 200; same identity/configuration |
| Provider forced restart using the same PostgreSQL database | Signing keys and owner retained; refresh 200; refreshed token accepted by MCP |
| Cleanup | Zero remaining fixture processes or test-port listeners |

Earlier fixture attempts caught Keycloak's default clustered cache creating
additional LAN listeners. Those processes were stopped. The corrected qualified
run used **local cache**, and its captured listeners were exclusively loopback.
The Windows runner now forces `--cache=local` and both loopback binding arguments;
the documented provider configuration also requires local cache. HTTP binding
alone is not a sufficient network-isolation control.

## Automated checks and review

The offline gateway suite covers canonical public identity, three OAuth tool
descriptors, read-only results/unchanged database and profile, fixed client/resource/
callback/S256, disallowed scopes/grants, token rejection, duplicate headers/fields,
malformed encoding/forms, unlisted routes, proxy header replacement, sanitized
provider failures, cookie/redirect handling, isolation between separate browsers
(including a provider cookie without `Secure`), metadata mismatch startup failure,
gateway restart, and hidden Windows startup.

Windows lifecycle tests cover current-user limited task XML, exact action/owner
verification, safe paths, operation ordering, production/local provider guards and
real read-only PowerShell Preview including Unicode paths. They do not register
tasks. Native logon, hidden-window behavior, scheduler failure recovery and process
tree termination remain separate Windows qualification steps.

The existing stdio tests preserve both protocol modes. A Windows cold SDK import
was measured at 22 seconds and produced a valid legacy response in 28 seconds;
their startup budget is now bounded at 60 seconds on Windows. Two earlier full
runs still exceeded this allowance; an isolated protocol run and a subsequent
full run passed. No deterministic protocol regression or buffering failure was
reproduced, and the cause of those earlier long delays remains unconfirmed.
Other platforms retain a short budget; these are not performance assertions.

The staged implementation received a completed Codex Security diff review with
no confirmed vulnerabilities. A follow-up defense-in-depth change disables the
shared proxy client's cookie storage; its two-browser regression failed before
the policy and passed after it. That small follow-up is reviewed separately from
the sealed snapshot. Passing local checks do not replace the live activation gates.

PyPA dependency auditing found no known advisories after updating the isolated
environment's old pip tooling. CI audits a complete pinned public dependency
inventory; the editable application is reviewed as source. This advisory check
does not establish absence of unknown vulnerabilities or supply-chain compromise.
Full regression and review results are recorded with the PR and its CI checks.
The final Windows Python 3.12 regression run on 2026-10-29 passed **279 tests and
22 subtests**, with three optional live tests skipped. Compilation, dependency
consistency, staged whitespace and the 88-file repository privacy check passed.

## Reproduce offline checks

```powershell
python -m pip install --upgrade pip
python -m pip install -e '.[test,google,mcp,security]'
python -m pytest -q
python -m compileall -q src scripts/windows
python scripts/check_repo_hygiene.py
python -m pip check
```

CI exports `pip list --format=freeze --exclude internship-agent` and audits that
complete pinned inventory with `pip_audit --strict --disable-pip --no-deps`.
Do not export private package-index URLs, credentials or a personal environment.
Keep any provider reproduction fixture under an ignored private directory; do
not commit its users, signing secrets, database or access/refresh tokens.

## Controlled live connection decision

The implementation has a working local route/authentication and persistent-provider
proof. Activation still requires review, verified private production configuration,
the actual callback/client fields from the operator's Plus account, pinned keys,
and local startup qualification. Only then may a separately authorized controlled
Funnel test check real HTTPS/Host behavior and an authenticated ChatGPT call with
fictional data. **No tunnel or paid resource was activated. Issue #3 remains open.**

See [gateway setup and boundaries](MCP_EXTERNAL_CONNECTIVITY.md),
[Windows controls](MCP_WINDOWS_STARTUP.md), and [OAuth limitations](MCP_OAUTH_COMPATIBILITY.md).
