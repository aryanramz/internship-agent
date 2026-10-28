"""Offline qualification harness checks; no Google imports or authorization."""
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from internship_agent.integrations.google_auth import GoogleGateway
from internship_agent.integrations.sheet_sync import SHEET_READ_RANGE, SHEET_APPEND_RANGE
from internship_agent.store import Store
from internship_agent.integrations.sheet_sync import plan_sync, sync_sheet
from internship_agent.tracker import COLUMNS


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_google_sheets.py"
SID = "EXAMPLE_SPREADSHEET_ID_12345678901234567890123"


class MemorySheet:
    def __init__(self, corrupt_manual=False):
        self.tabs={"Applications":[],"Dashboard":[],"Lists":[]}
        self.corrupt_manual=corrupt_manual

    def get_values(self,sid,rng):
        assert sid == SID
        tab=rng.split("!")[0].strip("'")
        rows=[list(row) for row in self.tabs[tab]]
        if rng == "'Applications'!A1:S5000":
            rows=rows[:5000]
        for row in rows:
            while row and row[-1] == "":
                row.pop()
        while rows and not rows[-1]:
            rows.pop()
        return rows

    def update_cells(self,sid,data):
        assert sid == SID
        for entry in data:
            tab,cell=entry["range"].split("!")
            tab=tab.strip("'")
            match=re.match(r"([A-Z]+)([0-9]+)",cell)
            column=ord(match[1])-ord("A")
            start=int(match[2])-1
            for offset,values in enumerate(entry["values"]):
                rn=start+offset
                while len(self.tabs[tab])<=rn:
                    self.tabs[tab].append([])
                row=self.tabs[tab][rn]
                while len(row)<column+len(values):
                    row.append("")
                row[column:column+len(values)]=values

    def append_rows(self,sid,rng,rows):
        assert sid == SID and rng == SHEET_APPEND_RANGE
        self.tabs["Applications"].extend([list(row) for row in rows])
        if self.corrupt_manual:
            self.tabs["Applications"][4][1]="Wrongly overwritten manual row"


def test_default_command_only_describes_plan_without_google_access():
    proc=subprocess.run([sys.executable,str(SCRIPT)],cwd=ROOT,capture_output=True,text=True)
    assert proc.returncode == 0, proc.stderr
    result=json.loads(proc.stdout)
    assert result["status"] == "PLAN"
    assert result["will_create"] == "new synthetic tracker only"


def test_live_command_requires_exact_confirmation_before_any_oauth():
    proc=subprocess.run([sys.executable,str(SCRIPT),"--live"],cwd=ROOT,capture_output=True,text=True)
    assert proc.returncode == 2
    assert "CREATE SYNTHETIC TEST TRACKER" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_harness_exercises_real_sync_and_preserves_manual_rows(tmp_path):
    from scripts.validate_google_sheets import run_checks
    gateway=MemorySheet()
    result=run_checks(Store(str(tmp_path/"agent.db")),gateway,SID)
    assert result["status"] == "PASS"
    assert result["checks"] == ["preview_no_writes","header_guard","confirmed_insert",
        "repeat_noop","status_update","manual_status_protected","unrelated_tabs_preserved"]
    assert len(gateway.get_values(SID,SHEET_READ_RANGE)) == 7


def test_harness_fails_if_remote_manual_row_is_changed(tmp_path):
    from scripts.validate_google_sheets import run_checks
    with pytest.raises(AssertionError,match="manual row"):
        run_checks(Store(str(tmp_path/"agent.db")),MemorySheet(corrupt_manual=True),SID)


def test_google_gateway_uses_raw_writes_and_fixed_read_rendering():
    class API:
        def __init__(self):
            self.calls=[]
        def spreadsheets(self): return self
        def values(self): return self
        def get(self,**kwargs): self.calls.append(("get",kwargs)); return self
        def batchUpdate(self,**kwargs): self.calls.append(("update",kwargs)); return self
        def append(self,**kwargs): self.calls.append(("append",kwargs)); return self
        def execute(self): return {"values":[["fixture"]]}

    gateway=GoogleGateway.__new__(GoogleGateway)
    gateway.api=API()
    assert gateway.get_values(SID,SHEET_READ_RANGE) == [["fixture"]]
    cells=[{"range":"'Applications'!K6","values":[["=synthetic literal"]]}]
    gateway.update_cells(SID,cells)
    gateway.append_rows(SID,SHEET_APPEND_RANGE,[["=synthetic literal"]])
    assert gateway.api.calls == [
        ("get",{"spreadsheetId":SID,"range":SHEET_READ_RANGE,"valueRenderOption":"FORMATTED_VALUE"}),
        ("update",{"spreadsheetId":SID,"body":{"valueInputOption":"RAW","data":cells}}),
        ("append",{"spreadsheetId":SID,"range":SHEET_APPEND_RANGE,"valueInputOption":"RAW",
                   "insertDataOption":"INSERT_ROWS","body":{"majorDimension":"ROWS","values":[["=synthetic literal"]]}}),
    ]


