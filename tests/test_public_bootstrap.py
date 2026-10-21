"""Public first-run integrity uses synthetic byte streams, never real downloads."""
import json
import os
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import portable_test

ROOT=Path(__file__).resolve().parents[1]

FIXTURE=r'''param([string]$Source,[string]$Folder)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Invalid provider bootstrap syntax'}
foreach($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
    # Bound the synthetic stream quota to 16 bytes instead of 180 MiB.
    Invoke-Expression ($definition.Extent.Text.Replace('180MB','16'))
}
function Pin([byte[]]$Data){$sha=[Security.Cryptography.SHA256]::Create();try{[BitConverter]::ToString($sha.ComputeHash($Data)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}}
function Write-A2DownloadProgress {param($Component,$Received,$ExpectedLength)}
$data=[Text.Encoding]::UTF8.GetBytes('fixture');$pin=Pin $data
$path=Join-Path $Folder 'cache\provider.zip'
$inputStream=New-Object IO.MemoryStream (,$data)
try{Copy-A2ProviderStream $inputStream $path $pin}finally{$inputStream.Dispose()}
$valid=Test-A2ProviderFile $path $pin
$inputStream=New-Object IO.MemoryStream (,$data)
try{Copy-A2ProviderStream $inputStream $path $pin}finally{$inputStream.Dispose()}
$repeat=Test-A2ProviderFile $path $pin
$failed=0
foreach($bytes in @([Text.Encoding]::UTF8.GetBytes('wrong'),[Text.Encoding]::UTF8.GetBytes('way-too-long-fixture-data'))){
    $inputStream=New-Object IO.MemoryStream (,$bytes)
    try{Copy-A2ProviderStream $inputStream (Join-Path $Folder 'cache\bad.zip') $pin}catch{$failed++}finally{$inputStream.Dispose()}
}
[IO.File]::WriteAllBytes($path,[Text.Encoding]::UTF8.GetBytes('foreign'))
$inputStream=New-Object IO.MemoryStream (,$data)
try{Copy-A2ProviderStream $inputStream $path $pin}catch{$failed++}finally{$inputStream.Dispose()}
$foreign=[Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($path))
$providers=@(Get-A2PublicProviders | ForEach-Object {@{name=$_.name;sha256=$_.sha256;url=$_.url}})
@{valid=$valid;repeat=$repeat;failed=$failed;foreign=$foreign;partial=@(Get-ChildItem -LiteralPath (Join-Path $Folder 'cache') -Filter '*.download' -Force).Count;bad_exists=(Test-Path -LiteralPath (Join-Path $Folder 'cache\bad.zip'));providers=$providers} | ConvertTo-Json -Depth 5 -Compress
'''

LOAD_FUNCTIONS=FIXTURE.split('$data=')[0]

LENGTH_FIXTURE=LOAD_FUNCTIONS+r'''
$data=[Text.Encoding]::UTF8.GetBytes('fixture');$pin=Pin $data
$eventsList=New-Object 'Collections.Generic.List[object]'
$callback={param($name,$received,$expected) $eventsList.Add(@{component=$name;received=$received;total=$expected})}
$path=Join-Path $Folder 'cache\complete.zip'
$statePath=Join-Path $Folder 'local\launcher\component-progress.json'
$inputStream=New-Object IO.MemoryStream (,$data)
try{Copy-A2ProviderStream $inputStream $path $pin -ExpectedLength $data.Length -Component 'fixture.zip' -Clock {0} -DeadlineMilliseconds 100 -Progress $callback -ProgressRoot $Folder -ProgressPath $statePath}finally{$inputStream.Dispose()}
$state=[IO.File]::ReadAllText($statePath)|ConvertFrom-Json
$failed=@{}
foreach($length in @(-2,0,6,8,17)){
    $candidate=Join-Path $Folder ('cache\length'+$length+'.zip')
    $inputStream=New-Object IO.MemoryStream (,$data)
    try{Copy-A2ProviderStream $inputStream $candidate $pin -ExpectedLength $length;$failed[[string]$length]=$false}catch{$failed[[string]$length]=-not [IO.File]::Exists($candidate)}finally{$inputStream.Dispose()}
}
$unknown=Join-Path $Folder 'cache\unknown.zip'
$inputStream=New-Object IO.MemoryStream (,$data)
try{Copy-A2ProviderStream $inputStream $unknown $pin -ExpectedLength -1}finally{$inputStream.Dispose()}
$invalidPath=Join-Path $Folder 'outside-progress.json';$badPathRejected=$false
try{Write-A2ComponentState $Folder $invalidPath 'complete'}catch{$badPathRejected=-not [IO.File]::Exists($invalidPath)}
Write-A2ComponentState $Folder $statePath 'complete'
$final=[IO.File]::ReadAllText($statePath)|ConvertFrom-Json
@{valid=(Test-A2ProviderFile $path $pin);unknown=(Test-A2ProviderFile $unknown $pin);failed=$failed;events=$eventsList.ToArray();state=$state;final=$final;bad_path=$badPathRejected;temporary=@(Get-ChildItem -LiteralPath $Folder -Recurse -Force -File|Where-Object {$_.Name -like '*.tmp' -or $_.Name -like '*.download'}).Count} | ConvertTo-Json -Depth 5 -Compress
'''

