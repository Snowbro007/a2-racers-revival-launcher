"""Version-bound IV/Vakantieracer byte plans and original-aspect HD settings.

Pure functions only: never execute games, enumerate devices, or change source files.
"""
from __future__ import annotations
import hashlib
import re
import struct
from tools import trial_manifest

PROFILES=('compat','hd1080')

SPECS={
 'a2racer4':{
  'menu':(1158656,'d56c94301a56dc6c20ac278e15abb2fdccc9a144b6e59986897c67740ba2b0f0'),
  'race':(1875968,'ccd1b03472b25c8b7acacf4ba7e6abf60f657dfff2efd90f29e740b03f62286b'),
  'display':(0x5f78,'ff2594e74a00'),'import':0xacb18,
  'intro':(0xa5024,0x4a5c24,0x4ab694,0x10,0x403cb0),
  'keyboard':0xed4f1,
  'setter':(0x4735c,'8b4c2404890d38db5900c3','c70538db590003000000c3'),'table':0x1b3864},
 'vakantieracer':{
  'menu':(6444544,'bbd3b40f0a48630e30aa73456fa97dd95c3c0b7e424e98cb9efc6050acb5116b'),
  'race':(1126400,'6c4a3a196fa8ee3d2a2bf7b437adbc9da5be3be0708eec15d0fce2d4eb99c939'),
  'display':(0x6948,'ff250c874900'),'import':0x965bc,
  'intro':(0x8e044,0x48ec44,0x495208,0x14,0x4045f8),
  'keyboard':0xb43b1,
  'setter':(0x33d5c,'8b4c2404890dc89f4f00c3','c705c89f4f0003000000c3'),'table':0x10aa94}}


MENU_CONFIG=b'''[ddraw]
windowed=true
fullscreen=false
width=1920
height=1080
maintas=true
aspect_ratio=4:3
renderer=gdi
adjmouse=true
devmode=true
nonexclusive=true
border=false
resizable=false
center_window=2
posX=-32000
posY=-32000
savesettings=0
maxgameticks=-1
maxfps=60
fixchilds=2
singlecpu=false
hook_peekmessage=true
'''


def sha(raw): return hashlib.sha256(raw).hexdigest()


def keyboard_patches(raw,start):
    # Both positions were independently located through their own keyboard
    # diagnostic xrefs. Keep the original unknown-HRESULT exception path.
    cave=start+0x4d;general=start+0xa5;acquire=start+0x1d;end=start+0x101
    jump=lambda at,target:b'\xe9'+struct.pack('<i',target-(at+5))
    jcc=lambda opcode,at,target:bytes([0x0f,opcode])+struct.pack('<i',target-(at+6))
    initial=bytes.fromhex('5033c0b940000000f3ab588dbedc0000008b08')
    initial+=jump(cave+len(initial),start+8)
    classify=cave+len(initial)
    first=b'\x3d'+struct.pack('<I',0x8007001e)
    first+=jcc(0x84,classify+len(first),acquire)
    first+=b'\x3d'+struct.pack('<I',0x8007000c)
    first+=jcc(0x84,classify+len(first),acquire)
    first+=jump(classify+len(first),general)
    retry=cave+len(initial)+len(first)
    clear=retry+19
    second=b'\x3d'+struct.pack('<I',0x8007001e)+bytes([0x74,clear-(retry+7)])
    second+=b'\x3d'+struct.pack('<I',0x8007000c)+bytes([0x74,clear-(retry+14)])
    second+=jump(retry+len(second),general)
    second+=bytes.fromhex('33c0b940000000f3ab')
    second+=jump(retry+len(second),end)
    code=initial+first+second
    if len(code)>88: raise ValueError('Keyboard-code overschrijdt de oorspronkelijke fouttak.')
    changes=[(start,bytes.fromhex('8b088dbedc000000'),bytes.fromhex('8dbedc000000eb')+bytes([cave-(start+8)])),
             (start+0x12,bytes.fromhex('3d1e0007800f8588000000'),jump(start+0x12,classify)+b'\x90'*6),
             (start+0x2c,bytes.fromhex('0f85cf000000'),jcc(0x85,start+0x2c,clear)),
             (start+0x45,bytes.fromhex('85c00f84b4000000'),jump(start+0x45,retry)+b'\x90'*3),
             (cave,raw[cave:cave+88],code+b'\x90'*(88-len(code)))]
    return changes


