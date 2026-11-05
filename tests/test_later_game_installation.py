"""Synthetic owned-file imports: no original game data or executable starts."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from tools import later_game_installation as install


class LaterInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='later-owned-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'launcher'; self.root.mkdir()
        self.profiles = {}; self.payloads = {}
        for game, parent in install.PARENTS.items():
            payload = {parent: ('synthetic parent ' + game).encode(),
                       'MENU.EXE': ('synthetic menu ' + game).encode(),
                       'SPEL.DAT': ('synthetic race ' + game).encode(),
                       'GAME.INI': b'[game]\noriginal=1\n', 'RASER.INI': b'[render]\nsize=0\n',
                       'MENU.INI': b'[menu]\nintro=1\n', 'INTRO1.MPG': b'synthetic video',
                       'ASSETS/ROAD.DSO': b'original synthetic road', 'EMPTY.DAT': b''}
            files = [{'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                     for name, raw in sorted(payload.items(), key=lambda r: r[0].casefold())]
            self.profiles[game] = {'version': 'synthetic-nl', 'parent': parent,
                'files': files, 'core_pins': {r['path']: r['sha256'] for r in files if r['path'] in (parent, 'MENU.EXE', 'SPEL.DAT')}}
            self.payloads[game] = payload
        self.profile_patch = patch.object(install, '_profile', side_effect=lambda game: copy.deepcopy(self.profiles[game]))
        self.profile_patch.start(); self.addCleanup(self.profile_patch.stop)

    def folder(self, game='vakantieracer', layout='flat', suffix=''):
        source = self.base / ('owned-' + game + '-' + layout + suffix); source.mkdir()
        for name, raw in self.payloads[game].items():
            prefix = 'DATA/MENUDATA/' if layout == 'disc' and name in ('MENU.EXE', 'MENU.INI') else ('DATA/' if layout == 'disc' else '')
            path = source / (prefix + name); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        return source

    def archive(self, game='vakantieracer', layout='flat', prefix='', extras=()):
        path = self.base / ('owned-' + game + '-' + layout + '.zip')
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for name, raw in self.payloads[game].items():
                inside = 'DATA/MENUDATA/' + name if layout == 'disc' and name in ('MENU.EXE', 'MENU.INI') else ('DATA/' + name if layout == 'disc' else name)
                output.writestr(prefix + inside, raw)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)  # Intentional duplicate-name fixture.
                for name, raw in extras: output.writestr(name, raw)
        return path

    def managed(self, game='vakantieracer'):
        return self.root / 'local/games' / game / 'original'

    def assert_no_import(self, game='vakantieracer'):
        self.assertFalse(self.managed(game).exists())
        self.assertFalse((self.root / 'local/launcher' / ('installation-' + game + '.json')).exists())
        self.assertFalse(list(self.root.rglob('.original-import-*')))

    def test_both_games_import_flat_or_disc_layout_and_leave_source_untouched(self):
        for game in install.PARENTS:
            for layout in ('flat', 'disc'):
                with self.subTest(game=game, layout=layout):
                    self.root = self.base / ('launcher-' + game + '-' + layout); self.root.mkdir()
                    source = self.folder(game, layout)
                    before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()}
                    result = install.import_installation(self.root, source, game)
                    self.assertTrue(result['ready']); self.assertTrue(result['game_imported'])
                    self.assertFalse(result['game_started']); self.assertTrue(result['source_unchanged'])
                    self.assertEqual(result['source_path'], str(self.managed(game)))
                    self.assertEqual(result['parent'], install.PARENTS[game])
                    self.assertEqual({p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()}, before)
                    self.assertEqual({p.relative_to(self.managed(game)).as_posix(): p.read_bytes() for p in self.managed(game).rglob('*') if p.is_file()}, self.payloads[game])

    def test_complete_zip_accepts_single_wrapper_folder_and_preserves_archive(self):
        for game, layout in (('a2racer4', 'flat'), ('vakantieracer', 'disc')):
            with self.subTest(game=game):
                archive = self.archive(game, layout, 'My own game/')
                before = archive.read_bytes()
                result = install.import_archive(self.root, archive, game)
                self.assertTrue(result['ready']); self.assertEqual(result['files'], self.profiles[game]['files'])
                self.assertEqual(archive.read_bytes(), before)

    def test_disc_installer_executable_is_excluded_but_unknown_payload_code_is_rejected(self):
        source = self.folder(layout='disc'); (source / 'SETUP.EXE').write_bytes(b'not executed or copied')
        install.import_installation(self.root, source, 'vakantieracer')
        self.assertFalse((self.managed() / 'SETUP.EXE').exists())
        self.root = self.base / 'launcher-bad'; self.root.mkdir()
        source = self.folder(layout='flat'); (source / 'mod.dll').write_bytes(b'untrusted')
        with self.assertRaisesRegex(ValueError, 'Onbekende uitvoerbare'):
            install.import_installation(self.root, source, 'vakantieracer')
        self.assert_no_import()

    def test_missing_and_same_size_changed_core_or_asset_are_rejected_before_publication(self):
        for index, name in enumerate(('SPEL.DAT', 'ASSETS/ROAD.DSO', 'MENU.INI')):
            with self.subTest(name=name):
                source = self.folder(suffix=str(index)); path = source / name
                path.write_bytes(b'X' * len(path.read_bytes()))
                with self.assertRaisesRegex(ValueError, 'gameversie'):
                    install.import_installation(self.root, source, 'vakantieracer')
                self.assert_no_import()
        source = self.folder(suffix='missing'); (source / 'INTRO1.MPG').unlink()
        with self.assertRaises(ValueError): install.import_installation(self.root, source, 'vakantieracer')
        self.assert_no_import()

    def test_source_change_during_copy_is_refused_and_only_owned_stage_is_cleaned(self):
        source = self.folder(); real = install._stream_file; changed = False
        def mutate(path, **kwargs):
            nonlocal changed
            result = real(path, **kwargs)
            if kwargs.get('target') is not None and not changed:
                changed = True; path.write_bytes(b'X' * path.stat().st_size)
            return result
        with patch.object(install, '_stream_file', side_effect=mutate), self.assertRaises(ValueError):
            install.import_installation(self.root, source, 'vakantieracer')
        self.assert_no_import(); self.assertTrue(source.is_dir())

    def test_existing_original_or_receipt_is_not_overwritten(self):
        source = self.folder(); destination = self.managed(); destination.mkdir(parents=True)
        marker = destination / 'keep.txt'; marker.write_bytes(b'keep')
        with self.assertRaises(ValueError): install.import_installation(self.root, source, 'vakantieracer')
        self.assertEqual(marker.read_bytes(), b'keep')
        self.root = self.base / 'launcher-receipt'; self.root.mkdir()
        receipt = self.root / 'local/launcher/installation-vakantieracer.json'; receipt.parent.mkdir(parents=True); receipt.write_bytes(b'keep receipt')
        with self.assertRaises(ValueError): install.import_installation(self.root, source, 'vakantieracer')
        self.assertEqual(receipt.read_bytes(), b'keep receipt')

    def test_receipt_write_failure_leaves_no_published_original_or_owned_record(self):
        source = self.folder()
        with patch('tools.game_installation.os.fsync', side_effect=OSError('synthetic full disk')), self.assertRaises(OSError):
            install.import_installation(self.root, source, 'vakantieracer')
        self.assert_no_import()

    def test_competing_destination_is_preserved_and_only_our_stage_is_cleaned(self):
        source = self.folder(); real = install.promote_import
        def compete(stage, destination, receipt, data, **kwargs):
            destination.mkdir(); (destination / 'keep.txt').write_bytes(b'competing data')
            return real(stage, destination, receipt, data, **kwargs)
        with patch.object(install, 'promote_import', side_effect=compete), self.assertRaises(ValueError):
            install.import_installation(self.root, source, 'vakantieracer')
        self.assertEqual((self.managed() / 'keep.txt').read_bytes(), b'competing data')
        self.assertFalse(list(self.root.rglob('.original-import-*')))
        self.assertFalse((self.root / 'local/launcher/installation-vakantieracer.json').exists())

    def test_selecting_data_directory_itself_is_also_a_supported_layout(self):
        source = self.folder(layout='disc') / 'DATA'
        self.assertTrue(install.import_installation(self.root, source, 'vakantieracer')['ready'])

    def test_quick_status_uses_stats_but_full_check_detects_same_size_tamper(self):
        install.import_installation(self.root, self.folder(), 'vakantieracer')
        with patch.object(install, '_stream_file', side_effect=AssertionError('No game content hash at startup')):
            self.assertTrue(install.status(self.root, 'vakantieracer')['ready'])
        target = self.managed() / 'SPEL.DAT'; target.write_bytes(b'X' * target.stat().st_size)
        self.assertTrue(install.status(self.root, 'vakantieracer')['ready'])
        with self.assertRaises(ValueError): install.check(self.root, 'vakantieracer')

    def test_missing_or_edited_receipt_and_extra_managed_file_are_not_ready(self):
        self.assertFalse(install.status(self.root, 'vakantieracer')['ready'])
        install.import_installation(self.root, self.folder(), 'vakantieracer')
        extra = self.managed() / 'unexpected.txt'; extra.write_bytes(b'changed')
        self.assertFalse(install.status(self.root, 'vakantieracer')['ready']); extra.unlink()
        receipt = self.root / 'local/launcher/installation-vakantieracer.json'
        data = json.loads(receipt.read_text()); data['source_path'] = str(self.base / 'arbitrary')
        receipt.write_text(json.dumps(data))
        self.assertFalse(install.status(self.root, 'vakantieracer')['source_ready'])

    def test_managed_receipt_survives_launcher_directory_move(self):
        install.import_installation(self.root, self.folder(), 'vakantieracer')
        moved = self.base / 'moved-launcher'; self.root.rename(moved); self.root = moved
        self.assertEqual(install.check(self.root, 'vakantieracer')['source_path'], str(self.managed()))

    def test_unknown_game_and_overlapping_source_are_rejected_without_source_reads(self):
        with patch.object(install, '_profile', side_effect=AssertionError('No metadata read')):
            for game in ('a2racer2', '../a2racer4', True, ['vakantieracer']):
                with self.subTest(game=game), self.assertRaises(ValueError): install.import_installation(self.root, self.base, game)
        with self.assertRaisesRegex(ValueError, 'overlappen'):
            install.import_installation(self.root, self.root, 'vakantieracer')
        with self.assertRaises(ValueError): install.check(self.root, 'vakantieracer', full=1)

    def test_hardlinked_source_file_is_rejected(self):
        source = self.folder(); original = source / 'SPEL.DAT'; linked = self.base / 'linked-race'
        try: os.link(original, linked)
        except OSError as error: self.skipTest(str(error))
        with self.assertRaisesRegex(ValueError, 'hardlink'):
            install.import_installation(self.root, source, 'vakantieracer')
        self.assert_no_import()

    def test_linked_source_directory_is_rejected_without_traversal(self):
        source = self.folder(); link = source / 'linked'
        try: link.symlink_to(self.base, target_is_directory=True)
        except OSError as error: self.skipTest(str(error))
        with self.assertRaises(ValueError): install.import_installation(self.root, source, 'vakantieracer')
        self.assert_no_import()

    def test_zip_unsafe_paths_duplicate_names_case_clashes_and_file_parents_are_refused(self):
        bad = ['../escape.txt', '/root.txt', 'C:/escape.txt', 'DATA/back\\slash', 'NUL.txt',
               'MENU.EXE:stream', 'trail. ', 'DATA/../escape.txt']
        for name in bad:
            with self.subTest(name=name):
                archive = self.archive(extras=[(name, b'bad')])
                with self.assertRaises(ValueError): install.import_archive(self.root, archive, 'vakantieracer')
                self.assert_no_import()
        for extras in ([('MENU.EXE', b'duplicate')], [('menu.exe', b'case clash')],
                       [('Dir/a', b'a'), ('dir/b', b'b')], [('node', b'x'), ('node/child', b'y')]):
            archive = self.archive(extras=extras)
            with self.assertRaises(ValueError): install.import_archive(self.root, archive, 'vakantieracer')
            self.assert_no_import()

    def test_zip_symlink_and_unix_link_metadata_are_refused(self):
        for kind in ('symlink', 'unix-extra'):
            info = zipfile.ZipInfo('linked.txt'); info.create_system = 3
            if kind == 'symlink': info.external_attr = (stat.S_IFLNK | 0o777) << 16
            else: info.extra = b'\x6e\x75\x04\x00link'
            archive = self.archive(extras=[(info, b'../elsewhere')])
            with self.assertRaises(ValueError): install.import_archive(self.root, archive, 'vakantieracer')
            self.assert_no_import()

    def test_zip_changed_payload_and_expansion_limit_leave_no_partial_import(self):
        archive = self.archive(extras=[('extra.txt', b'x' * 1024)])
        with patch.object(install, 'MAX_FILE_BYTES', 100), self.assertRaises(ValueError):
            install.import_archive(self.root, archive, 'vakantieracer')
        self.assert_no_import()

    def test_encrypted_corrupt_and_truncated_zip_never_publish_game_data(self):
        archive = self.archive(); raw = bytearray(archive.read_bytes())
        central = raw.index(b'PK\x01\x02'); raw[central + 8] |= 1
        archive.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'versleutelde'):
            install.import_archive(self.root, archive, 'vakantieracer')
        self.assert_no_import()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as output:
            for name, data in self.payloads['vakantieracer'].items(): output.writestr(name, data)
        raw = archive.read_bytes(); self.assertIn(b'synthetic video', raw)
        archive.write_bytes(raw.replace(b'synthetic video', b'X' * len(b'synthetic video'), 1))
        with self.assertRaises(ValueError): install.import_archive(self.root, archive, 'vakantieracer')
        self.assert_no_import()
        archive.write_bytes(b'PK\x03\x04truncated')
        with self.assertRaises(ValueError): install.import_archive(self.root, archive, 'vakantieracer')
        self.assert_no_import()
        self.payloads['vakantieracer']['SPEL.DAT'] = b'wrong exact game bytes'
        archive = self.archive()
        with self.assertRaises(ValueError): install.import_archive(self.root, archive, 'vakantieracer')
        self.assert_no_import()

    def test_public_metadata_contains_only_relative_content_records_and_known_core_pins(self):
        self.profile_patch.stop()
        try:
            for game, count in (('a2racer4', 135), ('vakantieracer', 374)):
                value = install._profile(game)
                self.assertEqual(len(value['files']), count); self.assertEqual(value['parent'], install.PARENTS[game])
                for row in value['files']:
                    self.assertEqual(set(row), {'path', 'size', 'sha256'})
                    self.assertNotIn('DATA/', row['path']); self.assertFalse(Path(row['path']).is_absolute())
            raw = (install.ROOT / install.METADATA).read_text()
            self.assertNotIn('reports/', raw); self.assertNotIn('C:/Users/', raw); self.assertNotIn('archive', raw)
        finally: self.profile_patch.start()


if __name__ == '__main__': unittest.main()
