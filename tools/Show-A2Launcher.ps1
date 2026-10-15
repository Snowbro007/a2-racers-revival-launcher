#Requires -Version 5.1
param([string]$PythonPath, [string]$PowerShellPath, [switch]$CheckOnly, [string]$PreviewPath,
      [ValidateSet('play','options','logs','iii')][string]$PreviewPage = 'play',
      [ValidateSet('a2racer1','a2racer2')][string]$PreviewGame)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
$workspacePath = Split-Path -Parent $PSScriptRoot
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
$script:operation = $null; $script:worker = $null; $script:sessionName = $null
$script:catalog = $null; $script:settings = $null; $script:game = 'a2racer1'; $script:binding = $false
$script:initialized = $false; $script:bootstrapAttempted = $false
$script:releaseInitialized = $false
$script:installationScanAttempted = $false
$script:developmentRuntimes = [bool](($PythonPath -and $PowerShellPath) -or
    (Test-Path -LiteralPath (Join-Path $workspacePath 'local\launcher\runtimes.json')))

function New-LauncherProcess([string]$Executable, [string[]]$Arguments, [switch]$Detached) {
    Assert-LauncherPath $Executable -ReadOnlySystemPowerShell
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = ConvertTo-LauncherArguments $Arguments
    $info.WorkingDirectory = $workspacePath
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    if (-not $Detached) {
        $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = [Text.Encoding]::UTF8; $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    if (-not $process.Start()) { throw 'Achtergrondproces kon niet worden gestart.' }
    if ($Detached) { return @{ process=$process } }
    return @{ process=$process; output=$process.StandardOutput.ReadToEndAsync(); error=$process.StandardError.ReadToEndAsync() }
}

function Set-Status([string]$Title, [string]$Message) {
    $ui.StatusTitle.Text = $Title; $ui.StatusMessage.Text = $Message
}

function Set-CoverArtwork([Windows.Controls.Image]$Control, [string]$Path) {
    Assert-LauncherPath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'De launcherachtergrond ontbreekt. Pak de complete launcher opnieuw uit.' }
    # Load from this copy, then release the stream so the portable folder can move.
    $stream = [IO.File]::OpenRead($Path)
    try {
        $bitmap = New-Object Windows.Media.Imaging.BitmapImage
        $bitmap.BeginInit()
        $bitmap.CacheOption = [Windows.Media.Imaging.BitmapCacheOption]::OnLoad
        $bitmap.StreamSource = $stream
        $bitmap.EndInit()
        $bitmap.Freeze()
        $Control.Source = $bitmap
    } finally { $stream.Dispose() }
}

function Get-IIChoiceSupport([string]$Resolution,[string]$Hud) {
    if (-not $script:catalog -or $script:catalog.PSObject.Properties.Name -notcontains 'ii_graphics_support') {
        return [PSCustomObject]@{available=$true;reason=''}
    }
    return $script:catalog.ii_graphics_support.($Resolution).($Hud)
}

function Update-Buttons {
    $isIIIPage = $ui.Pages.SelectedIndex -eq 3
    for ($pageIndex = 0; $pageIndex -lt $ui.Pages.Items.Count; $pageIndex++) {
        $visible = if ($pageIndex -eq 3) { $isIIIPage } else { -not $isIIIPage }
        $ui.Pages.Items[$pageIndex].Visibility = if ($visible) { 'Visible' } else { 'Collapsed' }
    }
    $idle = -not $script:operation
    $running = $script:worker -and -not $script:worker.process.HasExited
    $ready = $script:catalog -and $script:catalog.games.($script:game).ready
    if ($ready -and $script:initialized -and $script:game -eq 'a2racer1') {
        $texture = $script:catalog.textures.([string]$ui.TextureChoice.SelectedItem.Tag)
        $display = $script:catalog.displays.([string]$ui.ResolutionChoice.SelectedItem.Tag)
        $menu = $script:catalog.menus.([string]$ui.MenuChoice.SelectedItem.Tag)
        $ready = $texture.available -and $menu.available -and (Test-VisibleLauncherChoice $texture) -and (Test-VisibleLauncherChoice $display) -and
            -not (Get-TextureCompatibilityNote $texture (Current-Preferences))
    }
    if($script:catalog -and $script:initialized -and $script:game -eq 'a2racer2'){
        $ready=$script:catalog.ii_menus.([string]$ui.IIMenuChoice.SelectedItem.Tag).available
        if ($ui.IIMenuChoice.SelectedItem.Tag -eq 'revival' -and $ui.IIRaceDisplayChoice.SelectedItem.Tag -eq 'widescreen') {
            $ready=$ready -and (Get-IIChoiceSupport ([string]$ui.IIResolutionChoice.SelectedItem.Tag) ([string]$ui.IIHudChoice.SelectedItem.Tag)).available
        }
    }
    $ui.PlayButton.IsEnabled = [bool]($idle -and -not $running -and $ready)
    foreach ($name in @('SaveOptions','ResetOptions','GameOne','GameTwo','RefreshState','ImportGame','ChooseOptions','IntroChoice','DebugChoice')) {
        $ui[$name].IsEnabled = [bool]($idle -and $script:initialized)
    }
    foreach ($name in @('DetectInstallations','ChooseInstallation','GetGame','InstallationChoice','PrepareGame')) {
        $ui[$name].IsEnabled = [bool]($idle -and -not $running -and $script:initialized)
    }
    $ui.LinkInstallation.IsEnabled = [bool]($idle -and -not $running -and $script:initialized -and $ui.InstallationChoice.SelectedItem)
    foreach ($name in @('GraphicsChoice','ResolutionChoice','DashboardChoice','FpsChoice','DistanceChoice','ObjectDistanceChoice','TextureChoice','MenuChoice','HorizonChoice','FocusRecoveryChoice')) {
        $ui[$name].IsEnabled = [bool]($idle -and $script:initialized -and $script:game -eq 'a2racer1')
    }
    $ui.RecommendedOptions.IsEnabled = [bool]($idle -and $script:initialized -and $script:game -in @('a2racer1','a2racer2'))
    foreach ($name in @('OriginalProfile','MaxProfile')) {
        $ui[$name].IsEnabled = $ui.RecommendedOptions.IsEnabled
        $ui[$name].Visibility = 'Visible'
    }
    if ($script:game -eq 'a2racer2') { $ui.MaxProfile.IsEnabled=$ui.MaxProfile.IsEnabled -and (Get-IIChoiceSupport '4k' 'hd').available }
    $ui.IIMenuChoice.IsEnabled=[bool]($idle -and $script:initialized -and $script:game -eq 'a2racer2')
    $ui.IIRaceDisplayChoice.IsEnabled=[bool]($idle -and $script:initialized -and $script:game -eq 'a2racer2' -and $ui.IIMenuChoice.SelectedItem.Tag -eq 'revival')
    foreach($name in @('IIResolutionChoice','IIHudChoice','IISkyChoice','IIDistanceChoice')){
        $ui[$name].IsEnabled=[bool]($ui.IIRaceDisplayChoice.IsEnabled -and $ui.IIRaceDisplayChoice.SelectedItem.Tag -eq 'widescreen')
    }
    foreach($item in $ui.IIHudChoice.Items){
        $support=Get-IIChoiceSupport ([string]$ui.IIResolutionChoice.SelectedItem.Tag) ([string]$item.Tag)
        $item.IsEnabled=($item.Tag -eq 'native' -or $ui.IIResolutionChoice.SelectedItem.Tag -ne '720p') -and $support.available
        if (-not $support.available) { $item.ToolTip='Deze HUD-variant is op deze pc nog niet voorbereid.' }
    }
    if($script:initialized -and $script:game -eq 'a2racer2' -and $ui.IIMenuChoice.SelectedItem.Tag -eq 'revival'){
        $ui.IntroChoice.IsEnabled=$false;$ui.DebugChoice.IsEnabled=$false
    }
    if ($script:initialized -and $script:game -eq 'a2racer1' -and $ui.GraphicsChoice.SelectedItem.Tag -eq 'software-640') {
        foreach ($name in @('DistanceChoice','ObjectDistanceChoice','FocusRecoveryChoice')) { $ui[$name].IsEnabled = $false }
    }
    $ui.GameThree.IsEnabled = [bool]($idle -and $script:initialized)
    $ui.IIITourChoice.IsEnabled = [bool]($idle -and $script:initialized)
    $ui.IIIProfileChoice.IsEnabled = [bool]($idle -and $script:initialized)
    $ui.IIIChooseInstallation.IsEnabled = [bool]($idle -and -not $running -and $script:initialized)
    if ($ui.Pages.SelectedIndex -eq 3) {
        $iiiReady = $false
        $iiiHasMap = $false
        if ($script:catalog -and $ui.IIITourChoice.SelectedItem) {
            $tourState = $script:catalog.iii_preparation.tours.([string]$ui.IIITourChoice.SelectedItem.Tag)
            $iiiHasMap = ($tourState.PSObject.Properties.Name -contains 'launch_ready') -and $tourState.launch_ready
            if ($ui.IIIProfileChoice.SelectedItem) {
                $profileState = $tourState.profiles.([string]$ui.IIIProfileChoice.SelectedItem.Tag)
                $iiiReady = $profileState -and $profileState.available
            }
        }
        $ui.PlayButton.IsEnabled = [bool]($idle -and -not $running -and $iiiReady)
        $ui.PlayButton.Content = if ($iiiReady) { 'Start deze variant' } else { 'Gamemap nodig' }
        $ui.PlayNote.Text = if ($iiiReady) { 'Origineel menu en race · lokale bestanden · geen cd-mount.' } else { 'Deel III is voorbereid; er wordt nog geen game gestart.' }
        $ui.GameTitle.Text = 'A2 Racer III'
        $ui.GameSubtitle.Text = 'Europa Tour · Tour 1 en Tour 2'
        $ui.GameThree.BorderBrush = '#FFDD4A'
        $ui.GameOne.BorderBrush = '#356E95'; $ui.GameTwo.BorderBrush = '#356E95'
        $ui.GameOneSelected.Visibility = 'Collapsed'; $ui.GameTwoSelected.Visibility = 'Collapsed'
        if (-not $running -and -not $script:operation -and $ui.StatusTitle.Text -notin @('Start onderbroken','Deel III kon niet starten','Deel III kon niet koppelen','Kon niet doorgaan')) {
            if ($iiiReady) { Set-Status 'Deel III voorbereid' 'Start zonder cd beschikbaar; de speeltest volgt apart.' }
            elseif (-not $iiiHasMap) { Set-Status 'Gamemap nodig' 'Kies eerst de volledige gamemap van deze tour.' }
            else { Set-Status 'Beeldvariant niet beschikbaar' $ui.IIIProfileNote.Text }
        }
    } else { $ui.GameThree.BorderBrush = '#356E95' }
}