DEADLINE_FIXTURE=LOAD_FUNCTIONS+r'''
$data=[Text.Encoding]::UTF8.GetBytes('fixture');$pin=Pin $data
# Synthetic stream returns one byte immediately each time: no sleep or network.
$stream=[PSCustomObject]@{Position=0;Data=$data}
$stream|Add-Member ScriptMethod ReadAsync {param($buffer,$offset,$count,$token)
    $completion=New-Object 'Threading.Tasks.TaskCompletionSource[int]'
    if($this.Position -ge $this.Data.Length){$completion.SetResult(0)}else{$buffer[$offset]=$this.Data[$this.Position];$this.Position++;$completion.SetResult(1)}
    return $completion.Task
}
$script:ticks=0
$clock={$script:ticks++;return $script:ticks}
$path=Join-Path $Folder 'cache\drip.zip';$expired=$false
try{Copy-A2ProviderStream $stream $path $pin -Clock $clock -DeadlineMilliseconds 18}catch{$expired=$_.Exception.Message -like '*Downloadtijd verstreken*'}
$waits=New-Object 'Collections.Generic.List[int]'
$pending=[PSCustomObject]@{}
$pending|Add-Member ScriptMethod Wait {param($milliseconds) $waits.Add($milliseconds);return $false}
$bounded=$false
try{Wait-A2DownloadTask $pending 19 {0} 'fixture.zip'}catch{$bounded=$_.Exception.Message -like '*reageert niet*'}
try{Wait-A2DownloadTask $pending 90000 {0} 'fixture.zip'}catch{}
$before=$waits.Count;$alreadyExpired=$false
try{Wait-A2DownloadTask $pending 20 {20} 'fixture.zip'}catch{$alreadyExpired=$_.Exception.Message -like '*Downloadtijd verstreken*'}
@{expired=$expired;reads=$stream.Position;destination_exists=[IO.File]::Exists($path);bounded=$bounded;waits=$waits.ToArray();already_expired=$alreadyExpired;no_wait_after_deadline=($waits.Count -eq $before);partial=@(Get-ChildItem -LiteralPath (Join-Path $Folder 'cache') -Filter '*.download' -Force).Count} | ConvertTo-Json -Compress
'''

OFFLINE_FIXTURE=LOAD_FUNCTIONS+r'''
$statePath=Join-Path $Folder 'local\launcher\component-progress.json'
$failed=$false
try{Install-A2PublicProviders $Folder -OfflineCheck -ProgressPath $statePath}catch{$failed=$_.Exception.Message -like '*Component ontbreekt*'}
$value=[IO.File]::ReadAllText($statePath)|ConvertFrom-Json
@{failed=$failed;state=$value;temporary=@(Get-ChildItem -LiteralPath $Folder -Recurse -Force -File|Where-Object {$_.Name -like '*.tmp'}).Count}|ConvertTo-Json -Depth 4 -Compress
'''

