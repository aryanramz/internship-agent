# Internship Agent

**Local-first internship discovery, job-fit ranking, and application preparation — designed for AI-assisted workflows.**

Internship Agent is an open-source Python project that combines employer job-board readers, an explainable matching engine, a SQLite application ledger, optional Google Workspace integrations, and an MCP tool interface. It's intended for students who want a disciplined, inspectable internship pipeline rather than a bulk-apply bot.

**Project status: v0.4.0 — working local prototype, not production-ready.** Most automated tests are offline/mocked. The MCP/Google connections and provider endpoint behavior need live validation. There is **no automatic job application submission or recruiter emailing**.

## Features

| Component | Current capability | Limitation |
|---|---|---|
| Discovery | 18 source types: public ATS feeds, public aggregators, RSS, approved JSON/CSV imports | No exhaustive global job index; feeds can change or rate-limit |
| Fit scoring | Explainable weighted role, skill, location, freshness, compensation, employer scoring | Heuristic score, **not** an interview/hiring probability |
| Screening | Flags senior/graduate/clearance language | Does not determine legal/work eligibility |
| Documents | Single-column DOCX resume and cover-letter draft from a verified profile | No guarantee of passing ATS; requires human review |
| Tracking | SQLite status ledger with audit events and explicit approval step | Records confirmation evidence; doesn't independently verify submission |
| Google | Gmail alert lead staging; Sheets dry-run and explicitly confirmed sync | Separate Google OAuth authorization; untested against live accounts |
| MCP | Structured tool surface for supported MCP clients | ChatGPT client access, remote authentication, and hosting not configured |

## Quickstart (Windows, Python 3.11+)

```powershell
# From the extracted repository root
.\scripts\setup-windows.ps1
.\.venv\Scripts\Activate.ps1

# Safely demonstrate the pipeline without network or personal data
python scripts/demo.py

# Copy then edit your PRIVATE, untracked configuration files
Copy-Item config\profile.example.json config\profile.json -ErrorAction SilentlyContinue
Copy-Item config\sources.example.json config\sources.json -ErrorAction SilentlyContinue

# Optional: discover from configured permitted sources (requires internet)
internship-agent discover
internship-agent rank --min-score 55
```

The demo creates `demo-output/` containing a fictional three-job database, ranking summary and DOCX resume/letter. It does not authenticate, search real jobs, submit forms, or send email. **Never use the synthetic profile as your real resume.**

For macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python scripts/demo.py
python -m pytest -q
```

## ChatGPT and Work integration

The primary interface is intended to be ChatGPT Chat/Work; the backend offers an MCP server and a local CLI. Install the optional MCP extra with `python -m pip install -e '.[mcp]'`. The server code alone does **not** make it discoverable from a ChatGPT cloud session. Actual custom MCP access depends on your account/workspace, connection options, and authorized hosting. **Do not publicly tunnel this development server:** the current implementation lacks production authentication. See [integration options](docs/INTEGRATION.md) and [ChatGPT workflow guide](docs/CHATGPT_BRIDGE.md).

ChatGPT can independently work with connected Google Sheets and Gmail for user-approved workflows without a direct MCP connection; that is **not** equivalent to executing the local backend. A standalone script cannot use a ChatGPT subscription as an unmetered model API.

## Why this project exists

A collection of job listings is easy to build. A trustworthy pipeline requires handling duplicates, sourcing, field confidence, eligibility warnings, verified resume claims, explicit approvals, and sync conflicts. This project makes those tradeoffs visible and testable.

## Architecture

```mermaid
flowchart TD
    S[Public ATS APIs / feeds / authorized imports] --> N[Normalize & deduplicate]
    N --> DB[(SQLite source of truth)]
    DB --> R[Deterministic fit scoring]
    R --> P[Verified profile-based DOCX drafting]
    P --> A[Human review / approval]
    A --> W[Externally completed application + evidence]
    W --> DB
    DB --> G[Optional Google Sheets reconciliation]
    M[Optional local MCP interface] <--> DB
    C[ChatGPT Chat / Work] -. permitted tool access only .-> M
```

**Boundaries:** No unauthorized account scraping; no anti-bot bypass; no automated submission; no recruiter email sending; job descriptions and emails are untrusted input. Google writes are previewed and separately confirmed. The application ledger retains status transitions and events.

## Reproducibility and development

```powershell
python -m pytest -q
python scripts/check_repo_hygiene.py
python -m compileall -q src
```

[Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) · [Source coverage](docs/SOURCE_MATRIX.md) · [Roadmap](docs/ROADMAP.md) · [Demo walkthrough](docs/DEMO.md) · [Portfolio notes](docs/PORTFOLIO.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)

GitHub Actions runs tests across supported Python versions and checks for common accidental private-file commits. The file-checker is not a substitute for full secret scanning or security review.

## Roadmap

- **v0.4 (current):** public repo hygiene, synthetic offline demonstration, CI, documented tradeoffs and release artifacts.
- **v0.5:** authenticated end-to-end verification of at least one real ATS feed and Google sync using a test sheet; integration tests with sanitized recordings.
- **v0.6:** human-reviewed tailoring improvements, robust parsing/format QA and validation of MCP client connectivity.
- **Future:** approved, platform-compliant application assistance; recruiter outreach drafts and confirmation monitoring.

## Privacy and license

Your resume, real profile, application database, imported messages, generated documents and OAuth tokens must remain in the ignored local directories. The public repository includes only synthetic example data. Never paste credentials or real application records into issues. Licensed under the [MIT License](LICENSE); employment websites and third-party source APIs have their own terms.

> **Important:** This project helps organize and prepare applications. It cannot guarantee an ATS pass, an interview, employment, or that a particular posting is currently open.
