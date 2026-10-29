"""Synthetic JWTs and in-process HTTP only; no credentials or public listener."""
import json
import time

import anyio
import pytest

pytest.importorskip("mcp")
jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from internship_agent.models import Job, stable_id
from internship_agent.service import Agent

ISSUER = "http://127.0.0.1:8180/realms/synthetic"
RESOURCE = "http://127.0.0.1:8765/mcp"
OWNER = "synthetic-owner-subject"
CLIENT = "synthetic-chatgpt-client"
READ_SCOPE = "internship:read"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings(tmp_path, signing_key):
    from internship_agent.mcp_http import AuthConfig
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public.update(kid="synthetic-key", use="sig", alg="RS256")
    jwks = tmp_path / "public-jwks.json"
    jwks.write_text(json.dumps({"keys": [public]}), encoding="utf-8")
    return AuthConfig(issuer=ISSUER, resource=RESOURCE, owner_subject=OWNER,
                      client_id=CLIENT, jwks_path=jwks)


def token(key, **changes):
    now = int(time.time())
    claims = dict(iss=ISSUER, aud=RESOURCE, sub=OWNER, client_id=CLIENT,
                  iat=now, exp=now + 300, scope=READ_SCOPE)
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "synthetic-key", "typ": "at+jwt"})


def verified(settings, raw):
    from internship_agent.mcp_http import JWTVerifier
    return anyio.run(JWTVerifier(settings).verify_token, raw)


def test_signed_owner_access_token_is_accepted(settings, signing_key):
    result = verified(settings, token(signing_key))
    assert result.subject == OWNER
    assert result.resource == RESOURCE
    assert result.scopes == [READ_SCOPE]
    assert result.claims == {"iss": ISSUER}


@pytest.mark.parametrize("changes", [
    {"iss": "https://attacker.invalid"}, {"aud": "another-resource"},
    {"aud": [RESOURCE, "another-resource"]}, {"sub": "another-owner"},
    {"client_id": "another-client"}, {"azp": "another-client"},
    {"exp": 1}, {"exp": None}, {"exp": "9999999999"},
    {"iat": 9999999999}, {"nbf": 9999999999}, {"scope": "internship:write"},
    {"scope": [READ_SCOPE]}, {"sub": None}, {"iat": None},
])
def test_invalid_claims_are_rejected(settings, signing_key, changes):
    assert verified(settings, token(signing_key, **changes)) is None


