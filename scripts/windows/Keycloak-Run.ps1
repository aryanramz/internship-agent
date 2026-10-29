# A synchronous hidden task action, not a daemon or a process-name based killer.
param([Parameter(Mandatory = $true)][string]$KeycloakHome)
$ErrorActionPreference = 'Stop'
try {
    if (-not [System.IO.Path]::IsPathRooted($KeycloakHome) -or
        $KeycloakHome -notmatch '^[A-Za-z]:\\' -or $KeycloakHome -match '["%&|<>^!`\r\n]') { exit 1 }
    $launcher = Join-Path $KeycloakHome 'bin\kc.bat'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { exit 1 }
    $workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
    $python = Join-Path $workspace '.venv\Scripts\python.exe'
    $guard = Join-Path $PSScriptRoot 'task_config.py'
    & $python $guard 'provider-guard' (Join-Path $KeycloakHome 'conf\keycloak.conf') *> $null
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Set-Location -LiteralPath $KeycloakHome
    # Credentials stay in the private provider configuration. Do not capture logs.
    & $launcher start --http-host=127.0.0.1 --http-management-host=127.0.0.1 --cache=local *> $null
    exit $LASTEXITCODE
} catch { exit 1 }
