#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$KitPath,
    [string]$DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory'),
    [switch]$Launcher
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
    if (-not $KitPath) { $KitPath = $PSScriptRoot }
    $kitRoot = (Get-Item -LiteralPath $KitPath -ErrorAction Stop).FullName
    $required = if ($Launcher) { @('Launcher.cmd','tools\Show-A2Launcher.ps1','tools\launcher_window.xaml','tools\launcher_model.py','tools\launcher_common.ps1','tools\Invoke-A2LauncherSession.ps1','tools\launcher_art\a2-revival.ico') }
        else { @('Start-A2.cmd', 'tools\Start-A2Portable.ps1', 'payload\python-3.13.16-embed-amd64.zip') }
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $kitRoot $relative) -PathType Leaf)) {
            throw 'Pak eerst A2-Revival-Test-I.zip volledig uit en gebruik Maak-snelkoppeling.cmd in die map. De GitHub-broncode bevat geen portable runtimes.'
        }
    }
    if ($Launcher -and -not ((Test-Path -LiteralPath (Join-Path $kitRoot 'payload\python-3.13.16-embed-amd64.zip')) -or
            (Test-Path -LiteralPath (Join-Path $kitRoot 'local\launcher\runtimes.json')) -or
            ((Test-Path -LiteralPath (Join-Path $kitRoot 'local\portable-runtime\python\python.exe')) -and
             (Test-Path -LiteralPath (Join-Path $kitRoot 'local\portable-runtime\powershell\pwsh.exe'))))) {
        throw 'De launcher heeft een complete portable kit of lokale runtimeconfig nodig.'
    }
    if (-not $DesktopDirectory -or -not (Test-Path -LiteralPath $DesktopDirectory -PathType Container)) {
        throw 'De bureaubladmap is niet beschikbaar.'
    }
    $desktopPath = (Get-Item -LiteralPath $DesktopDirectory).FullName
    $shortcutName = if ($Launcher) { 'A2 Revival - Launcher.lnk' } else { 'A2 Racer I - Revival.lnk' }
    $shortcutPath = Join-Path $desktopPath $shortcutName
    $powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $startScript = Join-Path $kitRoot $(if ($Launcher) { 'tools\Show-A2Launcher.ps1' } else { 'tools\Start-A2Portable.ps1' })
    $arguments = if ($Launcher) { '-NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $startScript + '"' }
        else { '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $startScript + '"' }
    $description = if ($Launcher) { 'Project A2 Revival - Launcher (prototype)' } else { 'Project A2 Revival - A2 Racer I (portable)' }

    # CreateShortcut only writes a link. It never launches the target.
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    if ((Test-Path -LiteralPath $shortcutPath) -and
        ($shortcut.Description -ne $description -or
         -not [string]::Equals($shortcut.TargetPath, $powershellPath, [StringComparison]::OrdinalIgnoreCase))) {
        throw ('Er bestaat al een andere ' + $shortcutName + '; deze wordt niet overschreven.')
    }
    $shortcut.TargetPath = $powershellPath
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $kitRoot
    $shortcut.Description = $description
    $shortcut.IconLocation = if ($Launcher) { (Join-Path $kitRoot 'tools\launcher_art\a2-revival.ico') + ',0' } else { $powershellPath + ',0' }
    $shortcut.WindowStyle = if ($Launcher) { 7 } else { 1 }
    $shortcut.Save()

    $saved = $shell.CreateShortcut($shortcutPath)
    if (-not [string]::Equals($saved.TargetPath, $powershellPath, [StringComparison]::OrdinalIgnoreCase) -or
        $saved.Arguments -ne $arguments -or
        -not [string]::Equals($saved.WorkingDirectory, $kitRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'De opgeslagen snelkoppeling wijkt af van dit testpakket.'
    }
    Write-Host ('Klaar: ' + $shortcutPath) -ForegroundColor Green
    if ($Launcher) { Write-Host 'Open A2 Revival - Launcher op je bureaublad. Laat de projectmap staan.'; return }
    Write-Host 'Open A2 Racer I - Revival op je bureaublad om de huidige gameproef te starten.'
    Write-Host 'Laat de uitgepakte testmap staan.'
    if (Test-Path -LiteralPath (Join-Path $kitRoot 'A2-Racer_Win_NL.zip') -PathType Leaf) {
        Write-Host 'De meegeleverde game-ZIP wordt bij de eerste start automatisch geimporteerd.'
    } else {
        Write-Host 'Bij de eerste start kies je je eigen game-ZIP.'
    }
} catch {
    Write-Host ('Snelkoppeling niet gemaakt: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
