"""Pure-byte correction for the cleanup-only IV/Vakantieracer message pump.

The exact native cleanup calls a small message pump which polls the library
mouse when its queue is empty. That mouse can be uninitialised during cleanup,
causing Mouse.cpp(772) and a real fatal exit. Skip only that idle poll. Message
dispatch and WM_QUIT -> exit(0) remain byte-identical; runtime input and the
generic native error handler are untouched. No file/process/native API is used.
"""
from __future__ import annotations

import hashlib

SPECS = {
    'vakantieracer': {
        'size': 1126400,
        'sha256': '6c4a3a196fa8ee3d2a2bf7b437adbc9da5be3be0708eec15d0fce2d4eb99c939',
        'pump': 0x9AE80,
        'idle': 0x9AEC4,
        'before': bytes.fromhex('e807160000'),
        'mouse_va': 0x49C4D0,
        'contexts': (
            (0x9AE80, 0x50, '64b7d2c75c0802c57fcbc5e43332382e4d89eebf6fe78c3089e6f1b5e5a66af4'),
            (0x91510, 0x105, '81c7035085f861a27a2975b30f966ae50487c08789d95b40f856e9b65dfc5f7d'),
            (0x9C4D0, 0x21, '1ca5ad1e9126cc3b351e3abe2834e74f2e8c241a60fa4bdb73d8ec35bb788e0c'),
        ),
        'cleanup_only_callers': (0x491601, 0x49160B),
    },
    'a2racer4': {
        'size': 1875968,
        'sha256': 'ccd1b03472b25c8b7acacf4ba7e6abf60f657dfff2efd90f29e740b03f62286b',
        'pump': 0xCD660,
        'idle': 0xCD6A4,
        'before': bytes.fromhex('e837160000'),
        'mouse_va': 0x4CECE0,
        'contexts': (
            (0xCD660, 0x50, 'ab809a3564817eab79e1833733c642f2a00421765ac1e9302cbea66f9a3b4e0f'),
            (0xC4040, 0x105, '4df0e88168d6f4622c2ee6b476aac7048fd97d60b9600823d2e7cbe7e07a1d7a'),
            (0xCECE0, 0x21, '86c86bc2343f6aeb462e8ecacdc3cc2c2d5c37e7c5b16ddd45a44cbb01196a8b'),
        ),
        'cleanup_only_callers': (0x4C4131, 0x4C413B),
    },
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes, game: str) -> tuple[bytes, dict]:
    """Patch only the one idle call on an exact original NL race binary."""
    if type(game) is not str or game not in SPECS:
        raise ValueError('Onbekende game voor de afsluitcorrectie.')
    spec = SPECS[game]
    if type(raw) is not bytes or len(raw) != spec['size'] or _sha(raw) != spec['sha256']:
        raise ValueError('Onbekende oorspronkelijke raceversie voor de afsluitcorrectie.')
    for offset, size, pin in spec['contexts']:
        if _sha(raw[offset:offset + size]) != pin:
            raise ValueError('De oorspronkelijke afsluit-/muiscontext wijkt af.')
    offset, before = spec['idle'], spec['before']
    if raw[offset:offset + 5] != before:
        raise ValueError('De oorspronkelijke idle-muisaanroep wijkt af.')
    after = b'\x90' * 5
    output = raw[:offset] + after + raw[offset + 5:]
    return output, {
        'schema': 1,
        'game': game,
        'kind': 'cleanup-message-pump-without-idle-mouse',
        'source_sha256': spec['sha256'],
        'sha256': _sha(output),
        'runtime_verified': False,
        'cleanup_only_callers': list(spec['cleanup_only_callers']),
        'absolute_or_rva_pump_references': 0,
        'wm_quit_exit_zero_preserved': True,
        'normal_message_dispatch_preserved': True,
        'native_mouse_error_handler_preserved': True,
        'exit_codes_modified': False,
        'contexts': [{'offset': start, 'size': size, 'sha256': pin}
                     for start, size, pin in spec['contexts']],
        'patches': [{'offset': offset, 'before': before.hex(), 'after': after.hex()}],
    }
