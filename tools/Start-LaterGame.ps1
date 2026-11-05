param(
    [Parameter(Mandatory=$true)][ValidateSet('a2racer4','vakantieracer')][string]$Game,
    [Alias('Profile')][ValidateSet('compat','hd1080','wide1080')][string]$GraphicsProfile='hd1080',
    [ValidatePattern('^[a-f0-9]{32}$')][string]$ControlToken,
    [string]$PythonPath,
    [switch]$UiResult,
    [switch]$CheckOnly,
    [ValidateRange(2,14400)][int]$Seconds=14400
)
$ErrorActionPreference='Stop'
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script=Join-Path $PSScriptRoot 'later_games_runtime.py'
$result=$null
$log=$null

function Resolve-LaterPython {
    $candidates = if (-not [string]::IsNullOrWhiteSpace($PythonPath)) { @($PythonPath) } else {
        @((Join-Path $workspace 'local/portable-runtime/python/python.exe'))
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return [IO.Path]::GetFullPath($candidate) }
    }
    throw 'De launcherbasis ontbreekt. Start Launcher.cmd om de runtime voor te bereiden.'
}

function Write-LaterUiResult([string]$Status,[string]$Message) {
    $text=if ($null -eq $Message) { '' } else { $Message }
    if ($text.Length -gt 1000) { $text=$text.Substring(0,1000) }
    [ordered]@{kind='later-game-session-result';game=$Game;profile=$GraphicsProfile;
        game_path=$(if($result){$result.game_path}else{$null});
        report=$(if($result){$result.report}else{$log});status=$Status;message=$text;
        game_started=[bool]($result -and $result.game_started);
        stop_requested=[bool]($result -and $result.stop_requested)} | ConvertTo-Json -Depth 4 -Compress
}

