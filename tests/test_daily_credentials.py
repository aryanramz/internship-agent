"""Execute the daily runner's actual preflight function against fictional paths."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which("pwsh"),reason="PowerShell preflight test requires pwsh")
@pytest.mark.parametrize("explicit_override",[False,True])
def test_daily_runner_reuses_checkout_legacy_grant_only_without_override(tmp_path,explicit_override):
    root=tmp_path/"checkout"
    old=root/"data/secrets/google_sheets_token.json"
    old.parent.mkdir(parents=True)
    old.write_text("fictional",encoding="utf-8")
    env=dict(os.environ)
    env.update(IA_TEST_ROOT=str(root),IA_TEST_ACTIVE=str(tmp_path/"new-database"),
        IA_TEST_SHARED=str(tmp_path/"shared"),IA_TEST_SCRIPT=str(Path(__file__).resolve().parents[1]/"scripts/run-daily.ps1"),
        INTERNSHIP_AGENT_GOOGLE_SECRETS=str(tmp_path/"explicit") if explicit_override else "")
    script="""
    $root=$env:IA_TEST_ROOT
    $legacyData=$env:IA_TEST_ACTIVE
    $googleSecrets=$env:IA_TEST_SHARED
    $tokens=$null; $errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile($env:IA_TEST_SCRIPT,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw 'Daily script syntax error' }
    $fn=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-GoogleAuthorization'},$true)
    . ([scriptblock]::Create($fn.Extent.Text))
    Test-GoogleAuthorization 'sheets'
    """
    result=subprocess.run([shutil.which("pwsh"),"-NoProfile","-NonInteractive","-Command",script],
        env=env,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("False" if explicit_override else "True")
