# Issue #14 implementation plan

Baseline: `ada3cda4c5a9207811a549db84a80fa4515513d0` (merged PR #27).
Spec: GitHub Issue #14, complete body inspected; no comments at kickoff.

Use PR #27's exclusive revisions, structural QA and packet hashes. Add a separate
atomic workflow-schema migration, preserving discovery's layout and all existing
rows. Ledger user_version=3 fences older writers; SQLite remains the only ledger.

- [x] Add journal/binding/evidence tables without rewriting historical outcomes;
  test legacy data, repeat/concurrent migration and rollback.
- [x] Reserve an intent before generating files; serialize generation/finalization
  with a SQLite writer transaction and publish a durable completion receipt.
  Recovery commits only complete, unchanged packets; incomplete attempts are
  marked failed and retained. Never generate for completed applications.
- [x] Require exact review tokens, recheck job/profile/packet identity, invalidate
  changed approvals, and make prepare/approve/submission retries idempotent.
  Submission evidence remains user-supplied/unverified, never employer receipt.
- [x] Add local review/application/recover CLI commands and explicit regeneration;
  document the complete offline flow, legacy handling, recovery and limits.
- [x] Run failure injection, process restart, concurrency, migration and CLI tests;
  full suite with extras, core-only environment, native Windows/Linux CI, audit,
  hygiene, compilation, dependency checks and synthetic demo. Obtain independent
  correctness/security reviews, fix confirmed issues, open an unmerged develop PR.

Decisions: identical current preparation inputs reuse the same revision; explicit
`--new-revision` regenerates and clears approval. Optional request IDs bind retries
to one attempt and cannot silently select superseded revisions. Pending attempts
block approval/submission until explicit recovery or a preparation retry. Recovery
never resumes application submission, deletes files, or grants approval. Process
crash recovery is qualified; filesystem durability across hardware/power failure
still depends on the OS/filesystem and private backups. No Issue #15, scheduler,
MCP expansion, Google change, live submission or paid service is in scope.
