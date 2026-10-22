"""Private inherited-handle watchdog; no executable build or PID-based kills."""
from __future__ import annotations
import argparse
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import os
import subprocess
import sys
import time


def api():
    if os.name != 'nt':
        raise OSError('De bewaker vereist Windows.')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateEventW': (w.HANDLE, [c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]),
        'GetCurrentProcess': (w.HANDLE, []),
        'DuplicateHandle': (w.BOOL, [w.HANDLE, w.HANDLE, w.HANDLE, c.POINTER(w.HANDLE),
                                   w.DWORD, w.BOOL, w.DWORD]),
        'SetEvent': (w.BOOL, [w.HANDLE]),
        'WaitForSingleObject': (w.DWORD, [w.HANDLE, w.DWORD]),
        'WaitForMultipleObjects': (w.DWORD, [w.DWORD, c.POINTER(w.HANDLE), w.BOOL, w.DWORD]),
        'TerminateJobObject': (w.BOOL, [w.HANDLE, w.UINT]),
        'CloseHandle': (w.BOOL, [w.HANDLE]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(kernel, name)
        function.restype, function.argtypes = result, arguments
    return kernel


def require(success, message):
    if not success:
        raise OSError(c.get_last_error(), message)


class Lease:
    """A second existing Python process holds only four explicit private handles."""
    def __init__(self, job):
        self.kernel = api()
        self.job = job
        self.events = []
        self.process = None

    def start(self):
        duplicates = []
        try:
            for _ in range(3):
                event = self.kernel.CreateEventW(None, False, False, None)
                require(event, 'Bewakerevent maken mislukt.')
                self.events.append(event)
            current = self.kernel.GetCurrentProcess()
            for handle in [self.job, *self.events]:
                duplicate = w.HANDLE()
                require(self.kernel.DuplicateHandle(current, handle, current, c.byref(duplicate), 0, True, 2),
                        'Privé-bewakerhandle dupliceren mislukt.')
                duplicates.append(duplicate.value)
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {'handle_list': duplicates}
            self.process = subprocess.Popen(
                [sys.executable, '-B', str(Path(__file__).resolve()), *map(str, duplicates)],
                startupinfo=startup, close_fds=True, creationflags=0x08000000,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=Path(__file__).resolve().parents[1])
            require(self.kernel.WaitForSingleObject(self.events[2], 3000) == 0,
                    'De onafhankelijke bewaker is niet gereed; start geweigerd.')
        except BaseException:
            self.close()
            raise
        finally:
            for handle in duplicates:
                self.kernel.CloseHandle(handle)

    def pulse(self):
        if self.process is None or self.process.poll() is not None:
            raise OSError('De onafhankelijke bewaker stopte; de eigen game wordt afgesloten.')
        require(self.kernel.SetEvent(self.events[0]), 'Hartslag van de bewaker mislukt.')

    def close(self):
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    if len(self.events) > 1:
                        self.kernel.SetEvent(self.events[1])
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.terminate()  # This exact owned watchdog handle only.
                        self.process.wait(timeout=3)
        finally:
            for handle in self.events:
                self.kernel.CloseHandle(handle)
            self.events.clear()


def watch(job, beat, stop, ready):
    kernel = api()
    try:
        require(kernel.SetEvent(ready), 'Bewaker kon gereedmelding niet geven.')
        # Stop has priority when stop and beat are both signalled.
        events = (w.HANDLE * 2)(stop, beat)
        deadline = time.monotonic() + 14430  # Independent upper bound, four hours + cleanup.
        while time.monotonic() < deadline:
            result = kernel.WaitForMultipleObjects(2, events, False, 2000)
            if result == 0:
                return 0
            if result != 1:
                break
        require(kernel.TerminateJobObject(job, 1), 'Eigen job beëindigen mislukt.')
        return 9
    finally:
        for handle in (job, beat, stop, ready):
            kernel.CloseHandle(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('job', 'beat', 'stop', 'ready'):
        parser.add_argument(name, type=int)
    values = parser.parse_args()
    raise SystemExit(watch(values.job, values.beat, values.stop, values.ready))
