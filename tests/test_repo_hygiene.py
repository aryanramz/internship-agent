from pathlib import Path
import subprocess

import pytest

from scripts import check_repo_hygiene


@pytest.mark.parametrize("relative",["google_sheets_token-abcd.tmp","client_secret_download.json",
    "backup/credentials/store.json","backup/agent.db-wal","backup/agent.db-shm",
    "config/mcp-auth.json","config/mcp-jwks.json","config/mcp-gateway.json",
    "config/keycloak.conf","config/keycloak-realm.json"])
def test_private_credential_and_database_artifacts_are_ignored_and_rejected(monkeypatch,tmp_path,relative,capsys):
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(["git","check-ignore","--stdin"],input=(relative+"\n").encode(),cwd=root,capture_output=True)
    assert result.returncode == 0, f"Private artifact is not ignored: {relative}"
    target=tmp_path/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text("FICTIONAL PRIVATE CONTENT",encoding="utf-8")
    monkeypatch.setattr(check_repo_hygiene,"ROOT",tmp_path)
    monkeypatch.setattr(check_repo_hygiene,"tracked_paths",lambda:[relative])
    assert check_repo_hygiene.main() == 1
    assert "FICTIONAL PRIVATE CONTENT" not in capsys.readouterr().out
