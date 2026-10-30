# Live ATS discovery validation (Issues #1 and #9)

## Three-provider qualification — 2026-10-29

Credential-free production readers were exercised against one public board each,
using isolated local ledgers and fictional preparation/approval references. No
personal profile, Google grant, application submission or private employer API was
used. Official contracts checked: [Greenhouse](https://docs.greenhouse.io/job-board.html),
[Lever public Postings API](https://github.com/lever/postings-api), and
[Ashby public job board API](https://developers.ashbyhq.com/docs/public-job-posting-api).

| Provider / board | Fixed GET endpoint | HTTP | Jobs / bytes per response | Descriptions / publication fields | Repeat |
|---|---|---|---|---|---|
| Greenhouse / greenhouse | `https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs?content=true` | 200 | 18 / 220,280 | 18 / 18 `first_published` | 0 added, 18 updated |
| Lever / palantir | `https://api.lever.co/v0/postings/palantir?mode=json` | 200 | 302 / 5,931,609 | 302 / 0 publication timestamps | 0 added, 302 updated |
| Ashby / Ashby | `https://api.ashbyhq.com/posting-api/job-board/Ashby?includeCompensation=true` | 200 | 71 / 2,303,443 | 71 / 71 `publishedAt` | 0 added, 71 updated |

The two qualification requests ran at 19:13:13/15 UTC (Greenhouse), 19:13:16/23
UTC (Lever) and 19:13:31/33 UTC (Ashby). All retained stable job IDs, exactly one
application row per posting, prepared and approved states, approval timestamps and
all historical events. The explicit live test result was **3 passed in 21.29s**.
These counts are observed snapshots, not internship-only totals or completeness
claims. The other 15 configured source types are not live-qualified by this work.

One initial shape probe and two final qualification GETs per provider produced
nine successful API responses in total. Initial restricted-local attempts returned
network errors with no HTTP status and were not counted as success; authorized
network execution then used the fixed endpoints. There were no automatic retries,
detail requests, redirects followed or broad employer searches. Each request had
a 20-second timeout and 16 MB response cap; repeat requests were serial with at
least one second between them. No additional live reruns were performed.

### Demonstrated corrections and date semantics

- Lever's published responses include description sections and closing content.
  The old reader dropped closing text and section headings; both are now retained
  with plain-text/HTML fallbacks. `createdAt` was present on all 302 records, but
  the public field contract does not define a publication date. It is deliberately
  not relabeled as publication; normalized publication remains unknown.
- Lever/Ashby malformed array/item/field/URL data now raises safe structured errors
  before any part of that snapshot is ingested. Valid empty snapshots remain valid.
- Ashby `publishedAt` means **last published**, not guaranteed original creation.
  The existing explicit-ID/URL-fallback identity, unlisted filtering and workplace
  type precedence are preserved. Dates, when supplied, must be timezone-aware.
- Linked job/application URLs are validated as public HTTPS syntactically and are
  never fetched by normalization. Private/IP/intranet/malformed hosts, credentials
  and nonstandard ports are rejected. This does not prove destination availability
  or solve DNS rebinding for future browser/network use.
- HTTP 404/410/429, Retry-After seconds/dates, malformed JSON, timeouts, transport
  failures and redirect refusal have fictional real-urllib replay coverage for
  all three providers. Retry-After is reported and never automatically retried;
  persistent backoff/health/lifecycle are outside this issue.

The [employer registry](EMPLOYER_REGISTRY.md) extends existing source JSON without
changing posting IDs/SQLite history. Registration and inspection never fetch URLs;
validation metadata remains unverified until an operator records actual evidence.

## Initial Greenhouse qualification — 2026-10-28

## Scope and observation

On 2026-10-28, a credential-free GET to
`https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs?content=true`
returned HTTP 200 with 18 postings in a `jobs` / `meta` object. All 18 descriptions
used entity-encoded HTML. The old reader retained HTML tags after normalization
and discarded publication dates. The reader now decodes the HTML before stripping
tags and maps `first_published` to `published_at`. It does **not** use `updated_at`
as a publication date. Missing optional dates remain unknown.

Public GETs for the nonexistent board `internship-agent-invalid-board-000` and
posting `greenhouse/jobs/0` returned HTTP 404. These establish missing-resource
behavior, not the historical expiry of any real posting. The opt-in ingestion
test validates the production HTTP reader, normalization, Agent orchestration and
temporary SQLite ledger across two requests. Counts may change as jobs change.

The [Greenhouse Job Board API documentation](https://docs.greenhouse.io/job-board.html)
defines the list endpoint and confirms public GET access without authentication.
That initial check validated one reader. Lever and Ashby were subsequently
qualified on 2026-10-29 as recorded above; other readers and Google integrations
require their own separate qualification.

## Network and rate-limit policy

- Only the fixed public Greenhouse API endpoint is requested. No credentials,
  browser scraping, application submission or job/apply URL fetching is involved.
- Each request has a 20-second socket timeout and a 16,000,000-byte response cap.
  All redirects, including same-host redirects, are refused.
- Discovery is serial. No automatic retries occur. The live check makes two GETs
  at least one second apart and stops if the first fails. Normal tests make zero
  network requests. Do not run parallel live checks.
- For routine discovery, poll a board at most once per 30 minutes; the two-request
  live qualification is a deliberate one-time repeat-ingestion check. These are
  conservative project limits, not a claimed provider quota. Observe any stricter
  provider policy. Do not repeatedly rerun a failed live test.
- HTTP 429 is reported with `code: rate_limited` and a validated `retry_after`
  when supplied (seconds or an ISO timestamp converted from HTTP-date). Wait at
  least that long before another manual run; if absent, wait at least 30 minutes.
  Fix configuration errors before retrying 404s or redirects.

## Error and availability semantics

Discovery retains its existing `errors[].board` and `errors[].error` fields and
adds `code`, optional `http_status`, and optional `retry_after` for source errors.
Response bodies, redirect targets and low-level network diagnostics are not
included. One board's failure does not prevent later boards from running.

| Condition | Behavior |
|---|---|
| HTTP 404 | `not_found`: board/posting absent; check configuration |
| HTTP 410 | `gone`: resource no longer available |
| HTTP 3xx | `redirect_blocked`: refuse redirect, review configured endpoint |
| HTTP 429 | `rate_limited`: no retry; expose safe Retry-After |
| Other HTTP failure | `http_error` with status |
| Connection failure / timeout | `network_error` |
| Oversized response | `response_too_large` |
| Non-JSON / missing or malformed jobs array | `invalid_payload`; never an empty success |
| Invalid Greenhouse ID, title, URL, content or deadline | `invalid_posting`; reject board before any job writes |
| Passed timezone-aware `application_deadline` | Skip that posting during ingestion |
| Empty valid jobs array | Successful empty snapshot |

An invalid posting rejects its entire snapshot so no partial snapshot is ingested.
Postings with no deadline have **unknown** expiry. Missing/expired postings and
board errors do not delete historical jobs or alter application state. Listing
availability is only a snapshot; it does not verify the destination application
page or guarantee that a job remains open. No new closed-job state is inferred.

Stable IDs remain based on provider, board token and posting ID. Repeat ingestion
updates the same rows (`updated`, rather than `duplicate`, is the existing counter
for identical IDs), with no additional application or discovery-event rows.
Different requisitions with identical titles stay separate.

## Reproduce

Install the existing test extra, then run the default offline suite:

```powershell
python -m pytest -q
```

Explicitly authorize public API requests for the three live checks (two serial
GETs per provider; six requests total):

```powershell
$env:RUN_LIVE_ATS = '1'
python -m pytest -q -s -m live tests/test_ats_live.py
Remove-Item Env:RUN_LIVE_ATS
```

On macOS/Linux use `RUN_LIVE_ATS=1 python -m pytest -q -s -m live tests/test_ats_live.py`.
The checks use only temporary configuration/database files, no personal profile,
and print sanitized counts/timing metadata only. Once enabled, network failures and empty boards fail the
test instead of silently skipping. A board change between its two snapshots can
also fail the repeat-count assertion; inspect the change before rerunning.

Recorded opt-in result on 2026-10-28: **1 passed**. First discovery added 18
postings with zero errors; repeat discovery added 0 and updated 18, retaining
18 application rows. No raw response content or database is committed.

The fixture provenance is in [tests/fixtures/README.md](../tests/fixtures/README.md).
Only fictional response fixtures are committed; no raw live payload is retained.
