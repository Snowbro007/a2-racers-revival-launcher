"""Opt-in, version-pinned A2-I selection-window experiment for trial copies.

This changes two data constants that size the camera-directed object/terrain
selection window. It does not set a D3D far plane or promise a physical distance.
Planning is read-only; game_fixes.apply_fixes enforces an independent trial copy.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

NAME = "A2SPEL.DAT"
EXPECTED_SHA256 = "069d39e815fc631ef433550459e8105042cf740dfc311e4f9285d4cca148e726"
EXPECTED_PATCHED_SHA256_BY_PROFILE = {
    "extended-8": "d7bf38d10cfc2a79bf470be1290c51575af9adb5225365f1f5f81db7824117f8",
    "extended-10": "2b6a33bf40eb482d71d9d48186e3547ef0c59ed3854feeb94a11eb5dbb9633e2",
    "extended-20": "c25d2cc6b01bc654de3abf00716ea4df073d8c03c6ab0e74490f2247f7f0cf9d",
}
# Keep the established eight-cell pin available to older callers.
EXPECTED_PATCHED_SHA256 = EXPECTED_PATCHED_SHA256_BY_PROFILE["extended-8"]
EXPECTED_SIZE = 395264
PROFILE_CELLS = {"extended-8": 8, "extended-10": 10, "extended-20": 20}
PROFILES = ("original", *PROFILE_CELLS)
# VA 0x4596D8/DC in the pinned binary; direct users are 0x4262CA/DD and
# 0x426C87/94. Each DWORD is a number of selection cells, not metres.
WINDOW_FIELDS = (("width", 0x582D8), ("depth", 0x582DC))
ORIGINAL_CELLS = 6


def checked_patch(data: bytes, profile: str = "extended-8") -> bytes:
    """Return a fresh patched byte string, refusing unknown versions and no-ops."""
    if profile not in PROFILE_CELLS:
        raise ValueError("Zichtvensterpatch vereist een opt-in-profiel extended-8, extended-10 of extended-20.")
    if (len(data) != EXPECTED_SIZE or
            hashlib.sha256(data).hexdigest() != EXPECTED_SHA256):
        raise ValueError(f"Onbekende binaryversie voor zichtvensterproef: {NAME}.")
    before = struct.pack("<I", ORIGINAL_CELLS)
    after = struct.pack("<I", PROFILE_CELLS[profile])
    for axis, offset in WINDOW_FIELDS:
        if offset + 4 > len(data) or data[offset:offset + 4] != before:
            raise ValueError(f"Afwijkend {axis}-veld voor zichtvensterproef: {NAME}.")
    result = bytearray(data)
    for axis, offset in WINDOW_FIELDS:
        result[offset:offset + 4] = after
    return bytes(result)


def plan_fixes(source: Path, profile: str = "original") -> list[dict]:
    """Plan a bounded experimental profile; the default requires no binary read."""
    if profile not in PROFILES:
        raise ValueError("Onbekend profiel voor zichtvensterproef.")
    if profile == "original":
        return []
    path = source / NAME
    if not path.is_file() or path.stat().st_size != EXPECTED_SIZE:
        raise ValueError(f"Binary voor zichtvensterproef ontbreekt of heeft afwijkende grootte: {NAME}.")
    data = path.read_bytes()
    fixed = checked_patch(data, profile)
    cells = PROFILE_CELLS[profile]
    return [{
        "path": NAME,
        "purpose": "render-selection-window-experimental",
        "profile": profile,
        "runtime_verified": False,
        "source_path": str(path),
        "before_sha256": hashlib.sha256(data).hexdigest(),
        "after_sha256": hashlib.sha256(fixed).hexdigest(),
        "data": fixed,
        "offsets": [offset for axis, offset in WINDOW_FIELDS],
        "selection_cells_before": {"width": ORIGINAL_CELLS, "depth": ORIGINAL_CELLS},
        "selection_cells_after": {"width": cells, "depth": cells},
        "patches": [{"axis": axis, "offset": offset, "old_value": ORIGINAL_CELLS,
                     "new_value": cells, "value_bytes": 4}
                    for axis, offset in WINDOW_FIELDS],
    }]
