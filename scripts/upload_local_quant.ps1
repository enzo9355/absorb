[CmdletBinding()]
param(
    [string]$DataRoot = 'D:\StockPapiData',
    [string]$Bucket = 'line-stock-bot-498908-quant-snapshots'
)

$ErrorActionPreference = 'Stop'
if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root is not allowlisted' }
if ($Bucket -ne 'line-stock-bot-498908-quant-snapshots') { throw 'Bucket is not allowlisted' }

$PublishRoot = Join-Path $DataRoot 'publish\quant\v1'
$ResolvedRoot = (Resolve-Path -LiteralPath $PublishRoot).Path
if (((Get-Item -LiteralPath $ResolvedRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'Publish root must not be a reparse point'
}
$Gcloud = (Get-Command gcloud -ErrorAction Stop).Source
$ObjectBatchSize = 100

function Assert-AllowlistedPath {
    param([string]$Path)
    $Resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $Resolved.StartsWith($ResolvedRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw 'Upload path escaped publish root'
    }
    $Current = Get-Item -LiteralPath $Resolved
    while ($Current.FullName -ne $ResolvedRoot) {
        if (($Current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Upload path contains a reparse point'
        }
        $Current = $Current.Parent
    }
    return $Resolved
}

function Invoke-GcloudCopy {
    param(
        [string]$Source,
        [string]$Destination,
        [switch]$NoClobber
    )
    $Arguments = @('storage', 'cp', '--quiet')
    if ($NoClobber) { $Arguments += '--no-clobber' }
    $Arguments += @($Source, $Destination)
    & $Gcloud @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud upload failed with exit code $LASTEXITCODE" }
}

function Invoke-GcloudCopyBatch {
    param(
        [string[]]$Sources,
        [string]$Destination
    )
    if (-not $Sources -or $Sources.Count -eq 0) { return }
    $Arguments = @('storage', 'cp', '--quiet', '--no-clobber')
    $Arguments += $Sources
    $Arguments += $Destination
    & $Gcloud @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud batch upload failed with exit code $LASTEXITCODE" }
}

$InsightsUploaded = $false
$InsightsLatestPath = Join-Path $ResolvedRoot 'latest-insights.json'
if (Test-Path -LiteralPath $InsightsLatestPath -PathType Leaf) {
    $InsightsLatestPath = Assert-AllowlistedPath $InsightsLatestPath
    $Insights = Get-Content -LiteralPath $InsightsLatestPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($Insights.schema_version -ne 1 -or $Insights.kind -ne 'market-insights') {
        throw 'Invalid market-insights latest pointer'
    }
    $InsightsObjectRelative = [string]$Insights.path
    if ($InsightsObjectRelative -notmatch '^objects/[0-9a-f]{64}\.json\.gz$') {
        throw 'Invalid market-insights object path'
    }
    $InsightsObjectPath = Assert-AllowlistedPath (Join-Path $ResolvedRoot $InsightsObjectRelative)
    $InsightsObject = Get-Item -LiteralPath $InsightsObjectPath
    if ($InsightsObject.Length -ne [long]$Insights.size) { throw 'Market-insights object size mismatch' }
    if ((Get-FileHash -LiteralPath $InsightsObjectPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Insights.sha256) {
        throw 'Market-insights object hash mismatch'
    }
    Invoke-GcloudCopy $InsightsObjectPath "gs://$Bucket/quant/v1/$InsightsObjectRelative" -NoClobber
    Invoke-GcloudCopy $InsightsLatestPath "gs://$Bucket/quant/v1/latest-insights.json"
    $InsightsUploaded = $true
}

$UploadedMarkets = @()
foreach ($Market in @('TW', 'US')) {
    $LatestPath = Join-Path $ResolvedRoot "latest-$Market.json"
    if (-not (Test-Path -LiteralPath $LatestPath -PathType Leaf)) { continue }
    $LatestPath = Assert-AllowlistedPath $LatestPath
    $Latest = Get-Content -LiteralPath $LatestPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($Latest.schema_version -ne 2 -or $Latest.market -ne $Market) {
        throw "Invalid latest pointer for $Market"
    }
    $ManifestRelative = [string]$Latest.manifest
    if ($ManifestRelative -notmatch '^manifests/[A-Z]+-[0-9TZ]+-[0-9a-f]{12}\.json$') {
        throw "Invalid manifest path for $Market"
    }
    $ManifestPath = Assert-AllowlistedPath (Join-Path $ResolvedRoot $ManifestRelative)
    if ((Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Latest.manifest_sha256) {
        throw "Manifest hash mismatch for $Market"
    }
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($Manifest.schema_version -ne 2 -or $Manifest.market -ne $Market) {
        throw "Invalid manifest for $Market"
    }

    # Upload objects only after validating every object in this manifest.
    $ValidatedObjectPaths = @()
    foreach ($Property in $Manifest.symbols.PSObject.Properties) {
        $Entry = $Property.Value
        $ObjectRelative = [string]$Entry.path
        if ($ObjectRelative -notmatch '^objects/[0-9a-f]{64}\.json\.gz$') {
            throw "Invalid object path for $Market"
        }
        $ObjectPath = Assert-AllowlistedPath (Join-Path $ResolvedRoot $ObjectRelative)
        $Object = Get-Item -LiteralPath $ObjectPath
        if ($Object.Length -ne [long]$Entry.size) { throw "Object size mismatch for $Market" }
        if ((Get-FileHash -LiteralPath $ObjectPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Entry.sha256) {
            throw "Object hash mismatch for $Market"
        }
        $ValidatedObjectPaths += $ObjectPath
    }
    for ($Offset = 0; $Offset -lt $ValidatedObjectPaths.Count; $Offset += $ObjectBatchSize) {
        $Last = [Math]::Min($Offset + $ObjectBatchSize - 1, $ValidatedObjectPaths.Count - 1)
        Invoke-GcloudCopyBatch `
            -Sources $ValidatedObjectPaths[$Offset..$Last] `
            -Destination "gs://$Bucket/quant/v1/objects/"
    }

    # Upload manifest
    Invoke-GcloudCopy $ManifestPath "gs://$Bucket/quant/v1/$ManifestRelative" -NoClobber

    # Upload latest pointer
    Invoke-GcloudCopy $LatestPath "gs://$Bucket/quant/v1/latest-$Market.json"
    $UploadedMarkets += $Market
}

$Status = @{
    uploaded_at = [DateTimeOffset]::Now.ToString('o')
    markets = $UploadedMarkets
    market_insights = $InsightsUploaded
    bucket = $Bucket
} | ConvertTo-Json -Compress
Set-Content -LiteralPath (Join-Path $DataRoot 'logs\upload-status.json') -Value $Status -Encoding utf8
Write-Output "Uploaded quant snapshots: $($UploadedMarkets -join ',')"
