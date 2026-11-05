"""Synthetic bytecode, cached ranges and fake COM only; no native game fixture."""
from __future__ import annotations

import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import later_iv_joystick_input as joy


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def signed(value):
    return value - 0x100000000 if value & 0x80000000 else value


def synthetic_source():
    raw = bytearray(b'\xcc' * joy.SOURCE_SIZE)
    raw[joy.BODY:joy.BODY + len(joy.PREFIX)] = bytes.fromhex(
        'e88f2800008b0850ff51648bcee8f22700008b108dbee0000000576a5050ff5224')
    raw[joy.GENERAL:joy.GENERAL + 4] = bytes.fromhex('85c07458')
    return bytes(raw)


class JoystickVM:
    """Independent interpreter of the emitted poll body and native COM ABI."""
    BUFFER = 0x60000000
    DEVICE, DEVICE2 = 0x10000100, 0x10000200
    VTABLE, VTABLE2 = 0x20000100, 0x20000200

    def __init__(self, code, reads, acquire=0, ranges=((0, 65535),) * 3, poll=0):
        self.code, self.reads = code, list(reads)
        self.acquire_result, self.poll_result = acquire, poll
        self.read_calls = self.acquire_calls = self.poll_calls = self.getter_calls = 0
        self.regs = {'eax': 0, 'ecx': self.BUFFER - 0xE0, 'edx': 0xDDDDDDDD,
                     'esi': self.BUFFER - 0xE0, 'edi': 0xEFEFEFEF,
                     'ebx': 0xABABABAB, 'ebp': 0xBEBEBEBE}
        self.stack = []
        self.ranges = ranges
        self.range_raw = struct.pack('<6i', *(number for pair in ranges for number in pair))
        self.memory = bytearray(b'\x5a' * 8 + b'\xff' * 80 + self.range_raw + b'\xc3' * 8)
        self.equal = False

    @property
    def state(self):
        return bytes(self.memory[8:88])

    def u32(self, at):
        return struct.unpack_from('<I', self.code, at)[0]

    def i32(self, at):
        return struct.unpack_from('<i', self.code, at)[0]

    def memory_read(self, address):
        if address == self.DEVICE:
            return self.VTABLE
        if address == self.DEVICE2:
            return self.VTABLE2
        offset = address - self.BUFFER
        assert 0 <= offset <= 100
        return struct.unpack_from('<I', self.memory, 8 + offset)[0]

    def write_dword(self, address, value):
        offset = address - self.BUFFER
        assert 0 <= offset <= 76, 'State write escaped 80-byte buffer'
        struct.pack_into('<I', self.memory, 8 + offset, value & 0xFFFFFFFF)

    def run(self):
        pc = joy.BODY
        for _ in range(300):
            if pc == joy.END:
                assert not self.stack, 'Unbalanced own/COM argument stack'
                return 'return'
            if pc == joy.GENERAL + 4:
                assert not self.stack, 'Unbalanced fatal argument stack'
                return 'fatal'
            op, pair = self.code[pc], self.code[pc:pc + 2]
            if op == 0xE9:
                pc += 5 + self.i32(pc + 1)
            elif op in (0x74, 0x75):
                take = self.equal if op == 0x74 else not self.equal
                pc += 2 + (struct.unpack_from('<b', self.code, pc + 1)[0] if take else 0)
            elif op == 0xE2:
                self.regs['ecx'] = (self.regs['ecx'] - 1) & 0xFFFFFFFF
                pc += 2 + (struct.unpack_from('<b', self.code, pc + 1)[0] if self.regs['ecx'] else 0)
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
            elif op in (0xB8, 0xB9):
                self.regs['eax' if op == 0xB8 else 'ecx'] = self.u32(pc + 1)
                pc += 5
            elif pair in (b'\x8d\xbe', b'\x8d\x9e'):
                self.regs['edi' if pair[1] == 0xBE else 'ebx'] = self.regs['esi'] + self.u32(pc + 2)
                pc += 6
            elif pair in (b'\x8b\x08', b'\x8b\x10'):
                self.regs['ecx' if pair[1] == 8 else 'edx'] = self.memory_read(self.regs['eax'])
                pc += 2
            elif pair == b'\x8b\xce':
                self.regs['ecx'] = self.regs['esi']
                pc += 2
            elif self.code[pc:pc + 3] == bytes.fromhex('8b4304'):
                self.regs['eax'] = self.memory_read(self.regs['ebx'] + 4)
                pc += 3
            elif pair == b'\x2b\x03':
                self.regs['eax'] = (self.regs['eax'] - self.memory_read(self.regs['ebx'])) & 0xFFFFFFFF
                pc += 2
            elif op == 0x99:
                self.regs['edx'] = 0xFFFFFFFF if self.regs['eax'] & 0x80000000 else 0
                pc += 1
            elif pair == b'\x2b\xc2':
                self.regs['eax'] = (self.regs['eax'] - self.regs['edx']) & 0xFFFFFFFF
                pc += 2
            elif pair == b'\xd1\xf8':
                self.regs['eax'] = (signed(self.regs['eax']) >> 1) & 0xFFFFFFFF
                pc += 2
            elif op in (0x50, 0x53, 0x57):
                self.stack.append(self.regs[{0x50: 'eax', 0x53: 'ebx', 0x57: 'edi'}[op]])
                pc += 1
            elif op in (0x58, 0x5B):
                self.regs['eax' if op == 0x58 else 'ebx'] = self.stack.pop()
                pc += 1
            elif op == 0x6A:
                self.stack.append(self.code[pc + 1])
                pc += 2
            elif op == 0xAB:
                self.write_dword(self.regs['edi'], self.regs['eax'])
                self.regs['edi'] += 4
                pc += 1
            elif pair == b'\xf3\xab':
                assert self.regs['ecx'] in (4, 20)
                while self.regs['ecx']:
                    self.write_dword(self.regs['edi'], self.regs['eax'])
                    self.regs['edi'] += 4
                    self.regs['ecx'] -= 1
                pc += 2
            elif self.code[pc:pc + 3] == bytes.fromhex('83c308'):
                self.regs['ebx'] += 8
                pc += 3
            elif self.code[pc:pc + 3] == bytes.fromhex('83c714'):
                self.regs['edi'] += 20
                pc += 3
            elif op == 0xE8:
                target = joy.IMAGE_BASE + pc + 5 + self.i32(pc + 1)
                assert target in (0x4F1D30, 0x4F1DC0)
                assert self.regs['ecx'] == self.regs['esi']
                self.getter_calls += 1
                self.regs['eax'] = self.DEVICE if target == 0x4F1D30 else self.DEVICE2
                pc += 5
            elif self.code[pc:pc + 3] == bytes.fromhex('ff5164'):
                assert self.regs['ecx'] == self.VTABLE2
                assert self.stack.pop() == self.DEVICE2
                self.poll_calls += 1
                assert self.poll_calls == 1
                self.regs.update(eax=self.poll_result, ecx=0xCCCCCCCC, edx=0xDDDDDDDD)
                self.equal = False
                pc += 3
            elif self.code[pc:pc + 3] == bytes.fromhex('ff5224'):
                assert self.regs['edx'] == self.VTABLE
                assert self.stack.pop() == self.DEVICE
                assert self.stack.pop() == 80
                assert self.stack.pop() == self.BUFFER
                assert self.read_calls < len(self.reads), 'Unbounded additional GetDeviceState'
                hr = self.reads[self.read_calls]
                self.read_calls += 1
                count = 80 if hr == 0 else 8
                self.memory[8:8 + count] = bytes([0x20 + self.read_calls]) * count
                self.regs.update(eax=hr, ecx=0xCCCCCCCC, edx=0xDDDDDDDD)
                self.equal = False
                pc += 3
            elif self.code[pc:pc + 3] == bytes.fromhex('ff511c'):
                assert self.regs['ecx'] == self.VTABLE
                assert self.stack.pop() == self.DEVICE
                self.acquire_calls += 1
                assert self.acquire_calls <= 1, 'Acquire loop within one poll'
                self.regs.update(eax=self.acquire_result, ecx=0xCCCCCCCC, edx=0xDDDDDDDD)
                self.equal = False
                pc += 3
            else:
                raise AssertionError('Unexpected emitted opcode at ' + hex(pc) + ': ' + self.code[pc:pc + 8].hex())
        raise AssertionError('Joystick poll did not terminate')


