"""Separate HD trial: scale right-hand HUD glyphs and bitmaps together.

Pure byte construction. The radar and centered dialogs keep their native size.
Only exact HD source hashes and audited caller stacks are accepted.
"""
import hashlib
import struct
from tools import ii_next_race_widescreen_fix as wide
from tools.ii_resolution_trials import OUTPUT_SHA256 as SOURCE_HASHES

OUTPUT_HASHES = {
    (1920,1080): '1715fc687b31c87441ffa7850fb5b792f4b170fc6ea9eee382d1f269d38fc307',
    (3840,2160): '6a363709651c38c76370d260cc12a0739af7cc2a21f2932a9a94917f421b8f4f',
}
GROUPS = dict((name, ids) for name, ids, _, _ in wide.HUD_GROUPS[:2])
# At the selected instruction each function has pushed four registers.
# PUSHFD/PUSHAD save an additional 0x24 bytes, preserving all live registers.
HOOKS = {
    'bitmap': (0x4691E4, 0x685E4, bytes.fromhex('8b44300450'),
               ((0x64, (0x41C1C2, 0x41C1D9)),), 0x94, (0x54,0x58,0x5C,0x60)),
    'glyph': (0x46956C, 0x6896C, bytes.fromhex('8b48688b0411'),
              ((0x60, (0x46A1F0,)), (0x88, (0x46A2B5,)),
               (0x230, (0x41C0D6,))), 0x3EC, (0x50,0x54,0x58,0x5C)),
}


def scale_rect(rect, display, group):
    if display not in SOURCE_HASHES or group not in GROUPS:
        raise ValueError('Onbekende gepaarde HUD-proef.')
    width,height=display
    anchors=(width, height if group=='right_bottom_race' else 0)*2
    denominator=2 if height==1080 else 1
    return tuple(a+(v-a)*3//denominator for v,a in zip(rect,anchors))


def build_stub(va, display, route):
    if display not in SOURCE_HASHES or route not in HOOKS:
        raise ValueError('Onbekende HUD-route.')
    hook,_,original,callers,index_offset,rect_offsets=HOOKS[route]
    c=wide._Code(va);c.emit(b'\x9c\x60');wide._wide_guards(c,'done',display)
    for number,(offset,values) in enumerate(callers):
        for v in values:
            c.emit(b'\x81\xbc\x24'+struct.pack('<II',offset,v))
            c.branch(b'\x0f\x84','caller'+str(number))
        c.branch(b'\xe9','done');c.label('caller'+str(number))
    c.emit(b'\x8b\x8c\x24'+struct.pack('<I',index_offset))
    for group,ids in GROUPS.items():
        for index in ids:
            c.emit(b'\x83\xf9'+bytes([index]));c.branch(b'\x0f\x84',group)
    c.branch(b'\xe9','done')
    for group in GROUPS:
        c.label(group)
        anchors=(display[0],display[1] if group=='right_bottom_race' else 0)*2
        for offset,anchor in zip(rect_offsets,anchors):
            c.emit(b'\x8b\x84\x24'+struct.pack('<I',offset))
            if anchor:c.emit(b'\x2d'+struct.pack('<I',anchor))
            c.emit(bytes.fromhex('6bc003'))
            if display[1]==1080:c.emit(bytes.fromhex('d1f8'))
            if anchor:c.emit(b'\x05'+struct.pack('<I',anchor))
            c.emit(b'\x89\x84\x24'+struct.pack('<I',offset))
        c.branch(b'\xe9','done')
    c.label('done');c.emit(b'\x61\x9d'+original)
    c.branch(b'\xe9',hook+len(original));return c.finish()


def _compose(source,display):
    pe=struct.unpack_from('<I',source,0x3C)[0]
    count=struct.unpack_from('<H',source,pe+6)[0]
    optional=struct.unpack_from('<H',source,pe+20)[0]
    section=pe+24+optional+(count-1)*40
    _,rva,raw_size,raw=struct.unpack_from('<4I',source,section+8)
    if (source[section:section+8]!=wide.SECTION_NAME or rva!=wide.SECTION_RVA
            or raw!=wide.SECTION_RAW_OFFSET or raw+raw_size!=len(source)):
        raise ValueError('Andere eigen RX-sectie.')
    result=bytearray(source);meta=[]
    for route,(hook,offset,original,*_) in HOOKS.items():
        if source[offset:offset+len(original)]!=original:
            raise ValueError('Andere oorspronkelijke HUD-instructies.')
        va=wide.IMAGE_BASE+rva+len(result)-raw
        stub=build_stub(va,display,route)
        meta.append({'route':route,'va':va,'offset':len(result),'size':len(stub)})
        result.extend(stub)
        result[offset:offset+len(original)]=b'\xe9'+struct.pack('<i',va-hook-5)+b'\x90'*(len(original)-5)
    payload_size=len(result)-raw
    result.extend(b'\0'*((-len(result))%wide.FILE_ALIGNMENT))
    struct.pack_into('<I',result,section+8,payload_size)
    struct.pack_into('<I',result,section+16,len(result)-raw)
    struct.pack_into('<I',result,pe+24+4,struct.unpack_from('<I',source,pe+24+4)[0]+len(result)-len(source))
    struct.pack_into('<I',result,pe+24+56,(rva+payload_size+wide.SECTION_ALIGNMENT-1)&~(wide.SECTION_ALIGNMENT-1))
    return bytes(result),meta


def build_trial(source,display):
    if type(source) is not bytes or display not in SOURCE_HASHES or hashlib.sha256(source).hexdigest()!=SOURCE_HASHES[display]:
        raise ValueError('Onbekende HD-bron; gepaarde HUD-proef geweigerd.')
    result,stubs=_compose(source,display)
    digest=hashlib.sha256(result).hexdigest()
    if digest!=OUTPUT_HASHES.get(display):raise ValueError('Onverwachte HUD-uitvoerhash.')
    return result,{'source_sha256':SOURCE_HASHES[display],'sha256':digest,
                   'display':list(display),'stubs':stubs,'radar_scaled':False,
                   'text_and_frames_scaled':True,'native_game_executed':False,
                   'runtime_tested':False}
