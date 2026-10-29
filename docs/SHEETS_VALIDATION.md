# Isolated Sheets sync qualification (Issue #2)

Status: **basic live OAuth, preview, synthetic append and repeat no-op reported
successful by the operator on 2026-10-28**. These results are user-provided evidence,
not a new agent-run qualification. The Google Drive connector is independent of
local backend authorization; no connector credentials were used or accessed.

| Operator-run check | Reported result |
|---|---|
| Local OAuth and empty-sheet read-only preview | Passed |
| Fictional application import and prepare | Passed |
| Preview new application | 1 append, 0 updates |
| Explicitly confirmed synthetic write | 1 write |
| Repeat preview | 0 appends, 0 updates |

The isolated tracker had the Applications worksheet and the expected 19 headers
on row 4. Its ID, local application ID, credentials and database are deliberately
omitted from public evidence. No actual application tracker was modified. The
broader harness below was not rerun. Credential routing and error messages have
offline regression coverage. The operator subsequently confirmed the focused
Windows check at commit `6239e68`: existing authorization was reused with the
isolated database, `existing_rows=1`, `agent_jobs=1`, zero appends/updates,
`mode=preview`, `did_write=false`. Issue #2 and PR #5 are complete. This is
operator-reported evidence, not a new test performed during roadmap reconciliation.

## Local setup

