"""Fictional manual correspondence; no accounts, credentials or network."""
from datetime import datetime, timezone
import sqlite3

import pytest

from internship_agent.outreach_messages import Correspondence


def message(**changes):
    return dict(message_id='<reply@fictional.test>', thread_id='fictional-thread',
                from_email='recruiter@fictional.test', to_email='candidate@example.test',
                cc=[], in_reply_to='<sent@example.test>', references=[],
                sent_at='2026-11-05T12:00:00+00:00', subject='Synthetic reply',
                body='Fictional fixture only.', text_format='plain', forwarded=False,
                bounce=False, optout=False, **changes)


def act(agent, action, **payload):
    return agent.action(action, {'confirm': action, **payload})


@pytest.fixture
def correspondence(tmp_path):
    from internship_agent.service import Agent
    from internship_agent.outreach import Outreach
    from internship_agent.models import Job
    Agent(str(tmp_path / 'data')).store.upsert_job(Job(
        id='fictional-job', provider='synthetic', company='Fictional Employer',
        source_id='fictional', title='Intern', location='Remote', description='Python',
        job_url='https://fictional.test/jobs/1', apply_url='https://fictional.test/jobs/1'))
    now = [datetime(2026, 11, 6, 12, tzinfo=timezone.utc)]
    agent = Correspondence(tmp_path, clock=lambda: now[0])
    core = Outreach(tmp_path, clock=lambda: now[0])
    with core._connection(write=True, create=True) as (c, _):
        c.execute('''INSERT INTO outreach_contacts
            (contact_id,job_id,employer_id,employer,employer_domain,name,role,email,address_hash,
             state,source_url,documentation,observed_at,verifier,method,permission,
             created_at,updated_at,verified_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('contact', 'fictional-job', 'fictional', 'Fictional Employer', 'fictional.test',
             'Fictional Recruiter', 'Recruiter', 'recruiter@fictional.test', 'fixture-contact-hash',
             'verified', 'https://fictional.test/team', 'Fictional operator documentation',
             '2026-11-01T12:00:00+00:00', 'Fictional operator', 'manual', 'allowed',
             '2026-11-01T12:00:00+00:00', '2026-11-01T12:00:00+00:00',
             '2026-11-01T12:00:00+00:00'))
        c.execute('''INSERT INTO outreach_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                  ('draft', 'contact', 'fictional-job', 'intro', 'Fictional subject',
                   'Fictional body', 1, '{}', 'fictional-draft-hash', None,
                   '2026-10-20T12:00:00+00:00', '2026-10-20T12:00:00+00:00'))
        c.execute('''INSERT INTO outreach_sends
            (send_id,contact_id,job_id,draft_id,sent_at,message_id,thread_id,from_email,
             to_email,evidence,certainty,evidence_hash,created_at,draft_revision,
             draft_content_hash,recipient_hash,binding_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('send', 'contact', 'fictional-job', 'draft', '2026-10-20T12:00:00+00:00',
             '<sent@example.test>', 'fictional-thread', 'candidate@example.test',
             'recruiter@fictional.test', 'Fictional manually inspected sent copy', 'confirmed',
             'fictional-evidence-hash', '2026-10-20T12:00:00+00:00', 1,
             'fictional-draft-hash', 'fictional-recipient-hash', 'fictional-binding-hash'))
    return agent, core, now


def test_get_never_creates_schema(correspondence):
    agent, core, _ = correspondence
    path = core.dashboard.root / 'data' / 'agent.db'
    before = path.read_bytes()
    assert agent.get('messages', {})['items'] == []
    assert agent.get('followups', {})['items'] == []
    assert path.read_bytes() == before


def test_import_strong_match_is_explicitly_unverified_and_idempotent(correspondence):
    agent, _, _ = correspondence
    result = act(agent, 'import-message', message=message(), operation_id='operation-1', checkpoint='1')
    assert result['message']['match_state'] == 'matched_unverified'
    assert result['message']['source'] == 'manual_import_unverified'
    assert 'body' not in result['message']
    again = act(agent, 'import-message', message=message(), operation_id='operation-1', checkpoint='1')
    assert again['idempotent'] is True
    assert len(agent.get('messages', {})['items']) == 1


@pytest.mark.parametrize('change', [
    {'from_email': 'alias@fictional.test'}, {'to_email': 'other@example.test'},
    {'thread_id': 'other-thread'}, {'in_reply_to': '', 'references': []},
    {'cc': ['other@example.test']}, {'forwarded': True},
    {'to_email': 'candidate@example.test,other@example.test'},
])
def test_weak_or_ambiguous_headers_never_match(correspondence, change):
    agent, _, _ = correspondence
    incoming = message()
    incoming.update(change)
    try:
        row = act(agent, 'import-message', message=incoming)['message']
    except ValueError:
        assert ',' in incoming['to_email']
    else:
        assert row['match_state'] == 'review_only'


def test_collision_preserves_original_invalidates_match_and_suppresses(correspondence):
    agent, _, _ = correspondence
    original = act(agent, 'import-message', message=message())['message']
    altered = message()
    altered['body'] = 'A different immutable message body'
    collision = act(agent, 'import-message', message=altered)['message']
    assert collision['collided'] and collision['match_state'] == 'review_only'
    assert agent.get('message', {'id': original['id']})['body'] == message()['body']
    with pytest.raises(ValueError):
        act(agent, 'match-message', id=original['id'])
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    assert agent.get('followups', {})['items'] == []


def test_followup_utc_dst_readonly_stable_and_dismissed_after_restart(correspondence):
    agent, core, now = correspondence
    act(agent, 'followup-policy', contact_id='contact', interval_days=14, min_days=7, enabled=True)
    path = core.dashboard.root / 'data' / 'agent.db'
    before = path.read_bytes()
    first = agent.get('followups', {})['items'][0]
    assert first['due_at'] == '2026-11-03T12:00:00+00:00'
    assert agent.get('followups', {})['items'][0]['id'] == first['id']
    assert path.read_bytes() == before
    act(agent, 'dismiss-followup', id=first['id'])
    reopened = Correspondence(core.dashboard.root, clock=lambda: now[0])
    assert reopened.get('followups', {})['items'] == []


@pytest.mark.parametrize('certainty,evidence,sent_at', [
    ('uncertain', 'Fictional manual export', '2026-10-20T12:00:00+00:00'),
    ('confirmed', '', '2026-10-20T12:00:00+00:00'),
    ('confirmed', 'Fictional future evidence', '2026-11-07T12:00:00+00:00'),
])
def test_uncertain_export_missing_evidence_or_future_send_no_followup(correspondence, certainty, evidence, sent_at):
    agent, core, _ = correspondence
    with core._connection(write=True) as (c, _):
        c.execute('UPDATE outreach_sends SET certainty=?,evidence=?,sent_at=?', (certainty, evidence, sent_at))
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    assert agent.get('followups', {})['items'] == []


@pytest.mark.parametrize('change', [{'optout': True}, {'bounce': True}, {'in_reply_to': ''}])
def test_unclear_reply_optout_bounce_and_redaction_keep_suppression(correspondence, change):
    agent, _, _ = correspondence
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    incoming = message()
    incoming.update(change)
    row = act(agent, 'import-message', message=incoming)['message']
    assert agent.get('followups', {})['items'] == []
    act(agent, 'redact-message', id=row['id'])
    detail = agent.get('message', {'id': row['id']})
    assert detail['body'] == '' and detail['subject'] == ''
    assert agent.get('followups', {})['items'] == []


def test_html_inert_bounded_detail_attachments_and_paths_rejected(correspondence):
    agent, _, _ = correspondence
    incoming = message()
    incoming.update(text_format='html', body='<img src="https://fictional.test/tracker">' + 'a' * 9000)
    row = act(agent, 'import-message', message=incoming)['message']
    detail = agent.get('message', {'id': row['id']})
    assert detail['text_format'] == 'html' and detail['body'].startswith('<img')
    assert len(detail['body']) == 8000 and detail['body_truncated']
    for field in ('path', 'attachments', 'profile_path'):
        bad = message()
        bad[field] = '/tmp/private'
        with pytest.raises(ValueError):
            act(agent, 'import-message', message=bad)


def test_missing_confirmation_rejected_before_schema(correspondence):
    agent, core, _ = correspondence
    before = (core.dashboard.root / 'data' / 'agent.db').read_bytes()
    with pytest.raises(ValueError):
        agent.action('import-message', {'message': message()})
    assert (core.dashboard.root / 'data' / 'agent.db').read_bytes() == before


def test_crash_rolls_back_schema_and_message_and_operation(correspondence, monkeypatch):
    agent, core, _ = correspondence
    def crash(*args, **kwargs):
        raise RuntimeError('Synthetic crash')
    monkeypatch.setattr(agent, '_event', crash)
    with pytest.raises(RuntimeError):
        act(agent, 'import-message', message=message(), operation_id='crash-1', checkpoint='1')
    with sqlite3.connect(core.dashboard.root / 'data' / 'agent.db') as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='outreach_messages'").fetchone()
    reopened = Correspondence(core.dashboard.root, clock=agent.core.clock)
    row = act(reopened, 'import-message', message=message(), operation_id='crash-1', checkpoint='1')
    assert not row['idempotent']


def test_future_schema_rejected_read_and_write(correspondence):
    agent, core, _ = correspondence
    act(agent, 'import-message', message=message())
    with core._connection(write=True) as (c, _):
        c.execute('UPDATE outreach_messages_schema SET version=99')
    with pytest.raises(ValueError):
        agent.get('messages', {})
    with pytest.raises(ValueError):
        act(agent, 'import-message', message=message())


def test_reordered_imports_and_operation_reuse_never_overwrite(correspondence):
    agent, _, _ = correspondence
    later = message()
    later.update(message_id='<later@fictional.test>', sent_at='2026-11-06T10:00:00+00:00')
    act(agent, 'import-message', message=later, operation_id='later', checkpoint='2')
    original = act(agent, 'import-message', message=message(), operation_id='earlier', checkpoint='1')['message']
    assert len(agent.get('messages', {})['items']) == 2
    changed = message()
    changed['body'] = 'Fictional operation conflict'
    with pytest.raises(ValueError, match='checkpoint'):
        act(agent, 'import-message', message=changed, operation_id='earlier', checkpoint='1')
    assert agent.get('message', {'id': original['id']})['body'] == message()['body']
    assert not agent.get('message', {'id': original['id']})['collided']


@pytest.mark.parametrize('change', [
    {'message_id': '<sent@example.test>'}, {'subject': 'Fwd: Synthetic reply'},
    {'body': '---------- Forwarded message ---------\nFictional sender'},
])
def test_send_id_reuse_and_conventional_forward_markers_are_review_only(correspondence, change):
    agent, _, _ = correspondence
    incoming = message()
    incoming.update(change)
    assert act(agent, 'import-message', message=incoming)['message']['match_state'] == 'review_only'


@pytest.mark.parametrize('field,value', [
    ('permission', 'unknown'), ('permission', 'denied'), ('state', 'unverified'),
    ('state', 'opted_out'), ('observed_at', '2025-01-01T00:00:00+00:00'),
])
def test_contact_current_verification_and_permissions_rechecked(correspondence, field, value):
    agent, core, _ = correspondence
    imported = act(agent, 'import-message', message=message())['message']
    with core._connection(write=True) as (c, _):
        c.execute('UPDATE outreach_contacts SET ' + field + '=?', (value,))
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    assert agent.get('followups', {})['items'] == []
    if field != 'permission' or value == 'denied':
        with pytest.raises(ValueError):
            act(agent, 'match-message', id=imported['id'])


def test_reply_binding_rechecks_header_collision_and_redaction(correspondence):
    agent, core, _ = correspondence
    row = act(agent, 'import-message', message=message())['message']
    with core._connection() as (c, _):
        assert agent._reply_binding(c, row['id'], 'contact')['source'] == 'manual_import_unverified'
    act(agent, 'redact-message', id=row['id'])
    with core._connection() as (c, _):
        with pytest.raises(ValueError):
            agent._reply_binding(c, row['id'], 'contact')


def test_redact_contact_scrubs_matched_and_unknown_messages(correspondence):
    agent, core, _ = correspondence
    matched = act(agent, 'import-message', message=message())['message']
    unknown = message()
    unknown.update(message_id='<unknown@fictional.test>', in_reply_to='', subject='Fictional private')
    unknown = act(agent, 'import-message', message=unknown)['message']
    with core._connection(write=True) as (c, _):
        agent._redact_contact(c, 'contact')
    for row in (matched, unknown):
        detail = agent.get('message', {'id': row['id']})
        assert detail['redacted'] and detail['body'] == '' and detail['from_email'] == ''


def test_explicit_retention_is_bounded_no_get_pruning_and_keeps_suppression(correspondence):
    agent, core, now = correspondence
    row = act(agent, 'import-message', message=message())['message']
    with core._connection(write=True) as (c, _):
        c.execute("UPDATE outreach_messages SET imported_at='2026-09-01T00:00:00+00:00'")
    assert agent.get('message', {'id': row['id']})['body']
    for days in (29, 3651, True, '30'):
        with pytest.raises(ValueError):
            act(agent, 'prune-messages', retention_days=days)
    result = act(agent, 'prune-messages', retention_days=30)
    assert result == {'redacted_count': 1, 'more_eligible': False, 'retention_days': 30, 'batch_limit': 100}
    assert agent.get('message', {'id': row['id']})['body'] == ''
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    assert agent.get('followups', {})['items'] == []
    assert act(agent, 'prune-messages', retention_days=30)['redacted_count'] == 0


def test_imported_optout_persists_shared_suppression_after_redaction(correspondence):
    agent, core, _ = correspondence
    incoming = message()
    incoming['optout'] = True
    row = act(agent, 'import-message', message=incoming)['message']
    act(agent, 'redact-message', id=row['id'])
    with core._connection() as (c, _):
        assert c.execute('SELECT reason FROM outreach_suppressions').fetchone()[0] == 'manual_message_optout'
        with pytest.raises(ValueError):
            core._contact(c, 'contact', usable=True)


def test_future_core_schema_rejects_without_mutation(correspondence):
    agent, core, _ = correspondence
    with core._connection(write=True) as (c, _):
        c.execute('UPDATE outreach_schema SET version=99')
    path = core.dashboard.root / 'data' / 'agent.db'
    before = path.read_bytes()
    with pytest.raises(ValueError):
        agent.get('messages', {})
    with pytest.raises(ValueError):
        act(agent, 'import-message', message=message())
    assert path.read_bytes() == before


@pytest.mark.parametrize('sender,bounce', [('mailer-daemon@fictional.test', True),
                                         ('unknown@fictional.test', False)])
def test_unknown_sender_with_exact_reply_references_suppresses_without_match(correspondence, sender, bounce):
    agent, _, _ = correspondence
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    assert len(agent.get('followups', {})['items']) == 1
    incoming = message()
    incoming.update(from_email=sender, bounce=bounce)
    row = act(agent, 'import-message', message=incoming)['message']
    assert row['match_state'] == 'review_only' and row['contact_id'] is None
    assert agent.get('followups', {})['items'] == []
    act(agent, 'redact-message', id=row['id'])
    assert agent.get('followups', {})['items'] == []


@pytest.mark.parametrize('sender,state', [('recruiter@FICTIONAL.TEST', 'matched_unverified'),
                                         ('RECRUITER@fictional.test', 'review_only')])
def test_email_domain_normalization_local_case_review_and_privacy(correspondence, sender, state):
    agent, core, _ = correspondence
    incoming = message()
    incoming.update(from_email=sender, in_reply_to='', references=['<sent@example.test>'])
    row = act(agent, 'import-message', message=incoming)['message']
    assert row['match_state'] == state
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    assert agent.get('followups', {})['items'] == []
    with core._connection(write=True) as (c, _):
        agent._redact_contact(c, 'contact')
    assert agent.get('message', {'id': row['id']})['body'] == ''


def test_case_variant_sender_without_reply_headers_still_suppresses(correspondence):
    agent, core, _ = correspondence
    incoming = message()
    incoming.update(from_email='RECRUITER@FICTIONAL.TEST', in_reply_to='', references=[])
    row = act(agent, 'import-message', message=incoming)['message']
    assert row['match_state'] == 'review_only'
    act(agent, 'followup-policy', contact_id='contact', interval_days=7, min_days=7, enabled=True)
    assert agent.get('followups', {})['items'] == []
    with core._connection(write=True) as (c, _):
        agent._redact_contact(c, 'contact')
    assert agent.get('message', {'id': row['id']})['body'] == ''


def test_contact_projection_keeps_optout_visible_after_redaction(correspondence):
    agent,core,_=correspondence
    incoming=message();incoming['optout']=True
    act(agent,'import-message',message=incoming)
    contact=core.get('contact',{'id':'contact'})
    assert contact['suppressed'] and contact['suppression_reason']
    assert any('suppressed' in warning for warning in contact['warnings'])
    core.action('redact-contact',{'confirm':'redact-contact','id':'contact','phrase':'REDACT contact'})
    redacted=core.get('contact',{'id':'contact'})
    assert redacted['email']=='' and redacted['suppressed']
    assert redacted['suppression_reason']
