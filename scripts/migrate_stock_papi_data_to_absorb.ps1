[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [string]$SourceRoot = 'D:\StockPapiData',
    [string]$TargetRoot = 'D:\AbsorbData',
    [switch]$Copy,
    [switch]$VerifyOnly,
    [switch]$SwitchConfig,
    [switch]$Rollback,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$AllowedSource = [IO.Path]::GetFullPath('D:\StockPapiData').TrimEnd('\')
$AllowedTarget = [IO.Path]::GetFullPath('D:\AbsorbData').TrimEnd('\')
$Source = [IO.Path]::GetFullPath($SourceRoot).TrimEnd('\')
$Target = [IO.Path]::GetFullPath($TargetRoot).TrimEnd('\')

if ($Source -ne $AllowedSource -or $Target -ne $AllowedTarget) {
    throw 'Migration roots must be exactly D:\StockPapiData and D:\AbsorbData.'
}
$SelectedModes = @($Copy, $VerifyOnly, $SwitchConfig, $Rollback) | Where-Object { $_.IsPresent }
if ($SelectedModes.Count -ne 1) {
    throw 'Choose exactly one mode: -Copy, -VerifyOnly, -SwitchConfig, or -Rollback.'
}

function Assert-NoReparsePoint([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root)) { return }
    $rootItem = Get-Item -LiteralPath $Root -Force
    if ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Reparse point is not allowed: $Root"
    }
    $reparse = Get-ChildItem -LiteralPath $Root -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
        Select-Object -First 1
    if ($reparse) { throw "Reparse point is not allowed under migration root: $($reparse.FullName)" }
}

function Get-Inventory([string]$Root, [switch]$ExcludeMigrationAudit) {
    $files = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Sort-Object FullName)
    if ($ExcludeMigrationAudit) {
        $auditPath = [IO.Path]::GetFullPath((Join-Path $Root 'migration\absorb-data-migration.json'))
        $files = @($files | Where-Object { [IO.Path]::GetFullPath($_.FullName) -ne $auditPath })
    }
    $items = foreach ($file in $files) {
        $relative = [IO.Path]::GetRelativePath($Root, $file.FullName)
        [pscustomobject]@{
            RelativePath = $relative
            Length = $file.Length
            Sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        }
    }
    [pscustomobject]@{
        Files = @($items)
        Count = $files.Count
        Bytes = [long](($files | Measure-Object Length -Sum).Sum)
    }
}

function Compare-Inventory($SourceInventory, $TargetInventory) {
    if ($SourceInventory.Count -ne $TargetInventory.Count -or $SourceInventory.Bytes -ne $TargetInventory.Bytes) {
        throw 'File count or total size verification failed.'
    }
    $targetByPath = @{}
    foreach ($item in $TargetInventory.Files) { $targetByPath[$item.RelativePath] = $item }
    foreach ($item in $SourceInventory.Files) {
        $other = $targetByPath[$item.RelativePath]
        if (-not $other -or $other.Length -ne $item.Length -or $other.Sha256 -ne $item.Sha256) {
            throw "Hash verification failed: $($item.RelativePath)"
        }
    }
}

if ($Rollback) {
    if ($PSCmdlet.ShouldProcess('User environment ABSORB_DATA_ROOT', "switch back to $Source")) {
        [Environment]::SetEnvironmentVariable('ABSORB_DATA_ROOT', $Source, 'User')
    }
    return
}

if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    throw "Source root does not exist: $Source"
}
Assert-NoReparsePoint $Source

if ($Copy) {
    if (Test-Path -LiteralPath $Target) {
        Assert-NoReparsePoint $Target
        $existing = @(Get-ChildItem -LiteralPath $Target -Force)
        if ($existing.Count -gt 0) { throw 'Target root is not empty; refusing to overwrite or merge.' }
        if (-not $Force) { throw 'Existing empty target requires -Force.' }
    }
    if ($PSCmdlet.ShouldProcess($Target, "copy from $Source without deleting source")) {
        New-Item -ItemType Directory -Path $Target -Force | Out-Null
        Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Target -Recurse -Force
        Assert-NoReparsePoint $Target
        Compare-Inventory (Get-Inventory $Source) (Get-Inventory $Target)
        $auditDirectory = Join-Path $Target 'migration'
        New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
        $audit = [ordered]@{
            operation = 'copy-verify'
            source = $Source
            target = $Target
            verified_at = [DateTimeOffset]::UtcNow.ToString('o')
            source_deleted = $false
        } | ConvertTo-Json -Compress
        $tempAudit = Join-Path $auditDirectory ('audit-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        $auditPath = Join-Path $auditDirectory 'absorb-data-migration.json'
        [IO.File]::WriteAllText($tempAudit, $audit, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $tempAudit -Destination $auditPath -Force
    }
    return
}

if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    throw "Target root does not exist: $Target"
}
Assert-NoReparsePoint $Target
Compare-Inventory (Get-Inventory $Source) (Get-Inventory $Target -ExcludeMigrationAudit)

if ($SwitchConfig) {
    if ($PSCmdlet.ShouldProcess('User environment ABSORB_DATA_ROOT', "switch to verified target $Target")) {
        [Environment]::SetEnvironmentVariable('ABSORB_DATA_ROOT', $Target, 'User')
    }
} else {
    Write-Output 'VERIFY_OK: source and target file counts, sizes, and SHA-256 hashes match.'
}
