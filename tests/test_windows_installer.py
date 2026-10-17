"""Native entrypoint checks using synthetic files; never install or start a game."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.build_windows_release import compiler, compile_cs

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
using System;
using System.IO;
using A2Revival.Windows;
class Harness {
    static void Require(bool test, string reason) { if (!test) throw new Exception(reason); }
    static bool Fails(Action action) { try { action(); return false; } catch (IOException) { return true; } }
    static int Main(string[] args) {
        string root = Path.Combine(args[0], "installed é test"); int cases = 0;
        try {
            foreach (string name in new[] {"../escape", "/absolute", "app/../../escape", "app/evil:ads", "app/CON.txt", "app/name. ", "app/name.", "app/\\escape", "app//empty"}) {
                Require(Fails(() => NativeCommon.Within(root, name)), "Unsafe path accepted: " + name); cases++;
            }
            Require(Fails(() => NativeCommon.LauncherInfo(root, false)), "Incomplete install accepted"); cases++;
            Directory.CreateDirectory(Path.Combine(root,"app/tools"));
            File.WriteAllText(Path.Combine(root,"app/tools/Show-A2Launcher.ps1"), "synthetic fixture only");
            File.WriteAllText(Path.Combine(root,"app/release-manifest.json"), "{}");
            var info = NativeCommon.LauncherInfo(root, false);
            Require(!info.UseShellExecute && info.CreateNoWindow, "Shell/console enabled");
            Require(info.WorkingDirectory == Path.Combine(root,"app"), "Wrong working directory");
            Require(info.Arguments.Contains("installed é test") && info.Arguments.EndsWith("Show-A2Launcher.ps1\""), "Bad quoted script path");
            Require(info.FileName.EndsWith("WindowsPowerShell\\v1.0\\powershell.exe", StringComparison.OrdinalIgnoreCase), "Wrong runtime");
            Require(info.EnvironmentVariables["PSModulePath"].EndsWith("WindowsPowerShell\\v1.0\\Modules"), "Inherited incompatible modules"); cases++;
            Require(NativeCommon.LauncherInfo(root, true).Arguments.EndsWith(" -CheckOnly"), "Check flag missing"); cases++;
            Require(NativeCommon.Quote("a\"b\\") == "\"a\\\"b\\\\\"", "Bad Windows quoting"); cases++;
            Console.WriteLine("passed=" + cases); return 0;
        } catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
'''


@unittest.skip('Native helper disabled: Bitdefender blocked Harness.exe as Gen:Variant.MSILHeracles.213981; review required')
class WindowsLauncherTests(unittest.TestCase):
    def test_native_paths_runtime_selection_and_quoted_launch_arguments(self):
        if not compiler().is_file(): self.skipTest('Windows .NET compiler unavailable')
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='native-launcher-', dir=parent, ignore_cleanup_errors=True) as directory:
            folder = Path(directory)
            harness = folder / 'Harness.cs'
            harness.write_text(HARNESS, encoding='utf-8')
            executable = folder / 'Harness.exe'
            compile_cs([ROOT / 'tools/windows/NativeCommon.cs', harness], executable, window=False)
            try:
                result = subprocess.run([str(executable), str(folder)], capture_output=True, text=True, timeout=60)
            except PermissionError as error:
                if error.winerror != 5: raise
                self.skipTest('Windows denied executing the synthetic helper (WinError 5); compilation succeeded')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('passed=13', result.stdout)
