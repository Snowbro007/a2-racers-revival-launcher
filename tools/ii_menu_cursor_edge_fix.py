"""Pinned software-hand edge experiment; transform immutable original bytes.

The old -1 saved-position sentinel overlaps a legitimately clipped cursor.
Reserve INT_MIN instead, beyond the accepted capture rectangle, and update
both initial positions and both comparisons together. Retain the hide guard.
No new sections, APIs, hooks, coordinate mapping or native cursor are added.
"""
from __future__ import annotations

import hashlib

from tools import ii_menu_cursor_background_fix as background

SOURCE_SIZE = background.SOURCE_SIZE
SOURCE_SHA256 = background.SOURCE_SHA256
PATCHED_SHA256 = '2234ca3ec15364fef32dce98147d4a540814c2fe0b8f17c9e436c34670a5217c'
INVALID_POSITION = -2147483648
GUARD_OFFSET = 0xFC99
GUARD_BEFORE = bytes.fromhex('8b0d387d430083c8ff3bc8741539053c7d4300740d')
# Same 21-byte region and original JE targets; EAX/ECX are caller-volatile.
GUARD_AFTER = bytes.fromhex('b8000000803905387d4300741539053c7d4300740d')
POSITION_OFFSET = 0x36738  # .data RVA 0x37D38, original section raw 0x25A00.
POSITION_BEFORE = b'\xff' * 8
POSITION_AFTER = bytes.fromhex('0000008000000080')
CAPTURE_BOUNDS_OFFSET = 0xF799
CAPTURE_BOUNDS = bytes.fromhex(
    '8b41088b490c03c603ca85c00f8c1f0200008b1d4c6b43003bf30f8f11020000'
    '85c90f8c090200008b3d506b43003bd70f8ffb0100008bee85ed7d0233f68b2dd8ff'
    '430085ed7d0233d23bcf7e028bcf3bc37e028bc33bf00f8dd30100003bd10f8dcb010000')
CAPTURE_SAVE_OFFSET = 0xF99E
CAPTURE_SAVE = bytes.fromhex(
    'a1387d43008b0d3c7d43008b15d4ff4300a3407d4300a1d8ff4300890d447d4300'
    '8915387d4300a33c7d43005f5e5d5b83c420c3')
CONTEXTS = ((CAPTURE_BOUNDS_OFFSET, CAPTURE_BOUNDS),
            (CAPTURE_SAVE_OFFSET, CAPTURE_SAVE),
            (GUARD_OFFSET, GUARD_BEFORE), (POSITION_OFFSET, POSITION_BEFORE))


def patch_menu_cursor_edges(source: bytes) -> tuple[bytes, list[dict]]:
    """Accept only the original version; retain the separate background guard."""
    if type(source) is not bytes or len(source) != SOURCE_SIZE:
        raise ValueError('Onjuiste MENU-versie/grootte voor de cursorrandproef.')
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Onbekende MENU-hash; cursorrandpatch geweigerd.')
    for offset, expected in CONTEXTS:
        if source[offset:offset+len(expected)] != expected:
            raise ValueError('MENU-cursorrandcontext wijkt af; patch geweigerd.')
    stage, guard_plan = background.patch_menu_cursor_background(source)
    data = bytearray(stage)
    data[GUARD_OFFSET:GUARD_OFFSET+len(GUARD_AFTER)] = GUARD_AFTER
    data[POSITION_OFFSET:POSITION_OFFSET+len(POSITION_AFTER)] = POSITION_AFTER
    result = bytes(data)
    if hashlib.sha256(result).hexdigest() != PATCHED_SHA256:
        raise ValueError('Onverwachte uitvoerhash van de cursorrandpatch.')
    return result, [guard_plan, {
        'name': 'ii-menu-software-cursor-edge-sentinel', 'path': 'DATA/MENU.DAT',
        'source_sha256': guard_plan['patched_sha256'],
        'original_source_sha256': SOURCE_SHA256, 'patched_sha256': PATCHED_SHA256,
        'size': SOURCE_SIZE, 'invalid_position': INVALID_POSITION,
        'edits': [{'offset': offset, 'before': before.hex(), 'after': after.hex()}
                  for offset, before, after in (
                      (GUARD_OFFSET, GUARD_BEFORE, GUARD_AFTER),
                      (POSITION_OFFSET, POSITION_BEFORE, POSITION_AFTER))],
        'software_cursor_preserved': True, 'mouse_mapping_changed': False,
        'runtime_tested': False, 'cursor_trails_fixed': False,
        'stale_valid_background_handled': False, 'restores_lost_surfaces': False,
    }]
