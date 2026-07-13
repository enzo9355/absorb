[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)]
    [ValidateSet('TW', 'US')]
    [string]$Market,

    [Parameter(Mandatory)]
    [ValidatePattern('^manifests/(TW|US)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json$')]
    [string]$LkgManifest,

    [string]$Bucket = 'line-stock-bot-498908-quant-snapshots',
    [int]$MaximumSeconds = 10
)

$ErrorActionPreference = 'Stop'
if ($Bucket -ne 'line-stock-bot-498908-quant-snapshots') { throw 'Bucket is not allowlisted' }
if ($MaximumSeconds -lt 1) { throw 'MaximumSeconds must be positive' }
if ($LkgManifest -notmatch "^manifests/$Market-") { throw 'LKG manifest market does not match Market' }

$Gcloud = (Get-Command gcloud -ErrorAction Stop).Source
$LatestUri = "gs://$Bucket/quant/v1/latest-$Market.json"
$LkgUri = "gs://$Bucket/quant/v1/$LkgManifest"
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("stock-papi-rollback-" + [Guid]::NewGuid().ToString('N'))
$StartedAt = [DateTimeOffset]::UtcNow

function Invoke-Gcloud {
    param([string[]]$Arguments)

    $PreviousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $null
        $Output = & $Gcloud @Arguments 2>&1
        $ExitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $PreviousPythonPath
    }
    if ($ExitCode -ne 0) {
        throw "gcloud command failed with exit code ${ExitCode}: $($Output | Out-String)"
    }
    return ($Output | Out-String)
}

function Get-JsonFile {
    param([string]$Path)

    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        throw "Invalid JSON object: $Path"
    }
}

function Download-Object {
    param([string]$Source, [string]$Destination)

    Invoke-Gcloud @('storage', 'cp', '--quiet', $Source, $Destination) | Out-Null
}

try {
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    $CurrentMetadata = Invoke-Gcloud @('storage', 'objects', 'describe', $LatestUri, '--format=json') |
        ConvertFrom-Json
    if ([string]$CurrentMetadata.generation -notmatch '^\d+$') {
        throw 'Active latest pointer has no valid GCS generation'
    }

    $CurrentPath = Join-Path $TempRoot 'current-latest.json'
    $ManifestPath = Join-Path $TempRoot 'lkg-manifest.json'
    Download-Object $LatestUri $CurrentPath
    Download-Object $LkgUri $ManifestPath

    $Current = Get-JsonFile $CurrentPath
    $Manifest = Get-JsonFile $ManifestPath
    if ($Current.schema_version -ne 2 -or $Current.market -ne $Market) {
        throw 'Active latest pointer schema or market is invalid'
    }
    if ($Current.manifest -eq $LkgManifest) {
        throw 'Requested LKG manifest is already active'
    }
    if ($Manifest.schema_version -ne 2 -or $Manifest.market -ne $Market) {
        throw 'LKG manifest schema or market is invalid'
    }
    if ([double]$Manifest.coverage -lt 0.95 -or [int]$Manifest.symbol_count -lt 1) {
        throw 'LKG manifest does not meet the 95 percent coverage requirement'
    }
    if (-not $Manifest.generated_at -or -not $Manifest.market_as_of) {
        throw 'LKG manifest lacks point-in-time metadata'
    }

    $ManifestHash = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $RollbackPointer = [ordered]@{
        schema_version = 2
        market = $Market
        generated_at = [string]$Manifest.generated_at
        manifest = $LkgManifest
        manifest_sha256 = $ManifestHash
    }
    $PointerPath = Join-Path $TempRoot 'rollback-latest.json'
    [IO.File]::WriteAllText(
        $PointerPath,
        ($RollbackPointer | ConvertTo-Json -Compress),
        [Text.UTF8Encoding]::new($false)
    )

    if (-not $PSCmdlet.ShouldProcess($LatestUri, "replace active pointer with $LkgManifest")) {
        return
    }

    Invoke-Gcloud @(
        'storage', 'cp', '--quiet',
        "--if-generation-match=$($CurrentMetadata.generation)",
        $PointerPath,
        $LatestUri
    ) | Out-Null

    $VerifiedPath = Join-Path $TempRoot 'verified-latest.json'
    Download-Object $LatestUri $VerifiedPath
    $Verified = Get-JsonFile $VerifiedPath
    if (
        $Verified.manifest -ne $LkgManifest -or
        $Verified.manifest_sha256 -ne $ManifestHash -or
        $Verified.market -ne $Market
    ) {
        throw 'Rollback pointer verification failed'
    }

    $ElapsedSeconds = ([DateTimeOffset]::UtcNow - $StartedAt).TotalSeconds
    if ($ElapsedSeconds -gt $MaximumSeconds) {
        throw "Rollback completed but exceeded ${MaximumSeconds}s target: $ElapsedSeconds"
    }
    [ordered]@{
        event = 'MANUAL_ROLLBACK'
        market = $Market
        lkg_manifest = $LkgManifest
        manifest_sha256 = $ManifestHash
        elapsed_seconds = [Math]::Round($ElapsedSeconds, 3)
    } | ConvertTo-Json -Compress
} finally {
    if (Test-Path -LiteralPath $TempRoot) {
        $ResolvedTemp = (Resolve-Path -LiteralPath $TempRoot).Path
        $SystemTemp = [IO.Path]::GetTempPath().TrimEnd([IO.Path]::DirectorySeparatorChar)
        if ($ResolvedTemp.StartsWith($SystemTemp + [IO.Path]::DirectorySeparatorChar)) {
            Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
        }
    }
}
