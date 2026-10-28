# Safe default daily ingestion. This script does NOT apply to jobs,
# send recruiter emails, or write to Google Sheets.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw 'Virtual environment missing; run scripts\setup-windows.ps1 first.' }
$reports = Join-Path $root 'data\reports'
New-Item -Path $reports -ItemType Directory -Force | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$googleSecrets = & $python -c 'from internship_agent.integrations.google_auth import credential_directory; print(credential_directory())'
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the Google credential directory.' }
$legacyData = if ($env:INTERNSHIP_AGENT_DATA) { $env:INTERNSHIP_AGENT_DATA } else { Join-Path $root 'data' }
function Test-GoogleAuthorization([string]$service) {
    $name = "google_${service}_token.json"
    if (Test-Path (Join-Path $googleSecrets $name)) { return $true }
    # Explicit account overrides never silently fall back to another grant.
    if ($env:INTERNSHIP_AGENT_GOOGLE_SECRETS) { return $false }
    return (Test-Path (Join-Path $legacyData "secrets/$name")) -or (Test-Path (Join-Path $root "data/secrets/$name"))
}

& $python -m internship_agent.cli discover --sources config/sources.json |
    Out-File (Join-Path $reports "discovery-$stamp.json") -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Discovery failed.' }

# Optional Gmail read only if the local account has already authorized.
if (Test-GoogleAuthorization 'gmail') {
    & $python -m internship_agent.cli ingest-alerts --limit 30 |
        Out-File (Join-Path $reports "alerts-$stamp.json") -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Gmail alert import failed. Check OAuth status.' }
}
if (Test-Path 'config\profile.json') {
    & $python -m internship_agent.cli rank --profile config/profile.json --min-score 50 --limit 50 |
        Out-File (Join-Path $reports "ranked-$stamp.json") -Encoding utf8
}
if ($env:INTERNSHIP_AGENT_SHEET_ID -and (Test-GoogleAuthorization 'sheets')) {
    & $python -m internship_agent.cli sync-sheet |
        Out-File (Join-Path $reports "sheet-preview-$stamp.json") -Encoding utf8
}
Write-Host "Daily report files saved to $reports. No applications or Sheets updates were performed."
