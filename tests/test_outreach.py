"""Fictional offline registry/draft evidence; no networking or Google credentials."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from email import message_from_string

import pytest

from internship_agent.dashboard_data import DashboardData
from internship_agent.models import Job
from internship_agent.outreach import Outreach, TTL_DAYS
from internship_agent.service import Agent


@pytest.fixture
def outreach(tmp_path):
    (tmp_path / 'config').mkdir()
    profile = {'name': 'Fictional Candidate', 'email': 'candidate@example.test', 'skills': ['Python'],
               'documents': {'version': 1, 'facts': [
                   {'id': name, 'path': '/' + name, 'value': value, 'verified': True,
                    'source': 'Synthetic operator declaration', 'reviewed_on': '2026-11-01'}
                   for name, value in [('name', 'Fictional Candidate'), ('email', 'candidate@example.test')]]}}
    (tmp_path / 'config' / 'profile.json').write_text(json.dumps(profile), encoding='utf-8')
    agent = Agent(str(tmp_path / 'data'))
    agent.store.upsert_job(Job(id='fixture', provider='synthetic', source_id='fictional',
                              company='Fictional Employer', title='Software Intern', location='Remote',
                              description='Python', job_url='https://employer.test/jobs/fixture',
                              apply_url='https://employer.test/jobs/fixture'))
    dashboard = DashboardData(tmp_path)
    review = dashboard.action('prepare', {'id': 'fixture', 'confirm': 'prepare'})['review']
    dashboard.action('approve', {'id': 'fixture', 'phrase': 'APPROVE fixture', 'review_token': review['review_token']})
    now = [datetime(2026, 11, 6, tzinfo=timezone.utc)]
    return Outreach(tmp_path, clock=lambda: now[0]), review['review_token'], now


def act(outreach, action_name, **payload):
    return outreach.action(action_name, {'confirm': action_name, **payload})


def register(outreach, **overrides):
    payload = dict(job_id='fixture', employer='Fictional Employer', employer_domain='employer.test',
                   name='Fictional Recruiter', role='Recruiter', email='recruiter@employer.test',
                   source_url='https://employer.test/team', method='official', observed_at='2026-11-01T00:00:00Z')
    payload.update(overrides)
    return act(outreach, 'register-contact', **payload)


def verify(outreach, contact):
    return act(outreach, 'verify-contact', id=contact['contact_id'], phrase='VERIFY ' + contact['contact_id'],
               verifier='Fictional operator', expected_contact_hash=contact['contact_hash'])


def draft(fixture):
    outreach, packet, _ = fixture
    contact = verify(outreach, register(outreach))
    return act(outreach, 'create-draft', contact_id=contact['contact_id'], purpose='intro', packet_review_token=packet)


def reviewed(fixture):
    row = draft(fixture)
    row = act(fixture[0], 'edit-draft', id=row['draft_id'], subject='Question about Software Intern',
              body='Hello,\n\nCould you clarify the location of this role?\n\nFictional Candidate')
    return act(fixture[0], 'review-draft', id=row['draft_id'], phrase='REVIEW ' + row['draft_id'],
               expected_revision=row['revision'], expected_content_hash=row['content_hash'])


def send_payload(row):
    return dict(id=row['draft_id'], review_token=row['review_token'], sent_at='2026-11-05T00:00:00Z',
                message_id='<fictional-send@example.test>', thread_id='fictional-thread',
                evidence='Fictional operator inspected the sent message', certainty='confirmed')


def test_read_only_no_schema_or_bytes_changed(outreach):
    adapter = outreach[0]
    path = adapter.dashboard.data / 'agent.db'
    before = path.read_bytes()
    assert adapter.get('contacts')['contacts'] == []
    assert adapter.get('drafts')['drafts'] == []
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        adapter.get('contact', {'id': 'missing'})
    with adapter._connection() as (c, exists):
        assert not exists
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='outreach_schema'").fetchone()


def test_failed_creation_rolls_back_schema(outreach):
    with pytest.raises(ValueError):
        register(outreach[0], employer='Wrong Employer')
    with outreach[0]._connection() as (_, exists):
        assert not exists


@pytest.mark.parametrize('changes', [
    {'email': 'person@gmail.com'}, {'email': 'person@other.test'},
    {'email': 'person@employer.test\r\nBcc: attacker@example.test'},
    {'email': 'Fictional <person@employer.test>'}, {'email': 'pérson@employer.test'},
    {'employer_domain': 'empl0yer.test', 'email': 'person@empl0yer.test'},
    {'employer_domain': 'xn--employer.test', 'email': 'person@xn--employer.test'},
    {'employer_domain': 'gmail.com', 'email': 'person@gmail.com'},
    {'source_url': 'https://employer.test.evil.test/team'},
    {'source_url': 'https://employer.test@evil.test/team'},
    {'source_url': 'https://evil.test@employer.test/team'},
    {'source_url': 'http://employer.test/team'}, {'method': 'guessed'}, {'guessed': True},
    {'observed_at': '2026-11-07T00:00:00Z'}, {'observed_at': '2026-11-01T00:00:00'},
    {'observed_at': '2026-11-01T00:00:00-04:00'}, {'name': 'x' * 201},
])
def test_unsafe_provenance_is_rejected(outreach, changes):
    with pytest.raises(ValueError):
        register(outreach[0], **changes)


def test_manual_documentation_exact_evidence_and_no_inference(outreach):
    adapter = outreach[0]
    with pytest.raises(ValueError):
        register(adapter, method='manual', documentation='Found online')
    contact = register(adapter, method='manual', documentation='Fictional Employer explicitly lists recruiter@employer.test in operator supplied letter')
    assert verify(adapter, contact)['state'] == 'verified'


def test_explicit_phrases_and_verifier(outreach):
    adapter = outreach[0]
    contact = register(adapter)
    with pytest.raises(ValueError):
        adapter.action('verify-contact', {'id': contact['contact_id'], 'phrase': 'VERIFY ' + contact['contact_id']})
    for extras in ({'phrase': 'VERIFY wrong', 'verifier': 'Operator'}, {'phrase': 'VERIFY ' + contact['contact_id']}):
        with pytest.raises(ValueError):
            act(adapter, 'verify-contact', id=contact['contact_id'], **extras)
    assert verify(adapter, contact)['state'] == 'verified'


def test_global_address_collision_and_duplicate_name_conflict(outreach):
    adapter = outreach[0]
    first = register(adapter)
    with pytest.raises(ValueError):
        register(adapter, name='Different Recruiter')
    second = register(adapter, email='other@employer.test')
    assert second['state'] == 'conflict'
    with pytest.raises(ValueError):
        verify(adapter, second)
    assert adapter.get('contact', {'id': first['contact_id']})['state'] == 'conflict'


def test_contact_expiry_is_computed_without_read_mutation(outreach):
    adapter, _, now = outreach
    contact = verify(adapter, register(adapter))
    now[0] = datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=TTL_DAYS)
    path = adapter.dashboard.data / 'agent.db'
    before = path.read_bytes()
    assert adapter.get('contact', {'id': contact['contact_id']})['state'] == 'stale'
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        verify(adapter, contact)


def test_contact_edit_invalidates_verification_and_review(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    contact = act(adapter, 'edit-contact', id=row['contact_id'], role='Talent team')
    assert contact['state'] == 'unverified'
    current = adapter.get('draft', {'id': row['draft_id']})
    assert current['review_token'] is None and not current['current']
    with pytest.raises(ValueError):
        act(adapter, 'export-draft', id=row['draft_id'], review_token=row['review_token'])


def test_draft_requires_verified_contact_and_current_approved_packet(outreach):
    adapter, token, _ = outreach
    contact = register(adapter)
    with pytest.raises(ValueError):
        act(adapter, 'create-draft', contact_id=contact['contact_id'], purpose='intro', packet_review_token=token)
    verify(adapter, contact)
    with pytest.raises(ValueError):
        act(adapter, 'create-draft', contact_id=contact['contact_id'], purpose='intro', packet_review_token='wrong')
    with adapter._connection(write=True) as (c, _):
        c.execute('UPDATE application_bindings SET approved_token=NULL')
    with pytest.raises(ValueError):
        act(adapter, 'create-draft', contact_id=contact['contact_id'], purpose='intro', packet_review_token=token)


def test_template_has_no_submission_claim_and_prompts_must_be_resolved(outreach):
    row = draft(outreach)
    assert 'I applied' not in row['body'] and 'submitted' not in row['body']
    assert '[ADD YOUR QUESTION' in row['body']
    with pytest.raises(ValueError):
        act(outreach[0], 'review-draft', id=row['draft_id'], phrase='REVIEW ' + row['draft_id'],
            expected_revision=row['revision'], expected_content_hash=row['content_hash'])
    serialized = json.dumps(row)
    assert str(outreach[0].dashboard.profile) not in serialized
    assert 'Python' not in row['body']  # Legacy skill is unverified.


def test_revisions_immutable_export_never_records_send(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    exported = act(adapter, 'export-draft', id=row['draft_id'], review_token=row['review_token'])
    parsed = message_from_string(exported['rfc822'])
    assert parsed['To'] == 'recruiter@employer.test'
    assert parsed['From'] == 'candidate@example.test'
    assert not exported['sent']
    with adapter._connection() as (c, _):
        assert c.execute('SELECT COUNT(*) FROM outreach_sends').fetchone()[0] == 0
        original = c.execute('SELECT * FROM outreach_draft_revisions').fetchone()
        assert original['revision'] == 1 and '[ADD YOUR QUESTION' in original['body']
    changed = act(adapter, 'edit-draft', id=row['draft_id'], subject='Updated subject', body='Updated manual message')
    assert changed['revision'] == 3 and changed['review_token'] is None
    with pytest.raises(ValueError):
        act(adapter, 'export-draft', id=row['draft_id'], review_token=row['review_token'])


@pytest.mark.parametrize('change', ['profile', 'job', 'packet', 'contact'])
def test_drift_blocks_export_and_send(outreach, change):
    adapter = outreach[0]
    row = reviewed(outreach)
    if change == 'profile':
        profile = json.loads(adapter.dashboard.profile.read_text())
        profile['skills'].append('Fictional Skill')
        adapter.dashboard.profile.write_text(json.dumps(profile))
    elif change == 'job':
        with adapter._connection(write=True) as (c, _):
            c.execute("UPDATE jobs SET title='Changed role'")
    elif change == 'packet':
        with adapter._connection() as (c, _):
            packet = json.loads(c.execute('SELECT packet_json FROM application_bindings').fetchone()[0])
        from pathlib import Path
        Path(packet['answers_path']).write_bytes(b'changed')
    else:
        act(adapter, 'edit-contact', id=row['contact_id'], role='Updated role')
    for action, payload in [('export-draft', dict(id=row['draft_id'], review_token=row['review_token'])),
                            ('record-send', send_payload(row))]:
        with pytest.raises(ValueError):
            act(adapter, action, **payload)


def test_header_injection_and_oversized_body_rejected(outreach):
    row = draft(outreach)
    for subject, body in [('Hello\r\nBcc: other@example.test', 'body'), ('Subject', 'x' * 10001),
                          ('x' * 201, 'body'), ('Subject', 'body\x00')]:
        with pytest.raises(ValueError):
            act(outreach[0], 'edit-draft', id=row['draft_id'], subject=subject, body=body)


def test_send_records_are_operator_evidence_idempotent_and_immutable(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    payload = send_payload(row)
    first = act(adapter, 'record-send', **payload)
    second = act(adapter, 'record-send', **payload)
    assert first['send_id'] == second['send_id'] and second['idempotent']
    assert not first['externally_verified']
    with pytest.raises(ValueError):
        act(adapter, 'record-send', **{**payload, 'sent_at': '2026-11-04T00:00:00Z'})
    with pytest.raises(ValueError):
        act(adapter, 'record-send', **{**payload, 'message_id': '<different@example.test>'})
    with adapter._connection() as (c, _):
        assert c.execute('SELECT COUNT(*) FROM outreach_sends').fetchone()[0] == 1
        assert c.execute('SELECT sent_at FROM outreach_sends').fetchone()[0] == '2026-11-05T00:00:00+00:00'


@pytest.mark.parametrize('override', [{'sent_at': '2026-11-07T00:00:00Z'}, {'certainty': 'yes'},
                                     {'evidence': ''}, {'message_id': 'missing-brackets'}, {'thread_id': 'bad\nheader'}])
def test_invalid_manual_send_evidence(outreach, override):
    row = reviewed(outreach)
    with pytest.raises(ValueError):
        act(outreach[0], 'record-send', **{**send_payload(row), **override})


def test_future_schema_refuses_all_reads_and_writes(outreach):
    adapter = outreach[0]
    register(adapter)
    with adapter._connection(write=True) as (c, _):
        c.execute('UPDATE outreach_schema SET version=2')
    path = adapter.dashboard.data / 'agent.db'
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Unsupported'):
        adapter.get('contacts')
    with pytest.raises(ValueError, match='Unsupported'):
        register(adapter, email='second@employer.test')
    assert path.read_bytes() == before


def test_optout_suppresses_existing_draft_and_cannot_be_reversed(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    cid = row['contact_id']
    with pytest.raises(ValueError):
        act(adapter, 'optout', id=cid)
    assert act(adapter, 'optout', id=cid, phrase='OPTOUT ' + cid)['state'] == 'opted_out'
    with pytest.raises(ValueError):
        act(adapter, 'edit-contact', id=cid, permission='allowed')
    with pytest.raises(ValueError):
        act(adapter, 'export-draft', id=row['draft_id'], review_token=row['review_token'])


def test_stale_preview_cannot_review_an_unseen_revision(outreach):
    adapter = outreach[0]
    preview = draft(outreach)
    current = act(adapter, 'edit-draft', id=preview['draft_id'], subject='Changed by another operator', body='A different exact body')
    with pytest.raises(ValueError, match='changed since preview'):
        act(adapter, 'review-draft', id=preview['draft_id'], phrase='REVIEW ' + preview['draft_id'],
            expected_revision=preview['revision'], expected_content_hash=preview['content_hash'])
    assert adapter.get('draft', {'id': preview['draft_id']})['review_token'] is None
    assert act(adapter, 'review-draft', id=current['draft_id'], phrase='REVIEW ' + current['draft_id'],
               expected_revision=current['revision'], expected_content_hash=current['content_hash'])['review_token']


def test_review_requires_exact_preview_content_hash_even_at_same_revision(outreach):
    adapter = outreach[0]
    row = draft(outreach)
    for missing_or_wrong in ({}, {'expected_revision': row['revision'], 'expected_content_hash': 'wrong'}):
        with pytest.raises(ValueError):
            act(adapter, 'review-draft', id=row['draft_id'], phrase='REVIEW ' + row['draft_id'], **missing_or_wrong)


def test_recorded_send_stays_bound_to_immutable_draft_revision(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    payload = send_payload(row)
    act(adapter, 'record-send', **payload)
    edited = act(adapter, 'edit-draft', id=row['draft_id'], subject='Different', body='New body')
    current = act(adapter, 'review-draft', id=edited['draft_id'], phrase='REVIEW ' + edited['draft_id'],
                  expected_revision=edited['revision'], expected_content_hash=edited['content_hash'])
    with pytest.raises(ValueError, match='Contradictory'):
        act(adapter, 'record-send', **{**payload, 'review_token': current['review_token']})
    with adapter._connection() as (c, _):
        send = c.execute('SELECT * FROM outreach_sends').fetchone()
        assert send['draft_revision'] == row['revision']
        assert send['draft_content_hash'] == row['content_hash']
        assert send['recipient_hash'] and send['binding_hash']


def test_redaction_clears_related_pii_retains_suppression_and_job_history(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    act(adapter, 'record-send', **send_payload(row))
    cid = row['contact_id']
    result = act(adapter, 'redact-contact', id=cid, phrase='REDACT ' + cid)
    assert result['state'] == 'redacted' and result['email'] == result['name'] == ''
    with adapter._connection() as (c, _):
        send = c.execute('SELECT * FROM outreach_sends').fetchone()
        assert send['from_email'] == send['to_email'] == send['evidence'] == ''
        assert send['evidence_hash'] and send['draft_content_hash']
        assert c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM applications').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM outreach_suppressions').fetchone()[0] == 1
        assert c.execute('SELECT body FROM outreach_draft_revisions').fetchone()[0] == ''
    with pytest.raises(ValueError):
        register(adapter, email='RECRUITER@employer.test')
    assert adapter.get('draft', {'id': row['draft_id']})['body'] == ''


def test_message_future_schema_refuses_even_contact_actions(outreach):
    adapter = outreach[0]
    contact = register(adapter)
    with adapter._connection(write=True) as (c, _):
        c.execute('CREATE TABLE outreach_messages_schema(version INTEGER NOT NULL)')
        c.execute('INSERT INTO outreach_messages_schema VALUES(2)')
    with pytest.raises(ValueError, match='Unsupported correspondence'):
        verify(adapter, contact)


def test_missing_ledger_read_projections_are_empty_and_create_no_files(tmp_path):
    adapter = Outreach(tmp_path)
    assert adapter.get('contacts')['contacts'] == []
    assert adapter.get('drafts')['drafts'] == []
    assert not (tmp_path / 'data').exists()
    with pytest.raises(ValueError):
        adapter.get('draft', {'id': 'missing'})


def test_unicode_draft_body_exports_safely(outreach):
    adapter = outreach[0]
    row = draft(outreach)
    row = act(adapter, 'edit-draft', id=row['draft_id'], subject='Question — rôle', body='Bonjour,\nQuel rôle est disponible ?\n候補者')
    row = act(adapter, 'review-draft', id=row['draft_id'], phrase='REVIEW ' + row['draft_id'],
              expected_revision=row['revision'], expected_content_hash=row['content_hash'])
    export = act(adapter, 'export-draft', id=row['draft_id'], review_token=row['review_token'])
    assert 'MIME-Version: 1.0' in export['rfc822'] and not export['sent']


def test_contact_verification_binds_the_exact_preview(outreach):
    adapter = outreach[0]
    old = register(adapter)
    new = act(adapter, 'edit-contact', id=old['contact_id'], email='different@employer.test')
    with pytest.raises(ValueError, match='changed since preview'):
        verify(adapter, old)
    with pytest.raises(ValueError):
        verify(adapter, new)  # Changed address needs explicit conflict resolution.
    verified = act(adapter, 'verify-contact', id=new['contact_id'], phrase='VERIFY ' + new['contact_id'],
                   expected_contact_hash=new['contact_hash'], verifier='Fictional operator',
                   resolution='Operator inspected the updated official directory for this exact identity')
    assert verified['email'] == 'different@employer.test' and verified['state'] == 'verified'
    with pytest.raises(ValueError):
        register(adapter, email=old['email'], name='Another Name')


def test_new_conflicting_identity_blocks_old_verified_contact_and_drafts(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    new = register(adapter, email='other@employer.test')
    assert new['state'] == 'conflict'
    old = adapter.get('contact', {'id': row['contact_id']})
    assert old['state'] == 'conflict'
    with pytest.raises(ValueError):
        act(adapter, 'export-draft', id=row['draft_id'], review_token=row['review_token'])
    with pytest.raises(ValueError, match='Unresolved conflicting'):
        act(adapter, 'verify-contact', id=old['contact_id'], phrase='VERIFY ' + old['contact_id'],
            expected_contact_hash=old['contact_hash'], verifier='Fictional operator', resolution='Inspected source')
    act(adapter, 'redact-contact', id=new['contact_id'], phrase='REDACT ' + new['contact_id'])
    assert act(adapter, 'verify-contact', id=old['contact_id'], phrase='VERIFY ' + old['contact_id'],
               expected_contact_hash=old['contact_hash'], verifier='Fictional operator', resolution='Incorrect conflicting identity redacted')['state'] == 'verified'


@pytest.mark.parametrize('token', [None, '', 'wrong'])
def test_unreviewed_drafts_cannot_export_or_record_with_absent_token(outreach, token):
    row = draft(outreach)
    with pytest.raises(ValueError):
        act(outreach[0], 'export-draft', id=row['draft_id'], review_token=token)
    with pytest.raises(ValueError):
        act(outreach[0], 'record-send', **{**send_payload(row), 'review_token': token})


def test_changed_address_conflict_cannot_be_bypassed_by_another_edit(outreach):
    adapter = outreach[0]
    old = register(adapter)
    changed = act(adapter, 'edit-contact', id=old['contact_id'], email='new@employer.test')
    revised = act(adapter, 'edit-contact', id=old['contact_id'], role='Changed role')
    assert changed['state'] == revised['state'] == 'conflict'
    with pytest.raises(ValueError):
        verify(adapter, revised)


def test_edited_identity_collision_invalidates_other_contact(outreach):
    adapter = outreach[0]
    row = reviewed(outreach)
    other = register(adapter, email='other@employer.test', name='Other Person')
    edited = act(adapter, 'edit-contact', id=other['contact_id'], name='FICTIONAL RECRUITER')
    assert edited['state'] == 'conflict'
    assert adapter.get('contact', {'id': row['contact_id']})['state'] == 'conflict'
    with pytest.raises(ValueError):
        act(adapter, 'export-draft', id=row['draft_id'], review_token=row['review_token'])
