#Requires -Version 7.4
[CmdletBinding()]
param([switch]$CheckOnly, [string]$RenderPath, [int]$RenderWidth=1600,
      [int]$RenderHeight=900, [switch]$UiCheck,
      [Alias('RaceDisplay')][ValidateSet('classic','widescreen')][string]$RaceDisplayPreference,
      [ValidateSet('Home','Garage','Cars','Controls','Options','Records','Players','Reset')][string]$RenderPage='Home')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:MenuWindow=$null
$script:Race=$null
$script:Session=$null
$script:MenuLock=$null
$script:Closing=$false
$script:Initializing=$false
$script:WaitingKey=$null
$script:Page='Home'
$script:StopClock=$null
$script:RaceToken=$null
$script:Cursors=@{}
$script:CloseRequested=$false
$script:ForcedClose=$false
$script:FakeStarted=0
$script:FakeDisposed=0
$script:ChunkClock=$null
$script:NextChunkRead=0
$script:LifetimeFrame=$null
$script:TestingLifetime=$false
$script:LifetimeSurvivedHide=$false
$script:LifetimeError=$null

$script:MenuMusicPlayer=$null
$script:MenuMusicPlaying=$false
$script:MenuMusicFailed=$false
$script:MenuMusicIndex=0
$script:MenuMusicPaths=@()

function Set-IIMenuMusic([bool]$Active,[int]$Volume) {
    if(-not $script:MenuMusicPlayer -or $script:MenuMusicFailed){return}
    $script:MenuMusicPlayer.Volume=[Math]::Clamp($Volume/3100.0,0.0,1.0)
    if(-not $Active -or $Volume -le 0){
        if($script:MenuMusicPlaying){$script:MenuMusicPlayer.Stop()}
        $script:MenuMusicPlaying=$false;return
    }
    if(-not $script:MenuMusicPlaying){
        $script:MenuMusicPlaying=$true
        $script:MenuMusicPlayer.Open([Uri]$script:MenuMusicPaths[$script:MenuMusicIndex])
        $script:MenuMusicPlayer.Play()
    }
}
function Next-IIMenuMusic {
    if(-not $script:MenuMusicPlayer -or -not $script:MenuMusicPlaying -or $script:Closing -or $script:MenuMusicFailed){return}
    $script:MenuMusicIndex=($script:MenuMusicIndex+1)%$script:MenuMusicPaths.Count
    $script:MenuMusicPlayer.Open([Uri]$script:MenuMusicPaths[$script:MenuMusicIndex])
    $script:MenuMusicPlayer.Play()
}
function Close-IIMenuMusic {
    $script:MenuMusicPlaying=$false
    if($script:MenuMusicPlayer){$script:MenuMusicPlayer.Close();$script:MenuMusicPlayer=$null}
}
function Initialize-IIMenuMusic {
    if($CheckOnly -or $RenderPath -or $UiCheck){return}
    if(-not $script:Config.PSObject.Properties['menu_music_revision'] -or $script:Config.menu_music_revision -ne '20261013'){return}
    $script:MenuMusicPaths=@('speed2','disco','moody','jammin','energy','speed')|ForEach-Object {
        Join-Path $PSScriptRoot ('assets/music/'+$_+'.wav')
    }
    $script:MenuMusicPlayer=[Windows.Media.MediaPlayer]::new()
    $script:MenuMusicPlayer.Add_MediaEnded({Next-IIMenuMusic})
    $script:MenuMusicPlayer.Add_MediaFailed({
        $script:MenuMusicFailed=$true;$script:MenuMusicPlaying=$false
        if($script:MenuMusicPlayer){$script:MenuMusicPlayer.Stop()}
        Write-MenuEvent 'menu-music-failed' 'Audio kon niet worden afgespeeld; het menu blijft bruikbaar.'
    })
}

function Invoke-MenuLifetime {
    # Hide must not end the host: only the Closed event stops this frame.
    $script:LifetimeFrame=[Windows.Threading.DispatcherFrame]::new()
    $script:MenuWindow.Show()
    if(-not $script:Closing){[Windows.Threading.Dispatcher]::PushFrame($script:LifetimeFrame)}
    $script:LifetimeFrame=$null
}

