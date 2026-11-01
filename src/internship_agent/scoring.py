"""Explainable, deterministic profile-fit scoring, not a hiring probability."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .ranking_config import DEFAULT_WEIGHTS

WEIGHTS = DEFAULT_WEIGHTS.copy()
INTERN = re.compile(r"\b(intern(ship)?|co[- ]?op|summer analyst)\b", re.I)
SENIOR = re.compile(r"\b(staff|principal|senior|sr\.|director)\b", re.I)


def _contains(text: str, phrase: str) -> bool:
    # Prevent matching e.g. IAM within 'William', or Java within JavaScript.
    pat = r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)"
    return bool(re.search(pat, text.lower()))


def _role_score(title: str, roles: list[str]) -> tuple[float, list[str]]:
    from .role_taxonomy import role_match
    match=role_match(title,roles)
    return match['unit'],match['matched_targets']


def _freshness(value, now):
    if not isinstance(value,str) or not value.strip():
        return .35,False
    try:
        try:
            dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:
            dt=parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        if dt>now:
            return .35,False
        days=(now-dt).days
        return (1. if days<=14 else .65 if days<=45 else .2),True
    except (ValueError,TypeError,OverflowError,IndexError):
        return .35,False



def evaluate(job: dict, profile: dict, *, as_of: datetime | None = None) -> dict:
    from .ranking_config import configuration
    config=configuration(profile)
    now=as_of if as_of is not None else datetime.now(timezone.utc)
    return _evaluate(job,config,now)


def _evaluate(job: dict, config: dict, now: datetime, *, explain=True) -> dict:
    """Invocation-local prepared profile; compact scoring precedes selection."""
    from .role_taxonomy import role_match
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Ranking requires a timezone-aware clock")
    weights=config['weights']
    preferences=config['preferences']
    missing=[]
    effects={key:[] for key in weights}
    title = str(job["title"])
    description = str(job.get("description") or "")
    text = " ".join([title, description, str(job.get("location", ""))]).lower()
    role_detail=role_match(title,config['roles'])
    role,matched_roles=role_detail['unit'],role_detail['matched_targets']
    skills = config["skills"]
    matched = [x for x in skills if _contains(text, x)]
    skill_score = min(1., len(matched) / min(7, max(3, len(skills))))

    indices=config['experience_indices']
    if preferences['use_experience']:
        corroborated=sum(bool(indices.get(skill)) for skill in matched)
        experience_score=corroborated/max(1,len(matched))
        skill_score=.8*skill_score+.2*experience_score
        effects['skills'].append('Configured experience corroboration: 80% skill coverage, 20% corroborated matches.')
    loc = f'{job.get("location", "")} {job.get("work_mode", "")}'.lower()
    prefs = config["locations"]
    location_matched = any(_contains(loc, x) for x in prefs)
    remote = _contains(loc,"remote")
    location_score = 1. if location_matched else (.8 if remote and "Remote" in prefs else .15)

    mode=str(job.get('work_mode','')).strip().casefold()
    mode={'on-site':'onsite','on site':'onsite','on_site':'onsite'}.get(mode,mode)
    mode_source='work_mode'
    if mode not in {'remote','hybrid','onsite'}:
        mode='remote' if _contains(str(job.get('location','')),'remote') else ''
        mode_source='inferred_from_location' if mode else 'unknown'
    if preferences['work_modes']:
        location_score=1. if mode in preferences['work_modes'] else .15
        effects['location'].append('Configured work-mode preference replaces location matching.')
    if mode in preferences['avoid_work_modes'] or any(_contains(loc,v) for v in preferences['avoid_locations']):
        location_score=0.
        effects['location'].append('Avoided work mode/location; fit preference only, not eligibility.')
    freshness,date_known=_freshness(job.get('published_at'),now)
    compensation_score=(.8 if job.get('compensation') else .4) if preferences['prefer_compensation'] else .5
    if not preferences['prefer_compensation']:
        effects['compensation'].append('Compensation presence preference disabled; neutral contribution.')
    preferred_employers=config['employers']
    company=str(job.get('company','')).casefold()
    employer_score=1. if company in [v.casefold() for v in preferred_employers] else .5
    if company in [v.casefold() for v in preferences['avoid_employers']]:
        employer_score=0.
        effects['employer'].append('Employer is avoided; fit preference only.')
    if config['roles']:
        effects['role'].append('Target roles compared with title-only taxonomy; adjacency is inferred relevance.')
    if prefs and not preferences['work_modes']:
        effects['location'].append('Profile preferred locations compared with posting location/work mode.')
    if preferred_employers:
        effects['employer'].append('Exact case-insensitive preferred employer matching.')
    for key,known in (('title',bool(title.strip())),('description',bool(description.strip())),
                      ('publication_date',date_known),('location',bool(str(job.get('location','')).strip())),
                      ('work_mode',mode_source=='work_mode' and bool(mode)),
                      ('compensation',bool(job.get('compensation')))):
        if not known:
            missing.append(key)
    if preferences['use_experience'] and not any(config['experience']):
        missing.append('profile_experience')
    if not skills:
        missing.append('profile_skills')
    if not config['roles']:
        missing.append('target_roles')

    components = dict(role=role, skills=skill_score, location=location_score, recency=freshness,
                      compensation=compensation_score, employer=employer_score)
    score = round(sum(weights[k] * components[k] for k in weights))
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
    report={"job_id": job["id"], "score": score, "components": {k: round(v * weights[k]) for k,v in components.items()},
            "matched_skills": matched, "matched_roles": matched_roles,
            "eligibility": eligible, "flags": flags,
            "reason": f"{len(matched)} profile skills referenced; role relevance {round(role * 100)}%; location relevance {round(location_score * 100)}%."}

    if not explain:
        return report
    reference_count=sum(len(indices.get(skill,[])) for skill in matched)
    experience_matches=[]
    for skill in matched:
        for i in indices.get(skill,[]):
            if len(experience_matches)<100:
                experience_matches.append({'skill':skill,'experience_index':i})
    explanation=dict(schema_version=1,score_kind='heuristic_fit',analysis='deterministic_only',
        as_of=now.isoformat(),eligibility='not_assessed_by_fit',weights=weights,units=components,
        contributions={key:round(weights[key]*value,4) for key,value in components.items()},
        rounding='Score rounds the summed raw contributions; displayed rounded components may differ.',
        role=role_detail,experience_matches=experience_matches,experience_matches_total=reference_count,
        experience_matches_truncated=reference_count>100,preference_effects=effects,
        missing_information=missing,confidence='low' if not description.strip() or len(description.split())<8 else 'limited' if missing else 'supported',
        observed_evidence={'skills':[{'skill':skill,'sources':[key for key in ('title','description','location') if _contains(str(job.get(key,'')),skill)]} for skill in matched],
                           'work_mode':mode,'work_mode_source':mode_source},
        limitations=['Heuristic fit is not eligibility or hiring probability.',
                     'Profile facts are supplied by the operator, not independently verified.',
                     'Keyword occurrences do not establish proficiency or requirement strength.',
                     'Confidence describes input completeness, not calibrated accuracy.'])
    report['ranking_explanation']=explanation
    return report
