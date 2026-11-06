"""Additive workflow migrations preserve legacy rows, objects and discovery state."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from internship_agent.store import Store, SCHEMA
from internship_agent.discovery_state import migrate as discovery_migrate
from internship_agent import workflow_schema


def legacy(path):
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    discovery_migrate(c)
    c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              ('historical', 'synthetic', 'Fictional', 'one', 'Intern', 'Example', 'Python',
               'https://example.test/one', 'https://example.test/one', 'https://example.test/one',
               'Unknown', '', '', 'old', 'old'))
    c.execute("INSERT INTO applications(job_id,status,approved_at,submitted_at,submission_evidence,notes,updated_at) VALUES('historical','offer','old-approved','old-submitted','Fictional evidence','preserved note','old')")
    c.execute("INSERT INTO events(job_id,event_type,payload_json,created_at) VALUES('historical','submitted','{}','old')")
    c.execute('CREATE INDEX idx_application_notes ON applications(notes)')
    c.execute('CREATE TRIGGER preserve_application_history AFTER UPDATE ON applications BEGIN SELECT 1; END')
    c.commit()
    return c


def rows(c):
    return {table: [tuple(r) for r in c.execute('SELECT * FROM ' + table)]
            for table in ('jobs', 'applications', 'events', 'discovery_runs', 'discovery_sources')}


def test_upgrade_preserves_legacy_history_ids_indexes_triggers_and_read_only_access(tmp_path):
    path = tmp_path / 'legacy.db'
    c = legacy(path)
    before = rows(c)
    c.close()
    reader = Store(str(path), read_only=True)
    assert reader.get_job('historical')['submission_evidence_kind'] == 'legacy_user_supplied'
    assert reader.application_report('historical')['preparations'] == []
    for _ in range(2):
        store = Store(str(path))
        with store.connection() as c:
            assert rows(c) == before
            assert c.execute('PRAGMA user_version').fetchone()[0] == 3  # Pre-workflow writers reject this version.
            assert c.execute('SELECT version FROM workflow_schema').fetchone()[0] == 1
            assert c.execute('PRAGMA foreign_key_check').fetchall() == []
            assert c.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('idx_application_notes','preserve_application_history')").fetchone()[0] == 2
    with pytest.raises(ValueError):
        store.mark_submitted('historical', 'New evidence', approval_token='legacy')
    assert store.get_job('historical')['status'] == 'offer'


def test_migration_failure_rolls_back_all_new_schema_and_preserves_history(tmp_path, monkeypatch):
    c = legacy(tmp_path / 'rollback.db')
    before = rows(c)
    monkeypatch.setattr(workflow_schema, 'DDL', (*workflow_schema.DDL, 'INVALID SQL'))
    with pytest.raises(sqlite3.Error):
        workflow_schema.migrate(c)
    assert rows(c) == before
    assert c.execute("SELECT name FROM sqlite_master WHERE name IN ('workflow_schema','preparation_operations','application_bindings','submission_records')").fetchall() == []
    assert c.execute('PRAGMA user_version').fetchone()[0] == 2
    c.close()


def test_parallel_upgrade_serializes_and_future_workflow_version_is_rejected(tmp_path):
    path = tmp_path / 'parallel.db'
    c = legacy(path)
    before = rows(c)
    c.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: Store(str(path)), range(4)))
    with sqlite3.connect(path) as c:
        assert rows(c) == before
        c.execute('UPDATE workflow_schema SET version=999')
    with pytest.raises(ValueError):
        Store(str(path))
    with sqlite3.connect(path) as c:
        assert rows(c) == before
        assert c.execute('SELECT version FROM workflow_schema').fetchone()[0] == 999


def test_migration_does_not_commit_callers_outer_transaction(tmp_path):
    c = legacy(tmp_path / 'outer.db')
    before = rows(c)
    c.execute("UPDATE applications SET notes='pending transaction'")
    workflow_schema.migrate(c)
    assert c.in_transaction
    c.rollback()
    assert rows(c) == before
    assert c.execute("SELECT name FROM sqlite_master WHERE name='workflow_schema'").fetchall() == []
    c.close()
