# Structured eligibility implementation plan

> **For agentic workers:** Use executing-plans / test-driven-development. The user authorizes autonomous implementation and merge after acceptance/review/CI, without routine design confirmation.

**Goal:** Complete Issue #11 with local, deterministic, evidence-backed eligible/uncertain/ineligible assessments, independent of fit score.

**Architecture:** A versioned private profile adapter, a bounded requirement parser and a pure evaluator. Add read-only local Agent/CLI reports; preserve legacy default Agent ranking/preview and all MCP projections. No SQLite migration, new dependency, model/network call, legal decision or application mutation.

**Baseline:** develop `1b35b343ac4c2da8791512c28e1aca881c9ec12a`; feature/11-structured-eligibility; target develop only.

**Spec:** User Work Session 5 and Issue #11; user guide/design will be `docs/ELIGIBILITY.md`.

## Decisions and interfaces

- Input new profile fields: `profile_version: 2`, `candidate_facts: [...]`; existing profile keys remain intact. Missing version means legacy v1. New assessment adapts legacy facts as unverified in memory; ranking/document workflows retain their original profile behavior. Future/invalid versions fail safely. Private profiles are not rewritten.
- `eligibility_profile.normalize_profile(profile) -> dict` returns `{schema_version:2,source_version,facts,warnings}` without contact/profile PII. `date_bounds(value)->(date,date)` handles ISO year/month/day precision. Optional text-month legacy adaptation remains unverified.
- Each fact: `{id,field,value,status:'known'|'unknown'|'conflicting',provenance:{kind:'user_declared'|'verified_document'|'unknown',reference,verified:bool},qualifiers:{...}}`. Unknown/conflicting values are None. Known values require correct types; unverified facts cannot satisfy or contradict a mandatory rule. Reference labels are never dereferenced. Duplicate IDs are invalid; contradictory applicable facts are uncertain, not silently resolved.
- Fields: enrolled/returning_student/work_authorized/needs_sponsorship/availability (bool); degree_level (associate/bachelor/master/doctoral); completed_degrees (list of those levels); majors/skills/coursework/work_locations (string lists); work_modes (remote/hybrid/onsite list); academic_year (1–8), completed_academic_years (0–8); residence_country (ISO2); graduation (ISO partial-date string or earliest/latest range, normalized to inclusive full-date bounds).
- Qualifiers: country, season, year, start/end, after, valid_from/valid_until, timeframe(current/future/both). Availability bool is tied to exact season+year or full-date interval; partial positive coverage is uncertain, explicit negative overlap contradicts. Returning-student facts need matching internship-term evidence. Work authorization/sponsorship comparisons need explicitly verified matching-country declarations; citizenship/clearance or unsupported legal language is manual review.
- `eligibility_requirements.parse_requirements(job)->dict`: `{schema_version:1,operator:'all',children,issues,source}`. Leaves: `{id,kind,strength:'required'|'preferred'|'ambiguous',constraint:{op,value?,min?,max?,min_inclusive?,max_inclusive?},qualifiers,evidence:[{source,start,end,text,reference}],issues}`. Groups add operator all/any and children instead of kind/constraint. Stable IDs/order; original evidence spans, no execution.
- Constraint ops: eq, one_of, all_of, date_range, gte, gt, lte, lt, term, interval, manual. Kinds map fact fields; `manual_review` covers unsupported material clauses. `validate_requirements(tree)` enforces depth/size/shape without fetching evidence. Parser uses only controlled explicit language/qualification headings, handles simple OR/AND, never treats preferred/negated text as hard requirements. Complex or contradictory scope becomes manual/ambiguous.
- Graduation ranges use inclusive date intervals; an interval wholly inside a requirement passes, wholly outside fails, straddling boundaries is uncertain. Month/year precision is never invented as a day. No internship year is inferred from current date/publication or test metadata. Term names compare only with explicit matching season+year; no hemisphere calendar assumption.
- `eligibility.evaluate_requirements(candidate, requirements, *, as_of:date)->dict` and `evaluate_eligibility(profile,job,*,as_of:date)->dict`. Per-rule outcomes satisfied/not_satisfied/uncertain with fact references, posting evidence, missing/conflicting information and manual guidance. Required AND fails on a reliable failed child; OR passes on one satisfied child, uncertain if an unresolved alternative remains, otherwise fails. Preferred findings never disqualify. Conflicting employer constraints are uncertain. No reliably identified mandatory rule => uncertain.
- Reports include only relevant local facts, not name/contact/entire profile. High fit score cannot change the assessment. Agent.ranked default and Agent.preview remain exactly compatible for MCP; optional local include_eligibility adds a separate assessment, never changes scores/order. CLI rank may request that projection; dedicated `eligibility JOB_ID --profile` supplies full local evidence and opens SQLite read-only.
- Bounds: at most 200 facts, 200 requirement nodes/depth 6, 100k posting text, 1 MB eligibility profile JSON; errors contain no raw values/private paths. No eval, arbitrary file/network dereference or remote eligibility tool.

## Review focus

1. A preferred qualification, negation or unused OR alternative must not create a hard failure.
2. Missing/unverified/conflicting/expired facts and imprecise dates cannot become definite matches or mismatches.
3. Current enrollment and program level do not prove a completed degree, returning status or legal authorization.
4. Metadata/title keywords and cross-field OR/AND ambiguity must not silently strengthen requirements or omit unsupported mandatory clauses.
5. Detailed facts/evidence remain local; MCP bytes/contracts and application/history/database contents stay unchanged.

## Tasks

- Profile/schema: RED→GREEN tests for versioning, typed facts/provenance, temporal qualification, bounds and legacy round-trip; implement eligibility_profile.py.
- Requirements: RED→GREEN explicit evidence/strength/group/date/negation/location/legal ambiguity tests; implement eligibility_requirements.py.
- Evaluator: RED→GREEN fact/conflict/interval/group/academic/term/location/authorization matrices; implement eligibility.py.
- Integration: RED→GREEN local read-only CLI/Agent, high-fit separation, existing ranking/preview/doc/application and MCP privacy compatibility tests; fictional sample only.
- Qualification: documentation/examples, full offline suite, compile/pip consistency/audit/privacy/demo/link checks; immutable independent complete review and scoped security review; fix confirmed blockers.
- GitHub: commit/push PR to develop, wait Python3.11–3.13/security CI, authorized expected-head merge, verify tree/main/post-merge CI, close #11 only after acceptance. #12 remains separate future work; R2 also requires #12/#13 and release preparation.
