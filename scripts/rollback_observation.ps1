[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][string]$ReceiptPath,
    [string]$DataRoot = 'D:\AbsorbData',
    [string]$Bucket = 'line-stock-bot-498908-quant-snapshots'
)

$ErrorActionPreference = 'Stop'
if ($DataRoot -notin @('D:\AbsorbData', 'D:\StockPapiData')) {
    throw 'Data root is not allowlisted'
}
if ($Bucket -ne 'line-stock-bot-498908-quant-snapshots') {
    throw 'Bucket is not allowlisted'
}
. (Join-Path $PSScriptRoot 'observation_release_common.ps1')

$Gcloud = (Get-Command gcloud -ErrorAction Stop).Source
$ReceiptRoot = Join-Path $DataRoot 'release\observation-lkg'
$ResolvedReceipt = Assert-PathWithinRoot `
    -Path $ReceiptPath `
    -Root $ReceiptRoot
$Receipt = Get-Content -LiteralPath $ResolvedReceipt -Raw -Encoding utf8 |
    ConvertFrom-Json
if (
    $Receipt.schema_version -ne 1 -or
    $Receipt.kind -ne 'absorb-observation-lkg' -or
    $Receipt.bucket -ne $Bucket -or
    -not ($Receipt.pointers -is [array])
) {
    throw 'Observation rollback receipt is invalid'
}
$CaptureRoot = Split-Path -Parent $ResolvedReceipt
$Results = New-Object System.Collections.Generic.List[object]

foreach ($Pointer in $Receipt.pointers) {
    $Uri = [string]$Pointer.uri
    $AppliedGeneration = [string]$Pointer.applied_generation
    if (-not $AppliedGeneration) { continue }
    if ($AppliedGeneration -notmatch '^\d+$' -or $AppliedGeneration -eq '0') {
        throw 'Observation rollback applied_generation is invalid'
    }
    $Current = Get-GcloudObjectState -Gcloud $Gcloud -Uri $Uri
    if (
        -not $Current.exists -or
        [string]$Current.generation -ne $AppliedGeneration
    ) {
        throw "Observation rollback generation mismatch: $Uri"
    }

    if (-not $PSCmdlet.ShouldProcess($Uri, 'restore Observation LKG pointer')) {
        continue
    }
    if ($Pointer.exists) {
        $PreviousPath = Assert-PathWithinRoot `
            -Path (Join-Path $CaptureRoot ([string]$Pointer.previous_file)) `
            -Root $CaptureRoot
        $Previous = Get-Item -LiteralPath $PreviousPath
        $PreviousHash = (
            Get-FileHash -LiteralPath $PreviousPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if (
            $Previous.Length -ne [long]$Pointer.previous_size -or
            $PreviousHash -ne [string]$Pointer.previous_sha256
        ) {
            throw "Observation previous_sha256 validation failed: $Uri"
        }
        Invoke-GcloudConditionalCopy `
            -Gcloud $Gcloud `
            -Source $PreviousPath `
            -Destination $Uri `
            -ExpectedGeneration $AppliedGeneration | Out-Null
        Assert-GcloudFileMatches `
            -Gcloud $Gcloud `
            -LocalPath $PreviousPath `
            -Uri $Uri
        $Results.Add([ordered]@{
            uri = $Uri
            action = 'restored'
            previous_sha256 = $PreviousHash
        }) | Out-Null
    } else {
        Invoke-GcloudConditionalDelete `
            -Gcloud $Gcloud `
            -Uri $Uri `
            -ExpectedGeneration $AppliedGeneration
        $After = Get-GcloudObjectState -Gcloud $Gcloud -Uri $Uri
        if ($After.exists) {
            throw "Observation rollback verification failed: $Uri"
        }
        $Results.Add([ordered]@{
            uri = $Uri
            action = 'deleted_new_pointer'
            previous_sha256 = $null
        }) | Out-Null
    }
}

if ($Results.Count -eq 0 -and $PSCmdlet.ShouldProcess('Observation pointers', 'verify rollback receipt')) {
    throw 'Observation rollback receipt has no applied pointers'
}
[ordered]@{
    schema_version = 1
    kind = 'absorb-observation-rollback'
    rolled_back_at = [DateTimeOffset]::UtcNow.ToString('o')
    receipt = $ResolvedReceipt
    results = $Results.ToArray()
} | ConvertTo-Json -Depth 6 -Compress
