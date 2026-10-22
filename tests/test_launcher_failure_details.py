"""Exercise actual failure routing with synthetic streams and offscreen WPF."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''param([string]$Source,[string]$Common,[string]$Xaml,[string]$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
foreach($file in @($Common,$Source)){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'PowerShell parse error'}
    foreach($definition in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
        if($definition.Name -in @('Assert-LauncherPath','ConvertTo-LauncherPlainText','Set-Status','Poll-Launcher')){
            Invoke-Expression $definition.Extent.Text
        }
    }
}
$reader=New-Object Xml.XmlNodeReader ([xml][IO.File]::ReadAllText($Xaml))
try{$window=[Windows.Markup.XamlReader]::Load($reader)}finally{$reader.Close()}
$ui=@{}
foreach($name in @('StatusTitle','StatusMessage','LogText','SupportDetails')){$ui[$name]=$window.FindName($name)}
$workspacePath=$Root;$script:worker=$null
function Update-Buttons{}
$results=@()
foreach($case in @(
    @{output='A2-test gestopt: synthetic FFmpeg download failure';error='';kind='game-components'},
    @{output='';error='synthetic unsupported disc image';kind='import'},
    @{output='';error='';kind='import'},
    @{output=(('progress '*6000)+'FINAL DOWNLOAD CAUSE');error='STDERR CAUSE';kind='game-components'}
)){
    $process=[PSCustomObject]@{HasExited=$true;ExitCode=1}
    $process|Add-Member ScriptMethod Dispose {}
    $output=New-Object 'Threading.Tasks.TaskCompletionSource[string]';$output.SetResult($case.output)
    $failure=New-Object 'Threading.Tasks.TaskCompletionSource[string]';$failure.SetResult($case.error)
    $script:operation=@{kind=$case.kind;process=$process;output=$output.Task;error=$failure.Task}
    $script:afterComponents=@{kind='import'};$script:gameComponentsVerified=$false
    Poll-Launcher
    # A bounded footer must retain space for the primary action. Never Show.
    $window.Measure((New-Object Windows.Size 1240,820))
    $window.Arrange((New-Object Windows.Rect 0,0,1240,820));$window.UpdateLayout()
    $results+=@{title=$ui.StatusTitle.Text;message=$ui.StatusMessage.Text;details=$ui.LogText.Text;
        link=[string]$ui.SupportDetails.Visibility;operation_cleared=($null -eq $script:operation);
        footer_height=$ui.StatusMessage.ActualHeight;
        saved=[IO.File]::ReadAllText((Join-Path $Root 'local\launcher\last-error.txt'))}
}
Set-Status 'Kon niet doorgaan' ''
$empty=@{message=$ui.StatusMessage.Text;details=$ui.LogText.Text}
$last=[IO.File]::ReadAllText((Join-Path $Root 'local\launcher\last-error.txt'))
Set-Status 'Opties opgeslagen' 'Opgeslagen.'
Set-Status 'Gamemap nodig' 'Kies je eigen game.'
$retained=$last -eq [IO.File]::ReadAllText((Join-Path $Root 'local\launcher\last-error.txt'))
$successLink=[string]$ui.SupportDetails.Visibility
# A blocked local log must not hide or replace the actual error on screen.
[IO.File]::Delete((Join-Path $Root 'local\launcher\last-error.txt'))
[IO.Directory]::CreateDirectory((Join-Path $Root 'local\launcher\last-error.txt'))|Out-Null
Set-Status 'Kon niet doorgaan' 'original failure while log is blocked'
@{cases=$results;empty=$empty;retained=$retained;success_link=$successLink;
    blocked=$ui.LogText.Text;visible=$window.IsVisible;
    temporary=@(Get-ChildItem -LiteralPath (Join-Path $Root 'local\launcher') -Filter '*.tmp').Count}|
    ConvertTo-Json -Depth 5 -Compress
'''


@unittest.skipUnless(os.name == 'nt', 'Windows WPF failure routing')
class FailureDetailsTests(unittest.TestCase):
    def check_failure_routing(self, runtime):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='failure-details-', dir=parent) as directory:
            folder = Path(directory)
            script = folder / 'fixture.ps1'
            script.write_text(FIXTURE, encoding='utf-8-sig')
            result = subprocess.run([
                str(runtime), '-NoProfile', '-STA', '-File', str(script),
                '-Source', str(ROOT / 'tools/Show-A2Launcher.ps1'),
                '-Common', str(ROOT / 'tools/launcher_common.ps1'),
                '-Xaml', str(ROOT / 'tools/launcher_window.xaml'), '-Root', str(folder),
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40)
            if 'running scripts is disabled' in result.stderr and 'UnauthorizedAccess' in result.stderr:
                self.skipTest('Local script policy blocks fixture; policy unchanged.')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout.strip())
        for case in data['cases']:
            self.assertEqual(case['title'], 'Kon niet doorgaan')
            self.assertTrue(case['message'].strip())
            self.assertEqual(case['link'], 'Visible')
            self.assertTrue(case['operation_cleared'])
            self.assertIn('exitcode: 1', case['details'])
            self.assertIn(case['details'], case['saved'])
            self.assertLessEqual(case['footer_height'], 36)
        self.assertIn('synthetic FFmpeg download failure', data['cases'][0]['details'])
        self.assertIn('unsupported disc image', data['cases'][1]['details'])
        self.assertIn('geen foutdetails', data['cases'][2]['details'])
        for cause in ('FINAL DOWNLOAD CAUSE', 'STDERR CAUSE'):
            self.assertIn(cause, data['cases'][3]['details'])
        self.assertLess(len(data['cases'][3]['details']), 30000)
        self.assertIn('zonder foutdetails', data['empty']['message'])
        self.assertTrue(data['retained'])
        self.assertEqual(data['success_link'], 'Collapsed')
        self.assertEqual(data['blocked'], 'original failure while log is blocked')
        self.assertEqual(data['temporary'], 0)
        self.assertFalse(data['visible'])

    def test_failure_routing_windows_powershell(self):
        self.check_failure_routing(Path(os.environ['SystemRoot']) /
                                  'System32/WindowsPowerShell/v1.0/powershell.exe')

    def test_failure_routing_powershell7(self):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 unavailable')
        self.check_failure_routing(runtime)
