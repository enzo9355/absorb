[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$DataRoot = 'D:\StockPapiData',
    [string]$TaskName = 'StockPapi-LocalQuant',
    [double]$MinimumFreeGB = 100
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runner = Join-Path $RepoRoot 'local_quant.py'
$Wrapper = Join-Path $PSScriptRoot 'run_local_quant_task.ps1'
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonExe = if (Test-Path $BundledPython) { $BundledPython } elseif ($PythonCommand) { $PythonCommand.Source } else { $null }

if (-not $PythonExe) { throw 'Python executable was not found' }
if (-not (Test-Path $Runner)) { throw "Runner not found: $Runner" }
if (-not (Test-Path $Wrapper)) { throw "Wrapper not found: $Wrapper" }
if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root must be D:\StockPapiData' }

$Drive = [System.IO.DriveInfo]::new('D')
if (-not $Drive.IsReady) { throw 'D drive is not ready' }
if ($Drive.DriveFormat -ne 'NTFS') { throw 'D drive must use NTFS' }
if ($Drive.AvailableFreeSpace -lt $MinimumFreeGB * 1GB) {
    throw "D drive must keep at least ${MinimumFreeGB}GB free"
}

$TriggerTime = '02:30'
if ($WhatIfPreference) {
    Write-Output "WhatIf: create $DataRoot with private NTFS ACL"
    Write-Output "WhatIf: register $TaskName daily at $TriggerTime, limit 7 hours"
    return
}

& $PythonExe $Runner --root $DataRoot --init --dry-run
if ($LASTEXITCODE -ne 0) { throw "Local quant initialization failed: $LASTEXITCODE" }

$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$UserSid = $Identity.User
$SystemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$Inheritance = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$Propagation = [System.Security.AccessControl.PropagationFlags]::None
$Allow = [System.Security.AccessControl.AccessControlType]::Allow
$FullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
$AllowedSids = @($UserSid.Value, $SystemSid.Value)
$ExistingAcl = Get-Acl -LiteralPath $DataRoot
$ValidRules = @($ExistingAcl.Access | Where-Object {
    $RuleSid = $_.IdentityReference.Translate(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
    -not $_.IsInherited -and
    $_.AccessControlType -eq $Allow -and
    ($_.FileSystemRights -band $FullControl) -eq $FullControl -and
    $RuleSid -in $AllowedSids
})
$AclIsPrivate = $ExistingAcl.AreAccessRulesProtected -and
    $ExistingAcl.Access.Count -eq 2 -and
    $ValidRules.Count -eq 2
if (-not $AclIsPrivate) {
    $Acl = Get-Acl -LiteralPath $DataRoot
    $Acl.SetAccessRuleProtection($true, $false)
    foreach ($Rule in @($Acl.Access)) {
        $Acl.RemoveAccessRuleSpecific($Rule)
    }
    $Acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $UserSid, $FullControl, $Inheritance, $Propagation, $Allow
    ))
    $Acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $SystemSid, $FullControl, $Inheritance, $Propagation, $Allow
    ))
    Set-Acl -LiteralPath $DataRoot -AclObject $Acl
}

$PowerShellExe = (Get-Process -Id $PID).Path
$ActionArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $Wrapper + '"'
$Action = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument $ActionArguments `
    -WorkingDirectory $RepoRoot
$TriggerAt = [datetime]::ParseExact($TriggerTime, 'HH:mm', $null)
$Trigger = New-ScheduledTaskTrigger -Daily -At $TriggerAt
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7) `
    -MultipleInstances IgnoreNew `
    -Priority 7
$Settings.StartWhenAvailable = $false
$Principal = New-ScheduledTaskPrincipal `
    -UserId $Identity.Name `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description 'Stock Papi local quant runner; data stays on D drive' `
    -Force | Out-Null

Write-Output "Installed $TaskName at $TriggerTime; data root $DataRoot"
