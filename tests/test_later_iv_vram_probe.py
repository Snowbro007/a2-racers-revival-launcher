"""Synthetic native probe interpreter: allocations, stack bounds and releases."""
import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import later_iv_vram_probe as probe


def fixture():
    raw=bytearray(probe.SOURCE_SIZE)
    raw[probe.CAVE:probe.PROBE]=b'\x90'*13
    # The synthetic loop/ABI uses the bounded original instruction vocabulary.
    body=bytes.fromhex('b800100000e806d309005355565733ff8be933db8d742410'
        '68000100006800010000e859ffffff83c408890685c07413a174097400'
        'c1e803c1e01003d84783c604ebd585ff899da10200007e128d742410'
        '8b06508b08ff510883c6044f75f25f5e5d5b81c400100000c3')
    raw[probe.PROBE:probe.PROBE+len(body)]=body
    raw=bytes(raw)
    contexts=tuple((o,n,hashlib.sha256(raw[o:o+n]).hexdigest()) for o,n,_ in probe.CONTEXTS)
    return raw,contexts


class ProbeVM:
    def __init__(self,code,fail_after,bpp=16):
        self.code=code;self.pc=probe.PROBE;self.fail_after=fail_after;self.bpp=bpp
        self.entry_sp=0x800000
        self.regs=dict(eax=0,ecx=0x100000,esp=self.entry_sp,
                       ebx=0xB0,ebp=0xB1,esi=0xB2,edi=0xB3)
        self.saved={k:self.regs[k] for k in ('ebx','ebp','esi','edi')}
        self.mem={self.entry_sp:0xFACE};self.allocations=[];self.released=[]
        self.zf=False;self.sf=False;self.cf=False;self.writes=[]

    def push(self,value):
        self.regs['esp']-=4;self.mem[self.regs['esp']]=value

    def pop(self):
        value=self.mem[self.regs['esp']];self.regs['esp']+=4;return value

    def test(self,value):
        self.zf=value==0;self.sf=bool(value&0x80000000);self.cf=False

    def run(self):
        for _ in range(60000):
            pc=self.pc;data=self.code[pc:pc+12];op=data[0];r=self.regs
            if op==0xB8:r['eax']=struct.unpack_from('<I',data,1)[0];self.pc+=5
            elif op==0xE8:
                target=pc+5+struct.unpack_from('<i',data,1)[0]
                if target==0x159400:r['esp']-=r['eax']
                elif target==0xBC070:
                    assert [self.mem[r['esp']],self.mem[r['esp']+4]]==[256,256]
                    if len(self.allocations)>=self.fail_after:r['eax']=0
                    else:
                        r['eax']=0x200000+len(self.allocations)*16
                        self.allocations.append(r['eax'])
                else:raise AssertionError(hex(target))
                self.pc+=5
            elif op in (0x50,0x53,0x55,0x56,0x57):
                self.push(r[{0x50:'eax',0x53:'ebx',0x55:'ebp',0x56:'esi',0x57:'edi'}[op]]);self.pc+=1
            elif op in (0x5B,0x5D,0x5E,0x5F):
                r[{0x5B:'ebx',0x5D:'ebp',0x5E:'esi',0x5F:'edi'}[op]]=self.pop();self.pc+=1
            elif data[:2]==b'\x33\xff':r['edi']=0;self.pc+=2
            elif data[:2]==b'\x33\xdb':r['ebx']=0;self.pc+=2
            elif data[:2]==b'\x8b\xe9':r['ebp']=r['ecx'];self.pc+=2
            elif data[:4]==bytes.fromhex('8d742410'):r['esi']=r['esp']+16;self.pc+=4
            elif op==0x68:self.push(struct.unpack_from('<I',data,1)[0]);self.pc+=5
            elif data[:3]==bytes.fromhex('83c408'):r['esp']+=8;self.pc+=3
            elif data[:2]==b'\x89\x06':
                if not self.entry_sp-4096<=r['esi']<self.entry_sp:
                    raise AssertionError('native stack pointer array overflow')
                self.mem[r['esi']]=r['eax'];self.writes.append(r['esi']);self.pc+=2
            elif data[:2] in (b'\x85\xc0',b'\x85\xff'):
                self.test(r['eax' if data[1]==0xC0 else 'edi']);self.pc+=2
            elif op==0x74:self.pc+=2+(struct.unpack_from('<b',data,1)[0] if self.zf else 0)
            elif op==0x75:self.pc+=2+(struct.unpack_from('<b',data,1)[0] if not self.zf else 0)
            elif op==0x7E:self.pc+=2+(struct.unpack_from('<b',data,1)[0] if self.zf or self.sf else 0)
            elif op==0x73:self.pc+=2+(data[1] if not self.cf else 0)
            elif op==0xA1:r['eax']=self.bpp;self.pc+=5
            elif data[:3]==bytes.fromhex('c1e803'):r['eax']>>=3;self.pc+=3
            elif data[:3]==bytes.fromhex('c1e010'):r['eax']<<=16;self.pc+=3
            elif data[:2]==b'\x03\xd8':r['ebx']+=r['eax'];self.pc+=2
            elif op==0x47:r['edi']+=1;self.pc+=1
            elif op==0x4F:r['edi']-=1;self.test(r['edi']);self.pc+=1
            elif data[:3]==bytes.fromhex('83c604'):r['esi']+=4;self.pc+=3
            elif op==0xEB:self.pc+=2+struct.unpack_from('<b',data,1)[0]
            elif op==0xE9:self.pc+=5+struct.unpack_from('<i',data,1)[0]
            elif data[:2]==b'\x81\xff':
                value=struct.unpack_from('<I',data,2)[0]
                self.cf=r['edi']<value;self.zf=r['edi']==value;self.pc+=6
            elif data[:2]==b'\x89\x9d':self.mem[r['ebp']+struct.unpack_from('<I',data,2)[0]]=r['ebx'];self.pc+=6
            elif data[:2]==b'\x8b\x06':r['eax']=self.mem[r['esi']];self.pc+=2
            elif data[:2]==b'\x8b\x08':r['ecx']=0xCAFE;self.pc+=2
            elif data[:3]==bytes.fromhex('ff5108'):
                handle=self.pop();assert handle==r['eax'] and handle in self.allocations
                self.released.append(handle);r['eax']=0;self.pc+=3
            elif data[:2]==b'\x81\xc4':r['esp']+=struct.unpack_from('<I',data,2)[0];self.pc+=6
            elif op==0xC3:
                assert self.pop()==0xFACE;return self
            else:raise AssertionError(f'Unexpected opcode {data.hex()} at {pc:x}')
        raise AssertionError('Unbounded native probe fixture')


