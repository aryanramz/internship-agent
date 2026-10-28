"""Read-only discovery adapters. No login bypass, browser scraping, or application submission.

Provider boards use fixed, vendor-published HTTPS endpoints. RSS and CSV input
are explicitly user-configured; platform alert emails can be normalized via CSV.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET
import csv
import json
import re
import os
import ipaddress

from .models import Job, now_iso, stable_id, validate_board

MAX_BYTES = 16_000_000
PUBLIC_BOARDS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "breezy", "personio", "pinpoint", "bamboohr", "teamtailor", "workday"}
AGGREGATORS = {"remotive", "jobicy", "simplify_github", "usajobs"}
LOCAL_IMPORTS = {"csv_import", "json_import"}
SUPPORTED = PUBLIC_BOARDS | AGGREGATORS | LOCAL_IMPORTS | {"rss"}
INTERNSHIP_TITLE = re.compile(r"\b(intern(ship)?|co[ -]?op|apprentice|summer analyst|summer associate)\b", re.I)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if not self.skip and tag in ("p", "br", "li", "div"):
            self.parts.append(" ")
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if not self.skip and tag in ("p", "br", "li", "div"):
            self.parts.append(" ")
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def strip_html(value: object) -> str:
    parser = _Text()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())


class _NoRedirect(HTTPRedirectHandler):
    """Refuse automatic cross-host redirects (prevents RSS redirect-to-intranet SSRF)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_feed_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Feeds must use public HTTPS URLs without credentials")
    if parsed.port not in (None, 443):
        raise ValueError("Nonstandard HTTPS ports are not allowed")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private feed host not permitted")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return
    raise ValueError("IP-literal feed hosts are not allowed")


def get_bytes(url: str, headers: dict | None = None, post_json: dict | None = None) -> bytes:
    """Read public HTTPS endpoints with bounded response and redirects disabled.

    The system does not accept arbitrary URLs from a job description. This
    defense-in-depth check also protects deliberately configured RSS feeds.
    """
    _validate_feed_url(url)
    req_headers = {"User-Agent": "InternshipAgent/0.4 (personal job discovery)", "Accept": "application/json, application/xml, text/xml, application/rss+xml, */*"}
    req_headers.update(headers or {})
    data = json.dumps(post_json).encode("utf-8") if post_json is not None else None
    if data is not None:
        req_headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=req_headers)
    opener = build_opener(_NoRedirect())
    with opener.open(req, timeout=20) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Source response exceeds 16MB limit")
    return body


def fetch_json(url: str) -> object:
    return json.loads(get_bytes(url))


def text(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("label") or value.get("value") or "")
    if isinstance(value, list):
        return ", ".join(filter(None, (text(v) for v in value)))
    return str(value or "")


def published_date(value: object) -> str:
    if isinstance(value, (float, int)) and value > 1_000_000_000:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return str(value or "")


def make_job(board: dict, sid: object, title: object, url: object, *, company: str = "", location: object = "",
             description: object = "", apply_url: object = "", published: object = "", work_mode: object = "Unknown",
             compensation: object = "", provider: str = "") -> Job | None:
    source = provider or board["provider"]
    sid, title, url = text(sid).strip(), strip_html(title), text(url).strip()
    if not sid or not title or not url.startswith("https://"):
        return None
    application = text(apply_url).strip()
    if not application.startswith("https://"):
        application = url
    return Job(id=stable_id(source, board["token"], sid), provider=source, company=company or board["company"],
               source_id=sid, title=title, location=text(location), description=strip_html(description),
               job_url=url, apply_url=application, work_mode=text(work_mode) or "Unknown",
               published_at=published_date(published), compensation=text(compensation), discovered_at=now_iso())


def _items(payload: object, field: str) -> list[dict]:
    value = payload.get(field, []) if isinstance(payload, dict) else payload
    if not isinstance(value, list):
        raise ValueError(f"Expected a list under {field}")
    return [i for i in value if isinstance(i, dict)]


