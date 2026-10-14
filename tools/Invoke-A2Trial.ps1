#Requires -Version 7.0
<#
.SYNOPSIS
Start een expliciete, lokale A2-runtimeproef met logs en hashcontrole.
.DESCRIPTION
Maakt een verse volledige werkkopie. Start uitsluitend bekende, gehashte
gamebinaries. Geen UI-bediening, downloads, installatie of registrywijzigingen.
Procesgegevens bewijzen geen zichtbaar menu of speelbare race.
#>
[CmdletBinding()]
param(
    [ValidateSet('a2racer1', 'a2racer2')][string]$Game = 'a2racer1',
    [ValidateSet('launcher', 'intro', 'menu', 'race')][string]$Stage = 'launcher',
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9-]{0,47}$')][string]$RunName,
    [ValidateRange(1, 300)][int]$DurationSeconds = 20,
    [ValidateRange(1048576, 67108864)][long]$MaxDebugBytes = 8388608,
    [switch]$EnableGameDebug,
    [switch]$SkipIntro,
    [switch]$DisableMovies,
    [switch]$LocalGameData,
    [ValidateRange(0, 120)][int]$RaceFPSLimit = 0,
    [switch]$HideWatermark,
    [switch]$OmitNativeIntro,
    [switch]$AnyKeyWelcome,
    [switch]$PumpLauncherMessages,
    [ValidateSet('original', 'extended-8', 'extended-10', 'extended-20')][string]$RenderDistanceProfile = 'original',
    [switch]$RaceFocusRecovery,
    [switch]$FocusLog,
    [ValidateSet('original', 'camera-16-9')][string]$CameraProfile = 'original',
    [ValidateSet('original', 'hd-road-256', 'hd-road-512', 'hd-scenery-1024', 'hd-scenery-cockpit', 'hd-expanded-v1')][string]$TextureProfile = 'original',
    [ValidateSet('original', 'hd-overlay-v1', 'hd-cockpit-v1', 'hd-cockpit-v2', 'hd-cockpit-v3')][string]$HudProfile = 'original',
    [ValidateSet('original', 'classic-fullscreen', 'refreshed-fullscreen')][string]$MenuProfile = 'original',
    [ValidateSet('original', 'gdi-30', 'gdi-30-direct')][string]$MenuRenderProfile = 'original',
    [ValidateSet('original', 'loaded-all')][string]$ObjectDistanceProfile = 'original',
    [switch]$KeepNativeOptions,
    [ValidateSet('preserve', 'software-640', 'accelerated-640')][string]$NativeGraphics = 'preserve',
    [ValidateRange(-1, 1)][int]$NativeDashboard = -1,
    [ValidateRange(-1, 1)][int]$NativeHorizon = -1,
    [ValidateSet('original', 'gdi', 'svga', 'no-dither')][string]$MapMode = 'original',
    [ValidateSet('original', 'borderless-4-3', 'hd-1280x960', 'hd-1280x960-fake', 'hd-1920x1440', 'hd-1440x1080', 'hd-2880x2160', 'hd-1920x1080-camera', 'hd-3840x2160-camera')][string]$DisplayProfile = 'original',
    [ValidateSet('original', '640x480')][string]$MovieDisplayMode = 'original',
    [ValidateSet('native', 'dxwrapper-windowed', 'cnc-ddraw-gdi', 'hybrid-windowed', 'hybrid-dgvoodoo', 'dgvoodoo-windowed')][string]$GraphicsWrapper = 'native',
    [ValidateSet('none', 'fps', 'gdi', 'emulate-surface', 'gdi-origin')][string]$GraphicsDiagnostic = 'none',
    [switch]$StopAtEnd,
    [switch]$FanNoticeShown,
    [string]$PythonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$helperPath = Join-Path $PSScriptRoot 'trial_manifest.py'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$tracked = @{}
$moduleCache = @{}
$diagnosticCodes = @{}
$initialPids = @{}
$startedUtc = $null
$mainProcess = $null
$prepared = $null
$menuDisplayCheck = $null
$reportPath = $null
$transcriptStarted = $false
$fatalError = $null
$noticeCancelled = $false
$cimAvailable = $true
$stdoutState = $null
$stderrState = $null
$integrity = $null
$observedEvents = @()
$remaining = @()
$eventWriter = $null
$stopReason = $null
$focusObserver = $null
$focusObserverStatus = [ordered]@{
    requested = [bool]$FocusLog; launch_attempted = $false; pid = $null
    stdout_path = $null; stderr_path = $null; exit_observed = $false; exit_code = $null
    start_error = $null; sampling_ready = 'unknown'
}
$introSkipAttempted = $false
$introSkipObserved = $false
$knownProcessNames = if ($Game -eq 'a2racer1') { @('A2.EXE', 'A2MOVIE.DAT', 'A2MENU.DAT', 'A2SPEL.DAT') } else { @('A2_II.EXE', 'MENU.DAT', 'SPEL.DAT') }
$cimNameFilter = (@($knownProcessNames | ForEach-Object { "Name='$_'" })) -join ' OR '

function Assert-RealPath([string]$Path) {
    $candidate = [System.IO.Path]::GetFullPath($Path)
    while ($candidate) {
        $item = $null
        try { $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop }
        catch {
            if ($_.CategoryInfo.Category -ne [System.Management.Automation.ErrorCategory]::ObjectNotFound) { throw }
        }
        if ($item) {
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Pad bevat link/reparse point: $candidate"
            }
        }
        $parent = [System.IO.Directory]::GetParent($candidate)
        $candidate = if ($parent) { $parent.FullName } else { $null }
    }
}