function Update-IIIStatus {
    if (-not $script:catalog -or -not $ui.IIITourChoice.SelectedItem) { return }
    $tour = [string]$ui.IIITourChoice.SelectedItem.Tag
    $tourState = $script:catalog.iii_preparation.tours.($tour)
    $ui.IIIStatus.Text = $tourState.reason
    $ui.IIITourOverview.Text = 'Tour ' + $tour
    $ui.IIIReadyOverview.Text = if (($tourState.PSObject.Properties.Name -contains 'launch_ready') -and $tourState.launch_ready) { 'Klaar voor start' } else { 'Niet beschikbaar' }
    if ($ui.IIIProfileChoice.SelectedItem) {
        $profile = [string]$ui.IIIProfileChoice.SelectedItem.Tag
        $profileState = $tourState.profiles.($profile)
        $ui.IIIResolutionOverview.Text = if ($profile -eq 'fullhd-skyoff') { '1920 × 1080' } else { 'Origineel' }
        $ui.IIIProfileNote.Text = if ($profileState) { [string]$profileState.reason } else { 'Koppel eerst de gamemap van deze tour.' }
    }
}

function Add-Choice($Control, [string]$Label, [string]$Value, [bool]$Enabled = $true) {
    $item = New-Object Windows.Controls.ComboBoxItem
    $item.Content = $Label; $item.Tag = $Value
    $item.IsEnabled = $Enabled
    $null = $Control.Items.Add($item)
}

function Select-Choice($Control, [string]$Value) {
    foreach ($item in $Control.Items) {
        if ([string]$item.Tag -eq $Value) { $Control.SelectedItem = $item; return }
    }
    throw ('Deze launcherkeuze ontbreekt: ' + $Value)
}

function Test-VisibleLauncherChoice($Entry) {
    # Older catalogs did not carry this presentation-only marker. Historical
    # preferences and frozen plans remain valid in the model.
    return -not ($Entry.PSObject.Properties.Name -contains 'launcher_visible' -and -not $Entry.launcher_visible)
}

function Get-TextureCompatibilityNote($Texture, $Preferences) {
    if (-not ($Texture.PSObject.Properties.Name -contains 'hud_profile')) { return '' }
    $notes = @()
    if ($Preferences.display_profile -notin @($Texture.hud_displays)) {
        $notes += 'Kies een HD-resolutie voor dit HD-pakket.'
    }
    if (-not $Preferences.race_focus_recovery) {
        $notes += 'Zet Alt+Tab-herstel aan voor dit HD-pakket.'
    }
    return $notes -join ' '
}

function Set-ResolutionChoices([string]$Graphics, [string]$Preferred) {
    $ui.ResolutionChoice.Items.Clear()
    foreach ($entry in $script:catalog.displays.PSObject.Properties) {
        if (-not $entry.Value.native_graphics -or $entry.Value.native_graphics -eq $Graphics) {
            if (Test-VisibleLauncherChoice $entry.Value) {
                Add-Choice $ui.ResolutionChoice $entry.Value.label $entry.Name
            } elseif ($entry.Name -eq $Preferred) {
                Add-Choice $ui.ResolutionChoice ('Vorige keuze: ' + $entry.Value.label + ' · vervallen') $entry.Name $false
            }
        }
    }
    $match = @($ui.ResolutionChoice.Items | Where-Object { $_.Tag -eq $Preferred })
    if ($match.Count -gt 0) { $ui.ResolutionChoice.SelectedItem = $match[0] }
    else { Select-Choice $ui.ResolutionChoice 'original' }
}

function Set-TextureChoices([string]$Graphics, [string]$Preferred) {
    $ui.TextureChoice.Items.Clear()
    foreach ($entry in $script:catalog.textures.PSObject.Properties) {
        $visible = Test-VisibleLauncherChoice $entry.Value
        if (-not $visible -and $entry.Name -ne $Preferred) { continue }
        $enabled = [bool]($visible -and $entry.Value.available -and ($entry.Name -eq 'original' -or $Graphics -eq 'accelerated-640'))
        $label = [string]$entry.Value.label
        if (-not $visible) { $label = 'Vorige keuze: ' + $label + ' · vervallen' }
        if (-not $entry.Value.available) { $label += ' · niet beschikbaar' }
        Add-Choice $ui.TextureChoice $label $entry.Name $enabled
    }
    # Retain a missing or retired saved choice without silently replacing it.
    Select-Choice $ui.TextureChoice $Preferred
}

function Update-GraphicsChoices {
    if (-not $script:initialized -or $script:binding -or $script:game -ne 'a2racer1') { return }
    $previous = [string]$ui.ResolutionChoice.SelectedItem.Tag
    $texture = [string]$ui.TextureChoice.SelectedItem.Tag
    $script:binding = $true
    try {
        $graphics = [string]$ui.GraphicsChoice.SelectedItem.Tag
        Set-ResolutionChoices $graphics $previous
        if ($graphics -eq 'software-640') {
            Select-Choice $ui.DistanceChoice 'original'; Select-Choice $ui.ObjectDistanceChoice 'original'
            $ui.FocusRecoveryChoice.IsChecked = $false
            $texture = 'original'
        }
        Set-TextureChoices $graphics $texture
    }
    finally { $script:binding = $false }
    Update-Summary; Update-Buttons
}

function Current-Preferences {
    if ($script:game -eq 'a2racer2') {
        return [PSCustomObject]@{ graphics='native'; dashboard=$null; fps=0; intro=[bool]$ui.IntroChoice.IsChecked; debug=[bool]$ui.DebugChoice.IsChecked;menu_profile=[string]$ui.IIMenuChoice.SelectedItem.Tag;race_display=[string]$ui.IIRaceDisplayChoice.SelectedItem.Tag;
            race_resolution=[string]$ui.IIResolutionChoice.SelectedItem.Tag;race_hud=[string]$ui.IIHudChoice.SelectedItem.Tag;
            sky_mode=[string]$ui.IISkyChoice.SelectedItem.Tag;race_distance=[string]$ui.IIDistanceChoice.SelectedItem.Tag }
    }
    return [PSCustomObject]@{ graphics=[string]$ui.GraphicsChoice.SelectedItem.Tag; dashboard=[bool]$ui.DashboardChoice.IsChecked;
        display_profile=[string]$ui.ResolutionChoice.SelectedItem.Tag;
        camera_profile=[string]$script:catalog.displays.([string]$ui.ResolutionChoice.SelectedItem.Tag).camera_profile;
        render_distance_profile=[string]$ui.DistanceChoice.SelectedItem.Tag;
        object_distance_profile=[string]$ui.ObjectDistanceChoice.SelectedItem.Tag;
        texture_profile=[string]$ui.TextureChoice.SelectedItem.Tag;
        menu_profile=[string]$ui.MenuChoice.SelectedItem.Tag;
        native_horizon=[int]$ui.HorizonChoice.SelectedItem.Tag; race_focus_recovery=[bool]$ui.FocusRecoveryChoice.IsChecked;
        fps=[int]$ui.FpsChoice.SelectedItem.Tag; intro=[bool]$ui.IntroChoice.IsChecked; debug=[bool]$ui.DebugChoice.IsChecked }
}

