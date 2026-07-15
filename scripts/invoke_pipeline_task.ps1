[CmdletBinding()]
param(
    [ValidateSet('TW-PostClose', 'TW-PreMarket', 'FullBacktest', 'US-Daily', 'WeeklyModel', 'ReportUploadRecovery')]
    [string]$Job,
    [string]$DataRoot = 'D:\AbsorbData'
)

$ErrorActionPreference = 'Stop'
if ($DataRoot -ne 'D:\AbsorbData') { throw 'Data root is not allowlisted' }

$Definitions = @{
    'TW-PostClose' = @{ Script = 'run_tw_post_close_pipeline.ps1'; Arguments = @() }
    'TW-PreMarket' = @{ Script = 'run_tw_pre_market_pipeline.ps1'; Arguments = @() }
    'FullBacktest' = @{ Script = 'run_full_backtest.ps1'; Arguments = @() }
    'US-Daily' = @{ Script = 'run_us_daily.ps1'; Arguments = @() }
    'WeeklyModel' = @{ Script = 'run_weekly_model.ps1'; Arguments = @() }
    'ReportUploadRecovery' = @{ Script = 'upload_local_quant.ps1'; Arguments = @('-RequireReportV2') }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Definition = $Definitions[$Job]
$ScriptPath = Join-Path $PSScriptRoot $Definition.Script
if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) { throw "Task wrapper not found: $ScriptPath" }

$LogDirectory = Join-Path $DataRoot 'logs\tasks'
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$StartedAt = [DateTimeOffset]::Now
$LogPath = Join-Path $LogDirectory ("{0}-{1:yyyyMMdd}.log" -f $Job, $StartedAt)
$StatusPath = Join-Path $LogDirectory ("current-{0}.json" -f $Job)
$PowerShellExe = (Get-Process -Id $PID).Path
$Arguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath, '-DataRoot', $DataRoot) + $Definition.Arguments

try {
    # 上游資料來源可能在 stderr 寫入非致命警告；保留到 transcript，
    # 但只依 child PowerShell 的實際 exit code 判定 pipeline 是否失敗。
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $PowerShellExe @Arguments 2>&1 | Tee-Object -FilePath $LogPath -Append
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) { throw "Pipeline exited with code $ExitCode" }
    @{ job = $Job; started_at = $StartedAt.ToString('o'); finished_at = [DateTimeOffset]::Now.ToString('o'); success = $true; exit_code = 0; log = $LogPath } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $StatusPath -Encoding utf8
} catch {
    @{ job = $Job; started_at = $StartedAt.ToString('o'); finished_at = [DateTimeOffset]::Now.ToString('o'); success = $false; exit_code = if ($ExitCode -is [int]) { $ExitCode } else { 1 }; error = $_.Exception.Message; log = $LogPath } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $StatusPath -Encoding utf8
    throw
}
