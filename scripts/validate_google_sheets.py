"""Qualify local Sheets OAuth/sync using a newly created fictional tracker only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from internship_agent.integrations.sheet_sync import SHEET_READ_RANGE, sync_sheet
from internship_agent.models import Job, stable_id
from internship_agent.store import Store
from internship_agent.tracker import COLUMNS


CONFIRMATION = "CREATE SYNTHETIC TEST TRACKER"


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _seed_store(store):
    ids=[]
    for sid in ("new", "existing"):
        jid=stable_id("synthetic","sheets-qualification",sid)
        url=f"https://example.com/fictional-jobs/{sid}"
        store.upsert_job(Job(id=jid,provider="synthetic",company="Example Employer (fictional)",
            source_id=sid,title=f"Cloud Intern ({sid}, fictional)",location="Example City",
            description="Synthetic qualification record; no actual application.",job_url=url,apply_url=url))
        store.set_prepared(jid,"synthetic-resume.docx","synthetic-letter.docx")
        ids.append(jid)
    # Fictional local state only, never a real submission or Google form action.
    store.approve(ids[1],f"APPROVE {ids[1]}")
    store.mark_submitted(ids[1],"SYNTHETIC TEST EVIDENCE - no external submission")
    return ids


def run_checks(store, gateway, spreadsheet_id):
    """Called only with a fresh tracker by the live runner; also exercised offline."""
    _,existing_id=_seed_store(store)
    manual=[1,"Manual Employer (fictional)","Synthetic manual role"]+[""]*16
    manual[10]="Manual review"
    manual[18]="Synthetic manual row; preserve exactly"
    owned=[2,"Example Employer (fictional)","Cloud Intern (existing, fictional)"]+[""]*16
    owned[10]="Not Applied"
    owned[18]=f"Agent ID: {existing_id}; Source: synthetic"
    gateway.update_cells(spreadsheet_id,[
        {"range":"'Applications'!A1:S6","values":[["SYNTHETIC QUALIFICATION ONLY"],
            ["No applicant data or real application evidence"],[],COLUMNS,manual,owned]},
        {"range":"'Dashboard'!A1","values":[["Synthetic dashboard sentinel"]]},
        {"range":"'Lists'!A1","values":[["Synthetic lists sentinel"]]},
    ])
    baseline=gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)
    other_tabs={name:gateway.get_values(spreadsheet_id,f"'{name}'!A1") for name in ("Dashboard","Lists")}
    checks=[]
    preview=sync_sheet(store,gateway,spreadsheet_id)
    _require(preview["append_count"]==1 and preview["update_count"]==4,"Unexpected initial sync plan")
    _require(len(preview["append_rows"])==1 and len(preview["updates"])==4,"Preview missing exact writes")
    _require(not preview["did_write"],"Preview reported writes")
    _require(gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)==baseline,"Preview changed the sheet")
    checks.append("preview_no_writes")

    gateway.update_cells(spreadsheet_id,[{"range":"'Applications'!A4","values":[["Unexpected header"]]}])
    bad_header=gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)
    try:
        try:
            sync_sheet(store,gateway,spreadsheet_id,True,"SYNC APPLICATIONS")
        except ValueError as exc:
            _require("headers" in str(exc),"Unexpected header rejection reason")
        else:
            raise AssertionError("Invalid headers were accepted")
        _require(gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)==bad_header,"Header rejection changed the sheet")
    finally:
        gateway.update_cells(spreadsheet_id,[{"range":"'Applications'!A4","values":[[COLUMNS[0]]]}])
    checks.append("header_guard")

    applied=sync_sheet(store,gateway,spreadsheet_id,True,"SYNC APPLICATIONS")
    _require(applied["append_count"]==1 and applied["update_count"]==4,"Confirmed plan changed")
    after=gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)
    _require(len(after)==7,"Append did not create exactly one row")
    _require(after[4]==baseline[4],"Confirmed sync changed the manual row")
    _require(after[5][10]=="Applied","Managed status update failed")
    _require(after[6][18].startswith("Agent ID:"),"Append did not retain ownership marker")
    checks.append("confirmed_insert")

    repeat=sync_sheet(store,gateway,spreadsheet_id,True,"SYNC APPLICATIONS")
    _require((repeat["append_count"],repeat["update_count"],repeat["did_write"])==(0,0,False),"Repeat was not a no-op")
    _require(gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)==after,"No-op changed the sheet")
    checks.append("repeat_noop")

    store.update_status(existing_id,"interview", "Synthetic test transition")
    status_preview=sync_sheet(store,gateway,spreadsheet_id)
    _require(status_preview["updates"]==[{"range":"'Applications'!K6","values":[["Interview"]]}],"Status preview was not exact")
    sync_sheet(store,gateway,spreadsheet_id,True,"SYNC APPLICATIONS")
    expected=[list(row) for row in after]
    expected[5][10]="Interview"
    _require(gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)==expected,"Status sync changed unrelated cells")
    checks.append("status_update")

    gateway.update_cells(spreadsheet_id,[{"range":"'Applications'!K6","values":[["Manual review"]]}])
    protected=gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)
    manual_plan=sync_sheet(store,gateway,spreadsheet_id,True,"SYNC APPLICATIONS")
    _require(not manual_plan["did_write"] and bool(manual_plan["skipped"]),"Manual status was not protected")
    _require(gateway.get_values(spreadsheet_id,SHEET_READ_RANGE)==protected,"Sync changed a manual status")
    checks.append("manual_status_protected")
    for name,values in other_tabs.items():
        _require(gateway.get_values(spreadsheet_id,f"'{name}'!A1")==values,"Sync changed an unrelated tab")
    checks.append("unrelated_tabs_preserved")
    return {"status":"PASS","checks":checks,"initial_append_count":1,"initial_update_count":4,
            "repeat_append_count":0,"repeat_update_count":0}


def run_live(output: Path, secret_dir: str):
    # No interactive OAuth here: the operator signs in separately beforehand.
    from internship_agent.integrations.google_auth import GoogleGateway
    run_dir=output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True,exist_ok=False)
    report_path=run_dir / "report.json"
    report={"status":"STARTED","created_at":datetime.now(timezone.utc).isoformat(),"stage":"authorize"}

    def save():
        report_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")

    save()
    try:
        gateway=GoogleGateway("sheets",secret_dir)
        report["stage"]="create"
        save()
        created=gateway.api.spreadsheets().create(body={
            "properties":{"title":"Internship Agent SYNTHETIC sync qualification"},
            "sheets":[{"properties":{"title":name,"gridProperties":{"rowCount":5000,"columnCount":19}}}
                      for name in ("Applications","Dashboard","Lists")],
        },fields="spreadsheetId,spreadsheetUrl").execute()
        sid=created["spreadsheetId"]
        # Persist identity immediately for review/recovery; no existing sheet input.
        report.update(spreadsheet_id=sid,spreadsheet_url=created.get("spreadsheetUrl",""),stage="checks")
        save()
        result=run_checks(Store(str(run_dir/"agent.db")),gateway,sid)
        report.update(result,stage="complete")
    except Exception as exc:
        # Keep OAuth errors, remote rows and diagnostic payloads out of reports/logs.
        report.update(status="FAILED",error_type=type(exc).__name__)
        save()
        raise RuntimeError(f"Sheets validation failed during {report['stage']}; inspect {report_path.resolve()} and the test tracker before retrying") from None
    save()
    return {"status":"PASS","report":str(report_path.resolve()),"checks":report["checks"]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true",help="Create a fresh Google tracker and test synthetic writes")
    parser.add_argument("--confirm",default="")
    parser.add_argument("--secret-dir",default="data/secrets")
    parser.add_argument("--output",type=Path,default=Path("data/sheets-validation"))
    args=parser.parse_args(argv)
    if not args.live:
        print(json.dumps({"status":"PLAN","will_create":"new synthetic tracker only",
            "checks":["exact preview","header guard","confirmed insert/update","repeat no-op",
                      "manual rows and statuses","unrelated tabs"],
            "required_confirmation":CONFIRMATION},indent=2))
        return 0
    if args.confirm != CONFIRMATION:
        parser.error(f"Live qualification requires --confirm '{CONFIRMATION}'")
    try:
        print(json.dumps(run_live(args.output,args.secret_dir),indent=2))
    except RuntimeError as exc:
        parser.exit(1,str(exc)+"\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
