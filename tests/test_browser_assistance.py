"""Synthetic sandbox journal tests: no browser, network, or application writes."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

import pytest

from internship_agent.browser_assistance import Assistance, FORM_FINGERPRINT, TTL_SECONDS
from internship_agent.dashboard_data import DashboardData
from internship_agent.models import Job
from internship_agent.service import Agent

ORIGIN = 'http://127.0.0.1:49152'


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / 'config').mkdir()
    profile = {'name': 'Fictional Candidate', 'email': 'fictional@example.test',
               'skills': ['Python'], 'documents': {'version': 1, 'facts': [
                   {'id': name, 'path': '/' + name, 'value': value, 'verified': True,
                    'source': 'Fictional local review', 'reviewed_on': '2026-11-01'}
                   for name, value in [('name', 'Fictional Candidate'), ('email', 'fictional@example.test')]]}}
    (tmp_path / 'config' / 'profile.json').write_text(json.dumps(profile))
    agent = Agent(str(tmp_path / 'data'))
    agent.store.upsert_job(Job(id='fixture', provider='synthetic', source_id='fictional',
                              company='Fictional Employer', title='Software Intern', location='Remote',
                              description='Python', job_url='https://example.test/fictional',
                              apply_url='https://example.test/fictional'))
    dashboard = DashboardData(tmp_path)
    review = dashboard.action('prepare', {'id': 'fixture', 'confirm': 'prepare'})['review']
    dashboard.action('approve', {'id': 'fixture', 'phrase': 'APPROVE fixture', 'review_token': review['review_token']})
    now = [datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp()]
    assistance = Assistance(tmp_path, ORIGIN, 'fictional-session', enabled=True, clock=lambda: now[0])
    return assistance, review['review_token'], now


def create(sandbox, challenge='none'):
    assistance, token, _ = sandbox
    return assistance.create('fixture', token, challenge)


def act(assistance, plan, action, **payload):
    return assistance.act(plan['plan_id'], action,
                          plan.get('observe_token', plan['action_token']) if action == 'observe' else plan['action_token'],
                          {'form_fingerprint': FORM_FINGERPRINT, **payload})


def intent(sandbox, challenge='none'):
    assistance = sandbox[0]
    plan = create(sandbox, challenge)
    plan = act(assistance, plan, 'fill')
    plan = act(assistance, plan, 'handoff')
    if challenge != 'none':
        plan = act(assistance, plan, 'resume', challenge_ack=True)
        plan = act(assistance, plan, 'handoff')
    return act(assistance, plan, 'intent', phrase='AUTHORIZE FIXTURE ' + plan['plan_id'])


def journal_rows(assistance):
    with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
        return c.execute('SELECT * FROM assistance_events').fetchall()


def test_constructor_and_inspection_never_initialize_tables(sandbox):
    assistance, _, _ = sandbox
    db = assistance.dashboard.data / 'agent.db'
    before = db.read_bytes()
    assert assistance.list_for_job('fixture') == []
    with pytest.raises(ValueError):
        assistance.review('a' * 32)
    assert db.read_bytes() == before
    with sqlite3.connect(db) as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'assistance_%'").fetchone()


@pytest.mark.parametrize('origin', ['https://127.0.0.1:4000', 'http://localhost:4000',
                                  'http://127.0.0.2:4000', 'http://127.0.0.1:4000/',
                                  'http://127.0.0.1:4000@example.test', 'http://127.0.0.1:0',
                                  'http://127.0.0.1:65536', 'http://127.0.0.1:4000/path'])
def test_only_fixed_numeric_http_origin(sandbox, origin):
    with pytest.raises(ValueError):
        Assistance(sandbox[0].dashboard.root, origin, 'session')


def test_disabled_and_unapproved_reject_before_schema_creation(sandbox):
    assistance, token, _ = sandbox
    disabled = Assistance(assistance.dashboard.root, ORIGIN, 'session')
    with pytest.raises(ValueError, match='disabled'):
        disabled.create('fixture', token)
    with pytest.raises(ValueError):
        assistance.create('fixture', 'wrong')
    with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='assistance_schema'").fetchone()


def test_plan_binds_only_exact_attested_name_email_and_manual_questions(sandbox):
    plan = create(sandbox)
    assert plan['target_url'] == ORIGIN + '/sandbox/application/' + plan['plan_id']
    assert plan['company'] == 'Fictional Employer'
    fields = {f['name']: f for f in plan['fields']}
    for name, value in [('name', 'Fictional Candidate'), ('email', 'fictional@example.test')]:
        assert fields[name]['value'] == value
        assert fields[name]['provenance']['value'] == value
        assert fields[name]['provenance']['path'] == '/' + name
    for name in ('legal', 'eeo', 'work_authorization'):
        assert fields[name] == {'name': name, 'manual': True}
    assert 'example.test/fictional' not in json.dumps(plan)
    assert len(plan['plan_digest']) == len(plan['packet_sha256']) == 64
    assert sandbox[0].dashboard.store.get_job('fixture')['status'] == 'approved'


def test_restart_tokens_and_double_click_replay(sandbox):
    assistance = sandbox[0]
    first = create(sandbox)
    reopened = Assistance(assistance.dashboard.root, ORIGIN, 'fictional-session', True, assistance.clock)
    assert reopened.review(first['plan_id'])['action_token'] == first['action_token']
    filled = act(reopened, first, 'fill')
    with pytest.raises(ValueError, match='token'):
        act(assistance, first, 'fill')
    assert filled['state'] == 'filled'
    assert len(journal_rows(assistance)) == 2
    assert first['action_token'] not in json.dumps(journal_rows(assistance))
    with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
        row = c.execute('SELECT token_hash,nonce,snapshot_json FROM assistance_plans').fetchone()
    assert first['action_token'] not in str(row)


def test_competing_sessions_serialize_creation_and_actions(sandbox):
    assistance, token, _ = sandbox
    other = Assistance(assistance.dashboard.root, ORIGIN, 'other-session', True, assistance.clock)
    def attempt(actor):
        try:
            return actor.create('fixture', token)
        except ValueError:
            return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, [assistance, other]))
    assert sum(r is not None for r in results) == 1
    winner = next(r for r in results if r)
    actor = assistance if not assistance.review(winner['plan_id'])['reconciliation_only'] else other
    loser = other if actor is assistance else assistance
    assert loser.review(winner['plan_id'])['reconciliation_only']
    with pytest.raises(ValueError, match='token'):
        act(loser, winner, 'fill')
    with ThreadPoolExecutor(2) as pool:
        def fill(_):
            try:
                return act(actor, winner, 'fill')['state']
            except ValueError:
                return 'blocked'
        assert sorted(pool.map(fill, range(2))) == ['blocked', 'filled']


@pytest.mark.parametrize('challenge', ['mfa', 'captcha'])
def test_manual_challenge_requires_explicit_resume(sandbox, challenge):
    assistance = sandbox[0]
    plan = act(assistance, create(sandbox, challenge), 'fill')
    plan = act(assistance, plan, 'handoff')
    with pytest.raises(ValueError, match='challenge'):
        act(assistance, plan, 'intent', phrase='AUTHORIZE FIXTURE ' + plan['plan_id'])
    with pytest.raises(ValueError, match='acknowledgement'):
        act(assistance, plan, 'resume')
    plan = act(assistance, plan, 'resume', challenge_ack=True)
    assert plan['state'] == 'filled'
    assert plan['challenge_resolved']


@pytest.mark.parametrize('drift', ['profile', 'job', 'document', 'form', 'origin', 'expiry', 'availability'])
def test_drift_invalidates_without_partial_action_or_application_change(sandbox, drift):
    assistance, _, now = sandbox
    plan = create(sandbox)
    payload = {}
    if drift == 'profile':
        path = assistance.dashboard.profile
        profile = json.loads(path.read_text())
        profile['email'] = 'different@example.test'
        path.write_text(json.dumps(profile))
    elif drift == 'job':
        with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
            c.execute("UPDATE jobs SET description='Changed fictional posting'")
    elif drift == 'document':
        packet = assistance.dashboard.store.review('fixture')
        from pathlib import Path
        Path(packet['resume_path']).write_bytes(b'changed')
    elif drift == 'form':
        payload['form_fingerprint'] = 'changed'
    elif drift == 'origin':
        assistance = Assistance(assistance.dashboard.root, 'http://127.0.0.1:49153',
                                'fictional-session', True, assistance.clock)
    elif drift == 'expiry':
        now[0] += TTL_SECONDS
    else:
        with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
            c.execute("INSERT INTO discovery_sources(source_id,provider) VALUES('new','synthetic')")
            c.execute("INSERT INTO discovery_job_sources VALUES(?,?,?,?,?,?,?,?,?)",
                      ('fixture', 'new', 'https://example.test/fixture', '2026-11-06', '2026-11-06',
                       'fictional-run', 'closed', 'observed', '2026-11-06'))
    with pytest.raises(ValueError):
        act(assistance, plan, 'fill', **payload)
    reviewed = assistance.review(plan['plan_id'])
    assert reviewed['state'] == 'invalidated'
    assert reviewed['action_token'] == ''
    assert assistance.dashboard.store.get_job('fixture')['status'] == 'approved'
    with pytest.raises(ValueError):
        act(assistance, plan, 'fill')


def test_intent_is_durable_before_manual_fixture_observation_and_never_submits(sandbox):
    assistance = sandbox[0]
    plan = intent(sandbox)
    assert plan['state'] == 'needs_manual_reconciliation'
    assert not plan['fixture_ui_observed']
    assert journal_rows(assistance)[-1][2] == 'submission_intent'
    observed = act(assistance, plan, 'observe')
    assert observed['fixture_ui_observed']
    assert observed['state'] == 'needs_manual_reconciliation'
    assert observed['history'][0]['kind'] == 'fixture_ui_observed'
    with pytest.raises(ValueError):
        act(assistance, plan, 'observe')
    with pytest.raises(ValueError):
        act(assistance, observed, 'intent', phrase='AUTHORIZE FIXTURE ' + plan['plan_id'])
    assert assistance.dashboard.store.get_job('fixture')['status'] == 'approved'


@pytest.mark.parametrize('outcome', ['submitted', 'not_submitted', 'unknown'])
def test_crash_expiry_new_session_explicit_reconciliation(sandbox, outcome):
    assistance, token, now = sandbox
    plan = intent(sandbox)
    now[0] += TTL_SECONDS + 1
    restarted = Assistance(assistance.dashboard.root, ORIGIN, 'new-authenticated-session', True, assistance.clock)
    current = restarted.review(plan['plan_id'])
    assert current['reconciliation_only']
    assert current['action_token']
    with pytest.raises(ValueError):
        act(restarted, current, 'observe')
    with pytest.raises(ValueError):
        act(restarted, current, 'revoke')
    with pytest.raises(ValueError):
        act(restarted, current, 'reconcile', phrase='wrong', outcome=outcome, provenance='Fictional operator review')
    reconciled = act(restarted, current, 'reconcile', phrase='RECONCILE ' + plan['plan_id'],
                     outcome=outcome, provenance='Fictional operator review')
    assert reconciled['state'] == ('needs_manual_reconciliation' if outcome == 'unknown' else 'reconciled_' + outcome)
    assert assistance.dashboard.store.get_job('fixture')['status'] == 'approved'
    if outcome == 'not_submitted':
        new = restarted.create('fixture', token)
        assert new['plan_id'] != plan['plan_id']
        with pytest.raises(ValueError):
            act(restarted, reconciled, 'intent', phrase='AUTHORIZE FIXTURE ' + plan['plan_id'])
    else:
        with pytest.raises(ValueError, match='blocks'):
            restarted.create('fixture', token)


def test_revoke_is_terminal_and_only_explicit_new_creation_allows_retry(sandbox):
    assistance = sandbox[0]
    plan = create(sandbox)
    revoked = act(assistance, plan, 'revoke')
    assert revoked['state'] == 'revoked'
    assert revoked['action_token'] == ''
    with pytest.raises(ValueError):
        act(assistance, plan, 'fill')
    assert create(sandbox)['plan_id'] != plan['plan_id']


def test_exact_phrase_mandatory_and_future_journal_rejected(sandbox):
    assistance = sandbox[0]
    plan = act(assistance, create(sandbox), 'fill')
    plan = act(assistance, plan, 'handoff')
    with pytest.raises(ValueError):
        act(assistance, plan, 'intent', phrase='authorize fixture ' + plan['plan_id'])
    with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
        c.execute('UPDATE assistance_schema SET version=2')
    with pytest.raises(ValueError, match='version'):
        assistance.review(plan['plan_id'])


def test_new_session_can_only_explicitly_revoke_before_intent(sandbox):
    assistance = sandbox[0]
    original = create(sandbox)
    other = Assistance(assistance.dashboard.root, ORIGIN, 'new-session', True, assistance.clock)
    current = other.review(original['plan_id'])
    assert current['reconciliation_only']
    with pytest.raises(ValueError):
        act(other, current, 'fill')
    with pytest.raises(ValueError):
        act(other, current, 'revoke')
    revoked = act(other, current, 'revoke', phrase='REVOKE ' + current['plan_id'])
    assert revoked['state'] == 'revoked'
    with pytest.raises(ValueError):
        act(assistance, original, 'fill')


@pytest.mark.parametrize('variant', ['unverified', 'stale', 'conflict', 'oversized'])
def test_unusable_contact_attestations_are_withheld(sandbox, variant):
    assistance = sandbox[0]
    profile = json.loads(assistance.dashboard.profile.read_text())
    fact = profile['documents']['facts'][0]
    if variant == 'unverified':
        fact['verified'] = False
    elif variant == 'stale':
        profile['name'] = 'Changed fictional candidate'
    elif variant == 'conflict':
        profile['documents']['facts'].append({**fact, 'id': 'conflict', 'value': 'Other candidate'})
    else:
        profile['name'] = fact['value'] = 'x' * 201
    assistance.dashboard.profile.write_text(json.dumps(profile))
    review = assistance.dashboard.action('prepare', {'id': 'fixture', 'confirm': 'prepare'})['review']
    assistance.dashboard.action('approve', {'id': 'fixture', 'phrase': 'APPROVE fixture',
                                           'review_token': review['review_token']})
    plan = assistance.create('fixture', review['review_token'])
    assert plan['fields'][0] == {'name': 'name', 'manual': True}
    assert plan['fields'][1]['value'] == 'fictional@example.test'


def test_intent_expiry_keeps_ambiguity_and_allows_explicit_reconciliation(sandbox):
    assistance, _, now = sandbox
    plan = intent(sandbox)
    now[0] += TTL_SECONDS
    with pytest.raises(ValueError, match='expired'):
        act(assistance, plan, 'observe')
    current = assistance.review(plan['plan_id'])
    assert current['state'] == 'needs_manual_reconciliation'
    assert not current['fixture_ui_observed']
    reconciled = act(assistance, current, 'reconcile', phrase='RECONCILE ' + plan['plan_id'],
                     outcome='unknown', provenance='Fictional manual inspection after restart')
    assert reconciled['state'] == 'needs_manual_reconciliation'


@pytest.mark.parametrize('stage', ['handoff', 'intent', 'resume'])
def test_binding_is_rechecked_after_fill_and_handoff(sandbox, stage):
    assistance = sandbox[0]
    plan = act(assistance, create(sandbox, 'mfa' if stage == 'resume' else 'none'), 'fill')
    if stage in ('intent', 'resume'):
        plan = act(assistance, plan, 'handoff')
    with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
        c.execute("UPDATE application_bindings SET approved_token=NULL")
    with pytest.raises(ValueError, match='changed'):
        act(assistance, plan, stage, phrase='AUTHORIZE FIXTURE ' + plan['plan_id'], challenge_ack=True)
    assert assistance.review(plan['plan_id'])['state'] == 'invalidated'


def test_immutable_snapshot_digest_rejects_modified_plan(sandbox):
    assistance = sandbox[0]
    plan = create(sandbox)
    with sqlite3.connect(assistance.dashboard.data / 'agent.db') as c:
        snapshot = json.loads(c.execute('SELECT snapshot_json FROM assistance_plans').fetchone()[0])
        snapshot['company'] = 'Changed employer'
        c.execute('UPDATE assistance_plans SET snapshot_json=?', (json.dumps(snapshot),))
    with pytest.raises(ValueError, match='integrity'):
        assistance.review(plan['plan_id'])
    with pytest.raises(ValueError, match='integrity'):
        act(assistance, plan, 'fill')


@pytest.mark.parametrize('new_session', [False, True])
def test_unknown_reconciliation_irreversibly_closes_fixture_control(sandbox, new_session):
    assistance = sandbox[0]
    original = intent(sandbox)
    actor = (Assistance(assistance.dashboard.root, ORIGIN, 'new-authenticated-session', True, assistance.clock)
             if new_session else assistance)
    current = actor.review(original['plan_id'])
    assert not current['can_observe']
    assert 'observe_token' not in current
    with pytest.raises(ValueError):
        act(actor, current, 'observe')
    reconciled = act(actor, current, 'reconcile', phrase='RECONCILE ' + current['plan_id'],
                     outcome='unknown', provenance='Fictional operator uncertain after interruption')
    assert not reconciled['fixture_ui_observed']
    assert not reconciled['can_observe']
    assert 'observe_token' not in reconciled
    for possible in (original, reconciled, actor.review(original['plan_id'])):
        with pytest.raises(ValueError):
            act(actor, possible, 'observe')
    # Unknown may be resolved later, but never recreates the old fixture control.
    done = act(actor, reconciled, 'reconcile', phrase='RECONCILE ' + current['plan_id'],
               outcome='not_submitted', provenance='Fictional later operator inspection')
    assert done['state'] == 'reconciled_not_submitted'


def test_review_and_list_never_redisclose_observe_capability(sandbox):
    assistance = sandbox[0]
    plan = intent(sandbox)
    assert plan['can_observe']
    assert plan['observe_token'] != plan['action_token']
    for inspected in (assistance.review(plan['plan_id']), assistance.list_for_job('fixture')[0]):
        assert not inspected['can_observe']
        assert 'observe_token' not in inspected
        with pytest.raises(ValueError):
            act(assistance, inspected, 'observe')
    assert act(assistance, plan, 'observe')['fixture_ui_observed']


@pytest.mark.parametrize('token', ['é', 'x' * 1000, '', None, {}, 123])
def test_malformed_action_tokens_fail_closed(sandbox, token):
    assistance = sandbox[0]
    plan = create(sandbox)
    with pytest.raises(ValueError, match='token'):
        assistance.act(plan['plan_id'], 'fill', token, {'form_fingerprint': FORM_FINGERPRINT})
    assert assistance.review(plan['plan_id'])['state'] == 'plan'

@pytest.mark.parametrize('email',['not-an-email','fictional@example.test\nextra'])
def test_verified_but_inapplicable_email_is_manual_only(sandbox,email):
    assistance=sandbox[0]
    profile=json.loads(assistance.dashboard.profile.read_text())
    profile['email']=email
    profile['documents']['facts'][1]['value']=email
    assistance.dashboard.profile.write_text(json.dumps(profile))
    if '\n' in email:
        with pytest.raises(ValueError):
            assistance.dashboard.action('prepare',{'id':'fixture','confirm':'prepare'})
        assert assistance.dashboard.store.get_job('fixture')['status']=='approved'
        return
    review=assistance.dashboard.action('prepare',{'id':'fixture','confirm':'prepare'})['review']
    assistance.dashboard.action('approve',{'id':'fixture','phrase':'APPROVE fixture','review_token':review['review_token']})
    plan=assistance.create('fixture',review['review_token'])
    assert plan['fields'][1]=={'name':'email','manual':True}


def test_cli_inspection_and_reconciliation_need_no_browser_or_session_export(sandbox,capsys):
    from internship_agent.browser_assistance_cli import main
    assistance=sandbox[0]
    plan=intent(sandbox)
    base=['--root',str(assistance.dashboard.root),'--origin',ORIGIN,'--plan-id',plan['plan_id']]
    assert main(['inspect',*base])==0
    inspected=capsys.readouterr().out
    assert 'action_token' not in inspected and 'review_token' not in inspected and 'observe_token' not in inspected
    assert main(['reconcile',*base,'--confirm','RECONCILE '+plan['plan_id'],'--outcome','unknown','--provenance','Fictional uncertain result'])==0
    assert json.loads(capsys.readouterr().out)['state']=='needs_manual_reconciliation'
    assert assistance.dashboard.store.get_job('fixture')['status']=='approved'
