import tempfile
import unittest
from pathlib import Path
from docx import Document
from internship_agent.models import Job,stable_id,validate_board,canonical_url
from internship_agent.sources import normalize,strip_html
from internship_agent.store import Store
from internship_agent.scoring import evaluate
from internship_agent.documents import create_documents
from internship_agent.tracker import export_append_candidates,COLUMNS
import csv

BOARD={"provider":"greenhouse","company":"Acme Corp","token":"acme"}

def job(sid="100",title="Cloud Infrastructure Intern",desc="AWS Terraform EC2 IAM VPC Python",url="https://boards.greenhouse.io/acme/jobs/100"):
    return Job(id=stable_id("greenhouse","acme",sid),provider="greenhouse",company="Acme Corp",source_id=sid,
               title=title,description=desc,location="New York, NY",job_url=url,apply_url=url,discovered_at="2026-10-27")

PROFILE={"name":"Test Candidate","email":"candidate@example.com","location":"New York, NY",
         "education":{"school":"Example University","degree":"BS Information Systems"},
         "target_roles":["cloud engineer","cybersecurity","devops"],
         "preferred_locations":["New York","Long Island"],"skills":["AWS","Terraform","EC2","IAM","Python"],
         "experience":[{"title":"Infrastructure Intern","company":"Example Company","bullets":["Deployed AWS resources with Terraform."]}],
         "projects":[{"name":"Cloud Application","bullets":["Configured EC2 web instances."]}]}

class AdapterTests(unittest.TestCase):
    def test_greenhouse(self):
        data={"jobs":[{"id":100,"title":"Cybersecurity Intern","location":{"name":"New York, NY"},
              "content":"<p>Learn <b>IAM</b> and Python</p>","absolute_url":"https://boards.greenhouse.io/acme/jobs/100"}]}
        got=normalize(BOARD,data)
        self.assertEqual(got[0].source_id,"100")
        self.assertIn("IAM",got[0].description)
    def test_lever(self):
        b={"provider":"lever","company":"Acme","token":"acme"}
        p=[{"id":"123","text":"Security Intern","hostedUrl":"https://jobs.lever.co/acme/123",
           "applyUrl":"https://jobs.lever.co/acme/123/apply","categories":{"location":"NYC"},
           "descriptionPlain":"Security automation"}]
        self.assertEqual(normalize(b,p)[0].title,"Security Intern")
    def test_ashby(self):
        b={"provider":"ashby","company":"Acme","token":"acme"}
        p={"jobs":[{"title":"Cloud Intern","jobUrl":"https://jobs.ashbyhq.com/acme/123", "isListed":True,
                  "location":"New York", "descriptionPlain":"AWS", "applyUrl":"https://jobs.ashbyhq.com/acme/123/apply"}]}
        self.assertEqual(normalize(b,p)[0].source_id,"123")
    def test_bad_tokens_rejected(self):
        with self.assertRaises(ValueError):validate_board({"provider":"greenhouse","token":"../../metadata","company":"bad"})
        self.assertEqual(canonical_url("https://a.test/jobs/123?utm_source=mail"),"https://a.test/jobs/123")

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(str(Path(self.tmp.name)/"data.db"))
        self.j=job()
        self.store.upsert_job(self.j)
    def tearDown(self):self.tmp.cleanup()
    def test_posting_id_not_title_dedup(self):
        self.assertEqual(self.store.upsert_job(self.j),"updated")
        j2=job("101",url="https://boards.greenhouse.io/acme/jobs/101")
        self.assertEqual(self.store.upsert_job(j2),"added")
        self.assertEqual(len(self.store.list_jobs()),2)
        j3=job("102",url="https://boards.greenhouse.io/acme/jobs/101?utm_source=mail")
        self.assertEqual(self.store.upsert_job(j3),"duplicate")
    def test_ranking_is_explainable(self):
        value=evaluate(self.j.to_dict(),PROFILE)
        self.assertGreaterEqual(value["score"],65)
        self.assertIn("Terraform",value["matched_skills"])
        self.assertEqual(value["eligibility"],"review")
    def test_cannot_mark_submitted_without_approval(self):
        with self.assertRaises(ValueError):self.store.mark_submitted(self.j.id,"confirmation-123")
        with self.assertRaises(ValueError):self.store.approve(self.j.id,f"APPROVE {self.j.id}")
        with self.assertRaises(ValueError):self.store.update_status(self.j.id,"interview")
    def test_documents_and_approval_state_machine(self):
        rp,lp=create_documents(self.j.to_dict(),PROFILE,self.tmp.name)
        words=' '.join(p.text for p in Document(rp).paragraphs)
        self.assertIn("Terraform",words)
        self.assertNotIn("Kubernetes",words)
        self.assertIn("DRAFT",lp)
        self.store.set_prepared(self.j.id,rp,lp)
        with self.assertRaises(ValueError):self.store.approve(self.j.id,"yes")
        self.store.approve(self.j.id,f"APPROVE {self.j.id}")
        self.store.mark_submitted(self.j.id,"Employer confirmation #S123456")
        self.assertEqual(self.store.get_job(self.j.id)["status"],"submitted")
        with self.assertRaises(ValueError):self.store.mark_submitted(self.j.id,"another")
    def test_tracker_compatible_columns(self):
        path=str(Path(self.tmp.name)/"out.csv")
        result=export_append_candidates(self.store,path,include_unapplied=True)
        with open(path,encoding="utf-8-sig",newline="") as f:
            rows=list(csv.reader(f))
        self.assertEqual(rows[0],COLUMNS)
        self.assertEqual(len(rows[1]),19)
        self.assertEqual(result["rows"],1)

if __name__=="__main__": unittest.main()
