# Security policy

**Current status:** This project is a local-first prototype. It is not a secure public MCP service and should not be exposed on the internet without an authentication, authorization and hosting security review.

## Reporting vulnerabilities

Before a public issue, report suspected vulnerabilities privately through GitHub's **Report a vulnerability** feature if enabled on the future repository. Do not paste exploit details, keys, tokens, personal records, resumes or screenshots containing PII into public issues. If private reporting is not enabled, ask the maintainer to provide a secure reporting channel; don't assume a guessed email address.

## Secret handling

The repo intentionally ignores `data/`, `generated/`, demo outputs, `config/profile.json`, `config/sources.json`, `config/google-oauth-client.json`, and OAuth token files. Never commit those files. If a credential leaks, immediately revoke or rotate it through its provider and remove it from Git history as appropriate; deleting a file in a later commit is not sufficient.

## Supported versions

The project is pre-1.0 and there is no formal security-support SLA. Please reproduce issues against the latest tagged release or main branch using fictional data.

See `docs/THREAT_MODEL.md` for current controls and unresolved risks.