function Get-ResolutionOverview([string]$Graphics, [string]$DisplayProfile) {
    switch ($DisplayProfile) {
        'original' { if ($Graphics -eq 'software-640') { return '640 × 480 · 4:3' } else { return 'Origineel · 4:3' } }
        'borderless-4-3' { return '640 × 480 · 4:3' }
        'hd-1280x960' { return '1280 × 960 · 4:3' }
        'hd-1280x960-fake' { return '1280 × 960 · 4:3' }
        'hd-1440x1080' { return '1440 × 1080 · 4:3' }
        'hd-1920x1440' { return '1920 × 1440 · 4:3' }
        'hd-2880x2160' { return '2880 × 2160 · 4:3' }
        'hd-1920x1080-camera' { return '1920 × 1080 · 16:9' }
        'hd-3840x2160-camera' { return '3840 × 2160 · 16:9' }
        default { throw 'Onbekende resolutiekeuze.' }
    }
}

function Update-Summary {
    if (-not $script:initialized -or $script:binding) { return }
    $preferences = Current-Preferences
    $notes = @()
    if ($script:game -eq 'a2racer1') {
        $display = $script:catalog.displays.($preferences.display_profile)
        $distance = $script:catalog.render_distances.($preferences.render_distance_profile)
        $objectDistance = $script:catalog.object_distances.($preferences.object_distance_profile)
        $texture = $script:catalog.textures.($preferences.texture_profile)
        $menu = $script:catalog.menus.($preferences.menu_profile)
        $ui.OverviewResolution.Text = Get-ResolutionOverview $preferences.graphics $preferences.display_profile
        $ui.OverviewFps.Text = [string]$preferences.fps + ' FPS'
        $ui.OverviewDistance.Text = ([string]$distance.label -split '·')[0].Trim()
        $ui.OverviewObjects.Text = if ($preferences.object_distance_profile -eq 'original') { 'Origineel' } else { 'Alle geladen' }
        $ui.PlaySummary.Text = $(if ($preferences.dashboard) { 'Dashboard aan' } else { 'Dashboard uit' }) +
            ' · ' + $(if ($preferences.intro) { 'Intro aan' } else { 'Intro overslaan' }) + ' · ' + $texture.label + ' · Menu: ' + $menu.label
        $ui.PlayNote.Text = 'Je start A2 Racer I met onderstaande keuzes.'
        $ui.GraphicsNote.Text = $script:catalog.graphics.($preferences.graphics).description
        $ui.ResolutionNote.Text = $display.description
        # Resolution choices already describe their paired camera. Avoid a
        # second copy of the same widescreen limitation below that choice.
        $ui.CameraNote.Text = ''
        $ui.CameraNote.Visibility = 'Collapsed'
        $ui.DistanceNote.Text = $distance.description
        $ui.ObjectDistanceNote.Text = $objectDistance.description
        $ui.TextureNote.Text = $texture.description
        $textureCompatibility = Get-TextureCompatibilityNote $texture $preferences
        if ($textureCompatibility) {
            $ui.TextureNote.Text += ' ' + $textureCompatibility
            $notes += $textureCompatibility
        }
        $ui.MenuNote.Text = $menu.description
        if (-not $menu.available) {
            $ui.MenuNote.Text += ' ' + $menu.reason
            $notes += $menu.reason
        }
        if (-not (Test-VisibleLauncherChoice $texture)) {
            $notes += 'Deze oude texturekeuze is vervallen. Kies Origineel of HD textures om te spelen.'
        }
        if (-not $texture.available) {
            $ui.TextureNote.Text += ' ' + $texture.reason
            $notes += $texture.reason
        }
        $ui.FocusRecoveryNote.Text = 'Herstel bij focuswissels. Werkt in de speelbasis; Alt+Tab met het nieuwste HD-pakket moet nog worden bevestigd.'
        if ($preferences.graphics -eq 'software-640') {
            $notes += 'Softwareweergave geselecteerd. Kies Aanbevolen instellingen voor de 3D-speelbasis.'
            $ui.DistanceNote.Text = 'Extra zichtafstand is beschikbaar met de 3D Accelerator.'
            $ui.ObjectDistanceNote.Text = 'Deze objectafstand is beschikbaar met de 3D Accelerator.'
            $ui.FocusRecoveryNote.Text = 'Alt+Tab-herstel is beschikbaar met de 3D Accelerator.'
        }
        if ($preferences.object_distance_profile -ne 'original') {
            $notes += 'Deze objectafstand is optioneel; de ronde rand van de map kan zichtbaar worden.'
        }
        if ($preferences.display_profile -eq 'hd-1280x960-fake') {
            $notes += 'Deze oude schermproef is vervallen. Kies een andere resolutie om te spelen.'
        }
        if ($preferences.fps -eq 30) {
            $ui.FpsNote.Text = '30 FPS is een alternatief. De game kan sneller lopen; 20 FPS blijft aanbevolen.'
            $notes += '30 FPS kan het spel sneller laten lopen.'
        } else {
            $ui.FpsNote.Text = '20 FPS is aanbevolen. 30 FPS is beschikbaar als alternatief.'
        }
    } else {
        $wide = $preferences.menu_profile -eq 'revival' -and $preferences.race_display -eq 'widescreen'
        $ui.OverviewResolution.Text = if ($wide) { [string]$ui.IIResolutionChoice.SelectedItem.Content } elseif ($preferences.menu_profile -eq 'revival') { '640 × 480 · 4:3' } else { 'Via spelmenu' }
        $ui.OverviewFps.Text = if ($preferences.menu_profile -eq 'revival') { '60 FPS' } else { 'Origineel tempo' }
        $ui.OverviewDistance.Text = if (-not $wide -or $preferences.race_distance -eq 'auto') { 'Origineel' } else { $preferences.race_distance + ' baanstukken' }
        $ui.OverviewObjects.Text = if (-not $wide -or $preferences.race_hud -eq 'native') { 'Origineel' } elseif ($preferences.race_hud -eq 'hd') { 'HD HUD' } else { 'HD HUD + radar' }
        $iiMenu=$script:catalog.ii_menus.($preferences.menu_profile)
        $ui.PlaySummary.Text=$iiMenu.label
        if($preferences.menu_profile -eq 'revival'){
            if($preferences.race_display -eq 'widescreen'){
                $ui.PlaySummary.Text+=' · '+$ui.IIResolutionChoice.SelectedItem.Content+' · '+$ui.IIHudChoice.SelectedItem.Content+"`n"+$ui.IISkyChoice.SelectedItem.Content+' · '+$ui.IIDistanceChoice.SelectedItem.Content+' · 60 FPS'
            }else{$ui.PlaySummary.Text+=' · 4:3 · 640 × 480 · originele HUD'}
        }
        $ui.PlayNote.Text=if($preferences.menu_profile -eq 'revival'){'Je gekozen beeldopties gelden bij de volgende start. Speler, auto, baan, audio en bediening kies je in het spelmenu.'}else{$iiMenu.description}
        $ui.IIMenuNote.Text=$iiMenu.description
        $ui.IIMenuNote.Visibility=if($preferences.menu_profile -eq 'revival'){'Collapsed'}else{'Visible'}
        if ($wide -and $preferences.race_resolution -eq '4k' -and $preferences.race_hud -eq 'hd' -and $preferences.sky_mode -eq 'flat' -and $preferences.race_distance -eq '60') {
            $notes += 'De MAX-combinatie moet nog worden speelgetest.'
        }
        if ($wide -and $preferences.race_hud -eq 'hd-map') { $notes += 'Uitgebreide radar en meldingen zijn een proef.' }
        if(-not $iiMenu.available){$notes+=$iiMenu.reason}
        if ($preferences.menu_profile -eq 'revival' -and $preferences.race_display -eq 'widescreen' -and -not (Get-IIChoiceSupport $preferences.race_resolution $preferences.race_hud).available) {
            $notes+='Deze HUD-variant is hier nog niet voorbereid. Kies Originele HUD of bereid de game eerst voor.'
        }
        $ui.GraphicsNote.Text = 'Beeldopties wijzig je in het originele deel-II-menu.'
        $ui.ResolutionNote.Text = 'Deel II gebruikt zijn eigen oorspronkelijke instellingen.'
        $ui.CameraNote.Text = ''
        $ui.CameraNote.Visibility = 'Collapsed'
        $ui.DistanceNote.Text = 'Extra zichtafstand voor deel II is nog niet onderzocht.'
        $ui.ObjectDistanceNote.Text = 'Objectafstand voor deel II is nog niet onderzocht.'
        $ui.TextureNote.Text = 'HD-wegtextures zijn voorlopig uitsluitend beschikbaar voor deel I.'
        $ui.FocusRecoveryNote.Text = 'Alt+Tab-herstel voor deel II is in deze launcher nog niet beschikbaar.'
    }
    $ui.SelectionNote.Text = $notes -join ' '
    $ui.SelectionNote.Visibility = if ($notes.Count) { 'Visible' } else { 'Collapsed' }
    if ($preferences.debug -and ($script:game -eq 'a2racer1' -or $preferences.menu_profile -eq 'original')) {
        $ui.PlayNote.Text = 'Diagnose staat aan: de game stopt na maximaal 3 minuten of eerder bij de loglimiet.'
    }
}

