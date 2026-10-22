"""Reproducible native-menu preparation using text-only source fixtures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from tools import ii_original_prepare as builder, ii_portable_prepare as portable
from tools import ii_original_launcher as native
from tests.test_ii_original_launcher import PROFILE, MENU, RACE, RASER


class OriginalPreparationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'local/test-fixtures'; parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.source = self.root/'source'
        (self.source/'DATA').mkdir(parents=True)
        for name, raw in {'MENU.DAT': b'unpatched synthetic menu', 'SPEL.DAT': RACE,
                          'RASER.INI': RASER.replace(b'ON=0', b'ON=1')+b'[HELPDESK]\nDEBUGON=0\n',
                          'MENURC.IMG': b'art', 'MENURC.IND': b'index',
                          'RCS.IMG': b'world', 'RCS.IND': b'world-index'}.items():
            (self.source/'DATA'/name).write_bytes(raw)
        self.before = self.tree(self.source)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        def inspect(source):
            return {'source_tree_sha256': portable.sha(portable.encoded(self.tree(source)))}
        self.stack.enter_context(patch.object(portable, 'inspect_source', side_effect=inspect))
        dependencies = [{'relative_path': 'DATA/'+name, 'source_path': 'synthetic-provider', 'data': raw, 'size': len(raw), 'sha256': portable.sha(raw)}
                        for name, raw in {'DDraw.dll': b'synthetic ddraw', 'D3DImm.dll': b'synthetic d3d', 'dgVoodoo.conf': PROFILE}.items()]
        self.stack.enter_context(patch.object(builder.trial_manifest, 'plan_graphics_wrapper', return_value=dependencies))
        self.stack.enter_context(patch.object(builder, 'menu_profile', return_value=PROFILE))
        self.stack.enter_context(patch.object(builder.cursor, 'patch_menu_cursor_edges', return_value=(MENU, [])))
        self.stack.enter_context(patch.object(native, 'PATCHED_SHA256', portable.sha(MENU)))
        self.stack.enter_context(patch.object(builder.cursor, 'PATCHED_SHA256', portable.sha(MENU)))
        self.stack.enter_context(patch.object(builder, 'MENU_PROFILE_SHA256', portable.sha(PROFILE)))
        pins = {'a2racer2': {'DATA/SPEL.DAT': portable.sha(RACE)}}
        self.stack.enter_context(patch.object(native, 'EXPECTED_BINARIES', pins))

    @staticmethod
    def tree(folder):
        return {p.relative_to(folder).as_posix(): portable.sha(p.read_bytes())
                for p in sorted(folder.rglob('*')) if p.is_file()}

    def test_build_is_separate_repeatable_and_preserves_source_and_progress(self):
        result = builder.prepare(self.root, source=self.source)
        self.assertFalse(result['native_game_executed']); self.assertFalse(result['race_runtime_tested'])
        self.assertEqual(self.tree(self.source), self.before)
        base = Path(result['base']); (base/'game/DATA/player.sav').write_bytes(b'progress')
        repeated = builder.prepare(self.root, source=self.source)
        self.assertFalse(repeated['prepared']); self.assertEqual(repeated['base'], result['base'])
        self.assertEqual((base/'game/DATA/player.sav').read_bytes(), b'progress')
        self.assertEqual((base/'game/DATA/SPEL.DAT').read_bytes(), RACE)
        self.assertEqual((base/'game/DATA/MENU.DAT').read_bytes(), MENU)

    def test_failed_verification_publishes_no_registration_or_partial_stage(self):
        original = builder.portable.inspect_source
        calls = 0
        def changing(source):
            nonlocal calls
            result = original(source); calls += 1
            if calls == 3: result['source_tree_sha256'] = 'f'*64
            return result
        with patch.object(portable, 'inspect_source', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'Gamebron veranderde'):
                builder.prepare(self.root, source=self.source)
        self.assertFalse((self.root/'local/ii-parallel/original-current.json').exists())
        self.assertFalse(list((self.root/'local/ii-parallel').glob('.ii-original-build-*')))
        self.assertEqual(self.tree(self.source), self.before)


if __name__ == '__main__': unittest.main()
