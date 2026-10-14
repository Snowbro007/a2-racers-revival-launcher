#Requires -Version 5.1
<#
.SYNOPSIS
Atlas: observe focus for one existing A2 I trial, without controlling its game.
.DESCRIPTION
Only reads processes belonging to the exact trial directory and four native
executables. Writes a new, bounded JSONL file in that trial's runtime reports.
Does not start, stop, activate, resize, or send input to any game or window.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')][string]$RunName,
    [ValidateSet('a2racer1')][string]$Game = 'a2racer1',
    [ValidateRange(1, 300)][int]$DurationSeconds = 120,
    [ValidateRange(100, 2000)][int]$SampleIntervalMilliseconds = 250
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-FocusDescriptor([string]$Path) {
    # Full preparation reports include bounded texture evidence and can exceed
    # 64 KiB. Keep an explicit 8 MiB ceiling rather than an unbounded JSON read.
    $descriptorLimitBytes = 8 * 1024 * 1024
    Assert-LauncherPath $Path
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or $item.Length -gt $descriptorLimitBytes) { throw 'Focusdescriptor ontbreekt of is te groot.' }
    # Deny concurrent writes while reading. Check the opened file's length too;
    # a separate Get-Item check alone would leave a size-check/read race.
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        if ($stream.Length -gt $descriptorLimitBytes) { throw 'Focusdescriptor is te groot.' }
        $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8, $true)
        try { $json = $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
    # PowerShell 7.5 otherwise converts ISO JSON strings into DateTime values.
    # Preserve the descriptor's declared string fields; 5.1 has no DateKind.
    $jsonCommand = Get-Command ConvertFrom-Json -CommandType Cmdlet
    if ($jsonCommand.Parameters.ContainsKey('DateKind')) {
        $value = $json | ConvertFrom-Json -DateKind String
    } else {
        $value = $json | ConvertFrom-Json
    }
    if ($null -eq $value -or $value -isnot [PSCustomObject]) { throw 'Focusdescriptor moet een JSON-object zijn.' }
    return $value
}

function Get-FocusStringField($Descriptor, [string]$Name) {
    $property = $Descriptor.PSObject.Properties[$Name]
    if ($null -eq $property -or $property.Value -isnot [string] -or -not $property.Value) {
        throw "Focusdescriptor heeft geen geldig veld: $Name."
    }
    return $property.Value
}

