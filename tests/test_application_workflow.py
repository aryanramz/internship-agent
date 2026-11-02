"""Recoverable workflow tests use only fictional profiles, jobs and receipts."""
import json
from pathlib import Path

import pytest

from internship_agent.models import Job
from internship_agent.service import Agent


@pytest.fixture
def scenario(tmp_path):
    agent = Agent(str(tmp_path / 'data'))
    job = Job(id='fictional-workflow', provider='synthetic', source_id='one',
              company='Fictional Employer', title='Software Intern', location='Example City',
              description='Python', job_url='https://example.test/jobs/one',
              apply_url='https://example.test/jobs/one')
    agent.store.upsert_job(job)
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'name': 'Fictional Candidate', 'skills': ['Python']}), encoding='utf-8')
    return agent, job, profile


def approve(agent, jid):
    token = agent.store.review(jid)['review_token']
    agent.store.approve(jid, 'APPROVE ' + jid, review_token=token)
    return token


def test_prepare_retries_reuse_revision_and_explicit_regeneration_invalidates_token(scenario):
    agent, job, profile = scenario
    first = agent.prepare(job.id, str(profile), request_id='fictional-request')
    token = approve(agent, job.id)
    again = agent.prepare(job.id, str(profile), request_id='fictional-request')
    assert again['resume_path'] == first['resume_path']
    assert again['status'] == 'approved'
    assert agent.prepare(job.id, str(profile))['resume_path'] == first['resume_path']
    fresh = agent.prepare(job.id, str(profile), new_revision=True)
    assert fresh['resume_path'] != first['resume_path']
    assert fresh['approved_at'] is None
    with pytest.raises(ValueError):
        agent.store.approve(job.id, 'APPROVE ' + job.id, review_token=token)
    assert Path(first['resume_path']).is_file()


@pytest.mark.parametrize('state', ['submitted', 'assessment', 'interview', 'offer', 'rejected', 'withdrawn'])
def test_completed_preparation_never_calls_generator_or_changes_files(scenario, monkeypatch, state):
    agent, job, profile = scenario
    packet = agent.prepare(job.id, str(profile))
    with agent.store.connection() as c:
        c.execute('UPDATE applications SET status=? WHERE job_id=?', (state, job.id))
    before = {p: p.read_bytes() for p in agent.root.rglob('*') if p.is_file()}
    def forbidden(*args, **kwargs):
        pytest.fail('Generator called for a completed application')
    monkeypatch.setattr('internship_agent.documents.create_packet', forbidden)
    with pytest.raises(ValueError):
        agent.prepare(job.id, str(profile))
    after = {p: p.read_bytes() for p in agent.root.rglob('*') if p.is_file()}
    assert before == after
    assert Path(packet['resume_path']).is_file()


