# Narrow browser assistance: local fixture only

Issue #17 implements one permitted adapter: this repository's own fictional local
application fixture. It is not a general ATS/browser driver. No real employer
origin, personal login, protected page, credential store, public endpoint or
external application submission is supported or authorized. Issue #17 remains
open for future separately approved permitted-provider qualification.

## Enable and use

Install normally (`python -m pip install -e .`); core assistance/CLI needs no
Playwright or optional Google/MCP packages. Use fictional locally attested profile
facts and a fictional posting, prepare/review the exact managed documents and
approve them through the existing CLI/dashboard first. Do not use your real data
for fixture qualification. Launch the existing dashboard explicitly:

```
python -m internship_agent.dashboard --root /absolute/fictional/checkout --sandbox-assistance
```

Without that flag, assistance routes and the fixture are disabled. The same
numeric IPv4 loopback bind, terminal access secret, session/Host/Origin/Referer/
fetch-site/CSRF policies and bounded JSON requests protect the adapter. No alternate
server, iframe, external navigation or generic browser-control endpoint is added.
Press Ctrl+C to stop; restart invalidates sessions. No native tasks are installed.

In the approved job's **Review current packet**, choose **Review sandbox assistance**.
Existing plans are shown before a new plan can be created. Review the employer,
job/source IDs and freshness (including unknowns), fixed target URL, job/profile/
packet/plan/form fingerprints, expiry and per-field provenance. A plan lasts 15
minutes from creation; stages do not renew that lifetime. A fill approval is not
submission authorization. No page-load operation fills fields or changes outcomes.

Open the exact local fixture in its own tab before final intent. Each action has
its own reviewed checkbox, exact phrase and one-use session-bound capability:

1. **Create** the concrete plan for that approved packet and fixed local form.
2. **Fill** only applicable locally attested `/name` and `/email` claims. Email
   syntax is deliberately conservative ASCII; unsupported formats remain manual.
   Missing, stale, conflicting, oversized or control-containing facts stay empty.
3. **Hand off** for human review. Synthetic MFA/CAPTCHA states only demonstrate a
   manual boundary: acknowledge and resume explicitly, then hand off again for
   final review. There are no password, OTP or challenge-answer inputs or solvers.
4. **Authorize intent** with `AUTHORIZE FIXTURE <plan_id>`. SQLite commits the
   intent and `needs_manual_reconciliation` state before the final control appears.
5. **Manually click** the one-shot local fixture control. No product code performs
   a browser submit click. The fixture records only a simulated observation,
   never an actual application or independently verified employer receipt.
6. **Reconcile** with `RECONCILE <plan_id>`, outcome and a short secret-free
   provenance statement. `unknown` remains blocked. `submitted` stays terminal and
   blocks another plan; it means an operator report about the fixture only.
   `not_submitted` permits a separately reviewed new plan, never reuse of old tokens.

Legal/immigration, work authorization, EEO and other sensitive fields are always
manual-only, empty and readonly in this adapter. This fixture neither collects nor
answers them. Proposed edits are not inferred from page labels or posting text.
Actual native-form/field/value changes stop assistance; rebuild and review a new
plan. Unknown custom JS, redirects and third-party scripts have no adapter surface.
The page has no document upload: it binds and displays the exact approved packet's
identity. Inspect/download that packet using existing safe review controls. This
qualifies identity binding, not provider-specific file upload or rendered Word QA.

## Intent, restart and ambiguity

Only an immediate successful intent response carries the purpose-bound, original-
session observation capability. It is not persisted in browser storage or URLs;
GET/reload/list inspection never reissues it. The manual control disables before
sending its single observation request. A lost acknowledgement, timeout or page
refresh never restores it; inspect and reconcile. An in-memory observation
capability is single-use and closes on any reconciliation, expiry or drift.
Unknown reconciliation cannot transfer final-action authority to another session.

