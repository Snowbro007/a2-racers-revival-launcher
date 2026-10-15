"""Read pinned own vector cockpit exports; never execute or change a game."""
from __future__ import annotations

import hashlib
from pathlib import Path

from tools import hud_cockpit_assets as art, hud_hd_native as native

# Own offscreen vector export03, visually inspected; runtime is still a trial.
ASSET_PINS: dict[str, str] = {
    'rim-bridge-vector-v1':'bdbf0cb3af23e8316e4dab922b4248fdf1b2c38045aca6b403696812d1da4023',
    'strip-vector-v1':'ebc0488d8be1bfc95095e572007ac60baecb9282ea01c38897798b49a6c92ab4',
    'wheel-vector-v1-0':'5735bf6afd03f84afe6f9a5d69a9367c863cf52213da13bc90c0ac50a8cdce15',
    'wheel-vector-v1-1':'4e616a42f64c4030fe762f0373d85182e5f6b035cbe7dfa83196141455996e44',
    'wheel-vector-v1-2':'c43665eb659ce1225ba7362ce41d6288150692386e916e609781ec96c4cdf47c',
    'right-vector-v1':'7f0ece4b9bff23c9064df1b3c5765a4efc4cdafb530e460ca91a0b66d6884880',
    'speed-vector-v1':'9f62c1e2904bb12fba161c24fcb953f4e5038b1522a3b9389fe15c1b3f1d114d',
    'tach-vector-v1':'fc0359002f6167405c6073619204fae62d9c36afe299afa9eed9a400b82ede6f',
}


def load_assets(workspace: Path) -> tuple[native.NativeAsset, ...]:
    from tools.trial_manifest import validate_ancestors
    art.validate_atlases(art.ATLASES)
    specs = (*art.FIXED_PATCHES, *art.ATLASES)
    if set(ASSET_PINS) != {spec.name for spec in specs}:
        raise ValueError("HD-cockpitexport heeft nog geen volledige gepinde assetset.")
    assets = []
    for atlas in specs:
        path = Path(workspace) / art.ASSET_ROOT / (atlas.name + ".rgb565")
        validate_ancestors(path)
        if not path.is_file() or path.stat().st_size != atlas.byte_count:
            raise ValueError(f"HD-cockpitatlas ontbreekt of heeft afwijkende grootte: {atlas.name}.")
        with path.open("rb") as stream:
            pixels = stream.read(atlas.byte_count + 1)
        if len(pixels) != atlas.byte_count or hashlib.sha256(pixels).hexdigest() != ASSET_PINS[atlas.name]:
            raise ValueError(f"Afwijkende HD-cockpitatlas: {atlas.name}.")
        if isinstance(atlas, art.PatchSpec):
            asset = native.NativeAsset(
                atlas.name, *atlas.logical_size, *atlas.texture_size, pixels,
                active_width=atlas.active_size[0], active_height=atlas.active_size[1],
                fixed_rect=atlas.logical_rect, require_dashboard=True)
        else:
            asset = native.NativeAsset(
                atlas.name, *atlas.logical_size, *atlas.texture_size, pixels,
                active_width=atlas.active_size[0], active_height=atlas.active_size[1],
                callers=atlas.callers, animation_group=atlas.animation_group,
                require_dashboard=True, cached_role=atlas.cached_role,
                atlas_frames=tuple(native.AtlasFrame(frame.animation_frame, frame.pixel_rect)
                                   for frame in atlas.frames))
        asset.validate()
        assets.append(asset)
    return tuple(assets)
