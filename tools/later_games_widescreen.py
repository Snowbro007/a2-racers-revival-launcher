"""Pinned optional IV/VR Hor+ 16:9 and proportional centered HUD; pure bytes only.

Input is the exact compatibility/input/texture/mouse-shutdown stage. Baseline
HD4:3 stays separate. The native viewport already uses H/W. A bounded PE32
section gates the cosine correction on proven world-camera return addresses;
the independent overlay camera and unknown callers retain the original matrix.
HUD screen X units and both X origins keep the established 4:3 safe area.
CPU culling, sky and actual presentation still need a visual playtest.
"""
from __future__ import annotations
import hashlib
import math
import struct

IMAGE_BASE=0x400000
SECTION_ALIGNMENT=0x1000
FILE_ALIGNMENT=0x1000
SECTION_NAME=b'.lgwide\0'
SPECS={'vakantieracer': {'source_sha256': '1c53f51e06224e4d79b3661f41b5e6c805a81b74e93c3265681b757da51b8a66',
                   'source_size': 1126400,
                   'matrix_raw': 549456,
                   'pe': 232,
                   'optional': 256,
                   'section_table': 480,
                   'section_rva': 1695744,
                   'world_returns': [4425957, 4429169, 4429356, 4445991, 4769599],
                   'overlay_return': 4614060,
                   'contexts': ((583392,
                                 168,
                                 'c310391e41bbcd2b8e328ce284b120701bca13d47c1a7a38942c44d54ff5af18'),
                                (549456,
                                 144,
                                 'ca0b6502d55eb8634908cdc1f43acd2b22b5cc8e85592842be3bdb82184545d8'),
                                (390048,
                                 165,
                                 'd2b3c34c9b74b28db7f80f7f4207487220eef10109a9b9ef850aa2180820fd61'),
                                (401696,
                                 528,
                                 '4d52744a9e0c29b030eddcf57e8049438501b6c6a554e4442c6d1d1a23ba9c90'),
                                (403840,
                                 448,
                                 'f5e696912a2cb342415500b2162a0959a57e9e647ff5308530907a019b0e6c98'),
                                (0, 4096, '8dcf70b76ade24e40b9c3a57d4bf77e7687ffab85a3ef2838f77e8a9dfdafbd4'),
                                (231616,
                                 53,
                                 'bcb9efd61ad5bf9731abdc99f116114992b8363b193eba01300b5a298382285a'),
                                (234828,
                                 53,
                                 '0992be600f549427fed3c9a47eea83e7bc58ba9a97447691a8d4f2308dccbcb7'),
                                (235015,
                                 53,
                                 'cde8b01ee6046813aef953da1a8986e7708897d4fe2d78520555e2869ab8676f'),
                                (251650,
                                 53,
                                 'ddd34580bc25a39d188381fe3d85a503f78c77b3ee1d8b46942be6e0d9c15016'),
                                (419719,
                                 53,
                                 '7afc2abe964a60a475ef8919d25e5d7a36e87b073db86276dadd624c6e68f7e8'),
                                (575258,
                                 53,
                                 'ebfda65a1527a25344c4f8a8096c4801e380d950dea4675c85fb1d07318913aa')),
                   'table': 1092244,
                   'hud_unit': 919928,
                   'hud_pos_sub': 402123,
                   'hud_text_origin': 403925},
 'a2racer4': {'source_sha256': '5224e395d45a3dae139013eb55801a13fc140e9352703919fd1465d11e0638ab',
              'source_size': 1875968,
              'matrix_raw': 735696,
              'pe': 248,
              'optional': 272,
              'section_table': 496,
              'section_rva': 3481600,
              'world_returns': [4506378, 4510774, 4510964, 4528247, 4961887],
              'overlay_return': 4735804,
              'contexts': ((790032, 168, '7ce4885653f698adf1cc42bbb2dd855ef49f49cd5925befadfcd0887aab12600'),
                           (735696, 144, 'eb28bd381d03da1a33472b7d23deb7d7c246675e3e4d1af598f4bc483a2715bb'),
                           (511376, 165, 'be760c5afa1c6f2db445cac641368a1d907b6c707d8fca2b680fb4e479b5c9cc'),
                           (523424, 528, 'aa95740691103408d896cfe119abb1a1381d82377239fdfaa33d6a62e1c0ccca'),
                           (525568, 448, '8ffbced09544f98db915832a7dd554eefa87693944d4b0b57832ad7ed4f45859'),
                           (0, 4096, '1e74299b4df1ee60572ba0fa3fe0003cdb2003a7fcdd0d57f5215b49977561db'),
                           (312037, 53, '33bfde5d0984b8aa193757a071fca7afb035b9b89df28057dc38a157e00e0ecc'),
                           (316433, 53, '4fa3403af4c7f47cb1ee5aff88a0240fd182de595900f4f26c41bb7ce2bf86df'),
                           (316623, 53, 'f0501705153ca301d31889cbc57cb5dacca1777274201bc87f96015d7a76df6a'),
                           (333906, 53, '01ec8514dcf812a4b24ed6a8134ef608e3f3f073bd10fe2ac3f16e1b700f842c'),
                           (541463, 53, '636e1f34e354cf92da93b119d77d04f475dd6f8bae38ff3284a517036a90767e'),
                           (767546, 53, '3ee67682f2d6edee3950ceef9d221d47974744ea29d44accbe85d035998a7edb')),
              'table': 1783908,
              'hud_unit': 1534800,
              'hud_pos_sub': 523851,
              'hud_text_origin': 525653}}


