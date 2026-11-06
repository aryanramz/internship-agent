# Issue #16 validation

Baseline: develop `4c88f554041dea346ce5c0a9630d84365efc4ef4`.
Final delivered head and exact immutable CI results are recorded in the PR.

Local Linux Python 3.12.14: **1162 passed, 8 skipped, 22 subtests passed in 36.48s**.
This includes actual headless Chromium keyboard navigation (Tab/Enter), unlock,
list/detail, preparation, selectable text review, exact approval, operator-reported
submission and interview outcome; malicious markup stays text and a loopback
posting URL is not linked. All browser requests beyond numeric loopback are
blocked. Desktop/mobile screenshots use fictional data under docs/images.
Chromium evidence: browser smoke separately passed in 3.66s. Responsive check
asserts no horizontal overflow at 390px. No real application or contact occurred.

Skipped: three opt-in ATS live tests; one opt-in Sheets test; two daily-script
preflight tests (pwsh absent); existing Windows lifecycle preview; scheduler
in-memory Windows COM check. No live flags enabled. Supported execution socket
permissions were used for loopback servers; ordinary external-network test guard
remains intact. CI's ordinary jobs omit optional Playwright and report a browser
module skip; a separate browser job actually runs Chromium.

Environment: pytest 9.2.0, playwright 1.64.1, python-docx 1.2.0, mcp 2.3.0,
PyJWT 2.15.1. pip consistency, compilation, JavaScript syntax, full installed
inventory pip-audit (no known vulnerabilities), fresh synthetic demo, staged-file
hygiene (166 files, zero problems) and whitespace checks passed.

Independent read-only correctness/security reviews covered transport, data facade,
UI, document authorization and existing workflow. Confirmed findings fixed with
regressions or actual browser checks: read endpoints opening writable databases;
invalid preparation combinations mutating intent/approval; source aggregation
limited before classification; missing source/eligibility/QA/revision evidence;
silent text truncation; Unknown filter mismatch; private-address links;
misleading fit ordering copy; withdrawn outcome controls. The UI now shows evidence,
source/scheduler freshness, QA limitations and explicit preview truncation warnings.

HTTP tests cover foreign Host/Origin/Referer, session isolation/expiry/logout,
per-POST CSRF replay, methods, content types, body/query limits, traversal and
native localhost subprocess launch/stop with a Unicode root. Backend tests cover
pagination across the full ledger, unknown profiles, unchanged read-only storage,
stale/corrupt/foreign/symlink/oversized packet access, approvals and submission
semantics, same-transaction status bindings and invalid preparation nonmutation.

Remaining limits: no Windows desktop-browser or screen-reader session, no rendered
Word visual qualification, no external integration activation, no public deployment
qualification. Local account/terminal/ACL protection remains trusted. Posting links
are syntactically constrained, not DNS-resolved. Browser timeout does not undo a
committed operation; inspect/retry using existing workflow recovery semantics.
Completed records whose bound facts change require careful CLI inspection rather
than a new dashboard approval. Installed Windows scheduler lifecycle and R4 gate
remain unqualified; Issue #15 stays open. No Issue #17 implementation is included.