function Start-TrialFocusObserver($Descriptor, [string]$Root, [string]$PowerShellPath, [int]$Seconds) {
    if ($Seconds -lt 1 -or $Seconds -gt 300) { throw 'Ongeldige focusmeetduur.' }
    foreach ($name in @('game', 'run_name', 'trial_path', 'working_directory', 'report_path', 'executable_path')) {
        $property = $Descriptor.PSObject.Properties[$name]
        if (-not $property -or $property.Value -isnot [string] -or -not $property.Value) {
            throw "Focusmonitor heeft geen geldig descriptorveld: $name."
        }
    }
    if ($Descriptor.game -cne 'a2racer1' -or $Descriptor.run_name -cnotmatch '^[a-z0-9][a-z0-9-]{0,47}$') {
        throw 'Focusmonitor is uitsluitend beschikbaar voor een exacte deel-I-proef.'
    }
    if (-not [IO.Path]::IsPathRooted($Root) -or -not [IO.Path]::IsPathRooted($PowerShellPath)) {
        throw 'Focusmonitor vereist absolute workspace- en PowerShell-paden.'
    }
    $canonicalRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $trialPath = [IO.Path]::GetFullPath((Join-Path $canonicalRoot "local/experiments/a2racer1/$($Descriptor.run_name)/game"))
    $reportPath = [IO.Path]::GetFullPath((Join-Path $canonicalRoot "reports/runtime/a2racer1/$($Descriptor.run_name)"))
    foreach ($binding in @(@('trial_path', $trialPath), @('working_directory', $trialPath), @('report_path', $reportPath))) {
        $declared = [string]$Descriptor.($binding[0])
        if (-not [IO.Path]::IsPathRooted($declared) -or
            -not [IO.Path]::GetFullPath($declared).Equals($binding[1], [StringComparison]::OrdinalIgnoreCase)) {
            throw "Focusmonitor verwijst naar een andere proefmap: $($binding[0])."
        }
    }
    $allowedExecutables = @('A2.EXE', 'A2MENU.DAT', 'A2SPEL.DAT', 'A2MOVIE.DAT') | ForEach-Object {
        [IO.Path]::GetFullPath((Join-Path $trialPath $_))
    }
    if (-not [IO.Path]::IsPathRooted($Descriptor.executable_path) -or
        $allowedExecutables -notcontains [IO.Path]::GetFullPath($Descriptor.executable_path)) {
        throw 'Focusmonitor heeft geen exacte native proef-executable.'
    }
    $observerPath = Join-Path $canonicalRoot 'tools/Watch-A2Focus.ps1'
    $preparedPath = Join-Path $reportPath 'prepared.json'
    $shellPath = [IO.Path]::GetFullPath($PowerShellPath)
    if ([IO.Path]::GetFileName($shellPath) -ine 'pwsh.exe') { throw 'Focusmonitor vereist de bestaande PowerShell 7-runtime.' }
    foreach ($path in @($canonicalRoot, $trialPath, $reportPath, $preparedPath, $observerPath, $shellPath, $Descriptor.executable_path)) {
        Assert-RealPath $path
        Assert-LauncherPath $path
    }
    foreach ($path in @($trialPath, $reportPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw 'Focusmonitor mist een bestaande proefmap.' }
    }
    foreach ($path in @($preparedPath, $observerPath, $shellPath, $Descriptor.executable_path)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Focusmonitor mist een vereist bestand.' }
    }
    $stdoutPath = Join-Path $reportPath 'focus-observer-stdout.txt'
    $stderrPath = Join-Path $reportPath 'focus-observer-stderr.txt'
    foreach ($path in @($stdoutPath, $stderrPath)) {
        Assert-RealPath $path
        Assert-LauncherPath $path
        if (Test-Path -LiteralPath $path) { throw 'Focusmonitor weigert bestaande observerlogs te overschrijven.' }
    }
    # Reserve only our two new files. Start-Process redirects into these owned
    # reservations; CreateNew refuses collisions before any child is started.
    foreach ($path in @($stdoutPath, $stderrPath)) {
        $reservation = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        $reservation.Dispose()
    }
    $values = @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', $observerPath,
                '-Game', 'a2racer1', '-RunName', [string]$Descriptor.run_name,
                '-DurationSeconds', [string]$Seconds, '-SampleIntervalMilliseconds', '250')
    $child = Start-Process -FilePath $shellPath -ArgumentList (ConvertTo-LauncherArguments $values) -WorkingDirectory $canonicalRoot `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -ErrorAction Stop
    return [PSCustomObject]@{ process = $child; stdout_path = $stdoutPath; stderr_path = $stderrPath }
}

function Update-TrialFocusObserver($Observer, $Status) {
    if (-not $Observer -or $Status.exit_observed) { return }
    try {
        $Observer.process.Refresh()
        if ($Observer.process.HasExited) {
            $Status.exit_observed = $true
            $Status.exit_code = $Observer.process.ExitCode
            Write-Event 'focus_observer_exit' @{ pid = $Status.pid; exit_code = $Status.exit_code }
            if ($Status.exit_code -ne 0) {
                Write-Diagnostic 'focus_observer_failed' "Focusmonitor stopte met exitcode $($Status.exit_code); zie focus-observer-stderr.txt."
            }
        }
    } catch { Write-Diagnostic 'focus_observer_status' "Focusmonitorstatus kon niet worden gelezen: $($_.Exception.Message)" }
}

function Write-Event([string]$Type, $Data) {
    if (-not $eventWriter) { return }
    $record = [ordered]@{ timestamp_utc = [DateTime]::UtcNow.ToString('o'); type = $Type; data = $Data }
    $eventWriter.WriteLine(($record | ConvertTo-Json -Depth 15 -Compress))
    $eventWriter.Flush()
}

function Write-Diagnostic([string]$Code, [string]$Message) {
    if ($diagnosticCodes.ContainsKey($Code)) { return }
    $diagnosticCodes[$Code] = $Message
    Write-Event 'diagnostic' @{ code = $Code; message = $Message }
    Write-Host "Diagnostiek: $Message"
}

function Invoke-Manifest([string]$Action) {
    $arguments = @($helperPath, $Action, '--game', $Game, '--run-name', $RunName, '--stage', $Stage)
    if ($EnableGameDebug -and $Action -eq 'prepare') { $arguments += '--enable-debug' }
    if ($SkipIntro -and $Action -eq 'prepare') { $arguments += '--skip-intro' }
    if ($DisableMovies -and $Action -eq 'prepare') { $arguments += '--disable-movies' }
    if ($Action -eq 'prepare') {
        if ($RaceFPSLimit) { $arguments += @('--race-fps-limit', $RaceFPSLimit) }
        if ($MapMode -ne 'original') { $arguments += @('--map-mode', $MapMode) }
        if ($DisplayProfile -ne 'original') { $arguments += @('--display-profile', $DisplayProfile) }
        if ($MenuProfile -ne 'original') { $arguments += @('--menu-profile', $MenuProfile) }
        if ($MenuRenderProfile -ne 'original') { $arguments += @('--menu-render-profile', $MenuRenderProfile) }
        if ($HideWatermark) { $arguments += '--hide-watermark' }
        if ($OmitNativeIntro) { $arguments += '--omit-native-intro' }
        if ($AnyKeyWelcome) { $arguments += '--any-key-welcome' }
        if ($PumpLauncherMessages) { $arguments += '--pump-launcher-messages' }
        if ($RenderDistanceProfile -ne 'original') { $arguments += @('--render-distance-profile', $RenderDistanceProfile) }
        if ($RaceFocusRecovery) { $arguments += '--race-focus-recovery' }
        if ($CameraProfile -ne 'original') { $arguments += @('--camera-profile', $CameraProfile) }
        if ($TextureProfile -ne 'original') { $arguments += @('--texture-profile', $TextureProfile) }
        if ($HudProfile -ne 'original') { $arguments += @('--hud-profile', $HudProfile) }
        if ($ObjectDistanceProfile -ne 'original') { $arguments += @('--object-distance-profile', $ObjectDistanceProfile) }
        if ($LocalGameData) { $arguments += '--local-game-data' }
        if ($KeepNativeOptions) { $arguments += '--keep-native-options' }
        if ($NativeGraphics -ne 'preserve') { $arguments += @('--native-graphics', $NativeGraphics) }
        if ($NativeDashboard -ne -1) { $arguments += @('--native-dashboard', $NativeDashboard) }
        if ($NativeHorizon -ne -1) { $arguments += @('--native-horizon', $NativeHorizon) }
        $arguments += @('--movie-display-mode', $MovieDisplayMode, '--graphics-wrapper', $GraphicsWrapper,
                        '--graphics-diagnostic', $GraphicsDiagnostic)
    }
    # Native argument array, no command-string interpolation or shell evaluation.
    $result = & $PythonPath @arguments
    if ($LASTEXITCODE -ne 0) { throw "Python $Action mislukt (exit $LASTEXITCODE)." }
    return ($result | ConvertFrom-Json)
}

function Set-LocalGameEnvironment($StartInfo, $Descriptor) {
    $property = $Descriptor.PSObject.Properties['local_game_data']
    if (-not $property -or -not $property.Value) { return }
    $data = $property.Value
    $drive = [IO.Path]::GetPathRoot($StartInfo.WorkingDirectory)
    if ($Descriptor.game -ne 'a2racer1' -or $data.mode -ne 'builtin-NOCD-local-files' -or
        $drive -notmatch '^[A-Za-z]:[\\/]$' -or
        @($data.environment.PSObject.Properties).Count -ne 1 -or
        -not $data.environment.PSObject.Properties['NOCD'] -or
        $data.environment.NOCD -cne $drive.Substring(0,1).ToUpperInvariant()) {
        throw 'Onverwachte lokale-data-procesomgeving; er wordt niets gestart.'
    }
    # Set only this new child. The launcher/menu/race copy this environment.
    $StartInfo.Environment['NOCD'] = [string]$data.environment.NOCD
}

function Test-InTrial([string]$Path) {
    if (-not $Path -or -not $prepared) { return $false }
    $prefix = [System.IO.Path]::GetFullPath($prepared.trial_path).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    return [System.IO.Path]::GetFullPath($Path).StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-PreparedDependencies {
    foreach ($dependency in @($prepared.graphics_dependencies)) {
        if (-not (Test-InTrial $dependency.path)) { throw 'Wrapperdependency ligt buiten de proefmap.' }
        Assert-RealPath $dependency.path
        $item = Get-Item -LiteralPath $dependency.path -Force
        if ($item.PSIsContainer -or $item.Length -ne $dependency.size -or
            (Get-FileHash -LiteralPath $dependency.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.sha256) {
            throw 'Wrapperdependency veranderde na voorbereiding.'
        }
    }
}

function Get-OwnedIdentity($Process) {
    try {
        $Process.Refresh()
        if ($Process.HasExited) { return $null }
        $path = $Process.Path
        $created = $Process.StartTime.ToUniversalTime()
        if (-not (Test-InTrial $path)) { return $null }
        if ($initialPids.ContainsKey($Process.Id)) { return $null }
        if ($created -lt $startedUtc.AddSeconds(-1)) { return $null }
        return @{ pid = $Process.Id; path = $path; start_ticks = $created.Ticks; start_utc = $created.ToString('o') }
    } catch {
        Write-Diagnostic 'process_identity_access' "Een procespad/starttijd kon niet worden gelezen: $($_.Exception.Message)"
        return $null
    }
}

function Add-OwnedProcess($Process, [string]$Origin, $CimRecord) {
    $identity = Get-OwnedIdentity $Process
    if (-not $identity) { return }
    if ($tracked.ContainsKey($identity.pid)) {
        if ($tracked[$identity.pid].identity.start_ticks -ne $identity.start_ticks) {
            Write-Diagnostic "pid_reused_$($identity.pid)" "PID $($identity.pid) is hergebruikt; nieuwe identiteit wordt niet gestopt."
        }
        return
    }
    $entry = @{ identity = $identity; process = $Process; origin = $Origin; fingerprint = ''; modules_seen = @{}; exited = $false; stop_requested = $false }
    $tracked[$identity.pid] = $entry
    $record = @{ identity = $identity; origin = $Origin }
    if ($CimRecord) {
        $record.parent_pid = [int]$CimRecord.ParentProcessId
        $record.command_line = $CimRecord.CommandLine
    }
    Write-Event 'process_discovered' $record
    Write-Host "Proces $($identity.pid): $([System.IO.Path]::GetFileName($identity.path)) ($Origin)."
}

function Find-OwnedProcesses {
    $cimRecords = @()
    if ($cimAvailable) {
        try { $cimRecords = @(Get-CimInstance -ClassName Win32_Process -Filter $cimNameFilter -ErrorAction Stop) }
        catch {
            $script:cimAvailable = $false
            Write-Diagnostic 'cim_denied' "CIM-procesboom/commandline niet beschikbaar: $($_.Exception.Message). Alleen nieuwe processen uit deze proefmap worden gevolgd."
        }
    }
    if ($cimAvailable) {
        # Descendant relation can span a child that exits before discovery;
        # exact trial-path fallback remains necessary and is labelled explicitly.
        foreach ($record in $cimRecords) {
            if (-not (Test-InTrial $record.ExecutablePath)) { continue }
            if ($initialPids.ContainsKey([int]$record.ProcessId)) { continue }
            try {
                $process = Get-Process -Id $record.ProcessId -ErrorAction Stop
                $origin = if ($tracked.ContainsKey([int]$record.ParentProcessId)) { 'child-of-tracked-pid' } else { 'new-trial-path-match' }
                Add-OwnedProcess $process $origin $record
            } catch { Write-Diagnostic "discover_$($record.ProcessId)" "Proces $($record.ProcessId) verdween of was ontoegankelijk bij ontdekking." }
        }
    } else {
        $names = @($knownProcessNames | ForEach-Object { [System.IO.Path]::GetFileNameWithoutExtension($_) })
        foreach ($process in @(Get-Process -Name $names -ErrorAction SilentlyContinue)) {
            if ($initialPids.ContainsKey($process.Id) -or $tracked.ContainsKey($process.Id)) { continue }
            try {
                if (Test-InTrial $process.Path) { Add-OwnedProcess $process 'new-trial-path-match-no-cim' $null }
            } catch { continue }
        }
    }
}

function Test-RelevantModuleName([string]$Name) {
    # Match basenames, including the selected engines and Direct3D backends.
    return $Name -in @('ddraw.dll', 'dsound.dll', 'dinput.dll', 'dinput8.dll', 'winmm.dll',
                      'smack.dll', 'smack32.dll', 'smack64.dll', 'smackw32.dll', 'smackw64.dll',
                      'dxgi.dll', 'dxwrapper.dll', 'd3dimm.dll', 'd3d8.dll', 'd3d9.dll',
                      'd3d10.dll', 'd3d10_1.dll', 'd3d11.dll', 'd3d12.dll')
}

function Test-IntroCommandLine([string]$CommandLine) {
    # Exactly the executable token and one literal intro argument. An outro,
    # suffix, another path, or extra argument never qualifies for termination.
    return $CommandLine -match '^[ \t]*(?:"[^"\r\n]+"|[^\s"\r\n]+)[ \t]+(?:"a2intro\.smk"|a2intro\.smk)[ \t]*$'
}

function Try-SkipIntro {
    if (-not $SkipIntro -or $introSkipAttempted) { return }
    if (-not $cimAvailable) {
        Write-Diagnostic 'intro_skip_unavailable' 'Intro overslaan niet beschikbaar: CIM-commandline ontbreekt; er wordt niets gestopt.'
        return
    }
    if (-not $prepared.skip_intro -or $Game -ne 'a2racer1' -or $Stage -ne 'launcher') { return }
    $parentIdentity = Get-OwnedIdentity $mainProcess
    if (-not $parentIdentity -or -not $tracked.ContainsKey($parentIdentity.pid) -or
        $tracked[$parentIdentity.pid].identity.start_ticks -ne $parentIdentity.start_ticks) { return }
    $moviePath = [System.IO.Path]::GetFullPath((Join-Path $prepared.trial_path 'A2MOVIE.DAT'))
    if (-not [string]::Equals($moviePath, $prepared.intro_executable_path, [System.StringComparison]::OrdinalIgnoreCase)) { return }
    foreach ($entry in @($tracked.Values)) {
        $identity = Get-OwnedIdentity $entry.process
        if (-not $identity -or $identity.start_ticks -ne $entry.identity.start_ticks -or
            -not [string]::Equals($identity.path, $moviePath, [System.StringComparison]::OrdinalIgnoreCase)) { continue }
        try {
            $records = @(Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$($identity.pid)" -ErrorAction Stop)
        } catch {
            $script:cimAvailable = $false
            Write-Diagnostic 'intro_skip_unavailable' "Intro overslaan niet beschikbaar: CIM-commandlinecontrole mislukt ($($_.Exception.Message)); er wordt niets gestopt."
            return
        }
        if ($records.Count -ne 1) { continue }
        $record = $records[0]
        if ([int]$record.ProcessId -ne $identity.pid -or [int]$record.ParentProcessId -ne $parentIdentity.pid -or
            -not [string]::Equals($record.ExecutablePath, $moviePath, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-IntroCommandLine $record.CommandLine)) { continue }
        try {
            Assert-RealPath $moviePath
            if ((Get-FileHash -LiteralPath $moviePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $prepared.intro_executable_sha256) {
                Write-Diagnostic 'intro_skip_changed_binary' 'Intro overslaan geweigerd: A2MOVIE.DAT wijkt af van de vastgelegde hash.'
                return
            }
            # Recheck PID, exact path and creation time after CIM/hash reads.
            $fresh = Get-OwnedIdentity $entry.process
            if (-not $fresh -or $fresh.pid -ne $identity.pid -or $fresh.start_ticks -ne $identity.start_ticks -or
                -not [string]::Equals($fresh.path, $moviePath, [System.StringComparison]::OrdinalIgnoreCase)) { continue }
            $script:introSkipAttempted = $true # One termination attempt per trial.
            $entry.stop_requested = $true
            $entry.process.Kill()
            Write-Event 'intro_skip_requested' @{ pid = $fresh.pid; path = $fresh.path; start_ticks = $fresh.start_ticks; command_line = $record.CommandLine }
            if ($entry.process.WaitForExit(1000)) {
                $script:introSkipObserved = $true
                Write-Event 'intro_skipped' @{ pid = $fresh.pid; path = $fresh.path; start_ticks = $fresh.start_ticks; code = $entry.process.ExitCode; command_line = $record.CommandLine }
                Write-Host "Intro-PID $($fresh.pid) overgeslagen; de originele launcher kan doorgaan."
            } else {
                Write-Diagnostic 'intro_skip_pending' 'Introstop gevraagd; afsluiting is nog niet waargenomen.'
            }
        } catch { Write-Diagnostic 'intro_skip_failed' "Intro overslaan mislukt: $($_.Exception.Message)" }
        return
    }
}

function Sample-Modules($Entry) {
    try {
        foreach ($module in $Entry.process.Modules) {
            $path = $module.FileName
            if ($Entry.modules_seen.ContainsKey($path)) { continue }
            $Entry.modules_seen[$path] = $true
            if (-not (Test-RelevantModuleName $module.ModuleName)) { continue }
            if (-not $moduleCache.ContainsKey($path)) {
                try {
                    $file = Get-Item -LiteralPath $path
                    $moduleCache[$path] = @{ path = $path; name = $module.ModuleName; file_version = $file.VersionInfo.FileVersion; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
                } catch {
                    $moduleCache[$path] = @{ path = $path; name = $module.ModuleName; error = $_.Exception.Message }
                }
            }
            Write-Event 'module_observed' @{ pid = $Entry.identity.pid; module = $moduleCache[$path] }
        }
    } catch { Write-Diagnostic "modules_$($Entry.identity.pid)" "Modules van PID $($Entry.identity.pid) niet beschikbaar: $($_.Exception.Message)" }
}

function Sample-Processes {
    foreach ($entry in @($tracked.Values)) {
        if ($entry.exited) { continue }
        $process = $entry.process
        try {
            $process.Refresh()
            if ($process.HasExited) {
                $entry.exited = $true
                $code = $null
                try { $code = $process.ExitCode } catch { }
                Write-Event 'process_exit' @{ pid = $entry.identity.pid; exit_code = $code; stop_requested = $entry.stop_requested }
                Write-Host "Proces $($entry.identity.pid) afgesloten; exitcode: $code."
                continue
            }
            $identity = Get-OwnedIdentity $process
            if (-not $identity -or $identity.start_ticks -ne $entry.identity.start_ticks) { continue }
            $sample = @{ pid = $identity.pid; cpu_seconds = $process.TotalProcessorTime.TotalSeconds; working_set_bytes = $process.WorkingSet64; responding = $process.Responding; window_title = $process.MainWindowTitle; window_handle = $process.MainWindowHandle.ToInt64() }
            Write-Event 'process_sample' $sample
            $fingerprint = "$($sample.responding)|$($sample.window_title)|$($sample.window_handle)"
            if ($fingerprint -ne $entry.fingerprint) {
                $entry.fingerprint = $fingerprint
                Write-Host "PID $($identity.pid): responding=$($sample.responding), venster='$($sample.window_title)'."
            }
            Sample-Modules $entry
        } catch { Write-Diagnostic "sample_$($entry.identity.pid)" "Procesmeting van PID $($entry.identity.pid) mislukt: $($_.Exception.Message)" }
    }
}

function New-StreamState($Reader, [string]$Name) {
    $path = Join-Path $reportPath "$Name.txt"
    Assert-RealPath $path
    $writer = [System.IO.StreamWriter]::new($path, $false, $utf8)
    $buffer = [char[]]::new(4096)
    return @{ reader = $Reader; writer = $writer; buffer = $buffer; task = $Reader.ReadAsync($buffer, 0, $buffer.Length); characters = 0; ended = $false; name = $Name; truncated = $false }
}

function Poll-Stream($State) {
    if (-not $State -or $State.ended -or -not $State.task.IsCompleted) { return }
    try {
        $count = $State.task.GetAwaiter().GetResult()
        if ($count -eq 0) { $State.ended = $true; return }
        $room = 4 * 1024 * 1024 - $State.characters
        if ($room -gt 0) {
            $keep = [Math]::Min($count, $room)
            $State.writer.Write($State.buffer, 0, $keep)
            $State.writer.Flush()
            $State.characters += $keep
        }
        if ($count -gt $room -and -not $State.truncated) {
            $State.truncated = $true
            Write-Diagnostic "$($State.name)_limit" "$($State.name) is begrensd op 4 Mi tekens; volgende uitvoer wordt alleen afgevoerd."
        }
        $State.task = $State.reader.ReadAsync($State.buffer, 0, $State.buffer.Length)
    } catch { $State.ended = $true; Write-Diagnostic "$($State.name)_read" "$($State.name) kon niet volledig worden gelezen: $($_.Exception.Message)" }
}

function Stop-OwnedProcesses {
    # Never kill by process name, parent PID alone, or a stale PID. Recheck
    # exact path, fresh start identity and initial PID exclusion immediately.
    Find-OwnedProcesses
    foreach ($entry in @($tracked.Values)) {
        $identity = Get-OwnedIdentity $entry.process
        if (-not $identity -or $identity.start_ticks -ne $entry.identity.start_ticks) { continue }
        try {
            $entry.stop_requested = $true
            $entry.process.Kill() # No entireProcessTree: children are checked individually.
            Write-Event 'stop_requested' @{ pid = $identity.pid; path = $identity.path }
        } catch { Write-Diagnostic "stop_$($identity.pid)" "Stoppen van proef-PID $($identity.pid) mislukt: $($_.Exception.Message)" }
    }
}

function Test-DebugLimit {
    # Check game debug output and author-named wrapper logs only in this trial's
    # working directory. No recursive search or unrelated path is inspected.
    $debugPath = Join-Path $prepared.working_directory 'debug.txt'
    try {
        Assert-RealPath $prepared.working_directory
        $logs = @()
        if (Test-Path -LiteralPath $debugPath) { $logs += Get-Item -LiteralPath $debugPath -Force }
        $logScopes = @($prepared.working_directory)
        $raceLocal = Join-Path $prepared.working_directory 'A2SPEL.DAT.local'
        if (Test-Path -LiteralPath $raceLocal) { $logScopes += $raceLocal }
        foreach ($scope in $logScopes) {
            Assert-RealPath $scope
            $logs += @(Get-ChildItem -LiteralPath $scope -Filter 'dxwrapper-*.log' -File -Force)
        }
        foreach ($log in $logs) {
            Assert-RealPath $log.FullName
            $size = $log.Length
            if ($size -gt $MaxDebugBytes) {
                Write-Diagnostic 'debug_size_limit' "$($log.Name) is $size bytes (limiet $MaxDebugBytes); uitsluitend processen uit deze proef worden gestopt."
                $script:stopReason = 'debug-size-limit'
                Stop-OwnedProcesses
                return $true
            }
        }
    } catch {
        Write-Diagnostic 'debug_size_check' "Proeflog-grootte kon niet worden gemeten: $($_.Exception.Message)"
    }
    return $false
}

function Capture-CrashEvents {
    try {
        $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = $startedUtc.ToLocalTime(); Id = @(1000, 1001, 1002) } -MaxEvents 200 -ErrorAction Stop)
        foreach ($event in $events) {
            $xml = [xml]$event.ToXml()
            $values = @{}
            foreach ($data in @($xml.Event.EventData.Data)) {
                if ($data.Name) { $values[$data.Name] = $data.InnerText }
            }
            $pathMatches = @($values.Values | Where-Object { $_ -and (Test-InTrial ([string]$_)) })
            if ($pathMatches.Count -eq 0) { continue }
            $record = @{ timestamp_utc = $event.TimeCreated.ToUniversalTime().ToString('o'); id = $event.Id; provider = $event.ProviderName; record_id = $event.RecordId; fields = $values }
            $script:observedEvents += $record
            Write-Event 'application_crash_event' $record
        }
    } catch {
        Write-Diagnostic 'application_events' "Application-crashlog niet volledig beschikbaar (geen matches of toegangsfout): $($_.Exception.Message)"
    }
}

try {
    if ($FocusLog -and $Game -cne 'a2racer1') { throw 'FocusLog is uitsluitend beschikbaar voor deel I; er wordt geen proef voorbereid.' }
    . (Join-Path $PSScriptRoot 'launcher_common.ps1')
    if (-not $PythonPath) {
        $pythonCommand = Get-Command python -CommandType Application -ErrorAction Stop
        $PythonPath = $pythonCommand.Source
    }
    if ($PythonPath -match '(?i)[\\/]WindowsApps[\\/]') {
        throw 'De WindowsApps-pythonalias is geen gecontroleerde interpreter. Geef -PythonPath met het pad naar een bestaande Python 3-interpreter.'
    }
    Assert-RealPath $workspacePath
    if ($MenuProfile -ne 'original') {
        # Inventory only: native-size menu controls require the exact output
        # mode. Do not let an unsupported mode fall into wrapper upscaling.
        $modeCheckPath = Join-Path $PSScriptRoot 'menu_display_check.py'
        Assert-RealPath $modeCheckPath
        $modeCheckText = & $PythonPath $modeCheckPath '--profile' $MenuProfile
        $modeCheckExit = $LASTEXITCODE
        $menuDisplayCheck = $modeCheckText | ConvertFrom-Json
        if ($modeCheckExit -ne 0 -or -not $menuDisplayCheck.available) {
            throw $menuDisplayCheck.reason
        }
    }
    if (-not $FanNoticeShown) {
        . (Join-Path $PSScriptRoot 'fan_notice_common.ps1')
        Invoke-A2FanNotice -Game $Game
        $FanNoticeShown = $true
    }
    $prepared = Invoke-Manifest 'prepare'
    $reportPath = $prepared.report_path
    Assert-RealPath $reportPath
    $eventWriter = [System.IO.StreamWriter]::new((Join-Path $reportPath 'events.jsonl'), $false, $utf8)
    Start-Transcript -LiteralPath (Join-Path $reportPath 'transcript.txt') -IncludeInvocationHeader | Out-Null
    $transcriptStarted = $true
    Write-Host "Proef $Game/$RunName, fase $Stage, duur ${DurationSeconds}s."
    Write-Host "Rapporten: $reportPath"
    Write-Event 'prepared' $prepared
    if ($menuDisplayCheck) { Write-Event 'menu_display_preflight' $menuDisplayCheck }
    Write-Event 'host' @{ os_version = [Environment]::OSVersion.VersionString; powershell_version = $PSVersionTable.PSVersion.ToString(); os_is_64_bit = [Environment]::Is64BitOperatingSystem; process_is_64_bit = [Environment]::Is64BitProcess; machine = [Environment]::MachineName }
    foreach ($process in @(Get-Process)) { $initialPids[$process.Id] = $true }
    # The hash is rechecked immediately before execution as well as before copy.
    Assert-RealPath $prepared.executable_path
    if ((Get-FileHash -LiteralPath $prepared.executable_path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $prepared.executable_sha256) { throw 'Executable veranderde na voorbereiding.' }
    Assert-PreparedDependencies
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $prepared.executable_path
    $startInfo.WorkingDirectory = $prepared.working_directory
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $prepared.arguments) { $startInfo.ArgumentList.Add([string]$argument) }
    Set-LocalGameEnvironment $startInfo $prepared
    $mainProcess = [System.Diagnostics.Process]::new()
    $mainProcess.StartInfo = $startInfo
    $startedUtc = [DateTime]::UtcNow
    if ($FocusLog) {
        $focusObserverStatus.launch_attempted = $true
        Write-Event 'focus_observer_requested' @{ game = $Game; run_name = $RunName; duration_seconds = $DurationSeconds; sampling_ready = 'unknown' }
        try {
            $focusObserver = Start-TrialFocusObserver $prepared $workspacePath (Join-Path $PSHOME 'pwsh.exe') $DurationSeconds
            $focusObserverStatus.pid = $focusObserver.process.Id
            $focusObserverStatus.stdout_path = $focusObserver.stdout_path
            $focusObserverStatus.stderr_path = $focusObserver.stderr_path
            Write-Event 'focus_observer_start' @{ pid = $focusObserverStatus.pid; stdout_path = $focusObserver.stdout_path; stderr_path = $focusObserver.stderr_path; sampling_ready = 'unknown' }
            Update-TrialFocusObserver $focusObserver $focusObserverStatus
        } catch {
            $focusObserverStatus.start_error = $_.Exception.Message
            Write-Event 'focus_observer_start_failed' @{ message = $focusObserverStatus.start_error }
            Write-Diagnostic 'focus_observer_start_failed' "Focusmonitor kon niet starten: $($focusObserverStatus.start_error)"
        }
    }
    if (-not $mainProcess.Start()) { throw 'Processtart gaf geen gestart proces terug.' }
    Write-Event 'process_start' @{ pid = $mainProcess.Id; executable = $prepared.executable_path; arguments = @($prepared.arguments); working_directory = $prepared.working_directory; started_utc = $startedUtc.ToString('o') }
    # Keep direct PID even if launcher exits before its identity can be read.
    $tracked[$mainProcess.Id] = @{ identity = @{ pid = $mainProcess.Id; path = $prepared.executable_path; start_ticks = $mainProcess.StartTime.ToUniversalTime().Ticks; start_utc = $mainProcess.StartTime.ToUniversalTime().ToString('o') }; process = $mainProcess; origin = 'direct-start'; fingerprint = ''; modules_seen = @{}; exited = $false; stop_requested = $false }
    $stdoutState = New-StreamState $mainProcess.StandardOutput 'stdout'
    $stderrState = New-StreamState $mainProcess.StandardError 'stderr'
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $DurationSeconds) {
        Update-TrialFocusObserver $focusObserver $focusObserverStatus
        Find-OwnedProcesses
        Try-SkipIntro
        Sample-Processes
        Poll-Stream $stdoutState
        Poll-Stream $stderrState
        if (Test-DebugLimit) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($StopAtEnd) {
        if (-not $stopReason) { $stopReason = 'duration-complete-stop-at-end' }
        Stop-OwnedProcesses
        Start-Sleep -Milliseconds 500
        Sample-Processes
    }
    Capture-CrashEvents
} catch [System.OperationCanceledException] {
    $noticeCancelled = $true
    Write-Host 'Start geannuleerd.'
} catch {
    $fatalError = $_.Exception.Message
    Write-Event 'runner_failure' @{ message = $fatalError }
    Write-Host "Proef fout: $fatalError"
} finally {
    if ($prepared -and $reportPath) {
        Update-TrialFocusObserver $focusObserver $focusObserverStatus
        if ($StopAtEnd -and $startedUtc -and $fatalError) { Stop-OwnedProcesses }
        foreach ($state in @($stdoutState, $stderrState)) {
            if ($state) { Poll-Stream $state; $state.writer.Dispose() }
        }
        foreach ($entry in @($tracked.Values)) {
            $identity = Get-OwnedIdentity $entry.process
            if ($identity -and $identity.start_ticks -eq $entry.identity.start_ticks) { $remaining += $identity }
        }
        if ($remaining.Count -gt 0) {
            Write-Host "$($remaining.Count) proefproces(sen) blijven draaien: $((@($remaining | ForEach-Object { $_.pid })) -join ', ')."
            Write-Diagnostic 'processes_remaining' 'Processen draaien nog; integriteit en logs zijn momentopnamen.'
        }
        try {
            $integrity = Invoke-Manifest 'finish'
            Write-Event 'integrity' $integrity
            if (-not $integrity.source_unchanged) {
                Write-Diagnostic 'source_changed' 'Bronbestanden veranderden tijdens de proef; zie source_diff in integrity.json.'
                if (-not $fatalError) { $fatalError = 'Integriteitscontrole: bronbestanden zijn veranderd.' }
            }
        } catch {
            Write-Diagnostic 'integrity_failed' "Hashcontrole mislukt: $($_.Exception.Message)"
            if (-not $fatalError) { $fatalError = "Integriteitscontrole mislukt: $($_.Exception.Message)" }
        }
        $summary = [ordered]@{
            game = $Game; run_name = $RunName; stage = $Stage; duration_seconds = $DurationSeconds
            started_utc = if ($startedUtc) { $startedUtc.ToString('o') } else { $null }
            stop_at_end = [bool]$StopAtEnd; debug_requested = [bool]$EnableGameDebug
            focus_observer = $focusObserverStatus
            skip_intro_requested = [bool]$SkipIntro; intro_skip_attempted = $introSkipAttempted; intro_skipped = $introSkipObserved
            movie_display_mode = $MovieDisplayMode
            disable_movies_requested = [bool]$DisableMovies
            graphics_wrapper = $GraphicsWrapper
            graphics_diagnostic = $GraphicsDiagnostic
            max_debug_bytes = $MaxDebugBytes; stop_reason = $stopReason
            fatal_error = $fatalError; preparation = $prepared; integrity = $integrity
            processes = @($tracked.Values | ForEach-Object { @{ identity = $_.identity; origin = $_.origin; exited_observed = $_.exited; stop_requested = $_.stop_requested } })
            remaining_processes = @($remaining); crash_events = @($observedEvents); modules = @($moduleCache.Values)
            diagnostics = $diagnosticCodes; gameplay_status = 'onbekend'
            limitations = @('Procesdata bewijst geen zichtbaar beeld, audio, bediening of race.', 'Korte processen tussen polls kunnen ontbreken.', 'Modules tonen geladen bestanden, geen daadwerkelijk API-gebruik.', 'Application-events kunnen vertraagd verschijnen; ontbreken bewijst geen foutvrije proef.', 'Integriteitscontrole is een momentopname als proefprocessen blijven draaien.')
        }
        try {
            Assert-RealPath (Join-Path $reportPath 'summary.json')
            [System.IO.File]::WriteAllText((Join-Path $reportPath 'summary.json'), ($summary | ConvertTo-Json -Depth 20), $utf8)
            $unchanged = if ($integrity) { $integrity.source_unchanged } else { 'onbekend' }
            $report = @(
                "# Runtimeproef $Game / $RunName", '',
                "Startfase: $Stage. Gevraagde meetduur: ${DurationSeconds}s. Debug: $([bool]$EnableGameDebug). Intro-displaymodus: $MovieDisplayMode. Graphics-wrapper: $GraphicsWrapper. Graphics-diagnostiek: $GraphicsDiagnostic. StopAtEnd: $([bool]$StopAtEnd).", '',
                "Intro overslaan gevraagd: $([bool]$SkipIntro). Stop geprobeerd: $introSkipAttempted. Introstop waargenomen: $introSkipObserved. Dit repareert de intro niet.", '',
                "Executable: $($prepared.executable_path)", "SHA-256: $($prepared.executable_sha256)",
                "Werkdirectory: $($prepared.working_directory)", '',
                "Bronbestanden ongewijzigd: $unchanged. Lopende proefprocessen bij afsluiting: $($remaining.Count).", '',
                "Runnerfout: $fatalError", '',
                "Focuslog gevraagd: $([bool]$FocusLog). Monitorstart geprobeerd: $($focusObserverStatus.launch_attempted). PID: $($focusObserverStatus.pid). Exit waargenomen: $($focusObserverStatus.exit_observed). Exitcode: $($focusObserverStatus.exit_code). Startfout: $($focusObserverStatus.start_error). Meetgereedheid: onbekend.", '',
                'Speelbaarheid, beeld, audio, menu en race: **onbekend**; deze proef meet processen en logs.', '',
                'Bestanden: events.jsonl, transcript.txt, summary.json, stdout.txt, stderr.txt, source-before/after.json, trial-before/after.json en eventueel game-logs/ met debug.txt en dxwrapper-*.log.', '',
                'Bij configuratiewijzigingen staan oorspronkelijke configuraties in config-before/ en wijzigingen in config.diff.', '',
                'Processen tussen twee polls, ontoegankelijke modules/procesboom en vertraagde Windows-crashmeldingen kunnen ontbreken.',
                'Als processen blijven draaien zijn de bestandshashes en gekopieerde logs momentopnamen.', '',
                '## Diagnostische beperkingen', ''
            ) + @($diagnosticCodes.GetEnumerator() | Sort-Object Key | ForEach-Object { "- $($_.Key): $($_.Value)" })
            Assert-RealPath (Join-Path $reportPath 'report.md')
            [System.IO.File]::WriteAllLines((Join-Path $reportPath 'report.md'), [string[]]$report, $utf8)
            Write-Host "Proef afgerond. Bron ongewijzigd: $unchanged. Zie summary.json en report.md."
        } catch { Write-Host "Rapport schrijven mislukt: $($_.Exception.Message)"; if (-not $fatalError) { $fatalError = $_.Exception.Message } }
    }
    if ($eventWriter) { $eventWriter.Dispose() }
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
if ($noticeCancelled) { exit 2 }
if ($fatalError) { throw $fatalError }
