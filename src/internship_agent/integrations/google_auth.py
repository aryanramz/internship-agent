"""Separate, least-privilege Google OAuth grants for local users.

The app NEVER uses credentials from ChatGPT's native Google connectors. You must
consent through a Google Cloud OAuth client you own before local API access.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys
import tempfile
from .google_errors import GoogleIntegrationError, google_error, http_status

SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly"],
    "sheets": ["https://www.googleapis.com/auth/spreadsheets"],
}


def credential_directory(override: str | Path | None = None) -> Path:
    """Shared per-user store; an override deliberately isolates a Google account."""
    configured=override or os.environ.get("INTERNSHIP_AGENT_GOOGLE_SECRETS")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "win32":
        base=Path(os.environ.get("LOCALAPPDATA") or Path.home()/"AppData/Local")
        return base/"InternshipAgent/credentials"
    if sys.platform == "darwin":
        return Path.home()/"Library/Application Support/InternshipAgent/credentials"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home()/".local/share")/"internship-agent/credentials"


def _save_credentials(directory: Path, token: Path, creds) -> None:
    temporary=None
    try:
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
        if token.is_symlink():
            raise OSError("Credential token cannot be a symlink")
        fd,name=tempfile.mkstemp(prefix=token.stem+"-",suffix=".tmp",dir=directory)
        temporary=Path(name)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(creds.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,token)
    except (OSError,ValueError,TypeError):
        raise RuntimeError("Could not save Google credentials. Check credential directory permissions; authorization was not deleted.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # A private temporary file may remain; never mask the safe error.


def credentials(service: str, secret_dir: str | Path | None = None, oauth_client: str | None = None,
                interactive: bool = False, *, legacy_dirs=()):
    if service not in SCOPES:
        raise ValueError("Unknown Google service")
    try:
        from google.auth.transport.requests import Request
        from google.auth.exceptions import RefreshError, TransportError
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from oauthlib.oauth2 import OAuth2Error
    except ImportError as exc:
        raise RuntimeError("Install Google integrations: pip install -e '.[google]'") from exc

    directory = credential_directory(secret_dir)
    token = directory / f"google_{service}_token.json"
    scopes = SCOPES[service]
    selected=token
    # Only the default store adopts old authorization. Explicit overrides must
    # never silently select a different account from a legacy database.
    if not token.exists() and not (secret_dir or os.environ.get("INTERNSHIP_AGENT_GOOGLE_SECRETS")):
        selected=next((Path(folder)/token.name for folder in legacy_dirs if (Path(folder)/token.name).is_file()),token)
    try:
        if selected.is_symlink():
            raise ValueError("Symlink token")
        creds=Credentials.from_authorized_user_file(str(selected),scopes) if selected.exists() else None
    except (OSError,ValueError,KeyError):
        raise RuntimeError(f"Google {service} authorization could not be loaded. Check file permissions or run 'internship-agent google-login {service}' with a separate credential directory.") from None
    if creds and creds.valid:
        if selected != token:
            _save_credentials(directory,token,creds)
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            if not interactive:
                raise RuntimeError(f"Google {service} authorization expired or was revoked. Run 'internship-agent google-login {service}' interactively.") from None
            creds=None
        except (TransportError,OSError):
            raise RuntimeError("Google authorization could not be refreshed. Check your connection and retry; existing credentials were preserved.") from None
    elif not interactive:
        raise RuntimeError(f"Google {service} authorization missing or expired. Run 'internship-agent google-login {service}' interactively.")
    if interactive and (creds is None or not creds.valid):
        configured_client=oauth_client or os.environ.get("INTERNSHIP_AGENT_GOOGLE_CLIENT")
        client=Path(configured_client) if configured_client else directory/"google-oauth-client.json"
        if not configured_client and not client.is_file():
            client=Path("config/google-oauth-client.json")
        if not client.is_file():
            raise FileNotFoundError("Google OAuth desktop client JSON is missing")
        try:
            creds=InstalledAppFlow.from_client_secrets_file(str(client),scopes).run_local_server(port=0)
        except (OSError,ValueError,RefreshError,TransportError,OAuth2Error):
            raise RuntimeError(f"Google {service} sign-in could not complete. Check the desktop client configuration and retry interactively.") from None
    _save_credentials(directory,token,creds)
    return creds


class GoogleGateway:
    def __init__(self, service: str, secret_dir: str | Path | None = None, oauth_client: str | None = None, *, legacy_dirs=()):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Install Google integrations: pip install -e '.[google]'") from exc
        creds = credentials(service, secret_dir, oauth_client,legacy_dirs=legacy_dirs)
        if service == "gmail":
            self.api = build("gmail", "v1", credentials=creds, cache_discovery=False)
        elif service == "sheets":
            self.api = build("sheets", "v4", credentials=creds, cache_discovery=False)
        else:
            raise ValueError("Unknown Google service")

    def list_messages(self, query: str, limit: int = 30) -> list[dict]:
        result = []
        token = None
        remaining = min(100, max(1, limit))
        while remaining > 0:
            data = self.api.users().messages().list(userId="me", q=query,
                maxResults=min(50, remaining), pageToken=token).execute()
            messages = data.get("messages", [])
            result.extend(messages)
            remaining -= len(messages)
            token = data.get("nextPageToken")
            if not token or not messages:
                break
        return result[:min(100, limit)]

    def get_message(self, message_id: str) -> dict:
        return self.api.users().messages().get(userId="me", id=message_id, format="full").execute()

    def get_values(self, spreadsheet_id: str, rng: str) -> list[list]:
        try:
            result = self.api.spreadsheets().values().get(spreadsheetId=spreadsheet_id,
                range=rng, valueRenderOption="FORMATTED_VALUE").execute()
            return result.get("values", [])
        except Exception as exc:
            if http_status(exc)==400:
                # One read-only diagnostic request; never expose the raw error body.
                try:
                    metadata=self.api.spreadsheets().get(spreadsheetId=spreadsheet_id,fields="sheets.properties.title").execute()
                except Exception as metadata_error:
                    raise google_error(metadata_error) from None
                names=[sheet["properties"]["title"] for sheet in metadata.get("sheets",[])]
                title=rng.split("!",1)[0].strip("'").replace("''", "'")
                if title not in names:
                    safe_names=["".join(c if c.isprintable() else " " for c in name)[:80] for name in names[:20]]
                    available=", ".join(safe_names) or "(none)"
                    raise GoogleIntegrationError("worksheet_missing",f"Worksheet '{title}' was not found. Available worksheets: {available}.") from None
            raise google_error(exc) from None

    def update_cells(self, spreadsheet_id: str, data: list[dict]) -> dict:
        if not data:
            return {"totalUpdatedCells": 0}
        try:
            return self.api.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id,
                body={"valueInputOption":"RAW","data":data}).execute()
        except Exception as exc:
            raise google_error(exc,write=True) from None

    def append_rows(self, spreadsheet_id: str, rng: str, rows: list[list]) -> dict:
        if not rows:
            return {"updates":{"updatedRows":0}}
        try:
            return self.api.spreadsheets().values().append(spreadsheetId=spreadsheet_id,
                range=rng, valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                body={"majorDimension":"ROWS","values":rows}).execute()
        except Exception as exc:
            raise google_error(exc,write=True) from None
