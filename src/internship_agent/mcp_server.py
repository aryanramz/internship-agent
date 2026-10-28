"""MCP v2 adapter: connect only through authenticated/private transport.

Install: pip install -e '.[mcp]'
Run: python -m internship_agent.mcp_server
"""
from __future__ import annotations
import os
from .service import Agent
from mcp.server import MCPServer

server=MCPServer("Internship Agent")
agent=Agent(os.environ.get("INTERNSHIP_AGENT_DATA","./data"))
profile=os.environ.get("INTERNSHIP_AGENT_PROFILE","config/profile.json")
sources=os.environ.get("INTERNSHIP_AGENT_SOURCES","config/sources.json")

@server.tool()
def discover_jobs() -> dict:
    """Fetch employer-approved public job-board endpoints from configured providers; returns ingestion counts and errors."""
    return agent.discover(sources)

@server.tool()
def import_external_jobs(records: list[dict]) -> dict:
    """Record up to 100 externally found jobs with real HTTPS URLs (e.g., approved connector results, Gmail alerts). Never submits."""
    return agent.import_external_jobs(records)

@server.tool()
def rank_jobs(limit: int=20, min_score: int=45) -> list[dict]:
    """Rank recorded roles with profile fit breakdown; scores are not hiring probabilities."""
    return agent.ranked(profile,limit,min_score)

@server.tool()
def preview_application(job_id: str) -> dict:
    """See source link, fit factors, eligibility warnings and truthful tailoring inputs without generating files."""
    return agent.preview(job_id,profile)

@server.tool()
def prepare_application(job_id: str) -> dict:
    """Generate draft ATS-readable resume and letter from verified profile claims. Does NOT apply."""
    return agent.prepare(job_id,profile)

@server.tool()
def approve_application(job_id: str, confirmation_phrase: str) -> dict:
    """Explicit user approval only. User must provide the exact phrase 'APPROVE <job_id>'. Does NOT apply."""
    return agent.store.approve(job_id,confirmation_phrase)

@server.tool()
def record_confirmed_submission(job_id: str, confirmation_evidence: str) -> dict:
    """Record an application after a real external submission, requiring prior approval and evidence. Does NOT submit."""
    return agent.store.mark_submitted(job_id,confirmation_evidence)

@server.tool()
def application_summary() -> dict:
    """Return counts by application stage for tracker reconciliation."""
    return agent.store.count()

@server.tool()
def ingest_google_job_alerts(query: str = "", limit: int = 30) -> dict:
    """Read up to 100 authorized Gmail job-alert messages and stage direct job links for review; read-only Gmail, no applications or emails sent."""
    return agent.ingest_alerts(query,limit)

@server.tool()
def list_pending_job_alerts(limit: int = 50) -> list[dict]:
    """Review staged Gmail job-alert URLs. Entries are unverified leads, not available jobs."""
    return agent.pending_alerts(limit)

@server.tool()
def review_job_alert(lead_id: str, action: str, company: str = "", title: str = "",
                     location: str = "", verified_url: str = "", description: str = "") -> dict:
    """With user approval, import a verified lead or ignore it. Never applies for a job."""
    return agent.handle_alert(lead_id,action,company,title,location,verified_url,description)

@server.tool()
def preview_google_sheet_sync(spreadsheet_id: str) -> dict:
    """Read-only Google Sheets reconciliation preview. Does not modify any cells."""
    return agent.sync_tracker(spreadsheet_id)

@server.tool()
def apply_google_sheet_sync(spreadsheet_id: str, confirmation_phrase: str) -> dict:
    """Update only agent-managed rows and append new prepared applications. Requires exact phrase SYNC APPLICATIONS."""
    return agent.sync_tracker(spreadsheet_id,True,confirmation_phrase)

if __name__=="__main__":
    # Development only: do not expose this service through a public tunnel without auth.
    server.run(transport="streamable-http")
