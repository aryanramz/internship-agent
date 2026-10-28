from __future__ import annotations
import json
from pathlib import Path
from .sources import retrieve_board, normalize, SUPPORTED, SourceError
from .scoring import evaluate
from .documents import create_documents,tailoring_report
from .store import Store
from .models import validate_board

class Agent:
    def __init__(self, root: str):
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.store=Store(str(self.root/"agent.db"))

    def load_profile(self, profile_path: str) -> dict:
        with open(profile_path, encoding="utf-8") as f:
            value=json.load(f)
        if not isinstance(value,dict):raise ValueError("Profile must be JSON object")
        return value

    def discover(self, sources_path: str) -> dict:
        with open(sources_path, encoding="utf-8") as f:
            source=json.load(f)
        summary={"added":0,"updated":0,"duplicate":0,"errors":[],"by_source":[]}
        for entry in source.get("boards",[]):
            if entry.get("enabled", True) is False:
                continue
            try:
                entry=validate_board(entry)
                jobs=retrieve_board(entry, str(Path(sources_path).resolve().parent.parent))
                counts={"provider":entry["provider"],"company":entry["company"],"retrieved":len(jobs),"added":0,"updated":0,"duplicate":0}
                for job in jobs:
                    outcome=self.store.upsert_job(job)
                    summary[outcome]+=1
                    counts[outcome]+=1
                summary["by_source"].append(counts)
            except Exception as exc:
                error={"board":entry.get("company","unknown"),"error":str(exc)[:250]}
                if isinstance(exc, SourceError):
                    error["code"]=exc.code
                    if exc.http_status is not None:
                        error["http_status"]=exc.http_status
                    if exc.retry_after:
                        error["retry_after"]=exc.retry_after
                summary["errors"].append(error)
        return summary



    def suggest_sources(self, sources_path: str, limit: int = 100, apply: bool = False) -> dict:
        """Discover employer boards from previously ingested public job URLs.

        Suggestions are never fetched. --apply explicitly registers at most `limit`
        employer boards for the *next* discovery run.
        """
        from .source_detection import detect_source
        sources_file=Path(sources_path)
        config=json.loads(sources_file.read_text(encoding="utf-8")) if sources_file.exists() else {"boards":[]}
        configured={(i.get("provider"),i.get("token"),i.get("site")) for i in config.get("boards",[])}
        discovered={}
        for record in self.store.list_jobs(10000):
            try:
                board=detect_source(record["job_url"],record["company"])
            except ValueError:
                continue
            key=(board.get("provider"),board.get("token"),board.get("site"))
            if key not in configured:
                discovered[key]=board
        suggestions=list(discovered.values())[:max(0,min(500,limit))]
        if apply and suggestions:
            config.setdefault("boards",[]).extend(suggestions)
            sources_file.parent.mkdir(parents=True,exist_ok=True)
            sources_file.write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
        return {"available":len(discovered),"shown":len(suggestions),"registered":len(suggestions) if apply else 0,
                "sources":suggestions,"note":"Registration does not fetch postings until the next discover run."}

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

    def ranked(self, profile_path: str, limit: int=25, min_score: int=0) -> list[dict]:
        profile=self.load_profile(profile_path)
        result=[]
        for job in self.store.list_jobs(10000):
            report=evaluate(job,profile)
            if report["score"]>=min_score:
                result.append({"job_id":job["id"],"company":job["company"],"title":job["title"],"location":job["location"],
                               "job_url":job["job_url"],"apply_url":job["apply_url"],"status":job["status"],**report})
        result.sort(key=lambda x:(x["eligibility"]!="review", -x["score"],x["company"]))
        return result[:max(1,min(limit,100))]

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
        gateway = GoogleGateway("gmail", str(self.root / "secrets"))
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
        gateway=GoogleGateway("sheets",str(self.root / "secrets"))
        return sync_sheet(self.store,gateway,spreadsheet_id,apply,confirmation)