def patch_binary(raw,game,kind):
    if game not in SPECS or kind not in ('menu','race'): raise ValueError('Onbekende game/binaryrol.')
    spec=SPECS[game];size,pin=spec[kind]
    if type(raw) is not bytes or len(raw)!=size or sha(raw)!=pin:
        raise ValueError('Onbekende oorspronkelijke gamebinary; baseline geweigerd.')
    if kind=='menu':
        offset,before=spec['display']
        changes=[(offset,bytes.fromhex(before),bytes.fromhex('31c0c2080090'))]
        intro_offset,intro_va,data_global,field,assign=spec['intro']
        # Same managed-string return contract as the native scanner, now the
        # host-verified absolute local INTROAVI path. Preserve EBX/refcounts.
        code=bytes.fromhex('538bdaa1')+struct.pack('<I',data_global)+bytes.fromhex('8b008b80c40000008b50')+bytes([field])+bytes.fromhex('8bc3e8')
        code+=struct.pack('<i',assign-(intro_va+len(code)+4))+bytes.fromhex('5bc3')
        changes.append((intro_offset,raw[intro_offset:intro_offset+len(code)],code))
        if game=='a2racer4':
            # The initial state continues to new-player/main-menu after this
            # isolated MPEG modal call. Preserve that state and skip only video.
            changes.append((0xa51f0,bytes.fromhex('e8dbf2ffff'),b'\x90'*5))
    else:
        offset,before,after=spec['setter']
        # Keep the native 640x480x16 screen record. First establish a working
        # renderer before reintroducing the experimental high-resolution table.
        changes=[(offset,bytes.fromhex(before),bytes.fromhex(after))]
        changes+=keyboard_patches(raw,spec['keyboard'])
        if game=='a2racer4':
            from tools import later_iv_mouse_input,later_iv_joystick_input,later_iv_texture_formats,later_iv_vram_probe
            _,mouse_plan=later_iv_mouse_input.patch(raw)
            changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                           for item in mouse_plan['patches'])
            _,joystick_plan=later_iv_joystick_input.patch(raw)
            changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                           for item in joystick_plan['patches'])
            _,texture_plan=later_iv_texture_formats.patch(raw)
            changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                           for item in texture_plan['patches'])
            _,probe_plan=later_iv_vram_probe.patch(raw)
            changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                           for item in probe_plan['patches'])
        if game=='vakantieracer':
            from tools import later_mouse_input,later_joystick_input,later_vacation_texture_formats
            _,mouse_plan=later_mouse_input.patch(raw)
            changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                           for item in mouse_plan['patches'])
            _,joystick_plan=later_joystick_input.patch(raw)
            changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                           for item in joystick_plan['patches'])
            _,texture_plan=later_vacation_texture_formats.patch(raw)
            changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                           for item in texture_plan['patches'])
        from tools import later_mouse_shutdown
        _,shutdown_plan=later_mouse_shutdown.patch(raw,game)
        changes.extend((item['offset'],bytes.fromhex(item['before']),bytes.fromhex(item['after']))
                       for item in shutdown_plan['patches'])
    out=bytearray(raw)
    covered=set()
    for offset,before,after in changes:
        if len(before)!=len(after) or raw[offset:offset+len(before)]!=before:
            raise ValueError('Onverwachte patchcontext; geen uitvoer gemaakt.')
        region=set(range(offset,offset+len(before)))
        if covered & region: raise ValueError('Patchgebieden overlappen; geen uitvoer gemaakt.')
        covered.update(region)
        out[offset:offset+len(before)]=after
    result=bytes(out)
    return result,{'source_sha256':pin,'sha256':sha(result),'kind':kind,
                   'patches':[{'offset':o,'before':a.hex(),'after':b.hex()} for o,a,b in changes],
                   'runtime_verified':False}


