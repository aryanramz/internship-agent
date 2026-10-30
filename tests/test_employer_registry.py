"""Fictional registry fixtures; registration and inspection never fetch a URL."""
import json

import pytest

from internship_agent.service import Agent
from internship_agent.discovery_types import SourcePage


def board(**changes):
    return dict(provider="lever", token="example", company="  Example   Employer  ", **changes)


def test_legacy_load_and_explicit_registration_round_trip(tmp_path, monkeypatch):
    from internship_agent.registry import load_registry, register_source
    monkeypatch.setattr("internship_agent.sources.get_bytes", lambda *a, **k: pytest.fail("Unexpected network"))
    path = tmp_path / "sources.json"
    legacy = {"boards": [board()], "operator_note": "fictional"}
    path.write_text(json.dumps(legacy))
    before = path.read_bytes()
    loaded = load_registry(path)
    entry = loaded["boards"][0]
    assert entry["company"] == "Example   Employer"
    assert entry["employer_name"] == "Example Employer"
    assert len(entry["employer_id"]) == 24
    assert entry["board_url"] == "https://jobs.lever.co/example"
    assert entry["enabled"] is True
    assert entry["validation"]["status"] == "unverified"
    assert path.read_bytes() == before
    result = register_source(path, {"provider": "ashby", "token": "example", "company": "Example Employer"})
    assert result["added"] is True
    saved = load_registry(path)
    assert saved["registry_version"] == 1
    assert saved["operator_note"] == "fictional"
    assert saved["boards"][0]["employer_id"] != saved["boards"][1]["employer_id"]
    linked = {"provider": "greenhouse", "token": "example", "company": "Example Employer",
              "employer_id": saved["boards"][0]["employer_id"]}
    register_source(path, linked)
    saved = load_registry(path)
    assert saved["boards"][0]["employer_id"] == saved["boards"][2]["employer_id"]
    assert load_registry(path) == saved


@pytest.mark.parametrize("url", ["https://intranet/careers", "https://jobs..example.com/careers",
    "https://127.1/careers", "https://jobs.lever.co:8000/example",
    "https://example.com/jobs with spaces", "https://example.com/jobs\\private"])
def test_registry_rejects_unsafe_careers_and_detection_urls(tmp_path, url):
    from internship_agent.registry import register_source
    from internship_agent.source_detection import detect_source
    if "lever.co" in url:
        with pytest.raises(ValueError):
            detect_source(url, "Example")
    else:
        with pytest.raises(ValueError):
            register_source(tmp_path / "sources.json", {**board(), "careers_url": url})


def test_duplicate_registration_is_noop_and_preserves_owner_metadata(tmp_path):
    from internship_agent.registry import register_source, load_registry
    path = tmp_path / "sources.json"
    first = register_source(path, board())
    before = path.read_bytes()
    again = register_source(path, {"provider": "lever", "token": "EXAMPLE", "company": "Other Name"})
    assert first["added"] is True and again["added"] is False
    assert path.read_bytes() == before
    assert again["source"]["employer_id"] == first["source"]["employer_id"]
    assert load_registry(path)["boards"][0]["company"] == "Example   Employer"


def test_unrelated_legacy_extensions_cannot_change_board_identity(tmp_path, monkeypatch):
    from internship_agent.registry import register_source, load_registry, board_identity
    path = tmp_path / "sources.json"
    legacy = {**board(), "domain": "example.com", "host": "historical note", "site": "old label",
              "feed_url": "https://example.com/Feed", "path": "fictional.json"}
    path.write_text(json.dumps({"boards": [legacy]}))
    before = path.read_bytes()
    assert register_source(path, board())["added"] is False
    assert path.read_bytes() == before
    assert load_registry(path)["boards"][0]["domain"] == "example.com"
    assert board_identity(load_registry(path)["boards"][0]) == board_identity(board())
    path.write_text(json.dumps({"boards": [legacy, board()]}))
    calls = []
    monkeypatch.setattr("internship_agent.service.retrieve_page", lambda entry, root, *a, **k: calls.append(entry) or SourcePage([]))
    result = Agent(str(tmp_path / "db")).discover(str(path))
    assert len(calls) == 1
    assert len(result["errors"]) == 1


def test_validation_and_provenance_are_serialized_without_becoming_authority(tmp_path):
    from internship_agent.registry import load_registry, register_source
    path = tmp_path / "sources.json"
    entry = board()
    entry.update(enabled=False, careers_url="https://example.com/careers",
                 provenance={"method": "manual", "url": "https://example.com/careers"},
                 validation={"status": "passed", "checked_at": "2026-10-29T12:00:00+00:00",
                             "evidence": "Fictional fixture only; not live evidence", "http_status": 200})
    register_source(path, entry)
    saved = load_registry(path)["boards"][0]
    assert saved["validation"] == entry["validation"]
    assert saved["provenance"] == entry["provenance"]
    assert saved["careers_url"] == entry["careers_url"]
    assert saved["enabled"] is False


