"""Synthetic metadata/bytes only. Never execute an MSI or launcher."""
import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.create_update_review import create_review, main
from tools.windows.msi.verify_app_install import preflight, inspect_signature


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
        # Invented human declarations exercise validation only, never real approval.
        signature = {'status': 'Valid', 'thumbprint': 'A' * 40, 'publisher': 'CN=Synthetic Publisher'}
        self.acceptance = {
            'schema': 1, 'evidence_kind': 'human-release-acceptance',
            'reviewed_by': 'Synthetic Reviewer', 'reviewed_at': '2026-10-21T14:00:00+02:00',
            'msi_sha256': digest, 'launcher_sha256': '1' * 64,
            'windows11': {'interactive': True, 'first_start': True, 'cached_start': True,
                          'game_import_and_return': True, 'update_with_save_preservation': True,
                          'uninstall_with_save_preservation': True, 'evidence_reference': 'synthetic://windows11'},
            'signatures': {'installer': dict(signature), 'launcher': dict(signature)},
            'antivirus': {artifact: {'sha256': value, 'reviewed': True, 'open_detections': 0,
                                   'product': 'Synthetic AV', 'evidence_reference': 'synthetic://av/' + artifact}
                          for artifact, value in (('installer', digest), ('launcher', '1' * 64))}}

    def test_approval_is_explicit_and_tied_to_exact_bytes_and_app(self):
        review = create_review(self.path, self.build, self.smoke, approved=True, acceptance=self.acceptance)
        self.assertEqual(set(review), {'schema', 'product', 'version', 'file', 'sha256', 'bytes', 'games_bundled', 'update_approved'})
        self.assertTrue(review['update_approved'])
        with self.assertRaises(ValueError):
            create_review(self.path, self.build, self.smoke, approved=False, acceptance=self.acceptance)
        self.path.write_bytes(self.path.read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            create_review(self.path, self.build, self.smoke, approved=True, acceptance=self.acceptance)

    def test_incomplete_or_different_app_evidence_cannot_approve(self):
        for key in self.smoke:
            bad = copy.deepcopy(self.smoke)
            bad[key] = not bad[key] if isinstance(bad[key], bool) else 'wrong'
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_review(self.path, self.build, bad, approved=True, acceptance=self.acceptance)
        for key in ('games_bundled', 'synthetic_tests_passed', 'source_payload_cabinet_and_database_verified'):
            bad = {**self.build, key: not self.build[key]}
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_review(self.path, bad, self.smoke, approved=True, acceptance=self.acceptance)

    def assert_rejected(self, acceptance):
        with self.assertRaises(ValueError):
            create_review(self.path, self.build, self.smoke, approved=True, acceptance=acceptance)

    def test_smoke_and_approve_alone_are_insufficient_and_cli_requires_separate_record(self):
        with self.assertRaises(ValueError):
            create_review(self.path, self.build, self.smoke, approved=True)
        self.assert_rejected(self.smoke)
        for value in (None, [], True, 'approved'):
            with self.subTest(value=value):
                self.assert_rejected(value)
        arguments = ['create_update_review.py', '--installer', str(self.path), '--build-review', 'build.json',
                     '--app-test', 'smoke.json', '--output', 'release-review.json', '--approve']
        with patch('sys.argv', arguments), patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)

    def test_declaration_requires_explicit_identity_timestamp_and_exact_hashes(self):
        for key in self.acceptance:
            bad = copy.deepcopy(self.acceptance)
            del bad[key]
            with self.subTest(missing=key):
                self.assert_rejected(bad)
        for key, value in (('schema', True), ('schema', 2), ('evidence_kind', 'automatic-smoke'),
                           ('reviewed_by', ''), ('reviewed_by', 1), ('reviewed_at', '2026-10-21'),
                           ('reviewed_at', '2026-10-21T14:00:00'), ('reviewed_at', 'invalid'),
                           ('msi_sha256', '0' * 64), ('launcher_sha256', '0' * 64),
                           ('msi_sha256', 1), ('extra_approval', True)):
            bad = copy.deepcopy(self.acceptance)
            bad[key] = value
            with self.subTest(key=key, value=value):
                self.assert_rejected(bad)
        build = {**self.build, 'launcher_sha256': 'not-a-hash'}
        smoke = {**self.smoke, 'launcher_sha256': 'not-a-hash'}
        bad = {**self.acceptance, 'launcher_sha256': 'not-a-hash'}
        with self.assertRaises(ValueError):
            create_review(self.path, build, smoke, approved=True, acceptance=bad)

    def test_nested_records_reject_unknown_keys_and_wrong_container_types(self):
        for path in (('windows11',), ('signatures',), ('signatures', 'installer'),
                     ('signatures', 'launcher'), ('antivirus',), ('antivirus', 'installer'),
                     ('antivirus', 'launcher')):
            for value in ([], None, True, 'approved'):
                bad = copy.deepcopy(self.acceptance)
                owner = bad
                for key in path[:-1]:
                    owner = owner[key]
                owner[path[-1]] = value
                with self.subTest(path=path, value=value):
                    self.assert_rejected(bad)
            bad = copy.deepcopy(self.acceptance)
            owner = bad
            for key in path:
                owner = owner[key]
            owner['automatic_approval'] = True
            with self.subTest(path=path, unknown=True):
                self.assert_rejected(bad)

    def test_cli_reads_separate_human_acceptance_without_running_an_installer(self):
        import json
        folder = self.path.parent
        for name, value in (('build.json', self.build), ('smoke.json', self.smoke),
                            ('acceptance.json', self.acceptance)):
            (folder / name).write_text(json.dumps(value), encoding='utf-8')
        output = folder / 'release-review.json'
        arguments = ['create_update_review.py', '--installer', str(self.path),
                     '--build-review', str(folder / 'build.json'), '--app-test', str(folder / 'smoke.json'),
                     '--acceptance', str(folder / 'acceptance.json'), '--output', str(output), '--approve']
        with patch('sys.argv', arguments), patch('sys.stdout', io.StringIO()), patch('subprocess.Popen') as process:
            main()
        process.assert_not_called()
        self.assertEqual(json.loads(output.read_text(encoding='utf-8')), create_review(
            self.path, self.build, self.smoke, approved=True, acceptance=self.acceptance))

    def test_windows11_acceptance_cannot_be_replaced_by_headless_checks_or_truthy_values(self):
        for key in self.acceptance['windows11']:
            bad = copy.deepcopy(self.acceptance)
            del bad['windows11'][key]
            with self.subTest(missing=key):
                self.assert_rejected(bad)
            values = ('', None, 1) if key == 'evidence_reference' else (False, 0, 1, 'true', None)
            for value in values:
                bad = copy.deepcopy(self.acceptance)
                bad['windows11'][key] = value
                with self.subTest(key=key, value=value):
                    self.assert_rejected(bad)

    def test_both_signatures_must_be_valid_and_share_a_named_signing_identity(self):
        for artifact in ('installer', 'launcher'):
            for key in self.acceptance['signatures'][artifact]:
                bad = copy.deepcopy(self.acceptance)
                del bad['signatures'][artifact][key]
                with self.subTest(artifact=artifact, missing=key):
                    self.assert_rejected(bad)
            for key, value in (('status', 'NotSigned'), ('status', 'NotTrusted'), ('status', True),
                               ('thumbprint', ''), ('thumbprint', None), ('thumbprint', 'Z' * 40),
                               ('thumbprint', 'A' * 39), ('thumbprint', 'B' * 40),
                               ('publisher', ''), ('publisher', 1), ('publisher', 'CN=Other')):
                bad = copy.deepcopy(self.acceptance)
                bad['signatures'][artifact][key] = value
                with self.subTest(artifact=artifact, key=key, value=value):
                    self.assert_rejected(bad)
        valid = copy.deepcopy(self.acceptance)
        valid['signatures']['launcher']['thumbprint'] = 'a' * 40
        self.assertTrue(create_review(self.path, self.build, self.smoke, approved=True,
                                      acceptance=valid)['update_approved'])

    def test_antivirus_review_is_separate_for_both_hashes_with_no_open_detections(self):
        for artifact in ('installer', 'launcher'):
            for key in self.acceptance['antivirus'][artifact]:
                bad = copy.deepcopy(self.acceptance)
                del bad['antivirus'][artifact][key]
                with self.subTest(artifact=artifact, missing=key):
                    self.assert_rejected(bad)
            for key, value in (('sha256', '0' * 64), ('reviewed', False), ('reviewed', 1),
                               ('open_detections', 1), ('open_detections', -1), ('open_detections', False),
                               ('open_detections', 0.0), ('open_detections', '0'),
                               ('product', ''), ('product', []), ('evidence_reference', ''),
                               ('evidence_reference', None)):
                bad = copy.deepcopy(self.acceptance)
                bad['antivirus'][artifact][key] = value
                with self.subTest(artifact=artifact, key=key, value=value):
                    self.assert_rejected(bad)

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

    def test_signature_probe_uses_system_modules_and_rejects_missing_or_bad_status(self):
        shell = Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')
        for status in ('', 'HashMismatch', 'NotTrusted'):
            with patch('subprocess.check_output', return_value='{"status":"' + status + '"}'), self.assertRaises(ValueError):
                inspect_signature(shell, self.path)
        with patch('subprocess.check_output', return_value='{"status":"NotSigned","thumbprint":null}') as run:
            self.assertEqual(inspect_signature(shell, self.path)['status'], 'NotSigned')
            self.assertEqual(run.call_args.kwargs['env']['PSModulePath'], str(shell.parent / 'Modules'))
            self.assertIn("$ErrorActionPreference='Stop'", run.call_args.args[0][-1])


if __name__ == '__main__':
    unittest.main()
