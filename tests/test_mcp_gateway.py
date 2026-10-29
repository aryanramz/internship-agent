"""Gateway boundaries with fictional identities, ephemeral keys and mocked Keycloak."""
import base64
import json
import time
import uuid
from urllib.parse import urlencode

import pytest

pytest.importorskip("mcp")
import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from internship_agent.models import Job, stable_id
from internship_agent.service import Agent

ORIGIN = "https://internship-test.tail-test.ts.net"
REALM = "internship-agent-test"
ISSUER = ORIGIN + "/realms/" + REALM
RESOURCE = ORIGIN + "/mcp"
OIDC = "/realms/" + REALM + "/protocol/openid-connect"
CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
CLIENT = "internship-agent-chatgpt"
OWNER = "synthetic-owner"


@pytest.fixture
def gateway(tmp_path):
    from internship_agent.mcp_gateway_config import GatewayConfig
    from internship_agent.mcp_gateway import create_gateway_app
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="synthetic-key", use="sig", alg="RS256")
    jwks = tmp_path / "public-jwks.json"
    jwks.write_text(json.dumps({"keys": [jwk]}))
    agent = Agent(str(tmp_path / "fictional"))
    jid = stable_id("synthetic", "gateway", "one")
    agent.store.upsert_job(Job(id=jid, provider="synthetic", source_id="one", company="Example TEST",
        title="Cloud Intern TEST ONLY", location="Example", description="Python AWS",
        job_url="https://example.com/job/one", apply_url="https://example.com/job/one"))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"name": "Synthetic Candidate", "skills": ["Python", "AWS"]}))
    config = GatewayConfig(public_origin=ORIGIN, realm=REALM, client_id=CLIENT, owner_subject=OWNER,
        jwks_path=jwks, data_root=agent.root, profile_path=profile, keycloak_port=14129,
        listen_port=8765, redirect_uris=[CALLBACK])
    calls, behavior = [], {}
    def signed(**changes):
        claims = dict(iss=ISSUER, aud=RESOURCE, sub=OWNER, azp=CLIENT,
                      iat=int(time.time()), exp=int(time.time()) + 300, scope="openid internship:read")
        claims.update(changes)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "synthetic-key", "typ": "at+jwt"})
    def provider(request):
        calls.append(request)
        if "response" in behavior:
            return behavior["response"](request)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(200, json={"issuer": ISSUER, "authorization_endpoint": ORIGIN + OIDC + "/auth",
                "token_endpoint": ORIGIN + OIDC + "/token", "jwks_uri": ORIGIN + OIDC + "/certs",
                "userinfo_endpoint": ORIGIN + OIDC + "/userinfo", "code_challenge_methods_supported": ["plain", "S256"],
                "authorization_response_iss_parameter_supported": True,
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                "scopes_supported": ["openid", "email", "profile", "offline_access", "internship:read"],
                "registration_endpoint": ORIGIN + "/admin/clients"})
        if request.url.path.endswith("/token"):
            return httpx2.Response(200, json={"access_token": signed(), "token_type": "Bearer", "expires_in": 300,
                                             "refresh_token": uuid.uuid4().hex})
        if request.url.path.endswith("/certs"):
            return httpx2.Response(200, json={"keys": [jwk]})
        return httpx2.Response(200, text="synthetic login", headers={"Content-Type": "text/html"})
    app = create_gateway_app(config, provider_transport=httpx2.MockTransport(provider))
    return app, config, agent, profile, jid, calls, behavior, signed


def authorization(**changes):
    values = dict(response_type="code", client_id=CLIENT, redirect_uri=CALLBACK,
        resource=RESOURCE, scope="openid email profile internship:read", state="synthetic-state",
        code_challenge="x" * 43, code_challenge_method="S256")
    values.update(changes)
    return OIDC + "/auth?" + urlencode(values)


def basic(client=CLIENT):
    return "Basic " + base64.b64encode((client + ":synthetic-placeholder-only").encode()).decode()


def token_form(**changes):
    fields = dict(grant_type="authorization_code", code="synthetic-code", code_verifier="x" * 43,
                  redirect_uri=CALLBACK, resource=RESOURCE)
    fields.update(changes)
    return fields


