# Engineering roadmap

Status definitions: **implemented** = local code/test coverage exists; **validated** = exercised with real authorized services; **planned** = design only.

| Phase | Deliverable | Status | Acceptance criteria |
|---|---|---|---|
| v0.1 | ATS APIs, local scoring, DOCX generator, SQLite status ledger | Implemented | Offline tests pass, submission requires approved state |
| v0.2 | Extended source registry, imports, source suggestion | Implemented | Normalization tests, no blocked-platform scrapers |
| v0.3 | Gmail lead staging, safe Sheets reconciliation | Implemented / unvalidated live | Mock conflict tests pass; OAuth needs real-user consent |
| v0.4 | GitHub-ready release, fictional demo, CI and security docs | Implemented | Demo runs offline; tests and hygiene checks pass |
| v0.5 | Live approved ATS retrieval and test-sheet sync | Greenhouse validated; Google live sync pending | [Public ATS validation](LIVE_ATS_VALIDATION.md) with sanitized schema fixtures; zero unintended writes |
| v0.6 | Resume tailoring QA + MCP client integration | Planned | DOCX parsing and page count, supported MCP handshake/auth tested |
| Future | Assisted permitted browser submission | Planned | Site-specific approved workflow, human consent, evidence capture |
| Future | Recruiter drafting and reply monitoring | Planned | Verified contact identity; drafts before sending |

## Open technical decisions

1. Distinguish actual Summer 2027 eligibility from keywords using structured eligibility fields and user verification, not speculative LLM answers.
2. Resolve cross-source duplicates when tracking parameters, reposts, and requisitions differ without merging separate jobs.
3. Harden Google sync for partial network failures, repeated submissions, and multi-user concurrent changes.
4. Decide how to connect ChatGPT Work to a secured hosted MCP endpoint without exposing a personal local service publicly.
5. Introduce richer evidence-backed resume variants while disallowing fabricated achievements.

## Evaluation metrics to collect

Source success/failure rate; duplicate ratio; % postings missing descriptions; ranking precision among manually reviewed jobs; document acceptance QA; Sheet reconciliation mismatches; accidental-write incidents (target zero). **Do not** report success metrics before collecting actual observations.
