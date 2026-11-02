# Verified document drafts

Issue #13 adds deterministic local drafts and review evidence. No model, paid
service, network request, eligibility/ranking change or MCP tool is added.
Verification means **explicit local attestation**; the software cannot
independently authenticate a certificate, declaration or achievement.

## Prepare a private revision

```bash
internship-agent --data data prepare JOB_ID --profile config/profile.json
internship-agent --data data prepare JOB_ID --profile config/profile.json --variant master
internship-agent --data data prepare JOB_ID --profile config/profile.json --variant track --track systems
internship-agent --data data prepare JOB_ID --profile config/profile.json --variant job --track software
```

The default is `job`. `master` retains source order. `track` emphasizes explicitly
configured source paths and items mentioning the track's verified skills. `job`
first emphasizes whole-phrase posting overlap with verified skills, then optional
track emphasis. This is occurrence-based ordering, not an assessment that a job
requires a skill. Untrusted descriptions cannot add facts or instructions. No
keywords are inserted beyond profile-supported text; JavaScript does not match
Java. Track keys reuse cloud/infrastructure/devops/security/software/systems/it
from the existing taxonomy, but taxonomy membership never establishes proficiency.
A known track without configured emphasis retains source order.

Existing profile strings and `create_documents(job, profile, output_root)` calls
remain readable; the pair return remains resume/letter paths. **Unattested legacy
claims are withheld** with review markers, rather than silently verified. Existing
preview/MCP field names (including `matching_verified_skills`) retain their legacy
shape/overlap behavior, with an explicit limitation that legacy labels are
unverified. These previews do not authorize document claims. New local provenance
and QA details are never added to MCP output.

## Private document fact contract, version 1

Keep ranking fields and eligibility-v2 declarations unchanged. Add `documents` to
your ignored profile. The following example is fictional:

```json
{
  "name": "Fictional Student",
  "skills": ["Python", "Linux"],
  "documents": {
    "version": 1,
    "facts": [
      {"id": "name-checked", "path": "/name", "value": "Fictional Student",
       "verified": true, "source": "Fictional local identity review", "reviewed_on": "2026-11-01"},
      {"id": "linux-checked", "path": "/skills/1", "value": "Linux",
       "verified": true, "source": "Fictional lab record review", "reviewed_on": "2026-11-01"}
    ],
    "tracks": {"systems": ["/skills/1"]}
  }
}
```

Each declaration requires exactly `id`, `path`, `value`, `verified`, `source`,
`reviewed_on`. IDs are unique 1–80 ASCII letters/digits/underscore/hyphen. Values
match the complete source string **exactly**, including quantitative claims.
`source` is a nonblank label up to 300 characters, never fetched/opened. The ISO
date records when the human reviewed the fact; it does not assert expiry or
independent freshness. Changed profile values make old attestations stale.
The flag must be a boolean. False/missing attestation withholds the claim.
Different declarations for the same path withhold it as conflicting, including
an unverified conflicting declaration. Semantically contradictory free text at
different paths is not automatically understood; humans must resolve it.

Supported exact JSON pointers reference leaf strings at:

- `/name`, `/email`, `/phone`, `/location`, `/linkedin`, `/github`;
- `/education/school`, `/education/degree`, `/education/graduation`, `/education/gpa`;
- `/skills/N`, `/certifications/N`;
- `/experience/N/` or `/projects/N/` followed by `name`, `title`, `company`,
  `dates`, `stack/N` or `bullets/N`.

Lists have at most 100 entries, leaf strings at most 2,000 characters, consumed
source text at most 100,000 characters, and declarations at most 2,000. Indices
are 0–99. Document configuration rejects unknown keys/versions, malformed values,
control characters and duplicate IDs. File reads reject duplicate JSON keys and
input above 1 MiB. Legal/authorization declarations are deliberately outside this
contract. A role/project needs an attested name/title before any of its other
claims can be used. `linkedin`/`github` must be HTTPS without embedded credentials;
unsafe links are withheld. Links are selectable plain text, not active DOCX
relationships. Profile contact fields are user-supplied text, not fetched URLs.

Track path lists contain at most 100 unique existing supported source paths.
Referencing a path cannot verify it. Missing/unsupported fields are never inferred.
For a quantitative bullet, attest the entire bullet after checking every number
and factual component. No substring synthesis or achievement inflation occurs.

## Local packet and review

Each preparation allocates a fresh exclusive `revision-NNNNNN` directory under a
sanitized, hash-suffixed job namespace. Existing originals and prior revisions
are retained, including revisions created by a failed final ledger update.
Files are private local artifacts, not GitHub attachments:

- `resume.docx`: single-column resume draft;
- `cover_letter_DRAFT.docx`: conservative application intent and supported skills;
- `application_answers_DRAFT.docx`: distinct name, education, skill and project
  answer prompts; missing facts and all legal/availability/motivation answers
  require explicit human input;
- `claims.json`: exact paragraph indices/text, claim IDs, source pointers/values,
  local attestation state/source/date, unresolved paths/reasons and input hashes;
- `qa.json`: revision, SHA-256 file identities, extraction/reading order, headings,
  single column, no tables/text boxes/macros/embedded objects/external relationships,
  long-text warnings and explicitly unexecuted rendering status.

The SHA-256 identities cover each DOCX and the claim trace. Identical inputs yield
identical DOCX bytes; revision allocation and packet metadata identify distinct
preparations. QA is structural evidence, not proof of truth, layout quality or
universal ATS compatibility. DOCX is the supported delivery format. PDF rendering
is an optional review aid, not an additional promised output format. Inspect every
page for font substitution, glyph coverage, wrapping, headings, page breaks,
clipping and blank pages on the intended Word/LibreOffice environment. Extraction
cannot measure pagination. A successful save is not visual QA.

The Issue #14 branch adds a [recoverable local workflow](LOCAL_WORKFLOW.md).
`review JOB_ID` returns the exact token for inspection; `approve` requires both
`APPROVE JOB_ID` and `--review-token TOKEN`. Managed preparation retains source
job/profile fingerprints and binds all five packet files, including QA itself.
Identical retries reuse an unchanged current packet; `--new-revision` regenerates
and invalidates approval. Old revisions and historical outcomes remain intact.
Legacy draft paths remain readable but require managed regeneration for a new
approval. Unresolved facts still need human review when structural checks pass.

Completed applications are rejected before document creation. A durable intent
and completion receipt support explicit restart reconciliation across filesystem
and SQLite operations. This is not a cross-resource atomic transaction or
protection against a malicious local OS account. No approval sends anything,
authenticates source truth or guarantees an ATS outcome.
