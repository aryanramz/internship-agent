# Component status and evidence

The roadmap was verified 2026-10-29 against develop at
`3a79f555617453fc68dd51d36a9d1e51eabd2dcc` and merged through PR #21.
This gateway integration revision also includes PR #8's prepared code and local
qualification; no public endpoint or installed service is implied. Each status
has a limited scope:

- **Implemented:** reachable merged code with local coverage; not proof of live
  compatibility or operational readiness.
- **Live validated:** a specific dated service exercise is recorded, identified
  as developer-run or operator-reported.
- **Experimental:** local proof with unresolved interoperability/security or
  operational gates.
- **Pending PR:** code on an unmerged branch, absent from the baseline.
- **Planned:** no complete implementation/qualification; partial foundations may exist.

## Capability matrix

| Component | Merged implementation / evidence | Validation boundary | Remaining work |
|---|---|---|---|
| Independent operation | Python CLI, `Agent`/`Store`, synthetic demo and `test_agent.py`/`test_public_demo.py` | Local operation needs no ChatGPT, model API or Google | Recoverable workflow #14, dashboard #16 |
| Sources | 18 configured types; Greenhouse/Lever/Ashby strict schemas and HTTP replay tests; #10 source health | One live board each for those three, not all types/boards | Broader qualification remains; [dated evidence](LIVE_ATS_VALIDATION.md) |
| ATS qualification | PR #4 Greenhouse fixes preserved; Issue #9 qualifies Greenhouse/Lever/Ashby with repeated ingestion and prepared/approved history | One public board each; no destination-page or internship-only completeness guarantee | Other providers remain live-unqualified; #10 adds offline lifecycle qualification |
| Employer sources | `registry.py`, known-URL detection, explicit add/suggest and read-only list; stable employer IDs/provenance/validation metadata | Legacy JSON compatible; suggestions inspect at most 1000 recent records; no automatic employer-name merging/crawling/remote validation | Single-writer local configuration; source health resides separately in SQLite |
| Incremental/availability | Issue #10: atomic page checkpoints, fenced restart, source-health/backoff, read-only reports and separate availability evidence | Absence never confirms closure; explicit Greenhouse deadlines only; other remote readers remain partial; [policy/recovery](DISCOVERY_LIFECYCLE.md) | Scheduler #15; broader provider qualification and retention policy remain |
| Candidate facts | Issue #11: bounded private profile v2, typed facts/status/provenance/qualifiers and unverified legacy adaptation | Explicit local confirmation is recorded, not independently authenticated; no document inspection or profile rewrite | [Schema and compatibility](ELIGIBILITY.md); document QA remains #13 |
| Eligibility | Issue #11: evidence-anchored requirements, deterministic eligible/uncertain/ineligible, local read-only CLI reports and optional separate rank summary | Controlled English only; missing/conflicting/unsupported material remains uncertain; no legal determination. Legacy `review`/`unlikely` warning fields preserved | [Rules/examples/limits](ELIGIBILITY.md); #12 ranking remains separate |
| Matching | Weighted role/skill/location/recency/compensation/employer explanations | Heuristic fit, fixed weights, limited taxonomy; no calibrated accuracy | #12 |
| Documents | Verified-profile emphasis, single-column resume and generic letter DOCX; demo/tests | Not comprehensive claim checking, career-track variants or rendered/ATS QA | #13, including application-answer drafts |
| Application ledger | Jobs/applications/events, preparation/approval/status/evidence checks; tracker CSV | Evidence is operator-supplied, not verified receipt. Preparation generates files before rejecting completed states, so file overwrite protection is incomplete | #14 pre-generation guard, file recovery/version-bound approvals; #17 browser evidence |
| Google authorization | PR #5; shared per-user directory, overrides/legacy adoption, error tests | Operator confirmed reuse at `6239e68` with isolated DB; JSON is not vault-encrypted | Preserve optional grants and protect local ACLs; no upload |
| Sheets mirror | Exact 19 headers, preview/confirmation, ownership/manual-row protection, conflict/recovery tests | Operator-reported synthetic append/no-op and final reuse preview; multiple API requests are not atomic | Broader live edge cases unqualified; [limits](SHEETS_VALIDATION.md) |
| Gmail leads | Read-only OAuth, alert extraction/staging/review and synthetic tests | Live Gmail unqualified; not recruiter/reply workflows | #18 with separately authorized live qualification |
| MCP stdio | PR #6; real SDK initialization/list/call in both protocol modes, read-only SQL | Exactly summary/ranking/preview; no discovery/import/document/approval/Google tools | Optional interface, preserve small projections |
| MCP HTTP/issuer | PR #7; strict pinned JWT/owner/client/resource/per-call checks; SDK HTTP and actual local issuer experiments | Experimental loopback resource server; provider resource indicators experimental | Existing #3; actual ChatGPT invocation pending |
| HTTPS gateway/identity startup | PR #8 integration code, synthetic gateway/Windows regressions and [local provider evidence](MCP_GATEWAY_VALIDATION.md) | No active Funnel, actual TLS/ChatGPT or native installed-task proof | #3 controlled live/private startup qualification; code inclusion does not authorize activation |
| Scheduling | `scripts/run-daily.ps1` discovery, optional alerts/ranking/Sheets preview | Script exists; no qualified unattended setup, locking/retry/catch-up/notifications | #15; PR #8 identity controls do not complete this |
| Local dashboard | Planned | An ASGI MCP endpoint is not a dashboard | #16 |
| Browser assistance | Planned | No backend form automation/submission implementation | #17, with explicit permission/preview/handoff |
| Recruiter workflow | Planned | No verified contacts, outreach backend or reply matching | #18; local drafts first, separate send authorization |
| Analytics | `Store.count` and CLI summary provide status counts | No conversion cohorts, reliability series or scoring calibration | #19; measured evidence only |
| Continuous/cloud operation | Planned | CLI scripts and local MCP proofs do not establish continuous uptime/hosting readiness | #15 first; #20 after local acceptance |

