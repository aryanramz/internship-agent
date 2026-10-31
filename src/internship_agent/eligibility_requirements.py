"""Bounded, conservative extraction of explicit posting requirements.

This is a controlled English pattern parser, not a general language model or a
legal interpretation engine. Unrecognized mandatory material remains a manual
rule. Evidence is always an original posting span; URLs are inert labels.
"""
from __future__ import annotations

import calendar
from bisect import bisect_right
from datetime import date
import hashlib
import re


MAX_TEXT = 100_000
MAX_NODES = 200
MAX_DEPTH = 6
FIELDS = {
    "enrolled", "returning_student", "work_authorized", "needs_sponsorship",
    "availability", "degree_level", "completed_degrees", "majors", "skills",
    "coursework", "work_locations", "work_modes", "academic_year",
    "completed_academic_years", "residence_country", "graduation", "manual_review",
}
OPS = {"eq", "one_of", "all_of", "date_range", "gte", "gt", "lte", "lt", "term", "interval", "manual"}
DEGREES = {"associate", "bachelor", "master", "doctoral"}
_DEGREE = r"\b(?:associate(?:['’]s)?|bachelor(?:['’]s)?|master(?:['’]s)?|doctoral|doctorate|ph\.?d\.?)\b"
_YEAR = r"(?:freshman|first[- ]year|sophomore|second[- ]year|junior|third[- ]year|senior|fourth[- ]year)"
_MODE = r"(?:on[- ]?site|hybrid|remote)(?![-]\w)"
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTH = "(?:" + "|".join(_MONTHS) + ")"
_DATE = rf"(?:\d{{4}}(?:-\d{{2}}(?:-\d{{2}})?)?|{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|{_MONTH}\s+\d{{4}})"
_COUNTRIES = {
    "united states": "US", "united states of america": "US", "u.s.": "US", "usa": "US", "us": "US",
    "canada": "CA", "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "germany": "DE", "france": "FR", "india": "IN", "australia": "AU", "ireland": "IE",
}
_COUNTRY = "(?:" + "|".join(re.escape(k) for k in sorted(_COUNTRIES, key=len, reverse=True)) + ")"
_TERM = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(20\d{2})\b", re.I)
_HEAD_REQUIRED = re.compile(r"^(?:(?:minimum|basic|required|essential)\s+)?(?:requirements|qualifications|eligibility)(?:\s*[:\-])?$", re.I)
_HEAD_PREFERRED = re.compile(r"^(?:preferred(?:\s+qualifications)?|desired(?:\s+qualifications)?|nice[- ]to[- ]haves?|bonus)(?:\s*[:\-])?$", re.I)


def _get(job, key):
    value = job.get(key, "") if isinstance(job, dict) else getattr(job, key, "")
    if not isinstance(value, str):
        raise ValueError("Posting text fields must be strings")
    return value


def _dates(value):
    value = value.strip().lower()
    if re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
        parts = [int(part) for part in value.split("-")]
        y, m = parts[0], parts[1] if len(parts) > 1 else 1
        lo = date(y, m, parts[2] if len(parts) > 2 else 1)
        hi = date(y, m, parts[2]) if len(parts) > 2 else date(y, m, calendar.monthrange(y, m)[1]) if len(parts) == 2 else date(y, 12, 31)
        return lo, hi
    match = re.fullmatch(rf"({_MONTH})\s+(?:(\d{{1,2}}),?\s+)?(\d{{4}})", value, re.I)
    if not match:
        raise ValueError("Invalid posting date")
    m, day, y = _MONTHS[match[1]], match[2], int(match[3])
    return date(y, m, int(day) if day else 1), date(y, m, int(day) if day else calendar.monthrange(y, m)[1])


def _evidence(source, name, start, end):
    return {"source": name, "start": start, "end": end, "text": source[name][start:end], "reference": source["reference"]}


def _leaf(kind, constraint, strength, evidence, qualifiers=None, issues=None):
    identity = repr((kind, constraint, strength, qualifiers or {}, evidence))
    return {"id": "req_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
            "kind": kind, "strength": strength, "constraint": constraint,
            "qualifiers": qualifiers or {}, "evidence": evidence, "issues": issues or []}


def _manual(strength, evidence, issue):
    return _leaf("manual_review", {"op": "manual"}, strength, evidence, issues=[issue])


def _segments(text):
    # Mask HTML without changing offsets, retaining block/list boundaries.
    masked = re.sub(r"<[^>]*>", lambda m: ("\n" if re.match(r"</?(?:p|li|br|div|h[1-6])\b", m[0], re.I) else " ") + " " * (len(m[0]) - 1), text)
    boundary = re.compile(r"[\n;]+|(?<=[.!?])\s+(?=(?:Must\b|Applicants\b|Candidates\b|You\b|Required\b|Preferred\b|Currently\b|A\s|An\s|The\s|We\s))")
    start = 0
    for match in list(boundary.finditer(masked)) + [None]:
        end = match.start() if match else len(masked)
        value = masked[start:end]
        left = len(value) - len(value.lstrip(" \t\r\n-*•"))
        right = len(value.rstrip())
        if right > left:
            yield start + left, start + right, masked[start + left:start + right]
        start = match.end() if match else len(masked)


