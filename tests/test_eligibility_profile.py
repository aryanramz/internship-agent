"""Offline profile normalization, using fictional eligibility declarations only."""
from copy import deepcopy
from datetime import date
import json

import pytest

from internship_agent.eligibility_profile import date_bounds, normalize_profile


def profile(*facts):
    return {"profile_version": 2, "candidate_facts": list(facts)}


def fact(field="enrolled", value=True, **extra):
    return {"field": field, "value": value, **extra}


@pytest.mark.parametrize("value, expected", [
    ("2028", (date(2028, 1, 1), date(2028, 12, 31))),
    ("2028-02", (date(2028, 2, 1), date(2028, 2, 29))),
    ("2027-02", (date(2027, 2, 1), date(2027, 2, 28))),
    ("2000-02-29", (date(2000, 2, 29), date(2000, 2, 29))),
    ("9999-12", (date(9999, 12, 1), date(9999, 12, 31))),
])
def test_partial_dates_preserve_calendar_precision(value, expected):
    assert date_bounds(value) == expected


@pytest.mark.parametrize("value", ["1900-02-29", "2028-2", "2028-02-30", "2028-13", "0000", "28", True, 2028, None])
def test_invalid_dates_fail_without_echoing_input(value):
    with pytest.raises(ValueError, match="Invalid eligibility date"):
        date_bounds(value)


def test_normalization_defaults_are_stable_json_and_drop_contact_information():
    raw = {**profile(fact()), "name": "Fictional Student", "email": "fiction@example.org"}
    saved = deepcopy(raw)
    result = normalize_profile(raw)
    assert result == {"schema_version": 2, "source_version": 2, "facts": [{
        "id": "fact-001", "field": "enrolled", "value": True, "status": "known",
        "provenance": {"kind": "unknown", "reference": None, "verified": False}, "qualifiers": {},
    }], "warnings": []}
    assert json.loads(json.dumps(result)) == result
    assert raw == saved
    assert normalize_profile(raw) == result


def test_verified_fact_preserves_explicit_source_without_dereferencing():
    result = normalize_profile(profile(fact("work_authorized", True, id="permit", qualifiers={"country": "us"},
        provenance={"kind": "verified_document", "reference": "https://example.invalid/no-fetch", "verified": True})))
    assert result["facts"][0]["qualifiers"] == {"country": "US"}
    assert result["facts"][0]["provenance"] == {
        "kind": "verified_document", "reference": "https://example.invalid/no-fetch", "verified": True}


@pytest.mark.parametrize("value, expected", [
    ("2028-02", {"earliest": "2028-02-01", "latest": "2028-02-29"}),
    ({"earliest": "2027", "latest": "2028-05"}, {"earliest": "2027-01-01", "latest": "2028-05-31"}),
])
def test_graduation_has_inclusive_bounds(value, expected):
    assert normalize_profile(profile(fact("graduation", value)))["facts"][0]["value"] == expected


@pytest.mark.parametrize("field,value", [
    ("enrolled", False), ("returning_student", True), ("degree_level", "bachelor"),
    ("completed_degrees", ["associate", "bachelor"]), ("academic_year", 1),
    ("completed_academic_years", 0), ("residence_country", "ca"),
    ("work_modes", ["remote", "hybrid", "onsite"]), ("skills", ["Python"]),
    ("majors", ["Computer Science"]), ("coursework", ["Algorithms"]),
    ("work_locations", ["Example City"]),
])
def test_supported_fact_types(field, value):
    output = normalize_profile(profile(fact(field, value)))["facts"][0]
    assert output["status"] == "known"
    assert output["value"] == ("CA" if field == "residence_country" else value)


