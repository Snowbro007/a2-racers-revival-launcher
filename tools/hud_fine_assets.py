"""Versioned fine typography and technical own-card RGB565 export.

Only own font outlines/card art are converted. No game is executed or written.
The accepted overlay-v1 exports remain separate and unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

from tools import hud_hd_native as native

ASSET_ROOT = "local/mods/a2racer1/hud-refined-v2"
COLOR_KEY = 0xF81F
INK_RGB = (8, 25, 70)
INK_RGB565 = ((INK_RGB[0] >> 3) << 11) | ((INK_RGB[1] >> 2) << 5) | (INK_RGB[2] >> 3)
FONT_FAMILY = "Courier New"
FONT_WEIGHT = "bold"
SCALE = 4
CAP_HEIGHT = 10.0
BASELINE = 11.0
ALPHA_THRESHOLD = 128
# Exact original resource dimensions and anchors. The game's four centers and
# 12-pixel advance remain untouched; sprite capture accounts for these anchors.
DIGIT_GEOMETRY = ((9,13,5,6),(6,12,3,6),(9,12,5,6),(9,13,5,6),(9,12,5,6),
                  (9,13,5,6),(8,13,4,6),(8,12,4,6),(9,13,5,6),(8,13,4,6))


@dataclass(frozen=True)
class AssetSpec:
    name: str
    logical_size: tuple[int, int]
    texture_size: tuple[int, int]
    active_size: tuple[int, int]
    animation_frame: int | None = None

    @property
    def byte_count(self):
        return self.texture_size[0] * self.texture_size[1] * 2


ASSETS = (AssetSpec("ticket-refined-v2", (320,194), (2048,1024), (1280,776)),) + tuple(
    AssetSpec(f"fine-refined-v2-{i}", (w,h), (64,64), (w*SCALE,h*SCALE), i)
    for i,(w,h,_,_) in enumerate(DIGIT_GEOMETRY))
# Filled from the exact local technical export, never from an unverified file.
ASSET_PINS: dict[str, str] = {
    "ticket-refined-v2": "33c6302d8d0fc981a273632190c3b19a448ad35b2b25480820432a9988b65ac0",
    "fine-refined-v2-0": "392ab3bceb00bf25a38c1ae3b478f3348adda20de26638142e54a7dc39ae87b5",
    "fine-refined-v2-1": "59c4c3431afa6b02691cb5a95bdd0ba08e099037d4ba06c3801849b6f077c443",
    "fine-refined-v2-2": "2f586ffee5acf05c052b6ee2cc2fd5fa9efca7e13de58352eaa68d42b4265e58",
    "fine-refined-v2-3": "522bc86270c466ae92bf5e76f0472fec380b3ed4b38f9ad99dad10526d52683c",
    "fine-refined-v2-4": "9e149928734a165d7653bee4450565302cec3a077066e1585c7224b8a5d0ad39",
    "fine-refined-v2-5": "951960a3c817c561053d09dda9371e3d13c0e4e9498b821cdac8dc4a1d5e7208",
    "fine-refined-v2-6": "4f9262b2ec0ab072361df828ce4c7625af20c094ce9e0b50345e69f57525761c",
    "fine-refined-v2-7": "e8085546fa0f7cef4c645781e5c2689325f2571499c55bf8efd916a0c66b9cde",
    "fine-refined-v2-8": "e405f0efcf67d00cfd3ece9fbe0f96a32af6480699f80372ca05fec862fbb93d",
    "fine-refined-v2-9": "4ef6aeb3e9b6a042745e9ca0f2fd5a8dda770807000266c9abc727ea641de0b9",
}


def export_plan() -> dict:
    """Font outline contract with a shared cap height, baseline and ink."""
    return dict(schema=1, source="WPF font outlines", font_family=FONT_FAMILY,
                font_weight=FONT_WEIGHT, ink_rgb=list(INK_RGB), scale=SCALE,
                cap_height=CAP_HEIGHT, baseline=BASELINE, alpha_threshold=ALPHA_THRESHOLD,
                native_advance=12, card_amount_aperture=False,
                game_executed=False, native_helper_executed=False,
                digits=[dict(name=spec.name, digit=spec.animation_frame,
                             logical_size=list(spec.logical_size),
                             active_size=list(spec.active_size),
                             native_anchor=list(DIGIT_GEOMETRY[spec.animation_frame][2:]))
                        for spec in ASSETS[1:]])


def encode_digit_alpha(digit: int, alpha: bytes) -> bytes:
    """Quantize only an own vector stencil into binary color-key coverage.

    A color-key device has no alpha blending. Never blend onto an invented
    paper rectangle; thresholding preserves the real card paper underneath.
    """
    if type(digit) is not int or not 0 <= digit <= 9:
        raise ValueError("Boetecijfer vereist een frame van nul tot en met negen.")
    spec = ASSETS[digit+1]
    w,h = spec.active_size
    if type(alpha) is not bytes or len(alpha) != w*h:
        raise ValueError("Boetecijfer vereist exact het grotere eigen vector-alpha-raster.")
    tw,th = spec.texture_size
    result = bytearray(struct.pack("<H",COLOR_KEY)*(tw*th))
    ink = struct.pack("<H",INK_RGB565)
    for y in range(h):
        for x in range(w):
            if alpha[y*w+x] >= ALPHA_THRESHOLD:
                offset = (y*tw+x)*2
                result[offset:offset+2] = ink
    return bytes(result)


def encode_rgb565(rgb: bytes, width: int, height: int, texture_size: tuple[int,int],
                  opacity: bytes) -> bytes:
    """Technical pixel-format/mask conversion, without resampling or retouching.

    The caller supplies RGB from the unchanged own card source and its original
    sprite opacity. In particular there is no separate amount cutout.
    """
    if (type(width) is not int or type(height) is not int or
            type(texture_size) is not tuple or len(texture_size) != 2 or
            any(type(edge) is not int or edge < 1 or edge > 2048 or edge & (edge-1)
                for edge in texture_size) or
            not 1 <= width <= texture_size[0] or not 1 <= height <= texture_size[1]):
        raise ValueError("Boetekaartconversie vereist begrensde echte afmetingen.")
    if (type(rgb) is not bytes or type(opacity) is not bytes or
            len(rgb) != width*height*3 or len(opacity) != width*height or
            any(value not in (0,255) for value in opacity)):
        raise ValueError("Boetekaartconversie vereist exact RGB en binair bronmasker.")
    tw,th = texture_size
    result = bytearray(struct.pack("<H",COLOR_KEY)*(tw*th))
    for p,visible in enumerate(opacity):
        if visible:
            r,g,b = rgb[p*3:p*3+3]
            value = ((r>>3)<<11)|((g>>2)<<5)|(b>>3)
            if value == COLOR_KEY:
                value = COLOR_KEY-1
            y,x = divmod(p,width)
            struct.pack_into("<H",result,(y*tw+x)*2,value)
    return bytes(result)


def load_assets(workspace: Path) -> tuple[native.NativeAsset, ...]:
    """Read exactly the new eleven pinned files; no writes or game execution."""
    from tools.trial_manifest import validate_ancestors
    if (set(ASSET_PINS) != {spec.name for spec in ASSETS} or
            any(type(pin) is not str or len(pin) != 64 or
                any(c not in "0123456789abcdef" for c in pin) for pin in ASSET_PINS.values())):
        raise ValueError("Nieuwe boetekaart en tien cijfers vereisen volledige gepinde eigen exports.")
    assets=[]
    for spec in ASSETS:
        path = Path(workspace)/ASSET_ROOT/(spec.name+".rgb565")
        validate_ancestors(path)
        if not path.is_file() or path.stat().st_size != spec.byte_count:
            raise ValueError(f"Nieuwe boeteasset ontbreekt of heeft afwijkende grootte: {spec.name}.")
        with path.open("rb") as stream:
            pixels=stream.read(spec.byte_count+1)
        if len(pixels)!=spec.byte_count or hashlib.sha256(pixels).hexdigest()!=ASSET_PINS[spec.name]:
            raise ValueError(f"Nieuwe boeteasset heeft afwijkende inhoud: {spec.name}.")
        options = dict(callers=native.CARD_CALLERS if spec.animation_frame is None else native.DIGIT_CALLERS)
        if spec.animation_frame is not None:
            options.update(animation_group=28,animation_frame=spec.animation_frame)
        asset=native.NativeAsset(spec.name,*spec.logical_size,*spec.texture_size,pixels,
                                 active_width=spec.active_size[0],active_height=spec.active_size[1],**options)
        asset.validate()
        assets.append(asset)
    return tuple(assets)
