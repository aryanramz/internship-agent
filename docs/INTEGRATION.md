# Using Internship Agent from ChatGPT Chat / Work

## Current validated state

The operator confirmed custom MCP Server URL, Tunnel and OAuth controls in their
ChatGPT Plus account. Do not substitute an old plan restriction for that observed
capability. Account/workspace policy still applies; see the official
[custom MCP setup](https://developers.openai.com/api/docs/guides/custom-mcp-server).
Local SDK interoperability is tested; a ChatGPT cloud connection is not yet proven.

The core CLI is usable without ChatGPT or Google. The local dashboard is planned
in Issue #16; neither interface depends on completing Issue #3. The
[capability matrix](CAPABILITIES.md) distinguishes merged local MCP from pending
[PR #8](https://github.com/aryanramz/internship-agent/pull/8) gateway/startup work.
No external endpoint is active; the approved architecture does not authorize
activation before review and private local qualification.

## Available custom MCP connection

1. Follow [local stdio validation](MCP_VALIDATION.md) or the separately implemented
   [authenticated loopback HTTP checks](MCP_HTTP_VALIDATION.md). Both preserve
   `application_summary`, `rank_jobs` and `preview_application`.
2. Review the conditionally approved [zero-cost architecture](MCP_CONNECTION_OPTIONS.md)
   and [OAuth findings](MCP_OAUTH_COMPATIBILITY.md). Keycloak passed the local
   static-client/S256 experiment; offline access remains excluded.
3. Public HTTPS routing, administration isolation and persistence are pending
   review/qualification in PR #8 before Funnel activation. Cloud ChatGPT cannot directly reach
   `localhost` or stdio. No external endpoint is currently configured.
4. Prove discovery and a read-only call from the actual account before claiming
   cloud integration. Do not expose approval, preparation, submission recording,
   Google operations, discovery/import or other state-changing tools initially.

## Without custom MCP permission

- Run the CLI locally; the existing daily script can collect local reports, but qualified unattended scheduling/retry/catch-up remains Issue #15. Optional Sheets use still requires its own preview/confirmation and authorization.
- ChatGPT Chat and Work can still analyze the connected Sheet, prepare/review documents, and use Gmail/Drive as authorized.
- A future authenticated web UI could let ChatGPT Work's browser operate the backend; this is **not** part of v0.1.

## Distinct responsibilities

- Initial MCP server: read-only counts, rankings and narrowly projected previews.
- Local CLI: separately authorized ingestion, preparation, tracking and Google sync.
- ChatGPT: reasoning, decisions, job-specific tailoring strategy, outreach drafting, user approvals.
- Work: permitted browser application workflows with MFA/CAPTCHA handoff; never bypass anti-bot or recruiter-site restrictions.
- Google Drive/Sheets/Gmail: separate permissions and credentials. Basic local
  synthetic Sheets validation is recorded in [Issue #2 evidence](SHEETS_VALIDATION.md).

No API billing, metered resource, paid tunnel/domain or extra subscription is
authorized. OpenAI Secure MCP Tunnel is not assumed free; its cost eligibility
remains unconfirmed. Keep the local fallback if no compliant cloud path is proven.
