"""Explainable, deterministic profile-fit scoring, not a hiring probability."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

WEIGHTS = {"role": 35, "skills": 25, "location": 15, "recency": 10, "compensation": 10, "employer": 5}
INTERN = re.compile(r"\b(intern(ship)?|co[- ]?op|summer analyst)\b", re.I)
SENIOR = re.compile(r"\b(staff|principal|senior|sr\.|director)\b", re.I)


def _contains(text: str, phrase: str) -> bool:
    # Prevent matching e.g. IAM within 'William', or Java within JavaScript.
    pat = r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)"
    return bool(re.search(pat, text.lower()))


def _role_score(title: str, roles: list[str]) -> tuple[float, list[str]]:
    found = []
    for role in roles:
        tokens = [x for x in re.findall(r"[a-z]+", role.lower()) if x not in {"intern", "internship", "engineer", "analyst"}]
        if tokens and any(_contains(title, token) for token in tokens):
            found.append(role)
    if found:
        return 1., found
    # Broad IT, technology, automation or software role: viable but lower priority.
    if any(_contains(title, word) for word in ["technology", "IT", "software", "systems", "engineering", "security"]):
        return .50, []
    return .12, []


def evaluate(job: dict, profile: dict) -> dict:
    title = str(job["title"])
    description = str(job.get("description", ""))
    text = " ".join([title, description, str(job.get("location", ""))]).lower()
    role, matched_roles = _role_score(title, profile.get("target_roles", []))
    skills = [str(x) for x in profile.get("skills", []) if str(x).strip()]
    matched = [x for x in skills if _contains(text, x)]
    skill_score = min(1., len(matched) / min(7, max(3, len(skills))))

    loc = f'{job.get("location", "")} {job.get("work_mode", "")}'.lower()
    prefs = [x for x in profile.get("preferred_locations", []) if x]
    location_matched = any(_contains(loc, x) for x in prefs)
    remote = "remote" in loc
    location_score = 1. if location_matched else (.8 if remote and "Remote" in prefs else .15)

    # Published time, not our time of first discovery, determines freshness.
    freshness = 0.35
    if job.get("published_at"):
        try:
            dt = datetime.fromisoformat(str(job["published_at"]).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - dt).days
            freshness = 1. if days <= 14 else (.65 if days <= 45 else .2)
        except ValueError:
            try:
                dt = parsedate_to_datetime(str(job["published_at"]))
                days = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days
                freshness = 1. if days <= 14 else (.65 if days <= 45 else .2)
            except (ValueError, TypeError, IndexError):
                pass
    compensation_score = .8 if job.get("compensation") else .4
    preferred_employers = profile.get("preferred_employers", [])
    employer_score = 1. if preferred_employers and job.get("company", "").lower() in [x.lower() for x in preferred_employers] else .5

    components = dict(role=role, skills=skill_score, location=location_score, recency=freshness,
                      compensation=compensation_score, employer=employer_score)
    score = round(sum(WEIGHTS[k] * components[k] for k in WEIGHTS))
    flags = []
    eligible = "review"
    if not INTERN.search(title):
        flags.append("Title does not explicitly indicate internship/co-op")
    if SENIOR.search(title):
        flags.append("Senior-level title: likely not appropriate")
        eligible = "unlikely"
    if re.search(r"\b(phd|doctoral)\s+(student|candidate|required|only)\b", text):
        flags.append("Possible PhD requirement; verify eligibility")
    if re.search(r"\b(master'?s|graduate students only)\b", text):
        flags.append("Graduate qualification mentioned; verify eligibility")
    if re.search(r"\b(us citizenship|security clearance|active clearance)\b", text):
        flags.append("Citizenship/clearance language: verify requirements")
    if not job.get("description"):
        flags.append("No job description: ranking less reliable")
    return {"job_id": job["id"], "score": score, "components": {k: round(v * WEIGHTS[k]) for k,v in components.items()},
            "matched_skills": matched, "matched_roles": matched_roles,
            "eligibility": eligible, "flags": flags,
            "reason": f"{len(matched)} verified skills referenced; role relevance {round(role * 100)}%; location relevance {round(location_score * 100)}%."}