@pytest.mark.parametrize("item", [
    fact("enrolled", "yes"), fact("enrolled", 1), fact("academic_year", True),
    fact("academic_year", 0), fact("completed_academic_years", 9), fact("degree_level", "B.S."),
    fact("completed_degrees", ["university"]), fact("skills", "Python"), fact("skills", [True]),
    fact("skills", [""]), fact("work_modes", ["anywhere"]), fact("residence_country", "USA"),
    fact("graduation", {"earliest": "2029", "latest": "2028"}),
    fact("email", "fiction@example.org"), fact("enrolled", True, status="unknown"),
    fact("enrolled", False, status="conflicting"), fact("enrolled", None, status="known"),
    fact("enrolled", True, status="certain"), fact("enrolled", True, id=""),
    fact("enrolled", True, provenance={"kind": "unknown", "verified": True, "reference": "label"}),
    fact("enrolled", True, provenance={"kind": "user_declared", "verified": True}),
    fact("enrolled", True, provenance={"kind": "web", "verified": False}),
    fact("enrolled", True, provenance={"verified": "true"}),
    fact("enrolled", True, qualifiers={"country": "United States"}),
    fact("enrolled", True, qualifiers={"year": True}),
    fact("enrolled", True, qualifiers={"year": 0}),
    fact("enrolled", True, qualifiers={"after": "2028-05"}),
    fact("enrolled", True, qualifiers={"valid_from": "2029-01-01", "valid_until": "2028-01-01"}),
    fact("enrolled", True, qualifiers={"timeframe": "yesterday"}),
    fact("enrolled", True, qualifiers={"unexpected": True}),
])
def test_malformed_fact_is_rejected(item):
    with pytest.raises(ValueError):
        normalize_profile(profile(item))


@pytest.mark.parametrize("field", ["work_authorized", "needs_sponsorship"])
def test_authorization_known_boolean_requires_explicit_country(field):
    with pytest.raises(ValueError):
        normalize_profile(profile(fact(field, True)))
    assert normalize_profile(profile(fact(field, None)))["facts"][0]["status"] == "unknown"


@pytest.mark.parametrize("qualifiers", [{"season": "summer", "year": 2028}, {"start": "2028-06-01", "end": "2028-08-31"}])
def test_availability_requires_explicit_term_or_complete_interval(qualifiers):
    output = normalize_profile(profile(fact("availability", False, qualifiers=qualifiers)))
    assert output["facts"][0]["qualifiers"] == qualifiers


@pytest.mark.parametrize("qualifiers", [{}, {"season": "summer"}, {"year": 2028}, {"start": "2028-06-01"},
    {"start": "2028-08-31", "end": "2028-06-01"}, {"season": "Summer", "year": 2028, "end": "2028-08-31"}])
def test_incomplete_or_invalid_term_qualification_is_rejected(qualifiers):
    with pytest.raises(ValueError):
        normalize_profile(profile(fact("availability", True, qualifiers=qualifiers)))


def test_unknown_and_conflicting_facts_remain_valueless():
    result = normalize_profile(profile({"field": "skills"}, fact("enrolled", None, status="conflicting")))
    assert [(x["status"], x["value"]) for x in result["facts"]] == [("unknown", None), ("conflicting", None)]


def test_legacy_is_unverified_in_memory_and_does_not_infer_location_or_degree():
    raw = {"name": "Fictional Student", "location": "Example City", "preferred_locations": ["Remote"],
        "education": {"school": "Example College", "degree": "Bachelor of Computing", "graduation": "May 2028"},
        "skills": ["Python"], "eligibility": {"us_work_authorization": True, "needs_sponsorship": False,
        "current_undergraduate": True}}
    saved = deepcopy(raw)
    result = normalize_profile(raw)
    assert result["source_version"] == 1
    by_field = {x["field"]: x for x in result["facts"]}
    assert by_field["graduation"]["value"] == {"earliest": "2028-05-01", "latest": "2028-05-31"}
    assert by_field["enrolled"]["value"] is True
    assert by_field["work_authorized"]["qualifiers"] == {"country": "US"}
    assert "work_locations" not in by_field
    assert "degree_level" not in by_field
    assert all(x["provenance"]["verified"] is False for x in result["facts"])
    assert raw == saved
    assert "fiction@example.org" not in json.dumps(result)


