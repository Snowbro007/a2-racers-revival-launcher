"""Bounded diagnostics for this launcher session's held Windows job handles."""
from __future__ import annotations
from pathlib import PureWindowsPath
import time
from tools.iii_session_guard import WindowsJobBackend

class MenuDiagnostics:
    """Bounded, in-memory records; no native APIs or report writes here."""

    MAX_EVENTS = 256
    MAX_ERRORS = 32
    SAMPLE_SECONDS = 0.25

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.timeline = []
        self.errors = []
        self.dropped_events = 0
        self.dropped_errors = 0
        self.last_state = None
        self.last_sample = None
        self.before_cleanup = None

    def error(self, stage, error):
        row = {"stage": stage, "error_type": type(error).__name__, "error": str(error)[:500]}
        if len(self.errors) < self.MAX_ERRORS:
            self.errors.append(row)
        else:
            self.dropped_errors += 1

    def observe(self, observation, processes):
        now = self.clock()
        state = (observation.active_processes, observation.own_foreground,
                 observation.cursor_confined, observation.responsive, observation.emergency)
        if (state == self.last_state and self.last_sample is not None
                and now - self.last_sample < self.SAMPLE_SECONDS):
            return
        own = processes() if callable(processes) else processes
        row = {"elapsed_seconds": round(now - self.started, 4),
               "active_processes": observation.active_processes,
               "own_foreground": observation.own_foreground,
               "cursor_confined": observation.cursor_confined,
               "responsive": observation.responsive, "emergency": observation.emergency,
               "own_processes": own}
        if len(self.timeline) >= self.MAX_EVENTS:
            self.timeline.pop(0)
            self.dropped_events += 1
        self.timeline.append(row)
        self.last_state, self.last_sample = state, now

    def snapshot(self):
        return {"schema": 1, "scope": "own-job-only", "maximum_events": self.MAX_EVENTS,
                "sample_seconds": self.SAMPLE_SECONDS, "timeline": list(self.timeline),
                "dropped_events": self.dropped_events, "errors": list(self.errors),
                "dropped_errors": self.dropped_errors,
                "processes_before_forced_cleanup": self.before_cleanup,
                "cleanup_termination_code": 1,
                "before_cleanup_is_not_cleanup_exit_code": True}


class DiagnosticMenuBackend(WindowsJobBackend):
    """Observe only held, verified own-job handles; cleanup remains in the base."""

    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        self.image_names = {}
        super().__init__()
        self.kernel.GetExitCodeProcess.restype = self.w.BOOL
        self.kernel.GetExitCodeProcess.argtypes = [self.w.HANDLE, self.c.POINTER(self.w.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = self.w.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = [self.w.HANDLE, self.w.DWORD,
                                                          self.w.LPWSTR, self.c.POINTER(self.w.DWORD)]

    def own_processes(self, *, exit_codes=False):
        if not self.assigned or not self.job:
            return []
        handles = dict(self.members)
        if self.process.process:
            handles[int(self.process.pid)] = self.process.process
        rows = []
        for pid, handle in sorted(handles.items()):
            belongs = self.w.BOOL()
            if not self.kernel.IsProcessInJob(handle, self.job, self.c.byref(belongs)):
                self.diagnostics.error("verify-own-handle", OSError(self.c.get_last_error(), "Eigen jobhandle niet verifieerbaar."))
                continue
            if not belongs.value:
                self.diagnostics.error("verify-own-handle", ValueError("Vastgehouden handle is geen bevestigd eigen joblid."))
                continue
            row = {"pid": int(pid), "image_basename": self.image_names.get(pid)}
            if pid not in self.image_names:
                buffer = self.c.create_unicode_buffer(32768)
                length = self.w.DWORD(len(buffer))
                if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, self.c.byref(length)):
                    row["image_basename"] = PureWindowsPath(buffer.value).name
                    self.image_names[pid] = row["image_basename"]
                else:
                    self.diagnostics.error("own-image-basename", OSError(self.c.get_last_error(), "Eigen procesnaam niet uitleesbaar."))
            if exit_codes:
                row.update(exit_code=None, state="unknown")
                wait = self.kernel.WaitForSingleObject(handle, 0)
                if wait == 258:
                    # 259 is the Windows STILL_ACTIVE marker, never a crash code.
                    # Do not race a later exit-code read against this live sample.
                    row.update(state="still_active", still_active_marker=259)
                elif wait == 0:
                    code = self.w.DWORD()
                    if self.kernel.GetExitCodeProcess(handle, self.c.byref(code)):
                        row.update(exit_code=int(code.value), state="exited")
                    else:
                        self.diagnostics.error("own-exit-code", OSError(self.c.get_last_error(), "Eigen exitcode niet uitleesbaar."))
                else:
                    self.diagnostics.error("own-exit-status", OSError(self.c.get_last_error(), "Eigen processtatus niet uitleesbaar."))
            rows.append(row)
        return rows

    def observe(self):
        try:
            observation = super().observe()
        except Exception as error:
            self.diagnostics.error("guard-observe", error)
            raise
        try:
            self.diagnostics.observe(observation, self.own_processes)
        except Exception as error:
            self.diagnostics.error("diagnostic-observe", error)
        return observation

    def close(self):
        if self.closed:
            return
        try:
            try:
                if self.assigned:
                    self.track_members()
                self.diagnostics.before_cleanup = self.own_processes(exit_codes=True)
            except Exception as error:
                self.diagnostics.error("before-cleanup", error)
        finally:
            # Logging may never prevent the original owned-process cleanup.
            super().close()