def _list(value):
    value = re.sub(r"\s+(?:is|are)\s+(?:required|preferred|desired)\s*[.!]?$", "", value, flags=re.I)
    value = re.sub(r"\s+(?:required|preferred|desired)\s*[.!]?$", "", value, flags=re.I).strip(" .:")
    if re.search(r"\band\b", value, re.I) and re.search(r"\bor\b", value, re.I):
        return None
    parts = [part.strip(" ,.").lower() for part in re.split(r"\s+(?:and|or)\s+|,\s*", value)]
    parts = [re.sub(r"^(?:a|an|the)\s+", "", part) for part in parts if part]
    # Lists cannot smuggle additional predicates or legal/qualification clauses.
    if not parts or len(parts) > 20 or any(len(part) > 100 or re.search(r"\b(?:must|have|be|need|enrolled|authorized|sponsorship|required|clearance|citizen|provide|supply|hold|possess|submit|attend|maintain|related|equivalent|similar|other|including)\b", part) for part in parts):
        return None
    return list(dict.fromkeys(parts))


def _list_constraint(values, original, *, single="eq"):
    if len(values) == 1 and single == "eq":
        return {"op": "eq", "value": values[0]}
    return {"op": "one_of" if re.search(r"\bor\b", original, re.I) else "all_of", "value": values}


def _candidate_prefix(value):
    return bool(re.fullmatch(r"\s*(?:(?:candidates?|applicants?|students?|you)\s+)?(?:(?:must|shall|should|are|is)\s+)?(?:(?:not\s+)?(?:be|remain|have)\s+)?(?:not\s+)?(?:an?\s+)?", value, re.I))


