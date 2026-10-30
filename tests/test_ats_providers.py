"""Fictional ATS snapshots replayed through urllib, discovery and SQLite."""
import copy
import io
import json
from email.message import Message
from urllib.error import URLError
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

import pytest

from internship_agent import sources
from internship_agent.service import Agent


PROVIDERS = ("greenhouse", "lever", "ashby")
ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/example?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/example?includeCompensation=true",
}


def snapshot(provider):
    if provider == "greenhouse":
        return {"jobs": [{"id": n, "title": "Example Intern", "location": {"name": "Example City"},
                          "absolute_url": f"https://example.com/careers?gh_jid={n}",
                          "content": "&lt;p&gt;Build tools.&lt;/p&gt;", "first_published": "2026-10-01T09:00:00Z"}
                         for n in (1001, 1002)]}
    if provider == "lever":
        return [{"id": f"example-{n}", "text": "Example Intern", "categories": {"location": "Example City"},
                 "hostedUrl": f"https://jobs.lever.co/example/example-{n}",
                 "applyUrl": f"https://jobs.lever.co/example/example-{n}/apply",
                 "descriptionPlain": "Build tools.", "description": "<p>Build tools.</p>",
                 "lists": [{"text": "Requirements", "content": "<ul><li>Python &amp; SQL.</li></ul>"}],
                 "additionalPlain": "Closing information.", "additional": "<p>Closing information.</p>",
                 "workplaceType": "hybrid", "createdAt": 1790000000000} for n in (1, 2)]
    return {"jobs": [{"title": "Example Intern", "location": "Example City", "department": "Engineering",
                      "team": "Example Team", "isRemote": True, "workplaceType": "Hybrid",
                      "isListed": True, "publishedAt": "2026-10-01T09:00:00Z",
                      "jobUrl": f"https://jobs.ashbyhq.com/example/example-{n}",
                      "applyUrl": f"https://jobs.ashbyhq.com/example/example-{n}/application",
                      "descriptionPlain": "Build tools.", "descriptionHtml": "<p>Build tools.</p>",
                      "compensation": {"compensationTierSummary": "$20–$25 per hour"}}
                     for n in (1, 2)]}


def items(provider, payload):
    return payload if provider == "lever" else payload["jobs"]


def ok(payload):
    return 200, json.dumps(payload).encode(), {}


def replay(monkeypatch, responses, *, extra_endpoints=()):
    """Keep urllib HTTP/redirect behavior; replace only outbound HTTPS I/O."""
    pending = list(responses)

    class Transport(HTTPSHandler):
        def https_open(self, request):
            assert request.full_url in (*ENDPOINTS.values(), *extra_endpoints)
            assert request.get_method() == "GET"
            assert request.timeout == 20
            assert not request.has_header("Authorization")
            status, body, headers = pending.pop(0)
            if isinstance(body, Exception):
                raise body
            message = Message()
            for key, value in headers.items():
                message[key] = value
            response = addinfourl(io.BytesIO(body), message, request.full_url, status)
            response.msg = "Synthetic response"
            return response

    monkeypatch.setattr(sources, "build_opener", lambda *handlers: build_opener(Transport(), *handlers))


@pytest.fixture(params=PROVIDERS)
def discovery(request, tmp_path):
    provider = request.param
    config = tmp_path / "boards.json"
    board = {"provider": provider, "token": "example", "company": "Example Employer"}
    config.write_text(json.dumps({"boards": [board]}), encoding="utf-8")
    return provider, Agent(str(tmp_path / "ledger")), config, board


def history(agent):
    with agent.store.connection() as connection:
        return [tuple(r) for r in connection.execute("SELECT * FROM events ORDER BY id")]


def test_replay_retains_descriptions_dates_and_distinct_requisitions(monkeypatch, discovery):
    provider, agent, config, _ = discovery
    replay(monkeypatch, [ok(snapshot(provider))])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"] == []
    assert result["added"] == 2
    rows = agent.store.list_jobs()
    assert len({row["id"] for row in rows}) == 2
    assert len({row["title"] for row in rows}) == 1
    assert all(row["location"] == "Example City" for row in rows)
    assert all(row["description"].startswith("Build tools.") for row in rows)
    if provider == "lever":
        assert all(row["description"] == "Build tools. Requirements Python & SQL. Closing information." for row in rows)
        assert all(row["published_at"] == "" for row in rows)  # createdAt is not publication evidence.
    else:
        assert all(row["published_at"] == "2026-10-01T09:00:00Z" for row in rows)
    if provider == "ashby":
        assert {row["source_id"] for row in rows} == {"example-1", "example-2"}
        assert all(row["work_mode"] == "Hybrid" for row in rows)
        assert all(row["compensation"] == "$20–$25 per hour" for row in rows)


