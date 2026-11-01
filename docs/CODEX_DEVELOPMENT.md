# Codex development and Cloud setup

Codex is the primary development workflow. The application remains local-first:
Python and SQLite, an independent CLI, optional MCP/Google, and no required model
API or additional paid service. Codex Cloud is for development with synthetic
fixtures; it is not the candidate's operational machine or the cloud deployment
planned for assessment in Issue #20.

Read [AGENTS.md](../AGENTS.md), [architecture](ARCHITECTURE.md),
[capabilities](CAPABILITIES.md), [roadmap](ROADMAP.md),
[threat model](THREAT_MODEL.md), and the issue's relevant implementation first.

## Baseline and branch

The onboarding baseline is accepted `develop` at
`e2b6e9742d48fb30500255714227d3ec1579b822` (PR #24). It includes PR #23 discovery
lifecycle and PR #24 eligibility. For new tasks, fetch and inspect the latest
accepted `origin/develop`; this SHA is historical evidence, not a permanent pin.

In the task's clean isolated checkout, after authorized GitHub connectivity:

```bash
git status --porcelain=v1
git fetch origin
git rev-parse origin/develop
git switch -c feature/ISSUE-short-description origin/develop
git rev-parse HEAD
```

Use `chore/...` for maintenance. Stop to preserve unrelated changes if status is
not clean. Reuse an existing isolated Codex workspace; do not nest worktrees.
If isolation is absent, arrange a separate checkout/worktree before editing.
Never reset/discard user work or force-push to resolve divergence. If the branch
already exists, inspect it rather than overwriting it. Target PRs to `develop`.

## Python environment

CI qualifies Python **3.11, 3.12 and 3.13**. Select one available interpreter for a
local run, report its exact version, and let the unchanged CI matrix qualify the
others. Python 3.12 is the example below; repeat in separate virtual environments
when testing other supported versions. Do not install system packages or upgrade
project dependencies as an incidental setup change.

From the repository root in Linux/Codex Cloud:

```bash
python3.12 -m venv /tmp/internship-agent-dev
source /tmp/internship-agent-dev/bin/activate
python --version
python -m pip install -e '.[test,google,mcp]'
python -m pip check
```

Choose a new virtual-environment path or inspect an existing one before reusing
it. Keep the environment active, or use its absolute Python path for every check.
On Windows, use `py -3.12 -m venv .venv` and
`.\.venv\Scripts\Activate.ps1` instead. No real Google credentials are needed to
install the extras or execute mocked tests.

The `test` extra alone omits optional SDK coverage: test modules use
`importorskip` for missing Google/MCP dependencies. Install all three extras for
the complete offline suite. Dependency ranges live in [pyproject.toml](../pyproject.toml);
there is no lockfile guaranteeing identical resolutions over time. Record a
sanitized version inventory from this dedicated environment when investigating
differences; do not publish a personal environment or private index URLs.

The separate CI security job installs `.[test,google,mcp,security]` and audits a
pinned inventory of the resolved installed packages. For a corresponding local
advisory check, install that declared extra and follow the commands in
[the workflow](../.github/workflows/ci.yml). Advisory access is network-dependent;
`pip check` checks dependency consistency and is not a vulnerability scan.

## Verification and skips

Keep `RUN_LIVE_ATS` and `RUN_LIVE_SHEETS` disabled for ordinary development.
Confirm neither is `1` before running tests; if inherited as enabled, stop and
select an offline test environment. Do not dump the process environment.

```bash
python -m pytest -q -ra
python scripts/check_repo_hygiene.py
python -m compileall -q src
python -m pip check
python scripts/demo.py --output /tmp/internship-agent-demo
git diff --check
git status --short
```

Use a fresh synthetic demo directory for a fresh-run result. Ordinary tests use
fictional data, temporary SQLite databases, mocked services and local MCP clients.
The [test guard](../tests/conftest.py) blocks external DNS/connections in ordinary
test processes; local subprocess/transport checks are not proof of public
connectivity. Dependency installation and advisory lookup are separate network
operations. Do not weaken the guard, turn skips into passes, or exclude MCP tests
to claim full qualification.

Expected skip reasons depend on the host:

| Check | Qualification boundary |
|---|---|
| Three ATS live tests | Opt-in public API requests; remain skipped offline |
| Sheets live test | Separate authorization for synthetic tracker creation/writes |
| Two daily-script preflight cases | Need `pwsh`; skipped if absent |
| Windows lifecycle preview | Needs `powershell.exe`; preview is not task installation/logon/recovery qualification |
| POSIX credential permissions | Skipped on Windows; Windows relies on account ACLs |
| Google/MCP SDK modules | Missing-extra skips indicate incomplete full-suite setup |

Report exact passes, skips, subtests, duration, Python/dependency versions and
execution permissions. Historical revision-specific counts are in
[CAPABILITIES.md](CAPABILITIES.md#baseline-checks-and-limits); they are not expected
counts for all future environments. Windows native task/sign-in/sleep/restart
qualification and actual ChatGPT OAuth/invocation require their own environments
and authorization. Linux offline passes do not satisfy those gates.

For documentation, review relative links/anchors and commands against code. If
`actionlint` is available, run `actionlint .github/workflows/ci.yml`; otherwise
report the narrower configuration check used and rely on PR CI for execution.

## Managed networking and supported permissions

Inspect managed environment readiness and its supported network policy before
network work. Preserve inherited proxies, CA trust and TLS verification. A failure
such as `Failed to connect to proxy port 8080` can reflect the execution sandbox,
not a missing GitHub permission or an application defect.

Try normal execution first unless the same session already establishes that the
required operation is blocked. If the execution tool exposes a supported approval
mechanism, request it for the specific authorized command. For Codex tools exposing
`sandbox_permissions`, this is `require_escalated` with a clear justification;
other hosts may expose different controls or no escalation at all. Proceed only
after approval. Necessary operations can include GitHub fetch/push for the requested
PR, declared dependency downloads, and offline tests that require local sockets.

The onboarding audit observed normal GitHub proxy failures and a stalled local
gateway test; approved elevated execution allowed GitHub access and the complete
offline suite. Elevation does not authorize live integrations or make test fixtures
an operational public service. Do not unset proxy variables, disable TLS checks,
change network policy/routes, or try undocumented bypasses. If approval is denied
or unavailable, stop the dependent operation and report the limitation. Continue
independent checks where possible.

## Review and delivery

1. Keep scope tied to the requested issue/maintenance task. Preserve existing
   SQLite history, profile compatibility, exact read-only MCP tools and privacy
   boundaries. Issue #12 is the next feature scope; onboarding does not start it.
2. Review `git diff` and staged files for accidental private artifacts; hygiene is
   not a substitute for secret scanning or appropriate security review. Use small
   regression tests for behavior changes and validate documentation/configuration
   without inventing application tests that merely repeat prose.
3. Record exact validation and obtain review. Commit only intended files and push
   only the feature/maintenance branch when PR delivery is authorized. Never push
   directly to `main` or `develop` as part of feature delivery.
4. Open a PR targeting `develop` with scope, behavior, test results, privacy impact
   and remaining qualification. Inspect CI and resolve relevant failures. Leave
   the PR unmerged for human review; PR creation is not merge authorization.

The existing CI jobs run on pull requests, pushes to `main` and `develop`, and
manual dispatch. Adding `develop` reuses the same Python matrix/security jobs;
it adds no parallel duplicate workflow. Feature branch pushes use PR CI. A merge
to `develop` deliberately verifies the resulting merge commit again.

Promotion to `main`, tags/releases, public connectivity, Google writes, application
submission and recruiter sending retain their separate approval gates. Never
upload private candidate profiles, tokens, databases, generated documents or
application histories to the Cloud workspace or GitHub. Core local development
requires no paid service, API credits, domain, hosting, or authenticated ChatGPT
connection. Keep Issue #3 open until actual authenticated invocation qualifies.
