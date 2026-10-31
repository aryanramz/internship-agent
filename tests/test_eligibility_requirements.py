"""Fictional, offline posting evidence and conservative requirement parsing."""
from copy import deepcopy
from datetime import date

import pytest

from internship_agent.eligibility_requirements import parse_requirements, validate_requirements
from internship_agent.eligibility import evaluate_eligibility


def posting(text, **extra):
    return {"description": text, "title": "Engineering intern", "job_url": "https://example.test/jobs/fictional", **extra}


def leaves(tree):
    if "children" in tree:
        return [leaf for child in tree["children"] for leaf in leaves(child)]
    return [tree]


def by_kind(tree, kind):
    return [leaf for leaf in leaves(tree) if leaf["kind"] == kind]


def test_explicit_education_and_preferred_skills_preserve_original_evidence():
    text = "Required qualifications:\nCurrently enrolled in a bachelor's or master's degree in Computer Science or Mathematics.\nPreferred:\nProficiency in Python and SQL."
    tree = parse_requirements(posting(text))
    validate_requirements(tree)
    assert by_kind(tree, "enrolled")[0]["constraint"] == {"op": "eq", "value": True}
    assert by_kind(tree, "degree_level")[0]["constraint"] == {"op": "one_of", "value": ["bachelor", "master"]}
    assert by_kind(tree, "majors")[0]["constraint"] == {"op": "one_of", "value": ["computer science", "mathematics"]}
    assert by_kind(tree, "skills")[0]["strength"] == "preferred"
    assert by_kind(tree, "skills")[0]["constraint"] == {"op": "all_of", "value": ["python", "sql"]}
    for leaf in leaves(tree):
        for evidence in leaf["evidence"]:
            assert text[evidence["start"]:evidence["end"]] == evidence["text"]
            assert evidence["source"] == "description"
    assert tree == parse_requirements(posting(text))


@pytest.mark.parametrize("text", ["Our master's interns use Python.", "Citizenship is not required.", "No security clearance is required.", "A bachelor's degree is not required."])
def test_keywords_and_negated_requirements_never_become_mandatory(text):
    tree = parse_requirements(posting(text))
    assert not [leaf for leaf in leaves(tree) if leaf["strength"] == "required"]


def test_completed_degree_is_distinct_from_current_program():
    tree = parse_requirements(posting("Requirements:\nMust have completed a bachelor's degree.\nMust be currently enrolled in a master's program."))
    assert by_kind(tree, "completed_degrees")[0]["constraint"] == {"op": "all_of", "value": ["bachelor"]}
    assert by_kind(tree, "degree_level")[0]["constraint"]["value"] == "master"
    assert by_kind(tree, "enrolled")[0]["constraint"]["value"] is True


@pytest.mark.parametrize(("text", "expected"), [
    ("Must graduate between May 2027 and August 2028.", {"op": "date_range", "min": "2027-05-01", "max": "2028-08-31", "min_inclusive": True, "max_inclusive": True}),
    ("Must graduate before 2028-05.", {"op": "date_range", "max": "2028-05-01", "max_inclusive": False}),
    ("Must graduate after May 2027.", {"op": "date_range", "min": "2027-05-31", "min_inclusive": False}),
    ("Must graduate on or after 2027-05-15.", {"op": "date_range", "min": "2027-05-15", "min_inclusive": True}),
])
def test_graduation_dates_respect_precision_and_boundaries(text, expected):
    assert by_kind(parse_requirements(posting(text)), "graduation")[0]["constraint"] == expected


def test_term_requires_explicit_unique_year_and_title_evidence():
    text = "Must be available for summer. Must return to school after the internship."
    no_year = parse_requirements(posting(text, published_at="2027-01-01"))
    assert not by_kind(no_year, "availability")
    assert not by_kind(no_year, "returning_student")
    tree = parse_requirements(posting(text, title="Summer 2027 software intern"))
    assert by_kind(tree, "availability")[0]["qualifiers"] == {"season": "summer", "year": 2027}
    assert by_kind(tree, "returning_student")[0]["qualifiers"] == {"season": "summer", "year": 2027}
    assert any(e["source"] == "title" for e in by_kind(tree, "availability")[0]["evidence"])


