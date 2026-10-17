"""Public first-run integrity uses synthetic byte streams, never real downloads."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
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

@unittest.skipUnless(os.name=='nt','Windows public-bootstrap stream checks')
class PublicBootstrapTests(unittest.TestCase):
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
