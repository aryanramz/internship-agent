"""Fictional deterministic eligibility matrices, independent of fit scoring."""
from datetime import date
import hashlib
import json

import pytest


AS_OF = date(2030, 1, 15)


def fact(field, value, *, verified=True, status="known", qualifiers=None, id=None):
    return {"id": id or "fact-"+field, "field": field, "value": value, "status": status,
            "provenance": {"kind": "user_declared", "reference": "Fictional declaration", "verified": verified},
            "qualifiers": qualifiers or {}}


def profile(*facts):
    return {"profile_version": 2, "candidate_facts": list(facts)}


def requirement(kind, op="eq", value=True, *, strength="required", qualifiers=None, **bounds):
    text = "Fictional requirement: " + kind + " " + op + " " + json.dumps(value)
    constraint = {"op": op, **bounds}
    if value is not None:
        constraint["value"] = value
    if kind == "graduation" and op in {"gte","gt","lte","lt"}:
        side = "min" if op in {"gte","gt"} else "max"
        constraint = {"op":"date_range",side:value,side+"_inclusive":op in {"gte","lte"}}
    if kind == "availability" and op in {"term","interval"} and qualifiers is None:
        qualifiers = dict(value)
    return {"id": hashlib.sha256(text.encode()).hexdigest()[:24], "kind": kind, "strength": strength,
            "constraint": constraint, "qualifiers": qualifiers or {}, "issues": [],
            "evidence": [{"source": "description", "start": 0, "end": len(text), "text": text,
                          "reference": "https://example.com/jobs/fixture"}]}


def group(operator, *children, strength="required"):
    return {"id": "group-"+operator, "operator": operator, "children": list(children),
            "strength": strength, "qualifiers": {}, "issues": [], "evidence": children[0]["evidence"] if children else []}


def assess(candidate, *requirements):
    from internship_agent.eligibility import evaluate_requirements
    from internship_agent.eligibility_profile import normalize_profile
    # These are explicit structured requirement records; parser anchoring has its
    # own evidence tests. They are not inferred from profile/test metadata.
    children = json.loads(json.dumps(requirements))
    evidence = []
    def anchor(node):
        for item in node.get("evidence",[]):
            if item["text"] not in evidence:
                evidence.append(item["text"])
        for child in node.get("children",[]):
            anchor(child)
    for child in children:
        anchor(child)
    source = "\n".join(evidence)
    def offsets(node):
        for item in node.get("evidence",[]):
            item["start"] = source.index(item["text"])
            item["end"] = item["start"]+len(item["text"])
        for child in node.get("children",[]):
            offsets(child)
    for child in children:
        offsets(child)
    tree = {"schema_version": 1, "operator": "all", "children": children, "issues": [],
            "source": {"reference": "https://example.com/jobs/fixture", "description":source, "title":""}}
    return evaluate_requirements(normalize_profile(candidate), tree, as_of=AS_OF)


@pytest.mark.parametrize("value,expected", [(True,"eligible"), (False,"ineligible")])
def test_verified_explicit_enrollment(value, expected):
    report = assess(profile(fact("enrolled",value)), requirement("enrolled"))
    assert report["outcome"] == expected
    assert report["rules"][0]["evidence"]
    assert report["rules"][0]["candidate_facts"][0]["id"] == "fact-enrolled"


@pytest.mark.parametrize("facts", [[], [fact("enrolled",False,verified=False)],
    [fact("enrolled",None,status="unknown")],
    [fact("enrolled",True,id="one"),fact("enrolled",False,id="two")]])
def test_missing_unverified_unknown_and_conflicting_facts_are_uncertain(facts):
    assert assess(profile(*facts),requirement("enrolled"))["outcome"] == "uncertain"


def test_preferred_mismatch_does_not_disqualify():
    report = assess(profile(fact("enrolled",True),fact("degree_level","bachelor")),
                    requirement("enrolled"), requirement("degree_level",value="master",strength="preferred"))
    assert report["outcome"] == "eligible"


def test_numeric_academic_alternatives_preserve_types():
    assert assess(profile(fact("academic_year",3)),
                  requirement("academic_year","one_of",[3,4]))["outcome"] == "eligible"


@pytest.mark.parametrize("field,qualifiers,required", [
    ("enrolled",{"timeframe":"future"},{}),
    ("work_authorized",{"country":"US","timeframe":"future"},{"country":"US"}),
])
def test_future_declaration_does_not_prove_current_status(field,qualifiers,required):
    assert assess(profile(fact(field,True,qualifiers=qualifiers)),
                  requirement(field,qualifiers=required))["outcome"] == "uncertain"


def test_optional_unknowns_and_satisfied_or_alternatives_are_not_material_gaps():
    report = assess(profile(fact("enrolled",True)),
        group("any",requirement("enrolled"),requirement("degree_level",value="master")),
        requirement("skills","all_of",["Python"],strength="preferred"))
    assert report["outcome"] == "eligible"
    assert report["missing_information"] == []
    assert report["manual_verification"] == []


def test_or_with_unknown_alternative_is_uncertain_and_known_match_satisfies():
    any_rule = group("any",requirement("enrolled"),requirement("degree_level",value="master"))
    assert assess(profile(fact("enrolled",False)), any_rule)["outcome"] == "uncertain"
    assert assess(profile(fact("enrolled",True)), any_rule)["outcome"] == "eligible"
    assert assess(profile(fact("enrolled",False),fact("degree_level","bachelor")), any_rule)["outcome"] == "ineligible"


def test_conflicting_employer_requirements_are_uncertain():
    assert assess(profile(fact("degree_level","bachelor")), requirement("degree_level",value="bachelor"),
                  requirement("degree_level",value="master"))["outcome"] == "uncertain"


