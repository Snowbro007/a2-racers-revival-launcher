"""Pinned 720p race composition for the Revival menu; never execute a game."""
from __future__ import annotations
import hashlib
import struct

from tools import ii_next_race_canvas_fix as canvas
from tools import ii_next_race_widescreen_fix as wide
from tools import ii_next_race_sky_fix as sky
from tools.ii_next_wrapper_probe import replace_setting

BASE_PROFILE_SHA256 = '6de487f0edbab8ec5d60d826211631ea3bc0a0d8ddc10a0bbe7eeca2b7f8c2f5'


def build_race(source: bytes) -> tuple[bytes, dict]:
    # Reuse the independently pinned table/context checks. The 720p stage
    # changes that same record, then uses the same audited hooks/PE layout.
    stage, canvas_plan = canvas.patch_race_canvas(source)
    stage = stage[:canvas.PATCH_OFFSET] + struct.pack('<II', 1280, 720) + stage[canvas.PATCH_OFFSET+8:]
    output, plan = wide.patch_race_widescreen(stage, display=(1280, 720))
    output, sky_plan = sky.patch_sky(output)
    return output, {'verified_table_context': canvas_plan, 'widescreen': plan,
                    'moving_sky': sky_plan,
                    'native_display_request': [1280, 720, 16],
                    'original_preserved': True, 'game_executed': False}


def race_profile(source: bytes) -> bytes:
    if type(source) is not bytes or hashlib.sha256(source).hexdigest() != BASE_PROFILE_SHA256:
        raise ValueError('Andere raceprofielbasis; fullscreenprofiel geweigerd.')
    # Keep the proven borderless screen-size window and 60-FPS request.
    # Explicit enumeration addresses the earlier unsupported custom mode.
    return replace_setting(source, b'DirectXExt', b'ExtraEnumeratedResolutions', b'', b'1280x720')
