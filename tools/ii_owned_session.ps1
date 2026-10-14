# Own child handles only. Loading/compiling this file starts no hook or game.
# Normal close is tried first. Alt+F4 explicitly authorizes bounded termination
# of this session's child if native shutdown hangs. No process-name killing.
function Import-IIOwnedSession {
    if ('AtlasIIOwnedSession' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;

public sealed class AtlasIIOwnedSession : IDisposable {
    private IntPtr job, hook;
    private Thread thread;
    private readonly ManualResetEventSlim ready = new ManualResetEventSlim(false);
    private Native.HookProc callback;
    private volatile int targetPid;
    private volatile bool stopping;
    private int requested, disposed;
    private Exception hookError;
    private uint hookThread;
    public bool StopRequested { get { return Volatile.Read(ref requested) != 0; } }
    public static bool IsOwnedAltF4(int code, int message, uint key, uint flags, int foregroundPid, int ownedPid) {
        return code >= 0 && (message == 0x100 || message == 0x104) && key == 0x73 &&
            (flags & 0x20) != 0 && (flags & 0x10) == 0 && ownedPid > 0 && foregroundPid == ownedPid;
    }
    public static bool ShouldStartNextStage(bool requested, int menuExit) { return !requested && menuExit == 40; }
    private AtlasIIOwnedSession() { }
    public static AtlasIIOwnedSession Begin() {
        var own = new AtlasIIOwnedSession();
        try {
            own.job = Native.CreateJobObjectW(IntPtr.Zero, null);
            if (own.job == IntPtr.Zero) throw new Win32Exception();
            var limits = new Native.EXTENDED_LIMITS();
            limits.Basic.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (!Native.SetInformationJobObject(own.job, 9, ref limits, (uint)Marshal.SizeOf(limits))) throw new Win32Exception();
            own.callback = own.Keyboard;
            own.thread = new Thread(own.Listen) { IsBackground = true, Name = "II owned Alt-F4" };
            own.thread.Start();
            if (!own.ready.Wait(3000)) throw new TimeoutException("Alt+F4 hook kon niet starten.");
            if (own.hookError != null) throw new InvalidOperationException("Alt+F4 hook kon niet starten.", own.hookError);
            return own;
        } catch { own.Dispose(); throw; }
    }
    // The host passes only Process objects it just started with UseShellExecute=false.
    // Handles remain owned; no PID re-open, process listing, or name matching.
    public void Track(Process child, bool game) {
        if (child == null || child.StartInfo.UseShellExecute || disposed != 0 || job == IntPtr.Zero)
            throw new InvalidOperationException("Geen eigen gestart childproces.");
        if (!child.HasExited && !Native.AssignProcessToJobObject(job, child.Handle)) {
            if (!child.HasExited) throw new Win32Exception(Marshal.GetLastWin32Error(), "Eigen child kon niet aan afsluitjob worden gekoppeld.");
        }
        if (game && !child.HasExited) targetPid = child.Id;
    }
    public void ClearGame() { targetPid = 0; }
    // Read-only diagnostic, exclusively through the session's existing child handle.
    // Called only by the pinned II distance trial. No global process lookup or writes.
    public static bool IsVisibleChunkDiagnosticValue(int count, int maximum) {
        return (maximum == 50 || maximum == 60) && count >= 10 && count <= maximum;
    }
    public int? ReadVisibleChunks(Process child, int maximum = 50) {
        try {
            if (child == null || disposed != 0 || targetPid <= 0 || child.Id != targetPid || child.HasExited) return null;
            long imageBase = child.MainModule.BaseAddress.ToInt64();
            byte[] value = new byte[4]; UIntPtr bytesRead;
            if (!Native.ReadProcessMemory(child.Handle, new IntPtr(imageBase + 0xD9A8C), value, new UIntPtr(4), out bytesRead) || bytesRead.ToUInt64() != 4) return null;
            int count = BitConverter.ToInt32(value,0);
            return IsVisibleChunkDiagnosticValue(count, maximum) ? count : (int?)null;
        } catch (InvalidOperationException) { return null; }
          catch (Win32Exception) { return null; }
    }
    private IntPtr Keyboard(int code, IntPtr message, IntPtr data) {
        try {
            if (code >= 0 && data != IntPtr.Zero) {
                var input = Marshal.PtrToStructure<Native.KEYBOARD>(data);
                uint foreground;
                Native.GetWindowThreadProcessId(Native.GetForegroundWindow(), out foreground);
                if (IsOwnedAltF4(code, message.ToInt32(), input.Key, input.Flags, (int)foreground, targetPid)) {
                    Interlocked.Exchange(ref requested, 1);
                    return new IntPtr(1); // suppress native dialogs/restart for this exact game
                }
            }
        } catch {
            // The close contract fails closed for our session, never for other apps.
            Interlocked.Exchange(ref requested, 1);
        }
        return Native.CallNextHookEx(hook, code, message, data);
    }
    private void Listen() {
        try {
            hookThread = Native.GetCurrentThreadId();
            Native.MESSAGE unused;
            Native.PeekMessageW(out unused, IntPtr.Zero, 0, 0, 0); // create own queue before ready
            hook = Native.SetWindowsHookExW(13, callback, Native.GetModuleHandleW(null), 0);
            if (hook == IntPtr.Zero) throw new Win32Exception();
            ready.Set();
            while (!stopping) {
                Native.MESSAGE message;
                int result = Native.GetMessageW(out message, IntPtr.Zero, 0, 0);
                if (result == 0) break;
                if (result < 0) throw new Win32Exception();
                Native.TranslateMessage(ref message);
                Native.DispatchMessageW(ref message);
            }
        } catch (Exception error) { hookError = error; Interlocked.Exchange(ref requested, 1); }
        finally {
            if (hook != IntPtr.Zero) { Native.UnhookWindowsHookEx(hook); hook = IntPtr.Zero; }
            ready.Set();
        }
    }
    public void Dispose() {
        if (Interlocked.Exchange(ref disposed, 1) != 0) return;
        targetPid = 0;
        stopping = true;
        if (hookThread != 0) Native.PostThreadMessageW(hookThread, 0x12, IntPtr.Zero, IntPtr.Zero);
        if (thread != null && thread != Thread.CurrentThread) thread.Join(3000);
        // This unnamed, non-inherited handle contains only this host's children.
        // Also closes them if the console/host is terminated by Windows.
        if (job != IntPtr.Zero) { Native.CloseHandle(job); job = IntPtr.Zero; }
        GC.KeepAlive(callback);
    }
    private static class Native {
        internal delegate IntPtr HookProc(int code, IntPtr message, IntPtr data);
        [StructLayout(LayoutKind.Sequential)] internal struct BASIC_LIMITS {
            internal long PerProcess, PerJob; internal uint LimitFlags;
            internal UIntPtr MinimumWorkingSet, MaximumWorkingSet;
            internal uint ActiveProcessLimit; internal UIntPtr Affinity;
            internal uint PriorityClass, SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct IO_COUNTERS {
            internal ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct EXTENDED_LIMITS {
            internal BASIC_LIMITS Basic; internal IO_COUNTERS IO;
            internal UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct KEYBOARD {
            internal uint Key, Scan, Flags, Time; internal UIntPtr Extra;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct MESSAGE {
            internal IntPtr Window; internal uint Message; internal UIntPtr WParam;
            internal IntPtr LParam; internal uint Time; internal int X, Y; internal uint Private;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] internal static extern IntPtr CreateJobObjectW(IntPtr attrs, string name);
        [DllImport("kernel32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool SetInformationJobObject(IntPtr job, int kind, ref EXTENDED_LIMITS limits, uint size);
        [DllImport("kernel32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] buffer, UIntPtr size, out UIntPtr read);
        [DllImport("kernel32.dll")] internal static extern uint GetCurrentThreadId();
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] internal static extern IntPtr GetModuleHandleW(string name);
        [DllImport("user32.dll")] internal static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
        [DllImport("user32.dll", SetLastError=true)] internal static extern IntPtr SetWindowsHookExW(int id, HookProc proc, IntPtr module, uint thread);
        [DllImport("user32.dll")] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool UnhookWindowsHookEx(IntPtr hook);
        [DllImport("user32.dll")] internal static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr message, IntPtr data);
        [DllImport("user32.dll", SetLastError=true)] internal static extern int GetMessageW(out MESSAGE message, IntPtr window, uint min, uint max);
        [DllImport("user32.dll")] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool PeekMessageW(out MESSAGE message, IntPtr window, uint min, uint max, uint remove);
        [DllImport("user32.dll")] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool TranslateMessage(ref MESSAGE message);
        [DllImport("user32.dll")] internal static extern IntPtr DispatchMessageW(ref MESSAGE message);
        [DllImport("user32.dll")] [return:MarshalAs(UnmanagedType.Bool)] internal static extern bool PostThreadMessageW(uint thread, uint message, IntPtr wParam, IntPtr lParam);
    }
}
'@
}