def test_repeat_preserves_prepared_approved_and_events(monkeypatch, discovery):
    provider, agent, config, _ = discovery
    replay(monkeypatch, [ok(snapshot(provider)), ok(snapshot(provider))])
    assert agent.discover(str(config), refresh=True)["added"] == 2
    ids = sorted(row["id"] for row in agent.store.list_jobs())
    for jid in ids:
        agent.store.set_prepared(jid, "fictional-resume.docx", "fictional-letter.docx")
    agent.store.approve(ids[1], f"APPROVE {ids[1]}")
    before = history(agent)
    approved_at = agent.store.get_job(ids[1])["approved_at"]
    result = agent.discover(str(config), refresh=True)
    assert (result["added"], result["updated"], result["duplicate"], result["errors"]) == (0, 2, 0, [])
    assert sorted(row["id"] for row in agent.store.list_jobs()) == ids
    assert agent.store.get_job(ids[0])["status"] == "prepared"
    assert agent.store.get_job(ids[1])["status"] == "approved"
    assert agent.store.get_job(ids[1])["approved_at"] == approved_at
    assert history(agent) == before
    with agent.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 2


def test_valid_empty_response_is_success(monkeypatch, discovery):
    provider, agent, config, _ = discovery
    replay(monkeypatch, [ok([] if provider == "lever" else {"jobs": []})])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"] == []
    assert result["by_source"][0]["retrieved"] == 0
    assert agent.store.list_jobs() == []


@pytest.mark.parametrize("bad", [None, {}, {"jobs": None}, {"jobs": {}}, "private"])
def test_invalid_schema_is_not_empty_success(monkeypatch, discovery, bad):
    _, agent, config, _ = discovery
    replay(monkeypatch, [ok(bad)])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"][0]["code"] == "invalid_payload"
    assert "private" not in json.dumps(result)
    assert result["by_source"] == []


@pytest.mark.parametrize("bad", [None, 1, "private"])
def test_nonobject_item_fails_entire_board(monkeypatch, discovery, bad):
    provider, agent, config, _ = discovery
    data = snapshot(provider)
    items(provider, data)[1] = bad
    replay(monkeypatch, [ok(data)])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"][0]["code"] == "invalid_payload"
    assert agent.store.list_jobs() == []


@pytest.mark.parametrize("field,value", [
    ("title", ""), ("title", {}), ("job_url", "https://"),
    ("job_url", "https://user:private@example.com/job"), ("job_url", "https://127.0.0.1/job"),
    ("job_url", "https://example.com:bad/job"), ("job_url", "https://example.local/job"),
    ("job_url", "https://bad host.example/job"), ("job_url", "https://example.com\\@private.local/job"),
    ("job_url", "https://intranet/job"), ("job_url", "https://bad..example.com/job"),
    ("description", {}),
])
def test_invalid_fields_abort_without_partial_ingestion(monkeypatch, discovery, field, value):
    provider, agent, config, _ = discovery
    mapping = {
        "greenhouse": {"title": "title", "job_url": "absolute_url", "description": "content"},
        "lever": {"title": "text", "job_url": "hostedUrl", "apply_url": "applyUrl", "description": "descriptionPlain"},
        "ashby": {"title": "title", "job_url": "jobUrl", "apply_url": "applyUrl", "description": "descriptionPlain"},
    }
    data = snapshot(provider)
    items(provider, data)[1][mapping[provider][field]] = value
    replay(monkeypatch, [ok(data)])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"][0]["code"] == "invalid_posting"
    assert "private" not in json.dumps(result)
    assert agent.store.list_jobs() == []


@pytest.mark.parametrize("discovery", ["lever", "ashby"], indirect=True)
@pytest.mark.parametrize("value", ["http://example.com/apply", "https://localhost/apply", {}])
def test_invalid_apply_url_aborts_without_partial_ingestion(monkeypatch, discovery, value):
    provider, agent, config, _ = discovery
    data = snapshot(provider)
    items(provider, data)[1]["applyUrl"] = value
    replay(monkeypatch, [ok(data)])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"][0]["code"] == "invalid_posting"
    assert agent.store.list_jobs() == []


@pytest.mark.parametrize("provider,patch", [
    ("lever", {"id": None}), ("lever", {"id": True}), ("lever", {"id": {}}),
    ("lever", {"id": " "}), ("lever", {"categories": []}),
    ("lever", {"categories": {"location": {}}}), ("lever", {"lists": {}}),
    ("lever", {"lists": [None]}), ("lever", {"lists": [{"text": {}, "content": "x"}]}),
    ("lever", {"lists": [{"text": "Skills", "content": {}}]}),
    ("lever", {"additionalPlain": {}}), ("lever", {"additional": []}),
    ("lever", {"workplaceType": False}),
    ("ashby", {"id": True}), ("ashby", {"id": []}), ("ashby", {"id": " "}),
    ("ashby", {"isListed": "false"}), ("ashby", {"isRemote": "true"}),
    ("ashby", {"location": []}), ("ashby", {"workplaceType": {}}),
    ("ashby", {"publishedAt": []}), ("ashby", {"publishedAt": "private-invalid-date"}),
    ("ashby", {"publishedAt": "2026-10-01T00:00:00"}),
    ("ashby", {"compensation": []}), ("ashby", {"compensation": {"compensationTierSummary": {}}}),
])
def test_provider_field_types_are_explicit(provider, patch):
    data = snapshot(provider)
    items(provider, data)[1].update(patch)
    with pytest.raises(sources.SourceError) as caught:
        sources.normalize({"provider": provider, "token": "example", "company": "Example Employer"}, data)
    assert caught.value.code == "invalid_posting"
    assert "private" not in str(caught.value)


