[CmdletBinding()]
param(
    [string]$DataRoot = 'D:\StockPapiData'
)

$ErrorActionPreference = 'Stop'
if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root must be D:\StockPapiData' }

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runner = Join-Path $RepoRoot 'local_quant.py'
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonExe = if (Test-Path $BundledPython) { $BundledPython } elseif ($PythonCommand) { $PythonCommand.Source } else { $null }
if (-not $PythonExe) { throw 'Python executable was not found' }

$CacheRoot = Join-Path $DataRoot 'cache'
$TempRoot = Join-Path $CacheRoot 'tmp'
foreach ($Directory in @($CacheRoot, $TempRoot, (Join-Path $CacheRoot 'huggingface'), (Join-Path $CacheRoot 'pycache'))) {
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
}

$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:XDG_CACHE_HOME = $CacheRoot
$env:HF_HOME = Join-Path $CacheRoot 'huggingface'
$env:PYTHONPYCACHEPREFIX = Join-Path $CacheRoot 'pycache'
$env:PYTHONPATH = Join-Path $RepoRoot '.deps'

& $PythonExe $Runner --root $DataRoot --run --market ALL --limit 5000 --delay 0.5
exit $LASTEXITCODE
