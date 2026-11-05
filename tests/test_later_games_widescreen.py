"""Synthetic PE + tiny x86/x87 VM and independent projection/HUD math; no game I/O."""
import copy
import hashlib
import math
import struct
import unittest
from unittest.mock import patch
from tools import later_games_widescreen as w


def fixture(game):
    s=copy.deepcopy(w.SPECS[game]);raw=bytearray(s['source_size'])
    pe=s['pe'];o=s['optional'];table=s['section_table']
    raw[0:2]=b'MZ';struct.pack_into('<I',raw,0x3c,pe);raw[pe:pe+4]=b'PE\0\0'
    struct.pack_into('<HH',raw,pe+4,0x14c,3);struct.pack_into('<H',raw,pe+20,224)
    struct.pack_into('<H',raw,o,0x10b);struct.pack_into('<III',raw,o+28,w.IMAGE_BASE,0x1000,0x1000)
    struct.pack_into('<II',raw,o+56,s['section_rva'],0x1000)
    for index in range(3):
        q=table+40*index
        struct.pack_into('<8sIIIIIIHHI',raw,q,('.s'+str(index)).encode(),0x1000,
                         (index+1)*0x1000,0x1000,(index+1)*0x1000,0,0,0,0,0x60000020)
    struct.pack_into('<3I',raw,s['table'],640,480,16)
    raw[s['matrix_raw']+0x42:s['matrix_raw']+0x48]=bytes.fromhex('dd5c2410d9fe')
    struct.pack_into('<f',raw,s['hud_unit'],1/320)
    raw[s['hud_pos_sub']:s['hud_pos_sub']+6]=b'\xd8\x25'+struct.pack('<I',0x4e0290 if game=='vakantieracer' else 0x576318)
    raw[s['hud_text_origin']:s['hud_text_origin']+8]=bytes.fromhex('c7442424000080bf')
    raw=bytes(raw);s['source_sha256']=w.sha(raw)
    s['contexts']=tuple((a,n,w.sha(raw[a:a+n])) for a,n,_ in s['contexts'])
    return raw,s


def stub_vm(blob,info,return_address,angle,*,flags=0x246):
    """Independent bounded interpretation of the actual emitted stub opcodes."""
    va=info['entry_va'];pc=0;sp=0x1000;original_sp=sp
    memory={sp+0x58:return_address};initial_flags=flags;fp=[math.cos(angle/2),angle/2]
    stores={};equal=False;visited=[]
    for _ in range(80):
        visited.append(pc)
        if blob[pc]==0x9c:
            sp-=4;memory[sp]=flags;pc+=1
        elif blob[pc:pc+4]==bytes.fromhex('817c245c'):
            equal=memory[sp+0x5c]==struct.unpack_from('<I',blob,pc+4)[0]
            flags=0x40 if equal else 0;pc+=8
        elif blob[pc:pc+2]==b'\x0f\x84':
            pc+=6+(struct.unpack_from('<i',blob,pc+2)[0] if equal else 0)
        elif blob[pc]==0xe9:
            target=va+pc+5+struct.unpack_from('<i',blob,pc+1)[0]
            if target==info['return_va']:
                return {'fp':fp,'stores':stores,'sp':sp,'initial_sp':original_sp,
                        'flags':flags,'initial_flags':initial_flags,'visited':visited,'memory':memory}
            pc=target-va
        elif blob[pc:pc+2]==b'\xd8\x0d':
            target=struct.unpack_from('<I',blob,pc+2)[0]
            fp[0]*=struct.unpack_from('<f',blob,target-va)[0];pc+=6
        elif blob[pc]==0x9d:
            flags=memory[sp];sp+=4;pc+=1
        elif blob[pc:pc+4]==bytes.fromhex('dd5c2410'):
            stores[sp+0x10]=fp.pop(0);pc+=4
        elif blob[pc:pc+2]==bytes.fromhex('d9fe'):
            fp[0]=math.sin(fp[0]);pc+=2
        else:raise AssertionError('Unexpected opcode at '+hex(pc))
    raise AssertionError('Stub did not reach original continuation')


