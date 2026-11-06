"""Bounded local discovery scheduling. No approval, submission or Google authority.

The actual worker owns the OS lock. A supervisor dying cannot release a live
worker's lock. Lease/PID fields are diagnostic, never permission to steal it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time as daytime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
from uuid import uuid4


@dataclass(frozen=True)
class Config:
    root: str
    at: str = '09:00'
    timeout_seconds: int = 1800
    lookback_hours: int = 24
    attempts: int = 3
    battery: bool = True
    wake: bool = False
    network_required: bool = False
    notifications: bool = True

    def __post_init__(self):
        if self.root == '.':
            object.__setattr__(self, 'root', str(Path.cwd().resolve()))
        if not isinstance(self.root, str) or not Path(self.root).is_absolute():
            raise ValueError('Absolute workspace required')
        if not isinstance(self.at, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', self.at):
            raise ValueError('Local schedule must be HH:MM')
        for value, low, high in ((self.timeout_seconds, 1, 86400), (self.lookback_hours, 1, 24), (self.attempts, 1, 3)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Invalid scheduling bound')
        if any(type(v) is not bool for v in (self.battery, self.wake, self.network_required, self.notifications)):
            raise ValueError('Invalid scheduling policy')

    @property
    def directory(self):
        return Path(self.root)/'data/scheduler'


def load_config(root):
    root = Path(root).resolve()
    path = root/'data/scheduler/config.json'
    raw = path.read_bytes()
    if len(raw) > 8192:
        raise ValueError('Invalid scheduler configuration')
    config = Config(**json.loads(raw.decode('utf-8-sig')))
    if Path(config.root).resolve() != root:
        raise ValueError('Scheduler belongs to another workspace')
    return config


def due_window(config, now, *, system_local=False):
    """Latest local daily boundary only; date+time identity survives DST folds."""
    if now.tzinfo is None:
        raise ValueError('Timezone-aware clock required')
    hour, minute = map(int, config.at.split(':'))
    def boundary_for(day):
        value = datetime.combine(day, daytime(hour, minute), tzinfo=None if system_local else now.tzinfo)
        return value.astimezone() if system_local else value
    boundary = boundary_for(now.date())
    if boundary.astimezone(timezone.utc) > now.astimezone(timezone.utc):
        boundary = boundary_for(now.date()-timedelta(days=1))
    age = now.astimezone(timezone.utc)-boundary.astimezone(timezone.utc)
    if age < timedelta(0) or age > timedelta(hours=config.lookback_hours):
        return None
    return f'{boundary.date().isoformat()}@{config.at}', boundary


class RunLock:
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = open(self.path, 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.stream.write(b'0'); self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise BlockingIOError('Scheduler already running') from None
        return self

    def __exit__(self, *args):
        if os.name == 'nt':
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


class Journal:
    """Separate journal: never changes agent.db's schema or application history."""
    def __init__(self, config, *, create=False):
        self.config = config
        self.path = config.directory/'journal.db'
        if create:
            config.directory.mkdir(parents=True, exist_ok=True)
            self.path.touch(exist_ok=True)
        elif not self.path.is_file() or self.path.stat().st_size == 0:
            raise ValueError('Scheduler journal missing; restore private backup or explicitly reconfigure')
        with self.connection() as c:
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('Unsupported scheduler journal')
            c.execute('BEGIN IMMEDIATE')
            if version == 1:
                control = c.execute('SELECT * FROM controls').fetchall()
                if len(control) != 1 or control[0]['id'] != 1 or control[0]['enabled'] not in (0,1) or control[0]['stopped'] not in (0,1) or type(control[0]['epoch']) is not int or control[0]['epoch'] < 0:
                    raise ValueError('Corrupt scheduler controls; restore private backup')
                latest = c.execute('SELECT MAX(window) FROM windows').fetchone()[0]
                if latest and latest > control[0]['highwater']:
                    raise ValueError('Corrupt scheduling watermark')
                c.execute('SELECT token FROM attempts LIMIT 1')
                return
            if not create or c.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError('Unversioned scheduler journal')
            c.execute('CREATE TABLE controls (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, stopped INTEGER NOT NULL, epoch INTEGER NOT NULL, highwater TEXT NOT NULL)')
            c.execute("INSERT OR IGNORE INTO controls VALUES(1,1,0,0,'')")
            c.execute('CREATE TABLE windows (window TEXT PRIMARY KEY, attempt INTEGER NOT NULL, token TEXT NOT NULL, pid INTEGER NOT NULL, started TEXT NOT NULL, lease_until TEXT NOT NULL, status TEXT NOT NULL, category TEXT NOT NULL, retry_at TEXT, counts TEXT NOT NULL, notification TEXT NOT NULL)')
            c.execute('CREATE TABLE attempts (token TEXT PRIMARY KEY, window TEXT NOT NULL, attempt INTEGER NOT NULL, started TEXT NOT NULL, status TEXT NOT NULL, category TEXT NOT NULL, retry_at TEXT, counts TEXT NOT NULL)')
            c.execute('PRAGMA user_version=1')

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def control(self, operation):
        with self.connection() as c:
            if operation == 'start':
                c.execute('UPDATE controls SET enabled=1,stopped=0 WHERE id=1')
            elif operation in {'stop', 'disable', 'remove'}:
                c.execute('UPDATE controls SET stopped=1,enabled=CASE WHEN ? THEN 0 ELSE enabled END,epoch=epoch+1 WHERE id=1', (operation != 'stop',))
            else:
                raise ValueError('Invalid control')

    def status(self):
        with self.connection() as c:
            control = dict(c.execute('SELECT * FROM controls WHERE id=1').fetchone())
            rows = [dict(r) for r in c.execute('SELECT * FROM windows ORDER BY window DESC LIMIT 30')]
        for row in rows:
            row['counts'] = json.loads(row['counts'])
        with self.connection() as c:
            attempts = [dict(r) for r in c.execute('SELECT * FROM attempts ORDER BY started,attempt LIMIT 90')]
        for attempt in attempts:
            attempt['counts'] = json.loads(attempt['counts'])
        return {**control, 'latest': rows[0] if rows else None, 'history': rows, 'attempts': attempts}

    def claim(self, window, now, token, epoch=None):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            control = c.execute('SELECT * FROM controls WHERE id=1').fetchone()
            if epoch is not None and control['epoch'] != epoch:
                return {'status':'stale_start'}
            if not control['enabled']:
                return {'status':'disabled'}
            if control['stopped']:
                return {'status':'stopped'}
            if window < control['highwater']:
                return {'status':'clock_rollback'}
            row = c.execute('SELECT * FROM windows WHERE window=?', (window,)).fetchone()
            if row:
                if row['status'] in {'success', 'noop'}:
                    return {'status':'already_complete'}
                if row['attempt'] >= self.config.attempts:
                    return {'status':'exhausted'}
                if row['retry_at'] and datetime.fromisoformat(row['retry_at']) > now:
                    return {'status':'backoff'}
            attempt = row['attempt']+1 if row else 1
            c.execute('INSERT OR REPLACE INTO windows VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (window, attempt, token, os.getpid(), now.isoformat(),
                       (now+timedelta(seconds=self.config.timeout_seconds)).isoformat(), 'running', 'none', None, '{}', 'pending'))
            c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)', (token,window,attempt,now.isoformat(),'running','none',None,'{}'))
            c.execute('UPDATE controls SET highwater=? WHERE id=1', (window,))
            c.execute('DELETE FROM windows WHERE window NOT IN (SELECT window FROM windows ORDER BY window DESC LIMIT 30)')
            c.execute('DELETE FROM attempts WHERE window NOT IN (SELECT window FROM windows)')
            return {'status':'running', 'attempt':attempt, 'epoch':control['epoch']}

    def finish(self, token, result, now, jitter):
        result = clean_result(result)
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM windows WHERE token=? AND status='running'", (token,)).fetchone()
            if not row:
                return result
            retry = None
            if result['status'] in {'failed', 'partial'}:
                retry = now+timedelta(seconds=min(3600,60*2**(row['attempt']-1))+max(0,min(30,jitter())))
                if result.get('retry_at'):
                    retry = max(retry, datetime.fromisoformat(result['retry_at']))
            result['retry_at'] = retry.isoformat() if retry else None
            c.execute('UPDATE windows SET status=?,category=?,retry_at=?,counts=? WHERE token=?',
                      (result['status'],result['category'],result['retry_at'],json.dumps(result['counts']),token))
            c.execute('UPDATE attempts SET status=?,category=?,retry_at=?,counts=? WHERE token=?',
                      (result['status'],result['category'],result['retry_at'],json.dumps(result['counts']),token))
        return result

    def recover(self, now):
        # Only call while holding the worker lock: its absence proves no live writer.
        with self.connection() as c:
            tokens = [r[0] for r in c.execute("SELECT token FROM windows WHERE status='running'")]
        for token in tokens:
            self.finish(token, {'status':'failed','category':'interrupted','counts':{}}, now, lambda:0)

    def notified(self, token, value):
        with self.connection() as c:
            c.execute('UPDATE windows SET notification=? WHERE token=?', (value,token))


