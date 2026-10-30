"""Synthetic HTTP replays through the real reader, Agent and SQLite ledger."""
import copy
import io
import json
from email.message import Message
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

import pytest

from internship_agent import sources
from internship_agent.service import Agent


BOARD = {"provider": "greenhouse", "token": "example", "company": "Example Employer"}
ENDPOINT = "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true"
FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse_jobs.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def discovery(tmp_path):
    config = tmp_path / "boards.json"
    config.write_text(json.dumps({"boards": [BOARD]}), encoding="utf-8")
    return Agent(str(tmp_path / "ledger")), str(config)


def replay(monkeypatch, responses, *, extra_endpoints=()):
    """Replace only HTTPS transport; keep urllib status/redirect handling real."""
    class Transport(HTTPSHandler):
        def https_open(self, request):
            assert request.full_url in (ENDPOINT, *extra_endpoints)
            assert request.get_method() == "GET"
            assert request.timeout == 20
            assert not request.has_header("Authorization")
            status, body, headers = responses.pop(0)
            if isinstance(body, Exception):
                raise body
            message = Message()
            for key, value in headers.items():
                message[key] = value
            response = addinfourl(io.BytesIO(body), message, request.full_url, status)
            response.msg = "Synthetic response"
            return response

    monkeypatch.setattr(sources, "build_opener", lambda *handlers: build_opener(Transport(), *handlers))


def ok(payload):
    return 200, json.dumps(payload).encode(), {}


def test_replay_ingests_plain_text_dates_and_distinct_requisitions(monkeypatch, payload, discovery):
    replay(monkeypatch, [ok(payload)])
    agent, config = discovery
    result = agent.discover(config)
    assert result["errors"] == []
    assert result["added"] == 2
    rows = {j["source_id"]: j for j in agent.store.list_jobs()}
    assert rows["1001"]["description"] == "Learn AWS & Python. Build tools."
    assert rows["1001"]["published_at"] == "2026-10-01T09:00:00Z"
    assert rows["1001"]["location"] == "Example City"
    assert rows["1001"]["apply_url"] == rows["1001"]["job_url"]
    # updated_at is an edit timestamp, never a substitute for publication time.
    assert rows["1002"]["published_at"] == ""
    assert rows["1002"]["description"] == "Use Python and Linux."


def test_repeat_discovery_updates_without_duplicate_applications(monkeypatch, payload, discovery):
    changed = copy.deepcopy(payload)
    changed["jobs"][0]["content"] = "&lt;p&gt;Updated skills.&lt;/p&gt;"
    replay(monkeypatch, [ok(payload), ok(changed)])
    agent, config = discovery
    assert agent.discover(config)["added"] == 2
    original = {r["id"] for r in agent.store.list_jobs()}
    jid = next(r["id"] for r in agent.store.list_jobs() if r["source_id"] == "1001")
    agent.store.set_prepared(jid, "synthetic-resume.docx", "synthetic-letter.docx")
    result = agent.discover(config)
    assert (result["added"], result["updated"], result["duplicate"]) == (0, 2, 0)
    assert {r["id"] for r in agent.store.list_jobs()} == original
    assert agent.store.get_job(jid)["status"] == "prepared"
    assert agent.store.get_job(jid)["description"] == "Updated skills."
    with agent.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM events WHERE event_type='discovered'").fetchone()[0] == 2


@pytest.mark.parametrize("status,code", [(301, "redirect_blocked"), (302, "redirect_blocked"),
    (307, "redirect_blocked"), (308, "redirect_blocked"), (404, "not_found"),
    (410, "gone"), (429, "rate_limited"), (503, "http_error")])
def test_http_failures_are_explicit_and_do_not_follow_redirects(monkeypatch, discovery, status, code):
    replay(monkeypatch, [(status, b"untrusted private response", {
        "Location": "https://internal.local/private", "Retry-After": "120"})])
    agent, config = discovery
    result = agent.discover(config)
    assert result["added"] == 0
    assert result["errors"][0]["code"] == code
    assert result["errors"][0]["http_status"] == status
    if status == 429:
        assert result["errors"][0]["retry_after"] == "120"
    assert "private" not in json.dumps(result)
    assert agent.store.list_jobs() == []


