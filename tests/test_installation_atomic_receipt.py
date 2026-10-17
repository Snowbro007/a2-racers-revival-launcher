"""Receipt write failures use synthetic text only; never run or copy a game."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import game_installation as gi, iii_installation as iii


ROOT = Path(__file__).resolve().parents[1]


class ImportReceiptTransactionTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='import-receipt-', dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stage = self.root / 'stage'
        self.stage.mkdir()
        (self.stage / 'fixture.txt').write_bytes(b'synthetic text fixture')
        self.target = self.root / 'finished'
        self.receipt = self.root / 'receipt.json'
        self.data = {'schema': 1, 'game_path': str(self.target), 'source_unchanged': True}

    def test_record_is_complete_before_directory_is_promoted(self):
        rename = Path.rename

        def checked_rename(source, target):
            self.assertEqual(json.loads(self.receipt.read_text()), self.data)
            self.assertEqual(self.data['game_path'], str(target))
            return rename(source, target)

        with patch.object(Path, 'rename', checked_rename):
            gi.promote_import(self.stage, self.target, self.receipt, self.data)
        self.assertEqual((self.target / 'fixture.txt').read_bytes(), b'synthetic text fixture')

    def test_partial_record_write_failure_rolls_back_only_own_record(self):
        def interrupted(data, handle, **kwargs):
            handle.write('{"partial":')
            raise OSError('Synthetic disk full')

        with patch.object(gi.json, 'dump', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'Synthetic disk full'):
                gi.promote_import(self.stage, self.target, self.receipt, self.data)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.receipt.exists())
        self.assertTrue((self.stage / 'fixture.txt').is_file())

    def test_record_flush_failure_does_not_publish_game_directory(self):
        with patch.object(gi.os, 'fsync', side_effect=OSError('Synthetic flush failure')):
            with self.assertRaisesRegex(OSError, 'Synthetic flush failure'):
                gi.promote_import(self.stage, self.target, self.receipt, self.data)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.receipt.exists())

    def test_failed_promotion_cleans_own_record_then_retry_succeeds(self):
        with patch.object(Path, 'rename', side_effect=PermissionError('Synthetic locked folder')):
            with self.assertRaisesRegex(PermissionError, 'Synthetic locked folder'):
                gi.promote_import(self.stage, self.target, self.receipt, self.data)
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.target.exists())
        gi.promote_import(self.stage, self.target, self.receipt, self.data)
        self.assertTrue(self.target.is_dir())

    def test_preexisting_foreign_record_or_game_data_are_preserved(self):
        self.receipt.write_bytes(b'preserve unrelated metadata')
        with self.assertRaisesRegex(ValueError, 'bestaan al'):
            gi.promote_import(self.stage, self.target, self.receipt, self.data)
        self.assertEqual(self.receipt.read_bytes(), b'preserve unrelated metadata')
        self.receipt.unlink()
        self.target.mkdir()
        (self.target / 'save.txt').write_bytes(b'preserve existing user data')
        with self.assertRaisesRegex(ValueError, 'bestaan al'):
            gi.promote_import(self.stage, self.target, self.receipt, self.data)
        self.assertEqual((self.target / 'save.txt').read_bytes(), b'preserve existing user data')

    def test_source_imports_i_and_ii_do_not_publish_after_receipt_write_error(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'fixture.txt').write_bytes(b'preserve source fixture')
        expected = {'source_tree_sha256': '0' * 64}
        for game in ('a2racer1', 'a2racer2'):
            with self.subTest(game=game):
                with patch.object(gi, 'inspect_installation', return_value=expected), \
                        patch.object(gi.json, 'dump', side_effect=OSError('Synthetic metadata write denied')):
                    with self.assertRaisesRegex(OSError, 'Synthetic metadata write denied'):
                        gi.import_installation(self.root, source, game)
                self.assertFalse((self.root / 'local/games' / game).exists())
                self.assertEqual((source / 'fixture.txt').read_bytes(), b'preserve source fixture')
        self.assertEqual(list((self.root / 'local/games').iterdir()), [])
        self.assertEqual(list((self.root / 'local/launcher').iterdir()), [])

    def test_source_import_iii_keeps_metadata_failure_before_final_game_path(self):
        source = self.root / 'source'
        source.mkdir()
        fixture = source / 'fixture.txt'
        fixture.write_bytes(b'preserve third source fixture')
        inspection = {'source_tree_sha256': '0' * 64,
                      'files': {'fixture.txt': {'source': fixture, 'bytes': fixture.stat().st_size,
                                               'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}}}
        with patch.object(iii, 'inspect', return_value=inspection), \
                patch.object(iii.native, 'local_movie_path'), patch.object(iii.native, 'check_folder'), \
                patch.object(gi.json, 'dump', side_effect=OSError('Synthetic III metadata denied')):
            with self.assertRaisesRegex(OSError, 'Synthetic III metadata denied'):
                iii.import_folder(self.root, source, 1)
        self.assertFalse(iii.native.game_folder(self.root, 1).exists())
        self.assertEqual(list((self.root / 'local/launcher').iterdir()), [])
        self.assertEqual(fixture.read_bytes(), b'preserve third source fixture')


if __name__ == '__main__':
    unittest.main()
