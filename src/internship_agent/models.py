from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_url(url: str) -> str:
    """Keep the employer's canonical path, strip tracking query strings."""
    if not url:
        return ""
    p = urlsplit(url)
    clean_params = [(k, v) for k, v in parse_qsl(p.query) if k.lower() in {"gh_jid", "jk", "vjk", "jobid", "job_id", "jid", "reqid"}]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(clean_params), ""))


def stable_id(provider: str, token: str, source_id: str) -> str:
    value = f"{provider.lower()}|{token.lower()}|{source_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class Job:
    id: str
    provider: str
    company: str
    source_id: str
    title: str
    location: str
    description: str
    job_url: str
    apply_url: str
    work_mode: str = "Unknown"
    published_at: str = ""
    compensation: str = ""
    discovered_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


VALID_PROVIDERS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "breezy", "personio", "pinpoint", "bamboohr", "teamtailor", "remotive", "jobicy", "simplify_github", "rss", "csv_import", "json_import", "workday", "usajobs"}
TOKEN_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}$")


def validate_board(board: dict) -> dict:
    provider = str(board.get("provider", "")).lower()
    token = str(board.get("token", ""))
    company = str(board.get("company", "")).strip()
    if provider not in VALID_PROVIDERS or not TOKEN_PATTERN.fullmatch(token) or not company:
        raise ValueError("Board requires a supported provider, safe URL token and company name")
    out = {"provider": provider, "token": token, "company": company}
    if "intern_only" in board:
        if not isinstance(board["intern_only"], bool):
            raise ValueError("intern_only must be boolean")
        out["intern_only"] = board["intern_only"]
    if provider in {"csv_import", "json_import"}:
        path = board.get("path", "")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Local import needs a path")
        out["path"] = path
    if provider == "personio":
        domain = board.get("domain", "de")
        if domain not in {"de","com"}: raise ValueError("Personio domain must be de or com")
        out["domain"] = domain
    if provider == "workday":
        terms = board.get("search_terms", ["intern", "summer", "co-op"])
        if not isinstance(terms, list) or not (1 <= len(terms) <= 4) or any(not isinstance(t, str) or not t.strip() or len(t)>40 for t in terms):
            raise ValueError("Workday search_terms must be 1-4 short search strings")
        out["search_terms"] = terms
        host = board.get("host", "")
        site = board.get("site", "")
        if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.myworkdayjobs\.com", host.lower()):
            raise ValueError("Workday host must be a company subdomain of myworkdayjobs.com")
        if not isinstance(site, str) or not TOKEN_PATTERN.fullmatch(site):
            raise ValueError("Workday needs site slug")
        out.update(host=host.lower(), site=site)
    if provider == "usajobs":
        out["keyword"] = str(board.get("keyword", "internship"))[:80]
    if provider == "rss":
        from urllib.parse import urlsplit
        url = board.get("feed_url", "")
        if not isinstance(url, str): raise ValueError("RSS needs HTTPS feed_url")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("RSS needs HTTPS feed_url with no embedded credentials")
        import ipaddress
        host = parsed.hostname.lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if host in {"localhost"} or host.endswith((".localhost", ".local", ".internal")):
                raise ValueError("Private feed hosts are not allowed")
        else:
            raise ValueError("RSS feed must use a public DNS hostname, not an IP address")
        if parsed.port not in (None, 443):
            raise ValueError("RSS feeds may only use HTTPS default port")
        out["feed_url"] = url
    return out
