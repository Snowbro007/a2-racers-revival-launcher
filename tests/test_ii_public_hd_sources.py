"""Synthetic archive assembly; no game data or native processes."""
import base64
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import ii_public_hd_sources as hd, ii_launcher_graphics as graphics
from tools.ii_hd_hud_assets import FONT_NAMES, decode_font
from tools.ii_frontend_prepare import resource


class PublicHDSourcesTests(unittest.TestCase):
    def fixture(self):
        font = bytearray(b'\xff' * 2048 + b'abcdefgh')
        struct.pack_into('<hhI', font, 65 * 8, 2, 1, len(font))
        font.extend(b'\x01\x02')
        names = (*FONT_NAMES, 'UNRELATED')
        si = bytearray(struct.pack('<H', len(names))); sm = bytearray()
        for name in names:
            si.extend(struct.pack('<20sI', name.encode(), len(sm)))
            sm.extend(bytes(font) if name != 'UNRELATED' else b'keep me')
        ci = bytearray(struct.pack('<H', 453)); cm = bytearray(b'!!')
        frames = {}
        for number in range(1, 454):
            ci.extend(struct.pack('<I', len(cm)))
            cm.extend(struct.pack('<4H', 2, 1, 17, 23) + b'\x01\x02')
            if number >= 426:
                frames[str(number)] = base64.b64encode(b'\x03' * 18).decode()
        spec = {'schema': 1, 'fonts': {name: {'65': base64.b64encode(b'\x04' * 18).decode()}
                 for name in FONT_NAMES}, 'frames': frames}
        return tuple(map(bytes, (ci, cm, si, sm))), spec

    def test_assembled_fonts_and_frames_keep_unselected_records_and_anchors(self):
        inputs, spec = self.fixture()
        raw = json.dumps(spec).encode()
        pins = dict(zip(('RC.IND', 'RC.IMG', 'RCS.IND', 'RCS.IMG'), map(hd.sha, inputs)))
        hd.compile_assets.cache_clear()
        with patch.object(graphics, 'NATIVE_ASSETS', pins), patch.object(hd, 'RECIPE_SHA256', hd.sha(raw)), patch.object(hd, 'OUTPUT_PINS', {}) as outputs:
            # Fixed fixture outputs, derived independently through the public primitives.
            ci, cm = hd.replace_frames(inputs[0], inputs[1], spec['frames'])
            from tools.ii_hd_hud_assets import encode_hd_font, replace_resources
            si, sm = replace_resources(inputs[2], inputs[3], {name: encode_hd_font(
                resource(inputs[2], inputs[3], name), {65: b'\x04' * 18}) for name in FONT_NAMES})
            outputs.update(dict(zip(pins, map(hd.sha, (ci, cm, si, sm)))))
            actual = dict(hd.compile_assets(*inputs, raw))
            self.assertEqual(resource(actual['RCS.IND'], actual['RCS.IMG'], 'UNRELATED'), b'keep me')
            header, glyphs = decode_font(resource(actual['RCS.IND'], actual['RCS.IMG'], FONT_NAMES[0]))
            self.assertEqual((header, glyphs[65]), (b'abcdefgh', (6, 3, b'\x04' * 18)))
            self.assertEqual(actual['RC.IMG'][:4252], inputs[1][:4252])
            offset = struct.unpack_from('<I', actual['RC.IND'], 2 + 425 * 4)[0]
            self.assertEqual(struct.unpack_from('<4H', actual['RC.IMG'], offset), (6, 3, 17, 23))
            with self.assertRaises(ValueError): hd.compile_assets(*inputs, raw + b' ')
            with self.assertRaises(ValueError): hd.compile_assets(inputs[0], inputs[1] + b'x', *inputs[2:], raw)
        hd.compile_assets.cache_clear()

    def test_invalid_frame_boundaries_and_pixel_lengths_are_rejected(self):
        inputs, spec = self.fixture()
        bad = bytearray(inputs[0]); struct.pack_into('<I', bad, 6, 2)
        with self.assertRaises(ValueError): hd.replace_frames(bytes(bad), inputs[1], spec['frames'])
        spec['frames']['426'] = base64.b64encode(b'short').decode()
        with self.assertRaises(ValueError): hd.replace_frames(*inputs[:2], spec['frames'])

    def test_bundled_authored_pixels_are_sealed(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(hd.sha((root / hd.RECIPE).read_bytes()), hd.RECIPE_SHA256)
        from tools import ii_vector_public as vector
        self.assertEqual(vector.vector.sha((root / vector.PAINT).read_bytes()), vector.PAINT_SHA256)
        self.assertEqual(vector.vector.sha((root / vector.PREVIEW).read_bytes()), vector.vector.ART_FILES['vector-menu-front-v3.png'])

    def test_public_fallback_never_hides_a_changed_existing_cache(self):
        parent = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        options = dict(graphics.DEFAULTS, race_resolution='4k', race_hud='hd-map', sky_mode='original')
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            recipe = root / hd.RECIPE; recipe.parent.mkdir(parents=True); recipe.write_bytes(b'fixture')
            payload = {'game/DATA/SPEL-WIDE.DAT': b'synthetic binary'}
            with patch.object(hd, 'source_payload', return_value=payload) as build, patch.dict(
                    graphics.SOURCES, {('4k','hd-map'): ('synthetic-hd-source', 'unused', hd.sha(b'synthetic binary'))}), patch.object(graphics, 'compose_world', side_effect=lambda raw, _: raw):
                self.assertEqual(graphics.source_payload(root, options), payload)
                build.assert_called_once_with(root, '4k', 'hd-map')
                build.reset_mock()
                cached = graphics.source_cache_folder(root, options); cached.mkdir(parents=True)
                (cached / 'Frontend.json').write_bytes(b'changed')
                with self.assertRaises(ValueError): graphics.source_payload(root, options)
                build.assert_not_called()


if __name__ == '__main__': unittest.main()
