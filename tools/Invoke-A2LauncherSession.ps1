#Requires -Version 7.0
param(
    [Parameter(Mandatory)][ValidatePattern('^launcher-[a-z0-9-]{1,35}$')][string]$RunName,
    [Parameter(Mandatory)][string]$PythonPath,
    [switch]$CheckOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
$workspacePath = Split-Path -Parent $PSScriptRoot
$folder = Join-Path $workspacePath ('local\launcher\sessions\' + $RunName)
$mutex = $null; $locked = $false; $transcript = $false

function Write-LauncherState([string]$State, [string]$Message, [int]$ProcessCount = 0) {
    Assert-LauncherPath $folder
    $path = Join-Path $folder 'status.json'
    Assert-LauncherPath $path
    $temporary = Join-Path $folder ('.status-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $value = [ordered]@{ run_name=$RunName; state=$State; message=$Message; process_count=$ProcessCount; updated_utc=[DateTime]::UtcNow.ToString('o'); worker_pid=$PID; worker_start_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks }
    try {
        [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temporary, $path, $true)
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
}

try {
    Assert-LauncherPath $PythonPath
    $json = & $PythonPath -B (Join-Path $PSScriptRoot 'launcher_model.py') plan --session $RunName
    if ($LASTEXITCODE -ne 0) { throw 'Startverzoek of gameversie ongeldig; er wordt niets gestart.' }
    $plan = $json | ConvertFrom-Json
    if ($CheckOnly) { $plan | ConvertTo-Json -Depth 6; return }
    Assert-LauncherPath $folder
    # One start at a time per workspace, including the whole intro and game.
    $digest = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($workspacePath.ToLowerInvariant()))
    $key = [Convert]::ToHexString($digest).Substring(0, 24)
    $mutex = [Threading.Mutex]::new($false, ('Local\A2Revival-' + $key))
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Er loopt al een start of game vanuit deze launcher.' }
    $active = @(Get-LauncherProcesses (Join-Path $workspacePath 'local\experiments'))
    if ($active.Count) { throw 'Er staat nog een game of intro uit deze workspace open. Sluit die eerst normaal af.' }
    if (Test-Path -LiteralPath (Join-Path $folder 'session.log')) { throw 'Deze sessie is al uitgevoerd; start opnieuw via de launcher.' }
    $null = Start-Transcript -LiteralPath (Join-Path $folder 'session.log') -NoClobber
    $transcript = $true
    $startedUtc = [DateTime]::UtcNow
    Write-Host ('Vastgelegde launcheropties: ' + ($plan.preferences | ConvertTo-Json -Depth 6 -Compress))
    Write-LauncherState 'starting' 'Onofficiële fanmod: herkomst en rechten tonen...'
    . (Join-Path $PSScriptRoot 'fan_notice_common.ps1')
    Invoke-A2FanNotice -Game $plan.game
    Write-LauncherState 'starting' 'Lokale gamebestanden en startprocedure voorbereiden...'
    $message = if($plan.script -eq 'Invoke-IIFrontend.ps1'){'Het aanbevolen Revival-menu openen…'}elseif($plan.script -eq 'Invoke-IIOriginalMenu.ps1'){'Oorspronkelijk menu openen zonder cd-image...'}elseif ($plan.script -eq 'Invoke-A2WithIntro.ps1') { 'Intro en game starten. Elke toets in het filmvenster slaat de intro over.' } else { 'Gamekopie voorbereiden en starten...' }
    if ($plan.debug) { $message += ' Diagnose stopt automatisch na maximaal 3 minuten game.' }
    Write-LauncherState 'starting' $message
    # Validated model selects only a fixed script and an argv array, never code.
    # Use a child PowerShell to bind argv as native command-line parameters.
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = (Get-Process -Id $PID).Path
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    foreach ($argument in @('-NoLogo', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File',
            (Join-Path $PSScriptRoot $plan.script)) + @($plan.arguments) + @('-PythonPath', $PythonPath, '-FanNoticeShown')) {
        $info.ArgumentList.Add([string]$argument)
    }
    $runner = [Diagnostics.Process]::new(); $runner.StartInfo = $info
    if (-not $runner.Start()) { throw 'Startprocedure kon niet worden gestart.' }
    if($plan.script -eq 'Invoke-IIFrontend.ps1'){Write-LauncherState 'running' 'Revival-menu geopend. Alt+F4 sluit het menu en zijn race.' 1}
    if($plan.script -eq 'Invoke-IIOriginalMenu.ps1'){Write-LauncherState 'running' 'Oorspronkelijk menu starten zonder cd-image. Alt+F4 sluit de sessie.' 1}
    if($plan.script -eq 'Start-IHDMenu.ps1'){Write-LauncherState 'running' 'HD-menu starten. Kies een speler en Start om te racen; Einde sluit af.' 1}
    $outTask = $runner.StandardOutput.ReadToEndAsync(); $errTask = $runner.StandardError.ReadToEndAsync()
    while (-not $runner.WaitForExit(500)) { } # Only this worker waits; WPF stays independent.
    $out = $outTask.GetAwaiter().GetResult(); $err = $errTask.GetAwaiter().GetResult()
    if ($out.Length) { Write-Host $out.Substring(0, [Math]::Min($out.Length, 1048576)) }
    if ($err.Length) { Write-Host $err.Substring(0, [Math]::Min($err.Length, 1048576)) }
    if ($runner.ExitCode -ne 0) { throw ('Startprocedure gaf een fout. ' + $err.Substring(0, [Math]::Min($err.Length, 1500))) }
    $runner.Dispose()
    $processes = @(Get-LauncherProcesses $plan.trial_path $startedUtc)
    while ($processes.Count) {
        Write-LauncherState 'running' 'Gameproces draait. Sluit de game af via het eigen menu.' $processes.Count
        Start-Sleep -Seconds 2
        $processes = @(Get-LauncherProcesses $plan.trial_path $startedUtc)
    }
    Write-LauncherState 'finished' 'Gameprocessen afgesloten. Klaar voor een volgende start.'
} catch [System.OperationCanceledException] {
    if (Test-Path -LiteralPath $folder) { Write-LauncherState 'finished' 'Start geannuleerd.' }
    Write-Host 'Start geannuleerd.'
} catch {
    $message = $_.Exception.Message
    if ((Test-Path -LiteralPath $folder) -and -not $CheckOnly) { Write-LauncherState 'error' $message }
    Write-Error $message -ErrorAction Continue
    exit 1
} finally {
    if ($transcript) { $null = Stop-Transcript }
    if ($locked -and $mutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
