#Requires -Version 7.0
<# Maak de vaste lokale speelknoppen; behoud alle bestaande/andere links. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PowerShellPath,
    [Parameter(Mandatory)][string]$PythonPath,
    [string]$DesktopPath = [Environment]::GetFolderPath('Desktop'),
    [switch]$CheckOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PowerShellPath = [IO.Path]::GetFullPath($PowerShellPath)
$workspacePath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
$desktopRoot = [IO.Path]::GetFullPath($DesktopPath)
$folder = [IO.Path]::GetFullPath((Join-Path $desktopRoot 'A2 Revival - Nieuwe tests'))
if ([IO.Path]::GetDirectoryName($folder) -ne $desktopRoot) { throw 'Onverwacht bureaubladdoel.' }
$runner = Join-Path $PSScriptRoot 'Start-A2Playtest.ps1'
foreach ($path in @($desktopRoot, $folder, $runner, $PowerShellPath, $PythonPath)) { Assert-LauncherPath $path }
$raw = & $PythonPath (Join-Path $PSScriptRoot 'playtest_catalog.py') list
if ($LASTEXITCODE -ne 0) { throw 'Proefcatalogus kon niet worden gelezen.' }
$profiles = @($raw | ConvertFrom-Json)
$shell = New-Object -ComObject WScript.Shell
$planned = @()
$index = 0
foreach ($profile in $profiles) {
    $index++
    if ($profile.id -notmatch '^[a-z0-9-]+$' -or $profile.label -match '[\\/:*?"<>|]') { throw 'Onveilige proefnaam.' }
    $target = [IO.Path]::GetFullPath((Join-Path $folder (('{0:00} - {1}.lnk' -f $index, $profile.label))))
    if ([IO.Path]::GetDirectoryName($target) -ne $folder) { throw 'Snelkoppeling valt buiten de testmap.' }
    Assert-LauncherPath $target
    $values = @('-NoLogo','-NoProfile','-File',$runner,'-Profile',[string]$profile.id,'-PythonPath',$PythonPath)
    $arguments = ConvertTo-LauncherArguments $values
    # WScript.Shell serializes descriptions longer than 260 UTF-16 characters
    # incorrectly on this PC, corrupting Arguments/WorkingDirectory. Leave one
    # character of headroom; the complete catalog note stays in the readme.
    $description = [string]$profile.note
    if ($description.Length -gt 259) {
        $prefixLength = 256
        if ([char]::IsHighSurrogate($description[$prefixLength - 1])) { $prefixLength-- }
        $description = $description.Substring(0, $prefixLength) + '...'
    }
    if (Test-Path -LiteralPath $target) {
        $existing = $shell.CreateShortcut($target)
        if ($existing.TargetPath -ne $PowerShellPath -or $existing.Arguments -ne $arguments -or
            $existing.WorkingDirectory -ne $workspacePath -or $existing.WindowStyle -ne 7) { throw 'Een bestaande andere link blijft behouden.' }
    }
    $icon = if ($profile.game -eq 'a2racer1') { 'local/games/a2racer1/A2.EXE' } else { 'local/games/a2racer2/DATA/A2_II.EXE' }
    $planned += @{ id=$profile.id; path=$target; arguments=$arguments; icon=(Join-Path $workspacePath $icon); note=$description; exists=(Test-Path -LiteralPath $target) }
}
$proof = [ordered]@{ folder=$folder; check_only=[bool]$CheckOnly; count=$planned.Count; game_started=$false; links=@() }
if ($CheckOnly) { $proof | ConvertTo-Json -Depth 6; return }
# Only this new folder is written; no existing desktop icon is retired.
$null = New-Item -ItemType Directory -Path $folder -Force
foreach ($item in $planned) {
    $link = $shell.CreateShortcut($item.path)
    if (-not $item.exists) {
        $link.TargetPath = $PowerShellPath
        $link.Arguments = $item.arguments
        $link.WorkingDirectory = $workspacePath
        $link.IconLocation = $item.icon + ',0'
        $link.Description = $item.note
        $link.WindowStyle = 7
        $link.Save()
    }
    $check = $shell.CreateShortcut($item.path)
    if ($check.TargetPath -ne $PowerShellPath -or $check.Arguments -ne $item.arguments -or
        $check.WorkingDirectory -ne $workspacePath -or $check.WindowStyle -ne 7 -or
        (-not $item.exists -and $check.Description -ne $item.note)) { throw 'Snelkoppelingcontrole faalde.' }
    $proof.links += @{ id=$item.id; path=$item.path; sha256=(Get-FileHash -LiteralPath $item.path -Algorithm SHA256).Hash.ToLowerInvariant() }
}
$guide = @(
    'A2 Revival - Nieuwe tests (Atlas)',
    '',
    'Sluit de vorige game normaal af. Dubbelklik daarna één testknop.',
    'Elke knop maakt een verse proefkopie. Originele games en bestaande speelknoppen blijven behouden.',
    'De normale meting duurt 20 seconden; je kunt daarna gewoon verder spelen.',
    'De logmeting bewijst geen succesvolle race. Logs staan onder reports/runtime en zijn via Launcher -> Logs -> Devtools te lezen.',
    '',
    'Deel I: begin met 01 (werkende basis), daarna 02 (1080 hoog/4:3).',
    '04 onderzoekt de bredere 16:9-camera. HUD/dashboard zijn nog niet gecorrigeerd.',
    '03 en 05 vragen 2160 beeldlijnen aan: hoge GPU-belasting, nog geen gemeten interne 4K-render.',
    '06 verandert slechts één wegtexture. Let op lijnen, bermen, naden en verkeer; nog geen compleet HD-pack.',
    'Alle I-proeven: 20 FPS, 20x20, Horizon Uit, dashboard en start-/focusherstel.',
    '10 vergelijkt alle geladen actieve objecten met 01; de wegselectie blijft 20x20. Experimenteel, mogelijk extra tekenlast.',
    'Het originele game-menu kan 640x480 blijven tonen: wrapperresolutie en camera staan in het proefrapport.',
    '',
    'Deel II: 07 native/films aan, dan 08 native/films uit, daarna 09 wrapper/films uit.',
    'Controleer telkens menu, profiel, geluid, racestart, rijden, finish en herstart.',
    'Deel-II-profielen hebben hun eigen binaryversie; deel-I-patches en 20FPS/20x20 worden niet overgenomen.',
    '',
    'Bij problemen: vermeld het knopnummer en of het tijdens laden, rijden of Alt+Tab gebeurde.',
    ''
)
foreach ($profile in $profiles) { $guide += ($profile.label + ': ' + $profile.note) }
$guidePath = Join-Path $folder 'LEESMIJ - testvolgorde.txt'
Assert-LauncherPath $guidePath
if (-not (Test-Path -LiteralPath $guidePath)) { [IO.File]::WriteAllLines($guidePath, $guide, [Text.UTF8Encoding]::new($true)) }
if (@($profiles | Where-Object { $_.id -eq 'i-object-max' }).Count) {
    $maxGuidePath = Join-Path $folder 'LEESMIJ - Objectafstand MAX.txt'
    Assert-LauncherPath $maxGuidePath
    if (-not (Test-Path -LiteralPath $maxGuidePath)) {
        [IO.File]::WriteAllLines($maxGuidePath, @(
            'A2 I - Objectafstand MAX (Atlas)',
            '',
            'Vergelijk 01 - I - Werkende basis met 10 - I - Objectafstand MAX (proef).',
            'Sluit de vorige game normaal af. Kies dezelfde etappe, auto, camera en herkenbare plek.',
            '10 selecteert alle geladen actieve objecten voor rendering. Dit is geen onbeperkte wereld of bewezen engine-maximum.',
            'Wegselectie blijft 20x20; beide proeven houden 1280x960, 20 FPS, Horizon Uit, dashboard en focusherstel.',
            'Let op eerder zichtbare gebouwen/bomen/borden, stotteren, verdwenen objecten, finish en herstart.',
            'Alt+Tab en screenshots zijn een aparte proef. De eerdere HD/4K-feedback bevestigde uitsluitend normaal rijden.',
            '01 start weer met de oorspronkelijke objectselectie. Elke knop gebruikt een verse lokale kopie.',
            'Geen nieuwe speeltest uitgevoerd door Atlas; deze knop staat klaar voor jouw beoordeling.'
        ), [Text.UTF8Encoding]::new($true))
    }
}
$reportRoot = Join-Path $workspacePath 'local/logs'
Assert-LauncherPath $reportRoot
$null = New-Item -ItemType Directory -Path $reportRoot -Force
$proof | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'playtest-shortcuts.json') -Encoding utf8
$proof | ConvertTo-Json -Depth 6
