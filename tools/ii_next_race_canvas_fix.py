"""Pinned experimental II race canvas; immutable bytes only, no file/game I/O.

Replace only the dimensions of native 16-bit display-table record 9. The
existing native resolution enum and mode flags remain intact. This helper
does not correct camera projection or HUD anchors and is only a component
of a combined widescreen experiment, not a runtime compatibility claim.
"""
from __future__ import annotations

import hashlib
import struct

SOURCE_SIZE = 669696
SOURCE_SHA256 = '551484bcf472407fd67ee8933c6f26b5a937d428e9e0cdf0cd72988dd003c2f9'
PATCHED_SHA256 = '78b702af52260f468ee7350e59162060ee4e4dc01c1c5ddf213f2124e2ad4ccf'

MODE_INDEX = 9
PATCH_OFFSET = 0x9BFFC
PATCH_VA = 0x49E7FC
BEFORE = struct.pack('<II', 640, 480)
AFTER = struct.pack('<II', 960, 540)

# Complete records 8, 9 and 10: width, height, bit depth, and two native flags.
# Only the first two DWORDs of record 9 change. The neighbours prove that
# this is a display table, not a matching dimension pair elsewhere.
MODE_CONTEXT_OFFSET = 0x9BFE8
MODE_CONTEXT_BYTES = bytes.fromhex(
    '8002000090010000100000000000000000000000'
    '80020000e0010000100000000000000000000000'
    '2003000058020000100000000000000000000000')

# Native enum 3 selects table index 9, with backbuffer-setting command 2
# and mode-setting command 0. Preserve its calls and control flow.
MODE_SELECTION_OFFSET = 0x1FBF0
MODE_SELECTION_BYTES = bytes.fromhex(
    '6a006a006a02e8f547040083c40c6a006a096a00e8e7470400'
    'be0100000083c40c8bc65ec3')


def patch_race_canvas(source: bytes) -> tuple[bytes, dict]:
    """Return the exact 960x540 table stage; refuse unknown or repeated input."""
    if type(source) is not bytes or len(source) != SOURCE_SIZE:
        raise ValueError('Onjuiste SPEL-versie/grootte voor de 16:9-racecanvas.')
    source_sha256 = hashlib.sha256(source).hexdigest()
    if source_sha256 != SOURCE_SHA256:
        raise ValueError('Onbekende SPEL-hash; 16:9-racecanvas geweigerd.')
    for offset, expected in ((MODE_CONTEXT_OFFSET, MODE_CONTEXT_BYTES),
                             (MODE_SELECTION_OFFSET, MODE_SELECTION_BYTES),
                             (PATCH_OFFSET, BEFORE)):
        if source[offset:offset+len(expected)] != expected:
            raise ValueError('SPEL-modustabel of 3D-moduskeuze wijkt af; patch geweigerd.')

    patched = source[:PATCH_OFFSET]+AFTER+source[PATCH_OFFSET+len(BEFORE):]
    if hashlib.sha256(patched).hexdigest() != PATCHED_SHA256:
        raise ValueError('Onverwachte uitvoerhash van de 16:9-racecanvas.')
    return patched, {
        'name': 'ii-race-native-canvas-960x540', 'path': 'DATA/SPEL.DAT',
        'source_sha256': source_sha256, 'patched_sha256': PATCHED_SHA256,
        'size': SOURCE_SIZE, 'offset': PATCH_OFFSET, 'va': PATCH_VA,
        'before': BEFORE.hex(), 'after': AFTER.hex(),
        'mode_index': MODE_INDEX, 'native_resolution_enum': 3,
        'native_display_request': [960, 540, 16], 'aspect_ratio': [16, 9],
        'original_display_request': [640, 480, 16],
        'mode_flags_unchanged': True, 'unselected_modes_unchanged': True,
        'native_resolution_selection_unchanged': True,
        'data_only': True, 'machine_code_changed': False,
        'menu_changed': False, 'camera_changed': False,
        'hud_layout_changed': False, 'camera_hud_companion_required': True,
        'experimental': True, 'runtime_tested': False,
        'scope': 'Native race mode-9 canvas only; combine with audited camera/HUD changes.',
    }
