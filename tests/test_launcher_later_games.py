"""CLI/menu contracts and atomic command publication; no game or GUI starts."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import launcher_later_games as bridge
from tools import later_game_control as control


class LaterBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='later-cli-')
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.host = self.root / bridge.START_SCRIPT; self.host.parent.mkdir()
        self.host.write_bytes(b'synthetic fixed host; never execute')
        self.runtime = SimpleNamespace(game_base=Mock(side_effect=lambda game, profile:
            'local/experiments/later/' + game + '/' + profile),
            run=Mock(return_value={'ready': True, 'game_started': False}))
        effect = patch.object(bridge, '_runtime', return_value=self.runtime)
        effect.start(); self.addCleanup(effect.stop)
        self.ready = {'ready': True, 'reason': 'Synthetic owned files present'}

    def test_catalog_uses_only_quick_status_and_confirms_both_hd_defaults(self):
        with patch.object(bridge.installation, 'status', return_value=self.ready) as status, \
                patch.object(bridge, '_runtime', side_effect=AssertionError('No preparation/native import')), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('No source content reads')):
            value = bridge.catalog(self.root)
        self.assertEqual(status.call_count, 2)
        self.assertEqual({call.args for call in status.call_args_list},
                         {(self.root, 'a2racer4'), (self.root, 'vakantieracer')})
        self.assertEqual(value['defaults'], {'a2racer4': 'hd1080', 'vakantieracer': 'hd1080'})
        self.assertTrue(all(p['confirmed_by_user'] for p in value['profiles']))
        self.assertTrue(all(g['ready'] and g['default_profile'] == 'hd1080' for g in value['games']))
        self.assertFalse(value['game_started']); self.assertLess(len(json.dumps(value)), 5000)

    def test_fixed_plan_has_only_closed_arguments_and_cannot_prepare_or_execute(self):
        with patch.object(bridge.installation, 'status', return_value=self.ready):
            for game in bridge.GAMES:
                for profile in bridge.PROFILES:
                    plan = bridge.plan(self.root, game, profile, 'a' * 32)
                    self.assertEqual(plan['start_script'], str(self.host))
                    self.assertEqual(plan['start_script_sha256'], hashlib.sha256(self.host.read_bytes()).hexdigest())
                    self.assertEqual(plan['arguments'], ['-Game', game, '-Profile', profile, '-ControlToken', 'a' * 32])
                    self.assertEqual(plan['game_path'], str(self.root / 'local/experiments/later' / game / profile / 'game'))
                    self.assertTrue(plan['original_menu_required']); self.assertFalse(plan['game_started'])
        self.runtime.run.assert_not_called()
        self.assertFalse((self.root / 'local').exists())

    def test_fresh_token_is_returned_but_used_or_invalid_token_is_refused(self):
        with patch.object(bridge.installation, 'status', return_value=self.ready):
            plan = bridge.plan(self.root, 'vakantieracer')
            self.assertRegex(plan['control_token'], '^[a-f0-9]{32}$')
            marker = control.stop_path(self.root, plan['control_token']); marker.parent.mkdir(parents=True)
            marker.write_bytes(b'stop\n')
            with self.assertRaisesRegex(ValueError, 'al gebruikt'):
                bridge.plan(self.root, 'vakantieracer', token=plan['control_token'])
        with patch.object(bridge.installation, 'status', side_effect=AssertionError('No source read')):
            for token in ('../escape', 'A' * 32, True, ''):
                with self.subTest(token=token), self.assertRaises(ValueError):
                    bridge.plan(self.root, 'vakantieracer', token=token)

    def test_unknown_game_profile_and_missing_source_cannot_select_an_executable(self):
        with patch.object(bridge.installation, 'status', side_effect=AssertionError('No source read')):
            for game, profile in (('cmd.exe', 'hd1080'), ('a2racer4', '-File'),
                                  (True, 'compat'), (['vakantieracer'], 'hd1080')):
                with self.subTest(game=game, profile=profile), self.assertRaises(ValueError):
                    bridge.plan(self.root, game, profile)
        with patch.object(bridge.installation, 'status', return_value={'ready': False, 'reason': 'Missing own files'}):
            with self.assertRaisesRegex(ValueError, 'Missing own files'):
                bridge.plan(self.root, 'a2racer4')
        self.runtime.run.assert_not_called()

    def test_plan_refuses_oversized_or_hardlinked_host(self):
        with patch.object(bridge.installation, 'status', return_value=self.ready):
            self.host.write_bytes(b'X' * (65536 + 1))
            with self.assertRaisesRegex(ValueError, 'te groot'): bridge.plan(self.root, 'a2racer4')
            self.host.write_bytes(b'synthetic host')
            try: os.link(self.host, self.root / 'another-host')
            except OSError as error: self.skipTest(str(error))
            with self.assertRaises(ValueError): bridge.plan(self.root, 'a2racer4')

    def test_prepare_requests_shared_check_only_and_compact_summary(self):
        value = bridge.prepare(self.root, 'vakantieracer', token='b' * 32)
        self.runtime.run.assert_called_once_with(self.root, 'vakantieracer', profile='hd1080',
                                                check_only=True, control_token='b' * 32)
        self.assertEqual(value['kind'], 'later-game-preparation-result')
        self.assertTrue(value['ready']); self.assertFalse(value['game_started'])
        self.assertLess(len(json.dumps(value)), 2000)
        self.runtime.run.reset_mock()
        with self.assertRaises(ValueError): bridge.prepare(self.root, 'vakantieracer', token='../bad')
        self.runtime.run.assert_not_called()
        for bad in ({'ready': False, 'game_started': False}, {'ready': True, 'game_started': True}):
            self.runtime.run.return_value = bad
            with self.assertRaises(ValueError): bridge.prepare(self.root, 'a2racer4')

    def test_import_actions_call_only_owned_importer_and_reduce_large_records(self):
        result = {'game': 'a2racer4', 'ready': True, 'source_path': str(self.root / 'managed'),
                  'files': [{'path': str(i)} for i in range(1000)], 'game_imported': True}
        with patch.object(bridge.installation, 'import_installation', return_value=result) as folder, \
                patch.object(bridge.installation, 'import_archive', return_value=result) as archive:
            one = bridge.import_installation(self.root, self.root / 'owned', 'a2racer4')
            two = bridge.import_game(self.root, self.root / 'owned.zip', 'a2racer4')
        folder.assert_called_once_with(self.root, self.root / 'owned', 'a2racer4')
        archive.assert_called_once_with(self.root, self.root / 'owned.zip', 'a2racer4')
        self.assertEqual(one['files'], 1000); self.assertEqual(two['files'], 1000)
        self.assertLess(len(json.dumps(one)), 2000); self.runtime.run.assert_not_called()

    def test_cli_success_is_compact_json_and_expected_errors_only_use_stderr(self):
        with patch.object(bridge, 'ROOT', self.root), patch.object(bridge.installation, 'status', return_value=self.ready):
            for args in (['catalog'], ['plan', '--game', 'a2racer4'], ['prepare', '--game', 'vakantieracer']):
                stdout = io.StringIO(); stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr): result = bridge.main(args)
                self.assertEqual(result, 0, stderr.getvalue()); self.assertEqual(stderr.getvalue(), '')
                self.assertIsInstance(json.loads(stdout.getvalue()), dict)
                self.assertEqual(stdout.getvalue().count('\n'), 1)
            stdout = io.StringIO(); stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = bridge.main(['import-installation', '--game', 'vakantieracer'])
            self.assertEqual(result, 1); self.assertEqual(stdout.getvalue(), '')
            self.assertIn('Kies je volledige eigen gamemap', stderr.getvalue())

    def test_non_windows_publication_is_refused_before_creating_state(self):
        fake = SimpleNamespace(name='posix', path=os.path)
        with patch.object(bridge, 'os', fake), self.assertRaises(OSError):
            bridge.stop(self.root, '1' * 32)
        self.assertFalse((self.root / 'local').exists())


@unittest.skipUnless(os.name == 'nt', 'Atomic no-replace rename publisher targets Windows')
class LaterStopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='later-stop-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.token = 'c' * 32
        self.path = control.stop_path(self.root, self.token)

    def test_partial_staging_is_invisible_and_final_is_published_after_close(self):
        original_open = Path.open; original_rename = Path.rename; events = []
        class StagedWriter:
            def __init__(self, handle): self.handle = handle
            def __enter__(self): return self
            def __exit__(self, *args): self.handle.close(); events.append('closed')
            def fileno(self): return self.handle.fileno()
            def flush(self): return self.handle.flush()
            def write(self, raw):
                self.handle.write(raw[:2]); self.handle.flush()
                events.append('partial')
                self_test.assertFalse(control.stop_requested(self_test.root, self_test.token))
                self.handle.write(raw[2:]); return len(raw)
        self_test = self
        def slow_open(path, mode='r', *args, **kwargs):
            handle = original_open(path, mode, *args, **kwargs)
            return StagedWriter(handle) if mode == 'xb' and path.suffix == '.tmp' else handle
        def publish(path, target):
            self.assertEqual(events, ['partial', 'closed'])
            self.assertEqual(path.read_bytes(), b'stop\n'); self.assertFalse(target.exists())
            return original_rename(path, target)
        with patch.object(Path, 'open', slow_open), patch.object(Path, 'rename', publish):
            value = bridge.stop(self.root, self.token)
        self.assertTrue(value['stop_requested']); self.assertTrue(control.stop_requested(self.root, self.token))
        self.assertFalse(list(self.path.parent.glob('*.tmp')))
        before = self.path.stat()
        with patch.object(Path, 'rename', side_effect=AssertionError('Idempotent marker is not rewritten')):
            bridge.stop(self.root, self.token)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_malformed_large_and_hardlinked_existing_markers_are_refused(self):
        self.path.parent.mkdir(parents=True)
        for data in (b'', b'stop', b'wrong\n', b'X' * 65536):
            with self.subTest(size=len(data)):
                self.path.write_bytes(data)
                with self.assertRaises(ValueError): bridge.stop(self.root, self.token)
                self.assertEqual(self.path.read_bytes(), data); self.assertFalse(list(self.path.parent.glob('*.tmp')))
        self.path.write_bytes(b'stop\n')
        os.link(self.path, self.root / 'linked-marker')
        with self.assertRaises(ValueError): bridge.stop(self.root, self.token)

    def test_losing_rename_preserves_competing_valid_or_invalid_marker(self):
        for data in (b'stop\n', b'wrong'):
            with self.subTest(data=data):
                if self.path.exists(): self.path.unlink()
                def compete(source, target):
                    target.write_bytes(data); raise FileExistsError('Synthetic other publisher won')
                with patch.object(Path, 'rename', compete):
                    if data == b'stop\n': self.assertTrue(bridge.stop(self.root, self.token)['stop_requested'])
                    else:
                        with self.assertRaises(ValueError): bridge.stop(self.root, self.token)
                self.assertEqual(self.path.read_bytes(), data); self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_failed_rename_cleans_only_its_own_temporary_file(self):
        self.path.parent.mkdir(parents=True)
        other = self.path.parent / 'other.tmp'; other.write_bytes(b'not owned')
        with patch.object(Path, 'rename', side_effect=PermissionError('Synthetic scanner handle')):
            with self.assertRaises(PermissionError): bridge.stop(self.root, self.token)
        self.assertEqual(other.read_bytes(), b'not owned')
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [other])
        self.assertFalse(self.path.exists())

    def test_replaced_temporary_inode_is_not_deleted(self):
        self.path.parent.mkdir(parents=True)
        replacement = self.root / 'replacement'; replacement.write_bytes(b'not the owned temporary')
        real = Path.rename
        def replace_owned(source, target):
            source.unlink(); real(replacement, source)
            raise PermissionError('Synthetic replacement before rename')
        with patch.object(Path, 'rename', replace_owned), self.assertRaisesRegex(ValueError, 'vervangen'):
            bridge.stop(self.root, self.token)
        remaining = list(self.path.parent.glob('*.tmp'))
        self.assertEqual(len(remaining), 1); self.assertEqual(remaining[0].read_bytes(), b'not the owned temporary')
        self.assertFalse(self.path.exists())


if __name__ == '__main__': unittest.main()
