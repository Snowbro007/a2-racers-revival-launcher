"""Synthetic pinned-code fixtures, never real game bytes or execution."""
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import ii_minimap_size as minimap


class MinimapSizeTests(unittest.TestCase):
    def setUp(self):
        hud = minimap.hud
        target = hud.wide.IMAGE_BASE + hud.wide.SECTION_RVA
        stub = hud.build_radar_stub(target, (3840, 2160))
        offset = hud.wide.SECTION_RAW_OFFSET
        source = bytearray(offset + len(stub) + 512)
        source[offset:offset + len(stub)] = stub
        va, hook, original = hud.RADAR_HOOK
        source[hook:hook + 5] = b'\xe9' + struct.pack('<i', target - va - 5)
        self.variants = [(minimap.distance.PATCH_OFFSET, b'\x48', b'\x90'),
                         (minimap.distance.LIMIT_OFFSET + 2, b'\x32', b'\x3c'),
                         (minimap.distance.LIMIT_OFFSET + 11, b'\x32', b'\x3c'),
                         *minimap.horizon.PATCHES,
                         *((off, before, b'\x90' * len(before))
                           for off, before in (minimap.sky.CLOUD_CALL, minimap.sky.BITMAP_CALL))]
        for off, before, _ in self.variants:
            source[off:off + len(before)] = before
        self.source = bytes(source)
        self.factor = offset + len(stub) - 4
        pin = patch.object(minimap, 'SOURCE_SHA256', hashlib.sha256(self.source).hexdigest())
        pin.start()
        self.addCleanup(pin.stop)

    def test_only_the_existing_radar_factor_changes(self):
        result, report = minimap.patch(self.source)
        self.assertEqual(len(result), len(self.source))
        self.assertEqual(result[:self.factor], self.source[:self.factor])
        self.assertEqual(result[self.factor + 4:], self.source[self.factor + 4:])
        self.assertEqual(struct.unpack_from('<f', result, self.factor)[0], 3.5)
        self.assertEqual(report['factor_offset'], self.factor)
        self.assertFalse(report['runtime_tested'])
        self.assertFalse(report['native_game_executed'])
        self.assertAlmostEqual(report['scale_after'] / report['scale_before'], 7 / 6)

    def test_accepted_world_options_remain_byte_equal(self):
        changed = bytearray(self.source)
        for off, _, after in self.variants:
            changed[off:off + len(after)] = after
        result, _ = minimap.patch(bytes(changed))
        for off, _, after in self.variants:
            self.assertEqual(result[off:off + len(after)], after)

    def test_unrecognized_corruption_and_double_scaling_are_rejected(self):
        for offset in (0, minimap.distance.PATCH_OFFSET, self.factor):
            changed = bytearray(self.source)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                minimap.patch(bytes(changed))
        result, _ = minimap.patch(self.source)
        with self.assertRaises(ValueError):
            minimap.patch(result)
        with self.assertRaises(ValueError):
            minimap.patch(b'unknown')

    def test_even_a_matching_pin_cannot_override_the_exact_helper_contract(self):
        changed = bytearray(self.source)
        changed[self.factor - 8] ^= 1
        with patch.object(minimap, 'SOURCE_SHA256', hashlib.sha256(changed).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'kaarthelper'):
                minimap.patch(bytes(changed))