function Select-Game([string]$GameName) {
    if (-not $script:settings) { return }
    $ui.GameOneAvailability.Text = if ($script:catalog.games.a2racer1.ready) { 'Klaar om te spelen' } else { 'Eigen game nodig' }
    $ui.GameTwoAvailability.Text = if ($script:catalog.games.a2racer2.ready) { 'Klaar om te spelen' } elseif ($script:catalog.games.a2racer2.PSObject.Properties.Name -contains 'source_ready' -and $script:catalog.games.a2racer2.source_ready) { 'Game voorbereiden' } else { 'Eigen game nodig' }
    if ($script:initialized -and -not $script:binding) { $script:settings.games.($script:game) = Current-Preferences }
    $script:binding = $true; $script:game = $GameName
    $preferences = $script:settings.games.($GameName)
    $one = $GameName -eq 'a2racer1'
    $ui.GameTitle.Text = if ($one) { 'A2 Racer I' } else { 'A2 Racer II' }
    $ui.GameSubtitle.Text = if ($one) { 'Graphics, gameplay en texture packs' } else { 'Graphics, gameplay en HUD' }
    $ui.OptionsGameTitle.Text = 'Instellingen · ' + $ui.GameTitle.Text
    $ui.PlayButton.Content = 'Speel ' + $ui.GameTitle.Text
    $ui.GameOneSelected.Visibility = if ($one) { 'Visible' } else { 'Collapsed' }
    $ui.GameTwoSelected.Visibility = if ($one) { 'Collapsed' } else { 'Visible' }
    $ui.IOptionsPanel.Visibility = if ($one) { 'Visible' } else { 'Collapsed' }
    $ui.IIOptionsNotice.Visibility = if ($one) { 'Collapsed' } else { 'Visible' }
    $ui.IOverviewPanel.Visibility = 'Visible'
    $ui.IIOverviewPanel.Visibility = 'Collapsed'
    $ui.OverviewDetailLabel.Text = if ($one) { 'OBJECTAFSTAND' } else { 'HUD' }
    $ui.RecommendedOptions.Visibility = 'Visible'
    $ui.OriginalProfile.ToolTip = if ($one) { '640 × 480, 20 FPS, originele zichtafstand, horizon, textures en menu.' } else { 'Klassieke 640 × 480-race, originele HUD en wereld via het Revival-menu.' }
    $ui.RecommendedOptions.ToolTip = if ($one) { '1080p, 20 FPS, verder wegzicht, horizon uit en dashboard aan. HD blijft optioneel.' } else { 'Full HD (1920 × 1080), 60 FPS, 60 baanstukken, egale lucht en originele HUD via het Revival-menu.' }
    $ui.MaxProfile.ToolTip = if ($one) { '4K, 30 FPS, alle geladen objecten, HD-textures en HD-menu. Meer belasting; de ronde maprand kan zichtbaar zijn.' } else { '4K, 60 FPS, 60 baanstukken, egale lucht en HD HUD. Deze combinatie moet nog worden speelgetest.' }
    $ui.GameOne.BorderBrush = if ($one) { '#FFDD4A' } else { '#356E95' }
    $ui.GameTwo.BorderBrush = if ($one) { '#356E95' } else { '#FFDD4A' }
    foreach ($name in @('GraphicsChoice','ResolutionChoice','FpsChoice','DistanceChoice','ObjectDistanceChoice','TextureChoice','MenuChoice','HorizonChoice')) { $ui[$name].Items.Clear() }
    if ($one) {
        foreach ($entry in $script:catalog.graphics.PSObject.Properties) { Add-Choice $ui.GraphicsChoice $entry.Value.label $entry.Name }
        Add-Choice $ui.FpsChoice '20 FPS · aanbevolen' '20'; Add-Choice $ui.FpsChoice '30 FPS · alternatief' '30'
        foreach ($entry in $script:catalog.render_distances.PSObject.Properties) { Add-Choice $ui.DistanceChoice $entry.Value.label $entry.Name }
        foreach ($entry in $script:catalog.object_distances.PSObject.Properties) { Add-Choice $ui.ObjectDistanceChoice $entry.Value.label $entry.Name }
        Add-Choice $ui.HorizonChoice 'Game-instelling behouden' '-1'; Add-Choice $ui.HorizonChoice 'Uit · aanbevolen' '0'; Add-Choice $ui.HorizonChoice 'Aan · originele achtergrond' '1'
        Select-Choice $ui.GraphicsChoice $preferences.graphics
        Set-ResolutionChoices $preferences.graphics $preferences.display_profile
        Set-TextureChoices $preferences.graphics $preferences.texture_profile
        foreach ($entry in $script:catalog.menus.PSObject.Properties) { Add-Choice $ui.MenuChoice $entry.Value.label $entry.Name $entry.Value.available }
        Select-Choice $ui.MenuChoice $preferences.menu_profile
        Select-Choice $ui.DistanceChoice $preferences.render_distance_profile
        Select-Choice $ui.ObjectDistanceChoice $preferences.object_distance_profile
        Select-Choice $ui.HorizonChoice ([string]$preferences.native_horizon)
        $ui.FocusRecoveryChoice.IsChecked = $preferences.race_focus_recovery
    } else {
        Add-Choice $ui.GraphicsChoice 'Originele instellingen' 'native'
        Add-Choice $ui.FpsChoice 'Origineel tempo' '0'; Add-Choice $ui.ResolutionChoice 'Via het originele game-menu' 'original'
        Add-Choice $ui.DistanceChoice 'Origineel' 'original'; Add-Choice $ui.ObjectDistanceChoice 'Origineel' 'original'
        Add-Choice $ui.TextureChoice 'Originele textures' 'original'
        Add-Choice $ui.MenuChoice 'Origineel' 'original'
        Add-Choice $ui.HorizonChoice 'Via het originele game-menu' '-1'
        foreach ($name in @('GraphicsChoice','ResolutionChoice','DistanceChoice','ObjectDistanceChoice','TextureChoice','MenuChoice','HorizonChoice')) { $ui[$name].SelectedIndex = 0 }
        $ui.FocusRecoveryChoice.IsChecked = $false
        $ui.IIMenuChoice.Items.Clear()
        foreach($entry in $script:catalog.ii_menus.PSObject.Properties){Add-Choice $ui.IIMenuChoice $entry.Value.label $entry.Name $entry.Value.available}
        Select-Choice $ui.IIMenuChoice $preferences.menu_profile
        $ui.IIRaceDisplayChoice.Items.Clear()
        Add-Choice $ui.IIRaceDisplayChoice 'Breedbeeld · 16:9' 'widescreen'
        Add-Choice $ui.IIRaceDisplayChoice 'Klassiek 4:3 · 640 × 480' 'classic'
        Select-Choice $ui.IIRaceDisplayChoice $preferences.race_display
        $iiChoices=@{
            IIResolutionChoice=@(@('1280 × 720 · 16:9','720p'),@('1920 × 1080 · 16:9','1080p'),@('3840 × 2160 · 16:9','4k'));
            IIHudChoice=@(@('Originele HUD','native'),@('HD HUD · tekst en kaders','hd'),@('HD HUD + radar en meldingen · proef','hd-map'));
            IISkyChoice=@(@('Originele horizon en lucht','original'),@('Horizon uit · wolken behouden','horizon-off'),@('Egale lucht · aanbevolen','flat'));
            IIDistanceChoice=@(@('Origineel · automatische afstand','auto'),@('Ver vooruit · 50 baanstukken','50'),@('Maximaal · 60 baanstukken · aanbevolen','60'))}
        foreach($name in $iiChoices.Keys){$ui[$name].Items.Clear();foreach($choice in $iiChoices[$name]){Add-Choice $ui[$name] $choice[0] $choice[1]}}
        Select-Choice $ui.IIResolutionChoice $preferences.race_resolution
        Select-Choice $ui.IIHudChoice $preferences.race_hud
        Select-Choice $ui.IISkyChoice $preferences.sky_mode
        Select-Choice $ui.IIDistanceChoice $preferences.race_distance
    }
    Select-Choice $ui.FpsChoice ([string]$preferences.fps)
    $ui.DashboardChoice.IsChecked = [bool]$preferences.dashboard; $ui.IntroChoice.IsChecked = $preferences.intro; $ui.DebugChoice.IsChecked = $preferences.debug
    $ui.DashboardChoice.Content = if ($one) { 'Dashboard aan · aanbevolen' } else { 'Dashboard: via de originele gameopties' }
    $ui.IntroChoice.Content = if ($one) { 'Originele intro afspelen' } else { 'Originele films afspelen' }
    $ui.FpsNote.Text = if ($one) { '20 FPS is aanbevolen; 30 FPS is een alternatief.' } else { 'Deel II gebruikt zijn eigen tempo.' }
    $sourceReady = $script:catalog.games.($GameName).ready
    if (-not $one -and $script:catalog.games.a2racer2.PSObject.Properties.Name -contains 'source_ready') { $sourceReady = $script:catalog.games.a2racer2.source_ready }
    $ui.ImportGame.Visibility = if (-not $sourceReady) { 'Visible' } else { 'Collapsed' }
    $needsII = -not $one -and -not $script:catalog.ii_menus.revival.available
    $ui.InstallationPanel.Visibility = if ($ui.ImportGame.Visibility -eq 'Visible' -or $needsII) { 'Visible' } else { 'Collapsed' }
    if (-not $sourceReady) {
        $ui.WelcomeTitle.Text = 'Eigen gamebestanden nodig'
        $ui.WelcomeHint.Text = 'Kies hieronder Gamemap kiezen of Gamearchief importeren voor je eigen ' + $ui.GameTitle.Text + '. Daarna kun je spelen.'
    } elseif ($needsII) {
        $ui.WelcomeTitle.Text = 'Maak A2 Racer II klaar'
        $ui.WelcomeHint.Text = 'Je gamebestanden zijn gevonden. Klik hieronder op Game voorbereiden; kies daarna Aanbevolen en Spelen.'
    } else {
        $ui.WelcomeTitle.Text = 'Klaar voor de start'
        $ui.WelcomeHint.Text = 'Je gamebestanden staan klaar. Klik op Speel ' + $ui.GameTitle.Text + '. Instellingen aanpassen kan later.'
    }
    $ui.InstallationTitle.Text = if ($needsII -and $sourceReady) { 'Stap 1 · Bereid A2 Racer II voor' } else { 'Stap 1 · Koppel je eigen ' + $ui.GameTitle.Text }
    $ui.GetGame.Content = if ($one) { 'Game verkrijgen' } else { 'Game verkrijgen ↗' }
    $ui.GetGame.ToolTip = if ($one) { 'Uitleg over het koppelen van je eigen gamekopie.' } else { 'Opent My Abandonware in je browser. Toestemming voor deze externe download is niet bevestigd.' }
    $ui.GetGame.Visibility = if (-not $sourceReady) { 'Visible' } else { 'Collapsed' }
    $ui.ChooseInstallation.Visibility = if (-not $sourceReady) { 'Visible' } else { 'Collapsed' }
    $ui.DetectInstallations.Visibility = if ($one -and -not $sourceReady) { 'Visible' } else { 'Collapsed' }
    $ui.PrepareGame.Visibility = if ($needsII -and $sourceReady) { 'Visible' } else { 'Collapsed' }
    if ($one) {
        $ui.InstallationNote.Text = 'Kies de volledige Nederlandse A2 Racer I-gamemap of importeer je eigen gamearchief.'
    } else {
        $ui.InstallationChoice.Visibility='Collapsed';$ui.LinkInstallation.Visibility='Collapsed'
        $ui.InstallationNote.Text=if($sourceReady){'Gamebestanden zijn gevonden. Kies Game voorbereiden voor de lokale speelkopie.'}else{'Kies de volledige Nederlandse A2 Racer II-gamemap, inclusief DATA. De oorspronkelijke bestanden blijven intact.'}
    }
    $script:initialized = $true; $script:binding = $false
    Update-Summary; Update-Buttons
    if (-not $script:worker) {
        $reason=if($one -or $preferences.menu_profile -eq 'original'){$script:catalog.games.($GameName).reason}else{$script:catalog.ii_menus.($preferences.menu_profile).reason}
        $statusTitle = if (-not $sourceReady) { 'Gamebestanden nodig' } elseif ($needsII) { 'Game voorbereiden' } else { 'Klaar voor de start' }
        Set-Status $statusTitle $reason
    }
}

