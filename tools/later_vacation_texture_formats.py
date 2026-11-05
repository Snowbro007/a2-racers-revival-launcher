"""Exact NL Vakantieracer: reject non-16-bit RGB/alpha enum entries locally."""
from __future__ import annotations

import hashlib
import struct

SOURCE_SIZE = 1126400
SOURCE_SHA256 = '6c4a3a196fa8ee3d2a2bf7b437adbc9da5be3be0708eec15d0fce2d4eb99c939'
IMAGE_BASE = 0x400000
GUARD = 0x8F4F2
PATCH_OFFSET = GUARD + 19
CONTINUE = 0x8F50C
EPILOGUE = 0x8FC07
LAST_UPDATE = EPILOGUE - 3
LAST_UPDATE_BEFORE = bytes.fromhex('896b5a')
LOGGER_VA = 0x491470
BEFORE = bytes.fromhex('8b54243483c408')
GUARD_BEFORE = bytes.fromhex('8b425483f81074125068f0a35000e86b1f00008b54243483c408')
EPILOGUE_BEFORE = bytes.fromhex('5f5e5db8010000005b83c418c20800')
CONTEXTS = (
    (0x8F040, 3030, '4dfaecef2c669beee32a7cee1e799a4764cc4772376fff376f93a6738a53e9fa'),
    (GUARD, 26, '3983aa7d2f2a25d08c032a0234a0e1ec4b27acc8b24a1cde8ac1704c32eca9c6'),
    (EPILOGUE, 15, 'c45151e84c9830c8e6472cbc90cb6f5c384b17125d5fadcee4a1dff1295009b2'),
    (0x8DC21, 125, '7643a11faf92d8b5778146d9b8032a21950811cd4094e81b6b0905d88ebccd09'),
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> tuple[bytes, dict]:
    if type(raw) is not bytes or len(raw) != SOURCE_SIZE or _sha(raw) != SOURCE_SHA256:
        raise ValueError('Onbekende oorspronkelijke Vakantieracer-textureversie.')
    for offset, size, digest in CONTEXTS:
        if _sha(raw[offset:offset + size]) != digest:
            raise ValueError('Andere Vakantieracer-enum-, return- of 16-bit-schrijfcontext.')
    if raw[GUARD:GUARD + 26] != GUARD_BEFORE or raw[EPILOGUE:EPILOGUE + 15] != EPILOGUE_BEFORE:
        raise ValueError('Andere Vakantieracer texture-enumcontrole/ABI.')
    if raw[LAST_UPDATE:EPILOGUE] != LAST_UPDATE_BEFORE:
        raise ValueError('Andere Vakantieracer-poolstaartupdate.')
    # Preserve the native bpp compare, 16-bit jump, warning and logger call.
    # Non-16-bit: discard its two cdecl log arguments, then use the original
    # success epilogue (EAX=1, nonvolatile restores, ret8). No pool rollback,
    # index renumbering or descriptor conversion. Allocation/linking already
    # happened: preserve native last-record assignment before the return.
    # Rejected RGB/alpha descriptors still cannot replace selected/fallback.
    after = b'\x58\x58\xE9' + struct.pack('<i', LAST_UPDATE - (PATCH_OFFSET + 7))
    output = raw[:PATCH_OFFSET] + after + raw[PATCH_OFFSET + 7:]
    return output, {
        'schema': 1, 'game': 'vakantieracer', 'kind': 'texture-format-16bit-filter',
        'source_sha256': SOURCE_SHA256, 'sha256': _sha(output),
        'runtime_verified': False, 'native_16bit_path_preserved': True,
        'palette_path_preserved': True, 'native_warning_preserved': True,
        'unsupported_format': 'native warning, skip RGB/alpha selection, continue enumeration',
        'pool_allocation': 'unchanged; no slot release, counter decrement or renumbering',
        'native_last_update_preserved': True,
        'continue_result': 1, 'return_argument_bytes': 8,
        'contexts': [{'offset': o, 'size': n, 'sha256': h} for o, n, h in CONTEXTS],
        'patches': [{'offset': PATCH_OFFSET, 'before': BEFORE.hex(), 'after': after.hex()}],
    }
