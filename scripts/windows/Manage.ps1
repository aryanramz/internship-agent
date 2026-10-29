# Reviewable per-user Task Scheduler controls. Preview never connects to Task Scheduler.
[CmdletBinding()]
param(
    [ValidateSet('Configure', 'Preview', 'Start', 'Stop', 'Disable', 'Remove', 'Status')]
    [string]$Operation = 'Status',
    [string]$SettingsPath,
    [string]$RendererPython
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$statePath = Join-Path $workspace 'data\windows-lifecycle.json'
$helper = Join-Path $PSScriptRoot 'task_config.py'
if (-not $RendererPython) { $RendererPython = Join-Path $workspace '.venv\Scripts\python.exe' }

function Invoke-Renderer([string]$Mode, $Request) {
    $inputJson = $Request | ConvertTo-Json -Depth 12 -Compress
    $result = $inputJson | & $RendererPython -X utf8 $helper $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Windows task validation failed.' }
    if ($result) { return ($result | ConvertFrom-Json) }
}

function Get-TaskOrNull($Folder, [string]$Name) {
    # COM returns the Win32 file-not-found code for an absent task. Other failures propagate.
    try { return $Folder.GetTask($Name) }
    catch {
        $taskException = $_.Exception
        while ($taskException) {
            if ($taskException.HResult -eq -2147024894) { return $null }
            $taskException = $taskException.InnerException
        }
        throw
    }
}

try {
    if ($Operation -eq 'Preview') {
        if (-not $SettingsPath) { throw 'Preview requires a synthetic settings file.' }
        $settings = Get-Content -Raw -LiteralPath $SettingsPath | ConvertFrom-Json
        Invoke-Renderer 'render' $settings | ConvertTo-Json -Depth 12
        exit 0
    }
    # Do not permit command-line path overrides for real lifecycle operations.
    if ($SettingsPath -or $PSBoundParameters.ContainsKey('RendererPython')) {
        throw 'Path overrides are allowed only for offline Preview.'
    }
    $owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($Operation -eq 'Configure') {
        if (Test-Path -LiteralPath $statePath) { throw 'Already configured. Use Remove before configuring again.' }
        Add-Type -AssemblyName System.Windows.Forms
        $configPicker = New-Object System.Windows.Forms.OpenFileDialog
        $configPicker.Title = 'Select the existing PRIVATE gateway JSON configuration'
        $configPicker.Filter = 'JSON files (*.json)|*.json'
        if ($configPicker.ShowDialog() -ne 'OK') { exit 1 }
        $providerPicker = New-Object System.Windows.Forms.FolderBrowserDialog
        $providerPicker.Description = 'Select the approved Keycloak home (persistent local database already configured)'
        if ($providerPicker.ShowDialog() -ne 'OK') { exit 1 }
        $settings = [ordered]@{ workspace = $workspace; config_path = $configPicker.FileName;
            keycloak_home = $providerPicker.SelectedPath; user_sid = $owner; windows_dir = $env:SystemRoot }
    } else {
        if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw 'Configure the controls first.' }
        $settings = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        if ($settings.workspace -ne $workspace -or $settings.user_sid -ne $owner -or
            $settings.windows_dir -ne $env:SystemRoot) { throw 'Configuration belongs to another workspace or user.' }
    }
    $definition = Invoke-Renderer 'render' $settings
    $requirements = Invoke-Renderer 'requirements' @{definition = $definition; operation = $Operation}
    foreach ($required in $requirements.files) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw 'A configured runtime or private configuration file is missing.' }
    }
    if ($Operation -in @('Configure', 'Start')) {
        $providerConfig = Join-Path $definition.settings.keycloak_home 'conf\keycloak.conf'
        & $RendererPython $helper 'provider-guard' $providerConfig
        if ($LASTEXITCODE -ne 0) { throw 'Provider production configuration did not pass validation.' }
    }
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    $folder = $scheduler.GetFolder('\')
    # Validate EVERY existing task before changing either task.
    foreach ($expected in $definition.tasks) {
        $actual = Get-TaskOrNull $folder $expected.name
        if ($Operation -eq 'Configure') {
            if ($actual) { throw 'A task already uses the reserved name; nothing was overwritten.' }
        } elseif ($actual) {
            Invoke-Renderer 'verify' @{actual = $actual.Xml; expected = $expected.xml}
        } elseif ($Operation -notin @('Remove', 'Status')) {
            throw 'An owned task is missing; inspect Task Scheduler before proceeding.'
        }
    }
    if ($Operation -eq 'Configure') {
        $created = @()
        try {
            foreach ($task in $definition.tasks) {
                # TASK_CREATE=2, TASK_LOGON_INTERACTIVE_TOKEN=3: no password or elevation.
                $null = $folder.RegisterTask($task.name, $task.xml, 2, $owner, $null, 3, $null)
                $created += $task.name
            }
            $null = New-Item -ItemType Directory -Path (Split-Path $statePath) -Force
            $definition.settings | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        } catch {
            foreach ($name in $created) { $folder.DeleteTask($name, 0) }
            throw
        }
        Write-Output 'Configured for your next sign-in. Double-click Start to run now.'
        exit 0
    }
    $ordered = Invoke-Renderer 'order' @{definition = $definition; operation = $Operation}
    foreach ($task in $ordered) {
        $registered = Get-TaskOrNull $folder $task.name
        if (-not $registered) { Write-Output ($task.role + ': not installed'); continue }
        switch ($Operation) {
            'Start' { $registered.Enabled = $true; $null = $registered.Run($null) }
            'Stop' { $registered.Stop(0) }
            'Disable' { $registered.Enabled = $false; $registered.Stop(0) }
            'Remove' { $registered.Enabled = $false; $registered.Stop(0); $folder.DeleteTask($task.name, 0) }
            'Status' { Write-Output ($task.role + ': state=' + $registered.State + '; last result=' + $registered.LastTaskResult) }
        }
    }
    if ($Operation -eq 'Remove') { Remove-Item -LiteralPath $statePath }
    if ($Operation -ne 'Status') { Write-Output ($Operation + ' completed for the two owned tasks.') }
    exit 0
} catch {
    # Do not echo config contents, provider output or raw exception payloads.
    Write-Error 'Windows control did not complete. Review the startup guide and Task Scheduler; no unrelated process was targeted.'
    exit 1
}