def test_explicit_availability_interval_and_academic_progress():
    tree = parse_requirements(posting("Requirements:\nMust be available from 2027-06-01 through 2027-08-31.\nMust have completed at least 2 academic years.\nMust be a junior or senior."))
    assert by_kind(tree, "availability")[0]["constraint"] == {"op": "interval", "value": {"start": "2027-06-01", "end": "2027-08-31"}}
    assert by_kind(tree, "completed_academic_years")[0]["constraint"] == {"op": "gte", "value": 2}
    assert by_kind(tree, "academic_year")[0]["constraint"] == {"op": "one_of", "value": [3, 4]}


def test_explicit_geography_work_mode_and_country_qualified_authorization():
    tree = parse_requirements(posting("Requirements:\nMust work onsite in Boston, MA.\nMust be authorized to work in the United States.\nMust not need sponsorship in the United States now or in the future."))
    assert by_kind(tree, "work_modes")[0]["constraint"] == {"op": "all_of", "value": ["onsite"]}
    assert by_kind(tree, "work_locations")[0]["constraint"] == {"op": "all_of", "value": ["boston, ma"]}
    assert by_kind(tree, "work_authorized")[0]["qualifiers"] == {"country": "US"}
    assert by_kind(tree, "needs_sponsorship")[0]["qualifiers"] == {"country": "US", "timeframe": "both"}
    assert by_kind(tree, "needs_sponsorship")[0]["constraint"] == {"op": "eq", "value": False}


@pytest.mark.parametrize("text", [
    "Must have work authorization.", "Must not need sponsorship now or in the future.",
    "US citizenship is required.", "Security clearance is required.",
    "Must be enrolled or have three years of industry experience.",
    "Must be enrolled and provide excellent references.",
    "Must graduate between May and August.",
])
def test_unresolved_mandatory_material_is_retained_for_manual_review(text):
    tree = parse_requirements(posting(text))
    manual = by_kind(tree, "manual_review")
    assert manual
    assert all(leaf["evidence"][0]["text"] for leaf in manual)


def test_conflicting_mandatory_constraints_do_not_silently_become_hard_rules():
    tree = parse_requirements(posting("Must be enrolled. Must not be enrolled."))
    assert any("conflict" in issue for issue in tree["issues"])
    assert all(leaf["strength"] == "ambiguous" for leaf in by_kind(tree, "enrolled"))


def test_missing_description_metadata_and_node_bounds_are_conservative():
    missing = parse_requirements(posting("", title="US Summer 2027 intern", location="Boston", work_mode="Onsite"))
    assert by_kind(missing, "manual_review")
    assert not [leaf for leaf in leaves(missing) if leaf["strength"] == "required"]
    with pytest.raises(ValueError, match="limit"):
        parse_requirements(posting("x" * 100001))
    many = parse_requirements(posting("\n".join(f"Must provide unexplained credential {i}." for i in range(205))))
    validate_requirements(many)
    assert by_kind(many, "manual_review")
    assert "requirement_limit" in many["issues"]


def test_validator_rejects_malformed_bounds_ids_evidence_and_cycles():
    tree = parse_requirements(posting("Must be enrolled."))
    bad = deepcopy(tree)
    bad["children"].append(deepcopy(bad["children"][0]))
    with pytest.raises(ValueError):
        validate_requirements(bad)
    bad = deepcopy(tree)
    bad["children"][0]["evidence"][0]["start"] = -1
    with pytest.raises(ValueError):
        validate_requirements(bad)
    bad = deepcopy(tree)
    bad["children"].append(bad)
    with pytest.raises(ValueError):
        validate_requirements(bad)


@pytest.mark.parametrize("text", [
    "Must not have a bachelor's degree.",
    "Must not work onsite in Boston.",
    "Must not be proficient in Python.",
    "Must know Python or SQL and Java.",
    "Must be enrolled in a bachelor's or master's and doctoral program.",
])
def test_negated_or_mixed_scope_cannot_create_positive_hard_leaf(text):
    tree = parse_requirements(posting(text))
    assert by_kind(tree, "manual_review")
    assert not [leaf for leaf in leaves(tree) if leaf["strength"] == "required" and leaf["kind"] != "manual_review"]


def test_contradictory_disjoint_graduation_windows_are_ambiguous():
    tree = parse_requirements(posting("Must graduate before May 2027. Must graduate after August 2028."))
    assert "conflicting_requirements" in tree["issues"]
    assert all(leaf["strength"] == "ambiguous" for leaf in by_kind(tree, "graduation"))


