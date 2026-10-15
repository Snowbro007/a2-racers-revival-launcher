"""Static, version-pinned exclusion of remaining sky draw calls in trial 47."""
import hashlib

SOURCE_SHA256 = 'cea74cf07d38bacaf213d3b1d9559b31b7f15a773525faab6f3e782989eab560'
CLOUD_CALL = (0x24606, bytes.fromhex('e8c5b1ffff'))  # VA 425206 -> 4203D0
BITMAP_CALL = (0x244B1, bytes.fromhex('e89a97ffff'))  # VA 4250B1 -> 41E850


def build_trial(source: bytes, *, skip_bitmap: bool = False) -> tuple[bytes, dict]:
    if type(source) is not bytes or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Onbekende horizon-uit-basis; luchtproef geweigerd.')
    if type(skip_bitmap) is not bool:
        raise ValueError('Onbekende luchtproef.')
    for offset, original in (CLOUD_CALL, BITMAP_CALL):
        if source[offset:offset + 5] != original:
            raise ValueError('Andere luchttekenroute; proef geweigerd.')
    output = bytearray(source)
    calls = (CLOUD_CALL, BITMAP_CALL) if skip_bitmap else (CLOUD_CALL,)
    for offset, _ in calls:
        output[offset:offset + 5] = b'\x90' * 5
    result = bytes(output)
    return result, {'source_sha256': SOURCE_SHA256,
                    'sha256': hashlib.sha256(result).hexdigest(),
                    'cloud_draw_call_disabled': True,
                    'bitmap_sky_draw_call_disabled': skip_bitmap,
                    'changed_raw_offsets': [offset for offset, _ in calls],
                    'native_game_executed': False, 'runtime_tested': False}
