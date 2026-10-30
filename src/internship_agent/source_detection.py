"""Convert a known employer career-site URL to a safe configured reader.
No pages are fetched; unknown hosts are not guessed or scraped.
"""
from __future__ import annotations
from urllib.parse import urlsplit
from .models import validate_board


def detect_source(url: str, company: str) -> dict:
    p = urlsplit(url)
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.port not in (None,443) or any(ord(c)<32 or ord(c)==127 for c in url)):
        raise ValueError("Paste an HTTPS employer careers URL")
    host = p.hostname.lower()
    parts = [part for part in p.path.split("/") if part]
    first = parts[0] if parts else ""
    provider = ""
    token = ""
    extra = {}
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io"}:
        provider, token = "greenhouse", parts[2] if len(parts)>2 and parts[0]=="v1" else first
    elif host == "jobs.lever.co":
        provider, token = "lever", first
    elif host == "jobs.ashbyhq.com":
        provider, token = "ashby", first
    elif host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}:
        provider, token = "smartrecruiters", first
    elif host == "apply.workable.com":
        provider, token = "workable", first
        if token in {"j", "api"}:
            raise ValueError("Workable short job URL does not contain the company board name; use the main careers URL")
    else:
        suffixes = {
            ".breezy.hr":"breezy", ".pinpointhq.com":"pinpoint",
            ".bamboohr.com":"bamboohr", ".teamtailor.com":"teamtailor",
            ".jobs.personio.de":"personio", ".jobs.personio.com":"personio",
        }
        for suffix, candidate in suffixes.items():
            if host.endswith(suffix) and host.count(".")==suffix.count("."):
                provider, token = candidate, host[:-len(suffix)]
                if provider == "personio": extra["domain"] = host.rsplit(".",1)[-1]
                break
        if host.endswith(".myworkdayjobs.com"):
            provider, token = "workday", host.split(".",1)[0]
            site = next((x for x in parts if not x.lower().startswith(("en-","fr-","es-"))), "")
            extra = {"host": host, "site": site}
    if not provider or not token:
        raise ValueError("Unrecognized career-board URL: use an explicit configured RSS feed or JSON/CSV import")
    return validate_board({"provider":provider,"token":token,"company":company, **extra})
