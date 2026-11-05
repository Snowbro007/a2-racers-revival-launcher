"""Synthetic x86 branch/stack fixture; never execute a game or generated PE."""
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import later_vacation_texture_formats as formats


def synthetic_source():
    raw = bytearray(b'\xCC' * formats.SOURCE_SIZE)
    raw[formats.GUARD:formats.GUARD + 26] = formats.GUARD_BEFORE
    raw[formats.EPILOGUE:formats.EPILOGUE + 15] = formats.EPILOGUE_BEFORE
    raw[formats.LAST_UPDATE:formats.EPILOGUE] = formats.LAST_UPDATE_BEFORE
    return bytes(raw)


class EnumVM:
    """Interpret only the enum warning/filter and its original success epilogue."""
    def __init__(self, raw, bpp):
        self.raw, self.bpp = raw, bpp
        self.pc = formats.GUARD
        self.regs = dict(eax=0xA0, edx=0x2000, ebx=0xB0, ebp=0xB1, esi=0xB2, edi=0xB3)
        self.saved = dict(edi=0xD0, esi=0xD1, ebp=0xD2, ebx=0xD3)
        self.stack = [self.saved[n] for n in ('edi', 'esi', 'ebp', 'ebx')] + [0xC0] * 6 + [0xABCDEF, 0x2000, 0x3000]
        self.calls = []
        self.pool = {'last':7}
        self.zf = False

    def run(self):
        for _ in range(40):
            if self.pc == formats.CONTINUE:
                return 'native-16bit'
            op = self.raw[self.pc]
            if self.raw[self.pc:self.pc+3] == b'\x8b\x42\x54':
                assert self.regs['edx'] == 0x2000
                self.regs['eax'] = self.bpp; self.pc += 3
            elif self.raw[self.pc:self.pc+3] == b'\x83\xf8\x10':
                self.zf = self.regs['eax'] == 16; self.pc += 3
            elif op == 0x74:
                self.pc += 2 + (struct.unpack_from('<b', self.raw, self.pc+1)[0] if self.zf else 0)
            elif op == 0x50:
                self.stack.insert(0, self.regs['eax']); self.pc += 1
            elif op == 0x68:
                self.stack.insert(0, struct.unpack_from('<I', self.raw, self.pc+1)[0]); self.pc += 5
            elif op == 0xE8:
                destination = formats.IMAGE_BASE + self.pc + 5 + struct.unpack_from('<i', self.raw, self.pc+1)[0]
                assert destination == formats.LOGGER_VA
                self.calls.append(('warning', self.stack[1]))
                # cdecl logger may clobber all volatile registers.
                self.regs.update(eax=0x11, edx=0xBAD, ecx=0x22); self.pc += 5
            elif op in (0x58, 0x5B, 0x5D, 0x5E, 0x5F):
                self.regs[{0x58:'eax', 0x5B:'ebx', 0x5D:'ebp', 0x5E:'esi', 0x5F:'edi'}[op]] = self.stack.pop(0)
                self.pc += 1
            elif op == 0xE9:
                self.pc += 5 + struct.unpack_from('<i', self.raw, self.pc+1)[0]
            elif op == 0xB8:
                self.regs['eax'] = struct.unpack_from('<I', self.raw, self.pc+1)[0]; self.pc += 5
            elif self.raw[self.pc:self.pc+3] == bytes.fromhex('896b5a'):
                self.pool['last'] = self.regs['ebp']; self.pc += 3
            elif self.raw[self.pc:self.pc+3] == b'\x83\xc4\x18':
                del self.stack[:6]; self.pc += 3
            elif self.raw[self.pc:self.pc+3] == b'\xc2\x08\x00':
                assert self.stack.pop(0) == 0xABCDEF
                del self.stack[:2]
                return 'continued-enumeration'
            else:
                raise AssertionError(f'Unexpected instruction {op:02x} at {self.pc:x}')
        raise AssertionError('Fixture exceeded bounded instruction count')


