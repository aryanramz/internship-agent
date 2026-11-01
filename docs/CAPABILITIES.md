# Component status and evidence

The original roadmap baseline was verified 2026-10-29 against develop at
`3a79f555617453fc68dd51d36a9d1e51eabd2dcc` and merged through PR #21.
Current implementation status includes PRs #22–#24 through accepted develop commit
`e2b6e9742d48fb30500255714227d3ec1579b822`, plus the earlier PR #8 gateway.
Code/local qualification does not establish public activation or installed services.
Each status has a limited scope:

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
| PR #8 | Gateway/identity lifecycle code merged before PRs #22–#24 | Local qualification is documented; activation remains separate and independent of discovery |
| Issues #9/#10, PRs #22/#23 | Discovery/registry and lifecycle merged | R1 engineering implemented; publication remains separate |
| Issue #11 / PR #24 | Structured eligibility merged at `e2b6e9742d48fb30500255714227d3ec1579b822` | Only the eligibility slice of R2; #12/#13 remain |
| Versions | Package metadata 0.4.0, `__init__.__version__` 0.1.0, MCP descriptor 0.4.0 | Existing drift, unchanged here; fix in release preparation |
| Publication | No tags or GitHub Releases found | Changelog 0.1–0.4 entries are development history, not published-artifact evidence |

## Baseline checks and limits

Before gateway integration, the roadmap baseline at
`3a79f555617453fc68dd51d36a9d1e51eabd2dcc` ran on Windows/Python 3.12 on 2026-10-29:
**184 passed, 3 skipped, 22 subtests passed**. Skips cover optional live exercises
and a platform-specific permission check. CI tests Python 3.11–3.13 with Google
and MCP extras. Counts describe that execution only, not usage, accuracy, provider
coverage or hiring metrics. [Gateway qualification](MCP_GATEWAY_VALIDATION.md)
records its larger suite and prior isolated provider proof separately. No live
ATS/Google/OAuth test is required or repeated by merging the code.

Later executions are separate evidence, not replacements for that baseline:

| Revision / source | Environment | Recorded outcome |
|---|---|---|
| PR #8 final head `37fe0c7`; [gateway evidence](MCP_GATEWAY_VALIDATION.md) | Windows / Python 3.12 | 279 passed, 3 skipped, 22 subtests passed |
| PR #23 final head `6201508`; [PR qualification](https://github.com/aryanramz/internship-agent/pull/23) | Windows / Python 3.12 | 592 passed, 5 skipped, 22 subtests passed |
| PR #24 final head `0468d79`; [PR qualification](https://github.com/aryanramz/internship-agent/pull/24) | Windows / Python 3.12 | 864 passed, 5 skipped, 22 subtests passed |
| Accepted merge `e2b6e9742d48fb30500255714227d3ec1579b822`; Codex migration audit, independently reproduced as the Codex onboarding baseline | Linux / Python 3.12.14, pytest 9.2.0, MCP 2.3.0; approved elevated execution | 862 passed, 7 skipped, 22 subtests passed |

The migration audit's seven skips were three live ATS, one live Sheets, two
`pwsh` preflight and one Windows PowerShell preview test. The Windows PR #24 run
skipped four live checks and one POSIX permission test. Counts vary with platform
and installed tooling; see [Codex verification](CODEX_DEVELOPMENT.md#verification-and-skips).
New PRs must record their own results rather than adopting these counts.

[Master roadmap](ROADMAP.md) · [Release acceptance](RELEASE_PLAN.md) ·
[Threat model](THREAT_MODEL.md) · [Next PR](NEXT_ENGINEERING_PR.md)
