"""Pinned experimental II 16:9 camera and HUD; immutable bytes, no game/file I/O.

Input is a separately pinned 960x540 or 1280x720 canvas stage, never an arbitrary SPEL.
Three guarded x86 stubs in a new PE section preserve the original native paths.
The projection stub maps only three proven float32 argument angles; the HUD
stub calls the original initializer before translating explicit high-layout
groups. Both guards require native enum 3 and a 960x540 canvas. Other modes,
unknown angles, original fonts, sprite geometry and both low-layout tables
remain unchanged. CPU side culling and actual compatibility need playtesting.
The native HUD function is a CRT initializer; a guarded late callback in the
proven display-setup sequence therefore applies the HUD after mode selection.
"""
from __future__ import annotations

import hashlib
import math
import struct

SOURCE_SIZE = 669696
ORIGINAL_SHA256 = '551484bcf472407fd67ee8933c6f26b5a937d428e9e0cdf0cd72988dd003c2f9'
SOURCE_SHA256 = '78b702af52260f468ee7350e59162060ee4e4dc01c1c5ddf213f2124e2ad4ccf'
PATCHED_SHA256 = '90efbffec34f5080d12cc05ecc0527a0172d0325801d3318e3bd87d107f300d5'
HD_SOURCE_SHA256 = '3ed24a63ca3d7de95bec9cf79492f624d0d15029285abd126aaf375e09215e07'
HD_PATCHED_SHA256 = 'da0424e4547a8a0f67d2fd2cd4e13f0f71a55e6e12c5ed3639e4ca368d564a5c'
SOURCE_VARIANTS = {'canvas_960x540': SOURCE_SHA256}

NATIVE_ENUM = 0x4895B0
NATIVE_WIDTH = 0x49E72C
NATIVE_HEIGHT = 0x49E730
HUD_HIGH_TABLE_VA = 0x488900
HUD_HIGH_TABLE_OFFSET = 0x86100
HUD_ENTRY_VA = 0x41B860
HUD_ENTRY_OFFSET = 0x1AC60
HUD_PROLOGUE = bytes.fromhex('a12ce74900')
CAMERA_ENTRY_VA = 0x45D860
CAMERA_ENTRY_OFFSET = 0x5CC60
CAMERA_PROLOGUE = bytes.fromhex('83ec50d9442460')
INIT_ENTRY_VA = 0x423EFE
INIT_ENTRY_OFFSET = 0x232FE
INIT_PROLOGUE = bytes.fromhex('d9056cfc4700')
SECTION_NAME = b'.iiwide\0'
IMAGE_BASE = 0x400000
SECTION_RVA = 0xFE000
SECTION_RAW_OFFSET = SOURCE_SIZE
SECTION_ALIGNMENT = 0x1000
FILE_ALIGNMENT = 0x200

# These are complete native windows, not occurrences of a dimension/angle.
# The initializer ends at its actual RET. 486D08 holds font records; geometry
# resides in the independent 12-byte image/resource-id,x,y placement table.
CONTEXT_SPECS = (
    (0x1AC60, 0x4B0, '34bb7e12cb4cdabc4b232a608043a5c99c68a90ed47b8d3ed9bd16adf7eebe3c'),
    (0x5CC60, 0xA8, 'a9e069d35a5ff68e67f175210a3b832efeda692bf8bb86105e317006e3c5f7e5'),
    (0x5C5F0, 0x13D, '407e2d4e5e008edd178069805b71c151165017134794f5ade19e9542df3c8961'),
    (0x23120, 0xA5, '8e02dd52035eaaff99b36c35a2510adb1c9672e9e9a33d9c5b2040f68d5630a9'),
    (0x85D10, 2016, '9e720c61e41ea2e2e12df429592b72610041902acf5802f8b063e309ead6b2aa'),
    (0x232FE, 0x47, '83489c794a64e1279667322fd9847856fe1a8c0c7ee96c172dd28c63620a41e4'),
    (0x5EBEC, 0x36, 'ae6a4d3fda803e0effba343e7763ea59e374dad81c058b2a95ba632f3f6322cb'),
    (0x5ED83, 0x36, 'cf7e1726bd3de8177dce886fcc11ed4fcd166c7b72c123f2ce6ad93bd3661b38'),
    (0x1FB70, 0x17C, 'd3f667a21ad8cdff26000e2dce22da2d30e01892fdd6a5337f5e6e88c6741a90'),
    (0x203E0, 0x0D, '4c9f6b76409df5922a955a01d48ce922ab19e9679b1274df4abbce5a745d6d89'),
    (0x30A5C, 0xB0, '8399d49fba8b028866cc1ad6381ea4588e4c7e7ac550d410d9a0cd4f3d3205e9'),
    (0x643F0, 0xC8, '6fabfefe95d16f528615b9edbb662c9adc441fa8d24a4262f8e0f9edeffe3dbc'),
    (0x70EA0, 0x30, '4688bc24211beac635c0c17c0188c9de7ef54ae818d4345b2b47001154510791'),
    (0x70FC0, 0x20, '1f0dbf3798bdc874327b5fce43c014aab07849d2d667166552daf89f2a2538ee'),
    (0x7F800, 0x13C, '178a0b1c72d4e78de49709e3a2ec99be8f37bd93e21976af949eb8738f149c69'),
)
PI_FLOAT32_BYTES = bytes.fromhex('db0f4940')
ANGLE_CONSTANTS = ((0x7DD74, bytes.fromhex('6666e63e')),
                   (0x7E2E8, bytes.fromhex('cdcc4c3e')),
                   (0x7E2D8, bytes.fromhex('9a99993e')))

