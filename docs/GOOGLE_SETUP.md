# Gmail job-alert and existing Google Sheets integration

This uses a **separate, user-controlled Google Cloud OAuth desktop application** for the local backend. It **does not** reuse the ChatGPT Gmail/Drive connector credentials. You can continue using ChatGPT's connected Gmail and Drive in chats independently.

## Step 1 — Google Cloud setup (manual user authorization)

1. In your own Google Cloud project, enable the **Gmail API** and **Google Sheets API**.
2. Configure the OAuth consent screen and use an appropriate app publishing/test mode. Add your Google account as a test user if required.
3. Create an **OAuth 2.0 Desktop application** client. Download its client JSON (do not send or commit it).
4. Save it as `config/google-oauth-client.json` in the extracted project directory.
5. On Windows, run the installer, then run the two commands below. Each opens a browser for Google consent.

```powershell
.\scripts\setup-windows.ps1
.\.venv\Scripts\Activate.ps1
internship-agent google-login gmail
internship-agent google-login sheets
```

The Gmail grant requests only `gmail.readonly`. The Sheets grant requests the `spreadsheets` scope, which can **read and edit Sheets that your account can access**; it is broader than a single file. No app password is used. Tokens are saved privately in `data/secrets/` and excluded from source control. Do not publish this directory or the OAuth client secret. Testing-mode refresh token expiration or admin consent policies may require renewed authorization; see Google documentation.

## Step 2 — Pull permitted job-alert emails into a review queue

```powershell
# Reads only matching alert emails, saves candidate job links + limited metadata.
internship-agent ingest-alerts --limit 30

# Review pending leads, including direct job URLs and anchor text.
internship-agent leads

# Import a verified lead after independently checking its posting. The title and company must be truthful.
internship-agent review-lead LEAD_ID import --company "Verified Employer" --title "Cloud Security Intern" --location "New York, NY" --url "https://employer.example/jobs/123"

# Or discard a false positive.
internship-agent review-lead LEAD_ID ignore
```

Sender allowlist includes LinkedIn, Indeed, Handshake, ZipRecruiter, Simplify, RippleMatch, WayUp, Wellfound, Built In, Y Combinator, Untapped and Jobright. A sender name is not proof of authenticity; emails and job URLs are untrusted. We **do not visit redirects**, scrape logged-in sessions, infer employer identity, or apply based on an email. Not all email templates contain extractable direct job links, so some alerts may yield no leads. Adjust `--query` for your own alert setup.

These candidate links are stored in `email_leads`, not in the applications table. Only manually reviewed leads can be promoted into the job database. Scoring can then process the imported job, but incomplete descriptions remain incomplete.

## Step 3 — Preview and then synchronize your existing tracker

Use the spreadsheet ID of your own tracker. The *running local backend* needs explicit OAuth authorization to access it.

```powershell
$env:INTERNSHIP_AGENT_SHEET_ID="EXAMPLE_SPREADSHEET_ID_12345678901234567890123"

# No changes to Google Sheets.
internship-agent sync-sheet

# AFTER reviewing the plan, authorize the writes.
internship-agent sync-sheet --apply --confirm "SYNC APPLICATIONS"
```

The sync expects `Applications!A4:S4` to match the original 19 headers. It never alters `Dashboard` or `Lists` and never modifies historical rows that lack an `Agent ID: <id>` marker in `Notes` (column S). It appends only **prepared or later** applications, not every newly discovered job. For agent-owned rows it only advances known statuses or fills blank submission dates and document names. Manual or unknown statuses are not replaced. It will not delete rows, rewrite notes or overwrite a manually edited resume name.

This sync is deliberately not fully transactional across multiple requests: if Google returns a timeout after a write, run the preview again. Agent ID markers make append retries idempotent under ordinary conditions. Avoid simultaneous manual and automated editing, and keep a versioned backup of the Sheet.

**Important:** the existing tracker includes historic rows and spreadsheet formulas; the sync doesn't copy conditional formats, data validation, or computed formulas into appended rows. If you depend on those calculations, extend the sheet template deliberately and test it first.

## ChatGPT integration options

- **Native ChatGPT path today:** Ask ChatGPT to read relevant Gmail messages and update the connected tracker using its Gmail/Drive plugins, without expecting it to call your local Python service. You can export reviewed job metadata as JSON and import it with `internship-agent import-jobs path.json`.
- **Direct MCP when allowed:** Run `python -m internship_agent.mcp_server`, connect via a supported authenticated HTTPS MCP endpoint or secure tunnel, and invoke `ingest_google_job_alerts`, `list_pending_job_alerts`, `rank_jobs`, `preview_google_sheet_sync`, etc. Never expose the local server without authentication. ChatGPT Plus does not currently have the same general custom MCP connection privileges as Business/Enterprise/Edu; verify actual account options instead of assuming access.
- **Task Scheduler (local):** Schedule `internship-agent discover` and `internship-agent ingest-alerts` to run on Windows after local consent. A cloud task cannot invoke the local CLI without an independently established connection.

## Google API reference

- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get
- https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append
- https://developers.google.com/workspace/gmail/api/auth/scopes