CATEGORIES = {'none','provider','partial','configuration','database','internal','interrupted','timeout','cancelled'}


def clean_result(result):
    status = result.get('status')
    category = result.get('category')
    if status not in {'success','noop','failed','partial','cancelled'} or category not in CATEGORIES:
        raise ValueError('Invalid scheduler outcome')
    counts = {key: max(0,min(1000000,value)) for key,value in result.get('counts',{}).items()
              if key in {'added','updated','duplicate','ranked','sources'} and type(value) is int}
    clean = {'status':status,'category':category,'counts':counts}
    if result.get('retry_at'):
        value = datetime.fromisoformat(result['retry_at'])
        if value.tzinfo is None:
            raise ValueError('Invalid retry timestamp')
        clean['retry_at'] = value.isoformat()
    return clean


def summarize(summary, health):
    counts = {key:summary.get(key,0) for key in ('added','updated','duplicate')}
    counts['sources'] = len(summary.get('by_source',[]))
    incomplete = {s['source_id'] for s in summary.get('by_source',[]) if not s.get('complete')}
    for skipped in summary.get('skipped',[]):
        source = next((h for h in health if h['source_id'] == skipped['source_id']), {})
        if skipped['skip_reason'] != 'cooldown' or source.get('status') not in {'healthy','healthy_empty'}:
            incomplete.add(skipped['source_id'])
    errors = summary.get('errors',[])
    failed_ids = incomplete | {e['source_id'] for e in errors if e.get('source_id')}
    retry = max((h.get('next_retry_at') or h.get('lease_expires_at') or '' for h in health if h['source_id'] in failed_ids), default='')
    result = {'status':'partial' if errors or incomplete else 'success' if counts['sources'] else 'noop',
              'category':'provider' if errors else 'partial' if incomplete else 'none','counts':counts}
    if retry and result['status'] == 'partial':
        result['retry_at'] = retry
    return clean_result(result)


