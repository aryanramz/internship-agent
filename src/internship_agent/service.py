from __future__ import annotations
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from .sources import retrieve_page, normalize, SUPPORTED, AGGREGATORS, SourceError
from .scoring import evaluate
from .documents import create_documents,tailoring_report
from .store import Store
from .models import validate_board
from .registry import board_identity, load_registry, read_configuration, registry_entry, register_sources


def discovery_source_id(board, config_root="."):
    """Opaque source namespace binds checkpoints to reader identity and filters."""
    clean = validate_board(board)
    filters = {"intern_only": clean.get("intern_only", clean["provider"] in AGGREGATORS)}
    if clean["provider"] == "workday":
        filters["search_terms"] = clean["search_terms"]
    if clean["provider"] == "usajobs":
        filters["keyword"] = clean["keyword"]
    if clean["provider"] in {"csv_import", "json_import"}:
        filters["resolved_path"] = str((Path(config_root) / clean["path"]).resolve())
    value = json.dumps([board_identity(clean), filters], sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()[:24]


class Agent:
    def __init__(self, root: str, *, credentials_dir: str | None = None, read_only: bool = False, clock=None):
        from .integrations.google_auth import credential_directory
        self._credentials_override=credentials_dir
        self.credentials_dir=credential_directory(credentials_dir)
        self.root=Path(root).resolve()
        if not read_only:
            self.root.mkdir(parents=True,exist_ok=True)
        self.store=Store(str(self.root/"agent.db"),read_only=read_only)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.legacy_credential_dirs=(self.root/"secrets",Path("data/secrets").resolve())

    def load_profile(self, profile_path: str) -> dict:
        with open(profile_path, encoding="utf-8") as f:
            value=json.load(f)
        if not isinstance(value,dict):raise ValueError("Profile must be JSON object")
        return value

    def discover(self, sources_path: str, *, refresh=False, max_pages=3, max_sources=20) -> dict:
        from .discovery_state import DiscoveryState
        if type(max_pages) is not int or not 1 <= max_pages <= 5 or type(max_sources) is not int or not 1 <= max_sources <= 100:
            raise ValueError("Discovery requires 1–5 pages and 1–100 sources per invocation")
        if type(refresh) is not bool:
            raise ValueError("Refresh must be boolean")
        source=read_configuration(sources_path)
        state = DiscoveryState(self.store, clock=self.clock)
        summary={"added":0,"updated":0,"duplicate":0,"errors":[],"by_source":[],"skipped":[]}
        config_root = str(Path(sources_path).resolve().parent.parent)
        seen=set()
        attempted = 0
        for entry in source.get("boards",[]):
            run = None
            try:
                entry=registry_entry(entry)
                if not entry["enabled"]:
                    continue
                identity=board_identity(entry)
                if identity in seen:
                    raise ValueError("Duplicate configured board; discovery skipped this entry")
                seen.add(identity)
                source_id = discovery_source_id(entry, config_root)
                if attempted >= max_sources:
                    summary["skipped"].append({"source_id": source_id, "skip_reason": "work_budget"})
                    continue
                run = state.begin(source_id, entry["provider"], self.clock(), refresh=refresh)
                if run.get("skip_reason"):
                    summary["skipped"].append(run)
                    continue
                attempted += 1
                counts={"provider":entry["provider"],"company":entry["company"],"source_id":source_id,
                        "run_id":run["run_id"],"retrieved":0,"added":0,"updated":0,"duplicate":0}
                cursor = run.get("cursor")
                for _ in range(max_pages):
                    page = retrieve_page(entry, config_root, cursor, now=self.clock())
                    outcomes = state.commit_page(run["run_id"], page, self.clock())
                    if counts not in summary["by_source"]:
                        summary["by_source"].append(counts)
                    counts["retrieved"] += len(page.jobs)
                    for outcome in ("added", "updated", "duplicate"):
                        counts[outcome] += outcomes[outcome]
                        summary[outcome] += outcomes[outcome]
                    counts["complete"] = page.complete
                    cursor = page.next_cursor
                    if cursor is None:
                        if not page.complete:
                            state.pause(run["run_id"], self.clock())
                        break
                else:
                    if cursor is not None:
                        state.pause(run["run_id"], self.clock())
            except Exception as exc:
                code = exc.code if isinstance(exc, SourceError) else "invalid_configuration" if isinstance(exc, ValueError) else "internal_error"
                if not isinstance(code, str) or not re.fullmatch(r"[a-z_]{1,40}", code):
                    code = "source_error"
                error={"board":entry.get("company","unknown") if isinstance(entry,dict) else "unknown",
                       "error":"Discovery failed; review source-health and local source configuration.", "code":code}
                if isinstance(exc, SourceError):
                    if exc.http_status is not None:
                        error["http_status"]=exc.http_status
                    if exc.retry_after:
                        error["retry_after"]=exc.retry_after
                if run is not None and run.get("run_id"):
                    try:
                        state.fail(run["run_id"], code, self.clock(), retry_after=error.get("retry_after", ""),
                                   http_status=error.get("http_status"))
                    except ValueError:
                        error["state_error"] = "lease_lost"
                summary["errors"].append(error)
        return summary



    def suggest_sources(self, sources_path: str, limit: int = 100, apply: bool = False) -> dict:
        """Discover employer boards from previously ingested public job URLs.

        Suggestions are never fetched. --apply explicitly registers at most `limit`
        employer boards for the *next* discovery run.
        """
        from .source_detection import detect_source
        sources_file=Path(sources_path)
        config=load_registry(sources_file,missing_ok=True)
        configured={board_identity(i) for i in config["boards"]}
        discovered={}
        inspected = self.store.list_jobs(1000)
        for record in inspected:
            try:
                board=registry_entry(detect_source(record["job_url"],record["company"]))
                board["provenance"]={"method":"suggested","url":board["board_url"]}
            except ValueError:
                continue
            key=board_identity(board)
            if key not in configured:
                discovered[key]=board
        suggestions=list(discovered.values())[:max(0,min(500,limit))]
        if apply and suggestions:
            register_sources(sources_file,suggestions)
        return {"available":len(discovered),"shown":len(suggestions),"registered":len(suggestions) if apply else 0,
                "inspected":len(inspected),"inspection_limit":1000,
                "sources":suggestions,"note":"Suggestions cover at most 1000 recent ingested jobs; registration does not fetch postings."}

    def import_external_jobs(self, records: list[dict]) -> dict:
        """Ingest real leads extracted through an authorized ChatGPT connector or exported file.

        Does not verify availability, browse protected platforms, or submit forms.
        """
        if not isinstance(records, list) or len(records) > 100:
            raise ValueError("Pass at most 100 structured job records")
        board={"provider":"json_import","company":"External job leads","token":"chat-import","path":"connector-data"}
        clean=[]
        for row in records:
            if not isinstance(row,dict): continue
            fields={key:row.get(key) for key in ("platform","source","company","title","location","job_url","url","link","apply_url","description","published_at","compensation","work_mode","id")}
            if len(str(fields.get("description") or ""))>20000:
                fields["description"]=str(fields["description"])[:20000]
            clean.append(fields)
        imported=normalize(board,{"jobs":clean})
        result={"input":len(records),"valid":len(imported),"added":0,"updated":0,"duplicate":0,
                "warning":"External leads are not verified; inspect employer posting before preparing or applying"}
        for job in imported:
            result[self.store.upsert_job(job)]+=1
        return result

    def _eligibility_profile(self, profile_path):
        """Bounded private input; duplicate fields cannot silently change a fact."""
        from .eligibility_profile import MAX_PROFILE_BYTES, normalize_profile
        def unique(pairs):
            out = {}
            for key,value in pairs:
                if key in out:
                    raise ValueError("Invalid eligibility profile")
                out[key] = value
            return out
        try:
            with open(profile_path,"rb") as stream:
                raw = stream.read(MAX_PROFILE_BYTES+1)
            if len(raw) > MAX_PROFILE_BYTES:
                raise ValueError()
            profile = json.loads(raw,object_pairs_hook=unique)
            if not isinstance(profile,dict):
                raise ValueError()
            for field in ("target_roles","skills","preferred_locations","preferred_employers"):
                values = profile.get(field,[])
                if not isinstance(values,list) or any(not isinstance(value,str) for value in values):
                    raise ValueError()
            normalize_profile(profile)
            return profile
        except (ValueError,UnicodeError,RecursionError):
            raise ValueError("Invalid eligibility profile") from None

    def eligibility(self, jid: str, profile_path: str) -> dict:
        """Local evidence report only; never changes applications or calls Google."""
        from .eligibility import evaluate_eligibility
        job = self.store.get_job(jid)
        profile = self._eligibility_profile(profile_path)
        assessment = evaluate_eligibility(profile,job,as_of=self.clock().date())
        fit = evaluate(job,profile)
        return {"job_id":jid,"company":job["company"],"title":job["title"],
                "fit_score":fit["score"],"fit_components":fit["components"],**assessment}

    def ranked(self, profile_path: str, limit: int=25, min_score: int=0, *, include_eligibility=False) -> list[dict]:
        if type(include_eligibility) is not bool:
            raise ValueError("Eligibility projection must be boolean")
        profile=self._eligibility_profile(profile_path) if include_eligibility else self.load_profile(profile_path)
        result=[]
        jobs = self.store.list_jobs(10000)
        for job in jobs:
            report=evaluate(job,profile)
            if report["score"]>=min_score:
                result.append({"job_id":job["id"],"company":job["company"],"title":job["title"],"location":job["location"],
                               "job_url":job["job_url"],"apply_url":job["apply_url"],"status":job["status"],**report})
        result.sort(key=lambda x:(x["eligibility"]!="review", -x["score"],x["company"]))
        selected = result[:max(1,min(limit,100))]
        if include_eligibility:
            from .eligibility import evaluate_requirements
            from .eligibility_profile import normalize_profile
            from .eligibility_requirements import parse_requirements
            candidate = normalize_profile(profile)
            by_id = {job["id"]:job for job in jobs}
            for row in selected:
                assessment = evaluate_requirements(candidate,parse_requirements(by_id[row["job_id"]]),as_of=self.clock().date())
                row["eligibility_assessment"] = {key:assessment[key] for key in ("outcome","required_rule_count","missing_information")}
        return selected

    def preview(self, jid: str, profile_path: str) -> dict:
        job=self.store.get_job(jid)
        return {"ranking":evaluate(job,self.load_profile(profile_path)),"tailoring":tailoring_report(job,self.load_profile(profile_path)),
                "job_url":job["job_url"],"apply_url":job["apply_url"]}

    def prepare(self, jid: str, profile_path: str) -> dict:
        profile=self.load_profile(profile_path)
        job=self.store.get_job(jid)
        rp,lp=create_documents(job,profile,str(self.root/"generated"))
        return self.store.set_prepared(jid,rp,lp)

    def ingest_alerts(self, query: str = "", limit: int = 30) -> dict:
        from .integrations.google_auth import GoogleGateway
        from .integrations.gmail_alerts import DEFAULT_QUERY, ingest_gmail
        gateway = GoogleGateway("gmail",self._credentials_override,legacy_dirs=self.legacy_credential_dirs)
        return ingest_gmail(self.store, gateway, query or DEFAULT_QUERY, limit)

    def pending_alerts(self, limit: int = 50) -> list[dict]:
        return self.store.list_email_leads(limit)

    def handle_alert(self, lead_id: str, action: str, company: str = "", title: str = "",
                     location: str = "", verified_url: str = "", description: str = "") -> dict:
        with self.store.connection() as c:
            r=c.execute("SELECT * FROM email_leads WHERE id=?",(lead_id,)).fetchone()
        if not r or r["status"]!="pending":
            raise ValueError("Unknown or previously handled alert lead")
        if action == "ignore":
            return self.store.set_email_lead(lead_id,"ignored")
        if action != "import":
            raise ValueError("Action must be import or ignore")
        if not company.strip() or not (title.strip() or r["title_hint"].strip()):
            raise ValueError("Import requires verified company and job title")
        url=verified_url.strip() or r["job_url"]
        from urllib.parse import urlsplit
        from .models import canonical_url
        parsed=urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Verified posting URL must be an absolute public HTTPS URL")
        record={"platform":r["platform"], "company":company.strip(),
                "title":title.strip() or r["title_hint"],"location":location,
                "job_url":url,"description":description[:20000]}
        outcome=self.import_external_jobs([record])
        if outcome["valid"]!=1:
            raise ValueError("Job did not validate. Lead remains pending.")
        matches=[j for j in self.store.list_jobs(10000) if canonical_url(j["job_url"])==canonical_url(url)]
        if not matches:
            raise ValueError("Job was not persisted")
        lead_result=self.store.set_email_lead(lead_id,"imported",matches[0]["id"])
        return {**lead_result,"ingestion":outcome}

    def sync_tracker(self, spreadsheet_id: str, apply: bool = False, confirmation: str = "") -> dict:
        from .integrations.google_auth import GoogleGateway
        from .integrations.sheet_sync import sync_sheet
        gateway=GoogleGateway("sheets",self._credentials_override,legacy_dirs=self.legacy_credential_dirs)
        return sync_sheet(self.store,gateway,spreadsheet_id,apply,confirmation)
