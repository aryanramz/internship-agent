# No task mutation occurs without verifying current-user identity and owned action.
[CmdletBinding()]
param([ValidateSet('inspect','install','start','disable','remove')][string]$Operation)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Assert-OwnedTask([xml]$existing, [xml]$expected) {
    $ns = New-Object System.Xml.XmlNamespaceManager($expected.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
        foreach ($path in @('RegistrationInfo/Description','RegistrationInfo/URI','Principals/Principal/UserId',
            'Principals/Principal/LogonType','Principals/Principal/RunLevel','Actions/Exec/Command',
            'Actions/Exec/Arguments','Actions/Exec/WorkingDirectory')) {
            $query = '/t:Task/' + (($path.Split('/') | ForEach-Object { 't:' + $_ }) -join '/')
            $a = $existing.SelectNodes($query,$ns)
            $b = $expected.SelectNodes($query,$ns)
            if ($a.Count -ne 1 -or $b.Count -ne 1 -or $a[0].InnerText -cne $b[0].InnerText) { throw 'Ownership drift' }
        }
        foreach ($path in @('/t:Task/t:Actions/*','/t:Task/t:Principals/*')) {
            if ($existing.SelectNodes($path,$ns).Count -ne 1) { throw 'Unexpected action/principal' }
        }
}
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($request.sid -cne $owner -or $request.name -notmatch '^InternshipAgent-Daily-[a-f0-9]{20}$') { throw 'Identity mismatch' }
    [xml]$expected = $request.xml
    $ns = New-Object System.Xml.XmlNamespaceManager($expected.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    if ($expected.SelectSingleNode('//t:Principal/t:UserId',$ns).InnerText -cne $owner) { throw 'Owner mismatch' }
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $actual = $null
    try { $actual = $folder.GetTask($request.name) }
    catch {
        $e = $_.Exception
        $missing = $false
        while ($e) {
            if ($e.HResult -eq -2147024894) { $missing = $true }
            $e = $e.InnerException
        }
        if (-not $missing) { throw }
    }
    if ($actual) {
        [xml]$existing = $actual.Xml
        Assert-OwnedTask $existing $expected
    } elseif ($Operation -notin @('inspect','install','remove')) { throw 'Task missing' }
    switch ($Operation) {
        'install' {
            # TASK_CREATE_OR_UPDATE=6; InteractiveToken=3; no password/elevation.
            $null = $folder.RegisterTask($request.name,$request.xml,6,$owner,$null,3,$null)
        }
        'start' { $actual.Enabled = $true; $null = $actual.Run($null) }
        'disable' { $actual.Enabled = $false }
        'remove' { if ($actual) { $actual.Enabled = $false; $folder.DeleteTask($request.name,0) } }
    }
    if ($actual) {
        @{exists=$true; state=[int]$actual.State; last_result=[int]$actual.LastTaskResult} | ConvertTo-Json -Compress
    } else { @{exists=$false} | ConvertTo-Json -Compress }
} catch {
    [Console]::Error.WriteLine('Owned scheduler task operation refused. Inspect local configuration and Task Scheduler.')
    exit 2
}