def test_forged_malformed_unsigned_and_id_tokens_are_rejected(settings, signing_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    good = jwt.decode(token(signing_key), options={"verify_signature": False})
    invalid = ["", "bad-token", "a" * 17000, token(other),
               jwt.encode(good, "", algorithm="none", headers={"kid": "synthetic-key"}),
               jwt.encode(good, "synthetic-secret-for-rejection-only-32", algorithm="HS256", headers={"kid": "synthetic-key"}),
               jwt.encode(good, signing_key, algorithm="RS256", headers={"kid": "unknown", "typ": "at+jwt"}),
               jwt.encode(good, signing_key, algorithm="RS256", headers={"kid": "synthetic-key", "typ": "JWT"})]
    for raw in invalid:
        assert verified(settings, raw) is None
    # Keycloak access tokens use JWT + payload typ=Bearer; ID tokens do not.
    good["typ"] = "Bearer"
    assert verified(settings, jwt.encode(good, signing_key, algorithm="RS256",
                    headers={"kid": "synthetic-key", "typ": "JWT"})) is not None


def test_missing_claims_and_token_controlled_keys_are_rejected(settings, signing_key):
    claims = jwt.decode(token(signing_key), options={"verify_signature": False})
    for required in ("iss", "aud", "sub", "iat", "exp", "scope", "client_id"):
        reduced = {key: value for key, value in claims.items() if key != required}
        assert verified(settings, jwt.encode(reduced, signing_key, algorithm="RS256",
                        headers={"kid": "synthetic-key", "typ": "at+jwt"})) is None
    for extra in ({"jku": "https://attacker.invalid/jwks"}, {"x5u": "https://attacker.invalid/cert"},
                  {"jwk": {}}, {"crit": ["arbitrary"]}):
        assert verified(settings, jwt.encode(claims, signing_key, algorithm="RS256",
                        headers={"kid": "synthetic-key", "typ": "at+jwt", **extra})) is None


@pytest.mark.parametrize("field,value", [
    ("resource", "http://0.0.0.0:8765/mcp"), ("resource", "https://public.example/mcp"),
    ("resource", "http://localhost:8765/mcp"), ("resource", "http://127.0.0.1:8765/admin"),
    ("issuer", "http://public.example"), ("owner_subject", ""), ("client_id", ""),
])
def test_configuration_fails_closed(settings, field, value):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(settings, **{field: value})


def test_public_jwks_rejects_private_keys_and_duplicate_ids(settings, signing_key):
    from internship_agent.mcp_http import JWTVerifier
    original = json.loads(settings.jwks_path.read_text())
    for keys in ([*original["keys"], *original["keys"]],
                 [{**original["keys"][0], "d": "must-not-load-private-key"}], []):
        settings.jwks_path.write_text(json.dumps({"keys": keys}))
        with pytest.raises(ValueError):
            JWTVerifier(settings)


def test_provider_encryption_keys_are_never_used_for_signature_verification(settings, signing_key):
    from internship_agent.mcp_http import JWTVerifier
    public = json.loads(settings.jwks_path.read_text())
    public["keys"].append({**public["keys"][0], "kid": "encryption-key", "use": "enc", "alg": "RSA-OAEP"})
    settings.jwks_path.write_text(json.dumps(public))
    verifier = JWTVerifier(settings)
    assert set(verifier.keys) == {"synthetic-key"}
    assert anyio.run(verifier.verify_token, token(signing_key)) is not None
    claims = jwt.decode(token(signing_key), options={"verify_signature": False})
    enc_signed = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "encryption-key", "typ": "at+jwt"})
    assert anyio.run(verifier.verify_token, enc_signed) is None


@pytest.fixture
def http_app(tmp_path, settings):
    from internship_agent.mcp_http import create_http_app
    root = tmp_path / "synthetic-data"
    agent = Agent(str(root))
    jid = stable_id("synthetic", "http-test", "one")
    agent.store.upsert_job(Job(id=jid, provider="synthetic", source_id="one",
        company="Fictional HTTP Employer", title="Cloud Intern TEST ONLY", location="Example City",
        description="Python AWS", job_url="https://example.com/jobs/1", apply_url="https://example.com/jobs/1"))
    agent.store.set_prepared(jid, "PRIVATE-DOCUMENT/resume.docx", "PRIVATE-DOCUMENT/letter.docx")
    profile = tmp_path / "private-profile.json"
    profile.write_text(json.dumps({"name": "Synthetic Candidate", "email": "private@example.com",
        "skills": ["Python", "AWS", "UnrelatedPrivateSkill"], "private_marker": "PRIVATE-PROFILE"}))
    return create_http_app(root, profile, settings), agent, profile, jid


def rpc(client, raw, method="tools/list", params=None, **kwargs):
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28"}
    if raw is not None:
        headers["Authorization"] = "Bearer " + raw
    headers.update(kwargs.pop("headers", {}))
    params = dict(params or {})
    if headers["MCP-Protocol-Version"] == "2026-07-28":
        headers["MCP-Method"] = method
        if "name" in params:
            headers["MCP-Name"] = params["name"]
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                           "io.modelcontextprotocol/clientCapabilities": {}}
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method,
                                   "params": params}, headers=headers, **kwargs)