def _parse_clause(text, strength, evidence, term, term_evidence):
    out = []
    covered = []
    alternative_spans = []

    def add(kind, constraint, match, qualifiers=None, extra_evidence=None):
        out.append(_leaf(kind, constraint, strength, evidence + (extra_evidence or []), qualifiers))
        span = match.span() if hasattr(match, "span") else match
        covered.append(span)
        if constraint["op"] in {"one_of", "date_range"}:
            alternative_spans.append(span)

    # Exceptions and conditions change the applicability of the predicate.
    # A matched fragment cannot be enforced while its scope remains unresolved.
    if re.search(r"\b(?:if|unless|except|provided|depending|conditional|subject to)\b", text, re.I):
        return [_manual(strength, evidence, "unsupported_conditional_scope")]

    # A scoped waiver conveys no positive requirement. Mixed material remains
    # visible rather than allowing a waiver to negate an unrelated hard clause.
    waiver = re.search(r"\b(?:not required|not necessary|no (?:\w+\s+){0,4}(?:required|necessary)|do(?:es)? not require|no need (?:for|to))\b", text, re.I)
    if waiver:
        pure = re.fullmatch(r"(?:(?:an?\s+)?[^.!;]{1,120}\s+(?:is|are)\s+not\s+(?:required|necessary)|No\s+[^.!;]{1,120}\s+(?:(?:is|are)\s+)?(?:required|necessary))[.!]?", text, re.I)
        if pure and not re.search(r"\b(?:and|or|but|while|must)\b", text, re.I):
            return []
        return [_manual("ambiguous", evidence, "waived_or_negated_requirement")]

    negated = re.search(r"\b(?:not|never|without)\b", text, re.I)
    simple_negative_enrollment = re.fullmatch(r"\s*(?:candidates?\s+)?(?:must|shall)\s+(?:not\s+be|be\s+not)\s+(?:currently\s+)?enrolled[.!]?\s*", text, re.I)
    negative_sponsorship = re.search(r"\b(?:not\s+(?:need|require)|without)\s+(?:employer\s+|employment\s+)?sponsorship\b", text, re.I)
    if negated and not simple_negative_enrollment and not negative_sponsorship:
        return [_manual(strength, evidence, "ambiguous_negation_scope")]

    # Mixing conjunction and alternatives within one degree list is not a
    # supported simple OR. Never flatten it into a weaker list of alternatives.
    degree_spans = list(re.finditer(_DEGREE, text, re.I))
    if degree_spans:
        degree_text = text[degree_spans[0].start():degree_spans[-1].end()]
        if re.search(r"\bor\b", degree_text, re.I) and re.search(r"\band\b", degree_text, re.I):
            return [_manual(strength, evidence, "ambiguous_mixed_connectors")]
        for first, second in zip(degree_spans, degree_spans[1:]):
            gap = text[first.end():second.start()]
            remainder = re.sub(r"\b(?:degrees?|programs?|students?|or|and|an?|the)\b", " ", gap, flags=re.I)
            if re.search(r"[a-z0-9]", remainder, re.I):
                return [_manual(strength, evidence, "ambiguous_degree_scope")]

    # Citizenship/clearance and unsupported legal language are never automated.
    if re.search(r"\b(?:citizen(?:ship)?|clearance|visa|permanent resident|export control|itar|itar-controlled|security eligibility)\b", text, re.I):
        return [_manual(strength, evidence, "legal_requirement_requires_manual_review")]

    # Mixed-field alternatives require syntax beyond the controlled grammar.
    domains = sum(bool(re.search(pattern, text, re.I)) for pattern in (
        r"enroll|degree|major|graduate|graduation|student|academic|freshman|sophomore|junior|senior",
        r"proficien|experience|skills|knowledge|coursework|courses|references",
        r"authoriz|sponsor|citizen|clearance", r"availab|onsite|on-site|hybrid|remote|reside|located"))
    if re.search(r"\bor\b", text, re.I) and domains > 1:
        return [_manual(strength, evidence, "ambiguous_cross_field_alternative")]

    # Explicit current enrollment is distinct from having completed a degree.
    for match in re.finditer(r"\b(?:(?:currently|presently)\s+)?(?:(?:be|remain|actively)\s+)?(?:(?:not)\s+)?enrolled\b(?:\s+(?:in|at)\s+(?:(?:an?|the)\s+)?(?:accredited\s+)?(?:college|university))?", text, re.I):
        if not _candidate_prefix(text[:match.start()]):
            continue
        negative = bool(re.search(r"\bnot\b", match[0], re.I) or re.search(r"\bnot\s+(?:be\s+)?$", text[:match.start()], re.I))
        add("enrolled", {"op": "eq", "value": not negative}, match)
    pursuing = re.search(r"\b(?:pursuing|working toward(?:s)?)\s+(?:(?:an?|the)\s+)?", text, re.I)
    if pursuing and _candidate_prefix(text[:pursuing.start()]):
        add("enrolled", {"op": "eq", "value": True}, pursuing)
    current_student = re.search(rf"\bcurrent\s+(?:{_DEGREE}\s+)?student\b", text, re.I)
    if current_student and _candidate_prefix(text[:current_student.start()]):
        add("enrolled", {"op": "eq", "value": True}, current_student)

    degree_matches = list(re.finditer(_DEGREE, text, re.I))
    if degree_matches:
        prefix = text[:degree_matches[0].start()]
        bound = re.search(r"\b(?:enrolled\s+in|pursuing|working\s+towards?|(?:have\s+)?completed|earned|hold|holds|have|possess)\s+(?:(?:an?|the|current|accredited|full[- ]time)\s+)*$", prefix, re.I)
        if bound:
            if re.search(r"\b(?:enrolled|pursuing|working)\b", bound[0], re.I):
                if not any(rule["kind"] == "enrolled" for rule in out):
                    bound = None
            elif not _candidate_prefix(prefix[:bound.start()]):
                bound = None
        direct = re.search(r"\b(?:must|shall)\s+be\s+(?:an?\s+)?(?:current\s+)?$", prefix, re.I)
        if direct and not _candidate_prefix(prefix[:direct.start()]):
            direct = None
        bound = bound or direct
        bound = bound or re.fullmatch(r"\s*(?:(?:an?|minimum|required|current)\s+)*", prefix, re.I)
        if not bound:
            return [_manual(strength, evidence, "unbound_education_reference")]
        vals = []
        for match in degree_matches:
            lower = match[0].lower()
            val = "doctoral" if lower.startswith(("doc", "ph")) else re.match(r"[a-z]+", lower)[0]
            if val not in vals:
                vals.append(val)
            covered.append(match.span())
        complete = bool(re.search(r"\b(?:completed|earned|hold|holds|have|possess)\b", text[:degree_matches[0].start()], re.I)) and not re.search(r"\b(?:enrolled|pursuing|working toward)\b", text, re.I)
        kind = "completed_degrees" if complete else "degree_level"
        if not complete and not re.search(r"\b(?:enrolled|pursuing|working toward|program|student)\b", text, re.I):
            # A bare required degree refers to completion, not current enrollment.
            kind = "completed_degrees"
        constraint = _list_constraint(vals, text[degree_matches[0].start():degree_matches[-1].end()], single="all_of" if kind == "completed_degrees" else "eq")
        if kind == "degree_level" and constraint["op"] == "all_of":
            return [_manual(strength, evidence, "ambiguous_program_conjunction")]
        add(kind, constraint, (degree_matches[0].start(), degree_matches[-1].end()))
        major = re.search(r"\b(?:degree|program|major(?:ing)?)\s+in\s+(.+?)(?=\s+(?:and\s+)?(?:must|with|who|expected|graduat|available|return)|[.!]?$)", text, re.I)
        if major:
            vals = _list(major[1])
            if vals:
                add("majors", _list_constraint(vals, major[1], single="all_of"), major)
    else:
        major = re.search(r"\b(?:major(?:ing)?\s+in|majors?\s*:)\s*(.+?)[.!]?$", text, re.I)
        if major and _candidate_prefix(text[:major.start()]) and (vals := _list(major[1])):
            add("majors", _list_constraint(vals, major[1], single="all_of"), major)

    progress = re.search(r"\b(?:completed|finished)\s+(?:(at least|more than|at most|fewer than|exactly)\s+)?([0-8])\s+(?:academic\s+)?years?\b", text, re.I)
    if progress and _candidate_prefix(text[:progress.start()]):
        add("completed_academic_years", {"op": {"at least": "gte", "more than": "gt", "at most": "lte", "fewer than": "lt"}.get((progress[1] or "").lower(), "eq"), "value": int(progress[2])}, progress)
    standing = re.fullmatch(rf"(?:(?:Candidates?|Applicants?|You|Students?)\s+)?(?:(?:must|shall)\s+be\s+|(?:currently|presently)\s+)?(?:(at least|at most|beyond|below|more than|less than)\s+)?(?:an?\s+)?({_YEAR}(?:\s+(?:or|and)\s+(?:an?\s+)?{_YEAR})*)(?:\s+(?:year|student))?[.!]?", text, re.I)
    year_matches = list(re.finditer(rf"\b{_YEAR}\b", text, re.I)) if standing else []
    if year_matches:
        academic = {"freshman": 1, "first-year": 1, "first year": 1, "sophomore": 2, "second-year": 2, "second year": 2, "junior": 3, "third-year": 3, "third year": 3, "senior": 4, "fourth-year": 4, "fourth year": 4}
        vals = list(dict.fromkeys(academic[m[0].lower()] for m in year_matches))
        for match in year_matches:
            covered.append(match.span())
        if standing[1] and len(vals) == 1:
            constraint = {"op": {"at least": "gte", "at most": "lte", "beyond": "gt", "below": "lt", "more than": "gt", "less than": "lt"}[standing[1].lower()], "value": vals[0]}
        else:
            constraint = _list_constraint(vals, text)
        add("academic_year", constraint, standing)

    if re.search(r"\b(?:graduate|graduating|graduation)\b", text, re.I):
        grad = re.search(rf"\b(?:graduate|graduating|graduation(?:\s+date)?)\s*(?:is\s+|of\s+|expected\s+)?(?:between\s+({_DATE})\s+and\s+({_DATE})|(?:from\s+)?({_DATE})\s+(?:through|to)\s+({_DATE})|(on or after|on or before|before|after|by|in)\s+({_DATE}))", text, re.I)
        try:
            if grad and (_candidate_prefix(text[:grad.start()]) or re.fullmatch(r"\s*expected\s+", text[:grad.start()], re.I)):
                if grad[1] or grad[3]:
                    lo = _dates(grad[1] or grad[3])[0]
                    hi = _dates(grad[2] or grad[4])[1]
                    if lo > hi:
                        raise ValueError("Reversed range")
                    constraint = {"op": "date_range", "min": lo.isoformat(), "max": hi.isoformat(), "min_inclusive": True, "max_inclusive": True}
                else:
                    lo, hi = _dates(grad[6])
                    word = grad[5].lower()
                    if word in {"before", "on or before", "by"}:
                        constraint = {"op": "date_range", "max": (lo if word == "before" else hi).isoformat(), "max_inclusive": word != "before"}
                    elif word in {"after", "on or after"}:
                        constraint = {"op": "date_range", "min": (hi if word == "after" else lo).isoformat(), "min_inclusive": word != "after"}
                    else:
                        constraint = {"op": "date_range", "min": lo.isoformat(), "max": hi.isoformat(), "min_inclusive": True, "max_inclusive": True}
                add("graduation", constraint, grad)
        except (ValueError, OverflowError):
            pass

    # Availability and returning status require an explicit posting term.
    available = re.search(r"\b(?:be\s+)?available\b", text, re.I)
    interval = re.search(rf"\b(?:from|between)\s+({_DATE})\s+(?:through|to|and)\s+({_DATE})", text, re.I)
    if available and _candidate_prefix(text[:available.start()]):
        if interval:
            try:
                lo, lo_hi = _dates(interval[1])
                hi_lo, hi = _dates(interval[2])
                if lo != lo_hi or hi != hi_lo or lo > hi:
                    raise ValueError("Imprecise interval")
                add("availability", {"op": "interval", "value": {"start": lo.isoformat(), "end": hi.isoformat()}}, (available.start(), interval.end()), {"start": lo.isoformat(), "end": hi.isoformat()})
            except ValueError:
                pass
        elif term:
            own_seasons = set(m.lower().replace("autumn", "fall") for m in re.findall(r"\b(spring|summer|fall|autumn|winter)\b", text, re.I))
            suffix = re.match(r"\s+(?:to\s+work\s+)?(?:(?:for|during|throughout)\s+)?(?:the\s+)?(?:(?:entire|full|whole)\s+)?(?:(?:spring|summer|fall|autumn|winter)(?:\s+20\d{2})?|internship)\b", text[available.end():], re.I)
            if suffix and (not own_seasons or own_seasons == {term["season"]}):
                add("availability", {"op": "term", "value": dict(term)}, (available.start(), available.end() + suffix.end()), dict(term), term_evidence)
    returning = re.search(r"\b(?:return(?:ing)?\s+to\s+(?:school|university|college|studies)|returning\s+student)\b", text, re.I)
    if returning and term and _candidate_prefix(text[:returning.start()]):
        suffix = re.match(r"\s+after\s+(?:the\s+)?(?:(?:spring|summer|fall|autumn|winter)\s+20\d{2}(?:\s+internship)?|internship)\b", text[returning.end():], re.I)
        add("returning_student", {"op": "eq", "value": True}, (returning.start(), returning.end() + (suffix.end() if suffix else 0)), dict(term), term_evidence)

    authorized = re.search(rf"\b(?:legally\s+)?authorized\s+to\s+work\s+in\s+(?:the\s+)?({_COUNTRY})(?=$|[\s.,;!])", text, re.I)
    if authorized and _candidate_prefix(text[:authorized.start()]):
        country = _COUNTRIES[authorized[1].lower()]
        add("work_authorized", {"op": "eq", "value": True}, authorized, {"country": country})
    if re.search(r"\bsponsor(?:ship|ed|ing)?\b", text, re.I):
        country = re.search(rf"\bin\s+(?:the\s+)?({_COUNTRY})(?=$|[\s.,;!])", text, re.I)
        current = bool(re.search(r"\b(?:now|currently|current|present)\b", text, re.I))
        future = bool(re.search(r"\bfuture\b", text, re.I))
        negative = re.search(r"\b(?:not\s+(?:need|require)|without|no)\s+(?:employer\s+|employment\s+)?sponsorship\b", text, re.I)
        if country and (current or future) and negative and _candidate_prefix(text[:negative.start()]):
            add("needs_sponsorship", {"op": "eq", "value": False}, negative, {"country": _COUNTRIES[country[1].lower()], "timeframe": "both" if current and future else "current" if current else "future"})
            covered.append(country.span())
            covered.extend(m.span() for m in re.finditer(r"\b(?:now|currently|current|present|future)\b", text, re.I))
            alternative_spans.extend(m.span() for m in re.finditer(r"\b(?:now|currently|current|present)\s+or\s+(?:in\s+)?(?:the\s+)?future\b", text, re.I))

    mode_list = rf"{_MODE}(?:\s+(?:or|and)\s+{_MODE})*"
    mode_context = re.search(rf"\b(?:work|working)\s+(?:in\s+(?:an?\s+)?)?{mode_list}\b|\b{mode_list}\s+(?:work|working|position|role)\b", text, re.I)
    modes = list(re.compile(rf"\b{_MODE}\b", re.I).finditer(text, mode_context.start(), mode_context.end())) if mode_context and _candidate_prefix(text[:mode_context.start()]) else []
    if modes:
        vals = list(dict.fromkeys("onsite" if re.match("on", m[0], re.I) else m[0].lower() for m in modes))
        for match in modes:
            covered.append(match.span())
        covered.extend(m.span() for m in re.finditer(r"\b(?:work|working|based|position|role)\b", text, re.I))
        add("work_modes", _list_constraint(vals, text, single="all_of"), (modes[0].start(), modes[-1].end()))
        place = re.search(r"\b(?:in|from|based in)\s+(.+?)(?:[.!]?$)", text[modes[-1].end():], re.I)
        if place:
            value = place[1].strip(" .")
            if len(value) <= 100 and not re.search(r"\b(?:and|or|must|authorized|sponsor|degree)\b", value, re.I):
                add("work_locations", {"op": "all_of", "value": [value.lower()]}, (modes[-1].end() + place.start(), modes[-1].end() + place.end()))
    if not modes and not authorized:
        place = re.search(r"\b(?:work|be\s+based)\s+in\s+(.+?)[.!]?$", text, re.I)
        if place and _candidate_prefix(text[:place.start()]):
            value = place[1].strip(" .")
            if value and len(value) <= 100 and not re.search(r"\b(?:and|or|must|authorized|sponsor|degree)\b", value, re.I):
                add("work_locations", {"op": "all_of", "value": [value.lower()]}, place)
    reside = re.search(rf"\b(?:reside|resident|located|based)\s+in\s+(?:the\s+)?({_COUNTRY})(?=$|[\s.,;!])", text, re.I)
    if reside and _candidate_prefix(text[:reside.start()]):
        add("residence_country", {"op": "eq", "value": _COUNTRIES[reside[1].lower()]}, reside)

    for kind, pattern in (
        ("skills", r"\b(?:proficiency\s+in|proficient\s+in|experience\s+(?:with|in)|knowledge\s+of|skills?\s*(?:in|:))\s+(.+?)[.!]?$"),
        ("coursework", r"\b(?:completed\s+)?(?:coursework|courses?)\s+(?:in\s+)?(.+?)[.!]?$"),
    ):
        match = re.search(pattern, text, re.I)
        if match and _candidate_prefix(text[:match.start()]) and (vals := _list(match[1])):
            add(kind, _list_constraint(vals, match[1], single="all_of"), match)

    # Any material not covered by the bounded grammar must survive the parse.
    if any(not any(start <= match.start() and match.end() <= end for start, end in alternative_spans) for match in re.finditer(r"\bor\b", text, re.I)):
        return [_manual(strength, evidence, "ambiguous_cross_field_alternative")]
    residual = list(text)
    for start, end in covered:
        residual[start:end] = " " * (end - start)
    remaining = "".join(residual)
    current_fields = {"enrolled","degree_level","completed_degrees","academic_year",
                      "completed_academic_years","work_authorized","needs_sponsorship","residence_country"}
    dated_scope = re.search(r"\b(?:by|before|after|during|until|throughout|starting|as of)\b|\bat\s+(?:the\s+)?(?:start|end|beginning|commencement)\b|\b(?:in|for)\s+(?:spring|summer|fall|autumn|winter)\b", remaining, re.I)
    if dated_scope and any(rule["kind"] in current_fields for rule in out):
        return [_manual(strength, evidence, "unsupported_predicate_time_scope")]
    remaining = re.sub(r"\b(?:must|required|requirements?|minimum|qualifications?|candidates?|applicants?|students?|you|we|are|is|be|being|have|has|hold|holds|an?|the|in|at|of|to|for|and|or|either|both|degree|degrees|program|programs|currently|presently|expected|with|as|from|will|should|shall|need|needs|not|completed|earned|possess)\b", " ", remaining, flags=re.I)
    if re.search(r"[a-z0-9]", remaining, re.I) or not out:
        out.append(_manual(strength, evidence, "unsupported_or_ambiguous_requirement"))
    return out


