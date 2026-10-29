"""Loopback-only gateway prepared for reviewed Funnel HTTPS forwarding.

This module never starts a tunnel. Its only upstream is one fixed loopback
Keycloak listener; it cannot proxy arbitrary hosts, realms, folders or services.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from http.cookies import SimpleCookie
import json
from urllib.parse import urlsplit

import httpx2
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .mcp_gateway_config import GatewayConfig
from .mcp_gateway_policy import GatewayPolicy, Rejected, SCOPES
from .mcp_http import JWTVerifier, METADATA_PATH, create_http_app

MAX_BODY = 65536
MAX_RESPONSE = 2 * 1024 * 1024


class BrowserOnlyCookies(DefaultCookiePolicy):
    """A shared proxy connection pool must never retain browser session state."""

    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


class Gateway:
    def __init__(self, config, *, provider_transport=None):
        self.config = config
        self.policy = GatewayPolicy(config)
        self.provider_transport = provider_transport
        self.verifier = JWTVerifier(config.auth)
        self.mcp = create_http_app(config.data_root, config.profile_path, config.auth)
        self.lifecycle = Starlette(lifespan=self.lifespan)
        self.http = None

    @asynccontextmanager
    async def lifespan(self, app):
        async with httpx2.AsyncClient(base_url=self.config.provider_url, transport=self.provider_transport,
                cookies=CookieJar(policy=BrowserOnlyCookies()),
                follow_redirects=False, trust_env=False, timeout=5,
                limits=httpx2.Limits(max_connections=8, max_keepalive_connections=4)) as http:
            self.http = http
            try:
                await self.preflight()
                async with self.mcp.app.router.lifespan_context(self.mcp.app):
                    yield
            finally:
                self.http = None

    async def upstream(self, path, *, method="GET", query=b"", body=b"", headers=None):
        if self.http is None:
            raise Rejected("Identity service unavailable", 503)
        host = urlsplit(self.config.public_origin).netloc
        forwarded = {"Host": host, "X-Forwarded-Proto": "https", "X-Forwarded-Host": host,
                     "X-Forwarded-Port": "443", "Accept-Encoding": "identity"}
        forwarded.update(headers or {})
        # Path came from the exact allowlist; caller input never selects an origin.
        url = self.config.provider_url + path + ("?" + query.decode("ascii") if query else "")
        try:
            async with self.http.stream(method, url, content=body, headers=forwarded) as response:
                content = bytearray()
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > MAX_RESPONSE:
                        raise Rejected("Identity response unavailable", 502)
                return response.status_code, response.headers, bytes(content)
        except httpx2.HTTPError:
            raise Rejected("Identity service unavailable", 503) from None

    async def preflight(self):
        status, _, content = await self.upstream(self.policy.discovery)
        try:
            doc = json.loads(content)
            cfg, endpoint = self.config, self.config.public_origin + self.policy.oidc
            if (status != 200 or doc.get("issuer") != cfg.issuer or
                    any(doc.get(name) != endpoint + suffix for name, suffix in (
                        ("authorization_endpoint", "/auth"), ("token_endpoint", "/token"),
                        ("jwks_uri", "/certs"), ("userinfo_endpoint", "/userinfo"))) or
                    "S256" not in doc.get("code_challenge_methods_supported", []) or
                    "client_secret_basic" not in doc.get("token_endpoint_auth_methods_supported", []) or
                    doc.get("authorization_response_iss_parameter_supported") is not True or
                    not set(SCOPES) <= set(doc.get("scopes_supported", []))):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise Rejected("Identity metadata does not match the approved configuration", 503) from None

    def metadata(self):
        cfg, endpoint = self.config, self.config.public_origin + self.policy.oidc
        return {"issuer": cfg.issuer, "authorization_endpoint": endpoint + "/auth",
            "token_endpoint": endpoint + "/token", "jwks_uri": endpoint + "/certs",
            "userinfo_endpoint": endpoint + "/userinfo", "response_types_supported": ["code"],
            "response_modes_supported": ["query"], "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            "code_challenge_methods_supported": ["S256"], "scopes_supported": list(SCOPES),
            "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"],
            "authorization_response_iss_parameter_supported": True}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.lifecycle(scope, receive, send)
        if scope["type"] != "http":
            return
        async def secure_send(message):
            if message["type"] == "http.response.start":
                remove = {b"server", b"cache-control", b"referrer-policy", b"x-content-type-options"}
                message = {**message, "headers": [(k, v) for k, v in message.get("headers", []) if k.lower() not in remove] + [
                    (b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"), (b"strict-transport-security", b"max-age=31536000")]}
            await send(message)
        try:
            await self.handle(scope, receive, secure_send)
        except Rejected as error:
            headers = None
            if error.status == 401:
                challenge = ('Basic realm="OAuth client"' if scope["path"] == self.policy.oidc + "/token" else
                             f'Bearer resource_metadata="{self.config.public_origin}{METADATA_PATH}"')
                headers = {"WWW-Authenticate": challenge}
            await JSONResponse({"error": str(error)}, status_code=error.status, headers=headers)(scope, receive, secure_send)

    async def handle(self, scope, receive, send):
        headers = {}
        for name, value in scope.get("headers", []):
            key = name.decode("latin-1").lower()
            if key in headers and key in ("host", "origin", "authorization", "content-type", "content-length", "cookie"):
                raise Rejected("Invalid request headers")
            headers[key] = value.decode("latin-1")
        if (headers.get("host") != urlsplit(self.config.public_origin).netloc or
                ("origin" in headers and headers["origin"] != self.config.public_origin)):
            raise Rejected("Invalid request headers")
        raw_path = scope.get("raw_path", scope["path"].encode()).split(b"?")[0]
        if (b"%" in raw_path or b"\\" in raw_path or b";" in raw_path or b"//" in raw_path or
                any(segment in (b".", b"..") for segment in raw_path.split(b"/"))):
            raise Rejected("Invalid request path")
        query = scope.get("query_string", b"")
        if len(query) > 16384:
            raise Rejected("Request too large", 413)
        async def read_body():
            result = bytearray()
            async for part in Request(scope, receive).stream():
                result.extend(part)
                if len(result) > MAX_BODY:
                    raise Rejected("Request too large", 413)
            return bytes(result)
        try:
            body = await asyncio.wait_for(read_body(), timeout=10)
        except asyncio.TimeoutError:
            raise Rejected("Request timed out", 408) from None
        kind = self.policy.route(scope["path"], scope["method"])
        self.policy.validate(kind, query, body, headers)
        if scope["method"] in ("GET", "HEAD") and body:
            raise Rejected()
        if kind in ("mcp", "metadata-alias"):
            if kind == "metadata-alias":
                scope = {**scope, "path": METADATA_PATH, "raw_path": METADATA_PATH.encode()}
            consumed = False
            async def replay():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()
            return await self.mcp(scope, replay, send)
        if kind == "discovery":
            return await JSONResponse(self.metadata())(scope, receive, send)
        if kind == "userinfo":
            auth = headers.get("authorization", "")
            if not auth.startswith("Bearer ") or await self.verifier.verify_token(auth[7:]) is None:
                raise Rejected("Authorization required", 401)
        forwarded = {name: headers[name] for name in ("content-type", "cookie", "accept", "accept-language") if name in headers}
        if kind in ("token", "userinfo"):
            forwarded["authorization"] = headers.get("authorization", "")
            forwarded.pop("cookie", None)
        status, response_headers, content = await self.upstream(scope["path"], method=scope["method"],
            query=query, body=body, headers=forwarded)
        if status >= 500:
            raise Rejected("Identity service unavailable", 503)
        if kind in ("token", "certs", "userinfo") and 300 <= status < 400:
            raise Rejected("Identity redirect unavailable", 502)
        if kind == "token" and status == 200:
            try:
                result = json.loads(content)
                if await self.verifier.verify_token(result.get("access_token", "")) is None:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise Rejected("Identity response unavailable", 502) from None
        elif kind == "token" and status >= 400:
            try:
                error = json.loads(content).get("error")
            except (ValueError, AttributeError):
                error = None
            safe = error if error in {"invalid_grant", "invalid_client", "invalid_target", "invalid_scope", "invalid_request"} else "invalid_request"
            return await JSONResponse({"error": safe}, status_code=status)(scope, receive, send)
        outgoing = []
        for name, value in response_headers.multi_items():
            key = name.lower()
            if key == "location":
                try:
                    if not self.policy.redirect_allowed(value):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    raise Rejected("Identity redirect unavailable", 502) from None
                outgoing.append((b"location", value.encode("latin-1")))
            elif key == "set-cookie":
                cookie = SimpleCookie()
                cookie.load(value)
                if not cookie or any(m["domain"] not in ("", urlsplit(self.config.public_origin).netloc) for m in cookie.values()):
                    raise Rejected("Identity cookie unavailable", 502)
                for morsel in cookie.values():
                    morsel["secure"] = True
                    outgoing.append((b"set-cookie", morsel.OutputString().encode("latin-1")))
            elif key in ("content-type", "content-security-policy", "x-frame-options", "content-language"):
                outgoing.append((key.encode(), value.encode("latin-1")))
        response = Response(content=content, status_code=status)
        response.raw_headers = outgoing + [(b"content-length", str(len(content)).encode())]
        await response(scope, receive, send)


def create_gateway_app(config, *, provider_transport=None):
    return Gateway(config, provider_transport=provider_transport)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Private local gateway JSON")
    args = parser.parse_args(argv)
    try:
        config = GatewayConfig.from_file(args.config)
        app = create_gateway_app(config)
    except Exception:
        parser.exit(2, "Gateway startup failed. Check the private configuration, existing database and public signing keys.\n")
    import uvicorn
    import logging
    # pythonw has no stderr/stdout; avoid Uvicorn's console formatter and prevent
    # request/credential data from reaching an inherited application log handler.
    logging.basicConfig(handlers=[logging.NullHandler()], force=True)
    uvicorn.run(app, host="127.0.0.1", port=config.listen_port, proxy_headers=False,
                access_log=False, server_header=False, log_level="warning", log_config=None,
                limit_concurrency=32, timeout_keep_alive=5)


if __name__ == "__main__":
    main()
