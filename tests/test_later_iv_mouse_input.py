"""Synthetic bytecode and fake COM mouse only; no game files or native APIs."""
from __future__ import annotations

import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import later_iv_mouse_input as mouse


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def synthetic_source():
    raw = bytearray(b'\xcc' * mouse.SOURCE_SIZE)
    native = bytes.fromhex(
        '8b088dbee0000000576a1050ff51243d1e0007800f8585000000'
        '8bcee87e3700008b1050ff521c85c00f85cc000000'
        '8bcee8693700008b08576a1050ff512485c00f84b4000000')
    assert len(native) == 0x47
    raw[mouse.START:mouse.START + len(native)] = native
    raw[mouse.CAVE:mouse.CAVE + 88] = b'\xa7' * 88
    raw[mouse.GENERAL:mouse.GENERAL + 4] = bytes.fromhex('85c07458')
    return bytes(raw)


class MouseVM:
    """Independent decoder for original polling and the emitted detour subset."""
    BUFFER = 0x60000000
    DEVICE = 0x10000100
    VTABLE = 0x20000200

    def __init__(self, code, reads, acquire=0):
        self.code = code
        self.reads = list(reads)
        self.acquire_result = acquire
        self.read_calls = self.acquire_calls = self.getter_calls = 0
        self.regs = {'eax': self.DEVICE, 'ecx': 0xCCCCCCCC, 'edx': 0xDDDDDDDD,
                     'esi': self.BUFFER - 0xE0, 'edi': 0xEFEFEFEF,
                     'ebx': 0xABABABAB, 'ebp': 0xBEBEBEBE}
        self.stack = []
        self.memory = bytearray(b'\x5a' * 8 + b'\xff' * 16 + b'\xc3' * 8)
        self.equal = False

    @property
    def state(self):
        return bytes(self.memory[8:24])

    def u32(self, at):
        return struct.unpack_from('<I', self.code, at)[0]

    def i32(self, at):
        return struct.unpack_from('<i', self.code, at)[0]

    def run(self):
        pc = mouse.START
        for _ in range(250):
            if pc == mouse.END:
                assert not self.stack, 'Unbalanced own/COM arguments'
                return 'return'
            if pc == mouse.GENERAL + 4:
                assert not self.stack, 'Unbalanced fatal-path arguments'
                return 'fatal'
            op = self.code[pc]
            pair = self.code[pc:pc + 2]
            if op == 0xE9:
                pc += 5 + self.i32(pc + 1)
            elif op == 0xEB:
                pc += 2 + struct.unpack_from('<b', self.code, pc + 1)[0]
            elif pair in (b'\x0f\x84', b'\x0f\x85'):
                taken = self.equal if pair[1] == 0x84 else not self.equal
                pc += 6 + (self.i32(pc + 2) if taken else 0)
            elif op == 0x74:
                pc += 2 + (struct.unpack_from('<b', self.code, pc + 1)[0] if self.equal else 0)
            elif op == 0x3D:
                self.equal = self.regs['eax'] == self.u32(pc + 1)
                pc += 5
            elif pair == b'\x85\xc0':
                self.equal = self.regs['eax'] == 0
                pc += 2
            elif pair == b'\x33\xc0':
                self.regs['eax'] = 0
                self.equal = True
                pc += 2
            elif op == 0xB9:
                self.regs['ecx'] = self.u32(pc + 1)
                pc += 5
            elif pair == b'\x8d\xbe':
                self.regs['edi'] = self.regs['esi'] + self.u32(pc + 2)
                pc += 6
            elif pair in (b'\x8b\x08', b'\x8b\x10'):
                assert self.regs['eax'] == self.DEVICE
                self.regs['ecx' if pair[1] == 8 else 'edx'] = self.VTABLE
                pc += 2
            elif pair == b'\x8b\xce':
                self.regs['ecx'] = self.regs['esi']
                pc += 2
            elif op in (0x50, 0x57):
                self.stack.append(self.regs['eax' if op == 0x50 else 'edi'])
                pc += 1
            elif op == 0x58:
                self.regs['eax'] = self.stack.pop()
                pc += 1
            elif op == 0x6A:
                self.stack.append(self.code[pc + 1])
                pc += 2
            elif pair == b'\xf3\xab':
                assert self.regs['edi'] == self.BUFFER
                assert self.regs['ecx'] == 4 and self.regs['eax'] == 0
                self.memory[8:24] = bytes(16)
                self.regs['edi'] += 16
                self.regs['ecx'] = 0
                pc += 2
            elif op == 0xE8:
                assert mouse.IMAGE_BASE + pc + 5 + self.i32(pc + 1) == 0x4F1D30
                assert self.regs['ecx'] == self.regs['esi']
                self.getter_calls += 1
                self.regs['eax'] = self.DEVICE
                pc += 5
            elif self.code[pc:pc + 3] == bytes.fromhex('ff5124'):
                assert self.regs['ecx'] == self.VTABLE
                assert self.stack.pop() == self.DEVICE
                assert self.stack.pop() == 16
                assert self.stack.pop() == self.BUFFER
                assert self.read_calls < len(self.reads), 'Unbounded additional read'
                hr = self.reads[self.read_calls]
                self.read_calls += 1
                # A failed API may leave partial output; the detour must not
                # retain it when returning neutral input.
                self.memory[8:8 + (16 if hr == 0 else 8)] = bytes([0x20 + self.read_calls]) * (16 if hr == 0 else 8)
                self.regs.update(eax=hr, ecx=0xCCCCCCCC, edx=0xDDDDDDDD)
                self.equal = False
                pc += 3
            elif self.code[pc:pc + 3] == bytes.fromhex('ff521c'):
                assert self.regs['edx'] == self.VTABLE
                assert self.stack.pop() == self.DEVICE
                self.acquire_calls += 1
                assert self.acquire_calls <= 1, 'Repeated Acquire within one poll'
                self.regs.update(eax=self.acquire_result, ecx=0xCCCCCCCC, edx=0xDDDDDDDD)
                self.equal = False
                pc += 3
            else:
                raise AssertionError('Unexpected instruction at ' + hex(pc) + ': ' + self.code[pc:pc + 8].hex())
        raise AssertionError('Mouse poll did not terminate')


