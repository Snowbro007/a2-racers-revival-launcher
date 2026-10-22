"""Build HD resources locally from owned game data and our authored pixels."""
import base64
import hashlib
import json
import struct
from functools import lru_cache

from tools.ii_frontend_state import read_regular
from tools.ii_frontend_prepare import resource
from tools.ii_hd_hud_assets import FONT_NAMES, encode_hd_font, replace_resources

RECIPE = 'tools/ii_frontend_art/hud-pixels.json'
RECIPE_SHA256 = '6ed26c65ff4a6ba241f3186babb8362fe5523a386f0cc64d963575fab7ade7b9'
OUTPUT_PINS = {
    'RC.IND': '50f8a51dac7ec946dcf2a0935b89ffd87657d4ba7517b5ec539e771343974734',
    'RC.IMG': 'b7847f39afef801846fcf1bd1e44f98121d773119d5d480a23bbddc89d55ae02',
    'RCS.IND': '859f565348c201a39d3f87b64d6b553339d16b5ce14b6d6f9334fc8f833ad817',
    'RCS.IMG': 'afcf885a37ab2aa2e37d76b0c0ed8ea9692bac23262d2af78e896b0955509687',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def replace_frames(index, image, frames):
    """Keep original bitmap anchors and all unselected records byte for byte."""
    if len(index) < 2:
        raise ValueError('Onjuiste HUD-bitmapindex.')
    count = struct.unpack_from('<H', index)[0]
    if count != 453 or len(index) != 2 + 4 * count:
        raise ValueError('Onjuist aantal HUD-bitmaps.')
    offsets = struct.unpack_from('<' + str(count) + 'I', index, 2)
    if (offsets[0] != 2 or offsets[-1] >= len(image)
            or any(a >= b for a, b in zip(offsets, offsets[1:]))
            or set(frames) != {str(n) for n in range(426, 454)}):
        raise ValueError('Onjuiste HUD-bitmapgrenzen of tekenset.')
    out_index = bytearray(index)
    out_image = bytearray(image[:2])
    for number, start in enumerate(offsets, 1):
        end = offsets[number] if number < count else len(image)
        record = image[start:end]
        if str(number) in frames:
            if len(record) < 8:
                raise ValueError('Onjuiste HUD-bitmapkop.')
            width, height, a, anchor = struct.unpack_from('<4H', record)
            pixels = base64.b64decode(frames[str(number)], validate=True)
            if (not 0 < width <= 4096 or not 0 < height <= 4096
                    or len(record) != 8 + width * height
                    or len(pixels) != width * height * 9):
                raise ValueError('Onjuiste HD-bitmapafmetingen.')
            record = struct.pack('<4H', width * 3, height * 3, a, anchor) + pixels
        struct.pack_into('<I', out_index, 2 + 4 * (number - 1), len(out_image))
        out_image.extend(record)
    return bytes(out_index), bytes(out_image)


@lru_cache(maxsize=1)
def compile_assets(rc_index, rc_image, rcs_index, rcs_image, recipe):
    from tools.ii_launcher_graphics import NATIVE_ASSETS
    for name, raw in zip(('RC.IND', 'RC.IMG', 'RCS.IND', 'RCS.IMG'),
                         (rc_index, rc_image, rcs_index, rcs_image)):
        if type(raw) is not bytes or sha(raw) != NATIVE_ASSETS[name]:
            raise ValueError('Andere oorspronkelijke HUD-bron: ' + name)
    if sha(recipe) != RECIPE_SHA256:
        raise ValueError('Eigen HD-HUD-pixels veranderden.')
    data = json.loads(recipe)
    if (set(data) != {'schema', 'fonts', 'frames'} or data['schema'] != 1
            or set(data['fonts']) != set(FONT_NAMES)):
        raise ValueError('Onjuist HD-HUD-pixelrecept.')
    fonts = {name: encode_hd_font(resource(rcs_index, rcs_image, name),
              {int(code): base64.b64decode(raw, validate=True)
               for code, raw in data['fonts'][name].items()}) for name in FONT_NAMES}
    new_rcs_index, new_rcs_image = replace_resources(rcs_index, rcs_image, fonts)
    new_rc_index, new_rc_image = replace_frames(rc_index, rc_image, data['frames'])
    outputs = dict(zip(('RC.IND', 'RC.IMG', 'RCS.IND', 'RCS.IMG'),
                       (new_rc_index, new_rc_image, new_rcs_index, new_rcs_image)))
    if any(sha(raw) != OUTPUT_PINS[name] for name, raw in outputs.items()):
        raise ValueError('Opgebouwde HD-HUD wijkt af van de gecontroleerde versie.')
    return tuple(outputs.items())


def source_payload(root, resolution, hud):
    from tools.ii_portable_prepare import native_payload
    from tools import ii_hud_pair_trial, ii_hd_hud_trial, ii_hud_map_dialog_trial
    from tools.ii_launcher_graphics import SOURCES
    if resolution not in ('1080p', '4k') or hud not in ('hd', 'hd-map'):
        raise ValueError('Onbekende HD-HUD-combinatie.')
    payload = native_payload(root, resolution)
    display = {'1080p': (1920, 1080), '4k': (3840, 2160)}[resolution]
    binary, _ = ii_hud_pair_trial.build_trial(payload['game/DATA/SPEL-WIDE.DAT'], display)
    binary, _ = ii_hd_hud_trial.build_trial(binary, display)
    if hud == 'hd-map':
        binary, _ = ii_hud_map_dialog_trial.build_trial(binary, display)
    if sha(binary) != SOURCES[(resolution, hud)][2]:
        raise ValueError('Opgebouwde HD-HUD-code veranderde.')
    assets = compile_assets(*(payload['game/DATA/' + name] for name in
        ('RC.IND', 'RC.IMG', 'RCS.IND', 'RCS.IMG')), read_regular(root / RECIPE, 2 * 1024**2))
    payload.update({'game/DATA/' + name: raw for name, raw in assets})
    payload['game/DATA/SPEL-WIDE.DAT'] = binary
    return payload
