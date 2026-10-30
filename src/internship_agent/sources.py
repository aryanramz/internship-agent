"""Read-only discovery adapters. No login bypass, browser scraping, or application submission.

Provider boards use fixed, vendor-published HTTPS endpoints. RSS and CSV input
are explicitly user-configured; platform alert emails can be normalized via CSV.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET
import csv
import json
import re
import os
import ipaddress

from .models import Job, now_iso, stable_id, validate_board
from .discovery_types import SourcePage

MAX_BYTES = 16_000_000
MAX_SOURCE_POSTINGS = 1_000_000
PUBLIC_BOARDS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "breezy", "personio", "pinpoint", "bamboohr", "teamtailor", "workday"}
AGGREGATORS = {"remotive", "jobicy", "simplify_github", "usajobs"}
LOCAL_IMPORTS = {"csv_import", "json_import"}
SUPPORTED = PUBLIC_BOARDS | AGGREGATORS | LOCAL_IMPORTS | {"rss"}
INTERNSHIP_TITLE = re.compile(r"\b(intern(ship)?|co[ -]?op|apprentice|summer analyst|summer associate)\b", re.I)


class SourceError(ValueError):
    """Safe, machine-readable discovery failure; never includes response content."""
    def __init__(self, code: str, message: str, *, http_status: int | None = None, retry_after: str = ""):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retry_after = retry_after


def _retry_after(value: str) -> str:
    if re.fullmatch(r"[0-9]+", value):
        digits = value.lstrip("0") or "0"
        # Restrictions beyond datetime's representable range remain conservative
        # without retaining an arbitrarily long untrusted header in diagnostics.
        return digits if len(digits) <= 12 else "253402300799"
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


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
    try:
        with opener.open(req, timeout=20) as response:
            body = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        retry_after = _retry_after(exc.headers.get("Retry-After", "")) if exc.headers else ""
        exc.close()
        if 300 <= status < 400:
            code, message = "redirect_blocked", "Source redirect refused; verify the configured public board"
        elif status == 404:
            code, message = "not_found", "Board or posting not found (HTTP 404); verify the board token or posting"
        elif status == 410:
            code, message = "gone", "Board or posting no longer available (HTTP 410)"
        elif status == 429:
            code, message = "rate_limited", "Source rate limited (HTTP 429); wait for Retry-After before another run"
        else:
            code, message = "http_error", f"Source request failed (HTTP {status})"
        raise SourceError(code, message, http_status=status, retry_after=retry_after) from None
    except (URLError, OSError):
        raise SourceError("network_error", "Source connection failed or timed out; no automatic retry") from None
    if len(body) > MAX_BYTES:
        raise SourceError("response_too_large", "Source response exceeds 16MB limit")
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


def _posting_url(value: object) -> str:
    """Validate linked ATS URLs without making a request to them."""
    try:
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError()
        _validate_feed_url(value)
        hostname = urlsplit(value).hostname or ""
        labels = hostname.split(".")
        if (len(labels) < 2 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", labels[-1])
                or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels)):
            raise ValueError()
    except ValueError:
        raise SourceError("invalid_posting", "ATS posting requires public HTTPS URLs without credentials") from None
    return value


def _ats_items(payload: object, *, array: bool = False) -> list[dict]:
    value = payload if array else payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SourceError("invalid_payload", "ATS response requires an array of posting objects")
    return value


def _ats_strings(item: dict, fields: tuple[str, ...]) -> None:
    if any(item.get(field) is not None and not isinstance(item[field], str) for field in fields):
        raise SourceError("invalid_posting", "ATS posting has invalid text fields")


def _ats_identity(item: dict, title_field: str, url_field: str, *, fallback_id: bool = False) -> tuple[str, str, str]:
    title = item.get(title_field)
    url = _posting_url(item.get(url_field))
    sid = item.get("id")
    if fallback_id and "id" not in item:
        # Preserve the existing Ashby identity when its optional ID is absent.
        sid = url.rsplit("/", 1)[-1]
    if (not isinstance(sid, str) or not sid.strip() or not isinstance(title, str) or not strip_html(title)):
        raise SourceError("invalid_posting", "ATS posting has an invalid ID or title")
    return sid, title, url


def _lever_jobs(board: dict, payload: object) -> list[Job]:
    jobs = []
    for item in _ats_items(payload, array=True):
        sid, title, url = _ats_identity(item, "text", "hostedUrl")
        _ats_strings(item, ("descriptionPlain", "description", "additionalPlain", "additional", "workplaceType"))
        apply_url = _posting_url(item["applyUrl"]) if item.get("applyUrl") is not None else url
        categories = item.get("categories")
        if categories is not None and not isinstance(categories, dict):
            raise SourceError("invalid_posting", "Lever posting has invalid categories")
        _ats_strings(categories or {}, ("location",))
        sections = item.get("lists", [])
        if not isinstance(sections, list) or any(not isinstance(section, dict) for section in sections):
            raise SourceError("invalid_posting", "Lever posting has invalid description sections")
        parts = [item.get("descriptionPlain") or item.get("description") or ""]
        for section in sections:
            _ats_strings(section, ("text", "content"))
            parts.extend((section.get("text") or "", section.get("content") or ""))
        parts.append(item.get("additionalPlain") or item.get("additional") or "")
        job = make_job(board, sid, title, url, apply_url=apply_url,
                       location=(categories or {}).get("location"), description=" ".join(parts),
                       work_mode=item.get("workplaceType"))
        # Lever's public field contract supplies no guaranteed publication date.
        if job:
            jobs.append(job)
    return jobs


def _ashby_jobs(board: dict, payload: object) -> list[Job]:
    jobs = []
    for item in _ats_items(payload):
        for field in ("isListed", "isRemote"):
            if field in item and not isinstance(item[field], bool):
                raise SourceError("invalid_posting", "Ashby posting has invalid boolean fields")
        if item.get("isListed") is False:
            continue
        sid, title, url = _ats_identity(item, "title", "jobUrl", fallback_id=True)
        _ats_strings(item, ("location", "descriptionPlain", "descriptionHtml", "publishedAt", "workplaceType"))
        apply_url = _posting_url(item["applyUrl"]) if item.get("applyUrl") is not None else url
        published = item.get("publishedAt")
        if published:
            try:
                if datetime.fromisoformat(published.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise SourceError("invalid_posting", "Ashby posting has an invalid publication timestamp") from None
        comp = item.get("compensation")
        if comp is not None and not isinstance(comp, dict):
            raise SourceError("invalid_posting", "Ashby posting has invalid compensation")
        _ats_strings(comp or {}, ("compensationTierSummary",))
        job = make_job(board, sid, title, url, apply_url=apply_url, location=item.get("location"),
                       description=item.get("descriptionPlain") or item.get("descriptionHtml"),
                       published=published, work_mode=item.get("workplaceType") or ("Remote" if item.get("isRemote") else "Unknown"),
                       compensation=(comp or {}).get("compensationTierSummary"))
        if job:
            jobs.append(job)
    return jobs


def _greenhouse_jobs(board: dict, payload: object, *, now: datetime | None = None) -> list[Job]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise SourceError("invalid_payload", "Greenhouse response requires a jobs array")
    jobs = []
    now = now or datetime.now(timezone.utc)
    for item in payload["jobs"]:
        if not isinstance(item, dict):
            raise SourceError("invalid_payload", "Greenhouse jobs array contains a non-object")
        sid = item.get("id")
        title, url = item.get("title"), item.get("absolute_url")
        content = item.get("content")
        published = item.get("first_published")
        if (isinstance(sid, bool) or not isinstance(sid, (str, int))
                or not re.fullmatch(r"[0-9]+", str(sid)) or int(sid) <= 0
                or not isinstance(title, str) or not strip_html(title)
                or not isinstance(url, str)
                or (content is not None and not isinstance(content, str))
                or (published is not None and not isinstance(published, str))):
            raise SourceError("invalid_posting", "Greenhouse posting has invalid ID, title, URL or content fields")
        _posting_url(url)
        deadline = item.get("application_deadline")
        if deadline is not None:
            try:
                expires = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    raise ValueError("Missing timezone")
            except (AttributeError, TypeError, ValueError):
                raise SourceError("invalid_posting", "Greenhouse posting has an invalid application deadline") from None
            if expires <= now:
                continue
        job = make_job(board, sid, title, url, location=_place(item.get("location")),
                       description=unescape(content or ""), published=published)
        if job:
            jobs.append(job)
    return jobs


def normalize(board: dict, payload: object, *, now: datetime | None = None) -> list[Job]:
    board = validate_board(board)
    provider, token = board["provider"], board["token"]
    jobs: list[Job] = []
    if provider == "greenhouse":
        jobs = _greenhouse_jobs(board, payload, now=now)
    elif provider == "lever":
        jobs = _lever_jobs(board, payload)
    elif provider == "ashby":
        jobs = _ashby_jobs(board, payload)
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
                items = _page_items(data, "jobPostings")
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
    try:
        payload, xml = _source_payload(board, config_root)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SourceError("invalid_payload", "Source response is not valid JSON") from None
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


def _page_items(payload: object, field: str) -> list[dict]:
    """Page evidence never treats a missing array or discarded objects as empty."""
    value = payload.get(field) if isinstance(payload, dict) else payload
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SourceError("invalid_payload", "Source response requires an array of posting objects")
    return value


def _smartrecruiters_page(board: dict, cursor: dict | None) -> SourcePage:
    offset = 0
    if cursor is not None:
        if (not isinstance(cursor, dict) or set(cursor) != {"offset", "total"}
                or type(cursor["offset"]) is not int or type(cursor["total"]) is not int
                or not 0 < cursor["offset"] < cursor["total"] <= MAX_SOURCE_POSTINGS):
            raise SourceError("invalid_cursor", "SmartRecruiters cursor requires bounded numeric offset and total")
        offset = cursor["offset"]
    data = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{board['token']}/postings?limit=100&offset={offset}")
    items = _page_items(data, "content")
    total = data.get("totalFound") if isinstance(data, dict) else None
    if type(total) is not int or not 0 <= total <= MAX_SOURCE_POSTINGS:
        raise SourceError("invalid_payload", "SmartRecruiters requires a bounded nonnegative integer total")
    if "offset" in data and (type(data["offset"]) is not int or data["offset"] != offset):
        raise SourceError("invalid_payload", "SmartRecruiters response offset does not match the requested page")
    if cursor is not None and total != cursor["total"]:
        raise SourceError("snapshot_changed", "SmartRecruiters total changed; restart the source scan")
    end = offset + len(items)
    if len(items) > 100 or end > total or (not items and end < total):
        raise SourceError("invalid_payload", "SmartRecruiters page counts are inconsistent")
    for item in items:
        sid = item.get("id") or item.get("uuid")
        title = item.get("name")
        if (isinstance(sid, bool) or not isinstance(sid, (str, int)) or not str(sid).strip()
                or not isinstance(title, str) or not strip_html(title)):
            raise SourceError("invalid_posting", "SmartRecruiters posting requires an ID and title")
        for key in ("postingUrl", "jobAdUrl"):
            if item.get(key):
                _posting_url(item[key])
        advertisement = item.get("jobAd")
        if advertisement is not None:
            if not isinstance(advertisement, dict):
                raise SourceError("invalid_posting", "SmartRecruiters posting has invalid description sections")
            sections = advertisement.get("sections", {})
            if not isinstance(sections, dict) or not isinstance(sections.get("jobDescription", {}), dict):
                raise SourceError("invalid_posting", "SmartRecruiters posting has invalid description sections")
    jobs = normalize(board, data)
    complete = end == total
    return SourcePage(jobs, next_cursor=None if complete else {"offset": end, "total": total},
                      complete=complete, raw_count=len(items), rejected_count=len(items) - len(jobs))


def retrieve_page(board: dict, config_root: str = ".", cursor: dict | None = None,
                  *, now: datetime | None = None) -> SourcePage:
    """Read one bounded page, preserving the distinction between coverage and jobs.

    Only the three validated unfiltered ATS snapshots supply absence evidence.
    Other public readers keep their existing request bounds and remain partial;
    their successful response alone cannot prove complete board coverage.
    """
    board = validate_board(board)
    provider = board["provider"]
    if provider != "smartrecruiters" and cursor is not None:
        raise SourceError("invalid_cursor", "This source does not support a resume cursor")
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Discovery time must include a timezone")
    observed_at = observed_at.astimezone(timezone.utc)
    try:
        if provider == "smartrecruiters":
            return _smartrecruiters_page(board, cursor)
        data, xml = _source_payload(board, config_root)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SourceError("invalid_payload", "Source response is not valid JSON") from None

    if xml is not None:
        try:
            root = ET.fromstring(xml)
            if provider == "personio":
                if root.tag != "workzag-jobs":
                    raise ValueError()
                count = len(root.findall(".//position"))
            elif root.tag == "rss" and root.find("channel") is not None:
                count = len(root.findall(".//item"))
            elif root.tag == "{http://www.w3.org/2005/Atom}feed":
                count = len(root.findall(".//{http://www.w3.org/2005/Atom}entry"))
            else:
                raise ValueError()
            jobs = normalize_xml(board, xml)
        except (ET.ParseError, ValueError):
            raise SourceError("invalid_payload", "Source response is not a supported XML feed") from None
        return SourcePage(jobs, complete=False, raw_count=count, rejected_count=count - len(jobs))

    fields = {"greenhouse": "jobs", "lever": "jobs", "ashby": "jobs", "workable": "jobs",
              "breezy": "jobs", "pinpoint": "data", "bamboohr": "result", "workday": "jobPostings",
              "remotive": "jobs", "jobicy": "jobs", "simplify_github": "listings",
              "csv_import": "jobs", "json_import": "jobs"}
    if provider == "usajobs":
        result = data.get("SearchResult") if isinstance(data, dict) else None
        items = _page_items(result, "SearchResultItems")
    else:
        items = _page_items(data, fields[provider])
    # Validate the whole snapshot before emitting any job or closure evidence.
    jobs = normalize(board, data, now=observed_at)
    closed = []
    if provider == "greenhouse":
        for item in items:
            deadline = item.get("application_deadline")
            if deadline is not None:
                expires = datetime.fromisoformat(deadline.replace("Z", "+00:00")).astimezone(timezone.utc)
                if expires <= observed_at:
                    closed.append({"job_id": stable_id(provider, board["token"], str(item["id"])),
                                   "deadline": expires.isoformat()})
    validated_ats = provider in {"greenhouse", "lever", "ashby"}
    return SourcePage(jobs, complete=validated_ats or provider in LOCAL_IMPORTS,
                      authoritative=validated_ats and not board.get("intern_only", False),
                      raw_count=len(items), rejected_count=len(items) - len(jobs), closed=tuple(closed))