LOCKED_PROGRESS_FIXTURE=LOAD_FUNCTIONS+r'''
$data=[Text.Encoding]::UTF8.GetBytes('fixture');$pin=Pin $data
$statePath=Join-Path $Folder 'local\launcher\component-progress.json'
Write-A2ComponentState $Folder $statePath 'checking'
$before=[IO.File]::ReadAllBytes($statePath)
$held=[IO.File]::Open($statePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
$path=Join-Path $Folder 'cache\complete.zip';$bad=Join-Path $Folder 'cache\bad.zip'
$hashError='';$offlineError='';$invalidRejected=$false
try{
    $inputStream=New-Object IO.MemoryStream (,$data)
    try{Copy-A2ProviderStream $inputStream $path $pin -ExpectedLength $data.Length -ProgressRoot $Folder -ProgressPath $statePath}finally{$inputStream.Dispose()}
    $inputStream=New-Object IO.MemoryStream (,$data)
    try{Copy-A2ProviderStream $inputStream $bad ('0'*64) -ProgressRoot $Folder -ProgressPath $statePath}catch{$hashError=$_.Exception.Message}finally{$inputStream.Dispose()}
    try{Install-A2PublicProviders $Folder -OfflineCheck -ProgressPath $statePath}catch{$offlineError=$_.Exception.Message}
    try{Write-A2ComponentState $Folder (Join-Path $Folder 'outside.json') 'complete'}catch{$invalidRejected=$_.Exception.Message -like '*Ongeldig componentvoortgangspad*'}
}finally{$held.Dispose()}
$after=[IO.File]::ReadAllBytes($statePath)
@{valid=(Test-A2ProviderFile $path $pin);bad_exists=[IO.File]::Exists($bad);hash_error=$hashError;offline_error=$offlineError;invalid_rejected=$invalidRejected;progress_preserved=([Convert]::ToBase64String($before) -eq [Convert]::ToBase64String($after));temporary=@(Get-ChildItem -LiteralPath $Folder -Recurse -Force -File|Where-Object {$_.Name -like '*.tmp' -or $_.Name -like '*.download'}).Count}|ConvertTo-Json -Compress
'''

STAGED_PROVIDERS_FIXTURE=LOAD_FUNCTIONS+r'''
$all=@(Get-A2PublicProviders);$launcher=@(Get-A2PublicProviders -LauncherOnly)
$data=[Text.Encoding]::UTF8.GetBytes('fixture');$pin=Pin $data
$payload=Join-Path $Folder 'payload';[IO.Directory]::CreateDirectory($payload)|Out-Null
[IO.File]::WriteAllBytes((Join-Path $payload 'python.zip'),$data)
function Get-A2PublicProviders([switch]$LauncherOnly) {
    $selected=@(@{name='python.zip';sha256=$pin;url='https://example.invalid/python.zip'})
    if(-not $LauncherOnly){$selected+=@{name='game.zip';sha256=$pin;url='https://example.invalid/game.zip'}}
    return $selected
}
$statePath=Join-Path $Folder 'local\launcher\component-progress.json'
$minimal=Install-A2PublicProviders $Folder -OfflineCheck -LauncherOnly -ProgressPath $statePath
$fullMissing=$false
try{Install-A2PublicProviders $Folder -OfflineCheck -ProgressPath $statePath}catch{$fullMissing=$_.Exception.Message -like '*Component ontbreekt: game.zip*'}
@{all_count=$all.Count;launcher_names=@($launcher|ForEach-Object {$_.name});minimal=$minimal;full_missing=$fullMissing}|ConvertTo-Json -Depth 5 -Compress
'''