@pytest.mark.parametrize("bad_payload", [{"error": "bad board"}, {"jobs": None}, {"jobs": [None]}, {"jobs": {}}])
def test_schema_errors_do_not_masquerade_as_empty_boards(monkeypatch, discovery, bad_payload):
    replay(monkeypatch, [ok(bad_payload)])
    agent, config = discovery
    result = agent.discover(config)
    assert result["errors"][0]["code"] == "invalid_payload"
    assert result["by_source"] == []


@pytest.mark.parametrize("patch", [{"id": None}, {"id": True}, {"title": ""},
    {"absolute_url": "https://"}, {"absolute_url": "https://user:password@example.com/job"},
    {"absolute_url": "https://example.com:bad/job"}, {"content": {}},
    {"application_deadline": "not-a-date"}, {"application_deadline": "2026-10-01T00:00:00"}])
def test_invalid_posting_aborts_board_without_partial_writes(monkeypatch, payload, discovery, patch):
    payload["jobs"][1].update(patch)
    replay(monkeypatch, [ok(payload)])
    agent, config = discovery
    result = agent.discover(config)
    assert result["errors"][0]["code"] == "invalid_posting"
    assert agent.store.list_jobs() == []


def test_expired_deadlines_are_not_ingested(monkeypatch, payload, discovery):
    payload["jobs"][0]["application_deadline"] = "2000-01-01T01:00:00+01:00"
    replay(monkeypatch, [ok(payload)])
    agent, config = discovery
    assert agent.discover(config)["added"] == 1
    assert [r["source_id"] for r in agent.store.list_jobs()] == ["1002"]


@pytest.mark.parametrize("body,code", [(b"<html>not JSON</html>", "invalid_payload"),
    (URLError("private transport diagnostics"), "network_error"),
    (TimeoutError("private timeout diagnostics"), "network_error")])
def test_invalid_json_and_network_errors_are_safely_reported(monkeypatch, discovery, body, code):
    replay(monkeypatch, [(200, body, {})])
    agent, config = discovery
    result = agent.discover(config)
    assert result["errors"][0]["code"] == code
    assert "private" not in json.dumps(result)


def test_response_size_is_bounded(monkeypatch, discovery):
    monkeypatch.setattr(sources, "MAX_BYTES", 40)
    replay(monkeypatch, [(200, b"x" * 41, {})])
    agent, config = discovery
    assert agent.discover(config)["errors"][0]["code"] == "response_too_large"


@pytest.mark.parametrize("header,expected", [
    ("Wed, 28 Oct 2026 12:00:00 GMT", "2026-10-28T12:00:00+00:00"),
    ("private untrusted header", None), ("", None),
])
def test_retry_after_dates_are_normalized_and_invalid_headers_omitted(monkeypatch, discovery, header, expected):
    replay(monkeypatch, [(429, b"", {"Retry-After": header})])
    agent, config = discovery
    error = agent.discover(config)["errors"][0]
    assert error["code"] == "rate_limited"
    assert error.get("retry_after") == expected
    assert "private" not in json.dumps(error)


def test_failed_board_preserves_ledger_and_later_boards_still_run(monkeypatch, payload, discovery):
    replay(monkeypatch, [ok(payload), (410, b"", {}), ok({"jobs": []})],
           extra_endpoints=(ENDPOINT.replace("/example/", "/other-example/"),))
    agent, config = discovery
    assert agent.discover(config)["added"] == 2
    jid = agent.store.list_jobs()[0]["id"]
    agent.store.set_prepared(jid, "synthetic-resume.docx", "synthetic-letter.docx")
    Path(config).write_text(json.dumps({"boards": [BOARD, {**BOARD, "token": "other-example"}]}), encoding="utf-8")
    result = agent.discover(config)
    assert len(result["errors"]) == 1
    assert len(result["by_source"]) == 1
    assert result["by_source"][0]["retrieved"] == 0
    assert len(agent.store.list_jobs()) == 2
    assert agent.store.get_job(jid)["status"] == "prepared"
