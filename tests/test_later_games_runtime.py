"""Synthetic portable preparation/session tests. Never start a game or change a display."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools import later_games_runtime as runtime
from tools.iii_session_guard import Observation

MENU = b'[GENERAL]\r\nINTROAVI=old.mpg\r\nEXITCODE=0\r\nPREVSTATE=9\r\n'
RACE = b'[PROGRAM]\r\nRESOLUTION=1\r\nWINDOWED=1\r\n[HELPDESK]\r\nDEBUGON=1\r\n'


class SyntheticFixture:
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='public-later-runtime-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'Portable Mënü'
        self.game = getattr(self, 'SELECTED_GAME', 'vakantieracer')
        self.profile = 'hd1080'
        self.originals = {
            'MENU.EXE': b'synthetic non-executable menu',
            'SPEL.DAT': b'synthetic non-executable race',
            ('VRACER.EXE' if self.game == 'vakantieracer' else 'A2RACER4.EXE'): b'synthetic non-executable parent',
            'MENU.INI': MENU, 'RASER.INI': RACE, 'GAME.INI': b'original settings',
            'INTRO1.MPG': b'synthetic non-video', 'savegame1.rcr': b'original imported save',
            'textures/road.raw': b'synthetic texture'
        }
        for name, data in self.originals.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.rows = [{'path': name, 'size': len(data), 'sha256': runtime.sha(data)}
                     for name, data in self.originals.items()]
        self.wrappers = {'DDraw.dll': b'synthetic menu wrapper',
                         'profiles/menu/DDraw.dll': b'synthetic menu wrapper',
                         'profiles/race/DDraw.dll': b'synthetic race wrapper',
                         'D3DImm.dll': b'synthetic d3d component',
                         'ddraw.ini': b'synthetic menu config',
                         'dgVoodoo.conf': b'synthetic 4:3 race config'}
        self.installation = self.start_patch(patch.object(runtime.installation, 'check', side_effect=self.installed))
        self.start_patch(patch.object(runtime, 'component_plan', side_effect=lambda *args: dict(self.wrappers)))
        self.patcher = self.start_patch(patch.object(runtime.native, 'patch_binary', side_effect=self.patch_binary))
        self.start_patch(patch.dict(runtime.WRAPPER_PINS, {
            'cnc_ddraw': {'sha256': runtime.sha(self.wrappers['DDraw.dll'])},
            'dg_ddraw': {'sha256': runtime.sha(self.wrappers['profiles/race/DDraw.dll'])}
        }))
        self.no_process = self.start_patch(patch('subprocess.Popen', side_effect=AssertionError('No native process in fixture')))
        self.no_winapi = self.start_patch(patch('ctypes.WinDLL', side_effect=AssertionError('No native display/device API in fixture'), create=True))

    def start_patch(self, value):
        result = value.start()
        self.addCleanup(value.stop)
        return result

    @property
    def source(self):
        return self.root / 'local/games' / self.game / 'original'

    @property
    def game_dir(self):
        return self.root / runtime.game_base(self.game, self.profile) / 'game'

    @property
    def prepared_path(self):
        return self.game_dir.parent / 'prepared.json'

    def installed(self, root, game):
        self.assertEqual(Path(root), self.root)
        self.assertEqual(game, self.game)
        return {'source_path': str(self.source), 'parent': 'VRACER.EXE' if self.game == 'vakantieracer' else 'A2RACER4.EXE', 'files': list(self.rows)}

    def patch_binary(self, data, game, kind):
        self.assertEqual(game, self.game)
        expected = self.originals['MENU.EXE' if kind == 'menu' else 'SPEL.DAT']
        self.assertEqual(data, expected)
        output = b'patched:' + data
        return output, {'kind': kind, 'source_sha256': runtime.sha(data), 'sha256': runtime.sha(output),
                        'patches': [], 'runtime_verified': False}

    def prepare(self):
        return runtime.prepare(self.root, self.game, self.profile)

    def assert_source_intact(self):
        for name, data in self.originals.items():
            self.assertEqual((self.source / name).read_bytes(), data, name)


class PreparationTests(SyntheticFixture, unittest.TestCase):
    def test_preparation_uses_managed_import_and_commits_only_verified_copy(self):
        metadata = self.prepare()
        self.installation.assert_called_once_with(self.root, self.game)
        self.assertEqual(metadata['parent'], 'VRACER.EXE')
        self.assertEqual(Path(metadata['game_path']), self.game_dir)
        self.assertFalse(metadata['runtime_verified'])
        self.assertFalse(metadata['graphics_runtime_verified'])
        self.assertEqual(metadata['race_aspect_ratio_requested'], [4, 3])
        self.assertEqual(metadata['render_resolution_requested'], [1440, 1080])
        self.assertEqual((self.game_dir / 'MENU.EXE').read_bytes(), b'patched:' + self.originals['MENU.EXE'])
        self.assertIn(str(self.game_dir / 'INTRO1.MPG').encode('cp1252'), (self.game_dir / 'MENU.INI').read_bytes())
        self.assertNotIn(b'.build-', (self.game_dir / 'MENU.INI').read_bytes())
        self.assertEqual((self.game_dir / 'savegame1.rcr').read_bytes(), self.originals['savegame1.rcr'])
        runtime.verify(self.game_dir, metadata)
        self.assert_source_intact()
        self.no_process.assert_not_called()
        self.no_winapi.assert_not_called()

    def test_reuse_preserves_player_changes_and_imported_originals(self):
        self.prepare()
        (self.game_dir / 'savegame1.rcr').write_bytes(b'new progress from own session')
        (self.game_dir / 'GAME.INI').write_bytes(b'own changed game settings')
        (self.game_dir / 'savegame2.rcr').write_bytes(b'new second save slot')
        original_registration = self.prepared_path.read_bytes()
        self.prepare()
        self.assertEqual((self.game_dir / 'savegame1.rcr').read_bytes(), b'new progress from own session')
        self.assertEqual((self.game_dir / 'GAME.INI').read_bytes(), b'own changed game settings')
        self.assertEqual((self.game_dir / 'savegame2.rcr').read_bytes(), b'new second save slot')
        self.assertEqual(self.prepared_path.read_bytes(), original_registration)
        self.assert_source_intact()

    def test_partial_failure_never_promotes_a_broken_copy_and_can_retry(self):
        real = self.patch_binary
        def fail_race(data, game, kind):
            if kind == 'race':
                raise ValueError('synthetic incompatible race')
            return real(data, game, kind)
        self.patcher.side_effect = fail_race
        with self.assertRaisesRegex(ValueError, 'synthetic incompatible race'):
            self.prepare()
        self.assertFalse(self.game_dir.parent.exists())
        self.assert_source_intact()
        self.patcher.side_effect = real
        self.prepare()
        runtime.verify(self.game_dir, json.loads(self.prepared_path.read_bytes()))

    def test_oversized_registration_is_rejected_before_json_parsing(self):
        self.prepare()
        self.prepared_path.write_bytes(b' ' * (4 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, 'record is te groot'):
            self.prepare()
        self.assert_source_intact()

    def test_existing_incomplete_directory_is_preserved_not_overwritten(self):
        marker = self.game_dir.parent / 'own-progress.txt'
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b'must remain')
        with self.assertRaisesRegex(ValueError, 'Onvolledige'):
            self.prepare()
        self.assertEqual(marker.read_bytes(), b'must remain')
        self.assertFalse(self.prepared_path.exists())

    def test_tampered_immutable_file_and_unexpected_code_are_rejected(self):
        self.prepare()
        path = self.game_dir / 'textures/road.raw'
        path.write_bytes(b'changed texture')
        with self.assertRaisesRegex(ValueError, 'wijkt af'):
            self.prepare()
        path.write_bytes(self.originals['textures/road.raw'])
        injected = self.game_dir / 'unexpected.exe'
        injected.write_bytes(b'non-executable test marker')
        with self.assertRaisesRegex(ValueError, 'Onverwachte uitvoerbare'):
            self.prepare()
        self.assert_source_intact()

    def test_unmanaged_source_path_and_changed_source_during_copy_are_refused(self):
        self.installation.side_effect = None
        self.installation.return_value = {'source_path': str(self.root / 'arbitrary source'), 'files': self.rows}
        with self.assertRaisesRegex(ValueError, 'beheerde bronmap'):
            self.prepare()
        self.installation.side_effect = self.installed
        (self.source / 'textures/road.raw').write_bytes(b'changed after inventory')
        with self.assertRaisesRegex(ValueError, 'Bron'):
            self.prepare()
        self.assertFalse(self.game_dir.parent.exists())

    def test_prepared_folder_can_be_relocated_and_reused_without_private_provider(self):
        self.prepare()
        moved = self.root.with_name('Moved Mënü')
        self.assertEqual(moved.parent, Path(self.temporary.name))
        # A scanner may briefly hold this synthetic directory after its file
        # reads. Retry only Windows access/sharing violations, never skip a
        # persistent failure or reinterpret a product exception as success.
        delays = iter((0.05, 0.1, 0.2, 0.4))
        while True:
            try:
                self.root.rename(moved)
                break
            except OSError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33):
                    raise
                delay = next(delays, None)
                if delay is None:
                    raise
                time.sleep(delay)
        self.root = moved
        metadata = self.prepare()
        runtime.verify(self.game_dir, metadata)
        self.assertEqual((self.game_dir / 'savegame1.rcr').read_bytes(), self.originals['savegame1.rcr'])
        self.assert_source_intact()

    def test_check_only_never_constructs_display_or_supervisor_and_releases_lock(self):
        supervisor, display = Mock(), Mock()
        result = runtime.run(self.root, self.game, profile=self.profile, check_only=True,
                             supervisor=supervisor, display_factory=display)
        self.assertTrue(result['ready'])
        self.assertFalse(result['game_started'])
        supervisor.assert_not_called()
        display.assert_not_called()
        self.assertFalse((self.root / runtime.BASE / 'session.lock').exists())
        self.assert_source_intact()

    def test_bad_request_cannot_claim_a_lock_or_start_preparation(self):
        for seconds in (True, 1, 14401, '60'):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                runtime.run(self.root, self.game, seconds=seconds, check_only=True)
        with self.assertRaises(ValueError):
            runtime.run(self.root, self.game, control_token='not-a-token', check_only=True)
        self.assertFalse((self.root / runtime.BASE / 'session.lock').exists())
        self.installation.assert_not_called()

    def test_existing_session_lock_is_not_deleted_or_replaced(self):
        lock = self.root / runtime.BASE / 'session.lock'
        lock.parent.mkdir(parents=True)
        lock.write_bytes(b'another owned session')
        with self.assertRaises(FileExistsError):
            runtime.run(self.root, self.game, profile=self.profile, check_only=True)
        self.assertEqual(lock.read_bytes(), b'another owned session')
        self.installation.assert_not_called()


class DisplayFixture:
    def __init__(self, verified=True):
        self.before = {'mode': 'synthetic original desktop'}
        self.snapshots = 0
        self.restores = []
        self.verified = verified

    def snapshot(self):
        self.snapshots += 1
        return dict(self.before)

    def restore(self, before):
        self.restores.append(before)
        return {'verified': self.verified}


@unittest.skipUnless(os.name == 'nt', 'Native session requires a Windows drive letter; supervisors remain synthetic')
class SessionTests(SyntheticFixture, unittest.TestCase):
    def run_session(self, supervisor, display=None, **kwargs):
        self.display = display or DisplayFixture()
        return runtime.run(self.root, self.game, profile=self.profile, seconds=60,
                           supervisor=supervisor, display_factory=lambda: self.display, **kwargs)

    def test_original_menu_requests_race_then_returns_to_menu_with_owned_environment(self):
        calls = []
        def supervisor(argv, cwd, environment, **options):
            index = len(calls)
            expected = ('MENU.EXE', 'SPEL.DAT', 'MENU.EXE')[index]
            self.assertEqual(Path(argv[0]).name, expected)
            self.assertEqual(Path(cwd), self.game_dir)
            self.assertEqual(argv[1:], ['/Default'] if expected == 'MENU.EXE' else [])
            wrapper = self.wrappers['profiles/menu/DDraw.dll' if expected == 'MENU.EXE' else 'profiles/race/DDraw.dll']
            self.assertEqual((cwd / 'DDraw.dll').read_bytes(), wrapper)
            self.assertEqual([key for key in environment if key.casefold() == 'nocd'], ['NOCD'])
            self.assertEqual(environment['NOCD'], self.root.drive[0].upper())
            self.assertTrue(2 <= options['seconds'] <= 60)
            ini = cwd / 'MENU.INI'
            if index == 0:
                self.assertIn(b'PREVSTATE=0', ini.read_bytes())
                ini.write_bytes(runtime.set_ini(runtime.set_ini(ini.read_bytes(), 'GENERAL', 'EXITCODE', '40'),
                                                'GENERAL', 'PREVSTATE', '7'))
            elif index == 1:
                self.assertIs(options['policy_factory'], runtime.RaceBaselinePolicy)
                self.assertIn(b'WINDOWED=0', (cwd / 'RASER.INI').read_bytes())
                self.assertIn(b'DEBUGON=0', (cwd / 'RASER.INI').read_bytes())
            else:
                self.assertIn(b'PREVSTATE=7', ini.read_bytes())
                self.assertIn(b'EXITCODE=0', ini.read_bytes())
            calls.append(expected)
            return {'reason': 'exited', 'exit_code': 0, 'cleanup_verified': True}
        with patch.dict(os.environ, {'NOCD': 'Z', 'LATER_SYNTHETIC_ONLY': 'yes'}):
            result = self.run_session(supervisor)
            self.assertEqual(os.environ['NOCD'], 'Z')
        self.assertEqual(calls, ['MENU.EXE', 'SPEL.DAT', 'MENU.EXE'])
        self.assertEqual([row['stage'] for row in result['stages']], ['menu', 'race', 'menu'])
        self.assertEqual(result['stages'][0]['menu_ini_exitcode'], 40)
        self.assertTrue(result['display_restore']['verified'])
        self.assertEqual(self.display.restores, [self.display.before])
        self.assertEqual((self.game_dir / 'DDraw.dll').read_bytes(), self.wrappers['DDraw.dll'])
        self.assertFalse((self.root / runtime.BASE / 'session.lock').exists())
        self.assert_source_intact()

    def test_native_error_codes_are_preserved_and_do_not_restart_menu(self):
        for code in (1, 0xc0000005):
            with self.subTest(exit_code=code):
                calls = []
                def supervisor(argv, cwd, environment, **kwargs):
                    calls.append(Path(argv[0]).name)
                    if len(calls) == 1:
                        path = cwd / 'MENU.INI'
                        path.write_bytes(runtime.set_ini(path.read_bytes(), 'GENERAL', 'EXITCODE', '40'))
                        return {'reason': 'exited', 'exit_code': 0}
                    return {'reason': 'exited', 'exit_code': code}
                result = self.run_session(supervisor)
                self.assertEqual(calls, ['MENU.EXE', 'SPEL.DAT'])
                self.assertEqual(result['stages'][-1]['exit_code'], code)
                self.assertTrue(result['display_restore']['verified'])
                self.assertFalse((self.root / runtime.BASE / 'session.lock').exists())

    def test_menu_failure_and_guard_stop_never_launch_race(self):
        for outcome in ({'reason': 'exited', 'exit_code': 1},
                        {'reason': 'unresponsive', 'exit_code': None}):
            with self.subTest(outcome=outcome):
                supervisor = Mock(return_value=outcome)
                result = self.run_session(supervisor)
                self.assertEqual(supervisor.call_count, 1)
                self.assertEqual(len(result['stages']), 1)
                self.assertEqual(result['guard'], outcome)
                self.assertTrue(result['display_restore']['verified'])

    def test_supervisor_exception_restores_wrapper_display_and_lock_without_suppressing_error(self):
        supervisor = Mock(side_effect=OSError('synthetic native supervisor failure'))
        display = DisplayFixture()
        with self.assertRaisesRegex(OSError, 'synthetic native supervisor failure'):
            self.run_session(supervisor, display)
        self.assertEqual(display.restores, [display.before])
        self.assertEqual((self.game_dir / 'DDraw.dll').read_bytes(), self.wrappers['DDraw.dll'])
        self.assertFalse((self.root / runtime.BASE / 'session.lock').exists())
        results = list((self.root / runtime.REPORTS).glob('*/result.json'))
        self.assertEqual(len(results), 1)
        self.assertTrue(json.loads(results[0].read_bytes())['display_restore']['verified'])

    def test_failed_display_restore_is_reported_as_unverified(self):
        result = self.run_session(Mock(return_value={'reason': 'exited', 'exit_code': 0}),
                                  DisplayFixture(verified=False))
        self.assertFalse(result['display_restore']['verified'])

    def test_stop_request_after_menu_prevents_the_race_stage(self):
        token = 'a' * 32
        def supervisor(argv, cwd, environment, **kwargs):
            path = cwd / 'MENU.INI'
            path.write_bytes(runtime.set_ini(path.read_bytes(), 'GENERAL', 'EXITCODE', '40'))
            stop = runtime.control.stop_path(self.root, token)
            stop.parent.mkdir(parents=True, exist_ok=True)
            stop.write_bytes(b'stop\n')
            return {'reason': 'exited', 'exit_code': 0}
        supervisor = Mock(side_effect=supervisor)
        result = self.run_session(supervisor, control_token=token)
        self.assertTrue(result['stop_requested'])
        self.assertEqual(result['guard']['reason'], 'user_requested_stop')
        self.assertEqual(supervisor.call_count, 1)
        self.assertTrue(result['display_restore']['verified'])


class PolicyTests(unittest.TestCase):
    def test_loading_grace_keeps_emergency_deadline_and_later_hang_guards(self):
        policy = runtime.RaceBaselinePolicy(0, 120)
        for moment in (18, 44.9, 45):
            self.assertIsNone(policy.stop_reason(Observation(1, True, False, False), moment))
        self.assertEqual(policy.stop_reason(Observation(1, True, False, False), 55), 'unresponsive')
        self.assertEqual(runtime.RaceBaselinePolicy(0, 120).stop_reason(Observation(1, emergency=True), 2),
                         'emergency_hotkey')
        self.assertEqual(runtime.RaceBaselinePolicy(0, 20).stop_reason(Observation(1, True, False, False), 20),
                         'time_limit')



class IVPreparationTests(SyntheticFixture, unittest.TestCase):
    SELECTED_GAME = 'a2racer4'

    def test_iv_metadata_preserves_original_parent_and_bounded_vram_contract(self):
        value = self.prepare()
        self.assertEqual(value['parent'], 'A2RACER4.EXE')
        self.assertEqual(value['vram_probe_max_handles'], 1024)
        self.assertEqual(value['virtual_vram_mb_requested'], 32)
        self.assertFalse(value['widescreen_requested'])
        self.assertFalse(value['shutdown_mouse_runtime_verified'])
        self.assert_source_intact()


@unittest.skipUnless(os.name == 'nt', 'Native session requires a Windows drive letter; supervisors remain synthetic')
class IVSessionTests(SessionTests):
    SELECTED_GAME = 'a2racer4'


class DiagnosticsTests(unittest.TestCase):
    def backend(self):
        import ctypes
        from ctypes import wintypes
        from types import SimpleNamespace
        from tools.later_session_backend import DiagnosticMenuBackend, MenuDiagnostics
        backend = DiagnosticMenuBackend.__new__(DiagnosticMenuBackend)
        backend.c, backend.w = ctypes, wintypes
        backend.diagnostics = MenuDiagnostics(clock=lambda: 0)
        backend.image_names = {}
        backend.assigned, backend.closed, backend.job = True, False, 99
        backend.process = SimpleNamespace(pid=101, process=201)
        backend.members = {102: 202, 103: 203}
        kernel = SimpleNamespace()
        def belongs(handle, job, pointer):
            self.assertEqual(job, 99)
            ctypes.cast(pointer, ctypes.POINTER(wintypes.BOOL)).contents.value = int(handle != 203)
            return True
        def image(handle, flags, buffer, length):
            self.assertNotEqual(handle, 203, 'Foreign handle must not be inspected')
            buffer.value = r'Z:\synthetic\SPEL.DAT' if handle == 201 else r'Z:\synthetic\helper.exe'
            return True
        def status(handle, pointer):
            self.assertEqual(handle, 201, 'STILL_ACTIVE must not be reread as an exit code')
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = 1
            return True
        kernel.IsProcessInJob = Mock(side_effect=belongs)
        kernel.QueryFullProcessImageNameW = Mock(side_effect=image)
        kernel.WaitForSingleObject = Mock(side_effect=lambda handle, timeout: 0 if handle == 201 else 258)
        kernel.GetExitCodeProcess = Mock(side_effect=status)
        backend.kernel = kernel
        return backend

    def test_diagnostics_read_only_verified_held_job_handles_and_keep_real_exit_code(self):
        backend = self.backend()
        rows = backend.own_processes(exit_codes=True)
        self.assertEqual([row['pid'] for row in rows], [101, 102])
        self.assertEqual(rows[0]['image_basename'], 'SPEL.DAT')
        self.assertEqual((rows[0]['state'], rows[0]['exit_code']), ('exited', 1))
        self.assertEqual(rows[1]['state'], 'still_active')
        self.assertIsNone(rows[1]['exit_code'])
        self.assertEqual(rows[1]['still_active_marker'], 259)
        self.assertEqual(backend.diagnostics.errors[0]['stage'], 'verify-own-handle')

    def test_diagnostic_failure_never_prevents_public_guard_cleanup(self):
        from tools.iii_session_guard import WindowsJobBackend
        backend = self.backend()
        backend.track_members = Mock()
        backend.own_processes = Mock(side_effect=ValueError('synthetic failed log'))
        with patch.object(WindowsJobBackend, 'close', autospec=True) as close:
            backend.close()
        backend.track_members.assert_called_once()
        close.assert_called_once_with(backend)
        self.assertEqual(backend.diagnostics.errors[0]['stage'], 'before-cleanup')

    def test_public_guard_exposes_the_required_backend_methods(self):
        from tools.iii_session_guard import WindowsJobBackend
        for name in ('start_suspended', 'assign', 'resume', 'own_window', 'track_members', 'observe', 'close'):
            self.assertTrue(callable(getattr(WindowsJobBackend, name)), name)


if __name__ == "__main__":
    unittest.main()
