"""Synthetic edge pixels and bounded instruction interpretation; no native game."""
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import ii_menu_cursor_edge_fix as fix
from tools import ii_menu_cursor_background_fix as background
from tests.test_ii_menu_cursor_background_fix import HideMachine, synthetic_menu_cursor_background


def synthetic_menu_cursor_edges():
    data = bytearray(synthetic_menu_cursor_background())
    for offset, value in fix.CONTEXTS:
        data[offset:offset+len(value)] = value
    return bytes(data)


class CursorEdgeTests(unittest.TestCase):
    def setUp(self):
        self.source = synthetic_menu_cursor_edges()
        self.stage = (self.source[:background.PATCH_OFFSET]+background.AFTER+
                      self.source[background.PATCH_OFFSET+5:])
        output = bytearray(self.stage)
        output[fix.GUARD_OFFSET:fix.GUARD_OFFSET+21] = fix.GUARD_AFTER
        output[fix.POSITION_OFFSET:fix.POSITION_OFFSET+8] = fix.POSITION_AFTER
        self.expected = bytes(output)
        for module, name, data in (
                (background, 'SOURCE_SHA256', self.source),
                (background, 'PATCHED_SHA256', self.stage),
                (fix, 'SOURCE_SHA256', self.source),
                (fix, 'PATCHED_SHA256', self.expected)):
            item = patch.object(module, name, hashlib.sha256(data).hexdigest())
            item.start(); self.addCleanup(item.stop)

    def test_composition_keeps_hand_code_and_changes_only_three_declared_regions(self):
        before = self.source
        result, plans = fix.patch_menu_cursor_edges(before)
        self.assertEqual(result, self.expected); self.assertEqual(before, self.source)
        self.assertEqual(len(result), len(before))
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, result)) if a != b],
                         [0xF480, 0xF481, *range(0xFC99, 0xFCA4), *range(0x36738, 0x36740)])
        self.assertEqual(result[background.INITIALIZER_OFFSET:background.INITIALIZER_OFFSET+len(background.INITIALIZER_BYTES)],background.INITIALIZER_BYTES)
        for offset, content in ((fix.CAPTURE_BOUNDS_OFFSET, fix.CAPTURE_BOUNDS),
                                (fix.CAPTURE_SAVE_OFFSET, fix.CAPTURE_SAVE)):
            self.assertEqual(result[offset:offset+len(content)],content)
        self.assertEqual(plans[0]['patched_sha256'],plans[1]['source_sha256'])
        self.assertFalse(plans[1]['runtime_tested']);self.assertFalse(plans[1]['cursor_trails_fixed'])

    def test_guard_branches_reach_existing_ret_and_initial_positions_match_comparison(self):
        result,_ = fix.patch_menu_cursor_edges(self.source)
        self.assertEqual(struct.unpack_from('<ii', result, fix.POSITION_OFFSET),
                         (fix.INVALID_POSITION, fix.INVALID_POSITION))
        self.assertEqual(struct.unpack_from('<i',result,fix.GUARD_OFFSET+1)[0],fix.INVALID_POSITION)
        for site in (0xFCA4,0xFCAC):
            self.assertEqual(result[site],0x74)
            self.assertEqual(site+2+struct.unpack_from('<b',result,site+1)[0],0xFCBB)
        self.assertEqual(result[0xFCBB],0xC3)

    def test_real_guard_instructions_restore_minus_one_but_skip_uninitialized_positions(self):
        result,_ = fix.patch_menu_cursor_edges(self.source)
        invalid = fix.INVALID_POSITION
        for saved, restore in (((-1, 10),True), ((10,-1),True), ((-1,-1),True),
                               ((0,0),True), ((-2,10),True),
                               ((invalid,invalid),False), ((invalid,10),False), ((10,invalid),False)):
            with self.subTest(saved=saved):
                machine = HideMachine(result,saved=saved).run()
                self.assertEqual(machine.calls, ([(background.ORIGINAL_TARGET_VA,0)] if restore else [])+[(0x45142C,0)])
                self.assertEqual(machine.r['esp'],machine.INITIAL_SP+4)
                for register in ('ebx','ebp','esi','edi'):
                    self.assertEqual(machine.r[register],machine.initial[register])

    def test_synthetic_pixels_reproduce_old_edge_trails_and_clean_new_hand_path(self):
        """Exercise real guard bytes while fake surfaces use independent pixels."""
        result,_ = fix.patch_menu_cursor_edges(self.source)
        width,height = 48,64
        clean = {(x,y):1+y*width+x for y in range(height) for x in range(width)}
        # Small synthetic asymmetric sprite; no original game image fixture.
        shape = {(x,y) for y in range(7) for x in range(5) if x<=y}
        path = [(-1,3),(-1,19),(-1,35),(10,-1),(25,48)]

        def draw_path(binary):
            pixels = dict(clean); previous = None; saved_pixels = {}
            for current in path:
                if previous is not None:
                    machine = HideMachine(binary,saved=previous).run()
                    if any(target==background.ORIGINAL_TARGET_VA for target,_ in machine.calls):
                        pixels.update(saved_pixels)
                x,y = current
                # Save/restore the clipped rectangle, draw only sprite pixels.
                region = {(x+dx,y+dy) for dy in range(7) for dx in range(5)
                          if 0<=x+dx<width and 0<=y+dy<height}
                saved_pixels = {point:pixels[point] for point in region}
                for dx,dy in shape:
                    point=x+dx,y+dy
                    if point in pixels:pixels[point]=-1
                previous=current
            return pixels

        expected = dict(clean)
        for dx,dy in shape:expected[path[-1][0]+dx,path[-1][1]+dy]=-1
        old = draw_path(self.stage)
        self.assertNotEqual(old,expected)
        self.assertTrue(any(old[point]==-1 and expected[point]!=-1 for point in clean if point[0]<4))
        self.assertEqual(draw_path(result),expected)

    def test_minus_one_can_capture_pixels_but_reserved_sentinel_cannot(self):
        def clipped(x,y,w=27,h=41):
            return max(0,min(640,x+w)-max(0,x))*max(0,min(480,y+h)-max(0,y))
        self.assertGreater(clipped(-1,20),0)
        self.assertGreater(clipped(20,-1),0)
        self.assertEqual(clipped(fix.INVALID_POSITION,20,w=64,h=64),0)
        self.assertEqual(clipped(20,fix.INVALID_POSITION,w=64,h=64),0)

    def test_unknown_mutable_prepatched_or_partial_versions_fail_closed(self):
        for value in (None,bytearray(self.source),self.source[:-1],self.source+b'x',self.stage,self.expected):
            with self.subTest(kind=type(value).__name__),self.assertRaises(ValueError):
                fix.patch_menu_cursor_edges(value)
        # Invalid paired guard/data contexts remain refused even if the
        # fixture's full digest is explicitly re-pinned by the test.
        for offset,_ in fix.CONTEXTS:
            changed=bytearray(self.source);changed[offset]^=1;changed=bytes(changed)
            with patch.object(fix,'SOURCE_SHA256',hashlib.sha256(changed).hexdigest()),self.assertRaises(ValueError):
                fix.patch_menu_cursor_edges(changed)
        with patch.object(fix,'PATCHED_SHA256','0'*64),self.assertRaises(ValueError):
            fix.patch_menu_cursor_edges(self.source)


if __name__ == '__main__':
    unittest.main()
