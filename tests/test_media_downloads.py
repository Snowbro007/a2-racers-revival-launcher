"""Deferred media setup and resumed HTTP bodies use synthetic data only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import portable_test, trial_manifest
from tests.test_public_bootstrap import LOAD_FUNCTIONS

ROOT = Path(__file__).resolve().parents[1]


class MediaSetupTests(unittest.TestCase):
    def test_game_setup_without_media_and_later_media_upgrade(self):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='media-setup-', dir=parent) as directory:
            root = Path(directory)
            providers = {}
            original = b'OutputAPI = bestavailable\nFullScreenMode = true\nAppControlledScreenMode = true\n'
            final = original.replace(b'bestavailable', b'd3d11_fl11_0').replace(b'true', b'false')
            entries = {
                'python': {'python.exe': b'synthetic python text'},
                'powershell': {'pwsh.exe': b'synthetic powershell text'},
                'cnc': {'ddraw.dll': b'synthetic wrapper text'},
                'dgvoodoo': {'MS/x86/DDraw.dll': b'wrapper1', 'MS/x86/D3DImm.dll': b'wrapper2',
                            'dgVoodoo.conf': original},
                'ffmpeg': {'ffplay.exe': b'synthetic player text'},
            }
            for kind, members in entries.items():
                archive = root / 'payload' / (kind + '.zip')
                archive.parent.mkdir(exist_ok=True)
                with zipfile.ZipFile(archive, 'x') as output:
                    for name, data in members.items():
                        output.writestr(name, data)
                providers[kind] = (archive.name, hashlib.sha256(archive.read_bytes()).hexdigest(), 'unused')
            media = root / 'payload/ffmpeg.zip'
            saved_media = media.read_bytes()
            media.unlink()
            with patch.object(portable_test, 'PAYLOADS', providers), \
                    patch.object(portable_test, 'ARCHIVE_SHA256', providers['ffmpeg'][1]), \
                    patch.object(trial_manifest, 'DGVOODOO_CONFIG_SOURCE',
                                 {'source': 'synthetic.conf', 'sha256': hashlib.sha256(final).hexdigest()}), \
                    patch.object(trial_manifest, 'plan_graphics_wrapper'):
                ready = portable_test.setup_components(root, skip_media=True)
                self.assertTrue(ready['components_ready'])
                self.assertFalse((root / 'local/components/ffmpeg').exists())
                self.assertFalse(media.exists())
                # Full setup still requires a checked player when requested.
                with self.assertRaises((OSError, ValueError)):
                    portable_test.setup_components(root)
                media.write_bytes(saved_media)
                portable_test.setup_components(root)
                installed = root / 'local/components/ffmpeg/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
                self.assertEqual(installed.read_bytes(), saved_media)
                before = installed.read_bytes()
                portable_test.setup_components(root, skip_media=True)
                self.assertEqual(installed.read_bytes(), before)

    def test_skip_media_does_not_change_import_or_start_commands(self):
        with patch('sys.argv', ['portable_test.py', 'import', '--skip-media']):
            with self.assertRaises(SystemExit) as error:
                portable_test.main()
        self.assertEqual(error.exception.code, 1)


RESUME_FIXTURE = LOAD_FUNCTIONS + r'''
Add-Type -AssemblyName System.Net.Http
$all=@(Get-A2PublicProviders);$base=@(Get-A2PublicProviders -SkipMedia)
$data=[Text.Encoding]::UTF8.GetBytes('abcdefghij');$pin=Pin $data
$script:requests=New-Object 'Collections.Generic.List[object]'
$script:responses=New-Object 'Collections.Generic.Queue[object]'
function Get-A2PublicProviders([switch]$LauncherOnly,[switch]$SkipMedia){
    return @(@{name='fixture.zip';sha256=$pin;url='https://example.invalid/fixture.zip'})
}
$factory={
    $client=[PSCustomObject]@{Timeout=$null}
    $client|Add-Member ScriptMethod Dispose {}
    $client|Add-Member ScriptMethod SendAsync {param($request,$option,$token)
        $script:requests.Add([string]$request.Headers.Range)
        $reply=$script:responses.Dequeue()
        $response=New-Object Net.Http.HttpResponseMessage ([Net.HttpStatusCode]$reply.status)
        $response.RequestMessage=$request
        $response.Content=New-Object Net.Http.ByteArrayContent (,[byte[]]$reply.body)
        if($reply.ContainsKey('length')){$response.Content.Headers.ContentLength=$reply.length}
        if($reply.ContainsKey('range')){$response.Content.Headers.ContentRange=[Net.Http.Headers.ContentRangeHeaderValue]::Parse($reply.range)}
        $completion=New-Object 'Threading.Tasks.TaskCompletionSource[Net.Http.HttpResponseMessage]'
        $completion.SetResult($response);return $completion.Task
    }
    return $client
}
function Fetch {
    Install-A2PublicProviders $Folder -ClientFactory $factory 6>$null | Out-Null
}
$path=Join-Path $Folder 'payload\fixture.zip'
$partial=Get-A2DownloadPartial $path $pin
$script:responses.Enqueue(@{status=200;body=$data[0..3];length=10})
$interrupted=$false
try{Fetch}catch{$interrupted=$_.Exception.Message -like '*onvolledig*'}
$kept=[IO.File]::Exists($partial) -and (Get-Item -LiteralPath $partial).Length -eq 4 -and -not [IO.File]::Exists($path)
$script:responses.Enqueue(@{status=206;body=$data[4..9];length=6;range='bytes 4-9/10'})
Fetch
$resumed=(Test-A2ProviderFile $path $pin) -and -not [IO.File]::Exists($partial)
$rangeRequest=$script:requests[1]
[IO.File]::Delete($path)
# If Range is ignored, discard the prefix and start with the complete 200 body.
[IO.File]::WriteAllBytes($partial,[Text.Encoding]::UTF8.GetBytes('wrong'))
$script:responses.Enqueue(@{status=200;body=$data})
Fetch
$restarted=Test-A2ProviderFile $path $pin
[IO.File]::Delete($path)
# Do not append an incorrect Content-Range to the retained prefix.
[IO.File]::WriteAllBytes($partial,$data[0..3])
$script:responses.Enqueue(@{status=206;body=$data[5..9];length=5;range='bytes 5-9/10'})
$badRange=$false
try{Fetch}catch{$badRange=$_.Exception.Message -like '*ongeldig hervatbereik*'}
$rangePreserved=(Get-Item -LiteralPath $partial).Length -eq 4
# A corrupted prefix can never be promoted, even with valid response headers.
[IO.File]::WriteAllBytes($partial,[Text.Encoding]::UTF8.GetBytes('xxxx'))
$script:responses.Enqueue(@{status=206;body=$data[4..9];length=6;range='bytes 4-9/10'})
$badHash=$false
try{Fetch}catch{$badHash=$_.Exception.Message -like '*Componenthash wijkt af*'}
$hashRefused=$badHash -and -not [IO.File]::Exists($path) -and -not [IO.File]::Exists($partial)
# Fully received, verified partials recover after an interruption before move.
[IO.File]::WriteAllBytes($partial,$data)
$script:responses.Enqueue(@{status=416;body=[byte[]]@()})
Fetch
$completed=Test-A2ProviderFile $path $pin
$request=New-Object Net.Http.HttpRequestMessage ([Net.Http.HttpMethod]::Get),'https://example.invalid/test'
$response=New-Object Net.Http.HttpResponseMessage ([Net.HttpStatusCode]::PartialContent)
$response.RequestMessage=$request;$response.Content=New-Object Net.Http.ByteArrayContent (,$data)
$response.Content.Headers.ContentRange=[Net.Http.Headers.ContentRangeHeaderValue]::Parse('bytes 0-9/10')
$request.RequestUri=[Uri]'http://example.invalid/test'
$httpRefused=$false
try{Get-A2DownloadRange $response 0|Out-Null}catch{$httpRefused=$_.Exception.Message -like '*HTTPS*'}
$response.Dispose();$request.Dispose()
@{all_count=$all.Count;base_count=$base.Count;base_names=@($base|ForEach-Object {$_.name});
    interrupted=$interrupted;kept=$kept;resumed=$resumed;range_request=$rangeRequest;
    restarted=$restarted;bad_range=$badRange;range_preserved=$rangePreserved;
    hash_refused=$hashRefused;completed=$completed;http_refused=$httpRefused}|
    ConvertTo-Json -Depth 4 -Compress
'''


@unittest.skipUnless(os.name == 'nt', 'Windows provider download helpers')
class ResumeTests(unittest.TestCase):
    def run_fixture(self, runtime):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='media-resume-', dir=parent) as directory:
            script = Path(directory) / 'fixture.ps1'
            script.write_text(RESUME_FIXTURE, encoding='utf-8-sig')
            result = subprocess.run([
                str(runtime), '-NoProfile', '-File', str(script),
                '-Source', str(ROOT / 'tools/Initialize-A2Public.ps1'), '-Folder', directory,
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            if 'UnauthorizedAccess' in result.stderr and 'running scripts is disabled' in result.stderr:
                self.skipTest('Local script policy blocks fixture; policy unchanged.')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout.strip())
        self.assertEqual(data.pop('all_count'), 5)
        self.assertEqual(data.pop('base_count'), 4)
        self.assertFalse(any('ffmpeg' in name for name in data.pop('base_names')))
        self.assertEqual(data.pop('range_request'), 'bytes=4-')
        for scenario, passed in data.items():
            with self.subTest(scenario=scenario):
                self.assertIs(passed, True)

    def test_resume_and_range_validation_powershell7(self):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 unavailable')
        self.run_fixture(runtime)

    def test_resume_and_range_validation_windows_powershell(self):
        self.run_fixture(Path(os.environ['SystemRoot']) /
                         'System32/WindowsPowerShell/v1.0/powershell.exe')
