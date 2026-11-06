# Issue #15 engineering evidence

Baseline: `09ba1e345a8cf1bfdc906c545e87ac8b5ac9fe76` (`origin/develop`, fetched at start).
Feature branch: `feature/15-windows-scheduling`. The PR records the exact delivered
head SHA and CI run URLs/results. No merge or native task installation is part of
this session. No integrations or Issue #16 work were activated.

## Local synthetic validation

Python 3.12.14 (Clang 22.1.3), Linux. Declared test/google/mcp/security extras.
pytest 9.2.0; python-docx 1.2.0; mcp 2.3.0; PyJWT 2.15.1;
google-api-python-client 2.201.0; google-auth-oauthlib 1.5.0; pip-audit 2.10.1.

- Full offline suite: **1108 passed, 8 skipped, 22 subtests passed, 27.35s**.
- Scheduler targeted suite: **50 passed, 1 skipped, 2.13s**.
- Skips: three live ATS checks; one live Sheets check; two daily PowerShell
  preflight checks (`pwsh` absent); one existing Windows lifecycle preview;
  one new Windows in-memory COM definition/actual PowerShell verifier check.
- Compilation, `pip check`, fresh three-job synthetic demo and staged repository
  hygiene (151 tracked/staged files; zero problems), diff whitespace check passed.
- Ordinary test processes retain the repository's external-network guard. The full
  suite used the supported execution network/socket permission for local gateway
  tests; no live flags were enabled. An initial restricted-socket run stalled in
  the existing gateway suite and was interrupted, not counted as a pass.
- No `actionlint` available locally; workflow changes are an added scheduler test
  selection in the existing core-only job. Full workflow execution is delegated
  to PR CI; the supported OS/version/security jobs are preserved.

## Independent reviews and regressions

Separate read-only correctness and security reviewers examined the implementation
against the kickoff and repository policy. Confirmed findings were fixed with
regressions covering:

1. Start idempotence and same-window resume after explicit cancellation.
2. System-local boundary-date DST offsets and repeated-hour window identities.
3. Unexpected child startup/crash failures cannot return an empty/stale success.
4. Removed sources cannot delay currently active source retries.
5. Missing/empty journals, missing controls and unsupported/corrupt state fail
   closed at runtime; only explicitly approved installation initializes state.
6. Alternate streams, DOS devices, trailing-dot/space and ambiguous Windows paths
   are refused before native execution.

Additional tests exercise per-attempt audit retention, stale launch epochs,
actual concurrent subprocesses, OS lock release after kill, orphan lock exclusion,
real subprocess timeout termination, durable stop/disable controls, source outage,
provider cooldown/partial-result semantics, sanitized notification failures and
mocked ownership/update/removal noninterference. The actual PowerShell verifier
and in-memory native XML have a separate Windows-only test. Tests do not register
or mutate any Windows task.

## Remaining qualification

**Not qualified:** native installation/export round trip, actual native triggers,
current-user logon/reboot/locked session, sleep/resume and power-policy behavior,
network outage/recovery through an installed task, actual notification display,
installed-task stop/restart/disable/removal and native unrelated-task sentinel
preservation. Those require separate approval in an isolated current-user
synthetic Windows scope. Mocked ownership/removal tests are engineering evidence,
not proof those scenarios passed. The detailed procedure, defaults and recovery
instructions are in [Windows scheduler](WINDOWS_SCHEDULER.md).

InteractiveToken requires a signed-in user; Windows policy can suppress wakes or
notifications. Local clock/timezone changes and destroyed journals require operator
review. Source-level cooldowns, pagination budgets, and the three-attempt limit may
leave a window partial. Native task registration and local configuration persistence
are not a shared transaction. Preserve private state and inspect the exact owned
task after a setup failure. Issue #15's native acceptance and the R4 release gate
remain outstanding; the PR intentionally does not close the issue.
