"""Authenticated, loopback-only HTTP proof of concept. No tunnel or OAuth issuer.

Only pinned public signing keys are loaded; the adapter never fetches a token URL,
loads Google credentials, or issues tokens. External routing is intentionally absent.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse

from .mcp_server import create_server

READ_SCOPE = "internship:read"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    resource: str
    owner_subject: str
    client_id: str
    jwks_path: Path
    public_origin: str | None = None

    def __post_init__(self):
        issuer = urlsplit(self.issuer)
        resource = urlsplit(self.resource)
        if (issuer.scheme not in ("http", "https") or not issuer.hostname or
                issuer.username or issuer.password or issuer.query or issuer.fragment or
                (issuer.scheme == "http" and issuer.hostname != "127.0.0.1")):
            raise ValueError("Configure an HTTPS issuer or an explicit loopback test issuer")
        if self.public_origin is not None:
            from .mcp_gateway_config import public_origin
            import re
            origin = public_origin(self.public_origin)
            if (self.resource != origin + "/mcp" or self.issuer == origin + "/realms/master" or
                    not self.issuer.startswith(origin + "/realms/") or
                    not re.fullmatch(r"/realms/[a-z][a-z0-9-]{0,62}", issuer.path)):
                raise ValueError("Public resource and issuer must share the configured dedicated HTTPS origin")
        elif (resource.scheme != "http" or resource.hostname != "127.0.0.1" or
                not resource.port or resource.path != "/mcp" or resource.query or resource.fragment or
                resource.netloc != f"127.0.0.1:{resource.port}"):
            raise ValueError("This proof of concept only accepts http://127.0.0.1:PORT/mcp")
        if not self.owner_subject.strip() or not self.client_id.strip():
            raise ValueError("An explicit owner subject and registered client ID are required")

    @classmethod
    def from_file(cls, path: str | Path) -> AuthConfig:
        path = Path(path).resolve()
        values = json.loads(path.read_text(encoding="utf-8-sig"))
        values["jwks_path"] = path.parent / values["jwks_path"]
        return cls(**values)


class JWTVerifier(TokenVerifier):
    """Fail closed using an operator-pinned public JWKS; no token-controlled I/O."""

    def __init__(self, config: AuthConfig):
        self.config = config
        path = Path(config.jwks_path)
        if path.stat().st_size > 65536:
            raise ValueError("Public JWKS exceeds the configured size limit")
        keys = json.loads(path.read_text(encoding="utf-8-sig"))["keys"]
        if not isinstance(keys, list) or not 1 <= len(keys) <= 10:
            raise ValueError("Configure between one and ten pinned public RSA keys")
        self.keys = {}
        seen = set()
        for entry in keys:
            kid = entry.get("kid")
            if (not isinstance(kid, str) or not kid or kid in seen or
                    any(field in entry for field in ("d", "p", "q", "dp", "dq", "qi", "oth", "k"))):
                raise ValueError("Use unique public keys only")
            seen.add(kid)
            # OIDC providers also publish encryption/other-algorithm keys.
            # They are not trusted for verification, even if a token names them.
            if entry.get("use", "sig") != "sig" or entry.get("alg", "RS256") != "RS256":
                continue
            if entry.get("kty") != "RSA" or ("key_ops" in entry and entry["key_ops"] != ["verify"]):
                raise ValueError("Use RS256 signing keys with verification permission")
            key = jwt.PyJWK.from_dict(entry, algorithm="RS256").key
            if key.key_size < 2048:
                raise ValueError("RSA signing keys must be at least 2048 bits")
            self.keys[kid] = key
        if not self.keys:
            raise ValueError("At least one public RS256 signing key is required")

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            if not isinstance(token, str) or not 0 < len(token) <= 16384:
                return None
            header = jwt.get_unverified_header(token)
            # Never follow jku/x5u or accept an algorithm selected by the caller.
            if (header.get("alg") != "RS256" or header.get("typ") not in ("at+jwt", "JWT") or
                    any(field in header for field in ("crit", "jku", "x5u", "jwk"))):
                return None
            key = self.keys.get(header.get("kid"))
            if key is None:
                return None
            cfg = self.config
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=cfg.issuer,
                audience=cfg.resource, leeway=0,
                options={"require": ["iss", "aud", "sub", "iat", "exp", "scope"]})
            if (claims["aud"] not in (cfg.resource, [cfg.resource]) or
                    claims["sub"] != cfg.owner_subject or
                    type(claims["iat"]) is not int or type(claims["exp"]) is not int or
                    ("nbf" in claims and type(claims["nbf"]) is not int) or
                    not isinstance(claims["scope"], str) or
                    (header["typ"] == "JWT" and claims.get("typ") != "Bearer")):
                return None
            clients = [claims[field] for field in ("client_id", "azp") if field in claims]
            if not clients or any(client != cfg.client_id for client in clients):
                return None
            scopes = claims["scope"].split()
            if READ_SCOPE not in scopes:
                return None
            if cfg.public_origin is not None and set(scopes) - {"openid", "email", "profile", READ_SCOPE}:
                return None
            return AccessToken(token=token, client_id=cfg.client_id, subject=cfg.owner_subject,
                scopes=scopes, expires_at=claims["exp"], resource=cfg.resource, claims={"iss": cfg.issuer})
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
            # No tokens, claims, paths or library exception strings reach logs/client.
            return None


class InvocationGuard:
    """Revalidate the current request immediately before each tool dispatch."""

    def __init__(self, verifier: JWTVerifier):
        self.verifier = verifier

    async def __call__(self, ctx, call_next):
        if ctx.method == "tools/call":
            request = ctx.request
            authorization = request.headers.get("authorization", "") if request is not None else ""
            token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
            if await self.verifier.verify_token(token) is None:
                raise MCPError(-32001, "Authorization required")
        return await call_next(ctx)


class OAuthToolMetadata:
    """Publish canonical OAuth tool descriptors and retain the SDK meta mirror."""

    async def __call__(self, ctx, call_next):
        result = await call_next(ctx)
        if ctx.method == "tools/list":
            data = result.model_dump(mode="json", by_alias=True) if hasattr(result, "model_dump") else result
            for tool in data.get("tools", []):
                tool["securitySchemes"] = [{"type": "oauth2", "scopes": [READ_SCOPE]}]
            return data
        return result


class LocalBoundary:
    """Exact route/Host/Origin allowlist also covers the unauthenticated metadata.

    Forwarded headers are deliberately ignored. No reverse proxy, admin mount,
    static-file route, redirect, CORS wildcard or query-token support is installed.
    """

    def __init__(self, app, resource: str):
        self.app = app
        parsed = urlsplit(resource)
        self.host = parsed.netloc
        self.origin = f"{parsed.scheme}://{parsed.netloc}"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        hosts = [value.decode("latin-1") for key, value in headers if key.lower() == b"host"]
        origins = [value.decode("latin-1") for key, value in headers if key.lower() == b"origin"]
        auth_headers = [value for key, value in headers if key.lower() == b"authorization"]
        if hosts != [self.host] or (origins and origins != [self.origin]) or len(auth_headers) > 1:
            return await JSONResponse({"error": "Invalid request headers"}, status_code=400)(scope, receive, send)
        if scope["path"] not in ("/mcp", METADATA_PATH):
            return await JSONResponse({"error": "Not found"}, status_code=404)(scope, receive, send)
        if scope.get("query_string"):
            return await JSONResponse({"error": "Query parameters are not accepted"}, status_code=400)(scope, receive, send)
        await self.app(scope, receive, send)


def create_http_app(data_root: str | Path, profile_path: str | Path, config: AuthConfig):
    verifier = JWTVerifier(config)
    server = create_server(data_root, profile_path, token_verifier=verifier,
        auth=AuthSettings(issuer_url=AnyHttpUrl(config.issuer), resource_server_url=AnyHttpUrl(config.resource),
                          required_scopes=[READ_SCOPE], validate_token_resource=True),
        middleware=[InvocationGuard(verifier), OAuthToolMetadata()])
    parsed = urlsplit(config.resource)
    app = server.streamable_http_app(json_response=True, stateless_http=True, max_request_body_size=65536,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[parsed.netloc], allowed_origins=[f"{parsed.scheme}://{parsed.netloc}"]))
    return LocalBoundary(app, config.resource)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-config", required=True, help="Private local configuration JSON with public JWKS path")
    parser.add_argument("--data", required=True, help="Existing isolated synthetic data directory")
    parser.add_argument("--profile", required=True, help="Synthetic verified profile JSON")
    args = parser.parse_args(argv)
    try:
        config = AuthConfig.from_file(args.auth_config)
        if config.public_origin is not None:
            raise ValueError("Public identity configuration requires the reviewed gateway entry point")
        app = create_http_app(args.data, args.profile, config)
    except Exception:
        parser.exit(2, "Local MCP startup failed. Check the existing database, auth configuration and public JWKS.\n")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=urlsplit(config.resource).port, proxy_headers=False,
                access_log=False, server_header=False, log_level="warning")


if __name__ == "__main__":
    main()