def test_unrelated_season_year_does_not_qualify_relative_internship_term():
    tree = parse_requirements(posting("Our company won a Summer 2026 award. Must be available for summer.", title="Engineering intern"))
    assert not by_kind(tree, "availability")


def test_unknown_heading_item_and_supported_snippet_keep_manual_requirement():
    tree = parse_requirements(posting("Requirements:\nMust be enrolled and supply recommendations.\nPossess excellent interpersonal abilities."))
    assert by_kind(tree, "enrolled")
    assert len(by_kind(tree, "manual_review")) == 2


def test_same_field_boolean_negation_and_preferred_scope_are_kept_local():
    tree = parse_requirements(posting("Preferred qualifications:\nExperience with Python.\nRequirements:\nMust not be enrolled.\nBenefits:\nWe provide onsite lunches."))
    assert by_kind(tree, "skills")[0]["strength"] == "preferred"
    assert by_kind(tree, "enrolled")[0]["constraint"] == {"op": "eq", "value": False}
    assert not by_kind(tree, "work_modes")


def test_html_evidence_is_original_and_clauses_remain_separate():
    text = "<h2>Requirements</h2><ul><li>Must be enrolled.</li><li>Must be a junior.</li></ul>"
    tree = parse_requirements(posting(text))
    assert by_kind(tree, "enrolled") and by_kind(tree, "academic_year")
    for leaf in leaves(tree):
        for evidence in leaf["evidence"]:
            assert text[evidence["start"]:evidence["end"]] == evidence["text"]


@pytest.mark.parametrize(("kind", "constraint", "qualifiers"), [
    ("enrolled", {"op": "eq", "value": "yes"}, {}),
    ("work_authorized", {"op": "eq", "value": True}, {}),
    ("needs_sponsorship", {"op": "eq", "value": False}, {"country": "US"}),
    ("degree_level", {"op": "eq", "value": "banana"}, {}),
    ("skills", {"op": "one_of", "value": [True]}, {}),
    ("academic_year", {"op": "eq", "value": 90}, {}),
    ("availability", {"op": "eq", "value": True}, {"season": "summer"}),
])
def test_validator_rejects_wrong_field_types_and_unqualified_sensitive_rules(kind, constraint, qualifiers):
    tree = parse_requirements(posting("Must be enrolled."))
    tree["children"][0].update(kind=kind, constraint=constraint, qualifiers=qualifiers)
    with pytest.raises(ValueError):
        validate_requirements(tree)


@pytest.mark.parametrize("text", [
    "Must be available for Summer 2027 and provide excellent references.",
    "Must return to school after the Summer 2027 internship and hold a pilot license.",
    "Must not need sponsorship in the United States now or in the future and hold a pilot license.",
])
def test_known_term_or_authorization_snippet_never_absorbs_unknown_material(text):
    tree = parse_requirements(posting(text, title="Summer 2027 intern"))
    assert by_kind(tree, "manual_review")


def test_simple_supported_clauses_are_evaluable_without_spurious_manual_tail():
    tree = parse_requirements(posting("Must work onsite in Boston, MA. Must be available for summer. Must return to school after the internship.", title="Summer 2027 intern"))
    assert by_kind(tree, "work_modes") and by_kind(tree, "availability") and by_kind(tree, "returning_student")
    assert not by_kind(tree, "manual_review")


def test_explicit_majors_and_coursework_lists_preserve_any_and_all():
    tree = parse_requirements(posting("Required qualifications:\nMajoring in Physics or Mathematics.\nCompleted coursework in Algorithms and Data Structures."))
    assert by_kind(tree, "majors")[0]["constraint"] == {"op": "one_of", "value": ["physics", "mathematics"]}
    assert by_kind(tree, "coursework")[0]["constraint"] == {"op": "all_of", "value": ["algorithms", "data structures"]}
    assert not by_kind(tree, "manual_review")


def test_explicit_current_student_is_enrollment_not_completed_degree():
    tree = parse_requirements(posting("Must be a current master's student."))
    assert by_kind(tree, "enrolled")[0]["constraint"] == {"op": "eq", "value": True}
    assert by_kind(tree, "degree_level")[0]["constraint"] == {"op": "eq", "value": "master"}
    assert not by_kind(tree, "completed_degrees")


