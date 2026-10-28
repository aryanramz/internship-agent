# Using Internship Agent from ChatGPT Chat / Work

## Current validated state

The operator confirmed custom MCP Server URL, Tunnel and OAuth controls in their
ChatGPT Plus account. Do not substitute an old plan restriction for that observed
capability. Account/workspace policy still applies; see the official
[custom MCP setup](https://developers.openai.com/api/docs/guides/custom-mcp-server).
Local SDK interoperability is tested; a ChatGPT cloud connection is not yet proven.

## Available custom MCP connection

1. Follow [local validation](MCP_VALIDATION.md): the entry point is stdio only,
   with `application_summary`, `rank_jobs` and `preview_application`.
2. Review the [zero-cost connection proposal](MCP_CONNECTION_OPTIONS.md). Stop for
   architecture approval before implementing an HTTP/OAuth endpoint or tunnel.
3. After approval, validate authentication on loopback before enabling external
   transport. Cloud ChatGPT cannot directly reach `localhost` or stdio.
4. Prove discovery and a read-only call from the actual account before claiming
   cloud integration. Do not expose approval, preparation, submission recording,
   Google operations, discovery/import or other state-changing tools initially.

## Without custom MCP permission

- Run the CLI locally on Windows (e.g. Task Scheduler can run discovery), and export reviewed applications into your already-connected Google Sheet using its 19-column format.
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