def _place(place: object) -> str:
    if isinstance(place, dict):
        return text(place.get("name") or ", ".join(filter(None, [text(place.get("city")), text(place.get("region") or place.get("state")), text(place.get("country"))])))
    return text(place)


def normalize(board: dict, payload: object) -> list[Job]:
    board = validate_board(board)
    provider, token = board["provider"], board["token"]
    jobs: list[Job] = []
    if provider == "greenhouse":
        for i in _items(payload, "jobs"):
            j = make_job(board, i.get("id"), i.get("title"), i.get("absolute_url"), location=_place(i.get("location")), description=i.get("content"))
            if j: jobs.append(j)
    elif provider == "lever":
        for i in _items(payload, "jobs"):
            desc = i.get("descriptionPlain") or i.get("description") or ""
            for sec in i.get("lists", []):
                if isinstance(sec, dict): desc += " " + text(sec.get("content"))
            j = make_job(board, i.get("id"), i.get("text"), i.get("hostedUrl"),
                         apply_url=i.get("applyUrl"), location=_place((i.get("categories") or {}).get("location")),
                         description=desc, work_mode=i.get("workplaceType"))
            if j: jobs.append(j)
    elif provider == "ashby":
        for i in _items(payload, "jobs"):
            if i.get("isListed") is False: continue
            url = i.get("jobUrl", "")
            comp = i.get("compensation") or {}
            j = make_job(board, i.get("id") or url.rsplit("/", 1)[-1], i.get("title"), url,
                         location=i.get("location"), description=i.get("descriptionPlain") or i.get("descriptionHtml"),
                         apply_url=i.get("applyUrl"), published=i.get("publishedAt"),
                         work_mode=i.get("workplaceType") or ("Remote" if i.get("isRemote") else "Unknown"),
                         compensation=comp.get("compensationTierSummary") if isinstance(comp, dict) else "")
            if j: jobs.append(j)
    elif provider == "smartrecruiters":
        for i in _items(payload, "content"):
            loc = i.get("location") or {}
            sid = i.get("id") or i.get("uuid")
            j = make_job(board, sid, i.get("name"), i.get("postingUrl") or i.get("jobAdUrl") or f"https://jobs.smartrecruiters.com/{token}/{sid}",
                         location=_place(loc), published=i.get("releasedDate"),
                         work_mode="Remote" if isinstance(loc, dict) and loc.get("remote") else "Unknown",
                         description=i.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", "") if isinstance(i.get("jobAd"), dict) else "")
            if j: jobs.append(j)
    elif provider == "workable":
        seen = set()
        for i in _items(payload, "jobs"):
            sid = i.get("shortcode") or i.get("code")
            if sid in seen: continue  # Multiple locations for one requisition
            seen.add(sid)
            j = make_job(board, sid, i.get("title"), i.get("url") or f"https://apply.workable.com/{token}/j/{sid}/",
                         apply_url=i.get("application_url"), location=", ".join(filter(None, [text(i.get("city")), text(i.get("state"))])) or text(i.get("country")),
                         description=i.get("description"), published=i.get("published_on"), work_mode="Remote" if i.get("telecommuting") else "Unknown")
            if j: jobs.append(j)
    elif provider == "breezy":
        for i in _items(payload, "jobs"):
            sid = i.get("id") or i.get("friendly_id")
            loc = i.get("location") or {}
            j = make_job(board, sid, i.get("name"), i.get("url") or f"https://{token}.breezy.hr/p/{i.get('friendly_id', sid)}",
                         location=_place(loc), published=i.get("published_date"), compensation=i.get("salary"),
                         work_mode="Remote" if isinstance(loc, dict) and loc.get("is_remote") else "Unknown")
            if j: jobs.append(j)
    elif provider == "pinpoint":
        for i in _items(payload, "data"):
            j = make_job(board, i.get("id"), i.get("title"), i.get("url") or f"https://{token}.pinpointhq.com{i.get('path', '')}",
                         location=_place(i.get("location")),
                         description=" ".join(text(i.get(x)) for x in ("description", "key_responsibilities", "skills_knowledge_expertise")),
                         compensation=i.get("compensation") if i.get("compensation_visible") else "")
            if j: jobs.append(j)
    elif provider == "bamboohr":
        for i in _items(payload, "result"):
            sid = i.get("id") or i.get("jobId")
            j = make_job(board, sid, i.get("jobOpeningName") or i.get("title"), f"https://{token}.bamboohr.com/careers/{sid}",
                         location=_place(i.get("location")))
            if j: jobs.append(j)
    elif provider == "workday":
        for i in _items(payload, "jobPostings"):
            path = str(i.get("externalPath") or "")
            if not path.startswith("/"): continue
            site = board["site"]
            host = board["host"]
            job_url = f"https://{host}/en-US/{site}{path}"
            j = make_job(board, path, i.get("title"), job_url,
                         location=i.get("locationsText"), published=i.get("postedOn"),
                         description=i.get("jobDescription") or text(i.get("bulletFields")))
            if j: jobs.append(j)
    elif provider == "usajobs":
        result = payload.get("SearchResult", {}) if isinstance(payload, dict) else {}
        for record in _items(result, "SearchResultItems"):
            i = record.get("MatchedObjectDescriptor") or {}
            locations = i.get("PositionLocation") or []
            detail = i.get("UserArea", {}).get("Details", {}) if isinstance(i.get("UserArea"), dict) else {}
            uri = i.get("PositionURI")
            apply_urls = i.get("ApplyURI") or []
            j = make_job(board, i.get("PositionID") or uri, i.get("PositionTitle"), uri,
                         company=text(i.get("OrganizationName") or i.get("DepartmentName")),
                         location=", ".join(text(x.get("LocationName")) for x in locations if isinstance(x, dict)),
                         description=detail.get("JobSummary", ""), apply_url=apply_urls[0] if apply_urls else uri,
                         published=i.get("PublicationStartDate"))
            if j: jobs.append(j)
    elif provider == "remotive":
        for i in _items(payload, "jobs"):
            j = make_job(board, i.get("id"), i.get("title"), i.get("url"), company=text(i.get("company_name")),
                         location=i.get("candidate_required_location") or "Remote", description=i.get("description"),
                         published=i.get("publication_date"), work_mode="Remote", compensation=i.get("salary"))
            if j: jobs.append(j)
    elif provider == "jobicy":
        for i in _items(payload, "jobs"):
            j = make_job(board, i.get("id"), i.get("jobTitle"), i.get("url"), company=text(i.get("companyName")),
                         location=i.get("jobGeo") or "Remote", description=i.get("jobDescription"),
                         published=i.get("pubDate"), work_mode="Remote", compensation=i.get("annualSalaryMin") and f"{i.get('annualSalaryMin')}-{i.get('annualSalaryMax', '')}")
            if j: jobs.append(j)
    elif provider == "simplify_github":
        items = _items(payload, "listings")
        for i in items:
            if i.get("active") is False or i.get("is_visible") is False: continue
            url = i.get("url") or ""
            j = make_job(board, i.get("id") or url, i.get("title"), url,
                         company=text(i.get("company_name")), location=i.get("locations"),
                         description="Terms: " + text(i.get("terms")), published=i.get("date_posted"))
            if j: jobs.append(j)
    elif provider in LOCAL_IMPORTS:
        for i in _items(payload, "jobs"):
            url = i.get("job_url") or i.get("url") or i.get("link")
            source = re.sub(r"[^a-z0-9_-]+", "_", text(i.get("platform") or i.get("source") or "manual").lower()).strip("_")
            source = source[:40] or "other"
            j = make_job(board, i.get("id") or url, i.get("title"), url, provider=source,
                         company=text(i.get("company")) or board["company"], location=i.get("location"),
                         description=i.get("description"), published=i.get("published_at"),
                         work_mode=i.get("work_mode"), apply_url=i.get("apply_url"), compensation=i.get("compensation"))
            if j: jobs.append(j)
    else:
        raise ValueError(f"Provider {provider} requires an XML reader")
    # Aggregators are broad: only store plausible internship postings by default.
    if board.get("intern_only", provider in AGGREGATORS):
        jobs = [j for j in jobs if INTERNSHIP_TITLE.search(j.title)]
    return jobs


def normalize_xml(board: dict, raw: bytes) -> list[Job]:
    board = validate_board(board)
    root = ET.fromstring(raw)
    provider, token = board["provider"], board["token"]
    jobs = []
    if provider == "personio":
        for item in root.findall(".//position"):
            sid = item.findtext("id", "")
            descr = " ".join((e.findtext("value", "") or "") for e in item.findall(".//jobDescriptions/jobDescription"))
            url = f"https://{token}.jobs.personio.{board.get('domain','de')}/job/{sid}"
            j = make_job(board, sid, item.findtext("name", ""), url,
                         location=item.findtext("office", ""), description=descr)
            if j: jobs.append(j)
    elif provider in {"rss", "teamtailor"}:
        # RSS 2.0 and Atom support. RSS field names are not universal.
        items = root.findall(".//item")
        atom = False
        if not items:
            atom = True
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items:
            if atom:
                ns = "{http://www.w3.org/2005/Atom}"
                title = item.findtext(ns + "title", "")
                link = next((e.attrib.get("href", "") for e in item.findall(ns + "link") if e.attrib.get("href")), "")
                desc = item.findtext(ns + "content", "") or item.findtext(ns + "summary", "")
                sid = item.findtext(ns + "id", "") or link
                date = item.findtext(ns + "published", "") or item.findtext(ns + "updated", "")
            else:
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                desc = item.findtext("description", "") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", "")
                sid = item.findtext("guid", "") or link
                date = item.findtext("pubDate", "")
            j = make_job(board, sid, title, link, description=desc, published=date)
            if j: jobs.append(j)
    else:
        raise ValueError("Unsupported XML source")
    if board.get("intern_only", False):
        jobs = [j for j in jobs if INTERNSHIP_TITLE.search(j.title)]
    return jobs


def _source_payload(board: dict, config_root: str) -> tuple[object, bytes | None]:
    provider, token = board["provider"], board["token"]
    if provider in LOCAL_IMPORTS:
        raw_path = Path(board["path"])
        path = raw_path if raw_path.is_absolute() else Path(config_root) / raw_path
        if not path.is_file(): raise FileNotFoundError(f"Import not found: {path}")
        if path.stat().st_size > MAX_BYTES: raise ValueError("Import file too large")
        if provider == "csv_import":
            with path.open(encoding="utf-8-sig", newline="") as f:
                return {"jobs": list(csv.DictReader(f))}, None
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
            return {"jobs": data} if isinstance(data, list) else data, None
    if provider == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    elif provider == "lever":
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    elif provider == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
    elif provider == "smartrecruiters":
        # Caller handles pagination in retrieve_board.
        url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset=0"
    elif provider == "workable":
        url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    elif provider == "breezy":
        url = f"https://{token}.breezy.hr/json"
    elif provider == "pinpoint":
        url = f"https://{token}.pinpointhq.com/postings.json"
    elif provider == "personio":
        url = f"https://{token}.jobs.personio.{board.get('domain','de')}/xml?language=en"
    elif provider == "bamboohr":
        url = f"https://{token}.bamboohr.com/careers/list"
    elif provider == "teamtailor":
        url = f"https://{token}.teamtailor.com/jobs.rss"
    elif provider == "workday":
        for i in _items(payload, "jobPostings"):
            path = str(i.get("externalPath") or "")
            if not path.startswith("/"): continue
            site = board["site"]
            host = board["host"]
            job_url = f"https://{host}/en-US/{site}{path}"
            j = make_job(board, path, i.get("title"), job_url,
                         location=i.get("locationsText"), published=i.get("postedOn"),
                         description=i.get("jobDescription") or text(i.get("bulletFields")))
            if j: jobs.append(j)
    elif provider == "usajobs":
        result = payload.get("SearchResult", {}) if isinstance(payload, dict) else {}
        for record in _items(result, "SearchResultItems"):
            i = record.get("MatchedObjectDescriptor") or {}
            locations = i.get("PositionLocation") or []
            detail = i.get("UserArea", {}).get("Details", {}) if isinstance(i.get("UserArea"), dict) else {}
            uri = i.get("PositionURI")
            apply_urls = i.get("ApplyURI") or []
            j = make_job(board, i.get("PositionID") or uri, i.get("PositionTitle"), uri,
                         company=text(i.get("OrganizationName") or i.get("DepartmentName")),
                         location=", ".join(text(x.get("LocationName")) for x in locations if isinstance(x, dict)),
                         description=detail.get("JobSummary", ""), apply_url=apply_urls[0] if apply_urls else uri,
                         published=i.get("PublicationStartDate"))
            if j: jobs.append(j)
    elif provider == "usajobs":
        from urllib.parse import urlencode
        key, email = os.environ.get("USAJOBS_API_KEY"), os.environ.get("USAJOBS_EMAIL")
        if not key or not email:
            raise ValueError("USAJOBS_API_KEY and USAJOBS_EMAIL environment variables are required")
        url = "https://data.usajobs.gov/api/search?" + urlencode({"Keyword":board.get("keyword") or "internship", "ResultsPerPage":100})
        return json.loads(get_bytes(url, {"Authorization-Key":key, "User-Agent":email})), None
    elif provider == "workday":
        # Limited public careers search: fixed host, tenant and site; no login needed.
        host, site = board["host"], board["site"]
        url = f"https://{host}/wday/cxs/{token}/{site}/jobs"
        combined = []
        seen = set()
        for term in board.get("search_terms", ["intern", "summer", "co-op"]):
            for page in range(3):
                data = json.loads(get_bytes(url, post_json={"appliedFacets": {}, "limit":20, "offset":page*20, "searchText":term}))
                items = _items(data, "jobPostings")
                for item in items:
                    path = item.get("externalPath")
                    if path and path not in seen:
                        seen.add(path)
                        combined.append(item)
                if len(items) < 20: break
        return {"jobPostings": combined}, None
    elif provider == "remotive":
        url = "https://remotive.com/api/remote-jobs?limit=500"
    elif provider == "jobicy":
        url = "https://jobicy.com/api/jobs?count=200"
    elif provider == "simplify_github":
        url = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
    elif provider == "rss":
        url = board["feed_url"]
    else:
        raise ValueError(f"Unsupported provider {provider}")
    raw = get_bytes(url)
    if provider in {"personio", "teamtailor", "rss"}:
        return {}, raw
    return json.loads(raw), None


def retrieve_board(board: dict, config_root: str = ".") -> list[Job]:
    board = validate_board(board)
    payload, xml = _source_payload(board, config_root)
    provider = board["provider"]
    if xml is not None:
        return normalize_xml(board, xml)
    if provider == "smartrecruiters":
        items = _items(payload, "content")
        total = payload.get("totalFound", len(items)) if isinstance(payload, dict) else len(items)
        for page in range(1, min(5, (int(total) + 99) // 100)):
            data = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{board['token']}/postings?limit=100&offset={page*100}")
            items.extend(_items(data, "content"))
        payload = {"content": items}
    return normalize(board, payload)