@pytest.mark.parametrize('change', ['job', 'profile', 'resume', 'qa'])
def test_relevant_change_rejects_approval_and_submission(scenario, change):
    from dataclasses import replace
    agent, job, profile = scenario
    packet = agent.prepare(job.id, str(profile))
    token = approve(agent, job.id)
    if change == 'job':
        agent.store.upsert_job(replace(job, description='Changed responsibilities'))
    elif change == 'profile':
        profile.write_text('{"name":"Changed Fictional Candidate"}', encoding='utf-8')
    elif change == 'resume':
        Path(packet['resume_path']).write_bytes(b'changed')
    else:
        path = Path(packet['qa_path'])
        path.write_text(path.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    with pytest.raises(ValueError):
        agent.store.mark_submitted(job.id, 'Fictional receipt', approval_token=token)
    with pytest.raises(ValueError):
        agent.store.approve(job.id, 'APPROVE ' + job.id, review_token=token)


def test_repeat_approval_submission_and_tracking_do_not_duplicate_history(scenario):
    agent, job, profile = scenario
    agent.prepare(job.id, str(profile))
    token = approve(agent, job.id)
    agent.store.approve(job.id, 'APPROVE ' + job.id, review_token=token)
    agent.store.mark_submitted(job.id, 'Fictional receipt', approval_token=token)
    agent.store.mark_submitted(job.id, 'Fictional receipt', approval_token=token)
    agent.store.update_status(job.id, 'interview', 'Fictional invitation')
    agent.store.update_status(job.id, 'interview', 'Fictional invitation')
    report = agent.store.application_report(job.id)
    assert report['application']['employer_receipt_verified'] is False
    assert report['application']['submission_evidence_kind'] == 'user_supplied'
    events = [e['event_type'] for e in report['events']]
    assert events.count('approved') == events.count('submitted') == events.count('status_updated') == 1
    with pytest.raises(ValueError):
        agent.store.mark_submitted(job.id, 'A different receipt', approval_token=token)


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize('phase', ['intent', 'file', 'receipt', 'database'])
def test_restart_reconciles_every_filesystem_database_gap(scenario, monkeypatch, phase):
    from internship_agent.application_workflow import Workflow
    from internship_agent import documents
    agent, job, profile = scenario
    original = agent.prepare(job.id, str(profile))
    before = Path(original['resume_path']).read_bytes()
    approve(agent, job.id)
    with monkeypatch.context() as patch:
        if phase == 'intent':
            patch.setattr(Workflow, '_operation_dir', lambda *a: (_ for _ in ()).throw(Interrupted()))
        elif phase == 'file':
            save = documents._save
            def interrupt_file(doc, path):
                save(doc, path)
                raise Interrupted()
            patch.setattr(documents, '_save', interrupt_file)
        else:
            finish = Workflow._record_prepared
            def interrupt_record(self, c, operation, packet):
                if phase == 'database':
                    finish(self, c, operation, packet)
                raise Interrupted()
            patch.setattr(Workflow, '_record_prepared', interrupt_record)
        with pytest.raises(Interrupted):
            agent.prepare(job.id, str(profile), new_revision=True)
    assert agent.store.get_job(job.id)['approved_at'] is None
    restarted = Agent(str(agent.root))
    recovered = restarted.recover(job.id)
    state = 'committed' if phase in {'receipt', 'database'} else 'failed'
    assert recovered['operations'][0]['state'] == state
    assert restarted.recover()['operations'] == []
    assert Path(original['resume_path']).read_bytes() == before
    report = restarted.store.application_report(job.id)
    assert len([e for e in report['events'] if e['event_type'] == 'prepared']) == (2 if state == 'committed' else 1)
    assert report['application']['status'] == 'prepared'
    assert report['application']['approved_at'] is None


@pytest.mark.parametrize('after_commit', [False, True])
def test_real_process_exit_rolls_back_or_reuses_committed_attempt(scenario, after_commit):
    import subprocess
    import sys
    agent, job, profile = scenario
    script = '''import os,sys
from internship_agent.service import Agent
from internship_agent.application_workflow import Workflow
if sys.argv[4] == 'False':
    original = Workflow._record_prepared
    def exit_before_commit(self,c,operation,packet):
        original(self,c,operation,packet)
        os._exit(42)
    Workflow._record_prepared = exit_before_commit
Agent(sys.argv[1]).prepare(sys.argv[2],sys.argv[3])
os._exit(42)
'''
    process = subprocess.run([sys.executable, '-c', script, str(agent.root), job.id,
                              str(profile), str(after_commit)], timeout=30)
    assert process.returncode == 42
    restarted = Agent(str(agent.root))
    results = restarted.recover()['operations']
    assert len(results) == (0 if after_commit else 1)
    packet = restarted.prepare(job.id, str(profile))
    assert packet['reused'] is True
    assert len(list(agent.root.rglob('resume.docx'))) == 1


def test_parallel_prepare_approve_and_record_are_serialized(scenario):
    from concurrent.futures import ThreadPoolExecutor
    agent, job, profile = scenario
    def prepare_one(_):
        try:
            return Agent(str(agent.root)).prepare(job.id, str(profile))
        except ValueError:
            return None  # Explicit recover/retry is safe if another reservation won.
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(prepare_one, range(3)))
    agent.recover()
    packet = agent.prepare(job.id, str(profile))
    token = agent.store.review(job.id)['review_token']
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: agent.store.approve(job.id, 'APPROVE ' + job.id, review_token=token), range(3)))
        list(pool.map(lambda _: agent.store.mark_submitted(job.id, 'Fictional receipt', approval_token=token), range(3)))
    report = agent.store.application_report(job.id)
    assert len([e for e in report['events'] if e['event_type'] == 'approved']) == 1
    assert len([e for e in report['events'] if e['event_type'] == 'submitted']) == 1
    assert Path(packet['resume_path']).is_file()
    with agent.store.connection() as c:
        assert c.execute('SELECT count(*) FROM applications').fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM submission_records').fetchone()[0] == 1


