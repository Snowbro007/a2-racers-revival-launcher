"""Synthetic buffers and bounded byte interpretation; never run a native game."""
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import ii_menu_cursor_background_fix as fix


def synthetic_menu_cursor_background():
    data = bytearray(b"\xCC" * fix.SOURCE_SIZE)
    marker = b"SYNTHETIC-NOT-A-GAME-PE! "
    data[:len(marker)] = marker
    for offset, expected in fix.CONTEXTS:
        data[offset:offset + len(expected)] = expected
    return bytes(data)


class HideMachine:
    """Read only the hide/wrapper bytes from a synthetic non-PE fixture.

    Unknown opcodes/targets fail. Low-level restore and ShowCursor are fake
    services with explicit cdecl/stdcall contracts; no DirectDraw/Windows API
    or original game file is used. At most 120 instructions are interpreted.
    """
    RETURN = 0xDEADBEEF
    INITIAL_SP = 0x100000
    TEXT_DELTA = 0x400C00

    def __init__(self, source, *, saved=(-1, -1), enabled=True, visible=True,
                 initialized=True, animation=True):
        self.source = source
        self.pc = 0x410060
        self.r = {"eax": 0x11111111, "ecx": 0x22222222, "edx": 0x33333333,
                  "ebx": 0x44444444, "ebp": 0x55555555, "esi": 0x66666666,
                  "edi": 0x77777777, "esp": self.INITIAL_SP}
        self.initial = self.r.copy()
        self.mem = {self.INITIAL_SP: self.RETURN,
                    0x43FFDC: int(initialized), 0x437D5C: 2,
                    0x43FFE4: int(animation), 0x43FFE0: int(enabled), 0x43FFE8: int(visible),
                    0x437D38: saved[0] & 0xFFFFFFFF, 0x437D3C: saved[1] & 0xFFFFFFFF}
        self.calls = []
        self.z = False

    def read(self, size):
        offset = self.pc - self.TEXT_DELTA
        allowed = any(start <= offset and offset + size <= start + len(data)
                      for start, data in ((fix.HIDE_OFFSET, fix.HIDE_BYTES),
                                          (fix.WRAPPER_OFFSET, fix.WRAPPER_BYTES)))
        if not allowed:
            raise AssertionError(f"Instruction outside bounded fixture: {self.pc:#x}")
        return self.source[offset:offset + size]

    def push(self, value):
        self.r["esp"] -= 4
        self.mem[self.r["esp"]] = value & 0xFFFFFFFF

    def pop(self):
        value = self.mem[self.r["esp"]]
        self.r["esp"] += 4
        return value

    def call(self, target, resume):
        self.push(resume)
        if target == fix.GUARDED_TARGET_VA:
            self.pc = target
            return
        if target not in (fix.ORIGINAL_TARGET_VA, 0x45142C):
            raise AssertionError(f"Unexpected call/fatal diagnostic: {target:#x}")
        argument = self.mem[self.r["esp"] + 4]
        self.calls.append((target, argument))
        # External routines may clobber volatile registers. The native caller
        # cannot rely on them; nonvolatiles and the caller's argument survive.
        self.r.update(eax=0xABCDEF00, ecx=0xABCDEF01, edx=0xABCDEF02)
        self.pc = self.pop()
        if target == 0x45142C:
            self.r["esp"] += 4  # ShowCursor is stdcall; restore is cdecl.

    def run(self):
        for _ in range(120):
            if self.pc == self.RETURN:
                return self
            op = self.read(1)[0]
            if op == 0xA1:
                address = struct.unpack_from("<I", self.read(5), 1)[0]
                self.r["eax"] = self.mem[address]; self.pc += 5
            elif op == 0xB8:
                self.r["eax"] = struct.unpack_from("<I", self.read(5), 1)[0]; self.pc += 5
            elif op == 0xC3:
                self.pc = self.pop()
            elif self.read(2) == b"\x85\xC0":
                self.z = self.r["eax"] == 0; self.pc += 2
            elif op in (0x74, 0x75):
                delta = struct.unpack_from("<b", self.read(2), 1)[0]
                taken = self.z if op == 0x74 else not self.z
                self.pc += 2 + (delta if taken else 0)
            elif op == 0x48:
                self.r["eax"] = (self.r["eax"] - 1) & 0xFFFFFFFF
                self.z = self.r["eax"] == 0; self.pc += 1
            elif op == 0x6A:
                self.push(struct.unpack_from("<b", self.read(2), 1)[0]); self.pc += 2
            elif op == 0x68:
                self.push(struct.unpack_from("<I", self.read(5), 1)[0]); self.pc += 5
            elif op == 0xE8:
                delta = struct.unpack_from("<i", self.read(5), 1)[0]
                resume = self.pc + 5
                self.call(resume + delta, resume)
            elif self.read(3) == b"\x83\xC4\x04":
                self.r["esp"] += 4; self.pc += 3
            elif self.read(3) == b"\x83\xC8\xFF":
                self.r["eax"] = 0xFFFFFFFF; self.z = False; self.pc += 3
            elif self.read(2) == b"\xFF\x15":
                target = struct.unpack_from("<I", self.read(6), 2)[0]
                self.call(target, self.pc + 6)
            elif self.read(2) == b"\xC7\x05":
                address, value = struct.unpack_from("<II", self.read(10), 2)
                self.mem[address] = value; self.pc += 10
            elif self.read(2) == b"\x83\x3D":
                instruction = self.read(7)
                address = struct.unpack_from("<I", instruction, 2)[0]
                self.z = self.mem[address] == instruction[6]; self.pc += 7
            elif self.read(2) == b"\x8B\x0D":
                address = struct.unpack_from("<I", self.read(6), 2)[0]
                self.r["ecx"] = self.mem[address]; self.pc += 6
            elif self.read(2) == b"\x3B\xC8":
                self.z = self.r["ecx"] == self.r["eax"]; self.pc += 2
            elif self.read(2) == b"\x39\x05":
                address = struct.unpack_from("<I", self.read(6), 2)[0]
                self.z = self.mem[address] == self.r["eax"]; self.pc += 6
            elif self.read(4) == b"\x8B\x44\x24\x04":
                self.r["eax"] = self.mem[self.r["esp"] + 4]; self.pc += 4
            elif op == 0x50:
                self.push(self.r["eax"]); self.pc += 1
            else:
                raise AssertionError(f"Unknown fixture instruction at {self.pc:#x}")
        raise AssertionError("Bounded hide interpretation did not return")


class MenuCursorBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.source = synthetic_menu_cursor_background()
        self.expected = (self.source[:fix.PATCH_OFFSET] + fix.AFTER +
                         self.source[fix.PATCH_OFFSET + len(fix.BEFORE):])
        for name, value in (("SOURCE_SHA256", hashlib.sha256(self.source).hexdigest()),
                            ("PATCHED_SHA256", hashlib.sha256(self.expected).hexdigest())):
            effect = patch.object(fix, name, value)
            effect.start(); self.addCleanup(effect.stop)

    def test_only_two_displacement_bytes_change_with_original_hand_and_cleanup_intact(self):
        before = self.source
        after, plan = fix.patch_menu_cursor_background(before)
        self.assertEqual(before, self.source)
        self.assertEqual(after, self.expected)
        self.assertEqual(len(after), fix.SOURCE_SIZE)
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b],
                         [0xF480, 0xF481])
        for instruction, target in ((fix.BEFORE, fix.ORIGINAL_TARGET_VA),
                                    (fix.AFTER, fix.GUARDED_TARGET_VA)):
            self.assertEqual(fix.PATCH_VA + 5 + struct.unpack_from("<i", instruction, 1)[0], target)
        self.assertEqual(after[fix.PATCH_OFFSET - 2:fix.PATCH_OFFSET], b"\x6A\x00")
        self.assertEqual(after[fix.PATCH_OFFSET + 5:fix.PATCH_OFFSET + 8], b"\x83\xC4\x04")
        for offset, context in fix.CONTEXTS[1:]:
            self.assertEqual(after[offset:offset + len(context)], context)
        self.assertTrue(plan["software_cursor_preserved"])
        for field in ("runtime_tested", "black_corner_fixed", "coordinates_changed",
                      "restores_lost_surfaces", "stale_valid_background_handled"):
            self.assertFalse(plan[field])

    def test_wrong_type_size_hash_and_prepatched_input_are_rejected(self):
        for value in (None, "not bytes", bytearray(self.source), memoryview(self.source),
                      self.source[:-1], self.source + b"!", self.expected,
                      b"!" + self.source[1:]):
            with self.subTest(type=type(value).__name__), self.assertRaises(ValueError):
                fix.patch_menu_cursor_background(value)

    def test_every_context_and_call_site_is_checked_beyond_digest(self):
        for offset in [entry[0] for entry in fix.CONTEXTS] + [fix.PATCH_OFFSET]:
            data = bytearray(self.source); data[offset] ^= 1; data = bytes(data)
            with self.subTest(offset=offset), patch.object(fix, "SOURCE_SHA256", hashlib.sha256(data).hexdigest()), self.assertRaises(ValueError):
                fix.patch_menu_cursor_background(data)

    def test_output_digest_is_an_independent_guard(self):
        with patch.object(fix, "PATCHED_SHA256", "0" * 64), self.assertRaises(ValueError):
            fix.patch_menu_cursor_background(self.source)

    def test_patched_hide_uses_exact_sentinel_and_preserves_stack_and_nonvolatiles(self):
        patched, _ = fix.patch_menu_cursor_background(self.source)
        for saved, restores in (((-1, -1), False), ((-1, 5), False), ((5, -1), False),
                                ((0, 0), True), ((-2, 5), True), ((640, 480), True)):
            with self.subTest(saved=saved):
                original = HideMachine(self.source, saved=saved).run()
                current = HideMachine(patched, saved=saved).run()
                self.assertEqual(original.calls, [(fix.ORIGINAL_TARGET_VA, 0), (0x45142C, 0)])
                self.assertEqual(current.calls, ([(fix.ORIGINAL_TARGET_VA, 0)] if restores else []) + [(0x45142C, 0)])
                for machine in (original, current):
                    self.assertEqual(machine.r["esp"], machine.INITIAL_SP + 4)
                    for register in ("ebx", "ebp", "esi", "edi"):
                        self.assertEqual(machine.r[register], machine.initial[register])
                    self.assertEqual(machine.mem[0x43FFE8], 0)
                    self.assertEqual(machine.mem[0x437D38], saved[0] & 0xFFFFFFFF)
                    self.assertEqual(machine.mem[0x437D3C], saved[1] & 0xFFFFFFFF)
                    self.assertEqual(machine.mem[0x437D5C], 2)

    def test_hidden_or_disabled_cursor_returns_without_restore_or_visibility_call(self):
        patched, _ = fix.patch_menu_cursor_background(self.source)
        for enabled, visible in ((False, False), (False, True), (True, False)):
            with self.subTest(enabled=enabled, visible=visible):
                machine = HideMachine(patched, enabled=enabled, visible=visible).run()
                self.assertEqual(machine.calls, [])
                self.assertEqual(machine.r["esp"], machine.INITIAL_SP + 4)
                self.assertEqual(machine.mem[0x43FFE8], int(visible))
                for register in ("ebx", "ebp", "esi", "edi"):
                    self.assertEqual(machine.r[register], machine.initial[register])

    def test_native_wrapper_still_diagnoses_inconsistent_initialization(self):
        patched, _ = fix.patch_menu_cursor_background(self.source)
        for state in ({"initialized": False}, {"animation": False}):
            with self.subTest(state=state), self.assertRaisesRegex(AssertionError, "fatal diagnostic"):
                HideMachine(patched, saved=(0, 0), **state).run()

    def test_interpreter_refuses_unknown_code_and_targets(self):
        unknown = bytearray(self.expected); unknown[fix.HIDE_OFFSET] = 0x90
        with self.assertRaisesRegex(AssertionError, "Unknown fixture instruction"):
            HideMachine(bytes(unknown)).run()
        unknown = bytearray(self.expected); unknown[fix.PATCH_OFFSET + 1] ^= 1
        with self.assertRaisesRegex(AssertionError, "Unexpected call"):
            HideMachine(bytes(unknown), saved=(0, 0)).run()


if __name__ == "__main__":
    unittest.main()
