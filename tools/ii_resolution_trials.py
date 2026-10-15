"""Compose higher-resolution trials from the exact verified 720p race.

Pure immutable bytes only; no execution or game filesystem access.
"""
import hashlib
import struct
from tools import ii_next_race_canvas_fix as canvas
from tools import ii_next_race_widescreen_fix as wide
from tools import ii_next_race_sky_fix as sky
from tools.ii_next_wrapper_probe import replace_setting
from tools.ii_frontend_state import RACE_DISPLAYS

SOURCE_SHA256 = sky.PATCHED_SHA256
OUTPUT_SHA256 = {
    (1920,1080): 'd71f20a7ac6f6fa27b0355fe41dfe51be96a25fa87711bc31b6ee7b32590eff1',
    (3840,2160): '1c29bf35586ef96865a762df0e59c9d68a7f65a86952963e64d7a736685aa1a8',
}
DISPLAYS = ((1920, 1080), (3840, 2160))


def _compose(source: bytes, display: tuple[int, int]) -> bytes:
    old, offsets = wide.build_stubs(wide.IMAGE_BASE + wide.SECTION_RVA, (1280,720))
    new, new_offsets = wide.build_stubs(wide.IMAGE_BASE + wide.SECTION_RVA, display)
    if len(old) != len(new) or offsets != new_offsets:
        raise ValueError('Andere stublayout; bestaande hooks kunnen niet worden hergebruikt.')
    start = wide.SECTION_RAW_OFFSET
    if source[start:start+len(old)] != old:
        raise ValueError('Andere 720p-camera/HUD-stubs.')
    if source[canvas.PATCH_OFFSET:canvas.PATCH_OFFSET+20] != struct.pack('<5I',1280,720,16,0,0):
        raise ValueError('Andere 720p-modustabel.')
    if source[sky.RECT_OFFSET:sky.RECT_OFFSET+16] != sky.RECT_AFTER:
        raise ValueError('Andere 720p-luchtbegrenzing.')
    output = bytearray(source)
    output[start:start+len(old)] = new
    struct.pack_into('<2I', output, canvas.PATCH_OFFSET, *display)
    struct.pack_into('<4I', output, sky.RECT_OFFSET, 0,0,display[0]-1,display[1]-1)
    return bytes(output)


def build_trial(source: bytes, display: tuple[int, int]) -> tuple[bytes, dict]:
    if display not in DISPLAYS or type(source) is not bytes or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Onbekende resolutie of 720p-basis; proef geweigerd.')
    output = _compose(source, display)
    digest = hashlib.sha256(output).hexdigest()
    if digest != OUTPUT_SHA256.get(display):
        raise ValueError('Onverwachte uitvoerhash van de resolutieproef.')
    return output, {'source_sha256': SOURCE_SHA256,'sha256':digest,
                    'native_display_request':[*display,16],'camera_aspect':[16,9],
                    'sky_rectangle':[0,0,display[0]-1,display[1]-1],
                    'hud_anchors_recomputed':True,'hud_sprites_resized':False,
                    'game_executed':False,'runtime_tested':False,
                    'render_distance_changed':False}


def trial_profile(source: bytes, display: tuple[int, int]) -> bytes:
    if display not in DISPLAYS or type(source) is not bytes or hashlib.sha256(source).hexdigest() != RACE_DISPLAYS['widescreen']['profile_sha256']:
        raise ValueError('Andere wrapperbasis of resolutie.')
    return replace_setting(source,b'DirectXExt',b'ExtraEnumeratedResolutions',b'1280x720',f'{display[0]}x{display[1]}'.encode())