def parse_requirements(job) -> dict:
    """Extract bounded, evidence-bearing rules from a Job or posting mapping."""
    source = {key: _get(job, key) for key in ("description", "title", "location", "work_mode")}
    source["reference"] = _get(job, "job_url")
    if sum(len(value) for value in source.values()) > MAX_TEXT:
        raise ValueError("Posting text limit exceeded")
    tree = {"schema_version": 1, "operator": "all", "children": [], "issues": [], "source": source}
    description = source["description"]
    if not description.strip():
        tree["children"] = [_manual("ambiguous", [_evidence(source, "description", 0, len(description))], "missing_description")]
        tree["issues"].append("missing_description")
        return tree

    # Only a unique, explicit season/year pair in the title or description can
    # qualify relative internship language. Publication/discovery dates are unused.
    terms = []
    term_refs = {}
    segments = list(_segments(description))
    segment_starts = [start for start, _, _ in segments]
    for name in ("title", "description"):
        for match in _TERM.finditer(source[name]):
            if name == "description":
                # A season/year in an award, publication, or company history is
                # not evidence of this internship's term.
                index = bisect_right(segment_starts, match.start()) - 1
                context = segments[index][2] if index >= 0 and match.start() < segments[index][1] else ""
                returning = re.search(r"\b(?:return(?:ing)?\s+to\s+(?:school|university|college|studies)|returning\s+student)\b", context, re.I)
                own_return = returning and _candidate_prefix(context[:returning.start()])
                if not own_return and not re.search(r"\b(?:intern(?:ship)?|available|availability|term|program)\b", context, re.I):
                    continue
            key = (match[1].lower().replace("autumn", "fall"), int(match[2]))
            if key not in terms:
                terms.append(key)
            term_refs.setdefault(key, []).append(_evidence(source, name, match.start(), match.end()))
    term = {"season": terms[0][0], "year": terms[0][1]} if len(terms) == 1 else None
    term_evidence = term_refs.get(terms[0], [])[:1] if term else []
    if len(terms) > 1:
        tree["issues"].append("ambiguous_internship_terms")

    heading = None
    for start, end, text in segments:
        # Qualification headings may prefix an inline first item.
        prefix = re.match(r"^([^:]{1,60}):\s*(.+)$", text)
        if prefix and (_HEAD_REQUIRED.fullmatch(prefix[1]) or _HEAD_PREFERRED.fullmatch(prefix[1])):
            heading = "required" if _HEAD_REQUIRED.fullmatch(prefix[1]) else "preferred"
            start += prefix.start(2)
            text = prefix[2]
        elif _HEAD_REQUIRED.fullmatch(text):
            heading = "required"
            continue
        elif _HEAD_PREFERRED.fullmatch(text):
            heading = "preferred"
            continue
        elif re.fullmatch(r"(?:responsibilities|about (?:us|the (?:role|team))|benefits|what (?:we offer|you(?:'|’)ll do)|compensation)\s*:?", text, re.I):
            heading = None
            continue
        preferred = bool(re.search(r"\b(?:preferred|desired|desirable|nice[- ]to[- ]have|bonus)\b", text, re.I))
        explicit = bool(re.search(r"\b(?:must|requires?|required|requirements?|mandatory|need(?:s)? to|shall|only candidates)\b", text, re.I))
        strength = "preferred" if preferred else "required" if explicit else heading
        if not strength:
            continue
        evidence = [_evidence(source, "description", start, end)]
        if preferred and explicit and re.search(r"\b(?:must|shall|mandatory)\b|(?<!not )\brequire(?:d|s)?\b", text, re.I):
            tree["children"].append(_manual("ambiguous", evidence, "ambiguous_required_preferred_scope"))
            continue
        tree["children"].extend(_parse_clause(text, strength, evidence, term, term_evidence))
        if len(tree["children"]) >= MAX_NODES:
            tree["children"] = [_manual("ambiguous", [_evidence(source, "description", 0, len(description))], "requirement_limit")]
            tree["issues"].append("requirement_limit")
            break

    # Contradictory explicit atomic rules are evidence of uncertainty, not a
    # convenient reliably failed conjunction. Do not resolve employer conflicts.
    by_key = {}
    for leaf in tree["children"]:
        if leaf["strength"] == "required" and leaf["kind"] in {"enrolled", "returning_student", "work_authorized", "needs_sponsorship", "degree_level", "academic_year", "completed_academic_years", "residence_country", "graduation"}:
            by_key.setdefault((leaf["kind"], repr(leaf["qualifiers"])), []).append(leaf)
    for rules in by_key.values():
        conflict = False
        value_sets = []
        academic_values = set(range(1 if rules[0]["kind"] == "academic_year" else 0, 9)) if rules[0]["kind"] in {"academic_year", "completed_academic_years"} else None
        low, high = date.min.toordinal(), date.max.toordinal()
        for rule in rules:
            constraint = rule["constraint"]
            if academic_values is not None:
                op, value = constraint["op"], constraint.get("value")
                if op in {"eq", "one_of"}:
                    academic_values &= set(value if op == "one_of" else [value])
                elif op == "gte":
                    academic_values = {v for v in academic_values if v >= value}
                elif op == "gt":
                    academic_values = {v for v in academic_values if v > value}
                elif op == "lte":
                    academic_values = {v for v in academic_values if v <= value}
                elif op == "lt":
                    academic_values = {v for v in academic_values if v < value}
            if constraint["op"] in {"eq", "one_of"}:
                value_sets.append(set(constraint["value"] if constraint["op"] == "one_of" else [constraint["value"]]))
            if constraint["op"] == "date_range":
                if "min" in constraint:
                    low = max(low, date.fromisoformat(constraint["min"]).toordinal() + (not constraint["min_inclusive"]))
                if "max" in constraint:
                    high = min(high, date.fromisoformat(constraint["max"]).toordinal() - (not constraint["max_inclusive"]))
        if value_sets:
            conflict = not set.intersection(*value_sets)
        if academic_values is not None and not academic_values:
            conflict = True
        conflict = conflict or low > high
        if conflict:
            tree["issues"].append("conflicting_requirements")
            for rule in rules:
                rule["strength"] = "ambiguous"
                rule["issues"].append("conflicting_requirements")
    if not tree["children"]:
        tree["issues"].append("no_explicit_requirements")
    validate_requirements(tree)
    return tree


