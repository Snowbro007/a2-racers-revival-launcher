"""Opt-in, pinned selection of all loaded active A2-I objects.

The existing object loop keeps its count, stride, inactive-object exclusion and
later callbacks. One short-branch displacement skips only the object's x/z
selection rectangle. Road selection, projection and GPU clipping stay intact.
Planning constructs bytes only; game_fixes.apply_fixes owns trial-copy writes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from tools import widescreen_fix

NAME = "A2SPEL.DAT"
EXPECTED_SHA256 = widescreen_fix.EXPECTED_SHA256
EXPECTED_SIZE = widescreen_fix.EXPECTED_SIZE
PROFILES = ("original", "loaded-all")
RENDER_DISTANCE_PROFILES = widescreen_fix.RENDER_DISTANCE_PROFILES
CAMERA_PROFILES = widescreen_fix.PROFILES
SIZE_BY_FOCUS = dict(widescreen_fix.SIZE_BY_FOCUS)
BASE_SHA256_BY_VARIANT = {
    (focus, distance, camera): (
        widescreen_fix.BASE_SHA256_BY_PROFILE[focus][distance]
        if camera == "original" else
        widescreen_fix.EXPECTED_CAMERA_SHA256_BY_PROFILE[focus][distance])
    for focus in (False, True)
    for distance in RENDER_DISTANCE_PROFILES
    for camera in CAMERA_PROFILES
}
# Full-file results independently constructed in memory from the original on
# 11 October 2026. These pins describe bytes, not successful game playtests.
EXPECTED_PATCHED_SHA256_BY_VARIANT = {
    (False, "original", "original"): "2bb0f0ef4464951d9b4e29e013e14972307e3c00f75848cc85b4387dbf3324a2",
    (False, "original", "camera-16-9"): "0c4786fcb89d334ae3b706fb0c7d61ba7670bb88e66ac608a2a692898335227c",
    (False, "extended-8", "original"): "4aabd5e5d1c2c489eba1979c0c8ab2760f68a423465bdc15e66fe9318555cc07",
    (False, "extended-8", "camera-16-9"): "0090dc09bba0a88975ec8406822e8f3c55387664b74663a9edd3fe0eaeaeebde",
    (False, "extended-10", "original"): "ac8d19a7a71f910714b30ba297b724a4012e2dcb2028c75e4ac1d575e41d6de4",
    (False, "extended-10", "camera-16-9"): "217eae3bb6f4c21eb8b4eb20498010645f83213de1ce28ef5d5cbfa1dd603239",
    (False, "extended-20", "original"): "203bc811620299e61b737e085496d5184a3230da070ed65da9db58973cffc73e",
    (False, "extended-20", "camera-16-9"): "a7c25211fcfb21d206c102409257a81c264dab5201375467e3f66ed58410d2af",
    (True, "original", "original"): "dc8cc6dbf0ab7bbfe5fd818a6a8552c58c77e12a7193bbf9eac1034e67e7cdee",
    (True, "original", "camera-16-9"): "bceda82d8cc8feffa87365a96621c9606351d3e17cff75abce31308aed3978a8",
    (True, "extended-8", "original"): "da1352cbf52467f2b576119cedcbf495ced4afe6ea51da64b852c638294f47e2",
    (True, "extended-8", "camera-16-9"): "4ecd2f08a89fcc52f3f6f6bc88de1db6f2180dbd3511047375f821f2b8334eb7",
    (True, "extended-10", "original"): "3d82a1d804bf7f3c7d4c2b9272e27dfef2e6affa23e03a78a2602d29b1e4d650",
    (True, "extended-10", "camera-16-9"): "6353835d4d63e4a23f8772e2447899b424b9bcb88c0b617762cd579149bbb817",
    (True, "extended-20", "original"): "eabea323ef1824208a0f6dcad46f3d8075c6c374bdf92241983498c6c5778d9b",
    (True, "extended-20", "camera-16-9"): "2ee960d32e8b976d6cb106f4f94f109251ccb3cbbe425480f86cc16ec8ce0e3e",
}
ALLOWED_PATCHED_SHA256 = frozenset(EXPECTED_PATCHED_SHA256_BY_VARIANT.values())
ROUTINE_VA = 0x423F75
ROUTINE_OFFSET = 0x23375
ROUTINE_BEFORE = bytes.fromhex(
    "50525351833d7c67470000751768f00000006845e444006852e44400e83b09ffff"
    "83c40c31c931dbeb27db44240cd85a08dfe09e770cdb442404d85a08dfe09e732b"
    "8b1574674700c6441a350083c34b413b0d786747007d318b157467470001da8a62"
    "3484e475c2886235ebe0db442408d85a10dfe09e77c9db0424d85a10dfe09e72be"
    "c6423501ebc383c410c3")
BRANCH_VA = 0x423FDB
BRANCH_OFFSET = 0x233DB
DISPLACEMENT_OFFSET = BRANCH_OFFSET + 1
ORIGINAL_DESTINATION_VA = 0x423F9F
LOADED_ALL_DESTINATION_VA = 0x423FF9
DISPLACEMENT_BEFORE = -62  # 0xc2: active object -> rectangle comparisons.
DISPLACEMENT_AFTER = 28  # 0x1c: active object -> existing visible=1 store.
LIMITATION = (
    "Alle geladen actieve objecten worden aan de rechthoekselectie toegelaten; "
    "latere callbacks en GPU-clipping blijven gelden. Wegselectie blijft gelijk. "
    "Dit bewijst geen onbeperkte zichtafstand of stabiele/prestatievrije werking."
)


def _validate_profile(profile: str, render_distance_profile: str,
                      race_focus_recovery: bool, camera_profile: str) -> tuple:
    if profile not in PROFILES:
        raise ValueError("Onbekend objectafstandprofiel.")
    if render_distance_profile not in RENDER_DISTANCE_PROFILES:
        raise ValueError("Onbekend zichtvensterprofiel voor objectafstandproef.")
    if type(race_focus_recovery) is not bool:
        raise ValueError("Focusherstel moet een expliciete boolean zijn.")
    if camera_profile not in CAMERA_PROFILES:
        raise ValueError("Onbekend cameraprofiel voor objectafstandproef.")
    return race_focus_recovery, render_distance_profile, camera_profile


def checked_patch(data: bytes, profile: str = "loaded-all", *,
                  render_distance_profile: str = "original",
                  race_focus_recovery: bool = False,
                  camera_profile: str = "original") -> bytes:
    """Change one displacement in an exact known variant; source stays intact."""
    variant = _validate_profile(profile, render_distance_profile,
                                race_focus_recovery, camera_profile)
    if profile == "original":
        raise ValueError("Objectafstandpatch vereist het opt-in-profiel loaded-all.")
    if (type(data) is not bytes or len(data) != SIZE_BY_FOCUS[race_focus_recovery]
            or hashlib.sha256(data).hexdigest() != BASE_SHA256_BY_VARIANT[variant]):
        raise ValueError("Onbekende racebinaryversie voor objectafstandproef.")
    if data[ROUTINE_OFFSET:ROUTINE_OFFSET + len(ROUTINE_BEFORE)] != ROUTINE_BEFORE:
        raise ValueError("Afwijkende objectselectieroutine voor objectafstandproef.")
    result = bytearray(data)
    result[DISPLACEMENT_OFFSET] = DISPLACEMENT_AFTER
    result = bytes(result)
    if hashlib.sha256(result).hexdigest() != EXPECTED_PATCHED_SHA256_BY_VARIANT[variant]:
        raise ValueError("Afwijkende uitkomsthash voor objectafstandproef.")
    return result


def compose_fixes(source: Path, existing_plans: list[dict], profile: str = "original", *,
                  render_distance_profile: str = "original",
                  race_focus_recovery: bool = False,
                  camera_profile: str = "original") -> list[dict]:
    """Fold object selection into one race plan after optional camera/focus fixes."""
    _validate_profile(profile, render_distance_profile, race_focus_recovery, camera_profile)
    plans = list(existing_plans)
    if profile == "original":
        return plans
    path = Path(source) / NAME
    if not path.is_file() or path.stat().st_size != EXPECTED_SIZE:
        raise ValueError("Gepinde bron voor objectafstandproef ontbreekt of heeft afwijkende grootte.")
    original = path.read_bytes()
    if len(original) != EXPECTED_SIZE or hashlib.sha256(original).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Onbekende bronbinaryversie voor objectafstandproef.")
    matches = [index for index, plan in enumerate(plans) if plan.get("path") == NAME]
    if len(matches) > 1:
        raise ValueError("Meerdere raceplannen kunnen niet veilig met de objectafstandproef worden gecombineerd.")
    if matches:
        index = matches[0]
        plan = dict(plans[index])
        if (plan.get("before_sha256") != EXPECTED_SHA256
                or Path(plan.get("source_path", "")).resolve() != path.resolve()):
            raise ValueError("Raceplan verwijst niet naar de gepinde objectafstandbron.")
        base = plan.get("data")
        if type(base) is not bytes or hashlib.sha256(base).hexdigest() != plan.get("after_sha256"):
            raise ValueError("Raceplan veranderde vóór de objectafstandproef.")
    else:
        if (race_focus_recovery or render_distance_profile != "original"
                or camera_profile != "original"):
            raise ValueError("De combinatie mist het bestaande focus-/zichtvenster-/cameraplan.")
        index = len(plans)
        base = original
        plan = {"path": NAME, "purpose": "active-object-selection-loaded-all-experimental",
                "source_path": str(path), "before_sha256": EXPECTED_SHA256}
    result = checked_patch(base, profile, render_distance_profile=render_distance_profile,
                           race_focus_recovery=race_focus_recovery, camera_profile=camera_profile)
    plan.update({
        "data": result,
        "after_sha256": hashlib.sha256(result).hexdigest(),
        "runtime_verified": False,
        "object_distance_profile": profile,
        "object_distance_patch": {
            "purpose": "active-object-selection-loaded-all-experimental",
            "branch_va": BRANCH_VA,
            "offset": DISPLACEMENT_OFFSET,
            "value_bytes": 1,
            "before_byte": DISPLACEMENT_BEFORE & 0xFF,
            "after_byte": DISPLACEMENT_AFTER,
            "branch_target_before_va": ORIGINAL_DESTINATION_VA,
            "branch_target_after_va": LOADED_ALL_DESTINATION_VA,
            "active_object_required": True,
            "loaded_object_count_modified": False,
            "object_allocation_modified": False,
            "road_selection_modified": False,
            "projection_modified": False,
            "later_callbacks_modified": False,
            "unlimited_visible_distance_proven": False,
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
    """Plan an object-only probe; compose_fixes accepts the known combinations."""
    return compose_fixes(source, [], profile)
