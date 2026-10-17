"""Offline update tests with text-only MSI-shaped bytes; never run installers."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.request import Request

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


if __name__ == '__main__':
    unittest.main()