def validate_requirements(tree) -> None:
    """Reject malformed, cyclic or oversized rule data; never dereference URLs."""
    if not isinstance(tree, dict) or type(tree.get("schema_version")) is not int or tree.get("schema_version") != 1 or tree.get("operator") != "all":
        raise ValueError("Invalid requirement schema")
    source = tree.get("source")
    if not isinstance(source, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in source.items()) or sum(map(len, source.values())) > MAX_TEXT:
        raise ValueError("Invalid requirement source or text limit")
    ids, seen = set(), set()
    count = 0

    def walk(node, depth, root=False):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH or id(node) in seen or not isinstance(node, dict):
            raise ValueError("Requirement shape or node/depth limit exceeded")
        seen.add(id(node))
        if not isinstance(node.get("issues"), list) or any(not isinstance(issue, str) or len(issue) > 200 for issue in node["issues"]):
            raise ValueError("Invalid requirement issues")
        if not root:
            identifier = node.get("id")
            if not isinstance(identifier, str) or not identifier or len(identifier) > 100 or identifier in ids:
                raise ValueError("Invalid or duplicate requirement ID")
            ids.add(identifier)
            if node.get("strength") not in {"required", "preferred", "ambiguous"}:
                raise ValueError("Invalid requirement strength")
            quals = node.get("qualifiers")
            if not isinstance(quals, dict) or len(quals) > 12:
                raise ValueError("Invalid requirement qualifiers")
            for key, value in quals.items():
                if key not in {"country", "season", "year", "start", "end", "after", "valid_from", "valid_until", "timeframe"} or type(value) not in {str, int, bool}:
                    raise ValueError("Invalid requirement qualifier")
                if key == "country" and (not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}", value)):
                    raise ValueError("Invalid requirement country")
                if key == "season" and value not in {"spring", "summer", "fall", "winter"}:
                    raise ValueError("Invalid requirement season")
                if key == "year" and (type(value) is not int or not 1900 <= value <= 2200):
                    raise ValueError("Invalid requirement year")
                if key == "timeframe" and value not in {"current", "future", "both"}:
                    raise ValueError("Invalid requirement timeframe")
                if key in {"start", "end", "after", "valid_from", "valid_until"}:
                    try:
                        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                            raise ValueError("Invalid date")
                        date.fromisoformat(value)
                    except ValueError:
                        raise ValueError("Invalid requirement qualifier date") from None
            evidence = node.get("evidence")
            if not isinstance(evidence, list) or not evidence or len(evidence) > 20:
                raise ValueError("Invalid requirement evidence")
            for item in evidence:
                if not isinstance(item, dict) or set(item) != {"source", "start", "end", "text", "reference"}:
                    raise ValueError("Invalid requirement evidence")
                name, start, end = item["source"], item["start"], item["end"]
                if not isinstance(name, str) or name not in source or type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(source[name]) or source[name][start:end] != item["text"] or not isinstance(item["reference"], str) or len(item["reference"]) > MAX_TEXT:
                    raise ValueError("Invalid requirement evidence span")
        if "operator" in node:
            if node["operator"] not in {"all", "any"} or "kind" in node or "constraint" in node or not isinstance(node.get("children"), list) or (not root and not node["children"]):
                raise ValueError("Invalid requirement group")
            for child in node["children"]:
                walk(child, depth + 1)
        else:
            if "children" in node or node.get("kind") not in FIELDS:
                raise ValueError("Invalid requirement kind")
            constraint = node.get("constraint")
            if not isinstance(constraint, dict) or constraint.get("op") not in OPS or set(constraint) - {"op", "value", "min", "max", "min_inclusive", "max_inclusive"}:
                raise ValueError("Invalid requirement constraint")
            op, kind = constraint["op"], node["kind"]
            boolean_fields = {"enrolled", "returning_student", "work_authorized", "needs_sponsorship", "availability"}
            list_fields = {"completed_degrees", "majors", "skills", "coursework", "work_locations", "work_modes"}
            academic_fields = {"academic_year", "completed_academic_years"}
            if kind in boolean_fields and (op not in ({"eq", "term", "interval"} if kind == "availability" else {"eq"}) or (op == "eq" and type(constraint.get("value")) is not bool)):
                raise ValueError("Invalid boolean requirement")
            if kind in list_fields:
                values = constraint.get("value")
                if op not in {"one_of", "all_of"} or not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in values):
                    raise ValueError("Invalid list requirement")
                if kind == "completed_degrees" and any(v not in DEGREES for v in values):
                    raise ValueError("Invalid completed degree requirement")
                if kind == "work_modes" and any(v not in {"remote", "hybrid", "onsite"} for v in values):
                    raise ValueError("Invalid work mode requirement")
            if kind in {"degree_level", "residence_country"}:
                values = constraint.get("value") if op == "one_of" else [constraint.get("value")]
                if op not in {"eq", "one_of"} or not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
                    raise ValueError("Invalid scalar requirement")
                if kind == "degree_level" and any(v not in DEGREES for v in values):
                    raise ValueError("Invalid degree requirement")
                if kind == "residence_country" and any(not re.fullmatch(r"[A-Z]{2}", v) for v in values):
                    raise ValueError("Invalid residence requirement")
            if kind in academic_fields:
                values = constraint.get("value") if op == "one_of" else [constraint.get("value")]
                if op not in {"eq", "one_of", "gte", "gt", "lte", "lt"} or not isinstance(values, list) or not values or any(type(v) is not int or not (1 if kind == "academic_year" else 0) <= v <= 8 for v in values):
                    raise ValueError("Invalid academic requirement")
            if kind == "work_authorized" and "country" not in node["qualifiers"]:
                raise ValueError("Work authorization requires a country")
            if kind == "needs_sponsorship" and not {"country", "timeframe"} <= node["qualifiers"].keys():
                raise ValueError("Sponsorship requires country and timeframe")
            if kind in {"availability", "returning_student"}:
                quals = node["qualifiers"]
                if not ({"season", "year"} <= quals.keys() or {"start", "end"} <= quals.keys()):
                    raise ValueError("Student term requires explicit dates")
            if kind == "graduation" and op != "date_range":
                raise ValueError("Invalid graduation requirement")
            if kind == "manual_review" and op != "manual":
                raise ValueError("Invalid manual requirement")
            if op == "manual":
                if kind != "manual_review" or set(constraint) != {"op"}:
                    raise ValueError("Invalid manual requirement")
            elif op == "date_range":
                if kind != "graduation" or not ({"min", "max"} & constraint.keys()) or "value" in constraint:
                    raise ValueError("Invalid date requirement")
                for bound in ("min", "max"):
                    if bound in constraint:
                        if not isinstance(constraint[bound], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", constraint[bound]) or type(constraint.get(bound + "_inclusive")) is not bool:
                            raise ValueError("Invalid date requirement boundary")
                        try:
                            date.fromisoformat(constraint[bound])
                        except ValueError:
                            raise ValueError("Invalid date requirement boundary") from None
                if "min" in constraint and "max" in constraint and constraint["min"] > constraint["max"]:
                    raise ValueError("Invalid date requirement interval")
            elif op in {"term", "interval"}:
                value = constraint.get("value")
                if kind != "availability" or not isinstance(value, dict):
                    raise ValueError("Invalid availability requirement")
                if op == "term":
                    if set(value) != {"season", "year"} or value["season"] not in {"spring", "summer", "fall", "winter"} or type(value["year"]) is not int or not 1900 <= value["year"] <= 2200:
                        raise ValueError("Invalid availability term")
                else:
                    if set(value) != {"start", "end"}:
                        raise ValueError("Invalid availability interval")
                    try:
                        start, end = date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
                    except (ValueError, TypeError):
                        raise ValueError("Invalid availability interval") from None
                    if start > end:
                        raise ValueError("Invalid availability interval")
            else:
                value = constraint.get("value")
                if set(constraint) != {"op", "value"}:
                    raise ValueError("Invalid atomic requirement")
                if op in {"one_of", "all_of"}:
                    if not isinstance(value, list) or not value or len(value) > 20 or any(type(v) not in {str, int, bool} for v in value):
                        raise ValueError("Invalid requirement alternatives")
                elif type(value) not in {str, int, bool}:
                    raise ValueError("Invalid requirement value")
                if op in {"gte", "gt", "lte", "lt"} and (kind not in {"academic_year", "completed_academic_years"} or type(value) is not int or not 0 <= value <= 8):
                    raise ValueError("Invalid academic requirement")
    walk(tree, 0, True)
