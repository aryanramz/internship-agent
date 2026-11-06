# Current-user Windows discovery scheduling (Issue #15)

This scheduler runs permitted discovery and a sanitized ranking count. It never
prepares documents, approves applications, records submissions, reads Gmail,
refreshes Google grants, sends email or writes Sheets. No optional SDK is needed.
SQLite `agent.db` remains authoritative; its revisions, approvals and discovery
page checkpoints are unchanged. Scheduler state is a separate private journal.

## Reviewable setup and controls

Use an existing local Windows checkout, its `.venv` with the package installed,
and an explicitly reviewed `config/sources.json`. The setup does not copy a
profile or activate any integration. Configure sources before installing tasks.

Double-click `scripts/windows/scheduler/Configure.cmd`. It shows the exact task
XML (executable, arguments, owner SID, triggers and settings), configuration and
unique task name. Installation/update requires typing `INSTALL <exact task name>`.
Closing the prompt cancels setup. `Preview.cmd` only displays the task definition.
Do not run Configure on an actual machine without the operator's separate approval.
These controls are separate from the gateway/Keycloak controls one folder above.

After setup, double-click the scheduler's `Start`, `Stop`, `Status`, `Disable`, or
`Remove` launcher. They invoke Python directly; no recurring PowerShell commands
are required. Equivalent CLI, from the selected checkout:

```powershell
internship-agent scheduler preview --root C:\Path\agent --at 09:00
internship-agent scheduler setup --root C:\Path\agent --at 09:00 --timeout-seconds 1800
internship-agent scheduler status --root C:\Path\agent
internship-agent scheduler start --root C:\Path\agent
internship-agent scheduler stop --root C:\Path\agent
internship-agent scheduler disable --root C:\Path\agent
internship-agent scheduler remove --root C:\Path\agent
```

`start` enables the task, clears the durable stop and asks Task Scheduler to wake
it now. It is idempotent while already running. It does not force a completed
window to run again or bypass retries. `stop` persists cancellation and suppresses
future work until Start. `disable` also disables future native triggers. `remove`
disables/deletes only the verified owned task. It preserves profiles, databases,
configuration, the lock file and audit history. Missing runtime/profile/source
files do not block Stop/Disable/Remove while the installed control interpreter
and scheduler configuration/journal are intact. No process is killed by saved PID.

Ownership is checked before native changes: exact unique name, URI/description,
current SID, InteractiveToken, LeastPrivilege and a single exact executable,
arguments and working directory. Any drift refuses the operation. Do not work
around that refusal by deleting an unverified task. Inspect it in Task Scheduler.
Update uses the same approval and refuses replacement of a foreign task. A running
worker blocks update. Keep the checkout/interpreter in their configured locations;
restore them before using controls if moved or deleted. Changing Python paths
requires removal using the old interpreter/definition before reinstallation.

## Defaults and recovery contract

| Setting | Default / meaning |
|---|---|
| Daily window | 09:00 in the Windows account's system local timezone |
| Native wake | Every five minutes from the daily boundary, plus current-user logon |
| Account | Current user, InteractiveToken, LeastPrivilege, no stored password |
| Signed-out operation | Unsupported: must be signed in; locked desktop is supported by design |
| Catch-up | Latest window only, at most once successfully, within 24 elapsed hours |
| Attempts | Three total per window, including interrupted/cancelled attempts |
| Retry delay | 60, 120, 240 seconds plus 0–30 seconds jitter; wake granularity is five minutes |
| Provider restrictions | Never earlier than relevant source retry/lease timestamps; discovery checks again; no refresh override |
| Timeout | 1800 seconds per attempt; configurable 1–86400 seconds; native limit adds 30 seconds |
| Battery / power | Allowed by default; `--no-battery` disallows start and stops on battery |
| Sleep | No wake by default; `--wake` opts into wake timers subject to Windows policy |
| Network | No native requirement, so offline failures are journaled; `--network-required` gates native wake |
| Notifications | Local balloon; disable with `--no-notifications`; Windows may suppress display |
| Retention | Latest 30 window summaries and their at most 90 attempt records |

The task runs a short-lived supervisor; the actual worker owns a non-reentrant
OS file lock for its entire lifetime, including result persistence. PID, random
attempt token and lease deadline are diagnostics, never authorization to steal a
lock. A crashed supervisor cannot release its child's lock. The worker independently
monitors cancellation and its hard deadline. Supervisor cancellation terminates
only the exact subprocess handle it created; orphaned workers exit themselves.
Windows task/power termination and sudden crashes may leave a `running` record.
Once the OS lock becomes available, the next wake records `interrupted`, applies
backoff and resumes through the existing discovery page checkpoints. No new
scheduler worker mutates jobs concurrently. Other manual CLI writers retain the
existing source-level leases and SQLite transactions; this is not a global lock
on all application commands.

