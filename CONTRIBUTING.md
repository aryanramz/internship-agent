# Contributing

Contributions are welcome to improve job-source reliability, accuracy, accessibility, and safety.

1. Open an issue describing the bug or proposal. Do not attach real resumes, job-application records, OAuth tokens, mailbox exports or secrets.
2. Read the [roadmap](docs/ROADMAP.md), [capability evidence](docs/CAPABILITIES.md) and issue dependencies. Branch from latest `develop` and make a small focused change; do not modify `main` directly.
3. Add or update offline tests and documentation; source adapters should test against synthetic/mocked responses.
4. Run `python -m pytest -q`, `python scripts/check_repo_hygiene.py` and `python -m compileall -q src`.
5. Open a pull request targeting `develop`, explaining scope, test results, risk and data/privacy impact. Leave it unmerged for review; pending PRs are not implemented baseline features.

For documentation changes, validate local Markdown links/anchors and check
commands/tool names against code. Report live checks as developer-run,
operator-reported, skipped or blocked. No uncollected accuracy/usage/hiring metrics.
Use the [release gates](docs/RELEASE_PLAN.md), preserving CLI/local operation
independently of optional ChatGPT and Google integrations. New infrastructure or
paid services are outside the approved roadmap execution scope.

Avoid introducing unauthorized scraping, MFA/CAPTCHA circumvention, third-party account automation, automatic application submission, or AI-generated resume claims unsupported by a verified profile. Use narrowly scoped OAuth permissions and never hard-code credentials.

Code of conduct: treat contributors respectfully, focus on constructive technical discussion, and report security concerns privately following `SECURITY.md`.
