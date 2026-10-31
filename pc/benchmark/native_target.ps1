param(
    [string]$EventLog = (Join-Path $PSScriptRoot 'native-target-events.jsonl'),
    [switch]$CaptureScreens,
    [switch]$MeasureVisualLatency
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = '语音输入延迟测试（不会发送消息）'
$form.Size = New-Object System.Drawing.Size(760, 310)
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.TopMost = $true

$editor = New-Object System.Windows.Forms.RichTextBox
$editor.Dock = [System.Windows.Forms.DockStyle]::Fill
$editor.Font = New-Object System.Drawing.Font('Microsoft YaHei', 19)
$editor.HideSelection = $false
$form.Controls.Add($editor)

function Write-Event([string]$name, [string]$detail) {
    $item = @{ name = $name; t_ns = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() * 1000000; detail = $detail }
    Add-Content -LiteralPath $EventLog -Value ($item | ConvertTo-Json -Compress) -Encoding UTF8
}

if (Test-Path -LiteralPath $EventLog) { Remove-Item -LiteralPath $EventLog }
$editor.Add_TextChanged({ Write-Event 'text_changed' $editor.Text })
$form.Add_Deactivate({ Write-Event 'target_deactivated' '' })
$form.Add_Activated({ Write-Event 'target_activated' '' })
$form.Add_Shown({
    $form.Activate()
    $editor.Focus() | Out-Null
    Write-Event 'target_ready' ('hwnd=' + $form.Handle)
})

$script:injectProcess = $null
$script:injectExitedAt = $null
$launchTimer = New-Object System.Windows.Forms.Timer
$launchTimer.Interval = 1500
$launchTimer.Add_Tick({
    $launchTimer.Stop()
    $form.Activate()
    $editor.Focus() | Out-Null
    $projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    $python = Join-Path $projectDir '.venv\Scripts\python.exe'
    $inject = Join-Path $PSScriptRoot 'inject_speech.py'
    $script:injectProcess = Start-Process -FilePath $python -ArgumentList @($inject) -WorkingDirectory $projectDir `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'injection.out.log') `
        -RedirectStandardError (Join-Path $PSScriptRoot 'injection.err.log') -PassThru
    Write-Event 'injection_process_started' ('pid=' + $script:injectProcess.Id)
})
$form.Add_Shown({ $launchTimer.Start() })

$watchTimer = New-Object System.Windows.Forms.Timer
$watchTimer.Interval = 250
$watchTimer.Add_Tick({
    if ($script:injectProcess -and $script:injectProcess.HasExited -and -not $script:injectExitedAt) {
        $script:injectExitedAt = [DateTimeOffset]::UtcNow
        Write-Event 'injection_process_exited' ('code=' + $script:injectProcess.ExitCode)
    }
    if ($script:injectExitedAt -and ([DateTimeOffset]::UtcNow - $script:injectExitedAt).TotalSeconds -gt 5) {
        $watchTimer.Stop()
        $form.Close()
    }
})
$watchTimer.Start()

if ($CaptureScreens -or $MeasureVisualLatency) {
    $injectEvents = Join-Path $PSScriptRoot 'injection-events.jsonl'
    if (Test-Path -LiteralPath $injectEvents) { Remove-Item -LiteralPath $injectEvents }
}

if ($MeasureVisualLatency) {
    $script:visualHotkeyMs = $null
    $script:indicatorSeen = $false
    $script:visibleTextSeen = $false
    $visualTimer = New-Object System.Windows.Forms.Timer
    $visualTimer.Interval = 25
    $visualTimer.Add_Tick({
        if (-not $script:visualHotkeyMs -and $script:injectProcess -and (Test-Path -LiteralPath $injectEvents)) {
            Get-Content -LiteralPath $injectEvents | ForEach-Object {
                try {
                    $event = $_ | ConvertFrom-Json
                    if ($event.name -eq 'hotkey_pressed') { $script:visualHotkeyMs = [double]$event.t_ns / 1000000 }
                } catch { }
            }
        }
        if (-not $script:visualHotkeyMs) { return }
        $elapsed = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $script:visualHotkeyMs
        if (-not $script:indicatorSeen) {
            $bmp = New-Object System.Drawing.Bitmap(220, 150)
            $graphics = [System.Drawing.Graphics]::FromImage($bmp)
            $graphics.CopyFromScreen((New-Object System.Drawing.Point(1170,1240)),[System.Drawing.Point]::Empty,$bmp.Size)
            $green = 0
            for ($y=0; $y -lt 150; $y+=5) {
                for ($x=0; $x -lt 220; $x+=5) {
                    $color = $bmp.GetPixel($x,$y)
                    if ($color.G -gt 150 -and $color.R -lt 80 -and $color.B -gt 70 -and $color.B -lt 200) { $green++ }
                }
            }
            $graphics.Dispose(); $bmp.Dispose()
            if ($green -gt 30) { $script:indicatorSeen = $true; Write-Event 'visual_voice_indicator' ("elapsed_ms=$([math]::Round($elapsed)) green_pixels=$green") }
        }
        if (-not $script:visibleTextSeen) {
            $origin = $editor.PointToScreen((New-Object System.Drawing.Point(0,0)))
            $bmp = New-Object System.Drawing.Bitmap(275, 60)
            $graphics = [System.Drawing.Graphics]::FromImage($bmp)
            $graphics.CopyFromScreen((New-Object System.Drawing.Point(($origin.X+5),($origin.Y+12))),[System.Drawing.Point]::Empty,$bmp.Size)
            $dark = 0
            for ($y=0; $y -lt 60; $y+=2) {
                for ($x=0; $x -lt 275; $x+=2) {
                    $color = $bmp.GetPixel($x,$y)
                    if ($color.R -lt 100 -and $color.G -lt 100 -and $color.B -lt 100) { $dark++ }
                }
            }
            $graphics.Dispose(); $bmp.Dispose()
            if ($dark -gt 40) { $script:visibleTextSeen = $true; Write-Event 'visual_first_text' ("elapsed_ms=$([math]::Round($elapsed)) dark_pixels=$dark") }
        }
        if (($script:indicatorSeen -and $script:visibleTextSeen) -or $elapsed -gt 8000) { $visualTimer.Stop() }
    })
    $visualTimer.Start()
}

if ($CaptureScreens) {
    $captureDir = Join-Path $PSScriptRoot 'screenshots'
    New-Item -ItemType Directory -Force -Path $captureDir | Out-Null
    $captureAt = @(100, 250, 500, 800, 1200, 1800, 2500, 3500)
    $script:captured = @{}
    $script:hotkeyTimeMs = $null
    $captureTimer = New-Object System.Windows.Forms.Timer
    $captureTimer.Interval = 40
    $captureTimer.Add_Tick({
        if (-not $script:hotkeyTimeMs -and $script:injectProcess) {
            if (Test-Path -LiteralPath $injectEvents) {
                Get-Content -LiteralPath $injectEvents | ForEach-Object {
                    try {
                        $event = $_ | ConvertFrom-Json
                        if ($event.name -eq 'hotkey_pressed') { $script:hotkeyTimeMs = [double]$event.t_ns / 1000000 }
                    } catch { }
                }
            }
        }
        if ($script:hotkeyTimeMs) {
            $elapsed = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $script:hotkeyTimeMs
            foreach ($threshold in $captureAt) {
                if ($elapsed -ge $threshold -and -not $script:captured.ContainsKey($threshold)) {
                    $script:captured[$threshold] = $true
                    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
                    $bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
                    $graphics = [System.Drawing.Graphics]::FromImage($bmp)
                    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
                    $path = Join-Path $captureDir ("after-hotkey-$threshold.png")
                    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
                    $graphics.Dispose()
                    $bmp.Dispose()
                    Write-Event 'screen_capture' ("threshold=$threshold actual_ms=$([math]::Round($elapsed)) path=$path")
                }
            }
            if ($script:captured.Count -eq $captureAt.Count) { $captureTimer.Stop() }
        }
    })
    $captureTimer.Start()
}

$timeout = New-Object System.Windows.Forms.Timer
$timeout.Interval = 25000
$timeout.Add_Tick({ $timeout.Stop(); Write-Event 'target_timeout' ''; $form.Close() })
$timeout.Start()
[System.Windows.Forms.Application]::Run($form)
Write-Event 'target_closed' $editor.Text
