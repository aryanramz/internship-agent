# Issue #14 validation evidence

Baseline: accepted `origin/develop` at
`ada3cda4c5a9207811a549db84a80fa4515513d0` (merged PR #27). Feature branch:
`feature/14-recoverable-workflow`. Every profile, posting, receipt and database
used in this work is synthetic. No live integration or application was activated.

## Local native Windows

Python **3.12.6**, locale **cp1252**, `PYTHONUTF8=0`, UTF-8 mode **0**. The final
isolated environment did not inherit system site packages and installed all
declared `.[test,google,mcp,security]` extras. Live ATS/Sheets flags were **0**;
the offline network guard was unchanged. Supported elevated execution was used
for dependency/advisory/GitHub access and offline tests requiring local sockets.

- Full offline suite: **1,060 passed, 5 skipped, 22 subtests passed in 181.58s**.
- Separate core-only environment (`.[test]`, actual MCP/Google SDKs absent):
  **38 passed in 53.90s**. The real CLI is additionally exercised with imports
  of optional SDKs explicitly denied, including Unicode job/profile data.
- Compileall for source/scripts, dependency consistency, fresh synthetic demo,
  and diff whitespace checks passed. The demo stops at prepared, exposes local
  review evidence, and confirms identical preparation reuses the revision.
- Strict audit of the isolated pinned installed inventory: **No known
  vulnerabilities found**. Dedicated pip was updated to 26.2.2, matching the
  existing CI setup. No project dependency range or paid dependency changed.

The five Windows skips are three opt-in live ATS tests, one opt-in live Sheets
write, and one POSIX-only credential permission test. There were no missing SDK
skips. `actionlint` was unavailable locally; workflow configuration is qualified
by actual PR CI execution, not claimed locally linted.

Selected exact installed versions: pip **26.2.2**, pytest **9.2.0**, python-docx
**1.2.0**, MCP **2.3.0**, google-api-python-client **2.201.0**,
google-auth-oauthlib **1.5.0**, cryptography **50.0.2**, pip-audit **2.10.1**.
Dependency audit covers the full pinned installed inventory, not only this list;
resolutions remain point-in-time rather than a new project lockfile.

## Recovery, regression and end-to-end coverage

New coverage checks state rejection before generation/file mutation for every
completed status; retry reuse and explicit regeneration; changed job/profile/
DOCX/QA and stale review tokens; idempotent approval, submission and outcome
recording; conflicting submission rejection; parallel writers and single records;
and preservation of completed approval/submission history after posting changes.

Failure injection covers intent-only, interrupted file writing, complete receipt
before ledger update, and interruption after SQL changes before commit. Real
child processes call `os._exit` before/after commit; restarted agents reconcile
or reuse their exact operations without duplicate audit entries. Recovery also
rejects changed inputs, unsafe receipt paths, modified packets and malformed QA.

Migration tests preserve IDs, original rows, statuses, notes, evidence, events,
discovery state, custom indexes/triggers and foreign keys. They cover repeat and
concurrent upgrades, rollback after injected DDL failure, nested transactions and
unsupported future versions. Discovery layout remains unchanged; the additive
workflow schema is atomically fenced by ledger `user_version=3` so older writers
reject the new approval contract.

The real CLI discovers a fictional local JSON source and exercises eligibility,
ranking, preview, prepare/retry, read-only review, token-bound approval, explicitly
operator-reported tracking, history, CSV export and recovery. No actual external
application occurs. Historical tests and the Sheets qualification harness now use
complete synthetic managed preparations instead of approving placeholder paths;
no Sheets authorization or write implementation changed.

## Independent reviews

Separate fresh-context correctness and manual security/PII reviewers inspected
the scoped runtime/test diff and performed synthetic reproductions without
network access. Both confirmed the same compatibility-import bypass: a valid
foreign packet could acquire a new job binding while losing profile tracking.

That finding was fixed: the legacy setter only records unbound draft paths;
new approvals require a managed journal-backed preparation, with an operation
foreign key and retained job/profile fingerprints. Wrong-job and stale-profile
import regressions were observed failing before the correction and passing
afterward, followed by the complete green suite. No additional confirmed finding
remained from either review. This was manual source review plus dependency audit,
not an automated Codex Security scan or a production penetration test.

## Hosted CI and remaining limits

Existing Linux Python 3.11/3.12/3.13, native Windows Python 3.12 with UTF-8 mode
disabled, and dependency-security checks are retained. A separate Linux core-only
job verifies SDK absence and runs workflow/recovery/migration/CLI tests. Exact
implementation-head results at `6781a51ede9bc9fced49c9398d0a2e6ad86136aa`:

[CI run 41368268763](https://github.com/aryanramz/internship-agent/actions/runs/41368268763)
passed all six jobs. Checkout logs confirm the exact head merged into baseline
`ada3cda4c5a9207811a549db84a80fa4515513d0` for testing.

| Job | Exact result | Pytest duration |
|---|---|---:|
| Windows / Python 3.12 | 1,060 passed, 5 skipped, 22 subtests passed | 145.98s |
| Linux / Python 3.11 | 1,060 passed, 5 skipped, 22 subtests passed | 41.29s |
| Linux / Python 3.12 | 1,060 passed, 5 skipped, 22 subtests passed | 43.97s |
| Linux / Python 3.13 | 1,060 passed, 5 skipped, 22 subtests passed | 44.74s |
| Core-only / Linux Python 3.12 | 38 passed; optional SDK absence asserted | 11.82s |
| Security | No known vulnerabilities found | Audit succeeded |

Windows reported `locale.getencoding(): cp1252` and UTF-8 mode 0. Its separate
document regression step passed **36 tests in 9.13s**. Every full-suite test job
also passed compilation, hygiene (**137 files, zero problems**) and the synthetic
demo. Windows/core-only dependency consistency passed. Linux's five skips were
the four live opt-ins and Windows PowerShell lifecycle preview; Windows skips are
listed above. The unmerged PR records final-head results after the documentation
follow-up, which does not change runtime or tests.

The workflow qualifies process crash/restart, not power-loss durability across
all OS/filesystem/storage combinations. Hardware durability, private backups and
local OS ACLs remain operator responsibilities. Hashes/tokens do not authenticate
a human or defend against a malicious trusted OS owner. Facts and rendered Word
layout still require human verification; no ATS outcome is promised. Submission
evidence remains user-supplied/unverified, including preserved legacy records.
There is no independent employer-receipt verification, automated application,
external integration activation, scheduler/Issue #15 work, release or main-branch
change. The PR must remain unmerged for human review.
