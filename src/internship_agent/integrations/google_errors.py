"""Actionable local errors without Google response bodies, URLs or OAuth details."""
from __future__ import annotations


class GoogleIntegrationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code=code


def http_status(error):
    return getattr(getattr(error,"resp",None),"status",None)


def google_error(error, *, write=False):
    # Imported only on a failed API operation; Google remains an optional extra.
    try:
        from google.auth.exceptions import RefreshError
        expired=isinstance(error,RefreshError)
    except ImportError:
        expired=False
    status=http_status(error)
    if status==401 or expired:
        code="authorization_required"
        message="Google Sheets authorization expired or was revoked. Run 'internship-agent google-login sheets' interactively."
    elif status==403:
        code="permission_denied"
        message="Google Sheets access was denied. Check sharing with the signed-in account, Editor permission for writes, Sheets API enablement and the Sheets OAuth grant."
    elif status==404:
        code="spreadsheet_not_found"
        message="The spreadsheet was not found or is not accessible to the signed-in account. Check its ID and sharing permissions."
    elif status==400:
        code="invalid_request"
        message="Invalid Google Sheets request. Check worksheet 'Applications', the requested range and the expected 19 headers on row 4."
    elif status==429:
        code="rate_limited"
        message="Google Sheets rate limit reached. Wait before retrying; no automatic retry was performed."
    elif status is not None and status>=500:
        code="service_unavailable"
        message="Google Sheets is temporarily unavailable. Try a read-only preview later."
    else:
        code="request_failed"
        message="Google Sheets request failed or timed out. Check your connection and local authorization."
    if write:
        message+=" Write outcome may be uncertain. Run a read-only sync preview before retrying; no rollback or automatic retry was performed."
    return GoogleIntegrationError(code,message)
