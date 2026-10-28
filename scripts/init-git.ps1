$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (!(Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first.' }
if (Test-Path '.git') { Write-Host 'Git already initialized; review status.'; git status --short; exit 0 }

# Never create a commit under a fabricated identity; use your own Git config.
$name = git config --get user.name
$email = git config --get user.email
if (!$name -or !$email) { throw 'Configure git user.name and user.email before committing.' }

git init -b main
git add --all
python scripts/check_repo_hygiene.py
if ($LASTEXITCODE -ne 0) { throw 'Repository privacy check failed. Unstage sensitive files before committing.' }
Write-Host 'Review staged files before the initial commit:'
git diff --cached --name-only
Write-Host 'If the files look correct, run: git commit -m "Initial open-source portfolio release"'
Write-Host 'Then create a repository on GitHub and add its remote. Nothing has been published.'