function Preference-Arguments([string]$Action) {
    $preferences = Current-Preferences
    $dashboard = if ($null -eq $preferences.dashboard) { '-1' } elseif ($preferences.dashboard) { '1' } else { '0' }
    $arguments = @($Action, '--game', $script:game, '--graphics', $preferences.graphics, '--fps', [string]$preferences.fps,
        '--dashboard', $dashboard, '--intro', [string][int]$preferences.intro, '--debug', [string][int]$preferences.debug)
    if ($script:game -eq 'a2racer1') {
        $arguments += @('--display-profile', $preferences.display_profile, '--camera-profile', $preferences.camera_profile,
            '--render-distance-profile', $preferences.render_distance_profile, '--object-distance-profile', $preferences.object_distance_profile,
            '--texture-profile', $preferences.texture_profile,
            '--menu-profile', $preferences.menu_profile,
            '--native-horizon', [string]$preferences.native_horizon, '--race-focus-recovery', [string][int]$preferences.race_focus_recovery)
    }
    else{$arguments+=@('--menu-profile',$preferences.menu_profile,'--race-display',$preferences.race_display,
        '--race-resolution',$preferences.race_resolution,'--race-hud',$preferences.race_hud,'--sky-mode',$preferences.sky_mode,'--race-distance',$preferences.race_distance)}
    return $arguments
}

function Reset-Preferences([switch]$InMemoryOnly) {
    $script:binding = $true
    # Keep the catalog's default object separate from editable session choices.
    $script:settings.games.($script:game) = $script:catalog.default_settings.games.($script:game) |
        ConvertTo-Json -Depth 6 | ConvertFrom-Json
    Select-Game $script:game
    if (-not $InMemoryOnly) { Start-Model 'save' (Preference-Arguments 'save') }
}

function Use-RecommendedOptions {
    if (-not $script:initialized -or $script:game -notin @('a2racer1','a2racer2') -or $script:operation) { return }
    Reset-Preferences -InMemoryOnly
    $ui.Pages.SelectedIndex = 0
    Set-Status 'Aanbevolen instellingen gekozen' ('Klik Speel ' + $ui.GameTitle.Text + ' om op te slaan en te starten.')
}

function Use-IProfile([string]$ProfileName) {
    if ($script:game -ne 'a2racer1' -or $script:operation) { return }
    if ($ProfileName -notin @('original','recommended','max')) { throw 'Onbekend profiel.' }
    $script:binding = $true
    $script:settings.games.a2racer1 = $script:catalog.i_profiles.($ProfileName).preferences.PSObject.Copy()
    Select-Game 'a2racer1'
    $ui.Pages.SelectedIndex = 0
    Set-Status ('Profiel ' + $script:catalog.i_profiles.($ProfileName).label + ' gekozen') 'Controleer de opties. Opslaan of Speel bewaart je keuze.'
}

function Use-IIProfile([string]$ProfileName) {
    if (-not $script:initialized -or $script:game -ne 'a2racer2' -or $script:operation) { return }
    if ($ProfileName -notin @('original','recommended','max')) { throw 'Onbekend profiel.' }
    $script:binding = $true
    $script:settings.games.a2racer2 = $script:catalog.ii_profiles.($ProfileName).preferences.PSObject.Copy()
    Select-Game 'a2racer2'
    $ui.Pages.SelectedIndex = 0
    Set-Status ('Profiel ' + $script:catalog.ii_profiles.($ProfileName).label + ' gekozen') 'Controleer de opties. Opslaan of Speel bewaart je keuze.'
}

function Use-GameProfile([string]$ProfileName) {
    if ($script:game -eq 'a2racer1') { Use-IProfile $ProfileName }
    elseif ($script:game -eq 'a2racer2') { Use-IIProfile $ProfileName }
}

function Start-Operation([string]$Kind, [string]$Executable, [string[]]$Arguments) {
    if ($script:operation) { return }
    try {
        $script:operation = New-LauncherProcess $Executable $Arguments
        $script:operation.kind = $Kind
        Update-Buttons
    } catch { Set-Status 'Kon niet doorgaan' $_.Exception.Message; $script:operation = $null; Update-Buttons }
}

function Start-Model([string]$Kind, [string[]]$Arguments) {
    Start-Operation $Kind $script:PythonPath (@('-B', (Join-Path $PSScriptRoot 'launcher_model.py')) + $Arguments)
}

function Start-IIIGame {
    if ($script:operation -or ($script:worker -and -not $script:worker.process.HasExited)) { return }
    try {
        if (-not (Load-Runtimes)) { throw 'Python-runtime ontbreekt.' }
        foreach ($relative in @('local/experiments','local/ii-parallel','local/iii-play','local/iii-trials')) {
            if (@(Get-LauncherProcesses (Join-Path $workspacePath $relative)).Count) {
                throw 'Sluit de eerdere game eerst normaal af voordat je deel III start.'
            }
        }
        $tour = [string]$ui.IIITourChoice.SelectedItem.Tag
        if ($tour -notin @('1','2')) { throw 'Kies Tour 1 of Tour 2.' }
        $profile = [string]$ui.IIIProfileChoice.SelectedItem.Tag
        if ($profile -notin @('original','compat','fullhd-skyoff')) { throw 'Kies een raceweergave.' }
        $script:sessionName = $null
        $arguments = @('-B',(Join-Path $PSScriptRoot 'iii_compat_launcher.py'),'start','--tour',$tour,'--profile',$profile)
        if ($profile -eq 'original') { $arguments = @('-B',(Join-Path $PSScriptRoot 'iii_local_launcher.py'),'start','--tour',$tour) }
        $script:worker = New-LauncherProcess $script:PythonPath $arguments
        $script:worker.kind = 'iii'
        Set-Status 'Deel III starten' ('Tour '+$tour+' · zonder gemounte cd')
        Update-Buttons
    } catch { Set-Status 'Deel III kon niet starten' $_.Exception.Message }
}