def test_explicit_country_of_residence_and_work_location_are_independent():
    tree = parse_requirements(posting("Requirements:\nMust reside in Canada.\nMust work in Toronto, Canada."))
    assert by_kind(tree, "residence_country")[0]["constraint"] == {"op": "eq", "value": "CA"}
    assert by_kind(tree, "work_locations")[0]["constraint"] == {"op": "all_of", "value": ["toronto, canada"]}
    assert not by_kind(tree, "manual_review")


@pytest.mark.parametrize("text", [
    "Must be enrolled or graduate in May 2027.",
    "Must be enrolled in a bachelor's program or have completed a master's degree.",
    "Must have completed at least 2 academic years or be a junior.",
    "Must be a bachelor's student or possess a master's degree.",
])
def test_cross_field_alternatives_within_education_are_not_flattened_into_and(text):
    tree = parse_requirements(posting(text))
    assert by_kind(tree, "manual_review")
    assert not [leaf for leaf in leaves(tree) if leaf["kind"] != "manual_review" and leaf["strength"] == "required"]


def test_degree_and_major_or_connectors_do_not_change_each_others_scope():
    tree = parse_requirements(posting("Must have completed a bachelor's and master's degree in Computer Science or Mathematics."))
    assert by_kind(tree, "completed_degrees")[0]["constraint"] == {"op": "all_of", "value": ["bachelor", "master"]}
    assert by_kind(tree, "majors")[0]["constraint"] == {"op": "one_of", "value": ["computer science", "mathematics"]}


@pytest.mark.parametrize(("text", "wrong_kind"), [
    ("Must understand Mastercard settlement systems.", "completed_degrees"),
    ("Must collaborate with senior engineers.", "academic_year"),
    ("Must work on hybrid engines.", "work_modes"),
    ("Must work with remote-control vehicles.", "work_modes"),
])
def test_embedded_keywords_are_not_requirement_claims(text, wrong_kind):
    tree = parse_requirements(posting(text))
    assert not by_kind(tree, wrong_kind)
    assert by_kind(tree, "manual_review")


@pytest.mark.parametrize(("text", "expected"), [
    ("Candidates must be at least a sophomore.", {"op": "gte", "value": 2}),
    ("Must be beyond junior year.", {"op": "gt", "value": 3}),
    ("Must be at most a junior.", {"op": "lte", "value": 3}),
    ("Must be below senior year.", {"op": "lt", "value": 4}),
])
def test_academic_standing_comparisons_preserve_minimum_and_maximum(text, expected):
    assert by_kind(parse_requirements(posting(text)), "academic_year")[0]["constraint"] == expected


def test_degree_reference_to_other_students_does_not_describe_candidate():
    tree = parse_requirements(posting("Candidates must mentor master's students."))
    assert not by_kind(tree, "completed_degrees") and not by_kind(tree, "degree_level")
    assert by_kind(tree, "manual_review")


def test_pure_waiver_does_not_make_an_explicit_supported_rule_uncertain():
    tree = parse_requirements(posting("Must be enrolled. A master's degree is not required."))
    assert by_kind(tree, "enrolled")
    assert not by_kind(tree, "manual_review")
    assert not by_kind(tree, "completed_degrees")


def test_mixed_required_and_preferred_same_clause_retains_scope_uncertainty():
    tree = parse_requirements(posting("Must be enrolled and master's degree preferred. Must work onsite."))
    assert any(leaf["strength"] == "ambiguous" for leaf in by_kind(tree, "manual_review"))
    assert not [leaf for leaf in by_kind(tree, "enrolled") if leaf["strength"] == "preferred"]


@pytest.mark.parametrize("text", [
    "Must interview currently enrolled students.",
    "Must mentor students pursuing a master's program.",
    "Must support a current master's student.",
])
def test_enrollment_and_program_references_must_describe_the_candidate(text):
    tree = parse_requirements(posting(text))
    assert not by_kind(tree, "enrolled")
    assert not by_kind(tree, "degree_level")
    assert by_kind(tree, "manual_review")


def test_work_mode_list_does_not_capture_unrelated_technical_adjective():
    tree = parse_requirements(posting("Must work onsite and understand hybrid engines."))
    assert by_kind(tree, "work_modes")[0]["constraint"] == {"op": "all_of", "value": ["onsite"]}
    assert by_kind(tree, "manual_review")


