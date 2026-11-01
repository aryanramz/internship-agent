# Explainable ranking implementation plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement these tasks in order with test-first checks and an independent whole-branch review.

**Goal:** Implement Issue #12 with deterministic preference-aware fit and separate eligibility.

**Architecture:** Keep six fit components and default weights (35/25/15/10/10/5). Add bounded pure ranking configuration and role taxonomy modules; local reports gain explanations, while MCP explicitly projects its existing fit fields. No database/schema or eligibility-evaluator change.

**Tech stack:** Existing Python 3.11–3.13 standard library, pytest, CLI, SQLite and MCP.

**Spec:** GitHub Issue #12 and the implementation request; detailed behavior is documented in `docs/RANKING.md` with the feature.

## Constraints

- Branch `feature/12-explainable-ranking`, base `cd85c434d642c173dfac1b5f7fdd3030d91f0c1b`; post-merge CI 41280116578 succeeded.
- Preserve profiles, identities/history, three read-only tools, privacy and approvals.
- No paid service, dependency addition, AI integration/calibration, external activation or Issue #13 work.
- Keep legacy field names/types; document deliberate role corrections and stable ID tie-breaking.

## Review focus

Unknown role phrases must not broaden via generic words; preferences cannot alter unrelated components; booleans/NaN/oversized values must fail safely; private experience/preferences must not leak through MCP; high fit cannot erase uncertain/ineligible assessments.

## Tasks

1. **Configuration and taxonomy.** Create `ranking_config.py` and `role_taxonomy.py`, with tests in `tests/test_ranking.py`. Test absent/legacy configuration, finite bounded weights totaling 100, conflicts and size limits. Test exact title aliases, curated adjacent tracks, unknown multiword phrases and false positives (physical security, HR systems, cloud sales, JavaScript/Java, incidental description words). Run failing tests before implementation; then focused tests.
2. **Scoring and explanation.** Modify `scoring.evaluate(job, profile, *, as_of=None)` while preserving existing response keys and baseline weights/skill formula. Configured experience relevance affects only skills. Preferences for work mode/location, employers, compensation affect only their component. Add local `ranking_explanation` with units, weights, contribution trace, posting evidence, preference effects, missingness and qualitative confidence. Inject date for deterministic freshness, including future/malformed dates. Tests pin component isolation, skill boundaries, experience provenance and no network/model dependency.
3. **Service/CLI/MCP integration.** Share one clock per ranking invocation, stable final job-ID tie-break, keep `--with-eligibility` assessment opt-in and add explicit action guidance. Default CLI gains local explanation; MCP uses an explicit legacy-fit allowlist in both ranking and preview so no experience/preferences/structured declarations escape. Test legacy/v2 profiles, CLI errors, stable order, readonly bytes and real MCP projections.
4. **Documentation and qualification.** Add `docs/RANKING.md` with schema/example, taxonomy/adjacency, intentional behavior changes and limits. Update capability/architecture/roadmap/handoff references without completing R2 or starting #13. Run full offline suite, hygiene, compile, pip check, synthetic demo, documentation/config checks, independent correctness/privacy/security review. Fix findings, push only feature branch, create PR to develop, wait for successful CI and leave unmerged.

## Execution record

- Configuration/taxonomy/scoring tests first failed against the old evaluator (64 failures); first implementation passed 63 cases, with one incorrect empty-experience expectation corrected because an empty list is valid missing information.
- Service tests reproduced unstable ID ties and missing eligibility action labels; MCP test reproduced local-explanation leakage before the explicit projection fix.
- First integrated full suite: 930 passed, 7 skipped, 22 subtests. Additional tests reproduced generic/noncomputing role matches, missing experience disclosure, writable CLI rank initialization and duplicate/oversized ranking profile input; corrected with 104 focused passes.
- Ruling: no optional analyzer or calibration hook — no labeled dataset or required free integration exists; deterministic-only behavior and explicit unsupported-configuration rejection avoid a new service boundary.
- Qualification and independent whole-branch review follow; existing historical validation counts remain attributed separately.
