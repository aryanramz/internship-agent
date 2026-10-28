import base64
import json
import tempfile
import unittest
from pathlib import Path
from internship_agent.integrations.gmail_alerts import extract_leads,ingest_gmail
from internship_agent.integrations.sheet_sync import plan_sync,sync_sheet
from internship_agent.tracker import COLUMNS
from internship_agent.store import Store
from internship_agent.models import Job,stable_id
from internship_agent.service import Agent


def msg_html(mid="message-one", sender="LinkedIn <updates@linkedin.com>"):
    html='''<a href="https://www.linkedin.com/jobs/view/123456/?utm_source=email">Security Engineering Intern</a>
    <a href="https://www.linkedin.com/jobs/view/123456/?utm_campaign=other">Security Engineering Intern</a>
    <a href="https://www.linkedin.com/preferences">Manage preferences</a>
    <a href="https://trk.mail-example.org/?redirect=linkedin">Other jobs</a>'''
    return {"id":mid,"payload":{"headers":[{"name":"From","value":sender},
        {"name":"Subject","value":"New internship postings"}],
        "mimeType":"text/html","body":{"data":base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")}}}

class FakeGmail:
    def __init__(self):self.calls=0
    def list_messages(self,q,limit):return [{"id":"message-one"}]
    def get_message(self,mid):self.calls+=1;return msg_html(mid)

class FakeSheet:
    def __init__(self,rows):self.rows=[list(r) for r in rows];self.updated=[];self.appended=[];self.mutate=False
    def get_values(self,sid,rng):
        assert rng=="'Applications'!A1:S5000"
        if self.mutate:
            self.rows[4][10]="Interview"
        return [list(r) for r in self.rows]
    def update_cells(self,sid,entries):
        self.updated.extend(entries)
        for u in entries:
            column=u["range"].split("!")[-1][0]
            row=int(u["range"].split(column)[-1])-1
            idx={"I":8,"K":10,"M":12,"N":13}[column]
            while len(self.rows[row])<=idx: self.rows[row].append("")
            self.rows[row][idx]=u["values"][0][0]
    def append_rows(self,sid,rng,items):
        self.appended.extend(items);self.rows.extend(items)


def make_agent(tmp, state="prepared"):
    agent=Agent(tmp)
    jd=Job(id=stable_id("greenhouse","acme","42"),provider="greenhouse",company="Acme",source_id="42",
           title="Cloud Security Intern",location="New York, NY",description="AWS IAM",
           job_url="https://boards.greenhouse.io/acme/jobs/42",apply_url="https://boards.greenhouse.io/acme/jobs/42")
    agent.store.upsert_job(jd)
    agent.store.set_prepared(jd.id, "data/generated/resume.docx", "data/generated/letter.docx")
    if state in ("approved","submitted"):
        agent.store.approve(jd.id,f"APPROVE {jd.id}")
    if state=="submitted":
        agent.store.mark_submitted(jd.id,"confirmation #abc123")
    return agent,jd.id

class BridgeTests(unittest.TestCase):
    def test_preview_reports_every_exact_insert_and_cell_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,jid=make_agent(tmp,"submitted")
            row=[1,"Manual company"]+[""]*17
            sheet=FakeSheet([["title"],["note"],[],COLUMNS,row])
            result=sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123")
            self.assertEqual(len(result["append_rows"]),1)
            self.assertEqual(len(result["append_rows"][0]),19)
            self.assertEqual(result["append_rows"][0][0],2)
            self.assertEqual(result["append_rows"][0][1:3],["Acme","Cloud Security Intern"])
            self.assertEqual(result["updates"],[])
            self.assertFalse(sheet.appended)
            owned=result["append_rows"][0]
            owned[10]="Not Applied"
            owned[8]=""
            sheet.rows.append(owned)
            preview=sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123")
            self.assertIn({"range":"'Applications'!K6","values":[["Applied"]]},preview["updates"])
            self.assertEqual(preview["append_rows"],[])
            self.assertFalse(sheet.updated)

    def test_sync_audit_contains_metadata_without_sheet_values_or_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,jid=make_agent(tmp)
            sheet=FakeSheet([["title"],["note"],[],COLUMNS])
            sid="EXAMPLE_SPREADSHEET_ID_12345678901234567890123"
            sync_sheet(agent.store,sheet,sid)
            sync_sheet(agent.store,sheet,sid,True,"SYNC APPLICATIONS")
            with agent.store.connection() as connection:
                events=connection.execute("SELECT payload_json FROM events WHERE event_type='sheet_sync' ORDER BY id").fetchall()
            values=[json.loads(e[0]) for e in events]
            self.assertEqual([e["phase"] for e in values],["started","preview","started","planned","completed"])
            self.assertEqual(values[-1]["append_count"],1)
            self.assertEqual(values[-1]["update_count"],0)
            self.assertEqual(values[-1]["sheet_ref"],values[1]["sheet_ref"])
            self.assertNotEqual(values[0]["sync_id"],values[2]["sync_id"])
            rendered=json.dumps(values)
            for private_value in (sid,"Acme","Cloud Security Intern","resume.docx",jid):
                self.assertNotIn(private_value,rendered)

    def test_ambiguous_append_is_audited_and_preview_prevents_duplicate_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,jid=make_agent(tmp)
            class AmbiguousSheet(FakeSheet):
                def append_rows(self,sid,rng,items):
                    super().append_rows(sid,rng,items)
                    raise TimeoutError("untrusted remote diagnostics")
            sheet=AmbiguousSheet([["title"],["note"],[],COLUMNS])
            sid="EXAMPLE_SPREADSHEET_ID_12345678901234567890123"
            with self.assertRaises(TimeoutError):
                sync_sheet(agent.store,sheet,sid,True,"SYNC APPLICATIONS")
            with agent.store.connection() as connection:
                event=json.loads(connection.execute("SELECT payload_json FROM events WHERE event_type='sheet_sync' ORDER BY id DESC LIMIT 1").fetchone()[0])
            self.assertEqual(event["phase"],"failed")
            self.assertEqual(event["stage"],"append")
            self.assertEqual(event["write_outcome"],"unknown")
            self.assertNotIn("untrusted",json.dumps(event))
            preview=sync_sheet(agent.store,sheet,sid)
            self.assertEqual((preview["append_count"],preview["update_count"]),(0,0))
            self.assertEqual(len(sheet.appended),1)
            self.assertEqual(agent.store.get_job(jid)["status"],"prepared")

    def test_extract_links_no_redirects_no_duplicates(self):
        items=extract_leads(msg_html())
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]["platform"],"linkedin")
        self.assertIn("123456",items[0]["job_url"])

    def test_handshake_job_link_staged(self):
        m=msg_html(sender="Handshake <alerts@joinhandshake.com>")
        html='<a href="https://app.joinhandshake.com/stu/jobs/123">Cloud Engineer Intern</a>'
        m["payload"]["body"]["data"]=base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
        self.assertEqual(len(extract_leads(m)),1)

    def test_untrusted_sender_does_not_stage(self):
        self.assertEqual(extract_leads(msg_html(sender="Spam <sales@fake-domain.com>")),[])

    def test_gmail_ingestion_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(str(Path(tmp)/"x.db"));gmail=FakeGmail()
            self.assertEqual(ingest_gmail(store,gmail)["leads_added"],1)
            self.assertEqual(ingest_gmail(store,gmail)["leads_existing"],1)
            self.assertEqual(len(store.list_email_leads()),1)
            self.assertEqual(store.count(),{})  # leads never become applications

    def test_review_to_import_requires_company(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent=Agent(tmp)
            for item in extract_leads(msg_html()):agent.store.add_email_lead(item)
            lid=agent.pending_alerts()[0]["id"]
            with self.assertRaises(ValueError):agent.handle_alert(lid,"import",title="Security Engineering Intern")
            res=agent.handle_alert(lid,"import",company="Example Corp",location="New York")
            self.assertEqual(res["status"],"imported")
            self.assertEqual(agent.store.count(),{"discovered":1})

    def test_header_guard_no_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,_=make_agent(tmp)
            with self.assertRaises(ValueError):plan_sync(agent.store,[["Wrong"]])

    def test_preserve_historical_rows_dryrun(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,jid=make_agent(tmp)
            rows=[["title"], ["note"], [], COLUMNS,
                  [1,"ExampleCompany","2026 Internship","7656", "", "Brookhaven", "", "", "", "", "Under Consideration"]]
            sheet=FakeSheet(rows)
            result=sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123")
            self.assertEqual(result["append_count"],1)
            self.assertEqual(result["update_count"],0)
            self.assertFalse(sheet.appended)
            self.assertEqual(sheet.rows[4][1],"ExampleCompany")

    def test_apply_needs_confirmation_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,jid=make_agent(tmp)
            rows=[["title"],["note"],[],COLUMNS,[1,"ExampleCompany"]]
            sheet=FakeSheet(rows)
            with self.assertRaises(ValueError):sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123",True)
            r=sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123",True,"SYNC APPLICATIONS")
            self.assertEqual(r["append_count"],1)
            self.assertEqual(len(sheet.appended),1)
            self.assertIn(jid,sheet.rows[-1][18])
            r2=sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123",True,"SYNC APPLICATIONS")
            self.assertEqual(r2["append_count"],0)
            self.assertEqual(len(sheet.appended),1)

    def test_update_owned_status_only_and_no_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,jid=make_agent(tmp,"submitted")
            row=[2,"Acme"]+[""]*17
            row[10]="Not Applied";row[18]=f"Agent ID: {jid}; Source: greenhouse"
            sheet=FakeSheet([["title"],["note"],[],COLUMNS,row])
            r=sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123",True,"SYNC APPLICATIONS")
            self.assertEqual(sheet.rows[4][10],"Applied")
            self.assertTrue(r["update_count"])
            sheet.rows[4][10]="Interview"
            p=sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123")
            self.assertEqual(p["update_count"],0)
            self.assertTrue(p["skipped"])

    def test_sync_detects_concurrent_manual_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent,jid=make_agent(tmp)
            rows=[["title"],["note"],[],COLUMNS,[1,"ExampleCompany","", "", "", "", "", "", "", "", "Under Consideration"]]
            class Changing(FakeSheet):
                n=0
                def get_values(self,sid,rng):
                    self.n+=1
                    data=super().get_values(sid,rng)
                    if self.n>=2:data[4][10]="Interview"
                    return data
            sheet=Changing(rows)
            with self.assertRaisesRegex(ValueError,"changed"):
                sync_sheet(agent.store,sheet,"EXAMPLE_SPREADSHEET_ID_12345678901234567890123",True,"SYNC APPLICATIONS")
            self.assertEqual(sheet.appended,[])

if __name__ == "__main__":unittest.main()
