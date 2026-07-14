[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$DataRoot = 'D:\StockPapiData',
  [ValidateSet('Saturday','Sunday')][string]$WeeklyDay = 'Saturday'
)
$ErrorActionPreference = 'Stop'
if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root is not allowlisted' }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-ScheduledTaskPrincipal -UserId $Identity.Name -LogonType Interactive -RunLevel Limited
$Definitions = @(
  @{ Name='StockPapi-TW-PostClose'; Time='17:10'; Command='scripts\run_tw_post_close_pipeline.ps1' },
  @{ Name='StockPapi-TW-PreMarket'; Time='07:30'; Command='scripts\run_tw_pre_market_pipeline.ps1' },
  @{ Name='StockPapi-FullBacktest'; Time='22:30'; Command='scripts\run_full_backtest.ps1' },
  @{ Name='StockPapi-US-Daily'; Time='05:30'; Command='scripts\run_us_daily.ps1' },
  @{ Name='StockPapi-WeeklyModel'; Time='18:00'; Days=$WeeklyDay; Command='scripts\run_weekly_model.ps1' },
  @{ Name='StockPapi-ReportUploadRecovery'; Time='09:35'; Command='scripts\upload_local_quant.ps1' }
)
foreach ($Definition in $Definitions) {
  $CommandPath = Join-Path $RepoRoot $Definition.Command
  if (-not (Test-Path -LiteralPath $CommandPath -PathType Leaf)) { throw "Task wrapper not found: $CommandPath" }
  $Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$CommandPath`" -DataRoot `"$DataRoot`"" -WorkingDirectory $RepoRoot
  $At = [datetime]::ParseExact($Definition.Time, 'HH:mm', $null)
  $Trigger = if ($Definition.Days) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Definition.Days -At $At
  } else {
    New-ScheduledTaskTrigger -Daily -At $At
  }
  $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)
  $Settings.StartWhenAvailable = $true
  $Settings.WakeToRun = $true
  if ($PSCmdlet.ShouldProcess($Definition.Name, 'Register shadow pipeline task')) {
    Register-ScheduledTask -TaskName $Definition.Name -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
  }
}