function Assert-MenuPath([string]$Path) {
    $candidate=[IO.Path]::GetFullPath($Path)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $item=Get-Item -LiteralPath $candidate -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                ($item.PSObject.Properties['LinkType'] -and $item.LinkType -eq 'HardLink')) {
                throw 'Menupad bevat een link of gedeeld bestand.'
            }
        }
        $parent=[IO.Directory]::GetParent($candidate)
        $candidate=if($parent){$parent.FullName}else{$null}
    }
}
function Write-MenuEvent([string]$Kind,$Value=$null) {
    if ($CheckOnly -or $RenderPath -or $UiCheck) { return }
    Assert-MenuPath $script:Events
    $eventFolder=[IO.Path]::GetDirectoryName($script:Events)
    $null=[IO.Directory]::CreateDirectory($eventFolder)
    Assert-MenuPath $script:Events
    $record=@{utc=[DateTime]::UtcNow.ToString('o');event=$Kind;value=$Value;native_menu_used=$false}
    Add-Content -LiteralPath $script:Events -Value ($record|ConvertTo-Json -Compress -Depth 8) -Encoding utf8
}
function Invoke-Backend([string]$Command,$Payload=@{}) {
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$script:Config.python
    $info.WorkingDirectory=$PSScriptRoot
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    foreach($arg in @((Join-Path $PSScriptRoot 'Backend.py'),'--base',$PSScriptRoot,
                    '--command',$Command,'--payload',($Payload|ConvertTo-Json -Compress -Depth 12))) {
        $info.ArgumentList.Add([string]$arg)
    }
    $child=[Diagnostics.Process]::new();$child.StartInfo=$info
    try {
        if(-not $child.Start()){throw 'Menustatus kon niet worden gelezen.'}
        $output=$child.StandardOutput.ReadToEndAsync();$errors=$child.StandardError.ReadToEndAsync()
        if(-not $child.WaitForExit(15000)){$child.Kill();throw 'Menustatus reageert niet.'}
        $message=$output.GetAwaiter().GetResult()
        if(-not $message.Trim()){throw ('Menustatus gaf geen antwoord: '+$errors.GetAwaiter().GetResult())}
        $result=$message|ConvertFrom-Json -Depth 32
        if($child.ExitCode -ne 0){throw $result.error}
        $script:Model=$result.state;$script:Catalog=$result.catalog
    } finally {$child.Dispose()}
}
function Set-Status([string]$Message,[bool]$Error=$false) {
    $script:Controls.Status.Text=$Message
    $script:Controls.Status.Foreground=if($Error){[Windows.Media.Brushes]::Salmon}else{[Windows.Media.BrushConverter]::new().ConvertFromString('#D3DCEC')}
}
function Current-Profile { return @($script:Model.profiles|Where-Object id -eq $script:Model.selected)[0] }
function New-Text([string]$Text,[int]$Size=23) {
    $label=[Windows.Controls.TextBlock]::new();$label.Text=$Text;$label.FontSize=$Size
    $label.TextWrapping='Wrap';$label.Margin='0,0,0,16';return $label
}
function Add-Detail($Item) {
    $parent=if($script:DetailSection){$script:DetailSection}else{$script:Controls.DetailContent}
    $null=$parent.Children.Add($Item)
}
function New-DetailSection([string]$Title) {
    $border=[Windows.Controls.Border]::new();$border.Style=$script:MenuWindow.Resources['GarageCard']
    $border.Padding='18';$border.Margin='0,0,0,20'
    $panel=[Windows.Controls.StackPanel]::new();$border.Child=$panel
    $label=New-Text $Title 25;$label.FontWeight='Bold';$label.Foreground=[Windows.Media.BrushConverter]::new().ConvertFromString('#FFF1CD')
    $null=$panel.Children.Add($label);$null=$script:Controls.DetailContent.Children.Add($border)
    $script:DetailSection=$panel
}
function Add-Action([string]$Text,[string]$Action,$Value=$null,$Parent=$null) {
    $button=[Windows.Controls.Button]::new();$button.Content=$Text
    $button.Tag=@{action=$Action;value=$Value}
    $button.Add_Click({param($sender,$event) Invoke-Action $sender.Tag.action $sender.Tag.value})
    if($Parent){$null=$Parent.Children.Add($button)}else{Add-Detail $button}
    return $button
}
function New-GarageCard([string]$Title,[string]$Description,$Parent) {
    $border=[Windows.Controls.Border]::new();$border.Style=$script:MenuWindow.Resources['GarageCard']
    $border.Width=340;$border.Margin='0,0,16,16'
    $panel=[Windows.Controls.StackPanel]::new();$border.Child=$panel
    $titleLabel=New-Text $Title 24;$titleLabel.FontWeight='SemiBold';$titleLabel.Margin='0,0,0,4'
    $titleLabel.Foreground=[Windows.Media.BrushConverter]::new().ConvertFromString('#FFF1CD')
    $descriptionLabel=New-Text $Description 18;$descriptionLabel.Margin='0,0,0,6'
    $descriptionLabel.Foreground=[Windows.Media.BrushConverter]::new().ConvertFromString('#DDE3EF')
    $null=$panel.Children.Add($titleLabel);$null=$panel.Children.Add($descriptionLabel)
    $null=$Parent.Children.Add($border)
    return $panel
}
function New-StatBar([string]$Label,[double]$Current,[double]$After) {
    $panel=[Windows.Controls.StackPanel]::new();$panel.Margin='0,0,0,12'
    $title=New-Text $Label 20;$title.Margin='0,0,0,5';$null=$panel.Children.Add($title)
    $frame=[Windows.Controls.Border]::new();$frame.Height=24;$frame.BorderThickness='2'
    $frame.BorderBrush=[Windows.Media.BrushConverter]::new().ConvertFromString('#CED5E2')
    $frame.Background=[Windows.Media.BrushConverter]::new().ConvertFromString('#141B2A')
    $track=[Windows.Controls.Grid]::new();$frame.Child=$track
    foreach($width in @($Current,($After-$Current),(100-$After))){
        $column=[Windows.Controls.ColumnDefinition]::new()
        $column.Width=if($width -le 0){[Windows.GridLength]::new(0)}else{[Windows.GridLength]::new($width,[Windows.GridUnitType]::Star)}
        $null=$track.ColumnDefinitions.Add($column)
    }
    $fill=[Windows.Controls.Border]::new();$fill.Background=$script:MenuWindow.Resources['SelectedSteel'];$null=$track.Children.Add($fill)
    $gain=[Windows.Controls.Border]::new();$gain.Background=[Windows.Media.BrushConverter]::new().ConvertFromString('#55D88C')
    [Windows.Controls.Grid]::SetColumn($gain,1);$null=$track.Children.Add($gain)
    $panel.Tag=@{label=$Label;current=$Current;after=$After}
    [Windows.Automation.AutomationProperties]::SetName($panel,$Label+' · huidige stand en na montage')
    $null=$panel.Children.Add($frame);return $panel
}
function Money-Text([int]$Value) {return 'ƒ '+$Value.ToString('N0',[Globalization.CultureInfo]::GetCultureInfo('nl-NL'))}
function Key-Text([int]$Value) {
    switch($Value){17{return 'Ctrl'}18{return 'Alt'}37{return '← Links'}38{return '↑ Gas'}39{return '→ Rechts'}40{return '↓ Rem'}}
    return [Windows.Input.KeyInterop]::KeyFromVirtualKey($Value).ToString()
}
function Make-PreviewPart($Data,[int]$TextureIndex) {
    $mesh=[Windows.Media.Media3D.MeshGeometry3D]::new()
    foreach($v in $Data.positions){$mesh.Positions.Add([Windows.Media.Media3D.Point3D]::new($v[0],$v[1],$v[2]))}
    if(($Data -is [Collections.IDictionary] -and $Data.Contains('normals')) -or $Data.PSObject.Properties['normals']){
        foreach($n in $Data.normals){$mesh.Normals.Add([Windows.Media.Media3D.Vector3D]::new($n[0],$n[1],$n[2]))}
    }
    foreach($uv in $Data.uv){$mesh.TextureCoordinates.Add([Windows.Point]::new($uv[0],$uv[1]))}
    foreach($t in $Data.triangles){foreach($i in $t){$mesh.TriangleIndices.Add([int]$i)}}
    $brush=[Windows.Media.ImageBrush]::new($script:Textures[$TextureIndex])
    $brush.ViewportUnits='Absolute';$brush.Viewport=[Windows.Rect]::new(0,0,1,1);$brush.TileMode=if($TextureIndex -eq 3){'None'}else{'Tile'}
    $material=[Windows.Media.Media3D.DiffuseMaterial]::new($brush)
    $part=[Windows.Media.Media3D.GeometryModel3D]::new($mesh,$material);$part.BackMaterial=$material
    return $part
}
function Make-CarView([int]$Id,[bool]$Compact=$false) {
    $view=[Windows.Controls.Viewport3D]::new();$view.IsHitTestVisible=$false
    $spritePath=Join-Path $PSScriptRoot "assets/car$Id-preview.png"
    if(Test-Path -LiteralPath $spritePath){
        $image=[Windows.Media.Imaging.BitmapImage]::new([Uri]::new($spritePath))
        $halfWidth=2.5;$halfHeight=$halfWidth*$image.PixelHeight/$image.PixelWidth
        $mesh=[Windows.Media.Media3D.MeshGeometry3D]::new()
        foreach($v in @(@(-$halfWidth,-$halfHeight),@($halfWidth,-$halfHeight),@($halfWidth,$halfHeight),@(-$halfWidth,$halfHeight))){$mesh.Positions.Add([Windows.Media.Media3D.Point3D]::new($v[0],$v[1],0))}
        foreach($uv in @(@(0,1),@(1,1),@(1,0),@(0,0))){$mesh.TextureCoordinates.Add([Windows.Point]::new($uv[0],$uv[1]))}
        foreach($i in @(0,1,2,0,2,3)){$mesh.TriangleIndices.Add($i)}
        $material=[Windows.Media.Media3D.DiffuseMaterial]::new([Windows.Media.ImageBrush]::new($image))
        $model=[Windows.Media.Media3D.GeometryModel3D]::new($mesh,$material);$model.BackMaterial=$material
        $group=[Windows.Media.Media3D.Model3DGroup]::new();$null=$group.Children.Add([Windows.Media.Media3D.AmbientLight]::new([Windows.Media.Colors]::White));$null=$group.Children.Add($model)
        $visual=[Windows.Media.Media3D.ModelVisual3D]::new();$visual.Content=$group;$null=$view.Children.Add($visual)
        $view.Camera=[Windows.Media.Media3D.OrthographicCamera]::new([Windows.Media.Media3D.Point3D]::new(0,0,10),[Windows.Media.Media3D.Vector3D]::new(0,0,-10),[Windows.Media.Media3D.Vector3D]::new(0,1,0),$(if($Compact){8}else{5.6}))
        $view.Tag=@{spriteHeight=2*$halfHeight}
        $view.Add_SizeChanged({param($sender,$event)
            $sender.Camera.Width=[Math]::Max(5.6,$sender.Tag.spriteHeight*$sender.ActualWidth/[Math]::Max(1,$sender.ActualHeight)*1.1)
        })
        return $view
    }
    $camera=[Windows.Media.Media3D.PerspectiveCamera]::new()
    $distance=if($Compact){1.65}else{1.0}
    $camera.Position=[Windows.Media.Media3D.Point3D]::new(52*$distance,9+21*$distance,64*$distance)
    $camera.LookDirection=[Windows.Media.Media3D.Vector3D]::new(-52*$distance,-21*$distance,-64*$distance)
    $camera.UpDirection=[Windows.Media.Media3D.Vector3D]::new(0,1,0);$camera.FieldOfView=43
    $view.Camera=$camera
    $group=[Windows.Media.Media3D.Model3DGroup]::new()
    $null=$group.Children.Add([Windows.Media.Media3D.AmbientLight]::new([Windows.Media.ColorConverter]::ConvertFromString('#B4BFD7')))
    $null=$group.Children.Add([Windows.Media.Media3D.DirectionalLight]::new([Windows.Media.Colors]::White,[Windows.Media.Media3D.Vector3D]::new(-1,-2,-1)))
    $data=$script:Meshes[$Id]
    $paintColor=if($data.PSObject.Properties['paint_color']){$data.paint_color}else{'#C4C7CC'}
    $body=Make-PreviewPart $data $data.texture_index
    if($data.PSObject.Properties['body_color'] -and $data.body_color){
        $body.Material=[Windows.Media.Media3D.DiffuseMaterial]::new([Windows.Media.BrushConverter]::new().ConvertFromString($data.body_color));$body.BackMaterial=$body.Material
    }
    $null=$group.Children.Add($body)
    if($data.PSObject.Properties['roof_triangles'] -and $data.roof_triangles.Count){
        $roof=Make-PreviewPart @{positions=$data.positions;normals=$data.normals;uv=$data.uv;triangles=$data.roof_triangles} $data.texture_index
        $paint=[Windows.Media.Media3D.DiffuseMaterial]::new([Windows.Media.BrushConverter]::new().ConvertFromString($paintColor))
        $roof.Material=$paint;$roof.BackMaterial=$paint;$null=$group.Children.Add($roof)
    }
    if($data.PSObject.Properties['paint_triangles'] -and $data.paint_triangles.Count){
        $panel=Make-PreviewPart @{positions=$data.positions;normals=$data.normals;uv=$data.uv;triangles=$data.paint_triangles} $data.texture_index
        $paint=[Windows.Media.Media3D.DiffuseMaterial]::new([Windows.Media.BrushConverter]::new().ConvertFromString($paintColor))
        $panel.Material=$paint;$panel.BackMaterial=$paint;$null=$group.Children.Add($panel)
    }
    if($data.PSObject.Properties['glass_triangles'] -and $data.glass_triangles.Count){
        $glass=Make-PreviewPart @{positions=$data.positions;normals=$data.normals;uv=$data.uv;triangles=$data.glass_triangles} $data.texture_index
        $surface=[Windows.Media.BrushConverter]::new().ConvertFromString('#293D52')
        $material=[Windows.Media.Media3D.DiffuseMaterial]::new($surface)
        $glass.Material=$material;$glass.BackMaterial=$material;$null=$group.Children.Add($glass)
    }
    if($data.PSObject.Properties['headlamp_triangles'] -and $data.headlamp_triangles.Count){
        $lamps=Make-PreviewPart @{positions=$data.positions;normals=$data.normals;uv=$data.uv;triangles=$data.headlamp_triangles} $data.texture_index
        $surface=[Windows.Media.BrushConverter]::new().ConvertFromString($paintColor)
        $material=[Windows.Media.Media3D.DiffuseMaterial]::new($surface)
        $lamps.Material=$material;$lamps.BackMaterial=$material;$null=$group.Children.Add($lamps)
    }
    if($data.PSObject.Properties['trim_triangles'] -and $data.trim_triangles.Count){
        $trim=Make-PreviewPart @{positions=$data.positions;normals=$data.normals;uv=$data.uv;triangles=$data.trim_triangles} $data.texture_index
        $trim.Material=[Windows.Media.Media3D.DiffuseMaterial]::new([Windows.Media.BrushConverter]::new().ConvertFromString('#262930'));$trim.BackMaterial=$trim.Material;$null=$group.Children.Add($trim)
    }
    if($data.PSObject.Properties['headlamp_centers']){
        foreach($center in $data.headlamp_centers){
            foreach($radius in @(1.05,.82)){
                $disk=[Windows.Media.Media3D.MeshGeometry3D]::new()
                $disk.Positions.Add([Windows.Media.Media3D.Point3D]::new($center[0],$center[1],$center[2]+$(if($radius -lt 1){.05}else{0})))
                for($i=0;$i -lt 24;$i++){
                    $angle=$i*[Math]::PI/12
                    $disk.Positions.Add([Windows.Media.Media3D.Point3D]::new($center[0]+$radius*[Math]::Cos($angle),$center[1]+.72*$radius*[Math]::Sin($angle),$center[2]-.7*$radius*[Math]::Sin($angle)+$(if($radius -lt 1){.05}else{0})))
                    $disk.TriangleIndices.Add(0);$disk.TriangleIndices.Add($i+1);$disk.TriangleIndices.Add(($i+1)%24+1)
                }
                $color=if($radius -lt 1){'#FFEAB5'}else{'#22252C'}
                $material=[Windows.Media.Media3D.DiffuseMaterial]::new([Windows.Media.BrushConverter]::new().ConvertFromString($color))
                $lamp=[Windows.Media.Media3D.GeometryModel3D]::new($disk,$material);$lamp.BackMaterial=$material;$null=$group.Children.Add($lamp)
            }
        }
    }
    foreach($center in $data.wheel_centers){
        $wheel=Make-PreviewPart $script:Wheel 2
        $wheel.Transform=[Windows.Media.Media3D.TranslateTransform3D]::new($center[0],$center[1],$center[2])
        $null=$group.Children.Add($wheel)
    }
    $visual=[Windows.Media.Media3D.ModelVisual3D]::new();$visual.Content=$group
    $null=$view.Children.Add($visual);return $view
}
function Update-Home {
    $script:Initializing=$true
    try {
        $p=Current-Profile
        $script:Controls.PlayerName.Text=$p.name
        $script:Controls.Money.Text=Money-Text $p.money
        $script:Controls.HeaderBudget.Text=Money-Text $p.money
        $script:Controls.Damage.Text=[string]$p.damage+'%'
        $script:Controls.DamageBar.Value=$p.damage
        $script:Controls.CarName.Text=$script:Catalog.cars[$p.car].name
        $script:Controls.TrackChoice.ItemsSource=@($script:Catalog.tracks | Where-Object { $_.id -le $p.next_track })
        $script:Controls.CampaignProgress.Text=if($p.next_track -ge 7){'Alle 7 etappes voltooid · kies een race om opnieuw te rijden'}else{'Voortgang: '+$p.next_track+' van 7 etappes voltooid · voltooi '+$script:Catalog.tracks[$p.next_track].name+' om verder te gaan'}
        $script:Controls.TrackChoice.SelectedValue=$script:Model.track
        $track=$script:Catalog.tracks[$script:Model.track]
        $script:Controls.TrackDescription.Text=if($track.city){'Stedenrace · '+$script:Model.settings.laps+' ronden'}else{'Snelwegrace · van start tot finish'}
        $script:Controls.CarViewport.Children.Clear()
        $preview=Make-CarView $p.car
        $script:Controls.CarViewport.Camera=$preview.Camera
        $script:Controls.CarViewport.Tag=$preview.Tag
        if($preview.Camera -is [Windows.Media.Media3D.OrthographicCamera] -and $script:Controls.CarViewport.ActualHeight -gt 0){
            $preview.Camera.Width=[Math]::Max(5.6,$preview.Tag.spriteHeight*$script:Controls.CarViewport.ActualWidth/$script:Controls.CarViewport.ActualHeight*1.1)
        }
        $visual=$preview.Children[0];$null=$preview.Children.Remove($visual)
        $script:Controls.CarViewport.Children.Add($visual)
        $script:MenuWindow.Cursor=$script:Cursors[$(if($script:Model.settings.large_cursor){48}else{32})]
        Set-Status $script:Model.last_message
    } finally {$script:Initializing=$false}
}
function Show-Page([string]$Page) {
    $script:DetailSection=$null
    $script:Page=$Page;$script:WaitingKey=$null
    foreach($name in @('NavHome','NavGarage','NavCars','NavControls','NavOptions','NavRecords','NavPlayers','NavReset')){
        $b=$script:Controls[$name]
        if($name -eq 'NavReset'){
            $b.Background=[Windows.Media.BrushConverter]::new().ConvertFromString($(if($Page -eq 'Reset'){'#B94A2E'}else{'#80361F'}))
        }else{
            $b.Background=if($b.Tag -eq $Page){$script:MenuWindow.Resources['SelectedSteel']}else{$script:MenuWindow.Resources['Steel']}
            $b.Foreground=[Windows.Media.BrushConverter]::new().ConvertFromString($(if($b.Tag -eq $Page){'#FFF5DB'}else{'#98151C'}))
        }
    }
    $script:Controls.HomeView.Visibility=if($Page -eq 'Home'){'Visible'}else{'Collapsed'}
    $script:Controls.DetailView.Visibility=if($Page -eq 'Home'){'Collapsed'}else{'Visible'}
    $script:Controls.DetailContent.Children.Clear()
    $p=Current-Profile;$car=$script:Catalog.cars[$p.car]
    $titles=@{Home='Hoofdmenu';Garage='Garage';Cars='Showroom';Controls='Besturing';Options='Opties';Records='Records';Players='Spelers';Reset='Opnieuw beginnen'}
    $script:Controls.Header.Text=$titles[$Page].ToUpperInvariant();$script:Controls.DetailTitle.Text=$titles[$Page]
    switch($Page){
        'Garage' {
            $summary=New-Text ($car.name+' · onderdelen en reparatie') 23;$summary.Margin='0,0,0,12';Add-Detail $summary
            New-DetailSection 'Autostatistieken'
            $stats=$script:Catalog.garage_stats
            $labels=@{speed='Snelheid';acceleration='Acceleratie';braking='Remmen';handling='Wegligging'}
            $script:GarageBars=@{};$script:UpgradeBars=@{}
            foreach($key in @('speed','acceleration','braking','handling')){
                $bar=New-StatBar $labels[$key] $stats.bars.$key $stats.bars.$key
                $script:GarageBars[$key]=$bar;Add-Detail $bar
            }
            Add-Detail (New-Text 'Blauw: jouw auto nu     Groen: verbetering na montage' 17)
            $script:DetailSection=$null
            $wrap=[Windows.Controls.WrapPanel]::new();Add-Detail $wrap
            $partLabels=@{motor='Motor';tires='Banden';turbo='Turbo';brakes='Remmen / ABS';gears='Versnellingsbak'}
            $descriptions=@{motor='Motorupgrade';tires='Bandenupgrade';turbo='Turboupgrade';brakes='Remmenupgrade';gears='Transmissie-upgrade'}
            $script:UpgradeButtons=@{}
            foreach($item in @('motor','tires','turbo','brakes','gears')){
                $owned=$p.upgrades.$item;$cost=$car.upgrades.$item
                $panel=New-GarageCard $partLabels[$item] $descriptions[$item] $wrap
                $image=[Windows.Controls.Image]::new();$image.Source=$script:PartArt[$item]
                $image.Height=100;$image.Stretch='Uniform';$image.Margin='0,4,0,8';$image.IsHitTestVisible=$false
                $null=$panel.Children.Insert(1,$image)
                $effect=$script:Catalog.upgrade_effects.$item
                $script:UpgradeBars[$item]=@{}
                foreach($key in @('speed','acceleration','braking','handling')){
                    if($effect.$key -gt 0){
                        $bar=New-StatBar $labels[$key] $stats.bars.$key $stats.bars_after_purchase.$item.$key
                        $script:UpgradeBars[$item][$key]=$bar;$null=$panel.Children.Add($bar)
                    }
                }
                if($item -eq 'turbo'){$null=$panel.Children.Add((New-Text 'Tijdelijke boost · gebruik de turbotoets' 18))}
                $text=if($owned){'Gemonteerd'}else{'Monteren · '+(Money-Text $cost)}
                $button=Add-Action $text 'upgrade' $item $panel
                $button.FontSize=20;$button.MinHeight=48;$button.Padding='12,10';$button.Margin='0'
                $button.IsEnabled=(-not $owned) -and $p.money -ge $cost
                $script:UpgradeButtons[$item]=$button
            }
            $panel=New-GarageCard 'Reparatie' ($p.damage.ToString()+'% schade') $wrap
            $preview=Make-CarView $p.car $true;$preview.Height=130;$preview.Margin='0,4,0,8';$null=$panel.Children.Insert(1,$preview)
            $script:RepairPreview=$preview
            $repair=Add-Action ('Repareren · '+(Money-Text ($p.damage*$car.repair))) 'repair' $null $panel
            $repair.FontSize=20;$repair.MinHeight=48;$repair.Padding='12,10';$repair.Margin='0'
            $repair.IsEnabled=$p.damage -gt 0 -and $p.money -ge ($p.damage*$car.repair)
        }
        'Cars' {
            Add-Detail (New-Text ('Budget '+(Money-Text $p.money)+'. Een nieuwe auto vervangt je huidige auto en onderdelen.') 21)
            $wrap=[Windows.Controls.WrapPanel]::new();Add-Detail $wrap
            foreach($item in $script:Catalog.cars){
                $panel=New-GarageCard $item.name '' $wrap
                $preview=Make-CarView $item.id;$preview.Height=155;$null=$panel.Children.Add($preview)
                $null=$panel.Children.Add((New-Text ($item.speed.ToString()+' km/u · '+(Money-Text $item.price)) 20))
                $button=Add-Action $(if($item.id -eq $p.car){'Jouw auto'}else{'Auto kopen'}) 'buy' $item.id $panel
                $button.IsEnabled=$item.id -ne $p.car -and $p.money -ge $item.price
            }
        }
        'Controls' {
            Add-Detail (New-Text 'Klik op een actie en druk de gewenste toets. Esc annuleert. Je kunt het hele menu ook met Tab en Enter bedienen.' 21)
            $labels=@{LEFT='Links sturen';RIGHT='Rechts sturen';UP='Gas';DOWN='Remmen';EXTRA1='Turbo';EXTRA2='Handrem'}
            foreach($key in @('UP','DOWN','LEFT','RIGHT','EXTRA1','EXTRA2')){
                $null=Add-Action ($labels[$key]+'     '+(Key-Text $script:Model.settings.keys.$key)) 'key' $key
            }
        }
        'Options' {
            New-DetailSection 'Beeld'
            Add-Detail (New-Text 'Kies je raceweergave. Breedbeeld gebruikt meer ruimte links en rechts en behoudt de verhoudingen van de auto.' 21)
            Add-Detail (New-Text 'Raceweergave' 23)
            $script:RaceDisplay=[Windows.Controls.ComboBox]::new()
            $script:RaceDisplay.ItemsSource=@('Schermvullend 16:9 (1280 × 720)','Klassiek 4:3 (640 × 480)')
            $script:RaceDisplay.SelectedIndex=if($script:Model.settings.race_display -eq 'widescreen'){0}else{1}
            Add-Detail $script:RaceDisplay
            New-DetailSection 'Geluid'
            Add-Detail (New-Text 'Geluidseffecten' 23)
            $script:Effects=[Windows.Controls.Slider]::new();$script:Effects.Minimum=0;$script:Effects.Maximum=3100;$script:Effects.Value=$script:Model.settings.effects;$script:Effects.TickFrequency=100;$script:Effects.Height=38;Add-Detail $script:Effects
            Add-Detail (New-Text 'Menumuziek (0 = uit)' 23)
            $script:MenuMusic=[Windows.Controls.Slider]::new();$script:MenuMusic.Minimum=0;$script:MenuMusic.Maximum=3100;$script:MenuMusic.Value=$script:Model.settings.menu_music;$script:MenuMusic.Height=38;Add-Detail $script:MenuMusic
            Add-Detail (New-Text 'Racemuziek (de originele race kan muziek uitschakelen)' 23)
            $script:Music=[Windows.Controls.Slider]::new();$script:Music.Minimum=0;$script:Music.Maximum=3100;$script:Music.Value=$script:Model.settings.music;$script:Music.Height=38;Add-Detail $script:Music
            New-DetailSection 'Cursor'
            $script:Large=[Windows.Controls.CheckBox]::new();$script:Large.Content='Grote, duidelijke cursor';$script:Large.IsChecked=$script:Model.settings.large_cursor;Add-Detail $script:Large
            $script:Center=[Windows.Controls.CheckBox]::new();$script:Center.Content='Cursor centreren als het menu weer actief wordt';$script:Center.IsChecked=$script:Model.settings.center_cursor;Add-Detail $script:Center
            New-DetailSection 'Race'
            Add-Detail (New-Text 'Moeilijkheid' 23)
            $script:Difficulty=[Windows.Controls.ComboBox]::new();$script:Difficulty.ItemsSource=@('Makkelijk','Moeilijk');$script:Difficulty.SelectedIndex=$script:Model.settings.difficulty;Add-Detail $script:Difficulty
            Add-Detail (New-Text 'Ronden bij een stedenrace (1–20)' 23)
            $script:Laps=[Windows.Controls.TextBox]::new();$script:Laps.Text=[string]$script:Model.settings.laps;$script:Laps.MaxLength=2;Add-Detail $script:Laps
            $script:DetailSection=$null
            $null=Add-Action 'Instellingen opslaan' 'settings'
        }
        'Reset' {
            Add-Detail (New-Text 'Een frisse start' 30)
            Add-Detail (New-Text 'Hiermee wis je alle Revival-spelers, aankopen, onderdelen, schade, records en instellingen van dit menu.' 23)
            Add-Detail (New-Text 'Je begint opnieuw met één nieuwe Speler, de Brabant, ƒ 35.000 en Amsterdam als eerste etappe.' 23)
            Add-Detail (New-Text 'De volgende knop vraagt eerst om bevestiging. Kies Nee als je je huidige voortgang wilt behouden.' 21)
            $reset=Add-Action 'Alles wissen en opnieuw beginnen…' 'reset'
            $reset.Style=$script:MenuWindow.Resources['ResetAction']
        }
        'Players' {
            Add-Detail (New-Text 'Deze spelers horen bij het nieuwe menu. Je eerdere testspelers blijven bewaard in hun eigen testmappen.' 21)
            $script:PlayerChoice=[Windows.Controls.ComboBox]::new();$script:PlayerChoice.ItemsSource=@($script:Model.profiles);$script:PlayerChoice.DisplayMemberPath='name';$script:PlayerChoice.SelectedValuePath='id';$script:PlayerChoice.SelectedValue=$script:Model.selected;Add-Detail $script:PlayerChoice
            $null=Add-Action 'Met deze speler verder' 'select-player'
            Add-Detail (New-Text 'Nieuwe speler' 28)
            $script:NewName=[Windows.Controls.TextBox]::new();$script:NewName.MaxLength=24;Add-Detail $script:NewName
            $null=Add-Action 'Speler aanmaken' 'new-player'
        }
        'Records' {
            Add-Detail (New-Text ('Beste racetijden van '+$p.name) 26)
            foreach($track in $script:Catalog.tracks){
                $record=$p.records.PSObject.Properties[[string]$track.id]
                $text=if($record){[TimeSpan]::FromMilliseconds($record.Value).ToString('mm\:ss\.fff')}else{'Nog geen finish'}
                $row=[Windows.Controls.Border]::new();$row.Style=$script:MenuWindow.Resources['GarageCard'];$row.Margin='0,0,0,10';$row.Padding='16'
                $grid=[Windows.Controls.Grid]::new()
                $null=$grid.ColumnDefinitions.Add([Windows.Controls.ColumnDefinition]::new())
                $column=[Windows.Controls.ColumnDefinition]::new();$column.Width=[Windows.GridLength]::new(240);$null=$grid.ColumnDefinitions.Add($column)
                $name=New-Text $track.name 23;$name.Margin='0';$null=$grid.Children.Add($name)
                $time=New-Text $text 23;$time.Margin='0';[Windows.Controls.Grid]::SetColumn($time,1);$null=$grid.Children.Add($time)
                $row.Child=$grid;Add-Detail $row
            }
        }
    }
}
function Invoke-Action([string]$Action,$Value=$null) {
    try {
        switch($Action){
            'name' {Invoke-Backend 'name' @{name=$script:Controls.PlayerName.Text}}
            'repair' {Invoke-Backend 'repair'}
            'upgrade' {Invoke-Backend 'upgrade' @{item=$Value}}
            'buy' {Invoke-Backend 'buy' @{car=[int]$Value}}
            'new-player' {Invoke-Backend 'player' @{new_name=$script:NewName.Text}}
            'select-player' {Invoke-Backend 'player' @{id=$script:PlayerChoice.SelectedValue}}
            'key' {$script:WaitingKey=$Value;Set-Status 'Druk de nieuwe toets. Esc annuleert.';return}
            'settings' {
                Invoke-Backend 'settings' @{effects=[int]$script:Effects.Value;music=[int]$script:Music.Value;menu_music=[int]$script:MenuMusic.Value;
                    large_cursor=[bool]$script:Large.IsChecked;center_cursor=[bool]$script:Center.IsChecked;
                    difficulty=$script:Difficulty.SelectedIndex;laps=[int]$script:Laps.Text;
                    race_display=$(if($script:RaceDisplay.SelectedIndex -eq 0){'widescreen'}else{'classic'})}
            }
            'reset' {
                if($script:Race){throw 'Sluit eerst je race af.'}
                if(-not $UiCheck){
                    $answer=[Windows.MessageBox]::Show($script:MenuWindow,
                        'Alle Revival-spelers, aankopen, records en instellingen wissen en opnieuw beginnen?',
                        'Opnieuw beginnen',[Windows.MessageBoxButton]::YesNo,[Windows.MessageBoxImage]::Question,[Windows.MessageBoxResult]::No)
                    if($answer -ne [Windows.MessageBoxResult]::Yes){return}
                }
                Invoke-Backend 'reset' @{confirmed=$true};$script:Page='Home'
            }
            'race' {Start-MenuRace;return}
            default {throw 'Onbekende menuactie.'}
        }
        Update-Home;Show-Page $script:Page
        Set-IIMenuMusic (-not $script:Race -and -not $script:Closing) $script:Model.settings.menu_music
    } catch {Set-Status $_.Exception.Message $true;Write-MenuEvent 'menu-action-error' $_.Exception.Message}
}
function Start-MenuRace {
    if($script:Race){return}
    if($script:Controls.PlayerName.Text -cne (Current-Profile).name){Invoke-Backend 'name' @{name=$script:Controls.PlayerName.Text}}
    Invoke-Backend 'start'
    $script:RaceToken=$script:Model.pending.token
    try {
        Set-IIMenuMusic $false $script:Model.settings.menu_music
        if($UiCheck){
            $script:Race=[AtlasIIFakeRace]::new();$script:FakeStarted++
        }else{
            $script:Session=[AtlasIIOwnedSession]::Begin()
            $info=[Diagnostics.ProcessStartInfo]::new()
            $binary=if($script:Model.pending.race_display -eq 'widescreen'){'SPEL-WIDE.DAT'}else{'SPEL.DAT'}
            $info.FileName=Join-Path $PSScriptRoot ('game/DATA/'+$binary)
            $info.WorkingDirectory=Join-Path $PSScriptRoot 'game/DATA'
            $info.UseShellExecute=$false;$info.Environment['NOCD']=[IO.Path]::GetPathRoot($PSScriptRoot).Substring(0,1)
            $script:Race=[Diagnostics.Process]::new();$script:Race.StartInfo=$info
            if(-not $script:Race.Start()){throw 'Race kon niet starten.'}
            $script:Session.Track($script:Race,$true)
            $script:ChunkClock=[Diagnostics.Stopwatch]::StartNew();$script:NextChunkRead=1000
            Write-MenuEvent 'race-started' @{pid=$script:Race.Id;track=$script:Model.track;car=(Current-Profile).car;
                race_display=$script:Model.pending.race_display;binary=$binary;
                requested_canvas=$(if($binary -eq 'SPEL-WIDE.DAT'){@(1280,720)}else{@(640,480)})}
        }
        $script:StopClock=$null
        $script:CloseRequested=$false;$script:ForcedClose=$false
        if(-not $UiCheck -or $script:TestingLifetime){$script:MenuWindow.Hide();$script:RaceTimer.Start()}
    } catch {
        if($script:Race){try{if(-not $script:Race.HasExited){$script:Race.Kill()}}catch{};$script:Race.Dispose();$script:Race=$null}
        if($script:Session){$script:Session.Dispose();$script:Session=$null}
        Invoke-Backend 'discard';Set-IIMenuMusic $true $script:Model.settings.menu_music;throw
    }
}
function Poll-MenuRace {
    if(-not $script:Race){return}
    try {
        if(-not $UiCheck -and $script:Session -and $script:Config.PSObject.Properties['distance_diagnostics'] -and
            $script:Config.distance_diagnostics -eq $true -and $script:ChunkClock -and
            $script:ChunkClock.ElapsedMilliseconds -ge $script:NextChunkRead -and -not $script:Race.HasExited){
            $script:NextChunkRead=$script:ChunkClock.ElapsedMilliseconds+1000
            $diagnosticMaximum=50
            if($script:Config.PSObject.Properties['visiblechunks_trial'] -and $script:Config.visiblechunks_trial -eq 60){$diagnosticMaximum=60}
            $chunkCount=$script:Session.ReadVisibleChunks($script:Race,$diagnosticMaximum)
            Write-MenuEvent 'visiblechunks-runtime' @{count=$chunkCount;read_only=$true;elapsed_ms=$script:ChunkClock.ElapsedMilliseconds}
        }
        if($script:Session -and $script:Session.StopRequested -and -not $script:Race.HasExited){
            $script:CloseRequested=$true
            if(-not $script:StopClock){
                $script:StopClock=[Diagnostics.Stopwatch]::StartNew()
                $null=$script:Race.CloseMainWindow();Write-MenuEvent 'alt-f4-requested'
            }elseif($script:StopClock.ElapsedMilliseconds -ge 1500 -and -not $script:ForcedClose){
                $script:Race.Kill();$script:ForcedClose=$true;Write-MenuEvent 'owned-race-forced-close'
            }
        }
        if(-not $script:Race.HasExited){return}
        $script:RaceTimer.Stop()
        $code=$script:Race.ExitCode
        $stop=$script:Session -and $script:Session.StopRequested
        $script:Race.Dispose();$script:Race=$null
        if($UiCheck){$script:FakeDisposed++}
        if($script:Session){$script:Session.Dispose();$script:Session=$null}
        Write-MenuEvent 'race-exited' $code
        if($stop){$script:MenuWindow.Close();return}
        Invoke-Backend 'finish' @{token=$script:RaceToken;exit_code=$code}
        Update-Home;Show-Page 'Home'
        if(-not $UiCheck){$script:MenuWindow.Show();$null=$script:MenuWindow.Activate();Set-IIMenuMusic $true $script:Model.settings.menu_music}
    } catch {
        $script:RaceTimer.Stop()
        $requested=$script:CloseRequested -or ($script:Session -and $script:Session.StopRequested)
        if($script:Session){$script:Session.Dispose();$script:Session=$null}
        if($script:Race){$script:Race.Dispose();$script:Race=$null}
        try{Invoke-Backend 'discard'}catch{}
        if($requested){$script:MenuWindow.Close();return}
        Set-Status $_.Exception.Message $true
        if(-not $UiCheck){$script:MenuWindow.Show();Set-IIMenuMusic $true $script:Model.settings.menu_music}
    }
}

