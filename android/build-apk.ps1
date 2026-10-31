param(
    [string]$SdkPath = $env:ANDROID_HOME
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SdkPath) {
    throw '未找到 Android SDK。请设置 ANDROID_HOME，或用 -SdkPath 指定 SDK 目录。'
}
$resolvedSdk = (Resolve-Path -LiteralPath $SdkPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedSdk 'platforms\android-35\android.jar'))) {
    throw 'SDK 缺少 platforms;android-35。'
}
$env:ANDROID_HOME = $resolvedSdk
Push-Location $projectDir
try {
    & .\gradlew.bat assembleDebug
    if ($LASTEXITCODE -ne 0) { throw "Gradle 构建失败，退出码 $LASTEXITCODE" }
    $apk = Join-Path $projectDir 'app\build\outputs\apk\debug\app-debug.apk'
    if (-not (Test-Path -LiteralPath $apk)) { throw '构建结束，但未找到 APK。' }
    $distDir = Join-Path (Split-Path -Parent $projectDir) 'dist'
    New-Item -ItemType Directory -Force -Path $distDir | Out-Null
    $distApk = Join-Path $distDir 'PhoneVoiceRemote-debug.apk'
    Copy-Item -LiteralPath $apk -Destination $distApk -Force
    $item = Get-Item -LiteralPath $distApk
    $hash = (Get-FileHash -LiteralPath $distApk -Algorithm SHA256).Hash
    Write-Output "APK: $($item.FullName)"
    Write-Output "Size: $($item.Length) bytes"
    Write-Output "SHA256: $hash"
} finally {
    Pop-Location
}
