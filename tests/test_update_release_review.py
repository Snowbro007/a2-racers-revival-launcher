"""Synthetic metadata/bytes only. Never execute an MSI or launcher."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.create_update_review import create_review
from tools.windows.msi.verify_app_install import preflight


class ReleaseReviewTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='release-review-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'A2-Racers-Revival-0.1.6-beta6.msi'
        self.path.write_bytes(bytes.fromhex('d0cf11e0a1b11ae1') + b'Synthetic text only; never execute')
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.build = {'version': '0.1.0-beta.6', 'file': self.path.name, 'sha256': digest,
                      'launcher_sha256': '1' * 64, 'games_bundled': False,
                      'source_payload_cabinet_and_database_verified': True,
                      'synthetic_tests_passed': True, 'text_fixture_installer_lifecycle_verified': True}
        self.smoke = {'msi_sha256': digest, 'launcher_sha256': '1' * 64, 'complete': True,
                      'first-run_verified': True, 'cached-run_verified': True,
                      'bundled_runtimes_verified': True, 'user_data_and_cache_preserved': True,
                      'game_executed': False, 'native_helper_executed': False}

    def test_approval_is_explicit_and_tied_to_exact_bytes_and_app(self):
        review = create_review(self.path, self.build, self.smoke, approved=True)
        self.assertEqual(set(review), {'schema', 'product', 'version', 'file', 'sha256', 'bytes', 'games_bundled', 'update_approved'})
        self.assertTrue(review['update_approved'])
        with self.assertRaises(ValueError):
            create_review(self.path, self.build, self.smoke, approved=False)
        self.path.write_bytes(self.path.read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            create_review(self.path, self.build, self.smoke, approved=True)

    def test_incomplete_or_different_app_evidence_cannot_approve(self):
        for key in self.smoke:
            bad = copy.deepcopy(self.smoke)
            bad[key] = not bad[key] if isinstance(bad[key], bool) else 'wrong'
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_review(self.path, self.build, bad, approved=True)
        for key in ('games_bundled', 'synthetic_tests_passed', 'source_payload_cabinet_and_database_verified'):
            bad = {**self.build, key: not self.build[key]}
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_review(self.path, bad, self.smoke, approved=True)

    def test_app_probe_refuses_wrong_product_or_custom_actions_before_installing(self):
        plan = {'output': str(self.path), 'product_code': '{SYNTHETIC}',
                'upgrade_code': '{8630F56B-38D8-5D0E-A1C1-E17B6DC9C84D}',
                'tables': [{'name': 'Property', 'rows': [['ProductCode', '{SYNTHETIC}']]}]}
        result = {'sha256': self.build['sha256']}
        preflight(plan, result)
        for key, value in (('upgrade_code', '{OTHER}'), ('product_code', '{DIFFERENT}'),
                           ('tables', plan['tables'] + [{'name': 'CustomAction'}])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                preflight({**plan, key: value}, result)
        with self.assertRaises(ValueError):
            preflight(plan, {'sha256': '0' * 64})


if __name__ == '__main__':
    unittest.main()
