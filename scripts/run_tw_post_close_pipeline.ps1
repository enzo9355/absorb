[CmdletBinding()]
param([string]$DataRoot = 'D:\StockPapiData')
$ErrorActionPreference = 'Stop'
if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root is not allowlisted' }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonExe = if (Test-Path $BundledPython) { $BundledPython } elseif ($PythonCommand) { $PythonCommand.Source } else { $null }
if (-not $PythonExe) { throw 'Python executable was not found' }
$env:PYTHONPATH = Join-Path $RepoRoot '.deps'
$TargetDate = (Get-Date).ToString('yyyy-MM-dd')
$Year = (Get-Date).Year
$CalendarPath = if ($env:TWSE_CALENDAR_ARTIFACT) { $env:TWSE_CALENDAR_ARTIFACT } else { Join-Path $DataRoot "publish\calendars\v1\TW-$Year.json" }
& $PythonExe -m stock_papi.batch.cli calendar-check --calendar-artifact $CalendarPath --date $TargetDate
$CalendarExitCode = $LASTEXITCODE
if ($CalendarExitCode -eq 3) { Write-Output "$TargetDate is not a TW trading session; skipped"; exit 0 }
if ($CalendarExitCode -ne 0) { exit $CalendarExitCode }
& $PythonExe (Join-Path $RepoRoot 'local_quant.py') --root $DataRoot --post-close --market TW --target-market-date $TargetDate --limit 5000 --delay 0.5
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$Latest = Get-Content -LiteralPath (Join-Path $DataRoot 'publish\quant\v1\latest-TW.json') -Raw -Encoding utf8 | ConvertFrom-Json
$ManifestRelative = [string]$Latest.manifest
$ManifestPath = Join-Path $DataRoot "publish\quant\v1\$ManifestRelative"
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$Versions = @($Manifest.symbols.PSObject.Properties.Value.model_version | Sort-Object -Unique)
if ($Versions.Count -ne 1) { throw 'Quant manifest contains mixed model versions' }
$BackfillArguments = @('-m', 'reporting.backfill', '--root', $DataRoot, '--market', 'TW', '--report-type', 'post_close', '--source-market-date', $Manifest.market_as_of, '--source-manifest', "quant/v1/$ManifestRelative", '--source-manifest-sha256', $Latest.manifest_sha256, '--model-version', $Versions[0], '--calendar-artifact', $CalendarPath, '--apply')
$NextCalendarPath = Join-Path $DataRoot "publish\calendars\v1\TW-$($Year + 1).json"
if (Test-Path -LiteralPath $NextCalendarPath -PathType Leaf) { $BackfillArguments += @('--calendar-artifact', $NextCalendarPath) }
& $PythonExe @BackfillArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot 'upload_local_quant.ps1') -DataRoot $DataRoot -RequireReportV2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonExe -m stock_papi.batch.cli notify --root $DataRoot --report-type post_close --audience admin --audience broadcast
exit $LASTEXITCODE
