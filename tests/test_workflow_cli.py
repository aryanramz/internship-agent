"""Complete local CLI flow; optional SDK imports can be denied throughout."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('deny_optional', [False, True])
def test_local_discovery_to_review_and_operator_reported_tracking(tmp_path, deny_optional):
    data = tmp_path / 'data'
    profile = tmp_path / 'fictional-profile.json'
    source = tmp_path / 'sources.json'
    postings = tmp_path / 'postings.json'
    postings.write_text(json.dumps([{'id': 'fictional-1', 'platform': 'synthetic',
        'company': 'Fictional Employer', 'title': 'Software Intern — 学生', 'location': 'Example City',
        'job_url': 'https://example.test/jobs/one', 'description': 'Python software internship'}]), encoding='utf-8')
    source.write_text(json.dumps({'boards': [{'provider': 'json_import', 'token': 'fictional',
        'company': 'Fictional Employer', 'path': str(postings)}]}), encoding='utf-8')
    profile.write_text(json.dumps({'name': 'Fictional Zoë 学生', 'skills': ['Python'],
        'target_roles': ['software engineer'], 'documents': {'version': 1, 'facts': [
            {'id': 'name', 'path': '/name', 'value': 'Fictional Zoë 学生', 'verified': True,
             'source': 'Synthetic local review', 'reviewed_on': '2026-11-01'},
            {'id': 'python', 'path': '/skills/0', 'value': 'Python', 'verified': True,
             'source': 'Synthetic local review', 'reviewed_on': '2026-11-01'}]}}), encoding='utf-8')
    # Execute the real CLI while making optional packages genuinely unimportable.
    runner = '''import runpy,sys
class DenyOptional:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'mcp','google','google_auth_oauthlib','googleapiclient'}:
            raise ImportError('Optional SDK unavailable in synthetic core-only check')
if sys.argv.pop(1) == 'True':
    sys.meta_path.insert(0,DenyOptional())
runpy.run_module('internship_agent.cli',run_name='__main__')
'''
    env = {**os.environ, 'PYTHONUTF8': '0', 'RUN_LIVE_ATS': '0', 'RUN_LIVE_SHEETS': '0'}
    def cli(*arguments):
        result = subprocess.run([sys.executable, '-c', runner, str(deny_optional), '--data',
                                 str(data), *arguments], env=env, text=True, encoding='utf-8',
                                capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    discovered = cli('discover', '--sources', str(source))
    assert discovered['added'] == 1 and discovered['errors'] == []
    ranked = cli('rank', '--profile', str(profile), '--with-eligibility')
    jid = ranked[0]['job_id']
    assert cli('eligibility', jid, '--profile', str(profile))['outcome'] in {'eligible', 'uncertain'}
    assert cli('preview', jid, '--profile', str(profile))['ranking']['job_id'] == jid
    prepared = cli('prepare', jid, '--profile', str(profile), '--request-id', 'fictional-first')
    assert cli('prepare', jid, '--profile', str(profile), '--request-id', 'fictional-first')['resume_path'] == prepared['resume_path']
    before = (data / 'agent.db').read_bytes()
    review = cli('review', jid)
    assert (data / 'agent.db').read_bytes() == before
    assert review['qa']['structural_pass']
    token = review['review_token']
    assert cli('approve', jid, 'APPROVE ' + jid, '--review-token', token)['status'] == 'approved'
    recorded = cli('mark-submitted', jid, 'Synthetic operator report only', '--approval-token', token)
    assert recorded['submission_evidence_kind'] == 'user_supplied'
    assert recorded['employer_receipt_verified'] is False
    cli('mark-submitted', jid, 'Synthetic operator report only', '--approval-token', token)
    assert cli('status', jid, 'interview', '--evidence', 'Synthetic invitation')['status'] == 'interview'
    report = cli('application', jid)
    assert len([e for e in report['events'] if e['event_type'] == 'submitted']) == 1
    exported = cli('export-tracker', '--output', str(tmp_path / 'tracker.csv'))
    assert exported['rows'] == 1
    assert cli('recover')['operations'] == []
    assert Path(prepared['resume_path']).is_file()
