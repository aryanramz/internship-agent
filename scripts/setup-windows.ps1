$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

# Use the available Python 3 interpreter, provided it satisfies pyproject.toml.
& py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or later before running setup.' }

if (!(Test-Path '.venv')) {
    & py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment.' }
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& .\.venv\Scripts\python.exe -m pip install -e '.[mcp,google,test]'
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }

if (!(Test-Path 'config\profile.json')) {
    Copy-Item config\profile.example.json config\profile.json
}
if (!(Test-Path 'config\sources.json')) {
    Copy-Item config\sources.example.json config\sources.json
}
Write-Host 'Edit your PRIVATE config\profile.json and config\sources.json before real discovery.'
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Test suite failed.' }