@pytest.mark.parametrize('mutation', ['job', 'profile', 'receipt_path', 'packet', 'qa_shape'])
def test_recovery_rejects_changed_or_unsafe_packet_without_replacing_old_revision(scenario, monkeypatch, mutation):
    from dataclasses import replace
    from internship_agent.application_workflow import Workflow
    agent, job, profile = scenario
    old = agent.prepare(job.id, str(profile))
    with monkeypatch.context() as patch:
        patch.setattr(Workflow, '_record_prepared', lambda *a: (_ for _ in ()).throw(Interrupted()))
        with pytest.raises(Interrupted):
            agent.prepare(job.id, str(profile), new_revision=True)
    receipt_path = next(p for p in agent.root.rglob('packet.json') if p.parent.name != old['operation_id'])
    if mutation == 'job':
        agent.store.upsert_job(replace(job, title='Changed Fictional Intern'))
    elif mutation == 'profile':
        profile.write_text('{"name":"Changed"}', encoding='utf-8')
    elif mutation == 'packet':
        (receipt_path.parent / json.loads(receipt_path.read_text(encoding='utf-8'))['resume']).write_bytes(b'changed')
    elif mutation == 'qa_shape':
        resume = receipt_path.parent / json.loads(receipt_path.read_text(encoding='utf-8'))['resume']
        (resume.parent / 'qa.json').write_text('[]', encoding='utf-8')
    else:
        receipt_path.write_text(json.dumps({'resume': '../../outside/resume.docx'}), encoding='utf-8')
    assert agent.recover()['operations'][0]['state'] == 'failed'
    assert agent.store.get_job(job.id)['resume_path'] == old['resume_path']


def test_request_id_cannot_be_reused_for_different_inputs(scenario):
    agent, job, profile = scenario
    agent.prepare(job.id, str(profile), request_id='fictional-request')
    with pytest.raises(ValueError):
        agent.prepare(job.id, str(profile), request_id='fictional-request', variant='master')


def test_discovery_refresh_does_not_invalidate_unchanged_review(scenario):
    agent, job, profile = scenario
    agent.prepare(job.id, str(profile))
    token = approve(agent, job.id)
    agent.store.upsert_job(job)
    assert agent.store.get_job(job.id)['status'] == 'approved'
    assert agent.store.review(job.id)['review_token'] == token


def test_each_explicit_request_id_binds_one_attempt_even_for_identical_inputs(scenario):
    agent, job, profile = scenario
    first = agent.prepare(job.id, str(profile), request_id='first')
    second = agent.prepare(job.id, str(profile), request_id='second')
    assert first['resume_path'] != second['resume_path']
    with pytest.raises(ValueError):
        agent.prepare(job.id, str(profile), request_id='first')


def test_withdrawn_command_retry_is_idempotent_but_cannot_reopen_application(scenario):
    agent, job, profile = scenario
    agent.prepare(job.id, str(profile))
    token = approve(agent, job.id)
    agent.store.mark_submitted(job.id, 'Fictional receipt', approval_token=token)
    first = agent.store.update_status(job.id, 'withdrawn', 'Fictional withdrawal')
    assert agent.store.update_status(job.id, 'withdrawn', 'Fictional withdrawal') == first
    with pytest.raises(ValueError):
        agent.store.update_status(job.id, 'interview')


def test_changed_posting_preserves_completed_approval_and_submission_history(scenario):
    from dataclasses import replace
    agent, job, profile = scenario
    agent.prepare(job.id, str(profile))
    token = approve(agent, job.id)
    agent.store.mark_submitted(job.id, 'Fictional receipt', approval_token=token)
    with agent.store.connection() as c:
        before = {table: [tuple(r) for r in c.execute('SELECT * FROM ' + table)]
                  for table in ('applications', 'application_bindings', 'submission_records', 'events')}
    agent.store.upsert_job(replace(job, description='Changed after historical submission'))
    with agent.store.connection() as c:
        assert {table: [tuple(r) for r in c.execute('SELECT * FROM ' + table)] for table in before} == before


def test_missing_token_never_approves_current_packet(scenario):
    agent, job, profile = scenario
    agent.prepare(job.id, str(profile))
    with pytest.raises(ValueError):
        agent.store.approve(job.id, 'APPROVE ' + job.id)
    assert agent.store.get_job(job.id)['status'] == 'prepared'


@pytest.mark.parametrize('target', ['other_job', 'stale_profile'])
def test_compatibility_setter_cannot_promote_foreign_or_stale_packet(scenario, target):
    from dataclasses import replace
    agent, job, profile = scenario
    packet = agent.prepare(job.id, str(profile))
    token = approve(agent, job.id)
    jid = job.id
    if target == 'other_job':
        jid = 'different-fictional-job'
        agent.store.upsert_job(replace(job, id=jid, title='Different Fictional Intern'))
    else:
        profile.write_text('{"name":"Changed Fictional Profile"}', encoding='utf-8')
    agent.store.set_prepared(jid, packet['resume_path'], packet['letter_path'])
    with pytest.raises(ValueError):
        agent.store.review(jid)
    with pytest.raises(ValueError):
        agent.store.approve(jid, 'APPROVE ' + jid, review_token=token)
    with pytest.raises(ValueError):
        agent.store.mark_submitted(jid, 'Fictional receipt', approval_token=token)