# Explicit translations in native pixels. Asset widths, heights, anchors,
# fonts and internal positions within each group remain unchanged. Entries
# 34 and 74..77 already use W/2 or H/2 in the original initializer, so they
# must not receive a second horizontal/vertical centering translation.
HUD_GROUPS = (
    ('right_bottom_race', (0, 1, 3, 4, 7, 10, 13, 14, 52, 53, 54, 55, 56, 83), 320, 60),
    ('right_top_race', (6, *range(38, 52), *range(57, 62)), 320, 0),
    ('left_bottom_radar', (11, 16), 0, 60),
    ('center_top_labels', (2, 73), 160, 0),
    ('center_dialog_results', (*range(17, 29), 30, 31, 32, 33, *range(62, 73),
                               78, 79, 80, 81, 82), 160, 30),
    ('center_warning', (29,), 160, 30),
    ('native_center_dialog_labels', (35, 36, 37), 0, 30),
)
HUD_UNCHANGED_IDS = (5, 8, 9, 12, 15, 34, 74, 75, 76, 77)
# Only high entries34..83 are rewritten by the original initializer. Restore
# each shifted static field to its pinned native anchor before applying the
# guard, so repeated initialization cannot accumulate shifts and selecting a
# legacy mode in the same process recovers the original static coordinates.
HUD_STATIC_ANCHORS = (
    (380, 431), (487, 381), (221, 6), (541, 349), (406, 456), (11, 9),
    (520, 9), (571, 329), (60, 72), (90, 9), (557, 421), (8, 345),
    (0, 0), (350, 389), (489, 425), (0, 0), (30, 350), (64, 109),
    (74, 120), (74, 170), (74, 220), (408, 120), (385, 170), (385, 220),
    (74, 300), (408, 300), (560, 100), (320, 240), (80, 277), (320, 120),
    (8, 112), (8, 138), (120, 200), (120, 200),
)


def _f32(value: float) -> float:
    return struct.unpack('<f', struct.pack('<f', value))[0]


def hor_plus_angle(angle: float, old_aspect: float = 4 / 3,
                   new_aspect: float = 16 / 9) -> float:
    """Return horizontal FOV retaining vertical span under native H/W clip."""
    if (type(angle) not in (int, float) or not math.isfinite(angle) or
            not 0 < angle < math.pi or
            type(old_aspect) not in (int, float) or not math.isfinite(old_aspect) or old_aspect <= 0 or
            type(new_aspect) not in (int, float) or not math.isfinite(new_aspect) or new_aspect <= 0):
        raise ValueError('Onjuiste projectiehoek of schermverhouding.')
    return 2 * math.atan((new_aspect / old_aspect) * math.tan(angle / 2))


def projection_angle_pairs() -> tuple[tuple[int, int], ...]:
    """Match the caller's float32 pi*factor argument, not the factor itself."""
    pi = struct.unpack('<f', PI_FLOAT32_BYTES)[0]
    result = []
    for _, constant in ANGLE_CONSTANTS:
        factor = struct.unpack('<f', constant)[0]
        old = _f32(pi * factor)  # x87 FMUL then the proven caller FSTP m32.
        new = _f32(hor_plus_angle(old))
        result.append((struct.unpack('<I', struct.pack('<f', old))[0],
                       struct.unpack('<I', struct.pack('<f', new))[0]))
    return tuple(result)


