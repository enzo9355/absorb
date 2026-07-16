[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Quant')]
    [ValidateSet('TW', 'US')]
    [string]$Market,

    [Parameter(Mandatory, ParameterSetName = 'Quant')]
    [ValidatePattern('^manifests/(TW|US)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json$')]
    [string]$LkgManifest,

    [Parameter(Mandatory, ParameterSetName = 'Observation')]
    [string]$ObservationDeploymentReceipt,

    [string]$Bucket = 'line-stock-bot-498908-quant-snapshots',
    [string]$Project = 'line-stock-bot-498908',
    [string]$Service = 'line-stock-bot',
    [string]$Region = 'asia-east1',
    [string]$DataRoot = 'D:\AbsorbData',
    [int]$MaximumSeconds = 10
)

$ErrorActionPreference = 'Stop'
if ($Bucket -ne 'line-stock-bot-498908-quant-snapshots') { throw 'Bucket is not allowlisted' }
if ($Project -ne 'line-stock-bot-498908') { throw 'Project is not allowlisted' }
if ($Service -ne 'line-stock-bot') { throw 'Service is not allowlisted' }
if ($Region -ne 'asia-east1') { throw 'Region is not allowlisted' }
if ($DataRoot -notin @('D:\AbsorbData', 'D:\StockPapiData')) {
    throw 'Data root is not allowlisted'
}
if ($MaximumSeconds -lt 1) { throw 'MaximumSeconds must be positive' }

if ($PSCmdlet.ParameterSetName -eq 'Observation') {
    . (Join-Path $PSScriptRoot 'observation_release_common.ps1')

    function Invoke-ObservationGcloud {
        param([string[]]$Arguments)

        $GcloudPath = (Get-Command gcloud -ErrorAction Stop).Source
        $PreviousPythonPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = $null
            $Output = & $GcloudPath @Arguments 2>&1
            $ExitCode = $LASTEXITCODE
        } finally {
            $env:PYTHONPATH = $PreviousPythonPath
        }
        if ($ExitCode -ne 0) {
            throw "gcloud command failed with exit code ${ExitCode}: $($Output | Out-String)"
        }
        return ($Output | Out-String)
    }

    $ReceiptRoot = Join-Path $DataRoot 'release\observation-lkg'
    $ResolvedDeploymentReceipt = Assert-PathWithinRoot `
        -Path $ObservationDeploymentReceipt `
        -Root $ReceiptRoot
    $Deployment = Get-Content `
        -LiteralPath $ResolvedDeploymentReceipt `
        -Raw `
        -Encoding utf8 | ConvertFrom-Json
    if (
        $Deployment.schema_version -ne 1 -or
        $Deployment.kind -ne 'absorb-observation-deployment' -or
        $Deployment.project -ne $Project -or
        $Deployment.service -ne $Service -or
        $Deployment.region -ne $Region -or
        $Deployment.traffic_applied -ne $true -or
        [string]$Deployment.candidate_revision -notmatch
            '^line-stock-bot-[0-9]{5}-[a-z0-9]+$' -or
        -not ($Deployment.previous_traffic -is [array])
    ) {
        throw 'Observation deployment rollback receipt is invalid'
    }

    $CaptureRoot = Split-Path -Parent $ResolvedDeploymentReceipt
    $PreviousServicePath = Assert-PathWithinRoot `
        -Path (Join-Path $CaptureRoot ([string]$Deployment.previous_service.file)) `
        -Root $CaptureRoot
    $PreviousServiceHash = (
        Get-FileHash -LiteralPath $PreviousServicePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($PreviousServiceHash -ne [string]$Deployment.previous_service.sha256) {
        throw 'Observation previous service snapshot hash mismatch'
    }

    $LkgReceipt = Assert-PathWithinRoot `
        -Path ([string]$Deployment.observation_lkg_receipt) `
        -Root $ReceiptRoot
    $LkgHash = (
        Get-FileHash -LiteralPath $LkgReceipt -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($LkgHash -ne [string]$Deployment.observation_lkg_sha256) {
        throw 'Observation LKG receipt hash mismatch'
    }

    $PreviousTraffic = @(
        $Deployment.previous_traffic |
            ForEach-Object {
                [ordered]@{
                    revision = [string]$_.revision
                    percent = [int]$_.percent
                }
            }
    )
    if (
        $PreviousTraffic.Count -lt 1 -or
        ($PreviousTraffic | Measure-Object -Property percent -Sum).Sum -ne 100
    ) {
        throw 'Observation previous_traffic is incomplete'
    }
    $PreviousTrafficSpec = (
        $PreviousTraffic |
            ForEach-Object { "$($_.revision)=$($_.percent)" }
    ) -join ','
    if ($PreviousTrafficSpec -ne [string]$Deployment.previous_traffic_spec) {
        throw 'Observation previous_traffic specification mismatch'
    }

    $Current = Invoke-ObservationGcloud @(
        'run', 'services', 'describe', $Service,
        '--project', $Project,
        '--region', $Region,
        '--format=json'
    ) | ConvertFrom-Json
    $CandidateActive = @(
        $Current.status.traffic |
            Where-Object {
                $_.revisionName -eq [string]$Deployment.candidate_revision -and
                [int]$_.percent -eq 100
            }
    )
    if ($CandidateActive.Count -ne 1) {
        throw 'Observation candidate is not the sole active Production revision'
    }

    if (-not $PSCmdlet.ShouldProcess(
        "$Project/$Region/$Service",
        'restore previous traffic and Observation pointers'
    )) {
        return
    }

    $StartedAt = [DateTimeOffset]::UtcNow
    Invoke-ObservationGcloud @(
        'run', 'services', 'update-traffic', $Service,
        '--project', $Project,
        '--region', $Region,
        "--to-revisions=$PreviousTrafficSpec",
        '--quiet'
    ) | Out-Null
    $AfterTraffic = Invoke-ObservationGcloud @(
        'run', 'services', 'describe', $Service,
        '--project', $Project,
        '--region', $Region,
        '--format=json'
    ) | ConvertFrom-Json
    foreach ($Expected in $PreviousTraffic) {
        $Match = @(
            $AfterTraffic.status.traffic |
                Where-Object {
                    $_.revisionName -eq $Expected.revision -and
                    [int]$_.percent -eq $Expected.percent
                }
        )
        if ($Match.Count -ne 1) {
            throw "Observation Cloud Run traffic rollback verification failed: $($Expected.revision)"
        }
    }

    $PointerResult = & (Join-Path $PSScriptRoot 'rollback_observation.ps1') `
        -ReceiptPath $LkgReceipt `
        -DataRoot $DataRoot `
        -Bucket $Bucket `
        -Confirm:$false
    $ElapsedSeconds = (
        [DateTimeOffset]::UtcNow - $StartedAt
    ).TotalSeconds
    [ordered]@{
        event = 'OBSERVATION_MANUAL_ROLLBACK'
        deployment_receipt = $ResolvedDeploymentReceipt
        restored_traffic = $PreviousTraffic
        observation_lkg_receipt = $LkgReceipt
        pointer_result = $PointerResult
        elapsed_seconds = [Math]::Round($ElapsedSeconds, 3)
    } | ConvertTo-Json -Depth 8 -Compress
    return
}

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
