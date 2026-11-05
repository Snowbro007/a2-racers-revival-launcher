#Requires -Version 5.1
# Shared path and Windows argv helpers. No game execution on dot-sourcing.
function Assert-LauncherPath([string]$Path, [switch]$ReadOnlySystemPowerShell) {
    $candidate = [IO.Path]::GetFullPath($Path)
    $requested = $candidate
    # Windows services its own PowerShell executable through WinSxS hardlinks.
    # The launcher only starts this exact host; it never writes it or its ACL.
    $windows = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $systemHost = [IO.Path]::GetFullPath((Join-Path $windows 'System32\WindowsPowerShell\v1.0\powershell.exe'))
    $allowSystemHost = $ReadOnlySystemPowerShell -and $requested.Equals($systemHost, [StringComparison]::OrdinalIgnoreCase)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -LiteralPath $candidate -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Launcherpad bevat een link/reparse point.' }
            $link = $item.PSObject.Properties['LinkType']
            if ($link -and $link.Value -eq 'HardLink' -and -not ($allowSystemHost -and $candidate.Equals($requested, [StringComparison]::OrdinalIgnoreCase))) {
                throw ('Launcherpad bevat een hardlink: ' + $candidate)
            }
        }
        $parent = [IO.Directory]::GetParent($candidate)
        $candidate = if ($parent) { $parent.FullName } else { $null }
    }
}

function ConvertTo-LauncherArguments([string[]]$Values) {
    # CommandLineToArgvW/CRT quoting, including embedded quotes and final slashes.
    # No shell parses these arguments: ProcessStartInfo.UseShellExecute is false.
    $quoted = foreach ($value in $Values) {
        $escaped = [regex]::Replace($value, '(\\*)"', '$1$1\"')
        $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
        '"' + $escaped + '"'
    }
    return $quoted -join ' '
}

function Get-LauncherProcesses([string]$Root, [DateTime]$After = [DateTime]::MinValue) {
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    foreach ($process in @(Get-Process -ErrorAction SilentlyContinue)) {
        try {
            if ($process.Path -and $process.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -and
                $process.StartTime.ToUniversalTime() -ge $After -and -not $process.HasExited) {
                $process
            }
        } catch { } # Access denied/exited process; never guess ownership or kill it.
    }
}

# One naming rule for every game (see tools/display_labels.py):
# [Origineel ·] [naam ·] B × H · verhouding [· status]. Status always last.
function Format-A2Resolution([int]$Width = 0, [int]$Height = 0, [string]$Ratio, [switch]$Original, [string]$Name, [string]$Status) {
    if (($Width -gt 0) -ne ($Height -gt 0)) { throw 'Geef breedte en hoogte samen op.' }
    if ($Ratio -and $Ratio -notin @('4:3','16:9')) { throw ('Onbekende beeldverhouding: ' + $Ratio) }
    if ($Status -and $Status -cnotin @('aanbevolen','untested','unstable','vervallen')) { throw ('Onbekende status: ' + $Status) }
    $parts = @()
    if ($Original) { $parts += 'Origineel' }
    if ($Name) { $parts += $Name }
    if ($Width -gt 0) { $parts += ([string]$Width + ' ' + [char]0x00D7 + ' ' + [string]$Height) }
    if ($Ratio) { $parts += $Ratio }
    if ($Status) { $parts += $Status }
    if (-not $parts.Count) { throw 'Lege resolutienaam.' }
    return ($parts -join (' ' + [char]0x00B7 + ' '))
}

# Development stage per library card, kept in one place so every card uses
# the same words. Change the text here when a game moves on.
function Get-A2GameStage([string]$Game) {
    switch ($Game) {
        'a2racer1' { return 'Bijna af' }
        'a2racer2' { return 'Speelbaar ' + [char]0x00B7 + ' wordt verbeterd' }
        'a2racer3' { return 'In ontwikkeling' }
        'a2racer4' { return 'Nieuw ' + [char]0x00B7 + ' HD-basis speelbaar' }
        'vakantieracer' { return 'Nieuw ' + [char]0x00B7 + ' HD-basis speelbaar' }
    }
    throw ('Onbekende game: ' + $Game)
}