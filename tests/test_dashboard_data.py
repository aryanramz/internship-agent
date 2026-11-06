"""Local dashboard fixtures are fictional and never access network or Google."""
import json
from pathlib import Path

import pytest

from internship_agent.dashboard_data import DashboardData, MAX_DOCUMENT_BYTES
from internship_agent.models import Job
from internship_agent.service import Agent


@pytest.fixture
def dashboard(tmp_path):
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'profile.json').write_text(json.dumps({
        'name': 'Fictional Candidate', 'skills': ['Python'],
        'target_roles': ['Software Intern'], 'preferred_locations': ['Remote'],
    }), encoding='utf-8')
    (config / 'sources.json').write_text('{"boards": []}', encoding='utf-8')
    agent = Agent(str(tmp_path / 'data'))
    agent.store.upsert_job(Job(id='fictional-job', provider='synthetic', source_id='fictional-job',
                              company='Fictional Employer', title='Software Intern', location='Remote', description='Python',
                              job_url='https://example.test/jobs/fictional-job', apply_url='https://example.test/jobs/fictional-job'))
    return DashboardData(tmp_path)


def add_job(data, jid, **kwargs):
    values = dict(id=jid, provider='synthetic', source_id=jid, company='Fictional Employer',
                  title='Software Intern', location='Remote', description='Python',
                  job_url='https://example.test/jobs/' + jid,
                  apply_url='https://example.test/jobs/' + jid)
    values.update(kwargs)
    Agent(str(data.data)).store.upsert_job(Job(**values))


def prepare(data, jid='fictional-job'):
    return data.action('prepare', {'id': jid, 'confirm': 'prepare'})['review']


def approve(data, review):
    return data.action('approve', {'id': review['job_id'], 'phrase': 'APPROVE ' + review['job_id'],
                                   'review_token': review['review_token']})


def submit(data, review):
    approve(data, review)
    return data.action('submitted', {'id': review['job_id'], 'confirm': 'submitted',
                                     'review_token': review['review_token'], 'evidence': 'Fictional manual receipt'})


def test_overview_distinguishes_unknowns_from_fit_and_submission(dashboard):
    result = dashboard.get('overview', {})
    assert result['total_jobs'] == 1
    assert result['counts']['discovered'] == 1
    assert result['submitted'] == 0
    assert 'unknown' in result['definitions']['unknown']
    job = dashboard.get('jobs', {})['jobs'][0]
    assert isinstance(job['ranking']['score'], int)
    assert job['eligibility']['outcome'] == 'uncertain'
    assert job['availability']['status'] == 'unknown'
    assert 'Fictional Candidate' not in json.dumps(result)


def test_missing_profile_keeps_jobs_readable_as_unknown(dashboard):
    dashboard.profile.unlink()
    job = dashboard.get('jobs', {})['jobs'][0]
    assert job['ranking']['score'] is None
    assert job['eligibility']['outcome'] == 'unknown'
    assert dashboard.get('jobs', {'eligibility': 'unknown'})['total'] == 1
    assert dashboard.get('jobs', {'eligibility': 'uncertain'})['total'] == 0
    assert not dashboard.get('overview')['profile_available']


def test_pagination_does_not_truncate_at_legacy_store_limit(dashboard):
    # SQL selection, rather than Store.list_jobs(limit), covers the full ledger.
    for i in range(60):
        add_job(dashboard, f'fictional-{i:03d}')
    first = dashboard.get('jobs', {})
    second = dashboard.get('jobs', {'page': '2'})
    third = dashboard.get('jobs', {'page': '3'})
    assert first['total'] == 61
    assert first['pages'] == 3
    ids = [j['id'] for page in (first, second, third) for j in page['jobs']]
    assert len(ids) == len(set(ids)) == 61
    assert len(third['jobs']) == 11
    assert dashboard.get('jobs', {'page': '4'})['jobs'] == []