function Open-Devtools {
    try {
        if (-not (Load-Runtimes)) { throw 'Runtimes ontbreken voor de devtools.' }
        $viewerPath = Join-Path $workspacePath 'tools\Show-A2Devtools.ps1'
        Assert-LauncherPath $viewerPath
        $viewer = New-LauncherProcess $script:PowerShellPath @('-NoLogo','-NoProfile','-STA','-WindowStyle','Hidden',
            '-ExecutionPolicy','Bypass','-File',$viewerPath,'-PythonPath',$script:PythonPath,'-Game',$script:game) -Detached
        $viewer.process.Dispose()
    } catch { Set-Status 'Devtools niet geopend' $_.Exception.Message }
}

function Open-GameSource {
    if ($script:game -eq 'a2racer2') {
        # User-selected fixed external page. No archive is downloaded by us.
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = 'https://www.myabandonware.com/game/a2-racer-ii-gri'
        $info.UseShellExecute = $true
        $browser = [Diagnostics.Process]::Start($info)
        if ($browser) { $browser.Dispose() }
        return
    }
    $null = [Windows.MessageBox]::Show($window,
        'Gebruik een rechtmatig verkregen eigen gamekopie. Voor deel I en II is een volledige ondersteunde Nederlandse gamemap of het ondersteunde gamearchief nodig. Een minimale cd-installatie kan gegevens missen. Deze launcher downloadt geen games.',
        'A2 Racer verkrijgen', 'OK', 'Information')
}

function Load-Runtimes {
    $config = Join-Path $workspacePath 'local\launcher\runtimes.json'
    if ((-not $script:PythonPath -or -not $script:PowerShellPath) -and (Test-Path -LiteralPath $config)) {
        Assert-LauncherPath $config
        if ((Get-Item -LiteralPath $config).Length -gt 4096) { throw 'Runtimeconfig is te groot.' }
        $runtime = [IO.File]::ReadAllText($config) | ConvertFrom-Json
        if (-not $script:PythonPath) { $script:PythonPath = [string]$runtime.python_path }
        if (-not $script:PowerShellPath) { $script:PowerShellPath = [string]$runtime.powershell_path }
    }
    if (-not $script:PythonPath) { $script:PythonPath = Join-Path $workspacePath 'local\portable-runtime\python\python.exe' }
    if (-not $script:PowerShellPath) { $script:PowerShellPath = Join-Path $workspacePath 'local\portable-runtime\powershell\pwsh.exe' }
    foreach ($path in @($script:PythonPath, $script:PowerShellPath)) { Assert-LauncherPath $path }
    return [bool]((Test-Path -LiteralPath $script:PythonPath -PathType Leaf) -and (Test-Path -LiteralPath $script:PowerShellPath -PathType Leaf))
}

function Start-InitialCheck {
    try {
        $payload = Join-Path $workspacePath 'payload\python-3.13.16-embed-amd64.zip'
        $publicRelease = Test-Path -LiteralPath (Join-Path $workspacePath 'public-release.json')
        if (-not $script:developmentRuntimes -and -not $script:bootstrapAttempted -and ((Test-Path -LiteralPath $payload) -or $publicRelease)) {
            $script:bootstrapAttempted = $true
            Set-Status 'Eerste voorbereiding' $(if ($publicRelease) { 'De componenten worden bij hun leveranciers opgehaald en gecontroleerd. De eerste start vereist internet.' } else { 'De lokale runtimes worden gecontroleerd. Dit kan even duren.' })
            Start-Operation 'bootstrap' (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') @('-NoLogo','-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'Start-A2Portable.ps1'),'-CheckOnly')
            return
        }
        if (Load-Runtimes) {
            if (-not $script:releaseInitialized -and (Test-Path -LiteralPath (Join-Path $workspacePath 'release-manifest.json'))) {
                Set-Status 'Eerste voorbereiding' 'Launcherbestanden controleren en een meegeleverd persoonlijk gamearchief lokaal importeren…'
                Start-Operation 'initialize' $script:PythonPath @('-B',(Join-Path $PSScriptRoot 'portable_launcher.py'),'initialize')
                return
            }
            Start-Model 'snapshot' @('snapshot'); return
        }
        throw 'Runtimes ontbreken. Gebruik de complete portable kit, of configureer local/launcher/runtimes.json.'
    } catch { Set-Status 'Voorbereiding nodig' $_.Exception.Message }
}

