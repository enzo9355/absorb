[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CandidatePath,
    [string]$Service = 'line-stock-bot',
    [string]$Project = 'line-stock-bot-498908',
    [string]$Region = 'asia-east1'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$AllowedRoot = (Resolve-Path 'D:\AbsorbData\outputs\post_close_report\candidates').Path
$Candidate = (Resolve-Path -LiteralPath $CandidatePath).Path
if (-not $Candidate.StartsWith($AllowedRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw 'Preview candidate is outside the allowlisted candidate root'
}
$CandidateId = Split-Path $Candidate -Leaf
if ($CandidateId -notmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{16}$') {
    throw 'Preview candidate id is invalid'
}
$ManifestPath = Join-Path $Candidate 'candidate.json'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
if ($Manifest.schema_version -ne 1 -or $Manifest.kind -ne 'absorb-daily-candidate') {
    throw 'Preview candidate manifest is invalid'
}
foreach ($Property in $Manifest.files.PSObject.Properties) {
    $Path = Join-Path $Candidate $Property.Name
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Preview candidate file is missing: $($Property.Name)"
    }
    $File = Get-Item -LiteralPath $Path
    $Digest = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($File.Length -ne [long]$Property.Value.size -or $Digest -ne [string]$Property.Value.sha256) {
        throw "Preview candidate hash mismatch: $($Property.Name)"
    }
}

$ServiceInfo = gcloud run services describe $Service --project $Project --region $Region --format=json |
    ConvertFrom-Json
if (-not $ServiceInfo.status.url) { throw 'Cloud Run service is unavailable' }
$Bucket = @(
    $ServiceInfo.spec.template.spec.containers[0].env |
    Where-Object { $_.name -eq 'QUANT_SNAPSHOT_BUCKET' } |
    Select-Object -ExpandProperty value
)[0]
if (-not $Bucket) { throw 'QUANT_SNAPSHOT_BUCKET is unavailable' }

$Prefix = "previews/$CandidateId"
$Files = @('candidate.json') + @($Manifest.files.PSObject.Properties.Name)
foreach ($Name in $Files) {
    gcloud storage cp (Join-Path $Candidate $Name) "gs://$Bucket/$Prefix/$Name" `
        --if-generation-match=0 --project $Project --quiet
    if ($LASTEXITCODE -ne 0) { throw "Preview upload failed: $Name" }
}

$Tag = ('preview-' + ($CandidateId -replace '[^a-z0-9-]', '-')).Trim('-')
gcloud run deploy $Service --source $RepoRoot --project $Project --region $Region `
    --no-traffic --tag $Tag `
    --update-env-vars "ABSORB_PREVIEW_CANDIDATE_PREFIX=$Prefix" --quiet
if ($LASTEXITCODE -ne 0) { throw 'Cloud Run no-traffic preview deployment failed' }

$After = gcloud run services describe $Service --project $Project --region $Region --format=json |
    ConvertFrom-Json
$Revision = [string]$After.status.latestCreatedRevisionName
$Traffic = @($After.status.traffic | Where-Object { $_.revisionName -eq $Revision })
if (@($Traffic | Where-Object { [int]$_.percent -gt 0 }).Count -gt 0) {
    throw 'Preview revision unexpectedly received production traffic'
}
$Tagged = @($After.status.traffic | Where-Object { $_.tag -eq $Tag }) | Select-Object -First 1
if (-not $Tagged.url) { throw 'Preview tag URL is unavailable' }

[ordered]@{
    service = $Service
    revision = $Revision
    tag = $Tag
    preview_url = [string]$Tagged.url
    candidate_prefix = $Prefix
    production_traffic_percent = 0
    gcs_production_latest_updated = $false
    line_production_updated = $false
} | ConvertTo-Json -Compress
