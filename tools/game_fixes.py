"""Version-checked startup/keyboard fixes for fresh A2-I trial copies only.

Offsets and original instruction bytes were read from the supplied binaries;
see docs/playtest-fixes.md and docs/render-distance.md. This module never
starts a game. CD checks and original sources stay unchanged. The optional
renderer experiment changes two data fields while retaining gameplay code.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

VERSION_HASHES = {
    "A2.EXE": "bb2ed6f29964628771e48707bf8e938c2d2be3bb19d0745bd3e3f5734cec8f13",
    "A2MENU.DAT": "45b883ec76872622241beb75afb3966723d9bee806d76741c29c6642df6ff6e6",
}
LAUNCHER_INTRO_OFFSET = 0x6B8
LAUNCHER_INTRO_CALL = bytes.fromhex("e8fafdffff")
WELCOME_CALL_OFFSET = 0x4889
WELCOME_CALL = bytes.fromhex("e8aef50000")
WELCOME_CALL_VA = 0x405489
KEY_CAVE_OFFSET = 0x23BC0
KEY_CAVE_VA = 0x4247C0
KEY_IAT_VA = 0x443238  # USER32!GetAsyncKeyState in this exact binary.
KEY_CAVE_SIZE = 64
MAX_BINARY_BYTES = 512 * 1024


def any_key_code() -> bytes:
    # Save the same volatile registers as the original key helper, plus ESI.
    # call/pop obtains a position-independent IAT pointer; no absolute address
    # or new relocation is needed when Windows relocates the image.
    code = bytearray(bytes.fromhex("53515256e8000000005e81c6"))
    code += struct.pack("<i", KEY_IAT_VA - (KEY_CAVE_VA + 9))
    code += bytes.fromhex("bb08000000")  # First keyboard VK; mouse buttons excluded.
    loop = len(code)
    code += bytes.fromhex("53ff1666a90080")  # stdcall GetAsyncKeyState; test key-down bit.
    branch = len(code)
    code += b"\x75\x00"  # A key is down: return its nonzero state.
    code += bytes.fromhex("4381fbfe000000")
    code += b"\x7e" + struct.pack("b", loop - (len(code) + 2))
    code += b"\x31\xc0"
    done = len(code)
    code[branch + 1] = done - (branch + 2)
    code += bytes.fromhex("5e5a595bc3")
    if len(code) > KEY_CAVE_SIZE:
        raise ValueError("Toetshelper past niet in de gecontroleerde vrije ruimte.")
    return bytes(code).ljust(KEY_CAVE_SIZE, b"\x00")


def checked_patch(data: bytes, name: str, patches: list[tuple[int, bytes, bytes]]) -> bytes:
    if len(data) > MAX_BINARY_BYTES or hashlib.sha256(data).hexdigest() != VERSION_HASHES[name]:
        raise ValueError(f"Onbekende binaryversie voor intro/toetsfix: {name}.")
    for offset, before, after in patches:
        if len(before) != len(after) or data[offset:offset + len(before)] != before:
            raise ValueError(f"Afwijkende instructie/vrije ruimte voor intro/toetsfix: {name}.")
    result = bytearray(data)
    for offset, before, after in patches:
        result[offset:offset + len(before)] = after
    return bytes(result)


def plan_fixes(source: Path, omit_native_intro: bool = False,
               any_key_welcome: bool = False, pump_launcher_messages: bool = False,
               render_distance_profile: str = "original", *,
               race_focus_recovery: bool = False) -> list[dict]:
    if type(race_focus_recovery) is not bool:
        raise ValueError("Focusherstel moet een expliciete boolean zijn.")
    plans = []
    choices = []
    if pump_launcher_messages:
        from tools.parent_wait_fix import plan_fixes as plan_parent_wait
        plans.extend(plan_parent_wait(source, omit_native_intro))
    elif omit_native_intro:
        choices.append(("A2.EXE", "omit-native-intro",
                        [(LAUNCHER_INTRO_OFFSET, LAUNCHER_INTRO_CALL, b"\x90" * 5)]))
    if any_key_welcome:
        displacement = KEY_CAVE_VA - (WELCOME_CALL_VA + 5)
        choices.append(("A2MENU.DAT", "welcome-any-key", [
            (WELCOME_CALL_OFFSET, WELCOME_CALL, b"\xe8" + struct.pack("<i", displacement)),
            (KEY_CAVE_OFFSET, b"\x00" * KEY_CAVE_SIZE, any_key_code()),
        ]))
    for name, purpose, patches in choices:
        path = source / name
        if not path.is_file() or path.stat().st_size > MAX_BINARY_BYTES:
            raise ValueError(f"Binary voor intro/toetsfix ontbreekt of is te groot: {name}.")
        data = path.read_bytes()
        fixed = checked_patch(data, name, patches)
        plans.append({"path": name, "purpose": purpose, "source_path": str(path),
                      "before_sha256": hashlib.sha256(data).hexdigest(),
                      "after_sha256": hashlib.sha256(fixed).hexdigest(),
                      "data": fixed, "offsets": [p[0] for p in patches]})
    if race_focus_recovery:
        from tools.race_focus_fix import plan_fixes as plan_race_focus
        plans.extend(plan_race_focus(source, render_distance_profile))
    else:
        from tools.render_distance_fix import plan_fixes as plan_render_distance
        plans.extend(plan_render_distance(source, render_distance_profile))
    return plans


def apply_fixes(trial: Path, plans: list[dict]) -> list[dict]:
    # Validate every target before the first write. Copies must be independent.
    for plan in plans:
        target = trial / plan["path"]
        original = Path(plan["source_path"])
        if target.is_symlink() or target.samefile(original) or target.stat().st_nlink != 1:
            raise ValueError("Intro/toetsfix mag uitsluitend een zelfstandige proefkopie wijzigen.")
        if hashlib.sha256(target.read_bytes()).hexdigest() != plan["before_sha256"]:
            raise ValueError("Proefbinary veranderde vóór intro/toetsfix.")
    for plan in plans:
        (trial / plan["path"]).write_bytes(plan["data"])
    return [{key: value for key, value in plan.items() if key != "data"} for plan in plans]
