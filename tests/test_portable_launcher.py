"""Release packaging tests use synthetic artwork, providers and game bytes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import portable_launcher as release, launcher_assets as assets
from tools import prepare_public_release as public_release

ROOT = Path(__file__).resolve().parents[1]


class PortableLauncherTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'local/test-fixtures';parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix='launcher-release-', dir=parent)
        self.addCleanup(temp.cleanup);self.root = Path(temp.name)
        self.target = 'local/mods/a2racer1/fixture.pcx'
        self.art = b'synthetic art';self.pin = hashlib.sha256(self.art).hexdigest()
        self.seed = ['Launcher.cmd', 'tools/entry.py']
        self.write('Launcher.cmd', b'synthetic launcher')
        self.write('tools/entry.py', b'from tools import dependency\n')
        self.write('tools/dependency.py', b'# synthetic dependency\n')
        self.write('docs/portable-launcher.md', b'Synthetic user instructions')
        self.write('local/components/cnc-ddraw/v7.0.0.0/LICENSE-v7.0.0.0.txt', b'synthetic notice')
        self.write('local/components/dgvoodoo/v2.87.5/author-readme-general.html', b'synthetic notice')
        self.write(self.target, self.art)
        self.payload = b'synthetic verified provider'
        self.write('provider.zip', self.payload)
        providers = {'fixture': ('provider.zip', hashlib.sha256(self.payload).hexdigest(), 'provider.zip')}
        for obj, name, value in ((release.kit, 'APP_FILES', self.seed), (release, 'EXTRA_FILES', ()),
                                 (release.kit, 'PAYLOADS', providers), (release, 'asset_catalog', lambda: {self.target: self.pin}),
                                 (assets, 'asset_catalog', lambda: {self.target: self.pin})):
            context = patch.object(obj, name, value);context.start();self.addCleanup(context.stop)

    def write(self, name, data):
        path = self.root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data)
        return path

    def build(self, game=None):
        output = self.root / 'download.zip'
        result = release.build(self.root, output, game)
        return output, result

    def test_clean_download_excludes_agents_prompts_reports_saves_and_old_tests(self):
        for name in ('AGENTS.md', '.git/config', 'prompts.txt', 'local/launcher/settings.json',
                     'local/experiments/old/game.DAT', 'reports/user.json', 'tests/test_secret.py',
                     'Gamebestanden/A2 Racer I/own-source.txt'):
            self.write(name, b'personal fixture excluded')
        output, result = self.build()
        self.assertFalse(result['game_archive_included'])
        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
            self.assertIn(release.PREFIX + 'Launcher.cmd', names)
            self.assertIn(release.PREFIX + 'tools/dependency.py', names)
            self.assertIn(release.PREFIX + assets.package_path(self.target), names)
            self.assertFalse(any('AGENTS' in n or '/local/' in n or '/Gamebestanden/' in n or '/tests/' in n or '/reports/' in n or '/.git/' in n for n in names))
            manifest = json.loads(archive.read(release.PREFIX + 'release-manifest.json'))
            self.assertEqual(manifest['audience'], 'launcher-only')
        self.assertEqual(release.audit(output, self.root), result['files_checked'])
        self.assertIn(result['sha256'], output.with_suffix('.zip.sha256').read_text())
        with self.assertRaises(ValueError):release.build(self.root, output)

    def test_public_source_rejects_game_input_folder_even_if_added_to_package_list(self):
        path = self.write('Gamebestanden/A2 Racer I/own-source.txt', b'synthetic private source')
        with patch.object(release, 'records', return_value=[('Gamebestanden/A2 Racer I/own-source.txt', path, None)]):
            with self.assertRaisesRegex(ValueError, 'Persoonlijk/game/componentbestand'):
                public_release.source_files(self.root)

    def test_public_download_omits_all_provider_binaries_and_game_archives(self):
        for name in release.PUBLIC_FILES:
            self.write(name, b'synthetic public documentation')
        self.write('docs/public-release.json', b'{"schema":1,"games_bundled":false}')
        output=self.root/'public.zip'
        result=release.build(self.root,output,public=True)
        with zipfile.ZipFile(output) as archive:
            names=archive.namelist()
            manifest=json.loads(archive.read(release.PREFIX+'release-manifest.json'))
            self.assertEqual(manifest['audience'],'launcher-public')
            self.assertFalse(any('/payload/' in name or name.endswith(('.exe','.dll','.zip')) for name in names))
            self.assertIn(release.PREFIX+'LICENSE',names)
            self.assertIn(release.PREFIX+'public-release.json',names)
            archive.extractall(self.root/'public moved é')
        self.assertEqual(release.audit(output,self.root),result['files_checked'])
        self.assertFalse(release.bundled_import_needed(self.root/'public moved é'/release.PREFIX))
        game=self.write('game.zip',b'synthetic game')
        with self.assertRaisesRegex(ValueError,'gamearchief'):
            release.build(self.root,self.root/'forbidden.zip',game,public=True)
        self.assertFalse((self.root/'forbidden.zip').exists())

    def test_public_package_and_source_do_not_require_legacy_shortcut_helper(self):
        # Retain the private kit's list, but do not require its old user helper
        # in a public source copy or pass it through into an MSI payload.
        self.seed.append('Maak-snelkoppeling.ps1')
        for name in release.PUBLIC_FILES:
            self.write(name, b'synthetic public documentation')
        self.write('docs/public-release.json', b'{"schema":1,"games_bundled":false}')
        self.assertFalse((self.root/'Maak-snelkoppeling.ps1').exists())
        names = {name for name, _, _ in public_release.source_files(self.root)}
        self.assertNotIn('Maak-snelkoppeling.ps1', names)
        output = self.root/'public-without-legacy.zip'
        result = release.build(self.root, output, public=True)
        with zipfile.ZipFile(output) as archive:
            self.assertNotIn(release.PREFIX+'Maak-snelkoppeling.ps1', archive.namelist())
        self.assertEqual(release.audit(output, self.root), result['files_checked'])
        self.assertIn('Maak-snelkoppeling.ps1', release.kit.APP_FILES)

    def test_public_source_copy_is_separate_complete_and_rebuildable(self):
        for name in release.PUBLIC_FILES:
            self.write(name, b'# synthetic public source\n' if name.endswith('.py') else b'synthetic documentation')
        self.write('docs/public-release.json', b'{"schema":1,"games_bundled":false}')
        source=self.root/'clean-source'
        game=self.write('game-media/original.zip',b'keep original')
        self.write('AGENTS.md',b'private instructions')
        output=self.root/'public-copy.zip'
        before=game.read_bytes()
        result=public_release.prepare(self.root,source,output)
        self.assertFalse(result['external_binaries_bundled']);self.assertFalse(result['published'])
        self.assertEqual(game.read_bytes(),before)
        self.assertFalse((source/'AGENTS.md').exists());self.assertFalse((source/'game-media').exists())
        self.assertEqual((source/'assets/a2racer1/fixture.pcx').read_bytes(),self.art)
        self.assertEqual(release.audit(output,source),result['files_checked'])
        rebuilt=self.root/'rebuilt.zip'
        release.build(source,rebuilt,public=True)
        self.assertEqual(release.audit(rebuilt,source),result['files_checked'])
        with self.assertRaises(ValueError):public_release.freeze(self.root,source)

    def test_only_known_personal_game_archive_allowed_and_source_preserved(self):
        game = self.write('fixture-game.zip', b'synthetic game archive')
        with self.assertRaises(ValueError):self.build(game)
        self.assertFalse((self.root / 'download.zip').exists())
        pin = hashlib.sha256(game.read_bytes()).hexdigest()
        with patch.object(release.kit, 'GAME_ARCHIVE_SHA256', pin):
            output, result = self.build(game)
            self.assertTrue(result['game_archive_included'])
            with zipfile.ZipFile(output) as archive:
                archive.extractall(self.root / 'unpacked')
            # Use the fixture source root for dependency names in the runtime check.
            unpacked = self.root / 'unpacked' / release.PREFIX
            self.assertTrue(release.bundled_import_needed(unpacked))
            (unpacked / 'local/games/a2racer1').mkdir(parents=True)
            self.assertFalse(release.bundled_import_needed(unpacked))
        self.assertEqual(game.read_bytes(), b'synthetic game archive')

    def test_archive_audit_rejects_extra_data_tampering_and_path_traversal(self):
        output, _ = self.build()
        with zipfile.ZipFile(output) as archive:
            original = {n: archive.read(n) for n in archive.namelist()}
        for index, extra in enumerate(('AGENTS.md', '../outside.txt', 'local/launcher/players.json')):
            bad = self.root / f'bad-{index}.zip'
            with zipfile.ZipFile(bad, 'w') as archive:
                for name, data in original.items():archive.writestr(name, data)
                archive.writestr(release.PREFIX + extra, b'not allowed')
            with self.assertRaises(ValueError):release.audit(bad, self.root)
        with zipfile.ZipFile(self.root / 'tampered.zip', 'w') as archive:
            for name, data in original.items():
                archive.writestr(name, b'changed' if name.endswith('Launcher.cmd') else data)
        with self.assertRaises(ValueError):release.audit(self.root / 'tampered.zip', self.root)
        forged = dict(original)
        forged[release.PREFIX + 'Launcher.cmd'] = b'changed code'
        manifest = json.loads(forged[release.PREFIX + 'release-manifest.json'])
        for row in manifest['files']:
            if row['path'] == 'Launcher.cmd':
                row.update(size=12, sha256=hashlib.sha256(b'changed code').hexdigest())
        forged[release.PREFIX + 'release-manifest.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.root / 'forged-manifest.zip', 'w') as archive:
            for name, data in forged.items():archive.writestr(name, data)
        with self.assertRaises(ValueError):release.audit(self.root / 'forged-manifest.zip', self.root)

    def test_existing_checksum_and_racing_zip_are_never_deleted(self):
        path = self.root / 'existing.zip'
        path.with_suffix('.zip.sha256').write_bytes(b'keep checksum')
        with self.assertRaises(ValueError):release.build(self.root, path)
        self.assertFalse(path.exists())
        self.assertEqual(path.with_suffix('.zip.sha256').read_bytes(), b'keep checksum')
        def competing_open(*args, **kwargs):
            path.write_bytes(b'foreign package')
            raise FileExistsError('synthetic competing builder')
        path.with_suffix('.zip.sha256').unlink()
        with patch.object(release.zipfile, 'ZipFile', side_effect=competing_open):
            with self.assertRaises(FileExistsError):release.build(self.root, path)
        self.assertEqual(path.read_bytes(), b'foreign package')

    def test_asset_install_is_relocatable_idempotent_and_preserves_user_data(self):
        output, _ = self.build()
        with zipfile.ZipFile(output) as archive:archive.extractall(self.root / 'verplaatst é')
        moved = self.root / 'verplaatst é' / release.PREFIX
        user = moved / 'local/launcher/i-hd-menu/players.json';user.parent.mkdir(parents=True)
        user.write_bytes(b'synthetic user save')
        self.assertEqual(assets.install_assets(moved), 1)
        self.assertEqual(assets.install_assets(moved), 0)
        self.assertEqual(user.read_bytes(), b'synthetic user save')
        (moved / self.target).write_bytes(b'foreign data')
        with self.assertRaises(ValueError):assets.install_assets(moved)
        self.assertEqual((moved / self.target).read_bytes(), b'foreign data')

    def test_missing_or_wrong_art_refuses_before_partial_install(self):
        packaged = self.write(assets.package_path(self.target), b'wrong art')
        original = self.root / self.target;original.unlink()
        with self.assertRaises(ValueError):assets.install_assets(self.root)
        self.assertFalse(original.exists())
        packaged.write_bytes(self.art)
        self.assertEqual(assets.install_assets(self.root), 1)

    def test_dependency_closure_includes_literal_script_and_xaml_routes(self):
        self.write('tools/dependency.py', b"SCRIPT='child.ps1'\n")
        self.write('tools/child.ps1', b"$view='child.xaml'\n")
        self.write('tools/child.xaml', b'<fixture/>')
        self.assertIn('tools/child.xaml', release.app_files(self.root))


if __name__ == '__main__':unittest.main()
