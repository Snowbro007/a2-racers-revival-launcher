#Requires -Version 7.0
# Dot-sourcing only defines functions; it never opens a window or starts a game.
function Get-A2FanNoticeText {
    param([ValidateSet('a2racer1','a2racer2')][string]$Game = 'a2racer1')
    $gameTitle = if ($Game -eq 'a2racer2') { 'A2 Racer II' } else { 'A2 Racer' }
    return [PSCustomObject]@{
        title = 'Onofficiële fanmod'
        body = ('Je start een door fans aangepaste versie van ' + $gameTitle + '. A2 Racers Revival is een onafhankelijk fanproject en geen officiële uitgave van Davilex of Visma. Alle rechten op de oorspronkelijke game, namen, personages en het oorspronkelijke materiaal blijven bij de rechthebbenden.')
        credit = 'Originele game: Davilex'
        rights = 'Rechten: Davilex/Visma en overige rechthebbenden*'
        source = '* Vermelding op basis van Beeld & Geluid (2023).'
        seconds = 4
    }
}

function Set-A2FanNoticeResult {
    param([hashtable]$State, [ValidateSet('continue','timer','cancel')][string]$Reason)
    # The first event wins: a late Tick cannot undo closing the window.
    if ($State.Completed) { return $false }
    $State.Completed = $true
    $State.ExitCode = if ($Reason -eq 'cancel') { 2 } else { 0 }
    $State.Reason = $Reason
    return $true
}

function Assert-A2FanNoticeExitCode {
    param([int]$ExitCode)
    if ($ExitCode -eq 0) { return }
    if ($ExitCode -eq 2) {
        $noticeException = [OperationCanceledException]::new('Start geannuleerd.')
    } else {
        $noticeException = [InvalidOperationException]::new('De fanprojectmelding kon niet worden getoond (exitcode ' + $ExitCode + '). De game is niet gestart.')
    }
    $noticeException.Data['ExitCode'] = $ExitCode
    throw $noticeException
}

function New-A2FanNoticeStartInfo {
    param([ValidateSet('a2racer1','a2racer2')][string]$Game = 'a2racer1')
    $runtime = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if ([IO.Path]::GetFileName($runtime) -ine 'pwsh.exe') {
        throw 'De fanprojectmelding vereist de huidige PowerShell 7-runtime (pwsh.exe).'
    }
    $script = Join-Path $PSScriptRoot 'Show-A2FanNotice.ps1'
    foreach ($path in @($runtime, $script, (Join-Path $PSScriptRoot 'fan_notice_window.xaml'))) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw ('Bestand voor de fanprojectmelding ontbreekt: ' + $path)
        }
    }
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $runtime
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in @('-NoLogo','-NoProfile','-STA','-File',$script,'-Game',$Game)) {
        $info.ArgumentList.Add($argument)
    }
    return $info
}

function Invoke-A2FanNotice {
    param([ValidateSet('a2racer1','a2racer2')][string]$Game = 'a2racer1')
    $process = [Diagnostics.Process]::new()
    try {
        $process.StartInfo = New-A2FanNoticeStartInfo -Game $Game
        if (-not $process.Start()) { throw 'De fanprojectmelding kon niet worden gestart.' }
        # Drain both streams concurrently while waiting for the one UI child.
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $null = $output.GetAwaiter().GetResult()
        $null = $errors.GetAwaiter().GetResult()
        Assert-A2FanNoticeExitCode -ExitCode $process.ExitCode
    } finally {
        $process.Dispose()
    }
}
