param(
    [switch]$InstallStartup,
    [switch]$FromWatchdog,
    [ValidateSet('wechat', 'local')][string]$Mode = 'wechat'
)

$ErrorActionPreference = 'Stop'
$pcDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $pcDir
$wechatPython = Join-Path $projectDir '.venv\Scripts\python.exe'
$localPython = Join-Path $projectDir '.venv-asr\Scripts\python.exe'
$python = if ($Mode -eq 'local') { $localPython } else { $wechatPython }
$main = Join-Path $pcDir 'main.py'
if (-not (Test-Path -LiteralPath $python)) { throw "找不到 Python 环境：$python" }
if (-not (Test-Path -LiteralPath $main)) { throw "找不到接收程序：$main" }
$logDir = Join-Path $pcDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$modeFile = Join-Path $logDir 'receiver-mode.txt'
if (-not $FromWatchdog) {
    Set-Content -LiteralPath $modeFile -Value $Mode -Encoding ascii
}

if ($InstallStartup) {
    $startupDir = [Environment]::GetFolderPath('Startup')
    $shortcutPath = Join-Path $startupDir 'Phone Voice Remote.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Get-Command powershell.exe).Source
    $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Mode $Mode"
    $shortcut.WorkingDirectory = $pcDir
    $shortcut.Description = '接收 Android 手机蓝牙麦克风和 Ctrl+Win 快捷键'
    $shortcut.Save()
    Write-Output "已设置登录后启动：$shortcutPath"
}

$existing = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*main.py*--port auto*" -and $_.ExecutablePath -in @($wechatPython, $localPython) })
$sameMode = @($existing | Where-Object { $_.ExecutablePath -eq $python })
$heartbeatPath = Join-Path $logDir 'receiver.heartbeat'
$recentStart = (Get-Date).AddSeconds(-90)
$heartbeatFresh = (Test-Path -LiteralPath $heartbeatPath) -and
    (Get-Item -LiteralPath $heartbeatPath).LastWriteTime -gt (Get-Date).AddSeconds(-45)
$newProcess = @($sameMode | Where-Object { $_.CreationDate -gt $recentStart }).Count -gt 0
if ($sameMode -and ($heartbeatFresh -or $newProcess)) {
    Write-Output "接收程序已运行，模式 $Mode；PID: $($sameMode.ProcessId -join ', ')"
    return
}
$stalled = $sameMode.Count -gt 0
$processes = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'")
foreach ($old in $existing) {
    foreach ($child in @($processes | Where-Object { $_.ParentProcessId -eq $old.ProcessId })) {
        Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $old.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output "已停止$(if ($stalled) { '无响应' } else { '其他模式' })的接收程序，PID: $($old.ProcessId)"
}

$outputLog = Join-Path $logDir 'receiver.out.log'
$errorLog = Join-Path $logDir 'receiver.err.log'
$env:PYTHONIOENCODING = 'utf-8'
$process = Start-Process -FilePath $python -ArgumentList @('-u', 'main.py', '--port', 'auto', '--hotkey', 'Ctrl+Win', '--mode', $Mode) `
    -WorkingDirectory $pcDir -WindowStyle Hidden -RedirectStandardOutput $outputLog `
    -RedirectStandardError $errorLog -PassThru
Write-Output "接收程序已启动，模式 $Mode；PID: $($process.Id)"
Write-Output "日志：$outputLog"