def core_work(config):
    from .service import Agent
    from .discovery_state import DiscoveryState
    root = Path(config.root)
    agent = Agent(str(root/'data'))
    summary = agent.discover(str(root/'config/sources.json'), max_sources=100)
    health = DiscoveryState(agent.store).health(agent.clock())
    result = summarize(summary, health)
    profile = root/'config/profile.json'
    if profile.is_file():
        result['counts']['ranked'] = len(agent.ranked(str(profile),limit=100))
    return result


def execute(config, *, clock=None, work=core_work, notify=None, jitter=None, token=None, epoch=None):
    system_local = clock is None
    clock = clock or (lambda: datetime.now().astimezone())
    jitter = jitter or (lambda: random.SystemRandom().randint(0,30))
    token = token or uuid4().hex
    try:
        with RunLock(config.directory/'worker.lock'):
            journal = Journal(config)
            journal.recover(clock())
            window = due_window(config, clock(), system_local=system_local)
            if not window:
                return {'status':'outside_lookback'}
            claim = journal.claim(window[0], clock(), token, epoch)
            if claim['status'] != 'running':
                return claim
            try:
                result = clean_result(work(config))
            except (ValueError, OSError):
                result = {'status':'failed','category':'configuration','counts':{}}
            except sqlite3.Error:
                result = {'status':'failed','category':'database','counts':{}}
            except Exception:
                result = {'status':'failed','category':'internal','counts':{}}
            control = journal.status()
            if control['epoch'] != claim['epoch']:
                result = {'status':'cancelled','category':'cancelled','counts':{}}
            result = journal.finish(token, result, clock(), jitter)
            deliver_notification(journal, token, result, notify)
            return result
    except BlockingIOError:
        return {'status':'busy'}