def test_lever_html_fallback_keeps_closing_and_headings():
    data = snapshot("lever")
    for row in data:
        del row["descriptionPlain"]
        del row["additionalPlain"]
    jobs = sources.normalize({"provider": "lever", "token": "example", "company": "Example Employer"}, data)
    assert jobs[0].description == "Build tools. Requirements Python & SQL. Closing information."


def test_ashby_unlisted_filter_and_explicit_id_preserve_identity():
    data = snapshot("ashby")
    data["jobs"][0]["id"] = "explicit-id"
    data["jobs"][1]["isListed"] = False
    jobs = sources.normalize({"provider": "ashby", "token": "example", "company": "Example Employer"}, data)
    assert len(jobs) == 1
    assert jobs[0].source_id == "explicit-id"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("url", ["https://127.1/jobs/1", "https://example.123/jobs/1"])
def test_ats_links_reject_short_numeric_hosts(provider, url):
    data = snapshot(provider)
    field = {"greenhouse": "absolute_url", "lever": "hostedUrl", "ashby": "jobUrl"}[provider]
    items(provider, data)[0][field] = url
    with pytest.raises(sources.SourceError):
        sources.normalize({"provider": provider, "token": "example", "company": "Example Employer"}, data)


@pytest.mark.parametrize("status,code", [(301, "redirect_blocked"), (302, "redirect_blocked"),
    (307, "redirect_blocked"), (308, "redirect_blocked"), (403, "http_error"),
    (404, "not_found"), (410, "gone"), (429, "rate_limited")])
def test_http_failures_are_safe_without_retry_or_redirect(monkeypatch, discovery, status, code):
    _, agent, config, _ = discovery
    replay(monkeypatch, [(status, b"private diagnostics", {"Location": "https://internal.local/private", "Retry-After": "120"})])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"][0]["code"] == code
    assert result["errors"][0]["http_status"] == status
    if status == 429:
        assert result["errors"][0]["retry_after"] == "120"
    assert "private" not in json.dumps(result)
    assert agent.store.list_jobs() == []


@pytest.mark.parametrize("header,expected", [("Wed, 28 Oct 2026 12:00:00 GMT", "2026-10-28T12:00:00+00:00"), ("120", "120")])
def test_rate_limit_retry_after_is_preserved(monkeypatch, discovery, header, expected):
    _, agent, config, _ = discovery
    replay(monkeypatch, [(429, b"", {"Retry-After": header})])
    assert agent.discover(str(config), refresh=True)["errors"][0]["retry_after"] == expected


@pytest.mark.parametrize("body,code", [(b"<html>private</html>", "invalid_payload"),
    (URLError("private"), "network_error"), (TimeoutError("private"), "network_error")])
def test_malformed_json_and_transport_failures_are_safe(monkeypatch, discovery, body, code):
    _, agent, config, _ = discovery
    replay(monkeypatch, [(200, body, {})])
    result = agent.discover(str(config), refresh=True)
    assert result["errors"][0]["code"] == code
    assert "private" not in json.dumps(result)
    assert agent.store.list_jobs() == []


def test_failed_board_retains_history_and_does_not_block_later_board(monkeypatch, discovery):
    provider, agent, config, board = discovery
    data = snapshot(provider)
    bad = copy.deepcopy(data)
    items(provider, bad)[1] = None
    replay(monkeypatch, [ok(data), ok(bad), ok([] if provider == "lever" else {"jobs": []})],
           extra_endpoints=(ENDPOINTS[provider].replace("/example", "/other-example"),))
    assert agent.discover(str(config), refresh=True)["added"] == 2
    jid = agent.store.list_jobs()[0]["id"]
    agent.store.set_prepared(jid, "fictional-resume.docx", "fictional-letter.docx")
    before = history(agent)
    config.write_text(json.dumps({"boards": [board, {**board, "token": "other-example", "company": "Other Example Employer"}]}), encoding="utf-8")
    result = agent.discover(str(config), refresh=True)
    assert len(result["errors"]) == 1
    assert len(result["by_source"]) == 1
    assert result["by_source"][0]["retrieved"] == 0
    assert len(agent.store.list_jobs()) == 2
    assert agent.store.get_job(jid)["status"] == "prepared"
    assert history(agent) == before
