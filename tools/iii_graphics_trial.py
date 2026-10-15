"""III-specific immutable Full HD / sky-off candidate, never execute a game.

Offsets and contexts were inspected independently in the two supplied III
binaries. The native viewport already computes height/width from its actual
canvas. Camera field of view and old HUD artwork still need a visual playtest.
"""
from __future__ import annotations
import hashlib
import struct

SOURCE_SIZE=659456
SOURCE_SHA256={
    1:'4754e7d6374563103ff56ead0eeb685f8e90bcd8e211c9cd30bf37f92eb00f8d',
    2:'17e8da1b6a8f69c998ad6eb239efa9465665729d837b779c8a39ffa9379e883e',
}
CONTEXTS=(
    (0x2DC10,0x40,'b3183505469c9b8eebca5737112cd23c7977cb31cafcf5ed5d9a654874e57a01'),
    (0x9BAB8,19*20,'674d2ccf1daad8513c947e2356763fed3370f4212a87b92fe071d35dce8dffe0'),
    (0x32AD0,0x120,'1bd247e3770b6ab581f4789097cc273f878eda333501f8a9a68d8a215a6e2b74'),
    (0x607E0,0x40,'c4fee20f82d893c1c0a75047d66f21fe7aabec94d08064c751dba1920ee468d7'),
    (0x60DC0,0xB0,'69a29d7464a0d1e0529bbf4516569fdec24b3b0c8c8d1ca5d539b33979861be8'),
)
OUTPUT_SHA256={
    (1,False):'473c426e3ad53a0e91d5a4dfbe0e0ef52bdc6a03bb41f10a7c6030972e5cfaae',
    (1,True):'c3b25c2f5e2ca40bfee0da4006a25ae5fe1c5a4ded3831d8cbfd661405a4c8bf',
    (2,False):'747079a8efa6d81e0347503265baeeef49e4d94546a3247c804fd7f655f03d32',
    (2,True):'dc844c2161ba7421e6c4e5f5580e64f6e0e687dd3bba111da327b2a419871226',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(source,tour,sky_off=True):
    if (type(source) is not bytes or type(tour) is not int or tour not in SOURCE_SHA256
            or len(source)!=SOURCE_SIZE or digest(source)!=SOURCE_SHA256[tour]
            or type(sky_off) is not bool):
        raise ValueError('Andere deel-III-binary/tour; beeldproef geweigerd.')
    for offset,size,pin in CONTEXTS:
        if digest(source[offset:offset+size])!=pin:
            raise ValueError('Andere deel-III-scherm-/viewport-/luchtcontext.')
    patches=[
        # Native table slot9 = 640x480x16; selector writes actual width/height.
        (0x9BB6C,struct.pack('<2I',640,480),struct.pack('<2I',1920,1080)),
        # Enforce race enum3 in this optional copy even if the menu saves mode0.
        # Use only the setter's own RET-following alignment padding.
        (0x2DC40,bytes.fromhex('890df8fb4800c3')+b'\x90'*4,
                  bytes.fromhex('c705f8fb480003000000c3')),
    ]
    if sky_off:
        patches += [
            # Preserve initialization; disable actual per-frame sky draws.
            (0x32BC9,bytes.fromhex('e8b233ffff'),b'\x90'*5),
            (0x32AF4,bytes.fromhex('e8b797ffff'),b'\x90'*5),
            # Every clear must include TARGET, even without a depth buffer.
            # PUSH EBX already preserves the caller. A short detour uses only
            # unreachable padding after the previous function's RET.
            (0x607F4,b'\x90'*7,bytes.fromhex('bb01000000eb0d')),
            (0x60806,bytes.fromhex('33db'),bytes.fromhex('ebec')),
            # Keep OR depth2 conditional; do not replace target1 with arg0.
            (0x60817,bytes.fromhex('8b5c2410'),b'\x90'*4),
        ]
    output=bytearray(source)
    for offset,before,after in patches:
        if len(before)!=len(after) or source[offset:offset+len(before)]!=before:
            raise ValueError('Andere deel-III-patchbytes; geen uitvoer gemaakt.')
        output[offset:offset+len(before)]=after
    result=bytes(output)
    if digest(result)!=OUTPUT_SHA256[(tour,sky_off)]:
        raise ValueError('Onverwachte deel-III-uitvoerhash.')
    return result,{'tour':tour,'source_sha256':SOURCE_SHA256[tour],
        'sha256':digest(result),'canvas':[1920,1080,16],'native_race_mode':3,
        'viewport_aspect_native_dynamic':True,'camera_fov_modified':False,
        'sky_draws_disabled':sky_off,'clear_target_requested':sky_off,
        'hud_artwork_original':True,'runtime_tested':False,'native_game_executed':False,
        'patches':[{'offset':offset,'before':before.hex(),'after':after.hex()}
                   for offset,before,after in patches]}
