"""Conservatively stage Gmail job-alert links for human verification.

Never follow tracking URLs, infer an employer, or silently apply to any job.
"""
from __future__ import annotations
import base64
import hashlib
from html.parser import HTMLParser
import re
from email.utils import parseaddr
from urllib.parse import urlsplit
from ..models import canonical_url, now_iso

DEFAULT_QUERY = '(from:(linkedin.com) OR from:(indeed.com) OR from:(joinhandshake.com) OR from:(handshake.com) OR from:(ziprecruiter.com) OR from:(simplify.jobs) OR from:(ripplematch.com) OR from:(wayup.com) OR from:(wellfound.com) OR from:(builtin.com) OR from:(ycombinator.com) OR from:(untapped.io) OR from:(jobright.ai)) newer_than:30d'
PROVIDER_DOMAINS = {
    "linkedin": ("linkedin.com",), "indeed": ("indeed.com",),
    "handshake": ("joinhandshake.com", "handshake.com"),
    "ziprecruiter": ("ziprecruiter.com",),
    "simplify": ("simplify.jobs",), "ripplematch": ("ripplematch.com",),
    "wayup": ("wayup.com",), "wellfound": ("wellfound.com",),
    "builtin": ("builtin.com",), "ycombinator": ("ycombinator.com",),
    "untapped": ("untapped.io",), "jobright": ("jobright.ai",),
}
JOB_WORDS = re.compile(r"\b(intern(ship)?|co[- ]?op|summer\s+20\d\d|student\s+trainee)\b", re.I)
JOBS_LINK = re.compile(r"/(job[s]?|careers?|positions?|posting[s]?|vacanc(?:y|ies)|internships?)(/|$)", re.I)
BLOCK_WORDS = re.compile(r"unsubscribe|preferences?|privacy|terms|manage.alert|settings|sign.in|log.in|view.all|browse.all|download.app|\bapply now\b|notification", re.I)

class Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False; self.href = ""; self.words = []; self.found = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.inside = True
            self.href = dict(attrs).get("href", "")
            self.words = []
    def handle_data(self, data):
        if self.inside:
            self.words.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.inside:
            self.found.append((self.href, " ".join(" ".join(self.words).split())))
            self.inside = False

def decode_part(part: dict) -> str:
    raw = part.get("body", {}).get("data", "")
    if not raw:
        return ""
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return ""

def message_bodies(payload: dict) -> list[tuple[str, str]]:
    out = []
    def walk(p):
        mime = p.get("mimeType", "")
        if mime in ("text/html", "text/plain"):
            out.append((mime, decode_part(p)))
        for child in p.get("parts", []):
            walk(child)
    walk(payload)
    return out

def _platform(sender: str) -> str:
    domain = parseaddr(sender)[1].rsplit("@", 1)[-1].lower()
    for platform, options in PROVIDER_DOMAINS.items():
        if any(domain == x or domain.endswith("." + x) for x in options):
            return platform
    return "other"

def _is_job_link(url: str, title: str) -> bool:
    if not isinstance(url, str) or len(url)>3000 or len(url)<12 or not url.startswith("https://"):
        return False
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.username or parsed.password or not host or host in ("localhost",) or host.endswith((".local", ".internal")):
        return False
    # Do not ingest redirectors or tracking links; preserve a direct source URL.
    if BLOCK_WORDS.search(title) or BLOCK_WORDS.search(parsed.path):
        return False
    path = parsed.path.lower()
    known = (
        host.endswith("greenhouse.io") or host.endswith("lever.co") or
        host.endswith("ashbyhq.com") or host.endswith("myworkdayjobs.com") or
        (host.endswith("linkedin.com") and path.startswith("/jobs/view/")) or
        (host.endswith("indeed.com") and path.startswith("/viewjob")) or
        (host.endswith("joinhandshake.com") and ("/postings/" in path or "/stu/jobs/" in path)) or
        (host.endswith("simplify.jobs") and "/p/" in path) or
        (host.endswith("ziprecruiter.com") and "/jobs/" in path) or
        (host.endswith("wellfound.com") and "/jobs/" in path) or
        (host.endswith("ripplematch.com") and "/job/" in path)
    )
    return bool(known or (JOBS_LINK.search(path) and JOB_WORDS.search(title)))

def extract_leads(message: dict) -> list[dict]:
    payload = message.get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
    sender = headers.get("from", "")
    subject = headers.get("subject", "")
    platform = _platform(sender)
    mid = str(message.get("id", ""))
    if not mid or platform == "other":
        return []
    anchors = []
    for mime, body in message_bodies(payload):
        if mime == "text/html":
            parser = Anchors(); parser.feed(body[:500000]); anchors.extend(parser.found[:150])
        else:
            for url in re.findall(r"https://[^\s<>\]\)]+", body[:100000])[:150]:
                anchors.append((url.rstrip(".,;"), ""))
    leads=[]; seen=set()
    for url,title in anchors:
        if not _is_job_link(url, title):
            continue
        canonical = canonical_url(url)
        if canonical in seen: continue
        seen.add(canonical)
        lid=hashlib.sha256(f"{mid}|{canonical}".encode()).hexdigest()[:24]
        leads.append({"id":lid,"message_id":mid,"platform":platform,"sender":sender[:300],
            "subject":subject[:300],"title_hint":title[:250],"job_url":url[:3000],"created_at":now_iso()})
    return leads[:40]

def ingest_gmail(store, gateway, query: str = DEFAULT_QUERY, limit: int = 30) -> dict:
    """Fetch at most 100 matching messages; store metadata and possible job URLs only."""
    if not isinstance(query,str) or len(query)>500:
        raise ValueError("Gmail query must be <=500 characters")
    messages=gateway.list_messages(query, min(100,max(1,limit)))
    counts={"messages_found":len(messages),"messages_read":0,"leads_added":0,"leads_existing":0,"errors":[]}
    for msg in messages:
        mid=str(msg.get("id",""))
        if not mid:
            continue
        try:
            data=gateway.get_message(mid)
            counts["messages_read"]+=1
            for lead in extract_leads(data):
                counts["leads_added" if store.add_email_lead(lead) else "leads_existing"]+=1
        except Exception as exc:
            counts["errors"].append({"message_id":mid,"error":str(exc)[:140]})
    return counts
