import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from tools import iii_local_launcher as launcher


class LocalIIITests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        fixture.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=fixture)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'local/iii-prepared/baseline-20261013/tour1'
        records = []
        for name, content in {'A2 Racer III Tour 1.exe': b'synthetic-parent',
                              'spel.dat': b'synthetic-race',
                              'MenuData/menu.exe': b'synthetic-menu',
                              'MenuData/menu.ini': b'[General]\r\nExitCode=255\r\nINTROAVI=\\DATA\\INTRO.AVI\r\n',
                              'game.ini': b'synthetic-player-state',
                              'raser.ini': b'DEBUGON=0'}.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            records.append({'path': name, 'bytes': len(content),
                            'sha256': hashlib.sha256(content).hexdigest()})
        report = self.root / 'reports/a2racer3/tours-20261013/tour1-files.json'
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({'files': records}), encoding='utf-8')
        self.pins = patch.dict(launcher.PINS, {1: launcher.digest(report)})
        self.pins.start()
        self.addCleanup(self.pins.stop)

    def test_separate_copy_flattens_menu_without_binary_changes(self):
        folder = launcher.prepare(self.root, 1)
        self.assertEqual((folder/'menu.exe').read_bytes(), b'synthetic-menu')
        self.assertEqual((self.source/'MenuData/menu.exe').read_bytes(), b'synthetic-menu')
        self.assertFalse((folder/'MenuData').exists())
        state = launcher.check(self.root, 1)
        self.assertTrue(state['launch_ready'])
        self.assertFalse(state['runtime_verified'])
        self.assertFalse(state['disc_image_used'])
        self.assertFalse(state['binary_modified'])

    def test_changed_source_does_not_create_play_copy(self):
        (self.source/'spel.dat').write_bytes(b'changed')
        with self.assertRaises(ValueError): launcher.prepare(self.root, 1)
        self.assertFalse(launcher.game_folder(self.root, 1).exists())

    def test_changed_binary_is_rejected_without_overwriting(self):
        folder = launcher.prepare(self.root, 1)
        (folder/'spel.dat').write_bytes(b'changed')
        with self.assertRaises(ValueError): launcher.prepare(self.root, 1)
        self.assertEqual((folder/'spel.dat').read_bytes(), b'changed')

    def test_saved_player_state_survives_repeated_prepare(self):
        folder = launcher.prepare(self.root, 1)
        (folder/'game.ini').write_bytes(b'saved-player')
        launcher.prepare(self.root, 1)
        self.assertEqual((folder/'game.ini').read_bytes(), b'saved-player')

    def test_intro_uses_local_file_preserving_original_config_and_saved_values(self):
        original = (self.source/'MenuData/menu.ini').read_bytes()
        folder = launcher.prepare(self.root, 1)
        self.assertEqual((folder/'menu.ini').read_bytes(), original.replace(b'INTROAVI=\\DATA\\INTRO.AVI', b'INTROAVI=.\\intro.avi'))
        self.assertEqual((self.source/'MenuData/menu.ini').read_bytes(), original)
        saved = (folder/'menu.ini').read_bytes().replace(b'ExitCode=255', b'ExitCode=40')
        (folder/'menu.ini').write_bytes(saved)
        launcher.prepare(self.root, 1)
        self.assertEqual((folder/'menu.ini').read_bytes(), saved)

    def test_start_hands_verified_tour1_to_mandatory_guard(self):
        with patch.dict(os.environ, {'NOCD': 'parent-value'}), patch.object(launcher.iii_guarded_start, 'run', return_value=0) as guarded, patch.object(launcher.subprocess, 'Popen') as spawn:
            self.assertEqual(launcher.start(self.root, 1), 0)
            folder = launcher.game_folder(self.root, 1)
            guarded.assert_called_once_with(self.root, 1, 'original', folder)
            spawn.assert_not_called()
            self.assertEqual(os.environ['NOCD'], 'parent-value')

    def test_unknown_tour_rejected(self):
        for tour in (0, 3, True, '1'):
            with self.subTest(tour=tour), self.assertRaises(ValueError):
                launcher.prepare(self.root, tour)


if __name__ == '__main__':
    unittest.main()
