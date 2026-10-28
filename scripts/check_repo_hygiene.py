"""Fail if repository file inventory includes common secrets/private artifacts.

This is a lightweight safeguard, NOT a substitute for professional secret scanning.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def tracked_paths() -> list[str]:
    try:
        proc = subprocess.run(["git", "ls-files", "--cached", "-z"], cwd=ROOT,
                              capture_output=True, check=True)
        result = [x.decode("utf-8") for x in proc.stdout.split(b"\0") if x]
        if result:
            return result
    except (OSError, subprocess.CalledProcessError):
        pass
    # Before git init, scan only publishable source files, not ignored local data.
    excluded = {"data", "demo-output", "generated", "secrets", ".venv", "build", "dist", "__pycache__"}
    return [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
            if p.is_file() and not any(part in excluded or (part.startswith(".") and part != ".github")
                                      for part in p.relative_to(ROOT).parts)]


def main() -> int:
    failures = []
    bad_name = re.compile(r"(^|/)(data/|demo-output/|generated/|secrets/|credentials/|profile\.json$|sources\.json$|google-oauth-client\.json$|client_secret[^/]*\.json$)|\.(db(?:-shm|-wal)?|sqlite3?|pem|key)$|(^|/)\.env($|\.)|token\.json$|google_[^/]*_token[^/]*\.tmp$|credentials[^/]*\.json$", re.I)
    # Match likely tokens and credential payloads without embedding personal values.
    credential_patterns = [
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
        re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
        re.compile(r'\"client_secret\"\s*:\s*\"[^\"]+\"'),
        re.compile(r'\"refresh_token\"\s*:\s*\"[^\"]+\"'),
    ]
    for relative in tracked_paths():
        if bad_name.search(relative):
            failures.append(f"Private artifact tracked: {relative}")
            continue
        f = ROOT / relative
        if f.suffix in {".md", ".py", ".json", ".toml", ".yml", ".yaml", ".ps1", ".txt"}:
            text = f.read_text(encoding="utf-8", errors="replace")
            for pattern in credential_patterns:
                if pattern.search(text):
                    failures.append(f"Possible credential detected in {relative}")
    for item in failures:
        print("FAIL:", item)
    print(f"Checked {len(tracked_paths())} repository files; problems: {len(failures)}")
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
