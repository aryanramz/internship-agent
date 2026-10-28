"""Conservative sync to the user's EXISTING 19-column Applications sheet.

Dry run by default. Existing human-entered rows are never modified. Rows
managed by the agent are identified by an explicit Agent ID in column S.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import re
import uuid
from ..tracker import COLUMNS, STATUS_MAP, _track

HEADER_ROW = 4
SHEET_NAME = "Applications"
SHEET_READ_RANGE = "'Applications'!A1:S5000"
SHEET_APPEND_RANGE = "'Applications'!A4:S"
AGENT_ID = re.compile(r"(?:^|;)\s*Agent ID:\s*([a-f0-9]{24})(?:\s*;|\s*$)", re.I)
PROGRESSION = {"Not Applied":0, "Applied":1, "Assessment":2, "Interview":3, "Offer":4,
               "Rejected":3, "Withdrawn":3}


def _get(row, i):
    return str(row[i]) if len(row)>i and row[i] is not None else ""


def _escape(value):
    # RAW Sheets input means text is not treated as a formula. Make CSV safe too.
    return str(value or "")[:4000]


def _source_rows(store):
    rows=[]
    with store.connection() as c:
        data=c.execute("""SELECT j.*, a.status, a.resume_path, a.letter_path, a.submitted_at
                          FROM jobs j JOIN applications a ON j.id=a.job_id
                          WHERE a.status IN ('prepared','approved','submitted','assessment','interview','offer','rejected','withdrawn')
                          ORDER BY a.updated_at, j.id""").fetchall()
        rows=[dict(r) for r in data]
    return rows


def plan_sync(store, sheet_rows: list[list]) -> dict:
    """Pure planning: no network writes. Requires exact row-4 schema."""
    if len(sheet_rows)<HEADER_ROW or [_get(sheet_rows[HEADER_ROW-1],i).strip() for i in range(19)] != COLUMNS:
        raise ValueError("Unexpected tracker headers: expected the original 19 columns on Applications row 4. No changes made.")
    known={}; occupied=set(); max_app=0; collisions=[]
    for sheet_row, row in enumerate(sheet_rows[HEADER_ROW:], start=HEADER_ROW+1):
        app_number=_get(row,0).strip()
        if app_number.isdigit():max_app=max(max_app,int(app_number))
        match=AGENT_ID.search(_get(row,18))
        if match:
            key=match.group(1).lower()
            if key in known:
                collisions.append({"job_id":key,"rows":[known[key][0],sheet_row]})
            else:
                known[key]=(sheet_row,row)
    if collisions:
        raise ValueError("Duplicate Agent IDs in live Sheet. Resolve manually; no changes made.")
    append=[]; updates=[]; skipped=[]
    for job in _source_rows(store):
        jid=job["id"]
        desired_status=STATUS_MAP[job["status"]]
        applied_date=(job["submitted_at"] or "")[:10]
        resume=Path(job["resume_path"]).name if job.get("resume_path") else ""
        letter=Path(job["letter_path"]).name if job.get("letter_path") else ""
        if jid in known:
            rn,row=known[jid]
            actual=_get(row,10).strip()
            if actual != desired_status:
                if actual not in PROGRESSION:
                    skipped.append({"job_id":jid,"row":rn,"reason":"Manual or unknown status; not overwritten"})
                elif PROGRESSION[desired_status] > PROGRESSION[actual]:
                    updates.append({"range":f"'Applications'!K{rn}","values":[[desired_status]]})
                else:
                    skipped.append({"job_id":jid,"row":rn,"reason":"Would downgrade or replace equal-stage outcome"})
            if applied_date and not _get(row,8).strip():
                updates.append({"range":f"'Applications'!I{rn}","values":[[applied_date]]})
            if resume and not _get(row,12).strip():
                updates.append({"range":f"'Applications'!M{rn}","values":[[resume]]})
            if letter and not _get(row,13).strip():
                updates.append({"range":f"'Applications'!N{rn}","values":[[letter]]})
        else:
            max_app+=1
            append.append([max_app,_escape(job["company"]),_escape(job["title"]),
                _escape(job["source_id"]),_track(job["title"]),_escape(job["location"]),
                _escape(job["work_mode"]),_escape(job["job_url"]),applied_date,"",
                desired_status,"Medium",resume,letter,"","","","",
                f"Agent ID: {jid}; Source: {_escape(job['provider'])}"])
    return {"existing_rows":len(sheet_rows)-HEADER_ROW,"agent_jobs":len(_source_rows(store)),
            "append_count":len(append),"update_count":len(updates),"skipped":skipped,
            "append_preview":[{"company":r[1],"role":r[2],"status":r[10]} for r in append[:10]],
            "_append_rows":append,"_updates":updates}


def sync_sheet(store, gateway, spreadsheet_id: str, apply: bool = False,
               confirmation: str = "") -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{25,100}", spreadsheet_id):
        raise ValueError("Invalid Google Sheet ID")
    sync_id=uuid.uuid4().hex
    sheet_ref=hashlib.sha256(spreadsheet_id.encode()).hexdigest()[:16]
    mode="applied" if apply else "preview"
    plan=None
    stage="read"
    write_attempted=False

    def audit(phase, **details):
        # Counts and a pseudonymous target only; no cells, URLs, filenames or tokens.
        payload={"sync_id":sync_id,"sheet_ref":sheet_ref,"mode":mode,"phase":phase,**details}
        if plan is not None:
            payload.update(append_count=plan["append_count"],update_count=plan["update_count"])
        with store.connection() as connection:
            store.event(connection,None,"sheet_sync",payload)

    audit("started")  # If local audit storage fails, do not contact Google.
    try:
        values=gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)
        stage="plan"
        plan=plan_sync(store,values)
        public={k:v for k,v in plan.items() if not k.startswith("_")} | {
            "append_rows":plan["_append_rows"],"updates":plan["_updates"],
            "sync_id":sync_id,"sheet_ref":sheet_ref}
        if not apply:
            audit("preview")
            return public | {"mode":"preview", "did_write":False}
        stage="confirm"
        if confirmation != "SYNC APPLICATIONS":
            raise ValueError("Applying sync requires exact confirmation: SYNC APPLICATIONS")
        audit("planned")
        stage="recheck"
        # Re-read just before writing; do not overwrite concurrent manual edits.
        if gateway.get_values(spreadsheet_id,SHEET_READ_RANGE) != values:
            raise ValueError("Sheet changed during sync planning. Retry; no changes made.")
        writes=0
        if plan["_updates"]:
            stage="update"
            write_attempted=True
            gateway.update_cells(spreadsheet_id, plan["_updates"])
            writes+=len(plan["_updates"])
        if plan["_append_rows"]:
            stage="append"
            write_attempted=True
            gateway.append_rows(spreadsheet_id,SHEET_APPEND_RANGE,plan["_append_rows"])
            writes+=len(plan["_append_rows"])
        stage="complete"
        audit("completed",write_ops=writes)
        return public | {"mode":"applied", "did_write":bool(writes), "write_ops":writes}
    except Exception as exc:
        try:
            audit("failed",stage=stage,error_type=type(exc).__name__,
                  write_outcome="unknown" if write_attempted else "not_attempted")
        except Exception:
            exc.add_note("Could not persist sync failure audit; inspect the remote sheet before retrying.")
        raise
