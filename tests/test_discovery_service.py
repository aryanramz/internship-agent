"""Offline lifecycle orchestration and compatibility with fictional records."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from internship_agent.models import Job, stable_id
from internship_agent.service import Agent
from internship_agent.store import Store


def posting(sid="one", provider="greenhouse", url="https://example.com/jobs/shared"):
    return Job(id=stable_id(provider, "example", sid), provider=provider, company="Example Employer",
               source_id=sid, title="Example Intern", location="Example City", description="Fictional work",
               job_url=url, apply_url=url)


def test_distinct_requisitions_with_same_canonical_url_keep_separate_history(tmp_path):
    store = Store(str(tmp_path / "ledger.db"))
    first, second = posting(), posting("two", url="https://example.com/jobs/shared?utm_source=fixture")
    assert store.upsert_job(first) == "added"
    store.set_prepared(first.id, "fictional.docx", "fictional-letter.docx")
    store.approve(first.id, f"APPROVE {first.id}")
    store.mark_submitted(first.id, "FICTIONAL-CONFIRMATION")
    before = store.get_job(first.id)
    with store.connection() as c:
        events = [tuple(r) for r in c.execute("SELECT * FROM events ORDER BY id")]
    assert store.upsert_job(second) == "added"
    assert store.upsert_job(second) == "updated"
    assert len(store.list_jobs()) == 2
    assert store.get_job(first.id) == before
    with store.connection() as c:
        assert [tuple(r) for r in c.execute("SELECT * FROM events WHERE job_id=? ORDER BY id", (first.id,))] == events


def test_atomic_upsert_interface_rolls_back_discovery_and_application_event(tmp_path):
    store = Store(str(tmp_path / "ledger.db"))
    with pytest.raises(RuntimeError):
        with store.connection() as c:
            store._upsert_job(c, posting())
            raise RuntimeError("synthetic crash before checkpoint")
    assert store.list_jobs() == []
    with store.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def config(tmp_path, boards=None):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"boards": boards or [
        {"provider": "greenhouse", "company": "Example Employer", "token": "example"}]}))
    return str(path)


def test_healthy_cooldown_can_only_be_bypassed_explicitly(tmp_path, monkeypatch):
    from internship_agent.discovery_types import SourcePage
    import internship_agent.service as service
    calls = []
    monkeypatch.setattr(service, "retrieve_page", lambda *a, **k: calls.append(k) or SourcePage([posting()], authoritative=True))
    clock = Clock()
    agent = Agent(str(tmp_path / "db"), clock=clock)
    path = config(tmp_path)
    assert agent.discover(path)["added"] == 1
    assert agent.discover(path)["skipped"][0]["skip_reason"] == "cooldown"
    assert len(calls) == 1
    assert agent.discover(path, refresh=True)["updated"] == 1
    clock.advance(1800)
    assert agent.discover(path)["updated"] == 1


def test_failure_backoff_is_durable_and_refresh_never_bypasses_it(tmp_path, monkeypatch):
    import internship_agent.service as service
    from internship_agent.sources import SourceError
    calls = []
    def failing(*args, **kwargs):
        calls.append(1)
        raise SourceError("rate_limited", "synthetic private diagnostic", http_status=429, retry_after="3600")
    monkeypatch.setattr(service, "retrieve_page", failing)
    clock = Clock()
    path = config(tmp_path)
    root = str(tmp_path / "db")
    assert Agent(root, clock=clock).discover(path)["errors"][0]["code"] == "rate_limited"
    clock.advance(3599)
    report = Agent(root, clock=clock).discover(path, refresh=True)
    assert report["skipped"] and len(calls) == 1
    assert "private" not in json.dumps(report)
    clock.advance(1)
    assert Agent(root, clock=clock).discover(path)["errors"]
    assert len(calls) == 2


def test_partial_page_budget_resumes_after_restart_without_refetching_first_page(tmp_path, monkeypatch):
    from internship_agent.discovery_types import SourcePage
    import internship_agent.service as service
    seen = []
    def pages(board, root, cursor=None, **kwargs):
        seen.append(cursor)
        if cursor is None:
            return SourcePage([posting()], next_cursor={"offset": 100, "total": 200}, complete=False, raw_count=100)
        return SourcePage([posting("two")], complete=True, raw_count=100)
    monkeypatch.setattr(service, "retrieve_page", pages)
    clock = Clock()
    path = config(tmp_path)
    root = str(tmp_path / "db")
    first = Agent(root, clock=clock).discover(path, max_pages=1)
    assert first["added"] == 1
    clock.advance(60)
    second = Agent(root, clock=clock).discover(path, max_pages=1)
    assert second["added"] == 1
    assert seen == [None, {"offset": 100, "total": 200}]
    assert len(Agent(root, clock=clock).store.list_jobs()) == 2


def test_disabled_and_bounded_sources_never_start_unnecessary_requests(tmp_path, monkeypatch):
    from internship_agent.discovery_types import SourcePage
    import internship_agent.service as service
    calls = []
    monkeypatch.setattr(service, "retrieve_page", lambda b, *a, **k: calls.append(b["token"]) or SourcePage([]))
    boards = [{"provider": "lever", "company": "Example", "token": str(n), "enabled": n != 0} for n in range(4)]
    agent = Agent(str(tmp_path / "db"), clock=Clock())
    report = agent.discover(config(tmp_path, boards), max_sources=1)
    assert calls == ["1"]
    assert len(report["skipped"]) == 2
    with pytest.raises(ValueError):
        agent.discover(config(tmp_path, boards), max_pages=999)


def test_source_namespace_changes_for_retrieval_filters_not_private_metadata():
    from internship_agent.service import discovery_source_id
    base = {"provider": "greenhouse", "token": "example", "company": "Example"}
    assert discovery_source_id(base) != discovery_source_id({**base, "intern_only": True})
    assert discovery_source_id(base) == discovery_source_id({**base, "careers_url": "https://example.com/other", "company": "Renamed"})


@pytest.mark.parametrize("command", ["source-health", "scans", "availability"])
def test_cli_discovery_reports_are_read_only_and_need_no_profile(tmp_path, monkeypatch, capsys, command):
    from internship_agent import cli
    root = tmp_path / "db"
    store = Store(str(root / "agent.db"))
    store.upsert_job(posting())
    before = (root / "agent.db").read_bytes()
    monkeypatch.setattr("sys.argv", ["internship-agent", "--data", str(root), command])
    cli.main()
    assert isinstance(json.loads(capsys.readouterr().out), list)
    assert (root / "agent.db").read_bytes() == before


def test_no_ordinary_test_can_accidentally_access_external_network():
    import socket
    with pytest.raises(AssertionError, match="external hosts"):
        socket.getaddrinfo("example.com", 443)


def test_unpaged_limited_reader_waits_thirty_minutes_before_rescanning(tmp_path, monkeypatch):
    from internship_agent.discovery_types import SourcePage
    import internship_agent.service as service
    calls = []
    monkeypatch.setattr(service, "retrieve_page", lambda *a, **k: calls.append(1) or SourcePage([], complete=False))
    clock = Clock()
    agent = Agent(str(tmp_path / "db"), clock=clock)
    path = config(tmp_path)
    agent.discover(path)
    clock.advance(1799)
    assert agent.discover(path, refresh=True)["skipped"]
    assert len(calls) == 1
    clock.advance(1)
    agent.discover(path)
    assert len(calls) == 2


def test_valid_reopened_posting_is_not_blocked_by_unrelated_expired_posting(tmp_path, monkeypatch):
    from internship_agent import sources
    from internship_agent.discovery_state import DiscoveryState
    clock = Clock()
    row = {"id": 1, "title": "Example Intern", "absolute_url": "https://example.com/jobs/1", "content": "Fictional"}
    expired = {**row, "application_deadline": "2026-01-01T00:00:00Z"}
    snapshots = iter([{"jobs": [row]}, {"jobs": [expired]}, {"jobs": [row, {**expired, "id": 2}]}])
    monkeypatch.setattr(sources, "_source_payload", lambda *a, **k: (next(snapshots), None))
    agent = Agent(str(tmp_path / "db"), clock=clock)
    path = config(tmp_path)
    agent.discover(path)
    jid = agent.store.list_jobs()[0]["id"]
    state = DiscoveryState(agent.store, clock=clock)
    agent.discover(path, refresh=True)
    assert state.availability(jid)[0]["status"] == "closed"
    agent.discover(path, refresh=True)
    assert state.availability(jid)[0]["status"] == "reopened"


def test_long_retry_after_survives_transport_sanitization_and_restart(tmp_path, monkeypatch):
    from internship_agent import sources
    from internship_agent.discovery_state import DiscoveryState
    header = sources._retry_after("10000000000")
    assert header == "10000000000"
    store = Store(str(tmp_path / "ledger.db"))
    state = DiscoveryState(store)
    now = Clock()()
    run = state.begin("synthetic-source", "lever", now)
    state.fail(run["run_id"], "rate_limited", now, retry_after=header, http_status=429)
    retry = datetime.fromisoformat(state.health(now)[0]["next_retry_at"])
    assert retry >= now + timedelta(seconds=10000000000)


def test_actual_process_crash_rolls_back_page_before_restart(tmp_path):
    import subprocess
    import sys
    from internship_agent.discovery_state import DiscoveryState
    path = str(tmp_path / "crash-ledger.db")
    store = Store(path)
    state = DiscoveryState(store)
    now = Clock()()
    run = state.begin("fictional-source", "greenhouse", now)
    script = '''
import os, sys
from datetime import datetime
from internship_agent.store import Store
from internship_agent.discovery_state import DiscoveryState
from internship_agent.discovery_types import SourcePage
from internship_agent.models import Job
store = Store(sys.argv[1])
original = store._upsert_job
def crash(connection, job):
    original(connection, job)
    os._exit(23)
store._upsert_job = crash
job = Job(id="fictional-job",provider="greenhouse",company="Example",source_id="one",title="Intern",location="",description="Fictional",job_url="https://example.com/jobs/one",apply_url="https://example.com/jobs/one")
DiscoveryState(store).commit_page(sys.argv[2],SourcePage([job]),datetime.fromisoformat(sys.argv[3]))
'''
    child = subprocess.run([sys.executable, "-c", script, path, run["run_id"], now.isoformat()], capture_output=True, timeout=30)
    assert child.returncode == 23, child.stderr.decode(errors="replace")
    recovered = Store(path)
    assert recovered.list_jobs() == []
    with recovered.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    recovery = DiscoveryState(recovered)
    assert recovery.scans()[0]["page_count"] == 0
    replacement = recovery.begin("fictional-source", "greenhouse", now + timedelta(seconds=301))
    assert replacement["run_id"] != run["run_id"]
    assert any(scan["status"] == "interrupted" for scan in recovery.scans())


@pytest.mark.parametrize("code", ["gone", "redirect_blocked"])
def test_safe_source_failure_categories_survive_restart(tmp_path, monkeypatch, code):
    import internship_agent.service as service
    from internship_agent.sources import SourceError
    from internship_agent.discovery_state import DiscoveryState
    def fail(*a, **k):
        raise SourceError(code, "private response details", http_status=410 if code == "gone" else 302)
    monkeypatch.setattr(service, "retrieve_page", fail)
    clock = Clock()
    root = str(tmp_path / "db")
    report = Agent(root, clock=clock).discover(config(tmp_path))
    assert "private" not in json.dumps(report)
    state = DiscoveryState(Agent(root, clock=clock).store)
    assert state.health(clock())[0]["error_code"] == code


def test_cli_future_database_failure_is_actionable_and_does_not_change_it(tmp_path, monkeypatch, capsys):
    import sqlite3
    from internship_agent import cli
    root = tmp_path / "db"
    root.mkdir()
    path = root / "agent.db"
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA user_version=999")
    before = path.read_bytes()
    monkeypatch.setattr("sys.argv", ["internship-agent", "--data", str(root), "summary"])
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2
    assert "database" in capsys.readouterr().err.lower()
    assert path.read_bytes() == before
