"""Synthetic scheduling contracts; never install native tasks or contact providers."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from internship_agent.scheduler import Config, Journal, RunLock, due_window, execute, summarize, supervise

NOW = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)


def configuration(tmp_path, **kw):
    config = Config(root=str(tmp_path), **kw)
    Journal(config,create=True)
    return config


def test_daily_window_is_latest_only_and_lookback_bounded():
    c = Config(root='.')
    assert due_window(c, NOW)[0] == '2026-11-05@09:00'
    assert due_window(c, NOW.replace(hour=8))[0] == '2026-11-04@09:00'
    assert due_window(Config(root='.', lookback_hours=2), NOW.replace(hour=8)) is None


def test_success_and_noop_deduplicate_across_restarts(tmp_path):
    c = configuration(tmp_path)
    calls = []
    work = lambda c: (calls.append(1) or {'status': 'noop', 'category': 'none', 'counts': {}})
    assert execute(c, clock=lambda: NOW, work=work)['status'] == 'noop'
    assert execute(c, clock=lambda: NOW, work=work)['status'] == 'already_complete'
    assert calls == [1]


def test_bounded_retries_never_precede_provider_cooldown(tmp_path):
    c = configuration(tmp_path)
    work = lambda c: {'status':'partial', 'category':'provider', 'counts':{}, 'retry_at':(NOW+timedelta(hours=3)).isoformat()}
    first = execute(c, clock=lambda: NOW, work=work, jitter=lambda: 0)
    assert first['retry_at'] == (NOW+timedelta(hours=3)).isoformat()
    assert execute(c, clock=lambda: NOW+timedelta(hours=2), work=work)['status'] == 'backoff'
    execute(c, clock=lambda: NOW+timedelta(hours=3), work=work, jitter=lambda: 0)
    execute(c, clock=lambda: NOW+timedelta(hours=6), work=work, jitter=lambda: 0)
    assert execute(c, clock=lambda: NOW+timedelta(hours=7), work=work)['status'] == 'exhausted'


def test_lock_is_nonreentrant_and_recovers_on_process_exit(tmp_path):
    path = tmp_path/'worker.lock'
    with RunLock(path):
        with pytest.raises(BlockingIOError):
            with RunLock(path):
                pytest.fail('must not reenter')
    child = subprocess.Popen([sys.executable, '-c',
        'from internship_agent.scheduler import RunLock; import sys,time; '
        'lock=RunLock(sys.argv[1]); lock.__enter__(); print("locked",flush=True); time.sleep(30)', str(path)], stdout=subprocess.PIPE)
    assert child.stdout.readline().strip() == b'locked'
    child.kill(); child.wait(timeout=5)
    with RunLock(path):
        pass


def test_crash_recovery_records_interrupted_and_waits_before_retry(tmp_path):
    c = configuration(tmp_path)
    j = Journal(c)
    assert j.claim('2026-11-05@09:00', NOW, 'dead')['attempt'] == 1
    result = execute(c, clock=lambda: NOW, work=lambda c: pytest.fail('immediate retry'))
    assert result['status'] == 'backoff'
    row = Journal(c).status()['latest']
    assert row['category'] == 'interrupted'
    assert row['status'] == 'failed'


def test_errors_and_notifications_never_persist_private_text(tmp_path):
    c = configuration(tmp_path)
    def broken(c):
        raise ValueError('SECRET fictional@example.invalid token=private')
    def notification(result):
        raise RuntimeError('SECRET notification')
    result = execute(c, clock=lambda: NOW, work=broken, notify=notification)
    assert result['category'] == 'configuration'
    assert 'SECRET' not in json.dumps(Journal(c).status())
    assert Journal(c).status()['latest']['notification'] == 'failed'
    assert execute(c, clock=lambda: NOW, work=broken)['status'] == 'backoff'


def test_partial_and_failed_cooldowns_are_not_successful_noops():
    for skipped in ('cooldown', 'busy', 'work_budget'):
        result = summarize({'added':0,'updated':0,'duplicate':0,'errors':[], 'by_source':[],
                            'skipped':[{'source_id':'a','skip_reason':skipped}]},
                           [{'source_id':'a','status':'failed','next_retry_at':(NOW+timedelta(hours=4)).isoformat()}])
        assert result['status'] == 'partial'
    assert summarize({'errors':[],'by_source':[],'skipped':[]}, [])['status'] == 'noop'


def test_disable_stop_and_cancel_are_durable_and_nonexecuting(tmp_path):
    c = configuration(tmp_path)
    j = Journal(c)
    j.control('disable')
    assert execute(c, clock=lambda: NOW, work=lambda c: pytest.fail())['status'] == 'disabled'
    j.control('start')
    j.control('stop')
    assert execute(c, clock=lambda: NOW, work=lambda c: pytest.fail())['status'] == 'stopped'
    j.control('start')
    assert execute(c, clock=lambda: NOW, work=lambda c:{'status':'success','category':'none','counts':{}})['status'] == 'success'


def test_corrupt_state_fails_closed(tmp_path):
    c = configuration(tmp_path)
    directory = tmp_path/'data/scheduler'
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'journal.db').write_bytes(b'corrupt')
    with pytest.raises(Exception):
        execute(c, work=lambda c: pytest.fail())


def test_history_is_bounded_and_clock_rollback_cannot_replay_pruned_window(tmp_path):
    c = configuration(tmp_path)
    for day in range(40):
        execute(c, clock=lambda d=day: NOW+timedelta(days=d), work=lambda c:{'status':'noop','category':'none','counts':{}})
    assert len(Journal(c).status()['history']) == 30
    assert execute(c, clock=lambda:NOW, work=lambda c:pytest.fail())['status'] == 'clock_rollback'


@pytest.mark.parametrize('field,value', [('at','25:00'),('timeout_seconds',0),('attempts',10),('root','relative'),('lookback_hours',48)])
def test_config_rejects_invalid_values(field,value,tmp_path):
    with pytest.raises(ValueError):
        configuration(tmp_path, **{field:value}) if field != 'root' else Config(root=value)


def test_dst_fold_keeps_one_window_identity():
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        zone = ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        pytest.skip('Host lacks IANA timezone data')
    c = Config(root='.',at='01:30')
    early = datetime(2026,11,1,1,45,tzinfo=zone,fold=0)
    late = early.replace(fold=1)
    assert due_window(c,early)[0] == due_window(c,late)[0] == '2026-11-01@01:30'


def test_supervisor_timeout_and_cancel_only_target_its_child(tmp_path):
    for category in ('timeout','cancelled'):
        root = tmp_path/category
        root.mkdir()
        c = configuration(root,timeout_seconds=1)
        j = Journal(c)
        now = datetime.now().astimezone()
        ticks = iter([0,0,2])
        class Child:
            returncode = None
            def poll(self):
                return self.returncode
            def terminate(self):
                self.returncode = -1
            def wait(self,timeout):
                return self.returncode
        child = Child()
        def spawn(argv,**kw):
            token = argv[-1]
            j.claim('2026-11-05@09:00',now,token)
            if category == 'cancelled':
                j.control('stop')
            return child
        result = supervise(c,popen=spawn,monotonic=lambda:next(ticks),sleep=lambda _:None)
        assert child.returncode == -1
        assert result['latest']['category'] == category
        assert result['latest']['status'] == ('cancelled' if category=='cancelled' else 'failed')


def test_subprocess_runner_empty_synthetic_sources_deduplicates(tmp_path):
    from dataclasses import asdict
    c = configuration(tmp_path,notifications=False)
    c.directory.mkdir(parents=True,exist_ok=True)
    (c.directory/'config.json').write_text(json.dumps(asdict(c)),encoding='utf-8')
    (tmp_path/'config').mkdir()
    (tmp_path/'config/sources.json').write_text('{"boards":[]}',encoding='utf-8')
    command = [sys.executable,'-m','internship_agent.scheduler','run','--root',str(tmp_path)]
    first = subprocess.run(command,capture_output=True,timeout=15)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)['latest']['status'] == 'noop'
    second = subprocess.run(command,capture_output=True,timeout=15)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)['latest']['attempt'] == 1


def test_concurrent_workers_do_not_duplicate_mutations(tmp_path):
    from dataclasses import asdict
    c = configuration(tmp_path,notifications=False)
    c.directory.mkdir(parents=True,exist_ok=True)
    (c.directory/'config.json').write_text(json.dumps(asdict(c)),encoding='utf-8')
    (tmp_path/'config').mkdir()
    (tmp_path/'config/sources.json').write_text('{"boards":[]}',encoding='utf-8')
    cmd = [sys.executable,'-m','internship_agent.scheduler','run','--root',str(tmp_path)]
    processes = [subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
    for child in processes:
        out,err=child.communicate(timeout=20)
        assert child.returncode == 0,err
    assert Journal(c).status()['latest']['attempt'] == 1


def test_offline_provider_failure_keeps_sanitized_durable_retry(tmp_path,monkeypatch):
    from internship_agent.sources import SourceError
    import internship_agent.service as service
    def offline(*args,**kw):
        raise SourceError('network','PRIVATE fictional source URL')
    monkeypatch.setattr(service,'retrieve_page',offline)
    (tmp_path/'config').mkdir()
    (tmp_path/'config/sources.json').write_text(json.dumps({'boards':[{'provider':'lever','token':'fictional','company':'Fictional'}]}))
    c=configuration(tmp_path)
    result=execute(c)
    assert result['status']=='partial'
    assert result['category']=='provider'
    assert result['retry_at']
    assert 'PRIVATE' not in json.dumps(Journal(c).status())


def test_attempt_audit_retains_failure_before_retry(tmp_path):
    c=configuration(tmp_path)
    execute(c,clock=lambda:NOW,work=lambda c:{'status':'failed','category':'provider','counts':{}},jitter=lambda:0)
    execute(c,clock=lambda:NOW+timedelta(minutes=2),work=lambda c:{'status':'success','category':'none','counts':{}})
    attempts=Journal(c).status()['attempts']
    assert [row['status'] for row in attempts] == ['failed','success']


def test_stale_start_epoch_cannot_claim_after_stop_restart(tmp_path):
    c=configuration(tmp_path)
    j=Journal(c)
    epoch=j.status()['epoch']
    j.control('stop'); j.control('start')
    assert execute(c,clock=lambda:NOW,epoch=epoch,work=lambda c:pytest.fail())['status']=='stale_start'


def test_real_process_timeout_releases_lock_and_records_failure(tmp_path):
    c=configuration(tmp_path,timeout_seconds=1)
    def spawn(argv,**kw):
        code = '''import sys,time
from internship_agent.scheduler import Config, Journal, RunLock
from datetime import datetime
c=Config(root=sys.argv[1]); lock=RunLock(c.directory/'worker.lock'); lock.__enter__()
Journal(c).claim('2026-11-05@09:00',datetime.now().astimezone(),sys.argv[2])
time.sleep(60)
'''
        return subprocess.Popen([sys.executable,'-c',code,c.root,argv[-1]],**kw)
    result=supervise(c,popen=spawn)
    assert result['latest']['category']=='timeout'
    with RunLock(c.directory/'worker.lock'):
        pass


def test_start_is_idempotent_and_cancelled_window_resumes_on_explicit_start(tmp_path):
    c=configuration(tmp_path)
    j=Journal(c)
    before=j.status()['epoch']
    j.control('start')
    assert j.status()['epoch']==before
    j.claim('2026-11-05@09:00',NOW,'cancelled')
    j.control('stop')
    j.finish('cancelled',{'status':'cancelled','category':'cancelled','counts':{}},NOW,lambda:0)
    j.control('start')
    assert execute(c,clock=lambda:NOW,work=lambda c:{'status':'noop','category':'none','counts':{}})['status']=='noop'


def test_missing_control_row_is_corruption_never_implicit_enable(tmp_path):
    c=configuration(tmp_path)
    j=Journal(c)
    j.control('disable')
    with j.connection() as db:
        db.execute('DELETE FROM controls')
    with pytest.raises(ValueError):
        execute(c,work=lambda c:pytest.fail())


def test_unexpected_worker_failure_is_not_reported_as_success(tmp_path):
    c=configuration(tmp_path)
    class Child:
        returncode=2
        def poll(self): return 2
    with pytest.raises(ValueError):
        supervise(c,popen=lambda *a,**k:Child())


def test_retired_source_cooldown_cannot_postpone_current_retry():
    summary={'errors':[],'by_source':[],'skipped':[{'source_id':'active','skip_reason':'cooldown'}]}
    health=[{'source_id':'active','status':'failed','next_retry_at':(NOW+timedelta(minutes=1)).isoformat()},
            {'source_id':'retired','status':'failed','next_retry_at':(NOW+timedelta(days=10)).isoformat()}]
    assert summarize(summary,health)['retry_at']==health[0]['next_retry_at']


@pytest.mark.skipif(not hasattr(time,'tzset'),reason='POSIX system-timezone injection requires tzset')
def test_system_clock_uses_boundary_date_dst_offset(monkeypatch):
    prior=os.environ.get('TZ')
    try:
        monkeypatch.setenv('TZ','America/New_York'); time.tzset()
        # Production astimezone() gives a fixed-offset current-time object.
        now=datetime(2026,11,1,8,30).astimezone()
        assert due_window(Config(root='.'),now,system_local=True) is None
    finally:
        if prior is None: monkeypatch.delenv('TZ',raising=False)
        else: monkeypatch.setenv('TZ',prior)
        time.tzset()


def test_deleted_journal_never_implicitly_resumes(tmp_path):
    c=configuration(tmp_path)
    j=Journal(c); j.control('disable')
    j.path.unlink()
    with pytest.raises(ValueError):
        execute(c,work=lambda c:pytest.fail())


def test_orphan_worker_still_blocks_new_start_and_recovers_after_kill(tmp_path):
    c=configuration(tmp_path)
    code='''import sys,time
from datetime import datetime
from internship_agent.scheduler import Config, Journal, RunLock
c=Config(root=sys.argv[1]); lock=RunLock(c.directory/'worker.lock'); lock.__enter__()
Journal(c).claim('2026-11-05@09:00',datetime.now().astimezone(),'orphan')
print('locked',flush=True); time.sleep(60)
'''
    child=subprocess.Popen([sys.executable,'-c',code,c.root],stdout=subprocess.PIPE)
    try:
        assert child.stdout.readline().strip()==b'locked'
        assert execute(c,work=lambda c:pytest.fail())['status']=='busy'
    finally:
        child.kill(); child.wait(timeout=5)
    assert execute(c,clock=lambda:NOW,work=lambda c:pytest.fail())['status']=='backoff'