function Read-Session {
    if (-not $script:sessionName) { return }
    $folder = Join-Path $workspacePath ('local\launcher\sessions\' + $script:sessionName)
    Assert-LauncherPath $folder
    $statusPath = Join-Path $folder 'status.json'
    if ((Test-Path -LiteralPath $statusPath) -and (Get-Item -LiteralPath $statusPath).Length -le 16384) {
        Assert-LauncherPath $statusPath
        $status = [IO.File]::ReadAllText($statusPath) | ConvertFrom-Json
        if ($status.run_name -eq $script:sessionName) {
            $titles = @{ starting='Starten…'; running='Gameproces draait'; finished='Afgesloten'; error='Start onderbroken' }
            if ($titles.ContainsKey([string]$status.state)) { Set-Status $titles[[string]$status.state] ([string]$status.message) }
            $ui.LogText.Text = $script:sessionName + "`r`n" + $status.message + "`r`n`r`n"
        }
    }
    $logPath = Join-Path $folder 'session.log'
    if (Test-Path -LiteralPath $logPath) {
        Assert-LauncherPath $logPath
        $stream = [IO.File]::Open($logPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        try {
            $length = [int][Math]::Min($stream.Length, 16384); $null = $stream.Seek(-$length, [IO.SeekOrigin]::End)
            $bytes = New-Object byte[] $length; $count = $stream.Read($bytes, 0, $length)
            $ui.LogText.Text += [Text.Encoding]::UTF8.GetString($bytes, 0, $count)
        } finally { $stream.Dispose() }
    }
}

function Restore-Session([string]$Name) {
    if (-not $Name -or $Name -notmatch '^launcher-[a-z0-9-]{1,35}$') { return }
    $script:sessionName = $Name
    $path = Join-Path $workspacePath ('local\launcher\sessions\' + $Name + '\status.json')
    Assert-LauncherPath $path
    if ((Get-Item -LiteralPath $path).Length -gt 16384) { return }
    $status = [IO.File]::ReadAllText($path) | ConvertFrom-Json
    if ($status.state -in @('starting','running')) {
        try {
            $process = Get-Process -Id ([int]$status.worker_pid) -ErrorAction Stop
            if ([string]::Equals($process.Path, $script:PowerShellPath, [StringComparison]::OrdinalIgnoreCase) -and
                    $process.StartTime.ToUniversalTime().Ticks -eq [long]$status.worker_start_ticks) {
                $script:worker = @{ process=$process }
            }
        } catch { } # An old status never proves that the old PID is still our worker.
    }
    Read-Session
}

function Show-Installations($Result) {
    $ui.InstallationChoice.Items.Clear()
    $first = $null
    foreach ($entry in $Result.installations) {
        $item = New-Object Windows.Controls.ComboBoxItem
        $item.Content = [string]$entry.path; $item.Tag = [string]$entry.path
        $item.ToolTip = [string]$entry.reason; $item.IsEnabled = [bool]$entry.supported
        $null = $ui.InstallationChoice.Items.Add($item)
        if (-not $first -and $item.IsEnabled) { $first = $item }
    }
    $ui.InstallationChoice.SelectedItem = $first
    $ui.InstallationChoice.Visibility = if ($ui.InstallationChoice.Items.Count) { 'Visible' } else { 'Collapsed' }
    $ui.LinkInstallation.Visibility = if ($first) { 'Visible' } else { 'Collapsed' }
    $ui.InstallationNote.Text = if ($first) { 'Ondersteunde installatie gevonden. Koppelen maakt een eigen kopie; je installatie blijft intact.' } elseif ($ui.InstallationChoice.Items.Count) { 'Installatie gevonden, maar deze versie is onvolledig of niet ondersteund. Zie de uitleg bij de map. Importeer anders je volledige gamearchief.' } else { 'Geen geregistreerde installatie gevonden. Kies zelf de volledige gamemap of importeer je gamearchief.' }
    Set-Status 'Installatiecontrole afgerond' $ui.InstallationNote.Text
    Update-Buttons
}

function Poll-Launcher {
    $pending = $null
    try {
        if ($script:operation -and $script:operation.process.HasExited -and $script:operation.output.IsCompleted -and $script:operation.error.IsCompleted) {
            $pending = $script:operation; $script:operation = $null
            $output = $pending.output.GetAwaiter().GetResult(); $errorText = $pending.error.GetAwaiter().GetResult()
            $code = $pending.process.ExitCode; $pending.process.Dispose()
            if ($code -ne 0) { throw $errorText.Substring(0, [Math]::Min($errorText.Length, 1600)) }
            if ($pending.kind -eq 'bootstrap') { Start-InitialCheck; return }
            if ($pending.kind -eq 'initialize') { $script:releaseInitialized = $true; Start-InitialCheck; return }
            if ($pending.kind -in @('import','iii-import')) { Start-Model 'snapshot' @('snapshot'); return }
            $result = $output | ConvertFrom-Json
            switch ($pending.kind) {
                'snapshot' {
                    $script:catalog = $result
                    if (-not $script:settings) { $script:settings = $result.settings; $script:game = $result.settings.selected_game }
                    Select-Game $script:game
                    if (-not $script:sessionName -and $result.latest_session) { Restore-Session $result.latest_session }
                    if (-not $result.games.a2racer1.ready -and -not $script:installationScanAttempted) {
                        $script:installationScanAttempted = $true
                        Start-Model 'detect' @('detect-installations'); return
                    }
                }
                'detect' { Show-Installations $result }
                'save' { $script:settings = $result; Set-Status 'Opties opgeslagen' 'Deze keuzes gelden bij je volgende start.' }
                'start' {
                    if ($result.run_name -notmatch '^launcher-[a-z0-9-]{1,35}$') { throw 'Ongeldige sessienaam.' }
                    $script:sessionName = $result.run_name
                    $script:worker = New-LauncherProcess $script:PowerShellPath @('-NoLogo','-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'Invoke-A2LauncherSession.ps1'),'-RunName',$script:sessionName,'-PythonPath',$script:PythonPath) -Detached
                    Set-Status 'Starten…' 'Je startprocedure loopt op de achtergrond.'
                }
            }
        }
        if ($script:worker) {
            Read-Session
            if ($script:worker.process.HasExited) {
                $completed = $script:worker; $script:worker = $null
                if ($completed.process.ExitCode -ne 0) {
                    if ($completed.ContainsKey('kind') -and $completed.kind -eq 'iii') {
                        $detail = $completed.error.GetAwaiter().GetResult()
                        $ui.LogText.Text = $detail
                        Set-Status 'Start onderbroken' $detail.Substring(0,[Math]::Min($detail.Length,1600))
                    } elseif ($ui.StatusTitle.Text -ne 'Start onderbroken') { Set-Status 'Start onderbroken' 'De achtergrondstart is gestopt. Bekijk het sessielog voor de fout.' }
                }
                $completed.process.Dispose()
            }
        }
        Update-Buttons
    } catch {
        $title = if ($pending -and $pending.kind -eq 'iii-import') { 'Deel III kon niet koppelen' } else { 'Kon niet doorgaan' }
        Set-Status $title $_.Exception.Message; $ui.LogText.Text = $_.Exception.Message; Update-Buttons
    }
}

try {
    Assert-LauncherPath $workspacePath
    $reader = New-Object Xml.XmlNodeReader ([xml][IO.File]::ReadAllText((Join-Path $PSScriptRoot 'launcher_window.xaml')))
    try { $window = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
    $ui = @{}
    foreach ($name in @('CoverBackdrop','CoverPreview','LauncherBadge','WelcomeTitle','WelcomeHint','GameOne','GameTwo','GameThree','GameOneAvailability','GameTwoAvailability','IIITourChoice','IIIStatus','IIIStartScroll','IIIOverviewPanel','IIITourOverview','IIIReadyOverview','IIIResolutionOverview','IIIProfileChoice','IIIProfileNote','IIIChooseInstallation','GameOneSelected','GameTwoSelected','GameTitle','GameSubtitle','OptionsGameTitle',
            'IOptionsPanel','IIOptionsNotice','IOverviewPanel','IIOverviewPanel','IIMenuChoice','IIRaceDisplayChoice','IIResolutionChoice','IIHudChoice','IISkyChoice','IIDistanceChoice','IIMenuNote','Pages','PlaySummary','PlayNote','ImportGame','GraphicsChoice',
            'GraphicsNote','ResolutionChoice','ResolutionNote','CameraNote','DistanceChoice','DistanceNote','ObjectDistanceChoice','ObjectDistanceNote','TextureChoice','TextureNote','MenuChoice','MenuNote',
            'HorizonChoice','FocusRecoveryChoice','FocusRecoveryNote','ChooseOptions','RecommendedOptions','OverviewResolution','OverviewFps','OverviewDistance','OverviewObjects','OverviewDetailLabel','SelectionNote','AdvancedOptions','StartScroll','SupportScroll','OptionsScroll','DashboardChoice','FpsChoice','FpsNote','IntroChoice','DebugChoice',
            'OriginalProfile','MaxProfile','SaveOptions','ResetOptions','OpenLogs','OpenDevtools','RefreshState','LogText','StatusTitle','StatusMessage','PlayButton',
            'InstallationPanel','InstallationTitle','InstallationChoice','InstallationNote','DetectInstallations','ChooseInstallation','LinkInstallation','GetGame','PrepareGame')) {
        $ui[$name] = $window.FindName($name)
        if (-not $ui[$name]) { throw ('Ontbrekend launcherelement: ' + $name) }
    }
    $artworkPath = Join-Path $PSScriptRoot 'launcher_art\cover-inspired-highway-v1.png'
    Set-CoverArtwork $ui.CoverBackdrop $artworkPath
    Set-CoverArtwork $ui.CoverPreview $artworkPath
    $iconPath = Join-Path $PSScriptRoot 'launcher_art\a2-revival.ico'
    Assert-LauncherPath $iconPath
    if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) { throw 'Het A2-launcherpictogram ontbreekt. Pak de complete launcher opnieuw uit.' }
    $iconStream = [IO.File]::OpenRead($iconPath)
    try {
        $iconDecoder = [Windows.Media.Imaging.BitmapDecoder]::Create($iconStream, [Windows.Media.Imaging.BitmapCreateOptions]::None, [Windows.Media.Imaging.BitmapCacheOption]::OnLoad)
        $iconFrames = @($iconDecoder.Frames)
        $titleFrame = $iconFrames | Sort-Object @{ Expression = { [Math]::Abs($_.PixelWidth - 32) } } | Select-Object -First 1
        $badgeFrame = $iconFrames | Sort-Object PixelWidth -Descending | Select-Object -First 1
        $titleFrame.Freeze()
        $badgeFrame.Freeze()
        $window.Icon = $titleFrame
        $ui.LauncherBadge.Source = $badgeFrame
    } finally { $iconStream.Dispose() }
    Add-Choice $ui.IIITourChoice 'Tour 1' '1'; Add-Choice $ui.IIITourChoice 'Tour 2' '2'
    $ui.IIITourChoice.SelectedIndex = 0
    Add-Choice $ui.IIIProfileChoice 'Compatibiliteit · proef' 'compat'
    Add-Choice $ui.IIIProfileChoice '1080p · horizon en wolken uit · proef' 'fullhd-skyoff'
    Add-Choice $ui.IIIProfileChoice 'Origineel · crash gemeld' 'original'
    $ui.IIIProfileChoice.SelectedIndex = 0
    if ($CheckOnly -or $PreviewPath) {
        if (-not $script:developmentRuntimes) {
            & (Join-Path $PSScriptRoot 'Start-A2Portable.ps1') -CheckOnly
            if (-not $?) { throw 'Portable verificatie faalde; catalogus niet geladen.' }
        }
        if (-not (Load-Runtimes)) { throw 'Runtimes ontbreken voor controle.' }
        $probe = New-LauncherProcess $script:PythonPath @('-B',(Join-Path $PSScriptRoot 'launcher_model.py'),'snapshot')
        $probe.process.WaitForExit()
        $json = $probe.output.GetAwaiter().GetResult(); $errorText = $probe.error.GetAwaiter().GetResult()
        if ($probe.process.ExitCode -ne 0) { throw $errorText }
        $probe.process.Dispose()
        $script:catalog = $json | ConvertFrom-Json; $script:settings = $script:catalog.settings
        Select-Game $script:settings.selected_game
        if ($PreviewPath) {
            if ($PreviewGame) { Select-Game $PreviewGame }
            $ui.Pages.SelectedIndex = @{ play=0; options=1; logs=2; iii=3 }[$PreviewPage]
            Update-IIIStatus; Update-Buttons
            $localPrefix = [IO.Path]::GetFullPath((Join-Path $workspacePath 'local')).TrimEnd('\') + '\'
            if (-not [IO.Path]::GetFullPath($PreviewPath).StartsWith($localPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Preview moet onder local/ worden opgeslagen.' }
            Assert-LauncherPath $PreviewPath
            $content = $window.Content; $window.Content = $null
            $surface = New-Object Windows.Controls.Border; $surface.Background = $window.Background; $surface.Child = $content
            $surface.Resources = $window.Resources
            [Windows.Documents.TextElement]::SetForeground($surface, $window.Foreground)
            [Windows.Documents.TextElement]::SetFontFamily($surface, $window.FontFamily)
            [Windows.Documents.TextElement]::SetFontSize($surface, $window.FontSize)
            $previewWidth = [int]$window.Width; $previewHeight = [int]$window.Height
            $surface.Measure((New-Object Windows.Size $previewWidth,$previewHeight)); $surface.Arrange((New-Object Windows.Rect 0,0,$previewWidth,$previewHeight)); $surface.UpdateLayout()
            $bitmap = New-Object Windows.Media.Imaging.RenderTargetBitmap $previewWidth,$previewHeight,96,96,([Windows.Media.PixelFormats]::Pbgra32)
            $bitmap.Render($surface)
            $encoder = New-Object Windows.Media.Imaging.PngBitmapEncoder
            $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
            $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $PreviewPath))
            $stream = [IO.File]::Open($PreviewPath, [IO.FileMode]::Create, [IO.FileAccess]::Write)
            try { $encoder.Save($stream) } finally { $stream.Dispose() }
        }
        Write-Output 'Launchercontrole geslaagd: WPF, gamecatalogus en opties geladen; geen game gestart of cd gemount.'
        return
    }
    $ui.IIITourChoice.Add_SelectionChanged({ Update-IIIStatus; Update-Buttons })
    $ui.IIIProfileChoice.Add_SelectionChanged({ Update-IIIStatus; Update-Buttons })
    $ui.IIIChooseInstallation.Add_Click({
        try {
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object Windows.Forms.FolderBrowserDialog
            $dialog.Description = 'Kies de volledige A2 Racer III Tour '+$ui.IIITourChoice.SelectedItem.Tag+'-gamemap of DATA-map. De bron blijft intact.'
            $dialog.ShowNewFolderButton = $false
            try {
                if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {
                    Set-Status 'Deel III koppelen' 'De gekozen tourmap wordt gecontroleerd en naar een zelfstandige kopie gekopieerd.'
                    Start-Model 'iii-import' @('import-iii-installation','--folder',$dialog.SelectedPath,'--tour',[string]$ui.IIITourChoice.SelectedItem.Tag)
                }
            } finally { $dialog.Dispose() }
        } catch { Set-Status 'Deel III kon niet koppelen' $_.Exception.Message }
    })
    foreach($name in @('IIResolutionChoice','IIHudChoice','IISkyChoice','IIDistanceChoice')){
        $ui[$name].Add_SelectionChanged({
            if(-not $script:binding -and $script:initialized -and $script:game -eq 'a2racer2'){
                if($ui.IIResolutionChoice.SelectedItem.Tag -eq '720p' -and $ui.IIHudChoice.SelectedItem.Tag -ne 'native'){Select-Choice $ui.IIHudChoice 'native'}
                foreach($item in $ui.IIHudChoice.Items){$item.IsEnabled=($item.Tag -eq 'native' -or $ui.IIResolutionChoice.SelectedItem.Tag -ne '720p')}
                Update-Summary;Update-Buttons
            }
        })
    }
    $ui.GameThree.Add_Click({ $ui.Pages.SelectedIndex = 3; Update-IIIStatus; Update-Buttons })
    $ui.Pages.Add_SelectionChanged({
        if ($_.OriginalSource -eq $ui.Pages -and $script:initialized) {
            if ($ui.Pages.SelectedIndex -ne 3) { Select-Game $script:game }
            Update-IIIStatus; Update-Buttons
        }
    })
    $ui.GameOne.Add_Click({ $ui.Pages.SelectedIndex = 0; Select-Game 'a2racer1' }); $ui.GameTwo.Add_Click({ $ui.Pages.SelectedIndex = 0; Select-Game 'a2racer2' })
    $ui.ChooseOptions.Add_Click({ $ui.Pages.SelectedIndex = 1; $ui.OptionsScroll.ScrollToTop() })
    $ui.GraphicsChoice.Add_SelectionChanged({ Update-GraphicsChoices })
    foreach ($name in @('ResolutionChoice','FpsChoice','DistanceChoice','ObjectDistanceChoice','TextureChoice','MenuChoice','IIMenuChoice','IIRaceDisplayChoice','HorizonChoice')) {
        $ui[$name].Add_SelectionChanged({ Update-Summary; if ($script:initialized -and -not $script:binding) { Update-Buttons } })
    }
    foreach ($name in @('DashboardChoice','FocusRecoveryChoice','IntroChoice','DebugChoice')) {
        $ui[$name].Add_Click({ Update-Summary; if ($script:initialized -and -not $script:binding) { Update-Buttons } })
    }
    $ui.SaveOptions.Add_Click({ Start-Model 'save' (Preference-Arguments 'save') })
    $ui.ResetOptions.Add_Click({ Reset-Preferences })
    $ui.RecommendedOptions.Add_Click({ Use-RecommendedOptions })
    $ui.OriginalProfile.Add_Click({ Use-GameProfile 'original' })
    $ui.MaxProfile.Add_Click({ Use-GameProfile 'max' })
    $ui.PlayButton.Add_Click({ if ($ui.Pages.SelectedIndex -eq 3) { Start-IIIGame } else { Start-Model 'start' (Preference-Arguments 'create-session') } })
    $ui.RefreshState.Add_Click({ Start-Model 'snapshot' @('snapshot') })
    $ui.OpenDevtools.Add_Click({ Open-Devtools })
    $ui.OpenLogs.Add_Click({
        try {
            $folder = Join-Path $workspacePath 'local\launcher'
            Assert-LauncherPath $folder; $null = [IO.Directory]::CreateDirectory($folder)
            $null = Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList @($folder)
        } catch { Set-Status 'Logmap niet geopend' $_.Exception.Message }
    })
    $ui.ImportGame.Add_Click({
        $dialog = New-Object Microsoft.Win32.OpenFileDialog
        $archiveName = if ($script:game -eq 'a2racer2') {'A2_Racer_II_v1.01_Win_ROM_NL.zip'} else {'A2-Racer_Win_NL.zip'}
        $dialog.Title = 'Kies je eigen ondersteunde '+$ui.GameTitle.Text+'-archief'; $dialog.Filter = 'Gamearchief (*.zip)|*.zip'
        $candidate = Join-Path $workspacePath $archiveName
        if (Test-Path -LiteralPath $candidate) { $dialog.FileName = $candidate }
        if ($dialog.ShowDialog($window)) {
            Set-Status 'Gamebestanden voorbereiden' 'Je bronarchief wordt gecontroleerd en lokaal geïmporteerd.'
            Start-Model 'import' @('import-game','--archive',$dialog.FileName,'--game',$script:game)
        }
    })
    $ui.DetectInstallations.Add_Click({ Start-Model 'detect' @('detect-installations') })
    $ui.PrepareGame.Add_Click({ Set-Status 'Game voorbereiden' 'Deel II wordt lokaal voorbereid met de gecontroleerde bronnen.';Start-Model 'import' @('prepare-ii') })
    $ui.InstallationChoice.Add_SelectionChanged({ Update-Buttons })
    $ui.LinkInstallation.Add_Click({
        if ($ui.InstallationChoice.SelectedItem -and $ui.InstallationChoice.SelectedItem.IsEnabled) {
            Set-Status 'Installatie koppelen' 'De bestanden worden gecontroleerd en naar onze eigen opslag gekopieerd.'
            Start-Model 'import' @('import-installation','--folder',[string]$ui.InstallationChoice.SelectedItem.Tag)
        }
    })
    $ui.ChooseInstallation.Add_Click({
        try {
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object Windows.Forms.FolderBrowserDialog
            $dialog.Description = 'Kies de volledige '+$ui.GameTitle.Text+'-gamemap. De bron blijft intact.'
            $dialog.ShowNewFolderButton = $false
            try {
                if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {
                    Set-Status 'Installatie koppelen' 'De gekozen map wordt gecontroleerd; andere versies worden niet gestart.'
                    Start-Model 'import' @('import-installation','--folder',$dialog.SelectedPath,'--game',$script:game)
                }
            } finally { $dialog.Dispose() }
        } catch { Set-Status 'Installatiemap niet gekoppeld' $_.Exception.Message }
    })
    $ui.GetGame.Add_Click({
        try { Open-GameSource } catch { Set-Status 'Pagina niet geopend' $_.Exception.Message }
    })
    $timer = New-Object Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromMilliseconds(500); $timer.Add_Tick({ Poll-Launcher })
    $window.Add_Loaded({ Start-InitialCheck; $timer.Start() })
    $window.Add_Closed({ $timer.Stop() }) # Closing the launcher never kills the worker or game.
    $null = $window.ShowDialog()
} catch {
    if ($CheckOnly -or $PreviewPath) { Write-Error $_.Exception.Message; exit 1 }
    $null = [Windows.MessageBox]::Show($_.Exception.Message, 'A2 Revival — launcher', 'OK', 'Error')
    exit 1
}
