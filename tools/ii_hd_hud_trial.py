"""Pinned native HD source surfaces with original logical HUD geometry."""
import hashlib
import struct
from tools import ii_next_race_widescreen_fix as wide
from tools import ii_hud_pair_trial as pair
from tools.ii_hd_hud_assets import FONT_INDICES

FONT_BASE = 0x486D08 + 17*148
FONT_HOOK = (0x4183D2, 0x177D2, bytes.fromhex('8b35507c4a00'))
SIZE_HOOK = (0x4690AA, 0x684AA, bytes.fromhex('8b44310c8b6c3108'))
BITMAP_IDS = (426, 453)


def _font_filter(c, done):
    c.emit(b'\xa1'+struct.pack('<I', 0x4EAD08))
    for index in FONT_INDICES:
        c.emit(b'\x3d'+struct.pack('<I', FONT_BASE+index*148))
        c.branch(b'\x0f\x84','font_ok')
    c.branch(b'\xe9',done); c.label('font_ok')


def _bitmap_filter(c, done):
    c.emit(b'\x81\xfe'+struct.pack('<I',BITMAP_IDS[0]*32));c.branch(b'\x0f\x82',done)
    c.emit(b'\x81\xfe'+struct.pack('<I',(BITMAP_IDS[1]+1)*32));c.branch(b'\x0f\x83',done)


def build_source_stub(va, display, route, previous):
    c=wide._Code(va);c.emit(b'\x9c\x60');wide._wide_guards(c,'done',display)
    if route=='glyph': _font_filter(c,'done'); offsets=(0x40,0x44,0x48,0x4C)
    elif route=='bitmap': _bitmap_filter(c,'done'); offsets=(0x44,0x48,0x4C,0x50)
    else: raise ValueError('Onbekende bronroute.')
    for offset in offsets:
        c.emit(b'\x6b\x44\x24'+bytes([offset])+b'\x03')
        c.emit(b'\x89\x44\x24'+bytes([offset]))
    c.label('done');c.emit(b'\x61\x9d');c.branch(b'\xe9',previous)
    return c.finish()


def build_size_stub(va,display):
    c=wide._Code(va);c.emit(SIZE_HOOK[2]);c.emit(b'\x9c\x60')
    wide._wide_guards(c,'done',display);_bitmap_filter(c,'done')
    c.emit(bytes.fromhex('b90300000031d2f7f18944241c8bc531d2f7f189442408'))
    c.label('done');c.emit(b'\x61\x9d');c.branch(b'\xe9',SIZE_HOOK[0]+8)
    return c.finish()


def build_font_stub(va,display):
    c=wide._Code(va);c.emit(b'\x9c\x60');wide._wide_guards(c,'done',display)
    c.emit(bytes.fromhex('833d507c4a0001'));c.branch(b'\x0f\x85','done')
    c.emit(bytes.fromhex('bb03000000'))
    for index in FONT_INDICES:
        address=FONT_BASE+148*index; label=str(index)
        c.emit(b'\x8b\x35'+struct.pack('<I',address+0x68))
        c.emit(bytes.fromhex('85f6'));c.branch(b'\x0f\x84','next'+label)
        c.emit(bytes.fromhex('bf00010000'))
        c.label('loop'+label);c.emit(bytes.fromhex('8b2e85ed'));c.branch(b'\x0f\x84','skip'+label)
        c.emit(bytes.fromhex('837d0400'));c.branch(b'\x0f\x8e','skip'+label)
        c.emit(bytes.fromhex('8b450431d2f7f38945048b450831d2f7f3894508'))
        c.label('skip'+label);c.emit(bytes.fromhex('83c60c4f'));c.branch(b'\x0f\x85','loop'+label)
        for field in (0x80,0x84):
            c.emit(b'\xa1'+struct.pack('<I',address+field));c.emit(bytes.fromhex('31d2f7f3'))
            c.emit(b'\xa3'+struct.pack('<I',address+field))
        c.label('next'+label)
    c.label('done');c.emit(b'\x61\x9d'+FONT_HOOK[2]);c.branch(b'\xe9',FONT_HOOK[0]+6)
    return c.finish()


def build_trial(source,display):
    if (type(source) is not bytes or display not in pair.OUTPUT_HASHES or
            hashlib.sha256(source).hexdigest()!=pair.OUTPUT_HASHES[display]):
        raise ValueError('Onbekende werkende HD-HUD-bron.')
    for _,off,before in (FONT_HOOK,SIZE_HOOK):
        if source[off:off+len(before)]!=before:raise ValueError('Andere HUD-loader/geometrie.')
    pe=struct.unpack_from('<I',source,0x3C)[0];opt=struct.unpack_from('<H',source,pe+20)[0]
    count=struct.unpack_from('<H',source,pe+6)[0];section=pe+24+opt+40*(count-1)
    _,rva,size,raw=struct.unpack_from('<4I',source,section+8)
    if (source[section:section+8]!=wide.SECTION_NAME or raw!=wide.SECTION_RAW_OFFSET
            or raw+size!=len(source) or rva!=wide.SECTION_RVA):raise ValueError('Andere eigen RX-sectie.')
    result=bytearray(source);stubs=[]
    tasks=[('font',FONT_HOOK,build_font_stub),('size',SIZE_HOOK,build_size_stub)]
    for route,(_,off,original,*_) in pair.HOOKS.items():
        if source[off]!=0xE9:raise ValueError('Ontbrekende gepaarde HUD-hook.')
        hook=pair.HOOKS[route][0]
        prev=hook+5+struct.unpack_from('<i',source,off+1)[0]
        if not wide.IMAGE_BASE+rva<=prev<wide.IMAGE_BASE+rva+size:raise ValueError('Andere helperketen.')
        tasks.append((route,(hook,off,source[off:off+len(original)]),
                      lambda va,d,route=route,prev=prev:build_source_stub(va,d,route,prev)))
    for name,(hook,off,original),factory in tasks:
        va=wide.IMAGE_BASE+rva+len(result)-raw;payload=factory(va,display)
        stubs.append({'name':name,'va':va,'bytes':len(payload)})
        result.extend(payload);result[off:off+len(original)]=b'\xe9'+struct.pack('<i',va-hook-5)+b'\x90'*(len(original)-5)
    payload_size=len(result)-raw;result.extend(b'\0'*((-len(result))%wide.FILE_ALIGNMENT))
    struct.pack_into('<I',result,section+8,payload_size);struct.pack_into('<I',result,section+16,len(result)-raw)
    struct.pack_into('<I',result,pe+24+4,struct.unpack_from('<I',source,pe+24+4)[0]+len(result)-len(source))
    struct.pack_into('<I',result,pe+24+56,(rva+payload_size+4095)&~4095)
    data=bytes(result)
    return data,{'source_sha256':hashlib.sha256(source).hexdigest(),'sha256':hashlib.sha256(data).hexdigest(),
                 'source_scale':3,'display':list(display),'stubs':stubs,'runtime_tested':False}