try {
    if([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA'){throw 'Start het menu met PowerShell -STA.'}
    Assert-MenuPath $PSScriptRoot
    $script:Config=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Frontend.json') -Raw|ConvertFrom-Json -Depth 32
    if($script:Config.schema -ne 1 -or $script:Config.game -cne 'a2racer2' -or $script:Config.native_menu_used -ne $false){throw 'Onbekend menucontract.'}
    $prefix=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')+'\'
    foreach($file in $script:Config.files){
        $path=[IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot,$file.path));Assert-MenuPath $path
        if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
           (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $file.sha256){throw ('Menubestand veranderde: '+$file.path)}
    }
    Assert-MenuPath $script:Config.python
    Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
    . (Join-Path $PSScriptRoot 'OwnedSession.ps1');Import-IIOwnedSession
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AtlasIIMenuMonitor {
 [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left,Top,Right,Bottom; }
 [StructLayout(LayoutKind.Sequential)] struct INFO { public int Size; public RECT Monitor,Work; public uint Flags; }
 [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr hwnd,uint flags);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern bool GetMonitorInfoW(IntPtr monitor,ref INFO info);
 [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hwnd,IntPtr after,int x,int y,int w,int h,uint flags);
 [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hwnd,out RECT rect);
 [DllImport("user32.dll")] static extern bool SetCursorPos(int x,int y);
 public static void Fill(IntPtr hwnd) {
   var info=new INFO { Size=Marshal.SizeOf<INFO>() };
   if(hwnd==IntPtr.Zero || !GetMonitorInfoW(MonitorFromWindow(hwnd,2),ref info)) return;
   var r=info.Monitor;SetWindowPos(hwnd,IntPtr.Zero,r.Left,r.Top,r.Right-r.Left,r.Bottom-r.Top,0x14);
 }
 public static void Center(IntPtr hwnd) {RECT r;if(hwnd!=IntPtr.Zero && GetWindowRect(hwnd,out r)) SetCursorPos((r.Left+r.Right)/2,(r.Top+r.Bottom)/2);}
}
public sealed class AtlasIIFakeRace : IDisposable {
 public bool HasExited {get;set;} public int ExitCode {get;set;} public bool Disposed {get;private set;}
 public void Dispose(){Disposed=true;} public bool CloseMainWindow(){HasExited=true;return true;}
 public void Kill(){HasExited=true;}
}
public sealed class AtlasIIFakeSession : IDisposable {
 public bool StopRequested {get;set;} public bool Disposed {get;private set;}
 public void Dispose(){Disposed=true;}
}
'@
    $xml=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Menu.xaml') -Raw
    $reader=[Xml.XmlReader]::Create([IO.StringReader]::new($xml))
    try{$script:MenuWindow=[Windows.Markup.XamlReader]::Load($reader)}finally{$reader.Dispose()}
    $script:Controls=@{}
    foreach($name in @('Header','HeaderBudget','HomeView','DetailView','DetailTitle','DetailContent','Status','PlayerName','Money','Damage','DamageBar','CarName','CarViewport','CampaignProgress','TrackChoice','TrackDescription','StartRace','SaveName','HomeGarage','Quit','NavHome','NavGarage','NavCars','NavControls','NavOptions','NavRecords','NavPlayers','NavReset')){
        $script:Controls[$name]=$script:MenuWindow.FindName($name)
        if(-not $script:Controls[$name]){throw ('Menubediening ontbreekt: '+$name)}
    }
    $script:Cursors=@{}
    $script:Controls.CarViewport.Add_SizeChanged({param($sender,$event)
        if($sender.Camera -is [Windows.Media.Media3D.OrthographicCamera] -and $sender.Tag){
            $sender.Camera.Width=[Math]::Max(5.6,$sender.Tag.spriteHeight*$sender.ActualWidth/[Math]::Max(1,$sender.ActualHeight)*1.1)
        }
    })
    foreach($size in @(32,48)){
        $stream=[IO.File]::OpenRead((Join-Path $PSScriptRoot ('assets/arrow'+$size+'.cur')))
        try{$script:Cursors[$size]=[Windows.Input.Cursor]::new($stream,$false)}finally{$stream.Dispose()}
    }
    $script:Meshes=@();for($i=0;$i -lt 7;$i++){$script:Meshes+=,(Get-Content -LiteralPath (Join-Path $PSScriptRoot ('assets/car'+$i+'.json')) -Raw|ConvertFrom-Json -Depth 12)}
    $script:Wheel=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'assets/wheel.json') -Raw|ConvertFrom-Json -Depth 12
    $script:Textures=@()
    foreach($i in @(0,1,2,3)){
        $image=[Windows.Media.Imaging.BitmapImage]::new();$image.BeginInit();$image.CacheOption='OnLoad';$image.UriSource=[Uri]::new((Join-Path $PSScriptRoot ('assets/texture'+$i+'.png')));$image.EndInit();$image.Freeze();$script:Textures+=,$image
    }
    $script:PartArt=@{}
    foreach($name in @('motor','tires','turbo','brakes','gears')){
        $image=[Windows.Media.Imaging.BitmapImage]::new();$image.BeginInit();$image.CacheOption='OnLoad'
        $image.DecodePixelWidth=384;$image.UriSource=[Uri]::new((Join-Path $PSScriptRoot ('assets/part-'+$name+'.png')))
        $image.EndInit();$image.Freeze();$script:PartArt[$name]=$image
    }
    if($UiCheck -and (-not $script:Config.PSObject.Properties['synthetic_fixture'] -or $script:Config.synthetic_fixture -ne $true)){throw 'UI-test vereist uitsluitend synthetische fixtures.'}
    if(-not $CheckOnly -and -not $RenderPath){
        $path=Join-Path $PSScriptRoot 'menu.lock';Assert-MenuPath $path
        try {
            $script:MenuLock=[IO.File]::Open($path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        } catch {
            $cause=$_.Exception.GetBaseException()
            if($cause -is [IO.IOException] -and (($cause.HResult -band 0xFFFF) -in @(32,33))) {
                throw 'Dit menu of de bijbehorende race staat al open. Ga terug met Alt+Tab, of sluit die sessie met Alt+F4 voordat je deze test opnieuw opent.'
            }
            throw
        }
    }
    $script:Events=Join-Path $script:Config.report_path ('frontend-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')+'.jsonl')
    Assert-MenuPath $script:Events
    Invoke-Backend $(if($CheckOnly -or $RenderPath){'check'}else{'load'})
    if($RaceDisplayPreference -and -not $CheckOnly -and -not $RenderPath -and -not $UiCheck){
        Invoke-Backend 'settings' @{race_display=$RaceDisplayPreference}
    }
    $script:RaceTimer=[Windows.Threading.DispatcherTimer]::new();$script:RaceTimer.Interval=[TimeSpan]::FromMilliseconds(50)
    $script:RaceTimer.Add_Tick({Poll-MenuRace})
    foreach($name in @('NavHome','NavGarage','NavCars','NavControls','NavOptions','NavRecords','NavPlayers','NavReset')){
        $script:Controls[$name].Add_Click({param($sender,$event)try{Show-Page $sender.Tag}catch{Set-Status $_.Exception.Message $true}})
    }
    $script:Controls.Quit.Add_Click({$script:MenuWindow.Close()})
    $script:Controls.SaveName.Add_Click({Invoke-Action 'name'})
    $script:Controls.HomeGarage.Add_Click({Show-Page 'Garage'})
    $script:Controls.StartRace.Add_Click({Invoke-Action 'race'})
    $script:Controls.TrackChoice.Add_SelectionChanged({
        if(-not $script:Initializing -and $null -ne $script:Controls.TrackChoice.SelectedValue){
            try{Invoke-Backend 'track' @{track=[int]$script:Controls.TrackChoice.SelectedValue};Update-Home}catch{Set-Status $_.Exception.Message $true}
        }
    })
    $script:MenuWindow.Add_PreviewKeyDown({param($sender,$event)
        if($script:WaitingKey){
            $event.Handled=$true
            if($event.Key -eq 'Escape'){$script:WaitingKey=$null;Set-Status 'Toetswijziging geannuleerd.';return}
            try{
                $keys=@{};foreach($p in $script:Model.settings.keys.PSObject.Properties){$keys[$p.Name]=[int]$p.Value}
                $key=if($event.Key -eq 'System'){$event.SystemKey}else{$event.Key}
                $keys[$script:WaitingKey]=[Windows.Input.KeyInterop]::VirtualKeyFromKey($key)
                Invoke-Backend 'settings' @{keys=$keys};$script:WaitingKey=$null;Show-Page 'Controls';Set-Status 'Racetoets opgeslagen.'
            }catch{Set-Status $_.Exception.Message $true}
        }elseif($event.Key -eq 'Escape'){
            $event.Handled=$true
            if($script:Page -ne 'Home'){Show-Page 'Home'}else{$script:MenuWindow.Close()}
        }
    })
    $script:MenuWindow.Add_SourceInitialized({if(-not $UiCheck){[AtlasIIMenuMonitor]::Fill([Windows.Interop.WindowInteropHelper]::new($script:MenuWindow).Handle)}})
    $script:MenuWindow.Add_Activated({
        if(-not $UiCheck -and $script:Model.settings.center_cursor -and -not $script:Race){[AtlasIIMenuMonitor]::Center([Windows.Interop.WindowInteropHelper]::new($script:MenuWindow).Handle)}
    })
    $script:MenuWindow.Add_Closed({$script:Closing=$true;Close-IIMenuMusic;$script:RaceTimer.Stop();if($script:LifetimeFrame){$script:LifetimeFrame.Continue=$false};if($script:Session){$script:Session.Dispose();$script:Session=$null}})
    Update-Home;Show-Page 'Home'
    if($CheckOnly){
        @{menu='replacement-wpf';native_menu_started=$false;game_started=$false;hook_started=$false;
          fullscreen='monitor bounds, borderless';cursor='single Windows hardware cursor';controls=$script:Controls.Count}|ConvertTo-Json
    }elseif($RenderPath){
        if($RenderWidth -lt 640 -or $RenderWidth -gt 3840 -or $RenderHeight -lt 480 -or $RenderHeight -gt 2160){throw 'Ongeldige previewafmetingen.'}
        Assert-MenuPath $RenderPath
        Show-Page $RenderPage
        $content=$script:MenuWindow.Content
        $content.Measure([Windows.Size]::new($RenderWidth,$RenderHeight));$content.Arrange([Windows.Rect]::new(0,0,$RenderWidth,$RenderHeight));$content.UpdateLayout()
        $bitmap=[Windows.Media.Imaging.RenderTargetBitmap]::new($RenderWidth,$RenderHeight,96,96,[Windows.Media.PixelFormats]::Pbgra32)
        $bitmap.Render($content)
        $encoder=[Windows.Media.Imaging.PngBitmapEncoder]::new();$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
        $stream=[IO.File]::Create($RenderPath);try{$encoder.Save($stream)}finally{$stream.Dispose()}
        @{rendered=$RenderPath;game_started=$false;window_shown=$false}|ConvertTo-Json
    }elseif($UiCheck){
        $script:Controls.PlayerName.Text='Fixture Robin';$script:Controls.SaveName.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if((Current-Profile).name -cne 'Fixture Robin'){throw 'Naamknop slaagt niet.'}
        if($script:Controls.TrackChoice.Items.Count -ne 1 -or $script:Model.track -ne 0){throw 'Nieuwe speler kan vergrendelde etappes kiezen.'}
        foreach($page in @('Garage','Cars','Controls','Options','Records','Players')){Show-Page $page}
        Show-Page 'Players';$script:NewName.Text='Tweede speler';Invoke-Action 'new-player'
        if((Current-Profile).name -cne 'Tweede speler'){throw 'Nieuwe speler slaagt niet.'}
        Show-Page 'Options';$script:Large.IsChecked=$false;$script:Laps.Text='3';$script:RaceDisplay.SelectedIndex=1;Invoke-Action 'settings'
        if($script:Model.settings.large_cursor -ne $false -or $script:Model.settings.laps -ne 3 -or $script:Model.settings.race_display -ne 'classic'){throw 'Instellingen slaan niet op.'}
        Show-Page 'Options';$script:RaceDisplay.SelectedIndex=0;Invoke-Action 'settings'
        if($script:Model.settings.race_display -ne 'widescreen'){throw 'Fullscreenkeuze slaat niet op.'}
        Show-Page 'Garage'
        if($script:UpgradeButtons.Count -ne 5 -or $script:PartArt.Count -ne 5){throw 'Garage mist zijn onderdelenafbeeldingen of knoppen.'}
        if($script:RepairPreview.Height -ne 130 -or ($script:RepairPreview.Camera -isnot [Windows.Media.Media3D.OrthographicCamera] -and $script:RepairPreview.Camera.Position.Z -lt 100)){throw 'Reparatiepreview heeft geen ruimte voor de volledige auto.'}
        $spriteCheck=Make-CarView 4
        if($spriteCheck.Camera -isnot [Windows.Media.Media3D.OrthographicCamera]){throw 'Parche gebruikt de gebroken mesh in plaats van zijn preview.'}
        function Read-FixtureText($node) {
            if($node -is [Windows.Controls.TextBlock]){$node.Text}
            if($node -is [Windows.DependencyObject]){
                foreach($child in [Windows.LogicalTreeHelper]::GetChildren($node)){Read-FixtureText $child}
            }
        }
        if($script:GarageBars.Count -ne 4 -or $script:UpgradeBars.motor.speed.Tag.current -ne 25 -or
           $script:UpgradeBars.motor.speed.Tag.after -ne 40 -or $script:UpgradeBars.tires.handling.Tag.after -ne 80){
            throw 'Garagebalken tonen de huidige en toekomstige stand niet correct.'
        }
        if(-not $script:GarageBars.speed.Children[1].Child.Children[0].Background -or
           $script:GarageBars.speed.Children[1].Child.ColumnDefinitions[0].Width.Value -ne 25){throw 'Garagebalk is onzichtbaar of heeft de verkeerde lengte.'}
        $script:UpgradeButtons.motor.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if(-not (Current-Profile).upgrades.motor){throw 'Garageknop slaagt niet.'}
        if($script:GarageBars.speed.Tag.current -ne 40 -or $script:UpgradeBars.motor.speed.Tag.after -ne 40){throw 'Gemonteerde motor telt dubbel in de garagebalk.'}
        Show-Page 'Home';$script:Controls.StartRace.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if($script:FakeStarted -ne 1 -or -not $script:Race){throw 'Startknop start niet precies één neprace.'}
        $fixtureIni=Join-Path $PSScriptRoot 'game/DATA/GAME.INI'
        $fixtureResult=[IO.File]::ReadAllText($fixtureIni).Replace('finished=0','finished=1').Replace('tracktime=0','tracktime=1000')
        [IO.File]::WriteAllText($fixtureIni,$fixtureResult,[Text.UTF8Encoding]::new($false))
        $script:Race.HasExited=$true;Poll-MenuRace
        if($script:FakeDisposed -ne 1 -or $script:Race -or $script:Model.pending){throw 'Terugkeer uit neprace faalt.'}
        if($script:Page -cne 'Home'){throw 'Terugkeer heeft geen hoofdmenu.'}
        if((Current-Profile).next_track -ne 1 -or $script:Controls.TrackChoice.Items.Count -ne 2 -or $script:Controls.TrackChoice.SelectedValue -ne 1){throw 'Finish ontgrendelt niet precies de volgende etappe in het menu.'}
        $beforeReset=$script:Model|ConvertTo-Json -Compress -Depth 32
        $script:Controls.NavReset.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if($script:Page -cne 'Reset' -or ($script:Model|ConvertTo-Json -Compress -Depth 32) -cne $beforeReset){throw 'Resettab opent niet veilig zonder voortgang te wissen.'}
        $resetButton=@($script:Controls.DetailContent.Children|Where-Object {$_ -is [Windows.Controls.Button] -and $_.Tag.action -eq 'reset'})
        if($resetButton.Count -ne 1 -or $resetButton[0].Style -ne $script:MenuWindow.Resources['ResetAction']){throw 'Resettab mist zijn eigen duidelijk gekleurde actie.'}
        $resetButton[0].RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if($script:Model.profiles.Count -ne 1 -or (Current-Profile).name -cne 'Speler' -or (Current-Profile).money -ne 35000 -or $script:Model.track -ne 0 -or -not $script:Model.settings.large_cursor){throw 'Opnieuw beginnen laat oude spelers of keuzes achter.'}
        if((Current-Profile).next_track -ne 0 -or $script:Controls.TrackChoice.Items.Count -ne 1){throw 'Reset laat ontgrendelde etappes achter.'}
        # A synthetic offscreen window exercises the real host lifetime across Hide.
        # No focus/cursor/monitor changes, native job, hook or actual game are used.
        $script:MenuWindow.WindowStartupLocation='Manual';$script:MenuWindow.Left=-20000;$script:MenuWindow.Top=-20000
        $script:MenuWindow.Width=2;$script:MenuWindow.Height=2;$script:MenuWindow.ShowActivated=$false
        $script:MenuWindow.ShowInTaskbar=$false;$script:TestingLifetime=$true;$script:LifetimePhase=0
        $script:LifetimeTicks=0;$script:LifetimeFakeSession=$null
        $driver=[Windows.Threading.DispatcherTimer]::new();$driver.Interval=[TimeSpan]::FromMilliseconds(120)
        $driver.Add_Tick({
            try {
                $script:LifetimeTicks++
                if($script:LifetimeTicks -gt 20){throw 'Menulevensduurtest heeft geen einde.'}
                if($script:LifetimePhase -eq 0){
                    $script:Controls.StartRace.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
                    $script:LifetimePhase=1
                }else{
                    if(-not $script:Race -or $script:MenuWindow.IsVisible -or $script:Closing){throw 'Menu blijft niet leven tijdens de verborgen race.'}
                    $script:LifetimeSurvivedHide=$true
                    $script:LifetimeFakeSession=[AtlasIIFakeSession]::new();$script:LifetimeFakeSession.StopRequested=$true
                    $script:Session=$script:LifetimeFakeSession;Poll-MenuRace
                }
            }catch{$script:LifetimeError=$_.Exception.Message;$script:MenuWindow.Close()}
        })
        $driver.Start()
        try{Invoke-MenuLifetime}finally{$driver.Stop();$script:TestingLifetime=$false}
        if($script:LifetimeError){throw $script:LifetimeError}
        if(-not $script:LifetimeSurvivedHide){throw 'Het verbergen van het menu beeindigt de starter en race.'}
        if(-not $script:LifetimeFakeSession.Disposed -or -not $script:Closing -or $script:Race -or $script:FakeDisposed -ne 2){throw 'Afsluitverzoek laat een neprace of menu achter.'}
        @{ui_actions_passed=$true;fake_races_started=$script:FakeStarted;fake_races_disposed=$script:FakeDisposed;
          close_request_passed=$true;race_lifetime_passed=$script:LifetimeSurvivedHide;
          native_menu_started=$false;game_started=$false;hook_started=$false}|ConvertTo-Json
    }else{
        Initialize-IIMenuMusic;Set-IIMenuMusic $true $script:Model.settings.menu_music
        Write-MenuEvent 'menu-opened';Invoke-MenuLifetime;Write-MenuEvent 'session-closed'
    }
} catch {
    if($script:MenuWindow -and -not $script:Closing){try{$script:MenuWindow.Close()}catch{}}
    if($CheckOnly -or $RenderPath -or $UiCheck){Write-Error $_;exit 1}
    Add-Type -AssemblyName PresentationFramework
    $null=[Windows.MessageBox]::Show(('Het nieuwe menu kon niet starten: '+$_.Exception.Message),'A2 Racer II',0,16)
    exit 1
} finally {
    Close-IIMenuMusic
    if($script:Session){$script:Session.Dispose()}
    if($script:Race){$script:Race.Dispose()}
    if($script:MenuLock){$script:MenuLock.Dispose()}
    foreach($value in @($script:Cursors.Values)){if($value){$value.Dispose()}}
}
