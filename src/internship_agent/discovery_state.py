"""Transactional discovery checkpoints and availability evidence.

A run ID is a single lease attempt, not a reusable logical scan identity. Resumed
attempts share logical_run_id while retaining their own immutable audit rows.
Application status and application events are never changed by this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

from .models import canonical_url

VERSION = 1
AUTHORITATIVE_PROVIDERS = frozenset({'greenhouse', 'lever', 'ashby'})
ERROR_CODES = frozenset({'network', 'network_error', 'http_error', 'rate_limited',
    'forbidden', 'not_found', 'unauthorized', 'invalid_payload', 'invalid_posting',
    'response_too_large', 'invalid_cursor', 'snapshot_changed', 'source_error',
    'configuration_error', 'invalid_configuration', 'internal_error', 'gone',
    'redirect_blocked', 'interrupted', 'unknown_error'})

DDL = (
    """CREATE TABLE discovery_sources (
        source_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
        latest_run_id TEXT, status TEXT NOT NULL DEFAULT 'unknown',
        last_attempt_at TEXT, last_success_at TEXT, next_retry_at TEXT,
        failure_count INTEGER NOT NULL DEFAULT 0,
        interruptions INTEGER NOT NULL DEFAULT 0,
        error_code TEXT, http_status INTEGER)""",
    """CREATE TABLE discovery_runs (
        run_id TEXT PRIMARY KEY, logical_run_id TEXT NOT NULL,
        source_id TEXT NOT NULL REFERENCES discovery_sources(source_id),
        provider TEXT NOT NULL, status TEXT NOT NULL,
        started_at TEXT NOT NULL, completed_at TEXT, lease_expires_at TEXT,
        cursor_json TEXT, page_count INTEGER NOT NULL DEFAULT 0,
        accepted_count INTEGER NOT NULL DEFAULT 0,
        rejected_count INTEGER NOT NULL DEFAULT 0,
        raw_count INTEGER NOT NULL DEFAULT 0,
        added_count INTEGER NOT NULL DEFAULT 0,
        updated_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        authoritative INTEGER NOT NULL DEFAULT 1,
        error_code TEXT, http_status INTEGER, next_retry_at TEXT,
        predecessor_run_id TEXT)""",
    'CREATE INDEX idx_discovery_runs_source ON discovery_runs(source_id, started_at)',
    """CREATE TABLE discovery_scan_events (
        id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES discovery_runs(run_id),
        status TEXT NOT NULL, created_at TEXT NOT NULL, error_code TEXT, http_status INTEGER)""",
    """CREATE TABLE discovery_job_sources (
        job_id TEXT NOT NULL REFERENCES jobs(id),
        source_id TEXT NOT NULL REFERENCES discovery_sources(source_id),
        canonical_url TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL, last_seen_run_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'available', reason TEXT NOT NULL DEFAULT 'observed',
        status_at TEXT NOT NULL, PRIMARY KEY(job_id, source_id))""",
    'CREATE INDEX idx_discovery_provenance_url ON discovery_job_sources(canonical_url)',
    """CREATE TABLE discovery_evidence (
        id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
        source_id TEXT NOT NULL REFERENCES discovery_sources(source_id),
        run_id TEXT NOT NULL REFERENCES discovery_runs(run_id),
        kind TEXT NOT NULL, observed_at TEXT NOT NULL, deadline TEXT)""",
    'CREATE INDEX idx_discovery_evidence_job ON discovery_evidence(job_id, id)',
)


def migrate(connection: sqlite3.Connection) -> None:
    """Add version-one tables atomically without touching the baseline ledger."""
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > VERSION:
        raise ValueError('Unsupported discovery schema version')
    if version == VERSION:
        return
    # executescript implicitly commits; individual DDL inside a savepoint does not.
    connection.execute('SAVEPOINT discovery_migration')
    try:
        for statement in DDL:
            connection.execute(statement)
        connection.execute('PRAGMA user_version=1')
        connection.execute('RELEASE SAVEPOINT discovery_migration')
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT discovery_migration')
        connection.execute('RELEASE SAVEPOINT discovery_migration')
        raise


def _time(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Discovery clock must be timezone-aware')
    return now.astimezone(timezone.utc)


def _iso(now: datetime) -> str:
    return _time(now).isoformat(timespec='microseconds')


def _parse(value: str) -> datetime:
    return _time(datetime.fromisoformat(value.replace('Z', '+00:00')))


def _limit(value: int) -> int:
    return max(1, min(int(value), 1000))


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return ''
        return canonical_url(value)
    except ValueError:
        return ''


def _cursor(value: dict | None) -> str | None:
    if value is None:
        return None
    # Only validated numeric checkpoints are currently supported by retrieval.
    # Keep endpoint URLs, response fragments and credentials out of diagnostics.
    if (not isinstance(value, dict) or len(value) > 10 or
            any(not isinstance(k, str) or not k.isidentifier() or len(k) > 40 or
                not isinstance(v, int) or isinstance(v, bool) or v < 0
                for k, v in value.items())):
        raise ValueError('Invalid discovery checkpoint')
    return json.dumps(value, sort_keys=True)


def _row(row) -> dict:
    out = dict(row)
    if 'cursor_json' in out:
        value = out.pop('cursor_json')
        out['cursor'] = json.loads(value) if value else None
    if 'authoritative' in out:
        out['authoritative'] = bool(out['authoritative'])
    return out


class DiscoveryState:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _event(self, c, run_id, status, stamp, code=None, http_status=None):
        c.execute('INSERT INTO discovery_scan_events(run_id,status,created_at,error_code,http_status) VALUES(?,?,?,?,?)',
                  (run_id, status, stamp, code, http_status))

    def _active(self, c, run_id: str, now: datetime):
        run = c.execute('''SELECT r.* FROM discovery_runs r JOIN discovery_sources s
            ON s.source_id=r.source_id WHERE r.run_id=? AND r.status='running'
            AND s.latest_run_id=r.run_id''', (run_id,)).fetchone()
        if run is None or _parse(run['lease_expires_at']) <= _time(now):
            raise ValueError('Stale or expired discovery lease')
        return run

    def begin(self, source_id: str, provider: str, now: datetime, refresh: bool = False) -> dict:
        now = _time(now)
        stamp = _iso(now)
        with self.store.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            source = c.execute('SELECT * FROM discovery_sources WHERE source_id=?', (source_id,)).fetchone()
            if source and source['provider'] != provider:
                raise ValueError('Discovery source provider changed')
            previous = None
            if source:
                previous = c.execute('SELECT * FROM discovery_runs WHERE run_id=?', (source['latest_run_id'],)).fetchone()
                if previous and previous['status'] == 'running':
                    if _parse(previous['lease_expires_at']) > now:
                        return {'skip_reason': 'busy', 'next_retry_at': previous['lease_expires_at'], 'source_id': source_id}
                    c.execute("UPDATE discovery_runs SET status='interrupted',completed_at=?,error_code='interrupted' WHERE run_id=?", (stamp, previous['run_id']))
                    c.execute('UPDATE discovery_sources SET interruptions=interruptions+1 WHERE source_id=?', (source_id,))
                    self._event(c, previous['run_id'], 'interrupted', stamp, 'interrupted')
                elif source['next_retry_at'] and _parse(source['next_retry_at']) > now:
                    if not (refresh and source['status'] in {'healthy', 'healthy_empty'}):
                        return {'skip_reason': 'cooldown', 'next_retry_at': source['next_retry_at'], 'source_id': source_id}
            else:
                c.execute('INSERT INTO discovery_sources(source_id,provider) VALUES(?,?)', (source_id, provider))
            resumable = previous is not None and previous['status'] in {'running', 'partial', 'failed', 'interrupted'} and previous['cursor_json'] is not None
            run_id = uuid4().hex
            logical = previous['logical_run_id'] if resumable else run_id
            counters = ['page_count', 'accepted_count', 'rejected_count', 'raw_count', 'added_count', 'updated_count', 'duplicate_count', 'authoritative']
            values = [previous[name] for name in counters] if resumable else [0, 0, 0, 0, 0, 0, 0, 1]
            c.execute('''INSERT INTO discovery_runs(run_id,logical_run_id,source_id,provider,status,
                started_at,lease_expires_at,cursor_json,page_count,accepted_count,rejected_count,
                raw_count,added_count,updated_count,duplicate_count,authoritative,predecessor_run_id)
                VALUES(?,?,?,?,'running',?,?,?,?,?,?,?,?,?,?,?,?)''',
                (run_id, logical, source_id, provider, stamp, _iso(now + timedelta(minutes=5)),
                 previous['cursor_json'] if resumable else None, *values,
                 previous['run_id'] if previous else None))
            c.execute("UPDATE discovery_sources SET latest_run_id=?,status='running',last_attempt_at=? WHERE source_id=?", (run_id, stamp, source_id))
            self._event(c, run_id, 'running', stamp)
            return _row(c.execute('SELECT * FROM discovery_runs WHERE run_id=?', (run_id,)).fetchone())

    def _evidence(self, c, run, job_id, kind, stamp, deadline=None):
        c.execute('INSERT INTO discovery_evidence(job_id,source_id,run_id,kind,observed_at,deadline) VALUES(?,?,?,?,?,?)',
                  (job_id, run['source_id'], run['run_id'], kind, stamp, deadline))

    def commit_page(self, run_id: str, page, now: datetime) -> dict:
        now = _time(now)
        stamp = _iso(now)
        cursor = _cursor(page.next_cursor)
        if page.complete and cursor is not None:
            raise ValueError('Complete discovery page cannot have a resume cursor')
        if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in (page.raw_count, page.rejected_count)):
            raise ValueError('Invalid discovery page counters')
        counts = {'added': 0, 'updated': 0, 'duplicate': 0}
        with self.store.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            run = self._active(c, run_id, now)
            provider_authority = run['provider'] in AUTHORITATIVE_PROVIDERS
            positive_authority = bool(page.authoritative and provider_authority)
            authoritative = bool(run['authoritative'] and positive_authority and not page.rejected_count)
            # Closure applies only to requisitions already observed at this source.
            prior_ids = {r[0] for r in c.execute('SELECT job_id FROM discovery_job_sources WHERE source_id=?', (run['source_id'],))} if page.closed else set()
            for job in page.jobs:
                result = self.store._upsert_job(c, job)
                counts[result] += 1
                prior = c.execute('SELECT status,reason,status_at FROM discovery_job_sources WHERE source_id=? AND job_id=?', (run['source_id'], job.id)).fetchone()
                if prior and prior['status'] == 'closed':
                    status = 'reopened' if positive_authority else 'closed'
                else:
                    status = 'available'
                safe_url = _safe_url(job.job_url)
                reason = ('reopened' if status == 'reopened' else 'observed') if safe_url else 'unsafe_url'
                status_at = stamp
                if prior and status == 'closed':
                    reason, status_at = prior['reason'], prior['status_at']
                c.execute('''INSERT INTO discovery_job_sources(job_id,source_id,canonical_url,
                    first_seen_at,last_seen_at,last_seen_run_id,status,reason,status_at)
                    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,source_id) DO UPDATE SET
                    canonical_url=excluded.canonical_url,last_seen_at=excluded.last_seen_at,
                    last_seen_run_id=excluded.last_seen_run_id,status=excluded.status,
                    reason=excluded.reason,status_at=excluded.status_at''',
                    (job.id, run['source_id'], safe_url, stamp, stamp, run['logical_run_id'], status, reason, status_at))
                self._evidence(c, run, job.id, 'reopened' if status == 'reopened' else 'observed', stamp)
            if run['provider'] == 'greenhouse':
                for item in page.closed:
                    jid, deadline = item.get('job_id'), item.get('deadline')
                    if jid not in prior_ids or not isinstance(deadline, str):
                        continue
                    try:
                        closed_at = _parse(deadline)
                    except (ValueError, TypeError):
                        continue
                    if closed_at > now:
                        continue
                    c.execute("UPDATE discovery_job_sources SET status='closed',reason='application_deadline',status_at=? WHERE job_id=? AND source_id=?", (stamp, jid, run['source_id']))
                    self._evidence(c, run, jid, 'application_deadline', stamp, _iso(closed_at))
            c.execute('''UPDATE discovery_runs SET cursor_json=?,page_count=page_count+1,
                accepted_count=accepted_count+?,rejected_count=rejected_count+?,raw_count=raw_count+?,
                added_count=added_count+?,updated_count=updated_count+?,duplicate_count=duplicate_count+?,
                authoritative=?,lease_expires_at=? WHERE run_id=?''',
                (cursor, len(page.jobs), page.rejected_count, page.raw_count, counts['added'], counts['updated'], counts['duplicate'],
                 int(authoritative), _iso(now + timedelta(minutes=5)), run_id))
            if page.complete:
                if authoritative:
                    missing = c.execute('''SELECT job_id FROM discovery_job_sources WHERE source_id=?
                        AND last_seen_run_id<>? AND status NOT IN ('closed','unknown')''',
                        (run['source_id'], run['logical_run_id'])).fetchall()
                    for item in missing:
                        c.execute("UPDATE discovery_job_sources SET status='unknown',reason='snapshot_absence',status_at=? WHERE source_id=? AND job_id=?", (stamp, run['source_id'], item['job_id']))
                        self._evidence(c, run, item['job_id'], 'snapshot_absence', stamp)
                health = 'healthy' if run['accepted_count'] + len(page.jobs) else 'healthy_empty'
                self._finish(c, run, 'complete', health, stamp, _iso(now + timedelta(minutes=30)), success=True)
        return counts

    def _finish(self, c, run, status, health, stamp, retry, code=None, http_status=None, success=False):
        c.execute('''UPDATE discovery_runs SET status=?,completed_at=?,lease_expires_at=NULL,
            next_retry_at=?,error_code=?,http_status=? WHERE run_id=?''',
            (status, stamp, retry, code, http_status, run['run_id']))
        if success:
            c.execute('''UPDATE discovery_sources SET status=?,next_retry_at=?,last_success_at=?,
                failure_count=0,error_code=NULL,http_status=NULL WHERE source_id=?''',
                (health, retry, stamp, run['source_id']))
        else:
            c.execute('UPDATE discovery_sources SET status=?,next_retry_at=?,error_code=?,http_status=? WHERE source_id=?',
                      (health, retry, code, http_status, run['source_id']))
        self._event(c, run['run_id'], status, stamp, code, http_status)

    def pause(self, run_id: str, now: datetime) -> None:
        with self.store.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            run = self._active(c, run_id, now)
            delay = 60 if run['cursor_json'] else 1800
            self._finish(c, run, 'partial', 'degraded', _iso(now), _iso(_time(now) + timedelta(seconds=delay)))

    def fail(self, run_id: str, code: str, now: datetime, retry_after: str = '', http_status: int | None = None) -> None:
        now = _time(now)
        code = code if code in ERROR_CODES else 'source_error'
        if not isinstance(http_status, int) or isinstance(http_status, bool) or not 100 <= http_status <= 599:
            http_status = None
        with self.store.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            run = self._active(c, run_id, now)
            failures = c.execute('SELECT failure_count FROM discovery_sources WHERE source_id=?', (run['source_id'],)).fetchone()[0] + 1
            seconds = min(86400, 60 * 2 ** min(failures - 1, 11))
            if http_status == 429:
                seconds = max(seconds, 1800)
            retry = now + timedelta(seconds=seconds)
            # Retry-After is interpreted, never stored verbatim. Arbitrarily long
            # numeric restrictions are clamped only to datetime's representable max.
            try:
                raw = str(retry_after).strip()
                if raw.isascii() and raw.isdigit():
                    seconds = min(int(raw) if len(raw) < 15 else 10**14, 10**14)
                    try:
                        server_retry = now + timedelta(seconds=seconds)
                    except OverflowError:
                        server_retry = datetime.max.replace(tzinfo=timezone.utc)
                else:
                    try:
                        server_retry = _parse(raw)
                    except ValueError:
                        server_retry = _time(parsedate_to_datetime(raw))
                retry = max(retry, server_retry)
            except (ValueError, TypeError, OverflowError):
                pass
            c.execute('UPDATE discovery_sources SET failure_count=? WHERE source_id=?', (failures, run['source_id']))
            if code in {'snapshot_changed', 'invalid_cursor'}:
                c.execute('UPDATE discovery_runs SET cursor_json=NULL WHERE run_id=?', (run_id,))
            partial = run['page_count'] > 0
            health = 'rate_limited' if http_status == 429 else ('degraded' if partial else 'failed')
            self._finish(c, run, 'partial' if partial else 'failed', health, _iso(now), _iso(retry), code, http_status)

    def health(self, now: datetime, limit: int = 100) -> list[dict]:
        now = _time(now)
        with self.store.connection() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='discovery_sources'").fetchone():
                return []
            rows = c.execute('''SELECT s.*,r.page_count,r.accepted_count,r.rejected_count,r.cursor_json,
                r.lease_expires_at,r.logical_run_id FROM discovery_sources s LEFT JOIN discovery_runs r
                ON r.run_id=s.latest_run_id ORDER BY s.last_attempt_at DESC,s.source_id LIMIT ?''', (_limit(limit),)).fetchall()
        out = []
        for row in rows:
            item = _row(row)
            item['lease_expired'] = bool(item['lease_expires_at'] and _parse(item['lease_expires_at']) <= now)
            item['lease_active'] = bool(item['lease_expires_at'] and not item['lease_expired'])
            item['retry_eligible'] = not item['lease_active'] and (not item['next_retry_at'] or _parse(item['next_retry_at']) <= now)
            item['stale'] = bool(item['last_success_at'] and now - _parse(item['last_success_at']) >= timedelta(days=7))
            out.append(item)
        return out

    def scans(self, limit: int = 100) -> list[dict]:
        with self.store.connection() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='discovery_runs'").fetchone():
                return []
            rows = c.execute('SELECT * FROM discovery_runs ORDER BY started_at DESC,rowid DESC LIMIT ?', (_limit(limit),)).fetchall()
            output = []
            for row in rows:
                item = _row(row)
                item['transitions'] = [dict(event) for event in c.execute('SELECT status,created_at,error_code,http_status FROM discovery_scan_events WHERE run_id=? ORDER BY id LIMIT 100', (row['run_id'],))]
                output.append(item)
        return output

    def availability(self, job_id: str | None = None, limit: int = 100) -> list[dict]:
        now = _time(self.clock())
        with self.store.connection() as c:
            ids = c.execute('SELECT id,canonical_url FROM jobs' + (' WHERE id=?' if job_id is not None else '') + ' ORDER BY id LIMIT ?',
                            (job_id, _limit(limit)) if job_id is not None else (_limit(limit),)).fetchall()
            has_schema = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='discovery_job_sources'").fetchone()
            result = []
            for row in ids:
                jid = row['id']
                sources = []
                if has_schema:
                    for source in c.execute('''SELECT p.*,s.provider FROM discovery_job_sources p JOIN discovery_sources s
                        ON s.source_id=p.source_id WHERE p.job_id=? ORDER BY p.source_id LIMIT 100''', (jid,)):
                        item = dict(source)
                        item['stale'] = now - _parse(item['last_seen_at']) >= timedelta(days=7)
                        item['evidence'] = [dict(e) for e in c.execute('''SELECT kind,observed_at,deadline,run_id FROM discovery_evidence
                            WHERE job_id=? AND source_id=? ORDER BY id DESC LIMIT 20''', (jid, item['source_id']))]
                        sources.append(item)
                statuses = {source['status'] for source in sources}
                # Positive sources outrank absence or closure at a different source.
                status = next((s for s in ('reopened', 'available', 'unknown', 'closed') if s in statuses), 'unknown')
                matches = set()
                urls = {_safe_url(row['canonical_url'])} | {source['canonical_url'] for source in sources}
                for url in urls:
                    if url:
                        matches.update(r[0] for r in c.execute('''SELECT id FROM jobs
                            WHERE canonical_url=? AND id<>? ORDER BY id LIMIT 100''', (url, jid)))
                result.append({'job_id': jid, 'status': status, 'stale': bool(sources) and all(s['stale'] for s in sources),
                               'sources': sources, 'canonical_matches': sorted(matches)[:100]})
        return result