def test_filters_are_functional_and_parameterized(dashboard):
    add_job(dashboard, 'cloud-job', title='Cloud Engineering Intern', location='Example City')
    assert dashboard.get('jobs', {'track': 'cloud'})['total'] == 1
    assert dashboard.get('jobs', {'track': 'software', 'location': 'remote'})['total'] == 1
    assert dashboard.get('jobs', {'search': 'fictional employer', 'eligibility': 'uncertain', 'status': 'discovered'})['total'] == 2
    assert dashboard.get('jobs', {'search': "' OR 1=1 --"})['total'] == 0
    assert dashboard.get('jobs', {'search': '%'})['total'] == 0
    assert dashboard.get('jobs', {'eligibility': 'eligible'})['total'] == 0


@pytest.mark.parametrize('query', [{'page': '0'}, {'page': '-1'}, {'page': '1 OR 1=1'},
                                  {'status': 'forged'}, {'eligibility': 'review'}, {'track': 'unknown'},
                                  {'search': 'x' * 201}, {'path': '/tmp/file'}])
def test_invalid_queries_rejected(dashboard, query):
    with pytest.raises(ValueError):
        dashboard.get('jobs', query)


def test_prepare_review_and_exact_document_access(dashboard):
    review = prepare(dashboard)
    assert {d['kind'] for d in review['documents']} == {'resume', 'letter', 'answers'}
    assert 'DRAFT' in review['documents'][0]['text']
    assert review['qa']['structural_pass'] is True
    assert review['qa']['ats_guarantee'] is False
    for document in review['documents']:
        raw, filename = dashboard.document('fictional-job', review['review_token'], document['kind'])
        assert raw.startswith(b'PK')
        assert filename == document['filename']
        assert filename.endswith('.docx')
    serialized = json.dumps(review)
    assert str(dashboard.root) not in serialized
    assert 'trace_path' not in serialized
    assert 'profile_sha256' not in serialized
    detail = dashboard.get('job', {'id': 'fictional-job'})
    assert detail['history'][-1]['event_type'] == 'prepared'
    assert str(dashboard.root) not in json.dumps(detail)
    operations = dashboard.get('operations')
    assert operations['preparations'][0]['state'] == 'committed'
    assert str(dashboard.root) not in json.dumps(operations)


@pytest.mark.parametrize('kind', ['claims', 'qa', 'trace', '../resume.docx', '/etc/passwd'])
def test_download_only_named_docx_kinds(dashboard, kind):
    review = prepare(dashboard)
    with pytest.raises(ValueError):
        dashboard.document('fictional-job', review['review_token'], kind)


def test_complete_workflow_reuses_store_and_does_not_claim_employer_verification(dashboard):
    review = prepare(dashboard)
    assert approve(dashboard, review)['job']['status'] == 'approved'
    assert submit(dashboard, review)['job']['status'] == 'submitted'
    result = dashboard.action('status', {'id': 'fictional-job', 'confirm': 'status',
                                       'review_token': review['review_token'], 'status': 'interview',
                                       'evidence': 'Fictional interview invitation'})
    assert result['job']['status'] == 'interview'
    detail = dashboard.get('job', {'id': 'fictional-job'})
    assert detail['application']['submission_evidence_kind'] == 'user_supplied'
    assert detail['application']['employer_receipt_verified'] is False
    assert dashboard.get('overview')['outcomes']['interview'] == 1


@pytest.mark.parametrize('name', ['discover', 'prepare', 'submitted', 'status', 'recover'])
def test_writes_require_exact_explicit_confirmation(dashboard, name):
    with pytest.raises(ValueError, match='confirmation'):
        dashboard.action(name, {'id': 'fictional-job', 'confirm': True})


def test_approve_requires_exact_phrase_and_current_token(dashboard):
    review = prepare(dashboard)
    with pytest.raises(ValueError):
        dashboard.action('approve', {'id': 'fictional-job', 'phrase': 'approve fictional-job',
                                      'review_token': review['review_token']})
    for token in (None, '', 'a' * 64):
        with pytest.raises(ValueError):
            dashboard.action('approve', {'id': 'fictional-job', 'phrase': 'APPROVE fictional-job', 'review_token': token})
    assert dashboard.store.get_job('fictional-job')['status'] == 'prepared'


