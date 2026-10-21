"""Interrupted extraction uses text-only fixtures; no runtime/game is executed."""
from pathlib import Path
import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import portable_test as pt


ROOT = Path(__file__).resolve().parents[1]


class AtomicRuntimeExtractionTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='runtime-atomic-', dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        if os.name == 'nt':
            cleanup_root = self.root.resolve()
            cleanup_root.relative_to(parent.resolve())
            temporary.name = '\\\\?\\' + str(cleanup_root)
        self.archive = self.root / 'synthetic.zip'
        self.contents = {'nested/first.txt': b'first text fixture',
                         'nested/second.txt': b'second text fixture'}
        with zipfile.ZipFile(self.archive, 'x') as archive:
            for name, data in self.contents.items():
                archive.writestr(name, data)
        self.archive_bytes = self.archive.read_bytes()
        self.pin = hashlib.sha256(self.archive_bytes).hexdigest()
        self.target = self.root / 'runtime'

    def assert_no_staging(self):
        self.assertEqual(list(self.root.glob('.runtime-extract-*')), [])

    def assert_contents(self):
        for name, data in self.contents.items():
            self.assertEqual((self.target / name).read_bytes(), data)
        self.assertEqual(self.archive.read_bytes(), self.archive_bytes)

    def test_interrupted_copy_keeps_live_path_absent_and_retry_succeeds(self):
        original_copy = pt.shutil.copyfileobj
        count = 0

        def interrupted(source, output, length):
            nonlocal count
            count += 1
            if count == 2:
                output.write(b'partial')
                raise OSError('Synthetic disk interruption')
            original_copy(source, output, length)

        with patch.object(pt.shutil, 'copyfileobj', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'Synthetic disk interruption'):
                pt.extract_verified(self.archive, self.pin, self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_staging()
        pt.extract_verified(self.archive, self.pin, self.target)
        pt.extract_verified(self.archive, self.pin, self.target)
        self.assert_contents()

    def test_corrupted_staging_is_not_published(self):
        def corrupted(source, output, length):
            output.write(b'corrupt text fixture')

        with patch.object(pt.shutil, 'copyfileobj', side_effect=corrupted):
            with self.assertRaisesRegex(ValueError, 'gewijzigd'):
                pt.extract_verified(self.archive, self.pin, self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_failed_promotion_leaves_no_partial_runtime_and_retry_succeeds(self):
        with patch.object(Path, 'rename', side_effect=PermissionError('Synthetic locked folder')):
            with self.assertRaisesRegex(PermissionError, 'Synthetic locked folder'):
                pt.extract_verified(self.archive, self.pin, self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_staging()
        pt.extract_verified(self.archive, self.pin, self.target)
        self.assert_contents()

    def test_existing_incomplete_and_foreign_files_are_preserved(self):
        self.target.mkdir()
        (self.target / 'personal.txt').write_bytes(b'preserve unrelated data')
        with self.assertRaisesRegex(ValueError, 'afwijkende bestanden'):
            pt.extract_verified(self.archive, self.pin, self.target)
        self.assertEqual((self.target / 'personal.txt').read_bytes(), b'preserve unrelated data')
        self.assertEqual(list(self.target.iterdir()), [self.target / 'personal.txt'])
        self.assert_no_staging()

    def test_windows_sharing_error_retries_only_after_rechecking_unchanged_tree(self):
        rename = Path.rename
        calls = []
        error = PermissionError('Synthetic transient sharing error')
        error.winerror = 32

        def transient(stage, target):
            calls.append((stage, target))
            if len(calls) == 1:
                raise error
            return rename(stage, target)

        with patch.object(Path, 'rename', autospec=True, side_effect=transient), patch.object(pt.time, 'sleep') as wait:
            pt.extract_verified(self.archive, self.pin, self.target)
        self.assertEqual(len(calls), 2)
        wait.assert_called_once_with(0.05)
        self.assert_contents()

    def test_persistent_windows_access_failure_is_bounded_and_not_reported_as_success(self):
        error = PermissionError('Synthetic persistent Windows access error')
        error.winerror = 5
        with patch.object(Path, 'rename', side_effect=error) as rename, patch.object(pt.time, 'sleep') as wait:
            with self.assertRaisesRegex(PermissionError, 'persistent Windows access'):
                pt.extract_verified(self.archive, self.pin, self.target)
        self.assertEqual(rename.call_count, 5)
        self.assertAlmostEqual(sum(call.args[0] for call in wait.call_args_list), 0.75)
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_destination_appearing_during_retry_is_checked_and_never_overwritten(self):
        error = PermissionError('Synthetic sharing error')
        error.winerror = 33

        def foreign_destination(stage, target):
            target.mkdir()
            (target / 'personal.txt').write_bytes(b'preserve foreign destination')
            raise error

        with patch.object(Path, 'rename', autospec=True, side_effect=foreign_destination) as rename, patch.object(pt.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'afwijkende bestanden'):
                pt.extract_verified(self.archive, self.pin, self.target)
        self.assertEqual(rename.call_count, 1)
        self.assertEqual((self.target / 'personal.txt').read_bytes(), b'preserve foreign destination')
        self.assert_no_staging()

    def test_staging_changed_during_retry_is_never_published(self):
        error = PermissionError('Synthetic sharing error')
        error.winerror = 32

        def changed_staging(stage, target):
            (stage / 'nested/first.txt').write_bytes(b'changed text fixture')
            raise error

        with patch.object(Path, 'rename', autospec=True, side_effect=changed_staging) as rename, patch.object(pt.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'gewijzigd'):
                pt.extract_verified(self.archive, self.pin, self.target)
        self.assertEqual(rename.call_count, 1)
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_unknown_old_staging_folder_is_neither_reused_nor_removed(self):
        abandoned = self.root / '.runtime-extract-unowned'
        abandoned.mkdir()
        (abandoned / 'personal.txt').write_bytes(b'preserve unknown staging')
        pt.extract_verified(self.archive, self.pin, self.target)
        self.assert_contents()
        self.assertEqual((abandoned / 'personal.txt').read_bytes(), b'preserve unknown staging')

    def test_bad_archive_hash_creates_no_destination_or_staging(self):
        with self.assertRaisesRegex(ValueError, 'hash'):
            pt.extract_verified(self.archive, '0' * 64, self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_staging()


if __name__ == '__main__':
    unittest.main()
