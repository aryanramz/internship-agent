# Contributing

Contributions are welcome to improve job-source reliability, accuracy, accessibility, and safety.

1. Open an issue describing the bug or proposal. Do not attach real resumes, job-application records, OAuth tokens, mailbox exports or secrets.
2. Create a feature branch and make a small focused change.
3. Add or update offline tests and documentation; source adapters should test against synthetic/mocked responses.
4. Run `python -m pytest -q`, `python scripts/check_repo_hygiene.py` and `python -m compileall -q src`.
5. Open a pull request explaining scope, test results, risk, and data/privacy impact.

Avoid introducing unauthorized scraping, MFA/CAPTCHA circumvention, third-party account automation, automatic application submission, or AI-generated resume claims unsupported by a verified profile. Use narrowly scoped OAuth permissions and never hard-code credentials.

Code of conduct: treat contributors respectfully, focus on constructive technical discussion, and report security concerns privately following `SECURITY.md`.