def test_numeric_alternative_conflicts_and_nested_or_conjunctions_are_uncertain():
    assert assess(profile(fact("academic_year",3)),requirement("academic_year","one_of",[3,4]),
                  requirement("academic_year",value=1))["outcome"] == "uncertain"
    choice = group("any",group("all",requirement("degree_level",value="bachelor"),
                   requirement("degree_level",value="master")),requirement("enrolled"))
    assert assess(profile(fact("degree_level","bachelor"),fact("enrolled",False)),choice)["outcome"] == "uncertain"


@pytest.mark.parametrize("graduation,op,bound,expected", [
    ("2031-05-15","gte","2031-05-15","eligible"),
    ("2031-05-15","gt","2031-05-15","ineligible"),
    ("2031-05","gte","2031-05-15","uncertain"),
    ("2031-05","gte","2031-05-01","eligible"),
    ("2031-05","lt","2031-05-01","ineligible"),
])
def test_date_precision_and_exclusive_boundaries(graduation,op,bound,expected):
    assert assess(profile(fact("graduation",graduation)),requirement("graduation",op,value=bound))["outcome"] == expected


def test_completed_degree_is_not_inferred_from_current_program():
    assert assess(profile(fact("degree_level","bachelor")),requirement("completed_degrees","one_of",["bachelor"]))["outcome"] == "uncertain"


def test_authorization_is_exact_verified_country_declaration_not_legal_inference():
    rule = requirement("work_authorized",qualifiers={"country":"US"})
    assert assess(profile(fact("work_authorized",True,qualifiers={"country":"CA"})),rule)["outcome"] == "uncertain"
    assert assess(profile(fact("work_authorized",False,qualifiers={"country":"US"})),rule)["outcome"] == "ineligible"
    assert assess(profile(fact("work_authorized",True,qualifiers={"country":"US"})),rule)["outcome"] == "eligible"


def test_expired_fact_and_no_mandatory_requirements_are_uncertain():
    assert assess(profile(fact("enrolled",True,qualifiers={"valid_until":"2029-12-31"})),requirement("enrolled"))["outcome"] == "uncertain"
    assert assess(profile()) ["outcome"] == "uncertain"


def test_repeated_result_stable_and_no_unrelated_profile_data():
    raw = profile(fact("enrolled",True))
    raw.update(name="PRIVATE CONTACT",email="private@example.com",notes="DO NOT EMIT")
    first = assess(raw,requirement("enrolled"))
    assert first == assess(raw,requirement("enrolled"))
    assert "PRIVATE" not in json.dumps(first) and "private@example" not in json.dumps(first)


@pytest.mark.parametrize("available,expected", [(True,"eligible"),(False,"ineligible")])
def test_exact_explicit_availability_term(available, expected):
    term = {"season":"summer","year":2031}
    assert assess(profile(fact("availability",available,qualifiers=term)),
                  requirement("availability","term",term))["outcome"] == expected


@pytest.mark.parametrize("value,expected", [(True,"eligible"),(False,"ineligible")])
def test_returning_student_uses_explicit_matching_term(value, expected):
    term = {"season":"summer","year":2031}
    assert assess(profile(fact("returning_student",value,qualifiers=term)),
                  requirement("returning_student",qualifiers=term))["outcome"] == expected


def test_unqualified_returning_status_and_other_year_do_not_prove_returning():
    rule = requirement("returning_student",qualifiers={"season":"summer","year":2031})
    assert assess(profile(fact("returning_student",True)),rule)["outcome"] == "uncertain"
    assert assess(profile(fact("returning_student",False,qualifiers={"season":"summer","year":2030})),rule)["outcome"] == "uncertain"


def test_partial_availability_needs_verification_but_explicit_negative_overlap_conflicts():
    interval = {"start":"2031-05-15","end":"2031-08-31"}
    positive = fact("availability",True,qualifiers={"start":"2031-06-01","end":"2031-08-31"})
    rule = requirement("availability","interval",interval)
    assert assess(profile(positive),rule)["outcome"] == "uncertain"
    negative = fact("availability",False,id="unavailable",qualifiers={"start":"2031-05-15","end":"2031-05-31"})
    assert assess(profile(positive,negative),rule)["outcome"] == "ineligible"


@pytest.mark.parametrize("field,values,required,expected", [
    ("majors",["Computer Science"],["computer science","electrical engineering"],"eligible"),
    ("majors",["economics"],["computer science"],"ineligible"),
    ("majors",["Novel Interdisciplinary Program"],["computer science"],"uncertain"),
    ("skills",["Python"],["SQL"],"uncertain"),
    ("coursework",["databases"],["networks"],"uncertain"),
    ("work_modes",["remote"],["onsite"],"ineligible"),
    ("work_locations",["Boston, MA"],["Boston"],"uncertain"),
    ("completed_degrees",["bachelor"],["master"],"ineligible"),
])
def test_explicit_sets_without_invented_skill_or_geography_negatives(field,values,required,expected):
    assert assess(profile(fact(field,values)),requirement(field,"one_of",required))["outcome"] == expected


@pytest.mark.parametrize("year,expected", [(1,"ineligible"),(2,"eligible"),(3,"eligible")])
def test_academic_standing_minimum(year, expected):
    assert assess(profile(fact("academic_year",year)),requirement("academic_year","gte",2))["outcome"] == expected


def test_conflicting_graduation_windows_are_uncertain():
    assert assess(profile(fact("graduation","2031-05")),
                  requirement("graduation","gte","2031-06-01"),
                  requirement("graduation","lt","2031-05-01"))["outcome"] == "uncertain"
