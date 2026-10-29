# Next engineering PR: multi-provider ATS validation and employer registry

[Issue #9](https://github.com/aryanramz/internship-agent/issues/9), gate R1. Branch
from latest reviewed develop after the roadmap review. This document scopes the
next PR; no feature code is implemented in the reconciliation session.

## Objective

Qualify existing Greenhouse, Lever and Ashby readers against current permitted
public endpoints. Add a backward-compatible employer/ATS registry around current
`boards`, `add-source` and `suggest-sources` behavior. Preserve Greenhouse fixes
and application IDs/status/events. Do not rebuild the backend or wait for MCP.

## Scope

1. Inspect current primary API documentation and choose one permitted public,
   credential-free board per provider. Record provenance/date and a bounded
   request policy before exercising it. Do not publish raw live payload dumps.
2. Verify actual responses, dates/descriptions, canonical job/apply URLs, stable
   IDs and repeat ingestion. Identify reused versus fresh Greenhouse evidence.
   An unavailable provider is a documented blocker, not a passed gate.
3. Fix demonstrated transport/normalization incompatibilities only. Retain HTTPS,
   public-host validation, refused redirects, bounded reads, structured failures
   and per-board isolation. Respect 429/Retry-After; no blind retries or request
   escalation to force success.
4. Define employer identity, provider/token/site, public board URL, provenance,
   enabled state and validation evidence. Extend existing configuration; SQLite
   remains the application ledger. Old source JSON must remain usable. Public
   examples stay fictional; operational registry files remain local/private.
5. Repeated registration is idempotent; invalid/duplicate records are actionable.
   Preserve preview/explicit registration: detecting/registering a board does
   not itself fetch it.
6. Update source coverage and dated evidence without claiming all-reader coverage.

## Existing files to reuse

| Concern | Files |
|---|---|
| URLs, transport, normalization | `src/internship_agent/sources.py` |
| Detection/configuration | `src/internship_agent/source_detection.py`, `models.py`, `config/sources.example.json` |
| Orchestration/registration | `src/internship_agent/service.py`, `cli.py` |
| Identity/history | `src/internship_agent/models.py`, `store.py` |
| Tests | `tests/test_ats_integration.py`, `test_ats_live.py`, `test_sources_v02.py` |
| Evidence | `docs/LIVE_ATS_VALIDATION.md`, `SOURCE_MATRIX.md`, `CAPABILITIES.md` |

Abbreviated module names are under `src/internship_agent/`, tests under `tests/`
and documentation under `docs/`.

## Acceptance and tests

- Dated bounded live evidence for all three providers, with explicit limitations.
  Live discovery stays opt-in and skipped in ordinary CI.
- Synthetic HTTP replays per provider: success, empty/malformed snapshots, 404,
  429, redirect rejection and transport failure through reader/Agent/isolated DB.
- Repeat ingestion adds no duplicate applications and preserves prepared/approved
  states, distinct requisitions and historical events.
- Registry round-trip, old boards JSON compatibility, invalid/duplicate entries,
  enabled flags/provenance and registration-without-fetch are covered.
- Full offline suite, compilation, privacy/diff and appropriate network/security
  checks pass. Report skipped/blocked criteria. No credentials, private registry,
  personal database or raw live payload is committed.

## Exclusions and following work

No new provider families, broad crawler, cross-source lifecycle redesign, durable
scan health/checkpoints, closure inference, scheduling/dashboard, eligibility,
ranking/documents, runtime version cleanup, Google writes, browser automation,
outreach, hosting, Funnel activation or MCP writes. #10 owns incremental scans,
health/freshness/closed postings; #11 owns eligibility. Issue #3 stays independent.