def test_http_metadata_discovery_and_all_three_readonly_tools(http_app, signing_key):
    app, agent, profile, jid = http_app
    before = (agent.store.path.read_bytes(), profile.read_bytes())
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == RESOURCE
        assert metadata.json()["authorization_servers"] == [ISSUER]
        assert metadata.json()["scopes_supported"] == [READ_SCOPE]
        raw = token(signing_key)
        init = rpc(client, raw, "initialize", {"protocolVersion": "2025-11-25",
            "capabilities": {}, "clientInfo": {"name": "synthetic-test", "version": "1"}},
            headers={"MCP-Protocol-Version": "2025-11-25"})
        assert init.status_code == 200, init.text
        listed = rpc(client, raw).json()["result"]["tools"]
        assert {t["name"] for t in listed} == {"application_summary", "rank_jobs", "preview_application"}
        assert all(t["annotations"]["readOnlyHint"] for t in listed)
        for name, args in (("application_summary", {}), ("rank_jobs", {"min_score": 0}),
                           ("preview_application", {"job_id": jid})):
            response = rpc(client, raw, "tools/call", {"name": name, "arguments": args})
            assert response.status_code == 200, response.text
            result = response.json()["result"]
            assert not result.get("isError")
            assert result["structuredContent"]
            for marker in ("PRIVATE-DOCUMENT", "PRIVATE-PROFILE", "private@example.com", "UnrelatedPrivateSkill"):
                assert marker not in response.text
        for name in ("approve_application", "record_confirmed_submission", "apply_google_sheet_sync",
                     "discover_jobs", "prepare_application", "read_file"):
            rejected = rpc(client, raw, "tools/call", {"name": name, "arguments": {}})
            assert rejected.json()["result"]["isError"]
        for method, field in (("resources/list", "resources"), ("prompts/list", "prompts")):
            assert not rpc(client, raw, method).json()["result"][field]
    assert (agent.store.path.read_bytes(), profile.read_bytes()) == before
    assert not (agent.root / "generated").exists()


def test_every_http_call_rejects_invalid_auth_without_dispatch(http_app, signing_key, monkeypatch, caplog):
    app, _, _, _ = http_app
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthenticated request reached a tool")
    monkeypatch.setattr("internship_agent.store.Store.count", forbidden)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        invalid = [None, "forged-private-marker", token(other), token(signing_key, exp=1),
                   token(signing_key, aud="wrong"), token(signing_key, sub="wrong"),
                   token(signing_key, iss="https://wrong.invalid"), token(signing_key, client_id="wrong"),
                   token(signing_key, scope="wrong")]
        for raw in invalid:
            response = rpc(client, raw, "tools/call", {"name": "application_summary", "arguments": {}})
            assert response.status_code in (401, 403)
            assert "resource_metadata" in response.headers["www-authenticate"]
            assert "forged-private-marker" not in response.text
        assert rpc(client, None, params={"access_token": token(signing_key)}).status_code == 401
    assert "forged-private-marker" not in caplog.text


def test_route_host_origin_and_query_boundaries(http_app, signing_key):
    app, _, _, _ = http_app
    raw = token(signing_key)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        for path in ("/", "/admin", "/realms/master", "/api", "/data/agent.db", "/config/profile.json",
                     "/credentials", "/mcp/../admin", "/mcp/", "/.well-known/openid-configuration"):
            response = client.get(path, headers={"Authorization": "Bearer " + raw})
            assert response.status_code == 404
        assert client.post("/mcp?access_token=" + raw, json={}).status_code == 400
        for headers in ({"Host": "attacker.invalid"}, {"Origin": "https://attacker.invalid"},
                        {"X-Forwarded-Host": "attacker.invalid", "Host": "attacker.invalid"}):
            assert rpc(client, raw, headers=headers).status_code == 400
        allowed = rpc(client, raw, headers={"X-Forwarded-Host": "attacker.invalid"})
        assert allowed.status_code == 200, allowed.text


