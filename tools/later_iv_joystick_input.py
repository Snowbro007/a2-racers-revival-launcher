"""Pure-byte bounded joystick reacquire for the exact NL A2 Racer IV race."""
from __future__ import annotations

import hashlib
import struct

SOURCE_SIZE = 1875968
SOURCE_SHA256 = 'ccd1b03472b25c8b7acacf4ba7e6abf60f657dfff2efd90f29e740b03f62286b'
IMAGE_BASE = 0x400000
BODY = 0xEF52C
GENERAL = 0xEF5DD
END = 0xEF639
BODY_SIZE = GENERAL - BODY
STATE_OFFSET = 0xE0
STATE_BYTES = 80
RANGES_OFFSET = 0x130
INPUT_LOST, NOT_ACQUIRED = 0x8007001E, 0x8007000C
# Independent IV contexts: whole poll, full normalizer, full range getter.
CONTEXTS = (
    (0xEF510, 0x140, '5b8cd952652e3defd6ed896262327c4335555e045627b8c93929935108a932cc'),
    (0xEF650, 0x90, '4d4a7e1f741cd2e480dfb135ff9cdbd12e33a34b7f57ac7afc1444071e97d525'),
    (0xF06C0, 0xD0, 'eaf53674db341d6394af1ad73aa89b95e0d122bc3f2fa7448adfef7ad07739e8'),
)
PREFIX = bytes.fromhex('e88f2800008b0850ff51648bcee8f22700008b108dbee0000000576a5050ff5224')


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
        raise ValueError('Onbekende oorspronkelijke A2 Racer IV-joystickversie.')
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
    code.near(0xE8, 0xF1D30)
    code.emit(bytes.fromhex('8b0850ff511c85c0'))
    code.short(0x75, 'neutral')
    code.emit(bytes.fromhex('8bce'))
    code.near(0xE8, 0xF1D30)
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
        'schema': 1, 'game': 'a2racer4', 'kind': 'joystick-input-reacquire',
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