For a personal Google account, create/select a Google Cloud project, enable the
Google Sheets API, and configure Google Auth platform Branding and External
Audience in testing mode. Add your own account under Audience / Test users.
Under Clients create a Desktop app OAuth client, download its JSON, and save it
privately as `config/google-oauth-client.json`. Do not upload it to a chat or PR.
See Google's [desktop setup](https://developers.google.com/workspace/sheets/api/quickstart/python)
and [consent configuration](https://developers.google.com/workspace/guides/configure-oauth-consent).

From the repository root, install the existing optional integration and sign in:

```powershell
python -m pip install -e '.[google,test]'
internship-agent google-login sheets
```

The grant uses the existing Sheets read/write scope, which applies to spreadsheets
accessible to the signed-in account. Review that consent yourself; a separate
Google test account is suitable. Gmail/Drive API grants are not needed. The client
and tokens stay local; see [credential storage and compatibility](GOOGLE_SETUP.md#credential-storage-and-compatibility).
Refresh or consent problems must be resolved interactively; the runner never logs
in or prints token contents. All databases now use the same per-user grant by
default, instead of coupling authorization to `--data`.

## Focused local verification after updating

The operator completed this check at `6239e68`; no repeat is needed for this
reconciliation. The procedure remains for future upgrades. From the checkout where your
legacy authorization and isolated test database already exist, set the isolated
test tracker ID locally, then run **one read-only preview**:

```powershell
# INTERNSHIP_AGENT_SHEET_ID must refer to your isolated test tracker.
internship-agent --data data/sheet-sync-test sync-sheet
```

This checks that the existing grant is adopted into the shared credential store
without another sign-in. Expect the same zero-change result for the existing
synthetic database. The old token is preserved. If it was stored in a different
checkout, use `--credentials-dir` to point at that existing private directory;
never upload it. A different database may propose a different plan; preview only.

Optionally verify the missing-worksheet diagnostic using a separate empty test
spreadsheet with only Sheet1, in preview mode. Do not rename or change your
successful test tracker merely to recreate the earlier error.

## Review and run the concrete plan

```powershell
# Prints the plan only; no Google imports, sign-in, reads or writes.
python scripts/validate_google_sheets.py

# Explicit authorization to create ONE NEW synthetic tracker and test its rows.
python scripts/validate_google_sheets.py --live --confirm "CREATE SYNTHETIC TEST TRACKER"
```

The live runner is optional, for a future broader qualification; do not rerun it
just to repeat the successful basic checks. It has no existing spreadsheet-ID
argument. It creates a new tracker
named `Internship Agent SYNTHETIC sync qualification`, with Applications, Dashboard
and Lists tabs. All companies, documents and local submission evidence are
fictional. It does not submit a job application, send mail, read Gmail, or use a
personal profile/history file.

Checks against this new tracker:

1. Seed one manual row and one managed row; prepare a second synthetic local job.
2. Preview one exact insert and four exact cell updates; verify no remote change.
3. Temporarily change a header, confirm rejection with no sync writes, restore it.
4. Apply only the planned synthetic insert/updates; verify the manual row survives.
5. Confirm a repeat apply is a no-op with zero planned changes.
6. Preview/apply one status advance, then verify an unknown manually edited status
   is preserved. Compare unrelated cells and Dashboard/Lists sentinels.

The test workbook remains in your Google account for inspection. The local
`data/sheets-validation/<run>/report.json` records its ID/link immediately after
creation, PASS/FAILED, stage and check names; the same folder contains the
fictional database and its audit events. Neither is for public commit. No extra
Drive permissions are requested to delete the workbook; remove it manually when
you no longer need it.

An equivalent default-skipped pytest check is available:

```powershell
$env:RUN_LIVE_SHEETS = '1'  # authorizes creation and synthetic writes
python -m pytest -q -s tests/test_sheets_live.py
Remove-Item Env:RUN_LIVE_SHEETS
```

Do not run both live commands just to repeat the same qualification: each creates
a separate workbook. Normal tests skip both Google and ATS live checks unless
their own opt-in environment variables are enabled.

## Exact preview and local audit

`sync-sheet` still defaults to preview. Its result now includes every proposed
19-column `append_rows` entry and each `updates` A1 range/value, in addition to
the existing counts and short summary. Inspect those exact changes before using
`--apply --confirm "SYNC APPLICATIONS"`. Preview values can contain private job
or document metadata; keep the output local.

Every sync records `sheet_sync` events in the existing local SQLite `events`
table. Events have a `sync_id`, a 16-character SHA-256 spreadsheet reference,
mode, phase and planned counts. They contain no sheet cells, titles, names,
filenames, raw spreadsheet ID, credentials or exception messages. Phases are
`started`, `preview`, `planned`, `completed`, and `failed`; failures include the
stage, exception type and whether writes were unattempted or their outcome is
unknown. These are operational records, not an immutable security audit trail.

For example, inspect the synthetic database in a local SQLite viewer:

```sql
SELECT created_at, payload_json
FROM events WHERE event_type = 'sheet_sync' ORDER BY id;
```

Preview never writes to Google, but does record its local audit events. If the
initial local audit cannot be persisted, sync stops before contacting Google.

## Failure recovery and limits

- A timeout after an update/append may mean Google applied it. The local audit
  records `write_outcome: unknown`; it never reports a failure as a rollback.
  Stop editing, inspect the tracker, then run preview again before authorizing
  another apply. Existing Agent IDs normally make this repeat a no-op. Offline
  coverage simulates an append that succeeds remotely then times out locally.
- `planned` with no completion/failure event can mean a process stopped mid-run.
  Treat remote write outcome as unknown and inspect before retrying.
- A failed create request may have created the workbook without returning its ID.
  Look for the synthetic qualification title in Google Sheets before rerunning.
- Headers must exactly match the 19 names and order in Applications A4:S4,
  including spacing. Duplicate Agent IDs are errors; resolve them manually. Missing IDs
  and unknown statuses are not permission to overwrite human-entered history.
- Writes remain separate Google requests, not an atomic transaction. The reread
  guard reduces concurrent-edit risk but cannot eliminate races. Run one writer
  at a time. Keep a versioned backup of real trackers.
- Reads cover Applications A:S so sparse managed rows beyond the old 5,000-row
  window cannot be missed. A populated row 5000 or later stops sync before writes.
  Archive or partition a large tracker manually; pagination is not implemented,
  and a large sheet may require a large read response before this guard runs.
  Columns outside A:S are outside the sync surface and are not rewritten.
- Offer, Rejected and Withdrawn are protected terminal outcomes. A different
  local outcome requires manual review. Interview can advance to Rejected or
  Withdrawn; earlier stages are never substituted for later stages.

## Troubleshooting

| Error | Action |
|---|---|
| Worksheet 'Applications' was not found; available worksheets listed | Create/rename the intended test tab and put the expected headers on row 4; no automatic worksheet creation occurs during sync |
| Spreadsheet not found or inaccessible | Check the local ID and sharing with the signed-in Google account; an inaccessible file can look like a missing file |
| Access denied | Check sharing, Editor access for writes, Sheets API enablement and the Sheets OAuth consent |
| Authorization missing, expired or revoked | Check credential-directory override, then run `internship-agent google-login sheets` interactively if needed |
| Unexpected headers / duplicate Agent IDs | Correct the synthetic test tracker, inspect preview again; no writes are made |
| Rate limit / service unavailable | Wait and try preview later; writes are never retried automatically |

Raw API response bodies, OAuth errors and request URLs are not displayed. Missing
worksheet diagnosis performs one metadata read to list tab names; keep those
names and exact preview values private. The metadata-only audit omits them.

The gateway uses RAW input for updates/appends, and INSERT_ROWS for appends.
The [Google append API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append)
finds the end of a logical table; the live check verifies placement by reading
back the new tracker. Offline fake placement alone is not proof of Google behavior.
