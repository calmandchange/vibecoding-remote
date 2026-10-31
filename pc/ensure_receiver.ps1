# Keep the desktop receiver running in the user's interactive Windows session.

$ErrorActionPreference = 'Stop'
$pcDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$modeFile = Join-Path $pcDir 'logs\receiver-mode.txt'
$mode = 'wechat'
if (Test-Path -LiteralPath $modeFile) {
    $saved = (Get-Content -LiteralPath $modeFile -Raw).Trim()
    if ($saved -in @('wechat', 'local')) { $mode = $saved }
}

try {
    & (Join-Path $pcDir 'start_receiver.ps1') -Mode $mode -FromWatchdog | Out-Null
} catch {
    $logDir = Join-Path $pcDir 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Add-Content -LiteralPath (Join-Path $logDir 'watchdog.log') -Value "$(Get-Date -Format o) $_"
    throw
}
