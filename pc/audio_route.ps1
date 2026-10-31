param(
    [ValidateSet('status', 'enable', 'disable')][string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

# AudioDeviceCmdlets is installed for the current user. Windows PowerShell 5.1 does
# not search PowerShell 7's module directory, so locate it explicitly if needed.
$module = Get-Module -ListAvailable AudioDeviceCmdlets |
    Sort-Object Version -Descending | Select-Object -First 1
if (-not $module) {
    $moduleRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\Modules\AudioDeviceCmdlets'
    $manifest = Get-ChildItem -LiteralPath $moduleRoot -Filter AudioDeviceCmdlets.psd1 -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $manifest) { throw 'AudioDeviceCmdlets is missing. Run Install-Module AudioDeviceCmdlets -Scope CurrentUser.' }
    Import-Module -Name $manifest.FullName -ErrorAction Stop
} else {
    Import-Module -Name $module.Path -ErrorAction Stop
}

$stateFile = Join-Path $PSScriptRoot 'logs\previous-input.json'
$recording = @(Get-AudioDevice -List | Where-Object Type -eq 'Recording')
$cable = $recording | Where-Object { $_.Name -like 'CABLE Output*' } | Select-Object -First 1
if (-not $cable) { throw 'VB-CABLE recording endpoint CABLE Output was not found.' }
$fallback = $recording | Where-Object { $_.ID -ne $cable.ID } |
    Sort-Object @{ Expression = { if ($_.Name -match 'microphone|mic') { 0 } else { 1 } } } |
    Select-Object -First 1

function Defaults {
    return @{
        default = Get-AudioDevice -Recording
        communication = Get-AudioDevice -RecordingCommunication
    }
}

function Previous {
    if (Test-Path -LiteralPath $stateFile) {
        return Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    }
    return $null
}

if ($Action -eq 'enable') {
    if (-not $fallback) { throw 'No other recording endpoint is available for restoration.' }
    $before = Defaults
    $saved = Previous
    $previousDefault = if ($before.default.ID -ne $cable.ID) { $before.default.ID } elseif ($saved) { $saved.default } else { $fallback.ID }
    $previousCommunication = if ($before.communication.ID -ne $cable.ID) { $before.communication.ID } elseif ($saved) { $saved.communication } else { $fallback.ID }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stateFile) | Out-Null
    @{ default = $previousDefault; communication = $previousCommunication } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $stateFile -Encoding UTF8
    Set-AudioDevice -ID $cable.ID -ErrorAction Stop | Out-Null
}

if ($Action -eq 'disable') {
    $before = Defaults
    $saved = Previous
    $previousDefault = if ($saved -and $saved.default) { $saved.default } else { $fallback.ID }
    $previousCommunication = if ($saved -and $saved.communication) { $saved.communication } else { $fallback.ID }
    $knownIds = @($recording | ForEach-Object ID)
    if ($previousDefault -notin $knownIds) { $previousDefault = $fallback.ID }
    if ($previousCommunication -notin $knownIds) { $previousCommunication = $fallback.ID }
    if ($before.default.ID -eq $cable.ID) {
        if (-not $previousDefault) { throw 'No default recording endpoint is available for restoration.' }
        Set-AudioDevice -ID $previousDefault -DefaultOnly -ErrorAction Stop | Out-Null
    }
    if ($before.communication.ID -eq $cable.ID) {
        if (-not $previousCommunication) { throw 'No communication recording endpoint is available for restoration.' }
        Set-AudioDevice -ID $previousCommunication -CommunicationOnly -ErrorAction Stop | Out-Null
    }
}

$after = Defaults
$enabled = $after.default.ID -eq $cable.ID -and $after.communication.ID -eq $cable.ID
if ($Action -eq 'enable' -and -not $enabled) { throw 'Failed to activate the virtual microphone.' }
if ($Action -eq 'disable' -and ($after.default.ID -eq $cable.ID -or $after.communication.ID -eq $cable.ID)) {
    throw 'Failed to restore the original microphone.'
}
if ($Action -eq 'disable' -and (Test-Path -LiteralPath $stateFile)) {
    Remove-Item -LiteralPath $stateFile -Force
}
@{
    enabled = $enabled
    default = @{ id = $after.default.ID; name = $after.default.Name }
    communication = @{ id = $after.communication.ID; name = $after.communication.Name }
} | ConvertTo-Json -Compress
