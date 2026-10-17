using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace A2Revival.Windows {
    internal static class NativeCommon {
        [StructLayout(LayoutKind.Sequential)] struct FileInfo {
            public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
            public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetFileInformationByHandle(SafeFileHandle handle, out FileInfo info);

        internal static void CheckPath(string path) {
            string current = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(current)) {
                if (File.Exists(current) || Directory.Exists(current)) {
                    if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("De map loopt via een koppeling. Kies een gewone lokale map.");
                    if (File.Exists(current)) using (var stream = File.Open(current, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
                        FileInfo info;
                        if (!GetFileInformationByHandle(stream.SafeFileHandle, out info) || info.Links != 1)
                            throw new IOException("Dit bestand is gekoppeld aan een andere locatie: " + current);
                    }
                }
                current = Path.GetDirectoryName(current);
            }
        }
        internal static string Within(string root, string relative) {
            if (String.IsNullOrEmpty(relative) || relative.Contains("\\") || relative.Contains(":")) throw new IOException("Ongeldige pakketnaam.");
            foreach (string part in relative.Split('/')) {
                string stem = part.Split('.')[0].ToUpperInvariant();
                if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" ") ||
                    part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                    stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" ||
                    System.Text.RegularExpressions.Regex.IsMatch(stem, "^(COM|LPT)[1-9]$")) throw new IOException("Onveilige pakketnaam.");
            }
            string fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string target = Path.GetFullPath(Path.Combine(fullRoot, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!target.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase)) throw new IOException("Pakketpad valt buiten de installatiemap.");
            CheckPath(target); return target;
        }
        internal static string Hash(Stream stream) {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
        internal static string Quote(string value) {
            var output = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) {
                if (c == '\\') { slashes++; continue; }
                output.Append('\\', c == '"' ? slashes * 2 + 1 : slashes); output.Append(c); slashes = 0;
            }
            return output.Append('\\', slashes * 2).Append('"').ToString();
        }
        internal static ProcessStartInfo LauncherInfo(string root, bool check) {
            CheckPath(root);
            string script = Within(root, "app/tools/Show-A2Launcher.ps1");
            if (!File.Exists(script) || !File.Exists(Within(root, "app/release-manifest.json")))
                throw new IOException("De launcher is niet compleet. Installeer A2 Racers Revival opnieuw; je lokale instellingen blijven bewaard.");
            string system = Environment.GetFolderPath(Environment.SpecialFolder.System);
            var info = new ProcessStartInfo(Path.Combine(system, "WindowsPowerShell\\v1.0\\powershell.exe"));
            info.Arguments = "-NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File " + Quote(script) + (check ? " -CheckOnly" : "");
            info.WorkingDirectory = Path.Combine(root, "app"); info.UseShellExecute = false; info.CreateNoWindow = true;
            // A PowerShell 7 parent may export an incompatible module path. This is
            // process-local runtime selection, never a Windows security setting.
            info.EnvironmentVariables["PSModulePath"] = Path.Combine(system, "WindowsPowerShell\\v1.0\\Modules");
            return info;
        }
    }
}
