# Using Internship Agent from ChatGPT Chat / Work

## Check capability first

The official OpenAI Help article currently documents creating custom MCP connections for Business and Enterprise/Edu workspaces. Plugin tutorials also describe personal plugins. Product permissions may change or depend on account/workspace settings; **do not assume a personal Plus plan can add an arbitrary MCP**. Check for Plugins > Add custom MCP server in your actual account. The core CLI works regardless.

## Available custom MCP connection

1. Install and run the Python MCP v2 adapter and validate it with MCP Inspector.
2. Add **authentication/authorization**, access controls, rate limiting and private network safeguards before exposing any personal-data tool.
3. Use an authenticated hosted HTTPS MCP endpoint or supported Secure MCP Tunnel; cloud ChatGPT cannot reach `localhost` directly.
4. In ChatGPT Plugins, use Add custom MCP server (if available), verify discovered tools, install the connection and invoke it in Chat or Work. The `docs/CHATGPT_INSTRUCTIONS.md` document can be used as persistent project/plugin skill instructions.
5. Initially enable discovery, ranking, preview and prepare tools; retain explicit human approval for application actions.

## Without custom MCP permission

- Run the CLI locally on Windows (e.g. Task Scheduler can run discovery), and export reviewed applications into your already-connected Google Sheet using its 19-column format.
- ChatGPT Chat and Work can still analyze the connected Sheet, prepare/review documents, and use Gmail/Drive as authorized.
- A future authenticated web UI could let ChatGPT Work's browser operate the backend; this is **not** part of v0.1.

## Distinct responsibilities

- MCP server: job data, stable IDs, status transitions, file generation.
- ChatGPT: reasoning, decisions, job-specific tailoring strategy, outreach drafting, user approvals.
- Work: permitted browser application workflows with MFA/CAPTCHA handoff; never bypass anti-bot or recruiter-site restrictions.
- Google Drive/Sheets/Gmail: persistent shared records and communications. Google OAuth-based local reconciliation was introduced in v0.3; live authorization and production behavior remain unverified.

Sources:
- https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt
- https://developers.openai.com/plugins/quickstart
- https://developers.openai.com/plugins/deploy/connect-chatgpt
