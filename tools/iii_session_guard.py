"""Owned-process containment for III probes and the restored Tour 1 play route.

This module has no command-line game-start bypass. It uses only stdlib ctypes;
it creates no helper executable and never changes the shared cursor or focus.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import subprocess
import time


@dataclass(frozen=True)
class Observation:
    active_processes: int
    own_foreground: bool = False
    cursor_confined: bool = False
    responsive: bool | None = None
    emergency: bool = False


class GuardPolicy:
    """Conservative test policy: losing focus ends the whole owned session."""

    def __init__(self, started: float, seconds: float):
        if not math.isfinite(seconds) or not 2 <= seconds <= 30:
            raise ValueError('Een bewaakte proef duurt minimaal 2 en maximaal 30 seconden.')
        self.deadline = started + seconds
        self.had_focus = False
        self.unresponsive_since = None
        self.hang_seconds = 1.0

    def stop_reason(self, observation: Observation, now: float) -> str | None:
        if observation.active_processes < 0:
            raise ValueError('Ongeldige proceswaarneming.')
        if observation.active_processes == 0:
            return 'exited'
        if observation.emergency:
            return 'emergency_hotkey'
        if now >= self.deadline:
            return 'time_limit'
        if observation.cursor_confined:
            return 'cursor_confined'
        if self.had_focus and not observation.own_foreground:
            return 'focus_lost'
        self.had_focus |= observation.own_foreground
        if observation.responsive is False:
            if self.unresponsive_since is None:
                self.unresponsive_since = now
            if now - self.unresponsive_since >= self.hang_seconds:
                return 'unresponsive'
        else:
            self.unresponsive_since = None
        return None


class PlayPolicy(GuardPolicy):
    """Allow normal focus switches; stop if confinement persists outside the game."""
    def __init__(self, started, seconds):
        if not math.isfinite(seconds) or not 2 <= seconds <= 14400:
            raise ValueError('Een bewaakte speelsessie duurt maximaal vier uur.')
        super().__init__(started, 30)
        self.deadline = started + seconds
        self.hang_seconds = 10.0  # Loading can temporarily stop the window message pump.

    def stop_reason(self, observation, now):
        if observation.own_foreground:
            observation = replace(observation, cursor_confined=False)
        else:
            self.had_focus = False
        return super().stop_reason(observation, now)


def supervise(argv: list[str], cwd: Path, environment: dict[str, str], *,
              seconds: float = 10, backend_factory=None,
              clock=time.monotonic, sleep=time.sleep, policy_factory=GuardPolicy) -> dict:
    """Bounded test session; close kills descendants even after the parent exits.

    The adapter must implement preflight/start_suspended/assign/resume/observe/
    close. Failed assignment never permits the suspended process to run.
    """
    started = clock()
    policy = policy_factory(started, seconds)
    if not argv or any(not isinstance(value, str) or '\0' in value for value in argv):
        raise ValueError('Ongeldige procesargumenten.')
    if not Path(argv[0]).is_absolute() or not Path(cwd).is_absolute():
        raise ValueError('Gebruik expliciete absolute proces- en werkpaden.')
    backend = (backend_factory or WindowsJobBackend)()
    reason = None
    try:
        backend.preflight()
        backend.start_suspended(argv, cwd, environment)
        backend.assign()
        backend.resume()
        while reason is None:
            reason = policy.stop_reason(backend.observe(), clock())
            if reason is None:
                sleep(0.05)
    finally:
        # close must also terminate a suspended child after a failed assignment.
        # Cleanup errors propagate; they must not be reported as a successful stop.
        backend.close()
    return {'reason': reason, 'elapsed_seconds': round(clock() - started, 3),
            'cleanup_verified': True, 'game_compatibility_verified': False}


def supervise_play(argv, cwd, environment):
    return supervise(argv, cwd, environment, seconds=14400, policy_factory=PlayPolicy)


class WindowsJobBackend:
    """One private non-inheritable job, assigned before any game code executes."""

    HOTKEY_ID = 0x4133

    def __init__(self):
        if os.name != 'nt':
            raise OSError('De procesbewaker vereist Windows.')
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.user = c.WinDLL('user32', use_last_error=True)
        uptr = c.c_size_t

        class BasicLimits(c.Structure):
            _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64),
                        ('flags', w.DWORD), ('min_ws', uptr), ('max_ws', uptr),
                        ('active_limit', w.DWORD), ('affinity', uptr),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]

        class IoCounters(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

        class ExtendedLimits(c.Structure):
            _fields_ = [('basic', BasicLimits), ('io', IoCounters),
                        ('process_memory', uptr), ('job_memory', uptr),
                        ('peak_process_memory', uptr), ('peak_job_memory', uptr)]

        class Accounting(c.Structure):
            _fields_ = [(name, c.c_int64) for name in
                        ('user_time', 'kernel_time', 'period_user_time', 'period_kernel_time')]
            _fields_ += [(name, w.DWORD) for name in
                         ('page_faults', 'total_processes', 'active_processes', 'terminated_processes')]

        class Startup(c.Structure):
            _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR),
                        ('title', w.LPWSTR)]
            _fields_ += [(name, w.DWORD) for name in
                         ('x', 'y', 'width', 'height', 'x_chars', 'y_chars', 'fill', 'flags')]
            _fields_ += [('show', w.WORD), ('reserved_size', w.WORD),
                         ('reserved_bytes', c.POINTER(c.c_ubyte)), ('stdin', w.HANDLE),
                         ('stdout', w.HANDLE), ('stderr', w.HANDLE)]

        class ProcessInfo(c.Structure):
            _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE),
                        ('pid', w.DWORD), ('tid', w.DWORD)]

        class Message(c.Structure):
            _fields_ = [('hwnd', w.HWND), ('message', w.UINT), ('wparam', uptr),
                        ('lparam', c.c_ssize_t), ('time', w.DWORD),
                        ('point', w.POINT), ('private', w.DWORD)]

        class ProcessList(c.Structure):
            _fields_ = [('assigned', w.DWORD), ('listed', w.DWORD), ('pids', uptr * 128)]

        self.Limits, self.Accounting = ExtendedLimits, Accounting
        self.Startup, self.ProcessInfo, self.Message = Startup, ProcessInfo, Message
        self.ProcessList = ProcessList
        signatures = {
            'CreateJobObjectW': (w.HANDLE, [c.c_void_p, w.LPCWSTR]),
            'SetInformationJobObject': (w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]),
            'QueryInformationJobObject': (w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]),
            'CreateProcessW': (w.BOOL, [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p,
                                      w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR,
                                      c.POINTER(Startup), c.POINTER(ProcessInfo)]),
            'AssignProcessToJobObject': (w.BOOL, [w.HANDLE, w.HANDLE]),
            'IsProcessInJob': (w.BOOL, [w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)]),
            'ResumeThread': (w.DWORD, [w.HANDLE]),
            'TerminateJobObject': (w.BOOL, [w.HANDLE, w.UINT]),
            'TerminateProcess': (w.BOOL, [w.HANDLE, w.UINT]),
            'OpenProcess': (w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
            'CloseHandle': (w.BOOL, [w.HANDLE]),
            'WaitForSingleObject': (w.DWORD, [w.HANDLE, w.DWORD]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.kernel, name)
            function.restype, function.argtypes = result, arguments
        signatures = {
            'RegisterHotKey': (w.BOOL, [w.HWND, c.c_int, w.UINT, w.UINT]),
            'UnregisterHotKey': (w.BOOL, [w.HWND, c.c_int]),
            'PeekMessageW': (w.BOOL, [c.POINTER(Message), w.HWND, w.UINT, w.UINT, w.UINT]),
            'GetForegroundWindow': (w.HWND, []),
            'GetWindowThreadProcessId': (w.DWORD, [w.HWND, c.POINTER(w.DWORD)]),
            'GetClipCursor': (w.BOOL, [c.POINTER(w.RECT)]),
            'GetSystemMetrics': (c.c_int, [c.c_int]),
            'SendMessageTimeoutW': (c.c_ssize_t, [w.HWND, w.UINT, uptr, c.c_ssize_t,
                                                w.UINT, w.UINT, c.POINTER(uptr)]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.user, name)
            function.restype, function.argtypes = result, arguments
        self.job = None
        self.process = ProcessInfo()
        self.assigned = False
        self.hotkey = False
        self.closed = False
        self.members = {}
        self.lease = None

    def require(self, success, action):
        if not success:
            raise OSError(self.c.get_last_error(), action)

    def confined(self):
        rectangle = self.w.RECT()
        self.require(self.user.GetClipCursor(self.c.byref(rectangle)), 'GetClipCursor mislukt.')
        x, y, width, height = (self.user.GetSystemMetrics(index) for index in (76, 77, 78, 79))
        if width <= 0 or height <= 0:
            raise OSError('Geen geldig bureaublad voor de muiscontrole.')
        return (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom) != (x, y, x + width, y + height)

    def preflight(self):
        if self.confined():
            raise OSError('De muis is al begrensd; er wordt geen proef gestart.')
        # Thread message queue; no low-level hook and no keyboard monitoring.
        message = self.Message()
        self.user.PeekMessageW(self.c.byref(message), None, 0, 0, 0)
        self.require(self.user.RegisterHotKey(None, self.HOTKEY_ID, 0x4006, 0x77),
                     'Noodstop Ctrl+Shift+F8 is niet beschikbaar; start geweigerd.')
        self.hotkey = True
        self.job = self.kernel.CreateJobObjectW(None, None)
        self.require(self.job, 'Privé-procesgroep maken mislukt.')
        limits = self.Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway.
        self.require(self.kernel.SetInformationJobObject(self.job, 9, self.c.byref(limits), self.c.sizeof(limits)),
                     'Procesgroep beveiligen mislukt.')
        from tools.iii_guard_lease import Lease
        self.lease = Lease(self.job)
        self.lease.start()

    def start_suspended(self, argv, cwd, environment):
        entries = []
        seen = set()
        for name, value in sorted(environment.items(), key=lambda pair: pair[0].casefold()):
            if (not isinstance(name, str) or not name or '=' in name or '\0' in name
                    or not isinstance(value, str) or '\0' in value or name.casefold() in seen):
                raise ValueError('Ongeldige of dubbele procesomgeving.')
            seen.add(name.casefold())
            entries.append(name + '=' + value)
        block = self.c.create_unicode_buffer('\0'.join(entries) + '\0\0')
        command = self.c.create_unicode_buffer(subprocess.list2cmdline(argv))
        startup = self.Startup()
        startup.cb = self.c.sizeof(startup)
        # CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW.
        # Explicit executable + no handle inheritance; never invoke a shell.
        self.require(self.kernel.CreateProcessW(argv[0], command, None, None, False,
                     0x08000404, block, str(cwd), self.c.byref(startup), self.c.byref(self.process)),
                     'Geschorste proefstart mislukt.')

    def assign(self):
        self.require(self.kernel.AssignProcessToJobObject(self.job, self.process.process),
                     'Proef kon niet vóór uitvoering worden afgeschermd.')
        self.assigned = True

    def resume(self):
        if not self.assigned:
            raise OSError('Een niet-afgeschermd proces wordt nooit hervat.')
        self.require(self.kernel.ResumeThread(self.process.thread) == 1,
                     'Proef hervatten mislukt.')

    def active_count(self):
        accounting = self.Accounting()
        self.require(self.kernel.QueryInformationJobObject(self.job, 1, self.c.byref(accounting),
                     self.c.sizeof(accounting), None), 'Procesgroep controleren mislukt.')
        return accounting.active_processes

    def own_window(self, hwnd):
        if not hwnd:
            return False
        pid = self.w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, self.c.byref(pid))
        if not pid.value:
            return False
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            # A vanished or inaccessible foreground window is never assumed owned.
            return False
        try:
            belongs = self.w.BOOL()
            self.require(self.kernel.IsProcessInJob(handle, self.job, self.c.byref(belongs)),
                         'Venstereigenaar controleren mislukt.')
            return bool(belongs.value)
        finally:
            self.require(self.kernel.CloseHandle(handle), 'Vensterproceshandle sluiten mislukt.')

    def track_members(self):
        listing = self.ProcessList()
        self.require(self.kernel.QueryInformationJobObject(self.job, 3, self.c.byref(listing),
                     self.c.sizeof(listing), None), 'Eigen proceslijst controleren mislukt.')
        if listing.assigned > 128 or listing.listed > 128:
            raise OSError('Onverwacht grote proefprocesketen.')
        for pid in listing.pids[:listing.listed]:
            if pid in self.members or pid == self.process.pid:
                continue
            handle = self.kernel.OpenProcess(0x00101000, False, pid)  # SYNCHRONIZE + query.
            if not handle:
                if self.c.get_last_error() == 87:  # Process already vanished.
                    continue
                raise OSError(self.c.get_last_error(), 'Eigen proceshandle openen mislukt.')
            belongs = self.w.BOOL()
            if not self.kernel.IsProcessInJob(handle, self.job, self.c.byref(belongs)):
                self.kernel.CloseHandle(handle)
                raise OSError('Lidmaatschap eigen procesgroep controleren mislukt.')
            if belongs.value:
                self.members[pid] = handle
            else:
                self.require(self.kernel.CloseHandle(handle), 'Niet-eigen proceshandle sluiten mislukt.')

    def observe(self):
        if self.lease is None:
            raise OSError('Onafhankelijke bewaker ontbreekt.')
        self.lease.pulse()
        self.track_members()
        active = self.active_count()
        emergency = False
        message = self.Message()
        # Only our own hotkey queue; bounded even if messages keep arriving.
        for _ in range(16):
            if not self.user.PeekMessageW(self.c.byref(message), None, 0x0312, 0x0312, 1):
                break
            emergency |= message.wparam == self.HOTKEY_ID
        hwnd = self.user.GetForegroundWindow()
        own = self.own_window(hwnd)
        responsive = None
        if own:
            result = self.c.c_size_t()
            # WM_NULL, SMTO_BLOCK | SMTO_ABORTIFHUNG, bounded to 100 ms.
            responsive = bool(self.user.SendMessageTimeoutW(hwnd, 0, 0, 0, 3, 100, self.c.byref(result)))
        return Observation(active, own, self.confined(), responsive, emergency)

    def close(self):
        if self.closed:
            return
        self.closed = True
        failures = []
        try:
            if self.process.process and not self.assigned:
                if not self.kernel.TerminateProcess(self.process.process, 1):
                    failures.append('Geschorst proces beëindigen mislukt.')
                elif self.kernel.WaitForSingleObject(self.process.process, 2000) != 0:
                    failures.append('Geschorst proces is niet tijdig afgesloten.')
            if self.job:
                if self.assigned:
                    self.track_members()
                if not self.kernel.TerminateJobObject(self.job, 1):
                    failures.append('Eigen procesgroep beëindigen mislukt.')
                else:
                    deadline = time.monotonic() + 2
                    while self.active_count():
                        if time.monotonic() >= deadline:
                            failures.append('Eigen procesgroep is niet tijdig leeg.')
                            break
                        time.sleep(0.02)
                    # Accounting can reach zero before Windows has signalled
                    # every process handle and released its working directory.
                    for handle in (self.process.process, *self.members.values()):
                        remaining = max(0, int((deadline - time.monotonic()) * 1000))
                        if handle and self.kernel.WaitForSingleObject(handle, remaining) != 0:
                            failures.append('Eigen proces is niet tijdig volledig afgesloten.')
        finally:
            # Closing the last private job handle is a second termination path.
            for handle in (self.process.thread, self.process.process, *self.members.values(), self.job):
                if handle and not self.kernel.CloseHandle(handle):
                    failures.append('Eigen proceshandle sluiten mislukt.')
            if self.hotkey and not self.user.UnregisterHotKey(None, self.HOTKEY_ID):
                failures.append('Noodstopregistratie vrijgeven mislukt.')
            if self.lease is not None:
                self.lease.close()
        if failures:
            raise OSError(' '.join(failures))
