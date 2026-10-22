#Requires -Version 7.4
param([Parameter(Mandatory)][string]$PythonPath, [switch]$FanNoticeShown, [switch]$CheckOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
Assert-LauncherPath $PythonPath
$raw=& $PythonPath -B (Join-Path $PSScriptRoot 'launcher_model.py') ii-original-menu-plan
if($LASTEXITCODE -ne 0){throw 'Het oorspronkelijke deel-II-menu is niet gereed.'}
$plan=$raw | ConvertFrom-Json
$hostPath=Join-Path $PSScriptRoot 'ii_original_session.ps1'
Assert-LauncherPath $hostPath
if(-not $CheckOnly -and -not $FanNoticeShown){
    . (Join-Path $PSScriptRoot 'fan_notice_common.ps1')
    Invoke-A2FanNotice -Game 'a2racer2'
}
# The host sets NOCD only on its owned MENU/SPEL children and waits
# throughout the session. Never invoke A2_II.EXE or mount a disc here.
$previousNonInteractive=$env:II_PROBE_NONINTERACTIVE
try {
    $env:II_PROBE_NONINTERACTIVE='1'
    & $hostPath -PythonPath $PythonPath -CheckOnly:$CheckOnly
} finally {
    $env:II_PROBE_NONINTERACTIVE=$previousNonInteractive
}