## GitHub and release reconciliation

| Item | Verified state | Interpretation |
|---|---|---|
| Issue #1 / PR #4 | Original one-provider scope complete; issue reconciled closed, PR merged | Greenhouse retained; #9 is additional scope |
| Issue #2 / PR #5 | Complete, closed / merged | Final operator reuse check recorded without private identifiers |
| Issue #3 / PRs #6–#7 | Issue open; both PRs merged | Local MCP done; actual authenticated ChatGPT call remains exit gate |
| PR #8 | Gateway/lifecycle code included in this integration revision | Local qualification is documented; activation remains separate and independent of discovery |
| Versions | Package metadata 0.4.0, `__init__.__version__` 0.1.0, MCP descriptor 0.4.0 | Existing drift, unchanged here; fix in release preparation |
| Publication | No tags or GitHub Releases found | Changelog 0.1–0.4 entries are development history, not published-artifact evidence |

## Baseline checks and limits

Before gateway integration, the roadmap baseline's Windows Python 3.12 suite ran on 2026-10-29:
**184 passed, 3 skipped, 22 subtests passed**. Skips cover optional live exercises
and a platform-specific permission check. CI tests Python 3.11–3.13 with Google
and MCP extras. Counts describe that execution only, not usage, accuracy, provider
coverage or hiring metrics. [Gateway qualification](MCP_GATEWAY_VALIDATION.md)
records its larger suite and prior isolated provider proof separately. No live
ATS/Google/OAuth test is required or repeated by merging the code.

[Master roadmap](ROADMAP.md) · [Release acceptance](RELEASE_PLAN.md) ·
[Threat model](THREAT_MODEL.md) · [Next PR](NEXT_ENGINEERING_PR.md)
