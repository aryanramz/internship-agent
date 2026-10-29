"""Real local MCP clients; fictional DB/profile; no HTTP listener or cloud calls."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

pytest.importorskip("mcp",reason="Install the mcp extra for protocol regression coverage")
import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from internship_agent.models import Job, stable_id
from internship_agent.service import Agent

# Cold Windows SDK imports were measured at 22s before a valid legacy reply.
# These are interoperability checks, not startup-performance assertions.
STARTUP_TIMEOUT = 60 if os.name == "nt" else 15

@pytest.fixture
def fictional_agent(tmp_path):
    root=tmp_path/"isolated database #1"
    agent=Agent(str(root))
    jid=stable_id("synthetic","mcp-test","one")
    url="https://example.com/fictional-jobs/one"
    agent.store.upsert_job(Job(id=jid,provider="synthetic",company="Example Employer (fictional)",
        source_id="one",title="Cloud Infrastructure Intern - TEST ONLY",location="Example City",
        description="Python AWS infrastructure tools",job_url=url,apply_url=url))
    agent.store.set_prepared(jid,"PRIVATE-DOCUMENT/resume.docx","PRIVATE-DOCUMENT/letter.docx")
    profile=tmp_path/"PRIVATE-PROFILE.json"
    profile.write_text(json.dumps({"name":"Synthetic Candidate","email":"private@example.com",
        "target_roles":["cloud infrastructure"],"skills":["Python","AWS","UnrelatedPrivateSkill"],
        "preferred_locations":["Example City"],"private_marker":"NEVER_RETURN_FULL_PROFILE"}),encoding="utf-8")
    return agent,profile,jid


def factory(root,profile):
    from internship_agent import mcp_server
    assert hasattr(mcp_server,"create_server"), "An explicit import-safe server factory is required"
    return mcp_server.create_server(root,profile)


def test_importing_adapter_does_not_create_or_open_a_database(tmp_path):
    env=dict(os.environ)
    env["INTERNSHIP_AGENT_DATA"]=str(tmp_path/"must-not-exist")
    proc=subprocess.run([sys.executable,"-c","import internship_agent.mcp_server"],cwd=tmp_path,
        env=env,capture_output=True,text=True,timeout=STARTUP_TIMEOUT)
    assert proc.returncode==0,proc.stderr
    assert not (tmp_path/"must-not-exist").exists()


def test_readonly_agent_refuses_sql_writes_and_missing_database(fictional_agent,tmp_path):
    agent,_,_=fictional_agent
    reader=Agent(str(agent.root),read_only=True)
    with reader.store.connection() as connection,pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM jobs")
    missing=tmp_path/"nonexistent"
    with pytest.raises(FileNotFoundError):
        Agent(str(missing),read_only=True)
    assert not missing.exists()


@pytest.mark.parametrize("mode",["auto","legacy"])
def test_real_stdio_initialization_discovery_and_readonly_calls(fictional_agent,mode):
    agent,profile,jid=fictional_agent
    # Fail before spawning the old module, whose original entry point was HTTP.
    factory(agent.root,profile)
    before=(agent.store.path.read_bytes(),profile.read_bytes())
    async def exercise():
        params=StdioServerParameters(command=sys.executable,args=["-m","internship_agent.mcp_server",
            "--data",str(agent.root),"--profile",str(profile)])
        async with Client(params,mode=mode,read_timeout_seconds=STARTUP_TIMEOUT) as client:
            assert client.server_info.name == "Internship Agent"
            assert client.server_capabilities.tools is not None
            assert "read-only" in client.instructions
            if mode=="auto":
                assert client.protocol_version=="2026-07-28"
            else:
                assert client.protocol_version.startswith("2025-")
            definitions=(await client.list_tools()).tools
            print(f"Local MCP: mode={mode}, protocol={client.protocol_version}, tools={len(definitions)}")
            assert {tool.name for tool in definitions} == {"application_summary","rank_jobs","preview_application"}
            for tool in definitions:
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.open_world_hint is False
                assert "profile" not in tool.input_schema.get("properties",{})
                assert "data" not in tool.input_schema.get("properties",{})
            summary=await client.call_tool("application_summary",{})
            assert not summary.is_error
            assert summary.structured_content == {"prepared":1}
            ranked=await client.call_tool("rank_jobs",{"limit":5,"min_score":0})
            assert not ranked.is_error
            assert ranked.structured_content["jobs"][0]["job_id"] == jid
            preview=await client.call_tool("preview_application",{"job_id":jid})
            assert not preview.is_error
            assert preview.structured_content["matching_verified_skills"] == ["Python","AWS"]
            output=json.dumps(preview.structured_content)+json.dumps(ranked.structured_content)
            for private in ("PRIVATE-DOCUMENT","PRIVATE-PROFILE","private@example.com",
                            "NEVER_RETURN_FULL_PROFILE","UnrelatedPrivateSkill"):
                assert private not in output
            for name in ("approve_application","record_confirmed_submission","prepare_application",
                         "apply_google_sheet_sync","import_external_jobs","discover_jobs","ingest_google_job_alerts"):
                rejected=await client.call_tool(name,{})
                assert rejected.is_error
            assert not (await client.list_resources()).resources
            assert not (await client.list_resource_templates()).resource_templates
            assert not (await client.list_prompts()).prompts
    anyio.run(exercise)
    assert (agent.store.path.read_bytes(),profile.read_bytes())==before
    assert agent.store.count()=={"prepared":1}
    assert not (agent.root/"generated").exists()


def test_schema_bounds_and_safe_tool_errors(fictional_agent):
    agent,profile,_=fictional_agent
    server=factory(agent.root,profile)
    async def exercise():
        async with Client(server) as client:
            for arguments in ({"limit":0},{"limit":101},{"min_score":-1},{"min_score":101}):
                assert (await client.call_tool("rank_jobs",arguments)).is_error
            bad_id=await client.call_tool("preview_application",{"job_id":"not-an-id"})
            assert bad_id.is_error
            unknown=await client.call_tool("preview_application",{"job_id":"f"*24})
            assert unknown.is_error
            assert "rank_jobs" in str(unknown.content)
            profile.write_text("PRIVATE INVALID PROFILE",encoding="utf-8")
            failed=await client.call_tool("rank_jobs",{})
            assert failed.is_error
            assert "PRIVATE" not in str(failed.content)
            assert str(profile.parent) not in str(failed.content)
    anyio.run(exercise)


def test_cli_rejects_http_transport_before_starting_a_server(fictional_agent):
    agent,profile,_=fictional_agent
    factory(agent.root,profile)
    proc=subprocess.run([sys.executable,"-m","internship_agent.mcp_server","--transport","streamable-http"],
        capture_output=True,text=True,timeout=STARTUP_TIMEOUT)
    assert proc.returncode==2
    assert "unrecognized arguments" in proc.stderr