class IVJoystickPatchTests(unittest.TestCase):
    def setUp(self):
        self.original = synthetic_source()
        contexts = tuple((o, n, sha(self.original[o:o + n])) for o, n, _ in joy.CONTEXTS)
        for value in (patch.object(joy, 'SOURCE_SHA256', sha(self.original)),
                      patch.object(joy, 'CONTEXTS', contexts)):
            value.start()
            self.addCleanup(value.stop)
        self.output, self.plan = joy.patch(self.original)

    def simulate(self, reads, acquire=0, **kwargs):
        vm = JoystickVM(self.output, reads, acquire, **kwargs)
        result = vm.run()
        self.assertEqual(vm.memory[:8], b'\x5a' * 8)
        self.assertEqual(vm.memory[88:112], vm.range_raw)
        self.assertEqual(vm.memory[112:], b'\xc3' * 8)
        self.assertEqual(vm.regs['esi'], vm.BUFFER - 0xE0)
        self.assertEqual((vm.regs['ebx'], vm.regs['ebp']), (0xABABABAB, 0xBEBEBEBE))
        self.assertEqual(vm.poll_calls, 1)
        return result, vm

    def assert_neutral(self, vm):
        axes = struct.unpack_from('<3i', vm.state)
        centers = tuple(int((hi - lo) / 2) for lo, hi in vm.ranges)
        self.assertEqual(axes, centers)
        self.assertEqual(vm.state[12:32], bytes(20))
        self.assertEqual(struct.unpack_from('<4I', vm.state, 32), (0xFFFFFFFF,) * 4)
        self.assertEqual(vm.state[48:], bytes(32))
        # Independent form of the three pinned native normalizations. Literal
        # zero or a fixed 32767 would fail the asymmetric/custom range cases.
        self.assertEqual((axes[0] / centers[0] - 1,
                          1 - axes[1] / centers[1], axes[2] / centers[2] - 1), (0, 0, 0))

    def test_success_retains_all_80_actual_bytes_and_com_abi(self):
        result, vm = self.simulate([0])
        self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 1, 0))
        self.assertEqual(vm.state, b'\x21' * 80)

    def test_both_temporary_errors_reacquire_once_and_success_keeps_device_state(self):
        for first in (0x8007001E, 0x8007000C):
            with self.subTest(first=hex(first)):
                result, vm = self.simulate([first, 0])
                self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 2, 1))
                self.assertEqual(vm.state, b'\x22' * 80)

    def test_temporary_retry_errors_are_typed_neutral_and_hresult_preserved(self):
        for first in (0x8007001E, 0x8007000C):
            for retry in (0x8007001E, 0x8007000C):
                with self.subTest(first=hex(first), retry=hex(retry)):
                    result, vm = self.simulate([first, retry])
                    self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 2, 1))
                    self.assert_neutral(vm)
                    self.assertEqual(vm.regs['eax'], retry)

    def test_any_acquire_failure_keeps_early_return_and_discards_partial_read(self):
        for acquire in (0x8007001E, 0x8007000C, 0x80004005, 0x8007000E, 1):
            with self.subTest(acquire=hex(acquire)):
                result, vm = self.simulate([0x8007000C], acquire)
                self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('return', 1, 1))
                self.assert_neutral(vm)
                self.assertEqual(vm.regs['eax'], acquire)

    def test_neutral_axes_use_cached_native_ranges_instead_of_assumed_center(self):
        for ranges in (((0, 65535), (0, 65535), (0, 65535)),
                       ((0, 1000), (-100, 300), (100, 800)),
                       ((-32768, 32767), (0, 2001), (10, 10010))):
            with self.subTest(ranges=ranges):
                result, vm = self.simulate([0x8007001E], 0x8007000C, ranges=ranges)
                self.assertEqual(result, 'return')
                self.assert_neutral(vm)

    def test_unknown_first_read_errors_remain_fatal_157(self):
        for hr in (0x80004005, 0x8007000E, 1, 0xFFFFFFFF):
            with self.subTest(hr=hex(hr)):
                result, vm = self.simulate([hr])
                self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('fatal', 1, 0))
                self.assertEqual(vm.regs['eax'], hr)

    def test_unknown_retry_errors_stay_fatal_without_another_acquire(self):
        for hr in (0x80004005, 0x8007000E, 1):
            with self.subTest(hr=hex(hr)):
                result, vm = self.simulate([0x8007001E, hr])
                self.assertEqual((result, vm.read_calls, vm.acquire_calls), ('fatal', 2, 1))
                self.assertEqual(vm.regs['eax'], hr)

    def test_original_poll_hresult_is_still_ignored_not_newly_suppressed(self):
        result, vm = self.simulate([0], poll=0x8007000C)
        self.assertEqual(result, 'return')
        self.assertEqual(vm.state, b'\x21' * 80)

    def test_only_pinned_177_byte_body_changes_prefix_seh_and_general_path_preserved(self):
        self.assertEqual(len(self.plan['patches']), 1)
        row = self.plan['patches'][0]
        self.assertEqual(row['offset'], joy.BODY)
        self.assertEqual(len(bytes.fromhex(row['before'])), 177)
        self.assertEqual(len(self.output), len(self.original))
        self.assertEqual(self.output[:joy.BODY], self.original[:joy.BODY])
        self.assertEqual(self.output[joy.GENERAL:], self.original[joy.GENERAL:])
        self.assertEqual(self.output[joy.BODY:joy.BODY + len(joy.PREFIX)], joy.PREFIX)
        self.assertEqual(self.original, synthetic_source())
        self.assertEqual(self.plan['helper_bytes'], 176)
        self.assertFalse(self.plan['runtime_verified'])

    def test_unknown_version_type_size_and_repatch_refused(self):
        for raw in (bytearray(self.original), self.original[:-1], b'unknown', self.output):
            with self.subTest(kind=type(raw).__name__, size=len(raw)):
                with self.assertRaises(ValueError):
                    joy.patch(raw)

    def test_normalizer_range_and_full_poll_contexts_are_independently_pinned(self):
        for offset, size, _ in joy.CONTEXTS:
            changed = bytearray(self.original)
            changed[offset + size - 1] ^= 1
            changed = bytes(changed)
            with self.subTest(offset=hex(offset)), patch.object(joy, 'SOURCE_SHA256', sha(changed)):
                with self.assertRaisesRegex(ValueError, 'context'):
                    joy.patch(changed)


if __name__ == '__main__':
    unittest.main()