@pytest.fixture
def reconciliation(tmp_path):
    from scripts.validate_google_sheets import _seed_store
    store=Store(str(tmp_path/"synthetic.db"))
    new_id,owned_id=_seed_store(store)
    manual=[1,"Historic Employer (fictional)","Manual role"]+[""]*16
    manual[10]="Interview"
    manual[18]="Human notes without an ownership marker"
    owned=[2,"Example Employer (fictional)"]+[""]*17
    owned[10]="Applied"
    owned[8]=store.get_job(owned_id)["submitted_at"][:10]
    owned[12:14]=["synthetic-resume.docx","synthetic-letter.docx"]
    owned[18]=f"Agent ID: {owned_id}; Source: synthetic"
    sheet=MemorySheet()
    sheet.tabs["Applications"]=[["Synthetic tracker"],[],[],list(COLUMNS),manual,owned]
    return store,sheet,new_id,owned_id


@pytest.mark.parametrize("header",[COLUMNS[:-1],COLUMNS+["Unexpected"],
    [COLUMNS[1],COLUMNS[0],*COLUMNS[2:]],[" App #",*COLUMNS[1:]],None])
def test_header_schema_requires_exact_19_columns(reconciliation,header):
    store,sheet,_,_=reconciliation
    sheet.tabs["Applications"][3]=header
    with pytest.raises(ValueError,match="headers"):
        plan_sync(store,sheet.tabs["Applications"])


def test_duplicate_agent_ids_abort_without_any_writes(reconciliation):
    store,sheet,_,_=reconciliation
    sheet.tabs["Applications"].append(list(sheet.tabs["Applications"][5]))
    before=[list(row) for row in sheet.tabs["Applications"]]
    with pytest.raises(ValueError,match="Duplicate Agent IDs"):
        sync_sheet(store,sheet,SID,True,"SYNC APPLICATIONS")
    assert sheet.tabs["Applications"] == before


@pytest.mark.parametrize("actual,desired,updates",[("Applied","interview",True),
    ("Interview","submitted",False),("Offer","interview",False),
    ("Rejected","offer",False),("Withdrawn","interview",False),
    ("Interview","rejected",True),("Interview","withdrawn",True)])
def test_status_progression_protects_terminal_outcomes(reconciliation,actual,desired,updates):
    store,sheet,_,owned_id=reconciliation
    sheet.tabs["Applications"][5][10]=actual
    if desired != "submitted":
        store.update_status(owned_id,desired,"Synthetic transition")
    plan=plan_sync(store,sheet.tabs["Applications"])
    assert bool(plan["_updates"]) is updates
    if updates:
        assert plan["_updates"] == [{"range":"'Applications'!K6","values":[[desired.title()]]}]


@pytest.mark.parametrize("append_committed",[False,True])
def test_partial_write_recovery_replans_committed_updates_and_uncertain_append(reconciliation,append_committed):
    store,sheet,_,owned_id=reconciliation
    store.update_status(owned_id,"interview","Synthetic transition")
    manual=list(sheet.tabs["Applications"][4])
    original_append=sheet.append_rows
    def fail_append(sid,rng,rows):
        if append_committed:
            original_append(sid,rng,rows)
        raise TimeoutError("Synthetic ambiguous write")
    sheet.append_rows=fail_append
    with pytest.raises(TimeoutError):
        sync_sheet(store,sheet,SID,True,"SYNC APPLICATIONS")
    assert sheet.tabs["Applications"][5][10] == "Interview"
    assert sheet.tabs["Applications"][4] == manual
    plan=sync_sheet(store,sheet,SID)
    assert plan["update_count"] == 0
    assert plan["append_count"] == (0 if append_committed else 1)
    sheet.append_rows=original_append
    sync_sheet(store,sheet,SID,True,"SYNC APPLICATIONS")
    assert len(sheet.tabs["Applications"]) == 7
    assert sync_sheet(store,sheet,SID)["append_count"] == 0


def test_confirmation_precedes_all_remote_writes(reconciliation):
    store,sheet,_,_=reconciliation
    def forbidden(*args): raise AssertionError("Unconfirmed remote write")
    sheet.update_cells=forbidden
    sheet.append_rows=forbidden
    with pytest.raises(ValueError,match="confirmation"):
        sync_sheet(store,sheet,SID,True,"WRONG")


def test_full_read_window_refuses_incomplete_deduplication(reconciliation):
    store,sheet,_,_=reconciliation
    sheet.tabs["Applications"].extend([[] for _ in range(5000-len(sheet.tabs["Applications"]))])
    sheet.tabs["Applications"][-1]=[5000,"Synthetic last row"]
    with pytest.raises(ValueError,match="read window"):
        sync_sheet(store,sheet,SID,True,"SYNC APPLICATIONS")


def test_sparse_postings_beyond_old_window_cannot_be_appended_again(reconciliation):
    store,sheet,new_id,_=reconciliation
    sheet.tabs["Applications"].extend([[] for _ in range(6000-len(sheet.tabs["Applications"]))])
    distant=[3,"Synthetic distant managed row"]+[""]*17
    distant[18]=f"Agent ID: {new_id}; Source: synthetic"
    sheet.tabs["Applications"][-1]=distant
    # Google trims blank rows at the end of a bounded range. A blank row 5000
    # must not be mistaken for proof that no managed rows exist after it.
    with pytest.raises(ValueError,match="read window"):
        sync_sheet(store,sheet,SID,True,"SYNC APPLICATIONS")
