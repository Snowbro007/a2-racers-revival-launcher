"""Increase the pinned 4K accelerated minimap; never run or mutate a game."""
import hashlib
import struct

from tools import ii_hud_map_dialog_trial as hud
from tools import ii_distance_trial as distance
from tools import ii_sky_off_trial as horizon
from tools import ii_sky_layer_trial as sky

SOURCE_SHA256 = '25262d7b2ecffd7aad57533aa772957d474527bea6c8534cf2f3d9813ee9a532'
OLD_SCALE = 3.0
NEW_SCALE = 3.5


def patch(source: bytes) -> tuple[bytes, dict]:
    if type(source) is not bytes:
        raise ValueError('Onbekende 4K-kaartbinary.')
    normalized = bytearray(source)
    # Only the existing, independently checked launcher world choices may vary.
    variants = [(distance.PATCH_OFFSET, b'\x48', b'\x90'),
                (distance.LIMIT_OFFSET + 2, b'\x32', b'\x3c'),
                (distance.LIMIT_OFFSET + 11, b'\x32', b'\x3c'),
                *horizon.PATCHES,
                *((offset, before, b'\x90' * len(before))
                  for offset, before in (sky.CLOUD_CALL, sky.BITMAP_CALL))]
    for offset, before, after in variants:
        if source[offset:offset + len(before)] not in (before, after):
            raise ValueError('Andere wereldopties in de 4K-kaartbinary.')
        normalized[offset:offset + len(before)] = before
    if hashlib.sha256(normalized).hexdigest() != SOURCE_SHA256:
        raise ValueError('Onbekende 4K-kaartbinary.')
    va, offset, original = hud.RADAR_HOOK
    if source[offset] != 0xe9:
        raise ValueError('De vergrote kaarthelper ontbreekt.')
    target = va + 5 + struct.unpack_from('<i', source, offset + 1)[0]
    stub = hud.build_radar_stub(target, (3840, 2160))
    location = hud.wide.SECTION_RAW_OFFSET + target - hud.wide.IMAGE_BASE - hud.wide.SECTION_RVA
    if location < 0 or source[location:location + len(stub)] != stub:
        raise ValueError('Andere 4K-kaarthelper.')
    factor_offset = location + len(stub) - 4
    if source[factor_offset:factor_offset + 4] != struct.pack('<f', OLD_SCALE):
        raise ValueError('Andere kaartgrootte; niet dubbel vergroten.')
    result = bytearray(source)
    result[factor_offset:factor_offset + 4] = struct.pack('<f', NEW_SCALE)
    output = bytes(result)
    return output, {'source_sha256': hashlib.sha256(source).hexdigest(),
                    'sha256': hashlib.sha256(output).hexdigest(),
                    'factor_offset': factor_offset, 'scale_before': OLD_SCALE,
                    'scale_after': NEW_SCALE, 'native_game_executed': False,
                    'runtime_tested': False}
