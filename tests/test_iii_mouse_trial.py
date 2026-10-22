"""Copy/isolation contracts with existing small synthetic III fixture records."""
from pathlib import Path
import json
import unittest
from unittest.mock import patch
import tests.test_iii_compat_launcher as compatibility_tests
from tools import iii_mouse_trial as trial, iii_local_launcher as native, iii_compat_launcher as compat


class MouseTrialTests(unittest.TestCase):
    def setUp(self):
        self.fixture = compatibility_tests.CompatibilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.imported()
        self.root = self.fixture.root
        self.source = native.game_folder(self.root, 1)
        self.builder = patch.object(trial.fix, 'build', return_value=(b'synthetic-shared-mouse-race', {'runtime_verified':False}))
        self.builder.start()
        self.addCleanup(self.builder.stop)

    def test_new_copy_preserves_source_and_reuses_its_own_player_progress(self):
        before = compat.tree_bytes(self.source)
        target = trial.prepare(self.root, 1, 'original', self.source)
        self.assertEqual(compat.tree_bytes(self.source), before)
        self.assertEqual((target/'spel.dat').read_bytes(), b'synthetic-shared-mouse-race')
        (target/'game.ini').write_bytes(b'new player progress')
        self.assertEqual(trial.prepare(self.root, 1, 'original', self.source), target)
        self.assertEqual((target/'game.ini').read_bytes(), b'new player progress')
        self.assertEqual(compat.tree_bytes(self.source), before)

    def test_tampered_race_and_forged_receipt_are_rejected_without_overwrite(self):
        target = trial.prepare(self.root, 1, 'original', self.source)
        (target/'spel.dat').write_bytes(b'changed')
        with self.assertRaises(ValueError): trial.prepare(self.root, 1, 'original', self.source)
        self.assertEqual((target/'spel.dat').read_bytes(), b'changed')
        record = json.loads((target/'mouse-trial.json').read_text())
        record['files']['spel.dat'] = '0'*64
        (target/'mouse-trial.json').write_text(json.dumps(record))
        with self.assertRaises(ValueError): trial.prepare(self.root, 1, 'original', self.source)

    def test_unknown_executable_in_original_source_and_wrong_tour_are_rejected(self):
        with self.assertRaises(ValueError): trial.prepare(self.root, 2, 'original', self.source)
        (self.source/'extra.exe').write_bytes(b'synthetic extra')
        with self.assertRaisesRegex(ValueError, 'Onbekend bronbestand'):
            trial.prepare(self.root, 1, 'original', self.source)
        self.assertFalse((self.root/'local/iii-mouse').exists())

    def test_source_changing_during_preparation_does_not_promote(self):
        def build_then_change(raw):
            (self.source/'game.ini').write_bytes(b'concurrent saved progress')
            return b'synthetic-shared-mouse-race', {}
        with patch.object(trial.fix, 'build', side_effect=build_then_change), self.assertRaisesRegex(ValueError,'veranderde'):
            trial.prepare(self.root, 1, 'original', self.source)
        self.assertFalse((self.root/'local/iii-mouse/tour1-original').exists())
        self.assertEqual((self.source/'game.ini').read_bytes(), b'concurrent saved progress')
