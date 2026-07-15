[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$DataRoot = 'D:\StockPapiData',
    [string]$TaskName = 'StockPapi-LocalQuant',
    [string]$UploadTaskName = 'StockPapi-QuantUpload',
    [string]$Bucket = 'line-stock-bot-498908-quant-snapshots',
    [double]$MinimumFreeGB = 100
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runner = Join-Path $RepoRoot 'local_quant.py'
$Wrapper = Join-Path $PSScriptRoot 'run_local_quant_task.ps1'
$UploadWrapper = Join-Path $PSScriptRoot 'upload_local_quant.ps1'
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonExe = if (Test-Path $BundledPython) { $BundledPython } elseif ($PythonCommand) { $PythonCommand.Source } else { $null }

if (-not $PythonExe) { throw 'Python executable was not found' }
if (-not (Test-Path $Runner)) { throw "Runner not found: $Runner" }
if (-not (Test-Path $Wrapper)) { throw "Wrapper not found: $Wrapper" }
if (-not (Test-Path $UploadWrapper)) { throw "Uploader not found: $UploadWrapper" }
if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root must be D:\StockPapiData' }
if ($Bucket -ne 'line-stock-bot-498908-quant-snapshots') { throw 'Bucket is not allowlisted' }

$Drive = [System.IO.DriveInfo]::new('D')
if (-not $Drive.IsReady) { throw 'D drive is not ready' }
if ($Drive.DriveFormat -ne 'NTFS') { throw 'D drive must use NTFS' }
if ($Drive.AvailableFreeSpace -lt $MinimumFreeGB * 1GB) {
    throw "D drive must keep at least ${MinimumFreeGB}GB free"
}

$TriggerTime = '02:30'
$UploadTriggerTime = '09:35'
if ($WhatIfPreference) {
    Write-Output "WhatIf: create $DataRoot with private NTFS ACL"
    Write-Output "WhatIf: register $TaskName daily at $TriggerTime, limit 7 hours"
    Write-Output "WhatIf: register $UploadTaskName daily at $UploadTriggerTime, limit 1 hour"
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
    -Description 'ABSORB legacy-name local quant runner; data stays on D drive' `
    -Force | Out-Null

$UploadArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    $UploadWrapper + '" -DataRoot "' + $DataRoot + '" -Bucket "' + $Bucket + '"'
$UploadAction = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument $UploadArguments `
    -WorkingDirectory $RepoRoot
$UploadTriggerAt = [datetime]::ParseExact($UploadTriggerTime, 'HH:mm', $null)
$UploadTrigger = New-ScheduledTaskTrigger -Daily -At $UploadTriggerAt
$UploadSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew `
    -Priority 7
$UploadSettings.StartWhenAvailable = $false

Register-ScheduledTask `
    -TaskName $UploadTaskName `
    -Action $UploadAction `
    -Trigger $UploadTrigger `
    -Settings $UploadSettings `
    -Principal $Principal `
    -Description 'ABSORB legacy-name private quant snapshot uploader' `
    -Force | Out-Null

Write-Output "Installed $TaskName at $TriggerTime and $UploadTaskName at $UploadTriggerTime"
