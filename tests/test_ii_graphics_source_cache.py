"""Synthetic regular-file II provider caches; no game or helper execution."""
from copy import deepcopy
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import ii_launcher_graphics as graphics
from tools import ii_portable_prepare as portable


class IIGraphicsSourceCacheTests(unittest.TestCase):
    def setUp(self):
        parent = graphics.ROOT/'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='ii-source-cache-', dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.options = dict(graphics.DEFAULTS, race_resolution='4k', race_hud='hd-map',
                            sky_mode='original', race_distance='auto')
        self.content = {
            'game/DATA/SPEL-WIDE.DAT': b'synthetic non-executable race bytes',
            'profiles/widescreen.conf': b'synthetic provider profile',
            'game/DATA/RC.IND': b'synthetic sprite index',
            'game/DATA/RC.IMG': b'synthetic sprite pixels',
            'game/DATA/RCS.IND': b'synthetic resource index',
            'game/DATA/RCS.IMG': b'synthetic resource pixels',
        }
        self.registration = json.dumps({'files': [
            {'path': name, 'sha256': graphics.sha(data)}
            for name, data in self.content.items()
        ]}).encode('utf-8')
        self.sources = {key: (value[0], graphics.sha(self.registration),
                             graphics.sha(self.content['game/DATA/SPEL-WIDE.DAT']))
                        for key, value in graphics.SOURCES.items()}
        sources_patch = patch.object(graphics, 'SOURCES', self.sources)
        sources_patch.start()
        self.addCleanup(sources_patch.stop)
        # The existing composition module separately tests all instruction
        # contexts. Here only provider selection and its unchanged pins vary.
        compose_patch = patch.object(graphics, 'compose_world', side_effect=lambda raw, _: raw)
        compose_patch.start()
        self.addCleanup(compose_patch.stop)

    def cache(self, options=None):
        return graphics.source_cache_folder(self.root, options or self.options)

    def legacy(self, options=None):
        options = options or self.options
        return self.root/'local/ii-parallel'/self.sources[
            options['race_resolution'], options['race_hud']][0]

    def write_provider(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in self.content.items():
            target = folder/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (folder/'Frontend.json').write_bytes(self.registration)

    def test_all_seven_families_use_exact_cache_identifier_and_pins(self):
        for resolution, hud in self.sources:
            with self.subTest(resolution=resolution, hud=hud):
                options = dict(self.options, race_resolution=resolution, race_hud=hud)
                cached = self.cache(options)
                self.assertEqual(cached, self.root/'local/ii-parallel'/
                                 'ii-graphics-sources-v1'/self.sources[resolution, hud][0])
                self.write_provider(cached)
                self.assertEqual(graphics.source_payload(self.root, options), self.content)
                self.assertFalse(self.legacy(options).exists())

    def test_valid_cache_wins_without_reading_linked_legacy_or_portable_source(self):
        options = dict(self.options, race_hud='native')
        self.write_provider(self.cache(options))
        legacy = self.legacy(options)
        original_lstat = Path.lstat

        def no_legacy_access(path):
            if path == legacy or legacy in path.parents:
                self.fail('A valid cache must never inspect the legacy junction.')
            return original_lstat(path)

        with patch.object(Path, 'lstat', no_legacy_access), \
                patch.object(portable, 'native_payload', side_effect=AssertionError('Unexpected fallback')):
            self.assertEqual(graphics.source_payload(self.root, options), self.content)

    def test_missing_cache_preserves_regular_legacy_route_without_creating_cache(self):
        self.write_provider(self.legacy())
        self.assertEqual(graphics.source_payload(self.root, self.options), self.content)
        self.assertFalse(self.cache().exists())

    def test_present_incomplete_cache_never_falls_back_to_valid_legacy(self):
        self.write_provider(self.legacy())
        cached = self.cache()
        cached.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'ontbreekt'):
            graphics.source_payload(self.root, self.options)
        self.assertEqual((self.legacy()/'Frontend.json').read_bytes(), self.registration)

    def test_changed_registration_and_each_payload_are_rejected_without_fallback(self):
        self.write_provider(self.legacy())
        cached = self.cache()
        self.write_provider(cached)
        (cached/'Frontend.json').write_bytes(b'{"files":[]}')
        with self.assertRaisesRegex(ValueError, 'registratie veranderde'):
            graphics.source_payload(self.root, self.options)
        (cached/'Frontend.json').write_bytes(self.registration)
        for name, data in self.content.items():
            with self.subTest(file=name):
                (cached/name).write_bytes(b'changed synthetic payload')
                with self.assertRaisesRegex(ValueError, 'bron veranderde'):
                    graphics.source_payload(self.root, self.options)
                (cached/name).write_bytes(data)

    def test_missing_cache_payload_does_not_fall_back(self):
        self.write_provider(self.legacy())
        self.write_provider(self.cache())
        (self.cache()/'profiles/widescreen.conf').unlink()
        with self.assertRaisesRegex(ValueError, 'ontbreekt'):
            graphics.source_payload(self.root, self.options)

    def test_changed_binary_cannot_be_blessed_by_a_different_registration_pin(self):
        cached = self.cache()
        self.write_provider(cached)
        unknown = b'synthetic unknown binary'
        (cached/'game/DATA/SPEL-WIDE.DAT').write_bytes(unknown)
        registration = json.loads(self.registration)
        registration['files'][0]['sha256'] = graphics.sha(unknown)
        raw = json.dumps(registration).encode('utf-8')
        (cached/'Frontend.json').write_bytes(raw)
        altered = deepcopy(self.sources)
        key = self.options['race_resolution'], self.options['race_hud']
        name, _, binary_pin = altered[key]
        altered[key] = name, graphics.sha(raw), binary_pin
        with patch.object(graphics, 'SOURCES', altered):
            with self.assertRaisesRegex(ValueError, 'Onbekende deel-II-racebinary'):
                graphics.source_payload(self.root, self.options)

    def test_cache_entry_and_ancestor_reparse_points_fail_closed_even_when_dangling(self):
        self.write_provider(self.legacy())
        cached = self.cache()
        original_lstat = Path.lstat
        for linked in (cached, cached.parent):
            with self.subTest(path=linked.name):
                def reparse(path):
                    if path == linked:
                        return SimpleNamespace(st_mode=stat.S_IFDIR | 0o777,
                                               st_nlink=1, st_file_attributes=0x410)
                    return original_lstat(path)
                with patch.object(Path, 'lstat', reparse):
                    with self.assertRaisesRegex(ValueError, 'link/reparse'):
                        graphics.source_payload(self.root, self.options)

    def test_shared_manifest_or_payload_files_are_still_refused(self):
        self.write_provider(self.cache())
        cached = self.cache()
        original_lstat = Path.lstat
        for shared in (cached/'Frontend.json', cached/'game/DATA/RCS.IMG'):
            with self.subTest(file=shared.name):
                def hardlink(path):
                    metadata = original_lstat(path)
                    if path == shared:
                        return SimpleNamespace(st_mode=metadata.st_mode, st_nlink=2,
                                               st_file_attributes=0)
                    return metadata
                with patch.object(Path, 'lstat', hardlink):
                    with self.assertRaisesRegex(ValueError, 'link of gedeeld'):
                        graphics.source_payload(self.root, self.options)

    def test_cache_path_api_rejects_unknown_choices_without_writing(self):
        with self.assertRaises(ValueError):
            graphics.source_cache_folder(self.root, dict(self.options, race_hud='../escape'))
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
