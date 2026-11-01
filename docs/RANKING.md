# Explainable local ranking

Issue #12 adds title taxonomy, bounded preferences, fixed-clock scoring and local
explanations. This implementation is subject to PR review/acceptance. It requires
no new dependency, database migration, network call, model, account or paid service.

## Fit and eligibility

```bash
internship-agent --data data rank --profile config/profile.json
internship-agent --data data rank --profile config/profile.json --with-eligibility
```

Both commands read an existing ledger without creating/migrating it. Ordinary
`rank` retains the legacy fields/types and adds `ranking_explanation`. The legacy
`eligibility: review/unlikely` field is a keyword warning, not a structured
assessment; the explanation explicitly says `not_assessed_by_fit`.

`--with-eligibility` uses the unchanged [eligibility evaluator](ELIGIBILITY.md).
It adds the existing minimal `eligibility_assessment` summary plus `action`:
`do_not_apply` for ineligible, `manual_review` for uncertain, and `review_posting`
for eligible. These are advisory labels, not workflow actions or approval.
Neither a high score, preference nor score threshold changes an eligibility result.
Results remain in fit order, so a high-fit ineligible record remains visible with
its explicit label rather than being relabeled eligible. Read the original posting
and verify applicable facts before any consequential action.

MCP still exposes exactly three read-only tools with their existing fields.
Ranking and preview explicitly project the legacy fit fields; local explanation,
experience references, preferences and structured eligibility are not added to the
remote contract. Numeric fit may change for the documented role corrections or
explicit preferences. Profiles and full local reports remain private.

## Default six-component baseline

| Component | Weight | Unit score before weighting |
|---|---:|---|
| Role | 35 | Direct title match 1; curated adjacency .65; broad technical title .5; unmatched .12 |
| Skills | 25 | Whole-token/phrase profile skill occurrences in title, description or location; matches / min(7, max(3, profile skill count)), capped at 1 |
| Location | 15 | Existing preferred-location whole-phrase match 1; legacy remote fallback .8; otherwise .15 |
| Recency | 10 | Publication age ≤14 days: 1; ≤45: .65; older: .2; unknown/invalid/future: .35 |
| Compensation | 10 | Compensation text present .8; absent .4; no currency/salary-value comparison |
| Employer | 5 | Exact case-insensitive preferred company 1; otherwise .5 |

Weights still sum to 100. Total score rounds the sum of raw weighted contributions
using Python rounding. Rounded displayed components can differ from that total;
explanations retain unrounded contributions (to four decimal places) and units.
Scores describe heuristic fit, never hiring probability or proof of proficiency.

Freshness uses one timezone-aware clock per service invocation, not discovery time.
Standalone `evaluate(..., as_of=...)` supports reproducible synthetic evaluation.
ISO/RFC publication timestamps are supported; naive dates retain the historical UTC
interpretation. Future/invalid dates now remain unknown rather than earning full
freshness. Remote-location inference now uses whole-token matching rather than
accepting substrings such as `Nonremote`. Input/configuration is never rewritten.

Ordering retains the legacy warning group (`review` before `unlikely`), then
score descending, case-folded company and stable job ID. The added ID tie-break
removes dependence on ingestion order; case-folding intentionally removes company
capitalization as a ranking preference. `limit`/`min-score` retain existing bounds.
Only the existing at-most-10,000 recent stored records are considered.

## Role taxonomy and ambiguity

Matching uses the **title**, not incidental description text. Case-insensitive
whole-token/phrase boundaries avoid Java/JavaScript-style substring matching.

| Track | Explicit aliases / title contexts |
|---|---|
| Cloud | cloud engineer/engineering/intern, infrastructure, developer/development, operations, platform, computing, security, architecture prefixed by `cloud` |
| Infrastructure | infrastructure; platform engineer/engineering |
| DevOps | devops, dev ops, devsecops, site reliability, SRE |
| Cyber/information security | cybersecurity, cyber security, information security, infosec, security engineer/engineering/analyst/operations, application/cloud/network security |
| Software | software, application/web/backend/frontend development |
| Systems | systems engineer/engineering/administration/administrator/analyst/intern |
| IT | information technology, IT support/engineering/intern/operations; uppercase `IT` acronym in titles |

Targets may use the broad track name `cloud`; titles require the explicit cloud
contexts above. IT target aliases are case-insensitive, but a title's ordinary
pronoun `it` alone is not a technical track. Bare `security` is ambiguous: it may
receive broad technical relevance, never a direct cyber match by itself.

A direct shared track scores 1. The only adjacent pairs, symmetrically scored .65,
are cloud–infrastructure, cloud–DevOps, infrastructure–DevOps,
infrastructure–systems, DevOps–software, systems–software and systems–IT.
Adjacency is explicitly **inferred relevance**, not equivalence or eligibility.
Other pairs receive no inferred match. Multiple tracks can occur in one title;
the best direct/adjacent relation determines the role unit.

