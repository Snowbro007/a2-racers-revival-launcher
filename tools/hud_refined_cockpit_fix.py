"""Read only pinned own material cockpit exports; preserve historical trials."""
from __future__ import annotations

import hashlib
from pathlib import Path
from tools import hud_refined_cockpit_assets as art,hud_hd_native as native

ASSET_PINS: dict[str,str] = {
    'left-material-v1':'61065ffba1fa70fda9f83ead3399648cc6028d5680ee6e3ecfb73c41778d4b96',
    'strip-material-v1':'1d3a48e4bb49ffa5142a777962a6aa21f93e955e1c33706890ab2d48a6c3eb8f',
    'wheel-material-v1-0':'07d01a857daaea69debb0d9111d0450f426c362f8732602320e0b9796f14527e',
    'wheel-material-v1-1':'f63bf8b29e4baa95f5f30ba0871b01006985ca5ff2ea96773faadcb189e0eba0',
    'wheel-material-v1-2':'e351f02a4611f9d2187f356bd2f173a84d99d1ed9542fc308fb86f5c8b443f62',
    'right-material-v1':'c66835b97f680fed59b96ce7f9400d9477fc789ae82af9882346a4d344695f6b',
    'speed-material-v1':'3564a3366c2db7c0dd873f074039df704f8004e797fb923d46ebe12677e2339b',
    'tach-material-v1':'7fd9ef8ce3c624d43ca6d6bb42d491fc8fe31ee6856a613783c8dbfb0f06e3dc',
}
ASSET_PINS_V2: dict[str,str] = {
    'left-material-v2': '26457146b602dce53066bdc54d040662808471a8e428cc133d1544e5c98a2996',
    'strip-material-v2': '1d3a48e4bb49ffa5142a777962a6aa21f93e955e1c33706890ab2d48a6c3eb8f',
    'wheel-material-v2-0': '07d01a857daaea69debb0d9111d0450f426c362f8732602320e0b9796f14527e',
    'wheel-material-v2-1': 'f63bf8b29e4baa95f5f30ba0871b01006985ca5ff2ea96773faadcb189e0eba0',
    'wheel-material-v2-2': 'e351f02a4611f9d2187f356bd2f173a84d99d1ed9542fc308fb86f5c8b443f62',
    'right-material-v2': 'f2b4343b182c42f3c005ef035b54a0ac8e8bea6d8577d6c1c9818e289a11b1a5',
    'speed-material-v2': '59fbe41851e7c43040a362ed0075aecfacc9d46cfaaee0647bc9f3b2af33ba67',
    'tach-material-v2': '0b08a16d7484d8e83bf349de64f1780067e776168d56d16e342df6aaba6b71d3',
}


def load_assets(workspace: Path, *, variant: str = "v1") -> tuple[native.NativeAsset,...]:
    from tools.trial_manifest import validate_ancestors
    if type(variant) is not str or variant not in art.VARIANTS:
        raise ValueError('Onbekende materiaalcockpitversie.')
    atlases = art.ATLASES if variant == "v1" else art.ATLASES_V2
    patches = art.FIXED_PATCHES if variant == "v1" else art.FIXED_PATCHES_V2
    asset_root = art.ASSET_ROOT if variant == "v1" else art.ASSET_ROOT_V2
    pins = ASSET_PINS if variant == "v1" else ASSET_PINS_V2
    art.original.validate_atlases(atlases)
    specs=(*patches,*atlases)
    if set(pins)!={spec.name for spec in specs}:
        raise ValueError('Verfijnde cockpit mist een volledige gepinde assetset.')
    assets=[]
    for spec in specs:
        path=Path(workspace)/asset_root/(spec.name+'.rgb565')
        validate_ancestors(path)
        if not path.is_file() or path.stat().st_size!=spec.byte_count:
            raise ValueError(f'Verfijnde cockpitasset ontbreekt of heeft afwijkende grootte: {spec.name}.')
        with path.open('rb') as stream:
            pixels=stream.read(spec.byte_count+1)
        if len(pixels)!=spec.byte_count or hashlib.sha256(pixels).hexdigest()!=pins[spec.name]:
            raise ValueError(f'Afwijkende verfijnde cockpitasset: {spec.name}.')
        if isinstance(spec,art.original.PatchSpec):
            options={'fixed_rect':spec.logical_rect,'require_dashboard':True}
        else:
            options={'callers':spec.callers,'animation_group':spec.animation_group,
                     'require_dashboard':True,'cached_role':spec.cached_role,
                     'atlas_frames':tuple(native.AtlasFrame(frame.animation_frame,frame.pixel_rect) for frame in spec.frames)}
        asset=native.NativeAsset(spec.name,*spec.logical_size,*spec.texture_size,pixels,
                                 active_width=spec.active_size[0],active_height=spec.active_size[1],**options)
        asset.validate()
        assets.append(asset)
    return tuple(assets)
