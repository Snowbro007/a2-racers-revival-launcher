"""Synthetic lifecycle orchestration guards; never invoke Windows Installer."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.windows.msi import build_msi as builder
from tools.windows.msi import verify_lifecycle as trial


class LifecycleTests(unittest.TestCase):
    def test_msiexec_property_quoting_keeps_spaces_and_unicode_inside_the_value(self):
        target = r'C:\test & fixtures\gekozen map - é'
        command = trial.msi_command(Path('msiexec.exe'), ['/i', r'C:\test build\fixture.msi'],
                                    Path('install.log'), {'INSTALLDIR': target})
        self.assertIn('INSTALLDIR="' + target + '"', command)
        self.assertNotIn('"INSTALLDIR=', command)
        self.assertIn('"C:\\test build\\fixture.msi"', command)
        for invalid in ('quote"value', 'line\nvalue', 'nul\x00value'):
            with self.assertRaises(ValueError):
                trial.msi_command(Path('msiexec.exe'), [], Path('log'), {'INSTALLDIR': invalid})

    def test_identity_is_unique_and_does_not_use_the_live_product_registry(self):
        first = trial.identity('a' * 32)
        second = trial.identity('b' * 32)
        self.assertNotEqual(first['UPGRADE_CODE'], builder.UPGRADE_CODE)
        self.assertNotEqual(first['UPGRADE_CODE'], second['UPGRADE_CODE'])
        self.assertNotEqual(first['INSTALLER_REGISTRY_KEY'], builder.INSTALLER_REGISTRY_KEY)
        self.assertTrue(first['INSTALLER_REGISTRY_KEY'].startswith('Software\\A2 Revival Installer Tests\\'))
        for token in ('', '../escape', 'A' * 32, 'z' * 32):
            with self.assertRaises(ValueError):
                trial.identity(token)

    def test_payload_is_only_versioned_text_without_user_data_or_machine_code(self):
        name = trial.identity('c' * 32)['NAME']
        first = trial.fixture_files(name, '0.1.5')
        second = trial.fixture_files(name, '0.1.6')
        self.assertEqual(set(first), {name + '.exe', 'app/tools/fixture.txt'})
        self.assertTrue(all(not data.startswith(b'MZ') for data in first.values()))
        self.assertTrue(all(first[path] != second[path] for path in first))

    def test_synthetic_plan_has_a_separate_identity_and_no_payload_execution(self):
        identity = trial.identity('d' * 32)
        with patch.multiple(builder, **identity):
            plan = builder.build_plan(trial.fixture_files(identity['NAME'], '0.1.5'), Path('stage'), Path('icon'), '0.1.5')
        self.assertNotEqual(plan['upgrade_code'], builder.UPGRADE_CODE)
        self.assertFalse(any(table['name'] in ('CustomAction', 'RemoveFile') for table in plan['tables']))
        registry = next(table['rows'] for table in plan['tables'] if table['name'] == 'Registry')
        self.assertTrue(all(row[1] == 1 and (row[2] == identity['INSTALLER_REGISTRY_KEY']
                                           or row[2].startswith(identity['INSTALLER_REGISTRY_KEY'] + chr(92)))
                            for row in registry))

    def test_output_claim_preserves_existing_data_and_rejects_escape(self):
        parent = trial.ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            with patch.object(trial, 'ROOT', root):
                output = root / 'local/installer-validation/new'
                self.assertEqual(trial.claim_output(output), output.absolute())
                (output / 'keep.txt').write_text('preserve')
                with self.assertRaises(FileExistsError):
                    trial.claim_output(output)
                with self.assertRaises(ValueError):
                    trial.claim_output(root / 'elsewhere')
                with self.assertRaises(ValueError):
                    trial.claim_output(root / 'local/installer-validation/../escape')
                self.assertEqual((output / 'keep.txt').read_text(), 'preserve')
