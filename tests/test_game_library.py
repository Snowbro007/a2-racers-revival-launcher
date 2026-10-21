"""Optional input-library behavior with synthetic files only; no game execution."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import game_library as library
from tools import launcher_model


class GameLibraryTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='game-library-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'Launcher proef'
        self.root.mkdir()

    def test_describe_missing_games_is_readonly_and_explicit(self):
        value = library.describe_library(self.root)
        self.assertEqual(value['schema'], 1)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(value['root_path'], str(self.root / 'Gamebestanden'))
        for game, item in value['games'].items():
            self.assertFalse(item['imported'])
            self.assertIsNone(item['source_path'])
            self.assertEqual(item['source_kind'], 'none')
            self.assertIn('Nog geen game', item['note'])
            self.assertEqual(item['managed_path'], str(self.root / 'local/games' / game))

    def test_explicit_folder_action_creates_instructions_without_importing(self):
        value = library.ensure_game_folder(self.root, 'a2racer2')
        self.assertEqual(value['path'], str(self.root / 'Gamebestanden/A2 Racer II'))
        self.assertEqual(len(value['created_help_files']), 3)
        self.assertFalse(value['game_imported'])
        self.assertFalse(value['game_started'])
        self.assertFalse((self.root / 'local').exists())
        for relative in ('', 'A2 Racer I', 'A2 Racer II'):
            text = (self.root / 'Gamebestanden' / relative / 'LEESMIJ.txt').read_text(encoding='utf-8')
            self.assertIn('geen games', text)
            self.assertIn('nog niet toe', text)

    def test_existing_user_files_and_help_are_preserved_and_not_autoimported(self):
        folder = self.root / 'Gamebestanden/A2 Racer I'
        folder.mkdir(parents=True)
        archive = folder / 'eigen-archief.zip'
        archive.write_bytes(b'synthetic user-owned archive, never opened')
        help_file = folder / 'LEESMIJ.txt'
        help_file.write_text('Mijn eigen uitleg', encoding='utf-8')
        value = library.ensure_game_folder(self.root, 'a2racer1')
        self.assertEqual(help_file.read_text(encoding='utf-8'), 'Mijn eigen uitleg')
        self.assertEqual(archive.read_bytes(), b'synthetic user-owned archive, never opened')
        self.assertNotIn(str(help_file), value['created_help_files'])
        self.assertEqual(library.ensure_game_folder(self.root, 'a2racer1')['created_help_files'], [])
        self.assertFalse(library.describe_library(self.root)['games']['a2racer1']['imported'])
        self.assertFalse((self.root / 'local').exists())

    def test_file_conflict_is_rejected_before_creating_other_folders(self):
        folder = self.root / 'Gamebestanden'
        folder.mkdir()
        conflict = folder / 'A2 Racer II'
        conflict.write_bytes(b'preserve this file')
        with self.assertRaises(ValueError):
            library.ensure_game_folder(self.root, 'a2racer1')
        self.assertFalse((folder / 'A2 Racer I').exists())
        self.assertEqual(conflict.read_bytes(), b'preserve this file')

    def test_root_file_and_help_directory_conflicts_preserve_originals(self):
        root_file = self.root / 'Gamebestanden'
        root_file.write_bytes(b'preserve')
        with self.assertRaises(ValueError):
            library.ensure_game_folder(self.root, 'a2racer1')
        self.assertEqual(root_file.read_bytes(), b'preserve')
        root_file.unlink()
        (root_file / 'LEESMIJ.txt').mkdir(parents=True)
        with self.assertRaises(ValueError):
            library.ensure_game_folder(self.root, 'a2racer1')
        self.assertTrue((root_file / 'LEESMIJ.txt').is_dir())
        self.assertFalse((root_file / 'A2 Racer I').exists())

    def test_snapshot_source_is_display_data_and_is_not_followed(self):
        managed = self.root / 'local/games/a2racer1'
        managed.mkdir(parents=True)
        receipts = self.root / 'local/launcher'
        receipts.mkdir()
        missing_source = Path(self.temporary.name) / 'Eigen onbeschikbare installatie'
        (receipts / 'installation.json').write_text(json.dumps({
            'schema': 1, 'game': 'a2racer1', 'source_path': str(missing_source),
            'source_unchanged': True}), encoding='utf-8')
        item = library.describe_library(self.root)['games']['a2racer1']
        self.assertTrue(item['imported'])
        self.assertEqual(item['source_kind'], 'installation')
        self.assertEqual(item['source_path'], str(missing_source))
        self.assertFalse(missing_source.exists())
        self.assertFalse((self.root / 'Gamebestanden').exists())

    def test_archive_and_legacy_managed_sources_are_distinguished(self):
        (self.root / 'local/games/a2racer1').mkdir(parents=True)
        (self.root / 'local/games/a2racer2').mkdir()
        media = self.root / 'local/media/a2racer2'
        media.mkdir(parents=True)
        archive = Path(self.temporary.name) / 'eigen.zip'
        (media / 'extraction.json').write_text(json.dumps({
            'game': 'a2racer2', 'archive': str(archive)}), encoding='utf-8')
        items = library.describe_library(self.root)['games']
        self.assertEqual(items['a2racer1']['source_kind'], 'managed')
        self.assertEqual(items['a2racer2']['source_kind'], 'archive')
        self.assertEqual(items['a2racer2']['source_path'], str(archive))

    def test_bad_optional_receipt_does_not_fail_other_games(self):
        (self.root / 'local/games/a2racer1').mkdir(parents=True)
        folder = self.root / 'local/launcher'
        folder.mkdir()
        for raw in (b'not json', b'x' * (library.MAX_RECEIPT_BYTES + 1), b'[]'):
            with self.subTest(raw_length=len(raw)):
                (folder / 'installation.json').write_bytes(raw)
                value = library.describe_library(self.root)
                self.assertFalse(value['games']['a2racer1']['folder_available'])
                self.assertTrue(value['games']['a2racer1']['imported'])
                self.assertTrue(value['games']['a2racer2']['folder_available'])
                self.assertIsNone(value['games']['a2racer1']['source_path'])

    def test_relative_or_control_character_source_is_not_presented_as_path(self):
        (self.root / 'local/games/a2racer1').mkdir(parents=True)
        receipts = self.root / 'local/launcher'
        receipts.mkdir()
        for source in ('../other', 'https://example.invalid', str(self.root) + '\ncommand'):
            with self.subTest(source=source):
                (receipts / 'installation.json').write_text(json.dumps({
                    'schema': 1, 'game': 'a2racer1', 'source_path': source}), encoding='utf-8')
                item = library.describe_library(self.root)['games']['a2racer1']
                self.assertIsNone(item['source_path'])
                self.assertEqual(item['source_kind'], 'managed')

    def test_linked_optional_folder_is_not_followed_or_used_for_writes(self):
        outside = Path(self.temporary.name) / 'outside'
        outside.mkdir()
        try:
            (self.root / 'Gamebestanden').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest('Synthetic symlink unavailable: ' + str(exc))
        with self.assertRaises(ValueError):
            library.ensure_game_folder(self.root, 'a2racer1')
        self.assertEqual(list(outside.iterdir()), [])
        value = library.describe_library(self.root)
        self.assertFalse(value['games']['a2racer1']['folder_available'])

    def test_unknown_game_and_missing_root_never_create_folders(self):
        for game in ('a2racer3', '../../other', '', 'A2 Racer I'):
            with self.subTest(game=game), self.assertRaises(ValueError):
                library.ensure_game_folder(self.root, game)
        missing = self.root / 'missing'
        with self.assertRaises(ValueError):
            library.ensure_game_folder(missing, 'a2racer1')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_creation_permission_failure_is_reported_without_game_activity(self):
        with patch.object(Path, 'mkdir', side_effect=PermissionError('synthetic read-only folder')):
            with self.assertRaises(PermissionError):
                library.ensure_game_folder(self.root, 'a2racer1')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_model_command_returns_only_fixed_folder_for_selected_game(self):
        stdout = io.StringIO()
        with patch.object(launcher_model, 'ROOT', self.root), patch.object(
                os.sys, 'argv', ['launcher_model.py', 'game-library-folder', '--game', 'a2racer2']), patch(
                    'sys.stdout', stdout):
            self.assertEqual(launcher_model.main(), 0)
        value = json.loads(stdout.getvalue())
        self.assertEqual(value['path'], str(self.root / 'Gamebestanden/A2 Racer II'))
        self.assertFalse(value['game_started'])
        self.assertFalse((self.root / 'local').exists())


if __name__ == '__main__':
    unittest.main()