def test_invocation_guard_rechecks_current_token_after_http_admission(settings, signing_key, monkeypatch):
    from internship_agent.mcp_http import InvocationGuard, JWTVerifier
    from mcp.shared.exceptions import MCPError
    from starlette.requests import Request
    from types import SimpleNamespace
    verifier = JWTVerifier(settings)
    raw = token(signing_key)
    assert anyio.run(verifier.verify_token, raw)
    async def expired(_):
        return None
    monkeypatch.setattr(verifier, "verify_token", expired)
    request = Request({"type": "http", "headers": [(b"authorization", ("Bearer " + raw).encode())]})
    context = SimpleNamespace(method="tools/call", request=request)
    async def forbidden(_):
        pytest.fail("Expired request reached the tool")
    with pytest.raises(MCPError, match="Authorization required"):
        anyio.run(InvocationGuard(verifier), context, forbidden)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_real_sdk_http_client_uses_authenticated_transport(http_app, signing_key, mode):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    app, _, _, jid = http_app
    async def exercise():
        async with app.app.router.lifespan_context(app.app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                    headers={"Authorization": "Bearer " + token(signing_key)}, trust_env=False) as http:
                async with Client(streamable_http_client(RESOURCE, http_client=http), mode=mode,
                                  read_timeout_seconds=5, cache=None) as client:
                    assert client.server_info.name == "Internship Agent"
                    assert len((await client.list_tools()).tools) == 3
                    for name, arguments in (("application_summary", {}), ("rank_jobs", {"min_score": 0}),
                                            ("preview_application", {"job_id": jid})):
                        result = await client.call_tool(name, arguments)
                        assert not result.is_error
                        assert result.structured_content
    anyio.run(exercise)


def test_cli_binds_loopback_and_disables_proxy_and_access_logs(http_app, settings, tmp_path, monkeypatch):
    from internship_agent import mcp_http
    path = tmp_path / "local-auth.json"
    path.write_text(json.dumps(dict(issuer=ISSUER, resource=RESOURCE, owner_subject=OWNER,
        client_id=CLIENT, jwks_path=str(settings.jwks_path))))
    app, agent, profile, _ = http_app
    called = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: called.append(kwargs))
    mcp_http.main(["--auth-config", str(path), "--data", str(agent.root), "--profile", str(profile)])
    assert called[0]["host"] == "127.0.0.1"
    assert called[0]["port"] == 8765
    assert called[0]["proxy_headers"] is False
    assert called[0]["access_log"] is False
    with pytest.raises(SystemExit) as refused:
        mcp_http.main(["--auth-config", str(path), "--data", str(agent.root),
                       "--profile", str(profile), "--host", "0.0.0.0"])
    assert refused.value.code == 2


def test_http_body_limit_and_duplicate_auth_headers(http_app, signing_key):
    app, _, _, _ = http_app
    raw = token(signing_key)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post("/mcp", content=b"x" * 65537, headers={"Authorization": "Bearer " + raw,
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        assert response.status_code == 413
        response = client.post("/mcp", json={}, headers=[("Authorization", "Bearer " + raw),
                                                                       ("Authorization", "Bearer forged")])
        assert response.status_code == 400
        for repeated in ([("Host", "127.0.0.1:8765"), ("Host", "attacker.invalid")],
                         [("Origin", "http://127.0.0.1:8765"), ("Origin", "https://attacker.invalid")],
                         [("Origin", "null")]):
            assert client.get("/.well-known/oauth-protected-resource/mcp", headers=repeated).status_code == 400


def test_http_token_expiring_after_admission_never_reaches_tool(http_app, signing_key, monkeypatch):
    from datetime import datetime, timedelta
    from internship_agent.mcp_http import JWTVerifier
    app, _, _, _ = http_app
    original = JWTVerifier.verify_token
    checks = []
    class AdvancingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=600 if len(checks) >= 2 else 0)
    async def observe(self, raw):
        checks.append(1)
        return await original(self, raw)
    monkeypatch.setattr("jwt.api_jwt.datetime", AdvancingClock)
    monkeypatch.setattr(JWTVerifier, "verify_token", observe)
    def forbidden(*args, **kwargs):
        pytest.fail("Expired token reached a tool after HTTP admission")
    monkeypatch.setattr("internship_agent.store.Store.count", forbidden)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = rpc(client, token(signing_key), "tools/call", {"name": "application_summary", "arguments": {}})
        assert response.status_code == 200
        assert response.json()["error"]["message"] == "Authorization required"
        assert len(checks) == 2
