[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Enable,
    [string]$TaskName = 'ABSORB-TEJ-Research',
    [string]$At = '03:00'
)

$ErrorActionPreference = 'Stop'
if (-not $Enable) {
    Write-Output 'TEJ scheduler remains disabled. Re-run with -Enable only after TEJ entitlement and secret policy are approved.'
    exit 0
}
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$PythonExe = Resolve-AbsorbPythonExecutable -RepoRoot $RepoRoot
Assert-AbsorbPythonRuntime -PythonExe $PythonExe -RepoRoot $RepoRoot

$UserKey = [Environment]::GetEnvironmentVariable('TEJ_API_KEY', 'User')
$MachineKey = [Environment]::GetEnvironmentVariable('TEJ_API_KEY', 'Machine')
$UserEnabled = [Environment]::GetEnvironmentVariable('TEJ_ENABLED', 'User')
$MachineEnabled = [Environment]::GetEnvironmentVariable('TEJ_ENABLED', 'Machine')
if (
    [string]::IsNullOrWhiteSpace($UserKey) -and
    [string]::IsNullOrWhiteSpace($MachineKey)
) {
    throw 'Refusing to enable TEJ scheduler without a persistent environment-provided TEJ_API_KEY'
}
if (
    ($UserEnabled -notmatch '^(1|true|yes|on)$') -and
    ($MachineEnabled -notmatch '^(1|true|yes|on)$')
) {
    throw 'Refusing to enable TEJ scheduler without persistent TEJ_ENABLED=true'
}

$ScriptPath = (Resolve-Path (Join-Path $PSScriptRoot 'run_tej_research.ps1')).Path
$HiddenLauncher = (Resolve-Path (Join-Path $PSScriptRoot 'run_hidden.vbs')).Path
$WscriptExe = (Get-Command wscript.exe -ErrorAction Stop).Source
$PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$ActionArguments = @(
    '//B'
    '//NoLogo'
    "`"$HiddenLauncher`""
    "`"$PowerShellExe`""
    '-NoProfile'
    '-NonInteractive'
    '-WindowStyle'
    'Hidden'
    '-ExecutionPolicy'
    'Bypass'
    '-File'
    "`"$ScriptPath`""
    '-Command'
    'backfill'
    '-DataRoot'
    'D:\AbsorbData'
) -join ' '
$Action = New-ScheduledTaskAction `
    -Execute $WscriptExe `
    -Argument $ActionArguments `
    -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($At, 'HH:mm', $null))
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, 'register separate TEJ research task')) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Force | Out-Null
    Write-Output "Registered $TaskName; it never invokes the TW post-close writer."
} else {
    Write-Output "WhatIf: register $TaskName at $At with the separate TEJ research wrapper"
}
