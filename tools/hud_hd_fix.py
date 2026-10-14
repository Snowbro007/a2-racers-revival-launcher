"""Pinned, opt-in HD HUD composition; original files remain read-only inputs.

Appends own RX/RW helper sections and changes three verified native hook sites.
The native 2D drawing remains the fallback. No code in this module starts a game.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

from tools import hud_hd_native as native, hud_hd_pe as pe

PROFILES = ("original", "hd-overlay-v1", "hd-cockpit-v1", "hd-cockpit-v2", "hd-cockpit-v3")
CACHED_BACKEND = "isolated-device2-cockpit-v3"
NAME = "A2SPEL.DAT"
SOURCE_SHA256 = "069d39e815fc631ef433550459e8105042cf740dfc311e4f9285d4cca148e726"
SOURCE_BYTES = 395264
ASSET_ROOT = "local/mods/a2racer1/hud-hd-v1"
TEARDOWN_CALL = 0x4028FA


@dataclass(frozen=True)
class AssetSpec:
    name: str
    sha256: str
    logical_size: tuple[int, int]
    texture_size: tuple[int, int]
    active_size: tuple[int, int]
    animation_frame: int | None = None

    @property
    def path(self):
        return f"{ASSET_ROOT}/{self.name}.rgb565"

    @property
    def byte_count(self):
        return self.texture_size[0] * self.texture_size[1] * 2


ASSETS = (
    AssetSpec("dashboard-hd-v1", "16fe06190a80800311c520906a3863f7640affb178d71b7b6266af313ce8fd4a", (640, 480), (2048, 2048), (1920, 1440)),
    AssetSpec("ticket-hd-v2", "3b64050b73e32556edbd03803883896cef60faf278ff8660ddc0fa000d943d4a", (320, 194), (2048, 1024), (1280, 776)),
    AssetSpec("fine-digit-0", "63c56a010fef33ca79e1337a609c85e1d81266489ea82534389eddb9804d6c15", (9, 13), (64, 64), (36, 52), 0),
    AssetSpec("fine-digit-1", "e1f3c70eca8dcc221fed8ecd19a40ad49b0c5fe139d71c8177da6e915fb830c7", (6, 12), (64, 64), (24, 48), 1),
    AssetSpec("fine-digit-2", "845a8bd12a55764223afee895643e76b813ccf512f7638be438653c4c0fdde9c", (9, 12), (64, 64), (36, 48), 2),
    AssetSpec("fine-digit-3", "3481351b77071b4f7d181820e722778b5661ca96fc4cc2b6c37a164805df16a8", (9, 13), (64, 64), (36, 52), 3),
    AssetSpec("fine-digit-4", "726c3af52da6502f744c2d9c34ef57c947a05dec08476768c2bb53bbc5b0139d", (9, 12), (64, 64), (36, 48), 4),
    AssetSpec("fine-digit-5", "20c20074898572c0e8605fc89b750352832980a50be8ab4586db69a049d985e0", (9, 13), (64, 64), (36, 52), 5),
    AssetSpec("fine-digit-6", "937e68b9e2ad462002dfa1fb8ad0f2d502d886090866b437df8ca2a3abeb17b4", (8, 13), (64, 64), (32, 52), 6),
    AssetSpec("fine-digit-7", "5182be27e31ddad6ca1b0210d7aeb7fb84ec4cc70e5db2ff8bcb24b27e9e3e2d", (8, 12), (64, 64), (32, 48), 7),
    AssetSpec("fine-digit-8", "d03abeb39abc82448db5f26c50ee6690191f63e2a82ba27b18ff8e8c30014ba3", (9, 13), (64, 64), (36, 52), 8),
    AssetSpec("fine-digit-9", "c2f46181e7e254b111e77dfbd0e0f4bdc2fed57a53708684abf1641742e2a1ef", (8, 13), (64, 64), (32, 52), 9),
)


def load_assets(workspace: Path) -> tuple[native.NativeAsset, ...]:
    """Bounded read of the exact own-art exports, before trial writes."""
    from tools.trial_manifest import validate_ancestors
    assets = []
    for spec in ASSETS:
        path = Path(workspace) / spec.path
        validate_ancestors(path)
        if not path.is_file() or path.stat().st_size != spec.byte_count:
            raise ValueError(f"HD-interfaceasset ontbreekt of heeft afwijkende grootte: {spec.name}.")
        with path.open("rb") as stream:
            pixels = stream.read(spec.byte_count + 1)
        if len(pixels) != spec.byte_count or hashlib.sha256(pixels).hexdigest() != spec.sha256:
            raise ValueError(f"Afwijkende HD-interfaceasset: {spec.name}.")
        options = {"fixed_rect": (0, 0, 640, 480), "require_dashboard": True} if spec.name == "dashboard-hd-v1" else {
            "callers": native.CARD_CALLERS if spec.animation_frame is None else native.DIGIT_CALLERS}
        if spec.animation_frame is not None:
            options.update(animation_group=28, animation_frame=spec.animation_frame)
        assets.append(native.NativeAsset(spec.name, *spec.logical_size, *spec.texture_size,
                                        pixels, active_width=spec.active_size[0],
                                        active_height=spec.active_size[1], **options))
    return tuple(assets)


def load_profile_assets(workspace: Path, profile: str) -> tuple[native.NativeAsset, ...]:
    """Resolve only an explicit HUD profile; keep accepted v2 art unchanged."""
    if profile == "hd-overlay-v1":
        return load_assets(workspace)
    if profile == "hd-cockpit-v1":
        from tools.hud_cockpit_fix import load_assets as load_cockpit_assets
        return load_assets(workspace) + load_cockpit_assets(workspace)
    if profile in ("hd-cockpit-v2", "hd-cockpit-v3"):
        from tools.hud_refined_cockpit_fix import load_assets as load_refined_assets
        from tools.hud_fine_assets import load_assets as load_fine_assets
        # The accepted historical card and digits remain pinned and unchanged.
        cockpit = (load_refined_assets(workspace) if profile == "hd-cockpit-v2"
                   else load_refined_assets(workspace, variant="v2"))
        return load_assets(workspace)[:1] + load_fine_assets(workspace) + cockpit
    raise ValueError("HD-assetlader vereist een expliciet interface- of cockpitprofiel.")


def checked_patch(data: bytes, assets: tuple[native.NativeAsset, ...], *,
                  profile: str | None = None) -> tuple[bytes, dict]:
    """Pure byte composition of a known existing race variant and own HUD."""
    if profile is not None and (profile not in ("hd-cockpit-v2", "hd-cockpit-v3") or
                               not any(asset.cached_role is not None for asset in assets)):
        raise ValueError("Expliciete nieuwe cockpitversie vereist gecachte cockpitassets.")
    input_sha = hashlib.sha256(data).hexdigest()
    if input_sha not in pe.KNOWN_VARIANTS:
        raise ValueError("Onbekende racevariant voor de HD-interfaceproef.")
    variant = pe.KNOWN_VARIANTS[input_sha]
    sections = pe.expected_sections(variant.focus_recovery)
    cleanup_offset = pe._mapped_offset(data,sections,TEARDOWN_CALL-pe.IMAGE_BASE,5)
    cleanup_before = data[cleanup_offset:cleanup_offset+5]
    if cleanup_before[:1] != b"\xe8":
        raise ValueError("HD-interface mist de bewezen cleanup-CALL.")
    cleanup_target = TEARDOWN_CALL+5+struct.unpack_from("<i",cleanup_before,1)[0]
    if variant.focus_recovery:
        from tools.race_focus_fix import helper_bundle, HELPER_VA
        _, focus_labels = helper_bundle()
        expected_cleanup = HELPER_VA+focus_labels["cache_cleanup"]
    else:
        expected_cleanup = 0x407799
    if cleanup_target != expected_cleanup:
        raise ValueError("HD-interfacecleanup verwijst niet naar de gepinde bestaande cleanupchain.")
    focus_va = 0x45A400 if variant.focus_recovery else None
    provisional = native.build_helper(assets, state_va=0x4A0000, focus_state_va=focus_va,
                                      cleanup_target_va=cleanup_target)
    layout = pe.plan_layout(data, input_sha, len(provisional.code), len(provisional.state))
    bundle = native.build_helper(assets, code_va=layout.code_va, state_va=layout.state_va,
                                 focus_state_va=focus_va, cleanup_target_va=cleanup_target)
    if (len(bundle.code), len(bundle.state)) != (layout.code_size, layout.state_size):
        raise ValueError("HUD-helperlayout veranderde tijdens de tweede encodeerpass.")
    appended = pe.append_sections(data, input_sha, bundle.code, bundle.state)
    result = bytearray(appended.data)
    hooks = []
    for address, before, opcode, label in (
            (native.SPRITE_ENTRY, native.SPRITE_REPLAY, b"\xe9", "capture"),
            (native.PRESENT_CALL, native.PRESENT_BYTES, b"\xe8", "present"),
            (TEARDOWN_CALL,cleanup_before,b"\xe8","teardown")):
        rva = address - pe.IMAGE_BASE
        offset = pe._mapped_offset(data, pe.expected_sections(variant.focus_recovery), rva, len(before))
        if data[offset:offset + len(before)] != before:
            raise ValueError("Native HD-interfacehook wijkt af van de bewezen instructies.")
        target = layout.code_va + bundle.labels[label]
        after = opcode + struct.pack("<i", target - address - 5) + b"\x90" * (len(before) - 5)
        result[offset:offset + len(before)] = after
        hooks.append({"va": address, "offset": offset, "before": before.hex(), "after": after.hex(), "target_va": target})
    # Independent final scope check: original payload changes only at three hooks.
    allowed = (*pe.ALLOWED_HEADER_CHANGES, *((h["offset"], h["offset"] + len(bytes.fromhex(h["before"]))) for h in hooks))
    for offset, (before, after) in enumerate(zip(data, result)):
        if before != after and not any(start <= offset < end for start, end in allowed):
            raise ValueError("HD-interface wijzigde bytes buiten de drie hooks/sectieheaders.")
    cached = any(asset.cached_role is not None for asset in assets)
    evidence = {
        "profile": profile or ("hd-cockpit-v1" if cached else "hd-overlay-v1"), "input_sha256": input_sha,
        "render_backend": CACHED_BACKEND if cached else native.BACKEND,
        "helper_sha256": hashlib.sha256(bundle.code).hexdigest(),
        "helper_bytes": len(bundle.code), "state_bytes": len(bundle.state),
        "code_va": layout.code_va, "state_va": layout.state_va,
        "diagnostic_state_offsets": bundle.state_offsets,
        "diagnostic_stages": dict(native.STAGES), "hooks": hooks,
        "preserved_cleanup_target_va": cleanup_target,
        "native_drawing_preserved": True, "native_animations_preserved": True,
        "runtime_verified": False, "full_cockpit_hd": False,
        "assets": [{"name": a.name, "sha256": hashlib.sha256(a.pixels_rgb565).hexdigest(),
                    "logical_size": [a.logical_width, a.logical_height],
                    "texture_size": [a.texture_width, a.texture_height],
                    "active_size": [a.active_width_or_full, a.active_height_or_full]} for a in assets],
    }
    if cached:
        from tools.hud_hd_assets import COCKPIT_GROUPS
        evidence["cockpit_roles"] = [group.name for group in COCKPIT_GROUPS
                                    if any(asset.cached_role == group.name for asset in assets)]
        for record, asset in zip(evidence["assets"], assets):
            if asset.cached_role is not None:
                record.update(cached_role=asset.cached_role, animation_group=asset.animation_group,
                              callers=list(asset.callers),
                              atlas_frames=[{"animation_frame": frame.animation_frame,
                                             "pixel_rect": list(frame.pixel_rect)}
                                            for frame in asset.atlas_frames])
    return bytes(result), evidence


def compose_fixes(workspace: Path, source: Path, existing_plans: list[dict],
                  profile: str = "original") -> list[dict]:
    if profile not in PROFILES:
        raise ValueError("Onbekend HD-interfaceprofiel.")
    plans = list(existing_plans)
    if profile == "original":
        return plans
    path = Path(source) / NAME
    from tools.trial_manifest import validate_ancestors
    validate_ancestors(path)
    if not path.is_file() or path.stat().st_size != SOURCE_BYTES:
        raise ValueError("Gepinde HD-interfacebron ontbreekt of heeft afwijkende grootte.")
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("Onbekende bronbinary voor de HD-interfaceproef.")
    matches = [index for index, plan in enumerate(plans) if plan.get("path") == NAME]
    if len(matches) > 1:
        raise ValueError("Meerdere raceplannen kunnen niet met de HD-interfaceproef worden gecombineerd.")
    if matches:
        index = matches[0]
        plan = dict(plans[index])
        if (plan.get("before_sha256") != SOURCE_SHA256 or
                Path(plan.get("source_path", "")).resolve() != path.resolve()):
            raise ValueError("Raceplan verwijst niet naar de gepinde HD-interfacebron.")
        base = plan.get("data")
        if type(base) is not bytes or hashlib.sha256(base).hexdigest() != plan.get("after_sha256"):
            raise ValueError("Raceplan veranderde vóór de HD-interfaceproef.")
    else:
        index, base = len(plans), original
        plan = {"path": NAME, "purpose": "hd-interface-experimental", "source_path": str(path),
                "before_sha256": SOURCE_SHA256}
    assets = load_assets(workspace) if profile == "hd-overlay-v1" else load_profile_assets(workspace, profile)
    result, evidence = (checked_patch(base, assets, profile=profile)
                        if profile in ("hd-cockpit-v2", "hd-cockpit-v3") else checked_patch(base, assets))
    if evidence["profile"] != profile:
        raise ValueError("HD-assets passen niet bij het aangevraagde HUD-profiel.")
    plan.update(data=result, after_sha256=hashlib.sha256(result).hexdigest(),
                hud_profile=profile, hud_patch=evidence, runtime_verified=False)
    if index == len(plans):
        plans.append(plan)
    else:
        plans[index] = plan
    return plans
