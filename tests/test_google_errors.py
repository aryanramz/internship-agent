"""SDK-shaped HTTP failures remain offline and contain only synthetic payloads."""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("googleapiclient.errors",reason="Install the google extra for SDK error regression coverage")
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
from httplib2 import Response

from internship_agent import cli
from internship_agent.integrations.google_auth import GoogleGateway
from internship_agent.service import Agent


SID="EXAMPLE_SPREADSHEET_ID_12345678901234567890123"
RANGE="'Applications'!A1:S5000"


def http_error(status):
    return HttpError(Response({"status":str(status)}),
        json.dumps({"error":{"message":"PRIVATE API RESPONSE","code":status}}).encode(),
        uri="https://example.com/PRIVATE-SPREADSHEET-ID")


def failing_gateway(error,names=("Sheet1",),metadata_error=None):
    calls=[]
    class Request:
        def __init__(self,kind): self.kind=kind
        def execute(self):
            calls.append(self.kind)
            if self.kind=="metadata":
                if metadata_error: raise metadata_error
                return {"sheets":[{"properties":{"title":name}} for name in names]}
            raise error
    class API:
        def spreadsheets(self): return self
        def get(self,**kwargs):
            assert kwargs == {"spreadsheetId":SID,"fields":"sheets.properties.title"}
            return Request("metadata")
        def values(self):
            return SimpleNamespace(get=lambda **kwargs:Request("read"),
                batchUpdate=lambda **kwargs:Request("update"),append=lambda **kwargs:Request("append"))
    gateway=GoogleGateway.__new__(GoogleGateway)
    gateway.api=API()
    return gateway,calls


def test_missing_worksheet_lists_available_tabs_without_raw_response():
    gateway,calls=failing_gateway(http_error(400))
    with pytest.raises(RuntimeError,match="Worksheet 'Applications' was not found. Available worksheets: Sheet1.") as error:
        gateway.get_values(SID,RANGE)
    assert error.value.code == "worksheet_missing"
    assert "PRIVATE" not in str(error.value)
    assert calls == ["read","metadata"]


@pytest.mark.parametrize("status,code,action",[(401,"authorization_required","google-login sheets"),
    (403,"permission_denied","sharing"),(404,"spreadsheet_not_found","spreadsheet"),
    (429,"rate_limited","wait"),(503,"service_unavailable","later")])
def test_http_errors_are_actionable_and_never_echo_private_payloads(status,code,action):
    gateway,calls=failing_gateway(http_error(status))
    with pytest.raises(RuntimeError) as error:
        gateway.get_values(SID,RANGE)
    assert error.value.code == code
    assert action in str(error.value).lower()
    assert "PRIVATE" not in str(error.value)
    assert calls == ["read"]


def test_bad_range_on_existing_tab_reports_request_problem():
    gateway,_=failing_gateway(http_error(400),names=("Applications",))
    with pytest.raises(RuntimeError,match="request") as error:
        gateway.get_values(SID,RANGE)
    assert error.value.code == "invalid_request"


def test_missing_worksheet_metadata_failure_still_reports_safe_permission_error():
    gateway,_=failing_gateway(http_error(400),metadata_error=http_error(403))
    with pytest.raises(RuntimeError) as error:
        gateway.get_values(SID,RANGE)
    assert error.value.code == "permission_denied"
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("operation",["update","append"])
def test_failed_writes_include_uncertain_outcome_recovery_and_never_retry(operation):
    gateway,calls=failing_gateway(TimeoutError("PRIVATE TRANSPORT DIAGNOSTIC"))
    with pytest.raises(RuntimeError,match="preview") as error:
        if operation=="update":
            gateway.update_cells(SID,[{"range":"'Applications'!K5","values":[["Applied"]]}])
        else:
            gateway.append_rows(SID,"'Applications'!A4:S",[["fictional row"]])
    assert "uncertain" in str(error.value)
    assert "PRIVATE" not in str(error.value)
    assert calls == [operation]


def test_api_refresh_error_requests_local_sign_in_without_sensitive_details():
    gateway,_=failing_gateway(RefreshError("PRIVATE OAUTH ERROR"))
    with pytest.raises(RuntimeError,match="google-login sheets") as error:
        gateway.get_values(SID,RANGE)
    assert "PRIVATE" not in str(error.value)


def test_cli_reports_missing_worksheet_without_traceback(monkeypatch,tmp_path,capsys):
    gateway,_=failing_gateway(http_error(400))
    def fail(self,*args,**kwargs): return gateway.get_values(SID,RANGE)
    monkeypatch.setattr(Agent,"sync_tracker",fail)
    monkeypatch.setattr("sys.argv",["internship-agent","--data",str(tmp_path),"sync-sheet","--spreadsheet-id",SID])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 2
    output=capsys.readouterr()
    assert "Available worksheets: Sheet1" in output.err
    assert "Traceback" not in output.err
    assert "PRIVATE" not in output.err
