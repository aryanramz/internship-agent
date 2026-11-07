# Issue #18 engineering qualification

Baseline: `097a78b95c21fd5467bb3ef56e45298e28f3ded0` (accepted develop).
Final head/base, immutable run URLs and precise CI counts are recorded in the PR.

Local Linux Python3.12.14, pytest9.2.0, Playwright1.64.1:
**1317 passed, 8 skipped, 22 subtests passed in79.41s**. This full run includes
all four actual Chromium tests: existing dashboard, MFA/CAPTCHA application
fixtures, and the new complete outreach workflow. No actual account or recipient
was contacted. Browser requests beyond the owned numeric loopback server were
blocked; no external request was observed.

New real browser evidence: keyboard Tab/Enter unlock/navigation/confirmations,
contact registration and exact verification, current approved packet lookup,
draft editing (clears review), exact revision review, local RFC822 download with
zero send rows, separate fictional send-evidence recording, enabled bounded policy,
due suggestion, strong header-based reply import, inert HTML-looking body,
opt-out suppression, and explicit mobile contact opt-out with no horizontal
overflow at390px. Review capabilities are omitted from rendered metadata,
including collapsed content. Screenshots under docs/images/outreach-* use only
fictional contacts/messages; no secrets or actual contact data were published.

Independent read-only correctness/security reviewers reproduced and helped fix:

- Stale draft previews could review a newer unseen body. Review now checks exact
  expected revision and content hash inside the same writer transaction.
- Stale contact verification could approve changed recipient/source evidence.
  Verification now binds the displayed contact hash.
- Send evidence could lose its original content identity after a draft edit.
  Immutable records now retain revision/content/recipient/binding hashes and
  conflicting attempts cannot replace an old send record.
- Conflicting identities initially invalidated only the new record. Both old and
  new contacts/reviews now become conflicting, including edit-induced collisions.
- Unknown mailer-daemon bounces or wrong senders with exact send references did
  not suppress follow-ups. They now suppress conservatively without becoming a
  positive recruiter match; suppression persists after redaction.
- Email domain case differences could evade matching/suppression/redaction.
  Canonical domain comparison plus conservative casefold suppression hashes fix it.
- API/CLI forwarding fields and UI identity keys did not match the concrete backend
  schema. Actual API/CLI/browser regressions now cover dispatch, reads and writes.
- Contact redaction needed linked draft/send/message PII removal. It is now one
  transaction, preserving audit hashes, opt-out sentinels and job/application history.

Additional regressions cover no read migration, version-forward refusal,
transaction rollback/crash restart, stale/false/guessed provenance, domain/header
injection, cross-employer/wrong-recipient/alias/forward/multi-recipient messages,
immutable-ID collisions, reordered/idempotent imports, missing verified facts,
Unicode MIME output, UTC/DST/due boundaries, export-without-send, uncertain send,
policy/dismissal deduplication, correction/retention/redaction, preserved opt-outs,
message prompt injection and visible suppression markers. No known confirmed
review finding is intentionally deferred. No sending implementation exists.

Compilation, JavaScript syntax, dependency consistency, full installed inventory
advisory audit (no known vulnerabilities), fresh synthetic demo, actual CLI entry
point/empty read without creation, wheel asset inclusion and staged hygiene/diff
checks passed. Browser tooling remains optional. Core and correspondence require
no Google/MCP SDKs. Package/runtime versions and Google scopes were not changed.

Local skips: 3 opt-in ATS live tests, 1 opt-in Sheets live test, 2 daily PowerShell
preflight tests (pwsh unavailable), existing Windows lifecycle preview, Windows
scheduler in-memory COM check. Live flags remained disabled. Supported execution
permissions were used for loopback sockets/browser tests; the ordinary external
network guard stayed in force. Ordinary CI jobs skip optional browser modules;
the dedicated Chromium job executes them. Native Windows offline/localhost/
CP1252 qualification is reported separately from Linux Chromium.

Limits: no live Gmail/account permission, real recruiter identity/deliverability/
reply qualification, external mail send, Windows desktop-browser/screen-reader
session or actual Task Scheduler installation. Manual contact verification and
send records are unverified operator attestations, not authenticated ownership,
willingness or delivery. Body edits require human fact review. Source URLs are
not fetched or authenticated. Conservative address/domain formats, one job per
contact and immutable suppression can refuse legitimate cases. The operator guide
contains exact supported steps/recovery and limitations. Keep #18 open for live
Gmail/permission qualification; #15/#17 operational gates remain separate. No
Issue #19, task installation, public endpoint, paid service or integration activation.
