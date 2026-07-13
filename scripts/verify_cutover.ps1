[CmdletBinding()]
param(
    [string]$Project = 'line-stock-bot-498908',
    [string]$Bucket = 'line-stock-bot-498908-quant-snapshots',
    [string]$Service = 'line-stock-bot',
    [string]$Region = 'asia-east1',
    [string]$DataRoot = 'D:\StockPapiData',
    [string]$ReleaseEvidencePath = 'release-evidence.json',
    [double]$MinimumCoverage = 0.95,
    [double]$MinimumFreeGB = 100
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
    if ($DataRoot -ne 'D:\StockPapiData') { throw 'Data root is not allowlisted' }
    $Drive = [IO.DriveInfo]::new('D')
    if (-not $Drive.IsReady -or $Drive.AvailableFreeSpace -lt $MinimumFreeGB * 1GB) {
        throw 'D drive free space is below threshold'
    }
    $Acl = Get-Acl -LiteralPath $DataRoot
    if (-not $Acl.AreAccessRulesProtected) { throw 'Data root ACL is not protected' }
    foreach ($TaskName in @('StockPapi-LocalQuant', 'StockPapi-QuantUpload')) {
        $Task = Get-ScheduledTask -TaskName $TaskName
        if ($Task.State -eq 'Disabled') { throw "Scheduled task is disabled: $TaskName" }
    }
    return 'D drive, private ACL and scheduled tasks are ready'
}

$TemporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("stock-papi-cutover-" + [Guid]::NewGuid().ToString('N'))
try {
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
    New-Item -ItemType Directory -Path $TemporaryRoot -Force | Out-Null
    Invoke-Checked 'latest_tw' { Test-MarketPointer 'TW' $TemporaryRoot }
    Invoke-Checked 'latest_us' { Test-MarketPointer 'US' $TemporaryRoot }
    Invoke-Checked 'local_operations' { Test-LocalOperations }
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
    checked_at = [DateTimeOffset]::UtcNow.ToString('o')
    checks = $Checks
} | ConvertTo-Json -Depth 4

if (-not $Ready) { exit 2 }
