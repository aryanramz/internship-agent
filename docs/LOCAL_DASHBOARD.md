# Private local dashboard

Issue #16 adds a local browser interface over the existing Python/SQLite ledger.
No ChatGPT, Google, MCP, Node build, model account or paid infrastructure is needed.
Nothing submits applications, sends email or verifies an employer receipt.

## Launch and stop

Install the project into the checkout's virtual environment using the existing
Windows setup or `python -m pip install -e .`. Keep your profile and reviewed source
configuration in the ignored `config/profile.json` and `config/sources.json` files.

```
python -m internship_agent.dashboard --root /absolute/path/to/checkout
```

Or use `internship-dashboard --root /absolute/path/to/checkout`. Windows users may
double-click `scripts/windows/dashboard/Start.cmd`. Keep that terminal private;
open the printed `http://127.0.0.1:8765` address and paste the access secret into
the unlock form. The secret never goes into a URL. Use `--port 8766` if occupied.
The server binds IPv4 127.0.0.1 only; localhost aliases, IPv6, public interfaces,
reverse proxies, tunnels and remote deployment are unsupported.

Press Ctrl+C in the launching terminal to stop. Restart creates a new secret and
invalidates every old session. No service, native task or startup entry is installed.
One-hour sessions use HttpOnly/SameSite=Strict cookies. Plain HTTP loopback cannot
provide a portable Secure-cookie guarantee; this is not production authentication.
Same-account terminal/filesystem access and installed local software are trusted.
Other users must not receive the terminal secret. Do not share screenshots of it.

## UX map

Unlock → Overview (defined counts, unknowns and recovery warnings) → Opportunities
(search, filters and pages) → Job detail (fit, separate eligibility and source
provenance) → Prepare (explicit variant/track) → Review (selectable document text,
QA gaps and exact packet identities) → Explicit local approval → Operator-reported
submission/outcomes. Operations shows discovery, scheduler and integration limits.
Nothing runs on page load beyond read-only local projections.

Review every draft and original posting. Extracted paragraph text is not rendered
Word visual QA. Downloads are restricted to the current managed application's
resume, letter and answer DOCX files after integrity/token checks. No profile,
raw claims JSON, database, journal or arbitrary path downloads exist. Files stay
private. A changed profile/job/packet invalidates review; prepare/review again.

All mutations require an authenticated session, fresh per-session CSRF token and
explicit confirmation. Tokens rotate after each authenticated POST, including a
refused action, so replay is refused. Approval/submission reuse existing workflow
transactions and exact revision tokens. Outcome status updates additionally check
the current binding. Operator evidence remains unverified. Discovery is explicit
and uses only configured permitted sources; Google credentials are not consulted
for authorization and integrations are not activated.

Storage busy/read-only/corrupt, missing profile and stale packet errors are shown
without raw exceptions or paths. Stop competing writers, inspect CLI `application`,
`source-health` and `scans`, back up private data, and use explicit recovery. Recovery
never grants approval. The dashboard keeps no second database and does not change
MCP tools or existing migrations. A browser timeout is not proof an action failed:
inspect current state before retrying; workflow idempotency remains authoritative.

## HTTP contract and privacy

Only packaged HTML/CSS/JS assets are served. Authenticated GET routes are
`/api/session`, `/api/overview`, `/api/jobs`, `/api/job`, `/api/review`, and
`/api/operations`. Writes use JSON POST `/api/action`; current-packet downloads use
JSON POST `/api/document`; unlock/logout use POST `/login` and `/logout`.
Requests are limited to 16 KiB, query fields/rows/documents are bounded. Host must
match the exact numeric loopback address and selected port. Foreign Origin,
Referer and browser fetch-site values are refused, with mandatory Origin and CSRF
on mutations. No CORS, request logging, root static server or tokens in URLs.
CSP, no-store, nosniff, no-referrer and frame denial apply. Posting text is rendered
as text; links permit only public HTTP(S) schemes and use noopener/noreferrer.
These controls do not turn localhost into a multiuser or public hosting service.

## Qualification

See the PR for exact immutable head/base, Linux/Windows CI counts, independent
review findings and browser evidence. All fixtures/screenshots use fictional data.
Browser smoke blocks all requests beyond loopback and includes actual keyboard
Tab/Enter navigation, list/detail/prepare/review, responsive checks and screenshots.
Windows CI exercises native localhost process launch/stop, Unicode paths and the
full offline suite with UTF-8 mode disabled. A Windows desktop browser, screen
reader, rendered Word documents and installed scheduler lifecycle require their
own manual qualification. Issue #15's native lifecycle and R4 acceptance remain
open. No Issue #17 work or external integration activation is included.

If a completed application's bound profile or packet changes, the dashboard refuses
further token-bound outcome changes. It cannot regenerate a submitted application.
Preserve the original private inputs; inspect CLI history/recovery rather than
assuming a fresh approval can repair that record. The existing CLI remains an
independent operator interface with its documented status-transition contracts.

For browser development, install `.[test,browser]`, run
`python -m playwright install chromium`, then
`python -m pytest tests/test_dashboard_browser.py -v`. Optional
`IA_BROWSER_EXECUTABLE` selects an existing Chromium executable;
`IA_DASHBOARD_SCREENSHOTS` selects the synthetic screenshot output directory.
The dedicated Linux browser CI job uploads screenshots without session secrets.
Public-DNS-shaped links are checked syntactically without network resolution;
DNS rebinding at an external posting destination remains outside this local UI.
