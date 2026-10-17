"""Synthetic build orchestration; no game data or compiler execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import build_windows_release as build
from tools import portable_launcher


class NativeReleaseBuildTests(unittest.TestCase):
    def temporary(self):
        parent = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=parent)

    def fixture(self, directory, *, version='0.1.0-beta.5', games=False):
        root = Path(directory)
        icon = root / 'tools/launcher_art/a2-revival.ico'
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b'synthetic icon')
        portable = root / 'portable.zip'
        rows = {'release-manifest.json': json.dumps({'audience': 'launcher-public', 'game_archive_included': games}).encode(),
                'public-release.json': json.dumps({'version': version}).encode(), 'fixture.txt': b'exact source bytes'}
        with zipfile.ZipFile(portable, 'w') as archive:
            for name, value in rows.items(): archive.writestr(portable_launcher.PREFIX + name, value)
        return root, portable, rows

    def test_build_emits_only_native_entrypoint_and_exact_public_app(self):
        with self.temporary() as directory:
            root, portable, rows = self.fixture(directory)
            def compile_fixture(sources, output, **kwargs):
                self.assertEqual([p.name for p in sources], ['NativeCommon.cs', 'Launcher.cs', 'Version.cs'])
                output.write_bytes(b'synthetic native launcher')
            output = root / 'new-build'
            with patch.object(portable_launcher, 'audit') as audit, patch.object(build, 'compile_cs', side_effect=compile_fixture), patch.object(build.subprocess, 'run') as run:
                result = build.build(root, portable, output, '0.1.0-beta.5')
            audit.assert_called_once_with(portable, root)
            run.assert_not_called()
            self.assertFalse(list(output.glob('*Setup.exe')))
            with zipfile.ZipFile(output / result['payload']) as archive:
                self.assertEqual(set(archive.namelist()), {'app/' + name for name in rows} | {'A2 Racers Revival.exe'})
                for name, value in rows.items(): self.assertEqual(archive.read('app/' + name), value)
                self.assertEqual(archive.read('A2 Racers Revival.exe'), b'synthetic native launcher')
            self.assertEqual(result['payload_sha256'], build.digest(output / result['payload']))
            self.assertFalse(result['signed']); self.assertFalse(result['published']); self.assertFalse(result['games_bundled'])
            with patch.object(portable_launcher, 'audit'), self.assertRaises(ValueError):
                build.build(root, portable, output, '0.1.0-beta.5')

    def test_missing_icon_fails_before_creating_or_executing_any_build_file(self):
        with self.temporary() as directory:
            root, portable, _ = self.fixture(directory)
            (root / 'tools/launcher_art/a2-revival.ico').unlink()
            output = root / 'missing-icon-build'
            with patch.object(portable_launcher, 'audit'), patch.object(build, 'compile_cs') as compile_cs, patch.object(build.subprocess, 'run') as run:
                with self.assertRaisesRegex(FileNotFoundError, 'A2-icoon ontbreekt'):
                    build.build(root, portable, output, '0.1.0-beta.5')
            compile_cs.assert_not_called()
            run.assert_not_called()
            self.assertFalse(output.exists())

    def test_wrong_version_or_game_manifest_never_creates_output(self):
        for version, games in [('0.1.0-beta.4', False), ('0.1.0-beta.5', True)]:
            with self.subTest(version=version, games=games), self.temporary() as directory:
                root, portable, _ = self.fixture(directory, version=version, games=games)
                output = root / 'rejected'
                with patch.object(portable_launcher, 'audit'), self.assertRaises(ValueError):
                    build.build(root, portable, output, '0.1.0-beta.5')
                self.assertFalse(output.exists())
