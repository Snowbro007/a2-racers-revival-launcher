"""Synthetic first-open/queued-game routing; no UI, runtime or game is started."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''param([string]$Source,[string]$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'PowerShell parse failed'}
$fixtureTools=Split-Path -Parent $Source
foreach($definition in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
    if($definition.Name -in @('Load-Runtimes','Start-InitialCheck','Start-Model','Start-GameComponentPreparation','Poll-Launcher','Open-GameLibraryResult')){Invoke-Expression $definition.Extent.Text.Replace('$PSScriptRoot','$fixtureTools')}
}
$workspacePath=$Root
$script:PythonPath=Join-Path $Root 'python.exe'
$script:PowerShellPath=Join-Path $Root 'pwsh.exe'
[IO.File]::WriteAllText($script:PythonPath,'synthetic non-executable fixture')
$ui=@{LogText=[PSCustomObject]@{Text=''};StatusTitle=[PSCustomObject]@{Text=''}}
$script:game='a2racer2';$script:mediaComponentsVerified=$false
$script:worker=$null;$script:operation=$null;$script:afterComponents=$null
$script:gameComponentsVerified=$false;$script:calls=@();$script:failStart=$false
function Assert-LauncherPath([string]$Path){}
function Set-Status([string]$Title,[string]$Message){}
function Update-Buttons{}
function Start-Operation([string]$Kind,[string]$Executable,[string[]]$Arguments){
    $script:calls+=@{kind=$Kind;arguments=@($Arguments)}
    if(-not $script:failStart){$script:operation=@{kind=$Kind}}
}
function Complete-Fixture([int]$Code){
    $process=[PSCustomObject]@{HasExited=$true;ExitCode=$Code}
    $process|Add-Member ScriptMethod Dispose {}
    $output=New-Object 'Threading.Tasks.TaskCompletionSource[string]'
    $output.SetResult('')
    $failure=New-Object 'Threading.Tasks.TaskCompletionSource[string]'
    $failure.SetResult('synthetic preparation failure')
    $script:operation=@{kind='game-components';process=$process;output=$output.Task;error=$failure.Task}
    Poll-Launcher
}
$launcherOnly=(Load-Runtimes)
$gameRuntimeMissing=-not (Load-Runtimes -RequireGameRuntime)
[IO.File]::WriteAllText((Join-Path $Root 'public-release.json'),'{}')
Start-Model 'snapshot' @('snapshot')
$snapshotDirect=$script:calls[-1].kind -eq 'snapshot'
$script:operation=$null
Start-Model 'library-folder' @('game-library-folder','--game','a2racer1')
$libraryDirect=$script:calls[-1].kind -eq 'library-folder'
$script:operation=$null
Start-Model 'import' @('import-installation','--folder','literal game folder','--game','a2racer1')
$importSkipsMedia=$script:calls[-1].arguments -contains '-SkipMedia'
$queued=$script:calls[-1].kind -eq 'game-components'
$fullCheck=$script:calls[-1].arguments -contains '-CheckOnly' -and $script:calls[-1].arguments -notcontains '-LauncherOnly'
[IO.File]::WriteAllText($script:PowerShellPath,'synthetic non-executable fixture')
Complete-Fixture 0
$resumed=$script:calls[-1].kind -eq 'import' -and $script:calls[-1].arguments -contains 'literal game folder'
$successCleared=$null -eq $script:afterComponents
$script:operation=$null
Start-Model 'start' @('create-session')
$verifiedDirect=$script:calls[-1].kind -eq 'start'
$script:operation=$null;$script:game='a2racer1'
Start-Model 'start' @('create-session','--intro','0')
$noIntroDirect=$script:calls[-1].kind -eq 'start'
$script:operation=$null
Start-Model 'start' @('create-session','--intro','1')
$introQueuesMedia=$script:calls[-1].kind -eq 'game-components' -and $script:calls[-1].arguments -notcontains '-SkipMedia'
Complete-Fixture 0
$introResumed=$script:calls[-1].kind -eq 'start' -and $script:mediaComponentsVerified
$script:operation=$null
Start-Model 'start' @('create-session','--intro','1')
$introCached=$script:calls[-1].kind -eq 'start'
$script:game='a2racer2'
$script:operation=$null;$script:gameComponentsVerified=$false
Start-Model 'start' @('create-session')
$beforeFailure=$script:calls.Count
Complete-Fixture 1
$failureStopped=$script:calls.Count -eq $beforeFailure -and $null -eq $script:afterComponents -and -not $script:gameComponentsVerified
Start-Model 'start' @('create-session')
[IO.File]::Delete($script:PowerShellPath)
$beforeMissing=$script:calls.Count
Complete-Fixture 0
$missingRuntimeStopped=$script:calls.Count -eq $beforeMissing -and $null -eq $script:afterComponents -and -not $script:gameComponentsVerified
Start-Model 'import' @('prepare-ii')
$retryQueued=$script:calls[-1].kind -eq 'game-components'
$script:operation=$null;$script:afterComponents=$null;$script:failStart=$true
Start-Model 'start' @('create-session')
$launchFailureCleared=$null -eq $script:afterComponents
$script:failStart=$false;$script:operation=$null;$script:bootstrapAttempted=$false;$script:developmentRuntimes=$false
Start-InitialCheck
$publicMinimal=$script:calls[-1].arguments -contains '-LauncherOnly'
[IO.File]::Delete((Join-Path $Root 'public-release.json'))
[IO.Directory]::CreateDirectory((Join-Path $Root 'payload'))|Out-Null
[IO.File]::WriteAllText((Join-Path $Root 'payload/python-3.13.16-embed-amd64.zip'),'synthetic')
$script:operation=$null;$script:bootstrapAttempted=$false
Start-InitialCheck
$privateFull=$script:calls[-1].arguments -notcontains '-LauncherOnly'
$outsideRefused=$false
try{Open-GameLibraryResult ([PSCustomObject]@{schema=1;game='a2racer1';path=(Join-Path $Root 'outside')})}catch{$outsideRefused=$true}
@{importSkipsMedia=$importSkipsMedia;noIntroDirect=$noIntroDirect;introQueuesMedia=$introQueuesMedia;introResumed=$introResumed;introCached=$introCached;launcherOnly=$launcherOnly;gameRuntimeMissing=$gameRuntimeMissing;snapshotDirect=$snapshotDirect;libraryDirect=$libraryDirect;queued=$queued;fullCheck=$fullCheck;resumed=$resumed;successCleared=$successCleared;verifiedDirect=$verifiedDirect;failureStopped=$failureStopped;missingRuntimeStopped=$missingRuntimeStopped;retryQueued=$retryQueued;launchFailureCleared=$launchFailureCleared;publicMinimal=$publicMinimal;privateFull=$privateFull;outsideRefused=$outsideRefused}|ConvertTo-Json -Compress
'''


class LauncherOnboardingTests(unittest.TestCase):
    def test_initial_screen_does_not_claim_a_game_exists(self):
        tree = ET.parse(ROOT / 'tools/launcher_window.xaml')
        names = {node.attrib.get('{http://schemas.microsoft.com/winfx/2006/xaml}Name'): node for node in tree.iter()}
        self.assertIn('Games zijn niet inbegrepen', names['WelcomeHint'].attrib['Text'])
        self.assertNotIn('game wordt gecontroleerd', names['WelcomeTitle'].attrib['Text'])
        self.assertEqual(names['OpenGameLibrary'].attrib['Content'], 'Gamebestandenmap openen')

    def run_routing(self, runtime):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='onboarding-', dir=parent) as directory:
            folder = Path(directory)
            script = folder / 'fixture.ps1'
            script.write_text(FIXTURE, encoding='utf-8-sig')
            result = subprocess.run([str(runtime), '-NoProfile', '-File', str(script), '-Source',
                                     str(ROOT / 'tools/Show-A2Launcher.ps1'), '-Root', str(folder)],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=35)
            if 'UnauthorizedAccess' in result.stderr and 'running scripts is disabled' in result.stderr:
                self.skipTest('Local script policy blocks fixture; policy unchanged.')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout.strip())
            for scenario, passed in data.items():
                with self.subTest(scenario=scenario):
                    self.assertIs(passed, True, data)

    @unittest.skipUnless(os.name == 'nt', 'Windows routing helpers')
    def test_staged_routing_windows_powershell(self):
        self.run_routing(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')

    def test_staged_routing_powershell7(self):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 unavailable')
        self.run_routing(runtime)