def sha(raw): return hashlib.sha256(raw).hexdigest()


def projection_stub(game):
    """Preserve flags/GPRs/SP/x87 depth; only known world cos(FOV/2) *=3/4."""
    s=SPECS[game];va=IMAGE_BASE+s['section_rva'];code=bytearray(b'\x9c');jumps=[]
    # At this exact native point ESP is entryESP-0x58; PUSHFD adds four.
    # Return address is therefore [ESP+0x5c]. No arguments or GPRs changed.
    for ret in s['world_returns']:
        code+=b'\x81\x7c\x24\x5c'+struct.pack('<I',ret)
        code+=b'\x0f\x84';jumps.append(len(code));code+=b'\0'*4
    code+=b'\xe9';skip=len(code);code+=b'\0'*4
    apply=len(code)
    code+=b'\xd8\x0d'+struct.pack('<I',va+0x100)  # FMUL m32 0.75.
    done=len(code)
    code+=b'\x9d'+bytes.fromhex('dd5c2410d9fe')  # Original FSTP qword; FSIN.
    code+=b'\xe9'+struct.pack('<i',IMAGE_BASE+s['matrix_raw']+0x48-(va+len(code)+5))
    for at in jumps:struct.pack_into('<i',code,at,apply-(at+4))
    struct.pack_into('<i',code,skip,done-(skip+4))
    if len(code)>0x100:raise ValueError('Breedbeeldstub overschrijdt de limiet.')
    blob=bytes(code)+b'\x90'*(0x100-len(code))+struct.pack('<f',.75)
    return blob,{'entry_va':va,'constant_va':va+0x100,'code_size':len(code),
                 'apply_offset':apply,'done_offset':done,
                 'return_va':IMAGE_BASE+s['matrix_raw']+0x48}


def _append_section(raw,game,blob):
    s=SPECS[game];pe=s['pe'];opt=s['optional'];table=s['section_table'];next_header=table+3*40
    if (raw[pe:pe+4]!=b'PE\0\0' or struct.unpack_from('<HH',raw,pe+4)!=(0x14c,3)
        or struct.unpack_from('<H',raw,pe+20)[0]!=224 or struct.unpack_from('<H',raw,opt)[0]!=0x10b
        or struct.unpack_from('<III',raw,opt+28)!=(IMAGE_BASE,SECTION_ALIGNMENT,FILE_ALIGNMENT)
        or struct.unpack_from('<I',raw,opt+56)[0]!=s['section_rva']
        or struct.unpack_from('<I',raw,opt+60)[0]!=0x1000
        or struct.unpack_from('<II',raw,opt+96+5*8)!=(0,0)
        or any(raw[next_header:next_header+40]) or len(raw)%FILE_ALIGNMENT):
        raise ValueError('Andere gepinde PE32-sectionlayout; breedbeeld geweigerd.')
    for i in range(3):
        q=table+40*i;vs,rva,n,offset=struct.unpack_from('<4I',raw,q+8)
        if offset+n>len(raw) or rva+max(vs,n)>s['section_rva']:
            raise ValueError('Bestaande section overlapt nieuwe breedbeeldsection.')
    if not 1<=len(blob)<=0x1000:raise ValueError('Ongeldige breedbeeldsection.')
    out=bytearray(raw);out+=blob+b'\0'*(FILE_ALIGNMENT-len(blob))
    out[next_header:next_header+40]=struct.pack('<8sIIIIIIHHI',SECTION_NAME,len(blob),s['section_rva'],
        FILE_ALIGNMENT,len(raw),0,0,0,0,0x60000020)
    struct.pack_into('<H',out,pe+6,4)
    struct.pack_into('<I',out,opt+4,struct.unpack_from('<I',raw,opt+4)[0]+FILE_ALIGNMENT)
    struct.pack_into('<I',out,opt+56,s['section_rva']+SECTION_ALIGNMENT)
    struct.pack_into('<I',out,opt+64,0)
    return out,{'header_offset':next_header,'rva':s['section_rva'],'raw_offset':len(raw),
                'raw_size':FILE_ALIGNMENT,'virtual_size':len(blob),'characteristics':0x60000020}