The window identity is local `YYYY-MM-DD@HH:MM`; a DST repeated hour does not
create a second window. System-local conversion uses the boundary date's DST
offset, not today's fixed offset. Spring gaps use the system runtime's local-time
normalization. Older missed dates are discarded rather than replayed as a queue.
Clock rollback is fenced by a durable high-water mark even after history pruning.
Avoid changing timezone or schedule during a window; re-preview and approve setup
after a timezone/policy change. This is local wall-clock scheduling, not a
cross-timezone calendar service.

`success` means discovery completed, `noop` means no eligible work (including
healthy source cooldowns). Provider errors, failed/busy cooldowns, incomplete
pages and work-budget skips yield `partial`, never completion. Partial runs can
already have committed pages; those commits remain in `agent.db`. Errors never
include raw exception messages. Retired source cooldowns do not postpone current
sources. Notification failure is recorded separately and cannot retry core work.
A nonzero worker exit is surfaced as a control error and matching active attempts
are marked interrupted. Cancellation can be resumed with Start within the three
attempt limit; exhaustion waits for the next daily window. Notification delivery
is best effort; `sent` means the Windows API accepted the attempt, not that the
operator saw it.

Private files under `data/scheduler/` are `config.json`, `journal.db` and the
persistent `worker.lock` inode. Do not delete the lock while any worker may exist.
Missing/empty/corrupt/incompatible journals fail closed. Stop/disable the owned task
using Task Scheduler if controls cannot open their journal, retain private backups
and inspect `source-health`/`scans` before recovery. Restore the journal from backup;
explicit approved setup can initialize a missing/empty journal only after operator
review of possible replay. Do not delete a corrupt nonempty journal to force a retry.
The scheduler cannot prove previous outcomes if its journal was destroyed.
Task registration and local configuration writes are not one atomic transaction:
if setup fails partway, inspect the previewed task and retry the same approved setup.
A task without a valid configuration/journal fails closed.

Status shows native task state/result separately from the latest window outcome,
attempt history, categories, counts, retry time and notification state. It exposes
no employer, job, profile, URL or credential content. `configuration` means inspect
private local inputs; `database` means check compatible schema/competing writers
and backup; `provider`/`partial` means inspect private `source-health` and `scans`;
`interrupted`/`timeout` means inspect status and the runtime/power history. These
private diagnostic CLI reports can contain source metadata; do not publish them.
The journal provides bounded local logs. Local ACLs/account protection are trusted;
this feature is not a defense against another process already controlling the user.

The older `scripts/run-daily.ps1` remains a manual diagnostic script producing
private detailed reports. Google reads now require `-EnableGmailAlerts`; Sheets
preview requires `-EnableSheetsPreview` and existing grant/configuration. Token
presence alone is not authorization. Neither option is used by the scheduler.

## Qualification boundary and native test procedure

Linux synthetic tests cover durable window/retry/checkpoint decisions, partial
results, offline providers, real concurrent processes/OS lock recovery, orphan
worker exclusion, timeout termination, cancellation controls, corruption, retention,
privacy and clock behavior. Windows CI runs the offline suite with `PYTHONUTF8=0`,
checks Unicode paths, actual Windows file locks and in-memory native task XML plus
the actual PowerShell ownership verifier. No CI test calls task registration.

**Native task lifecycle qualification is NOT COMPLETE.** No actual Windows task
was installed or integration activated by this implementation session. In-memory
COM XML validation is not installation, trigger or recovery evidence. Issue #15's
native acceptance criteria and the R4 release gate remain outstanding.

After separate explicit approval, use an isolated current-user Windows synthetic
checkout and fictional import sources only. Record exact Windows build, Python,
base/head SHAs and sanitized before/after evidence:

1. Preview; approve installation; export and compare owner/action/policy; repeat
   setup to show one owned task. Use a second synthetic task as a noninterference
   sentinel, and test ownership drift refusal without changing unrelated tasks.
2. Trigger manually and by clock; locked-session execution; logoff/logon and
   reboot-equivalent restart; verify stable window IDs and one successful mutation.
3. Sleep across one and several boundaries; resume within/outside lookback; verify
   latest-only catch-up, battery/wake policy, no replay of completed windows.
4. Offline failure then online retry; simulated rate limit/Retry-After; partial scan
   checkpoint resume; enforce three attempts and verify actionable notifications.
5. Overlapping starts, supervisor/worker crashes, timeout, Stop then Start,
   Disable, and notification API failure/suppression; inspect attempt history and
   application-event/revision invariance.
6. Remove; verify owned task absent, unrelated task/files/processes untouched,
   no remaining worker, and private ledger/profile retained. Remove only approved
   synthetic artifacts and document any host-policy limitation honestly.

Do not mark these scenarios passed from mocks or CI. No approval for performing
this native installation/lifecycle sequence is implied by the implementation PR.
