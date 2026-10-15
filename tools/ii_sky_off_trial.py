"""Version-pinned, immutable 60-chunk experiment without accelerated sky."""
import hashlib

SOURCE_SHA256 = 'fce6ccd53db05e738765be0e021e4c98bd66db139d36646491c58511ab87b3b6'
# Raw offsets for this exact PE only. The cave is unreachable alignment padding
# following a RET; short branches return before the original PUSH ESI.
PATCHES = (
    (0x245FC, bytes.fromhex('e8cf3effff'), b'\x90' * 5),
    (0x244B6, bytes.fromhex('6a00e8b37a0200'), bytes.fromhex('6a01e8b37a0200')),
    (0x4BF64, b'\x90' * 6, bytes.fromhex('8b5c2408eb0e')),
    (0x4BF76, bytes.fromhex('33db'), bytes.fromhex('ebec')),
)
CONTEXT_OFFSET = 0x4BF63
CONTEXT = bytes.fromhex('c3') + b'\x90' * 12 + bytes.fromhex(
    'a174ab4e005333db5685c0577410a13ca84e0085c074078b5c241083cb02')


def build_trial(source: bytes) -> tuple[bytes, dict]:
    if type(source) is not bytes or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Onbekende vaste-60-basis; horizonproef geweigerd.')
    if source[CONTEXT_OFFSET:CONTEXT_OFFSET + len(CONTEXT)] != CONTEXT:
        raise ValueError('Onbekende clearcode of padding; horizonproef geweigerd.')
    output = bytearray(source)
    for offset, original, replacement in PATCHES:
        if source[offset:offset + len(original)] != original:
            raise ValueError('Onbekende teken-/clearroute; horizonproef geweigerd.')
        output[offset:offset + len(original)] = replacement
    result = bytes(output)
    return result, {
        'source_sha256': SOURCE_SHA256,
        'sha256': hashlib.sha256(result).hexdigest(),
        'accelerated_sky_draw_disabled': True,
        'frame_clear_target_requested': True,
        'clear_helper_preserves_caller_flags_without_depth_buffer': True,
        'visiblechunks': 60,
        'far_plane_unchanged': True,
        'native_game_executed': False,
        'runtime_tested': False,
    }
