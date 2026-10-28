"""Public project checks: offline demo and deployment privacy boundaries."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from demo import run_demo  # noqa: E402


class PublicDemoTests(unittest.TestCase):
    def test_demo_creates_prepared_documents_without_submission(self):
        with TemporaryDirectory() as d:
            result = run_demo(Path(d))
            self.assertEqual(result["ingestion"]["added"], 3)
            self.assertEqual(result["application_status"], "prepared")
            self.assertTrue(Path(result["generated_files"]["resume"]).exists())
            self.assertTrue(Path(result["generated_files"]["cover_letter_draft"]).exists())
            self.assertTrue(Path(d, "demo_summary.json").exists())
            self.assertEqual(len(result["rankings"]), 3)
            self.assertTrue(any(r["eligibility"] == "unlikely" for r in result["rankings"]))

    def test_example_profile_is_synthetic(self):
        profile = json.loads((ROOT / "config" / "profile.example.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["name"], "Demo Student")
        self.assertIn("SYNTHETIC", profile["review_note"])
        self.assertNotIn("@gmail.com", profile.get("email", ""))


if __name__ == "__main__":
    unittest.main()