Sales, marketing, recruiting, kitchen, physical security, security guard, HR/human
resources, business systems, civil, construction, electrical, mechanical and
facilities title contexts suppress technical taxonomy matching. Food, national,
homeland, international, social, economic, public and personal security contexts
also do not establish cybersecurity. This conservative
rule can under-rank mixed roles; it avoids treating a keyword as qualification.
Targets containing an alias plus an unrecognized occupation (for example `cloud
economist` or `software procurement`) do not expand to the technical track.
An unknown target matches only its complete phrase, with at least one informative
word beyond generic intern/engineer/engineering/analyst/student/summer/co-op words.
No stemming, arbitrary shared-word equivalence or learned taxonomy is implied.

These rules intentionally correct the previous any-shared-target-token matching.
They are not a promise to classify every title, discipline or language.

## Private configuration version 1

Existing profiles need no new field. Add an optional `ranking` object to the
ignored profile, keeping existing `target_roles`, `skills`, `preferred_locations`
and `preferred_employers`. For example (fictional preferences):

```json
{
  "target_roles": ["cloud engineer", "information security"],
  "skills": ["Python", "AWS", "Terraform"],
  "preferred_locations": ["Example City"],
  "preferred_employers": ["Example Employer"],
  "ranking": {
    "version": 1,
    "weights": {"role": 25, "skills": 35},
    "preferences": {
      "work_modes": ["remote", "hybrid"],
      "avoid_work_modes": ["onsite"],
      "avoid_locations": ["Other City"],
      "avoid_employers": ["Other Employer"],
      "prefer_compensation": true,
      "use_experience": false
    }
  }
}
```

`weights` overlays the defaults. Keys are exactly the six components; values are
integers 0–100 (booleans/floats/NaN are invalid), and the resulting sum must be 100.
Zero can disable a component; omitted weights retain defaults. No silent
normalization or fallback hides an invalid configuration. Empty configuration
objects select defaults; unknown keys/versions and malformed shapes fail safely.

| Preference | Component / behavior |
|---|---|
| Existing `target_roles` | Role only; taxonomy/exact phrase targets |
| Existing `skills` | Skills only; profile-supplied labels, not independently verified facts |
| Existing `preferred_locations` | Location only; whole phrase in posting location/work mode |
| Existing `preferred_employers` | Employer only; exact case-insensitive company |
| `work_modes` | Location only; when nonempty, replaces preferred-location matching: matching mode 1, otherwise .15 |
| `avoid_work_modes`, `avoid_locations` | Location only; matching avoidance sets 0, taking precedence over positive matches |
| `avoid_employers` | Employer only; exact avoided company sets 0 |
| `prefer_compensation` | Compensation only; defaults true, false gives neutral .5 irrespective of text presence |
| `use_experience` | Skills only; defaults false, true combines 80% existing skill coverage + 20% fraction of matched skills also referenced in supplied experience |

Work-mode preference values are remote/hybrid/onsite, case-insensitive. Provider
`on-site`, `on site` and `on_site` spellings normalize to onsite. Explicit normalized
posting mode is preferred; a whole `remote` location token can supply an inferred
mode, labeled separately. Unknown mode is not assumed to satisfy a preference.
Exact case-insensitive positive/avoidance intersections are rejected. Broader
geographic containment is not resolved; a non-identical avoidance match takes
precedence rather than becoming legal/geographic eligibility evidence.

Lists are at most 100 strings, 120 characters each; blank entries are ignored and
case-insensitive duplicates collapsed. Types/control characters/oversized input
fail safely. Optional experience accepts at most 100 objects, title and bullet/stack
strings up to 2,000 characters, at most 100 bullet/stack entries each, and 100,000
consumed text characters total. Only posting-matched profile skills can receive
experience corroboration; missing experience is disclosed, never invented.
Experience indices are private local references, not proof of employment or truth.
Whitespace-only/empty objects remain missing evidence. Corroboration is prepared
once per invocation; all candidates receive compact scoring before selection.
Only returned rows receive detailed explanations, capped at 100 experience
references per row, with `experience_matches_total` and
`experience_matches_truncated` disclosing omissions. The cap never changes the
score or corroborated-skill count.
The ranking profile reader rejects duplicate JSON keys and input over 1 MiB.
Legacy and eligibility-v2 profiles keep their schema; facts are not promoted into
skills, and scoring never rewrites or independently verifies declarations.

## Explanation, confidence and limits

Local reports expose weights, unit values, raw/displayed contributions, role tracks,
matched targets, observed skill source fields, inferred adjacency/work mode,
experience indices, preference effects and missing information. They do not
execute posting instructions or follow evidence URLs.

Confidence is qualitative input completeness: `low` for absent descriptions or
fewer than eight description words; otherwise `limited` if a listed input is
missing; `supported` only means those input fields are present. It is not a
calibrated model-confidence score or a claim that extraction/evidence is correct.
Skill mentions may be preferred, negated or unrelated; the fit explanation records
occurrences and leaves mandatory requirement interpretation to eligibility.

No optional analyzer, model hook or calibration is implemented. Deterministic
ranking works without AI packages/credentials and has no analysis failure path.
Unsupported analysis configuration is rejected as invalid; it cannot enable a
paid model. No labeled evaluation dataset supports accuracy/calibration claims.
No precision, recall, interview probability or hiring outcomes are asserted.
Document claim QA remains Issue #13; workflow/approval recovery remains Issue #14.
