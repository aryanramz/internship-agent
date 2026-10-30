"""SQLite is the authoritative application state. Google Sheets remains a mirror."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from .models import Job, canonical_url, now_iso

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL, company TEXT NOT NULL, source_id TEXT NOT NULL,
  title TEXT NOT NULL, location TEXT NOT NULL, description TEXT NOT NULL,
  job_url TEXT NOT NULL, canonical_url TEXT NOT NULL,
  apply_url TEXT NOT NULL, work_mode TEXT NOT NULL,
  published_at TEXT NOT NULL, compensation TEXT NOT NULL,
  discovered_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(canonical_url);
CREATE TABLE IF NOT EXISTS applications (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id), status TEXT NOT NULL,
  resume_path TEXT, letter_path TEXT, approved_at TEXT, submitted_at TEXT,
  submission_evidence TEXT, notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_leads (
  id TEXT PRIMARY KEY, message_id TEXT NOT NULL, platform TEXT NOT NULL,
  sender TEXT NOT NULL, subject TEXT NOT NULL, title_hint TEXT NOT NULL,
  job_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL, imported_job_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_leads_message ON email_leads(message_id);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT REFERENCES jobs(id),
  event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""

STATUSES = ("discovered", "shortlisted", "prepared", "approved", "submitted", "assessment", "interview", "offer", "rejected", "withdrawn")


class Store:
    def __init__(self, db_path: str, *, read_only: bool = False):
        self.path = Path(db_path)
        self.read_only=read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError("Read-only access requires an existing application database")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .discovery_state import migrate, VERSION
        with self.connection() as c:
            if c.execute("PRAGMA user_version").fetchone()[0] > VERSION:
                raise ValueError("Database schema is newer than this application supports")
            c.executescript(SCHEMA)
            migrate(c)

    @contextmanager
    def connection(self):
        if self.read_only:
            conn=sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro",uri=True)
            conn.execute("PRAGMA query_only=ON")
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=3000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def event(self, conn, jid: str | None, kind: str, payload: dict):
        conn.execute("INSERT INTO events(job_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                     (jid, kind, json.dumps(payload, sort_keys=True), now_iso()))

    def upsert_job(self, job: Job) -> str:
        """Dedup posting identity; shared URLs remain reviewable separate records."""
        with self.connection() as c:
            return self._upsert_job(c, job)

    def _upsert_job(self, c, job: Job) -> str:
        """Share one transaction with source evidence and its durable checkpoint."""
        url = canonical_url(job.job_url)
        existing = c.execute("SELECT id FROM jobs WHERE id=?", (job.id,)).fetchone()
        c.execute("""INSERT INTO jobs(id,provider,company,source_id,title,location,description,job_url,canonical_url,apply_url,work_mode,published_at,compensation,discovered_at,last_seen_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET title=excluded.title, location=excluded.location,
                         description=excluded.description, job_url=excluded.job_url,
                         canonical_url=excluded.canonical_url, apply_url=excluded.apply_url,
                         work_mode=excluded.work_mode, published_at=excluded.published_at,
                         compensation=excluded.compensation, last_seen_at=excluded.last_seen_at""",
                      (job.id,job.provider,job.company,job.source_id,job.title,job.location,job.description,
                       job.job_url,url,job.apply_url,job.work_mode,job.published_at,job.compensation,
                       job.discovered_at or now_iso(),now_iso()))
        if not existing:
            c.execute("INSERT INTO applications(job_id,status,updated_at) VALUES(?,?,?)",(job.id,"discovered",now_iso()))
            self.event(c,job.id,"discovered",{"provider":job.provider,"url":job.job_url})
            return "added"
        return "updated"

    def list_jobs(self, limit: int = 100) -> list[dict]:
        with self.connection() as c:
            rows=c.execute("""SELECT j.*,a.status,a.resume_path,a.letter_path FROM jobs j
                              JOIN applications a ON a.job_id=j.id
                              ORDER BY j.last_seen_at DESC LIMIT ?""",(max(1,min(limit,10000)),)).fetchall()
        return [dict(r) for r in rows]

    def get_job(self, jid: str) -> dict:
        with self.connection() as c:
            r=c.execute("""SELECT j.*,a.status,a.approved_at,a.resume_path,a.letter_path,
                          a.submission_evidence,a.submitted_at FROM jobs j
                          JOIN applications a ON a.job_id=j.id WHERE j.id=?""",(jid,)).fetchone()
        if not r:
            raise ValueError("Unknown job ID")
        return dict(r)

    def set_prepared(self, jid: str, resume_path: str, letter_path: str) -> dict:
        with self.connection() as c:
            rec=c.execute("SELECT status FROM applications WHERE job_id=?",(jid,)).fetchone()
            if not rec:
                raise ValueError("Unknown job ID")
            if rec["status"] in {"submitted", "assessment", "interview", "offer", "rejected", "withdrawn"}:
                raise ValueError("Cannot overwrite documents for a completed application")
            c.execute("""UPDATE applications SET status='prepared',approved_at=NULL,resume_path=?,letter_path=?,
                         updated_at=? WHERE job_id=?""", (resume_path,letter_path,now_iso(),jid))
            self.event(c,jid,"prepared",{"resume_path":resume_path,"letter_path":letter_path})
        return self.get_job(jid)

    def approve(self, jid: str, phrase: str) -> dict:
        if phrase != f"APPROVE {jid}":
            raise ValueError("Approval requires exact phrase: APPROVE <job_id>")
        with self.connection() as c:
            r=c.execute("SELECT status,resume_path FROM applications WHERE job_id=?",(jid,)).fetchone()
            if not r or r["status"] != "prepared" or not r["resume_path"]:
                raise ValueError("Application must first be prepared with a resume")
            c.execute("UPDATE applications SET status='approved', approved_at=?, updated_at=? WHERE job_id=?",(now_iso(),now_iso(),jid))
            self.event(c,jid,"approved",{"mode":"explicit confirmation phrase"})
        return self.get_job(jid)

    def mark_submitted(self, jid: str, confirmation: str) -> dict:
        if not confirmation or len(confirmation.strip()) < 6:
            raise ValueError("Provide a real submission confirmation identifier or URL")
        with self.connection() as c:
            r=c.execute("SELECT status FROM applications WHERE job_id=?",(jid,)).fetchone()
            if not r or r["status"] != "approved":
                raise ValueError("Submission must follow approved state")
            c.execute("UPDATE applications SET status='submitted',submitted_at=?,submission_evidence=?,updated_at=? WHERE job_id=?",
                      (now_iso(),confirmation.strip(),now_iso(),jid))
            self.event(c,jid,"submitted",{"evidence":confirmation.strip()})
        return self.get_job(jid)

    def update_status(self, jid: str, status: str, evidence: str = "") -> dict:
        if status not in {"assessment","interview","offer","rejected","withdrawn"}:
            raise ValueError("Only post-application statuses can be set here")
        with self.connection() as c:
            r=c.execute("SELECT status FROM applications WHERE job_id=?",(jid,)).fetchone()
            if not r or r["status"] not in {"submitted","assessment","interview","offer","rejected"}:
                raise ValueError("Cannot set outcome for a job without confirmed submission")
            c.execute("UPDATE applications SET status=?, updated_at=? WHERE job_id=?", (status,now_iso(),jid))
            self.event(c,jid,"status_updated",{"new_status":status,"evidence":evidence})
        return self.get_job(jid)

    def add_email_lead(self, lead: dict) -> bool:
        with self.connection() as c:
            cursor=c.execute("""INSERT OR IGNORE INTO email_leads
               (id,message_id,platform,sender,subject,title_hint,job_url,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",(lead["id"],lead["message_id"],lead["platform"],
               lead["sender"],lead["subject"],lead["title_hint"],lead["job_url"],lead["created_at"]))
            return cursor.rowcount > 0

    def list_email_leads(self, limit: int = 100, status: str = "pending") -> list[dict]:
        if status not in {"pending","imported","ignored","all"}:
            raise ValueError("Invalid lead status")
        with self.connection() as c:
            if status=="all":
                result=c.execute("SELECT * FROM email_leads ORDER BY created_at DESC LIMIT ?",(min(500,max(1,limit)),)).fetchall()
            else:
                result=c.execute("SELECT * FROM email_leads WHERE status=? ORDER BY created_at DESC LIMIT ?",(status,min(500,max(1,limit)))).fetchall()
        return [dict(r) for r in result]

    def set_email_lead(self, lead_id: str, status: str, imported_job_id: str = "") -> dict:
        if status not in {"imported","ignored"}:
            raise ValueError("Only imported or ignored lead outcomes allowed")
        with self.connection() as c:
            entry=c.execute("SELECT * FROM email_leads WHERE id=?",(lead_id,)).fetchone()
            if not entry or entry["status"]!="pending":
                raise ValueError("Unknown or already processed lead")
            c.execute("UPDATE email_leads SET status=?, imported_job_id=? WHERE id=?",
                      (status,imported_job_id or None,lead_id))
        return {"lead_id":lead_id,"status":status,"job_id":imported_job_id}

    def count(self) -> dict:
        with self.connection() as c:
            rows=c.execute("SELECT status,COUNT(*) n FROM applications GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}
