"""Pinned 720p accelerated sky extent repair; static data editing only.

The active 3D background constructs two TL-vertex strips from a separate
inclusive 640x480 rectangle, independent of the native display table.
Only the separately generated 1280x720 race binary receives this repair.
"""
import hashlib
import struct
from tools import ii_next_race_widescreen_fix as wide

SOURCE_SHA256 = wide.HD_PATCHED_SHA256
PATCHED_SHA256 = '1e5cef6499bd001ace3f22ff0a818101fe43bcf80b2ff086f0d912e6f3891016'
RECT_OFFSET = 0x859A0
RECT_VA = 0x4881A0
RECT_BEFORE = struct.pack('<4I',0,0,639,479)
RECT_AFTER = struct.pack('<4I',0,0,1279,719)
CONTEXT_OFFSET = 0x17EB0
CONTEXT_SIZE = 0x2E8
CONTEXT_SHA256 = '35b85a9a3025d8c4d67830b061316e0d56a323e11b505a7dcebe72a369e4d7f3'


def patch_sky(source):
    if type(source) is not bytes or hashlib.sha256(source).hexdigest()!=SOURCE_SHA256:
        raise ValueError('Andere 720p-racebasis; luchtcorrectie geweigerd.')
    if source[RECT_OFFSET:RECT_OFFSET+16]!=RECT_BEFORE:
        raise ValueError('Andere achtergrondrechthoek; luchtcorrectie geweigerd.')
    context=source[CONTEXT_OFFSET:CONTEXT_OFFSET+CONTEXT_SIZE]
    if hashlib.sha256(context).hexdigest()!=CONTEXT_SHA256:
        raise ValueError('Andere 3D-achtergrondconstructor; luchtcorrectie geweigerd.')
    output=source[:RECT_OFFSET]+RECT_AFTER+source[RECT_OFFSET+16:]
    if PATCHED_SHA256 and hashlib.sha256(output).hexdigest()!=PATCHED_SHA256:
        raise ValueError('Onverwachte luchtcorrectie-uitvoer.')
    return output, {'path':'accelerated_tl_background','rectangle_va':RECT_VA,
                    'offset':RECT_OFFSET,'before':[0,0,639,479],
                    'after':[0,0,1279,719],'inclusive_edges':True,
                    'game_executed':False,'sha256':hashlib.sha256(output).hexdigest()}
