# Local recruiter outreach

Issue #18 adds local contact/source evidence, fact-bound drafts, private manual
correspondence imports and follow-up suggestions. **There is no email sending
capability.** No SMTP, Gmail read/refresh/write, OAuth activation, inferred-address
enrichment, contact scraping, mailto launch or bulk clipboard automation is added.
Google's existing gmail.readonly/Sheets separation and job-alert workflow stay intact.

## Workflow and evidence definitions

Open the existing private dashboard and choose **Outreach**. Existing loopback
access secret/session, exact numeric Host/Origin/Referer checks, per-POST rotating
CSRF and request limits protect every mutation. Loading a view is read-only and
never creates or migrates SQLite. An existing local job ledger is needed to write.

1. Register a documented contact for an exact saved job/company. Use an explicitly
   copied address, documented name/role, employer domain, source/method, observed
   UTC timestamp and permission state. Choose the saved job or enter its stable ID.
2. Inspect the exact contact evidence and use `VERIFY <contact_id>`. Verification
   binds the displayed contact hash. It records a human's evidence-backed local
   attestation, not authenticated ownership, deliverability, consent or willingness.
3. Approve the current job document packet through the existing workflow first.
   Create an intro, application follow-up or reply draft. Read-only packet lookup
   supplies the existing exact review token; outreach never approves documents.
4. Edit editor-required prompts into factual human-authored text. Review the full
   recipient, employer, subject/body, verified facts and packet/job/profile binding.
   `REVIEW <draft_id>` also requires the displayed revision/content hash. A stale
   preview cannot approve a different revision. Edits clear the previous review.
5. Optionally export the exact reviewed RFC822 draft for manual use. **Export is
   not send evidence.** No message is sent and no external mail client is opened.
6. Only after a separate external action, record operator-supplied send evidence,
   UTC date, exact message/thread IDs and confirmed/uncertain state. These are
   unverified operator reports. Records bind immutable draft revision/content,
   recipient and evidence hashes; retries cannot replace historical content.
7. Configure suggestion-only follow-up policy. Import fictional/manual message
   JSON to inspect conservative reply matching, or explicitly record opt-out.
   There is no mailbox connection behind the import form.

Contact data uses conservative single ASCII addresses and non-public-mail employer
domains. Unsupported IDN/numeric-domain or complex mailbox formats are refused,
not guessed. Official evidence requires an exact HTTPS employer host; manual
source documentation must identify the exact employer and address. No source URL
is fetched. Observations in the future or without UTC are rejected. Evidence ages
out after 90 days. Domain/name/address collisions, changed identity and source
corrections invalidate verification and draft reviews. Conflicts affect both
identities; an operator cannot bypass an active competing identity by reverifying.
Manual verification remains dependent on the operator recognizing a false source;
this does not authenticate a domain's relationship to an employer independently.

Drafts are deterministic local templates using current, locally attested applicant
name/sender email and current job/company context. Unknown information remains an
editor-required prompt, and review refuses unresolved prompts. Templates never
invent a prior application, referral, connection, skill, title or legal fact.
Reply drafts additionally bind an existing conservatively matched source message.
User edits remain user-authored text requiring independent human fact review; the
software cannot authenticate every assertion in free text. Structural document
QA is not truth verification or ATS acceptance. The current sender, recipient,
contact/source evidence, profile/job/packet integrity and draft revision are
checked again under the writer transaction before review/export/send recording.

## Safe correspondence matching

The message form accepts one bounded JSON fixture, with explicit canonical fields:

```json
{"message_id":"<fictional-reply@employer.test>","thread_id":"fictional-thread",
 "from_email":"recruiter@employer.test","to_email":"candidate@example.test",
 "in_reply_to":"<fictional-sent@example.test>","references":[],"cc":[],
 "sent_at":"2026-11-05T12:00:00Z","subject":"Fictional reply",
 "body":"Fictional local fixture only.","text_format":"plain",
 "forwarded":false,"bounce":false,"optout":false}
```

A match requires a current evidenced contact, exact sender/recipient, thread and
recorded In-Reply-To/References to an operator-recorded send. Subject and display
names never establish association. Aliases, forwarded/multi-recipient, unknown or
cross-employer evidence remain review-only (malformed unsupported headers may be
refused). Matching is labeled `matched_unverified`, not an authenticated recruiter
response or positive hiring outcome. A bounce from an unknown mailer-daemon with
strong send references suppresses suggestions without impersonating the recruiter.
Even unclear messages from a contact, address case variants, collisions or strong
reply references can conservatively suppress suggestions pending operator review.

Message IDs/content hashes and incremental operation/checkpoint records make
reordered/repeated import idempotent. A reused ID with changed content becomes a
collision; original content is not overwritten. Transaction failure rolls back
schema/import/checkpoint together, and retry is explicit. Bodies stay private and
inert; HTML is displayed as text, with no attachment execution, external link
fetch, tracking pixel or positive-response inference. Detail output is bounded
and marks truncation. UI body input is capped at 8,000 characters; total JSON
requests/stdin are capped at 16 KiB. Unsupported/unbounded input is refused.

## Suggestions, opt-outs and privacy