def test_public_identity_metadata_and_readonly_mcp(gateway):
    app, _, agent, profile, jid, calls, _, signed = gateway
    before = (agent.store.path.read_bytes(), profile.read_bytes())
    with TestClient(app, base_url=ORIGIN) as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert metadata["resource"] == RESOURCE
        assert metadata["authorization_servers"] == [ISSUER]
        discovery = client.get("/realms/" + REALM + "/.well-known/openid-configuration").json()
        assert discovery["issuer"] == ISSUER
        assert discovery["code_challenge_methods_supported"] == ["S256"]
        assert discovery["token_endpoint_auth_methods_supported"] == ["client_secret_basic"]
        assert "offline_access" not in discovery["scopes_supported"]
        assert "registration_endpoint" not in discovery
        assert not discovery.get("client_id_metadata_document_supported")
        for method, params in [("tools/list", {}), ("tools/call", {"name": "application_summary", "arguments": {}}),
                               ("tools/call", {"name": "rank_jobs", "arguments": {"min_score": 0}}),
                               ("tools/call", {"name": "preview_application", "arguments": {"job_id": jid}})]:
            params["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                               "io.modelcontextprotocol/clientCapabilities": {}}
            headers = {"Authorization": "Bearer " + signed(), "Accept": "application/json, text/event-stream",
                       "MCP-Protocol-Version": "2026-07-28", "MCP-Method": method}
            if "name" in params:
                headers["MCP-Name"] = params["name"]
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers=headers)
            assert response.status_code == 200, response.text
            assert not response.json()["result"].get("isError")
            if method == "tools/list":
                tools = response.json()["result"]["tools"]
                assert len(tools) == 3
                assert all(t["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["internship:read"]}] for t in tools)
                assert all(t["securitySchemes"] == t["_meta"]["securitySchemes"] for t in tools)
    assert (agent.store.path.read_bytes(), profile.read_bytes()) == before


@pytest.mark.parametrize("changes", [{"resource": ORIGIN + "/wrong"}, {"client_id": "wrong"},
    {"redirect_uri": "https://attacker.invalid/callback"}, {"scope": "openid offline_access internship:read"},
    {"code_challenge_method": "plain"}, {"response_type": "token"}, {"state": ""}, {"request_uri": "https://attacker.invalid"}])
def test_authorization_parameters_are_pinned(gateway, changes):
    app, _, _, _, _, calls, _, _ = gateway
    with TestClient(app, base_url=ORIGIN) as client:
        before = len(calls)
        assert client.get(authorization(**changes)).status_code == 400
        assert len(calls) == before


def test_proxy_overwrites_untrusted_headers_and_preserves_valid_flow(gateway):
    app, _, _, _, _, calls, _, _ = gateway
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get(authorization(), headers={"X-Forwarded-Host": "attacker.invalid",
            "X-Forwarded-Proto": "http", "Forwarded": "host=attacker.invalid", "Authorization": "Bearer private-marker"})
        assert response.status_code == 200
        sent = calls[-1]
        assert sent.url.host == "127.0.0.1"
        assert sent.headers["host"] == "internship-test.tail-test.ts.net"
        assert sent.headers["x-forwarded-proto"] == "https"
        assert "forwarded" not in sent.headers
        assert "authorization" not in sent.headers
        assert client.post(OIDC + "/token", data=token_form(), headers={"Authorization": basic()}).status_code == 200
        assert client.post(OIDC + "/token", data={"grant_type": "refresh_token", "refresh_token": uuid.uuid4().hex,
            "resource": RESOURCE}, headers={"Authorization": basic()}).status_code == 200


@pytest.mark.parametrize("changes", [{"grant_type": "password"}, {"resource": "https://wrong.invalid/mcp"},
    {"scope": "offline_access"}, {"redirect_uri": "https://attacker.invalid"}, {"client_id": "wrong"},
    {"code_verifier": "short"}])
def test_token_exchange_rejects_invalid_forms(gateway, changes):
    app, _, _, _, _, calls, _, _ = gateway
    with TestClient(app, base_url=ORIGIN) as client:
        before = len(calls)
        response = client.post(OIDC + "/token", data=token_form(**changes), headers={"Authorization": basic()})
        assert response.status_code == 400
        assert len(calls) == before


@pytest.mark.parametrize("path", ["/", "/admin", "/realms/master", "/metrics", "/health", "/data/agent.db",
    "/config/profile.json", "/credentials", "/.env", "/realms/other/.well-known/openid-configuration",
    OIDC + "/registrations", OIDC + "/revoke", OIDC + "/token/introspect", OIDC + "/auth/extra",
    "/resources/abc12/admin/keycloak.v2/app.js", "/resources/abc12/account/keycloak.v3/app.js",
    "/resources/abc12/login/keycloak.v2/../../admin/secrets.js", "/realms/" + REALM + "/account",
    "/realms/" + REALM + "/login-actions/reset-credentials", "/mcp/", "/mcp%2f..%2fadmin"])
def test_unauthorized_paths_never_reach_provider(gateway, path):
    app, _, _, _, _, calls, _, _ = gateway
    with TestClient(app, base_url=ORIGIN) as client:
        before = len(calls)
        assert client.get(path).status_code in (400, 404)
        assert len(calls) == before


def test_malformed_headers_queries_forms_and_auth_fail_closed(gateway):
    app, _, _, _, _, calls, _, signed = gateway
    with TestClient(app, base_url=ORIGIN) as client:
        for raw in (None, "forged", signed(exp=1), signed(aud="wrong"), signed(sub="wrong"), signed(scope="write"),
                    signed(scope="internship:read offline_access")):
            headers = {} if raw is None else {"Authorization": "Bearer " + raw}
            assert client.post("/mcp", json={}, headers=headers).status_code in (401, 403)
        for headers in ({"Host": "attacker.invalid"}, {"Origin": "null"}, {"Origin": "https://attacker.invalid"}):
            assert client.get("/.well-known/oauth-protected-resource/mcp", headers=headers).status_code == 400
        assert client.get(authorization() + "&resource=" + RESOURCE).status_code == 400
        assert client.post(OIDC + "/token", content="grant_type=refresh_token&resource=a&resource=b",
            headers={"Authorization": basic(), "Content-Type": "application/x-www-form-urlencoded"}).status_code == 400
        assert client.post(OIDC + "/token", json=token_form(), headers={"Authorization": basic()}).status_code == 400
        assert client.post(OIDC + "/token", data=token_form()).status_code == 401
        assert client.get(OIDC + "/token?access_token=secret-marker").status_code in (400, 405)
        assert client.post(OIDC + "/token", content=b"x" * 65537).status_code == 413


def test_provider_failure_redirect_and_token_responses_are_sanitized(gateway):
    app, _, _, _, _, _, behavior, signed = gateway
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        for response in (lambda r: httpx2.Response(500, text="PRIVATE provider exception"),
                         lambda r: httpx2.Response(302, headers={"Location": "https://attacker.invalid"}),
                         lambda r: httpx2.Response(200, json={"access_token": signed(aud="wrong")})):
            behavior["response"] = response
            result = client.post(OIDC + "/token", data=token_form(), headers={"Authorization": basic()})
            assert result.status_code in (502, 503)
            assert "PRIVATE" not in result.text
        behavior["response"] = lambda r: httpx2.Response(302, headers=[("Location", CALLBACK + "?code=test&state=x&iss=" + ISSUER),
            ("Set-Cookie", "AUTH_SESSION_ID=fictional; Path=/realms/" + REALM + "; HttpOnly; Secure; SameSite=Lax"),
            ("Set-Cookie", "KC_RESTART=fictional; Path=/realms/" + REALM + "; HttpOnly; Secure; SameSite=Lax")])
        result = client.get(authorization())
        assert result.status_code == 302
        assert len(result.headers.get_list("set-cookie")) == 2
        assert result.headers["cache-control"] == "no-store"


def test_gateway_restart_retains_identity_keys_and_database(gateway):
    from internship_agent.mcp_gateway import create_gateway_app
    app, config, agent, profile, _, calls, _, signed = gateway
    before = (agent.store.path.read_bytes(), profile.read_bytes())
    for instance in (app, create_gateway_app(config, provider_transport=app.provider_transport)):
        with TestClient(instance, base_url=ORIGIN) as client:
            assert client.get("/.well-known/oauth-protected-resource/mcp").json()["resource"] == RESOURCE
            assert client.get(OIDC + "/userinfo", headers={"Authorization": "Bearer " + signed()}).status_code == 200
    assert (agent.store.path.read_bytes(), profile.read_bytes()) == before


def test_proxy_cookies_belong_to_each_browser_only(gateway):
    app, _, _, _, _, calls, behavior, _ = gateway
    with TestClient(app, base_url=ORIGIN) as first:
        # Even a provider cookie missing Secure must never enter a shared jar.
        behavior["response"] = lambda r: httpx2.Response(200, text="fictional login", headers={
            "Set-Cookie": "KEYCLOAK_SESSION=fictional; Path=/; HttpOnly; SameSite=Lax"})
        response = first.get(authorization(), headers={"Cookie": "browser-only=first"})
        assert calls[-1].headers["cookie"] == "browser-only=first"
        assert "Secure" in response.headers["set-cookie"]
        second = TestClient(app, base_url=ORIGIN)
        try:
            assert second.get(authorization()).status_code == 200
            assert "cookie" not in calls[-1].headers
        finally:
            second.close()
        assert first.get(authorization()).status_code == 200
        assert "KEYCLOAK_SESSION=fictional" in calls[-1].headers["cookie"]


@pytest.mark.parametrize("changes", [
    {"public_origin": "http://internship-test.tail-test.ts.net"}, {"public_origin": "https://paid.example"},
    {"public_origin": ORIGIN + "/"}, {"public_origin": "https://user:pass@internship-test.tail-test.ts.net"},
    {"realm": "master"}, {"realm": "../admin"}, {"keycloak_port": 8765}, {"listen_port": True},
    {"redirect_uris": ["https://chatgpt.com/*"]}, {"redirect_uris": ["https://attacker.invalid/callback"]},
    {"redirect_uris": [CALLBACK + "?next=attacker"]}, {"owner_subject": ""},
])
def test_configuration_rejects_noncanonical_or_unsafe_values(gateway, changes):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(gateway[1], **changes)


def test_duplicate_headers_and_provider_metadata_fail_closed(gateway):
    app, _, _, _, _, calls, behavior, _ = gateway
    with TestClient(app, base_url=ORIGIN) as client:
        before = len(calls)
        for headers in ([('Host', 'internship-test.tail-test.ts.net'), ('Host', 'attacker.invalid')],
                        [('Origin', ORIGIN), ('Origin', 'https://attacker.invalid')],
                        [('Authorization', basic()), ('Authorization', 'Basic forged')]):
            assert client.get(authorization(), headers=headers).status_code == 400
        assert len(calls) == before
    behavior['response'] = lambda r: httpx2.Response(200, json={'issuer': 'https://attacker.invalid'})
    with pytest.raises(ValueError, match="Identity metadata"):
        with TestClient(app, base_url=ORIGIN):
            pytest.fail("Mismatched provider metadata must prevent startup")


def test_only_qualified_login_and_public_assets_are_proxied(gateway):
    app, _, _, _, _, calls, _, _ = gateway
    with TestClient(app, base_url=ORIGIN) as client:
        for path in ("/resources/abc12/login/keycloak.v2/css/styles.css", "/resources/abc12/common/keycloak/web_modules/app.js",
                     "/realms/" + REALM + "/login-actions/restart?client_id=" + CLIENT):
            assert client.get(path).status_code == 200
        before = len(calls)
        assert client.get("/realms/" + REALM + "/login-actions/restart?client_id=wrong").status_code == 400
        assert client.get("/realms/" + REALM + "/login-actions/required-action").status_code == 404
        assert len(calls) == before


def test_cli_stays_loopback_with_hidden_windows_streams(gateway, tmp_path, monkeypatch):
    from dataclasses import asdict
    from internship_agent import mcp_gateway
    import sys
    values = asdict(gateway[1])
    for name in ("jwks_path", "data_root", "profile_path"):
        values[name] = str(values[name])
    path = tmp_path / "gateway.json"
    path.write_text(json.dumps(values))
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    monkeypatch.setattr("logging.basicConfig", lambda **kwargs: None)
    # pythonw supplies no console streams. This must not initialize a console formatter.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    mcp_gateway.main(["--config", str(path)])
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["proxy_headers"] is False
    assert calls[0]["access_log"] is False
    assert calls[0]["log_config"] is None
    assert calls[0]["limit_concurrency"] == 32
