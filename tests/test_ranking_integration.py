"""Ranking integrates clocks, private reports and unchanged public tool projections."""
from datetime import datetime,timezone
import json
import sys

import pytest
from internship_agent.models import Job
from internship_agent.service import Agent

NOW=datetime(2030,1,15,tzinfo=timezone.utc)


@pytest.fixture
def ledger(tmp_path):
    agent=Agent(str(tmp_path/'db'),clock=lambda:NOW)
    for sid in ('b'*24,'a'*24):
        agent.store.upsert_job(Job(id=sid,source_id=sid,provider='synthetic',company='Example',
            title='Cloud Intern',description='Candidates must be currently enrolled. Python AWS Terraform.',
            location='Example City',job_url='https://example.com/'+sid,apply_url='https://example.com/'+sid,
            published_at='2030-01-10T00:00:00Z'))
    profile=tmp_path/'profile.json'
    profile.write_text(json.dumps(dict(name='Fictional',target_roles=['cloud engineer'],
        skills=['Python','AWS','Terraform'],preferred_locations=['Example City'],
        profile_version=2,candidate_facts=[dict(id='enrollment',field='enrolled',value=False,status='known',
            qualifiers={},provenance=dict(kind='user_declared',reference='PRIVATE_FACT',verified=True))],
        ranking={'preferences':{'use_experience':True}},experience=[{'title':'PRIVATE_ROLE','bullets':['Python AWS Terraform PRIVATE_BULLET']}])))
    return agent,profile


def test_clock_and_id_tiebreak_are_independent_of_ingestion_order(ledger):
    agent,path=ledger
    before=(agent.store.path.read_bytes(),path.read_bytes())
    values=agent.ranked(str(path))
    assert [v['job_id'] for v in values]==['a'*24,'b'*24]
    assert {v['ranking_explanation']['as_of'] for v in values}=={'2030-01-15T00:00:00+00:00'}
    assert agent.ranked(str(path))==values
    assert before==(agent.store.path.read_bytes(),path.read_bytes())


def test_high_fit_never_erases_structured_ineligibility(ledger):
    agent,path=ledger
    rows=agent.ranked(str(path),include_eligibility=True,min_score=70)
    assert len(rows)==2
    assert rows[0]['score']>=70
    assert rows[0]['eligibility']=='review'  # compatibility warning, not a decision
    assert rows[0]['eligibility_assessment']['outcome']=='ineligible'
    assert rows[0]['eligibility_assessment']['action']=='do_not_apply'
    assert 'PRIVATE_FACT' not in json.dumps(rows)


def test_uncertain_eligibility_retains_manual_review(ledger):
    agent,path=ledger
    raw=json.loads(path.read_text());raw.pop('candidate_facts');raw.pop('profile_version')
    path.write_text(json.dumps(raw))
    row=agent.ranked(str(path),include_eligibility=True)[0]
    assert row['eligibility_assessment']['outcome']=='uncertain'
    assert row['eligibility_assessment']['action']=='manual_review'


def test_cli_invalid_config_is_sanitized_and_explanation_is_local(ledger,monkeypatch,capsys):
    from internship_agent.cli import main
    agent,path=ledger
    monkeypatch.setattr(sys,'argv',['internship-agent','--data',str(agent.root),'rank','--profile',str(path)])
    main()
    assert 'ranking_explanation' in json.loads(capsys.readouterr().out)[0]
    raw=json.loads(path.read_text());raw['ranking']['weights']={'PRIVATE_WEIGHT':5}
    path.write_text(json.dumps(raw))
    with pytest.raises(SystemExit) as failed:main()
    assert failed.value.code==2
    error=capsys.readouterr().err
    assert 'PRIVATE' not in error and str(path) not in error


def test_mcp_rank_and_preview_keep_legacy_shapes_and_hide_explanations(ledger):
    pytest.importorskip('mcp')
    from mcp import Client
    import anyio
    from internship_agent.mcp_server import create_server
    agent,path=ledger
    before=(agent.store.path.read_bytes(),path.read_bytes())
    server=create_server(agent.root,path)
    async def check():
        async with Client(server) as client:
            assert {t.name for t in (await client.list_tools()).tools}=={'application_summary','rank_jobs','preview_application'}
            result=(await client.call_tool('rank_jobs',{'min_score':0})).structured_content
            row=result['jobs'][0]
            assert set(row)=={'job_id','company','title','location','job_url','apply_url','status','score','components','matched_skills','matched_roles','eligibility','flags','reason'}
            preview=(await client.call_tool('preview_application',{'job_id':row['job_id']})).structured_content
            assert set(preview['ranking'])=={'job_id','score','components','matched_skills','matched_roles','eligibility','flags','reason'}
            for forbidden in ('PRIVATE_FACT','PRIVATE_ROLE','PRIVATE_BULLET','ranking_explanation','experience_index','candidate_facts','eligibility_assessment'):
                assert forbidden not in json.dumps((result,preview))
    anyio.run(check)
    assert before==(agent.store.path.read_bytes(),path.read_bytes())


def test_cli_ranking_reads_existing_ledger_without_initializing_missing_one(tmp_path,monkeypatch,capsys):
    from internship_agent.cli import main
    root=tmp_path/'missing-db'
    path=tmp_path/'profile.json';path.write_text('{}')
    monkeypatch.setattr(sys,'argv',['internship-agent','--data',str(root),'rank','--profile',str(path)])
    with pytest.raises(SystemExit) as failed:main()
    assert failed.value.code==2
    assert not root.exists()


def test_empty_ledger_still_rejects_invalid_preferences(tmp_path):
    agent=Agent(str(tmp_path/'empty'))
    path=tmp_path/'profile.json';path.write_text('{"ranking":{"weights":{"role":1}}}')
    with pytest.raises(ValueError,match='Invalid ranking configuration'):
        agent.ranked(str(path))


def test_rank_profile_duplicate_keys_and_size_fail_safely(ledger):
    agent,path=ledger
    for raw in ('{"ranking":{},"ranking":{"weights":{"role":0}}}', '{"private":"'+'x'*1_048_577+'"}'):
        path.write_text(raw)
        with pytest.raises(ValueError,match='Invalid ranking configuration'):
            agent.ranked(str(path))