@pytest.mark.parametrize('mutation', ['profile', 'job', 'document', 'qa'])
def test_changed_inputs_block_review_download_and_all_status_writes(dashboard, mutation):
    review = prepare(dashboard)
    submit(dashboard, review)
    packet = dashboard.store.review('fictional-job')
    if mutation == 'profile':
        profile = json.loads(dashboard.profile.read_text())
        profile['skills'].append('Fictional New Skill')
        dashboard.profile.write_text(json.dumps(profile))
    elif mutation == 'job':
        add_job(dashboard, 'fictional-job', description='Changed posting')
    elif mutation == 'document':
        Path(packet['resume_path']).write_bytes(b'changed')
    else:
        qa_path = Path(packet['qa_path'])
        qa = json.loads(qa_path.read_text())
        qa['unresolved_count'] += 1
        qa_path.write_text(json.dumps(qa))
    with pytest.raises(ValueError):
        dashboard.get('review', {'id': 'fictional-job'})
    with pytest.raises(ValueError):
        dashboard.document('fictional-job', review['review_token'], 'resume')
    for action, extra in (('approve', {'phrase': 'APPROVE fictional-job'}),
                          ('submitted', {'evidence': 'Fictional manual receipt'}),
                          ('status', {'status': 'interview'})):
        with pytest.raises(ValueError):
            dashboard.action(action, {'id': 'fictional-job', 'confirm': action,
                                     'review_token': review['review_token'], **extra})
    assert dashboard.store.get_job('fictional-job')['status'] == 'submitted'


def test_stale_revision_token_is_rejected(dashboard):
    old = prepare(dashboard)
    dashboard.action('prepare', {'id': 'fictional-job', 'confirm': 'prepare', 'new_revision': True})
    with pytest.raises(ValueError):
        approve(dashboard, old)
    with pytest.raises(ValueError):
        dashboard.document('fictional-job', old['review_token'], 'resume')


@pytest.mark.parametrize('mutation', ['file_symlink', 'directory_symlink', 'oversized', 'foreign_path'])
def test_document_preflight_rejects_unsafe_packets(dashboard, tmp_path, mutation):
    review = prepare(dashboard)
    packet = dashboard.store.review('fictional-job')
    path = Path(packet['resume_path'])
    if mutation == 'file_symlink':
        target = tmp_path / 'other.docx'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    elif mutation == 'directory_symlink':
        original = path.parent
        target = original.with_name('moved')
        original.rename(target)
        original.symlink_to(target, target_is_directory=True)
    elif mutation == 'oversized':
        with path.open('wb') as stream:
            stream.truncate(MAX_DOCUMENT_BYTES + 1)
    else:
        packet['resume_path'] = str(tmp_path / 'resume.docx')
        with dashboard.store.connection() as c:
            c.execute('UPDATE application_bindings SET packet_json=?', (json.dumps(packet),))
    with pytest.raises(ValueError):
        dashboard.document('fictional-job', review['review_token'], 'resume')


def test_discover_and_recover_are_local_workflow_facades(dashboard, monkeypatch):
    calls = []
    def discover(self, path, **options):
        calls.append((path, options))
        return {'added': 2, 'updated': 0, 'duplicate': 0, 'errors': [{'secret': '/private/path'}], 'skipped': []}
    monkeypatch.setattr(Agent, 'discover', discover)
    result = dashboard.action('discover', {'confirm': 'discover', 'sources': '/untrusted/path'})
    assert calls[0][0] == str(dashboard.sources)
    assert calls[0][1] == {'max_pages': 3, 'max_sources': 20}
    assert result['error_count'] == 1
    assert 'secret' not in json.dumps(result)
    assert dashboard.action('recover', {'confirm': 'recover'})['operations'] == []


def test_config_symlinks_are_refused_before_read_or_write(dashboard, tmp_path):
    target = tmp_path / 'other-profile.json'
    dashboard.profile.rename(target)
    dashboard.profile.symlink_to(target)
    with pytest.raises(ValueError):
        dashboard.get('jobs')
    with pytest.raises(ValueError):
        dashboard.action('recover', {'confirm': 'recover'})


