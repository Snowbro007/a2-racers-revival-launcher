#Requires -Version 7.0
<#
.SYNOPSIS
Speel de originele deel-I-intro met geverifieerde FFplay, start daarna de game.
.DESCRIPTION
Geen downloads, conversie of UI-automation. Versiegecontroleerde intro/toetsfix
uitsluitend in een verse lokale gamekopie. Nieuwe lokale kopieën
en logs per proef. -IntroOnly test uitsluitend de alternatieve videospeler.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9-]{0,41}$')][string]$RunName,
    [string]$PythonPath,
    [switch]$LocalGameData = $true,
    [switch]$IntroOnly,
    [ValidateRange(1, 300)][int]$DurationSeconds = 20,
    [ValidateRange(45, 180)][int]$MaxIntroSeconds = 90,
    [switch]$EnableGameDebug,
    [ValidateRange(0, 120)][int]$RaceFPSLimit = 20,
    [ValidateSet('original', 'gdi', 'svga', 'no-dither')][string]$MapMode = 'original',
    [ValidateSet('original', 'borderless-4-3', 'hd-1280x960', 'hd-1280x960-fake', 'hd-1920x1440', 'hd-1440x1080', 'hd-2880x2160', 'hd-1920x1080-camera', 'hd-3840x2160-camera')][string]$DisplayProfile = 'original',
    [switch]$PumpLauncherMessages = $true,
    [ValidateSet('original', 'extended-8', 'extended-10', 'extended-20')][string]$RenderDistanceProfile = 'original',
    [switch]$RaceFocusRecovery,
    [ValidateSet('original', 'camera-16-9')][string]$CameraProfile = 'original',
    [ValidateSet('original', 'hd-road-256', 'hd-road-512', 'hd-scenery-1024', 'hd-scenery-cockpit', 'hd-expanded-v1')][string]$TextureProfile = 'original',
    [ValidateSet('original', 'hd-overlay-v1', 'hd-cockpit-v1', 'hd-cockpit-v2', 'hd-cockpit-v3')][string]$HudProfile = 'original',
    [ValidateSet('original', 'loaded-all')][string]$ObjectDistanceProfile = 'original',
    [ValidateSet('original', 'classic-fullscreen', 'refreshed-fullscreen')][string]$MenuProfile = 'original',
    [switch]$ResetNativeOptions,
    [ValidateSet('preserve', 'software-640', 'accelerated-640')][string]$NativeGraphics = 'preserve',
    [ValidateRange(-1, 1)][int]$NativeDashboard = -1,
    [ValidateRange(-1, 1)][int]$NativeHorizon = -1,
    [switch]$StopAtEnd,
    [switch]$FanNoticeShown
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$helper = Join-Path $PSScriptRoot 'intro_player.py'
$player = $null
$identity = $null
$prepared = $null
$stdoutTask = $null
$stderrTask = $null
$result = [ordered]@{ run_name=$RunName; started_utc=[DateTime]::UtcNow.ToString('o'); intro_only=[bool]$IntroOnly; player_exit_code=$null; elapsed_seconds=$null; stop_requested=$false; error=$null; integrity=$null; playback_status='onbekend'; limitations=@('Exitcode 0 bewijst geen zichtbaar beeld of hoorbaar geluid.', 'Elke toets in het filmvenster kan de film eerder beëindigen; de speler geeft dan ook exitcode 0.') }

function Assert-IntroRealPath([string]$Path) {
    $candidate = [IO.Path]::GetFullPath($Path)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -LiteralPath $candidate -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Intro-pad bevat een link/reparse point.' }
        }
        $parent = [IO.Directory]::GetParent($candidate)
        $candidate = if($parent) { $parent.FullName } else { $null }
    }
}

