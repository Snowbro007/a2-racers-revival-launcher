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

HEADER = FIXTURE.split('function New-LauncherProcess')[0]

# Portable route: notice first, then settings, automatic check, one question,
# download after consent and the self-update start. All tasks are synthetic.
PORTABLE_FLOW = HEADER + r'''
function New-LauncherProcess { throw 'No process is allowed in this synthetic UI test' }
function Open-VerifiedLauncherUpdate { throw 'The MSI route must not open for a portable update' }
$script:asked=@();$script:started=@();$script:applied=@();$script:notices=@();$script:answer=$false
function Confirm-LauncherUpdate([string]$Text){$script:asked+=$Text;return $script:answer}
function Show-LauncherUpdateNotice([string]$Text,[bool]$Failed){$script:notices+=,@($Text,$Failed)}
function Start-PortableLauncherUpdate($Result){$script:applied+=[string]$Result.version}
function Start-LauncherUpdateTask([string]$Action,[string[]]$Arguments){$script:started+=$Action}
function Set-TestTask([string]$Action,[string]$Json,[int]$Code=0) {
    $task=[Threading.Tasks.TaskCompletionSource[string]]::new();$task.SetResult($Json)
    $process=[PSCustomObject]@{HasExited=$true;ExitCode=$Code}
    $process|Add-Member -MemberType ScriptMethod -Name Dispose -Value {}
    $script:launcherUpdates.process=@{process=$process;output=$task.Task}
    $script:launcherUpdates.action=$Action
}
$ui=@{}
Initialize-LauncherUpdates $window $ui $Fixture {return 'synthetic-runtime'} {return $false}
Poll-LauncherUpdates
if(($script:started -join ',') -ne 'notice'){throw ('Notice must be read first: '+($script:started -join ','))}
Set-TestTask 'notice' '{"state":"notice","outcome":"failed","message":"Synthetic update restored"}'
Poll-LauncherUpdates
if($script:notices.Count -ne 1 -or -not $script:notices[0][1]){throw 'Failure notice not shown once'}
if($script:started[-1] -ne 'settings'){throw 'Settings did not follow the notice'}
Set-TestTask 'settings' '{"state":"settings","automatic_check":true}'
Poll-LauncherUpdates
if($script:started[-1] -ne 'auto-check'){throw 'Automatic check did not start'}
$offer='{"state":"available","message":"Versie 0.1.0-beta.12 is beschikbaar.","current_version":"0.1.0-beta.11","offer":{"kind":"portable","version":"0.1.0-beta.12"}}'
Set-TestTask 'auto-check' $offer
Poll-LauncherUpdates
if($script:asked.Count -ne 1 -or $script:asked[0] -notlike '*0.1.0-beta.12*0.1.0-beta.11*'){throw 'Update question missing versions'}
if($script:started -contains 'download'){throw 'Download started after No'}
if($ui.UpdateMessage.Text -notlike '*Support*'){throw 'No hint after No'}
Set-TestTask 'auto-check' $offer
Poll-LauncherUpdates
if($script:asked.Count -ne 1){throw 'Asked twice in one session'}
$script:launcherUpdates.prompted=$false;$script:answer=$true
Set-TestTask 'auto-check' $offer
Poll-LauncherUpdates
if($script:started[-1] -ne 'download' -or -not $script:launcherUpdates.autoApply){throw 'Download after Yes missing'}
Set-TestTask 'download' '{"state":"downloaded","kind":"portable","version":"0.1.0-beta.12","receipt":"synthetic-only","message":"klaargezet"}'
Poll-LauncherUpdates
if(($script:applied -join ',') -ne '0.1.0-beta.12'){throw 'Self-update not started after consent'}
if($ui.InstallUpdate.Content -ne 'Nu bijwerken'){throw 'Portable button text'}
$script:launcherUpdates.autoApply=$false;$script:applied=@()
Set-TestTask 'download' '{"state":"downloaded","version":"0.1.0-beta.6","receipt":"synthetic-msi","message":"MSI"}'
Poll-LauncherUpdates
if($script:applied.Count -or $ui.InstallUpdate.Content -ne 'Update installeren'){throw 'MSI download must wait for the user'}
'Portable flow: OK; no network, installer or game executed'
'''

# The self-update start: refused while busy or without consent; otherwise one
# detached updater that waits for this launcher and its Launcher.cmd shell.
PORTABLE_START = HEADER + r'''
$script:launched=@();$script:answer=$false;$script:busy=$true
function New-LauncherProcess([string]$Executable,[string[]]$Arguments,[switch]$Detached){
    if(-not $Detached){throw 'The updater must run detached'}
    $script:launched+=,@($Executable,$Arguments);return @{}
}
function Confirm-LauncherUpdate([string]$Text){return $script:answer}
function Get-LauncherParentShell {return 4321}
$ui=@{}
Initialize-LauncherUpdates $window $ui $Fixture {return 'C:\synthetic\python.exe'} {return $script:busy}
$result=[pscustomobject]@{version='0.1.0-beta.12';receipt='C:\synthetic\download.json'}
Start-PortableLauncherUpdate $result
if($script:launched.Count){throw 'Started while a game was busy'}
$script:busy=$false
Start-PortableLauncherUpdate $result
if($script:launched.Count){throw 'Started without consent'}
$script:answer=$true
Start-PortableLauncherUpdate $result
if($script:launched.Count -ne 1){throw 'Updater not started once'}
$exe,$arguments=$script:launched[0]
$line=$arguments -join ' '
foreach($part in @('apply','--restart','--receipt C:\synthetic\download.json',"--wait $PID",'--wait 4321')){
    if($line -notlike "*$part*"){throw ('Missing updater argument: '+$part+' in '+$line)}
}
if($exe -ne 'C:\synthetic\python.exe'){throw 'Wrong runtime'}
'Portable start: OK; no updater, network or game executed'
'''


@unittest.skipUnless(os.name == 'nt', 'Windows WPF')
class UpdateUITests(unittest.TestCase):
    def test_updater_backend_and_controls_are_in_the_runtime_package(self):
        from tools.portable_launcher import app_files
        files = set(app_files(ROOT))
        self.assertTrue({'tools/launcher_updates.py', 'tools/launcher_updates.ps1'} <= files)
        self.assertFalse('tools/create_update_review.py' in files)

    def run_fixture(self, script: str, expected: str):
        runtime = shutil.which('pwsh')
        if not runtime:
            self.skipTest('PowerShell 7 unavailable')
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='update-ui-', dir=parent) as folder:
            fixture = Path(folder)
            (fixture / 'VERSION.txt').write_text('0.1.0-beta.5')
            source = fixture / 'update-ui.ps1'
            source.write_text(script, encoding='utf-8-sig')
            result = subprocess.run([runtime, '-NoProfile', '-STA', '-File', str(source),
                                     '-Root', str(ROOT), '-Fixture', str(fixture)],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn(expected, result.stdout)

    def test_update_controls_refuse_busy_or_changed_installer_without_launching(self):
        self.run_fixture(FIXTURE, 'Update controls: OK')

    def test_portable_update_asks_once_and_only_starts_after_consent(self):
        self.run_fixture(PORTABLE_FLOW, 'Portable flow: OK')

    def test_portable_self_update_start_is_detached_and_waits_for_launcher(self):
        self.run_fixture(PORTABLE_START, 'Portable start: OK')


if __name__ == '__main__':
    unittest.main()
