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
