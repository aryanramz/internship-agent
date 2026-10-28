"""Separate, least-privilege Google OAuth grants for local users.

The app NEVER uses credentials from ChatGPT's native Google connectors. You must
consent through a Google Cloud OAuth client you own before local API access.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly"],
    "sheets": ["https://www.googleapis.com/auth/spreadsheets"],
}


def credentials(service: str, secret_dir: str, oauth_client: str = "config/google-oauth-client.json", interactive: bool = False):
    if service not in SCOPES:
        raise ValueError("Unknown Google service")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError("Install Google integrations: pip install -e '.[google]'") from exc

    directory = Path(secret_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    token = directory / f"google_{service}_token.json"
    scopes = SCOPES[service]
    creds = Credentials.from_authorized_user_file(str(token), scopes) if token.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactive:
        if not Path(oauth_client).is_file():
            raise FileNotFoundError("Google OAuth desktop client JSON is missing")
        creds = InstalledAppFlow.from_client_secrets_file(oauth_client, scopes).run_local_server(port=0)
    else:
        raise RuntimeError(f"Google {service} authorization missing or expired. Run 'internship-agent google-login {service}' interactively.")
    # Owner-only file where supported; avoid writing refresh tokens to log output.
    data = creds.to_json()
    temp = token.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(temp, token)
    try:
        os.chmod(token, 0o600)
    except OSError:
        pass
    return creds


class GoogleGateway:
    def __init__(self, service: str, secret_dir: str, oauth_client: str = "config/google-oauth-client.json"):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Install Google integrations: pip install -e '.[google]'") from exc
        creds = credentials(service, secret_dir, oauth_client)
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
        result = self.api.spreadsheets().values().get(spreadsheetId=spreadsheet_id,
            range=rng, valueRenderOption="FORMATTED_VALUE").execute()
        return result.get("values", [])

    def update_cells(self, spreadsheet_id: str, data: list[dict]) -> dict:
        if not data:
            return {"totalUpdatedCells": 0}
        return self.api.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id,
            body={"valueInputOption":"RAW","data":data}).execute()

    def append_rows(self, spreadsheet_id: str, rng: str, rows: list[list]) -> dict:
        if not rows:
            return {"updates":{"updatedRows":0}}
        return self.api.spreadsheets().values().append(spreadsheetId=spreadsheet_id,
            range=rng, valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"majorDimension":"ROWS","values":rows}).execute()
