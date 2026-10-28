"""Generate Google Sheets-compatible append candidates; never overwrite user history."""
from __future__ import annotations

import csv
from pathlib import Path
from .store import Store

COLUMNS = ["App #","Company","Role","Job ID","Track/Function","Location","Work Mode","Source/URL",
           "Date Applied","Deadline","Status","Priority","Resume Version","Cover Letter Version",
           "Follow-Up Date","Days Since Applied","Follow-Up Due","Contact","Notes"]

STATUS_MAP = {"discovered":"Not Applied", "shortlisted":"Not Applied", "prepared":"Not Applied",
              "approved":"Not Applied", "submitted":"Applied", "assessment":"Assessment",
              "interview":"Interview", "offer":"Offer", "rejected":"Rejected", "withdrawn":"Withdrawn"}


def _track(title: str) -> str:
    title = title.lower()
    if "security" in title or "cyber" in title: return "Cybersecurity"
    if any(x in title for x in ["cloud", "infrastructure", "platform", "devops", "systems"]):return "Engineering / IT Systems"
    if any(x in title for x in ["data", "analytics", "business intelligence"]):return "Data / Analytics"
    if "network" in title:return "Networking"
    if any(x in title for x in ["support", "helpdesk"]):return "IT Support"
    return "Other"


def _safe_cell(value):
    """Prevent formula execution when imported into Excel/Google Sheets."""
    if isinstance(value,str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_append_candidates(store: Store, output: str, include_unapplied: bool = False) -> dict:
    """Creates CSV rows for review. Does not edit or synchronize any sheet."""
    items = store.list_jobs(1000)
    rows=[]
    for j in items:
        if not include_unapplied and j["status"] in {"discovered","shortlisted"}:
            continue
        with store.connection() as c:
            r=c.execute("SELECT submitted_at FROM applications WHERE job_id=?",(j["id"],)).fetchone()
        app_date=r["submitted_at"][:10] if r and r["submitted_at"] else ""
        rows.append(["",j["company"],j["title"],j["source_id"],_track(j["title"]),j["location"],j["work_mode"],
                     j["job_url"],app_date,"",STATUS_MAP[j["status"]],"Medium",
                     Path(j["resume_path"]).name if j.get("resume_path") else "",
                     Path(j["letter_path"]).name if j.get("letter_path") else "",
                     "","","","",f"Agent ID: {j['id']}; Source: {j['provider']}"])
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.writer(f);writer.writerow(COLUMNS);writer.writerows([[_safe_cell(v) for v in r] for r in rows])
    return {"file":str(path.resolve()),"rows":len(rows),"note":"Review and de-duplicate against live Sheet before append; do not replace historical rows."}
