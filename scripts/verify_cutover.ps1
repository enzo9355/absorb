[CmdletBinding()]
param(
    [string]$Project = 'line-stock-bot-498908',
    [string]$Bucket = 'line-stock-bot-498908-quant-snapshots',
    [string]$Service = 'line-stock-bot',
    [string]$Region = 'asia-east1',
    [string]$DataRoot = 'D:\AbsorbData',
    [string]$ReleaseEvidencePath = 'release-evidence.json',
    [double]$MinimumCoverage = 0.95,
    [double]$MinimumFreeGB = 100,
    [switch]$ObservationOnly,
    [string]$BaseUrl
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Checks = New-Object System.Collections.Generic.List[object]
$Gcloud = Get-Command gcloud -ErrorAction SilentlyContinue
$RequiredSecrets = @(
    'stock-papi-line-channel-access-token',
    'stock-papi-line-channel-secret',
    'stock-papi-gemini-api-key',
    'stock-papi-finmind-user',
    'stock-papi-finmind-password',
    'stock-papi-alert-task-token'
)

function Add-Check {
    param([string]$Name, [bool]$Ready, [string]$Detail)

    $Checks.Add([ordered]@{
        name = $Name
        status = if ($Ready) { 'READY' } else { 'BLOCKED' }
        detail = $Detail
    }) | Out-Null
}

function Invoke-Gcloud {
    param([string[]]$Arguments)

    if (-not $Gcloud) { throw 'gcloud was not found' }
    $PreviousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $null
        $Output = & $Gcloud.Source @Arguments 2>&1
        $ExitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $PreviousPythonPath
    }
    if ($ExitCode -ne 0) { throw 'gcloud command failed' }
    return ($Output | Out-String)
}

function Invoke-Checked {
    param([string]$Name, [scriptblock]$Action)

    try {
        $Detail = & $Action
        Add-Check $Name $true ([string]$Detail)
    } catch {
        Add-Check $Name $false $_.Exception.GetType().Name
    }
}

function Get-JsonFile {
    param([string]$Path)

    $Document = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
    if ($null -eq $Document) { throw 'JSON object is empty' }
    return $Document
}