@pytest.mark.parametrize("text", [
    "Must have a bachelor's or higher degree.",
    "Must have a bachelor's degree or equivalent.",
])
def test_unenumerated_degree_alternatives_cannot_reliably_fail_lower_degree_rule(text):
    tree = parse_requirements(posting(text))
    assert not by_kind(tree, "completed_degrees")
    assert by_kind(tree, "manual_review")


@pytest.mark.parametrize("text", [
    "Required: Proficiency in Python and provide references.",
    "Required: Majoring in Computer Science or a related field.",
])
def test_unknown_list_material_is_manual_not_a_named_skill_or_major(text):
    tree = parse_requirements(posting(text))
    assert by_kind(tree, "manual_review")
    assert not by_kind(tree, "skills") and not by_kind(tree, "majors")


def test_mutually_impossible_academic_comparisons_remain_uncertain():
    tree = parse_requirements(posting("Must be at least a senior. Must be at most a sophomore."))
    assert "conflicting_requirements" in tree["issues"]
    assert all(leaf["strength"] == "ambiguous" for leaf in by_kind(tree, "academic_year"))


def test_schema_accepts_simple_or_group_and_rejects_depth_and_size_overflow():
    tree = parse_requirements(posting("Must be enrolled. Must be a junior."))
    first, second = tree["children"]
    group = {"id": "choice", "operator": "any", "children": [first, second], "strength": "required", "qualifiers": {}, "evidence": first["evidence"], "issues": []}
    tree["children"] = [group]
    validate_requirements(tree)
    for i in range(7):
        group = {**group, "id": f"depth_{i}", "children": [group]}
    tree["children"] = [group]
    with pytest.raises(ValueError, match="limit"):
        validate_requirements(tree)
    tree = parse_requirements(posting("Must be enrolled."))
    tree["children"] = [{**deepcopy(tree["children"][0]), "id": f"rule_{i}"} for i in range(200)]
    with pytest.raises(ValueError, match="limit"):
        validate_requirements(tree)


@pytest.mark.parametrize(("text", "field", "value", "qualifiers"), [
    ("Must confirm that employees are authorized to work in the United States.", "work_authorized", False, {"country": "US"}),
    ("Must support customers based in Canada.", "residence_country", "US", {}),
    ("Must mentor students majoring in Mathematics.", "majors", ["computer science"], {}),
    ("Must interview students graduating before May 2027.", "graduation", "2028-05", {}),
    ("Must mentor students who have completed at least 2 academic years.", "completed_academic_years", 1, {}),
    ("Must supervise remote work.", "work_modes", ["onsite"], {}),
    ("Must schedule candidates available for summer.", "availability", False, {"season": "summer", "year": 2027}),
    ("Must support a returning student after the internship.", "returning_student", False, {"season": "summer", "year": 2027}),
])
def test_third_party_predicates_cannot_become_hard_candidate_requirements(text, field, value, qualifiers):
    job = posting(text, title="Summer 2027 intern")
    tree = parse_requirements(job)
    assert not by_kind(tree, field)
    profile = {"profile_version": 2, "candidate_facts": [{"id": "fictional", "field": field, "value": value,
        "status": "known", "qualifiers": qualifiers,
        "provenance": {"kind": "user_declared", "reference": "Fictional declaration", "verified": True}}]}
    assert evaluate_eligibility(profile, job, as_of=date(2026, 10, 30))["outcome"] == "uncertain"


@pytest.mark.parametrize("text", [
    "Must be enrolled. We require a valid driver's license.",
    "Must be enrolled. The employer requires excellent references.",
    "Must be enrolled. A valid driver's license is mandatory.",
])
def test_explicit_unsupported_require_and_mandatory_cues_cannot_be_ignored(text):
    tree = parse_requirements(posting(text))
    assert by_kind(tree, "enrolled")
    assert by_kind(tree, "manual_review")
    profile = {"profile_version": 2, "candidate_facts": [{"id": "fictional", "field": "enrolled", "value": True,
        "provenance": {"kind": "user_declared", "reference": "Fictional declaration", "verified": True}}]}
    assert evaluate_eligibility(profile, posting(text), as_of=date(2026, 10, 30))["outcome"] == "uncertain"


def test_explicit_dated_after_term_supports_returning_student_without_title_year():
    tree = parse_requirements(posting("Must return to school after summer 2030."))
    assert by_kind(tree, "returning_student")[0]["qualifiers"] == {"season": "summer", "year": 2030}
    assert not by_kind(tree, "manual_review")
