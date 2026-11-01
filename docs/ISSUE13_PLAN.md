# Issue #13 implementation plan

Spec: Issue #13 and its November 1 kickoff comment. Base: latest origin/develop,
1f31f5769101a6906dcd82d604c043cd2e2bfa3a. Implementation uses existing Python,
SQLite, python-docx and CLI; no new runtime dependency or integration.

- [x] Add a bounded document-fact contract in `document_profile.py`: explicit
  path/value-bound local attestations, stable IDs, source and review date. Legacy
  values remain readable but are withheld from candidate claims until attested.
  Conflicting, stale, missing and unverified facts produce review items.
- [x] Replace document drafting with deterministic master/track/job variants.
  Track emphasis references existing fact paths and taxonomy keys; job emphasis
  uses only whole-phrase verified skill overlap. Generate conservative letters,
  separate answer drafts, exact paragraph-level claim traces and DOCX QA reports.
- [x] Allocate new exclusive local revision directories; retain prior files and
  ledger events. Existing set_prepared invalidates approval. Keep completed-state
  evidence and the existing final ledger guard; do not implement Issue #14's
  file/DB transaction, restart recovery or submission-evidence redesign.
- [x] Add CLI selection and private local packet paths, preserving legacy calls,
  ranking, eligibility and the three MCP projections. Document schema and limits.
- [x] Test fictional missing/conflicting/unsupported facts, source trace identity,
  variants, Unicode/long text, empty skills, stale approval, historical states,
  safe paths, deterministic output, and offline CLI round trips.
- [x] Run full offline suite, hygiene, compileall, pip check, fresh synthetic demo,
  dependency audit and diff checks. Render representative DOCX with available
  tools, extract PDF text, inspect pages and record pagination/overflow limits.
- [ ] Obtain independent correctness/security reviews, fix confirmed findings,
  rerun affected checks, push feature branch, open unmerged PR to develop and
  inspect all CI jobs (delivery evidence recorded in ISSUE13_VALIDATION.md).

Review focus: no implicit verification; no invented coursework/experience or
legal answers; no private expansion of MCP output; symlink/path collisions;
revision allocation and modified packet identity. Local attestation records user
confirmation, not independent authentication of truth. Generated files and
reports remain private; only synthetic source fixtures enter Git.