def deliver_notification(journal, token, result, notify):
    if journal.config.notifications and notify:
        try:
            notify(clean_result(result))
            journal.notified(token,'sent')
        except Exception:
            journal.notified(token,'failed')
    else:
        journal.notified(token,'disabled')


def supervise(config, *, notify=None, popen=subprocess.Popen, monotonic=time.monotonic, sleep=time.sleep):
    """Only terminate the exact subprocess we created; never kill by saved PID."""
    journal = Journal(config)
    epoch = journal.status()['epoch']
    token = uuid4().hex
    child = popen([sys.executable, '-m', 'internship_agent.scheduler', 'worker', '--root',config.root,'--epoch',str(epoch),'--token',token],
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  cwd=config.root)
    started = monotonic()
    category = None
    try:
        while child.poll() is None:
            if journal.status()['epoch'] != epoch:
                category = 'cancelled'; break
            if monotonic()-started >= config.timeout_seconds:
                category = 'timeout'; break
            sleep(0.2)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)
    if category or child.returncode in (124,125):
        category = category or ('cancelled' if child.returncode == 125 else 'timeout')
        try:
            with RunLock(config.directory/'worker.lock'):
                row = journal.status()['latest']
                if row and row['token'] == token and row['status'] == 'running':
                    result = journal.finish(token, {'status':'cancelled' if category=='cancelled' else 'failed','category':category,'counts':{}}, datetime.now().astimezone(),lambda:0)
                    if notify is None:
                        from .scheduler_windows import notify_windows
                        notify = notify_windows
                    deliver_notification(journal, token, result, notify)
        except BlockingIOError:
            pass
    if child.returncode not in (0,124,125) and category is None:
        try:
            with RunLock(config.directory/'worker.lock'):
                journal.finish(token, {'status':'failed','category':'interrupted','counts':{}}, datetime.now().astimezone(),lambda:0)
        except BlockingIOError:
            pass
        raise ValueError('Worker exited unexpectedly; inspect scheduler status')
    return journal.status()


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('operation', choices=['run','worker','status','start','stop','disable'])
    p.add_argument('--root', required=True)
    p.add_argument('--token')
    p.add_argument('--epoch',type=int)
    args = p.parse_args()
    try:
        config = load_config(args.root)
        if args.operation == 'worker':
            # If the supervisor crashes, its worker still has a hard lifetime bound.
            done = threading.Event()
            def monitor():
                deadline = time.monotonic()+config.timeout_seconds
                while not done.wait(0.2):
                    if time.monotonic() >= deadline:
                        os._exit(124)
                    try:
                        if args.epoch is not None and Journal(config).status()['epoch'] != args.epoch:
                            os._exit(125)
                    except Exception:
                        os._exit(124)
            watchdog = threading.Thread(target=monitor,daemon=True)
            watchdog.start()
            from .scheduler_windows import notify_windows
            try:
                result = execute(config, notify=notify_windows, token=args.token, epoch=args.epoch)
            finally:
                done.set()
        elif args.operation == 'run':
            result = supervise(config)
        else:
            journal = Journal(config)
            if args.operation != 'status':
                journal.control(args.operation)
            result = journal.status()
        print(json.dumps(result,ensure_ascii=True))
    except (ValueError,OSError,sqlite3.Error,TypeError,KeyError):
        print('Scheduler failed: inspect local configuration, journal and database; no raw error logged.',file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
