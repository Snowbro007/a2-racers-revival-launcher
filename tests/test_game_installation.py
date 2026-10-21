"""Installation linking uses synthetic files only, never real games or registry."""
import hashlib
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import game_installation as gi, local_game_data as data


class InstallationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='installation-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Revival é'
        self.root.mkdir()
        self.source = Path(self.temp.name) / 'Eigen installatie é'
        self.source.mkdir()
        (self.source / 'A2SPEL.DAT').write_bytes(b'synthetic-never-executable')
        (self.source / 'RCS.IMG').write_bytes(b'synthetic-data')
        records = [{'path': p.name, 'size': p.stat().st_size,
                    'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in sorted(self.source.iterdir())]
        treehash = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
        profile = {'files': 2, 'bytes': sum(r['size'] for r in records), 'sha256': treehash,
                   'essential': {'RCS.IMG': (records[1]['size'], records[1]['sha256'])}}
        self.addCleanup(patch.stopall)
        patch.object(data, 'SOURCE_PROFILE', profile).start()
        patch.object(gi, 'EXPECTED_BINARIES', {'a2racer1': {'A2SPEL.DAT': records[0]['sha256']}}).start()

    def test_link_copies_verified_data_preserves_source_and_remembers_location(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        result = gi.import_installation(self.root, self.source)
        self.assertTrue(result['source_unchanged'])
        self.assertFalse(result['game_started'])
        self.assertFalse(result['disc_image_required'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'local/games/a2racer1').iterdir()})
        receipt = json.loads((self.root / 'local/launcher/installation.json').read_text())
        self.assertEqual(receipt['source_path'], str(self.source))
        with self.assertRaises(ValueError):
            gi.import_installation(self.root, self.source)

    def test_ii_copy_has_its_own_receipt_and_preserves_i_cache(self):
        marker=self.root/'local/games/a2racer1/keep.sav';marker.parent.mkdir(parents=True)
        marker.write_bytes(b'keep first game')
        def inspect(path, game='a2racer1'):
            self.assertEqual(game,'a2racer2')
            rows=[(p.relative_to(path).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(path.rglob('*')) if p.is_file()]
            return {'source_tree_sha256':hashlib.sha256(json.dumps(rows).encode()).hexdigest(),'files':len(rows)}
        before={p.name:p.read_bytes() for p in self.source.iterdir()}
        with patch.object(gi,'inspect_installation',side_effect=inspect):
            result=gi.import_installation(self.root,self.source,'a2racer2')
        self.assertEqual(result['game'],'a2racer2');self.assertTrue(result['source_unchanged'])
        self.assertEqual(marker.read_bytes(),b'keep first game')
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.source.iterdir()})
        self.assertTrue((self.root/'local/launcher/installation-a2racer2.json').is_file())
        self.assertFalse((self.root/'local/launcher/installation.json').exists())

    def test_discovery_is_readonly_deduplicated_and_reports_wrong_versions(self):
        bad = Path(self.temp.name) / 'Onvolledig'; bad.mkdir()
        report = gi.discover(self.root, candidates=[self.source, self.source, bad])
        self.assertEqual(len(report['installations']), 2)
        self.assertTrue(report['installations'][0]['supported'])
        self.assertFalse(report['installations'][1]['supported'])
        self.assertIsNone(report['download_url'])
        self.assertFalse((self.root / 'local').exists())

    def test_unknown_version_or_incomplete_data_never_creates_destination(self):
        for name in ('A2SPEL.DAT', 'RCS.IMG'):
            with self.subTest(name=name):
                path = self.source / name; before = path.read_bytes()
                path.write_bytes(b'unknown')
                with self.assertRaises(ValueError):
                    gi.import_installation(self.root, self.source)
                self.assertFalse((self.root / 'local').exists())
                path.write_bytes(before)

    def test_existing_source_cache_and_receipt_are_preserved(self):
        target = self.root / 'local/games/a2racer1'
        target.mkdir(parents=True)
        (target / 'save').write_bytes(b'keep')
        with self.assertRaises(ValueError):
            gi.import_installation(self.root, self.source)
        self.assertEqual((target / 'save').read_bytes(), b'keep')

    def test_changing_source_rolls_back_own_staging_only(self):
        original = gi.copy_file
        def mutate(source, target):
            original(source, target)
            if source.name == 'RCS.IMG':
                source.write_bytes(b'changed-data')
        with patch.object(gi, 'copy_file', side_effect=mutate), self.assertRaises(ValueError):
            gi.import_installation(self.root, self.source)
        self.assertFalse((self.root / 'local/games/a2racer1').exists())
        self.assertEqual(list((self.root / 'local/games').iterdir()), [])
        self.assertFalse((self.root / 'local/launcher/installation.json').exists())

    def test_bounds_and_overlap_refuse_before_copy(self):
        with patch.object(gi, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            gi.import_installation(self.root, self.source)
        with self.assertRaises(ValueError):
            gi.import_installation(self.root, self.root)
        self.assertFalse((self.root / 'local').exists())

    def test_unknown_extra_file_is_not_silently_imported(self):
        (self.source / 'untrusted.dll').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            gi.import_installation(self.root, self.source)
        self.assertFalse((self.root / 'local').exists())

    def test_os_walk_access_error_cannot_be_reported_as_complete(self):
        def broken(*args, **kwargs):
            kwargs['onerror'](PermissionError('denied'))
            return iter([])
        with patch.object(gi.os, 'walk', side_effect=broken), self.assertRaises(PermissionError):
            gi.inspect_installation(self.source)

    def test_registry_only_uses_matching_install_locations_not_commands(self):
        entries = [
            {'DisplayName': 'A2 Racer', 'InstallLocation': str(self.source)},
            {'DisplayName': 'A2 Racer II', 'InstallLocation': str(self.root)},
            {'DisplayName': 'Other app', 'InstallLocation': str(self.root)},
            {'DisplayName': 'A2 Racer', 'UninstallString': 'never-execute.exe'},
            {'DisplayName': 'A2 Racer', 'InstallLocation': 'relative-path'},
        ]
        class Key:
            def __init__(self, index=None): self.index = index
            def __enter__(self): return self
            def __exit__(self, *args): pass
        def query(key, name):
            try: return entries[key.index][name], 1
            except KeyError: raise OSError('missing')
        registry = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2,
            KEY_WOW64_32KEY=32, KEY_WOW64_64KEY=64, KEY_READ=128, REG_SZ=1, REG_EXPAND_SZ=2,
            OpenKey=lambda parent, name, *args: Key(int(name)) if isinstance(parent, Key) else Key(),
            QueryInfoKey=lambda key: (len(entries), 0, 0), EnumKey=lambda key, index: str(index), QueryValueEx=query)
        # Use a stable ntpath parser without changing pathlib's platform globals.
        import ntpath
        with patch.dict(sys.modules, {'winreg': registry}), patch.object(gi, 'os', SimpleNamespace(name='nt', path=ntpath)):
            self.assertEqual(gi.registry_locations(), [self.source])
