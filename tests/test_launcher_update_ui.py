"""Real WPF update controls with synthetic tasks; no network, installer or game."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''param([string]$Root,[string]$Fixture)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
. (Join-Path $Root 'tools/launcher_common.ps1')
. (Join-Path $Root 'tools/launcher_updates.ps1')
$reader=New-Object Xml.XmlNodeReader ([xml][IO.File]::ReadAllText((Join-Path $Root 'tools/launcher_window.xaml')))
try{$window=[Windows.Markup.XamlReader]::Load($reader)}finally{$reader.Close()}
function New-LauncherProcess { throw 'No process is allowed in this synthetic UI test' }
function Open-VerifiedLauncherUpdate { throw 'No installer is allowed in this synthetic UI test' }
function Set-TestTask([string]$Action,[string]$Json,[int]$Code=0) {
    $task=[Threading.Tasks.TaskCompletionSource[string]]::new();$task.SetResult($Json)
    $process=[PSCustomObject]@{HasExited=$true;ExitCode=$Code}
    $process|Add-Member -MemberType ScriptMethod -Name Dispose -Value {}
    $script:launcherUpdates.process=@{process=$process;output=$task.Task}
    $script:launcherUpdates.action=$Action
}
$script:testBusy=$false
$ui=@{}
Initialize-LauncherUpdates $window $ui $Fixture {return $null} {return $script:testBusy}
Poll-LauncherUpdates
if($ui.InstallUpdate.IsEnabled){throw 'Install enabled before download'}
if($ui.LauncherVersion.Text -ne 'A2 Racers Revival · 0.1.0-beta.5'){throw 'Version is not displayed'}
$ui.CheckUpdates.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Primitives.ButtonBase]::ClickEvent))
if($script:launcherUpdates.process){throw 'Process before runtime initialization'}
$script:launcherUpdates.initialized=$true
Set-TestTask 'check' '{"state":"available","message":"Synthetic update available","offer":{"version":"0.1.0-beta.6"}}'
Poll-LauncherUpdates
if($ui.DownloadUpdate.Visibility -ne 'Visible' -or -not $ui.DownloadUpdate.IsEnabled){throw 'Download action unavailable'}
$script:testBusy=$true
Set-TestTask 'download' '{"state":"downloaded","message":"Synthetic download verified","receipt":"synthetic-only"}'
Poll-LauncherUpdates
if($ui.InstallUpdate.IsEnabled){throw 'Installer enabled while game/worker is busy'}
$script:testBusy=$false;Poll-LauncherUpdates
if(-not $ui.InstallUpdate.IsEnabled){throw 'Verified download action missing'}
Set-TestTask 'verify' '{"state":"error","message":"Synthetic changed file refused"}' 1
Poll-LauncherUpdates
if($ui.UpdateMessage.Text -notlike '*Synthetic changed file refused*'){throw 'Refusal not shown'}
Set-TestTask 'check' '{"state":"current","message":"No newer installer"}'
Poll-LauncherUpdates
if($ui.DownloadUpdate.Visibility -ne 'Collapsed' -or $ui.InstallUpdate.IsEnabled){throw 'Old offer remained active'}
'Update controls: OK; no network, installer or game executed'
'''


@unittest.skipUnless(os.name == 'nt', 'Windows WPF')
class UpdateUITests(unittest.TestCase):
    def test_updater_backend_and_controls_are_in_the_runtime_package(self):
        from tools.portable_launcher import app_files
        files = set(app_files(ROOT))
        self.assertTrue({'tools/launcher_updates.py', 'tools/launcher_updates.ps1'} <= files)
        self.assertFalse('tools/create_update_review.py' in files)

    def test_update_controls_refuse_busy_or_changed_installer_without_launching(self):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 unavailable')
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='update-ui-', dir=parent) as folder:
            fixture = Path(folder)
            (fixture / 'VERSION.txt').write_text('0.1.0-beta.5')
            source = fixture / 'update-ui.ps1'
            source.write_text(FIXTURE, encoding='utf-8-sig')
            result = subprocess.run([runtime, '-NoProfile', '-STA', '-File', str(source),
                                     '-Root', str(ROOT), '-Fixture', str(fixture)],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Update controls: OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