class IVVramProbeTests(unittest.TestCase):
    def setUp(self):
        self.raw,self.contexts=fixture()
        for p in (patch.object(probe,'SOURCE_SHA256',hashlib.sha256(self.raw).hexdigest()),
                  patch.object(probe,'CONTEXTS',self.contexts)):
            p.start();self.addCleanup(p.stop)

    def test_original_loop_fixture_detects_the_unbounded_array_write(self):
        with self.assertRaisesRegex(AssertionError,'stack pointer array overflow'):
            ProbeVM(self.raw,1500).run()

    def test_cap_releases_every_saved_handle_before_any_out_of_bounds_write(self):
        code,plan=probe.patch(self.raw)
        for capacity in (1024,1025,2048,1000000):
            with self.subTest(capacity=capacity):
                vm=ProbeVM(code,capacity).run()
                self.assertEqual(len(vm.allocations),1024)
                self.assertEqual(vm.released,vm.allocations)
                self.assertEqual(len(vm.writes),1024)
                self.assertEqual(vm.mem[0x100000+0x2A1],1024*256*256*2)
                self.assertEqual(vm.regs['esp'],vm.entry_sp+4)
                self.assertEqual({k:vm.regs[k] for k in vm.saved},vm.saved)
        self.assertEqual(plan['maximum_successful_allocations'],1024)

    def test_early_allocation_failure_keeps_native_cleanup_accounting_and_return(self):
        code,_=probe.patch(self.raw)
        for capacity in (0,1,127,512,1023):
            for bpp in (16,32):
                with self.subTest(capacity=capacity,bpp=bpp):
                    vm=ProbeVM(code,capacity,bpp).run()
                    self.assertEqual(len(vm.allocations),capacity)
                    self.assertEqual(vm.released,vm.allocations)
                    self.assertEqual(vm.mem[0x100000+0x2A1],capacity*65536*(bpp//8))
                    self.assertEqual(vm.mem[vm.entry_sp],0xFACE)
                    self.assertEqual({k:vm.regs[k] for k in vm.saved},vm.saved)

    def test_only_the_padding_and_original_tail_jump_change_without_pe_growth(self):
        code,plan=probe.patch(self.raw)
        expected=set(range(probe.CAVE,probe.CAVE+13))|set(range(probe.TAIL_JUMP,probe.TAIL_JUMP+2))
        self.assertEqual(len(code),len(self.raw))
        self.assertTrue({i for i,(a,b) in enumerate(zip(self.raw,code)) if a!=b}<=expected)
        self.assertEqual(len(plan['patches']),2)
        self.assertFalse(plan['runtime_verified'])

    def test_each_context_and_original_padding_are_version_bound(self):
        for offset,_,_ in self.contexts:
            modified=bytearray(self.raw);modified[offset]^=1;modified=bytes(modified)
            with self.subTest(offset=offset),patch.object(probe,'SOURCE_SHA256',hashlib.sha256(modified).hexdigest()):
                with self.assertRaises(ValueError):probe.patch(modified)

    def test_unknown_version_type_size_and_repatch_are_refused(self):
        for invalid in (bytearray(self.raw),self.raw[:-1],b'unknown'):
            with self.assertRaises(ValueError):probe.patch(invalid)
        modified=bytearray(self.raw);modified[0x200]^=1
        with self.assertRaises(ValueError):probe.patch(bytes(modified))
        code,_=probe.patch(self.raw)
        with self.assertRaises(ValueError):probe.patch(code)


if __name__=='__main__':unittest.main()
