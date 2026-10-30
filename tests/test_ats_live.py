"""Opt-in credential-free qualification: exactly two serial public GETs per board."""
from datetime import datetime, timezone
import json
import os
import re
import time

import pytest

from internship_agent import sources
from internship_agent.models import validate_board
from internship_agent.service import Agent


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE_ATS") != "1", reason="Set RUN_LIVE_ATS=1 to allow public API requests")
@pytest.mark.parametrize("provider,token,company", [
    ("greenhouse", "greenhouse", "Greenhouse"),
    ("lever", "palantir", "Palantir"),
    ("ashby", "Ashby", "Ashby"),
])
def test_live_ingestion_and_repeat_preserves_history(tmp_path, monkeypatch, provider, token, company):
    # Fixed published public boards: no credentials, detail pages or submissions.
    board = {"provider": provider, "token": token, "company": company}
    canonical = validate_board(board)
    assert all(canonical[field] == board[field] for field in ("provider", "token", "company"))
    requests = []
    original_opener, original_get = sources.build_opener, sources.get_bytes

    class Observer:
        def __init__(self, opener):
            self.opener = opener

        def open(self, request, timeout):
            # Observe the real response; retain production no-redirect behavior.
            response = self.opener.open(request, timeout=timeout)
            requests.append({"at": datetime.now(timezone.utc).isoformat(), "http_status": response.status})
            return response

    monkeypatch.setattr(sources, "build_opener", lambda *handlers: Observer(original_opener(*handlers)))

    def observe_bytes(url, *args, **kwargs):
        raw = original_get(url, *args, **kwargs)
        payload = json.loads(raw)
        postings = payload if provider == "lever" else payload["jobs"]
        requests[-1].update(bytes=len(raw), raw_count=len(postings), field_presence={
            field: sum(field in row and row[field] is not None and row[field] != "" for row in postings)
            for field in ("id", "content", "descriptionPlain", "additionalPlain", "lists", "first_published", "publishedAt", "createdAt")
        })
        return raw

    monkeypatch.setattr(sources, "get_bytes", observe_bytes)
    config = tmp_path / "boards.json"
    config.write_text(json.dumps({"boards": [board]}), encoding="utf-8")
    agent = Agent(str(tmp_path / "ledger"))
    first = agent.discover(str(config))
    assert not first["errors"], first["errors"]
    assert first["added"] >= 2, "Public board needs two postings to qualify both preparation states"
    rows = agent.store.list_jobs(10000)
    original_ids = {row["id"] for row in rows}
    assert len(rows) == first["added"]
    assert all(row["provider"] == provider and row["source_id"] and row["title"] and row["description"] for row in rows)
    assert all(not re.search(r"</?(?:p|div|script)\b|&lt;/?(?:p|div|script)\b", row["description"]) for row in rows)
    for row in rows:
        sources._posting_url(row["job_url"])
        sources._posting_url(row["apply_url"])
    if provider == "greenhouse":
        assert all(row["source_id"].isdigit() and row["apply_url"] == row["job_url"] for row in rows)
    if provider == "lever":
        assert all(row["published_at"] == "" for row in rows), "createdAt is not documented publication evidence"
    else:
        assert all(row["published_at"] for row in rows)

    ids = sorted(original_ids)[:2]
    for jid in ids:
        agent.store.set_prepared(jid, "fictional-qualification-resume.docx", "fictional-qualification-letter.docx")
    agent.store.approve(ids[1], f"APPROVE {ids[1]}")
    approved_at = agent.store.get_job(ids[1])["approved_at"]
    with agent.store.connection() as connection:
        before_events = [tuple(row) for row in connection.execute("SELECT * FROM events ORDER BY id")]
    time.sleep(1)  # Two serial requests; no retries or redirects.
    second = agent.discover(str(config))
    assert not second["errors"], second["errors"]
    assert second["added"] == 0 and second["updated"] == first["added"], "Board changed; inspect without blind reruns"
    assert {row["id"] for row in agent.store.list_jobs(10000)} == original_ids
    assert agent.store.get_job(ids[0])["status"] == "prepared"
    assert agent.store.get_job(ids[1])["status"] == "approved"
    assert agent.store.get_job(ids[1])["approved_at"] == approved_at
    with agent.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == len(rows)
        assert [tuple(row) for row in connection.execute("SELECT * FROM events ORDER BY id")] == before_events
    assert len(requests) == 2
    # Metadata only; never emit posting text, contact details, job IDs or ledger rows.
    print(json.dumps({"provider": provider, "requests": requests, "normalized": len(rows),
                      "description_nonempty": sum(bool(row["description"]) for row in rows),
                      "published_nonempty": sum(bool(row["published_at"]) for row in rows),
                      "repeat_added": second["added"], "repeat_updated": second["updated"],
                      "stable_ids": True, "prepared_approved_and_events_preserved": True}))
