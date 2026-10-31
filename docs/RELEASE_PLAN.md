# Versioning, release slices and acceptance

## Versioning decision

Keep pre-1.0 semantic versioning. Named gates R1–R7 schedule work; assign/publish
a numeric version only after acceptance. I1 is optional ChatGPT qualification and
can join the next accepted release without blocking local progress. This roadmap
creates no release, tag or runtime version bump.

At reconciliation, package metadata is 0.4.0, `__init__.__version__` is 0.1.0 and
the MCP descriptor is 0.4.0. No tags/GitHub Releases were found. Preserve changelog
0.1–0.4 development history without retroactively claiming publication. The old
v0.5/v0.6 roadmap mixed finished validation, unfinished ChatGPT access and document
QA. New versions describe coherent accepted outcomes, not those old phase labels.

Before the next release, align package/runtime/server version reporting and the
changelog in a focused release-preparation change, preferably using one version
source. This unrelated runtime change is excluded from the next ATS/registry PR.
Backward-incompatible local schemas/interfaces require an explicit pre-1.0 minor
change plus migration/rollback notes; compatible fixes use patches.

Issues #9/#10 provide the R1 discovery engineering evidence; see
[discovery qualification and recovery](DISCOVERY_LIFECYCLE.md). They do not publish
a release. Version alignment, clean-package qualification and release-preparation
review remain outstanding before claiming the full publication gate is satisfied.

## Release gates

Every row also requires the common checks below. Versions are recommendations,
not deadlines or claims that features already exist.

| Milestone | Candidate version | Required evidence |
|---|---|---|
| [R1 — Reliable discovery](https://github.com/aryanramz/internship-agent/milestone/1) | 0.5.0 | #9: one permitted Greenhouse/Lever/Ashby board each and compatible employer registration. #10: resumable scans, health/backoff, conservative closure/reopening and history-safe dedup. Blocked live checks cannot pass the gate. |
| [R2 — Eligibility/matching/documents](https://github.com/aryanramz/internship-agent/milestone/2) | 0.6.0 | #11: known/missing/conflicting facts yield eligible/uncertain/ineligible reasons. #12: deterministic preferences and component explanations, separate from eligibility. #13: claim provenance, extracted text and rendered visual QA on fictional track/job variants. |
| [R3 — Complete local workflow](https://github.com/aryanramz/internship-agent/milestone/3) | 0.7.0 | #14: fictional discovery→eligibility→rank→prepare→review/approve→tracking without MCP/Google. Restart/retry cannot reuse stale approval, duplicate actions or lose history; externally supplied evidence is labeled honestly. |
| [R4 — Scheduling/dashboard](https://github.com/aryanramz/internship-agent/milestone/4) | 0.8.0 | #15: native Windows sign-in/restart/missed-run/overlap/stop evidence. #16: accessible local dashboard, CLI fallback, local-request security and confirmations. Routine work avoids shell commands after reviewed setup. |
| [R5 — Browser assistance](https://github.com/aryanramz/internship-agent/milestone/5) | 0.9.0 | #17: one permitted flow, concrete authorization, verified facts/documents, MFA/CAPTCHA handoff, evidence and no blind retry after uncertain submission. Ordinary CI never submits a real application. |
| [R6 — Recruiter/analytics](https://github.com/aryanramz/internship-agent/milestone/6) | 0.10.0 | #18: verified contact/draft/reply/follow-up behavior, optional Google. #19: reconciled cohorts with samples/denominators/unknown outcomes. Sending remains separately authorized per concrete message. |
| [R7 — Cloud assessment](https://github.com/aryanramz/internship-agent/milestone/7) | None promised | #20 only after R1–R6. A no-go is valid if no secure zero-additional-cost option exists. Decision record only, no resources/provisioning. |
| [I1 — ChatGPT qualification](https://github.com/aryanramz/internship-agent/milestone/8) | Next suitable accepted release | #3: actual authenticated invocation, OAuth/refresh/restart and exposure evidence. PR #8 review/private startup qualification precede separately authorized Funnel testing. Does not gate R1–R4. |

## Common acceptance and publication procedure

1. Confirm exact develop revision/dependencies. Separate pending PRs from merged
   capability and update [CAPABILITIES.md](CAPABILITIES.md).
2. Run the full offline suite with relevant extras, compilation, dependency
   consistency, privacy and diff checks. Preserve the CI matrix. Run advisory and
   security checks appropriate to new dependencies or auth/network/write surfaces;
   report review coverage and limitations.
3. Use synthetic fixtures and isolated databases. Live checks are opt-in,
   authorized and bounded, with dated endpoint/status evidence. A skipped or
   blocked exercise is not a pass. Publish no raw private payloads or credentials.
4. Verify migrations, restart recovery, approval paths and history preservation.
   External content is data; OAuth/API errors must not expose tokens/PII.
5. Define metric evidence, sample, denominator and time window. Passing tests is
   not an ATS guarantee, uptime measure or hiring probability.
6. Align versions/changelog and record completed/deferred scope. Inspect built
   package contents for private artifacts and test installation in a clean
   environment before claiming an installable release.
7. Open a reviewed release-preparation PR targeting develop. Promotion to main,
   tag/release publication and public connection activation each require explicit
   authorization. This roadmap authorizes none of them.

No API billing, paid hosting/domain/subscription, payment method, metered resource
or automatic upgrade is acceptable. Keep local operation when a cost, permission
or connection condition fails. Python/SQLite/CLI must not require a ChatGPT
account, Google grant or the optional Keycloak stack.