class VacationTextureFormatTests(unittest.TestCase):
    def setUp(self):
        self.raw = synthetic_source()
        self.contexts = tuple((o, n, hashlib.sha256(self.raw[o:o+n]).hexdigest()) for o,n,_ in formats.CONTEXTS)
        self.source_pin = patch.object(formats, 'SOURCE_SHA256', hashlib.sha256(self.raw).hexdigest())
        self.context_pin = patch.object(formats, 'CONTEXTS', self.contexts)
        self.source_pin.start(); self.addCleanup(self.source_pin.stop)
        self.context_pin.start(); self.addCleanup(self.context_pin.stop)

    def test_only_seven_warning_tail_bytes_change_and_repatch_is_refused(self):
        output, plan = formats.patch(self.raw)
        self.assertEqual(len(output), len(self.raw))
        self.assertEqual(output[:formats.PATCH_OFFSET], self.raw[:formats.PATCH_OFFSET])
        self.assertEqual(output[formats.PATCH_OFFSET+7:], self.raw[formats.PATCH_OFFSET+7:])
        self.assertEqual(len(plan['patches']), 1)
        self.assertFalse(plan['runtime_verified'])
        with self.assertRaises(ValueError): formats.patch(output)

    def test_all_16bit_masks_keep_original_control_path_and_state(self):
        output, _ = formats.patch(self.raw)
        for name in ('RGB565', 'RGB555', 'ARGB1555', 'ARGB4444'):
            with self.subTest(format=name):
                vm = EnumVM(output, 16)
                before_regs, before_stack = dict(vm.regs), list(vm.stack)
                self.assertEqual(vm.run(), 'native-16bit')
                before_regs['eax'] = 16
                self.assertEqual(vm.regs, before_regs)
                self.assertEqual(vm.stack, before_stack)
                self.assertEqual(vm.calls, [])

    def test_non16_formats_warn_and_return_continue_with_clean_stack_and_abi(self):
        output, _ = formats.patch(self.raw)
        for depth in (0, 8, 15, 24, 32, 64, 0xFFFFFFFF):
            with self.subTest(depth=depth):
                vm = EnumVM(output, depth)
                self.assertEqual(vm.run(), 'continued-enumeration')
                self.assertEqual(vm.calls, [('warning', depth)])
                self.assertEqual(vm.regs['eax'], 1)
                self.assertEqual(vm.stack, [])
                for name, value in vm.saved.items(): self.assertEqual(vm.regs[name], value)

    def test_pool_and_selection_instructions_stay_native_while_rejection_keeps_tail_update(self):
        output, _ = formats.patch(self.raw)
        # Allocation, descriptor copy and palette paths precede the warning;
        # Category/alpha/RGB selection and last/fallback code stays byte-identical;
        # the rejected path now executes the original last update only.
        self.assertEqual(output[0x8F040:formats.GUARD], self.raw[0x8F040:formats.GUARD])
        self.assertEqual(output[formats.CONTINUE:formats.EPILOGUE], self.raw[formats.CONTINUE:formats.EPILOGUE])
        vm = EnumVM(output, 32)
        vm.run()
        self.assertNotEqual(vm.pc, formats.CONTINUE)
        self.assertEqual(vm.pool['last'],0xB1)

    def test_each_version_context_remains_independently_required(self):
        for offset, size, _ in self.contexts:
            changed = bytearray(self.raw); changed[offset] ^= 1; changed = bytes(changed)
            with self.subTest(offset=offset), patch.object(formats, 'SOURCE_SHA256', hashlib.sha256(changed).hexdigest()):
                with self.assertRaises(ValueError): formats.patch(changed)

    def test_full_native_pool_sequence_preserves_links_and_tail_without_selecting_unsupported(self):
        output,_=formats.patch(self.raw)
        pool={'allocated':[False]*12,'cursor':0,'last':0,'fallback':0,
              'rgb':None,'alpha':None,'alpha_bits':0,
              'records':[{'prev':0,'next':0} for _ in range(12)]}
        sequence=[('palette',8,0),('rgb',16,0),('rgb',32,0),('alpha',32,8),
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
                vm=EnumVM(output,bits);vm.regs['ebp']=index;vm.pool=pool
                outcome=vm.run()
            else:outcome='native-16bit'
            if outcome=='native-16bit':
                if kind=='rgb':pool['rgb']=index
                elif kind=='alpha' and alpha>pool['alpha_bits']:
                    pool['alpha']=index;pool['alpha_bits']=alpha
                if not pool['fallback']:pool['fallback']=index
                pool['last']=index
            else:
                self.assertEqual(outcome,'continued-enumeration')
                self.assertEqual((pool['rgb'],pool['alpha'],pool['alpha_bits'],pool['fallback']),selected)
            self.assertEqual(pool['last'],index)
        self.assertEqual(pool['cursor'],7)
        self.assertEqual(pool['rgb'],1);self.assertEqual(pool['alpha'],4)
        self.assertEqual(pool['fallback'],1);self.assertEqual(pool['last'],7)
        for index in range(2,8):
            self.assertEqual(pool['records'][index]['prev'],index-1)
            self.assertEqual(pool['records'][index-1]['next'],index)

    def test_type_length_and_unknown_original_hash_are_refused(self):
        for value in (bytearray(self.raw), self.raw[:-1], b'unknown'):
            with self.subTest(type=type(value).__name__), self.assertRaises(ValueError): formats.patch(value)
        with patch.object(formats, 'SOURCE_SHA256', '0'*64):
            with self.assertRaises(ValueError): formats.patch(self.raw)


if __name__ == '__main__': unittest.main()
