#Requires -Version 7.0
<# Eén vaste speelproef; -CheckOnly leest het plan zonder game/cd/procesacties. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Profile,
    [string]$PythonPath,
    [switch]$CheckOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
try {
    if (-not $PythonPath) { $PythonPath = (Get-Command python -CommandType Application).Source }
    Assert-LauncherPath $PythonPath
    if ($PythonPath -match '(?i)[\\/]WindowsApps[\\/]') { throw 'Geef een echte Python-executable via -PythonPath.' }
    $runName = 'play-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,6)
    $rawPlan = & $PythonPath (Join-Path $PSScriptRoot 'playtest_catalog.py') plan --profile $Profile --run-name $runName
    if ($LASTEXITCODE -ne 0) { throw 'Het proefplan kon niet worden gelezen.' }
    $plan = $rawPlan | ConvertFrom-Json
    if ($plan.game -eq 'a2racer1' -and @($plan.arguments) -notcontains '-LocalGameData') {
        $plan.arguments = @($plan.arguments) + @('-LocalGameData')
    }
    if ($CheckOnly) { $plan | ConvertTo-Json -Depth 8; return }
    $expectedScript = Join-Path $PSScriptRoot 'Invoke-A2Trial.ps1'
    if ($plan.script -ne $expectedScript) { throw 'Onverwacht proefscript.' }
    Assert-LauncherPath $expectedScript
    if ($plan.game -eq 'a2racer2') {
        $checkValues = @('--graphics-wrapper', [string]$plan.wrapper)
        if ($plan.movies_off) { $checkValues += '--disable-movies' }
        $preflight = & $PythonPath (Join-Path $PSScriptRoot 'ii_playtest_check.py') @checkValues
        if ($LASTEXITCODE -ne 0 -or -not ($preflight | ConvertFrom-Json).ready_for_trial) { throw 'De deel-II-broncontrole faalde.' }
    }
    $trialRoot = Join-Path $workspacePath 'local/experiments'
    if (@(Get-LauncherProcesses $trialRoot).Count) { throw 'Sluit de eerdere gameproef eerst normaal af.' }
    Write-Host $plan.label
    Write-Host $plan.note
    Write-Host 'De game blijft na de logmeting open. Sluit hem normaal af voordat je een volgende proef start.'
    if ($plan.game -eq 'a2racer2') {
        $otherGame = 'a2racer1'
        & (Join-Path $PSScriptRoot 'Mount-A2Disc.ps1') -Game $otherGame -Dismount
        if (-not $?) { throw 'Loskoppelen van de eigen andere test-cd faalde.' }
        & (Join-Path $PSScriptRoot 'Mount-A2Disc.ps1') -Game $plan.game
        if (-not $?) { throw 'Cdvoorbereiding faalde.' }
    }
    # Native argument array: no Invoke-Expression, command interpolation or shell.
    $values = @($plan.arguments | ForEach-Object { [string]$_ }) + @('-PythonPath', $PythonPath)
    & (Join-Path $PSHOME 'pwsh.exe') -NoLogo -NoProfile -File $expectedScript @values
    if ($LASTEXITCODE -eq 2) { Write-Host 'Start geannuleerd.'; return }
    if ($LASTEXITCODE -ne 0) { throw 'Proef faalde; raadpleeg de lokale logs.' }
    if ($plan.PSObject.Properties['hud'] -and $plan.hud -in @('hd-overlay-v1','hd-cockpit-v1','hd-cockpit-v2','hd-cockpit-v3')) {
        # Only the HUD trial requests this bounded read of its recorded race.
        # A missing/closed race or unsupported observer leaves playing intact.
        try {
            $statusPath = Join-Path $plan.report_path 'hud-status.json'
            Assert-LauncherPath $statusPath
            try {
                $statusTool = Join-Path $PSScriptRoot 'hud_hd_status.py'
                Assert-LauncherPath $statusTool
                $rawStatus = @(& $PythonPath $statusTool --trial $runName 2>&1)
                $statusJson = $rawStatus -join [Environment]::NewLine
                if ([Text.Encoding]::UTF8.GetByteCount($statusJson) -gt 16384) { throw 'HUD-statusuitvoer overschrijdt de 16 KiB limiet.' }
                if ($LASTEXITCODE -ne 0) { throw $statusJson }
                $hudStatus = $statusJson | ConvertFrom-Json
            } catch {
                $statusNote = $_.Exception.Message
                if ($statusNote.Length -gt 512) { $statusNote = $statusNote.Substring(0, 512) }
                $hudStatus = @{ status='status-unavailable'; read_only=$true; visual_quality_verified=$false;
                                note=$statusNote }
            }
            $savedStatus = $hudStatus | ConvertTo-Json -Depth 8
            if ([Text.Encoding]::UTF8.GetByteCount($savedStatus) -gt 16384) { throw 'HUD-statusrapport overschrijdt de 16 KiB limiet.' }
            if (-not (Test-Path -LiteralPath $statusPath)) {
                [IO.File]::WriteAllText($statusPath, $savedStatus, [Text.UTF8Encoding]::new($false))
            }
            $statusDetails = @()
            if ($hudStatus.PSObject.Properties['diagnostics'] -and $hudStatus.diagnostics) {
                $statusDetails += 'stap: ' + [string]$hudStatus.diagnostics.stage
                if ($hudStatus.diagnostics.asset_name) { $statusDetails += 'asset: ' + [string]$hudStatus.diagnostics.asset_name }
            }
            if ($hudStatus.PSObject.Properties['counters'] -and $hudStatus.counters) {
                $statusDetails += 'HRESULT: ' + [string]$hudStatus.counters.last_hr_hex
                $statusDetails += 'HD draws: ' + [string]$hudStatus.counters.draw_count
            }
            $detailText = if ($statusDetails.Count) { ' (' + ($statusDetails -join ', ') + ')' } else { '' }
            Write-Host ('HD-tekenpad: ' + $hudStatus.status + $detailText + '. Zie hud-status.json in de proeflogs.')
        } catch {
            Write-Host ('HD-status kon niet worden vastgelegd: ' + $_.Exception.Message)
        }
    }
    Write-Host ('Proeflogs: ' + $plan.report_path)
} catch {
    Write-Host ('Proef kon niet starten: ' + $_.Exception.Message) -ForegroundColor Red
    if (-not $CheckOnly) { $null = Read-Host 'Druk op Enter om dit venster te sluiten' }
    throw
}
