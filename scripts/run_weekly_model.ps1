[CmdletBinding()]
param([string]$DataRoot = 'D:\StockPapiData')
$ErrorActionPreference = 'Stop'
if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root is not allowlisted' }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonExe = if (Test-Path $BundledPython) { $BundledPython } elseif ($PythonCommand) { $PythonCommand.Source } else { $null }
if (-not $PythonExe) { throw 'Python executable was not found' }
$Year = (Get-Date).Year
$CalendarPath = if ($env:TWSE_CALENDAR_ARTIFACT) { $env:TWSE_CALENDAR_ARTIFACT } else { Join-Path $DataRoot "publish\calendars\v1\TW-$Year.json" }
$env:PYTHONPATH = Join-Path $RepoRoot '.deps'
& $PythonExe -m stock_papi.batch.weekly_cli --root $DataRoot --calendar-artifact $CalendarPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot 'upload_local_quant.ps1') -DataRoot $DataRoot -RequireReportV2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonExe -m stock_papi.batch.cli notify --root $DataRoot --report-type weekly_model --audience admin --audience broadcast
exit $LASTEXITCODE
