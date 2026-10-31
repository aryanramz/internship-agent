# Structured internship eligibility

Issue #11 adds a deterministic local comparison of explicit posting requirements
and private candidate declarations. It produces `eligible`, `uncertain` or
`ineligible` independently of fit score. This is evidence screening, not an
employer decision, acceptance guarantee or legal qualification determination.

## Inspect an existing posting

```powershell
internship-agent --data data eligibility <job_id> --profile config/profile.json
internship-agent --data data rank --profile config/profile.json --with-eligibility
```

Both new CLI paths open an existing database read-only. They do not discover
jobs, create or migrate a database, rewrite the profile, prepare documents or
change application status. The dedicated report includes relevant candidate
facts, posting evidence, per-rule explanations, missing information and manual
verification guidance. Treat its output as private; do not paste it into public
issues or logs. Errors omit raw profile values and private paths.

The rank flag adds `eligibility_assessment` containing only `outcome`,
`required_rule_count` and `missing_information`. It preserves existing scores,
ordering and defaults. Existing `rank`/preview fields named `eligibility` retain
their legacy `review`/`unlikely` keyword-warning meaning for compatibility;
they are not the new three-state decision. A high fit score never changes the
structured assessment. The MCP registry, its default projections and its exact
three read-only tools are unchanged. No remote eligibility tool is added.

## Private profile version 2

Keep existing resume/ranking fields and add `profile_version: 2` with a
`candidate_facts` list to the ignored local profile. Public examples are
fictional. An enrollment declaration looks like:

```json
{
  "profile_version": 2,
  "candidate_facts": [
    {
      "id": "enrollment-declaration",
      "field": "enrolled",
      "value": true,
      "status": "known",
      "provenance": {
        "kind": "user_declared",
        "reference": "Fictional student declaration",
        "verified": true
      },
      "qualifiers": {}
    }
  ]
}
```

`status` is `known`, `unknown` or `conflicting`. Unknown/conflicting facts have
`value: null`; do not insert a guessed negative. Provenance kinds are
`user_declared`, `verified_document` and `unknown`. Definite comparisons require
a known, applicable fact with `verified: true`, a non-unknown provenance kind and
a nonempty reference. The flag records explicit local confirmation; the program
does not authenticate a declaration or inspect a document. References are opaque
labels: no file is opened and no URL is fetched.

| Field | Value and meaning |
|---|---|
| `enrolled`, `returning_student` | Boolean; returning status needs the applicable internship term |
| `degree_level` | Current program: `associate`, `bachelor`, `master`, `doctoral` |
| `completed_degrees` | List of those levels; enrollment does not prove completion |
| `majors`, `skills`, `coursework` | String lists; missing skill/coursework entries do not establish inability |
| `academic_year` / `completed_academic_years` | Integer 1–8 / 0–8 |
| `graduation` | ISO year/month/day or `{ "earliest": "2030-05", "latest": "2030-06" }` |
| `availability` | Boolean tied to explicit `season`+`year` or full-date `start`+`end` |
| `work_locations` | Explicit acceptable work locations; no address-derived inference |
| `work_modes` | List of `remote`, `hybrid`, `onsite` |
| `residence_country` | Explicit ISO two-letter country code; never inferred |
| `work_authorized`, `needs_sponsorship` | Boolean with explicit `country`; only declaration comparison, not legal advice |

Qualifiers support `country`, `season`, `year`, `start`, `end`, `after`,
`valid_from`, `valid_until` and declaration `timeframe` (`current`, `future`,
`both`). Date qualifiers use full ISO dates; season/year and interval statements
must match the rule being evaluated. Expired or not-yet-valid facts cannot
establish a definite result. Do not use generic authorization declarations across
countries or assume current sponsorship answers establish future requirements.
Future-only declarations cannot prove current status. `autumn` and `fall` name
the same explicit term; neither supplies dates or a missing year.

The bounded schema accepts at most 200 facts, with unique IDs, typed values and
bounded labels; the eligibility profile input and normalized projection are
limited to 1 MiB. Duplicate JSON keys, invalid/future versions, invalid dates and
malformed declarations fail safely. Unsupported fields are not silently
converted into verified facts.

Missing `profile_version` means legacy version 1. Existing ranking, document and
tracking paths keep their behavior. The new evaluator adapts explicit legacy
declarations in memory as **unverified**, with warnings; it does not infer a
degree from school text, add legal facts or rewrite a file. Confirm structured
facts explicitly to resolve those uncertainties. No SQLite migration or new
credential store is required; discovery schema/version and application history
are unchanged.

## Posting requirement version 1

`parse_requirements(job)` produces a bounded tree:

```text
schema_version: 1
operator: all
children: [leaf or all/any group, ...]
issues: [...]
source: {description, title, location, work_mode, reference}
```

Each leaf has a stable `id`, `kind`, `strength` (`required`, `preferred` or
`ambiguous`), `constraint`, `qualifiers`, `evidence` and `issues`. Evidence stores
`source`, original `start`/`end` offsets, exact `text` and inert source `reference`.
Validation requires the text to match the original slice. Groups retain
strength/evidence and use `operator: all` or `any` plus `children`.

