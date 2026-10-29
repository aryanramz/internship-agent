"""Render/verify current-user Task Scheduler definitions. No scheduler side effects.

Only filesystem locations and the Windows owner SID enter task XML. Private
configuration contents, passwords and tokens are never loaded by this renderer.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NAMESPACE)


def local_path(value: str) -> str:
    """Accept an absolute local Windows path safe even for the kc.bat shell."""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise ValueError("An absolute local path is required")
    path = PureWindowsPath(value)
    if (not re.fullmatch(r"[A-Za-z]:", path.drive) or not path.is_absolute()
            or any(char in value for char in '"%&|<>^!`') or ".." in path.parts):
        raise ValueError("Path must be local and contain no shell expansion characters")
    return str(path)


def render_tasks(workspace: str, config_path: str, keycloak_home: str,
                 user_sid: str, windows_dir: str = r"C:\Windows") -> dict:
    workspace, config_path, keycloak_home, windows_dir = map(
        local_path, (workspace, config_path, keycloak_home, windows_dir))
    if not isinstance(user_sid, str) or not re.fullmatch(r"S-1-\d+(?:-\d+)+", user_sid):
        raise ValueError("A Windows user SID is required")
    identity = hashlib.sha256((workspace.casefold() + "\0" + user_sid).encode()).hexdigest()[:20]
    prefix = "InternshipAgent-" + identity
    tasks = []
    for role, executable, arguments, directory, delay in (
        ("Keycloak", str(PureWindowsPath(windows_dir) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File '
         f'"{workspace}\\scripts\\windows\\Keycloak-Run.ps1" -KeycloakHome "{keycloak_home}"',
         keycloak_home, "PT5S"),
        ("Gateway", str(PureWindowsPath(workspace) / ".venv/Scripts/pythonw.exe"),
         f'-m internship_agent.mcp_gateway --config "{config_path}"', workspace, "PT30S"),
    ):
        name = prefix + "-" + role
        root = ET.Element("Task", {"xmlns": NAMESPACE, "version": "1.4"})

        def child(parent, tag, value=None, **attributes):
            element = ET.SubElement(parent, tag, attributes)
            if value is not None:
                element.text = value
            return element

        info = child(root, "RegistrationInfo")
        child(info, "Description", f"Internship Agent managed lifecycle v1; {workspace}; {user_sid}; {role}")
        child(info, "URI", "\\" + name)
        trigger = child(child(root, "Triggers"), "LogonTrigger")
        child(trigger, "Enabled", "true")
        child(trigger, "UserId", user_sid)
        child(trigger, "Delay", delay)
        principal = child(child(root, "Principals"), "Principal", id="Owner")
        child(principal, "UserId", user_sid)
        child(principal, "LogonType", "InteractiveToken")
        child(principal, "RunLevel", "LeastPrivilege")
        settings = child(root, "Settings")
        for tag, value in (("MultipleInstancesPolicy", "IgnoreNew"),
                           ("DisallowStartIfOnBatteries", "false"),
                           ("StopIfGoingOnBatteries", "false"),
                           ("AllowHardTerminate", "true"), ("StartWhenAvailable", "true"),
                           ("RunOnlyIfNetworkAvailable", "false"), ("AllowStartOnDemand", "true"),
                           ("Enabled", "true"), ("Hidden", "true"),
                           ("ExecutionTimeLimit", "PT0S"), ("Priority", "7")):
            child(settings, tag, value)
        restart = child(settings, "RestartOnFailure")
        child(restart, "Interval", "PT1M")
        child(restart, "Count", "3")
        action = child(child(root, "Actions", Context="Owner"), "Exec")
        child(action, "Command", executable)
        child(action, "Arguments", arguments)
        child(action, "WorkingDirectory", directory)
        tasks.append({"name": name, "role": role, "xml": ET.tostring(root, encoding="unicode")})
    return {"settings": dict(workspace=workspace, config_path=config_path,
                             keycloak_home=keycloak_home, user_sid=user_sid, windows_dir=windows_dir),
            "tasks": tasks}


def ordered_tasks(definition: dict, operation: str) -> list[dict]:
    if operation not in {"Start", "Stop", "Disable", "Remove", "Status"}:
        raise ValueError("Unknown lifecycle operation")
    tasks = definition["tasks"]
    return tasks if operation in {"Start", "Status"} else list(reversed(tasks))


def required_files(definition: dict, operation: str) -> list[str]:
    """Missing private config must never prevent shutting down an owned task."""
    if operation not in {"Configure", "Start"}:
        return []
    settings = definition["settings"]
    workspace, home = PureWindowsPath(settings["workspace"]), PureWindowsPath(settings["keycloak_home"])
    return [str(workspace / ".venv/Scripts/pythonw.exe"), settings["config_path"],
            str(home / "bin/kc.bat"), str(home / "conf/keycloak.conf")]


def validate_provider_config(text: str, environment: dict[str, str]) -> None:
    """Check selected nonsecret settings without returning values or raw errors."""
    selected = {"db", "db-url", "db-url-host", "db-url-port", "db-url-properties", "db-url-database",
                "http-host", "http-management-host", "http-enabled", "hostname", "features",
                "features-disabled"}
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if key not in selected:
            continue
        if not separator or key in settings:
            raise ValueError("Ambiguous provider security configuration")
        settings[key] = value.strip()
    for key in selected | {"hostname-strict", "cache"}:
        if environment.get("KC_" + key.upper().replace("-", "_")):
            raise ValueError("Ambient provider security override is not allowed")
    for key in ("JAVA_OPTS", "JAVA_OPTS_APPEND", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
        if environment.get(key):
            raise ValueError("Ambient Java options require separate review")
    for key, value in {"db": "postgres", "http-host": "127.0.0.1",
                       "http-management-host": "127.0.0.1", "http-enabled": "true"}.items():
        if settings.get(key) != value:
            raise ValueError("Persistent local production provider configuration is required")
    jdbc = settings.get("db-url")
    if jdbc:
        match = re.fullmatch(r"jdbc:postgresql://127\.0\.0\.1(?::([0-9]+))?/[A-Za-z0-9_-]+", jdbc)
        if not match or (match.group(1) and not 1 <= int(match.group(1)) <= 65535):
            raise ValueError("Database must use a literal loopback PostgreSQL URL")
    elif settings.get("db-url-host") != "127.0.0.1":
        raise ValueError("Database must use a literal loopback host")
    if settings.get("db-url-properties"):
        raise ValueError("Additional database URL properties require separate review")
    if "db-url-database" in settings and not re.fullmatch(r"[A-Za-z0-9_-]+", settings["db-url-database"]):
        raise ValueError("A simple database name without URL parameters is required")
    if "db-url-port" in settings:
        port = settings["db-url-port"]
        if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("Invalid database port")
    origin = urlsplit(settings.get("hostname", ""))
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path not in {"", "/"} or origin.query or origin.fragment):
        raise ValueError("An explicit HTTPS provider hostname is required")
    features = {value.strip().split(":", 1)[0] for value in settings.get("features", "").split(",")}
    disabled = {value.strip().split(":", 1)[0] for value in settings.get("features-disabled", "").split(",")}
    if "resource-indicators" not in features or "resource-indicators" in disabled:
        raise ValueError("The approved provider resource-indicators feature is required")


def assert_owned_task(actual_xml: str, expected_xml: str) -> None:
    """Refuse action/owner drift instead of stopping or replacing another task."""
    ns = {"t": NAMESPACE}
    try:
        actual, expected = ET.fromstring(actual_xml), ET.fromstring(expected_xml)
        paths = ("RegistrationInfo/Description", "RegistrationInfo/URI",
                 "Principals/Principal/UserId", "Principals/Principal/LogonType",
                 "Principals/Principal/RunLevel", "Actions/Exec/Command",
                 "Actions/Exec/Arguments", "Actions/Exec/WorkingDirectory")
        for path in paths:
            query = "/".join("t:" + segment for segment in path.split("/"))
            if actual.findtext(query, namespaces=ns) != expected.findtext(query, namespaces=ns):
                raise ValueError("Task ownership or action differs; refusing operation")
        for path in ("Actions", "Principals"):
            if len(actual.find("t:" + path, ns)) != 1:
                raise ValueError("Task has unexpected actions or principals")
    except (ET.ParseError, TypeError, AttributeError) as error:
        raise ValueError("Invalid task definition") from error


def main() -> int:
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "provider-guard":
            path = Path(local_path(sys.argv[2]))
            validate_provider_config(path.read_text(encoding="utf-8-sig"), dict(os.environ))
            return 0
        request = json.load(sys.stdin)
        if sys.argv[1:] == ["render"]:
            print(json.dumps(render_tasks(**request)))
        elif sys.argv[1:] == ["order"]:
            print(json.dumps(ordered_tasks(request["definition"], request["operation"])))
        elif sys.argv[1:] == ["requirements"]:
            print(json.dumps({"files": required_files(request["definition"], request["operation"])}))
        elif sys.argv[1:] == ["verify"]:
            assert_owned_task(request["actual"], request["expected"])
        else:
            raise ValueError("Unknown renderer operation")
    except (OSError, ValueError, TypeError, KeyError):
        print("Windows task validation failed; review the local configuration.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
