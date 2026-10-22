"""Repacked ZIP recognition with synthetic ISO data, never original game code."""
import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import extract_disc, ii_archive_import as importer, portable_test
from tests.test_extract_disc import iso, raw_mode2


class IIArchiveImportTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix='ii-archive-', dir=parent)
        self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.iso = iso(); self.raw = raw_mode2(self.iso)
        self.pins = {self.sha(self.iso): {'size': len(self.iso), 'format': 'ISO2048'},
                     self.sha(self.raw): {'size': len(self.raw), 'format': 'MODE2/2352 Form1'}}
        patched = patch.object(importer, 'KNOWN_IMAGES', self.pins)
        patched.start(); self.addCleanup(patched.stop)

    @staticmethod
    def sha(raw): return hashlib.sha256(raw).hexdigest()

    def archive(self, name, member, raw, compression=zipfile.ZIP_DEFLATED):
        path = self.root/name
        with zipfile.ZipFile(path, 'w', compression=compression) as archive:
            archive.writestr(member, raw)
            archive.writestr('disc.cue', b'FILE "ignored.bin" BINARY\n')
            archive.writestr('unrelated.exe', b'synthetic unused text, never extracted')
        return path

    def test_supported_image_survives_changed_zip_name_prefix_comment_and_compression(self):
        names = [('A2-Racer-II_Win_NL.zip', 'A2 Racer II (Netherlands) (v1.01).bin', zipfile.ZIP_DEFLATED),
                 ('own-backup.zip', 'Game Files/NL v1.01.bin', zipfile.ZIP_STORED)]
        archives = []
        for name, member, method in names:
            source = self.archive(name, member, self.raw, method); before = source.read_bytes()
            result = importer.recognize_archive(source)
            self.assertEqual(result['sha256'], self.sha(self.raw)); self.assertEqual(result['member'], member)
            self.assertFalse(result['native_game_executed']); self.assertEqual(source.read_bytes(), before)
            archives.append(self.sha(before))
        self.assertNotEqual(*archives)
        self.assertFalse((self.root/'local').exists())

    def test_iso_export_is_also_recognized_by_bytes(self):
        result = importer.recognize_archive(self.archive('backup.zip', 'disc.iso', self.iso))
        self.assertEqual(result['format'], 'ISO2048'); self.assertEqual(result['sha256'], self.sha(self.iso))

    def test_renaming_another_image_to_supported_name_does_not_allow_it(self):
        for name, raw in (('wrong-version.zip', self.raw[:-1]+bytes([self.raw[-1] ^ 1])),
                          ('truncated.zip', self.raw[:-1])):
            with self.subTest(name=name):
                source = self.archive(name, 'A2 Racer II (Netherlands) (v1.01).bin', raw)
                with self.assertRaisesRegex(ValueError, 'niet herkend'): importer.recognize_archive(source)
        self.assertFalse((self.root/'local').exists())

    def test_multiple_images_and_missing_image_are_explained(self):
        for members in ({'one.bin': self.raw, 'two.iso': self.iso}, {'disc.cue': b'cue only'}):
            source = self.root/'bad.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                for name, raw in members.items(): archive.writestr(name, raw)
            with self.assertRaisesRegex(ValueError, 'precies'): importer.recognize_archive(source)

    def test_nrg_gets_a_specific_message_without_mounting_or_output(self):
        source = self.archive('nrg.zip', 'disc.nrg', b'synthetic nero image')
        with self.assertRaisesRegex(ValueError, 'NRG'): importer.recognize_archive(source)
        self.assertFalse((self.root/'local').exists())

    def test_linked_and_damaged_archive_are_rejected(self):
        source = self.root/'linked.zip'
        info = zipfile.ZipInfo('disc.bin'); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(source, 'w') as archive: archive.writestr(info, self.raw)
        with self.assertRaisesRegex(ValueError, 'gekoppelde'): importer.recognize_archive(source)
        source.write_bytes(b'synthetic damaged zip')
        with self.assertRaisesRegex(ValueError, 'beschadigd'): importer.recognize_archive(source)

    def test_import_repacked_image_extracts_only_game_and_keeps_other_game_and_original(self):
        source = self.archive('A2-Racer-II_Win_NL.zip', 'A2 Racer II (Netherlands) (v1.01).bin', self.raw)
        before = source.read_bytes(); root = self.root/'launcher'
        first = root/'local/games/a2racer1/save.txt'; first.parent.mkdir(parents=True); first.write_bytes(b'keep I')
        with patch('tools.ii_portable_prepare.inspect_source', return_value={'verified': True}) as inspect:
            result = portable_test.import_game(root, source, 'a2racer2')
        inspect.assert_called_once_with(root/'local/games/a2racer2')
        self.assertEqual(result['archive_recognition'], 'verified-disc-image')
        self.assertFalse(result['game_started']); self.assertEqual(result['disc_image_sha256'], self.sha(self.raw))
        self.assertEqual((root/'local/games/a2racer2/HELLO.TXT').read_bytes(), b'synthetic data\n')
        self.assertEqual(first.read_bytes(), b'keep I'); self.assertEqual(source.read_bytes(), before)
        self.assertFalse(list((root/'local').rglob('unrelated.exe')))

    def test_unknown_version_is_refused_before_any_output(self):
        source = self.archive('unknown.zip', 'disc.bin', b'wrong version')
        with patch.object(extract_disc, 'extract_archive') as extraction:
            with self.assertRaisesRegex(ValueError, 'niet herkend'):
                portable_test.import_game(self.root/'launcher', source, 'a2racer2')
        extraction.assert_not_called(); self.assertFalse((self.root/'launcher').exists())

    def test_image_substitution_between_recognition_and_extraction_cleans_only_staging(self):
        source = self.archive('changing.zip', 'disc.bin', self.raw)
        image = importer.recognize_archive(source)
        replacement = self.raw[:-1]+bytes([self.raw[-1] ^ 1])
        with zipfile.ZipFile(source, 'w') as archive: archive.writestr('disc.bin', replacement)
        output = self.root/'local'; output.mkdir(); keep = output/'keep.txt'; keep.write_bytes(b'keep')
        contract = {key: image[key] for key in ('member', 'size', 'sha256')}
        with self.assertRaisesRegex(ValueError, 'cd-image veranderde'):
            extract_disc.extract_archive(source, output, 'a2racer2', expected_image=contract)
        self.assertEqual(keep.read_bytes(), b'keep')
        self.assertEqual(list((output/'games').iterdir()), []); self.assertEqual(list((output/'media').iterdir()), [])

    def test_first_game_does_not_gain_unverified_archive_fallback(self):
        source = self.archive('first-game.zip', 'disc.bin', self.raw)
        with patch.object(importer, 'recognize_archive') as recognition:
            with self.assertRaisesRegex(ValueError, 'niet herkend'):
                portable_test.import_game(self.root/'launcher', source, 'a2racer1')
        recognition.assert_not_called(); self.assertFalse((self.root/'launcher').exists())


if __name__ == '__main__': unittest.main()
