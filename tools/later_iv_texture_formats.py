"""Reject non-16-bit RGB formats in the exact NL IV texture enumerator."""
from __future__ import annotations

import hashlib
import struct

SOURCE_SIZE = 1875968
SOURCE_SHA256 = 'ccd1b03472b25c8b7acacf4ba7e6abf60f657dfff2efd90f29e740b03f62286b'
IMAGE_BASE = 0x400000
WARNING = 0xC2312
PATCH_OFFSET = WARNING + 19
CONTINUE = WARNING + 26
SUCCESS_EPILOGUE = 0xC2A27
LAST_UPDATE = SUCCESS_EPILOGUE - 3
LAST_UPDATE_BYTES = bytes.fromhex('896b5a')
LOGGER = 0xC3FA0
WARNING_STRING = 0x5B322C
BEFORE = bytes.fromhex('8b54243483c408')
WARNING_BYTES = bytes.fromhex('8b425483f810741250682c325b00e87b1c00008b54243483c408')
EPILOGUE_BYTES = bytes.fromhex('5f5e5db8010000005b83c418c20800')
CONTEXTS = (
    (0xC1E60, 0xBE0, '38bb4012d3e485208c48a9cac8f35764685ade106308701536881fc669ccf902'),
    (WARNING, 26, '12fa6ffe5f2c4d427cbb9fca6eccdda7749549b8daa91f599ea67385a67eef19'),
    (SUCCESS_EPILOGUE, 15, 'c45151e84c9830c8e6472cbc90cb6f5c384b17125d5fadcee4a1dff1295009b2'),
    (0xB9B7A, 0x18, 'cb6036a5f7cc4a399e35bc94f2fa083005d39d21fb2bd8efb3ba5611ddbb3c60'),
    (0xC00B0, 0x391, 'd7f9bd0d05c5fcbf7956bf70f1a5e1a19ca54f924522d601556c0e5ed2d72603'),
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> tuple[bytes, dict]:
    """Keep native warning/slot allocation, then continue enum without selection."""
    if type(raw) is not bytes or len(raw) != SOURCE_SIZE or _sha(raw) != SOURCE_SHA256:
        raise ValueError('Onbekende oorspronkelijke IV-textureformatversie.')
    for offset, size, digest in CONTEXTS:
        if _sha(raw[offset:offset + size]) != digest:
            raise ValueError('Andere IV-texturecallback, ABI of 16-bit-uploadcontext.')
    if raw[WARNING:CONTINUE] != WARNING_BYTES or raw[PATCH_OFFSET:CONTINUE] != BEFORE:
        raise ValueError('Andere IV-RGB-bitdieptewaarschuwing.')
    if raw[SUCCESS_EPILOGUE:SUCCESS_EPILOGUE + 15] != EPILOGUE_BYTES:
        raise ValueError('Andere IV-enumeratie-success-ABI.')
    if raw[LAST_UPDATE:SUCCESS_EPILOGUE] != LAST_UPDATE_BYTES:
        raise ValueError('Andere IV-poolstaartupdate.')
    # Original warning is cdecl(depth, formatstring): discard its two args
    # with two pops, then preserve the native last-record update before the
    # success epilogue returns 1 / ret 8. Allocation/linking already happened;
    # bypassing this tail assignment would corrupt the next enum link update.
    # The 16-bit short branch skips this whole warning path unchanged.
    after = b'\x58\x58\xe9' + struct.pack('<i', LAST_UPDATE - CONTINUE)
    output = raw[:PATCH_OFFSET] + after + raw[CONTINUE:]
    return output, {
        'schema': 1, 'game': 'a2racer4', 'kind': '16-bit-rgb-texture-format-filter',
        'source_sha256': SOURCE_SHA256, 'sha256': _sha(output),
        'runtime_verified': False, 'patch_bytes': len(after),
        'native_warning_preserved': True, 'native_pool_allocation_preserved': True,
        'paletted_paths': 'unchanged; do not enter RGB warning',
        'accepted_rgb_bits': 16,
        'rejected_rgb_bits': 'all non-16-bit RGB/alpha descriptors, before slot selection',
        'rejected_callback_return': 1, 'callback_argument_cleanup_bytes': 8,
        'native_last_update_preserved': True,
        'last_and_fallback_updates': 'native pool-tail update preserved; unsupported fallback selection bypassed',
        'original_contexts': [{'offset': o, 'size': n, 'sha256': h} for o, n, h in CONTEXTS],
        'patches': [{'offset': PATCH_OFFSET, 'before': BEFORE.hex(), 'after': after.hex()}],
    }
