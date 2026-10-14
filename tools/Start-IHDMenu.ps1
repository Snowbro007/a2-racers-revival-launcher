#Requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunName,[Parameter(Mandatory)][string]$PythonPath,
      [switch]$CheckOnly,[switch]$FanNoticeShown,[switch]$Intro,
      [int]$RaceFPSLimit=20,[string]$DisplayProfile='hd-1920x1080-camera',
      [string]$CameraProfile='camera-16-9',[string]$RenderDistanceProfile='extended-20',
      [string]$TextureProfile='original',[string]$HudProfile='original',
      [string]$ObjectDistanceProfile='original',[string]$NativeGraphics='accelerated-640',
      [int]$NativeDashboard=1,[int]$NativeHorizon=0,[switch]$RaceFocusRecovery,
      [switch]$EnableGameDebug,[switch]$IsolatedState,[switch]$StopAtEnd,[int]$DurationSeconds=20)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$choices=@{race_fps_limit=$RaceFPSLimit;display_profile=$DisplayProfile;camera_profile=$CameraProfile;
           render_distance_profile=$RenderDistanceProfile;texture_profile=$TextureProfile;hud_profile=$HudProfile;
           object_distance_profile=$ObjectDistanceProfile;native_graphics=$NativeGraphics;
           native_dashboard=$NativeDashboard;native_horizon=$NativeHorizon;race_focus_recovery=[bool]$RaceFocusRecovery}
try{
    if(-not $CheckOnly -and -not $FanNoticeShown){. (Join-Path $PSScriptRoot 'fan_notice_common.ps1');Invoke-A2FanNotice -Game a2racer1}
    $prepArgs=@((Join-Path $PSScriptRoot 'i_frontend_prepare.py'),'--run-name',$RunName,'--python-path',$PythonPath,'--choices',($choices|ConvertTo-Json -Compress))
    if($EnableGameDebug){$prepArgs+='--debug'}
    if($IsolatedState){$prepArgs+='--isolated-state'}
    $output=& $PythonPath @prepArgs
    if($LASTEXITCODE -ne 0){throw 'HD-menuvoorbereiding is mislukt.'};$prepared=$output|ConvertFrom-Json
    if($CheckOnly){& $prepared.script -CheckOnly;return}
    if($Intro){& (Join-Path $PSScriptRoot 'Invoke-A2WithIntro.ps1') -RunName ($RunName+'-intro') -PythonPath $PythonPath -IntroOnly -FanNoticeShown
        if(-not $?){throw 'Intro kon niet starten.'}}
    & $prepared.script -StopAfterSeconds $(if($StopAtEnd){$DurationSeconds}else{0})
    if(-not $?){throw 'HD-menu is afgesloten met een fout.'}
}catch [OperationCanceledException]{Write-Host 'Start geannuleerd.'}catch{Write-Error $_;exit 1}