@pytest.mark.parametrize("changes", [
    {"enabled": "false"}, {"company": ""}, {"company": None}, {"company": {}},
    {"token": ""}, {"token": "../private"}, {"provider": "unknown"},
    {"board_url": "https://jobs.lever.co/other"},
    {"careers_url": "https://127.0.0.1/private"}, {"careers_url": "https://example.com:8000/jobs"},
    {"careers_url": "https://user:pass@example.com"}, {"careers_url": "https://example.com/?token=x"},
    {"employer_id": "not-an-id"}, {"employer_name": "Other Employer"},
    {"provenance": {"method": "guessed", "url": "https://example.com"}},
    {"validation": {"status": "passed", "evidence": "missing date"}},
    {"validation": {"status": "passed", "checked_at": "2026-10-29", "evidence": "no timezone"}},
    {"validation": {"status": "passed", "checked_at": "2026-10-29T12:00:00Z", "evidence": "", "http_status": True}},
])
def test_invalid_registry_entry_never_writes_or_fetches(tmp_path, monkeypatch, changes):
    from internship_agent.registry import register_source
    monkeypatch.setattr("internship_agent.sources.get_bytes", lambda *a, **k: pytest.fail("Unexpected network"))
    path = tmp_path / "sources.json"
    entry = board()
    entry.update(changes)
    with pytest.raises(ValueError):
        register_source(path, entry)
    assert not path.exists()


def test_registry_file_failures_are_nondestructive(tmp_path, monkeypatch):
    from internship_agent import registry
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"boards": [board()]}))
    before = path.read_bytes()
    monkeypatch.setattr(registry.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("synthetic failure")))
    with pytest.raises(OSError):
        registry.register_source(path, {"provider": "ashby", "token": "example", "company": "Example"})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".sources-registry-*.tmp"))


def test_registry_size_limit_is_checked_before_writing(tmp_path, monkeypatch):
    from internship_agent import registry
    path = tmp_path / "sources.json"
    monkeypatch.setattr(registry, "MAX_CONFIG_BYTES", 50)
    with pytest.raises(ValueError):
        registry.register_source(path, board())
    assert not path.exists()


def test_existing_public_examples_and_source_namespaces_round_trip(tmp_path):
    from pathlib import Path
    from internship_agent.registry import load_registry, register_source, board_identity
    examples = Path(__file__).resolve().parents[1] / "config/sources.example.json"
    path = tmp_path / "sources.json"
    path.write_bytes(examples.read_bytes())
    loaded = load_registry(path)
    register_source(path, {"provider": "lever", "token": "second", "company": "Second Employer"})
    assert load_registry(path)["boards"][:-1] == loaded["boards"]
    assert board_identity({"provider": "rss", "token": "one", "feed_url": "https://example.com/Feed"}) != board_identity(
        {"provider": "rss", "token": "one", "feed_url": "https://example.com/feed"})
    assert board_identity({"provider": "personio", "token": "one", "domain": "de"}) != board_identity(
        {"provider": "personio", "token": "one", "domain": "com"})


def test_legacy_employer_id_survives_display_rename(tmp_path):
    from internship_agent.registry import register_source, load_registry
    path = tmp_path / "sources.json"
    initial = register_source(path, board())["source"]
    stored = json.loads(path.read_text())
    stored["boards"][0].update(company="Renamed Employer", employer_name="Renamed Employer")
    path.write_text(json.dumps(stored))
    assert load_registry(path)["boards"][0]["employer_id"] == initial["employer_id"]


@pytest.mark.parametrize("payload", [[], {"boards": {}}, {"boards": [None]},
    {"registry_version": 2, "boards": []}, {"registry_version": True, "boards": []},
    {"boards": [board(), board()]}])
def test_invalid_containers_and_duplicate_board_entries_are_rejected(tmp_path, payload):
    from internship_agent.registry import load_registry
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_registry(path)


def test_discovery_validates_entry_before_fetch_and_skips_disabled(tmp_path, monkeypatch):
    import internship_agent.service as service
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"boards": [board(enabled=False),
        {"provider": "lever", "token": "bad", "company": "Bad", "enabled": "false"},
        {"provider": "greenhouse", "token": "valid", "company": "Valid"}]}))
    calls = []
    monkeypatch.setattr(service, "retrieve_page", lambda entry, root, *a, **k: calls.append(entry) or SourcePage([]))
    agent = Agent(str(tmp_path / "db"))
    result = agent.discover(str(path))
    assert [b["token"] for b in calls] == ["valid"]
    assert len(result["errors"]) == 1
    assert not agent.store.count()


def test_cli_add_and_list_sources_need_neither_database_nor_network(tmp_path, monkeypatch, capsys):
    from internship_agent import cli
    path = tmp_path / "sources.json"
    monkeypatch.setattr(cli, "Agent", lambda *a, **k: pytest.fail("Registration must not open a DB"))
    monkeypatch.setattr("internship_agent.sources.get_bytes", lambda *a, **k: pytest.fail("Unexpected network"))
    for command in (["add-source", "https://jobs.lever.co/example", "--company", "Example", "--sources", str(path)],
                    ["list-sources", "--sources", str(path)]):
        monkeypatch.setattr("sys.argv", ["internship-agent", *command])
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result
    assert result["boards"][0]["provider"] == "lever"
