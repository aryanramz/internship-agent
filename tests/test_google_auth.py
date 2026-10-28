"""Credential routing and refresh tests use fictional objects, never local tokens."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("google.oauth2.credentials", reason="Install the google extra for OAuth regression coverage")
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from internship_agent.integrations import google_auth
from internship_agent.service import Agent


class FictionalCredentials:
    valid=True
    expired=False
    refresh_token=None
    def to_json(self): return json.dumps({"fixture":"authorized"})


@pytest.fixture
def isolated_auth(monkeypatch,tmp_path):
    monkeypatch.delenv("INTERNSHIP_AGENT_GOOGLE_SECRETS",raising=False)
    monkeypatch.delenv("INTERNSHIP_AGENT_GOOGLE_CLIENT",raising=False)
    monkeypatch.setenv("LOCALAPPDATA",str(tmp_path/"user-data"))
    monkeypatch.setattr(google_auth,"sys",SimpleNamespace(platform="win32"),raising=False)
    loaded=[]
    value=FictionalCredentials()
    def load(path,scopes):
        loaded.append(Path(path))
        assert scopes == google_auth.SCOPES["sheets"]
        return value
    monkeypatch.setattr(Credentials,"from_authorized_user_file",staticmethod(load))
    return value,loaded


def token_at(folder):
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/"google_sheets_token.json"
    path.write_text('{"fixture":"original"}',encoding="utf-8")
    return path


def test_default_storage_is_user_level_and_independent_of_database(isolated_auth,tmp_path):
    first=Agent(str(tmp_path/"database-one"))
    second=Agent(str(tmp_path/"database-two"))
    expected=tmp_path/"user-data"/"InternshipAgent"/"credentials"
    assert first.credentials_dir == second.credentials_dir == expected


@pytest.mark.parametrize("platform,env_name,subpath",[
    ("win32","LOCALAPPDATA",Path("InternshipAgent/credentials")),
    ("linux","XDG_DATA_HOME",Path("internship-agent/credentials")),
])
def test_platform_storage_uses_user_data_environment(monkeypatch,tmp_path,platform,env_name,subpath):
    monkeypatch.delenv("INTERNSHIP_AGENT_GOOGLE_SECRETS",raising=False)
    monkeypatch.setattr(google_auth,"sys",SimpleNamespace(platform=platform),raising=False)
    monkeypatch.setenv(env_name,str(tmp_path))
    assert google_auth.credential_directory() == tmp_path/subpath


def test_macos_default_uses_application_support(monkeypatch,tmp_path):
    monkeypatch.delenv("INTERNSHIP_AGENT_GOOGLE_SECRETS",raising=False)
    monkeypatch.setattr(google_auth,"sys",SimpleNamespace(platform="darwin"),raising=False)
    monkeypatch.setattr(Path,"home",classmethod(lambda cls:tmp_path))
    assert google_auth.credential_directory() == tmp_path/"Library/Application Support/InternshipAgent/credentials"


def test_explicit_directory_overrides_environment(isolated_auth,monkeypatch,tmp_path):
    monkeypatch.setenv("INTERNSHIP_AGENT_GOOGLE_SECRETS",str(tmp_path/"env"))
    assert google_auth.credential_directory(tmp_path/"explicit") == tmp_path/"explicit"
    assert Agent(str(tmp_path/"db"),credentials_dir=str(tmp_path/"explicit")).credentials_dir == tmp_path/"explicit"


def test_valid_legacy_authorization_is_adopted_without_deleting_original(isolated_auth,tmp_path):
    value,loaded=isolated_auth
    original=token_at(tmp_path/"old-data/secrets")
    before=original.read_bytes()
    assert google_auth.credentials("sheets",legacy_dirs=[original.parent]) is value
    shared=google_auth.credential_directory()/original.name
    assert loaded == [original]
    assert json.loads(shared.read_text()) == {"fixture":"authorized"}
    assert original.read_bytes() == before
    assert not list(shared.parent.glob("*.tmp"))
    google_auth.credentials("sheets",legacy_dirs=[original.parent])
    assert loaded[-1] == shared


@pytest.mark.parametrize("use_env",[False,True])
def test_override_isolates_accounts_and_does_not_import_legacy(isolated_auth,monkeypatch,tmp_path,use_env):
    _,loaded=isolated_auth
    old=token_at(tmp_path/"old/secrets")
    target=tmp_path/"isolated"
    if use_env:
        monkeypatch.setenv("INTERNSHIP_AGENT_GOOGLE_SECRETS",str(target))
    with pytest.raises(RuntimeError,match="google-login sheets"):
        google_auth.credentials("sheets",None if use_env else str(target),legacy_dirs=[old.parent])
    assert loaded == []
    assert not (target/old.name).exists()


def test_expired_authorization_refreshes_without_interactive_login(isolated_auth,tmp_path):
    value,loaded=isolated_auth
    token_at(google_auth.credential_directory())
    value.valid=False
    value.expired=True
    value.refresh_token="fictional-refresh-marker"
    calls=[]
    value.refresh=lambda request:calls.append(request)
    assert google_auth.credentials("sheets") is value
    assert len(calls)==1


def test_rejected_refresh_is_actionable_and_preserves_original(isolated_auth):
    value,_=isolated_auth
    original=token_at(google_auth.credential_directory())
    before=original.read_bytes()
    value.valid=False
    value.expired=True
    value.refresh_token="fictional-refresh-marker"
    def fail(request): raise RefreshError("PRIVATE OAUTH RESPONSE")
    value.refresh=fail
    with pytest.raises(RuntimeError,match="google-login sheets") as error:
        google_auth.credentials("sheets")
    assert "PRIVATE" not in str(error.value)
    assert original.read_bytes()==before


def test_invalid_token_errors_never_include_token_content(isolated_auth,monkeypatch):
    token_at(google_auth.credential_directory())
    def fail(*args,**kwargs): raise ValueError("PRIVATE TOKEN CONTENT")
    monkeypatch.setattr(Credentials,"from_authorized_user_file",staticmethod(fail))
    with pytest.raises(RuntimeError,match="authorization") as error:
        google_auth.credentials("sheets")
    assert "PRIVATE" not in str(error.value)


def test_failed_atomic_replace_leaves_original_and_removes_temporary_file(isolated_auth,monkeypatch):
    value,_=isolated_auth
    path=token_at(google_auth.credential_directory())
    before=path.read_bytes()
    value.valid=False
    value.expired=True
    value.refresh_token="fictional-refresh-marker"
    value.refresh=lambda request:None
    def fail(*args): raise PermissionError("PRIVATE PATH")
    monkeypatch.setattr(google_auth.os,"replace",fail)
    with pytest.raises(RuntimeError,match="credential") as error:
        google_auth.credentials("sheets")
    assert "PRIVATE" not in str(error.value)
    assert path.read_bytes()==before
    assert not list(path.parent.glob("*.tmp"))


def test_agents_with_different_databases_reuse_default_legacy_grant(isolated_auth,monkeypatch,tmp_path):
    _,loaded=isolated_auth
    monkeypatch.chdir(tmp_path)
    old=token_at(tmp_path/"data/secrets")
    from internship_agent.tracker import COLUMNS
    import googleapiclient.discovery
    api=SimpleNamespace(spreadsheets=lambda:SimpleNamespace(values=lambda:SimpleNamespace(
        get=lambda **kwargs:SimpleNamespace(execute=lambda:{"values":[[],[],[],COLUMNS]}))))
    monkeypatch.setattr(googleapiclient.discovery,"build",lambda *args,**kwargs:api)
    first=Agent(str(tmp_path/"database-one"))
    second=Agent(str(tmp_path/"database-two"))
    sid="EXAMPLE_SPREADSHEET_ID_12345678901234567890123"
    assert first.sync_tracker(sid)["append_count"] == 0
    assert second.sync_tracker(sid)["append_count"] == 0
    assert loaded == [old,first.credentials_dir/old.name]


@pytest.mark.parametrize("choice",["default","environment","argument"])
def test_oauth_client_lookup_preserves_legacy_configuration(isolated_auth,monkeypatch,tmp_path,choice):
    from google_auth_oauthlib.flow import InstalledAppFlow
    value,_=isolated_auth
    monkeypatch.chdir(tmp_path)
    legacy=tmp_path/"config/google-oauth-client.json"
    legacy.parent.mkdir()
    legacy.write_text("fictional client")
    custom=tmp_path/"custom-client.json"
    custom.write_text("fictional client")
    if choice=="environment":
        monkeypatch.setenv("INTERNSHIP_AGENT_GOOGLE_CLIENT",str(custom))
    calls=[]
    def flow(path,scopes):
        calls.append(Path(path).resolve())
        return SimpleNamespace(run_local_server=lambda **kwargs:value)
    monkeypatch.setattr(InstalledAppFlow,"from_client_secrets_file",staticmethod(flow))
    google_auth.credentials("sheets",oauth_client=str(custom) if choice=="argument" else None,interactive=True)
    assert calls == [legacy if choice=="default" else custom]


def test_cleanup_failure_does_not_expose_raw_filesystem_errors(isolated_auth,monkeypatch,tmp_path):
    value,_=isolated_auth
    old=token_at(tmp_path/"legacy")
    original_unlink=Path.unlink
    def fail_unlink(path,*args,**kwargs):
        if path.suffix==".tmp": raise PermissionError("PRIVATE PATH")
        return original_unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,"unlink",fail_unlink)
    def fail_replace(*args): raise PermissionError("PRIVATE PATH")
    monkeypatch.setattr(google_auth.os,"replace",fail_replace)
    with pytest.raises(RuntimeError) as error:
        google_auth.credentials("sheets",legacy_dirs=[old.parent])
    assert "PRIVATE" not in str(error.value)


def test_denied_interactive_consent_does_not_expose_raw_oauth_error(isolated_auth,monkeypatch,tmp_path):
    from google_auth_oauthlib.flow import InstalledAppFlow
    from oauthlib.oauth2 import AccessDeniedError
    client=tmp_path/"fictional-client.json"
    client.write_text("fictional client")
    def deny(**kwargs): raise AccessDeniedError(description="PRIVATE OAUTH DETAILS")
    monkeypatch.setattr(InstalledAppFlow,"from_client_secrets_file",staticmethod(
        lambda *args,**kwargs:SimpleNamespace(run_local_server=deny)))
    with pytest.raises(RuntimeError,match="sign-in") as error:
        google_auth.credentials("sheets",oauth_client=str(client),interactive=True)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.skipif(os.name=="nt",reason="POSIX permissions; Windows relies on user-profile ACLs")
def test_new_credential_store_is_owner_only(isolated_auth,tmp_path):
    original=token_at(tmp_path/"legacy")
    google_auth.credentials("sheets",legacy_dirs=[original.parent])
    directory=google_auth.credential_directory()
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory/original.name).stat().st_mode & 0o777 == 0o600
