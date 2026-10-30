"""Offline persistence regression tests; every job and database is fictional."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import importlib.util
import sqlite3
import pytest

from internship_agent.models import Job
from internship_agent.store import Store, SCHEMA

NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)

@dataclass
class Page:
    jobs: tuple = ()
    next_cursor: dict | None = None
    complete: bool = True
    authoritative: bool = False
    raw_count: int = 0
    rejected_count: int = 0
    closed: tuple = ()

def implementation():
    assert importlib.util.find_spec('internship_agent.discovery_state'), 'Discovery persistence is missing'
    from internship_agent.discovery_state import DiscoveryState, migrate
    return DiscoveryState, migrate

@pytest.fixture
def state(tmp_path):
    cls, migrate = implementation()
    store = Store(str(tmp_path / 'synthetic.sqlite3'))
    with store.connection() as c:
        migrate(c)
    return cls(store), store

def job(n='1', url=None):
    return Job(n, 'greenhouse', 'Fictional', n, 'Intern', 'Remote', 'Synthetic role',
               url or f'https://fictional.example/jobs/{n}', f'https://fictional.example/apply/{n}')

def begin(state, now=NOW, source='fictional', provider='greenhouse', **kw):
    return state.begin(source, provider, now, **kw)


def test_migration_is_additive_and_rejects_future_versions(tmp_path):
    _, migrate = implementation()
    c = sqlite3.connect(tmp_path / 'legacy.sqlite3')
    c.executescript(SCHEMA)
    c.execute("INSERT INTO events(event_type,payload_json,created_at) VALUES('legacy','{}','old')")
    c.commit()
    migrate(c)
    migrate(c)
    assert c.execute('PRAGMA user_version').fetchone()[0] == 1
    assert c.execute('SELECT event_type,payload_json,created_at FROM events').fetchall() == [('legacy', '{}', 'old')]
    c.execute('PRAGMA user_version=2')
    before = c.execute('SELECT name FROM sqlite_master').fetchall()
    with pytest.raises(ValueError, match='version'):
        migrate(c)
    assert c.execute('SELECT name FROM sqlite_master').fetchall() == before


def test_migration_rolls_back_all_ddl_and_version(tmp_path):
    _, migrate = implementation()
    class Broken(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if 'CREATE TABLE' in sql and 'discovery_runs' in sql:
                raise sqlite3.OperationalError('synthetic DDL failure')
            return super().execute(sql, *args, **kwargs)
    c = sqlite3.connect(tmp_path / 'rollback.sqlite3', factory=Broken)
    c.executescript(SCHEMA)
    with pytest.raises(sqlite3.OperationalError):
        migrate(c)
    assert c.execute('PRAGMA user_version').fetchone()[0] == 0
    assert not c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'discovery_%'").fetchall()


def test_atomic_page_checkpoint_and_restart(state, monkeypatch):
    ds, store = state
    run = begin(ds)
    original = store._upsert_job
    def broken(c, item):
        result = original(c, item)
        if item.id == '2':
            raise RuntimeError('synthetic transaction failure')
        return result
    monkeypatch.setattr(store, '_upsert_job', broken)
    with pytest.raises(RuntimeError):
        ds.commit_page(run['run_id'], Page((job(), job('2')), {'offset': 2}, False), NOW)
    assert store.list_jobs() == []
    assert ds.scans()[0]['page_count'] == 0
    assert ds.availability() == []
    monkeypatch.setattr(store, '_upsert_job', original)
    assert ds.commit_page(run['run_id'], Page((job(),), {'offset': 1}, False), NOW) == {'added': 1, 'updated': 0, 'duplicate': 0}
    ds.pause(run['run_id'], NOW)
    new = type(ds)(Store(str(store.path)))
    assert begin(new, NOW + timedelta(seconds=59), refresh=True)['skip_reason'] == 'cooldown'
    resumed = begin(new, NOW + timedelta(seconds=60))
    assert resumed['cursor'] == {'offset': 1}
    assert resumed['logical_run_id'] == run['logical_run_id']
    assert resumed['run_id'] != run['run_id']
    new.commit_page(resumed['run_id'], Page((job('2'),), authoritative=True), NOW + timedelta(seconds=60))
    assert len(store.list_jobs()) == 2
    with store.connection() as c:
        assert c.execute("SELECT count(*) FROM events WHERE event_type='discovered'").fetchone()[0] == 2


def test_expired_lease_fences_old_worker_and_preserves_cursor(state):
    ds, _ = state
    first = begin(ds)
    ds.commit_page(first['run_id'], Page((job(),), {'offset': 1}, False, True), NOW)
    assert begin(ds, NOW + timedelta(seconds=299), refresh=True)['skip_reason'] == 'busy'
    second = begin(ds, NOW + timedelta(seconds=300))
    assert second['run_id'] != first['run_id']
    assert second['cursor'] == {'offset': 1}
    for operation in [lambda: ds.commit_page(first['run_id'], Page((job('stale'),)), NOW + timedelta(seconds=300)),
                      lambda: ds.pause(first['run_id'], NOW + timedelta(seconds=300)),
                      lambda: ds.fail(first['run_id'], 'network', NOW + timedelta(seconds=300))]:
        with pytest.raises(ValueError, match='lease|active|stale'):
            operation()
    assert any(row['status'] == 'interrupted' for row in ds.scans())
    assert ds.health(NOW + timedelta(seconds=300))[0]['interruptions'] == 1


@pytest.mark.parametrize('retry_after,seconds', [('1', 1800), ('7200', 7200), ('Fri, 02 Jan 2026 15:00:00 GMT', 10800)])
def test_rate_limit_boundary_and_refresh_cannot_bypass(state, retry_after, seconds):
    ds, _ = state
    run = begin(ds)
    ds.fail(run['run_id'], 'http_error', NOW, retry_after=retry_after, http_status=429)
    expected = NOW + timedelta(seconds=seconds)
    assert datetime.fromisoformat(ds.health(NOW)[0]['next_retry_at']) == expected
    assert begin(ds, expected - timedelta(seconds=1), refresh=True)['skip_reason'] == 'cooldown'
    assert 'run_id' in begin(ds, expected, refresh=True)


def test_healthy_empty_partial_failed_backoff_and_sanitized_errors(state):
    ds, _ = state
    run = begin(ds)
    ds.commit_page(run['run_id'], Page(authoritative=True), NOW)
    assert ds.health(NOW)[0]['status'] == 'healthy_empty'
    assert begin(ds, NOW + timedelta(seconds=1799))['skip_reason'] == 'cooldown'
    again = begin(ds, NOW + timedelta(seconds=1), refresh=True)
    ds.fail(again['run_id'], 'https://user:secret@example.com/private?token=raw', NOW + timedelta(seconds=1))
    failed = ds.health(NOW + timedelta(seconds=1))[0]
    assert failed['status'] == 'failed'
    assert failed['last_success_at']
    assert 'secret' not in str(failed)
    run = begin(ds, NOW + timedelta(seconds=61), refresh=True)
    ds.commit_page(run['run_id'], Page((job(),), {'offset': 1}, False), NOW + timedelta(seconds=61))
    ds.fail(run['run_id'], 'network', NOW + timedelta(seconds=61))
    health = ds.health(NOW + timedelta(seconds=61))[0]
    assert health['status'] == 'degraded'
    assert datetime.fromisoformat(health['next_retry_at']) == NOW + timedelta(seconds=181)
    assert any(event['error_code'] == 'network' for event in ds.scans())


def test_absence_closure_and_authoritative_reopen_preserve_history(state):
    ds, store = state
    initial = begin(ds)
    ds.commit_page(initial['run_id'], Page((job(), job('2'), job('3')), authoritative=True), NOW)
    store.set_prepared('1', 'synthetic-resume', 'synthetic-letter')
    store.approve('1', 'APPROVE 1')
    store.mark_submitted('1', 'synthetic-confirmation')
    store.set_prepared('2', 'synthetic-resume', 'synthetic-letter')
    store.approve('2', 'APPROVE 2')
    store.set_prepared('3', 'synthetic-resume', 'synthetic-letter')
    with store.connection() as c:
        applications = [tuple(row) for row in c.execute('SELECT * FROM applications ORDER BY job_id')]
        events = [tuple(row) for row in c.execute('SELECT * FROM events ORDER BY id')]
    empty = begin(ds, NOW + timedelta(seconds=1), refresh=True)
    ds.commit_page(empty['run_id'], Page(authoritative=True), NOW + timedelta(seconds=1))
    assert ds.availability('1')[0]['status'] == 'unknown'
    closed = begin(ds, NOW + timedelta(seconds=2), refresh=True)
    ds.commit_page(closed['run_id'], Page(authoritative=True, closed=({'job_id': '1', 'deadline': '2026-01-01T00:00:00Z'},)), NOW + timedelta(seconds=2))
    assert ds.availability('1')[0]['status'] == 'closed'
    nonauthoritative = begin(ds, NOW + timedelta(seconds=3), refresh=True)
    ds.commit_page(nonauthoritative['run_id'], Page((job(),)), NOW + timedelta(seconds=3))
    assert ds.availability('1')[0]['status'] == 'closed'
    positive = begin(ds, NOW + timedelta(seconds=4), refresh=True)
    ds.commit_page(positive['run_id'], Page((job(),), authoritative=True), NOW + timedelta(seconds=4))
    assert ds.availability('1')[0]['status'] == 'reopened'
    with store.connection() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM applications ORDER BY job_id')] == applications
        assert [tuple(row) for row in c.execute('SELECT * FROM events ORDER BY id')] == events


def test_nonauthoritative_or_rejected_snapshot_does_not_supply_absence(state):
    ds, _ = state
    run = begin(ds)
    ds.commit_page(run['run_id'], Page((job(),), authoritative=True), NOW)
    for n, page in enumerate([Page(), Page(authoritative=True, rejected_count=1)], 1):
        run = begin(ds, NOW + timedelta(seconds=n), refresh=True)
        ds.commit_page(run['run_id'], page, NOW + timedelta(seconds=n))
        assert ds.availability('1')[0]['status'] == 'available'


def test_unsafe_url_is_omitted_and_shared_url_candidates_do_not_merge(state):
    ds, store = state
    run = begin(ds)
    ds.commit_page(run['run_id'], Page((job('1', 'https://fictional.example/same?utm_source=one'), job('2', 'https://fictional.example/same?utm_source=two'), job('3', 'https://user:password@fictional.example/private')), authoritative=True), NOW)
    assert len(store.list_jobs()) == 3
    one = ds.availability('1')[0]
    assert '2' in one['canonical_matches']
    assert ds.availability('3')[0]['sources'][0]['canonical_url'] == ''
    assert 'password' not in str(ds.availability())


def test_read_only_store_never_migrates_legacy_database(tmp_path):
    implementation()
    path = tmp_path / 'readonly.sqlite3'
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.close()
    store = Store(str(path), read_only=True)
    assert store.list_jobs() == []
    c = sqlite3.connect(path)
    assert c.execute('PRAGMA user_version').fetchone()[0] == 0
    assert not c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'discovery_%'").fetchall()

def test_nonauthoritative_positive_retains_deadline_reason(state):
    ds, _ = state
    run = begin(ds)
    ds.commit_page(run['run_id'], Page((job(),), authoritative=True), NOW)
    run = begin(ds, NOW + timedelta(seconds=1), refresh=True)
    ds.commit_page(run['run_id'], Page(closed=({'job_id': '1', 'deadline': '2026-01-01T00:00:00Z'},)), NOW + timedelta(seconds=1))
    closed_at = ds.availability('1')[0]['sources'][0]['status_at']
    run = begin(ds, NOW + timedelta(seconds=2), refresh=True)
    ds.commit_page(run['run_id'], Page((job(),)), NOW + timedelta(seconds=2))
    evidence = ds.availability('1')[0]['sources'][0]
    assert evidence['status'] == 'closed'
    assert evidence['reason'] == 'application_deadline'
    assert evidence['status_at'] == closed_at


def test_candidates_include_legacy_jobs_without_discovery_provenance(state):
    ds, store = state
    store.upsert_job(job('legacy', 'https://fictional.example/shared'))
    run = begin(ds)
    ds.commit_page(run['run_id'], Page((job('new', 'https://fictional.example/shared?utm_source=fake'),)), NOW)
    assert ds.availability('new')[0]['canonical_matches'] == ['legacy']
    assert ds.availability('legacy')[0]['canonical_matches'] == ['new']


def test_failure_backoff_cap_and_very_long_retry_header(state):
    ds, _ = state
    clock = NOW
    for failure in range(1, 15):
        run = begin(ds, clock, refresh=True)
        ds.fail(run['run_id'], 'network_error', clock)
        next_retry = datetime.fromisoformat(ds.health(clock)[0]['next_retry_at'])
        assert (next_retry - clock).total_seconds() == min(86400, 60 * 2 ** (failure - 1))
        clock = next_retry
    run = begin(ds, clock)
    ds.fail(run['run_id'], 'rate_limited', clock, retry_after='9' * 5000, http_status=429)
    assert datetime.fromisoformat(ds.health(clock)[0]['next_retry_at']) > clock + timedelta(days=365)


def test_checkpoint_pages_cannot_grant_absence_after_nonauthoritative_page(state):
    ds, _ = state
    run = begin(ds)
    ds.commit_page(run['run_id'], Page((job(),), authoritative=True), NOW)
    run = begin(ds, NOW + timedelta(seconds=1), refresh=True)
    ds.commit_page(run['run_id'], Page(next_cursor={'offset': 1}, complete=False), NOW + timedelta(seconds=1))
    ds.pause(run['run_id'], NOW + timedelta(seconds=1))
    resumed = begin(ds, NOW + timedelta(seconds=61))
    ds.commit_page(resumed['run_id'], Page(authoritative=True), NOW + timedelta(seconds=61))
    assert ds.availability('1')[0]['status'] == 'available'


def test_only_previously_observed_same_source_greenhouse_past_deadline_closes(state):
    ds, _ = state
    run = begin(ds)
    ds.commit_page(run['run_id'], Page((job(), job('2')), authoritative=True), NOW)
    run = begin(ds, NOW, source='different-source')
    ds.commit_page(run['run_id'], Page(closed=({'job_id': '1', 'deadline': '2026-01-01T00:00:00Z'},)), NOW)
    assert ds.availability('1')[0]['status'] == 'available'
    run = begin(ds, NOW + timedelta(seconds=1), refresh=True)
    ds.commit_page(run['run_id'], Page((job('3'),), closed=(
        {'job_id': '1', 'deadline': '2999-01-01T00:00:00Z'},
        {'job_id': '2', 'deadline': 'garbage'},
        {'job_id': '3', 'deadline': '2026-01-01T00:00:00Z'})), NOW + timedelta(seconds=1))
    assert {row['status'] for row in ds.availability()} == {'available'}
    lever = begin(ds, NOW, source='lever-source', provider='lever')
    ds.commit_page(lever['run_id'], Page((job(),)), NOW)
    lever = begin(ds, NOW + timedelta(seconds=1), source='lever-source', provider='lever', refresh=True)
    ds.commit_page(lever['run_id'], Page(closed=({'job_id': '1', 'deadline': '2026-01-01T00:00:00Z'},)), NOW + timedelta(seconds=1))
    assert all(source['status'] != 'closed' for source in ds.availability('1')[0]['sources'])


def test_concurrent_begin_has_only_one_active_lease(state):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    ds, _ = state
    barrier = Barrier(2)
    def contend():
        barrier.wait(timeout=5)
        return begin(ds)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: contend(), range(2)))
    assert sum('run_id' in result for result in results) == 1
    assert sum(result.get('skip_reason') == 'busy' for result in results) == 1


def test_expired_lease_rejects_commit_without_takeover_and_stale_is_separate(state):
    ds, store = state
    run = begin(ds)
    with pytest.raises(ValueError, match='lease'):
        ds.commit_page(run['run_id'], Page((job(),)), NOW + timedelta(minutes=5))
    fresh = begin(ds, NOW + timedelta(minutes=5))
    ds.commit_page(fresh['run_id'], Page((job(),), authoritative=True), NOW + timedelta(minutes=5))
    assert ds.availability('1')[0]['stale'] is True  # fictional observation is months old
    assert store.get_job('1')['status'] == 'discovered'
    assert ds.health(NOW + timedelta(days=8))[0]['stale'] is True

def test_iso_retry_after_and_rate_limited_health(state):
    ds, _ = state
    run = begin(ds)
    deadline = NOW + timedelta(hours=3)
    ds.fail(run['run_id'], 'rate_limited', NOW, retry_after=deadline.isoformat(), http_status=429)
    row = ds.health(NOW)[0]
    assert datetime.fromisoformat(row['next_retry_at']) == deadline
    assert row['status'] == 'rate_limited'
    assert row['retry_eligible'] is False
    assert ds.health(deadline)[0]['retry_eligible'] is True


@pytest.mark.parametrize('code', ['snapshot_changed', 'invalid_cursor'])
def test_invalidated_checkpoint_starts_new_logical_scan(state, code):
    ds, _ = state
    first = begin(ds)
    ds.commit_page(first['run_id'], Page((job(),), {'offset': 1, 'total': 2}, False, True), NOW)
    ds.fail(first['run_id'], code, NOW)
    next_run = begin(ds, NOW + timedelta(seconds=60))
    assert next_run['cursor'] is None
    assert next_run['page_count'] == 0
    assert next_run['logical_run_id'] != first['logical_run_id']
    assert any(row['error_code'] == code for row in ds.scans())


def test_healthy_empty_refresh_and_retry_eligible(state):
    ds, _ = state
    first = begin(ds)
    assert ds.health(NOW)[0]['retry_eligible'] is False
    assert ds.health(NOW + timedelta(minutes=5))[0]['retry_eligible'] is True
    ds.commit_page(first['run_id'], Page(), NOW)
    row = ds.health(NOW)[0]
    assert row['status'] == 'healthy_empty'
    assert row['retry_eligible'] is False
    assert ds.health(NOW + timedelta(minutes=30))[0]['retry_eligible'] is True
    assert 'run_id' in begin(ds, NOW + timedelta(seconds=1), refresh=True)


def test_availability_uses_injected_clock(state):
    ds, store = state
    first = begin(ds)
    ds.commit_page(first['run_id'], Page((job(),)), NOW)
    clock = [NOW]
    reporting = type(ds)(store, clock=lambda: clock[0])
    assert reporting.availability('1')[0]['stale'] is False
    clock[0] = NOW + timedelta(days=7)
    assert reporting.availability('1')[0]['stale'] is True
