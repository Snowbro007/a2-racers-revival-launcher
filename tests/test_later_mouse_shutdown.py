"""Authored synthetic x86 pumps only; no game bytes or native execution."""
import copy
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import later_mouse_shutdown as fix

PEEK, TRANSLATE, DISPATCH, EXIT = 0x10001000, 0x10001004, 0x10001008, 0x500000


def fixture(game):
    spec = copy.deepcopy(fix.SPECS[game])
    start = spec['pump']
    va = start + 0x400000
    raw = bytearray(b'\xcc' * spec['size'])
    code = bytearray(bytes.fromhex('83ec1c8d4424006a016a006a006a0050ff15'))
    code += struct.pack('<I', PEEK)
    code += bytes.fromhex('85c0742a837c24041275076a00e8')
    code += struct.pack('<i', EXIT - (va + len(code) + 4))
    code += bytes.fromhex('8d4c240051ff15') + struct.pack('<I', TRANSLATE)
    code += bytes.fromhex('8d54240052ff15') + struct.pack('<I', DISPATCH)
    code += bytes.fromhex('33c083c41cc3e8')
    code += struct.pack('<i', spec['mouse_va'] - (va + len(code) + 4))
    code += bytes.fromhex('33c083c41cc390')
    assert len(code) == 0x50
    assert code[0x44:0x49] == spec['before']
    raw[start:start + len(code)] = code
    contexts = []
    for offset, size, _ in spec['contexts']:
        contexts.append((offset, size, hashlib.sha256(raw[offset:offset + size]).hexdigest()))
    raw = bytes(raw)
    spec['contexts'] = tuple(contexts)
    spec['sha256'] = hashlib.sha256(raw).hexdigest()
    return raw, spec


def pump_vm(code, spec, message=None, mouse_initialised=False):
    """Independent, narrow x86 interpreter for queue/quit/idle control flow."""
    base = spec['pump'] + 0x400000
    regs = {'eax': 0xdead, 'ecx': 0xbeef, 'edx': 0xabcd, 'esp': 0x100000,
            'ebx': 1, 'esi': 2, 'edi': 3, 'ebp': 4}
    mem = {regs['esp']: 0xcafebabe}
    counts = {'peek': 0, 'translate': 0, 'dispatch': 0, 'mouse': 0}
    equal = False
    pc = 0

    def push(value):
        regs['esp'] -= 4
        mem[regs['esp']] = value & 0xffffffff

    for _ in range(100):
        op = code[pc:pc + 3]
        if op == b'\x83\xec\x1c':
            regs['esp'] -= 0x1c; pc += 3
        elif op == b'\x83\xc4\x1c':
            regs['esp'] += 0x1c; pc += 3
        elif code[pc:pc + 3] in (b'\x8d\x44\x24', b'\x8d\x4c\x24', b'\x8d\x54\x24'):
            register = {0x44: 'eax', 0x4c: 'ecx', 0x54: 'edx'}[code[pc + 1]]
            regs[register] = regs['esp'] + code[pc + 3]; pc += 4
        elif code[pc] == 0x6a:
            push(code[pc + 1]); pc += 2
        elif code[pc] in (0x50, 0x51, 0x52):
            push(regs[{0x50: 'eax', 0x51: 'ecx', 0x52: 'edx'}[code[pc]]]); pc += 1
        elif code[pc:pc + 2] == b'\xff\x15':
            target = struct.unpack_from('<I', code, pc + 2)[0]
            if target == PEEK:
                counts['peek'] += 1
                pointer = mem[regs['esp']]
                if message is not None: mem[pointer + 4] = message
                regs['eax'] = int(message is not None)
                regs['esp'] += 20
            elif target in (TRANSLATE, DISPATCH):
                counts['translate' if target == TRANSLATE else 'dispatch'] += 1
                regs['esp'] += 4
            else:
                raise AssertionError('Unexpected synthetic import')
            pc += 6
        elif code[pc:pc + 2] == b'\x85\xc0':
            equal = regs['eax'] == 0; pc += 2
        elif code[pc:pc + 4] == b'\x83\x7c\x24\x04':
            equal = mem[regs['esp'] + 4] == code[pc + 4]; pc += 5
        elif code[pc] in (0x74, 0x75):
            taken = equal if code[pc] == 0x74 else not equal
            pc += 2 + (struct.unpack_from('<b', code, pc + 1)[0] if taken else 0)
        elif code[pc] == 0xe8:
            target = base + pc + 5 + struct.unpack_from('<i', code, pc + 1)[0]
            if target == EXIT:
                return {'kind': 'exit', 'exit_code': mem[regs['esp']], 'counts': counts, 'regs': regs}
            if target != spec['mouse_va']: raise AssertionError('Unexpected direct call')
            counts['mouse'] += 1
            if not mouse_initialised:
                return {'kind': 'native-mouse-error', 'exit_code': 1, 'counts': counts, 'regs': regs}
            pc += 5
        elif code[pc:pc + 2] == b'\x33\xc0':
            regs['eax'] = 0; pc += 2
        elif code[pc] == 0x90:
            pc += 1
        elif code[pc] == 0xc3:
            assert mem[regs['esp']] == 0xcafebabe
            regs['esp'] += 4
            return {'kind': 'returned', 'value': regs['eax'], 'counts': counts, 'regs': regs}
        else:
            raise AssertionError('Unexpected opcode at ' + hex(pc))
    raise AssertionError('Synthetic pump did not terminate')


