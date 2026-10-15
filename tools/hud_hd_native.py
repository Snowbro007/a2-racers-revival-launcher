"""Construct an opt-in A2-I HUD helper as bytes; never execute or read a game.

The native sprite draw remains the fallback. Selected calls are collected and
drawn as textured TL quads immediately before the unchanged presentation call.
This module is version-bound design code, not Windows/driver runtime proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from tools.hud_hd_pe import PicX86


IMAGE_BASE = 0x400000
BACKEND = "isolated-device2-v2"
CODE_VA = 0x48D000
MAX_ASSETS = 32
MAX_COMMANDS = 64
MAX_TEXTURE_DIMENSION = 2048
MAX_PIXEL_BYTES = 64 * 1024 * 1024
TRANSPARENT_RGB565 = 0xF81F
SPRITE_ENTRY = 0x42B674
SPRITE_REPLAY = bytes.fromhex("56575583ec44")
PRESENT_CALL = 0x4019DA
PRESENT_BYTES = bytes.fromhex("e89e2f0100")
TEARDOWN_CALL = 0x4028FA
TEARDOWN_BYTES = bytes.fromhex("e89a4e0000")
CARD_CALLERS = (0x41228B,)
DIGIT_CALLERS = (0x4122A3, 0x4122BB, 0x4122D5, 0x4122F5)
NATIVE = {"ddraw": 0x475F1C, "d3d": 0x4764F8, "device": 0x4764FC,
          "backbuffer": 0x475F28, "device_guid": 0x476508,
          "images": 0x4770F0, "capacity": 0x45978C, "animations": 0x4770E8,
          "dashboard": 0x458C20, "accelerated": 0x458C1C,
          "width": 0x4592E4, "height": 0x4592E8}
STATE = {name: index * 4 for index, name in enumerate((
    "ready", "disabled", "queue_count", "ddraw", "d3d", "device",
    "viewport", "viewport_added", "execute", "locked_surface", "locked_pixels",
    "execute_locked", "last_hr", "scene_open", "draw_count", "failure_count"))}
STATE["queue_overflow"] = 0x1D0
STATE["failed_device"] = 0x1D4
STATE["device2"] = 0x1D8
STATE.update(last_stage=0x1DC, asset_index=0x1E0, failure_stage=0x1E4,
             failure_asset_index=0x1E8, native_identity=0x1EC,
             own_identity=0x1F0, backbuffer=0x1F4, d3d2=0x1F8,
             failed_backbuffer=0x1FC)
NO_ASSET = 0xFFFFFFFF
STAGES = dict(idle=0, query_d3d2=1, create_device2=2, query_native_identity=3,
              query_own_identity=4, verify_distinct_identity=5, create_viewport2=6,
              add_viewport=7, set_viewport=8, set_current_viewport=9,
              create_source_surface=10, lock_source=11, unlock_source=12,
              set_source_color_key=13, query_source_texture2=14,
              create_destination_surface=15, set_destination_color_key=16,
              query_destination_texture2=17, load_texture2=18,
              get_texture_handle=19, set_render_states=20, check_surface_loss=21,
              begin_scene=22, set_texture=23, draw_indexed_primitive=24, end_scene=25)
SURFACE_DESC, LOCK_DESC, EXEC_DESC, EXEC_DATA = 0x40, 0xB0, 0x120, 0x140
VIEWPORT_DESC, COLOR_KEY = 0x180, 0x1B0
PACKET, QUEUE, RECORDS, RECORD_SIZE = 0x200, 0x400, 0x900, 64
IID_TEXTURE1 = bytes.fromhex("e0d9dc2ca025cf11a31a00aa00b93356")
IID_DEVICE2 = bytes.fromhex("01152893f88cd01189ab00a0c9054129")
INDICES, UNKNOWN_IID, TEXTURE_IID, D3D2_IID = 0x810, 0x820, 0x830, 0x840
IID_UNKNOWN = bytes.fromhex("0000000000000000c000000000000046")
IID_TEXTURE2 = bytes.fromhex("02152893f88cd01189ab00a0c9054129")
IID_D3D2 = bytes.fromhex("c11eae6a2a66d011889d00aa00bbb76a")
OWN_RENDER_STATES = ((7, 0), (14, 0), (28, 0), (27, 0), (41, 1),
                     (21, 7), (17, 1), (18, 1), (22, 1), (15, 0), (8, 3))
REG = {name: index for index, name in enumerate(("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi"))}


@dataclass(frozen=True)
class AtlasFrame:
    animation_frame: int
    pixel_rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class NativeAsset:
    name: str
    logical_width: int
    logical_height: int
    texture_width: int
    texture_height: int
    pixels_rgb565: bytes
    active_width: int | None = None
    active_height: int | None = None
    callers: tuple[int, ...] = ()
    animation_group: int | None = None
    animation_frame: int | None = None
    fixed_rect: tuple[int, int, int, int] | None = None
    require_dashboard: bool = False
    cached_role: str | None = None
    atlas_frames: tuple[AtlasFrame, ...] = ()

    def validate(self):
        if not self.name or not isinstance(self.pixels_rgb565, bytes):
            raise ValueError("Assetnaam en immutable RGB565-bytes zijn vereist.")
        if not (1 <= self.logical_width <= 640 and 1 <= self.logical_height <= 480):
            raise ValueError("Logische HUD-afmetingen vallen buiten 640×480.")
        for value in (self.texture_width, self.texture_height):
            if not isinstance(value, int) or value < 1 or value > MAX_TEXTURE_DIMENSION or value & (value - 1):
                raise ValueError("Texture-afmetingen moeten begrensde powers of two zijn.")
        if len(self.pixels_rgb565) != self.texture_width * self.texture_height * 2:
            raise ValueError("RGB565-bytecount past niet bij de texture-afmetingen.")
        if not (1 <= self.active_width_or_full <= self.texture_width and
                1 <= self.active_height_or_full <= self.texture_height):
            raise ValueError("Actieve texturecrop valt buiten de texture.")
        if self.fixed_rect is not None:
            if self.callers or self.animation_group is not None:
                raise ValueError("Vaste achtergrond en sprite-selector zijn afzonderlijke assets.")
            x, y, width, height = self.fixed_rect
            if (width, height) != (self.logical_width, self.logical_height) or not (
                    0 <= x < 640 and 0 <= y < 480 and x + width <= 640 and y + height <= 480):
                raise ValueError("Vaste rectangle past niet op het logische HUD.")
        elif not self.callers:
            raise ValueError("Sprite-assets vereisen een concrete caller-allowlist.")
        if any(not isinstance(value, int) or not IMAGE_BASE <= value < CODE_VA for value in self.callers):
            raise ValueError("Caller is geen native A2-I codeadres.")
        if self.cached_role is not None:
            from tools.hud_hd_assets import COCKPIT_BY_NAME
            group = COCKPIT_BY_NAME.get(self.cached_role)
            if (group is None or self.animation_group != group.group_index or
                    self.animation_frame is not None or self.fixed_rect is not None or
                    not self.require_dashboard or set(self.callers) != set(group.caller_return_vas) or
                    len(self.callers) != len(group.caller_return_vas) or
                    (self.logical_width, self.logical_height) != group.logical_rect[2:] or
                    type(self.atlas_frames) is not tuple or not self.atlas_frames):
                raise ValueError("Cockpitatlas vereist de exacte gepinde rol, callers, groep en geometrie.")
            seen = set()
            for frame in self.atlas_frames:
                if (not isinstance(frame, AtlasFrame) or type(frame.animation_frame) is not int or
                        not 0 <= frame.animation_frame < len(group.resource_indices) or
                        frame.animation_frame in seen or type(frame.pixel_rect) is not tuple or
                        len(frame.pixel_rect) != 4 or any(type(value) is not int for value in frame.pixel_rect)):
                    raise ValueError("Cockpitframe is ongeldig of dubbel geselecteerd.")
                x, y, width, height = frame.pixel_rect
                if (x < 0 or y < 0 or width < 1 or height < 1 or
                        x + width > self.active_width_or_full or y + height > self.active_height_or_full):
                    raise ValueError("Cockpitframe valt buiten de actieve atlas.")
                seen.add(frame.animation_frame)
        elif self.atlas_frames:
            raise ValueError("Atlasframes vereisen een gepinde cached cockpitrol.")
        elif (self.animation_group is None) != (self.animation_frame is None):
            raise ValueError("Animatiegroep en frame moeten samen worden opgegeven.")
        if self.animation_group is not None and not (
                0 <= self.animation_group < 128 and (self.cached_role is not None or
                                                    0 <= self.animation_frame < 256)):
            raise ValueError("Animatieselector is buiten de begrenzing.")

    @property
    def active_width_or_full(self):
        return self.texture_width if self.active_width is None else self.active_width

    @property
    def active_height_or_full(self):
        return self.texture_height if self.active_height is None else self.active_height


@dataclass(frozen=True)
class NativeBundle:
    code: bytes
    state: bytes
    labels: dict[str, int]
    state_offsets: dict[str, int]
    asset_offsets: tuple[int, ...]
    pixel_offsets: tuple[int, ...]
    code_va: int
    state_va: int
    packet_instruction_offset: int
    packet_instruction_length: int


def _cockpit_layout(assets):
    """Allocate the optional cache after records; baseline v2 bytes stay exact."""
    from tools.hud_hd_assets import COCKPIT_GROUPS
    roles = tuple(group for group in COCKPIT_GROUPS
                  if any(asset.cached_role == group.name for asset in assets))
    if not roles: return None
    offset = (RECORDS + len(assets) * RECORD_SIZE + 15) & ~15
    commands = {}
    for group in roles:
        commands[group.name] = offset
        offset += 16
    frames = {}
    for index, asset in enumerate(assets):
        if asset.cached_role is not None:
            frames[index] = offset
            offset += 16 * len(asset.atlas_frames)
    fields = {"cockpit_" + name: 0x850 + index * 4 for index, name in enumerate(
              ("images", "animations", "dashboard", "device", "backbuffer", "capacity"))}
    frame_fields = {"cockpit_frame_table_" + group.name: 0x868 + index * 4
                    for index, group in enumerate(roles)}
    return dict(roles=roles, commands=commands, frames=frames, fields=fields,
                frame_fields=frame_fields, end=offset)


def _u32(value):
    return struct.pack("<I", value & 0xFFFFFFFF)


def _f32(value):
    return struct.pack("<f", value)


class _Emitter:
    def __init__(self, code_va, state_va):
        self.code = PicX86(code_va, state_va)
        self.code_va, self.state_va = code_va, state_va

    def hex(self, value): self.code.hex(value)
    def label(self, value): self.code.label(value)
    def branch(self, opcode, label): self.code.branch(bytes.fromhex(opcode), label)
    def call(self, label): self.branch("e8", label)
    def jump(self, label): self.branch("e9", label)

    def load(self, reg, offset, native=False):
        opcode = bytes((0x8B, 0x85 + 8 * REG[reg]))
        self.code.relative(opcode, offset if native else self.state_va + offset)

    def store(self, reg, offset):
        self.code.state(bytes((0x89, 0x85 + 8 * REG[reg])), offset)

    def lea(self, reg, offset, native=False):
        opcode = bytes((0x8D, 0x85 + 8 * REG[reg]))
        self.code.relative(opcode, offset if native else self.state_va + offset)

    def set(self, offset, value):
        self.code.state(b"\xc7\x85", offset)
        self.code.emit(_u32(value))

    def compare(self, offset, value):
        self.code.state(b"\x81\xbd", offset)
        self.code.emit(_u32(value))

    def immediate(self, reg, value):
        self.code.emit(bytes((0xC7, 0xC0 + REG[reg])) + _u32(value))

    def push_imm(self, value): self.code.emit(b"\x68" + _u32(value))

    def com(self, pointer_offset, slot, arguments=(), stage=None, asset_index=NO_ASSET):
        """Arguments are emitted in reverse; receiver is the final push."""
        if stage is not None: self.stage(stage, asset_index)
        for kind, value in reversed(arguments):
            if kind == "imm": self.push_imm(value)
            elif kind == "addr": self.lea("eax", value); self.hex("50")
            elif kind == "native_addr": self.lea("eax", value, native=True); self.hex("50")
            elif kind == "value": self.load("eax", value); self.hex("50")
            elif kind == "reg": self.code.emit(bytes((0x50 + REG[value],)))
            else: raise ValueError("Onbekend COM-argument.")
        self.load("eax", pointer_offset)
        self.hex("8b1050")
        if slot <= 127: self.code.emit(bytes((0xFF, 0x52, slot)))
        else: self.code.emit(b"\xff\x92" + _u32(slot))

    def stage(self, name, asset_index=NO_ASSET):
        self.set(STATE["last_stage"], STAGES[name])
        if asset_index is not None: self.set(STATE["asset_index"], asset_index)

    def latch_failure(self):
        for source, destination in (("last_stage", "failure_stage"),
                                    ("asset_index", "failure_asset_index")):
            self.load("eax", STATE[source]); self.store("eax", STATE[destination])
        self.load("eax", NATIVE["device"], native=True)
        self.store("eax", STATE["failed_device"])
        self.load("eax", NATIVE["backbuffer"], native=True)
        self.store("eax", STATE["failed_backbuffer"])

    def failed(self, label):
        self.store("eax", STATE["last_hr"])
        self.hex("85c0")
        self.branch("0f85", label)

    def pointer(self, offset, label):
        self.load("eax", offset)
        self.hex("85c0")
        self.branch("0f84", label)


def _initial_state(assets, cockpit=None):
    size = RECORDS + len(assets) * RECORD_SIZE
    size = (size + 15) & ~15
    if cockpit is not None: size = (cockpit["end"] + 15) & ~15
    data = bytearray(size)
    assert all(offset + 4 <= SURFACE_DESC or
               0x1D0 <= offset < PACKET for offset in STATE.values())
    data[UNKNOWN_IID:UNKNOWN_IID + 16] = IID_UNKNOWN
    data[TEXTURE_IID:TEXTURE_IID + 16] = IID_TEXTURE2
    data[D3D2_IID:D3D2_IID + 16] = IID_D3D2
    struct.pack_into("<HHHHHH", data, INDICES, 0, 1, 2, 0, 2, 3)
    for name in ("asset_index", "failure_asset_index"):
        struct.pack_into("<I", data, STATE[name], NO_ASSET)
    struct.pack_into("<II", data, COLOR_KEY, TRANSPARENT_RGB565, TRANSPARENT_RGB565)
    struct.pack_into("<I", data, VIEWPORT_DESC, 0x2C)
    struct.pack_into("<IIII", data, VIEWPORT_DESC + 4, 0, 0, 640, 480)
    struct.pack_into("<ffffff", data, VIEWPORT_DESC + 20, 320.0, 240.0, 1.0, 1.0, 0.0, 1.0)
    if cockpit is not None:
        for offset in cockpit["commands"].values(): struct.pack_into("<I", data, offset, NO_ASSET)
    pixels = []
    for index, asset in enumerate(assets):
        record = RECORDS + index * RECORD_SIZE
        struct.pack_into("<IIII", data, record + 20, asset.logical_width, asset.logical_height,
                         asset.texture_width, asset.texture_height)
        struct.pack_into("<ffff", data, record + 36, float(asset.logical_width), float(asset.logical_height),
                         asset.active_width_or_full / asset.texture_width,
                         asset.active_height_or_full / asset.texture_height)
        if asset.cached_role is not None:
            frame_offset = cockpit["frames"][index]
            struct.pack_into("<II", data, record + 52, frame_offset, len(asset.atlas_frames))
            for ordinal, frame in enumerate(asset.atlas_frames):
                x, y, width, height = frame.pixel_rect
                struct.pack_into("<ffff", data, frame_offset + ordinal * 16,
                                 x / asset.texture_width, y / asset.texture_height,
                                 (x + width) / asset.texture_width, (y + height) / asset.texture_height)
        pixels.append(len(data))
        data.extend(asset.pixels_rgb565)
        data.extend(b"\0" * ((-len(data)) & 15))
    # Four TL vertices are passed directly to the separately created Device2.
    # No legacy Execute instructions or native renderstate snapshots exist.
    for vertex in range(4):
        struct.pack_into("<ffII", data, PACKET + vertex * 32 + 8, 0.0, 1.0, 0xFFFFFFFF, 0)
    return data, tuple(pixels)


def build_helper(assets: tuple[NativeAsset, ...] | list[NativeAsset], *, code_va=CODE_VA,
                 state_va=0x4A0000, focus_state_va=0x45A400,
                 cleanup_target_va=0x407799) -> NativeBundle:
    """Return relocatable helper/data bytes and hook entrypoints, without a PE."""
    assets = tuple(assets)
    if not 1 <= len(assets) <= MAX_ASSETS or len({asset.name for asset in assets}) != len(assets):
        raise ValueError("Eén tot 32 uniek benoemde HUD-assets zijn vereist.")
    for asset in assets: asset.validate()
    if sum(len(asset.pixels_rgb565) for asset in assets) > MAX_PIXEL_BYTES:
        raise ValueError("Ingebedde HUD-textures overschrijden 64 MiB.")
    if code_va < CODE_VA or state_va <= code_va or code_va & 0xFFF or state_va & 0xFFF:
        raise ValueError("Helpersecties vereisen afzonderlijke gealigneerde RVA's.")
    if type(cleanup_target_va) is not int or not IMAGE_BASE <= cleanup_target_va < CODE_VA:
        raise ValueError("Cleanupchain vereist een native/gepind helper-codeadres.")
    cockpit = _cockpit_layout(assets)
    if cockpit is not None:
        for group in cockpit["roles"]:
            frames = [frame.animation_frame for asset in assets if asset.cached_role == group.name
                      for frame in asset.atlas_frames]
            if len(frames) != len(set(frames)):
                raise ValueError("Cockpitframes mogen niet in meerdere atlassen van dezelfde rol voorkomen.")
    data, pixel_offsets = _initial_state(assets, cockpit)
    e = _Emitter(code_va, state_va)

    # A sprite-entry JMP retains its original return address and one stack arg.
    e.label("capture")
    e.hex("9c60")
    e.code.base()
    e.hex("837c241c01")  # saved EAX: back buffer only.
    e.branch("0f85", "capture_end")
    if cockpit is not None: e.call("cockpit_sync")
    e.compare(STATE["queue_count"], MAX_COMMANDS)
    e.branch("0f83", "capture_overflow")
    e.load("eax", NATIVE["images"], native=True)
    e.hex("85c0")
    e.branch("0f84", "capture_invalid_images" if cockpit is not None else "capture_end")
    e.hex("8b74241485f6")  # saved EDX live ID, reject negative.
    e.branch("0f88", "capture_invalid_images" if cockpit is not None else "capture_end")
    e.load("edx", NATIVE["capacity"], native=True)
    e.hex("39d6")
    e.branch("0f87", "capture_invalid_images" if cockpit is not None else "capture_end")  # Inclusive maximum.
    e.hex("c1e60501c6")  # ESI = image record.
    if cockpit is not None:
        for group in cockpit["roles"]:
            selected, next_role = "cockpit_select_" + group.name, "cockpit_next_" + group.name
            for caller in group.caller_return_vas:
                e.lea("eax", caller, native=True); e.hex("39442424")
                e.branch("0f84", selected)
            e.jump(next_role)
            e.label(selected)
            command = cockpit["commands"][group.name]
            e.set(command, NO_ASSET)  # A changed but unsupported frame uses native.
            e.load("eax", NATIVE["dashboard"], native=True)
            e.hex("85c0"); e.branch("0f84", "capture_end")
            for saved_offset, expected in ((0x28, 2), (0x10, group.logical_rect[0]),
                                           (0x18, group.logical_rect[1])):
                e.code.emit(b"\x81\x7c\x24" + bytes((saved_offset,)) + _u32(expected))
                e.branch("0f85", "capture_end")
            for field, expected in ((8, group.logical_rect[2]), (12, group.logical_rect[3])):
                e.code.emit(b"\x81\x7e" + bytes((field,)) + _u32(expected))
                e.branch("0f85", "capture_end")
            e.hex("837e1c00"); e.branch("0f84", "capture_end")
            e.load("edx", NATIVE["animations"], native=True)
            e.hex("85d2"); e.branch("0f84", "capture_end")
            e.code.emit(b"\x8b\x92" + _u32(group.group_index * 12 + 8))
            e.hex("85d2"); e.branch("0f84", "capture_end")
            for index, asset in enumerate(assets):
                if asset.cached_role != group.name: continue
                for ordinal, frame in enumerate(asset.atlas_frames):
                    label = f"cockpit_frame_{index}_{ordinal}"
                    e.code.emit(b"\x8b\x82" + _u32(frame.animation_frame * 8 + 4))
                    e.hex("39442414"); e.branch("0f85", label)
                    e.set(command, index)
                    e.set(command + 4, struct.unpack("<I", _f32(group.logical_rect[0]))[0])
                    e.set(command + 8, struct.unpack("<I", _f32(group.logical_rect[1]))[0])
                    e.set(command + 12, ordinal + 1)
                    e.jump("capture_end")
                    e.label(label)
            e.jump("capture_end")
            e.label(next_role)
    for index, asset in enumerate(assets):
        if asset.fixed_rect is not None or asset.cached_role is not None: continue
        select, matched, next_asset = f"select_{index}", f"matched_{index}", f"next_{index}"
        for caller in asset.callers:
            e.lea("eax", caller, native=True)
            e.hex("39442424")
            e.branch("0f84", select)
        e.jump(next_asset)
        e.label(select)
        if asset.animation_group is not None:
            e.load("eax", NATIVE["animations"], native=True)
            e.hex("85c0"); e.branch("0f84", next_asset)
            e.code.emit(b"\x8b\x80" + _u32(asset.animation_group * 12 + 8))
            e.hex("85c0"); e.branch("0f84", next_asset)
            e.code.emit(b"\x8b\x80" + _u32(asset.animation_frame * 8 + 4))
            e.hex("39442414"); e.branch("0f85", next_asset)
        e.code.emit(b"\x81\x7e\x08" + _u32(asset.logical_width))
        e.branch("0f85", next_asset)
        e.code.emit(b"\x81\x7e\x0c" + _u32(asset.logical_height))
        e.branch("0f85", next_asset)
        e.hex("837e1c00"); e.branch("0f84", next_asset)
        e.immediate("eax", index)
        e.jump("capture_store")
        e.label(next_asset)
    e.jump("capture_end")
    e.label("capture_store")
    e.load("edi", STATE["queue_count"])
    e.hex("c1e704")
    e.lea("edx", QUEUE)
    e.hex("01d78907")
    e.hex("8b4424108b542418")  # native x/y saved.
    e.hex("f744242802000000")
    e.branch("0f85", "capture_top_left")
    e.hex("2b46102b5614")
    e.label("capture_top_left")
    e.hex("894704895708db4704d95f04db4708d95f08")
    e.code.state(b"\xff\x85", STATE["queue_count"])
    e.jump("capture_end")
    e.label("capture_overflow")
    e.set(STATE["queue_overflow"], 1)
    if cockpit is not None:
        e.label("capture_invalid_images")
        e.call("cockpit_clear")
    e.label("capture_end")
    e.hex("619d")
    e.code.emit(SPRITE_REPLAY)
    e.code.jump_native(SPRITE_ENTRY + len(SPRITE_REPLAY))

    e.label("present")
    e.hex("9c60")
    e.code.base()
    e.call("flush")
    e.hex("619d")
    e.code.jump_native(0x41497D)

    # Optional lifecycle hook: a caller may invoke reset before native teardown.
    # It does not call a native cleanup function itself and preserves its ABI.
    e.label("reset")
    e.hex("9c60")
    e.code.base()
    e.call("cleanup")
    if cockpit is not None:
        e.call("cockpit_clear")
        for offset in (*cockpit["fields"].values(), *cockpit["frame_fields"].values()): e.set(offset, 0)
    for name in ("disabled", "failed_device", "failed_backbuffer", "queue_count",
                 "queue_overflow", "last_stage", "failure_stage", "last_hr"):
        e.set(STATE[name], 0)
    for name in ("asset_index", "failure_asset_index"): e.set(STATE[name], NO_ASSET)
    e.hex("619dc3")

    e.label("teardown")
    e.call("reset")
    e.code.jump_native(cleanup_target_va)

    e.label("flush")
    if cockpit is not None: e.call("cockpit_sync")
    e.compare(STATE["queue_overflow"], 0); e.branch("0f85", "flush_end")
    if focus_state_va is not None:
        for offset, expected in ((0, 1), (4, 1), (8, 0), (12, 0)):
            e.code.relative(b"\x81\xbd", focus_state_va + offset)
            e.code.emit(_u32(expected))
            e.branch("0f85", "flush_end")
    # This first trial is tied to the proven logical high-resolution HUD path.
    e.load("eax", NATIVE["accelerated"], native=True)
    e.hex("85c0"); e.branch("0f84", "flush_invalid_context")
    for key, expected in (("width", 640), ("height", 480)):
        e.load("eax", NATIVE[key], native=True)
        e.code.emit(b"\x3d" + _u32(expected))
        e.branch("0f85", "flush_invalid_context")
    e.load("eax", NATIVE["device"], native=True)
    e.hex("85c0"); e.branch("0f84", "flush_invalid_context")
    e.load("ecx", NATIVE["backbuffer"], native=True)
    e.hex("85c9"); e.branch("0f84", "flush_invalid_context")
    e.load("edx", STATE["failed_device"])
    e.hex("85d2"); e.branch("0f84", "flush_check_retained")
    e.hex("39c2"); e.branch("0f85", "flush_clear_failure")
    e.load("edx", STATE["failed_backbuffer"])
    e.hex("39ca"); e.branch("0f84", "flush_end")
    e.label("flush_clear_failure")
    e.set(STATE["disabled"], 0)
    e.set(STATE["failed_device"], 0)
    e.set(STATE["failed_backbuffer"], 0)
    e.label("flush_check_retained")
    e.load("edx", STATE["device"])
    e.hex("85d2"); e.branch("0f84", "flush_same_device")
    e.hex("39c2"); e.branch("0f85", "flush_changed_context")
    e.load("edx", STATE["backbuffer"])
    e.hex("39ca"); e.branch("0f84", "flush_same_device")
    e.label("flush_changed_context")
    e.call("cleanup")
    e.set(STATE["disabled"], 0)
    e.label("flush_same_device")
    e.compare(STATE["disabled"], 0); e.branch("0f85", "flush_end")
    e.compare(STATE["ready"], 0); e.branch("0f85", "flush_recover")
    e.call("initialize")
    e.compare(STATE["ready"], 1); e.branch("0f85", "flush_end")
    e.label("flush_recover")
    # Retained source bytes permit bounded full recreation when a surface is
    # lost. Recreate also refreshes every Texture1 handle; no stale comparisons.
    e.com(STATE["backbuffer"], 0x60, stage="check_surface_loss")
    e.failed("flush_lost")
    for index in range(len(assets)):
        record = RECORDS + index * RECORD_SIZE
        for offset in (record, record + 8):
            e.com(offset, 0x60, stage="check_surface_loss", asset_index=index)
            e.failed("flush_lost")
    e.jump("flush_draw")
    e.label("flush_lost")
    e.call("cleanup")
    e.call("initialize")
    e.compare(STATE["ready"], 1); e.branch("0f85", "flush_end")
    e.label("flush_draw")
    e.com(STATE["device2"], 0x28, stage="begin_scene")
    e.failed("flush_failed")
    e.set(STATE["scene_open"], 1)
    for index, asset in enumerate(assets):
        if asset.fixed_rect is None: continue
        if asset.require_dashboard:
            e.load("eax", NATIVE["dashboard"], native=True)
            e.hex("85c0"); e.branch("0f84", f"fixed_skip_{index}")
        x, y, _, _ = asset.fixed_rect
        e.set(QUEUE + MAX_COMMANDS * 16, index)
        e.set(QUEUE + MAX_COMMANDS * 16 + 4, struct.unpack("<I", _f32(x))[0])
        e.set(QUEUE + MAX_COMMANDS * 16 + 8, struct.unpack("<I", _f32(y))[0])
        e.lea("edi", QUEUE + MAX_COMMANDS * 16)
        e.call("draw_command")
        e.hex("85c0"); e.branch("0f85", "flush_failed")
        e.label(f"fixed_skip_{index}")
    if cockpit is not None:
        for group in cockpit["roles"]:
            command = cockpit["commands"][group.name]
            e.compare(command, NO_ASSET); e.branch("0f84", "cockpit_skip_" + group.name)
            e.lea("edi", command)
            e.call("draw_command")
            e.hex("85c0"); e.branch("0f85", "flush_failed")
            e.label("cockpit_skip_" + group.name)
    e.load("esi", STATE["queue_count"])
    e.lea("edi", QUEUE)
    e.label("flush_queue")
    e.hex("85f6"); e.branch("0f84", "flush_scene_end")
    e.hex("5657")
    e.call("draw_command")
    e.hex("5f5e85c0"); e.branch("0f85", "flush_failed")
    e.hex("83c7104e")
    e.jump("flush_queue")
    e.label("flush_scene_end")
    e.com(STATE["device2"], 0x2C, stage="end_scene")
    e.failed("flush_failed")
    e.set(STATE["scene_open"], 0)
    e.jump("flush_end")
    e.label("flush_failed")
    e.code.state(b"\xff\x85", STATE["failure_count"])
    e.latch_failure()
    e.call("cleanup")
    e.set(STATE["disabled"], 1)
    e.jump("flush_end")
    e.label("flush_invalid_context")
    e.call("cleanup")
    if cockpit is not None: e.call("cockpit_clear")
    e.set(STATE["disabled"], 0)
    e.set(STATE["failed_device"], 0)
    e.set(STATE["failed_backbuffer"], 0)
    e.label("flush_end")
    e.set(STATE["queue_count"], 0)
    e.set(STATE["queue_overflow"], 0)
    e.hex("c3")

    e.label("initialize")
    for name in ("ddraw", "d3d", "device", "backbuffer"):
        e.load("eax", NATIVE[name], native=True)
        e.hex("85c0"); e.branch("0f84", "initialize_null")
        e.store("eax", STATE[name])
        e.com(STATE[name], 4)
    e.com(STATE["backbuffer"], 0x60, stage="check_surface_loss")
    e.failed("initialize_failed")
    e.com(STATE["d3d"], 0, (("addr", D3D2_IID), ("addr", STATE["d3d2"])), stage="query_d3d2")
    e.failed("initialize_failed"); e.pointer(STATE["d3d2"], "initialize_null")
    e.com(STATE["d3d2"], 0x20, (("native_addr", NATIVE["device_guid"]),
          ("value", STATE["backbuffer"]), ("addr", STATE["device2"])), stage="create_device2")
    e.failed("initialize_failed"); e.pointer(STATE["device2"], "initialize_null")
    # Canonical IUnknown identities must differ before any viewport or state
    # operation. Different interface pointers alone do not prove isolation.
    e.com(STATE["device"], 0, (("addr", UNKNOWN_IID), ("addr", STATE["native_identity"])),
          stage="query_native_identity")
    e.failed("initialize_failed"); e.pointer(STATE["native_identity"], "initialize_null")
    e.com(STATE["device2"], 0, (("addr", UNKNOWN_IID), ("addr", STATE["own_identity"])),
          stage="query_own_identity")
    e.failed("initialize_failed"); e.pointer(STATE["own_identity"], "initialize_null")
    e.stage("verify_distinct_identity")
    e.load("eax", STATE["native_identity"]); e.load("edx", STATE["own_identity"])
    e.hex("39d0"); e.branch("0f84", "initialize_null")
    e.com(STATE["d3d2"], 0x18, (("addr", STATE["viewport"]), ("imm", 0)),
          stage="create_viewport2")
    e.failed("initialize_failed"); e.pointer(STATE["viewport"], "initialize_null")
    e.com(STATE["device2"], 0x18, (("value", STATE["viewport"]),), stage="add_viewport")
    e.failed("initialize_failed")
    e.set(STATE["viewport_added"], 1)
    e.com(STATE["viewport"], 0x14, (("addr", VIEWPORT_DESC),), stage="set_viewport")
    e.failed("initialize_failed")
    e.com(STATE["device2"], 0x34, (("value", STATE["viewport"]),), stage="set_current_viewport")
    e.failed("initialize_failed")
    for index, asset in enumerate(assets):
        record = RECORDS + index * RECORD_SIZE
        e.set(SURFACE_DESC, 0x6C); e.set(SURFACE_DESC + 4, 0x1007)
        e.set(SURFACE_DESC + 8, asset.texture_height); e.set(SURFACE_DESC + 12, asset.texture_width)
        e.set(SURFACE_DESC + 0x48, 32); e.set(SURFACE_DESC + 0x4C, 0x40)
        e.set(SURFACE_DESC + 0x54, 16)
        for field, value in ((0x58, 0xF800), (0x5C, 0x7E0), (0x60, 0x1F), (0x68, 0x1800)):
            e.set(SURFACE_DESC + field, value)
        e.com(STATE["ddraw"], 0x18, (("addr", SURFACE_DESC), ("addr", record), ("imm", 0)),
              stage="create_source_surface", asset_index=index)
        e.failed("initialize_failed"); e.pointer(record, "initialize_null")
        e.load("eax", record); e.store("eax", STATE["locked_surface"])
        e.set(LOCK_DESC, 0x6C)
        e.com(record, 0x64, (("imm", 0), ("addr", LOCK_DESC), ("imm", 1), ("imm", 0)),
              stage="lock_source", asset_index=index)
        e.failed("initialize_unlock_clear")
        e.load("edi", LOCK_DESC + 0x24); e.store("edi", STATE["locked_pixels"])
        e.hex("85ff"); e.branch("0f84", "initialize_null")
        for field, expected in ((8, asset.texture_height), (12, asset.texture_width),
                                (0x54, 16), (0x58, 0xF800), (0x5C, 0x7E0), (0x60, 0x1F)):
            e.compare(LOCK_DESC + field, expected); e.branch("0f85", "initialize_null")
        e.load("ebx", LOCK_DESC + 0x10)
        e.code.emit(b"\x81\xfb" + _u32(asset.texture_width * 2))
        e.branch("0f82", "initialize_null")
        e.code.emit(b"\x81\xfb" + _u32(0x100000))
        e.branch("0f87", "initialize_null")
        e.lea("esi", pixel_offsets[index])
        e.immediate("edx", asset.texture_height)
        e.label(f"copy_row_{index}")
        e.hex("57fc")
        e.immediate("ecx", asset.texture_width * 2)
        e.hex("f3a45f01df4a")
        e.branch("0f85", f"copy_row_{index}")
        e.com(record, 0x80, (("value", STATE["locked_pixels"]),), stage="unlock_source", asset_index=index)
        e.failed("initialize_failed")
        e.set(STATE["locked_surface"], 0); e.set(STATE["locked_pixels"], 0)
        e.com(record, 0x74, (("imm", 8), ("addr", COLOR_KEY)), stage="set_source_color_key", asset_index=index)
        e.failed("initialize_failed")
        e.com(record, 0, (("addr", TEXTURE_IID), ("addr", record + 4)),
              stage="query_source_texture2", asset_index=index)
        e.failed("initialize_failed"); e.pointer(record + 4, "initialize_null")
        e.set(SURFACE_DESC + 0x68, 0x04001000)
        e.com(STATE["ddraw"], 0x18, (("addr", SURFACE_DESC), ("addr", record + 8), ("imm", 0)),
              stage="create_destination_surface", asset_index=index)
        e.failed("initialize_failed"); e.pointer(record + 8, "initialize_null")
        e.com(record + 8, 0x74, (("imm", 8), ("addr", COLOR_KEY)),
              stage="set_destination_color_key", asset_index=index)
        e.failed("initialize_failed")
        e.com(record + 8, 0, (("addr", TEXTURE_IID), ("addr", record + 12)),
              stage="query_destination_texture2", asset_index=index)
        e.failed("initialize_failed"); e.pointer(record + 12, "initialize_null")
        e.com(record + 12, 0x14, (("value", record + 4),), stage="load_texture2", asset_index=index)
        e.failed("initialize_failed")
        e.com(record + 12, 0x0C, (("value", STATE["device2"]), ("addr", record + 16)),
              stage="get_texture_handle", asset_index=index)
        e.failed("initialize_failed"); e.pointer(record + 16, "initialize_null")
    for key, value in OWN_RENDER_STATES:
        e.com(STATE["device2"], 0x5C, (("imm", key), ("imm", value)), stage="set_render_states")
        e.failed("initialize_failed")
    e.set(STATE["ready"], 1)
    e.hex("c3")
    e.label("initialize_unlock_clear")
    # A failed Lock never creates a lock which cleanup should try to unlock.
    e.set(STATE["locked_surface"], 0)
    e.jump("initialize_failed")
    e.label("initialize_null")
    e.set(STATE["last_hr"], 0x80004005)
    e.label("initialize_failed")
    e.code.state(b"\xff\x85", STATE["failure_count"])
    e.latch_failure()
    e.call("cleanup")
    e.set(STATE["disabled"], 1)
    e.hex("c3")

    e.label("draw_command")
    # EDI points to bounded {asset index, x float, y float, reserved}.
    e.hex("8b07")
    e.code.emit(b"\x3d" + _u32(len(assets)))
    e.branch("0f83", "draw_invalid")
    e.store("eax", STATE["asset_index"])
    e.hex("c1e006")
    e.lea("ebx", RECORDS)
    e.hex("01c3")
    # Set x/y for all four vertices and add each asset's logical dimensions.
    for vertex, x_add, y_add in ((0, False, False), (1, True, False), (2, True, True), (3, False, True)):
        e.hex("d94704")
        if x_add: e.hex("d84324")
        e.code.state(b"\xd9\x9d", PACKET + vertex * 32)
        e.hex("d94708")
        if y_add: e.hex("d84328")
        e.code.state(b"\xd9\x9d", PACKET + vertex * 32 + 4)
        e.set(PACKET + vertex * 32 + 24, 0)
        e.set(PACKET + vertex * 32 + 28, 0)
        if x_add: e.hex("8b432c"); e.store("eax", PACKET + vertex * 32 + 24)
        if y_add: e.hex("8b4330"); e.store("eax", PACKET + vertex * 32 + 28)
    if cockpit is not None:
        # Only cached commands have a one-based atlas ordinal. Validate against
        # this asset's immutable table before deriving any frame UV address.
        e.hex("8b570c85d2"); e.branch("0f84", "draw_default_uv")
        e.hex("3b5338"); e.branch("0f87", "draw_invalid")
        e.hex("4ac1e2048b7334")
        e.lea("eax", 0); e.hex("01c601d6")
        for vertex, x_add, y_add in ((0, False, False), (1, True, False),
                                     (2, True, True), (3, False, True)):
            e.code.emit(b"\x8b\x46" + bytes((8 if x_add else 0,)))
            e.store("eax", PACKET + vertex * 32 + 24)
            e.code.emit(b"\x8b\x46" + bytes((12 if y_add else 4,)))
            e.store("eax", PACKET + vertex * 32 + 28)
        e.label("draw_default_uv")
    e.hex("8b4310")
    e.com(STATE["device2"], 0x5C, (("imm", 1), ("reg", "eax")),
          stage="set_texture", asset_index=None)
    e.failed("draw_failed")
    e.com(STATE["device2"], 0x78, (("imm", 4), ("imm", 3), ("addr", PACKET),
          ("imm", 4), ("addr", INDICES), ("imm", 6), ("imm", 0)),
          stage="draw_indexed_primitive", asset_index=None)
    e.failed("draw_failed")
    e.code.state(b"\xff\x85", STATE["draw_count"])
    e.hex("31c0c3")
    e.label("draw_invalid")
    e.immediate("eax", 0x80070057)
    e.store("eax", STATE["last_hr"])
    e.label("draw_failed")
    e.load("eax", STATE["last_hr"])
    # Failure due to a null pointer with S_OK still becomes a nonzero result.
    e.hex("85c0"); e.branch("0f85", "draw_return")
    e.immediate("eax", 0x80004005)
    e.label("draw_return")
    e.hex("c3")
    e.label("cleanup")
    e.compare(STATE["scene_open"], 0); e.branch("0f84", "cleanup_locks")
    e.com(STATE["device2"], 0x2C)
    e.set(STATE["scene_open"], 0)
    e.label("cleanup_locks")
    e.label("cleanup_source_lock")
    e.pointer(STATE["locked_surface"], "cleanup_viewport")
    e.com(STATE["locked_surface"], 0x80, (("value", STATE["locked_pixels"]),))
    e.set(STATE["locked_surface"], 0); e.set(STATE["locked_pixels"], 0)
    e.label("cleanup_viewport")
    e.compare(STATE["viewport_added"], 0); e.branch("0f84", "cleanup_release")
    e.com(STATE["device2"], 0x1C, (("value", STATE["viewport"]),))
    e.set(STATE["viewport_added"], 0)
    e.label("cleanup_release")
    release_slots = [STATE["viewport"]]
    for index in reversed(range(len(assets))):
        record = RECORDS + index * RECORD_SIZE
        release_slots += [record + 12, record + 8, record + 4, record]
    release_slots += [STATE["own_identity"], STATE["native_identity"], STATE["device2"],
                      STATE["backbuffer"], STATE["device"], STATE["d3d2"],
                      STATE["d3d"], STATE["ddraw"]]
    for index, offset in enumerate(release_slots):
        e.pointer(offset, f"release_skip_{index}")
        e.com(offset, 8)
        e.set(offset, 0)
        e.label(f"release_skip_{index}")
    for index in range(len(assets)): e.set(RECORDS + index * RECORD_SIZE + 16, 0)
    e.set(STATE["ready"], 0)
    e.hex("c3")
    if cockpit is not None:
        e.label("cockpit_sync")
        for name, offset in cockpit["fields"].items():
            native_name = name.removeprefix("cockpit_")
            e.load("eax", NATIVE[native_name], native=True)
            e.code.state(b"\x39\x85", offset)
            e.branch("0f85", "cockpit_context_changed")
        e.load("edx", NATIVE["animations"], native=True)
        e.hex("85d2"); e.branch("0f84", "cockpit_clear")
        for group in cockpit["roles"]:
            e.code.emit(b"\x8b\x82" + _u32(group.group_index * 12 + 8))
            e.code.state(b"\x39\x85", cockpit["frame_fields"]["cockpit_frame_table_" + group.name])
            e.branch("0f85", "cockpit_context_changed")
        e.load("eax", NATIVE["dashboard"], native=True)
        e.hex("85c0"); e.branch("0f84", "cockpit_clear")
        e.hex("c3")
        e.label("cockpit_context_changed")
        e.call("cockpit_clear")
        for name, offset in cockpit["fields"].items():
            e.load("eax", NATIVE[name.removeprefix("cockpit_")], native=True)
            e.store("eax", offset)
        e.load("edx", NATIVE["animations"], native=True)
        for group in cockpit["roles"]:
            label = "cockpit_sync_null_frame_table_" + group.name
            e.immediate("eax", 0)
            e.hex("85d2"); e.branch("0f84", label)
            e.code.emit(b"\x8b\x82" + _u32(group.group_index * 12 + 8))
            e.label(label)
            e.store("eax", cockpit["frame_fields"]["cockpit_frame_table_" + group.name])
        e.hex("c3")
        e.label("cockpit_clear")
        for offset in cockpit["commands"].values(): e.set(offset, NO_ASSET)
        e.hex("c3")
    code = e.code.finish()
    if state_va < code_va + len(code):
        raise ValueError("HUD-state overlapt de RX-helper.")
    state_offsets = dict(STATE)
    if cockpit is not None:
        state_offsets.update(cockpit["fields"])
        state_offsets.update(cockpit["frame_fields"])
        state_offsets.update({"cockpit_cache_" + name: offset for name, offset in cockpit["commands"].items()})
    return NativeBundle(code, bytes(data), dict(e.code.labels), state_offsets,
                        tuple(RECORDS + index * RECORD_SIZE for index in range(len(assets))),
                        pixel_offsets, code_va, state_va, 0, 0)
