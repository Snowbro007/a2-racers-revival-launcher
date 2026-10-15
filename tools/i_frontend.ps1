#Requires -Version 7.4
[CmdletBinding()]
param([switch]$CheckOnly,[string]$RenderPath,[ValidateSet('Home','Players','Controls','Score')][string]$RenderPage='Home',
      [ValidateRange(320,7680)][int]$RenderWidth=1920,[ValidateRange(240,4320)][int]$RenderHeight=1080,
      [switch]$UiCheck,[ValidateRange(0,86400)][int]$StopAfterSeconds=0)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:Race=$null;$script:Session=$null;$script:Lock=$null;$script:Frame=$null
$script:Page='Home';$script:Closing=$false;$script:WaitingKey=$null;$script:Dialog=$null
$script:ConfirmClearScores=$false
$deadline=$null
function Assert-Path([string]$Path) {
    $p=[IO.Path]::GetFullPath($Path)
    while($p){
        if([IO.File]::Exists($p) -or [IO.Directory]::Exists($p)){
            $attributes=[IO.File]::GetAttributes($p)
            if($attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Menupad bevat een link.'}
            if(-not ($attributes -band [IO.FileAttributes]::Directory)){$i=Get-Item -LiteralPath $p -Force
                if($i.PSObject.Properties['LinkType'] -and $i.LinkType -eq 'HardLink'){throw 'Menupad bevat een gedeeld bestand.'}}}
        $parent=[IO.Directory]::GetParent($p);$p=if($parent){$parent.FullName}else{$null}
    }
}
function Backend([string]$Command,$Payload=@{}) {
    $si=[Diagnostics.ProcessStartInfo]::new();$si.FileName=$script:Config.python
    $si.UseShellExecute=$false;$si.CreateNoWindow=$true;$si.RedirectStandardOutput=$true;$si.RedirectStandardError=$true
    foreach($a in @((Join-Path $PSScriptRoot 'Backend.py'),'--base',$PSScriptRoot,'--command',$Command,'--payload',($Payload|ConvertTo-Json -Compress -Depth 12))){$si.ArgumentList.Add([string]$a)}
    $p=[Diagnostics.Process]::new();$p.StartInfo=$si
    try{
        if(-not $p.Start()){throw 'Menustatus kon niet starten.'}
        $out=$p.StandardOutput.ReadToEndAsync();$err=$p.StandardError.ReadToEndAsync()
        if(-not $p.WaitForExit(15000)){$p.Kill();throw 'Menustatus reageert niet.'}
        $r=$out.GetAwaiter().GetResult()|ConvertFrom-Json -Depth 24
        if($p.ExitCode -ne 0){throw $r.error};$script:Model=$r.state
    }finally{$p.Dispose()}
}
function Current {return @($script:Model.profiles|Where-Object id -eq $script:Model.selected)|Select-Object -First 1}
function Add-At($Element,[double]$X,[double]$Y,[double]$W,[double]$H,$Parent=$script:Canvas) {
    $Element.Width=$W;$Element.Height=$H;[Windows.Controls.Canvas]::SetLeft($Element,$X);[Windows.Controls.Canvas]::SetTop($Element,$Y)
    $null=$Parent.Children.Add($Element);return $Element
}
function Text([string]$Value,[int]$Size=30) {
    $t=[Windows.Controls.TextBlock]::new();$t.Text=$Value;$t.FontSize=$Size;$t.Foreground=[Windows.Media.Brushes]::White
    $t.FontWeight='Bold';$t.TextWrapping='Wrap';return $t
}
function Button([string]$Name,[double]$X,[double]$Y,[double]$W,[double]$H,[scriptblock]$Action,[bool]$Hotspot=$true) {
    $b=[Windows.Controls.Button]::new();$b.Tag=$Name;$b.ToolTip=$Name
    [Windows.Automation.AutomationProperties]::SetName($b,$Name)
    $b.Style=$script:Window.Resources[$(if($Hotspot){'Hotspot'}else{'Action'})]
    if(-not $Hotspot){$b.Content=$Name}
    $b.Add_Click($Action);$null=Add-At $b $X $Y $W $H;return $b
}
function Time-Text($Times) {
    if(@($Times).Count -eq 0){return '—'}
    $ticks=0L;foreach($t in $Times){$ticks+=[long]$t}
    # Native stage time uses 60 units/second (same scale as TRACK/BONUS).
    $seconds=[long][Math]::Floor($ticks/60);return ('{0:00}:{1:00}:{2:00}' -f [Math]::Floor($seconds/3600),[Math]::Floor(($seconds%3600)/60),($seconds%60))
}
function Status([string]$Message){$script:Status.Text=$Message}
function Action([string]$Command,$Payload=@{}) {
    try{Backend $Command $Payload;Show-Page $script:Page}catch{Status $_.Exception.Message}
}
function Confirm([string]$Question) {
    if($UiCheck){return $true}
    return [Windows.MessageBox]::Show($script:Window,$Question,'A2 Racer', 'YesNo','Question') -eq 'Yes'
}
function Clear-Scores {
    $confirmed=if($UiCheck){$script:ConfirmClearScores}else{
        [Windows.MessageBox]::Show($script:Window,
            'Het hele scoreboard voor alle HD-spelers wissen? Namen, geld en etappevoortgang blijven behouden.',
            'Scoreboard wissen','YesNo','Warning','No') -eq 'Yes'
    }
    if($confirmed){Action 'clear_scores' @{confirmed=$true}}
}
function Name-Dialog {
    foreach($child in $script:Canvas.Children){if($child -ne $script:Status){$child.IsEnabled=$false}}
    $script:Dialog=[Windows.Controls.Border]::new();$script:Dialog.Background=[Windows.Media.BrushConverter]::new().ConvertFromString('#F0292442')
    $script:Dialog.BorderBrush=[Windows.Media.Brushes]::Silver;$script:Dialog.BorderThickness='3';$script:Dialog.Padding='35'
    $stack=[Windows.Controls.StackPanel]::new();$script:Dialog.Child=$stack
    $null=$stack.Children.Add((Text 'Nieuwe speler' 36));$null=$stack.Children.Add((Text 'Naam (maximaal 15 tekens)' 24))
    $script:NameBox=[Windows.Controls.TextBox]::new();$script:NameBox.MaxLength=15;$script:NameBox.FontSize=34;$script:NameBox.Margin='0,22,0,22';$null=$stack.Children.Add($script:NameBox)
    foreach($name in @('Opslaan','Annuleren')){
        $b=[Windows.Controls.Button]::new();$b.Style=$script:Window.Resources['Action'];$b.Content=$name;$b.Tag=$name
        if($name -eq 'Opslaan'){$script:SaveName=$b}
        $b.Add_Click({param($sender,$event)
            try{if($sender.Tag -eq 'Opslaan'){Backend 'new' @{name=$script:NameBox.Text}}
                Show-Page 'Home'}catch{Status $_.Exception.Message}})
        $null=$stack.Children.Add($b)
    }
    $script:NameBox.Add_PreviewKeyDown({param($sender,$event)
        if($event.Key -eq 'Return'){$event.Handled=$true;$script:SaveName.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))}})
    $null=Add-At $script:Dialog 430 330 620 370;$null=$script:NameBox.Focus()
}
function Show-Page([string]$Page) {
    $script:Page=$Page;$script:WaitingKey=$null;$script:Dialog=$null;$script:Canvas.Children.Clear()
    $bg=[Windows.Controls.Image]::new();$bg.Source=$script:Images[$(if($Page -eq 'Players'){'Players'}else{'Home'})];$bg.Stretch='Fill';$bg.IsHitTestVisible=$false
    $null=Add-At $bg 0 0 1448 1086
    $null=Button 'Einde' 24 68 224 80 {$script:Window.Close()}
    $null=Button 'Help' 1200 68 224 80 {Show-Page 'Help'}
    $script:Status=Text $script:Model.message 22;$script:Status.Background=[Windows.Media.BrushConverter]::new().ConvertFromString('#AA10282D')
    $null=Add-At $script:Status 24 1035 1400 40
    if($Page -eq 'Home'){
        $script:Start=Button 'Start' 18 268 380 90 {Start-Race}
        $null=Button 'Nieuwe speler' 18 376 380 90 {Show-Page 'Players'}
        $null=Button 'Bediening' 18 484 380 90 {Show-Page 'Controls'}
        $null=Button 'Score' 18 592 380 90 {Show-Page 'Score'}
        $null=Button 'Opnieuw' 18 700 380 90 {if(Confirm 'De voortgang van deze HD-speler opnieuw beginnen?'){Action 'restart'}}
        $p=Current
        $values=if($p){@($p.name,('ƒ '+$p.money),(Time-Text $p.times),'Toetsenbord',$script:Config.display)}else{@('Kies een speler','—','—','Toetsenbord',$script:Config.display)}
        for($i=0;$i -lt 5;$i++){$value=Text $values[$i] 24;$value.TextWrapping='NoWrap';$value.TextTrimming='CharacterEllipsis';$value.ToolTip=$values[$i]
            $null=Add-At $value 1175 (318+39*$i) 195 40}
        $null=Add-At (Text $(if($p){if($p.stage -eq 6){'Alle etappes voltooid'}else{'Etappe '+($p.stage+1)+' / 6'}}else{'Nieuwe speler → naam invoeren'}) 30) 775 575 570 80
        $script:Start.IsEnabled=$null -ne $p -and $p.stage -lt 6
    }elseif($Page -eq 'Players'){
        $script:List=[Windows.Controls.ListBox]::new();$script:List.Background=[Windows.Media.Brushes]::Black
        $script:List.Foreground=[Windows.Media.Brushes]::Yellow;$script:List.BorderThickness='0';$script:List.FontFamily='Consolas';$script:List.FontSize=30
        foreach($p in $script:Model.profiles){$row=[Windows.Controls.ListBoxItem]::new();$row.Tag=$p.id;$row.Padding='16,5,0,5'
            $grid=[Windows.Controls.Grid]::new();$grid.Width=1125
            foreach($width in @(345,310,280,190)){$column=[Windows.Controls.ColumnDefinition]::new();$column.Width=$width;$grid.ColumnDefinitions.Add($column)}
            $columns=@($p.name,($p.stage.ToString()+'/6'),('ƒ '+$p.money),(Time-Text $p.times))
            for($i=0;$i -lt 4;$i++){$value=Text $columns[$i] 26;$value.Foreground=[Windows.Media.Brushes]::Yellow
                [Windows.Controls.Grid]::SetColumn($value,$i);$null=$grid.Children.Add($value)}
            $row.Content=$grid
            $null=$script:List.Items.Add($row);if($p.id -eq $script:Model.selected){$script:List.SelectedItem=$row}}
        $null=Add-At $script:List 146 334 1158 495
        $null=Button 'Selecteren' 180 938 313 80 {if($script:List.SelectedItem){Action 'select' @{id=$script:List.SelectedItem.Tag};Show-Page 'Home'}}
        $null=Button 'Verwijderen' 578 938 313 80 {if($script:List.SelectedItem -and (Confirm 'Deze HD-speler verwijderen?')){Action 'delete' @{id=$script:List.SelectedItem.Tag}}}
        $null=Button 'Annuleren' 966 938 313 80 {Show-Page 'Home'}
        $null=Button 'Nieuwe naam' 550 848 340 62 {Name-Dialog} $false
    }else{
        $panel=[Windows.Controls.Border]::new();$panel.Background=[Windows.Media.BrushConverter]::new().ConvertFromString('#F019182C')
        $stack=[Windows.Controls.StackPanel]::new();$stack.Margin='35';$panel.Child=$stack
        $null=$stack.Children.Add((Text $(switch($Page){'Controls'{'Bediening'}'Score'{'Scoreboard'}default{'Help'}}) 42))
        if($Page -eq 'Controls'){
            foreach($item in @(@('Links','KEY_LINKS'),@('Rechts','KEY_RECHTS'),@('Gas','KEY_GAS'),@('Rem','KEY_REM'),@('Actie 1','KEY_ACTIE1'),@('Actie 2','KEY_ACTIE2'))){
                $b=[Windows.Controls.Button]::new();$b.Style=$script:Window.Resources['Action'];$b.Tag=$item[1]
                $b.Content=$item[0]+'  ·  '+[Windows.Input.KeyInterop]::KeyFromVirtualKey([int]$script:Model.keys.($item[1]))
                $b.Add_Click({param($sender,$event)$script:WaitingKey=$sender.Tag;Status 'Druk op de nieuwe toets. Escape annuleert.'});$null=$stack.Children.Add($b)
            }
        }elseif($Page -eq 'Score'){
            $scored=@($script:Model.profiles|Where-Object {$_.stage -gt $_.score_start})
            $null=$stack.Children.Add((Text 'Speler · etappes · totale tijd sinds wissen' 22))
            foreach($p in $scored){
                $times=@($p.times|Select-Object -Skip $p.score_start)
                $null=$stack.Children.Add((Text ($p.name+'  ·  '+$times.Count+'  ·  '+(Time-Text $times)) 28))
            }
            if($scored.Count -eq 0){$null=$stack.Children.Add((Text 'Geen scores. Nieuwe voltooide etappes verschijnen hier.' 28))}
        }else{$null=$stack.Children.Add((Text 'Start vervolgt de etappes van je gekozen speler. Nieuwe speler beheert de namen. Bediening wijzigt de racetoetsen. Grafische instellingen kies je vooraf in de launcher. Escape gaat terug; Einde sluit af.' 27))
            $null=$stack.Children.Add((Text 'Deze optionele HD-menuvariant bewaart eigen spelers. De originele spelerbestanden blijven behouden.' 25))}
        $null=Add-At $panel 315 235 850 700
        if($Page -eq 'Score'){
            $null=Add-At (Text 'Wissen geldt voor alle HD-spelers. Namen en voortgang blijven behouden.' 22) 350 790 780 75
            $script:ClearScores=Button 'Hele scoreboard wissen' 390 865 700 60 {Clear-Scores} $false
            $script:ClearScores.IsEnabled=$scored.Count -gt 0
        }
        $null=Button 'Terug' 560 940 330 65 {Show-Page 'Home'} $false
    }
}
function Check-Files {
    $prefix=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')+'\'
    foreach($f in $script:Config.files){
        $p=[IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot,$f.path));Assert-Path $p
        if(-not $p.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or (Get-FileHash -LiteralPath $p).Hash.ToLowerInvariant() -cne $f.sha256){throw ('Menubestand is veranderd: '+$f.path)}
    }
}
function Start-Race {
    if($script:Race){return}
    try{
        if(-not $UiCheck){Check-Files}
        Backend 'start';$script:Token=$script:Model.pending.token;$script:StopClock=$null
        if($UiCheck){$script:Race=[AtlasIFakeRace]::new()}else{
            $script:Session=[AtlasIIOwnedSession]::Begin()
            $si=[Diagnostics.ProcessStartInfo]::new();$si.FileName=Join-Path $PSScriptRoot 'game/A2SPEL.DAT'
            $si.WorkingDirectory=Join-Path $PSScriptRoot 'game';$si.UseShellExecute=$false
            $si.Environment['NOCD']=[IO.Path]::GetPathRoot($PSScriptRoot).Substring(0,1)
            $script:Race=[Diagnostics.Process]::new();$script:Race.StartInfo=$si
            if(-not $script:Race.Start()){throw 'Race kon niet starten.'};$script:Session.Track($script:Race,$true)
        }
        $script:Window.Hide();$script:Timer.Start()
    }catch{
        if($script:Session){$script:Session.Dispose();$script:Session=$null}
        if($script:Race){try{if(-not $script:Race.HasExited){$script:Race.Kill()}}catch{};$script:Race.Dispose();$script:Race=$null}
        try{Backend 'discard'}catch{};Status $_.Exception.Message
    }
}
function Poll-Race {
    if(-not $script:Race){return}
    try{
        if($script:Config.PSObject.Properties['debug_log_limit_bytes'] -and $script:Config.debug_log_limit_bytes -gt 0){
            $log=Join-Path $PSScriptRoot 'game/debug.txt'
            if(Test-Path -LiteralPath $log){
                Assert-Path $log
                if((Get-Item -LiteralPath $log).Length -ge $script:Config.debug_log_limit_bytes){
                    $script:Window.Close();return
                }
            }
        }
        if($script:Session -and $script:Session.StopRequested -and -not $script:Race.HasExited){
            if(-not $script:StopClock){$script:StopClock=[Diagnostics.Stopwatch]::StartNew();$null=$script:Race.CloseMainWindow()}
            elseif($script:StopClock.ElapsedMilliseconds -ge 1500){$script:Race.Kill()}
        }
        if(-not $script:Race.HasExited){return}
        $script:Timer.Stop();$code=$script:Race.ExitCode;$script:Race.Dispose();$script:Race=$null
        $close=$script:Session -and $script:Session.StopRequested
        if($script:Session){$script:Session.Dispose();$script:Session=$null};$script:StopClock=$null
        Backend 'finish' @{token=$script:Token;exit_code=$code}
        if($close){$script:Window.Close();return}
        Show-Page 'Home';if(-not $UiCheck){$script:Window.Show();$null=$script:Window.Activate()}
    }catch{
        $message=$_.Exception.Message;$script:Timer.Stop()
        if($script:Session){$script:Session.Dispose();$script:Session=$null}
        if($script:Race){$script:Race.Dispose();$script:Race=$null}
        try{Backend 'discard'}catch{}
        Show-Page 'Home';Status $message;if(-not $UiCheck){$script:Window.Show()}
    }
}
try{
    if([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA'){throw 'Start het menu met PowerShell -STA.'}
    Assert-Path $PSScriptRoot;$configPath=Join-Path $PSScriptRoot 'Frontend.json';Assert-Path $configPath
    if((Get-Item -LiteralPath $configPath).Length -gt 2097152){throw 'Menucontract is te groot.'}
    $script:Config=Get-Content $configPath -Raw|ConvertFrom-Json -Depth 24
    if($script:Config.schema -ne 1 -or $script:Config.game -cne 'a2racer1' -or $script:Config.native_menu_used -ne $false){throw 'Onbekend menucontract.'}
    Check-Files;Assert-Path $script:Config.python;Assert-Path $script:Config.state_path
    $expected=Join-Path ([IO.Directory]::GetParent([IO.Directory]::GetParent([IO.Directory]::GetParent([IO.Directory]::GetParent($PSScriptRoot).FullName).FullName).FullName).FullName) 'local/launcher/i-hd-menu/players.json'
    if($script:Config.PSObject.Properties['profile_scope']){
        if($script:Config.profile_scope -eq 'trial'){$expected=Join-Path $PSScriptRoot 'players.json'}
        elseif($script:Config.profile_scope -ne 'launcher'){throw 'Onbekende profielscope.'}
    }
    if([IO.Path]::GetFullPath($script:Config.state_path) -cne [IO.Path]::GetFullPath($expected)){throw 'Profielpad is veranderd.'}
    if($UiCheck -and (-not $script:Config.PSObject.Properties['synthetic_fixture'] -or $script:Config.synthetic_fixture -ne $true)){throw 'UI-check vereist synthetische fixtures.'}
    if(-not $CheckOnly -and -not $RenderPath){
        $parent=Split-Path $script:Config.state_path -Parent;$null=[IO.Directory]::CreateDirectory($parent)
        $lockPath=Join-Path $parent 'menu.lock';Assert-Path $lockPath
        $script:Lock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    }
    Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
    . (Join-Path $PSScriptRoot 'OwnedSession.ps1');Import-IIOwnedSession
    Add-Type -TypeDefinition @'
using System;
public sealed class AtlasIFakeRace : IDisposable {
 public bool HasExited {get;set;} public int ExitCode {get;set;}
 public bool Disposed {get;private set;} public void Dispose(){Disposed=true;}
}
'@
    $script:Window=[Windows.Window]::new();$script:Window.Title='A2 Racer · HD menu'
    $script:Window.WindowStyle='None';$script:Window.ResizeMode='NoResize';$script:Window.Background=[Windows.Media.Brushes]::Black
    $script:Window.WindowState='Maximized';$script:Window.Topmost=$false
    $styles=@'
<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
 <Style x:Key="Hotspot" TargetType="Button"><Setter Property="Background" Value="Transparent"/><Setter Property="Cursor" Value="Hand"/>
 <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button"><Border x:Name="Ring" Background="{TemplateBinding Background}" CornerRadius="40" BorderThickness="3" BorderBrush="Transparent"/></ControlTemplate></Setter.Value></Setter>
 <Style.Triggers><Trigger Property="IsMouseOver" Value="True"><Setter Property="Background" Value="#33FFFF66"/></Trigger><Trigger Property="IsKeyboardFocused" Value="True"><Setter Property="Background" Value="#66FFFF66"/></Trigger></Style.Triggers></Style>
 <Style x:Key="Action" TargetType="Button"><Setter Property="FontSize" Value="28"/><Setter Property="Margin" Value="0,8,0,0"/><Setter Property="MinHeight" Value="55"/><Setter Property="Background" Value="#224F66"/><Setter Property="Foreground" Value="#FFFF55"/><Setter Property="Cursor" Value="Hand"/></Style>
</ResourceDictionary>
'@
    $script:Window.Resources=[Windows.Markup.XamlReader]::Parse($styles)
    $script:Canvas=[Windows.Controls.Canvas]::new();$script:Canvas.Width=1448;$script:Canvas.Height=1086
    $view=[Windows.Controls.Viewbox]::new();$view.Stretch='Fill';$view.Child=$script:Canvas;$script:Window.Content=$view
    $script:Images=@{}
    foreach($item in @(@('Home','main-hd-v2.png'),@('Players','players-hd.png'))){
        $img=[Windows.Media.Imaging.BitmapImage]::new();$img.BeginInit();$img.CacheOption='OnLoad';$img.UriSource=[Uri]::new((Join-Path $PSScriptRoot ('assets/'+$item[1])));$img.EndInit();$img.Freeze();$script:Images[$item[0]]=$img
    }
    Backend $(if($CheckOnly -or $RenderPath){'check'}else{'load'})
    $script:StopClock=$null;$script:Timer=[Windows.Threading.DispatcherTimer]::new();$script:Timer.Interval=[TimeSpan]::FromMilliseconds(50);$script:Timer.Add_Tick({Poll-Race})
    $script:Window.Add_PreviewKeyDown({param($sender,$event)
        if($script:WaitingKey){$event.Handled=$true
            if($event.Key -eq 'Escape'){$script:WaitingKey=$null;Status 'Toetswijziging geannuleerd.';return}
            $keys=@{};foreach($p in $script:Model.keys.PSObject.Properties){$keys[$p.Name]=[int]$p.Value}
            $key=if($event.Key -eq 'System'){$event.SystemKey}else{$event.Key}
            $keys[$script:WaitingKey]=[Windows.Input.KeyInterop]::VirtualKeyFromKey($key);Action 'keys' @{keys=$keys}
        }elseif($event.Key -eq 'Escape'){$event.Handled=$true;if($script:Dialog){Show-Page $script:Page}elseif($script:Page -eq 'Home'){$script:Window.Close()}else{Show-Page 'Home'}}
    })
    $script:Window.Add_Closed({$script:Closing=$true;$script:Timer.Stop();if($script:Frame){$script:Frame.Continue=$false};if($script:Session){$script:Session.Dispose();$script:Session=$null}})
    Show-Page $RenderPage
    $deadline=$null
    if(-not $CheckOnly -and -not $RenderPath -and -not $UiCheck -and $StopAfterSeconds -gt 0){
        $deadline=[Windows.Threading.DispatcherTimer]::new();$deadline.Interval=[TimeSpan]::FromSeconds($StopAfterSeconds)
        $deadline.Add_Tick({$script:Window.Close()});$deadline.Start()
    }
    if($CheckOnly){@{game_started=$false;native_menu_started=$false;menu='HD WPF';canvas=@(1448,1086);fullscreen=$true}|ConvertTo-Json}
    elseif($RenderPath){
        Assert-Path $RenderPath;$script:Window.WindowState='Normal';$view.Width=$RenderWidth;$view.Height=$RenderHeight
        $view.Measure([Windows.Size]::new($RenderWidth,$RenderHeight));$view.Arrange([Windows.Rect]::new(0,0,$RenderWidth,$RenderHeight));$view.UpdateLayout()
        $bmp=[Windows.Media.Imaging.RenderTargetBitmap]::new($RenderWidth,$RenderHeight,96,96,[Windows.Media.PixelFormats]::Pbgra32);$bmp.Render($view)
        $encoder=[Windows.Media.Imaging.PngBitmapEncoder]::new();$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp))
        $file=[IO.File]::Open($RenderPath,[IO.FileMode]::CreateNew);try{$encoder.Save($file)}finally{$file.Dispose()}
        @{game_started=$false;rendered=$RenderPath}|ConvertTo-Json
    }elseif($UiCheck){
        Name-Dialog;$script:NameBox.Text='Fixture'
        $script:SaveName.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if(-not (Current)){throw 'Naamveld slaat geen speler op.'}
        $script:Start.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if(-not $script:Race -or -not $script:Model.pending){throw 'Neprace start niet.'}
        $fixtureIni=Join-Path $PSScriptRoot 'game/INFIO.INI'
        $fixtureResult=[IO.File]::ReadAllText($fixtureIni).Replace('RACE_KLAAR=0','RACE_KLAAR=1').Replace('TIJD=0','TIJD=600').Replace('POSITIE=0','POSITIE=6')
        [IO.File]::WriteAllText($fixtureIni,$fixtureResult,[Text.Encoding]::ASCII)
        $fake=$script:Race;$fake.HasExited=$true;Poll-Race
        if(-not $fake.Disposed -or $script:Race -or $script:Model.pending){throw 'Neprace keert niet terug.'}
        Show-Page 'Score'
        if(-not $script:ClearScores.IsEnabled){throw 'Wisknop ontbreekt bij scores.'}
        $before=[IO.File]::ReadAllText($script:Config.state_path)
        $script:ClearScores.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if([IO.File]::ReadAllText($script:Config.state_path) -cne $before){throw 'Annuleren wist scores.'}
        $script:ConfirmClearScores=$true
        $script:ClearScores.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
        if($script:ClearScores.IsEnabled -or (Current).stage -ne 1 -or (Current).score_start -ne 1){throw 'Scorewissen beschadigt voortgang.'}
        Show-Page 'Players';if($script:List.Items.Count -ne 1){throw 'Spelerlijst ontbreekt.'}
        # Exercise the actual dispatcher lifetime across Hide with a synthetic race.
        Show-Page 'Home';$script:Phase=0;$script:LifetimeError=$null;$script:SurvivedHide=$false
        $script:Window.WindowState='Normal';$script:Window.Left=-20000;$script:Window.Top=-20000
        $script:Window.Width=2;$script:Window.Height=2;$script:Window.ShowActivated=$false;$script:Window.ShowInTaskbar=$false
        $driver=[Windows.Threading.DispatcherTimer]::new();$driver.Interval=[TimeSpan]::FromMilliseconds(100)
        $driver.Add_Tick({
            try{if($script:Phase -eq 0){Start-Race;$script:Phase=1}
                else{if(-not $script:Race -or $script:Window.IsVisible -or -not $script:Frame.Continue){throw 'Verbergen eindigt de menulevensduur.'}
                    $script:SurvivedHide=$true;$script:Race.HasExited=$true;Poll-Race;$script:Window.Close()}}
            catch{$script:LifetimeError=$_.Exception.Message;$script:Window.Close()}
        })
        $script:Frame=[Windows.Threading.DispatcherFrame]::new();$script:Window.Show();$driver.Start()
        try{[Windows.Threading.Dispatcher]::PushFrame($script:Frame)}finally{$driver.Stop()}
        if($script:LifetimeError){throw $script:LifetimeError}
        if(-not $script:SurvivedHide -or $script:Model.pending -or $script:Race){throw 'Neprace verlaat de host niet netjes.'}
        @{game_started=$false;hook_started=$false;fake_race_returned=$true;player_controls=$true;score_clear_confirm_and_cancel=$true;hidden_lifetime_passed=$true}|ConvertTo-Json
    }else{
        # ShowDialog would end when hidden. Keep the dispatcher alive until Closed.
        $script:Frame=[Windows.Threading.DispatcherFrame]::new();$script:Window.Show()
        if(-not $script:Closing){[Windows.Threading.Dispatcher]::PushFrame($script:Frame)}
    }
}catch{
    if($CheckOnly -or $RenderPath -or $UiCheck){Write-Error $_;exit 1}
    Add-Type -AssemblyName PresentationFramework
    $null=[Windows.MessageBox]::Show(('HD-menu kon niet starten: '+$_.Exception.Message),'A2 Racer',0,16);exit 1
}finally{
    if($deadline){$deadline.Stop()}
    if($script:Session){$script:Session.Dispose()};if($script:Race){$script:Race.Dispose()};if($script:Lock){$script:Lock.Dispose()}
}
