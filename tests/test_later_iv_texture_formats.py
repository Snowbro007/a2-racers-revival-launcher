"""Synthetic x86 callback ABI fixtures; no native game binary is executed."""
import copy
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import later_iv_texture_formats as fmt


def fixture():
    raw = bytearray(fmt.SOURCE_SIZE)
    raw[fmt.WARNING:fmt.CONTINUE] = fmt.WARNING_BYTES
    raw[fmt.SUCCESS_EPILOGUE:fmt.SUCCESS_EPILOGUE + 15] = fmt.EPILOGUE_BYTES
    raw[fmt.LAST_UPDATE:fmt.SUCCESS_EPILOGUE] = fmt.LAST_UPDATE_BYTES
    # Synthetic markers bind both selection and writer source contexts.
    raw[0xC2866:0xC286E] = b'ALPHASEL'
    raw[0xC03C8:0xC03D0] = b'WORD2BPP'
    raw = bytes(raw)
    contexts = tuple((o, n, hashlib.sha256(raw[o:o+n]).hexdigest()) for o, n, _ in fmt.CONTEXTS)
    return raw, contexts


class FilterVM:
    def __init__(self, code, bits):
        self.code = code
        self.bits = bits
        self.pc = fmt.WARNING
        self.regs = {'eax': 0xBAD, 'ecx': 0x1234, 'edx': 0x2000,
                     'ebx': 0x3000, 'ebp': 7, 'esi': 0x3333, 'edi': 0x4444}
        # Stack at native callback's RGB branch, after four pushes + 24 locals.
        self.stack = [0xD1, 0x51, 0xB1, 0x31] + [0xA0 + n for n in range(6)] + [0xF00D, 0x2000, 0x3000]
        self.original_stack = self.stack.copy()
        self.equal = False
        self.logs = []
        self.slot_state = {'allocated': [1]*8, 'cursor': 7, 'alpha': 3, 'rgb': 0,
                           'last': 3, 'fallback': 1, 'descriptors': ['synthetic']*8}
        self.before_state = copy.deepcopy(self.slot_state)

    def run(self):
        for _ in range(30):
            if self.pc == fmt.CONTINUE:
                return 'accepted'
            at = self.pc
            if self.code[at:at+3] == bytes.fromhex('8b4254'):
                assert self.regs['edx'] == 0x2000
                self.regs['eax'] = self.bits
                self.pc += 3
            elif self.code[at:at+2] == b'\x83\xf8':
                self.equal = self.regs['eax'] == self.code[at+2]
                self.pc += 3
            elif self.code[at] == 0x74:
                self.pc += 2 + (struct.unpack_from('<b', self.code, at+1)[0] if self.equal else 0)
            elif self.code[at] == 0x50:
                self.stack.insert(0, self.regs['eax']); self.pc += 1
            elif self.code[at] == 0x68:
                self.stack.insert(0, struct.unpack_from('<I', self.code, at+1)[0]); self.pc += 5
            elif self.code[at] == 0xE8:
                target = at + 5 + struct.unpack_from('<i', self.code, at+1)[0]
                assert target == fmt.LOGGER
                assert self.stack[:2] == [fmt.WARNING_STRING, self.bits]
                self.logs.append(tuple(self.stack[:2]))
                # Ordinary cdecl callee may clobber these caller-saved regs.
                self.regs.update(eax=0xBADBAD, ecx=0xEEEE, edx=0xDDDD)
                self.pc += 5
            elif self.code[at] in (0x58, 0x5B, 0x5D, 0x5E, 0x5F):
                reg = {0x58:'eax', 0x5B:'ebx', 0x5D:'ebp', 0x5E:'esi', 0x5F:'edi'}[self.code[at]]
                self.regs[reg] = self.stack.pop(0); self.pc += 1
            elif self.code[at] == 0xE9:
                self.pc += 5 + struct.unpack_from('<i', self.code, at+1)[0]
            elif self.code[at] == 0xB8:
                self.regs['eax'] = struct.unpack_from('<I', self.code, at+1)[0]; self.pc += 5
            elif self.code[at:at+3] == bytes.fromhex('896b5a'):
                self.slot_state['last'] = self.regs['ebp']; self.pc += 3
            elif self.code[at:at+2] == b'\x83\xc4':
                assert self.code[at+2] == 24
                del self.stack[:6]; self.pc += 3
            elif self.code[at] == 0xC2:
                assert struct.unpack_from('<H', self.code, at+1)[0] == 8
                assert self.stack == [0xF00D, 0x2000, 0x3000]
                self.stack.clear()
                return 'rejected'
            else:
                raise AssertionError(f'Unexpected opcode at {at:x}')
        raise AssertionError('Unbounded callback flow')


class IVTextureFormatTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.contexts = fixture()
        contexts = patch.object(fmt, 'CONTEXTS', self.contexts)
        contexts.start(); self.addCleanup(contexts.stop)
        pin = patch.object(fmt, 'SOURCE_SHA256', hashlib.sha256(self.raw).hexdigest())
        pin.start(); self.addCleanup(pin.stop)

    def test_only_seven_warning_cleanup_bytes_change_without_growth(self):
        output, plan = fmt.patch(self.raw)
        self.assertEqual(len(output), len(self.raw))
        self.assertEqual(output[:fmt.PATCH_OFFSET], self.raw[:fmt.PATCH_OFFSET])
        self.assertEqual(output[fmt.CONTINUE:], self.raw[fmt.CONTINUE:])
        self.assertEqual(plan['patch_bytes'], 7)
        self.assertEqual(len(plan['patches']), 1)
        self.assertFalse(plan['runtime_verified'])

    def test_16bit_rgb_and_alpha_keep_original_branch_and_stack(self):
        output, _ = fmt.patch(self.raw)
        vm = FilterVM(output, 16)
        self.assertEqual(vm.run(), 'accepted')
        self.assertEqual(vm.stack, vm.original_stack)
        self.assertEqual(vm.logs, [])
        self.assertEqual(vm.regs['eax'], 16)
        self.assertEqual(vm.regs['edx'], 0x2000)
        self.assertEqual(vm.slot_state, vm.before_state)

    def test_non16_rgb_logs_once_and_returns_enum_continue_with_correct_abi(self):
        output, _ = fmt.patch(self.raw)
        for bits in (0, 8, 15, 24, 32, 64):
            with self.subTest(bits=bits):
                vm = FilterVM(output, bits)
                self.assertEqual(vm.run(), 'rejected')
                self.assertEqual(vm.logs, [(fmt.WARNING_STRING, bits)])
                self.assertEqual(vm.regs['eax'], 1)
                self.assertEqual(vm.stack, [])
                self.assertEqual({k:vm.regs[k] for k in ('ebx','ebp','esi','edi')},
                                 {'ebx':0x31,'ebp':0xB1,'esi':0x51,'edi':0xD1})
                expected = copy.deepcopy(vm.before_state)
                expected['last'] = 7
                self.assertEqual(vm.slot_state, expected)

    def test_full_enum_allocation_links_tail_and_selection_survive_multiple_rejections(self):
        output, _ = fmt.patch(self.raw)
        pool = {'allocated':[False]*12, 'cursor':0, 'last':0, 'fallback':0,
                'rgb':None, 'alpha':None, 'alpha_bits':0,
                'records':[{'prev':0,'next':0} for _ in range(12)]}
        # Native index0 is a zero sentinel in last/fallback bookkeeping.
        sequence = [('palette',8,0),('rgb',16,0),('rgb',32,0),('alpha',32,8),
                    ('alpha',16,4),('rgb',24,0),('alpha',16,1),('alpha',32,8)]
        for kind,bits,alpha in sequence:
            scan=list(range(pool['cursor'],12))+list(range(pool['cursor']))
            index=next(i for i in scan if not pool['allocated'][i])
            pool['allocated'][index]=True;pool['cursor']=index
            previous=pool['last']
            if previous:
                pool['records'][index]['prev']=previous
                pool['records'][previous]['next']=index
            selected=(pool['rgb'],pool['alpha'],pool['alpha_bits'],pool['fallback'])
            if kind!='palette':
                vm=FilterVM(output,bits);vm.regs['ebp']=index;vm.slot_state=pool
                outcome=vm.run()
            else: outcome='accepted'
            if outcome=='accepted':
                if kind=='rgb':pool['rgb']=index
                elif kind=='alpha' and alpha>pool['alpha_bits']:
                    pool['alpha']=index;pool['alpha_bits']=alpha
                if not pool['fallback']:pool['fallback']=index
                pool['last']=index
            else:
                self.assertEqual(outcome,'rejected')
                self.assertEqual((pool['rgb'],pool['alpha'],pool['alpha_bits'],pool['fallback']),selected)
            self.assertEqual(pool['last'],index)
        self.assertEqual(pool['cursor'],7)
        self.assertEqual(pool['rgb'],1);self.assertEqual(pool['alpha'],4)
        self.assertEqual(pool['fallback'],1)
        self.assertEqual(pool['last'],7)
        for index in range(2,8):
            self.assertEqual(pool['records'][index]['prev'],index-1)
            self.assertEqual(pool['records'][index-1]['next'],index)

    def test_palette_paths_allocation_selection_and_writer_are_byte_identical(self):
        output, _ = fmt.patch(self.raw)
        self.assertEqual(output[0xC1E60:fmt.PATCH_OFFSET], self.raw[0xC1E60:fmt.PATCH_OFFSET])
        self.assertEqual(output[fmt.CONTINUE:0xC2A40], self.raw[fmt.CONTINUE:0xC2A40])
        self.assertEqual(output[0xC00B0:0xC0441], self.raw[0xC00B0:0xC0441])

    def test_each_own_callback_writer_and_loader_context_is_required(self):
        for offset, _, _ in self.contexts:
            changed = bytearray(self.raw); changed[offset] ^= 1; changed = bytes(changed)
            with self.subTest(offset=offset), patch.object(fmt,'SOURCE_SHA256',hashlib.sha256(changed).hexdigest()):
                with self.assertRaises(ValueError): fmt.patch(changed)

    def test_unknown_type_size_source_and_second_application_are_refused(self):
        for invalid in (bytearray(self.raw), self.raw[:-1], b'unknown'):
            with self.subTest(kind=type(invalid).__name__), self.assertRaises(ValueError): fmt.patch(invalid)
        changed = bytearray(self.raw); changed[0x100] ^= 1
        with self.assertRaises(ValueError): fmt.patch(bytes(changed))
        output, _ = fmt.patch(self.raw)
        with self.assertRaises(ValueError): fmt.patch(output)


if __name__ == '__main__':
    unittest.main()
