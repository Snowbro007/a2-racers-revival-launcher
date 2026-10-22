#Requires -Version 7.0
param([Parameter(Mandatory)][string]$PythonPath, [switch]$FanNoticeShown, [switch]$CheckOnly,
      [ValidateSet('classic','widescreen')][string]$RaceDisplay,
      [ValidatePattern('^launcher-[a-z0-9-]{1,35}$')][string]$RunName,
      [ValidateSet('720p','1080p','4k')][string]$RaceResolution='720p',
      [ValidateSet('native','hd','hd-map')][string]$RaceHud='native',
      [ValidateSet('original','horizon-off','flat')][string]$SkyMode='flat',
      [ValidateSet('auto','50','60')][string]$RenderDistance='60', [switch]$DeveloperMode, [switch]$VectorCar,
      [string]$CheatsJson)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
Assert-LauncherPath $PythonPath
if($DeveloperMode -and -not $RunName){throw 'Ontwikkelaarsmodus vereist een eigen startkopie.'}
if($VectorCar -and -not $RunName){throw 'Vector vereist een eigen startkopie.'}
if($CheatsJson -and -not $RunName){throw 'Cheats vereisen een eigen startkopie.'}
if($CheatsJson){
    & $PythonPath -B (Join-Path $PSScriptRoot 'launcher_cheats.py') --game a2racer2 --cheats $CheatsJson | Out-Null
    if($LASTEXITCODE -ne 0){throw 'Ongeldige cheatkeuzes; starten geweigerd.'}
}
$model=Join-Path $PSScriptRoot 'launcher_model.py'
$raw=& $PythonPath -B $model ii-menu-plan
if($LASTEXITCODE -ne 0){throw 'Het aanbevolen deel-II-menu is niet gereed.'}
$plan=$raw | ConvertFrom-Json
$menuPath=Join-Path $plan.base 'Menu.ps1'
Assert-LauncherPath $menuPath
if($CheckOnly){
    if($VectorCar){
        & $PythonPath -B -c 'import pathlib,sys;sys.path.insert(0,sys.argv[1]);from tools.ii_vector_car import checked_art;checked_art(pathlib.Path(sys.argv[1]))' (Split-Path -Parent $PSScriptRoot)
        if($LASTEXITCODE -ne 0){throw 'De lokale Vector-bestanden zijn niet gereed.'}
    }
    if($RunName -and $RaceDisplay -ne 'classic'){
        $checkArguments=@('-B',(Join-Path $PSScriptRoot 'ii_launcher_graphics.py'),'check','--race-resolution',$RaceResolution,'--race-hud',$RaceHud,'--sky-mode',$SkyMode,'--race-distance',$RenderDistance)
        if($CheatsJson){$checkArguments+=@('--cheats',$CheatsJson)}
        & $PythonPath @checkArguments | Out-Null
        if($LASTEXITCODE -ne 0){throw 'De gekozen deel-II-beeldopties zijn niet gereed.'}
    }
    $plan | ConvertTo-Json;return
}
if(-not $FanNoticeShown){
    . (Join-Path $PSScriptRoot 'fan_notice_common.ps1')
    Invoke-A2FanNotice -Game 'a2racer2'
}
# Keep the host alive throughout menu Hide -> race -> menu return.
$menuArguments=@{}
if($RaceDisplay){$menuArguments.RaceDisplay=$RaceDisplay}
$sourceLock=$null
try {
    if($RunName){
        if(@(Get-LauncherProcesses (Join-Path (Split-Path -Parent $PSScriptRoot) 'local/ii-parallel')).Count){throw 'Sluit de eerdere deel-II-race eerst normaal af.'}
        $lockPath=Join-Path $plan.base 'menu.lock';Assert-LauncherPath $lockPath
        try{$sourceLock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
        catch{throw 'Het aanbevolen deel-II-menu staat nog open. Sluit dit eerst normaal af.'}
        $prepareArguments=@('-B',(Join-Path $PSScriptRoot 'ii_launcher_graphics.py'),'prepare','--run-name',$RunName,'--mode',$RaceDisplay,'--race-resolution',$RaceResolution,'--race-hud',$RaceHud,'--sky-mode',$SkyMode,'--race-distance',$RenderDistance,'--developer-mode',([int][bool]$DeveloperMode),'--vector-car',([int][bool]$VectorCar))
        if($CheatsJson){$prepareArguments+=@('--cheats',$CheatsJson)}
        $raw=& $PythonPath @prepareArguments
        if($LASTEXITCODE -ne 0){throw 'De deel-II-beeldsessie kon niet worden voorbereid.'}
        $graphicsPlan=$raw | ConvertFrom-Json
        $menuPath=Join-Path $graphicsPlan.base 'Menu.ps1';Assert-LauncherPath $menuPath
    }
    & $menuPath @menuArguments
    if($RunName){
        & $PythonPath -B (Join-Path $PSScriptRoot 'ii_launcher_graphics.py') sync --run-name $RunName --canonical-run $graphicsPlan.canonical_run | Out-Null
        if($LASTEXITCODE -ne 0){throw 'Voortgang blijft in de eigen beeldsessie behouden; terugschrijven is onderbroken.'}
    }
}finally{if($sourceLock){$sourceLock.Dispose()}}
