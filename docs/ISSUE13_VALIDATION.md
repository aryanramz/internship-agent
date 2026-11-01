# Issue #13 validation evidence

Development date: November 1, 2026. All profiles, employers, achievements and
application receipts exercised here are fictional. Base: latest origin/develop
`1f31f5769101a6906dcd82d604c043cd2e2bfa3a`. Feature branch:
`feature/13-verified-document-variants`; PR targets develop and must stay unmerged.

## Local checks

Python **3.12.14**, isolated virtual environment, declared
`.[test,google,mcp,security]` extras. Live flags remained disabled. Supported
execution permission was used for proxy-backed dependency/GitHub/advisory access
and offline tests requiring local transport. The test network guard was unchanged.
The initial sandboxed full run stalled on local transport and was stopped; the
complete qualified run used the supported network execution permission. Preliminary
baseline attempts using an archive/editable source mismatch were discarded; a
clean detached baseline worktree with its own editable install passed **982 tests,
7 skips, 22 subtests in 15.20s** before restoring the feature editable install.

Final feature run: `python -m pytest -q -ra` — **1,018 passed, 7 skipped,
22 subtests passed in 21.56s**. The 36 new document regression cases cover exact
claim links, missing/unverified/conflicting/stale facts, identity dependencies,
metrics, variants, numerical source ordering, empty skills, Unicode/long content,
links, resource bounds, legacy calls/MCP privacy, approval invalidation, retained
historical states, modified/missing files, safe namespaces, concurrent revisions,
and fictional CLI round trips. Existing ranking and eligibility suites pass.

The seven skips are expected qualification boundaries:

- Three ATS opt-in live requests (`RUN_LIVE_ATS` disabled).
- Two daily-script preflight tests needing unavailable `pwsh`.
- One synthetic Sheets live write (`RUN_LIVE_SHEETS` disabled).
- One Windows lifecycle preview needing unavailable Windows PowerShell.

`compileall -q src`, `pip check`, the fresh synthetic demo, repository hygiene and
`git diff --check` passed. No missing Google/MCP-extra skips. `actionlint` is not
installed; workflow configuration was unchanged, inspected, and is executed by PR
CI rather than claimed locally linted. CI results are available on the PR checks.

## Rendered document QA

Renderer: **LibreOfficeDev 26.8.0.0.alpha0**, build
`2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`; Poppler **26.05.0** for PNG rendering,
and installed `pdftotext` for layout/bounding-box extraction.

Rendered 12 DOCX documents (resume, letter, answers for each of four fictional
packets) to **14 PDF pages**:

| Fixture | Resume | Letter | Answers |
|---|---:|---:|---:|
| Master / synthetic example profile | 1 | 1 | 1 |
| Systems track / same profile | 1 | 1 | 1 |
| Job / Unicode, long bullet, empty skills | 1 | 1 | 1 |
| Job / eight long bullets | 3 | 1 | 1 |

Every expected paragraph was found in PDF text in order after whitespace/Unicode
normalization. All extracted word boxes stayed within page bounds. The developer
inspected rasterized pages/contact sheets, including all three stress-resume
pages: no clipped text, missing Unicode glyphs, orphan headings or unexpected blank
pages observed. Long bullets can span pages; the generator warns about long text
and never silently truncates it. This is a stress layout, not a recommendation to
submit a three-page internship resume.

Reproduction uses `soffice --headless --convert-to pdf --outdir TEMP DOCX...`, a
fresh local LibreOffice user profile, `pdftotext -layout`, `pdftotext -bbox`, and
`pdftoppm -scale-to 1000 -png PDF PREFIX`, followed by actual image inspection.
Temporary local machine-readable rendering evidence records DOCX SHA-256 values,
page counts, extraction order and visual observations. Generated documents, PDF
renders, images and private traces were not committed or uploaded. Per-packet
`qa.json` accurately records generation-time structural checks and `rendering:
not_run`; visual qualification is a separate local exercise.

## Independent reviews and security

Two fresh reviewers separately inspected the changed source/tests against the
base, one for correctness and one for security/PII. Both used synthetic local
reproductions; neither performed external requests. This was independent manual
source review, not an automated Codex Security scan or a production penetration test.

Confirmed findings were fixed and pinned by failing-then-passing regressions:

1. Lexically sorted pointers put index 10 before index 2; source traversal order
   now preserves master/list reading order.
2. Missing name/education claims could leave blank answer sections; every wholly
   unsupported answer now has an explicit user-input marker.
3. Adding document configuration changed the historical preview/MCP overlap;
   previews now retain that projection independently of document attestations,
   with an explicit warning about unverified legacy labels.
4. Inherited first-person title interpolation could assert attacker-supplied
   certification/authorization text. Titles/employers now appear only as labeled
   untrusted posting fields, with a fixed application-intent sentence.

No additional confirmed source-security or PII finding remains from those reviews.
No deferred minor finding was reported. Local SHA-256 checks detect accidental
packet changes before approval, not a malicious trusted OS account.

The strict installed-inventory `pip-audit` initially reported 12 advisory records
(six distinct IDs) affecting the virtual environment's **pip 25.0.1**. Updating that
development tool to **pip 26.2.2**, matching CI's existing pip-upgrade step, resolved
them without changing project dependency ranges. The final strict audit of the
complete pinned installed inventory reported **No known vulnerabilities found**.
Audit used the declared security extra and a writable temporary cache; advisory
lookup retained the proxy and TLS verification. This is point-in-time advisory
coverage, not proof that all software is vulnerability-free.

## Remaining limits

Attestations record local user confirmation, not independent fact authentication.
Contradictory declarations on one path are detected; semantic contradictions in
free text across different paths still need human review. Legal/authorization,
availability and employer-motivation answers remain user-input markers. DOCX is
the supported output; PDF was a review aid, and other renderers/Word/Windows remain
unqualified. No ATS success guarantee is made.

Issue #14 remains separate: no file/DB transaction, restart reconciliation,
submitted-state pre-generation guard or submission-evidence redesign. A rejected
final completed-state ledger update can leave an unreferenced new revision, while
old files/state/evidence remain intact. Legacy packets keep the existing approval
contract. No live integration, external endpoint, release/version bump, submission,
message sending, main-branch change or merge was performed.

## Sanitized local dependency inventory

Exact installed versions used for the final tests/audit (not a new lockfile):

```text
annotated-types==0.8.0
anyio==4.16.0
attrs==26.1.0
boolean.py==5.0
CacheControl==0.14.4
certifi==2026.10.23
cffi==2.1.1
charset-normalizer==3.5.2
click==8.5.0
cryptography==50.0.2
cyclonedx-python-lib==11.12.0
defusedxml==0.7.1
filelock==4.2.6
google-api-core==2.43.2
google-api-python-client==2.201.0
google-auth==2.62.0
google-auth-httplib2==0.4.4
google-auth-oauthlib==1.5.0
googleapis-common-protos==1.76.0
h11==0.16.0
httpcore2==2.16.0
httplib2==0.32.1
httpx2==2.16.0
idna==3.20
iniconfig==2.3.1
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
license-expression==30.4.4
lxml==6.1.3
markdown-it-py==4.2.0
mcp==2.3.0
mcp-types==2.3.0
mdurl==0.1.2
msgpack==1.2.4
oauthlib==4.0.1
opentelemetry-api==1.45.2
packageurl-python==0.17.6
packaging==26.3
pip==26.2.2
pip_api==0.0.35
pip_audit==2.10.1
pip-requirements-parser==32.0.1
platformdirs==4.14.3
pluggy==1.7.0
proto-plus==1.29.0
protobuf==7.36.2
py-serializable==2.1.0
pyasn1==0.6.5
pyasn1_modules==0.4.2
pycparser==3.12
pydantic==2.14.2
pydantic_core==2.50.2
Pygments==2.21.0
PyJWT==2.15.1
pyparsing==3.3.3
pytest==9.2.0
python-docx==1.2.0
python-multipart==0.0.33
referencing==0.37.0
requests==2.34.2
requests-oauthlib==2.0.0
rich==15.0.0
rpds-py==2026.9.1
sortedcontainers==2.4.0
sse-starlette==3.6.0
starlette==1.10.0
tomli==2.5.0
tomli_w==1.2.0
truststore==0.10.5
typing_extensions==4.16.0
typing-inspection==0.4.4
uritemplate==4.2.0
urllib3==2.8.0
uvicorn==0.54.0
```
