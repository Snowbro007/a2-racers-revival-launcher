#Requires -Version 7.0
param([Parameter(Mandatory)][string]$PythonPath, [switch]$CheckOnly,
      [switch]$Diagnostic, [switch]$Dismount, [string]$GameArchive,
      [ValidateRange(-1, 120)][int]$RaceFPSLimit = -1,
      [ValidateSet('original', 'gdi', 'svga', 'no-dither')][string]$MapMode,
      [ValidateSet('original', 'borderless-4-3', 'hd-1280x960', 'hd-1280x960-fake', 'hd-1920x1440')][string]$DisplayProfile = 'original')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$kitRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kitRoot
try {
    if ($Dismount) {
        & (Join-Path $PSScriptRoot 'Mount-A2Disc.ps1') -Game a2racer1 -Dismount
        return
    }
    $settingsJson = & $PythonPath -B (Join-Path $PSScriptRoot 'portable_test.py') settings
    if ($LASTEXITCODE -ne 0) { throw 'Instellingen ongeldig; geen game gestart.' }
    $settings = $settingsJson | ConvertFrom-Json
    if ($RaceFPSLimit -ge 0) { $settings.race_fps_limit = $RaceFPSLimit }
    if ($MapMode) { $settings.map_mode = $MapMode }
    if ($CheckOnly) {
        & $PythonPath -B -c 'import sys,struct; print("Portable Python",sys.version.split()[0],"bits",struct.calcsize("P")*8)'
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python werkt niet.' }
        Write-Host ('Portable PowerShell ' + $PSVersionTable.PSVersion)
        foreach ($command in @('Get-CimInstance', 'Get-Acl')) {
            $null = Get-Command $command -ErrorAction Stop
        }
        $tokens = $null; $errors = $null
        foreach ($script in @('Invoke-A2Trial.ps1', 'Invoke-A2WithIntro.ps1')) {
            $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $script), [ref]$tokens, [ref]$errors)
            if ($errors.Count) { throw ('Parserfout in ' + $script) }
        }
        Write-Host 'Controle geslaagd. Geen game gestart of cd gemount. Gebruik Start-A2.cmd voor de speeltest.'
        return
    }
    $active = @(Get-CimInstance Win32_Process -Filter "Name='A2.EXE' OR Name='A2MOVIE.DAT' OR Name='A2MENU.DAT' OR Name='A2SPEL.DAT'" |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith((Join-Path $kitRoot 'local\experiments\'), [StringComparison]::OrdinalIgnoreCase) })
    if ($active.Count) { throw 'Deze kit heeft nog een game open. Sluit die eerst normaal af.' }
    if (-not (Test-Path -LiteralPath (Join-Path $kitRoot 'local\games\a2racer1'))) {
        if (-not $GameArchive) {
            $suggested = Join-Path $kitRoot 'A2-Racer_Win_NL.zip'
            if (Test-Path -LiteralPath $suggested) { $GameArchive = $suggested }
            else {
                Add-Type -AssemblyName System.Windows.Forms
                $dialog = [Windows.Forms.OpenFileDialog]::new()
                $dialog.Title = 'Kies je eigen A2-Racer_Win_NL.zip'
                $dialog.Filter = 'Gamearchief (*.zip)|*.zip'
                $dialog.CheckFileExists = $true
                try {
                    if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'Geen gamearchief gekozen.' }
                    $GameArchive = $dialog.FileName
                } finally { $dialog.Dispose() }
            }
        }
        $freeBytes = ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($kitRoot))).AvailableFreeSpace
        if ($freeBytes -lt 4GB) { throw 'Minstens 4 GB vrije ruimte nodig voor import en proefkopieën.' }
        Write-Host 'Eigen gamearchief controleren, importeren en lokale gamebestanden voorbereiden...'
        & $PythonPath -B (Join-Path $PSScriptRoot 'portable_test.py') import --archive $GameArchive
        if ($LASTEXITCODE -ne 0) { throw 'Game-import faalde; geen game gestart.' }
    }
    $runName = 'portable-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
    Write-Host 'A2 Racer I: originele intro, daarna profielkeuze. Selecteren -> OK -> Start.'
    Write-Host ('Racebegrenzing: ' + $settings.race_fps_limit + ' FPS; minimapprofiel: ' + $settings.map_mode + '. Druk op een toets in het introvenster om over te slaan.')
    if ($Diagnostic) {
        Write-Host 'Diagnoseproef: uitgebreide logs; de eigen game stopt na circa 180 seconden.'
        & (Join-Path $PSScriptRoot 'Invoke-A2WithIntro.ps1') -RunName $runName -PythonPath $PythonPath -RaceFPSLimit $settings.race_fps_limit -MapMode $settings.map_mode -DisplayProfile $DisplayProfile -DurationSeconds 180 -EnableGameDebug -StopAtEnd
    } else {
        Write-Host 'De game blijft na de korte meting open. Deze test bevestigt nog geen volledige speelbaarheid.'
        & (Join-Path $PSScriptRoot 'Invoke-A2WithIntro.ps1') -RunName $runName -PythonPath $PythonPath -RaceFPSLimit $settings.race_fps_limit -MapMode $settings.map_mode -DisplayProfile $DisplayProfile -DurationSeconds 20
    }
    Write-Host ('Logs: ' + (Join-Path $kitRoot ('reports\runtime\a2racer1\' + $runName)))
} catch {
    Write-Host ('A2-test gestopt: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
