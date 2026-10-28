"""Explicit opt-in: creates one fresh tracker containing only fictional data."""
import os
from pathlib import Path

import pytest


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE_SHEETS") != "1", reason="Set RUN_LIVE_SHEETS=1 to authorize synthetic tracker creation/writes")
def test_live_isolated_google_tracker():
    from scripts.validate_google_sheets import run_live
    result=run_live(Path("data/sheets-validation"),os.environ.get("INTERNSHIP_AGENT_GOOGLE_SECRETS","data/secrets"))
    assert result["status"] == "PASS"
    assert len(result["checks"]) == 7
    print(f"Synthetic Sheets validation report: {result['report']}")
