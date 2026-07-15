[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [ValidateSet('Inventory', 'InstallShadow', 'Cutover', 'Rollback')]
    [string]$Mode = 'Inventory',
    [string]$SourceRoot = 'D:\StockPapiData',
    [string]$TargetRoot = 'D:\AbsorbData',
    [switch]$ConfirmCutover
)

$ErrorActionPreference = 'Stop'
if ([IO.Path]::GetFullPath($SourceRoot).TrimEnd('\') -ne 'D:\StockPapiData' -or
    [IO.Path]::GetFullPath($TargetRoot).TrimEnd('\') -ne 'D:\AbsorbData') {
    throw 'Task migration roots must be exactly D:\StockPapiData and D:\AbsorbData.'
}

$Mappings = [ordered]@{
    'StockPapi-LocalQuant' = 'ABSORB-LocalQuant'
    'StockPapi-QuantUpload' = 'ABSORB-QuantUpload'
    'StockPapi-TW-PostClose' = 'ABSORB-TW-PostClose'
    'StockPapi-TW-PreMarket' = 'ABSORB-TW-PreMarket'
    'StockPapi-FullBacktest' = 'ABSORB-FullBacktest'
    'StockPapi-US-Daily' = 'ABSORB-US-Daily'
    'StockPapi-WeeklyModel' = 'ABSORB-WeeklyModel'
    'StockPapi-ReportUploadRecovery' = 'ABSORB-ReportUploadRecovery'
}

function Get-TaskOrNull([string]$Name) {
    Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
}

function Assert-TaskDefinition([string]$Name, [string]$ExpectedRoot, $SourceTask) {
    $task = Get-TaskOrNull $Name
    if (-not $task) { throw "Task not found after registration: $Name" }
    if ($task.Principal.RunLevel -ne 'Limited') { throw "Task is not Limited: $Name" }
    if ($task.Settings.MultipleInstances -ne 'IgnoreNew') { throw "Task is not IgnoreNew: $Name" }
    if ($task.Settings.RestartCount -lt 1) { throw "Task retry is missing: $Name" }
    if (-not $SourceTask) { throw "Source task definition is missing: $Name" }
    if ($task.Settings.StartWhenAvailable -ne $SourceTask.Settings.StartWhenAvailable) {
        throw "Task StartWhenAvailable changed: $Name"
    }
    if ($task.Settings.WakeToRun -ne $SourceTask.Settings.WakeToRun) {
        throw "Task WakeToRun changed: $Name"
    }
    if ($task.Settings.RestartCount -ne $SourceTask.Settings.RestartCount -or
        $task.Settings.RestartInterval -ne $SourceTask.Settings.RestartInterval) {
        throw "Task retry policy changed: $Name"
    }
    if ($task.Principal.UserId -ne $SourceTask.Principal.UserId) {
        throw "Task principal changed: $Name"
    }
    $actions = @($task.Actions)
    $sourceActions = @($SourceTask.Actions)
    if ($actions.Count -ne 1 -or [string]::IsNullOrWhiteSpace($actions[0].Execute)) {
        throw "Task action is invalid: $Name"
    }
    if ($sourceActions.Count -ne 1) { throw "Source task action is invalid: $Name" }
    $expectedExecute = [string]$sourceActions[0].Execute
    $expectedArguments = ([string]$sourceActions[0].Arguments).Replace($SourceRoot, $TargetRoot)
    $expectedWorkingDirectory = ([string]$sourceActions[0].WorkingDirectory).Replace($SourceRoot, $TargetRoot)
    if ([string]$actions[0].Execute -ne $expectedExecute -or
        [string]$actions[0].Arguments -ne $expectedArguments -or
        [string]$actions[0].WorkingDirectory -ne $expectedWorkingDirectory) {
        throw "Task action or working directory changed unexpectedly: $Name"
    }
    $joined = "$($actions[0].Execute) $($actions[0].Arguments) $($actions[0].WorkingDirectory)"
    if ($joined -notlike "*$ExpectedRoot*") { throw "Task does not reference expected data root: $Name" }
}

if ($Mode -eq 'Inventory') {
    foreach ($oldName in $Mappings.Keys) {
        $old = Get-TaskOrNull $oldName
        $new = Get-TaskOrNull $Mappings[$oldName]
        [pscustomobject]@{
            OldTask = $oldName
            OldState = if ($old) { $old.State } else { 'Missing' }
            NewTask = $Mappings[$oldName]
            NewState = if ($new) { $new.State } else { 'Missing' }
        }
    }
    return
}

if ($Mode -eq 'InstallShadow') {
    foreach ($oldName in $Mappings.Keys) {
        $old = Get-TaskOrNull $oldName
        if (-not $old) { Write-Warning "Skipping missing source task: $oldName"; continue }
        $newName = $Mappings[$oldName]
        if (Get-TaskOrNull $newName) { throw "Target task already exists: $newName" }
        $xml = Export-ScheduledTask -TaskName $oldName
        $xml = $xml.Replace($SourceRoot, $TargetRoot).Replace($oldName, $newName)
        if ($PSCmdlet.ShouldProcess($newName, 'register disabled ABSORB shadow task')) {
            Register-ScheduledTask -TaskName $newName -Xml $xml | Out-Null
            Disable-ScheduledTask -TaskName $newName | Out-Null
            Assert-TaskDefinition $newName $TargetRoot $old
        }
    }
    return
}

if ($Mode -eq 'Cutover' -and -not $ConfirmCutover) {
    throw 'Cutover requires -ConfirmCutover and still honors -WhatIf.'
}

$Pairs = @()
foreach ($oldName in $Mappings.Keys) {
    $newName = $Mappings[$oldName]
    $old = Get-TaskOrNull $oldName
    $new = Get-TaskOrNull $newName
    if (-not $old -and -not $new) { continue }
    if (-not $old -or -not $new) { throw "Incomplete task pair: $oldName / $newName" }
    Assert-TaskDefinition $newName $TargetRoot $old
    $Pairs += [pscustomobject]@{ OldName = $oldName; NewName = $newName }
}
if ($Pairs.Count -eq 0) { throw 'No complete task pairs are available for migration.' }

foreach ($pair in $Pairs) {
    $oldName = $pair.OldName
    $newName = $pair.NewName
    if ($Mode -eq 'Cutover') {
        if ($PSCmdlet.ShouldProcess("$oldName -> $newName", 'enable new task and disable old task')) {
            Enable-ScheduledTask -TaskName $newName | Out-Null
            Disable-ScheduledTask -TaskName $oldName | Out-Null
        }
    } elseif ($Mode -eq 'Rollback') {
        if ($PSCmdlet.ShouldProcess("$newName -> $oldName", 'disable new task and re-enable old task')) {
            Disable-ScheduledTask -TaskName $newName | Out-Null
            Enable-ScheduledTask -TaskName $oldName | Out-Null
        }
    }
}

# Old tasks are deliberately never deleted. Remove them only after a separate manual approval.