class IVMousePatchTests(unittest.TestCase):
    def setUp(self):
        self.original = synthetic_source()
        patches = (
            patch.object(mouse, 'SOURCE_SHA256', sha(self.original)),
            patch.object(mouse, 'CONTEXT_SHA256', sha(self.original[mouse.CONTEXT_OFFSET:mouse.CONTEXT_OFFSET + mouse.CONTEXT_SIZE])),
            patch.object(mouse, 'CAVE_BEFORE', b'\xa7' * 88),
        )
        for value in patches:
            value.start()
            self.addCleanup(value.stop)
        self.output, self.plan = mouse.patch(self.original)

    def simulate(self, reads, acquire=0):
        vm = MouseVM(self.output, reads, acquire)
        result = vm.run()
        self.assertEqual(vm.memory[:8], b'\x5a' * 8)
        self.assertEqual(vm.memory[24:], b'\xc3' * 8)
        self.assertEqual(vm.regs['esi'], vm.BUFFER - 0xE0)
        self.assertEqual((vm.regs['ebx'], vm.regs['ebp']), (0xABABABAB, 0xBEBEBEBE))
        return result, vm

    def test_success_preserves_read_state_and_abi_without_acquire(self):
        result, vm = self.simulate([0])
        self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 1, 0))
        self.assertEqual(vm.state, b'\x21' * 16)
        self.assertEqual(vm.regs['eax'], 0)

    def test_both_temporary_first_errors_reacquire_and_read_exactly_once(self):
        for hr in (0x8007001E, 0x8007000C):
            with self.subTest(hr=hex(hr)):
                result, vm = self.simulate([hr, 0])
                self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 2, 1))
                self.assertEqual(vm.state, b'\x22' * 16)

    def test_temporary_retry_errors_return_neutral_state_with_hresult_preserved(self):
        for first in (0x8007001E, 0x8007000C):
            for retry in (0x8007001E, 0x8007000C):
                with self.subTest(first=hex(first), retry=hex(retry)):
                    result, vm = self.simulate([first, retry])
                    self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 2, 1))
                    self.assertEqual(vm.state, bytes(16))
                    self.assertEqual(vm.regs['eax'], retry)

    def test_every_acquire_failure_keeps_original_early_return_and_neutral_output(self):
        for first in (0x8007001E, 0x8007000C):
            for acquire in (0x8007001E, 0x8007000C, 0x80004005, 0x8007000E, 1):
                with self.subTest(first=hex(first), acquire=hex(acquire)):
                    result, vm = self.simulate([first], acquire)
                    self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 1, 1))
                    self.assertEqual(vm.state, bytes(16))
                    self.assertEqual(vm.regs['eax'], acquire)

    def test_unknown_first_read_errors_retain_original_general_exception(self):
        for hr in (0x80004005, 0x8007000E, 1, 0xFFFFFFFF):
            with self.subTest(hr=hex(hr)):
                result, vm = self.simulate([hr])
                self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('fatal', 1, 0))
                self.assertEqual(vm.regs['eax'], hr)

    def test_unknown_retry_errors_remain_fatal_without_another_acquire(self):
        for hr in (0x80004005, 0x8007000E, 1):
            with self.subTest(hr=hex(hr)):
                result, vm = self.simulate([0x8007000C, hr])
                self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('fatal', 2, 1))
                self.assertEqual(vm.regs['eax'], hr)

    def test_only_five_declared_equal_length_ranges_change_and_original_is_immutable(self):
        allowed = set()
        for row in self.plan['patches']:
            before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
            self.assertEqual(len(before), len(after))
            self.assertEqual(self.original[row['offset']:row['offset'] + len(before)], before)
            self.assertEqual(self.output[row['offset']:row['offset'] + len(after)], after)
            allowed.update(range(row['offset'], row['offset'] + len(before)))
        self.assertEqual(len(self.plan['patches']), 5)
        self.assertEqual(len(self.output), len(self.original))
        self.assertTrue({i for i, (a, b) in enumerate(zip(self.original, self.output)) if a != b} <= allowed)
        self.assertEqual(self.original, synthetic_source())
        self.assertLessEqual(self.plan['helper_bytes'], 88)
        self.assertFalse(self.plan['runtime_verified'])
        self.assertEqual(self.plan['device_state_bytes'], 16)

    def test_unknown_input_type_size_hash_and_repatch_are_refused(self):
        for value in (bytearray(self.original), b'unknown', self.original[:-1], self.output):
            with self.subTest(kind=type(value).__name__, size=len(value)):
                with self.assertRaises(ValueError):
                    mouse.patch(value)

    def test_full_context_pin_includes_unmodified_control_flow_and_cave(self):
        for offset in (mouse.CAVE + 2, mouse.START + 8, mouse.END):
            changed = bytearray(self.original)
            changed[offset] ^= 1
            changed = bytes(changed)
            with patch.object(mouse, 'SOURCE_SHA256', sha(changed)):
                with self.assertRaisesRegex(ValueError, 'muispollcontext'):
                    mouse.patch(changed)

    def test_independent_patch_context_checks_do_not_trust_only_rehashed_fixture(self):
        changed = bytearray(self.original)
        changed[mouse.START] ^= 1
        changed = bytes(changed)
        with patch.object(mouse, 'SOURCE_SHA256', sha(changed)), patch.object(
                mouse, 'CONTEXT_SHA256', sha(changed[mouse.CONTEXT_OFFSET:mouse.CONTEXT_OFFSET + mouse.CONTEXT_SIZE])):
            with self.assertRaisesRegex(ValueError, 'patchcontext'):
                mouse.patch(changed)


if __name__ == '__main__':
    unittest.main()
