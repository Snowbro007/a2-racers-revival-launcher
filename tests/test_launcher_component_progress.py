"""Read synthetic progress records without showing UI or starting a game."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''param([string]$Source,[string]$Common,[string]$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
foreach($file in @($Common,$Source)){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'PowerShell syntax error'}
    foreach($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
        if($definition.Name -in @('Assert-LauncherPath','Read-LauncherComponentProgress')){Invoke-Expression $definition.Extent.Text}
    }
}
$path=Join-Path $Root 'local\launcher\component-progress.json'
[IO.Directory]::CreateDirectory((Split-Path -Parent $path))|Out-Null
$record=@{schema=1;stage='downloading';component='ffmpeg-9.0.2-essentials_build.zip';received=1048576;total=2097152}
function Save-Record($Value){[IO.File]::WriteAllText($path,($Value|ConvertTo-Json -Compress))}
Save-Record $record
$valid=Read-LauncherComponentProgress $Root ([DateTime]::UtcNow.AddMinutes(-1))
$stale=Read-LauncherComponentProgress $Root ([DateTime]::UtcNow.AddMinutes(1))
$record.total=$null;Save-Record $record
$unknown=Read-LauncherComponentProgress $Root ([DateTime]::MinValue)
$record.stage='complete';Save-Record $record
$complete=Read-LauncherComponentProgress $Root ([DateTime]::MinValue)
$invalid=0
foreach($change in @(@{received=-1},@{received=$true},@{total=1},@{total='2097152'},@{schema=$true},@{component='untrusted.exe'},@{stage='run'})){
    $bad=@{schema=1;stage='downloading';component='ffmpeg-9.0.2-essentials_build.zip';received=1048576;total=2097152}
    foreach($key in $change.Keys){$bad[$key]=$change[$key]}
    Save-Record $bad
    if($null -eq (Read-LauncherComponentProgress $Root ([DateTime]::MinValue))){$invalid++}
}
[IO.File]::WriteAllText($path,'{broken')
$partial=Read-LauncherComponentProgress $Root ([DateTime]::MinValue)
@{valid=$valid;stale=$stale;unknown=$unknown;complete=$complete;invalid=$invalid;partial=$partial}|ConvertTo-Json -Depth 5 -Compress
'''


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell progress reader')
class LauncherComponentProgressTests(unittest.TestCase):
    def check_reader(self, runtime):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='component-progress-', dir=parent) as directory:
            folder = Path(directory)
            script = folder / 'fixture.ps1'
            script.write_text(FIXTURE, encoding='utf-8-sig')
            result = subprocess.run([str(runtime), '-NoProfile', '-File', str(script),
                                     '-Source', str(ROOT / 'tools/Show-A2Launcher.ps1'),
                                     '-Common', str(ROOT / 'tools/launcher_common.ps1'),
                                     '-Root', str(folder)], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=30)
            if 'running scripts is disabled' in result.stderr and 'UnauthorizedAccess' in result.stderr:
                self.skipTest('Local script policy blocks fixture; policy unchanged.')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout.strip())
            self.assertEqual(data['valid']['title'], 'Onderdelen downloaden')
            self.assertIn('Video en muziek', data['valid']['message'])
            self.assertIn('1 van 2 MB', data['valid']['message'])
            self.assertIn('ontvangen', data['unknown']['message'])
            self.assertIn('uitgepakt', data['complete']['message'])
            self.assertIsNone(data['stale'])
            self.assertIsNone(data['partial'])
            self.assertEqual(data['invalid'], 7)

    def test_reader_windows_powershell(self):
        self.check_reader(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')

    def test_reader_powershell7(self):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 unavailable')
        self.check_reader(runtime)