function Test-ReleaseEvidence {
    $EvidencePath = Join-Path $RepoRoot $ReleaseEvidencePath
    $Evidence = Get-JsonFile $EvidencePath
    if ($Evidence.schema_version -ne 1 -or $Evidence.quality_gate -ne 'PASS') {
        throw 'Quality Gate evidence is not PASS'
    }
    if ($null -eq $Evidence.source_hashes -or $Evidence.source_hashes.PSObject.Properties.Count -lt 1) {
        throw 'Quality Gate evidence has no source hashes'
    }
    foreach ($Property in $Evidence.source_hashes.PSObject.Properties) {
        $RelativePath = [string]$Property.Name
        $ExpectedHash = [string]$Property.Value
        if ($RelativePath -notmatch '^[A-Za-z0-9._/-]+$' -or $ExpectedHash -notmatch '^[0-9a-f]{64}$') {
            throw 'Release evidence contains an invalid hash target'
        }
        $Candidate = (Join-Path $RepoRoot $RelativePath).Replace('/', [IO.Path]::DirectorySeparatorChar)
        $Resolved = (Resolve-Path -LiteralPath $Candidate).Path
        if (-not $Resolved.StartsWith($RepoRoot + [IO.Path]::DirectorySeparatorChar)) {
            throw 'Release evidence path escaped repository root'
        }
        if ((Get-FileHash -LiteralPath $Resolved -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
            throw "Release hash mismatch: $RelativePath"
        }
    }
    return 'Quality Gate PASS evidence and source hashes match'
}

function Get-CloudRunService {
    return Invoke-Gcloud @(
        'run', 'services', 'describe', $Service,
        '--region', $Region,
        '--project', $Project,
        '--format=json'
    ) | ConvertFrom-Json
}

function Test-BucketSecurity {
    $BucketInfo = Invoke-Gcloud @('storage', 'buckets', 'describe', "gs://$Bucket", '--format=json') |
        ConvertFrom-Json
    if ($BucketInfo.iamConfiguration.uniformBucketLevelAccess.enabled -ne $true) {
        throw 'Uniform bucket-level access is disabled'
    }
    if ([string]$BucketInfo.iamConfiguration.publicAccessPrevention -ne 'enforced') {
        throw 'Public access prevention is not enforced'
    }
    if (@($BucketInfo.lifecycle.rule).Count -lt 1) {
        throw 'Lifecycle rule is missing'
    }
    return 'Bucket is private with uniform access, public access prevention and lifecycle'
}

function Test-CloudRunIdentity {
    $ServiceInfo = Get-CloudRunService
    $ServiceAccount = [string]$ServiceInfo.spec.template.spec.serviceAccountName
    if (-not $ServiceAccount) { $ServiceAccount = [string]$ServiceInfo.template.serviceAccount }
    if (-not $ServiceAccount) { throw 'Cloud Run service account is missing' }
    if (-not $ServiceInfo.status.latestReadyRevisionName) { throw 'Cloud Run has no ready revision' }
    return $ServiceAccount
}

function Test-ServiceAccountAccess {
    param([string]$ServiceAccount)

    $Member = "serviceAccount:$ServiceAccount"
    $BucketPolicy = Invoke-Gcloud @('storage', 'buckets', 'get-iam-policy', "gs://$Bucket", '--format=json') |
        ConvertFrom-Json
    $ViewerBinding = @($BucketPolicy.bindings | Where-Object {
        $_.role -eq 'roles/storage.objectViewer' -and $_.members -contains $Member
    })
    $WriterBinding = @($BucketPolicy.bindings | Where-Object {
        $_.role -in @('roles/storage.objectAdmin', 'roles/storage.objectUser', 'roles/storage.admin') -and
        $_.members -contains $Member
    })
    if ($ViewerBinding.Count -ne 1 -or $WriterBinding.Count -ne 0) {
        throw 'Cloud Run storage IAM is not least privilege'
    }

    $ProjectPolicy = Invoke-Gcloud @('projects', 'get-iam-policy', $Project, '--format=json') | ConvertFrom-Json
    $SecretBinding = @($ProjectPolicy.bindings | Where-Object {
        $_.role -eq 'roles/secretmanager.secretAccessor' -and $_.members -contains $Member
    })
    if ($SecretBinding.Count -lt 1) {
        foreach ($Secret in $RequiredSecrets) {
            $SecretPolicy = Invoke-Gcloud @(
                'secrets', 'get-iam-policy', $Secret, '--project', $Project, '--format=json'
            ) | ConvertFrom-Json
            $SecretAccess = @($SecretPolicy.bindings | Where-Object {
                $_.role -eq 'roles/secretmanager.secretAccessor' -and $_.members -contains $Member
            })
            if ($SecretAccess.Count -lt 1) {
                throw 'Cloud Run Secret Manager access is missing'
            }
        }
    }
    return 'Cloud Run has viewer-only GCS and Secret Manager accessor roles'
}

function Test-RequiredSecrets {
    foreach ($Secret in $RequiredSecrets) {
        Invoke-Gcloud @('secrets', 'describe', $Secret, '--project', $Project, '--format=json') | Out-Null
    }
    return 'Required Secret Manager names exist without reading values'
}

function Test-MarketPointer {
    param([string]$Market, [string]$TemporaryRoot)

    $LatestUri = "gs://$Bucket/quant/v1/latest-$Market.json"
    $LatestMetadata = Invoke-Gcloud @('storage', 'objects', 'describe', $LatestUri, '--format=json') |
        ConvertFrom-Json
    if ([string]$LatestMetadata.generation -notmatch '^\d+$') { throw 'Latest pointer has no GCS generation' }

    $LatestPath = Join-Path $TemporaryRoot "latest-$Market.json"
    Invoke-Gcloud @('storage', 'cp', '--quiet', $LatestUri, $LatestPath) | Out-Null
    $Latest = Get-JsonFile $LatestPath
    if ($Latest.schema_version -ne 2 -or $Latest.market -ne $Market) {
        throw 'Latest pointer schema or market is invalid'
    }
    if ([string]$Latest.manifest -notmatch "^manifests/$Market-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json$") {
        throw 'Latest manifest path is invalid'
    }
    if ([string]$Latest.manifest_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Latest manifest hash is invalid'
    }

    $ManifestPath = Join-Path $TemporaryRoot "manifest-$Market.json"
    Invoke-Gcloud @('storage', 'cp', '--quiet', "gs://$Bucket/quant/v1/$($Latest.manifest)", $ManifestPath) | Out-Null
    if ((Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Latest.manifest_sha256) {
        throw 'Manifest SHA-256 mismatch'
    }
    $Manifest = Get-JsonFile $ManifestPath
    if ($Manifest.schema_version -ne 2 -or $Manifest.market -ne $Market) {
        throw 'Manifest schema or market is invalid'
    }
    if ([double]$Manifest.coverage -lt $MinimumCoverage) {
        throw 'Manifest coverage is below cutover threshold'
    }
    return "$Market latest pointer and manifest are verified"
}

function Test-LocalOperations {
    if ($DataRoot -notin @('D:\AbsorbData', 'D:\StockPapiData')) { throw 'Data root is not allowlisted' }
    $Drive = [IO.DriveInfo]::new('D')
    if (-not $Drive.IsReady -or $Drive.AvailableFreeSpace -lt $MinimumFreeGB * 1GB) {
        throw 'D drive free space is below threshold'
    }
    $Acl = Get-Acl -LiteralPath $DataRoot
    if (-not $Acl.AreAccessRulesProtected) { throw 'Data root ACL is not protected' }
    $TaskNames = if ($DataRoot -eq 'D:\AbsorbData') {
        @('ABSORB-LocalQuant', 'ABSORB-QuantUpload')
    } else {
        @('StockPapi-LocalQuant', 'StockPapi-QuantUpload')
    }
    foreach ($TaskName in $TaskNames) {
        $Task = Get-ScheduledTask -TaskName $TaskName
        if ($Task.State -eq 'Disabled') { throw "Scheduled task is disabled: $TaskName" }
    }
    return 'D drive, private ACL and scheduled tasks are ready'
}

$ObservationForbiddenKeys = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($Key in @(
    'forecast_probability',
    'probability',
    'ranking_score',
    'model_version',
    'backtest_version',
    'recommendation'
)) {
    $ObservationForbiddenKeys.Add($Key) | Out-Null
}

function Assert-ObservationNoPredictionKeys {
    param(
        [object]$Value,
        [string]$Path = '$'
    )

    if ($null -eq $Value) { return }
    if ($Value -is [Collections.IDictionary]) {
        foreach ($Key in $Value.Keys) {
            if ($ObservationForbiddenKeys.Contains([string]$Key)) {
                throw "Prediction key is forbidden at ${Path}: $Key"
            }
            Assert-ObservationNoPredictionKeys `
                -Value $Value[$Key] `
                -Path "$Path.$Key"
        }
        return
    }
    if ($Value -is [Management.Automation.PSCustomObject]) {
        foreach ($Property in $Value.PSObject.Properties) {
            if ($ObservationForbiddenKeys.Contains([string]$Property.Name)) {
                throw "Prediction key is forbidden at ${Path}: $($Property.Name)"
            }
            Assert-ObservationNoPredictionKeys `
                -Value $Property.Value `
                -Path "$Path.$($Property.Name)"
        }
        return
    }
    if ($Value -is [Collections.IEnumerable] -and $Value -isnot [string]) {
        $Index = 0
        foreach ($Item in $Value) {
            Assert-ObservationNoPredictionKeys `
                -Value $Item `
                -Path "$Path[$Index]"
            $Index += 1
        }
    }
}

function Get-ObservationEnvironment {
    param([object]$ServiceInfo)

    $Environment = @{}
    foreach ($Entry in @($ServiceInfo.spec.template.spec.containers[0].env)) {
        if ($Entry.name -and $null -ne $Entry.value) {
            $Environment[[string]$Entry.name] = [string]$Entry.value
        }
    }
    return $Environment
}

function Test-ObservationCloudRunEnvironment {
    $ServiceInfo = Get-CloudRunService
    $Environment = Get-ObservationEnvironment $ServiceInfo
    $Expected = [ordered]@{
        ABSORB_PREDICTION_MODE = 'research'
        ABSORB_OBSERVATION_ENABLED = 'true'
        ABSORB_PREDICTION_PROBABILITY_ENABLED = 'false'
        ABSORB_PREDICTION_RANKING_ENABLED = 'false'
        ABSORB_PREDICTION_STRONG_ACTIONS_ENABLED = 'false'
        ABSORB_PREDICTION_PERFORMANCE_ENDORSEMENT_ENABLED = 'false'
    }
    foreach ($Property in $Expected.GetEnumerator()) {
        if (
            -not $Environment.ContainsKey($Property.Key) -or
            $Environment[$Property.Key] -ne $Property.Value
        ) {
            throw "Observation Cloud Run environment mismatch: $($Property.Key)"
        }
    }
    foreach ($Name in @(
        'ABSORB_PREVIEW_CANDIDATE_PREFIX',
        'PREVIEW_CANDIDATE_PREFIX'
    )) {
        if ($Environment.ContainsKey($Name)) {
            throw "Preview prefix remains in Observation Production: $Name"
        }
    }
    return 'Observation mode is research, all Prediction flags are false, and preview prefix is absent'
}

function Get-GcsJsonEvidence {
    param(
        [string]$Uri,
        [string]$TemporaryRoot,
        [string]$Name
    )

    $Metadata = Invoke-Gcloud @(
        'storage', 'objects', 'describe', $Uri, '--format=json'
    ) | ConvertFrom-Json
    if ([string]$Metadata.generation -notmatch '^\d+$') {
        throw "GCS object has no generation: $Uri"
    }
    $Path = Join-Path $TemporaryRoot $Name
    Invoke-Gcloud @('storage', 'cp', '--quiet', $Uri, $Path) | Out-Null
    $File = Get-Item -LiteralPath $Path
    if ($File.Length -le 0) { throw "GCS object is empty: $Uri" }
    $Document = Get-JsonFile $Path
    return [pscustomobject]@{
        metadata = $Metadata
        path = $Path
        file = $File
        document = $Document
    }
}

function Assert-ObservationCapability {
    param([object]$Capability)

    if (
        $Capability.mode -ne 'research' -or
        $Capability.observation_enabled -ne $true -or
        $Capability.probability_allowed -ne $false -or
        $Capability.ranking_allowed -ne $false -or
        $Capability.strong_action_allowed -ne $false -or
        $Capability.performance_endorsement_allowed -ne $false
    ) {
        throw 'Observation prediction capability is not fail-closed'
    }
}

function Test-ObservationDashboardPointer {
    param([string]$TemporaryRoot)

    $LatestUri = "gs://$Bucket/dashboard/v1/latest-TW.json"
    $LatestEvidence = Get-GcsJsonEvidence `
        -Uri $LatestUri `
        -TemporaryRoot $TemporaryRoot `
        -Name 'observation-dashboard-latest.json'
    $Latest = $LatestEvidence.document
    if (
        $Latest.schema_version -ne 2 -or
        $Latest.kind -ne 'absorb-observation-dashboard' -or
        $Latest.product_mode -ne 'observation' -or
        $Latest.market -ne 'TW' -or
        [string]$Latest.path -notmatch '^objects/[0-9a-f]{64}\.json$' -or
        [string]$Latest.sha256 -notmatch '^[0-9a-f]{64}$' -or
        [long]$Latest.size -le 0
    ) {
        throw 'Observation dashboard latest pointer is invalid'
    }

    $ObjectEvidence = Get-GcsJsonEvidence `
        -Uri "gs://$Bucket/dashboard/v1/$($Latest.path)" `
        -TemporaryRoot $TemporaryRoot `
        -Name 'observation-dashboard-object.json'
    $Digest = (
        Get-FileHash -LiteralPath $ObjectEvidence.path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $ObjectEvidence.file.Length -ne [long]$Latest.size -or
        $Digest -ne [string]$Latest.sha256 -or
        [string]$Latest.path -ne "objects/$Digest.json"
    ) {
        throw 'Observation dashboard immutable object hash or size mismatch'
    }
    $Dashboard = $ObjectEvidence.document
    if (
        $Dashboard.schema_version -ne 2 -or
        $Dashboard.kind -ne 'absorb-observation-dashboard' -or
        $Dashboard.product_mode -ne 'observation' -or
        $Dashboard.market -ne 'TW' -or
        [string]$Dashboard.observation_as_of -ne [string]$Latest.observation_as_of
    ) {
        throw 'Observation dashboard immutable object schema mismatch'
    }
    Assert-ObservationCapability $Dashboard.prediction_capability
    Assert-ObservationNoPredictionKeys $Dashboard

    $SourceManifest = [string]$Dashboard.source_manifest
    if (
        $SourceManifest -notmatch
        '^quant/v1/manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json$' -or
        [string]$Dashboard.source_manifest_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw 'Observation dashboard source manifest identity is invalid'
    }
    $SourceEvidence = Get-GcsJsonEvidence `
        -Uri "gs://$Bucket/$SourceManifest" `
        -TemporaryRoot $TemporaryRoot `
        -Name 'observation-source-manifest.json'
    $SourceHash = (
        Get-FileHash -LiteralPath $SourceEvidence.path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $SourceHash -ne [string]$Dashboard.source_manifest_sha256 -or
        [double]$SourceEvidence.document.coverage -lt $MinimumCoverage -or
        $SourceEvidence.document.sample_data -eq $true
    ) {
        throw 'Observation dashboard source manifest failed coverage, sample, or hash Gate'
    }
    return "dashboard/v1/latest-TW.json generation $($LatestEvidence.metadata.generation) and immutable object are verified"
}

function Test-ObservationReportPointers {
    param([string]$TemporaryRoot)

    $IndexEvidence = Get-GcsJsonEvidence `
        -Uri "gs://$Bucket/reports/v2/index-TW.json" `
        -TemporaryRoot $TemporaryRoot `
        -Name 'observation-reports-index.json'
    $LatestEvidence = Get-GcsJsonEvidence `
        -Uri "gs://$Bucket/reports/v2/latest-TW-post_close.json" `
        -TemporaryRoot $TemporaryRoot `
        -Name 'observation-report-latest.json'
    $Index = $IndexEvidence.document
    $Latest = $LatestEvidence.document
    if (
        $Index.schema_version -ne 2 -or
        $Index.kind -ne 'absorb-report-index' -or
        $Index.market -ne 'TW' -or
        $Latest.schema_version -ne 2 -or
        $Latest.kind -ne 'absorb-report' -or
        $Latest.product_mode -ne 'observation' -or
        $Latest.report_type -ne 'post_close' -or
        [string]$Latest.metadata -notmatch '^metadata/[0-9a-f]{64}\.json$' -or
        [string]$Latest.metadata_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw 'Observation report index or latest pointer is invalid'
    }
    $Matches = @(
        $Index.reports |
            Where-Object {
                $_.report_type -eq 'post_close' -and
                $_.product_mode -eq 'observation' -and
                $_.metadata -eq $Latest.metadata -and
                $_.metadata_sha256 -eq $Latest.metadata_sha256
            }
    )
    if ($Matches.Count -ne 1) {
        throw 'Observation report latest pointer is not bound to exactly one index entry'
    }
    if (@($Matches[0].model_versions.PSObject.Properties).Count -ne 0) {
        throw 'Observation report index contains model versions'
    }

    $MetadataEvidence = Get-GcsJsonEvidence `
        -Uri "gs://$Bucket/reports/v2/$($Latest.metadata)" `
        -TemporaryRoot $TemporaryRoot `
        -Name 'observation-report-metadata.json'
    $MetadataHash = (
        Get-FileHash -LiteralPath $MetadataEvidence.path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $Metadata = $MetadataEvidence.document
    if (
        $MetadataHash -ne [string]$Latest.metadata_sha256 -or
        $Metadata.schema_version -ne 2 -or
        $Metadata.product_mode -ne 'observation' -or
        $Metadata.report_type -ne 'post_close' -or
        @($Metadata.model_versions.PSObject.Properties).Count -ne 0
    ) {
        throw 'Observation report immutable metadata failed hash or schema Gate'
    }
    Assert-ObservationCapability $Metadata.prediction_capability
    Assert-ObservationNoPredictionKeys $Metadata
    return "reports/v2/index-TW.json generation $($IndexEvidence.metadata.generation) and post-close latest generation $($LatestEvidence.metadata.generation) are verified"
}

function Test-ObservationHttp {
    $ServiceInfo = Get-CloudRunService
    $Target = if ($BaseUrl) { $BaseUrl } else { [string]$ServiceInfo.status.url }
    if (-not $Target) { throw 'Observation HTTP base URL is unavailable' }
    foreach ($Path in @(
        '/health',
        '/',
        '/api/dashboard',
        '/reports',
        '/market-map',
        '/stock/2330'
    )) {
        $Response = Invoke-WebRequest `
            -Uri ($Target.TrimEnd('/') + $Path) `
            -UseBasicParsing `
            -MaximumRedirection 5 `
            -TimeoutSec 45
        if ([int]$Response.StatusCode -ne 200) {
            throw "Observation HTTP smoke failed for ${Path}: $($Response.StatusCode)"
        }
        if ($Path -eq '/api/dashboard') {
            try {
                $Document = $Response.Content | ConvertFrom-Json
            } catch {
                throw 'Observation dashboard API did not return valid JSON'
            }
            if (
                $Document.product_mode -ne 'observation' -or
                $null -eq $Document.market_observation -or
                $null -eq $Document.industry_observations -or
                $null -eq $Document.data_quality
            ) {
                throw 'Observation dashboard API schema is invalid'
            }
            Assert-ObservationNoPredictionKeys $Document
        }
    }
    return "Observation HTTP smoke passed at $Target"
}

$TemporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("absorb-cutover-" + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $TemporaryRoot -Force | Out-Null
    if ($ObservationOnly) {
        Invoke-Checked 'gcloud_available' {
            if (-not $Gcloud) { throw 'gcloud was not found' }
            return 'gcloud is available'
        }
        Invoke-Checked 'gcs_bucket_security' { Test-BucketSecurity }

        $ServiceAccount = $null
        try {
            $ServiceAccount = Test-CloudRunIdentity
            Add-Check 'cloud_run_revision' $true 'Cloud Run has a ready revision and service account'
        } catch {
            Add-Check 'cloud_run_revision' $false $_.Exception.GetType().Name
        }
        if ($ServiceAccount) {
            Invoke-Checked 'cloud_run_iam' { Test-ServiceAccountAccess $ServiceAccount }
        } else {
            Add-Check 'cloud_run_iam' $false 'Service account unavailable'
        }
        Invoke-Checked 'secret_manager_names' { Test-RequiredSecrets }
        Invoke-Checked 'observation_environment' {
            Test-ObservationCloudRunEnvironment
        }
        Invoke-Checked 'observation_dashboard' {
            Test-ObservationDashboardPointer $TemporaryRoot
        }
        Invoke-Checked 'observation_reports' {
            Test-ObservationReportPointers $TemporaryRoot
        }
        Invoke-Checked 'observation_http' { Test-ObservationHttp }
    } else {
        Invoke-Checked 'release_evidence' { Test-ReleaseEvidence }
        Invoke-Checked 'gcloud_available' {
            if (-not $Gcloud) { throw 'gcloud was not found' }
            return 'gcloud is available'
        }
        Invoke-Checked 'gcs_bucket_security' { Test-BucketSecurity }

        $ServiceAccount = $null
        try {
            $ServiceAccount = Test-CloudRunIdentity
            Add-Check 'cloud_run_revision' $true 'Cloud Run has a ready revision and service account'
        } catch {
            Add-Check 'cloud_run_revision' $false $_.Exception.GetType().Name
        }
        if ($ServiceAccount) {
            Invoke-Checked 'cloud_run_iam' { Test-ServiceAccountAccess $ServiceAccount }
        } else {
            Add-Check 'cloud_run_iam' $false 'Service account unavailable'
        }

        Invoke-Checked 'secret_manager_names' { Test-RequiredSecrets }
        Invoke-Checked 'latest_tw' { Test-MarketPointer 'TW' $TemporaryRoot }
        Invoke-Checked 'latest_us' { Test-MarketPointer 'US' $TemporaryRoot }
        Invoke-Checked 'local_operations' { Test-LocalOperations }
    }
} finally {
    if (Test-Path -LiteralPath $TemporaryRoot) {
        $ResolvedTemp = (Resolve-Path -LiteralPath $TemporaryRoot).Path
        $SystemTemp = [IO.Path]::GetTempPath().TrimEnd([IO.Path]::DirectorySeparatorChar)
        if ($ResolvedTemp.StartsWith($SystemTemp + [IO.Path]::DirectorySeparatorChar)) {
            Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
        }
    }
}

$Ready = @($Checks | Where-Object { $_.status -eq 'BLOCKED' }).Count -eq 0
[ordered]@{
    overall = if ($Ready) { 'READY' } else { 'BLOCKED' }
    mode = if ($ObservationOnly) { 'observation' } else { 'prediction' }
    checked_at = [DateTimeOffset]::UtcNow.ToString('o')
    checks = $Checks
} | ConvertTo-Json -Depth 4

if (-not $Ready) { exit 2 }