Suggestions require explicit enabled policy, permission `allowed`, nonstale verified
contact evidence, and a confirmed operator send record with date and provenance.
An exported draft alone, uncertain send, wrong recipient, closed application,
reply/bounce/opt-out or unclear incoming evidence produces no suggestion. Policies
use 7–90 day intervals and a minimum contact interval; UTC elapsed-day arithmetic
avoids local DST duplicate reminders. At most the latest eligible send per contact
is suggested; IDs are deterministic, dismissal persists, and GET never writes a
reminder. No automatic follow-up draft, send, escalation or scheduler task exists.

Opt-outs add an address-hash suppression sentinel. They are visible separately
from identity verification and are never automatically undone. Address changes
retain an old-address suppression marker. Explicit contact redaction clears
contact PII, related draft/revision content, send addresses/evidence and related
message content while retaining audit digests and suppression. Individual message
redaction and explicit retention pruning (30–3,650 days, at most 100 eligible
records per confirmed action) retain matching/suppression hashes and historical
job/application evidence. Raw bodies never go into shared logs or job-alert tables.
Do not manually delete suppression rows to work around an opt-out.

All state stays in the authoritative agent.db. Versioned additive `outreach_schema`
and `outreach_messages_schema` install only on explicit mutation, under an immediate
SQLite writer transaction. Unsupported future versions fail closed; failed writes
roll back. Existing IDs, application statuses/revisions, browser-intent history,
CLI and exactly three read-only MCP tools remain unchanged. Back up the private
ledger before operational use. Do not copy private contact/draft/message JSON,
exports, profiles or the ledger into issues, screenshots or version control.

## CLI, launch and recovery

Use the ordinary dashboard launch (`internship-dashboard --root PATH`) and Ctrl+C
stop. No extra server, browser dependency, paid SDK or persistent task is needed.
The standalone CLI works without Google/MCP/Playwright:

```
internship-outreach --root /absolute/checkout get contacts
internship-outreach --root /absolute/checkout get contact --id CONTACT_ID
internship-outreach --root /absolute/checkout get drafts
internship-outreach --root /absolute/checkout get draft --id DRAFT_ID
internship-outreach --root /absolute/checkout get messages
internship-outreach --root /absolute/checkout get message --id MESSAGE_ID
internship-outreach --root /absolute/checkout get followups
```

`python -m internship_agent.outreach_cli` is equivalent. Mutation JSON comes from
bounded UTF-8 stdin, keeping bodies out of process arguments. For example, pipe
private JSON into `internship-outreach --root PATH action register-contact`.
Payload `confirm` must equal the action name. Verification uses `id`, `verifier`,
`phrase: VERIFY ID`, `expected_contact_hash` from the displayed contact. Draft
review uses `id`, `phrase: REVIEW ID`, `expected_revision`, and
`expected_content_hash` from its exact preview. Export/record-send additionally
require its current `review_token`. Tokens and recipient data are private; don't
publish CLI output. UI forms provide these bindings without copying opaque tokens.

Other explicit action names: `edit-contact`, `optout` (`OPTOUT ID`),
`redact-contact` (`REDACT ID`), `create-draft` (`contact_id`, `purpose`, existing
`packet_review_token`, optional matched `source_message_id`), `edit-draft`,
`import-message` (`message`, optional operation_id/checkpoint), `match-message`,
`followup-policy`, `dismiss-followup`, `redact-message`, `prune-messages`.

For a stale preview, refresh and inspect the changed evidence before reviewing.
For stale job/profile/documents, create a fresh correctly bound draft after the
existing document workflow review; don't reuse an old token. A browser timeout is
not proof a record failed: inspect current state and immutable events before an
explicit retry. Conflicting send evidence cannot replace an old record. Storage
busy/read-only/corrupt or future-version errors expose no raw exception details;
inspect private backups and competing writers, never force a schema downgrade.

## Qualification boundaries

All fixtures/screenshots/CI messages are fictional; actual Chromium exercises the
complete local workflow and keyboard confirmations with external traffic blocked.
Linux/Windows/core-only tests cover migration/history, MIME injection, stale
bindings, strong/ambiguous replies, fake clock/UTC/DST, suppression/redaction and
recovery. The PR records exact head/base, counts/skips, review fixes and CI links.

Live Gmail reading, account selection/permissions and actual recruiter identity,
address ownership, delivery or replies remain unqualified. No Gmail correspondence
reader is implemented; existing job-alert grants cannot quietly access messages
through this feature. Any future mailbox reader requires separate opt-in/account
selection and read-only scope; sending requires a separate approved design and
concrete consent. Windows desktop-browser/screen-reader sessions, Issue #15 task
lifecycle and Issue #17 real-provider/browser qualification remain open. This
change starts no Issue #19 work and does not close #18 from offline evidence alone.

On Windows PowerShell, provide UTF-8 stdin (for example set `$OutputEncoding` to
`[System.Text.UTF8Encoding]::new($false)`) or use ASCII-escaped JSON. Console JSON
output escapes non-ASCII characters for CP1252/UTF-8-disabled compatibility.
Contact records intentionally bind one exact saved job; reusing an address for a
second identity/job is refused rather than guessing a relationship. Complex
mailbox/alias formats and multi-job contact reassignment need separate review.
