"""Local source configuration with optional employer metadata; never fetches URLs.

Existing boards remain reader inputs. Employer identity is metadata only and never
replaces posting IDs or the SQLite application ledger. Reads do not migrate files.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import urlsplit

from .models import validate_board
from .source_detection import detect_source
from .sources import PUBLIC_BOARDS, _validate_feed_url

MAX_CONFIG_BYTES = 4_000_000


def normalized_name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 200
            or any(unicodedata.category(c) == "Cc" for c in value)):
        raise ValueError("Employer name must be nonempty text without control characters")
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _public_url(value):
    if (not isinstance(value, str) or not value or len(value) > 2000
            or "\\" in value or any(c.isspace() or unicodedata.category(c) == "Cc" for c in value)):
        raise ValueError("Use a public HTTPS URL without credentials or query parameters")
    _validate_feed_url(value)
    parsed = urlsplit(value)
    host = parsed.hostname.lower().rstrip(".")
    labels = host.split(".")
    if (len(labels) < 2 or not re.fullmatch(r"[a-z][a-z0-9-]*", labels[-1])
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)):
        raise ValueError("Registry URLs require a public DNS hostname")
    if parsed.query or parsed.fragment:
        raise ValueError("Registry URLs cannot contain query parameters or fragments")
    return value


def board_identity(board):
    """Keep provider-specific namespaces distinct; never use display names as keys."""
    provider = str(board["provider"]).casefold()
    # Unknown legacy extensions remain metadata, never part of a reader namespace.
    folded = (provider, str(board.get("token", "")).casefold(),
              str(board.get("domain", "de")).casefold() if provider == "personio" else "",
              str(board.get("host", "")).casefold() if provider == "workday" else "")
    exact = (str(board.get("site", "")) if provider == "workday" else "",)
    if provider not in PUBLIC_BOARDS:
        exact += (str(board.get("feed_url", "")) if provider == "rss" else "",
                  str(board.get("path", "")) if provider in {"csv_import", "json_import"} else "")
    return folded + exact


def _board_url(board):
    token, provider = board["token"], board["provider"]
    roots = {"greenhouse": "https://job-boards.greenhouse.io/", "lever": "https://jobs.lever.co/",
             "ashby": "https://jobs.ashbyhq.com/", "smartrecruiters": "https://careers.smartrecruiters.com/",
             "workable": "https://apply.workable.com/"}
    if provider in roots:
        return roots[provider] + token
    suffixes = {"breezy": "breezy.hr", "pinpoint": "pinpointhq.com", "bamboohr": "bamboohr.com",
                "teamtailor": "teamtailor.com", "personio": "jobs.personio." + board.get("domain", "de")}
    if provider in suffixes:
        return "https://" + token + "." + suffixes[provider]
    if provider == "workday":
        return "https://" + board["host"] + "/" + board["site"]
    return ""


def registry_entry(entry):
    if not isinstance(entry, dict):
        raise ValueError("Each configured source must be an object")
    name = normalized_name(entry.get("company"))
    board = validate_board(entry)
    enabled = entry.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("Source enabled must be boolean")
    out = {**entry, **board, "enabled": enabled}
    if board["provider"] not in PUBLIC_BOARDS:
        return out  # Existing feed/import/aggregator configuration is unchanged.
    if entry.get("employer_name", name) != name:
        raise ValueError("Employer name must match the normalized company name")
    # A shared name is not evidence that two boards belong to the same employer.
    # Linking verified boards is an explicit employer_id operation.
    anchor = "employer|" + "|".join(board_identity(board))
    eid = entry.get("employer_id", hashlib.sha256(anchor.encode()).hexdigest()[:24])
    if not isinstance(eid, str) or not re.fullmatch(r"[a-f0-9]{24}", eid):
        raise ValueError("Employer ID must be a stable 24-character lowercase hex identifier")
    canonical = _board_url(board)
    if "board_url" in entry:
        detected = detect_source(_public_url(entry["board_url"]), board["company"])
        if board_identity(detected) != board_identity(board):
            raise ValueError("Board URL does not match the configured provider and identifier")
    careers = _public_url(entry.get("careers_url", canonical))
    provenance = entry.get("provenance", {"method": "manual", "url": canonical})
    if (not isinstance(provenance, dict) or provenance.get("method") not in {"manual", "suggested", "imported"}
            or set(provenance) - {"method", "url"}):
        raise ValueError("Use explicit manual, suggested or imported source provenance")
    _public_url(provenance.get("url"))
    validation = entry.get("validation", {"status": "unverified", "checked_at": "", "evidence": ""})
    if (not isinstance(validation, dict) or validation.get("status") not in {"unverified", "passed", "failed", "blocked"}
            or set(validation) - {"status", "checked_at", "evidence", "http_status"}):
        raise ValueError("Invalid source validation metadata")
    evidence, checked = validation.get("evidence", ""), validation.get("checked_at", "")
    if not isinstance(evidence, str) or len(evidence) > 1000 or not isinstance(checked, str):
        raise ValueError("Validation evidence must be a short sanitized note with a timestamp")
    if validation["status"] != "unverified" or checked:
        try:
            date = datetime.fromisoformat(checked.replace("Z", "+00:00"))
            if date.tzinfo is None or not evidence.strip():
                raise ValueError()
        except ValueError:
            raise ValueError("Recorded validation requires timezone-aware checked_at and evidence") from None
    if "http_status" in validation and (type(validation["http_status"]) is not int or not 100 <= validation["http_status"] <= 599):
        raise ValueError("Invalid validation HTTP status")
    out.update(employer_id=eid, employer_name=name, board_url=canonical, careers_url=careers,
               provenance=dict(provenance), validation=dict(validation))
    return out


def read_configuration(path, *, missing_ok=False):
    path = Path(path)
    if missing_ok and not path.exists():
        return {"boards": []}
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError("Sources configuration exceeds 4MB")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError):
        raise ValueError("Sources configuration is not valid JSON") from None
    if not isinstance(value, dict) or not isinstance(value.get("boards"), list):
        raise ValueError("Sources configuration requires a boards array")
    version = value.get("registry_version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("Unsupported employer registry version")
    return value


def load_registry(path, *, missing_ok=False):
    value = read_configuration(path, missing_ok=missing_ok)
    boards, keys, names = [], set(), {}
    for raw in value["boards"]:
        entry = registry_entry(raw)
        key = board_identity(entry)
        if key in keys:
            raise ValueError("Duplicate configured board; resolve explicitly before registration")
        keys.add(key)
        if "employer_id" in entry:
            eid, name = entry["employer_id"], entry["employer_name"].casefold()
            if eid in names and names[eid] != name:
                raise ValueError("Employer ID has conflicting names; review the registry")
            names[eid] = name
        boards.append(entry)
    return {**value, "boards": boards}


def _save_registry(path, value):
    path = Path(path)
    content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if len(content.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ValueError("Sources configuration exceeds 4MB")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".sources-registry-",
                suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def register_sources(path, boards):
    """Validate a complete registration batch before one atomic local write."""
    entries = [registry_entry(board) for board in boards]
    value = load_registry(path, missing_ok=True)
    results = []
    for entry in entries:
        duplicate = None
        for existing in value["boards"]:
            if board_identity(existing) == board_identity(entry):
                duplicate = existing
                break
            if (existing.get("employer_id") == entry.get("employer_id") and "employer_id" in entry
                    and existing["employer_name"].casefold() != entry["employer_name"].casefold()):
                raise ValueError("Employer ID has conflicting names; review the registry")
        if duplicate is not None:
            results.append({"added": False, "reason": "Already configured; existing metadata retained", "source": duplicate})
        else:
            value["boards"].append(entry)
            results.append({"added": True, "source": entry, "file": str(Path(path))})
    if any(result["added"] for result in results):
        value["registry_version"] = 1
        _save_registry(path, value)
    return results


def register_source(path, board):
    """Explicit idempotent registration; no endpoint validation or job retrieval."""
    return register_sources(path, [board])[0]
