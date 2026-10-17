"""Actual WPF functions with synthetic III status; no launcher/game starts."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


FIXTURE = r'''param([string]$Source,[string]$Xaml)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Launcher parser error'}
foreach($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
    Invoke-Expression $definition.Extent.Text
}
$xml=[xml][IO.File]::ReadAllText($Xaml)
$reader=New-Object Xml.XmlNodeReader $xml
try{$window=[Windows.Markup.XamlReader]::Load($reader)}finally{$reader.Close()}
$ui=@{}
foreach($node in $xml.SelectNodes('//*[@*[local-name()="Name"]]')){
    $name=$node.GetAttribute('Name','http://schemas.microsoft.com/winfx/2006/xaml')
    if($name){$ui[$name]=$window.FindName($name)}
}
# Isolate unrelated cheats and footer formatting. Update-Buttons and
# Update-IIIStatus themselves remain the real repository functions.
function Get-CheatPreferences { return @{} }
function Test-ActiveCheats { return $false }
function Set-Status([string]$Title,[string]$Message){$ui.StatusTitle.Text=$Title;$ui.StatusMessage.Text=$Message}
$script:operation=$null;$script:worker=$null;$script:initialized=$true
$script:game='a2racer1';$script:cheatControls=@{}
$script:catalog='{"games":{"a2racer1":{"ready":false}},"iii_preparation":{"tours":{}}}' | ConvertFrom-Json
Add-Choice $ui.GraphicsChoice 'Original' 'accelerated-640';$ui.GraphicsChoice.SelectedIndex=0
foreach($tour in @('1','2')){
    Add-Choice $ui.IIITourChoice ('Tour '+$tour) $tour
    $state='{"reason":"synthetic blocked","launch_ready":true,"start_blocked":true,"profiles":{"original":{"available":true,"reason":"blocked"},"compat":{"available":true,"reason":"blocked"},"fullhd-skyoff":{"available":true,"reason":"blocked"}}}'|ConvertFrom-Json
    $script:catalog.iii_preparation.tours.PSObject.Properties.Add([Management.Automation.PSNoteProperty]::new($tour,$state))
}
foreach($profile in @('original','compat','fullhd-skyoff')){Add-Choice $ui.IIIProfileChoice $profile $profile}
$ui.Pages.SelectedIndex=3
foreach($tour in @('1','2')){
    Select-Choice $ui.IIITourChoice $tour
    foreach($profile in @('original','compat','fullhd-skyoff')){
        Select-Choice $ui.IIIProfileChoice $profile
        Update-IIIStatus;Update-Buttons
        if($ui.PlayButton.IsEnabled){throw 'Blocked III profile enabled Play'}
        if([string]$ui.PlayButton.Content -ne 'Start geblokkeerd'){throw 'Missing blocked button label'}
        if($ui.IIIReadyOverview.Text -ne 'Start geblokkeerd'){throw 'Files-ready mistaken for start permission'}
        if(-not $ui.IIIChooseInstallation.IsEnabled){throw 'III map selection must stay enabled'}
    }
    $script:catalog.iii_preparation.tours.($tour).start_blocked=$false
    foreach($entry in $script:catalog.iii_preparation.tours.($tour).profiles.PSObject.Properties){$entry.Value.available=$false}
    $script:catalog.iii_preparation.tours.($tour).PSObject.Properties.Remove('start_blocked')
    Update-IIIStatus;Update-Buttons
    if($ui.PlayButton.IsEnabled){throw 'Old unavailable catalog enabled Play'}
}
'III safety UI: OK'
'''


@unittest.skipUnless(os.name == 'nt', 'Windows WPF vereist Windows.')
class IIIUiSafetyTests(unittest.TestCase):
    def test_start_stop_wins_over_available_profile_without_disabling_map_choice(self):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 is niet beschikbaar.')
        root = Path(__file__).resolve().parents[1]
        base = root / 'local/test-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='iii-ui-stop-', dir=base) as directory:
            fixture = Path(directory) / 'check.ps1'
            fixture.write_text(FIXTURE, encoding='utf-8-sig')
            result = subprocess.run([runtime, '-NoProfile', '-STA', '-File', str(fixture),
                                     '-Source', str(root / 'tools/Show-A2Launcher.ps1'),
                                     '-Xaml', str(root / 'tools/launcher_window.xaml')],
                                    capture_output=True, text=True, errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('III safety UI: OK', result.stdout)
