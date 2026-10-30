# Discovery lifecycle implementation plan

> **For agentic workers:** Use superpowers:executing-plans or subagent-driven-development; implement tests before behavior.

**Goal:** Complete Issue #10 with durable, bounded recovery and truthful source/availability evidence.

**Architecture:** Extend the existing SQLite ledger additively, with atomic page ingestion and checkpoints. Keep source retrieval contracts separate from persistence and CLI orchestration. Application outcomes, approval and events remain independent of availability.

**Tech stack:** Existing Python 3.11+, sqlite3, urllib and pytest; no new dependencies.

**Spec:** User Work Session 4 and GitHub Issue #10; operational design in `docs/DISCOVERY_LIFECYCLE.md`.

## Constraints and decisions

- Base `85f2def736f82d7265bcecda5e00c8bc5220c5d6`; feature branch targets develop only. User authorizes merge after all acceptance/review/CI gates.
- Synthetic isolated databases only; no paid services, external activation, Google mutations, scheduler, eligibility/scoring/document changes or new MCP tools.
- Preserve IDs and existing application rows/events. Distinct incoming IDs must not be discarded merely for sharing a URL; canonical URL matches become reviewable candidates rather than destructive merges. Existing historical merged rows cannot be reconstructed without source evidence.
- Successful scans wait 30 minutes; explicit refresh bypasses only this healthy cooldown, never failures, rate limits or active leases. Partial scans wait 60 seconds; exponential failures start at 60 seconds and cap at one day; 429 waits at least 30 minutes and honors longer Retry-After.
- Five-minute source leases prevent overlaps; expired leases record interruption and resume the logical run/cursor. Each page commits jobs/provenance/evidence/cursor atomically; no payload cache required.
- Only complete unfiltered Greenhouse/Lever/Ashby snapshots can supply absence evidence. Absence is unknown/suspected, never confirmed closed. Only explicit passed Greenhouse application_deadline confirms closure; authoritative subsequent positive observation reopens. Other providers have no automatic closure policy.
- SmartRecruiters uses validated numeric offset/total cursors, fixed endpoints and bounded pages. Other readers remain bounded snapshots; unverifiable/truncated providers are partial, never authoritative absence.

## Interfaces

- `SourcePage` in `discovery_types.py`: jobs, next_cursor (dict or None), complete (bool), authoritative (bool), raw_count, rejected_count, closed (tuple of {job_id, deadline}). No diagnostic raw payloads.
- `retrieve_page(board, config_root='.', cursor=None)` in sources.py. Cursor never contains an arbitrary URL. Legacy retrieve_board remains usable.
- `DiscoveryState(store)` in discovery_state.py: `begin(source_id, provider, now, refresh=False)`, `commit_page(run_id, page, now)`, `pause(run_id, now)`, `fail(run_id, code, now, retry_after='', http_status=None)`, `health(now, limit=100)`, `scans(limit=100)`, `availability(job_id=None, limit=100)`.
- `begin` returns run row with `run_id`/`cursor` or skip with `skip_reason`/`next_retry_at`. `commit_page` returns added/updated/duplicate counts; uses `store._upsert_job(connection, job)` inside one transaction.
- `migrate(connection)` in discovery_state.py adds schema version 1 after baseline tables exist, atomically; rejects future versions. Read-only Store never migrates.
- Agent `discover(..., refresh=False, max_pages=3)` uses injectable UTC clock; compatibility summary retains existing counters/errors/by_source plus skipped/run metadata.

## Review focus

1. Crash between a job write and checkpoint: transaction rollback leaves both unchanged.
2. Concurrent scanners and expired workers: conditional run leases prevent stale writers from committing.
3. Filter/pagination/config changes: cannot turn partial evidence into closure or resume a different source namespace.
4. Rate-limit timestamps and clock boundaries: longer server restrictions cannot be bypassed with refresh.
5. Existing submitted/approved histories and shared URLs: new discovery never changes outcomes or loses requisitions.

## Tasks

- [ ] Retrieval: write failing offline tests for complete/partial pages, malformed cursors, interrupted pagination and deadline evidence; implement SourcePage/retrieve_page, run provider/network regressions.
- [ ] Persistence: write failing migration/rollback/restart/lease/backoff/availability/history tests; implement additive state tables and transactional page commits; verify read-only and legacy compatibility.
- [ ] Orchestration: write failing fake-clock/CLI/end-to-end recovery tests; integrate Store private upsert transaction interface and Agent/CLI reports; update deliberate repeat tests for explicit healthy refresh.
- [ ] Suggestions/provenance: bound inspected jobs and candidate results, keep registration explicit; canonical matches are review-only and preserve separate requisitions.
- [ ] Documentation and final qualification: explain recovery/evidence/limits; full offline suite, compile, pip check/audit, privacy, demo and links; commit/push/PR, independent complete diff and security review, Python 3.11–3.13 CI.
- [ ] Merge only after gates pass; verify exact merged tree/main unchanged/post-merge CI; close #10, assess R1 engineering acceptance separately from release publication, recommend #11 without implementing it.
