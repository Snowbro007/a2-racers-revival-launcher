"""Game-free folder-input and WPF construction checks; no file picker opened."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools import portable_test

ROOT=Path(__file__).resolve().parents[1]
PWSH=shutil.which('pwsh')


def ps_quote(value):
    return "'"+str(value).replace("'","''")+"'"


@unittest.skipUnless(os.name=='nt' and PWSH,'WPF requires Windows and PowerShell 7')
class FolderPickerTests(unittest.TestCase):
    def invoke(self,body):
        script='$ErrorActionPreference="Stop"; Set-StrictMode -Version Latest; . '+ps_quote(ROOT/'tools/launcher_folder_picker.ps1')+'; '+body
        result=subprocess.run([PWSH,'-NoProfile','-NonInteractive','-STA','-Command',script],capture_output=True,text=True,encoding='utf-8',timeout=35)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return json.loads(result.stdout)

    def test_editable_path_window_accepts_quoted_unicode_spaces_and_shell_metacharacters(self):
        parent=ROOT/'local/test-fixtures';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='map ',dir=parent) as temporary:
            folder=Path(temporary)/"eigen game é & ' test";folder.mkdir()
            value='  "'+str(folder)+'"  '
            report=self.invoke('$parts=New-A2FolderPickerWindow $null "synthetic description"; '
                '$parts.path.Text='+ps_quote(value)+'; '
                '$resolved=Resolve-A2FolderInput $parts.path.Text; '
                '[ordered]@{path=$resolved;editable=(-not $parts.path.IsReadOnly);description=$parts.window.FindName("Description").Text;'
                'default=$parts.window.FindName("Accept").IsDefault;cancel=$parts.window.FindName("Cancel").IsCancel;'
                'name=[Windows.Automation.AutomationProperties]::GetName($parts.path)} | ConvertTo-Json; $parts.window.Close()')
            self.assertEqual(Path(report['path']),folder)
            self.assertTrue(report['editable']);self.assertTrue(report['default']);self.assertTrue(report['cancel'])
            self.assertEqual(report['description'],'synthetic description');self.assertEqual(report['name'],'Pad naar je gamemap')

    def test_blank_relative_command_url_and_missing_folder_are_rejected(self):
        values=['','   ','relative/path','C:relative','https://example.invalid/game','C:/not-a-real-a2-test-path-000000']
        body='$values=@('+','.join(ps_quote(value) for value in values)+'); $results=@(foreach($value in $values){try{Resolve-A2FolderInput $value | Out-Null; $false}catch{$true}}); ConvertTo-Json -InputObject $results'
        self.assertEqual(self.invoke(body),[True]*len(values))

    def test_all_three_map_routes_use_the_shared_picker_and_package_contains_it(self):
        source=(ROOT/'tools/Show-A2Launcher.ps1').read_text(encoding='utf-8')
        self.assertEqual(source.count('Select-A2GameFolder $window'),3)
        self.assertNotIn('New-Object Windows.Forms.FolderBrowserDialog',source)
        self.assertIn('tools/launcher_folder_picker.ps1',portable_test.APP_FILES)
        self.assertIn('tools/game_source_files.py',portable_test.APP_FILES)
        self.assertIn('tools/game_source_profiles.py',portable_test.APP_FILES)

if __name__=='__main__':unittest.main()
