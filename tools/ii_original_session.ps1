#Requires -Version 7.4
# Persistent native-menu session. Only our own MENU/SPEL child is controlled.
param([Parameter(Mandatory)][string]$PythonPath, [switch]$CheckOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
Assert-LauncherPath $PythonPath
$workspace=Split-Path -Parent $PSScriptRoot
$model=Join-Path $PSScriptRoot 'launcher_model.py'
$process=$null; $session=$null; $lock=$null; $started=$false

function Read-OriginalPlan([string]$Stage) {
    $arguments=@('-B',$model,'ii-original-menu-plan')
    if ($Stage) { $arguments=@('-B',$model,'ii-original-stage','--stage',$Stage) }
    $raw=& $PythonPath @arguments
    if ($LASTEXITCODE -ne 0) { throw 'De oorspronkelijke menukopie veranderde of is niet voorbereid.' }
    return ($raw | ConvertFrom-Json)
}

function Write-SessionEvent([string]$Kind,[hashtable]$Details=@{}) {
    $entry=@{utc=[DateTime]::UtcNow.ToString('o');event=$Kind}
    foreach ($key in $Details.Keys) { $entry[$key]=$Details[$key] }
    Add-Content -LiteralPath $script:events -Value ($entry|ConvertTo-Json -Compress) -Encoding utf8
}

function Invoke-OriginalStage([string]$Stage,[string]$Argument) {
    $selected=Read-OriginalPlan $Stage
    if ($selected.base -cne $plan.base) { throw 'Menuregistratie veranderde tijdens de sessie.' }
    if ($session.StopRequested) { return 0 }
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName=Join-Path $data $(if ($Stage -ceq 'menu') {'MENU.DAT'} else {'SPEL.DAT'})
    Assert-LauncherPath $info.FileName
    $info.WorkingDirectory=$data; $info.UseShellExecute=$false
    if ($Argument) { $info.ArgumentList.Add($Argument) }
    $info.Environment['NOCD']=$drive
    $script:process=[Diagnostics.Process]::new(); $process.StartInfo=$info
    try {
        if (-not $process.Start()) { throw 'Eigen gameproces kon niet starten.' }
        $script:started=$true
        $session.Track($process,$true)
        Write-SessionEvent 'stage-started' @{stage=$Stage;pid=$process.Id}
        while (-not $process.WaitForExit(25)) {
            if ($session.StopRequested) {
                Write-SessionEvent 'close-requested' @{stage=$Stage;reason='alt-f4'}
                $null=$process.CloseMainWindow()
                if (-not $process.WaitForExit(1500)) {
                    $process.Kill()
                    if (-not $process.WaitForExit(3000)) { throw 'Eigen gameproces sloot niet binnen de afsluittermijn.' }
                }
                break
            }
        }
        $code=$process.ExitCode
        Write-SessionEvent 'stage-exited' @{stage=$Stage;exit_code=$code}
        return $code
    } finally {
        $session.ClearGame()
        if ($started -and -not $process.HasExited) { $process.Kill(); $null=$process.WaitForExit(3000) }
        $process.Dispose(); $script:process=$null; $script:started=$false
    }
}

try {
    $plan=Read-OriginalPlan ''
    $data=Join-Path $plan.base 'game/DATA'
    Assert-LauncherPath $data
    $drive=[IO.Path]::GetPathRoot($data).Substring(0,1).ToUpperInvariant()
    if ($drive -notmatch '^[A-Z]$') { throw 'Deze menuroute vereist een lokale schijfletter.' }
    if ($CheckOnly) {
        @{game='a2racer2';baseline=$plan.baseline;game_started=$false;native_helper_started=$false;
          race_runtime_tested=$false;session_timeout=$null} | ConvertTo-Json
        exit 0
    }
    $lockPath=Join-Path $plan.base 'session.lock'
    Assert-LauncherPath $lockPath
    $lock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    foreach ($relative in @('local/experiments','local/ii-parallel','local/launcher/sessions')) {
        if (@(Get-LauncherProcesses (Join-Path $workspace $relative)).Count) { throw 'Sluit de eerdere game eerst normaal af.' }
    }
    Assert-LauncherPath $plan.report_path
    $null=New-Item -ItemType Directory -Path $plan.report_path -Force
    $script:events=Join-Path $plan.report_path ('native-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')+'.jsonl')
    Assert-LauncherPath $events
    . (Join-Path $PSScriptRoot 'ii_owned_session.ps1')
    Import-IIOwnedSession
    $session=[AtlasIIOwnedSession]::Begin()
    $first=$true
    while (-not $session.StopRequested) {
        $argument=if ($first) {'\FIRST'} else {''}
        $code=Invoke-OriginalStage 'menu' $argument
        $first=$false
        if ($session.StopRequested) { break }
        if ($code -ne 40) {
            if ($code -notin @(0,255)) { throw ('Menu sloot onverwacht: '+$code) }
            break
        }
        Write-SessionEvent 'race-requested'
        $code=Invoke-OriginalStage 'race' ''
        if ($session.StopRequested) { break }
        if ($code -lt 0 -or $code -gt 255) { throw ('Race sloot onverwacht: '+$code) }
        Write-SessionEvent 'return-to-menu'
    }
} finally {
    if ($session) { $session.ClearGame(); $session.Dispose() }
    if ($process) {
        if ($started -and -not $process.HasExited) { $process.Kill(); $null=$process.WaitForExit(3000) }
        $process.Dispose()
    }
    if ($lock) { $lock.Dispose() }
}
