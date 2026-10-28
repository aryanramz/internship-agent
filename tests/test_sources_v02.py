import json
import tempfile
import unittest
from pathlib import Path
from internship_agent.sources import normalize, normalize_xml, retrieve_board, SUPPORTED
from internship_agent.models import validate_board


def b(provider, **kwargs):
    return {"provider":provider,"company":"Test Co","token":"testco",**kwargs}


class SourceNormalization(unittest.TestCase):
    def test_adapters_registry(self):
        self.assertGreaterEqual(len(SUPPORTED), 15)

    def test_smartrecruiters(self):
        data={"content":[{"id":"abc","name":"Cloud Security Intern","location":{"city":"New York","region":"NY"},"releasedDate":"2026-10-01"}]}
        out=normalize(b("smartrecruiters"),data)
        self.assertEqual(len(out),1)
        self.assertIn("smartrecruiters.com",out[0].job_url)

    def test_workable_duplicate_city(self):
        j={"shortcode":"ABCD","title":"SRE Intern","url":"https://apply.workable.com/j/ABCD/","city":"New York","description":"AWS"}
        out=normalize(b("workable"),{"jobs":[j,{**j,"city":"Boston"}]})
        self.assertEqual(len(out),1)

    def test_breezy(self):
        out=normalize(b("breezy"),[{"id":"123","name":"Security Intern","friendly_id":"security-intern","location":{"name":"NYC","is_remote":False}}])
        self.assertEqual(out[0].location,"NYC")

    def test_pinpoint_description(self):
        out=normalize(b("pinpoint"),{"data":[{"id":"101","title":"DevOps Intern","url":"https://testco.pinpointhq.com/postings/101","location":{"name":"NYC"},"description":"<p>AWS</p>","skills_knowledge_expertise":"<ul><li>Terraform</li></ul>"}]})
        self.assertIn("Terraform",out[0].description)

    def test_bamboohr(self):
        out=normalize(b("bamboohr"),{"result":[{"id":11,"jobOpeningName":"IT Intern","location":{"city":"Sampletown"}}]})
        self.assertEqual(len(out),1)

    def test_workday(self):
        board=b("workday",host="testco.wd5.myworkdayjobs.com",site="External")
        out=normalize(board,{"jobPostings":[{"title":"Infrastructure Intern","externalPath":"/job/NY/Intern_R123","locationsText":"New York"}]})
        self.assertEqual(len(out),1)
        self.assertIn("/External/job/NY",out[0].job_url)

    def test_remote_only_interns(self):
        out=normalize(b("remotive"),{"jobs":[{"id":1,"title":"Security Intern","url":"https://remotive.com/jobs/a","company_name":"Acme","description":"Security"},{"id":2,"title":"Senior Developer","url":"https://remotive.com/jobs/b"}]})
        self.assertEqual(len(out),1)
        self.assertEqual(out[0].company,"Acme")
        out2=normalize(b("jobicy"),{"jobs":[{"id":33,"jobTitle":"Cloud Engineering Internship","url":"https://jobicy.com/jobs/33","companyName":"Company","jobGeo":"USA"}]})
        self.assertEqual(len(out2),1)

    def test_simplify_inactive_filtered(self):
        out=normalize(b("simplify_github"),[
            {"id":"foo","company_name":"Acme","title":"Cloud Intern","url":"https://acme.com/a","active":True,"is_visible":True,"locations":["New York"],"date_posted":1790000000},
            {"id":"bar","company_name":"Acme","title":"Security Intern","url":"https://acme.com/b","active":False}
        ])
        self.assertEqual(len(out),1)
        self.assertEqual(out[0].company,"Acme")
        self.assertIn("2026",out[0].published_at)

    def test_personio_xml(self):
        xml=b'<workzag-jobs><position><id>7</id><name>IT Intern</name><office>New York</office><jobDescriptions><jobDescription><value><![CDATA[<p>Linux</p>]]></value></jobDescription></jobDescriptions></position></workzag-jobs>'
        out=normalize_xml(b("personio"),xml)
        self.assertEqual(len(out),1)
        self.assertIn("Linux",out[0].description)

    def test_rss_and_atom(self):
        rss=b'<rss><channel><item><title>Cybersecurity Intern</title><guid>abc</guid><link>https://example.org/jobs/abc</link><description><![CDATA[<p>Security</p>]]></description></item></channel></rss>'
        self.assertEqual(len(normalize_xml(b("rss",feed_url="https://example.org/jobs.rss"),rss)),1)
        atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id><title>Cloud Intern</title><link href="https://example.org/job/1" /></entry></feed>'
        self.assertEqual(len(normalize_xml(b("rss",feed_url="https://example.org/jobs.atom"),atom)),1)

    def test_manual_csv_import_linkedin_handshake_indeed(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"alerts.csv"
            path.write_text("platform,company,title,location,job_url\nlinkedin,Firm,Security Intern,NYC,https://linkedin.com/jobs/view/1\nhandshake,Hospital,IT Intern,NY,https://app.joinhandshake.com/stu/jobs/2\nindeed,Company,Cloud Intern,NY,https://www.indeed.com/viewjob?jk=123\n",encoding="utf-8")
            out=retrieve_board(b("csv_import",path="alerts.csv"),root)
            self.assertEqual(len(out),3)
            self.assertEqual({x.provider for x in out},{"linkedin","indeed","handshake"})

    def test_local_json_import(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"jobs.json"
            path.write_text(json.dumps([{"platform":"ripplematch","title":"Security Intern","company":"Acme","job_url":"https://acme.com/jobs/12"}]))
            self.assertEqual(retrieve_board(b("json_import",path="jobs.json"),root)[0].provider,"ripplematch")

    def test_security_configuration(self):
        with self.assertRaises(ValueError):validate_board(b("workday",host="169.254.169.254",site="External"))
        with self.assertRaises(ValueError):validate_board(b("rss",feed_url="http://localhost/private"))
        with self.assertRaises(ValueError):validate_board(b("json_import",path=""))


if __name__ == "__main__": unittest.main()

class DetectBoards(unittest.TestCase):
    def test_known_urls(self):
        from internship_agent.source_detection import detect_source
        samples={
            "https://boards.greenhouse.io/acme/jobs/123":"greenhouse",
            "https://jobs.lever.co/acme/123":"lever",
            "https://jobs.ashbyhq.com/acme/123":"ashby",
            "https://careers.smartrecruiters.com/acme":"smartrecruiters",
            "https://apply.workable.com/acme/":"workable",
            "https://acme.breezy.hr/":"breezy",
            "https://acme.pinpointhq.com/":"pinpoint",
            "https://acme.jobs.personio.de":"personio",
            "https://acme.bamboohr.com/careers":"bamboohr",
            "https://acme.teamtailor.com/jobs":"teamtailor",
            "https://acme.wd5.myworkdayjobs.com/en-US/AcmeExternal/jobs":"workday",
        }
        for url,expected in samples.items():
            with self.subTest(url=url):
                self.assertEqual(detect_source(url,"Acme")["provider"],expected)
    def test_reject_short_url(self):
        from internship_agent.source_detection import detect_source
        with self.assertRaises(ValueError):detect_source("https://apply.workable.com/j/ABC","Acme")

class Robustness(unittest.TestCase):
    def test_indeed_ids_not_collapsed(self):
        from internship_agent.models import canonical_url
        a=canonical_url("https://www.indeed.com/viewjob?jk=abc&utm_campaign=spam")
        b=canonical_url("https://www.indeed.com/viewjob?jk=def")
        self.assertNotEqual(a,b)
        self.assertNotIn("utm_",a)

    def test_direct_employer_enriches_community_duplicate(self):
        from internship_agent.store import Store
        from internship_agent.models import Job, stable_id
        with tempfile.TemporaryDirectory() as root:
            store=Store(str(Path(root)/"jobs.db"))
            base={"company":"Acme","title":"Security Intern","location":"NY","job_url":"https://acme.com/job/123","apply_url":"https://acme.com/job/123"}
            first=Job(id=stable_id("simplify_github","summer2027","1"),provider="simplify_github",source_id="1",description="",**base)
            second=Job(id=stable_id("greenhouse","acme","123"),provider="greenhouse",source_id="123",description="AWS IAM Terraform skills required",**base)
            self.assertEqual(store.upsert_job(first),"added")
            self.assertEqual(store.upsert_job(second),"duplicate")
            self.assertEqual(len(store.list_jobs()),1)
            self.assertIn("Terraform",store.list_jobs()[0]["description"])

    def test_connector_import(self):
        from internship_agent.service import Agent
        with tempfile.TemporaryDirectory() as root:
            agent=Agent(root)
            result=agent.import_external_jobs([{"platform":"handshake","company":"Acme","title":"IT Intern","job_url":"https://app.joinhandshake.com/stu/jobs/123"}])
            self.assertEqual(result["added"],1)
            self.assertEqual(agent.store.count(),{"discovered":1})

class Expansion(unittest.TestCase):
    def test_suggest_and_register_employer_board(self):
        from internship_agent.service import Agent
        from internship_agent.models import Job, stable_id
        with tempfile.TemporaryDirectory() as root:
            agent=Agent(root)
            base="https://jobs.lever.co/realcompany/jobid123"
            agent.store.upsert_job(Job(id=stable_id("simplify_github","summer2027","post"),provider="simplify_github",company="Real Company",source_id="post",title="IT Intern",location="NY",description="",job_url=base,apply_url=base))
            path=Path(root)/"config"/"sources.json"
            path.parent.mkdir()
            path.write_text('{"boards":[]}',encoding="utf-8")
            preview=agent.suggest_sources(str(path))
            self.assertEqual(preview["shown"],1)
            self.assertEqual(json.loads(path.read_text())["boards"],[])
            approved=agent.suggest_sources(str(path),apply=True)
            self.assertEqual(approved["registered"],1)
            self.assertEqual(json.loads(path.read_text())["boards"][0]["provider"],"lever")

class Safety(unittest.TestCase):
    def test_no_private_ip_rss(self):
        for url in ("https://169.254.169.254/private", "https://127.0.0.1/feed", "https://service.internal/jobs.rss", "https://example.com:8000/rss"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_board(b("rss",feed_url=url))