class LauncherOnlySetupTests(unittest.TestCase):
    def test_python_only_setup_never_inspects_games_or_requires_other_providers(self):
        parent=ROOT/'local/test-fixtures';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='launcher-only é ',dir=parent) as folder:
            root=Path(folder);provider=root/'payload/python.zip';provider.parent.mkdir()
            with zipfile.ZipFile(provider,'x') as archive:
                archive.writestr('python.exe',b'synthetic text, never executed')
                archive.writestr('python313._pth',b'python313.zip\n.\n')
            pin=hashlib.sha256(provider.read_bytes()).hexdigest()
            # A foreign game-like directory must not be opened during launcher setup.
            game=root/'local/games/a2racer1';game.mkdir(parents=True)
            (game/'A2.EXE').write_bytes(b'unknown fixture, preserve')
            providers={'python':('python.zip',pin,'unused'),
                       'powershell':('missing.zip','0'*64,'unused')}
            with patch.object(portable_test,'PAYLOADS',providers):
                result=portable_test.setup_components(root,launcher_only=True)
                self.assertTrue(result['launcher_ready']);self.assertFalse(result['components_ready'])
                self.assertFalse(result['game_imported'])
                self.assertEqual((root/'local/portable-runtime/python/python.exe').read_bytes(),b'synthetic text, never executed')
                self.assertFalse((root/'local/portable-runtime/powershell').exists())
                self.assertFalse((root/'local/components').exists())
                self.assertEqual((game/'A2.EXE').read_bytes(),b'unknown fixture, preserve')
                # A minimal success is not sufficient for the full game setup.
                with self.assertRaises((OSError,ValueError)):
                    portable_test.setup_components(root)
                (root/'local/portable-runtime/python/python.exe').write_bytes(b'foreign runtime')
                with self.assertRaisesRegex(ValueError,'gewijzigd'):
                    portable_test.setup_components(root,launcher_only=True)
                self.assertEqual((root/'local/portable-runtime/python/python.exe').read_bytes(),b'foreign runtime')

    def test_launcher_only_flag_cannot_select_other_actions(self):
        with patch('sys.argv',['portable_test.py','import','--launcher-only']):
            with self.assertRaises(SystemExit) as error:
                portable_test.main()
        self.assertEqual(error.exception.code,1)

