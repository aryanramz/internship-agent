"""Explicit public identity configuration; every local listener stays on loopback."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .mcp_http import AuthConfig


def public_origin(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
            r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\.ts\.net", value):
        raise ValueError("Use the exact free Funnel HTTPS origin without port, path or trailing slash")
    return value


def chatgpt_callback(value: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(
        r"https://chatgpt\.com/(?:connector_platform_oauth_redirect|connector/oauth/[A-Za-z0-9_-]{1,128})", value))


@dataclass(frozen=True)
class GatewayConfig:
    public_origin: str
    realm: str
    client_id: str
    owner_subject: str
    jwks_path: Path
    data_root: Path
    profile_path: Path
    keycloak_port: int
    listen_port: int
    redirect_uris: list[str]

    def __post_init__(self):
        public_origin(self.public_origin)
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", self.realm) or self.realm == "master":
            raise ValueError("Use a dedicated non-administrative realm")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.client_id) or not self.owner_subject.strip():
            raise ValueError("Configure one explicit client and owner subject")
        if any(type(port) is not int or not 1024 <= port <= 65535 for port in (self.keycloak_port, self.listen_port)):
            raise ValueError("Use unprivileged local listener ports")
        if self.keycloak_port == self.listen_port:
            raise ValueError("The gateway cannot proxy back to its own port")
        if (not isinstance(self.redirect_uris, list) or not 1 <= len(self.redirect_uris) <= 2 or
                len(set(self.redirect_uris)) != len(self.redirect_uris) or
                not all(chatgpt_callback(value) for value in self.redirect_uris)):
            raise ValueError("Copy the exact ChatGPT management-page redirect; no wildcard callbacks")

    @property
    def issuer(self):
        return self.public_origin + "/realms/" + self.realm

    @property
    def resource(self):
        return self.public_origin + "/mcp"

    @property
    def provider_url(self):
        return f"http://127.0.0.1:{self.keycloak_port}"

    @property
    def auth(self):
        return AuthConfig(issuer=self.issuer, resource=self.resource, owner_subject=self.owner_subject,
            client_id=self.client_id, jwks_path=self.jwks_path, public_origin=self.public_origin)

    @classmethod
    def from_file(cls, filename):
        path = Path(filename).resolve()
        if path.stat().st_size > 16384:
            raise ValueError("Gateway configuration exceeds the size limit")
        values = json.loads(path.read_text(encoding="utf-8-sig"))
        for key in ("jwks_path", "data_root", "profile_path"):
            values[key] = path.parent / values[key]
        return cls(**values)
