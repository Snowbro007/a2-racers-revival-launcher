"""Pinned software-cursor hide guard; immutable bytes only, no game execution.

The original hide path calls the low-level background restore directly. Route
only that call through the existing native wrapper, which skips copying when
either saved coordinate is the -1 sentinel. This retains the original hand,
capture, drawing, coordinates and visibility handling. A stale background at
valid coordinates is outside this guard; no runtime fix is claimed.
"""
from __future__ import annotations

import hashlib


SOURCE_SIZE = 253440
SOURCE_SHA256 = "ca55597bf957b17e893c1a887b8965e94c62ab59298709c66c26233369fdbe83"
PATCHED_SHA256 = "6c6042bfa88450c3343d6666bf67d1403f1b8cc7a4e595a96a8a158e01b2faf2"
PATCH_OFFSET = 0xF47F
PATCH_VA = 0x41007F
ORIGINAL_TARGET_VA = 0x4105E0
GUARDED_TARGET_VA = 0x410830
BEFORE = bytes.fromhex("e85c050000")
AFTER = bytes.fromhex("e8ac070000")

# Complete hide function, including PUSH 0, caller cleanup and the unchanged
# ShowCursor(FALSE)/visible-flag update after the redirected cdecl call.
HIDE_OFFSET = 0xF460
HIDE_BYTES = bytes.fromhex(
    "a1e8ff430085c07430a1e0ff430085c07427a15c7d430048740d48750a"
    "6a00e85c05000083c4046a00ff152c144500c705e8ff430000000000c3")
# Complete existing restore wrapper through RET. It retains diagnostics for
# uninitialized/type/animation state; only a saved x or y of exactly -1 skips.
WRAPPER_OFFSET = 0xFC30
WRAPPER_BYTES = bytes.fromhex(
    "a1dcff430085c0751768ad02000068947d430068a8824300e803ceffff83c40c"
    "833d5c7d430001751768b202000068947d43006864824300e8e3cdffff83c40c"
    "833d5c7d4300027520a1e4ff430085c0751768b702000068947d43006830824300"
    "e8bacdffff83c40c8b0d387d430083c8ff3bc8741539053c7d4300740d"
    "8b44240450e828fdffff83c404c3")
# WinMain still requests software type 2 and animation 2/frame 0; no hardware
# cursor selection, skipped animation, new worker or wrapper hook is introduced.
INITIALIZER_OFFSET = 0x8EDC
INITIALIZER_BYTES = bytes.fromhex("6a02e80d64000083c4046a006a006a02e8af66000083c40c")
# Existing low-level restore clamps negative coordinates toward zero. The new
# sentinel check precedes this route rather than changing clipping semantics.
CLAMP_OFFSET = 0xFA4E
CLAMP_BYTES = bytes.fromhex("85d27d0233d285f67d0233f63bcf7e028bcf3bc37e028bc33bd00f8db5010000")
CONTEXTS = ((HIDE_OFFSET, HIDE_BYTES), (WRAPPER_OFFSET, WRAPPER_BYTES),
            (INITIALIZER_OFFSET, INITIALIZER_BYTES), (CLAMP_OFFSET, CLAMP_BYTES))


def patch_menu_cursor_background(source: bytes) -> tuple[bytes, dict]:
    """Return the single guarded-call change and evidence; never write a file."""
    if type(source) is not bytes or len(source) != SOURCE_SIZE:
        raise ValueError("Onjuiste MENU-versie/grootte voor de cursorondergrondproef.")
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Onbekende MENU-hash; cursorondergrondpatch geweigerd.")
    if source[PATCH_OFFSET:PATCH_OFFSET + len(BEFORE)] != BEFORE:
        raise ValueError("MENU-herstelcall wijkt af; cursorondergrondpatch geweigerd.")
    for offset, expected in CONTEXTS:
        if source[offset:offset + len(expected)] != expected:
            raise ValueError("MENU-cursorcontext wijkt af; cursorondergrondpatch geweigerd.")
    patched = source[:PATCH_OFFSET] + AFTER + source[PATCH_OFFSET + len(BEFORE):]
    if hashlib.sha256(patched).hexdigest() != PATCHED_SHA256:
        raise ValueError("Onverwachte uitvoerhash van de cursorondergrondpatch.")
    return patched, {
        "name": "ii-menu-software-cursor-background-guard",
        "path": "DATA/MENU.DAT", "source_sha256": SOURCE_SHA256,
        "patched_sha256": PATCHED_SHA256, "size": SOURCE_SIZE,
        "offset": PATCH_OFFSET, "va": PATCH_VA,
        "before": BEFORE.hex(), "after": AFTER.hex(),
        "original_target_va": ORIGINAL_TARGET_VA, "guarded_target_va": GUARDED_TARGET_VA,
        "scope": "Hide-only restore through existing native -1-coordinate guard; software hand retained.",
        "runtime_tested": False, "black_corner_fixed": False,
        "software_cursor_preserved": True, "coordinates_changed": False,
        "restores_lost_surfaces": False, "stale_valid_background_handled": False,
    }
