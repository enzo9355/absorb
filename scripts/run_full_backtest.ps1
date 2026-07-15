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
$CommandExe = $env:ComSpec
if (-not $CommandExe -or -not (Test-Path -LiteralPath $CommandExe -PathType Leaf)) { throw 'Command processor was not found' }
$PythonCommand = '""{0}" -m stock_papi.batch.full_backtest_cli --root "{1}" --max-items {2} 2>&1"' -f $PythonExe, $DataRoot, $MaxItems
& $CommandExe /d /c $PythonCommand
$ExitCode = $LASTEXITCODE
exit $ExitCode
