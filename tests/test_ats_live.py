"""Opt-in, credential-free public API validation. Never runs in ordinary CI."""
import json
import os
import re
import time

import pytest

from internship_agent.service import Agent


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE_ATS") != "1", reason="Set RUN_LIVE_ATS=1 to allow public API requests")
def test_greenhouse_live_ingestion_and_repeat_run(tmp_path):
    # Fixed provider host/token: no applicant config, authentication or page crawling.
    config = tmp_path / "boards.json"
    config.write_text(json.dumps({"boards": [{
        "provider": "greenhouse", "token": "greenhouse", "company": "Greenhouse"
    }]}), encoding="utf-8")
    agent = Agent(str(tmp_path / "ledger"))
    first = agent.discover(str(config))
    assert not first["errors"], first["errors"]
    assert first["added"] > 0, "Public board is empty; select/revalidate a populated board before claiming live success"
    rows = agent.store.list_jobs(10000)
    original_ids = {r["id"] for r in rows}
    assert len(rows) == first["added"]
    for row in rows:
        assert row["provider"] == "greenhouse"
        assert row["source_id"].isdigit()
        assert row["title"] and row["description"]
        assert row["job_url"].startswith("https://")
        assert row["apply_url"] == row["job_url"]
        assert not re.search(r"</?(?:p|div|script)\b|&lt;/?(?:p|div|script)\b", row["description"])
    time.sleep(1)  # Two serial requests; no retries, details or redirects.
    second = agent.discover(str(config))
    assert not second["errors"], second["errors"]
    assert second["added"] == 0, "Board changed between snapshots; inspect before rerunning"
    assert second["updated"] == first["added"], "Board changed between snapshots"
    assert {r["id"] for r in agent.store.list_jobs(10000)} == original_ids
    with agent.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == len(rows)
    # Counts only: never emit employer descriptions, names or applicant records.
    print(f"Live Greenhouse: first added={first['added']}; repeat added={second['added']}, updated={second['updated']}")
