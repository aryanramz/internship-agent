"""Legacy namespace/history preservation and serialized migrations, offline only."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from internship_agent.models import Job, stable_id
from internship_agent.store import SCHEMA, Store
from internship_agent.discovery_state import migrate


LEGACY_JOBS = """
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, company TEXT NOT NULL, source_id TEXT NOT NULL,
 title TEXT NOT NULL, location TEXT NOT NULL, description TEXT NOT NULL,
 job_url TEXT NOT NULL, canonical_url TEXT NOT NULL, apply_url TEXT NOT NULL, work_mode TEXT NOT NULL,
 published_at TEXT NOT NULL, compensation TEXT NOT NULL, discovered_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 UNIQUE(provider, company, source_id));
"""


def legacy(path):
    c = sqlite3.connect(path)
    c.executescript(LEGACY_JOBS + SCHEMA)
    jid = stable_id("manual", "first", "req-1")
    c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        jid, "manual", "Fictional Employer", "req-1", "Intern", "Fictional City", "Fictional work",
        "https://example.com/jobs/1", "https://example.com/jobs/1", "https://example.com/jobs/1", "Unknown",
        "", "", "2026-01-01", "2026-01-02"))
    c.execute("INSERT INTO applications(job_id,status,approved_at,submitted_at,submission_evidence,notes,updated_at) VALUES(?,'submitted','approved','submitted','FICTIONAL-CONFIRMATION','historical note','old')", (jid,))
    c.execute("INSERT INTO events(job_id,event_type,payload_json,created_at) VALUES(?,'submitted','{}','old')", (jid,))
    c.execute("CREATE INDEX idx_jobs_custom_company ON jobs(company)")
    c.commit()
    return c, jid


def snapshot(c):
    return {table: c.execute(f"SELECT * FROM {table}").fetchall() for table in ("jobs", "applications", "events")}


def test_legacy_uniqueness_migration_preserves_rows_and_allows_distinct_tokens(tmp_path):
    path = tmp_path / "legacy.db"
    c, first_id = legacy(path)
    before = snapshot(c)
    c.close()
    store = Store(str(path))
    with store.connection() as c:
        assert {table: [tuple(r) for r in c.execute(f"SELECT * FROM {table}")] for table in before} == before
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='idx_jobs_custom_company'").fetchone()
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    second = Job(id=stable_id("manual", "second", "req-1"), provider="manual", company="Fictional Employer",
                 source_id="req-1", title="Intern", location="", description="Fictional", job_url="https://example.com/jobs/1", apply_url="https://example.com/jobs/1")
    assert store.upsert_job(second) == "added"
    assert store.get_job(first_id)["status"] == "submitted"
    with store.connection() as c:
        assert [tuple(r) for r in c.execute("SELECT * FROM applications WHERE job_id=?", (first_id,))] == before["applications"]
        assert [tuple(r) for r in c.execute("SELECT * FROM events WHERE job_id=?", (first_id,))] == before["events"]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_concurrent_initial_upgrades_serialize_before_reading_version(tmp_path):
    path = tmp_path / "concurrent.db"
    c, _ = legacy(path)
    c.close()
    barrier = threading.Barrier(2)
    class Coordinated(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            cursor = super().execute(sql, *args, **kwargs)
            if sql.strip().upper() == "PRAGMA USER_VERSION" and not self.in_transaction:
                barrier.wait(timeout=5)
            return cursor
    def upgrade():
        connection = sqlite3.connect(path, timeout=10, factory=Coordinated)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            migrate(connection)
            connection.commit()
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(upgrade) for _ in range(2)]
        for result in results:
            result.result(timeout=20)


def test_nested_migration_remains_part_of_callers_transaction(tmp_path):
    c, jid = legacy(tmp_path / "nested.db")
    c.execute("UPDATE applications SET notes='pending' WHERE job_id=?", (jid,))
    migrate(c)
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    c.rollback()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0
    assert c.execute("SELECT notes FROM applications").fetchone()[0] == "historical note"
    c.close()


def test_rebuild_failure_rolls_back_schema_and_all_references(tmp_path):
    path = tmp_path / "rollback.db"
    c, _ = legacy(path)
    before = snapshot(c)
    c.close()
    class Broken(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("INSERT INTO jobs SELECT"):
                raise sqlite3.OperationalError("synthetic failure after dropping old table")
            return super().execute(sql, *args, **kwargs)
    broken = sqlite3.connect(path, factory=Broken)
    broken.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(sqlite3.OperationalError):
        migrate(broken)
    assert snapshot(broken) == before
    assert broken.execute("PRAGMA foreign_key_check").fetchall() == []
    assert broken.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert broken.execute("PRAGMA defer_foreign_keys").fetchone()[0] == 0
    assert broken.execute("PRAGMA user_version").fetchone()[0] == 0
    assert not broken.execute("SELECT name FROM sqlite_temp_master WHERE name='_discovery_jobs_copy'").fetchall()
    broken.close()


def test_version_one_upgrade_preserves_discovery_evidence_and_custom_trigger(tmp_path):
    from internship_agent.discovery_state import DDL
    path = tmp_path / "version-one.db"
    c, jid = legacy(path)
    for statement in DDL:
        c.execute(statement)
    c.execute("INSERT INTO discovery_sources(source_id,provider) VALUES('source','manual')")
    c.execute("INSERT INTO discovery_runs(run_id,logical_run_id,source_id,provider,status,started_at) VALUES('run','run','source','manual','complete','old')")
    c.execute("INSERT INTO discovery_job_sources(job_id,source_id,first_seen_at,last_seen_at,last_seen_run_id,status_at) VALUES(?,'source','old','old','run','old')", (jid,))
    c.execute("INSERT INTO discovery_evidence(job_id,source_id,run_id,kind,observed_at) VALUES(?,'source','run','observed','old')", (jid,))
    c.execute("CREATE TRIGGER preserve_custom_trigger AFTER UPDATE ON jobs BEGIN SELECT 1; END")
    c.execute("PRAGMA user_version=1")
    c.commit()
    before = snapshot(c)
    provenance = c.execute("SELECT * FROM discovery_job_sources").fetchall()
    evidence = c.execute("SELECT * FROM discovery_evidence").fetchall()
    c.close()
    with Store(str(path)).connection() as upgraded:
        assert {table: [tuple(r) for r in upgraded.execute(f"SELECT * FROM {table}")] for table in before} == before
        assert [tuple(r) for r in upgraded.execute("SELECT * FROM discovery_job_sources")] == provenance
        assert [tuple(r) for r in upgraded.execute("SELECT * FROM discovery_evidence")] == evidence
        assert upgraded.execute("SELECT 1 FROM sqlite_master WHERE name='preserve_custom_trigger'").fetchone()
        assert upgraded.execute("PRAGMA foreign_key_check").fetchall() == []
        assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 2


@pytest.mark.parametrize("target", ["jobs", "JOBS", "Jobs"])
@pytest.mark.parametrize("action", ["CASCADE", "SET NULL"])
def test_custom_delete_actions_fail_without_mutating_any_history(tmp_path, target, action):
    c, jid = legacy(tmp_path / "custom.db")
    c.execute(f"CREATE TABLE custom_history(job_id TEXT REFERENCES {target}(id) ON DELETE {action})")
    c.execute("INSERT INTO custom_history VALUES(?)", (jid,))
    c.commit()
    before = snapshot(c)
    with pytest.raises(ValueError, match="delete actions"):
        migrate(c)
    assert snapshot(c) == before
    assert c.execute("SELECT job_id FROM custom_history").fetchone()[0] == jid
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0
    c.close()
