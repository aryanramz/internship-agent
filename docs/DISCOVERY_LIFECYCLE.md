# Incremental discovery, source health and posting evidence

Issue #10 builds on PR #22's registry and three-provider qualification. The local
CLI/SQLite workflow requires no ChatGPT, Google grant, model API or paid service.
No scheduler, dashboard, external endpoint or additional MCP tool is introduced.

## Run and inspect

```powershell
internship-agent discover --max-pages 3 --max-sources 20
internship-agent source-health --limit 100
internship-agent scans --limit 100
internship-agent availability --job-id <local-job-id>
```

`discover` retains its added/updated/duplicate/errors/by_source counters and adds
skipped reasons, source/run IDs and page completeness. Reports open the existing
database read-only and require no profile or network. A legacy database with no
discovery tables yields empty scan/health reports and unknown availability until
an explicit writable operation initializes the additive schema.

Routine scans respect durable retry times. `discover --refresh` explicitly bypasses
only a healthy source's 30-minute cooldown, for a deliberate qualification check.
It cannot bypass failed/degraded/rate-limited sources or an active worker lease.
The daily script remains a manually invoked script; unattended scheduling is #15.

## Checkpoints, transactions and recovery

Each source has an opaque identifier derived from its reader namespace and filters
(including import location, internship filter, Workday search terms and USAJOBS
keyword). Display names, validation notes and careers URLs do not change it.
Filter changes start a separate source history; they cannot reuse an incompatible
pagination checkpoint. No credentials, raw responses or configuration blobs enter
scan diagnostics. Provider/error categories, counts, timestamps and numeric cursors
are retained locally.

An attempt obtains a five-minute source lease under `BEGIN IMMEDIATE`. Job upserts,
new application/discovered-event creation, provenance, availability evidence and
the next cursor commit in **one transaction per page**. An exception rolls all of
that page back; previously committed pages remain durable. Concurrent invocations
skip a busy source. Every resumed attempt receives a new fencing run ID, while a
resumable snapshot retains its logical run ID. Old workers cannot commit or fail
the replacement attempt. Expired leases record an interrupted attempt.

After interruption, rerun the same `discover` command. A busy result means wait
until the reported lease expiry; do not edit the database or delete scan rows.
Partial pagination resumes after its retry time. A changed provider total or
invalid cursor discards that checkpoint after backoff and starts a fresh logical
snapshot; prior committed jobs/history remain intact. No cached payload is needed.