class ShutdownTests(unittest.TestCase):
    def patch_fixture(self, game):
        raw, spec = fixture(game)
        with patch.dict(fix.SPECS, {game: spec}):
            result, plan = fix.patch(raw, game)
        return raw, result, plan, spec

    def test_empty_queue_no_longer_polls_an_uninitialised_mouse(self):
        for game in fix.SPECS:
            with self.subTest(game=game):
                raw, result, _, spec = self.patch_fixture(game)
                start = spec['pump']
                original = pump_vm(raw[start:start + 0x50], spec)
                changed = pump_vm(result[start:start + 0x50], spec)
                self.assertEqual(original['kind'], 'native-mouse-error')
                self.assertEqual(original['exit_code'], 1)
                self.assertEqual(changed['kind'], 'returned')
                self.assertEqual(changed['value'], 0)
                self.assertEqual(changed['counts']['mouse'], 0)
                self.assertEqual(changed['regs']['esp'], 0x100004)
                for name, value in [('ebx', 1), ('esi', 2), ('edi', 3), ('ebp', 4)]:
                    self.assertEqual(changed['regs'][name], value)

    def test_wm_quit_exit_zero_and_normal_dispatch_are_unchanged(self):
        for game in fix.SPECS:
            raw, result, _, spec = self.patch_fixture(game)
            start = spec['pump']
            for message in (0x12, 0x200, 0x6):
                with self.subTest(game=game, message=message):
                    old = pump_vm(raw[start:start + 0x50], spec, message=message)
                    new = pump_vm(result[start:start + 0x50], spec, message=message)
                    self.assertEqual(old, new)
                    if message == 0x12:
                        self.assertEqual((new['kind'], new['exit_code']), ('exit', 0))
                    else:
                        self.assertEqual((new['counts']['translate'], new['counts']['dispatch']), (1, 1))
                        self.assertEqual(new['regs']['esp'], 0x100004)

    def test_only_idle_call_changes_and_native_error_context_is_not_suppressed(self):
        for game in fix.SPECS:
            raw, result, plan, spec = self.patch_fixture(game)
            offset = spec['idle']
            self.assertEqual(result[:offset], raw[:offset])
            self.assertEqual(result[offset + 5:], raw[offset + 5:])
            self.assertEqual(result[offset:offset + 5], b'\x90' * 5)
            self.assertEqual(len(result), len(raw))
            self.assertFalse(plan['runtime_verified'])
            self.assertFalse(plan['exit_codes_modified'])
            self.assertTrue(plan['native_mouse_error_handler_preserved'])
            self.assertEqual(plan['patches'], [{'offset': offset, 'before': spec['before'].hex(), 'after': '90' * 5}])
            for start, size, _ in spec['contexts'][1:]:
                self.assertEqual(result[start:start + size], raw[start:start + size])

    def test_unknown_game_type_size_hash_and_repatch_are_refused(self):
        raw, result, _, spec = self.patch_fixture('vakantieracer')
        for game in ('missing', None, [], 1):
            with self.subTest(game=game), self.assertRaises(ValueError): fix.patch(raw, game)
        with patch.dict(fix.SPECS, {'vakantieracer': spec}):
            for data in (bytearray(raw), raw[:-1], raw + b'0', b'X' + raw[1:], result):
                with self.assertRaises(ValueError): fix.patch(data, 'vakantieracer')

    def test_context_and_opcode_refusals_are_independent_of_the_whole_file_pin(self):
        raw, spec = fixture('vakantieracer')
        for start, _, _ in spec['contexts']:
            changed = bytearray(raw); changed[start] ^= 1; changed = bytes(changed)
            alternate = copy.deepcopy(spec); alternate['sha256'] = hashlib.sha256(changed).hexdigest()
            with patch.dict(fix.SPECS, {'vakantieracer': alternate}), self.assertRaisesRegex(ValueError, 'context'):
                fix.patch(changed, 'vakantieracer')
        changed = bytearray(raw); changed[spec['idle']] = 0x90; changed = bytes(changed)
        alternate = copy.deepcopy(spec); alternate['sha256'] = hashlib.sha256(changed).hexdigest()
        alternate['contexts'] = tuple((start, size, hashlib.sha256(changed[start:start + size]).hexdigest())
                                      for start, size, _ in spec['contexts'])
        with patch.dict(fix.SPECS, {'vakantieracer': alternate}), self.assertRaisesRegex(ValueError, 'idle'):
            fix.patch(changed, 'vakantieracer')


if __name__ == '__main__': unittest.main()