try {
    $python=Resolve-LaterPython
    $pin=(Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($pin -ne '9e27dbb6a9e4e8e02631056610a8c7cb638a2012d004a5de9fb288e2203c8933') { throw 'De gecontroleerde baselinecode is gewijzigd.' }
    $nativeScript=Join-Path $PSScriptRoot 'later_native.py'
    if ((Get-FileHash -LiteralPath $nativeScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'bda0dee39cf4ca1fe72f056c6f2338a5c91a02156e988c6dad0f4c25ac93eee4') { throw 'De gecontroleerde beeldcode is gewijzigd.' }
    $wideScript=Join-Path $PSScriptRoot 'later_games_widescreen.py'
    if ((Get-FileHash -LiteralPath $wideScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'cd2efc12096e7c7478398c70997318f6826d383d775a6d299f783bdb5238647b') { throw 'De gecontroleerde beeldcode is gewijzigd.' }
    $controlScript=Join-Path $PSScriptRoot 'later_game_control.py'
    if ((Get-FileHash -LiteralPath $controlScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'ae5886855f8e53e0f73ae4a28edf939e7ccc6c31916541996006953e79f8be78') { throw 'De gecontroleerde stopbediening is gewijzigd.' }
    $shutdownScript=Join-Path $PSScriptRoot 'later_mouse_shutdown.py'
    if ((Get-FileHash -LiteralPath $shutdownScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'c66c69540677497882398447721f7bbc0663313b25216dbfc6b428f8e6f9f3d5') { throw 'De gecontroleerde muisafsluiting is gewijzigd.' }
    if ($Game -eq 'vakantieracer') {
        $mouseScript=Join-Path $PSScriptRoot 'later_mouse_input.py'
        if ((Get-FileHash -LiteralPath $mouseScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne '28b5e47cd43bade34355d190f59d8cb7df93f4fa9dd0a562d39fe5bd1407f225') { throw 'De gecontroleerde muiscorrectie is gewijzigd.' }
        $joystickScript=Join-Path $PSScriptRoot 'later_joystick_input.py'
        if ((Get-FileHash -LiteralPath $joystickScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'f6fad55e92588de0b644aa105b52e2d05d2c8a64d4c5305fc338523afe41102e') { throw 'De gecontroleerde controllercorrectie is gewijzigd.' }
        $textureScript=Join-Path $PSScriptRoot 'later_vacation_texture_formats.py'
        if ((Get-FileHash -LiteralPath $textureScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne '8d671a1f867802df010da515692a72689b80f4bf9f4f08ea9f44d06601891859') { throw 'De gecontroleerde Vakantieracer-texturecorrectie is gewijzigd.' }
    } else {
        $mouseScript=Join-Path $PSScriptRoot 'later_iv_mouse_input.py'
        if ((Get-FileHash -LiteralPath $mouseScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne '86e61f8b022703241d02a7d49935a08e97a800d555b5e364e6b5c76bb931dea1') { throw 'De gecontroleerde IV-muiscorrectie is gewijzigd.' }
        $joystickScript=Join-Path $PSScriptRoot 'later_iv_joystick_input.py'
        if ((Get-FileHash -LiteralPath $joystickScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'b2e5b298f906d1ccbbc6567e5ab606bd0af9bd220b79f8569626414354dbd060') { throw 'De gecontroleerde IV-controllercorrectie is gewijzigd.' }
        $textureScript=Join-Path $PSScriptRoot 'later_iv_texture_formats.py'
        if ((Get-FileHash -LiteralPath $textureScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne '64bf8d14d4163cfc5798d5100061a4fdb281aff7413e660da561e3e647b01b95') { throw 'De gecontroleerde IV-texturecorrectie is gewijzigd.' }
        $probeScript=Join-Path $PSScriptRoot 'later_iv_vram_probe.py'
        if ((Get-FileHash -LiteralPath $probeScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne '94fee7bc7bf08755023594ca6847a88c5634cee6c08b544992ca70179b45e822') { throw 'De gecontroleerde IV-videogeheugengrens is gewijzigd.' }
    }
    $reportRoot=Join-Path $workspace 'reports/later-games-baseline-20261031'
    [IO.Directory]::CreateDirectory($reportRoot) | Out-Null
    $log=Join-Path $reportRoot ('desktop-'+$Game+'-'+[Guid]::NewGuid().ToString('N')+'.log')
    $arguments=@('-B',$script,'--game',$Game,'--profile',$GraphicsProfile,'--seconds',[string]$Seconds)
    if ($ControlToken) { $arguments+=@('--control-token',$ControlToken) }
    if ($CheckOnly) { $arguments+='--check-only' }
    & $python @arguments *> $log
    if ($LASTEXITCODE -ne 0) { throw ((Get-Content -LiteralPath $log -Tail 5) -join "`n") }
    $result=Get-Content -LiteralPath $log -Raw | ConvertFrom-Json
    if ($CheckOnly) {
        [ordered]@{game=$Game;profile=$GraphicsProfile;ready=$result.ready;game_started=$false;race_canvas_requested=$result.metadata.race_canvas_requested;render_resolution_requested=$result.metadata.render_resolution_requested;race_aspect_ratio_requested=$result.metadata.race_aspect_ratio_requested;widescreen_requested=$result.metadata.widescreen_requested;race_windowed_requested=$result.metadata.race_windowed_requested;wrapper_windowed_requested=$result.metadata.wrapper_windowed_requested;fullscreen_size_requested=$result.metadata.fullscreen_size_requested;wrapper_3d_resolution_requested=$result.metadata.wrapper_3d_resolution_requested;startup_behavior=$result.metadata.startup_behavior;runtime_verified=$result.metadata.runtime_verified} | ConvertTo-Json
        exit 0
    }
    $failedStage=@($result.stages | Where-Object { $_.guard.reason -eq 'exited' -and $null -ne $_.exit_code -and $_.exit_code -ne 0 })
    if ($failedStage.Count -gt 0) { throw ('De gamefase '+$failedStage[-1].stage+' stopte met code '+$failedStage[-1].exit_code+'. Rapport: '+$result.report) }
    if ($result.display_restore.verified -ne $true) { throw ('Schermherstel kon niet worden bevestigd. Rapport: '+$result.report) }
    if ($UiResult) {
        if ($result.guard.reason -eq 'exited') { Write-LaterUiResult 'closed' 'De gamesessie is afgesloten.' }
        elseif ($result.guard.reason -in @('emergency_hotkey','user_requested_stop','time_limit')) {
            Write-LaterUiResult 'stopped' ('De gamesessie is gestopt: '+$result.guard.reason+'.')
        } else { throw ('De eigen bewaker sloot de sessie af: '+$result.guard.reason+'. Rapport: '+$result.report) }
        exit 0
    }
    if ($result.guard.reason -notin @('exited','emergency_hotkey','user_requested_stop')) {
        Add-Type -AssemblyName PresentationFramework
        [Windows.MessageBox]::Show(('De eigen bewaker sloot de sessie af: '+$result.guard.reason+"`nRapport: "+$result.report),'A2 Revival - baselineproef','OK','Information') | Out-Null
    }
    exit 0
} catch {
    if ($UiResult) { Write-LaterUiResult 'error' $_.Exception.Message; exit 1 }
    if ($CheckOnly) { Write-Error $_; exit 1 }
    Add-Type -AssemblyName PresentationFramework
    $variant = if ($GraphicsProfile -eq 'hd1080') { 'Deze HD-basis behoudt de oorspronkelijke 4:3-verhouding.' } else { 'De 640 x 480-compatibiliteitsvariant stopte; de foutdetails staan hierboven.' }
    [Windows.MessageBox]::Show(($_.Exception.Message+"`n`n"+$variant),'A2 Revival - compatibiliteit','OK','Error') | Out-Null
    exit 1
}
