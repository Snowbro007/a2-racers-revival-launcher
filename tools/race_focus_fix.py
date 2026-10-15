"""Opt-in, pinned A2-I native focus-recovery prototype; constructs bytes only.

The source is never executed or written. A separate trial copy retains immutable
system-memory texture sources, pauses the frame when inactive, restores lost
surfaces, reloads texture contents and verifies every restored texture handle.
RX code and RW state extend existing sections without moving any existing RVA.
This is not runtime proof and cannot repair arbitrary driver/device failures.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

NAME = "A2SPEL.DAT"
EXPECTED_SHA256 = "069d39e815fc631ef433550459e8105042cf740dfc311e4f9285d4cca148e726"
# Independently audited outputs for this helper and the four selection profiles.
# Used only to identify earlier local trials when carrying saved native options.
EXPECTED_PATCHED_SHA256_BY_PROFILE = {
    "original": "5727fcfa8be692152573e288d1842a6fac519adcd7dbdc83c75326427508f652",
    "extended-8": "5f90f89de2cb65e79af17730d927e402f05e4e7fd39f2b8f7090b5584671ce91",
    "extended-10": "2e33c1726f6bef0e22082531a22b815877e43d7ea424b9671a53624b96dc28d6",
    "extended-20": "f8c397067a029de34fef7c5892b35d0d64a307a994e4923af9a446216fe82db8",
}
SOURCE_SIZE = EXPECTED_SIZE = 395264
PE_OFFSET, OPTIONAL_OFFSET, SECTION_TABLE_OFFSET = 0x80, 0x98, 0x178
IMAGE_BASE = 0x400000
HELPER_VA, STATE_VA = 0x440800, 0x45A400
INSERT_OFFSET, INSERT_SIZE = 0x3FC00, 0x800
DATA_INSERT_OFFSET, DATA_INSERT_SIZE = 0x59000, 0x200
MAX_CACHE = 4096
STATE_OFFSETS = {name: index * 4 for index, name in enumerate((
    "app_active", "window_active", "minimized", "recovery_pending",
    "cache_ptr", "cache_count", "cache_capacity", "cache_error",
    "retry_count", "last_hr", "recovery_count", "any_restored",
    "surface_restored"))}
EXPECTED_COFF = bytes.fromhex("4c010500e0d569330000000000000000e0008281")
EXPECTED_OPTIONAL = bytes.fromhex(
    "0b01021200f8030000940100008a020056380200001000000010040000004000"
    "001000000002000001000b000000000003000a000000000000d0080000040000"
    "0000000002000000000001000000010000200000001000000000000010000000"
    "0000000000000000004008001d10000000000000000000000000000000000000"
    "0000000000000000006008007864000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
SECTIONS = (
    (b"BEGTEXT", 0, 0x1000, 0x3F800, 0x400, 0x60000020),
    (b"DGROUP", 0, 0x41000, 0x19400, 0x3FC00, 0xC0000040),
    (b".bss", 0, 0x5B000, 0x28A00, 0, 0xC0000080),
    (b".idata", 0, 0x84000, 0x1200, 0x59000, 0xC0000040),
    (b".reloc", 0, 0x86000, 0x6600, 0x5A200, 0x42000040),
)
THUNKS = {"LocalAlloc": (0x484208, "kernel32.dll"),
          "LocalFree": (0x48420C, "kernel32.dll"),
          "Sleep": (0x484218, "kernel32.dll")}
# Each replacement consumes whole instructions; CALL+TEST wrappers return
# the actual COM HRESULT and regenerate the TEST flags consumed by native JE.
SITES = {
    "frame_gate": (0x40197B, bytes.fromhex("e813580000")),
    "window_handler": (0x42E5CD, bytes.fromhex("5356578b742414")),
    "capture_file": (0x424BF5, bytes.fromhex("ff521885c0")),
    "capture_image": (0x425011, bytes.fromhex("ff511885c0")),
    "capture_file_mipmap": (0x425538, bytes.fromhex("ff521885c0")),
    "capture_resource_mipmap": (0x425A1B, bytes.fromhex("ff521885c0")),
    "cache_init": (0x42487E, bytes.fromhex("53515289c3")),
    "cache_cleanup": (0x4028FA, bytes.fromhex("e89a4e0000")),
    "end_frame_pump": (0x401B0E, bytes.fromhex("e869f5ffff")),
}


def section_record(section: tuple) -> bytes:
    name, virtual_size, rva, raw_size, raw_pointer, flags = section
    return struct.pack("<8sIIIIIIHHI", name.ljust(8, b"\0"), virtual_size,
                       rva, raw_size, raw_pointer, 0, 0, 0, 0, flags)


class _Code:
    """Bounded encoder for our own x86 code, with no game disassembler."""
    def __init__(self):
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.branches: list[tuple[int, str]] = []

    def emit(self, value: str):
        self.data.extend(bytes.fromhex(value))

    def label(self, name: str):
        if name in self.labels:
            raise ValueError("Dubbel helperlabel.")
        self.labels[name] = len(self.data)

    def jump(self, opcode: str, name: str):
        self.emit(opcode)
        self.branches.append((len(self.data), name))
        self.emit("00000000")

    def call_label(self, name: str):
        self.jump("e8", name)

    def call_native(self, address: int):
        here = HELPER_VA + len(self.data)
        self.emit("e8" + struct.pack("<i", address - here - 5).hex())

    def jump_native(self, address: int):
        here = HELPER_VA + len(self.data)
        self.emit("e9" + struct.pack("<i", address - here - 5).hex())

    def native(self, opcode: str, address: int):
        self.emit(opcode + struct.pack("<i", address - HELPER_VA).hex())

    def own(self, opcode: str, name: str):
        self.native(opcode, STATE_VA + STATE_OFFSETS[name])

    def base(self):
        return_offset = len(self.data) + 5
        self.emit("e8000000005d81ed" + struct.pack("<I", return_offset).hex())

    def finish(self) -> bytes:
        for position, label in self.branches:
            self.data[position:position + 4] = struct.pack("<i", self.labels[label] - position - 4)
        if len(self.data) > INSERT_SIZE:
            raise ValueError("Focusherstelhelper past niet in de gecontroleerde RX-uitbreiding.")
        return bytes(self.data)


def _cmp(code: _Code, state: str, value: int = 0):
    code.own("83bd", state)
    code.emit(f"{value:02x}")


def _set(code: _Code, state: str, value: int):
    code.own("c785", state)
    code.emit(struct.pack("<I", value).hex())


def _append_capture(code: _Code):
    code.label("capture")
    code.emit("60")  # PUSHAD; original stdcall(dst,src) at ESP+24/+28.
    code.base()
    code.emit("8b7424248b7c242857568b06ff50188944241c85c0")
    code.jump("0f85", "capture_done")
    code.own("8b9d", "cache_ptr")
    code.emit("85db")
    code.jump("0f85", "capture_find")
    code.native("8b85", 0x47679C)
    code.emit("85c0")
    code.jump("0f8e", "fatal_invariant")
    code.emit("3d00100000")
    code.jump("0f87", "fatal_invariant")
    code.own("8985", "cache_capacity")
    code.emit("c1e003506a40")
    code.native("ff95", THUNKS["LocalAlloc"][0])
    code.emit("85c0")
    code.jump("0f84", "fatal_invariant")
    code.own("8985", "cache_ptr")
    code.emit("89c3")
    code.label("capture_find")
    code.emit("31c9")
    code.label("capture_search")
    code.own("3b8d", "cache_count")
    code.jump("0f83", "capture_append")
    code.emit("3934cb")
    code.jump("0f84", "capture_replace")
    code.emit("41")
    code.jump("e9", "capture_search")
    code.label("capture_append")
    code.own("3b8d", "cache_capacity")
    code.jump("0f83", "fatal_invariant")
    code.own("ff85", "cache_count")
    code.label("capture_replace")
    code.emit("8d1ccb578b07ff5004568b06ff5004")  # retain new src AND dst.
    code.emit("8b0385c0")
    code.jump("0f84", "capture_store")
    code.emit("508b10ff52088b4304508b10ff5208")  # release previous pair.
    code.label("capture_store")
    code.emit("8933897b04")
    code.label("capture_done")
    code.emit("6185c0c20800")  # real HRESULT; original native branch flags.


def _append_cleanup(code: _Code):
    code.label("cleanup")
    code.emit("60")
    code.base()
    code.own("8bb5", "cache_ptr")
    code.own("8bbd", "cache_count")
    code.emit("85ff")
    code.jump("0f84", "cleanup_free")
    code.label("cleanup_pair")
    code.emit("8b06508b10ff52088b4604508b10ff520883c6084f")
    code.jump("0f85", "cleanup_pair")
    code.label("cleanup_free")
    code.own("8b85", "cache_ptr")
    code.emit("85c0")
    code.jump("0f84", "cleanup_clear")
    code.emit("50")
    code.native("ff95", THUNKS["LocalFree"][0])
    code.label("cleanup_clear")
    for name in ("cache_ptr", "cache_count", "cache_capacity", "cache_error"):
        _set(code, name, 0)
    code.emit("61c3")
    code.label("cache_init")
    code.emit("9c60")
    code.base()
    code.call_label("cleanup")
    code.emit("619d53515289c3")
    code.jump_native(0x424883)
    code.label("cache_cleanup")
    code.emit("9c60")
    code.base()
    code.call_label("cleanup")
    code.emit("619d")
    code.jump_native(0x407799)


def _append_recovery(code: _Code):
    # EAX surface*. Preserve EBX; real IsLost/Restore HRESULT in EAX.
    code.label("restore_surface")
    code.emit("5389c3")
    _set(code, "surface_restored", 0)
    code.emit("85c0")
    code.jump("0f84", "surface_good")
    code.emit("538b13ff526085c0")
    code.jump("0f84", "surface_good")
    code.emit("3dc2017688")
    code.jump("0f85", "surface_return")
    _set(code, "recovery_pending", 1)  # block reentrant WM_TIMER before Restore.
    code.emit("538b13ff526c85c0")
    code.jump("0f85", "surface_return")
    _set(code, "surface_restored", 1)
    _set(code, "any_restored", 1)
    code.label("surface_good")
    code.emit("31c0")
    code.label("surface_return")
    code.emit("5bc3")

    # No-argument internal helper: preserves all registers except real EAX.
    code.label("recover")
    code.emit("6083ec04")  # one DWORD GetHandle output; saved EAX at ESP+20.
    code.base()
    _set(code, "any_restored", 0)
    for surface in (0x475F24, 0x475F28, 0x475F2C):
        code.native("8b85", surface)
        code.call_label("restore_surface")
        code.emit("85c0")
        code.jump("0f85", "recover_done")
    code.native("83bd", 0x476504)  # Z existence flag; pointer may be stale after release.
    code.emit("00")
    code.jump("0f84", "recover_no_z")
    code.native("8b85", 0x476500)
    code.call_label("restore_surface")
    code.emit("85c0")
    code.jump("0f85", "recover_done")
    code.label("recover_no_z")
    _cmp(code, "any_restored")
    code.jump("0f85", "recover_assets")
    _cmp(code, "recovery_pending")
    code.jump("0f84", "recover_success")
    code.label("recover_assets")
    code.native("8bb5", 0x476798)
    code.native("8bbd", 0x4767A0)
    code.native("3bbd", 0x47679C)
    code.jump("0f87", "fatal_invariant")
    code.emit("81ff00100000")
    code.jump("0f87", "fatal_invariant")
    code.label("recover_texture_loop")
    code.emit("85ff")
    code.jump("0f84", "recover_hud")
    code.emit("8b4604")
    code.call_label("restore_surface")
    code.emit("85c0")
    code.jump("0f85", "recover_done")
    # Refill ALL live textures during an asset-recovery transaction. A prior
    # attempt may have restored memory then failed Load: IsLost==S_OK on the
    # next attempt does not prove the pixels were repopulated.
    code.emit("8b5e08")
    code.own("8b95", "cache_ptr")
    code.own("8b8d", "cache_count")
    code.label("recover_find_source")
    code.emit("85c9")
    code.jump("0f84", "fatal_invariant")
    code.emit("391a")
    code.jump("0f84", "recover_load")
    code.emit("83c20849")
    code.jump("e9", "recover_find_source")
    code.label("recover_load")
    code.emit("ff7204538b03ff501885c0")
    code.jump("0f85", "recover_done")
    code.emit("54")  # output argument address before other pushes.
    code.native("ffb5", 0x4764FC)
    code.emit("538b13ff521085c0")
    code.jump("0f85", "recover_done")
    code.emit("8b04243b06")
    code.jump("0f85", "fatal_invariant")
    code.label("recover_texture_next")
    code.emit("83c60c4f")
    code.jump("e9", "recover_texture_loop")
    # HUD image sources are SYSTEMMEM; content loss cannot be repaired by
    # memory-only Restore. Refuse that exceptional case instead of blank HUD.
    code.label("recover_hud")
    code.native("8bb5", 0x4770F0)
    code.native("8bbd", 0x45978C)
    code.emit("85f6")
    code.jump("0f84", "recover_success")
    code.emit("85ff")
    code.jump("0f8e", "recover_success")
    code.emit("81ff00100000")
    code.jump("0f87", "fatal_invariant")
    code.label("recover_hud_loop")
    code.emit("837e1802")
    code.jump("0f85", "recover_hud_next")
    code.emit("837e1c00")
    code.jump("0f84", "recover_hud_next")
    code.emit("8b460485c0")
    code.jump("0f84", "fatal_invariant")
    code.emit("508b10ff526085c0")
    code.jump("0f85", "recover_done")
    code.label("recover_hud_next")
    code.emit("83c6204f")
    code.jump("0f85", "recover_hud_loop")
    code.label("recover_success")
    _cmp(code, "any_restored")
    code.jump("0f84", "recover_zero")
    code.own("ff85", "recovery_count")
    code.label("recover_zero")
    code.emit("31c0")
    code.label("recover_done")
    code.emit("8944242083c40461c3")


def _append_failure(code: _Code):
    code.label("fatal_hresult")
    code.own("8985", "last_hr")
    code.call_native(0x41C32C)
    code.emit("506a00")
    code.jump("e8", "get_error_strings")
    code.label("error_strings_return")
    code.emit("52")  # EDX diagnostic filename supplied by string helper.
    code.emit("51")  # ECX printf format.
    code.call_native(0x4148D1)
    code.emit("0f0b")  # Native fatal exits. Never silently return.
    code.label("fatal_invariant")
    _set(code, "cache_error", 1)
    code.emit("6a00")
    code.jump("e8", "get_invariant_strings")
    code.emit("5251")
    code.call_native(0x4148D1)
    code.emit("0f0b")
    code.label("get_error_strings")
    code.jump("e8", "error_string_data_end")
    code.label("error_string_data")
    error_format = b"Focus recovery failed: %s\0"
    code.data.extend(error_format + b"Atlas focus recovery\0")
    code.label("error_string_data_end")
    code.emit("598d51" + bytes((len(error_format),)).hex() + "c3")
    code.label("get_invariant_strings")
    code.jump("e8", "invariant_data_end")
    code.label("invariant_data")
    message = b"Focus recovery stopped: incomplete cache or changed texture handle.\0"
    code.data.extend(message + b"Atlas focus recovery\0")
    code.label("invariant_data_end")
    code.emit("598d51" + bytes((len(message),)).hex() + "c3")


# Window/gate builders are appended below; all offsets refer to own state.

def jump_native(code, target):
    here=HELPER_VA+len(code.data)
    code.emit('e9'+struct.pack('<i',target-(here+5)).hex())

def cmp_own(code, name, immediate=0):
    code.own('83bd',name)
    code.emit(f'{immediate:02x}')

def mov_one(code, name, value):
    code.own('c785',name)
    code.emit(struct.pack('<I',value).hex())

def append_window_handler(code):
    """Replace first7 WndProc bytes with JMP+2NOP; native stdcall ret10 ABI.

    Replays PUSH EBX/ESI/EDI once. After PUSHFD/PUSHAD original HWND,MSG,
    WPARAM,LPARAM are ESP+34h,38h,3Ch,40h. Ordinary exit rejoins42e5d4.
    Events only update state; Surface methods never run reentrantly here.
    """
    code.label('window_handler')
    code.emit('5356579c60')
    code.base()
    # Only the main window after it exists. Allow initial creation messages
    # while the native global is still zero (CreateWindow returns it later).
    code.native('8b85',0x475f48)
    code.emit('85c0')
    code.jump('0f84','window_message')
    code.emit('3b442434')
    code.jump('0f85','window_continue')
    code.label('window_message')
    code.emit('8b4424383d1c000000')
    code.jump('0f84','window_app')
    code.emit('83f806')
    code.jump('0f84','window_activate')
    code.emit('83f805')
    code.jump('0f84','window_size')
    code.emit('3d13010000')
    code.jump('0f85','window_continue')
    # WM_TIMER may otherwise dispatch native dynamic drawing callbacks.
    for field in ('app_active','window_active'):
        cmp_own(code,field)
        code.jump('0f84','window_ignore_timer')
    for field in ('minimized','recovery_pending'):
        cmp_own(code,field)
        code.jump('0f85','window_ignore_timer')
    code.jump('e9','window_continue')
    code.label('window_app')
    code.emit('8b44243c85c00f95c00fb6c0')
    code.own('8985','app_active')
    code.emit('85c0')
    code.jump('0f84','window_mark_pending')
    code.jump('e9','window_continue')
    code.label('window_activate')
    code.emit('8b4c243c89c825ffff000085c00f95c00fb6c0')
    code.own('8985','window_active')
    code.emit('c1e91085c90f95c10fb6c9')
    code.own('898d','minimized')
    code.emit('85c0')
    code.jump('0f84','window_mark_pending')
    code.emit('85c9')
    code.jump('0f85','window_mark_pending')
    code.jump('e9','window_continue')
    code.label('window_size')
    code.emit('8b44243c83f801')
    code.jump('0f84','window_minimize')
    code.emit('85c0')
    code.jump('0f84','window_unminimize')
    code.emit('83f802')
    code.jump('0f85','window_continue')
    code.label('window_unminimize')
    mov_one(code,'minimized',0)
    code.jump('e9','window_continue')
    code.label('window_minimize')
    mov_one(code,'minimized',1)
    code.label('window_mark_pending')
    mov_one(code,'recovery_pending',1)
    code.label('window_continue')
    code.emit('619d8b742414')
    jump_native(code,0x42e5d4)
    code.label('window_ignore_timer')
    code.emit('619d5f5e5b31c0c21000')

def append_frame_gate(code, recovery_failure_label='fatal_hresult'):
    """Redirect native CALL40197b to this no-argument helper.

    Stops the whole iteration, including update/callbacks/Clear/D3D/HUD/
    present/frame-counter, while inactive/minimized. Pumps real messages and
    sleeps20ms. WM_QUIT exits through the native mode8 loop cleanup without
    calling any frame render. Recovery returns realHRESULT, never fake success.
    """
    code.label('frame_gate')
    code.emit('9c60')
    code.base()
    code.label('gate_pump')
    code.call_native(0x401035)
    code.emit('85c0')
    code.jump('0f85','gate_quit')
    for field in ('app_active','window_active'):
        cmp_own(code,field)
        code.jump('0f84','gate_wait')
    cmp_own(code,'minimized')
    code.jump('0f85','gate_wait')
    # Native Options can change the renderer after launcher validation.
    # Software mode has no valid native D3D cache/device to recover.
    code.native('83bd',0x458c1c)
    code.emit('00')
    code.jump('0f84','gate_resume_checks')
    # Recover also checks IsLost every active frame to detect missed events.
    code.call_label('recover')
    code.emit('85c0')
    code.jump('0f85','gate_recover_failed')
    code.label('gate_resume_checks')
    # Do not clear a pending flag and start a frame after a synchronous
    # deactivation dispatched by a Surface recovery API.
    for field in ('app_active','window_active'):
        cmp_own(code,field)
        code.jump('0f84','gate_wait')
    cmp_own(code,'minimized')
    code.jump('0f85','gate_wait')
    mov_one(code,'recovery_pending',0)
    mov_one(code,'retry_count',0)
    code.emit('619d')
    # Original update ret reaches original401980 renderer call.
    jump_native(code,0x407193)
    code.label('gate_wait')
    code.emit('6a14')
    code.native('ff95',0x484218) # Sleep20, existing stdcall IAT.
    code.jump('e9','gate_pump')
    code.label('gate_recover_failed')
    code.own('8985','last_hr')
    mov_one(code,'recovery_pending',1)
    code.emit('3de1007688') # Real DDERR_NOEXCLUSIVEMODE; no fabricated HRESULT.
    code.jump('0f85',recovery_failure_label)
    code.own('ff85','retry_count')
    code.own('81bd','retry_count')
    code.emit('fa000000')
    code.jump('0f83',recovery_failure_label) # attempt250 is the terminal attempt.
    code.jump('e9','gate_wait')
    code.label('gate_quit')
    code.native('c785',0x458c64)
    code.emit('08000000619d83c404')
    # Discard only our original CALL40197b return slot; preserved main frame.
    jump_native(code,0x40196e)


def helper_bundle() -> tuple[bytes, dict[str, int]]:
    """Return own helper bytes and entry offsets, without reading a game."""
    code = _Code()
    _append_capture(code)
    _append_cleanup(code)
    _append_recovery(code)
    append_window_handler(code)
    append_frame_gate(code)
    _append_failure(code)
    return code.finish(), dict(code.labels)


def helper_code() -> bytes:
    return helper_bundle()[0]


def _source_offset(va: int, length: int = 1) -> int:
    for _, _, rva, size, offset, _ in SECTIONS:
        if offset and IMAGE_BASE + rva <= va and va + length <= IMAGE_BASE + rva + size:
            return offset + va - IMAGE_BASE - rva
    raise ValueError("Adres valt buiten gecontroleerde filebytes.")


def _check_imports(data: bytes):
    """Pin imported function identities, not merely their IAT addresses."""
    def u32(offset):
        return struct.unpack_from("<I", data, offset)[0]

    def string(rva):
        offset = _source_offset(IMAGE_BASE + rva)
        end = data.find(b"\0", offset, min(len(data), offset + 256))
        if end < 0:
            raise ValueError("Onbegrensde importnaam voor focusherstel.")
        _source_offset(IMAGE_BASE + rva, end - offset + 1)
        return data[offset:end].decode("ascii")

    expected = {address: (module, name) for name, (address, module) in THUNKS.items()}
    seen = {}
    for index in range(64):
        offset = _source_offset(0x484000 + index * 20, 20)
        lookup, stamp, chain, name, first = struct.unpack_from("<5I", data, offset)
        if not any((lookup, stamp, chain, name, first)):
            break
        module = string(name).lower()
        for entry in range(1024):
            symbol = u32(_source_offset(IMAGE_BASE + (lookup or first) + entry * 4, 4))
            if not symbol:
                break
            address = IMAGE_BASE + first + entry * 4
            if address in expected:
                seen[address] = (module, f"ordinal:{symbol & 0xffff}" if symbol & 0x80000000
                                 else string(symbol + 2))
        else:
            raise ValueError("Onbegrensde importthunks voor focusherstel.")
    else:
        raise ValueError("Onbegrensde importdescriptors voor focusherstel.")
    if seen != expected:
        raise ValueError("Afwijkende API-imports voor focusherstel.")


def _validate_source(data: bytes):
    if len(data) != SOURCE_SIZE or hashlib.sha256(data).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Onbekende racebinaryversie voor focusherstel.")
    if (data[PE_OFFSET:PE_OFFSET + 4] != b"PE\0\0" or
            data[PE_OFFSET + 4:PE_OFFSET + 24] != EXPECTED_COFF or
            data[OPTIONAL_OFFSET:OPTIONAL_OFFSET + len(EXPECTED_OPTIONAL)] != EXPECTED_OPTIONAL):
        raise ValueError("Afwijkende PE-header voor focusherstel.")
    for index, section in enumerate(SECTIONS):
        start = SECTION_TABLE_OFFSET + index * 40
        if data[start:start + 40] != section_record(section):
            raise ValueError("Afwijkende PE-sectie voor focusherstel.")
    for name, (va, original) in SITES.items():
        offset = _source_offset(va, len(original))
        if data[offset:offset + len(original)] != original:
            raise ValueError(f"Afwijkende focusherstelsite: {name}.")
    _check_imports(data)


def checked_patch(data: bytes, render_distance_profile: str = "original") -> bytes:
    """Construct one independently checked race patch, retaining original RVAs."""
    _validate_source(data)
    profiles = {"original": 6, "extended-8": 8, "extended-10": 10, "extended-20": 20}
    if render_distance_profile not in profiles:
        raise ValueError("Onbekend zichtvensterprofiel voor focusherstel.")
    helper, labels = helper_bundle()
    result = bytearray(data)
    for offset in (0x582D8, 0x582DC):
        if struct.unpack_from("<I", data, offset)[0] != 6:
            raise ValueError("Afwijkend zichtvenster-veld voor focusherstel.")
        struct.pack_into("<I", result, offset, profiles[render_distance_profile])
    targets = {name: HELPER_VA + labels["capture" if name.startswith("capture_") else name]
               for name in SITES if name != "end_frame_pump"}
    targets["end_frame_pump"] = 0x401035
    for name, (va, original) in SITES.items():
        offset = _source_offset(va, len(original))
        opcode = 0xE9 if name in ("window_handler", "cache_init") else 0xE8
        replacement = bytes((opcode,)) + struct.pack("<i", targets[name] - va - 5)
        result[offset:offset + len(original)] = replacement + b"\x90" * (len(original) - 5)
    # Insert from the highest offset first, preserving original-offset indexing.
    result[DATA_INSERT_OFFSET:DATA_INSERT_OFFSET] = bytes(DATA_INSERT_SIZE)
    result[INSERT_OFFSET:INSERT_OFFSET] = helper + bytes(INSERT_SIZE - len(helper))
    state_offset = DATA_INSERT_OFFSET + INSERT_SIZE
    for name in ("app_active", "window_active"):
        struct.pack_into("<I", result, state_offset + STATE_OFFSETS[name], 1)
    # SizeOfCode and SizeOfInitializedData grow; all existing image addresses,
    # entrypoint, relocations, import RVAs and SizeOfImage remain unchanged.
    struct.pack_into("<I", result, OPTIONAL_OFFSET + 4, 0x40000)
    struct.pack_into("<I", result, OPTIONAL_OFFSET + 8, 0x19600)
    updated = list(SECTIONS)
    updated[0] = (*SECTIONS[0][:3], 0x40000, 0x400, SECTIONS[0][5])
    updated[1] = (*SECTIONS[1][:3], 0x19600, 0x40400, SECTIONS[1][5])
    updated[3] = (*SECTIONS[3][:4], 0x59A00, SECTIONS[3][5])
    updated[4] = (*SECTIONS[4][:4], 0x5AC00, SECTIONS[4][5])
    for index, section in enumerate(updated):
        start = SECTION_TABLE_OFFSET + index * 40
        result[start:start + 40] = section_record(section)
    if len(result) != SOURCE_SIZE + INSERT_SIZE + DATA_INSERT_SIZE:
        raise ValueError("Onverwachte focusherstel-patchgrootte.")
    return bytes(result)


def plan_fixes(source: Path, render_distance_profile: str = "original") -> list[dict]:
    path = Path(source) / NAME
    if not path.is_file() or path.stat().st_size != SOURCE_SIZE:
        raise ValueError("Gepinde racebinary voor focusherstel ontbreekt.")
    data = path.read_bytes()
    result = checked_patch(data, render_distance_profile)
    helper, labels = helper_bundle()
    return [{"path": NAME, "purpose": "native-race-focus-recovery-experimental",
             "source_path": str(path), "before_sha256": hashlib.sha256(data).hexdigest(),
             "after_sha256": hashlib.sha256(result).hexdigest(), "data": result,
             "runtime_verified": False, "render_distance_profile": render_distance_profile,
             "helper_bytes": len(helper), "helper_va": HELPER_VA, "state_va": STATE_VA,
             "helper_labels": labels, "cache_capacity_max": MAX_CACHE,
             "limitation": "Pre-frame recovery; loss during an active scene can still fail."}]
