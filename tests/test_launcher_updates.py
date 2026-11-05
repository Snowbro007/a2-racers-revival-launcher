"""Offline update tests with text-only MSI-shaped bytes; never run installers."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.request import Request
import zipfile

from tools import launcher_updates as update

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = bytes.fromhex('d0cf11e0a1b11ae1') + b'Synthetic installer sentinel: never execute'


def release_fixture(release_version='0.1.0-beta.6', **changes):
    version = release_version
    name = update.msi_name(version)
    review = {'schema': 1, 'product': 'A2 Racers Revival', 'version': version, 'file': name,
              'sha256': hashlib.sha256(PAYLOAD).hexdigest(), 'bytes': len(PAYLOAD),
              'games_bundled': False, 'update_approved': True}
    review.update(changes)
    data = json.dumps(review).encode()
    base = 'https://github.com/' + update.REPOSITORY + '/releases/download/v' + version + '/'
    assets = [{'name': file, 'size': len(content), 'digest': 'sha256:' + hashlib.sha256(content).hexdigest(),
               'state': 'uploaded', 'browser_download_url': base + file}
              for file, content in ((name, PAYLOAD), ('release-review.json', data))]
    release = {'draft': False, 'prerelease': True, 'tag_name': 'v' + version,
               'html_url': update.PAGE_URL + '/tag/v' + version, 'assets': assets}
    return release, {base + name: PAYLOAD, base + 'release-review.json': data}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(prefix='updates-', dir=parent)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / 'VERSION.txt').write_text('0.1.0-beta.5')
        (self.root / 'keep-save.txt').write_bytes(b'own synthetic progress')

    def reader(self, releases, contents):
        def read(url, limit):
            data = json.dumps(releases).encode() if url == update.RELEASES_URL else contents[url]
            self.assertLessEqual(len(data), limit)
            return data
        return read

    def test_numeric_versions_and_stable_release_order(self):
        self.assertGreater(update.version_key('0.1.0-beta.10'), update.version_key('0.1.0-beta.9'))
        self.assertGreater(update.version_key('0.1.0'), update.version_key('0.1.0-beta.999'))
        self.assertGreater(update.version_key('0.1.1-beta.1'), update.version_key('0.1.0'))
        self.assertEqual(update.msi_name('0.1.0-beta.6'), 'A2-Racers-Revival-0.1.6-beta6.msi')
        self.assertEqual(update.msi_name('0.1.0'), 'A2-Racers-Revival-0.1.1000.msi')
        for invalid in ('v0.1.0', '0.1', '0.1.00-beta.1', '0.1.0-beta.0', '../escape', '1.2.3\n', '0.1.0-beta.10000000'):
            with self.assertRaises(ValueError):
                update.version_key(invalid)

    def test_automatic_opt_out_never_contacts_github_or_changes_game_data(self):
        def forbidden(*args):
            raise AssertionError('No network expected')
        result = update.check(self.root, automatic=True, reader=forbidden)
        self.assertEqual(result['state'], 'disabled')
        (self.root / 'public-release.json').write_text('{}')
        self.assertTrue(update.settings(self.root)['automatic_check'])
        update.save_settings(self.root, False)
        self.assertEqual(update.check(self.root, automatic=True, reader=forbidden)['state'], 'disabled')
        self.assertEqual((self.root / 'keep-save.txt').read_bytes(), b'own synthetic progress')

    def test_drafts_old_versions_unreviewed_zip_and_bad_review_are_never_offered(self):
        draft, _ = release_fixture('0.1.0-beta.9')
        draft['draft'] = True
        old, old_files = release_fixture('0.1.0-beta.4')
        bad, bad_files = release_fixture('0.1.0-beta.8', update_approved=False)
        plain, _ = release_fixture('0.1.0-beta.7')
        plain['assets'] = []
        good, files = release_fixture()
        result = update.check(self.root, reader=self.reader([draft, old, bad, plain, good], {**old_files, **bad_files, **files}))
        self.assertEqual(result['state'], 'available')
        self.assertEqual(result['offer']['version'], '0.1.0-beta.6')
        self.assertFalse((self.root / 'local/launcher/updates').exists())

    def test_asset_provenance_rejects_wrong_host_digest_duplicates_and_size(self):
        original, files = release_fixture()
        changes = ({'browser_download_url': 'https://github.com.evil.invalid/update.msi'},
                   {'digest': ''}, {'size': True}, {'size': update.MAX_MSI + 1}, {'state': 'new'})
        for change in changes:
            with self.subTest(change=change):
                release = copy.deepcopy(original)
                release['assets'][0].update(change)
                self.assertEqual(update.check(self.root, reader=self.reader([release], files))['state'], 'current')
        duplicate = copy.deepcopy(original)
        duplicate['assets'].append(copy.deepcopy(duplicate['assets'][0]))
        self.assertEqual(update.check(self.root, reader=self.reader([duplicate], files))['state'], 'current')

    def test_review_requires_exact_hash_and_real_boolean_approval(self):
        for change in ({'games_bundled': True}, {'games_bundled': 0}, {'update_approved': 1}, {'sha256': '0' * 64}, {'bytes': True}, {'version': '0.1.0-beta.99'}):
            with self.subTest(change=change):
                release, files = release_fixture(**change)
                self.assertEqual(update.check(self.root, reader=self.reader([release], files))['state'], 'current')
        release, files = release_fixture()
        files[release['assets'][1]['browser_download_url']] += b'changed'
        self.assertEqual(update.check(self.root, reader=self.reader([release], files))['state'], 'current')

    def test_redirects_must_remain_https_on_fixed_hosts(self):
        for url in ('http://github.com/file', 'https://github.com.evil.invalid/file', 'https://name:password@github.com/file', 'https://github.com:444/file'):
            with self.assertRaises(ValueError):
                update.safe_url(url)
            with self.assertRaises(ValueError):
                update.Redirects().redirect_request(Request('https://github.com/file'), None, 302, '', {}, url)
        with self.assertRaises(ValueError):
            update.safe_url('https://objects.githubusercontent.com/file', api=True)

    def test_download_and_revalidation_preserve_zone_save_and_preferences(self):
        release, files = release_fixture()
        reader = self.reader([release], files)
        marker = update.mark_download if os.name == 'nt' else lambda *args: None
        result = update.download(self.root, '0.1.0-beta.6', reader, marker)
        self.assertEqual(Path(result['path']).read_bytes(), PAYLOAD)
        self.assertEqual(update.verify_for_install(self.root, Path(result['receipt']), reader)['sha256'], hashlib.sha256(PAYLOAD).hexdigest())
        self.assertEqual((self.root / 'keep-save.txt').read_bytes(), b'own synthetic progress')
        self.assertFalse((self.root / 'local/launcher/settings.json').exists())
        if os.name == 'nt':
            self.assertIn('ZoneId=3', Path(result['path'] + ':Zone.Identifier').read_text())
        Path(result['path']).write_bytes(PAYLOAD + b'tamper')
        with self.assertRaises(ValueError):
            update.verify_download(self.root, Path(result['receipt']))

    def test_changed_or_withdrawn_offer_cannot_be_installed_from_cache(self):
        release, files = release_fixture()
        marker = update.mark_download if os.name == 'nt' else lambda *args: None
        result = update.download(self.root, '0.1.0-beta.6', self.reader([release], files), marker)
        with self.assertRaises(ValueError):
            update.verify_for_install(self.root, Path(result['receipt']), self.reader([], {}))
        (self.root / 'VERSION.txt').write_text('0.1.0-beta.6')
        with self.assertRaises(ValueError):
            update.verify_download(self.root, Path(result['receipt']))

    def test_bad_download_never_creates_an_installer_or_changes_user_files(self):
        release, files = release_fixture()
        files[release['assets'][0]['browser_download_url']] = b'wrong bytes'
        with self.assertRaises(ValueError):
            update.download(self.root, '0.1.0-beta.6', self.reader([release], files))
        self.assertFalse(list(self.root.rglob('*.msi')))
        self.assertEqual((self.root / 'keep-save.txt').read_bytes(), b'own synthetic progress')
        with self.assertRaises(ValueError):
            update.verify_download(self.root, self.root / 'elsewhere/download.json')

    def test_traversal_links_and_duplicate_json_fields_are_refused(self):
        with self.assertRaises(ValueError):
            update.checked_path(self.root / 'local/../outside')
        with self.assertRaises(ValueError):
            update.read_json(b'{"version":1,"version":2}')
        with self.assertRaises(ValueError):
            update.read_json(b'{"version":NaN}')
    @unittest.skipUnless(os.name == 'nt', 'Windows hardlink fixture')
    def test_real_hardlink_in_update_path_is_refused(self):
            first = self.root / 'first'
            first.write_text('synthetic')
            linked = self.root / 'linked'
            try:
                os.link(first, linked)
            except PermissionError:
                self.skipTest('Windows denied creating a synthetic hardlink; no permissions changed')
            with self.assertRaises(ValueError):
                update.checked_path(linked)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def app_payload(version: str, **overrides) -> dict:
    files = {name: ('synthetic ' + name + ' ' + version).encode() for name in update.REQUIRED_APP_FILES}
    files['VERSION.txt'] = version.encode()
    files.update(overrides)
    return {name: data for name, data in files.items() if data is not None}


def manifest_bytes(files: dict, **changes) -> bytes:
    manifest = {'schema': 1, 'kind': 'portable-launcher', 'game_archive_included': False,
                'audience': 'launcher-public', 'gameplay_verified_on_second_pc': False,
                'files': [{'path': name, 'size': len(data), 'sha256': sha(data)} for name, data in sorted(files.items())]}
    manifest.update(changes)
    return json.dumps(manifest, indent=2).encode()


def portable_zip(files: dict, extra=(), manifest=None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(update.APP_FOLDER + name, data)
        archive.writestr(update.APP_FOLDER + 'release-manifest.json', manifest or manifest_bytes(files))
        for name, data in extra:
            archive.writestr(name, data)
    return buffer.getvalue()


def portable_release(version: str, data: bytes, checksum: bytes | None = None):
    name = update.zip_name(version)
    checksum = checksum if checksum is not None else (sha(data) + '  ' + name + '\n').encode()
    base = 'https://github.com/' + update.REPOSITORY + '/releases/download/v' + version + '/'
    assets = [{'name': file, 'size': len(content), 'digest': 'sha256:' + sha(content),
               'state': 'uploaded', 'browser_download_url': base + file}
              for file, content in ((name, data), (name + '.sha256', checksum))]
    release = {'draft': False, 'prerelease': True, 'tag_name': 'v' + version,
               'html_url': update.PAGE_URL + '/tag/v' + version, 'assets': assets}
    return release, {base + name: data, base + name + '.sha256': checksum}


class PortableUpdateTests(unittest.TestCase):
    """Portable self-update with synthetic text files; no launcher, game or network."""
    OLD, NEW = '0.1.0-beta.11', '0.1.0-beta.12'

    def setUp(self):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(prefix='portable-updates-', dir=parent)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / 'A2-Racers-Revival'
        self.old_files = app_payload(self.OLD, **{'tools/old_helper.ps1': b'obsolete synthetic helper'})
        for name, data in self.old_files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / 'release-manifest.json').write_bytes(manifest_bytes(self.old_files))
        self.user_data = {'local/saves/progress.sav': b'own synthetic progress',
                          'local/launcher/settings.json': b'{"synthetic": true}',
                          'mijn-notities.txt': b'unlisted user file'}
        for name, data in self.user_data.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.new_files = app_payload(self.NEW, **{'tools/new_feature.ps1': b'new synthetic feature'})
        self.marker = update.mark_download if os.name == 'nt' else lambda *args: None

    def reader(self, releases, contents):
        def read(url, limit):
            data = json.dumps(releases).encode() if url == update.RELEASES_URL else contents[url]
            self.assertLessEqual(len(data), limit)
            return data
        return read

    def assert_user_data_kept(self):
        for name, data in self.user_data.items():
            self.assertEqual((self.root / name).read_bytes(), data, name)

    def download(self, data=None):
        release, contents = portable_release(self.NEW, data or portable_zip(self.new_files))
        return update.download(self.root, self.NEW, self.reader([release], contents), self.marker)

    def test_install_kinds_never_treat_msi_or_git_checkout_as_portable(self):
        self.assertEqual(update.install_kind(self.root), 'portable')
        (self.root / '.git').mkdir()
        self.assertEqual(update.install_kind(self.root), 'development')
        (self.root / '.git').rmdir()
        (self.root / 'public-release.json').unlink()
        self.assertEqual(update.install_kind(self.root), 'development')
        msi = Path(self.folder.name) / 'installed'
        (msi / 'app').mkdir(parents=True)
        (msi / update.NATIVE_LAUNCHER).write_bytes(b'synthetic, never executed')
        self.assertEqual(update.install_kind(msi / 'app'), 'msi')

    def test_portable_offer_needs_matching_published_checksum(self):
        data = portable_zip(self.new_files)
        release, contents = portable_release(self.NEW, data)
        offer = update.check(self.root, reader=self.reader([release], contents))
        self.assertEqual(offer['state'], 'available')
        self.assertEqual((offer['offer']['kind'], offer['offer']['sha256']), ('portable', sha(data)))
        for checksum in (b'0' * 64 + b'  ' + update.zip_name(self.NEW).encode(), b'', sha(data).encode() + b'  other.zip'):
            with self.subTest(checksum=checksum):
                release, contents = portable_release(self.NEW, data, checksum)
                self.assertEqual(update.check(self.root, reader=self.reader([release], contents))['state'], 'current')
        draft, contents = portable_release(self.NEW, data)
        draft['draft'] = True
        self.assertEqual(update.check(self.root, reader=self.reader([draft], contents))['state'], 'current')
        msi_only, msi_contents = release_fixture(self.NEW)
        self.assertEqual(update.check(self.root, reader=self.reader([msi_only], msi_contents))['state'], 'current')

    def test_download_stages_verified_files_without_touching_the_app(self):
        result = self.download()
        self.assertEqual((result['state'], result['kind']), ('downloaded', 'portable'))
        staged = Path(result['receipt']).parent / 'staged'
        self.assertEqual((staged / 'tools/new_feature.ps1').read_bytes(), b'new synthetic feature')
        self.assertEqual((self.root / 'VERSION.txt').read_text(), self.OLD)
        self.assert_user_data_kept()
        (staged / 'tools/new_feature.ps1').write_bytes(b'tampered after staging')
        with self.assertRaises(ValueError):
            update.verify_portable_download(self.root, Path(result['receipt']))

    def test_unsafe_or_inconsistent_packages_are_refused_and_cleaned_up(self):
        bad_manifest = dict(self.new_files)
        cases = {
            'user data path': portable_zip({**self.new_files, 'local/saves/progress.sav': b'overwrite'}),
            'traversal': portable_zip({**self.new_files, '../escape.txt': b'x'}),
            'reserved name': portable_zip({**self.new_files, 'tools/CON.txt': b'x'}),
            'extra entry': portable_zip(self.new_files, extra=(('A2-Racers-Revival/unlisted.txt', b'x'),)),
            'outside prefix': portable_zip(self.new_files, extra=(('elsewhere.txt', b'x'),)),
            'hash mismatch': portable_zip(self.new_files, manifest=manifest_bytes({**bad_manifest, 'Launcher.cmd': b'other'})),
            'games bundled': portable_zip(self.new_files, manifest=manifest_bytes(self.new_files, game_archive_included=True)),
            'private audience': portable_zip(self.new_files, manifest=manifest_bytes(self.new_files, audience='personal-private')),
            'missing updater': portable_zip(app_payload(self.NEW, **{'tools/launcher_updates.py': None})),
            'wrong version': portable_zip(app_payload('0.1.0-beta.99')),
            'not a zip': b'PK\x03\x04 synthetic broken archive',
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.download(data)
                self.assertEqual(list((self.root / 'local/launcher/updates').glob('*')), [])
        self.assertEqual((self.root / 'VERSION.txt').read_text(), self.OLD)
        self.assert_user_data_kept()

    def test_apply_replaces_listed_files_and_keeps_user_data(self):
        result = self.download()
        waited = []
        outcome = update.apply_portable(self.root, Path(result['receipt']), (1234,), waiter=waited.append)
        self.assertEqual(waited, [(1234,)])
        self.assertEqual((outcome['from'], outcome['version']), (self.OLD, self.NEW))
        for name, data in self.new_files.items():
            self.assertEqual((self.root / name).read_bytes(), data, name)
        self.assertFalse((self.root / 'tools/old_helper.ps1').exists())
        self.assertEqual((self.root / 'release-manifest.json').read_bytes(), manifest_bytes(self.new_files))
        self.assert_user_data_kept()
        self.assertFalse(Path(result['receipt']).parent.exists())
        backup = Path(outcome['backup'])
        self.assertEqual((backup / 'tools/old_helper.ps1').read_bytes(), b'obsolete synthetic helper')
        notice = update.take_notice(self.root)
        self.assertEqual((notice['state'], notice['outcome']), ('notice', 'updated'))
        self.assertIn(self.NEW, notice['message'])
        self.assertEqual(update.take_notice(self.root), {'state': 'none'})  # Shown only once.

    def test_failure_during_replacement_restores_previous_version(self):
        result = self.download()
        original = update.replace_file
        calls = []
        def failing(source, target):
            calls.append(target)
            if len(calls) == 3:
                raise OSError('synthetic locked file')
            return original(source, target)
        update.replace_file = failing
        try:
            with self.assertRaises(ValueError):
                update.apply_portable(self.root, Path(result['receipt']), waiter=lambda pids: None)
        finally:
            update.replace_file = original
        for name, data in self.old_files.items():
            self.assertEqual((self.root / name).read_bytes(), data, name)
        self.assertFalse((self.root / 'tools/new_feature.ps1').exists())
        self.assertEqual((self.root / 'release-manifest.json').read_bytes(), manifest_bytes(self.old_files))
        self.assert_user_data_kept()
        notice = update.take_notice(self.root)
        self.assertEqual(notice['outcome'], 'failed')
        self.assertIn(self.OLD, notice['message'])

    def test_still_open_launcher_or_changed_staging_changes_nothing(self):
        result = self.download()
        def still_open(pids):
            raise update.LauncherStillOpen('synthetic: launcher did not close')
        with self.assertRaises(update.LauncherStillOpen):
            update.apply_portable(self.root, Path(result['receipt']), (1,), waiter=still_open)
        staged = Path(result['receipt']).parent / 'staged'
        (staged / 'Launcher.cmd').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            update.apply_portable(self.root, Path(result['receipt']), waiter=lambda pids: None)
        for name, data in self.old_files.items():
            self.assertEqual((self.root / name).read_bytes(), data, name)
        self.assertEqual(update.take_notice(self.root)['outcome'], 'failed')
        self.assert_user_data_kept()

    @unittest.skipUnless(os.name == 'nt', 'Windows process handles')
    def test_wait_for_exit_waits_for_real_process_and_refuses_one_that_stays_open(self):
        import subprocess, sys, time
        quick = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.5)'])
        start = time.monotonic()
        update.wait_for_exit([quick.pid, 2 ** 31 - 2])  # A missing PID counts as closed.
        self.assertIsNotNone(quick.poll())
        self.assertGreater(time.monotonic() - start, 0.2)
        slow = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            with self.assertRaises(update.LauncherStillOpen):
                update.wait_for_exit([slow.pid], timeout=0.3)
        finally:
            slow.kill()
            slow.wait(timeout=10)

    def test_development_checkout_is_never_self_updated(self):
        (self.root / '.git').mkdir()
        release, contents = portable_release(self.NEW, portable_zip(self.new_files))
        self.assertEqual(update.check(self.root, reader=self.reader([release], contents))['state'], 'current')
        with self.assertRaises(ValueError):
            update.download_portable(self.root, {'url': 'unused'}, self.reader([], {}))


if __name__ == '__main__':
    unittest.main()