@unittest.skipUnless(os.name=='nt','Windows public-bootstrap stream checks')
class PublicBootstrapTests(unittest.TestCase):
    def fixture(self, text, runtime=None):
        parent=ROOT/'local/test-fixtures';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='download limits é ',dir=parent) as folder:
            script=Path(folder)/'fixture.ps1';script.write_text(text,encoding='utf-8-sig')
            ps=runtime or shutil.which('pwsh')
            if not ps:self.skipTest('PowerShell runtime unavailable')
            result=subprocess.run([ps,'-NoProfile','-File',str(script),'-Source',str(ROOT/'tools/Initialize-A2Public.ps1'),'-Folder',folder],capture_output=True,text=True,encoding='utf-8',timeout=30)
            if 'running scripts is disabled' in result.stderr and 'UnauthorizedAccess' in result.stderr:
                self.skipTest('Local execution policy blocks this test script; policy unchanged.')
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)

    def test_expected_length_and_atomic_component_progress(self):
        result=self.fixture(LENGTH_FIXTURE)
        self.assertTrue(result['valid']);self.assertTrue(result['unknown'])
        self.assertEqual(result['failed'],{str(n):True for n in (-2,0,6,8,17)})
        self.assertEqual(result['events'],[{'component':'fixture.zip','received':0,'total':7},{'component':'fixture.zip','received':7,'total':7}])
        self.assertEqual(result['state'],dict(schema=1,stage='downloading',component='fixture.zip',received=7,total=7))
        self.assertEqual(result['final'],dict(schema=1,stage='complete',component='',received=0,total=None))
        self.assertTrue(result['bad_path']);self.assertEqual(result['temporary'],0)

    def test_launcher_stage_selects_python_and_does_not_claim_full_readiness(self):
        result=self.fixture(STAGED_PROVIDERS_FIXTURE)
        self.assertEqual(result['all_count'],5)
        self.assertEqual(result['launcher_names'],['python-3.13.16-embed-amd64.zip'])
        self.assertEqual(result['minimal'],dict(components_downloaded=0,components_checked=1,
                                               game_downloaded=False,scope='launcher'))
        self.assertTrue(result['full_missing'])

    def test_launcher_only_start_refuses_game_options_before_any_setup(self):
        runtime=shutil.which('pwsh')
        if not runtime:self.skipTest('PowerShell runtime unavailable')
        parent=ROOT/'local/test-fixtures';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='control-only é ',dir=parent) as folder:
            script=Path(folder)/'tools/Start-A2Portable.ps1';script.parent.mkdir()
            script.write_bytes((ROOT/'tools/Start-A2Portable.ps1').read_bytes())
            for arguments in (['-LauncherOnly'],['-CheckOnly','-LauncherOnly','-GameArchive','synthetic.zip'],
                              ['-CheckOnly','-LauncherOnly','-Diagnostic']):
                result=subprocess.run([runtime,'-NoProfile','-File',str(script),*arguments],
                                      capture_output=True,text=True,encoding='utf-8',timeout=15)
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                self.assertIn('LauncherOnly is uitsluitend voor de launchercontrole',result.stdout)
            self.assertEqual(sorted(p.relative_to(folder).as_posix() for p in Path(folder).rglob('*') if p.is_file()),
                             ['tools/Start-A2Portable.ps1'])

    def test_dripping_body_is_bounded_by_total_deadline_and_read_budget(self):
        result=self.fixture(DEADLINE_FIXTURE)
        self.assertTrue(result['expired']);self.assertGreater(result['reads'],1);self.assertLess(result['reads'],7)
        self.assertFalse(result['destination_exists']);self.assertEqual(result['partial'],0)
        self.assertTrue(result['bounded']);self.assertEqual(result['waits'],[19,30000])
        self.assertTrue(result['already_expired']);self.assertTrue(result['no_wait_after_deadline'])

    def test_missing_offline_component_records_error_without_network(self):
        result=self.fixture(OFFLINE_FIXTURE)
        self.assertTrue(result['failed']);self.assertEqual(result['temporary'],0)
        self.assertEqual(result['state'],dict(schema=1,stage='error',component='python-3.13.16-embed-amd64.zip',received=0,total=None))

    def test_locked_optional_progress_preserves_download_and_original_failures(self):
        result=self.fixture(LOCKED_PROGRESS_FIXTURE)
        self.assertTrue(result['valid']);self.assertFalse(result['bad_exists'])
        self.assertIn('Componenthash wijkt af',result['hash_error'])
        self.assertIn('Component ontbreekt: python-',result['offline_error'])
        self.assertTrue(result['invalid_rejected']);self.assertTrue(result['progress_preserved'])
        self.assertEqual(result['temporary'],0)

    def test_download_guards_and_progress_work_in_windows_powershell51(self):
        runtime=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
        for fixture,key in ((LENGTH_FIXTURE,'valid'),(DEADLINE_FIXTURE,'expired'),(OFFLINE_FIXTURE,'failed')):
            self.assertTrue(self.fixture(fixture,runtime)[key])

    def test_hashes_stream_limit_atomic_cache_and_provider_identity(self):
        parent=ROOT/'local/test-fixtures';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='public bootstrap é ',dir=parent) as folder:
            script=Path(folder)/'fixture.ps1';script.write_text(FIXTURE,encoding='utf-8-sig')
            ps=shutil.which('pwsh')
            if not ps:self.skipTest('PowerShell runtime unavailable')
            result=subprocess.run([ps,'-NoProfile','-File',str(script),'-Source',str(ROOT/'tools/Initialize-A2Public.ps1'),'-Folder',folder],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            checked=json.loads(result.stdout)
            self.assertTrue(checked['valid']);self.assertTrue(checked['repeat'])
            self.assertEqual(checked['failed'],3);self.assertEqual(checked['foreign'],'foreign')
            self.assertEqual(checked['partial'],0);self.assertFalse(checked['bad_exists'])
            expected={row[0]:row[1] for row in portable_test.PAYLOADS.values()}
            self.assertEqual({row['name']:row['sha256'] for row in checked['providers']},expected)
            self.assertTrue(all(row['url'].startswith('https://') for row in checked['providers']))
