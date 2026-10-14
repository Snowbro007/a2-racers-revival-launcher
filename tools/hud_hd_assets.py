"""Pure asset/layout contracts for the pinned A2-I cockpit HD experiment.

No file I/O, native execution, image resizing or artwork generation occurs here.
The source is the 395264-byte 069d39e8... A2SPEL.DAT; live sprite IDs are
one-based GAMESPR archive indices, as verified in the original loader.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct


SOURCE_SHA256 = "069d39e815fc631ef433550459e8105042cf740dfc311e4f9285d4cca148e726"
LOGICAL_WIDTH, LOGICAL_HEIGHT = 640, 480
COLOR_KEY_RGB565 = 0xF81F
MAX_TEXTURE_EDGE, MAX_TEXTURE_PIXELS = 4096, 4096 * 4096
TL_VERTEX = struct.Struct("<4f2I2f")


@dataclass(frozen=True)
class CockpitGroup:
    name: str
    group_index: int
    resource_indices: tuple[int, ...]
    logical_rect: tuple[int, int, int, int]  # x, y, width, height
    anchor: tuple[int, int]
    caller_vas: tuple[int, ...]  # CALL instruction, not saved return address
    native_cached_id_va: int | None

    @property
    def live_image_ids(self) -> tuple[int, ...]:
        return tuple(index + 1 for index in self.resource_indices)

    @property
    def caller_return_vas(self) -> tuple[int, ...]:
        return tuple(address + 5 for address in self.caller_vas)


# Order is the original cockpit draw order, not animation/resource order.
COCKPIT_GROUPS = (
    CockpitGroup("dashboard_strip", 0, (0,), (0, 267, 640, 36), (320, 17),
                 (0x409B9B,), None),
    CockpitGroup("steering_wheel", 4, tuple(range(75, 90)), (44, 348, 330, 132),
                 (320, 240), (0x409CDD, 0x409C64), 0x458C10),
    CockpitGroup("right_gauge", 3, tuple(range(248, 268)), (292, 328, 48, 49),
                 (24, 25), (0x409B67,), 0x458C14),
    CockpitGroup("speedometer", 1, tuple(range(55, 75)) + tuple(range(216, 236)),
                 (215, 320, 71, 69), (37, 34), (0x409A43,), 0x458C08),
    CockpitGroup("tachometer", 2, tuple(range(90, 110)), (135, 319, 70, 68),
                 (36, 36), (0x409AD5,), 0x458C0C),
)
COCKPIT_BY_NAME = {group.name: group for group in COCKPIT_GROUPS}

# Leave the native dynamic rectangles visible below a new HD background.
# The left gauge has no demonstrated animation group and remains native.
DASHBOARD_APERTURES = tuple(group.logical_rect for group in COCKPIT_GROUPS) + (
    (486, 377, 58, 58),  # native minimap: [486,377,544,435)
    (89, 329, 40, 45),  # static/unidentified small left gauge
)


@dataclass(frozen=True)
class SpriteCall:
    group: str
    resource_index: int
    live_image_id: int
    logical_rect: tuple[int, int, int, int]
    caller_va: int
    buffer_index: int

    @property
    def cache_key(self) -> tuple[str, tuple[int, int, int, int]]:
        # Both verified wheel routines share one logical animation role.
        return self.group, self.logical_rect


def classify_native_sprite_call(live_image_id: int, caller_va: int, x: int, y: int,
                                flags: int, buffer_index: int) -> SpriteCall | None:
    """Recognize only exact pinned cockpit calls to native 0x42b674.

    Native ABI: EAX buffer (0 front / 1 back / 2 third), EDX live ID,
    EBX x, ECX y, one stack DWORD flags. Known calls use flags=2 (top-left).
    A hook observing the saved return address must subtract five first.
    This function is a classifier, not authorization to overlay non-race frames;
    the caller also gates the race present site and dashboard enabled. Native
    state 8 exits the race loop; it is not an active-race enable value.
    """
    values = (live_image_id, caller_va, x, y, flags, buffer_index)
    if any(type(value) is not int for value in values) or flags != 2 or buffer_index not in (0, 1, 2):
        return None
    for group in COCKPIT_GROUPS:
        if (caller_va in group.caller_vas and live_image_id in group.live_image_ids
                and (x, y) == group.logical_rect[:2]):
            return SpriteCall(group.name, live_image_id - 1, live_image_id,
                              group.logical_rect, caller_va, buffer_index)
    return None


class CockpitFrameCache:
    """Bounded reference model for native draws skipped after redrawcounter=2.

    Production hooks must clear on race initialization, leaving race state,
    dashboard toggle or native resource-table replacement. A frame boundary
    alone does not clear the native game's unchanged meter/wheel images.
    """
    def __init__(self):
        self._frames: dict[str, SpriteCall] = {}

    def record(self, call: SpriteCall) -> None:
        if not isinstance(call, SpriteCall) or classify_native_sprite_call(
                call.live_image_id, call.caller_va, *call.logical_rect[:2], 2, call.buffer_index) != call:
            raise ValueError("HUD-cache vereist een exact geclassificeerde cockpitcall.")
        self._frames[call.group] = call

    def clear(self) -> None:
        self._frames.clear()

    def frames(self) -> tuple[SpriteCall, ...]:
        return tuple(self._frames[group.name] for group in COCKPIT_GROUPS if group.name in self._frames)


def _dimension(value: int, label: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_TEXTURE_EDGE:
        raise ValueError(f"Ongeldige HUD-afmeting: {label}.")
    return value


def _rect(rect: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(rect, tuple) or len(rect) != 4 or any(type(value) is not int for value in rect):
        raise ValueError("HUD-opening vereist vier gehele coördinaten.")
    x, y, w, h = rect
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError("HUD-opening valt buiten de logische afbeelding.")
    return rect


def scaled_key_rect(rect: tuple[int, int, int, int], logical_width: int, logical_height: int,
                    width: int, height: int) -> tuple[int, int, int, int]:
    """Conservatively scale a half-open logical aperture without clipping it."""
    for value, label in ((logical_width, "logical width"), (logical_height, "logical height"),
                         (width, "width"), (height, "height")):
        _dimension(value, label)
    x, y, w, h = _rect(rect, logical_width, logical_height)
    left, top = x * width // logical_width, y * height // logical_height
    right = ((x + w) * width + logical_width - 1) // logical_width
    bottom = ((y + h) * height + logical_height - 1) // logical_height
    return left, top, right - left, bottom - top


@dataclass(frozen=True)
class Rgb565Texture:
    width: int
    height: int
    padded_width: int
    padded_height: int
    logical_width: int
    logical_height: int
    pixels: bytes  # tightly packed padded rows, little-endian RGB565
    transparent_pixels: int
    opaque_key_collisions: int

    def __post_init__(self):
        for value, label in ((self.width, "width"), (self.height, "height"),
                             (self.padded_width, "padded width"), (self.padded_height, "padded height"),
                             (self.logical_width, "logical width"), (self.logical_height, "logical height")):
            _dimension(value, label)
        count = self.padded_width * self.padded_height
        if (self.padded_width < self.width or self.padded_height < self.height
                or self.padded_width & (self.padded_width - 1) or self.padded_height & (self.padded_height - 1)
                or count > MAX_TEXTURE_PIXELS or type(self.pixels) is not bytes or len(self.pixels) != count * 2
                or type(self.transparent_pixels) is not int or not 0 <= self.transparent_pixels <= count
                or type(self.opaque_key_collisions) is not int
                or not 0 <= self.opaque_key_collisions <= self.width * self.height):
            raise ValueError("HUD-texturerecord heeft ongecontroleerde afmetingen/pixels/aantallen.")

    @property
    def uv_bounds(self) -> tuple[float, float]:
        return self.width / self.padded_width, self.height / self.padded_height

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.pixels).hexdigest()


def pack_rgb565_texture(rgb: bytes, width: int, height: int, padded_width: int,
                        padded_height: int, *, logical_width: int = LOGICAL_WIDTH,
                        logical_height: int = LOGICAL_HEIGHT,
                        key_rects: tuple[tuple[int, int, int, int], ...] = (),
                        transparent_mask: bytes | None = None) -> Rgb565Texture:
    """Encode caller-supplied RGB888; fill apertures and power-of-two padding.

    The RGB image must already have the desired artwork resolution. No resample
    is performed. Mask bytes are 0 opaque / 1 transparent. Opaque colors that
    quantize to the reserved key become 0xF81E so they do not make unintended
    holes. DD upload must separately verify RGB565 masks and honor surface pitch.
    """
    for value, label in ((width, "width"), (height, "height"),
                         (padded_width, "padded width"), (padded_height, "padded height"),
                         (logical_width, "logical width"), (logical_height, "logical height")):
        _dimension(value, label)
    if (padded_width < width or padded_height < height
            or padded_width & (padded_width - 1) or padded_height & (padded_height - 1)
            or padded_width * padded_height > MAX_TEXTURE_PIXELS
            or type(rgb) is not bytes or len(rgb) != width * height * 3):
        raise ValueError("HUD-texture heeft geen exacte RGB-lengte of begrensde pow2-padding.")
    if not isinstance(key_rects, tuple) or len(key_rects) > 32:
        raise ValueError("HUD-openingen zijn niet begrensd.")
    if transparent_mask is not None and (type(transparent_mask) is not bytes
            or len(transparent_mask) != width * height or any(value > 1 for value in transparent_mask)):
        raise ValueError("HUD-transparantiemasker heeft geen exacte 0/1-lengte.")
    scaled = tuple(scaled_key_rect(rect, logical_width, logical_height, width, height)
                   for rect in key_rects)
    row_rects = tuple(tuple((x, x + w) for x, top, w, h in scaled if top <= y < top + h)
                     for y in range(height))
    output = bytearray(b"\x1f\xf8" * (padded_width * padded_height))
    transparent, collisions = padded_width * padded_height - width * height, 0
    for y in range(height):
        spans = row_rects[y]
        for x in range(width):
            index = y * width + x
            if ((transparent_mask is not None and transparent_mask[index])
                    or any(left <= x < right for left, right in spans)):
                transparent += 1
                continue
            r, g, b = rgb[index * 3:index * 3 + 3]
            color = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            if color == COLOR_KEY_RGB565:
                color ^= 1
                collisions += 1
            struct.pack_into("<H", output, (y * padded_width + x) * 2, color)
    return Rgb565Texture(width, height, padded_width, padded_height, logical_width,
                         logical_height, bytes(output), transparent, collisions)


def pack_tl_quad(texture: Rgb565Texture, logical_rect: tuple[int, int, int, int], *,
                 z: float = 0.0) -> bytes:
    """Four D3DTLVERTEX records in clockwise order for triangles 0,1,2/0,2,3.

    Coordinates remain logical pixels for the wrapper's high-resolution target.
    A rasterization half-pixel adjustment, if needed, belongs to native rendering
    and must be accepted at runtime; it is deliberately not guessed here.
    """
    if not isinstance(texture, Rgb565Texture) or type(z) not in (int, float) or not math.isfinite(z) or not 0 <= z <= 1:
        raise ValueError("Ongeldige HUD-TL-texture/diepte.")
    x, y, w, h = _rect(logical_rect, LOGICAL_WIDTH, LOGICAL_HEIGHT)
    u, v = texture.uv_bounds
    return b"".join(TL_VERTEX.pack(float(px), float(py), float(z), 1.0,
                                  0xFFFFFFFF, 0, tu, tv)
                    for px, py, tu, tv in ((x, y, 0.0, 0.0), (x + w, y, u, 0.0),
                                          (x + w, y + h, u, v), (x, y + h, 0.0, v)))
