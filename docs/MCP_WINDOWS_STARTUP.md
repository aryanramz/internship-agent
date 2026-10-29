# Windows start and stop controls

These are prepared controls for the approved local gateway and Keycloak, not an
installed service. No scheduled task was installed during development or testing.
They do not sign into Tailscale, enable Funnel, configure public routing, install a
database, or perform a real ChatGPT connection.

## Before configuring once

Use your normal Windows account. Administrator access and a stored Windows
password are not required. Keep this checkout and its `.venv` at a stable local
path. Complete the reviewed Python/MCP installation first; the controls use this
checkout's `.venv\Scripts\python.exe` for validation and `pythonw.exe` for the
hidden gateway process. They never search PATH for a gateway executable.

Have a reviewed private gateway JSON configuration and a reviewed, existing
absolute Keycloak installation folder (`KC_HOME`). Keep private files outside
tracked source and protect them with your Windows account's file permissions.
The gateway configuration supplies `listen_port` and `keycloak_port`; the gateway
fixes both upstream and listening addresses to `127.0.0.1`. The gateway performs
its own complete security preflight and refuses unsafe settings.

Keycloak reads its private `KC_HOME\conf\keycloak.conf`. Prepare production
`start` mode, the approved public HTTPS hostname, `resource-indicators`, loopback
HTTP and management listeners, and a persistent **local PostgreSQL** database.
That database must already be configured and available before these tasks run.
Its Windows lifecycle is the responsibility of the existing database installation.
Keep database credentials only in private provider configuration or its reviewed
secret store. Do not put credentials into task actions or launchers. Remove
conflicting inherited `KC_*`/Java settings before qualification.

The provider guard runs before Configure/Start and before every scheduled provider
start. It requires explicit loopback HTTP/management hosts, `http-enabled=true`,
an HTTPS hostname and the resource-indicators feature. It rejects development
databases, duplicate security settings, ambient Java options/security overrides,
and nonlocal PostgreSQL connections. Use either a simple
`jdbc:postgresql://127.0.0.1:PORT/DATABASE` `db-url` without credentials/query
parameters, or `db-url-host=127.0.0.1` with a separate port/database setting.
It inspects only selected security keys and never returns private file contents.

Do not reuse the earlier throwaway `start-dev`/`dev-mem` experiment. Keycloak's
default `dev-file` database persists files but is intended only for development
and is unsuitable for production. See the official
[database configuration guide](https://www.keycloak.org/server/db). These controls
do not migrate realms, users, signing keys, sessions or an experimental database.

Review the scripts before running them. If Windows blocks a downloaded script,
use the file's Properties **Unblock** option only after reviewing its origin and
contents, or use your organization's signing process. The launchers do not change
the machine execution policy or bypass an organization policy. A blocked script
is an unqualified startup step, not a successful installation.

## One-time setup in File Explorer

1. Open `scripts\windows` in this checkout and double-click **Configure.cmd**.
2. Choose the existing private gateway JSON, then the approved Keycloak home.
   Paths must be absolute local drive paths. Network shares and shell expansion
   characters are refused; use a simple local folder name if validation fails.
3. Configuration creates two tasks for **your account, only while you are signed
   in**, with limited privileges. It does not start the processes immediately.
4. Double-click **Start.cmd**. It enables and starts Keycloak first, then the
   gateway. The gateway fails closed while the provider is unavailable; Task
   Scheduler retries a failed process three times at one-minute intervals.

Setup stores file locations and your Windows SID in the ignored local file
`data\windows-lifecycle.json`; it does not copy private configuration contents.
The two task names begin `InternshipAgent-` and contain a hash of this checkout
and your SID. Configure refuses to overwrite a task that already has its name.
Keep the checkout and the location manifest until the tasks have been removed.

## Daily controls

| Double-click | Result |
|---|---|
| **Start.cmd** | Enable both tasks and start Keycloak, then the gateway. |
| **Stop.cmd** | Stop the gateway task, then the Keycloak task. Next sign-in can start them again. |
| **Disable.cmd** | Disable future starts and stop the gateway, then Keycloak. Start enables them again. |
| **Remove.cmd** | Disable, stop and delete only the two owned tasks; remove their local location manifest. |
| **Status.cmd** | Show Task Scheduler state and last result for each task. |

At subsequent sign-in Keycloak is scheduled after five seconds and the gateway
after thirty seconds. This ordering gives the provider a head start; it is not
a readiness guarantee. A long database recovery can exhaust the three retries;
resolve the provider problem, then double-click Start again. The tasks do not
run before sign-in and signing out or shutting down ends the interactive session.
Sleep and hibernation make the local service unavailable.

The gateway uses `pythonw.exe`; Keycloak uses a small synchronous PowerShell
runner with a hidden window. The runner invokes only the selected absolute
`kc.bat start`, forces HTTP/management binding to `127.0.0.1`, and uses local
caching. It returns the provider's exit code so Task Scheduler controls retries.
There is no custom restart loop. Console output is discarded; these launchers
create no request or credential logs. Review any separately enabled provider logs
before sharing them.

Stop uses Task Scheduler's native control of the task process tree. It never
searches for or kills all Python, Java, Keycloak or port-owning processes. Native
task termination can be abrupt, so maintain normal PostgreSQL backups and recovery
procedures. It is not a promise of graceful Keycloak database shutdown. Stop or
Disable before planned Windows maintenance; do not delete the private database.

Before any operation, the controller checks both task actions and principals
against definitions derived from this checkout's saved locations and your SID.
If an action, owner or executable has changed, it refuses to touch either task.
Missing private gateway/provider files do not block Stop, Disable or Remove.
The checkout's validation Python must still exist; if the checkout has moved or
been removed, use the Task Scheduler fallback below.

## Inspection and fallback

Open **Task Scheduler** from Start and choose **View → Show Hidden Tasks**.
Find the two `InternshipAgent-…-Gateway` and `InternshipAgent-…-Keycloak` entries
in Task Scheduler Library. Inspect Actions, the absolute checkout path, and the
current-user limited-privilege principal before changing anything. Running state
is `4`; ready is `3`; disabled is `1`. A running task often reports last result
`267009` (`0x41301`), which is not an authentication or readiness check.

If a launcher cannot run, select only the entry with this checkout's exact action
and your account. Disable and End the Gateway entry first, then the Keycloak
entry. Delete only those two entries when removing the controls. Do not end other
Python/Java processes by name. This GUI fallback also works if the saved location
manifest is lost. If policy forbids per-user task registration, leave installation
unexecuted and follow the organization's approved process instead of elevating.

Offline tests cover XML rendering, exact executable/argument paths, limited
interactive principals, restart settings, ordering, shell/path rejection, and
refusal of modified task actions. They never register tasks or use real credentials.
The PowerShell Preview check is skipped when the host policy blocks unsigned
scripts. Real sign-in, hidden-window behavior, failure/restart and native child
termination still require an explicitly authorized Windows qualification run.