def set_ini(raw,section,key,value):
    lines=raw.splitlines(keepends=True);current=b'';positions=[]
    for index,line in enumerate(lines):
        header=re.fullmatch(rb'\s*\[([^\]]+)\]\s*',line)
        if header: current=header[1].strip().lower()
        elif current==section.encode().lower():
            match=re.match(rb'([ \t]*'+re.escape(key.encode())+rb'[ \t]*=[ \t]*)([^;\r\n]*)(.*)',line,re.I|re.S)
            if match:
                positions.append(index)
                trailing=match[2][len(match[2].rstrip()):]
                lines[index]=match[1]+value.encode('cp1252')+trailing+match[3]
    if len(positions)!=1: raise ValueError('Geen unieke INI-instelling: '+section+'/'+key)
    return b''.join(lines)


def validate_profile(game,profile):
    if game not in SPECS: raise ValueError('Onbekende baselinegame.')
    if profile not in PROFILES: raise ValueError('Onbekend beeldprofiel.')


def profile_metadata(profile):
    if profile not in PROFILES: raise ValueError('Onbekend beeldprofiel.')
    return {'profile':profile,'logical_canvas_requested':[640,480],
            'render_resolution_requested':[1440,1080] if profile=='hd1080' else [640,480],
            'race_aspect_ratio_requested':[4,3],'widescreen_requested':False,
            'race_windowed_requested':profile!='hd1080',
            'wrapper_windowed_requested':True,
            'fullscreen_size_requested':profile=='hd1080',
            'wrapper_3d_resolution_requested':'h:1440, v:1080' if profile=='hd1080' else 'unforced'}


def race_config(raw,profile='compat'):
    settings=profile_metadata(profile)
    if sha(raw)!=trial_manifest.DGVOODOO_CONFIG_SOURCE['sha256']:
        raise ValueError('Onbekende dgVoodoo-basisconfiguratie.')
    for section,key,value in [('General','CaptureMouse','false'),('General','CenterAppWindow','true'),
                              ('General','FullScreenMode','false'),
                              ('General','ScalingMode','stretched_ar'),
                              ('GeneralExt','WindowedAttributes','borderless,fullscreensize' if profile=='hd1080' else 'borderless'),
                              ('GeneralExt','DesktopBitDepth','16'),
                              ('DirectX','VRAM','32'),
                              ('DirectX','Resolution',settings['wrapper_3d_resolution_requested']),
                              ('DirectX','AppControlledScreenMode','false'),
                              ('DirectX','ForceVerticalSync','true'),('DirectX','dgVoodooWatermark','false')]:
        raw=set_ini(raw,section,key,value)
    return raw


def race_ini(raw,game,profile='compat'):
    validate_profile(game,profile)
    # True app-windowed mode does not use dgVoodoo's forced resolution. The HD
    # trial requests native fullscreen while dgVoodoo forces a desktop-sized
    # window. Compat keeps the confirmed native-windowed path unchanged.
    # This is a requested presentation route, not a runtime resolution claim.
    for key,value in [('RESOLUTION','3'),('WINDOWED','0' if profile=='hd1080' else '1')]:
        raw=set_ini(raw,'PROGRAM',key,value)
    # The native logger opens/appends/closes its file on every message. Restore
    # the quiet startup used by the earlier variants that reached a race.
    # This avoids diagnostic I/O; it is not proof that a loading hang is fixed.
    raw=set_ini(raw,'HELPDESK','DEBUGON','0')
    return raw
