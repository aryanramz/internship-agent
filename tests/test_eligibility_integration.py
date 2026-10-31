"""Local eligibility, legacy ranking and private-history compatibility."""
from datetime import datetime, timezone
import json

import pytest

from internship_agent.models import Job, stable_id
from internship_agent.service import Agent


@pytest.fixture
def workflow(tmp_path):
    agent = Agent(str(tmp_path / "db"), clock=lambda:datetime(2030,1,15,tzinfo=timezone.utc))
    jid = stable_id("greenhouse","example","eligible-fixture")
    job = Job(id=jid,provider="greenhouse",company="Example",source_id="eligible-fixture",title="Cloud Infrastructure Intern",
        location="Example City",description="Build AWS Python Terraform Linux SQL. Candidates must be currently enrolled in a bachelor's or master's program.",
        job_url="https://example.com/jobs/fixture",apply_url="https://example.com/jobs/fixture")
    agent.store.upsert_job(job)
    agent.store.set_prepared(jid,"fictional-resume.docx","fictional-letter.docx")
    agent.store.approve(jid,f"APPROVE {jid}")
    agent.store.mark_submitted(jid,"FICTIONAL-CONFIRMATION")
    raw = {"name":"Fictional Student","target_roles":["cloud infrastructure"],"skills":["AWS","Python","Terraform","Linux","SQL"],
        "preferred_locations":["Example City"],"profile_version":2,"candidate_facts":[
            {"id":"enrollment","field":"enrolled","value":False,"status":"known","qualifiers":{},
             "provenance":{"kind":"user_declared","reference":"PRIVATE ELIGIBILITY EVIDENCE","verified":True}},
            {"id":"degree","field":"degree_level","value":"bachelor","status":"known","qualifiers":{},
             "provenance":{"kind":"user_declared","reference":"Fictional program","verified":True}}]}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(raw))
    return agent,path,jid,raw


def test_local_eligibility_does_not_mutate_profile_database_or_application_history(workflow):
    agent,path,jid,_ = workflow
    before = (agent.store.path.read_bytes(),path.read_bytes(),agent.store.get_job(jid))
    report = agent.eligibility(jid,str(path))
    assert report["outcome"] == "ineligible"
    assert report["fit_score"] > 60
    assert report == agent.eligibility(jid,str(path))
    assert (agent.store.path.read_bytes(),path.read_bytes(),agent.store.get_job(jid)) == before


def test_rank_default_is_compatible_and_optional_assessment_never_changes_score_or_order(workflow):
    agent,path,jid,_ = workflow
    legacy = agent.ranked(str(path),10,0)
    assert "eligibility_assessment" not in legacy[0]
    extra = agent.ranked(str(path),10,0,include_eligibility=True)
    assert extra[0]["eligibility_assessment"]["outcome"] == "ineligible"
    assert [{k:v for k,v in row.items() if k != "eligibility_assessment"} for row in extra] == legacy
    assert "PRIVATE ELIGIBILITY EVIDENCE" not in json.dumps(extra)


def test_cli_eligibility_is_read_only_and_private_errors_are_generic(workflow,monkeypatch,capsys):
    from internship_agent import cli
    agent,path,jid,_ = workflow
    before = (agent.store.path.read_bytes(),path.read_bytes())
    monkeypatch.setattr("sys.argv",["internship-agent","--data",str(agent.root),"eligibility",jid,"--profile",str(path)])
    cli.main()
    assert json.loads(capsys.readouterr().out)["outcome"] == "ineligible"
    assert (agent.store.path.read_bytes(),path.read_bytes()) == before
    path.write_text('{"private-secret": INVALID DATA}')
    with pytest.raises(SystemExit) as failed:
        cli.main()
    assert failed.value.code == 2
    error = capsys.readouterr().err
    assert "private-secret" not in error and str(path) not in error


def test_legacy_profile_keeps_ranking_but_eligibility_needs_verified_facts(workflow):
    agent,path,jid,raw = workflow
    raw.pop("profile_version"); raw.pop("candidate_facts")
    raw["eligibility"] = {"current_undergraduate":True}
    path.write_text(json.dumps(raw))
    assert agent.ranked(str(path),5,0)[0]["job_id"] == jid
    assert agent.eligibility(jid,str(path))["outcome"] == "uncertain"


def test_duplicate_profile_keys_and_oversized_profiles_fail_safely(workflow):
    agent,path,jid,_ = workflow
    for payload in ('{"profile_version":1,"profile_version":2}', '{"notes":"' + 'x'*1_048_577 + '"}'):
        path.write_text(payload)
        with pytest.raises(ValueError):
            agent.eligibility(jid,str(path))


@pytest.mark.parametrize("field,value",[("preferred_locations",[17]),("target_roles",None),
    ("skills",{}),("preferred_employers",[False])])
def test_invalid_legacy_fit_fields_have_safe_errors_on_new_paths(workflow,field,value):
    agent,path,jid,raw = workflow
    raw[field] = value
    path.write_text(json.dumps(raw))
    for action in (lambda:agent.eligibility(jid,str(path)),
                   lambda:agent.ranked(str(path),include_eligibility=True)):
        with pytest.raises(ValueError,match="Invalid eligibility profile"):
            action()
