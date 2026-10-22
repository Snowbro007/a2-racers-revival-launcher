"""Real WPF selection events offscreen, with a synthetic availability catalog."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools import launcher_model

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''param($Source,$Common,$Xaml,$Catalog)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
. $Common
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Launcher parser error'}
foreach($definition in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
    Invoke-Expression $definition.Extent.Text
}
$xml=[xml][IO.File]::ReadAllText($Xaml)
$reader=New-Object Xml.XmlNodeReader $xml
try{$window=[Windows.Markup.XamlReader]::Load($reader)}finally{$reader.Close()}
$ui=@{}
# Discover all controls through the XAML namespace, not a duplicate name list.
foreach($node in $xml.SelectNodes('//*')){
    $name=$node.GetAttribute('Name','http://schemas.microsoft.com/winfx/2006/xaml')
    if($name){$control=$window.FindName($name);if($control){$ui[$name]=$control}}
}
$workspacePath=Split-Path -Parent $Catalog
$script:catalog=[IO.File]::ReadAllText($Catalog)|ConvertFrom-Json
$script:settings=$script:catalog.settings;$script:game='a2racer2';$script:binding=$false
$script:operation=$null;$script:worker=$null;$script:initialized=$false;$script:cheatControls=@{}
Select-Game 'a2racer2'
$script:initialized=$true
$ui.Pages.SelectedIndex=1
# Install the actual routed-event handlers without executing launcher startup.
$sourceText=[IO.File]::ReadAllText($Source)
$start=$sourceText.LastIndexOf("foreach(`$name in @('IIResolutionChoice','IIHudChoice','IISkyChoice','IIDistanceChoice')){")
$end=$sourceText.IndexOf('    $ui.GameOne.Add_Click',$start)
if($start -lt 0 -or $end -lt 0){throw 'II event handlers missing'}
Invoke-Expression $sourceText.Substring($start,$end-$start)
Update-Buttons
$initial=@{max=$ui.MaxProfile.IsEnabled;reason=[string]$ui.MaxProfile.ToolTip;note=$ui.IIHudNote.Text}
$script:catalog.ii_graphics_support.'1080p'.'hd-map'.available=$true
$script:catalog.ii_graphics_support.'1080p'.hd.available=$true
Update-Buttons
Select-Choice $ui.IIHudChoice 'hd-map'
$selected=@{page=$ui.Pages.SelectedIndex;hud=[string]$ui.IIHudChoice.SelectedItem.Tag;
            enabled=$ui.IIHudChoice.SelectedItem.IsEnabled;tooltip=$ui.IIHudChoice.SelectedItem.ToolTip}
$script:catalog.ii_graphics_support.'1080p'.'hd-map'.available=$false
Update-Buttons
$missing=@{enabled=$ui.IIHudChoice.SelectedItem.IsEnabled;reason=[string]$ui.IIHudChoice.SelectedItem.ToolTip}
$script:catalog.ii_graphics_support.'1080p'.'hd-map'.available=$true
Update-Buttons
$restored=@{enabled=$ui.IIHudChoice.SelectedItem.IsEnabled;tooltip=$ui.IIHudChoice.SelectedItem.ToolTip}
@{initial=$initial;selected=$selected;missing=$missing;restored=$restored;visible=$window.IsVisible}|ConvertTo-Json -Compress
'''


@unittest.skipUnless(os.name == 'nt', 'Windows WPF routed events')
class LauncherIIChoiceTests(unittest.TestCase):
    def test_availability_routed_selection_and_reason_recovery(self):
        runtime = shutil.which('pwsh')
        if not runtime: self.skipTest('PowerShell 7 unavailable')
        parent = ROOT/'local/test-fixtures'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            folder = Path(directory)
            catalog = launcher_model.snapshot(folder)
            catalog['ii_menus']['revival']['available'] = True
            for resolution, choices in catalog['ii_graphics_support'].items():
                for hud, item in choices.items():
                    item.update(available=hud == 'native', reason='Synthetische HD-bronnen ontbreken.')
            script = folder/'events.ps1'; script.write_text(FIXTURE, encoding='utf-8-sig')
            fixture = folder/'catalog.json'; fixture.write_text(json.dumps(catalog))
            result = subprocess.run([runtime, '-NoProfile', '-STA', '-File', str(script),
                '-Source', str(ROOT/'tools/Show-A2Launcher.ps1'), '-Common', str(ROOT/'tools/launcher_common.ps1'),
                '-Xaml', str(ROOT/'tools/launcher_window.xaml'), '-Catalog', str(fixture)],
                capture_output=True, text=True, encoding='utf-8', timeout=35)
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)
        self.assertFalse(actual['visible'])
        self.assertFalse(actual['initial']['max']); self.assertIn('ontbreken', actual['initial']['reason'])
        self.assertEqual(actual['selected']['page'], 1); self.assertEqual(actual['selected']['hud'], 'hd-map')
        self.assertTrue(actual['selected']['enabled']); self.assertIsNone(actual['selected']['tooltip'])
        self.assertFalse(actual['missing']['enabled']); self.assertIn('ontbreken', actual['missing']['reason'])
        self.assertTrue(actual['restored']['enabled']); self.assertIsNone(actual['restored']['tooltip'])


if __name__ == '__main__': unittest.main()