class ProjectionTests(unittest.TestCase):
    def test_actual_stub_preserves_stack_flags_and_overlay_or_unknown_camera(self):
        for game,s in w.SPECS.items():
            blob,info=w.projection_stub(game)
            for ret in (*s['world_returns'],s['overlay_return'],0x12345678):
                for angle in (.35,.9,math.pi/2,2.1):
                    with self.subTest(game=game,ret=hex(ret),angle=angle):
                        result=stub_vm(blob,info,ret,angle)
                        self.assertEqual(result['sp'],result['initial_sp'])
                        self.assertEqual(result['flags'],result['initial_flags'])
                        self.assertEqual(len(result['fp']),1)
                        self.assertAlmostEqual(result['fp'][0],math.sin(angle/2))
                        factor=.75 if ret in s['world_returns'] else 1
                        self.assertAlmostEqual(result['stores'][0x1010],factor*math.cos(angle/2))
                        self.assertEqual(result['memory'][0x1058],ret)

    def test_hor_plus_retains_pixel_scale_and_vertical_span_without_changing_depth(self):
        # Native D3DVIEWPORT2's H/W clip makes pixel scale W/2 *cot(FOV/2).
        # A sphere's X/Y radii therefore stay equal. Hor+ keeps HD4:3 vertical span.
        for angle in (.35,.9,math.pi/2,2.1):
            old_cot=1/math.tan(angle/2);new_cot=.75*old_cot
            old_focal=1440/2*old_cot;new_focal=1920/2*new_cot
            self.assertAlmostEqual(old_focal,new_focal)
            self.assertAlmostEqual(1080/(2*old_focal),1080/(2*new_focal))
            self.assertAlmostEqual((1920/(2*new_focal))/(1440/(2*old_focal)),4/3)
            # Independent D3D viewport conversion: Y clip includes actual H/W.
            x_radius=(1920/2)*(5*new_cot/40)
            y_radius=(1080/2)*(5*new_cot/40)/(1080/1920)
            self.assertAlmostEqual(x_radius,y_radius)
            self.assertGreater(2*math.atan(1/new_cot),angle)

    def test_hud_centered_safe_area_and_uniform_mesh_scale_match_accepted_hd(self):
        # Separate native 3D overlay camera is untouched. X units/origins compress
        # only its 640-wide layout to 75%; native H/W already compensates Y.
        for x in (0,10,40,160,320,515,538,640):
            base_offset=1440/2*(x/320-1)
            wide_offset=1920/2*(x*(.75/320)-.75)
            self.assertAlmostEqual(base_offset,wide_offset)
            self.assertAlmostEqual(1920/2+wide_offset,240+x*2.25)
        base_dx=1440/2/320;wide_dx=1920/2*.75/320
        base_dy=1440/2*(480/640)/240
        wide_dy=1920/2*(1080/1920)/240
        self.assertAlmostEqual(base_dx,wide_dx)
        self.assertAlmostEqual(base_dy,wide_dy)
        self.assertAlmostEqual(wide_dx,wide_dy)


