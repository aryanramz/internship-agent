"""Pure rendering checks: never register tasks, start processes or read credentials."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


HELPER = Path(__file__).resolve().parents[1] / "scripts/windows/task_config.py"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def load_helper():
    assert HELPER.exists(), "The offline Windows task renderer must exist"
    spec = importlib.util.spec_from_file_location("windows_task_config", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(**overrides):
    settings = dict(workspace=r"C:\Synthetic Workspace\agent", config_path=r"C:\Private\gateway.json",
                    keycloak_home=r"C:\Providers\keycloak", user_sid="S-1-5-21-1000")
    settings.update(overrides)
    return load_helper().render_tasks(**settings)


def test_tasks_run_only_as_current_limited_user_and_restart_without_passwords():
    result = render()
    assert len(result["tasks"]) == 2
    for task in result["tasks"]:
        xml = ET.fromstring(task["xml"])
        assert xml.findtext("t:Principals/t:Principal/t:UserId", namespaces=NS) == "S-1-5-21-1000"
        assert xml.findtext("t:Principals/t:Principal/t:LogonType", namespaces=NS) == "InteractiveToken"
        assert xml.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=NS) == "LeastPrivilege"
        assert xml.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces=NS) == "S-1-5-21-1000"
        assert xml.findtext("t:Settings/t:RestartOnFailure/t:Count", namespaces=NS) == "3"
        assert xml.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=NS) == "PT0S"
        assert xml.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"


def test_actions_use_exact_absolute_paths_and_no_shell_for_gateway():
    tasks = render()["tasks"]
    keycloak, gateway = [ET.fromstring(task["xml"]) for task in tasks]
    assert gateway.findtext("t:Actions/t:Exec/t:Command", namespaces=NS) == r"C:\Synthetic Workspace\agent\.venv\Scripts\pythonw.exe"
    assert gateway.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS) == '-m internship_agent.mcp_gateway --config "C:\\Private\\gateway.json"'
    assert keycloak.findtext("t:Actions/t:Exec/t:Command", namespaces=NS) == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert keycloak.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS) == (
        '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File '
        '"C:\\Synthetic Workspace\\agent\\scripts\\windows\\Keycloak-Run.ps1" '
        '-KeycloakHome "C:\\Providers\\keycloak"')


@pytest.mark.parametrize("bad", ["relative\\gateway.json", r"\\server\share\gateway.json", 'C:\\a"b\\gateway.json',
                                 r"C:\Bad%PATH%\gateway.json", r"C:\Bad&whoami\gateway.json", "C:\\bad\nfile.json"])
def test_untrusted_or_shell_expanding_paths_are_rejected(bad):
    with pytest.raises(ValueError):
        render(config_path=bad)


def test_task_names_are_stable_per_workspace_and_distinct_per_owner():
    first = render()
    assert first == render()
    assert {task["name"] for task in first["tasks"]}.isdisjoint(
        task["name"] for task in render(user_sid="S-1-5-21-2000")["tasks"])


def test_unrelated_or_modified_task_cannot_be_stopped_or_overwritten():
    helper = load_helper()
    expected = render()["tasks"][1]["xml"]
    helper.assert_owned_task(expected, expected)
    for original, replacement in [("internship_agent.mcp_gateway", "unrelated_program"),
                                  ("S-1-5-21-1000", "S-1-5-21-2000"),
                                  ("LeastPrivilege", "HighestAvailable"),
                                  ("pythonw.exe", "other.exe")]:
        with pytest.raises(ValueError):
            helper.assert_owned_task(expected.replace(original, replacement), expected)


def test_unrelated_additional_actions_are_rejected():
    helper = load_helper()
    expected = render()["tasks"][1]["xml"]
    modified = expected.replace("</Actions>", "<Exec><Command>C:\\unrelated.exe</Command></Exec></Actions>")
    with pytest.raises(ValueError):
        helper.assert_owned_task(modified, expected)


@pytest.mark.parametrize("operation, expected", [("Start", ["Keycloak", "Gateway"]),
                                                ("Stop", ["Gateway", "Keycloak"]),
                                                ("Disable", ["Gateway", "Keycloak"]),
                                                ("Remove", ["Gateway", "Keycloak"])])
def test_shutdown_is_gateway_first_and_startup_is_provider_first(operation, expected):
    helper = load_helper()
    assert [task["role"] for task in helper.ordered_tasks(render(), operation)] == expected


@pytest.mark.parametrize("operation", ["Stop", "Disable", "Remove", "Status"])
def test_shutdown_controls_do_not_depend_on_private_configs_still_existing(operation):
    assert load_helper().required_files(render(), operation) == []


PROVIDER_CONFIG = """db=postgres
db-url=jdbc:postgresql://127.0.0.1:15432/internship_keycloak
http-host=127.0.0.1
http-management-host=127.0.0.1
http-enabled=true
hostname=https://synthetic.example
features=resource-indicators
db-username=synthetic_user
db-password=synthetic-password
"""


def test_provider_guard_accepts_existing_persistent_local_postgresql_configuration():
    load_helper().validate_provider_config(PROVIDER_CONFIG, {})


def test_provider_guard_accepts_local_database_property_configuration():
    text = PROVIDER_CONFIG.replace("db-url=jdbc:postgresql://127.0.0.1:15432/internship_keycloak",
                                   "db-url-host=127.0.0.1\ndb-url-port=15432\ndb-url-database=internship_keycloak")
    load_helper().validate_provider_config(text, {})


def test_provider_guard_rejects_database_name_used_to_inject_url_parameters():
    text = PROVIDER_CONFIG.replace("db-url=jdbc:postgresql://127.0.0.1:15432/internship_keycloak",
                                   "db-url-host=127.0.0.1\ndb-url-database=internship?host=remote.example")
    with pytest.raises(ValueError):
        load_helper().validate_provider_config(text, {})


def test_provider_guard_errors_never_echo_private_configuration(tmp_path):
    fixture = tmp_path / "keycloak.conf"
    fixture.write_text(PROVIDER_CONFIG.replace("db=postgres", "db=dev-file"), encoding="utf-8")
    result = subprocess.run([sys.executable, str(HELPER), "provider-guard", str(fixture)],
                            capture_output=True, text=True, check=False, timeout=15)
    assert result.returncode == 1
    assert "synthetic-password" not in result.stdout + result.stderr
    assert "synthetic_user" not in result.stdout + result.stderr


@pytest.mark.parametrize("old, new", [
    ("db=postgres", "db=dev-file"), ("db=postgres", "db=dev-mem"),
    ("127.0.0.1:15432", "db.example:15432"),
    ("127.0.0.1:15432", "user:password@127.0.0.1:15432"),
    ("http-host=127.0.0.1", "http-host=0.0.0.0"),
    ("http-management-host=127.0.0.1", "http-management-host=0.0.0.0"),
    ("https://synthetic.example", "http://synthetic.example"),
    ("features=resource-indicators", "features=other"),
    ("db=postgres", "db=postgres\ndb=dev-file"),
])
def test_provider_guard_refuses_unsafe_or_ambiguous_startup_config(old, new):
    with pytest.raises(ValueError):
        load_helper().validate_provider_config(PROVIDER_CONFIG.replace(old, new), {})


@pytest.mark.parametrize("environment", [{"KC_DB": "dev-file"}, {"KC_DB_URL_HOST": "remote.example"},
                                           {"JAVA_OPTS_APPEND": "-Dkc.db=dev-file"}])
def test_provider_guard_rejects_ambient_overrides(environment):
    with pytest.raises(ValueError):
        load_helper().validate_provider_config(PROVIDER_CONFIG, environment)


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell unavailable")
def test_controller_preview_has_no_task_or_filesystem_side_effects(tmp_path):
    settings = tmp_path / "synthetic-settings.json"
    selected = render(workspace="C:\\Synthetic \u03a9 Workspace\\agent")["settings"]
    settings.write_text(json.dumps(selected), encoding="utf-8")
    before = set(tmp_path.iterdir())
    command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
               str(HELPER.with_name("Manage.ps1")), "-Operation", "Preview", "-SettingsPath", str(settings),
               "-RendererPython", sys.executable]
    result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True, check=False, timeout=30)
    if "AuthorizationManager check failed" in result.stderr:
        pytest.skip("Host policy blocks unsigned PowerShell; no task execution qualified")
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert len(rendered["tasks"]) == 2
    assert rendered["settings"]["workspace"] == "C:\\Synthetic \u03a9 Workspace\\agent"
    assert set(tmp_path.iterdir()) == before