def patch(raw,game):
    if game not in SPECS:raise ValueError('Onbekende breedbeeldgame.')
    s=SPECS[game]
    if type(raw) is not bytes or len(raw)!=s['source_size'] or sha(raw)!=s['source_sha256']:
        raise ValueError('Onbekende samengestelde raceversie; breedbeeld geweigerd.')
    for offset,size,pin in s['contexts']:
        if sha(raw[offset:offset+size])!=pin:raise ValueError('Andere camera/HUD/canvascontext.')
    blob,stub=projection_stub(game);out,section=_append_section(raw,game,blob)
    hook=s['matrix_raw']+0x42;target=stub['entry_va']
    changes=[
      ('native_canvas',s['table'],struct.pack('<3I',640,480,16),struct.pack('<3I',1920,1080,16)),
      ('world_hor_plus',hook,bytes.fromhex('dd5c2410d9fe'),
         b'\xe9'+struct.pack('<i',target-(IMAGE_BASE+hook+5))+b'\x90'),
      # Only five native HUD scale references use this shared screen-unit constant.
      # The Y mapper already contains actual H/W, so it must remain unchanged.
      ('hud_x_unit',s['hud_unit'],struct.pack('<f',1/320),struct.pack('<f',.75/320)),
      ('hud_element_x_origin',s['hud_pos_sub'],b'\xd8\x25'+struct.pack('<I',0x4e0290 if game=='vakantieracer' else 0x576318),
         b'\xd8\x25'+struct.pack('<I',stub['constant_va'])),
      ('hud_text_x_origin',s['hud_text_origin'],bytes.fromhex('c7442424000080bf'),
         bytes.fromhex('c7442424000040bf')),
    ]
    covered=set()
    for name,offset,before,after in changes:
        if len(before)!=len(after) or raw[offset:offset+len(before)]!=before:
            raise ValueError('Andere breedbeeldpatchbytes: '+name)
        region=set(range(offset,offset+len(before)))
        if region&covered:raise ValueError('Overlappende breedbeeldpatches.')
        covered|=region;out[offset:offset+len(after)]=after
    result=bytes(out)
    return result,{'kind':'later-games-native-hor-plus-wide1080','game':game,
        'source_sha256':sha(raw),'sha256':sha(result),'native_canvas':[1920,1080,16],
        'aspect':[16,9],'world_projection':'Hor+; cot(horizontal_FOV/2) multiplied by 3/4',
        'world_camera_return_addresses':s['world_returns'],'overlay_camera_return_address':s['overlay_return'],
        'unknown_camera_callers_preserved':True,'hud_safe_area':[240,0,1440,1080],
        'hud_geometry':'original assets; proportional 4:3 centered safe area',
        'menu_unchanged':True,'native_viewport_aspect_dynamic':True,
        'cpu_culling_modified':False,'runtime_verified':False,'native_game_executed':False,
        'section':section,'stub':stub,'contexts':[{'offset':o,'size':n,'sha256':p} for o,n,p in s['contexts']],
        'patches':[{'name':name,'offset':o,'before':a.hex(),'after':b.hex()} for name,o,a,b in changes]}
