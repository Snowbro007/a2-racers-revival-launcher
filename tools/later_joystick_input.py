"""Pure-byte bounded joystick reacquire for the exact NL Vakantieracer race."""
from __future__ import annotations

import hashlib
import struct

SOURCE_SIZE = 1126400
SOURCE_SHA256 = '6c4a3a196fa8ee3d2a2bf7b437adbc9da5be3be0708eec15d0fce2d4eb99c939'
IMAGE_BASE = 0x400000
BODY = 0xB63EC
GENERAL = 0xB649D
END = 0xB64F9
BODY_SIZE = GENERAL - BODY
STATE_OFFSET = 0xE0
STATE_BYTES = 80
RANGES_OFFSET = 0x130
INPUT_LOST, NOT_ACQUIRED = 0x8007001E, 0x8007000C
CONTEXTS = (
    (0xB63D0, 0x140, '187818a6d5a61b912f82d4ad4bbbbc492047fb89881a4d2842f08b6cc8687866'),
    (0xB6510, 0x90, '11a921eefb1c8fe5b8df9f3a12964e0edbd2c117deaa6a480133c828cbcd61b3'),
    (0xB7650, 0x90, 'bc534f076a4a645dd78592268cc94eee29f5ecdab5df1efa0001dc519f5b9ecb'),
)
PREFIX = bytes.fromhex('e8df2800008b0850ff51648bcee8422800008b108dbee0000000576a5050ff5224')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _Code:
    def __init__(self):
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    @property
    def pc(self):
        return BODY + len(self.data)

    def emit(self, raw):
        self.data.extend(raw)

    def label(self, name):
        self.labels[name] = self.pc

    def short(self, opcode, target):
        self.emit(bytes((opcode, 0)))
        self.fixups.append((len(self.data) - 1, 1, target))

    def near(self, opcode, target):
        self.emit(bytes((opcode,)) + bytes(4))
        self.fixups.append((len(self.data) - 4, 4, target))

    def finish(self):
        for offset, size, target in self.fixups:
            target = self.labels[target] if isinstance(target, str) else target
            displacement = target - (BODY + offset + size)
            if size == 1 and not -128 <= displacement <= 127:
                raise ValueError('Joystick-shortbranch overschrijdt het gepinde blok.')
            struct.pack_into('<b' if size == 1 else '<i', self.data, offset, displacement)
        return bytes(self.data)


def patch(raw: bytes) -> tuple[bytes, dict]:
    """Patch one original code range, retaining native SEH and fatal read path."""
    if type(raw) is not bytes or len(raw) != SOURCE_SIZE or _sha(raw) != SOURCE_SHA256:
        raise ValueError('Onbekende oorspronkelijke Vakantieracer-joystickversie.')
    for offset, size, digest in CONTEXTS:
        if _sha(raw[offset:offset + size]) != digest:
            raise ValueError('Andere joystickpoll-, asnormalisatie- of rangecontext.')
    if raw[BODY:BODY + len(PREFIX)] != PREFIX:
        raise ValueError('Andere native joystick Poll/GetDeviceState-prefix.')

    code = _Code()
    # Preserve native device2 Poll and first 80-byte GetDeviceState verbatim.
    # Successful reads keep every actual axis, POV and button untouched.
    code.emit(PREFIX)
    code.label('first_classifier')
    for hr in (INPUT_LOST, NOT_ACQUIRED):
        code.emit(b'\x3d' + struct.pack('<I', hr))
        code.short(0x74, 'acquire')
    code.near(0xE9, GENERAL)
    code.label('acquire')
    code.emit(bytes.fromhex('8bce'))
    code.near(0xE8, 0xB8C40)
    code.emit(bytes.fromhex('8b0850ff511c85c0'))
    code.short(0x75, 'neutral')
    code.emit(bytes.fromhex('8bce'))
    code.near(0xE8, 0xB8C40)
    code.emit(bytes.fromhex('8b10576a5050ff5224'))
    code.label('retry_classifier')
    for hr in (INPUT_LOST, NOT_ACQUIRED):
        code.emit(b'\x3d' + struct.pack('<I', hr))
        code.short(0x74, 'neutral')
    code.near(0xE9, GENERAL)
    code.label('neutral')
    # Preserve HRESULT and EBX; clear exactly DIJOYSTATE's 80 bytes.
    code.emit(bytes.fromhex('505333c0b9140000008dbee0000000f3ab'))
    # The pinned native normalizer uses raw / trunc((max-min)/2), then
    # subtracts one (Y reversed). Reproduce precisely that cached center;
    # literal zero or an assumed fixed 32767 can generate full steering.
    code.emit(bytes.fromhex('8dbee00000008d9e30010000b903000000'))
    code.label('center_axes')
    code.emit(bytes.fromhex('8b43042b03992bc2d1f8ab83c308'))
    code.short(0xE2, 'center_axes')
    # Rotations/sliders are not consumed by the pinned class; leave zero.
    # All four POVs must be centered (FFFFFFFF), and 32 buttons released.
    code.emit(bytes.fromhex('b8ffffffff83c714b904000000f3ab5b58'))
    code.near(0xE9, END)
    helper = code.finish()
    if len(helper) > BODY_SIZE:
        raise ValueError('Joystickherstel overschrijdt de gepinde native pollbody.')
    before = raw[BODY:GENERAL]
    after = helper + b'\x90' * (BODY_SIZE - len(helper))
    output = raw[:BODY] + after + raw[GENERAL:]
    return output, {
        'schema': 1, 'game': 'vakantieracer', 'kind': 'joystick-input-reacquire',
        'source_sha256': SOURCE_SHA256, 'sha256': _sha(output),
        'runtime_verified': False, 'device_state_bytes': STATE_BYTES,
        'state_member_offset': STATE_OFFSET, 'range_member_offset': RANGES_OFFSET,
        'max_reacquire_per_poll': 1, 'native_poll_preserved': True,
        'unknown_read_errors': 'original general exception path, CJoystickDevice.cpp157',
        'acquire_failure': 'original early return with typed neutral state and preserved HRESULT',
        'neutral_axes': 'native cached half-range, signed division truncated toward zero',
        'neutral_pov': 0xFFFFFFFF, 'neutral_buttons': 0,
        'rotation_sliders': 'zero; no native consumer in pinned joystick class',
        'helper_bytes': len(helper), 'labels': dict(code.labels),
        'original_contexts': [{'offset': o, 'size': n, 'sha256': h} for o, n, h in CONTEXTS],
        'patches': [{'offset': BODY, 'before': before.hex(), 'after': after.hex()}],
    }