def hud_translations(display=(960, 540)) -> tuple[tuple[int, int, int, str], ...]:
    if display not in ((960, 540), (1280, 720), (1920, 1080), (3840, 2160)):
        raise ValueError('Onbekende racecanvas.')
    width, height = display
    result = tuple((index, {0: 0, 160: (width-640)//2, 320: width-640}[dx],
                    {0: 0, 30: (height-480)//2, 60: height-480}[dy], name)
                   for name, ids, dx, dy in HUD_GROUPS for index in ids)
    ids = [row[0] for row in result]
    if (len(ids) != len(set(ids)) or set(ids) & set(HUD_UNCHANGED_IDS) or
            set(ids) | set(HUD_UNCHANGED_IDS) != set(range(84))):
        raise ValueError('Onvolledig of dubbel HUD-ankercontract.')
    return result


class _Code:
    """Bounded x86 byte emitter with explicit rel32 fixups; no execution."""
    def __init__(self, va: int):
        self.va, self.data, self.labels, self.fixups = va, bytearray(), {}, []

    def emit(self, value: bytes):
        self.data.extend(value)

    def label(self, name: str):
        if name in self.labels:
            raise ValueError('Dubbel code-label.')
        self.labels[name] = len(self.data)

    def branch(self, opcode: bytes, target: str | int):
        self.emit(opcode)
        self.fixups.append((len(self.data), target))
        self.emit(b'\0' * 4)

    def finish(self) -> bytes:
        for position, target in self.fixups:
            destination = self.va + self.labels[target] if isinstance(target, str) else target
            struct.pack_into('<i', self.data, position, destination - (self.va + position + 4))
        return bytes(self.data)


def _wide_guards(code: _Code, end: str, display=(960, 540)):
    for address, value in ((NATIVE_ENUM, 3), (NATIVE_WIDTH, display[0]), (NATIVE_HEIGHT, display[1])):
        code.emit(b'\x81\x3d' + struct.pack('<II', address, value))
        code.branch(b'\x0f\x85', end)


def build_stubs(section_va: int, display=(960, 540)) -> tuple[bytes, dict]:
    """Return three deterministic guarded stubs and their exact boundaries."""
    hud = _Code(section_va)
    hud.emit(HUD_PROLOGUE)  # Original EAX=width before calling original +5.
    hud.branch(b'\xe8', HUD_ENTRY_VA + len(HUD_PROLOGUE))
    hud.emit(b'\x9c\x60')  # Preserve original initializer result, flags, GPRs.
    for index, dx, dy, _ in hud_translations(display):
        if index < len(HUD_STATIC_ANCHORS):
            for field, delta, original in ((4, dx, HUD_STATIC_ANCHORS[index][0]),
                                          (8, dy, HUD_STATIC_ANCHORS[index][1])):
                if delta:
                    hud.emit(b'\xc7\x05' + struct.pack('<Ii', HUD_HIGH_TABLE_VA + index * 12 + field, original))
    _wide_guards(hud, 'done', display)
    for index, dx, dy, _ in hud_translations(display):
        for field, delta in ((4, dx), (8, dy)):
            if delta:
                hud.emit(b'\x81\x05' + struct.pack('<Ii', HUD_HIGH_TABLE_VA + index * 12 + field, delta))
    hud.label('done')
    hud.emit(b'\x61\x9d\xc3')
    hud_bytes = hud.finish()

    camera_offset = (len(hud_bytes) + 15) & ~15
    camera = _Code(section_va + camera_offset)
    camera.emit(b'\x9c\x60')
    _wide_guards(camera, 'done', display)
    # Caller phi is [entry ESP+16]; PUSHFD/PUSHAD add36 bytes: ESP+52.
    for index, (before, after) in enumerate(projection_angle_pairs()):
        camera.emit(b'\x81\x7c\x24\x34' + struct.pack('<I', before))
        camera.branch(b'\x0f\x85', f'next{index}')
        camera.emit(b'\xc7\x44\x24\x34' + struct.pack('<I', after))
        camera.branch(b'\xe9', 'done')
        camera.label(f'next{index}')
    camera.label('done')
    camera.emit(b'\x61\x9d' + CAMERA_PROLOGUE)
    camera.branch(b'\xe9', CAMERA_ENTRY_VA + len(CAMERA_PROLOGUE))
    camera_bytes = camera.finish()
    blob = hud_bytes + b'\x90' * (camera_offset - len(hud_bytes)) + camera_bytes
    init_offset = (len(blob) + 15) & ~15
    init = _Code(section_va + init_offset)
    init.emit(b'\x9c\x60')
    _wide_guards(init, 'done', display)
    init.branch(b'\xe8', section_va)  # Own idempotent HUD stub, only after guard.
    init.label('done')
    init.emit(b'\x61\x9d' + INIT_PROLOGUE)
    init.branch(b'\xe9', INIT_ENTRY_VA + len(INIT_PROLOGUE))
    init_bytes = init.finish()
    blob += b'\x90' * (init_offset - len(blob)) + init_bytes
    return blob, {'hud_offset': 0, 'hud_size': len(hud_bytes),
                  'camera_offset': camera_offset, 'camera_size': len(camera_bytes),
                  'init_offset': init_offset, 'init_size': len(init_bytes)}


def _append_section(source: bytes, blob: bytes) -> tuple[bytearray, dict]:
    """Strict PE32 new-section append; preserve imports, entry and old bytes."""
    if source[:2] != b'MZ' or struct.unpack_from('<I', source, 0x3C)[0] != 0x80:
        raise ValueError('Onjuiste SPEL PE-header.')
    pe, optional, section_table = 0x80, 0x98, 0x178
    if (source[pe:pe + 4] != b'PE\0\0' or
            struct.unpack_from('<HH', source, pe + 4) != (0x14C, 4) or
            struct.unpack_from('<H', source, pe + 20)[0] != 224 or
            struct.unpack_from('<H', source, optional)[0] != 0x10B or
            struct.unpack_from('<III', source, optional + 28) != (IMAGE_BASE, SECTION_ALIGNMENT, FILE_ALIGNMENT) or
            struct.unpack_from('<II', source, optional + 56) != (SECTION_RVA, 0x400)):
        raise ValueError('Onjuiste SPEL PE32-layout voor de guarded proef.')
    sections = []
    for index in range(4):
        name, virtual_size, rva, raw_size, raw_offset = struct.unpack_from('<8sIIII', source, section_table + index * 40)
        if raw_offset < 0x400 or raw_offset + raw_size > len(source):
            raise ValueError('SPEL-section valt buiten de gepinde binary.')
        sections.append((name.rstrip(b'\0'), rva, raw_size, raw_offset, virtual_size))
    expected = ((b'.text', 0x1000, 0x7D200, 0x400, 0x7D0B5),
                (b'.rdata', 0x7F000, 0x2200, 0x7D600, 0x20D0),
                (b'.data', 0x82000, 0x23200, 0x7F800, 0x7A074),
                (b'.idata', 0xFD000, 0xE00, 0xA2A00, 0xDF6))
    if tuple(sections) != expected:
        raise ValueError('SPEL bestaande section-layout wijkt af.')
    next_header = section_table + 4 * 40
    if any(source[next_header:next_header + 40]):
        raise ValueError('Nieuwe SPEL-sectionheader heeft geen lege ruimte.')
    if not 1 <= len(blob) <= SECTION_ALIGNMENT:
        raise ValueError('Guarded racecode overschrijdt de sectionlimiet.')
    raw_size = (len(blob) + FILE_ALIGNMENT - 1) & ~(FILE_ALIGNMENT - 1)
    result = bytearray(source)
    result.extend(blob + b'\0' * (raw_size - len(blob)))
    header = struct.pack('<8sIIIIIIHHI', SECTION_NAME, len(blob), SECTION_RVA,
                         raw_size, SECTION_RAW_OFFSET, 0, 0, 0, 0, 0x60000020)
    result[next_header:next_header + 40] = header
    struct.pack_into('<H', result, pe + 6, 5)
    struct.pack_into('<I', result, optional + 4,
                     struct.unpack_from('<I', source, optional + 4)[0] + raw_size)
    struct.pack_into('<I', result, optional + 56, SECTION_RVA + SECTION_ALIGNMENT)
    struct.pack_into('<I', result, optional + 64, 0)  # Original checksum is zero.
    return result, {'header_offset': next_header, 'rva': SECTION_RVA,
                    'raw_offset': SECTION_RAW_OFFSET, 'raw_size': raw_size,
                    'virtual_size': len(blob), 'characteristics': 0x60000020}


def patch_race_widescreen(source: bytes, *, display=(960, 540)) -> tuple[bytes, dict]:
    """Compose camera/HUD only after the exact pinned selected canvas stage."""
    if type(source) is not bytes or len(source) != SOURCE_SIZE:
        raise ValueError('Onjuiste SPEL-versie/grootte voor de 16:9-camera/HUD.')
    if display not in ((960, 540), (1280, 720)):
        raise ValueError('Onbekende racecanvas.')
    width, height = display
    source_pin = SOURCE_SHA256 if display == (960, 540) else HD_SOURCE_SHA256
    output_pin = PATCHED_SHA256 if display == (960, 540) else HD_PATCHED_SHA256
    digest = hashlib.sha256(source).hexdigest()
    if not source_pin or digest != source_pin:
        raise ValueError('Onbekende SPEL-hash; eerst de gepinde 960x540-canvasstage vereist.')
    for offset, size, expected_sha256 in CONTEXT_SPECS:
        if hashlib.sha256(source[offset:offset + size]).hexdigest() != expected_sha256:
            raise ValueError('SPEL-camera/HUD-context wijkt af; proef geweigerd.')
    for offset, expected in ((0x9BFFC, struct.pack('<IIIII', width, height, 16, 0, 0)),
                             (0x7E26C, PI_FLOAT32_BYTES),
                             (HUD_ENTRY_OFFSET, HUD_PROLOGUE),
                             (CAMERA_ENTRY_OFFSET, CAMERA_PROLOGUE),
                             (INIT_ENTRY_OFFSET, INIT_PROLOGUE), *ANGLE_CONSTANTS):
        if source[offset:offset + len(expected)] != expected:
            raise ValueError('SPEL-canvas/hoek/proloog wijkt af; proef geweigerd.')
    for index, anchors in enumerate(HUD_STATIC_ANCHORS):
        if struct.unpack_from('<ii', source, HUD_HIGH_TABLE_OFFSET + index * 12 + 4) != anchors:
            raise ValueError('SPEL statische HUD-ankers wijken af; proef geweigerd.')
    blob, stubs = build_stubs(IMAGE_BASE + SECTION_RVA, display)
    result, section = _append_section(source, blob)
    hooks = []
    for name, offset, va, before, stub_offset in (
            ('hud_late_init', INIT_ENTRY_OFFSET, INIT_ENTRY_VA, INIT_PROLOGUE, stubs['init_offset']),
            ('camera', CAMERA_ENTRY_OFFSET, CAMERA_ENTRY_VA, CAMERA_PROLOGUE, stubs['camera_offset'])):
        target = IMAGE_BASE + SECTION_RVA + stub_offset
        after = b'\xe9' + struct.pack('<i', target - (va + 5)) + b'\x90' * (len(before) - 5)
        result[offset:offset + len(before)] = after
        hooks.append({'name': name, 'offset': offset, 'va': va,
                      'before': before.hex(), 'after': after.hex(), 'target_va': target})
    patched = bytes(result)
    output_sha256 = hashlib.sha256(patched).hexdigest()
    if not output_pin or output_sha256 != output_pin:
        raise ValueError('Onverwachte uitvoerhash van de guarded 16:9-camera/HUD.')
    return patched, {
        'name': f'ii-race-guarded-widescreen-{width}x{height}', 'path': 'DATA/SPEL.DAT',
        'source_variant': f'canvas_{width}x{height}', 'source_sha256': digest,
        'original_source_sha256': ORIGINAL_SHA256, 'patched_sha256': output_sha256,
        'size_before': SOURCE_SIZE, 'size': len(patched),
        'native_display_request': [width, height, 16], 'aspect_ratio': [16, 9],
        'guard': {'native_resolution_enum': 3, 'width': width, 'height': height},
        'section': section, 'stubs': stubs, 'hooks': hooks,
        'projection_argument_pairs': [{'before_float32': f'{old:08x}', 'after_float32': f'{new:08x}'}
                                      for old, new in projection_angle_pairs()],
        'camera_changed': True, 'hud_layout_changed': True,
        'hud_translation_count': len(hud_translations(display)),
        'hud_initialization_idempotent': True,
        'static_anchors_restored_before_guard': True,
        'late_hud_initialization_after_mode_selection': True,
        'native_crt_hud_initializer_unchanged': True,
        'late_guard_failure_has_no_hud_side_effects': True,
        'hud_groups': [{'name': name, 'image_ids': list(ids),
                        'dx': {0:0,160:(width-640)//2,320:width-640}[dx],
                        'dy': {0:0,30:(height-480)//2,60:height-480}[dy]}
                       for name, ids, dx, dy in HUD_GROUPS],
        'unknown_projection_angles_preserved': True, 'unselected_modes_unchanged': True,
        'low_layout_unchanged': True, 'sprite_geometry_unchanged': True,
        'fonts_unchanged': True, 'menu_changed': False,
        'machine_code_changed': True, 'experimental': True, 'runtime_tested': False,
        'cpu_side_culling_verified': False,
        'scope': 'Guarded Hor+ for three proven projection routes and native-size HUD anchors; playtest required.',
    }
