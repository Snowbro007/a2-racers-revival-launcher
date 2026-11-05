"""Bound the exact NL IV native video-memory probe to its stack pointer array."""
from __future__ import annotations

import hashlib
import struct

SOURCE_SIZE = 1875968
SOURCE_SHA256 = 'ccd1b03472b25c8b7acacf4ba7e6abf60f657dfff2efd90f29e740b03f62286b'
IMAGE_BASE = 0x400000
PROBE = 0xBC0F0
LOOP = 0xBC108
TAIL_JUMP = 0xBC131
CLEANUP = 0xBC133
CAVE = 0xBC0E3
CAVE_SIZE = 13
STACK_BYTES = 0x1000
MAX_POINTERS = STACK_BYTES // 4
CONTEXTS = (
    (0xBC070, 0x90, '00825e3ad9d7c3bac7f31a35d5673fe6fd7af74c6bdf55a68b2f224055fd847e'),
    (PROBE, 0x70, '660c267c29846a168b8ebcf3385a3ed40b44a9a80c886d14f25e31c9956d4d11'),
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> tuple[bytes, dict]:
    if type(raw) is not bytes or len(raw) != SOURCE_SIZE or _sha(raw) != SOURCE_SHA256:
        raise ValueError('Onbekende oorspronkelijke IV-videogeheugenprobe.')
    for offset, size, digest in CONTEXTS:
        if _sha(raw[offset:offset + size]) != digest:
            raise ValueError('Andere IV-oppervlakallocatie, stackarray of vrijgavecontext.')
    if raw[CAVE:CAVE+CAVE_SIZE] != b'\x90'*CAVE_SIZE or raw[TAIL_JUMP:TAIL_JUMP+2] != bytes.fromhex('ebd5'):
        raise ValueError('Andere IV-probe-loop of padding.')
    # Execute after the native successful-handle write, counter/accounting and
    # pointer increment. At capacity, use the native cleanup for every saved
    # handle. Never attempt a 1025th CreateSurface/write outside the array.
    code = b'\x81\xff' + struct.pack('<I', MAX_POINTERS)
    code += bytes((0x73, CLEANUP-(CAVE+8)))
    code += b'\xe9' + struct.pack('<i', LOOP-(CAVE+CAVE_SIZE))
    tail = bytes((0xEB, (CAVE-(TAIL_JUMP+2)) & 0xFF))
    assert len(code) == CAVE_SIZE
    out = bytearray(raw)
    out[CAVE:CAVE+CAVE_SIZE] = code
    out[TAIL_JUMP:TAIL_JUMP+2] = tail
    output = bytes(out)
    return output, {
        'schema':1, 'game':'a2racer4', 'kind':'bounded-native-vram-probe',
        'source_sha256':SOURCE_SHA256, 'sha256':_sha(output),
        'runtime_verified':False, 'stack_array_bytes':STACK_BYTES,
        'maximum_successful_allocations':MAX_POINTERS,
        'create_surface':'original native 256x256 local-video-memory helper',
        'release':'original cleanup visits every successful saved handle',
        'accounting':'original native bpp-based accounting, capped to saved handles',
        'contexts':[{'offset':o,'size':n,'sha256':h} for o,n,h in CONTEXTS],
        'patches':[
            {'offset':CAVE,'before':raw[CAVE:CAVE+CAVE_SIZE].hex(),'after':code.hex()},
            {'offset':TAIL_JUMP,'before':raw[TAIL_JUMP:TAIL_JUMP+2].hex(),'after':tail.hex()},
        ],
    }