SmartRecruiters supports one fixed-endpoint GET per page using numeric offset and
total, with at most 100 records/page and a safety ceiling of 1,000,000 postings.
Defaults permit three pages/source and 20 eligible sources/invocation; CLI limits
are 1–5 and 1–100 respectively. Its documented
[public Posting API](https://developers.smartrecruiters.com/docs/endpoints) and
[paging contract](https://developers.smartrecruiters.com/docs/customer-overview)
define offset/limit/totalFound. Total/echoed-offset/count inconsistencies fail
safely. Equal-total reordering cannot be detected without provider revision tokens;
pagination is never authoritative absence evidence. Existing bounded readers
retain their transport limits; Workday may make its existing bounded searches.

## Health and retry rules

| Result | Health / retry |
|---|---|
| Complete validated scan | healthy or healthy_empty; 30 minutes |
| Accepted pages with a remaining cursor | degraded; resume after 60 seconds |
| Successful limited reader without a cursor | degraded; rescan after 30 minutes |
| First-page failure | failed; 60 seconds, doubling per consecutive failure to one day |
| Failure after committed pages | partial/degraded; same failure backoff, retain valid cursor |
| HTTP 429 | rate_limited; at least 30 minutes and exponential backoff |
| Valid Retry-After | Later of local backoff and server restriction, including seconds, HTTP date and transport-normalized ISO date |

No automatic request retries or sleeps occur. Healthy refresh never overrides
backoff; one source failure does not stop other eligible sources. Reports expose
last attempt/success, counters, categorized failures, next retry, lease activity,
retry eligibility and seven-day freshness. Counts describe committed validated
pages; a malformed failed response has unknown rejected-record count, not a
measured empty response. Interrupted/partial/failed attempts retain their audit.

## Availability evidence is separate from application outcomes

- A validated positive observation records available. After a confirmed closure,
  a subsequent authoritative positive observation records reopened.
- Only complete **unfiltered** Greenhouse/Lever/Ashby snapshots can record absence.
  Absence changes a previously observed posting to unknown, never closed. Repeated
  absences still cannot prove closure. Unlisted Ashby records are not closures.
- The only automatic confirmed-closure policy is an explicit valid timezone-aware
  Greenhouse `application_deadline` at or before observation time, for a posting
  already observed at that same source. Evidence retains the deadline and run ID.
  No other provider has a confirmed-closure rule. A 404/410 board failure is not
  proof that its individual postings closed.
- Timeouts, 429/5xx, malformed responses, partial pagination, disabled sources and
  import omissions never produce closure. Staleness is a separate seven-day flag.
- Positive evidence from another source outranks source-specific absence/closure.
  Reports show individual evidence so conflicts remain inspectable.
- Availability never modifies application statuses, approvals, submission evidence
  or application events. Prepared, approved and submitted records remain intact.

## Identity, provenance and suggestions

Existing provider/token/requisition IDs remain unchanged. Re-observation updates
that identity, retaining original discovery time, approval and application history.
Distinct incoming IDs are now retained even when they share a title or canonical
URL. Earlier URL-based destructive merging is replaced with review-only
`canonical_matches` in availability reports; tracking parameters are excluded by
the existing canonical URL rules. Matches are candidates, not proof of equality;
no cross-source grouping or application history is moved automatically. No old
historical merge can be reconstructed without further source evidence.

Provenance associates a job with its source, safe canonical URL and observation
times. Credential-bearing URLs are omitted from evidence. Suggestions inspect at
most 1,000 recent already-ingested records and show at most 500 known-board
candidates. Unknown sites are not crawled; preview never registers or fetches.
Only explicit `suggest-sources --apply` or `add-source` registers a board, as
documented in [the registry guide](EMPLOYER_REGISTRY.md).

## Schema compatibility and rollback

Writable Store initialization migrates `PRAGMA user_version` 0 to 1 with additive
source, run, transition, job-source and availability-evidence tables/indexes in a
transactional savepoint. Existing jobs/applications/events are not rewritten.
Repeated initialization is idempotent; migration failure rolls back the new
tables and version. Future schema versions are rejected before baseline DDL.
Read-only MCP and report access never migrates or creates a database.

Before upgrading an operational database, stop writers and make a private backup
with SQLite's backup API (or copy only while all database processes are stopped).
Keep backups under ignored private storage. Roll back by stopping writers and
restoring that backup; never delete individual history/checkpoint tables or claim
that an older executable understands new state. New discovery reports are read-only.

## Qualification and remaining limits

Offline regressions use fictional records, isolated databases, fake clocks,
synthetic provider pages and loopback tests. A test guard blocks external DNS and
connections unless an explicitly opted-in live test runs. Regression coverage
includes migrations/rollback, page/restart/fencing, Retry-After, false-closure
prevention, reopening and prepared/approved/submitted history.

Local qualification on 2026-10-29 (Windows, Python 3.12): **580 passed, 5 skipped,
22 subtests passed in 105.10 seconds**. Skips are the three opt-in ATS checks,
the opt-in Sheets write check and a POSIX-only permissions check. A real synthetic
subprocess terminated during a page transaction; restart recovered zero partial
job/application/event writes and fenced the abandoned attempt. Compilation,
dependency consistency/advisory audit, offline demo, 103-file privacy check and
124 relative documentation references passed. Final immutable review and PR/
post-merge Python 3.11–3.13 CI evidence are recorded on the associated PR/Issue #10.

[PR #22's live qualification](LIVE_ATS_VALIDATION.md) remains dated evidence for
one Greenhouse, Lever and Ashby board each; Issue #10 does not repeat those live
requests or newly qualify SmartRecruiters/other providers. The other bounded
remote readers are conservatively partial. DNS rebinding/private DNS resolution
for explicitly configured RSS remains the documented
[network limitation](THREAT_MODEL.md); this change introduces no new URL fetch path.
SQLite transactions/leases coordinate local writers, not distributed scheduling.
Observations/diagnostic history have no automatic retention purge yet.

R1's #9/#10 engineering evidence is distinct from publication: version alignment,
clean-package qualification, release review/tagging and promotion remain the
[release preparation procedure](RELEASE_PLAN.md). No release or version bump is
created by this implementation.
