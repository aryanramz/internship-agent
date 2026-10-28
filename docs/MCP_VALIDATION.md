# Local read-only MCP validation — Issue #3

Status (2026-10-28): local protocol validation implemented. **ChatGPT cloud
connection is not configured or validated.** External architecture approval is
required before adding HTTP/OAuth endpoints or configuring a tunnel.

## Validated surface

The optional `mcp>=2.3,<3` extra was tested with SDK **2.3.0** on Windows/Python
3.12. Real SDK subprocess clients exercised modern discovery (`2026-07-28`) and
legacy `initialize` negotiation (`2025-11-25`), tool listing and invocation.
This proves local client/server interoperability, not a completed ChatGPT plugin.
The protocol assertions deliberately record this qualification; a future SDK 2.x
negotiation-version change must be reviewed and requalified rather than silently
treated as the same tested wire behavior.
See the SDK's [client](https://py.sdk.modelcontextprotocol.io/client/) and
[protocol compatibility](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/) documentation.

| Tool | Inputs | Output |
|---|---|---|
| `application_summary` | None | Application counts by local stage |
| `rank_jobs` | `limit` 1–100, `min_score` 0–100 | `jobs` array with IDs, fit breakdown and posting links |
| `preview_application` | Existing 24-character job ID from ranking | Fit, matching verified skills, limits and posting links |

All tools advertise read-only, nondestructive, idempotent, local-only annotations.
Those hints are not a security boundary: the database is actually opened with
SQLite `mode=ro` and `query_only=ON`. No schema migration, new database, Google
request, generated document or application event is written by the adapter.
Other skill names, arbitrary file paths and write tools are not exposed as MCP
parameters. There are no file resources, resource templates or prompts.

The underlying CLI retains its existing explicitly authorized write workflows.
The previous write-capable MCP registry is deliberately replaced, with no flag
that enables it again during this initial connection phase. Client tool caches
must be refreshed when updating from an older experimental adapter.

## Compatibility fixes

- Imports no longer create/open the default database or initialize global Agent
  state. Explicit server construction requires an already existing database.
- Tool outputs use typed dictionary annotations; bare `dict` returns in the
  installed SDK produced text without `structured_content`.
- The module starts **stdio only**. It exposes no host/port/HTTP switch and creates
  no network listener. HTTP transport is a future, separately approved change.
- Bounds and ID schemas reject malformed input. Expected failures are safe MCP
  tool errors, without private profile values, filenames or raw tracebacks.
- Preview returns matching skills only; unrelated profile skills, contact fields,
  document paths, notes and submission evidence are omitted. Requested derived
  results are still data shared with the calling client.

## Reproduce locally

```powershell
python -m pip install -e '.[test,google,mcp]'
python -m pytest -q -s tests/test_mcp_readonly.py
```

Tests seed a separate temporary fictional database/profile and verify:
initialization/discovery, three annotated tool schemas, structured results,
unknown/write tool rejection, parameter bounds, safe errors, unchanged database
and profile bytes, no generated documents, and refusal of HTTP startup arguments.
The suite never calls OpenAI, Google, ATS feeds or an external tunnel. Windows
subprocess tests need normal local process/pipe permissions; restricted process
containers can stall SDK pipe cleanup and are not evidence of a protocol failure.

For a compatible **local stdio host**, the server command is:

```powershell
python -m internship_agent.mcp_server --data <existing-local-data-directory> --profile <verified-local-profile.json>
```

Use an existing synthetic database for qualification, not a personal application
tracker. The stdio host normally launches this command automatically; it is not a
command to run for every tool call. Paths are configured locally and never passed
as model-visible tool arguments. Environment alternatives remain
`INTERNSHIP_AGENT_DATA` and `INTERNSHIP_AGENT_PROFILE`.

ChatGPT's cloud Server URL box cannot reach this stdio process or `localhost`.
Read the [zero-cost connection proposal](MCP_CONNECTION_OPTIONS.md) before choosing
an external connection. Do not point a public tunnel at any unauthenticated server.
