"""Real launcher functions for IV/Vakantieracer with a synthetic catalog; no game, import or process starts."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''param([string]$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
. (Join-Path $Root 'tools/launcher_common.ps1')
$source=Join-Path $Root 'tools/Show-A2Launcher.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Launcher parser error'}
foreach($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
    Invoke-Expression $definition.Extent.Text
}
$xml=[xml][IO.File]::ReadAllText((Join-Path $Root 'tools/launcher_window.xaml'))
$reader=New-Object Xml.XmlNodeReader $xml
try{$window=[Windows.Markup.XamlReader]::Load($reader)}finally{$reader.Close()}
$ui=@{}
foreach($node in $xml.SelectNodes('//*[@*[local-name()="Name"]]')){
    $name=$node.GetAttribute('Name','http://schemas.microsoft.com/winfx/2006/xaml')
    if($name){$ui[$name]=$window.FindName($name)}
}
$workspacePath=$Root
# Only process starts and unrelated part I/II helpers are replaced.
function Get-CheatPreferences { return @{} }
function Test-ActiveCheats { return $false }
function Set-Status([string]$Title,[string]$Message){$ui.StatusTitle.Text=$Title;$ui.StatusMessage.Text=$Message}
function Load-Runtimes([switch]$RequireGameRuntime){return $true}
function Test-OtherGameRunning {return $false}
function Start-GameComponentPreparation {return $false}
$script:operations=@();$script:launched=@()
function Start-Operation([string]$Kind,[string]$Executable,[string[]]$Arguments){$script:operations+=,@($Kind,$Arguments)}
function New-LauncherProcess([string]$Executable,[string[]]$Arguments,[switch]$Detached){
    if($Detached){throw 'The game session must report its result'}
    $script:launched+=,@($Executable,$Arguments)
    return @{process=[pscustomobject]@{HasExited=$false;ExitCode=0}}
}
$script:operation=$null;$script:worker=$null;$script:initialized=$true;$script:game='a2racer1';$script:cheatControls=@{}
$script:laterCatalog=$null;$script:laterToken=$null;$script:laterSelection=$null
$script:PythonPath='C:\synthetic\python.exe';$script:PowerShellPath='C:\synthetic\pwsh.exe'
$script:catalog='{"games":{"a2racer1":{"ready":false}},"iii_preparation":{"tours":{}}}'|ConvertFrom-Json
Add-Choice $ui.GraphicsChoice 'Original' 'accelerated-640';$ui.GraphicsChoice.SelectedIndex=0
Add-Choice $ui.LaterGameChoice 'Vakantieracer' 'vakantieracer';Add-Choice $ui.LaterGameChoice 'IV' 'a2racer4';$ui.LaterGameChoice.SelectedIndex=0
Add-Choice $ui.LaterProfileChoice 'HD' 'hd1080';Add-Choice $ui.LaterProfileChoice 'Compat' 'compat';$ui.LaterProfileChoice.SelectedIndex=0
$ui.Pages.SelectedIndex=4

# 1. Before the catalog and without own files: no start.
Update-LaterStatus;Update-Buttons
if($ui.PlayButton.IsEnabled){throw 'Play enabled before the catalog'}
if($ui.Pages.Items[4].Visibility -ne 'Visible' -or $ui.Pages.Items[0].Visibility -ne 'Collapsed' -or $ui.Pages.Items[3].Visibility -ne 'Collapsed'){throw 'Wrong page visibility'}
$script:laterCatalog='{"kind":"later-game-catalog","games":[{"id":"a2racer4","ready":false,"reason":"[WinError 3] synthetic path"},{"id":"vakantieracer","ready":false,"reason":"Bestand ontbreekt: SPEL.EXE"}],"profiles":[{"id":"hd1080","description":"Synthetic HD note"}]}'|ConvertFrom-Json
Update-LaterStatus;Update-Buttons
if($ui.PlayButton.IsEnabled -or [string]$ui.PlayButton.Content -ne 'Eigen game nodig'){throw 'Missing own game must block Play'}
if($ui.LaterStatus.Text -ne 'Bestand ontbreekt: SPEL.EXE'){throw 'Readable reason not shown'}
if($ui.LaterProfileNote.Text -ne 'Synthetic HD note'){throw 'Profile note not from catalog'}
Select-Choice $ui.LaterGameChoice 'a2racer4';Update-LaterStatus;Update-Buttons
if($ui.LaterStatus.Text -like '*WinError*'){throw 'Technical path error shown to the player'}
if(-not $ui.LaterChooseFolder.IsEnabled -or -not $ui.LaterChooseArchive.IsEnabled){throw 'Import must stay available'}

# 2. Ready: start prepares first, with a fresh session token.
$script:laterCatalog.games[0].ready=$true
Update-LaterStatus;Update-Buttons
if(-not $ui.PlayButton.IsEnabled -or [string]$ui.PlayButton.Content -ne 'Speel De Politie Slaat Terug'){throw 'Ready game cannot start'}
if($ui.GameFourAvailability.Text -ne 'Klaar om te spelen' -or $ui.GameFiveAvailability.Text -ne 'Eigen game nodig'){throw 'Library cards not updated per game'}
if([string]$ui.GameFour.BorderBrush -ne '#FFFFDD4A' -or [string]$ui.GameFive.BorderBrush -eq '#FFFFDD4A'){throw 'Selected card not highlighted'}
Select-Choice $ui.LaterProfileChoice 'compat'
Start-LaterGame
if($script:operations.Count -ne 1){throw 'Prepare not queued once'}
$kind,$arguments=$script:operations[0]
$line=$arguments -join ' '
if($kind -ne 'later-prepare' -or $line -notlike '*launcher_later_games.py prepare --game a2racer4 --profile compat --token *'){throw ('Wrong prepare call: '+$line)}
if($script:laterToken -notmatch '^[a-f0-9]{32}$' -or $arguments[-1] -cne $script:laterToken){throw 'Token missing'}

# 3. Only our own start script with the planned token runs; anything else is refused.
$script:operation=$null
$startScript=[IO.Path]::GetFullPath((Join-Path $Root 'tools/Start-LaterGame.ps1'))
$hash=(Get-FileHash -LiteralPath $startScript -Algorithm SHA256).Hash.ToLowerInvariant()
$good=[pscustomobject]@{kind='later-game-launch-plan';game='a2racer4';profile='compat';control_token=$script:laterToken;start_script=$startScript;start_script_sha256=$hash}
foreach($change in @(@{control_token='b'*32},@{game='vakantieracer'},@{profile='hd1080'},@{start_script='C:\Windows\System32\cmd.exe'},@{start_script_sha256='0'*64})){
    $plan=$good.PSObject.Copy();foreach($key in $change.Keys){$plan.$key=$change[$key]}
    $refused=$false;try{Start-LaterSession $plan}catch{$refused=$true}
    if(-not $refused -or $script:launched.Count){throw ('Changed plan accepted: '+($change.Keys -join ','))}
}
Start-LaterSession $good
if($script:launched.Count -ne 1){throw 'Session not started once'}
$exe,$arguments=$script:launched[0]
if($exe -ne 'C:\synthetic\pwsh.exe'){throw 'Wrong PowerShell'}
$expected=@('-File',$startScript,'-Game','a2racer4','-Profile','compat','-ControlToken',$script:laterToken,'-PythonPath','C:\synthetic\python.exe','-UiResult') -join ' '
if(($arguments -join ' ') -notlike ('*'+$expected)){throw ('Wrong session arguments: '+($arguments -join ' '))}
if($script:worker.kind -ne 'later'){throw 'Worker kind missing'}

# 4. While it runs: stop is offered, other actions wait.
Update-Buttons
if($ui.LaterStop.Visibility -ne 'Visible' -or -not $ui.LaterStop.IsEnabled){throw 'Stop not offered'}
if($ui.PlayButton.IsEnabled -or $ui.LaterChooseFolder.IsEnabled -or [string]$ui.PlayButton.Content -ne 'Game draait'){throw 'Actions open while the game runs'}

# 5. The session result from Start-LaterGame -UiResult is shown.
function New-Result([string]$Text,[int]$Code){
    $out=[Threading.Tasks.TaskCompletionSource[string]]::new();$out.SetResult($Text)
    $err=[Threading.Tasks.TaskCompletionSource[string]]::new();$err.SetResult('')
    return @{kind='later';process=[pscustomobject]@{ExitCode=$Code};output=$out.Task;error=$err.Task}
}
Complete-LaterSession (New-Result '{"kind":"later-game-session-result","status":"closed","message":"x"}' 0)
if($ui.StatusTitle.Text -ne 'Game afgesloten' -or $script:laterToken){throw 'Closed session not reported'}
Complete-LaterSession (New-Result "noise`r`n{""status"":""error"",""message"":""Synthetic wrapper missing""}" 1)
if($ui.StatusTitle.Text -ne 'Start onderbroken' -or $ui.StatusMessage.Text -notlike '*Synthetic wrapper missing*'){throw 'Failure not reported'}
'Later games UI: OK'
'''


@unittest.skipUnless(os.name == 'nt', 'Windows WPF')
class LaterGamesUiTests(unittest.TestCase):
    def test_page_imports_prepares_and_starts_only_the_planned_session(self):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 unavailable')
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='later-ui-', dir=parent) as folder:
            source = Path(folder) / 'later-ui.ps1'
            source.write_text(FIXTURE, encoding='utf-8-sig')
            result = subprocess.run([runtime, '-NoProfile', '-STA', '-File', str(source), '-Root', str(ROOT)],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('Later games UI: OK', result.stdout)

    def test_bridge_and_start_script_are_in_the_runtime_package(self):
        from tools.portable_launcher import app_files
        files = set(app_files(ROOT))
        self.assertTrue({'tools/launcher_later_games.py', 'tools/Start-LaterGame.ps1',
                         'tools/Show-A2Launcher.ps1', 'tools/launcher_window.xaml'} <= files)


if __name__ == '__main__':
    unittest.main()
