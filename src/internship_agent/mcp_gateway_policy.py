"""Narrow Keycloak browser/OAuth route policy. No generic reverse-proxy mount."""
import base64
import binascii
import re
from urllib.parse import parse_qsl, urlsplit

from .mcp_http import READ_SCOPE

SCOPES = ("openid", "email", "profile", READ_SCOPE)


class Rejected(ValueError):
    def __init__(self, message="Invalid request", status=400):
        self.status = status
        super().__init__(message)


def fields(raw: bytes, limit=16384):
    if len(raw) > limit:
        raise Rejected("Request too large", 413)
    try:
        text = raw.decode("ascii")
        if re.search(r"%(?![0-9a-fA-F]{2})", text):
            raise ValueError()
        pairs = parse_qsl(text, keep_blank_values=True, strict_parsing=True,
                          encoding="utf-8", errors="strict", max_num_fields=24)
        if len({name for name, _ in pairs}) != len(pairs):
            raise ValueError()
        if any(any(ord(c) < 32 or ord(c) == 127 for c in name + value) for name, value in pairs):
            raise ValueError()
        return dict(pairs)
    except (ValueError, UnicodeError):
        raise Rejected() from None


class GatewayPolicy:
    def __init__(self, config):
        self.config = config
        self.realm_path = "/realms/" + config.realm
        self.oidc = self.realm_path + "/protocol/openid-connect"
        self.discovery = self.realm_path + "/.well-known/openid-configuration"
        self.discovery_aliases = {self.discovery,
            "/.well-known/oauth-authorization-server" + self.realm_path,
            "/.well-known/openid-configuration" + self.realm_path}

    def route(self, path, method):
        routes = {"/mcp": ({"GET", "POST", "DELETE"}, "mcp"),
            "/.well-known/oauth-protected-resource/mcp": ({"GET", "HEAD"}, "mcp"),
            "/.well-known/oauth-protected-resource": ({"GET", "HEAD"}, "metadata-alias"),
            self.oidc + "/auth": ({"GET"}, "authorize"), self.oidc + "/token": ({"POST"}, "token"),
            self.oidc + "/certs": ({"GET", "HEAD"}, "certs"),
            self.oidc + "/userinfo": ({"GET"}, "userinfo"),
            self.realm_path + "/login-actions/authenticate": ({"GET", "POST"}, "login"),
            self.realm_path + "/login-actions/restart": ({"GET"}, "restart"),
            self.realm_path + "/login-actions/consent": ({"POST"}, "login")}
        for route in self.discovery_aliases:
            routes[route] = ({"GET", "HEAD"}, "discovery")
        if re.fullmatch(r"/resources/[a-z0-9]{5}/(?:login/keycloak\.v2|common/keycloak)/[A-Za-z0-9_./@-]+", path):
            routes[path] = ({"GET", "HEAD"}, "asset")
        if path not in routes:
            raise Rejected("Not found", 404)
        methods, kind = routes[path]
        if method not in methods:
            raise Rejected("Method not allowed", 405)
        return kind

    def validate(self, kind, query, body, headers):
        cfg = self.config
        query_fields = fields(query)
        if kind == "authorize":
            required = {"response_type", "client_id", "redirect_uri", "resource", "scope", "state",
                        "code_challenge", "code_challenge_method"}
            optional = {"nonce", "prompt", "max_age", "login_hint", "id_token_hint", "ui_locales", "response_mode"}
            if not required <= query_fields.keys() or query_fields.keys() - required - optional:
                raise Rejected()
            q = query_fields
            if (q["response_type"] != "code" or q["client_id"] != cfg.client_id or
                    q["redirect_uri"] not in cfg.redirect_uris or q["resource"] != cfg.resource or
                    not q["state"] or len(q["state"]) > 2048 or q["code_challenge_method"] != "S256" or
                    not re.fullmatch(r"[A-Za-z0-9_-]{43}", q["code_challenge"]) or
                    q.get("response_mode", "query") != "query"):
                raise Rejected()
            self.validate_scopes(q["scope"])
        elif kind in ("login", "restart"):
            allowed = {"auth_session_id", "session_code", "execution", "client_id", "tab_id", "client_data"}
            if kind == "restart":
                allowed.add("skip_logout")
            if query_fields.keys() - allowed or query_fields.get("client_id", cfg.client_id) != cfg.client_id:
                raise Rejected()
            if body:
                self.form(body, headers)
        else:
            if query:
                raise Rejected("Query parameters are not accepted")
            if kind == "token":
                self.validate_token_request(self.form(body, headers), headers)

    @staticmethod
    def validate_scopes(value):
        scopes = value.split()
        if READ_SCOPE not in scopes or set(scopes) - set(SCOPES):
            raise Rejected("Unsupported scope")

    @staticmethod
    def form(body, headers):
        if headers.get("content-type", "").split(";")[0].lower() != "application/x-www-form-urlencoded":
            raise Rejected("Form encoding required")
        return fields(body, limit=65536)

    def validate_token_request(self, form, headers):
        cfg = self.config
        try:
            auth = headers.get("authorization", "")
            if not auth.startswith("Basic ") or len(auth) > 8192:
                raise ValueError()
            client, secret = base64.b64decode(auth[6:], validate=True).decode("utf-8").split(":", 1)
            if client != cfg.client_id or not secret:
                raise ValueError()
        except (ValueError, UnicodeError, binascii.Error):
            raise Rejected("Client authentication required", 401) from None
        grant = form.get("grant_type")
        allowed = {"grant_type", "resource", "client_id"}
        if grant == "authorization_code":
            allowed |= {"code", "code_verifier", "redirect_uri"}
            if (not form.get("code") or form.get("redirect_uri") not in cfg.redirect_uris or
                    not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", form.get("code_verifier", ""))):
                raise Rejected()
        elif grant == "refresh_token":
            allowed |= {"refresh_token", "scope"}
            if not form.get("refresh_token") or len(form["refresh_token"]) > 16384:
                raise Rejected()
            if "scope" in form:
                self.validate_scopes(form["scope"])
        else:
            raise Rejected("Unsupported grant")
        if (form.keys() - allowed or form.get("resource") != cfg.resource or
                form.get("client_id", cfg.client_id) != cfg.client_id):
            raise Rejected()

    def redirect_allowed(self, location):
        parsed = urlsplit(location)
        if parsed.fragment or parsed.username or parsed.password:
            return False
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if base in self.config.redirect_uris:
            values = fields(parsed.query.encode("ascii"))
            return values.get("iss") == self.config.issuer
        if f"{parsed.scheme}://{parsed.netloc}" != self.config.public_origin:
            return False
        try:
            return self.route(parsed.path, "GET") in ("authorize", "login", "restart")
        except Rejected:
            return False
