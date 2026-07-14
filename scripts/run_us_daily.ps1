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
& $PythonExe (Join-Path $RepoRoot 'local_quant.py') --root $DataRoot --run --market US --limit 5000 --delay 0.5
exit $LASTEXITCODE
