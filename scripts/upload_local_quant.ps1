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

$Global:VerifiedDirs = @{}

function Send-ReportUploadFailureNotification {
    param([string]$Message)
    $AdminUserId = 'U72f8c70881c4107fd03e506e97d3b75d'
    $OldPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $null
        $Token = (& $Gcloud secrets versions access latest `
            --secret=stock-papi-line-channel-access-token `
            --project=line-stock-bot-498908 2>$null).Trim()
        if (-not $Token) { return }
        $Headers = @{ Authorization = "Bearer $Token"; 'Content-Type' = 'application/json' }
        $Body = @{
            to = $AdminUserId
            messages = @(@{ type = 'text'; text = $Message })
        } | ConvertTo-Json -Depth 5 -Compress
        Invoke-RestMethod -Method Post -Uri 'https://api.line.me/v2/bot/message/push' `
            -Headers $Headers -Body $Body -TimeoutSec 10 | Out-Null
    } catch {
        Write-Warning 'LINE administrator notification failed'
    } finally {
        $env:PYTHONPATH = $OldPythonPath
    }
}

function Assert-AllowlistedPath {
    param([string]$Path)
    $Resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $Resolved.StartsWith($ResolvedRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw 'Upload path escaped publish root'
    }
    $Current = Get-Item -LiteralPath $Resolved
    while ($Current.FullName -ne $ResolvedRoot) {
        if ($Global:VerifiedDirs.ContainsKey($Current.FullName)) {
            break
        }
        if (($Current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Upload path contains a reparse point'
        }
        $Current = $Current.Parent
    }
    # Cache verified directories
    $Curr = Get-Item -LiteralPath $Resolved
    while ($Curr.FullName -ne $ResolvedRoot) {
        if ($Global:VerifiedDirs.ContainsKey($Curr.FullName)) { break }
        $Global:VerifiedDirs[$Curr.FullName] = $true
        $Curr = $Curr.Parent
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

    $OldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = $null
    & $Gcloud @Arguments
    $env:PYTHONPATH = $OldPythonPath

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

    $OldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = $null
    & $Gcloud @Arguments
    $env:PYTHONPATH = $OldPythonPath

    if ($LASTEXITCODE -ne 0) { throw "gcloud batch upload failed with exit code $LASTEXITCODE" }
}


try {
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
        $ValidatedObjectPaths = New-Object System.Collections.Generic.List[string]
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
            $ValidatedObjectPaths.Add($ObjectPath) | Out-Null
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

    $ReportUploaded = $false
    $ReportUploadError = $null
    $ReportPublishRoot = Join-Path $DataRoot 'publish\reports\v1'
    if (Test-Path -LiteralPath $ReportPublishRoot -PathType Container) {
        try {
            $ResolvedReportRoot = (Resolve-Path -LiteralPath $ReportPublishRoot).Path
            if (((Get-Item -LiteralPath $ResolvedReportRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Report publish root must not be a reparse point'
            }
            function Assert-ReportPath {
                param([string]$Path)
                $Resolved = (Resolve-Path -LiteralPath $Path).Path
                if (-not $Resolved.StartsWith($ResolvedReportRoot + [IO.Path]::DirectorySeparatorChar)) {
                    throw 'Report upload path escaped publish root'
                }
                $Current = Get-Item -LiteralPath $Resolved
                while ($Current.FullName -ne $ResolvedReportRoot) {
                    if (($Current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                        throw 'Report upload path contains a reparse point'
                    }
                    $Current = $Current.Parent
                }
                return $Resolved
            }

            $ReportLatestPath = Assert-ReportPath (Join-Path $ResolvedReportRoot 'latest-TW.json')
            $ReportLatest = Get-Content -LiteralPath $ReportLatestPath -Raw -Encoding utf8 | ConvertFrom-Json
            if (
                $ReportLatest.schema_version -ne 1 -or
                $ReportLatest.kind -ne 'daily-industry-report' -or
                $ReportLatest.market -ne 'TW' -or
                [string]$ReportLatest.report_date -notmatch '^\d{4}-\d{2}-\d{2}$'
            ) { throw 'Invalid report latest pointer' }
            $ReportMetadataRelative = [string]$ReportLatest.metadata
            if ($ReportMetadataRelative -notmatch '^metadata/[0-9a-f]{64}\.json$') {
                throw 'Invalid report metadata path'
            }
            $ReportMetadataPath = Assert-ReportPath (Join-Path $ResolvedReportRoot $ReportMetadataRelative)
            $ReportMetadataHash = (Get-FileHash -LiteralPath $ReportMetadataPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($ReportMetadataHash -ne [string]$ReportLatest.metadata_sha256) {
                throw 'Report metadata hash mismatch'
            }
            $ReportMetadata = Get-Content -LiteralPath $ReportMetadataPath -Raw -Encoding utf8 | ConvertFrom-Json
            $ReportPdfRelative = [string]$ReportMetadata.pdf_path
            if (
                $ReportMetadata.schema_version -ne 1 -or
                $ReportMetadata.kind -ne 'daily-industry-report' -or
                $ReportMetadata.market -ne 'TW' -or
                [string]$ReportMetadata.report_date -ne [string]$ReportLatest.report_date -or
                $ReportPdfRelative -notmatch '^objects/[0-9a-f]{64}\.pdf$' -or
                [long]$ReportMetadata.pdf_size -le 0 -or
                [long]$ReportMetadata.pdf_size -gt 15MB
            ) { throw 'Invalid report metadata' }
            $ReportPdfPath = Assert-ReportPath (Join-Path $ResolvedReportRoot $ReportPdfRelative)
            $ReportPdf = Get-Item -LiteralPath $ReportPdfPath
            if ($ReportPdf.Length -ne [long]$ReportMetadata.pdf_size) { throw 'Report PDF size mismatch' }
            if ((Get-FileHash -LiteralPath $ReportPdfPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$ReportMetadata.pdf_sha256) {
                throw 'Report PDF hash mismatch'
            }
            if ($ReportPdfRelative -ne "objects/$($ReportMetadata.pdf_sha256).pdf") {
                throw 'Report PDF content address mismatch'
            }
            $SourceManifest = [string]$ReportMetadata.source_manifest
            if ($SourceManifest -notmatch '^quant/v1/manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json$') {
                throw 'Invalid report source manifest path'
            }
            $SourceManifestRelative = $SourceManifest.Substring('quant/v1/'.Length)
            $SourceManifestPath = Assert-AllowlistedPath (Join-Path $ResolvedRoot $SourceManifestRelative)
            if ((Get-FileHash -LiteralPath $SourceManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$ReportMetadata.source_manifest_sha256) {
                throw 'Report source manifest hash mismatch'
            }
            $ReportIndexPath = Assert-ReportPath (Join-Path $ResolvedReportRoot 'index-TW.json')
            $ReportIndexFile = Get-Item -LiteralPath $ReportIndexPath
            if ($ReportIndexFile.Length -le 0 -or $ReportIndexFile.Length -gt 1MB) { throw 'Invalid report index size' }
            $ReportIndex = Get-Content -LiteralPath $ReportIndexPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($ReportIndex.schema_version -ne 1 -or $ReportIndex.market -ne 'TW') { throw 'Invalid report index' }
            $ReportIndexEntry = @($ReportIndex.reports | Where-Object {
                [string]$_.report_date -eq [string]$ReportLatest.report_date -and
                [string]$_.metadata -eq $ReportMetadataRelative -and
                [string]$_.metadata_sha256 -eq $ReportMetadataHash -and
                [string]$_.pdf_path -eq $ReportPdfRelative -and
                [string]$_.pdf_sha256 -eq [string]$ReportMetadata.pdf_sha256
            })
            if ($ReportIndexEntry.Count -ne 1) { throw 'Report index entry mismatch' }

            Invoke-GcloudCopy $ReportPdfPath "gs://$Bucket/reports/v1/$ReportPdfRelative" -NoClobber
            Invoke-GcloudCopy $ReportMetadataPath "gs://$Bucket/reports/v1/$ReportMetadataRelative" -NoClobber
            Invoke-GcloudCopy $ReportIndexPath "gs://$Bucket/reports/v1/index-TW.json"
            Invoke-GcloudCopy $ReportLatestPath "gs://$Bucket/reports/v1/latest-TW.json"
            $ReportUploaded = $true
        } catch {
            $ReportUploadError = $_.Exception.Message
            Write-Warning "日報上傳失敗：$ReportUploadError"
            Send-ReportUploadFailureNotification "日報上傳失敗：$ReportUploadError"
        }
    }

    $Status = @{
        uploaded_at = [DateTimeOffset]::Now.ToString('o')
        markets = $UploadedMarkets
        market_insights = $InsightsUploaded
        report_uploaded = $ReportUploaded
        report_error = $ReportUploadError
        bucket = $Bucket
    } | ConvertTo-Json -Compress
    Set-Content -LiteralPath (Join-Path $DataRoot 'logs\upload-status.json') -Value $Status -Encoding utf8
    Write-Output "Uploaded quant snapshots: $($UploadedMarkets -join ',')"

} catch {
    throw $_
}
