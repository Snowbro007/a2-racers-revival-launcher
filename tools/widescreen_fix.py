"""Pinned, opt-in camera experiment for fresh A2-I trial copies.

Only the horizontal projection coefficient changes. This is not a complete
widescreen fix: native HUD/dashboard layout and CPU side culling stay intact.
The planner constructs bytes only; game_fixes.apply_fixes owns copy writes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from tools.render_distance_fix import EXPECTED_PATCHED_SHA256_BY_PROFILE as DISTANCE_HASHES
from tools.race_focus_fix import EXPECTED_PATCHED_SHA256_BY_PROFILE as FOCUS_HASHES

NAME = "A2SPEL.DAT"
EXPECTED_SHA256 = "069d39e815fc631ef433550459e8105042cf740dfc311e4f9285d4cca148e726"
EXPECTED_SIZE = 395264
PROFILES = ("original", "camera-16-9")
RENDER_DISTANCE_PROFILES = ("original", "extended-8", "extended-10", "extended-20")
MATRIX_VA = 0x459598
MATRIX_OFFSET = 0x58198
# The focus helper inserts 0x800 raw bytes before DGROUP and a further 0x200
# after this matrix. Existing RVAs remain unchanged; the matrix file offset moves.
MATRIX_OFFSET_BY_FOCUS = {False: MATRIX_OFFSET, True: MATRIX_OFFSET + 0x800}
SIZE_BY_FOCUS = {False: EXPECTED_SIZE, True: EXPECTED_SIZE + 0xA00}
BASE_SHA256_BY_PROFILE = {
    False: {"original": EXPECTED_SHA256, **DISTANCE_HASHES},
    True: dict(FOCUS_HASHES),
}
# Read-only construction from the pinned original and the existing patchers,
# independently hashed on 10 October 2026. These are file hashes, not playtests.
EXPECTED_CAMERA_SHA256_BY_PROFILE = {
    False: {
        "original": "914b0a913c6fe727d593e2d41711852638e11a9649b24c4ddb94ce700f244a48",
        "extended-8": "7cd847eb17c93c66b46d36b7a46a87afe41c26de5678d54c1c7bb6ee258e2357",
        "extended-10": "c0e5ff3e5e080c17715b52065d1fceb20ac85bf5e7a8f8af917226d35d500fab",
        "extended-20": "2740b89bb63fee9fd3330c407432e5325d48aef307f2d437023b8b0b81ee1038",
    },
    True: {
        "original": "25a6f7884724c642df7a7a1ed965bc00f3ebabef769e3d3f5fb7907acaf06592",
        "extended-8": "51346dd2d70073a2b4ca9f2195c804f3a90d3419f63a9d5043c3319223c4ff53",
        "extended-10": "a132293d809d7712659100c8d70d57ce84f22923af44a9eb765a7c0c10f37b8b",
        "extended-20": "5c98529b3b86476beb5aabadf61acd2e2c21e73f12b394b069d3d44a41b1579f",
    },
}
ORIGINAL_MATRIX = struct.pack("<16f", 2, 0, 0, 0, 0, 2, 0, 0,
                              0, 0, 1, 1, 0, 0, -1, 0)
HORIZONTAL_BEFORE = 2.0
HORIZONTAL_AFTER = 1.5
LIMITATION = (
    "Experimentele 3D-camera; HUD/dashboard en CPU-zijculling zijn niet aangepast. "
    "Dit is geen volledig bewezen 16:9-weergave."
)


def _validate_profile(profile: str, render_distance_profile: str,
                      race_focus_recovery: bool) -> None:
    if profile not in PROFILES:
        raise ValueError("Onbekend profiel voor breedbeeldcameraproef.")
    if render_distance_profile not in RENDER_DISTANCE_PROFILES:
        raise ValueError("Onbekend zichtvensterprofiel voor breedbeeldcameraproef.")
    if type(race_focus_recovery) is not bool:
        raise ValueError("Focusherstel moet een expliciete boolean zijn.")


def checked_patch(data: bytes, profile: str = "camera-16-9", *,
                  render_distance_profile: str = "original",
                  race_focus_recovery: bool = False) -> bytes:
    """Change one float in one exact known race variant, retaining other fixes."""
    _validate_profile(profile, render_distance_profile, race_focus_recovery)
    if profile == "original":
        raise ValueError("Camerapatch vereist het opt-in-profiel camera-16-9.")
    expected = BASE_SHA256_BY_PROFILE[race_focus_recovery][render_distance_profile]
    if (type(data) is not bytes or len(data) != SIZE_BY_FOCUS[race_focus_recovery]
            or hashlib.sha256(data).hexdigest() != expected):
        raise ValueError("Onbekende racebinaryversie voor breedbeeldcameraproef.")
    offset = MATRIX_OFFSET_BY_FOCUS[race_focus_recovery]
    if data[offset:offset + len(ORIGINAL_MATRIX)] != ORIGINAL_MATRIX:
        raise ValueError("Afwijkende projectiematrix voor breedbeeldcameraproef.")
    result = bytearray(data)
    struct.pack_into("<f", result, offset, HORIZONTAL_AFTER)
    return bytes(result)


def compose_fixes(source: Path, existing_plans: list[dict], profile: str = "original", *,
                  render_distance_profile: str = "original",
                  race_focus_recovery: bool = False) -> list[dict]:
    """Fold the camera change into one existing race plan, never duplicate writes.

    Call after game_fixes.plan_fixes and before apply_fixes. The original profile
    returns a new list without reading a binary. Source and earlier plans are
    not changed. Already patched disk input is deliberately refused.
    """
    _validate_profile(profile, render_distance_profile, race_focus_recovery)
    plans = list(existing_plans)
    if profile == "original":
        return plans
    path = Path(source) / NAME
    if not path.is_file() or path.stat().st_size != EXPECTED_SIZE:
        raise ValueError("Gepinde bron voor breedbeeldcameraproef ontbreekt of heeft afwijkende grootte.")
    original = path.read_bytes()
    if (len(original) != EXPECTED_SIZE or
            hashlib.sha256(original).hexdigest() != EXPECTED_SHA256):
        raise ValueError("Onbekende bronbinaryversie voor breedbeeldcameraproef.")
    matches = [index for index, plan in enumerate(plans) if plan.get("path") == NAME]
    if len(matches) > 1:
        raise ValueError("Meerdere raceplannen kunnen niet veilig met de cameraproef worden gecombineerd.")
    if matches:
        index = matches[0]
        plan = dict(plans[index])
        if (plan.get("before_sha256") != EXPECTED_SHA256 or
                Path(plan.get("source_path", "")).resolve() != path.resolve()):
            raise ValueError("Raceplan verwijst niet naar de gepinde camerabron.")
        base = plan.get("data")
        if type(base) is not bytes or hashlib.sha256(base).hexdigest() != plan.get("after_sha256"):
            raise ValueError("Raceplan veranderde vóór de breedbeeldcameraproef.")
    else:
        if race_focus_recovery or render_distance_profile != "original":
            raise ValueError("De combinatie mist het bestaande focus-/zichtvensterplan.")
        index = len(plans)
        base = original
        plan = {"path": NAME, "purpose": "horizontal-camera-16-9-experimental",
                "source_path": str(path), "before_sha256": EXPECTED_SHA256}
    result = checked_patch(base, profile, render_distance_profile=render_distance_profile,
                           race_focus_recovery=race_focus_recovery)
    plan.update({
        "data": result,
        "after_sha256": hashlib.sha256(result).hexdigest(),
        "runtime_verified": False,
        "camera_profile": profile,
        "camera_patch": {
            "purpose": "horizontal-camera-16-9-experimental",
            "matrix_va": MATRIX_VA,
            "offset": MATRIX_OFFSET_BY_FOCUS[race_focus_recovery],
            "value_bytes": 4,
            "horizontal_projection_before": HORIZONTAL_BEFORE,
            "horizontal_projection_after": HORIZONTAL_AFTER,
            "world_horizontal_scale_ratio": HORIZONTAL_AFTER / HORIZONTAL_BEFORE,
            "hud_layout_modified": False,
            "cpu_side_culling_modified": False,
            "widescreen_complete": False,
            "runtime_verified": False,
            "limitation": LIMITATION,
        },
    })
    if index == len(plans):
        plans.append(plan)
    else:
        plans[index] = plan
    return plans


def plan_fixes(source: Path, profile: str = "original") -> list[dict]:
    """Plan a camera-only probe; use compose_fixes for focus/distance variants."""
    return compose_fixes(source, [], profile)