class PatchTests(unittest.TestCase):
    def test_synthetic_pe_is_bounded_and_only_declared_regions_change(self):
        for game in w.SPECS:
            raw,s=fixture(game)
            with patch.dict(w.SPECS,{game:s}):out,details=w.patch(raw,game)
            self.assertEqual(len(out),len(raw)+0x1000)
            self.assertEqual(struct.unpack_from('<3I',out,s['table']),(1920,1080,16))
            self.assertEqual(details['hud_safe_area'],[240,0,1440,1080])
            self.assertFalse(details['runtime_verified'])
            self.assertFalse(details['native_game_executed'])
            self.assertTrue(details['unknown_camera_callers_preserved'])
            allowed=set()
            for rec in details['patches']:
                allowed.update(range(rec['offset'],rec['offset']+len(bytes.fromhex(rec['before']))))
            for a,n in ((s['pe']+6,2),(s['optional']+4,4),(s['optional']+56,4),
                        (s['optional']+64,4),(s['section_table']+120,40)):
                allowed.update(range(a,a+n))
            diff={i for i,(a,b) in enumerate(zip(raw,out)) if a!=b}
            self.assertLessEqual(diff,allowed)
            section=details['section'];self.assertEqual(section['raw_offset'],len(raw))
            self.assertEqual(section['rva'],s['section_rva'])
            self.assertEqual(section['characteristics'],0x60000020)
            self.assertEqual(out[len(raw)+0x100:len(raw)+0x104],struct.pack('<f',.75))
            self.assertEqual(out[-0xefc:],b'\0'*0xefc)
            # Its real hook jumps into the new mapped section, never into BSS.
            hook=s['matrix_raw']+0x42
            self.assertEqual(0x400000+hook+5+struct.unpack_from('<i',out,hook+1)[0],
                             0x400000+section['rva'])

    def test_unknown_sources_profiles_contexts_header_and_repatch_refused(self):
        for game in w.SPECS:
            raw,s=fixture(game)
            with patch.dict(w.SPECS,{game:s}):
                out,_=w.patch(raw,game)
                for bad in (raw[:-1],out,bytearray(raw),b'unknown'):
                    with self.assertRaises(ValueError):w.patch(bad,game)
                changed=bytearray(raw);changed[s['matrix_raw']+1]^=1
                s2=copy.deepcopy(s);s2['source_sha256']=w.sha(changed)
                with patch.dict(w.SPECS,{game:s2}),self.assertRaisesRegex(ValueError,'context'):
                    w.patch(bytes(changed),game)
                # Even with synthetic source/context repins, occupied header space fails.
                changed=bytearray(raw);changed[s['section_table']+120]=1
                s2=copy.deepcopy(s);s2['source_sha256']=w.sha(changed)
                s2['contexts']=tuple((a,n,w.sha(changed[a:a+n])) for a,n,_ in s['contexts'])
                with patch.dict(w.SPECS,{game:s2}),self.assertRaisesRegex(ValueError,'PE32'):
                    w.patch(bytes(changed),game)
        with self.assertRaises(ValueError):w.patch(b'', 'missing')



from tools import later_native as native
from tools import later_games_runtime as runtime
from tests.test_later_games_runtime import SyntheticFixture

class WideProfileTests(SyntheticFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.profile='wide1080'
        self.start_patch(patch.object(w,'patch',side_effect=lambda raw,game:
            (raw+b' wide',{'sha256':runtime.sha(raw+b' wide')})))
    def test_wide_copy_preserves_original_and_hd_and_survives_reuse(self):
        hd=runtime.prepare(self.root,self.game,'hd1080')
        from pathlib import Path
        hdpath=Path(hd['game_path'])
        before={p.relative_to(hdpath):p.read_bytes() for p in hdpath.rglob('*') if p.is_file()}
        value=self.prepare()
        self.assertEqual(value['race_aspect_ratio_requested'],[16,9])
        self.assertEqual(value['render_resolution_requested'],[1920,1080])
        self.assertEqual(value['user_feedback_status'],'confirmed')
        self.assertEqual(value['baseline'],'native-wide1080-v1-horplus-hud')
        self.assertEqual((self.game_dir/'SPEL.DAT').read_bytes(),b'patched:'+self.originals['SPEL.DAT']+b' wide')
        (self.game_dir/'savegame1.rcr').write_bytes(b'wide progress')
        self.prepare()
        self.assertEqual((self.game_dir/'savegame1.rcr').read_bytes(),b'wide progress')
        for name,raw in before.items():self.assertEqual((hdpath/name).read_bytes(),raw)
        self.assert_source_intact()
        self.no_process.assert_not_called()
    def test_checkonly_does_not_start_process_or_display(self):
        result=runtime.run(self.root,self.game,profile='wide1080',check_only=True)
        self.assertTrue(result['ready'])
        self.assertFalse(result['game_started'])
        self.no_process.assert_not_called()
        self.no_winapi.assert_not_called()

class IVWideProfileTests(WideProfileTests):
    SELECTED_GAME='a2racer4'

if __name__=='__main__':unittest.main()
