"""Pure-byte, version-bound A2 Racer IV mouse polling correction.

No file, process or native APIs are called. Only known temporary loss of the
existing DirectInput mouse may cause one reacquire/read attempt per poll.
"""
from __future__ import annotations

import hashlib
import struct

SOURCE_SIZE = 1875968
SOURCE_SHA256 = 'ccd1b03472b25c8b7acacf4ba7e6abf60f657dfff2efd90f29e740b03f62286b'
IMAGE_BASE = 0x400000
CONTEXT_OFFSET = 0xEE570
CONTEXT_SIZE = 307
CONTEXT_SHA256 = 'a5505f075d8011b53472c406803268f19d7d0675d57c8be7cb514084a510842c'
START = 0xEE591
ACQUIRE = START + 0x1A
GENERAL = START + 0x9F
END = START + 0xFB
CAVE = START + 0x47
CAVE_SIZE = 88
STATE_OFFSET = 0xE0
STATE_BYTES = 16
INPUT_LOST = 0x8007001E
NOT_ACQUIRED = 0x8007000C
CAVE_BEFORE = bytes.fromhex(
    '688f00000068e8875b008d54241068e4775b0052e89ff9faff68c4875b00508d442430'
    'c78424a00000000000000050e8a4b0f8ff83c41c508d4c244cc684248c00000001'
    'e89ff4ffff8d4c244868d072580051e890ad0600')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _jump(at: int, target: int) -> bytes:
    return b'\xe9' + struct.pack('<i', target - (at + 5))


def _jcc(opcode: int, at: int, target: int) -> bytes:
    return bytes((0x0F, opcode)) + struct.pack('<i', target - (at + 6))


def patch(raw: bytes) -> tuple[bytes, dict]:
    """Return an own byte copy and explicit ranges on the exact original NL race."""
    if type(raw) is not bytes or len(raw) != SOURCE_SIZE or _sha(raw) != SOURCE_SHA256:
        raise ValueError('Onbekende oorspronkelijke A2 Racer IV-raceversie.')
    context = raw[CONTEXT_OFFSET:CONTEXT_OFFSET + CONTEXT_SIZE]
    if _sha(context) != CONTEXT_SHA256:
        raise ValueError('De oorspronkelijke muispollcontext wijkt af.')

    # EAX is the native device pointer. Preserve it while zeroing precisely
    # DIMOUSESTATE (three signed LONG deltas + four button bytes).
    initial = bytes.fromhex('5033c0b904000000f3ab588dbee00000008b08')
    initial += _jump(CAVE + len(initial), START + 8)
    first_at = CAVE + len(initial)
    first = b'\x3d' + struct.pack('<I', INPUT_LOST)
    first += _jcc(0x84, first_at + len(first), ACQUIRE)
    first += b'\x3d' + struct.pack('<I', NOT_ACQUIRED)
    first += _jcc(0x84, first_at + len(first), ACQUIRE)
    first += _jump(first_at + len(first), GENERAL)

    retry_at = first_at + len(first)
    clear_at = retry_at + 19
    retry = b'\x3d' + struct.pack('<I', INPUT_LOST)
    retry += bytes((0x74, clear_at - (retry_at + len(retry) + 2)))
    retry += b'\x3d' + struct.pack('<I', NOT_ACQUIRED)
    retry += bytes((0x74, clear_at - (retry_at + len(retry) + 2)))
    retry += _jump(retry_at + len(retry), GENERAL)
    # Preserve the HRESULT and the original early-return policy for every
    # failed Acquire. Clearing here also discards any partial failed read.
    retry += bytes.fromhex('5033c0b904000000f3ab58')
    retry += _jump(retry_at + len(retry), END)
    code = initial + first + retry
    if len(code) > CAVE_SIZE:
        raise ValueError('Muisherstel overschrijdt de bestaande fouttak.')
    changes = (
        (START, bytes.fromhex('8b088dbee0000000'),
         bytes.fromhex('8dbee0000000eb') + bytes((CAVE - (START + 8),))),
        (START + 0x0F, bytes.fromhex('3d1e0007800f8585000000'),
         _jump(START + 0x0F, first_at) + b'\x90' * 6),
        (START + 0x29, bytes.fromhex('0f85cc000000'),
         _jcc(0x85, START + 0x29, clear_at)),
        (START + 0x3F, bytes.fromhex('85c00f84b4000000'),
         _jump(START + 0x3F, retry_at) + b'\x90' * 3),
        (CAVE, CAVE_BEFORE, code + b'\x90' * (CAVE_SIZE - len(code))),
    )
    result = bytearray(raw)
    covered: set[int] = set()
    for offset, before, after in changes:
        region = set(range(offset, offset + len(before)))
        if (len(before) != len(after) or raw[offset:offset + len(before)] != before
                or covered.intersection(region)):
            raise ValueError('Andere of overlappende muispatchcontext.')
        covered.update(region)
        result[offset:offset + len(before)] = after
    output = bytes(result)
    return output, {
        'schema': 1, 'game': 'a2racer4', 'kind': 'mouse-input-reacquire',
        'source_sha256': SOURCE_SHA256, 'sha256': _sha(output),
        'runtime_verified': False, 'device_state_bytes': STATE_BYTES,
        'state_member_offset': STATE_OFFSET, 'max_reacquire_per_poll': 1,
        'temporary_hresult': [INPUT_LOST, NOT_ACQUIRED],
        'unknown_read_errors': 'original general exception path, CMouseDevice.cpp151',
        'acquire_failure': 'original early return, now with neutral state and preserved HRESULT',
        'original_context': {'offset': CONTEXT_OFFSET, 'size': CONTEXT_SIZE,
                             'sha256': CONTEXT_SHA256},
        'helper_bytes': len(code),
        'labels': {'start': START, 'initial': CAVE, 'first_classifier': first_at,
                   'acquire': ACQUIRE, 'retry_classifier': retry_at,
                   'clear': clear_at, 'general': GENERAL, 'end': END},
        'patches': [{'offset': offset, 'before': before.hex(), 'after': after.hex()}
                    for offset, before, after in changes],
    }
