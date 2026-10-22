"""Synthetic policy failures and headless Python processes; never start a game.

No fixture confines, moves, hides or captures the real mouse. No native helper is
compiled. The Windows tests exercise jobs using the existing Python runtime.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import iii_session_guard as guard


class GuardPolicyTests(unittest.TestCase):
    def test_focus_loss_ends_owned_session_but_startup_does_not_steal_focus(self):
        policy = guard.GuardPolicy(0, 10)
        self.assertIsNone(policy.stop_reason(guard.Observation(2), 1))
        self.assertIsNone(policy.stop_reason(guard.Observation(2, own_foreground=True), 2))
        self.assertEqual(policy.stop_reason(guard.Observation(1), 2.05), 'focus_lost')

    def test_parent_exit_does_not_end_session_while_a_child_is_still_alive(self):
        policy = guard.GuardPolicy(5, 2)
        self.assertIsNone(policy.stop_reason(guard.Observation(1), 6))
        self.assertEqual(policy.stop_reason(guard.Observation(1), 7), 'time_limit')
        self.assertEqual(policy.stop_reason(guard.Observation(0), 7), 'exited')

    def test_capture_hotkey_and_maximum_duration_are_independent_stop_paths(self):
        cases = [(guard.Observation(1, cursor_confined=True), 'cursor_confined'),
                 (guard.Observation(1, emergency=True), 'emergency_hotkey')]
        for observation, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(guard.GuardPolicy(0, 30).stop_reason(observation, 1), reason)
        for seconds in (0, 1, 31, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                guard.GuardPolicy(0, seconds)

    def test_transient_busy_window_can_recover_but_continuous_hang_is_stopped(self):
        policy = guard.GuardPolicy(0, 10)
        busy = guard.Observation(2, own_foreground=True, responsive=False)
        ready = guard.Observation(2, own_foreground=True, responsive=True)
        self.assertIsNone(policy.stop_reason(busy, 1))
        self.assertIsNone(policy.stop_reason(ready, 1.9))
        self.assertIsNone(policy.stop_reason(busy, 2))
        self.assertIsNone(policy.stop_reason(busy, 2.9))
        self.assertEqual(policy.stop_reason(busy, 3), 'unresponsive')


class PlayPolicyTests(unittest.TestCase):
    def test_foreground_capture_does_not_terminate_play_after_thirty_seconds(self):
        policy = guard.PlayPolicy(0, 14400)
        running = guard.Observation(2, own_foreground=True, cursor_confined=True, responsive=True)
        self.assertIsNone(policy.stop_reason(running, 60))
        self.assertIsNone(policy.stop_reason(running, 3600))
        self.assertEqual(policy.stop_reason(running, 14400), 'time_limit')

    def test_alt_tab_is_allowed_but_confinement_outside_game_still_stops(self):
        policy = guard.PlayPolicy(0, 600)
        policy.stop_reason(guard.Observation(1, own_foreground=True), 1)
        self.assertIsNone(policy.stop_reason(guard.Observation(1), 2))
        self.assertIsNone(policy.stop_reason(guard.Observation(1), 4))
        self.assertEqual(policy.stop_reason(guard.Observation(1, cursor_confined=True), 4), 'cursor_confined')

    def test_loading_grace_has_a_bound_and_emergency_still_wins(self):
        policy = guard.PlayPolicy(0, 600)
        busy = guard.Observation(1, own_foreground=True, responsive=False)
        self.assertIsNone(policy.stop_reason(busy, 1))
        self.assertIsNone(policy.stop_reason(busy, 10.9))
        self.assertEqual(policy.stop_reason(busy, 11), 'unresponsive')
        self.assertEqual(policy.stop_reason(guard.Observation(1, emergency=True), 11), 'emergency_hotkey')


class FakeBackend:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def step(self, name):
        self.calls.append(name)
        if name == self.failure:
            raise OSError('synthetic ' + name)

    def preflight(self): self.step('preflight')
    def start_suspended(self, *args): self.step('suspended')
    def assign(self): self.step('assigned')
    def resume(self): self.step('resumed')
    def observe(self):
        self.step('observed')
        return guard.Observation(1, emergency=True)
    def close(self): self.step('closed')


class GuardFailureTests(unittest.TestCase):
    def run_fake(self, backend):
        return guard.supervise([str(Path(sys.executable).resolve())], Path.cwd(), {},
                               backend_factory=lambda: backend, clock=lambda: 0)

    def test_start_order_and_cleanup_after_each_failure(self):
        sequence = ['preflight', 'suspended', 'assigned', 'resumed', 'observed']
        for index, failure in enumerate(sequence):
            backend = FakeBackend(failure)
            with self.subTest(failure=failure), self.assertRaisesRegex(OSError, failure):
                self.run_fake(backend)
            self.assertEqual(backend.calls, sequence[:index + 1] + ['closed'])

    def test_cleanup_error_cannot_be_reported_as_success(self):
        with self.assertRaisesRegex(OSError, 'closed'):
            self.run_fake(FakeBackend('closed'))
        backend = FakeBackend()
        result = self.run_fake(backend)
        self.assertEqual(result['reason'], 'emergency_hotkey')
        self.assertTrue(result['cleanup_verified'])
        self.assertEqual(backend.calls, ['preflight', 'suspended', 'assigned', 'resumed', 'observed', 'closed'])

    def test_invalid_paths_or_duration_never_construct_a_backend(self):
        with patch.object(guard, 'WindowsJobBackend') as factory:
            for argv, seconds in ((['relative.exe'], 10), ([sys.executable], 31), ([], 10)):
                with self.assertRaises(ValueError):
                    guard.supervise(argv, Path.cwd(), {}, seconds=seconds)
            factory.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'Windows Job Objects vereisen Windows.')
class WindowsGuardTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='iii-guard-python-', dir=base)
        self.folder = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def require_desktop(self):
        backend = guard.WindowsJobBackend()
        try:
            backend.preflight()
        except OSError as error:
            if error.errno == 5 and 'Noodstop' in str(error):
                self.skipTest('De sandbox weigert hotkeyregistratie; aparte desktopcontrole vereist.')
            if 'De muis is al begrensd' in str(error):
                self.skipTest('Een bestaande app begrenst de muis; er worden geen testprocessen gestart.')
            raise
        finally:
            backend.close()

    def test_abi_sizes_match_windows_headers(self):
        backend = guard.WindowsJobBackend()
        is64 = ctypes.sizeof(ctypes.c_void_p) == 8
        self.assertEqual(ctypes.sizeof(backend.Limits), 144 if is64 else 112)
        self.assertEqual(ctypes.sizeof(backend.Startup), 104 if is64 else 68)
        self.assertEqual(ctypes.sizeof(backend.ProcessInfo), 24 if is64 else 16)
        self.assertEqual(ctypes.sizeof(backend.Accounting), 48)

    def test_assignment_failure_kills_suspended_process_before_python_runs(self):
        self.require_desktop()
        marker = self.folder / 'must-not-exist.txt'

        class RefusedAssignment(guard.WindowsJobBackend):
            def assign(self):
                raise OSError('synthetic assignment refusal')

        backend = RefusedAssignment()
        with self.assertRaisesRegex(OSError, 'assignment refusal'):
            guard.supervise([sys.executable, '-c',
                             'from pathlib import Path; Path(' + repr(str(marker)) + ').write_text("ran")'],
                            self.folder, dict(os.environ), backend_factory=lambda: backend)
        self.assertFalse(marker.exists())
        self.assertTrue(backend.closed)

    def test_time_limit_cleans_child_after_parent_exit_without_mouse_operations(self):
        self.require_desktop()
        record = self.folder / 'child.json'
        code = ('import json, subprocess, sys; from pathlib import Path; '
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],'
                'creationflags=0x08000000); '
                'Path(' + repr(str(record)) + ').write_text(json.dumps({"child":p.pid}))')
        backend = guard.WindowsJobBackend()
        result = guard.supervise([sys.executable, '-c', code], self.folder, dict(os.environ),
                                 seconds=2, backend_factory=lambda: backend)
        self.assertTrue(record.exists(), 'The synthetic parent must really have spawned its child.')
        self.assertEqual(result['reason'], 'time_limit')
        self.assertTrue(result['cleanup_verified'])
        self.assertLess(result['elapsed_seconds'], 5)
        self.assertTrue(backend.closed)

    def test_guardian_process_death_closes_private_job_and_its_descendant(self):
        self.require_desktop()
        record = self.folder / 'child.json'
        release = self.folder / 'release.txt'
        # The supervisor deliberately exits without finally/close. Windows must
        # close its last job handle and terminate the already orphaned child.
        code = '''import json, os, sys, time
from pathlib import Path
from tools.iii_session_guard import WindowsJobBackend
folder, record, release = map(Path, sys.argv[1:])
backend = WindowsJobBackend()
backend.preflight()
parent_code = ('import subprocess,sys,json; from pathlib import Path; '
    'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],creationflags=0x08000000); '
    'Path('+repr(str(record))+').write_text(json.dumps({"child":p.pid}))')
backend.start_suspended([sys.executable, '-c', parent_code], folder, dict(os.environ))
backend.assign()
backend.resume()
deadline = time.monotonic()+8
while not release.exists() and time.monotonic()<deadline: time.sleep(0.02)
os._exit(7)
'''
        process = subprocess.Popen([sys.executable, '-c', code, str(self.folder), str(record), str(release)],
                                   cwd=Path(__file__).resolve().parents[1], creationflags=0x08000000)
        handle = None
        backend = guard.WindowsJobBackend()  # Only API declarations; no second hotkey/job.
        try:
            deadline = time.monotonic() + 5
            while not record.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(record.exists(), 'Synthetic supervisor did not create its child.')
            # A held handle identifies this exact child even if the PID is reused.
            pid = json.loads(record.read_text())['child']
            handle = backend.kernel.OpenProcess(0x00100000, False, pid)
            self.assertTrue(handle)
            release.write_text('exit', encoding='ascii')
            self.assertEqual(process.wait(timeout=5), 7)
            self.assertEqual(backend.kernel.WaitForSingleObject(handle, 3500), 0,
                             'The descendant outlived the private job owner.')
        finally:
            if process.poll() is None:
                process.terminate()  # This exact synthetic guardian only.
                process.wait(timeout=5)
            if handle:
                backend.kernel.CloseHandle(handle)

    def test_independent_watchdog_ends_child_when_guardian_stops_sending_heartbeats(self):
        self.require_desktop()
        backend = guard.WindowsJobBackend()
        try:
            backend.preflight()
            backend.start_suspended([sys.executable, '-c', 'import time; time.sleep(60)'],
                                    self.folder, dict(os.environ))
            backend.assign()
            backend.resume()
            # No observe/pulse: simulate a hung supervisor without ever trapping input.
            self.assertEqual(backend.kernel.WaitForSingleObject(backend.process.process, 4000), 0)
            self.assertEqual(backend.lease.process.wait(timeout=2), 9)
            self.assertEqual(backend.active_count(), 0)
        finally:
            backend.close()


if __name__ == '__main__':
    unittest.main()