function Stop-IntroPlayer {
    if (-not $player -or -not $identity) { return }
    $player.Refresh()
    if ($player.HasExited) { return }
    if ($player.Id -ne $identity.pid -or $player.StartTime.ToUniversalTime().Ticks -ne $identity.start_ticks -or
        -not [string]::Equals($player.Path, $prepared.player_path, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Introprocesidentiteit veranderde; stoppen geweigerd.'
    }
    $result.stop_requested = $true
    $player.Kill() # Only the freshly created, rechecked instance; never by name.
    $null = $player.WaitForExit(5000)
}

try {
    if (-not $PythonPath) { $PythonPath = (Get-Command python -CommandType Application).Source }
    if ($PythonPath -match '(?i)[\\/]WindowsApps[\\/]') { throw 'Geef een echte Python 3-executable via -PythonPath.' }
    if (-not $IntroOnly -and -not $FanNoticeShown) {
        . (Join-Path $PSScriptRoot 'fan_notice_common.ps1')
        Invoke-A2FanNotice -Game a2racer1
        $FanNoticeShown = $true
    }
    $json = & $PythonPath $helper prepare --run-name $RunName
    if ($LASTEXITCODE -ne 0) { throw 'Introvoorbereiding faalde; er wordt niets gestart.' }
    $prepared = $json | ConvertFrom-Json
    foreach ($entry in @(@{path=$prepared.player_path; hash=$prepared.player_sha256}, @{path=$prepared.video_path; hash=$prepared.video_sha256})) {
        Assert-IntroRealPath $entry.path
        if ((Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.hash) { throw 'Introdependency veranderde vóór uitvoering.' }
    }
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $prepared.player_path
    $startInfo.WorkingDirectory = $prepared.trial_path
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($entry in $prepared.environment.PSObject.Properties) { $startInfo.Environment[$entry.Name] = [string]$entry.Value }
    foreach($argument in $prepared.arguments) { $startInfo.ArgumentList.Add([string]$argument) }
    $player = [Diagnostics.Process]::new()
    $player.StartInfo = $startInfo
    $timer = [Diagnostics.Stopwatch]::StartNew()
    if (-not $player.Start()) { throw 'FFplay kon niet worden gestart.' }
    $identity = @{pid=$player.Id; path=$prepared.player_path; start_ticks=$player.StartTime.ToUniversalTime().Ticks}
    $result['player_identity'] = $identity
    $stdoutTask = $player.StandardOutput.ReadToEndAsync()
    $stderrTask = $player.StandardError.ReadToEndAsync()
    Write-Host "Originele intro via FFplay; PID $($player.Id). Druk op een toets in het filmvenster om verder te gaan."
    while (-not $player.WaitForExit(250)) {
        if ($timer.Elapsed.TotalSeconds -ge $MaxIntroSeconds) { throw 'Intro overschrijdt de meetlimiet; de game wordt niet gestart.' }
    }
    $result.player_exit_code = $player.ExitCode
    $result.elapsed_seconds = $timer.Elapsed.TotalSeconds
    $result.playback_status = if ($player.ExitCode -eq 0) { 'speler-afgesloten' } else { 'speler-fout' }
    if ($player.ExitCode -ne 0) { throw "FFplay eindigde met foutcode $($player.ExitCode); de game wordt niet gestart." }
} catch [System.OperationCanceledException] {
    Write-Host 'Start geannuleerd.'
    exit 2
} catch {
    $result.error = $_.Exception.Message
    throw
} finally {
    if ($player) { Stop-IntroPlayer }
    if ($prepared) {
        Assert-IntroRealPath $prepared.report_path
        foreach($entry in @(@{task=$stdoutTask; name='ffplay-stdout.txt'}, @{task=$stderrTask; name='ffplay-stderr.txt'})) {
            if ($entry.task -and $entry.task.IsCompletedSuccessfully) {
                $log = $entry.task.Result
                $target = Join-Path $prepared.report_path $entry.name
                Assert-IntroRealPath $target
                [IO.File]::WriteAllText($target, $log.Substring(0, [Math]::Min($log.Length, 1048576)), [Text.UTF8Encoding]::new($false))
            }
        }
        $json = & $PythonPath $helper finish --run-name $RunName
        if ($LASTEXITCODE -eq 0) { $result.integrity = $json | ConvertFrom-Json }
        else { $result.error = 'Intro-eindcontrole faalde.' }
        $summaryPath = Join-Path $prepared.report_path 'summary.json'
        Assert-IntroRealPath $summaryPath
        [IO.File]::WriteAllText($summaryPath, ($result | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        Write-Host "Introrapport: $($prepared.report_path)"
    }
}
if ($result.error -or -not $result.integrity -or @($result.integrity.PSObject.Properties | Where-Object { -not $_.Value }).Count) {
    throw 'Intro-integriteit niet bevestigd; de game wordt niet gestart.'
}
if (-not $IntroOnly) {
        & (Join-Path $PSScriptRoot 'Invoke-A2Trial.ps1') -Game a2racer1 -Stage launcher -RunName $RunName -LocalGameData -GraphicsWrapper hybrid-dgvoodoo -OmitNativeIntro -AnyKeyWelcome -KeepNativeOptions:(-not $ResetNativeOptions) -RaceFPSLimit $RaceFPSLimit -HideWatermark -MapMode $MapMode -DisplayProfile $DisplayProfile -NativeGraphics $NativeGraphics -NativeDashboard $NativeDashboard -NativeHorizon $NativeHorizon -DurationSeconds $DurationSeconds -PythonPath $PythonPath -EnableGameDebug:$EnableGameDebug -StopAtEnd:$StopAtEnd -PumpLauncherMessages:$PumpLauncherMessages -RenderDistanceProfile $RenderDistanceProfile -RaceFocusRecovery:$RaceFocusRecovery -CameraProfile $CameraProfile -TextureProfile $TextureProfile -HudProfile $HudProfile -ObjectDistanceProfile $ObjectDistanceProfile -MenuProfile $MenuProfile -FanNoticeShown:$FanNoticeShown
    if (-not $?) { throw 'Gameproef faalde; raadpleeg het afzonderlijke gamerapport.' }
}