@pytest.mark.parametrize("raw", [[], None, {"profile_version": True}, {"profile_version": 0}, {"profile_version": "2"},
    {"profile_version": 3}, {"profile_version": 2, "candidate_facts": {}},
    profile(fact(id="same"), fact(id="same")), profile(*[fact() for _ in range(201)]),
    profile(fact("skills", ["x" * 1001])), profile(fact(id="x" * 129)),
    profile(fact(provenance={"reference": "x" * 1001})),
    profile(fact(notes="x" * 2001)), {"notes": "x" * 1_048_577},
    profile(fact("skills", [float("nan")])), {"irrelevant": object()},
])
def test_bounds_and_versions_fail_with_generic_private_safe_errors(raw):
    with pytest.raises(ValueError) as error:
        normalize_profile(raw)
    assert "fiction@example.org" not in str(error.value)
    assert "xxxxxxxx" not in str(error.value)


def test_duplicate_auto_and_explicit_ids_are_rejected():
    with pytest.raises(ValueError):
        normalize_profile(profile(fact(id="fact-002"), fact()))


def test_result_does_not_share_nested_mutable_facts_with_input():
    raw = profile(fact("skills", ["Python"]))
    output = normalize_profile(raw)
    output["facts"][0]["value"].append("SQL")
    assert raw["candidate_facts"][0]["value"] == ["Python"]


def test_canonical_output_is_bounded_even_when_defaults_expand_small_input():
    raw = profile(*[fact("skills", ["x" * 1000] * 5 + ["x" * 100]) for _ in range(200)])
    assert len(json.dumps(raw).encode("utf-8")) < 1_048_576
    with pytest.raises(ValueError):
        normalize_profile(raw)


def test_candidate_facts_without_v2_cannot_be_silently_discarded():
    with pytest.raises(ValueError):
        normalize_profile({"candidate_facts": [fact()]})


@pytest.mark.parametrize("item", [
    fact("skills", ["x"] * 201), fact("residence_country", "XX"),
    fact("enrolled", True, qualifiers={"season": "monsoon", "year": 2028}),
    fact("enrolled", True, qualifiers={"valid_until": "2028-02-30"}),
    fact("enrolled", True, provenance={"reference": "a\nlabel"}),
])
def test_extra_invalid_declarations_do_not_escape_validation(item):
    with pytest.raises(ValueError):
        normalize_profile(profile(item))


def test_valid_temporal_qualifiers_are_detached_and_serializable():
    raw = profile(fact("returning_student", True, qualifiers={"season": "SUMMER", "year": 2028,
        "after": "2028-08-31", "valid_from": "2027-09-01", "valid_until": "2028-09-01", "timeframe": "future"}))
    output = normalize_profile(raw)
    assert output["facts"][0]["qualifiers"] == {"season": "summer", "year": 2028,
        "after": "2028-08-31", "valid_from": "2027-09-01", "valid_until": "2028-09-01", "timeframe": "future"}
    output["facts"][0]["qualifiers"]["year"] = 2029
    assert raw["candidate_facts"][0]["qualifiers"]["year"] == 2028


@pytest.mark.parametrize("season", ["autumn", "Autumn", "AUTUMN", "fall"])
def test_autumn_and_fall_declarations_share_the_posting_term(season):
    raw = profile(fact("availability", True, qualifiers={"season": season, "year": 2031}))
    output = normalize_profile(raw)
    assert output["facts"][0]["qualifiers"] == {"season": "fall", "year": 2031}
    assert raw["candidate_facts"][0]["qualifiers"]["season"] == season


def test_legacy_invalid_values_do_not_invent_facts_or_echo_them():
    raw = {"education": {"graduation": "fictional confidential value"}, "skills": "not-a-list"}
    result = normalize_profile(raw)
    assert result["facts"] == []
    assert "confidential" not in json.dumps(result)
