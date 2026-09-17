[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$TaskName = 'ABSORB-X-Opinions'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$PythonExe = Resolve-AbsorbPythonExecutable -RepoRoot $RepoRoot
Assert-AbsorbPythonRuntime -PythonExe $PythonExe -RepoRoot $RepoRoot -RequiredImports @('stock_papi.batch.x_watch_cli')
$Launcher = (Resolve-Path (Join-Path $PSScriptRoot 'run_hidden.vbs')).Path
$Arguments = "//B //NoLogo `"$Launcher`" `"$PythonExe`" -m stock_papi.batch.x_watch_cli"
$Action = New-ScheduledTaskAction -Execute (Get-Command wscript.exe).Source -Argument $Arguments -WorkingDirectory $RepoRoot
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing -and ($Existing.Actions.Arguments -notmatch 'stock_papi\.batch\.x_watch_cli' -or $Existing.Actions.WorkingDirectory -ne $RepoRoot)) {
    throw 'Existing task does not belong to this watcher; refusing replacement'
}
# No repetition duration: keep polling indefinitely, including after the next login.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, 'Enable free X polling every five minutes without visible windows')) {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
        -Principal $Principal -Description 'Free FxTwitter polling for three ABSORB research accounts; pending candidates only.' -Force | Out-Null
    Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, Actions, Triggers
}
