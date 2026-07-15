[CmdletBinding()]
param([string]$DataRoot = 'D:\AbsorbData', [int]$MaxItems = 25)
$ErrorActionPreference = 'Stop'
if ($DataRoot -notin @('D:\AbsorbData', 'D:\StockPapiData')) { throw 'Data root is not allowlisted' }
if ($MaxItems -lt 1 -or $MaxItems -gt 500) { throw 'MaxItems is outside the safe range' }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonExe = if (Test-Path $BundledPython) { $BundledPython } elseif ($PythonCommand) { $PythonCommand.Source } else { $null }
if (-not $PythonExe) { throw 'Python executable was not found' }
$env:PYTHONPATH = Join-Path $RepoRoot '.deps'
& $PythonExe -m stock_papi.batch.full_backtest_cli --root $DataRoot --max-items $MaxItems
exit $LASTEXITCODE