Before intent, a replacement authenticated session may only inspect or explicitly
revoke with `REVOKE <plan_id>`; it cannot fill using an old approval. After intent,
revocation is refused: manual reconciliation with provenance is required. Old
sessions/action tokens cannot revive revoked, invalidated or terminal plans.
Concurrent workers/tabs are fenced by SQLite BEGIN IMMEDIATE, immutable plan digest,
one-use token rotation and a per-job open/intent check under the same transaction.
A server/process restart does not imply a click failed. There is no automatic retry
of a possible consequential action and no background automation from discovery,
ranking or scheduling.

CLI recovery uses the original plan origin and trusted local account filesystem
boundary, with no browser package or browser session export:

```
internship-assistance inspect --root /absolute/fictional/checkout --origin http://127.0.0.1:8765 --plan-id PLAN
internship-assistance revoke --root /absolute/fictional/checkout --origin http://127.0.0.1:8765 --plan-id PLAN --confirm "REVOKE PLAN"
internship-assistance reconcile --root /absolute/fictional/checkout --origin http://127.0.0.1:8765 --plan-id PLAN --confirm "RECONCILE PLAN" --outcome unknown --provenance "Fictional operator observation: outcome uncertain"
```

`python -m internship_agent.browser_assistance_cli` is equivalent. CLI inspection
omits action/review/observation tokens; reports remain private because proposed
contact facts can appear. Do not paste them in GitHub. Reconciliation intentionally
works after session, expiry, origin or packet drift and never grants fill authority.
The UI skips browser-form guards for recovery only. No arbitrary URL is opened by
these commands.

## Proof and permission matrix

| Workflow | Permission / evidence | Lock, retries and boundary |
|---|---|---|
| Plan/review | Explicitly enabled owned fixture; existing approved exact packet; declared fact provenance | Read-only review, no migrations; creation installs versioned additive journal |
| Fill | Reviewed plan and one-use action token | Same transaction checks current packet/profile/job/freshness/form; no standing approval |
| MFA/CAPTCHA | Manual fixture acknowledgement only | No solver, credential capture, OTP logging or account/session sharing |
| Final intent | Exact phrase and original local session; last-chance concrete summary | Durable ambiguity before control, single use, no automated click |
| Observation | Immediate purpose-bound intent capability | Simulated UI observation only; no real application-state mutation |
| Recovery | Explicit revoke before intent, or outcome/provenance reconciliation after it | Unknown stays blocked; submitted terminal; not_submitted needs a fresh plan |
| Future provider | No permission or implementation | Separate concrete site policy/account/submission approval and qualification required |

SQLite `agent.db` remains authoritative. Additive `assistance_schema` version 1,
`assistance_plans` and `assistance_events` preserve all existing IDs/statuses,
revision files, operator evidence and migrations. Historical application status is
never changed by this adapter, including fixture reconciliation. Existing CLI and
exactly three read-only MCP tools retain their contracts. Journal records contain
bounded plan facts, fingerprints and explicit observation/operator provenance;
there is no HTTP request logging, screenshot of credentials or sensitive session
capture. Local account/ACL trust remains required, not adversarial multiuser hosting.

## Qualification limits

Tests use fictional facts and the owned local fixture with external browser traffic
blocked. Actual Chromium covers keyboard approvals, manual challenge boundary,
dynamic control rejection, intent, observation/lost acknowledgement and refresh
reconciliation. Backend fake-clock/concurrent tests cover page/form/job/profile/
packet drift, stale/malformed/replayed tokens, expiry, restart, competing operators,
unknown outcomes and privacy/status invariance. See PR exact head/base, CI counts,
skips and screenshot evidence. Browser tooling stays optional (`.[test,browser]`).

Not qualified: any real employer/provider policy, authenticated ATS/browser account,
live CAPTCHA/MFA, employer receipt, provider-specific upload, real submission,
Windows desktop-browser/screen-reader session, or Issue #15 installed scheduler
lifecycle. Native Windows offline/localhost tests are reported separately from
Linux Chromium. No Issue #18, recruiter send, Google write or external integration
is activated. Do not close Issue #17 from this simulation alone.