Constraint operators are typed `eq`, `one_of`, `all_of`, `gte`, `gt`, `lte`,
`lt`, `date_range`, `term`, `interval` or `manual`. Graduation date ranges use
full-date bounds and explicit inclusivity. The tree is limited to 200 nodes,
depth 6 and 100,000 total source characters. External descriptions are always
untrusted data; their instructions never run or establish candidate facts.

Extraction is controlled English pattern matching, not general language
understanding. Explicit qualification headings/cues distinguish mandatory and
preferred clauses. Unsupported mandatory residuals, mixed scope, related-field
alternatives and complicated cross-field OR conditions remain manual review.
Title words such as senior, master or clearance alone are not proof of candidate
ineligibility. A posting with no reliably identified mandatory rule is uncertain.
Always read the original posting before acting.

## Evaluation rules

| Situation | Behavior |
|---|---|
| Every material mandatory condition reliably satisfied | `eligible` |
| Missing, unverified, conflicting or ambiguous material evidence | `uncertain` |
| Clear mandatory conflict with an applicable verified declaration | `ineligible` |
| Preferred qualification mismatch | Per-rule finding only; never disqualifies |
| Required AND | A reliable failed condition fails; otherwise unresolved conditions remain uncertain |
| Required OR | One satisfied alternative passes; unresolved alternatives matter if none passes |
| Contradictory mandatory posting constraints | Uncertain; verify employer scope rather than arbitrarily choosing a clause |

Graduation values are intervals: `2030-05` represents May 1–31, not an invented
day. A candidate interval entirely inside a requirement passes; entirely outside
fails; crossing a boundary is uncertain. Inclusive/exclusive posting boundaries
remain distinct. A strict date after a month excludes that whole month; a date
before a month excludes that whole month. Impossible or inconsistent posting
dates require manual verification.

Internship seasons require explicit years. The parser may use an unambiguous
explicit posting term to qualify relative wording; it never guesses from the
clock, publication date, test metadata or a northern-hemisphere calendar. A
returning-student declaration must refer to that term. Availability over an exact
date interval passes only with complete positive coverage; partial positive
coverage is uncertain, while an explicit unavailable overlap conflicts. Separate
positive intervals are not automatically joined.
Contrary verified intervals that overlap within the required dates are reported
as conflicting even when the positive interval covers only part of the internship.

Current degree level and completed degrees are separate. Explicit simple accepted
degree/major alternatives are OR; mandatory independent requirements are AND.
Only a small documented-in-code major alias set is normalized; unfamiliar field
names remain uncertain. Skills/coursework lists are not assumed exhaustive.
Unsupported conditions/exceptions and future-qualified status predicates remain
manual review rather than enforcing a current fragment of the sentence. A
separate, clearly established mandatory failure still makes the result ineligible.
Work mode is compared separately from work location and residence country;
remote does not waive geographical restrictions. Unrecognized location spelling
or missing location information remains uncertain.

Authorization/sponsorship comparison requires explicit matching-country,
applicable verified declarations. Citizenship, immigration status, security
clearance and ambiguous legal wording require manual verification. Names,
schools, addresses, nationality and language never establish these facts.

## Reproducible fictional examples

For the exact posting evidence **“Candidates must be currently enrolled.”**:

| Explicit local fact | Result | Reason |
|---|---|---|
| Verified `enrolled: true` with the provenance shown above | `eligible` | Verified declaration satisfies the only identified mandatory rule |
| No enrollment fact, or the same declaration with `verified: false` | `uncertain` | No applicable verified fact establishes enrollment |
| Verified `enrolled: false` | `ineligible` | Verified declaration directly contradicts the mandatory enrollment rule |

These examples were exercised with a fictional posting and an explicit
evaluation date, without network or personal data. A preferred skill cannot
reverse these outcomes; a high fit score cannot override the failed mandatory
enrollment comparison. Additional ambiguous mandatory wording changes an
otherwise passing report to uncertain.

For **“Must graduate on or after 2031-05-15.”**, a verified full date
`2031-05-15` passes; `2031-05` remains uncertain because the interval straddles
the boundary; `2031-04-30` directly conflicts. For **“Must work onsite in
Boston, MA.”**, verified mode `onsite` plus that explicit work location passes;
verified mode `remote` conflicts; a missing work location remains uncertain.
The offline posting-to-decision tests exercise these boundaries and keep job
responsibilities about other people from becoming candidate requirements.

## Limits and following work

This engine compares declarations and supported evidence; it cannot establish
that a posting is current, validate source truth, guarantee parser completeness
or make legal/hiring decisions. Review uncertain results locally and correct the
explicit declarations or seek employer clarification. No automatic application
answers or consequential actions are added.

Issue #12 owns ranking taxonomy/preferences and remains a separate next scope.
Issue #13 owns document claim tracing/QA. R2 also requires those issues and
release preparation; this implementation does not publish a release. Issue #3
remains open pending actual authenticated ChatGPT invocation. No external
connectivity, MCP permission, subscription, paid API or infrastructure is added.
