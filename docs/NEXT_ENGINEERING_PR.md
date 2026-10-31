# Next engineering handoff — explainable ranking

[Issue #9](https://github.com/aryanramz/internship-agent/issues/9) implements
three-provider ATS qualification and the compatible employer registry;
[live evidence](LIVE_ATS_VALIDATION.md) and
[registry compatibility](EMPLOYER_REGISTRY.md) record its scope.
[Issue #10](https://github.com/aryanramz/internship-agent/issues/10) implements
[incremental discovery, health/backoff and conservative availability](DISCOVERY_LIFECYCLE.md).
R1 engineering acceptance is separate from formal release preparation/publication.

This revision implements [Issue #11](https://github.com/aryanramz/internship-agent/issues/11):
[private versioned facts and evidence-backed structured eligibility](ELIGIBILITY.md).
After its acceptance, the next engineering scope is
[Issue #12](https://github.com/aryanramz/internship-agent/issues/12), explainable
ranking, taxonomy and user preferences. It has **not** been started by the
eligibility implementation. Read the current issue and its dependencies before
opening a separate branch from the latest accepted `develop`.

## Boundary to preserve

- SQLite remains the authoritative application ledger. Preserve posting IDs,
  schema version, discovery checkpoints, availability evidence, application
  states and events; source availability is not an application outcome.
- Existing `scoring.py` weights, score components, sorting and default `rank`
  output remain the compatibility baseline. Issue #11 changes none of these.
- Structured `eligible`/`uncertain`/`ineligible` is separate from fit. A high fit
  score cannot override a failed mandatory eligibility rule. Missing or
  unverified candidate information must not become a definite negative.
- Preserve private profile v2 facts and provenance and legacy profile behavior.
  Do not infer sensitive/legal facts or expose declarations through MCP.
- Keep MCP's exact three read-only tools and minimal default projections. Full
  eligibility facts/evidence are local-only reports; consequential actions retain
  explicit approval requirements.
- Ranking evaluation uses fictional fixtures, stable clocks, explicit evidence
  and offline tests; do not invent accuracy or hiring-probability metrics.

## Existing foundations

| Concern | Files / guidance |
|---|---|
| Current fit behavior | `src/internship_agent/scoring.py`, `service.py`, `cli.py` |
| Private candidate facts | `src/internship_agent/eligibility_profile.py`, [schema](ELIGIBILITY.md) |
| Requirement/evaluation boundary | `src/internship_agent/eligibility_requirements.py`, `eligibility.py` |
| Compatibility tests | `tests/test_agent.py`, eligibility integration/posting tests, MCP read-only tests |
| Scope and release dependencies | [Roadmap](ROADMAP.md), [capabilities](CAPABILITIES.md), [release gates](RELEASE_PLAN.md) |

## Exclusions

Issue #13 owns document variants and claim QA; #14 owns recoverable application
workflow and document-bound approvals; #15–#20 own later scheduling, interfaces,
browser/recruiter workflows, analytics and cloud decisions. Do not fold them into
ranking changes. R2 requires #11–#13 plus release preparation; #11 alone does not
complete it. No version bump or release is implied.

Issue #3 remains an independent optional-interface track and stays open until
actual authenticated ChatGPT invocation succeeds. No external endpoint, Funnel,
service installation, paid dependency or new permission is authorized by this
handoff. Keep `main` unchanged and follow the explicit review/merge authorization
for the next task.
