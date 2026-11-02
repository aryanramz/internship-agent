# Recoverable local preparation and tracking

Issue #14 builds on PR #27's document revisions, path/value attestations, claim
trace and structural QA. SQLite remains authoritative. No ChatGPT, MCP, Google,
model API, paid service or network request is required for the local workflow.
Nothing here submits an application or authenticates employer receipt.

## Complete local CLI flow

Use your ignored private profile and an authorized source configuration. For an
offline exercise, configure `json_import` with a local fictional posting file,
as in the end-to-end CLI tests. Never use example candidate data as your resume.

```text
internship-agent --data data discover --sources config/sources.json
internship-agent --data data source-health
internship-agent --data data availability --job-id JOB_ID
internship-agent --data data eligibility JOB_ID --profile config/profile.json
internship-agent --data data rank --profile config/profile.json --with-eligibility
internship-agent --data data preview JOB_ID --profile config/profile.json
internship-agent --data data prepare JOB_ID --profile config/profile.json --request-id local-review-1
internship-agent --data data review JOB_ID
```

Read the original posting and inspect every resume, letter and answer draft at
the returned paths, including `claims.json` and `qa.json`. Resolve uncertain
eligibility, withheld facts and user-input markers. Structural QA is not rendered
Word qualification, truth verification or an ATS guarantee. Review source
availability separately: an import or observation is not proof an opening is live.

`review` is read-only and returns the exact `review_token` for the unchanged job,
profile and five-file packet. After inspecting those revisions, copy that token:

```text
internship-agent --data data approve JOB_ID "APPROVE JOB_ID" --review-token TOKEN
```

Approval records a local operator decision; it performs no external action. Only
if you separately completed an application outside this program, you may record
your report, using that exact approved token:

```text
internship-agent --data data mark-submitted JOB_ID "Operator-supplied reference or URL" --approval-token TOKEN
internship-agent --data data status JOB_ID interview --evidence "Operator-supplied invitation reference"
internship-agent --data data application JOB_ID
internship-agent --data data export-tracker --output data/tracker_append_candidates.csv
```

The existing `submitted` status means **operator-reported submission**. New records
explicitly carry `submission_evidence_kind: user_supplied` and
`employer_receipt_verified: false`; audit events record `verification: unverified`.
Legacy evidence is labeled `legacy_user_supplied` without changing historical
bytes, timestamps or statuses. A URL, confirmation phrase or click does not verify
employer receipt. This issue implements no independent receipt-verification path.
CSV columns/status meanings remain compatible; document labels identify their
relative revision paths and notes qualify submission provenance. Sheets remains a
separate, previewed and explicitly authorized optional mirror.

## Repeats, changes and approval

- Repeating preparation with identical current job/profile/variant/track inputs
  reuses the same complete unchanged packet and preserves its current approval.
- `--new-revision` explicitly regenerates identical inputs into a new operation
  directory and clears approval. Different inputs generate a new revision too.
- A request ID identifies exactly one attempt for one job. Retrying that same
  committed current attempt is a no-op. Reusing it for changed inputs, a failed
  attempt or a superseded revision is rejected; inspect recovery and use a fresh
  ID. A new explicit request ID starts a new attempt, even for identical inputs.
- Approval requires both the exact confirmation phrase and current review token.
  Job-content, profile-content, document or QA changes reject approval/submission.
  Job refresh timestamps alone do not invalidate review. Preparation never
  authorizes an application, and recovery never restores approval.
- Approval/submission retries with the same token and evidence do not add audit
  events or duplicate rows. Conflicting submission evidence cannot replace the
  historical record. Repeating the same outcome/evidence is a no-op; existing
  transition guards still prevent reopening withdrawn/unsubmitted applications.

Profiles are re-read locally at review, approval and submission recording. Moving,
deleting or changing the bound profile requires new preparation. IDs, completed
outcomes, evidence, prior events and old document files are retained. Legacy
`Store.set_prepared` remains a draft-path compatibility setter; it never invents
provenance or grants a new approval binding, even for a complete foreign packet.
Legacy prepared/approved records must be regenerated through `Agent.prepare` or
the CLI before a new approval/submission. Completed historical records are not
rewritten or silently upgraded.

## Interruption and explicit recovery

```text
internship-agent --data data application JOB_ID
internship-agent --data data recover --job-id JOB_ID
internship-agent --data data recover
```

Preparation first obtains a SQLite writer lock and checks the application state.
Submitted, assessment, interview, offer, rejected and withdrawn records are
rejected before allocating a document directory or invoking generation. The
compatibility setter has the same state guard.

A committed `preparation_operations` intent precedes file generation and clears
old approval. Generation, completion-receipt publication and final ledger update
are serialized under a SQLite writer transaction. Every attempt owns a unique
`generated/operations/OPERATION_ID/.../revision-NNNNNN` directory. The existing
generator creates the packet; file contents are flushed before atomically
publishing its small completion receipt. A crash releases the SQLite lock and
rolls back the uncommitted ledger update, leaving a durable intent to reconcile.

Recovery acquires the writer lock. It attaches only a complete packet whose
receipt, hashes, claim-trace job/profile digests and current inputs agree, and
whose application still permits preparation. It attaches it as **prepared**, not
approved. Incomplete, changed or unsafe attempts are marked failed; all partial
files and prior revisions remain for inspection. Repeating recovery is a no-op.
Preparation also reconciles pending attempts for its job before retrying. A
competing command can receive a bounded busy/pending error; recover/retry after
the active writer finishes. No background worker, scheduler or automatic
submission retry is introduced.

The filesystem and SQLite are not one atomic transaction. The journal/receipt
protocol qualifies process interruption and restart; hardware/power-loss
durability still depends on SQLite, the filesystem, OS and private backups.
There is no deletion, garbage collection or automatic reconstruction of missing
private facts. A damaged packet is retained and requires a new preparation.
The local OS account and private directory ACLs remain trusted; hashes are not
authentication against a malicious local owner.

## Storage and compatibility

The workflow migration uses its own versioned `workflow_schema` table, leaving
the discovery layout and all existing application tables/rows intact. It sets
ledger `PRAGMA user_version=3` atomically with the new workflow schema so older
writers (whose supported maximum is 2) refuse unbound approval writes.
New journal, binding and submission-evidence tables are additive, transactional,
foreign-key constrained and serialized before inspecting workflow versions.
Unsupported future workflow versions are rejected. Read-only legacy reports do
not migrate a database. The three existing MCP tools and their selected fields
remain unchanged; private journal, profile paths, QA and review tokens stay local.
No Issue #15 scheduling, dashboard, browser actions or integration activation is
implemented by this change.
