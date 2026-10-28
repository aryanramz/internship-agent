"""Reproducible offline demo. Uses fictional jobs/profile only; never accesses network."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
# Allows `python scripts/demo.py` before optional editable installation.
sys.path.insert(0, str(REPO / "src"))
from internship_agent.service import Agent  # noqa: E402


def run_demo(output: Path) -> dict:
    """Create example DB, score jobs, and generate one draft application packet."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    profile = REPO / "config" / "profile.example.json"
    jobs = json.loads((REPO / "examples" / "demo_jobs.json").read_text(encoding="utf-8"))
    agent = Agent(str(output))
    ingested = agent.import_external_jobs(jobs)
    ranked = agent.ranked(str(profile), min_score=0)
    # Search for the explicit demo job, never accidentally prepare the wrong role.
    target = next(j for j in ranked if "Cloud Infrastructure Intern" in j["title"])
    preview = agent.preview(target["job_id"], str(profile))
    packet = agent.prepare(target["job_id"], str(profile))
    result = {
        "notice": "Fictional, offline demo. No real job applications or emails sent.",
        "ingestion": ingested,
        "rankings": [{"title": j["title"], "fit_score": j["score"],
                      "eligibility": j["eligibility"], "flags": j["flags"]} for j in ranked],
        "tailoring": preview["tailoring"],
        "generated_files": {"resume": packet["resume_path"], "cover_letter_draft": packet["letter_path"]},
        "application_status": packet["status"],
        "next_step": "Review documents; nothing was submitted."
    }
    (output / "demo_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "demo-output")
    args = parser.parse_args()
    print(json.dumps(run_demo(args.output), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