function Assert-FocusDeclaredPath($Descriptor, [string]$Name, [string]$Expected) {
    $declared = Get-FocusStringField $Descriptor $Name
    if (-not [IO.Path]::IsPathRooted($declared) -or
        -not [IO.Path]::GetFullPath($declared).Equals($Expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Focusdescriptor verwijst naar een ander pad: $Name."
    }
}

function Get-FocusRunContext([string]$Root, [string]$Game, [string]$RunName) {
    if ($Game -cne 'a2racer1' -or $RunName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$') {
        throw 'Focusmonitor vereist een geldige, exacte A2 I proefnaam.'
    }
    $canonicalRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $trialPath = [IO.Path]::GetFullPath((Join-Path $canonicalRoot "local/experiments/$Game/$RunName/game"))
    $reportPath = [IO.Path]::GetFullPath((Join-Path $canonicalRoot "reports/runtime/$Game/$RunName"))
    $preparedPath = Join-Path $reportPath 'prepared.json'
    foreach ($path in @($canonicalRoot, $trialPath, $reportPath, $preparedPath)) { Assert-LauncherPath $path }
    if (-not (Test-Path -LiteralPath $trialPath -PathType Container) -or
        -not (Test-Path -LiteralPath $reportPath -PathType Container)) { throw 'De bestaande proefmap ontbreekt.' }
    $prepared = Read-FocusDescriptor $preparedPath
    if ((Get-FocusStringField $prepared 'game') -cne $Game -or
        (Get-FocusStringField $prepared 'run_name') -cne $RunName) { throw 'Focusdescriptor hoort bij een andere proef.' }
    Assert-FocusDeclaredPath $prepared 'trial_path' $trialPath
    Assert-FocusDeclaredPath $prepared 'working_directory' $trialPath
    Assert-FocusDeclaredPath $prepared 'report_path' $reportPath
    $allowedPaths = @('A2.EXE', 'A2MENU.DAT', 'A2SPEL.DAT', 'A2MOVIE.DAT') | ForEach-Object {
        [IO.Path]::GetFullPath((Join-Path $trialPath $_))
    }
    $executable = Get-FocusStringField $prepared 'executable_path'
    if (-not [IO.Path]::IsPathRooted($executable) -or
        $allowedPaths -notcontains [IO.Path]::GetFullPath($executable)) { throw 'Focusdescriptor heeft geen native proef-executable.' }
    foreach ($path in $allowedPaths) { Assert-LauncherPath $path }
    # Summary can already exist after the runner's initial 20-second observation.
    # During that observation, use the preparation timestamp as a lower bound.
    $afterUtc = (Get-Item -LiteralPath $preparedPath).LastWriteTimeUtc.AddSeconds(-1)
    $boundarySource = 'prepared-last-write-utc'
    $summaryPath = Join-Path $reportPath 'summary.json'
    if (Test-Path -LiteralPath $summaryPath) {
        $summary = Read-FocusDescriptor $summaryPath
        if ((Get-FocusStringField $summary 'game') -cne $Game -or
            (Get-FocusStringField $summary 'run_name') -cne $RunName) { throw 'Focussamenvatting hoort bij een andere proef.' }
        $started = Get-FocusStringField $summary 'started_utc'
        if ($started -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?Z$') { throw 'Ongeldige starttijd in focussamenvatting.' }
        $afterUtc = [DateTimeOffset]::Parse($started, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime.AddSeconds(-1)
        $boundarySource = 'summary-started-utc'
    }
    return [PSCustomObject]@{
        Game = $Game; RunName = $RunName; TrialPath = $trialPath; ReportPath = $reportPath
        AllowedPaths = @($allowedPaths); AfterUtc = $afterUtc; BoundarySource = $boundarySource
    }
}

function Get-FocusIdentity($Process, $Context) {
    try {
        $Process.Refresh()
        if ($Process.HasExited -or $Process.Id -le 0 -or -not $Process.Path) { return $null }
        $path = [IO.Path]::GetFullPath($Process.Path)
        if ($Context.AllowedPaths -notcontains $path) { return $null }
        Assert-LauncherPath $path
        $startedUtc = $Process.StartTime.ToUniversalTime()
        if ($startedUtc -lt $Context.AfterUtc) { return $null }
        return [PSCustomObject]@{
            pid = [int]$Process.Id; path = $path; start_ticks = $startedUtc.Ticks
            start_utc = $startedUtc.ToString('o')
        }
    } catch { return $null } # Exited/access denied/unverifiable never means owned.
}

function Test-FocusIdentity($Expected, $Observed) {
    return ($null -ne $Expected -and $null -ne $Observed -and
        $Expected.pid -eq $Observed.pid -and $Expected.start_ticks -eq $Observed.start_ticks -and
        $Expected.path.Equals($Observed.path, [StringComparison]::OrdinalIgnoreCase))
}

function Get-FocusProcessById([int]$ProcessId) {
    return Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Get-FocusCandidates($Context) {
    Get-LauncherProcesses $Context.TrialPath $Context.AfterUtc
}

function Get-FocusForeground {
    $handle = [AtlasA2FocusNative]::GetForegroundWindow()
    [uint32]$owner = 0
    if ($handle -ne [IntPtr]::Zero) { $null = [AtlasA2FocusNative]::GetWindowThreadProcessId($handle, [ref]$owner) }
    return [PSCustomObject]@{ window_handle = $handle.ToInt64(); process_id = [int64]$owner }
}

function Get-FocusWindowState([long]$Handle) {
    [uint32]$owner = 0
    $pointer = [IntPtr]$Handle
    $null = [AtlasA2FocusNative]::GetWindowThreadProcessId($pointer, [ref]$owner)
    return [PSCustomObject]@{
        process_id = [int64]$owner
        visible = [AtlasA2FocusNative]::IsWindowVisible($pointer)
        iconic = [AtlasA2FocusNative]::IsIconic($pointer)
    }
}

function Get-FocusTopWindows {
    return [AtlasA2FocusNative]::TopWindows()
}

function Get-FocusChildWindows([long]$Handle) {
    return [AtlasA2FocusNative]::ChildWindows([IntPtr]$Handle)
}

function Get-FocusWindowClass([long]$Handle) {
    return [AtlasA2FocusNative]::WindowClass([IntPtr]$Handle)
}

function Get-FocusWindowParent([long]$Handle) {
    return [AtlasA2FocusNative]::Parent([IntPtr]$Handle).ToInt64()
}

function Get-FocusStaticTextType([long]$Handle) {
    return [AtlasA2FocusNative]::StaticTextType([IntPtr]$Handle)
}

function Get-FocusDialogTitle([long]$Handle) {
    return [AtlasA2FocusNative]::DialogTitle([IntPtr]$Handle)
}

function Read-FocusStaticText([long]$Handle) {
    # The native helper exposes one hardcoded WM_GETTEXT query, not a general
    # message sender. At most 1024 text characters and a 50 ms timeout.
    return [AtlasA2FocusNative]::ReadStaticText([IntPtr]$Handle)
}

function Test-FocusOwnedDialogWindow([long]$Handle, $Expected, $Context) {
    $fresh = Get-FocusIdentity (Get-FocusProcessById $Expected.pid) $Context
    if (-not (Test-FocusIdentity $Expected $fresh)) { return $false }
    $window = Get-FocusWindowState $Handle
    return ($window.process_id -eq $Expected.pid -and $window.visible -and
        (Get-FocusWindowClass $Handle) -ceq '#32770')
}

function Test-FocusOwnedStaticWindow([long]$Handle, [long]$Dialog, $Expected, $Context) {
    if (-not (Test-FocusOwnedDialogWindow $Dialog $Expected $Context)) { return $false }
    $window = Get-FocusWindowState $Handle
    if ($window.process_id -ne $Expected.pid -or -not $window.visible -or
        (Get-FocusWindowParent $Handle) -ne $Dialog -or
        (Get-FocusWindowClass $Handle) -ine 'Static') { return $false }
    # SS_LEFT/CENTER/RIGHT/SIMPLE/LEFTNOWORDWRAP only; never read an icon,
    # bitmap or owner-drawn Static as if it contained error text.
    return ((Get-FocusStaticTextType $Handle) -in @(0, 1, 2, 11, 12))
}

function Get-FocusOwnedDialog([long]$Handle, $Expected, $Context) {
    try {
        if (-not (Test-FocusOwnedDialogWindow $Handle $Expected $Context)) { return $null }
        $title = [string](Get-FocusDialogTitle $Handle)
        if ($title.Length -gt 1024) { $title = $title.Substring(0, 1024) }
        if (-not (Test-FocusOwnedDialogWindow $Handle $Expected $Context)) { return $null }
        $texts = @()
        $queried = 0
        foreach ($child in @(Get-FocusChildWindows $Handle | Select-Object -First 128)) {
            if ($queried -ge 8) { break }
            if (-not (Test-FocusOwnedStaticWindow $child $Handle $Expected $Context)) { continue }
            $queried++
            $text = Read-FocusStaticText $child
            # Validate ownership again even when the query timed out or returned
            # empty text. Discard the whole dialog on PID/HWND reuse.
            if (-not (Test-FocusOwnedStaticWindow $child $Handle $Expected $Context)) { return $null }
            if ($null -ne $text) {
                $text = [string]$text
                if ($text.Length -gt 1024) { $text = $text.Substring(0, 1024) }
                if ($text) { $texts += [PSCustomObject]@{ window_handle = [long]$child; text = $text } }
            }
        }
        if (-not (Test-FocusOwnedDialogWindow $Handle $Expected $Context)) { return $null }
        return [PSCustomObject]@{
            pid = $Expected.pid; path = $Expected.path; start_ticks = $Expected.start_ticks
            window_handle = $Handle; title = $title; static_text = @($texts)
            text_controls_queried = $queried
        }
    } catch { return $null } # No unverifiable window text is retained.
}

function Get-FocusDialogs($Owned, $Context) {
    $dialogs = @()
    if (@($Owned).Count -eq 0) { return $dialogs }
    foreach ($handle in @(Get-FocusTopWindows | Select-Object -First 512)) {
        if ($dialogs.Count -ge 4) { break } # Global cap also bounds every PID.
        $window = Get-FocusWindowState $handle
        if (-not $window.visible) { continue }
        $expected = $null
        foreach ($process in @($Owned)) {
            if ($process.pid -eq $window.process_id) { $expected = $process; break }
        }
        # No class, title or child-text query for another application's window.
        if ($null -eq $expected) { continue }
        $dialog = Get-FocusOwnedDialog $handle $expected $Context
        if ($null -ne $dialog) { $dialogs += $dialog }
    }
    return $dialogs
}

function Get-FocusOwnedSample($Candidate, $Context) {
    $expected = Get-FocusIdentity $Candidate $Context
    if ($null -eq $expected) { return $null }
    # Query a fresh Process object; a cached object alone cannot rule out PID reuse.
    $current = Get-FocusProcessById $expected.pid
    if (-not (Test-FocusIdentity $expected (Get-FocusIdentity $current $Context))) { return $null }
    try {
        $handle = $current.MainWindowHandle.ToInt64()
        $window = $null
        $title = $null
        if ($handle -ne 0) {
            $window = Get-FocusWindowState $handle
            if ($window.process_id -ne $expected.pid) { return $null }
            $title = [string]$current.MainWindowTitle
            if ($title.Length -gt 256) { $title = $title.Substring(0, 256) }
        }
        $responding = [bool]$current.Responding
        $last = Get-FocusProcessById $expected.pid
        if (-not (Test-FocusIdentity $expected (Get-FocusIdentity $last $Context))) { return $null }
        # A main HWND may also have been reused while its metadata was sampled.
        if ($handle -ne 0 -and (Get-FocusWindowState $handle).process_id -ne $expected.pid) { return $null }
        return [PSCustomObject]@{
            pid = $expected.pid; path = $expected.path; start_ticks = $expected.start_ticks; start_utc = $expected.start_utc
            main_window_handle = $handle; main_window_title = $title; responding = $responding
            visible = $(if ($null -ne $window) { [bool]$window.visible } else { $false })
            iconic = $(if ($null -ne $window) { [bool]$window.iconic } else { $false })
        }
    } catch { return $null }
}

function Get-FocusSample($Context) {
    $foreground = Get-FocusForeground
    $owned = @()
    $rejected = 0
    foreach ($candidate in @(Get-FocusCandidates $Context)) {
        if ($owned.Count -ge 16) { $rejected++; continue }
        $sample = Get-FocusOwnedSample $candidate $Context
        if ($null -ne $sample) { $owned += $sample } else { $rejected++ }
    }
    $foregroundOwned = $false
    foreach ($process in $owned) {
        if ($process.pid -eq $foreground.process_id -and $foreground.window_handle -ne 0) {
            # Do not query the foreground process if it is outside this trial.
            $last = Get-FocusProcessById $process.pid
            $identity = Get-FocusIdentity $last $Context
            $window = Get-FocusWindowState $foreground.window_handle
            $foregroundOwned = (Test-FocusIdentity $process $identity) -and $window.process_id -eq $process.pid
            break
        }
    }
    return [ordered]@{
        event = 'sample'; observed_utc = [DateTime]::UtcNow.ToString('o')
        foreground = [ordered]@{
            window_handle = $foreground.window_handle; process_id = $foreground.process_id; owned = [bool]$foregroundOwned
        }
        owned_processes = @($owned); owned_dialogs = @(Get-FocusDialogs $owned $Context)
        rejected_or_unverified = $rejected
    }
}

function Write-FocusRecord($Writer, $Record) {
    $Writer.WriteLine(($Record | ConvertTo-Json -Depth 8 -Compress))
    $Writer.Flush()
}

function Invoke-FocusWatch($Context, [int]$DurationSeconds = 120, [int]$SampleIntervalMilliseconds = 250) {
    if ($DurationSeconds -lt 1 -or $DurationSeconds -gt 300 -or
        $SampleIntervalMilliseconds -lt 100 -or $SampleIntervalMilliseconds -gt 2000) { throw 'Ongeldige focusmeetduur of interval.' }
    Assert-LauncherPath $Context.ReportPath
    $logName = 'focus-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N') + '.jsonl'
    $logPath = Join-Path $Context.ReportPath $logName
    Assert-LauncherPath $logPath
    # CreateNew forbids replacing any existing report, even on a name collision.
    $stream = [IO.File]::Open($logPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $writer = New-Object IO.StreamWriter($stream, (New-Object Text.UTF8Encoding($false)))
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $reason = 'duration-limit'
    $samples = 0
    try {
        Write-FocusRecord $writer ([ordered]@{
            event = 'start'; schema_version = 1; observer = 'Atlas'; game = $Context.Game; run_name = $Context.RunName
            observed_utc = [DateTime]::UtcNow.ToString('o'); duration_seconds = $DurationSeconds
            sample_interval_milliseconds = $SampleIntervalMilliseconds; start_boundary_utc = $Context.AfterUtc.ToString('o')
            start_boundary_source = $Context.BoundarySource; ownership_scope = 'exact-trial-native-path-pid-start-time'
            note = 'Read-only snapshots; responding is a Windows indication, not a crash diagnosis. Own visible standard dialog text is queried with a bounded WM_GETTEXT; custom/exited/foreign dialogs may be absent.'
        })
        while ($clock.Elapsed.TotalSeconds -lt $DurationSeconds) {
            if ($stream.Position -ge 8388608) { $reason = 'log-size-limit'; break }
            Write-FocusRecord $writer (Get-FocusSample $Context)
            $samples++
            $remaining = ($DurationSeconds * 1000) - $clock.Elapsed.TotalMilliseconds
            if ($remaining -gt 0) { Start-Sleep -Milliseconds ([int][Math]::Min($SampleIntervalMilliseconds, [Math]::Ceiling($remaining))) }
        }
    } catch {
        $reason = 'observer-error'
        throw
    } finally {
        try {
            Write-FocusRecord $writer ([ordered]@{
                event = 'end'; observed_utc = [DateTime]::UtcNow.ToString('o'); reason = $reason
                elapsed_milliseconds = [long]$clock.Elapsed.TotalMilliseconds; samples = $samples
            })
        } finally { $writer.Dispose(); $clock.Stop() }
    }
    return [PSCustomObject]@{ log_path = $logPath; samples = $samples; reason = $reason }
}

. (Join-Path $PSScriptRoot 'launcher_common.ps1')
$context = Get-FocusRunContext (Join-Path $PSScriptRoot '..') $Game $RunName
# Read-only user32 imports and one bounded, hardcoded WM_GETTEXT query.
# No input, activation, style setter, close, or process mutation API.
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class AtlasA2FocusNative {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool IsIconic(IntPtr handle);
    private delegate bool WindowCallback(IntPtr handle, IntPtr parameter);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(WindowCallback callback, IntPtr parameter);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumChildWindows(IntPtr parent, WindowCallback callback, IntPtr parameter);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern int GetClassNameW(IntPtr handle, StringBuilder value, int capacity);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern int GetWindowTextW(IntPtr handle, StringBuilder value, int capacity);
    [DllImport("user32.dll", ExactSpelling = true)]
    private static extern IntPtr GetParent(IntPtr handle);
    [DllImport("user32.dll", ExactSpelling = true)]
    private static extern int GetWindowLongW(IntPtr handle, int index);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr SendMessageTimeoutW(IntPtr handle, uint message, UIntPtr capacity,
        StringBuilder value, uint flags, uint timeout, out UIntPtr result);
    public static long[] TopWindows() {
        var handles = new List<long>();
        WindowCallback callback = delegate(IntPtr handle, IntPtr parameter) {
            handles.Add(handle.ToInt64()); return handles.Count < 512;
        };
        EnumWindows(callback, IntPtr.Zero);
        GC.KeepAlive(callback);
        return handles.ToArray();
    }
    public static long[] ChildWindows(IntPtr parent) {
        var handles = new List<long>();
        WindowCallback callback = delegate(IntPtr handle, IntPtr parameter) {
            handles.Add(handle.ToInt64()); return handles.Count < 128;
        };
        EnumChildWindows(parent, callback, IntPtr.Zero);
        GC.KeepAlive(callback);
        return handles.ToArray();
    }
    public static string WindowClass(IntPtr handle) {
        var value = new StringBuilder(256);
        return GetClassNameW(handle, value, value.Capacity) > 0 ? value.ToString() : String.Empty;
    }
    public static IntPtr Parent(IntPtr handle) { return GetParent(handle); }
    public static int StaticTextType(IntPtr handle) { return GetWindowLongW(handle, -16) & 0x1F; }
    public static string DialogTitle(IntPtr handle) {
        var value = new StringBuilder(1025);
        return GetWindowTextW(handle, value, value.Capacity) > 0 ? value.ToString() : String.Empty;
    }
    public static string ReadStaticText(IntPtr handle) {
        var value = new StringBuilder(1025);
        UIntPtr count;
        // WM_GETTEXT only; SMTO_BLOCK|ABORTIFHUNG|ERRORONEXIT. Never broadcast.
        var ok = SendMessageTimeoutW(handle, 0x000D, (UIntPtr)1025, value, 0x0023, 50, out count);
        if (ok == IntPtr.Zero || count.ToUInt64() > 1024) { return null; }
        return value.ToString();
    }
}
'@
$result = Invoke-FocusWatch $context $DurationSeconds $SampleIntervalMilliseconds
$result | ConvertTo-Json -Compress
