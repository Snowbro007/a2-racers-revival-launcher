using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace A2Revival.Windows {
    internal static class Launcher {
        [STAThread] static int Main(string[] args) {
            try {
                bool check = args.Length == 1 && args[0] == "--check";
                if (args.Length != 0 && !check) throw new ArgumentException("Onbekende startoptie.");
                string root = AppDomain.CurrentDomain.BaseDirectory;
                var info = NativeCommon.LauncherInfo(root, check);
                if (check) { info.RedirectStandardOutput = true; info.RedirectStandardError = true; }
                using (var process = Process.Start(info)) {
                    if (check) {
                        var output = process.StandardOutput.ReadToEndAsync(); var error = process.StandardError.ReadToEndAsync();
                        process.WaitForExit();
                        string log = NativeCommon.Within(root, "app/local/launcher/native-check.log");
                        Directory.CreateDirectory(Path.GetDirectoryName(log));
                        File.WriteAllText(log, output.Result + "\n" + error.Result, new UTF8Encoding(false));
                        return process.ExitCode;
                    }
                }
                return 0;
            } catch (Exception error) {
                MessageBox.Show(error.Message, "A2 Racers Revival", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1;
            }
        }
    }
}
