# Issue #17 engineering qualification

Baseline: `635ea2faa85d59aa4a998648b452994a164f5615` (accepted develop).
Exact final head/base and CI run links/results are recorded in the PR.

Local Linux Python 3.12.14, pytest9.2.0, Playwright1.64.1, python-docx1.2.0:
**1217 passed, 8 skipped, 22 subtests passed in66.25s**. Includes the existing
dashboard browser workflow and two real Chromium assistance tests. Separate
MFA/CAPTCHA E2E run: **2 passed in18.31s** (the full suite includes final fixes).
Screenshots under docs/images/assistance-* contain fictional data only.

Both assistance tests exercise actual keyboard activation of approvals, exact
phrases, DOM-injected dynamic-control rejection, explicit verified-value fill,
empty legal/EEO/work-authorization fields, manual synthetic challenge handoff,
resume/review, committed intent, one-shot local final control, uncertain/lost
acknowledgement, page refresh without restored final authority, unknown outcome
reconciliation and recovery when profile/packet review becomes stale. External
browser traffic is blocked. These tests do not contact any employer or live account.

Backend/API regression coverage: read-only inspection without migration, additive
journal version refusal, malformed/replayed tokens, fake-clock expiry, exact
profile/job/packet/form drift, competing sessions/workers, restart before/after
intent, permanent ambiguity fencing, purpose-bound immediate observation versus
read-only reconciliation capabilities, strict fixed target URL, default-disabled
HTTP routes, inherited auth/CSRF and CLI token-free inspection/recovery. All
underlying application statuses remain unchanged by fixture operations.

Independent read-only correctness/security reviewers reproduced and reported:

- Unknown reconciliation could transfer final-action authority to a new session.
  Fixed with purpose-bound observation tokens disclosed only once, a persisted
  may_observe fence, and permanent closure of observation by every reconciliation.
- Recovery UI incorrectly applied original browser target/form guards, blocking
  reconciliation after drift. Recovery now requires its own explicit phrase and
  provenance but does not grant browser action authority.
- Absolute target mismatch, dashboard intent on a page without its final control,
  and missing source-freshness rendering. Fixed; intent is fixture-tab-only.
- Competing-session test inferred ownership from a token's presence; new-session
  tokens intentionally permit recovery only. Test now checks ownership semantics.
- Expiry copy now accurately describes fixed 15-minute plan lifetime.

Additional parent regressions cover verified-but-inapplicable email syntax,
control-containing profile rejection without approval mutation, stale-packet UI
inspection access, exact fixture navigation, and CLI recovery without token output.
A browser assertion originally expected a different refusal message and was aligned
with the actual dynamic-form rejection. No confirmed finding is knowingly deferred.

Compilation, JavaScript syntax, pip consistency, fresh synthetic demo, full installed
inventory pip-audit (no known vulnerabilities), wheel packaging of all fixture/UI
and existing assets, staged hygiene and diff whitespace checks passed. Only the
dedicated virtual environment's pip was upgraded to match CI bootstrap policy.
No project dependency ranges or runtime versions changed. Browser remains optional.

Local skips: three live ATS, one live Sheets, two daily PowerShell preflight checks
(no pwsh), existing Windows lifecycle preview, scheduler in-memory Windows COM.
Live flags remain disabled. Loopback socket/browser execution used supported tool
permissions; ordinary external-network guard remains. Ordinary CI jobs omit browser
extras and skip optional browser modules; the dedicated Chromium job executes both.

Permission/behavior/recovery matrix and operator instructions are in
[BROWSER_ASSISTANCE.md](BROWSER_ASSISTANCE.md). This is owned local fixture
qualification only. Real-provider permission, account sessions, MFA/CAPTCHA,
provider upload/rendered documents, actual submission and employer receipt remain
unqualified. Windows desktop-browser/screen-reader and Issue #15 installed-task
lifecycle are separate gaps. Do not close #17 or claim the R4/provider gates from
simulation. No Issue #18, account login, real data/application, integration activation,
Google write, recruiter send, public endpoint or native task installation occurred.