def test_read_only_browsing_does_not_create_or_migrate_database(tmp_path):
    data = DashboardData(tmp_path)
    assert data.get('overview')['total_jobs'] == 0
    assert data.get('jobs')['jobs'] == []
    assert data.get('operations')['preparations'] == []
    assert not (tmp_path / 'data').exists()
    agent = Agent(str(tmp_path / 'data'))
    before = agent.store.path.read_bytes()
    data = DashboardData(tmp_path)
    data.get('overview')
    data.get('jobs')
    data.get('operations')
    assert agent.store.path.read_bytes() == before


def test_overview_eligibility_aggregates_and_safe_reasoning(dashboard):
    add_job(dashboard, 'requirements', description='Requirements: Must be enrolled in a degree program. Python')
    result = dashboard.get('overview')
    assert sum(result['eligibility_counts'].values()) == 2
    assert result['eligibility_counts']['uncertain'] == 2
    detail = dashboard.get('job', {'id': 'requirements'})
    assert detail['eligibility']['rules']
    assert detail['eligibility']['rules'][0]['reason']
    assert detail['eligibility']['rules'][0]['evidence']
    assert 'candidate_facts' not in json.dumps(detail)
    assert detail['ranking']['ranking_explanation']['weights']
    dashboard.profile.unlink()
    assert dashboard.get('overview')['eligibility_counts']['unknown'] == 2


def test_review_surfaces_unresolved_gaps_safe_checks_and_revision(dashboard):
    review = prepare(dashboard)
    assert review['qa']['unresolved']
    assert review['qa']['unresolved'][0]['reason']
    assert review['qa']['files'][0]['checks']['selectable_text'] is True
    assert review['revision'] == 'revision-000001'
    assert review['variant'] == 'job'
    assert len(review['packet_sha256']) == 64
    assert 'claims' not in review


def test_scheduler_and_integrations_are_explicit_without_credentials(dashboard):
    operations = dashboard.get('operations')
    assert operations['scheduler']['status'] == 'not_configured'
    assert operations['integrations']['google']['status'] == 'unconnected'
    assert operations['integrations']['mcp']['status'] == 'unqualified'


@pytest.mark.parametrize('options', [{'variant': 'track'}, {'variant': 'master', 'track': 'cloud'}])
def test_invalid_preparation_options_preserve_approved_revision(dashboard, options):
    review = prepare(dashboard)
    approve(dashboard, review)
    with dashboard.store.connection() as c:
        before = [tuple(r) for r in c.execute('SELECT * FROM events ORDER BY id')]
        binding = tuple(c.execute('SELECT * FROM application_bindings').fetchone())
    with pytest.raises(ValueError):
        dashboard.action('prepare', {'id': 'fictional-job', 'confirm': 'prepare', **options})
    assert dashboard.store.get_job('fictional-job')['status'] == 'approved'
    with dashboard.store.connection() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM events ORDER BY id')] == before
        assert tuple(c.execute('SELECT * FROM application_bindings').fetchone()) == binding


def test_availability_aggregates_every_source_and_shows_provenance(dashboard):
    with Agent(str(dashboard.data)).store.connection() as c:
        for i in range(21):
            source = f'source-{i:02d}'
            c.execute('INSERT INTO discovery_sources(source_id,provider) VALUES(?,?)', (source, 'synthetic'))
            c.execute('INSERT INTO discovery_job_sources VALUES(?,?,?,?,?,?,?,?,?)',
                      ('fictional-job', source, 'https://example.test/jobs/fictional-job',
                       '2026-11-06', '2026-11-06', 'fictional-run',
                       'available' if i == 20 else 'closed', 'observed', '2026-11-06'))
    detail = dashboard.get('job', {'id': 'fictional-job'})
    assert detail['availability']['status'] == 'available'
    assert detail['availability']['total_sources'] == 21
    assert len(detail['availability']['sources']) == 20
    assert detail['availability']['sources'][0]['source_id'] == 'source-00'
    assert detail['job']['source_id'] == 'fictional-job'


def test_document_text_marks_truncated_previews():
    from io import BytesIO
    from docx import Document
    document = Document()
    document.add_paragraph('a' * 4500)
    stream = BytesIO()
    document.save(stream)
    preview = DashboardData._document_text(stream.getvalue())
    assert len(preview['text']) == 4000
    assert preview['text_truncated'] is True
    assert 'Download' in preview['warning']
