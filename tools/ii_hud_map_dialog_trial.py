"""Pinned HD extension: centered race dialogs and both radar draw routes.

Immutable byte construction only. The accelerated radar is redrawn from its
separate native input vertices each frame before this presentation hook.
"""
import hashlib
import struct
from tools import ii_next_race_widescreen_fix as wide
from tools import ii_hud_pair_trial as pair

SOURCE_HASHES = {
    (1920,1080): '0f4bfa843409a67eefd7c55a25e42d190680f5bbaca4e0ee44ac2d00602bc579',
    (3840,2160): '031f8bc4af3f595d2958494abc4c0aacb9f5f4e7acb6c838daae7ce8db311b81',
}
GROUPS = {'center_dialog': (34,35,36,37), 'left_bottom_radar': (11,16)}
RADAR_HOOK = (0x41D41F, 0x1C81F, bytes.fromhex('a1fca74e00'))
RADAR_VERTICES = 0x4AC9A8
RADAR_PARENT = 0x4251F2


def scale_rect(rect, display, group):
    if display not in SOURCE_HASHES or group not in GROUPS:
        raise ValueError('Onbekende kaart-/racevensterproef.')
    width,height=display
    anchor=(width//2,height//2) if group=='center_dialog' else (0,height)
    divisor=2 if height==1080 else 1
    return tuple(a+(v-a)*3//divisor for v,a in zip(rect,anchor*2))


def scale_radar(vertices, display):
    if display not in SOURCE_HASHES or len(vertices)!=4 or any(len(v)!=2 for v in vertices):
        raise ValueError('Onjuiste radarvlakgeometrie.')
    scale=display[1]/720
    return tuple((x*scale,y*scale) for x,y in vertices)


def build_rect_stub(va, display, route, previous):
    if display not in SOURCE_HASHES or route not in pair.HOOKS:
        raise ValueError('Onbekende kaart-/vensterroute.')
    _,_,_,callers,index_offset,offsets=pair.HOOKS[route]
    c=wide._Code(va);c.emit(b'\x9c\x60');wide._wide_guards(c,'done',display)
    for number,(offset,values) in enumerate(callers):
        for value in values:
            c.emit(b'\x81\xbc\x24'+struct.pack('<II',offset,value))
            c.branch(b'\x0f\x84','caller'+str(number))
        c.branch(b'\xe9','done');c.label('caller'+str(number))
    c.emit(b'\x8b\x8c\x24'+struct.pack('<I',index_offset))
    for group,indices in GROUPS.items():
        for index in indices:
            c.emit(b'\x83\xf9'+bytes([index]));c.branch(b'\x0f\x84',group)
    c.branch(b'\xe9','done')
    for group in GROUPS:
        c.label(group)
        anchor=(display[0]//2,display[1]//2) if group=='center_dialog' else (0,display[1])
        for offset,a in zip(offsets,anchor*2):
            c.emit(b'\x8b\x84\x24'+struct.pack('<I',offset))
            if a:c.emit(b'\x2d'+struct.pack('<I',a))
            c.emit(bytes.fromhex('6bc003'))
            if display[1]==1080:c.emit(bytes.fromhex('d1f8'))
            if a:c.emit(b'\x05'+struct.pack('<I',a))
            c.emit(b'\x89\x84\x24'+struct.pack('<I',offset))
        c.branch(b'\xe9','done')
    c.label('done');c.emit(b'\x61\x9d');c.branch(b'\xe9',previous)
    return c.finish()


def build_radar_stub(va, display):
    if display not in SOURCE_HASHES:
        raise ValueError('Onbekende radardoelresolutie.')
    c=wide._Code(va);c.emit(b'\x9c\x60');wide._wide_guards(c,'done',display)
    # Native function has pushed ESI and EDI; the parent return is ESP+8.
    c.emit(b'\x81\x7c\x24\x2c'+struct.pack('<I',RADAR_PARENT))
    c.branch(b'\x0f\x85','done')
    factor_refs=[]
    for index in range(4):
        for field in (0,4):
            address=RADAR_VERTICES+32*index+field
            c.emit(b'\xd9\x05'+struct.pack('<I',address))
            c.emit(b'\xd8\x0d');factor_refs.append(len(c.data));c.emit(b'\0'*4)
            c.emit(b'\xd9\x1d'+struct.pack('<I',address))
    c.label('done');c.emit(b'\x61\x9d'+RADAR_HOOK[2])
    c.branch(b'\xe9',RADAR_HOOK[0]+len(RADAR_HOOK[2]))
    constant_va=va+len(c.data);c.emit(struct.pack('<f',display[1]/720))
    result=bytearray(c.finish())
    for offset in factor_refs:struct.pack_into('<I',result,offset,constant_va)
    return bytes(result)


def build_trial(source, display):
    if type(source) is not bytes or display not in SOURCE_HASHES or hashlib.sha256(source).hexdigest()!=SOURCE_HASHES[display]:
        raise ValueError('Onbekende goedgekeurde HD-HUD-bron.')
    hook,off,original=RADAR_HOOK
    if source[off:off+len(original)]!=original:
        raise ValueError('Andere radarpresentatie.')
    pe=struct.unpack_from('<I',source,0x3c)[0]
    count=struct.unpack_from('<H',source,pe+6)[0];opt=struct.unpack_from('<H',source,pe+20)[0]
    sec=pe+24+opt+40*(count-1)
    _,rva,size,raw=struct.unpack_from('<4I',source,sec+8)
    if (source[sec:sec+8]!=wide.SECTION_NAME or rva!=wide.SECTION_RVA or
            raw!=wide.SECTION_RAW_OFFSET or raw+size!=len(source)):
        raise ValueError('Andere eigen helpersectie.')
    tasks=[]
    for route,(hook,off,original,*_) in pair.HOOKS.items():
        if source[off]!=0xe9:raise ValueError('Ontbrekende HD-HUD-helperketen.')
        previous=hook+5+struct.unpack_from('<i',source,off+1)[0]
        if not wide.IMAGE_BASE+rva<=previous<wide.IMAGE_BASE+rva+size:
            raise ValueError('HUD-helper buiten eigen sectie.')
        tasks.append((route,(hook,off,source[off:off+len(original)]),
            lambda va,route=route,previous=previous:build_rect_stub(va,display,route,previous)))
    tasks.append(('radar',RADAR_HOOK,lambda va:build_radar_stub(va,display)))
    result=bytearray(source);stubs=[]
    for name,(hook,off,before),factory in tasks:
        va=wide.IMAGE_BASE+rva+len(result)-raw;payload=factory(va)
        stubs.append({'route':name,'va':va,'size':len(payload)})
        result.extend(payload)
        result[off:off+len(before)]=b'\xe9'+struct.pack('<i',va-hook-5)+b'\x90'*(len(before)-5)
    payload_size=len(result)-raw
    result.extend(b'\0'*((-len(result))%wide.FILE_ALIGNMENT))
    struct.pack_into('<I',result,sec+8,payload_size);struct.pack_into('<I',result,sec+16,len(result)-raw)
    struct.pack_into('<I',result,pe+24+4,struct.unpack_from('<I',source,pe+24+4)[0]+len(result)-len(source))
    struct.pack_into('<I',result,pe+24+56,(rva+payload_size+wide.SECTION_ALIGNMENT-1)&~(wide.SECTION_ALIGNMENT-1))
    data=bytes(result)
    return data,{'source_sha256':SOURCE_HASHES[display],'sha256':hashlib.sha256(data).hexdigest(),
                 'display':list(display),'stubs':stubs,'radar_scaled':True,
                 'center_dialog_scaled':True,'right_hud_unchanged':True,
                 'native_game_executed':False,'runtime_tested':False}
