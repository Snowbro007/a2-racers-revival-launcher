"""Experimental, version-pinned message wait for a fresh A2-I trial copy.

This module reads/constructs bytes only. It does not run a game, change the
original source, suppress errors, change child lifecycle, or restore surfaces.
The exact supplied launcher needs more space than its 58-byte code padding.
We extend its existing code section by one file-aligned block, preserving all
existing RVAs and relocation entries. Runtime compatibility remains unproven.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

EXPECTED_SHA256 = "bb2ed6f29964628771e48707bf8e938c2d2be3bb19d0745bd3e3f5734cec8f13"
SOURCE_SIZE = 0x5E00
PE_OFFSET = 0x80
OPTIONAL_OFFSET = 0x98
SECTION_TABLE_OFFSET = 0x178
IMAGE_BASE = 0x400000
INSERT_OFFSET = 0x3E00
INSERT_SIZE = 0x200
HELPER_VA = 0x404A00
WAIT_CALL_OFFSET = 0x1BFB
WAIT_CALL_VA = 0x4027FB
WAIT_CALL = bytes.fromhex("e872210000")
WAIT_CONTEXT_OFFSET = 0x1BF4
WAIT_CONTEXT = bytes.fromhex("6aff8b74244856e87221000085c07511")
INTRO_OFFSET = 0x6B8
INTRO_CALL = bytes.fromhex("e8fafdffff")
POLL_MS = 20
MESSAGE_BUDGET = 32

# Exact metadata from the hash-pinned PE32. No new import or section is added.
EXPECTED_COFF = bytes.fromhex("4c010600921065330000000000000000e0008281")
EXPECTED_OPTIONAL = bytes.fromhex(
    "0b010212003a0000000e00000002000022150000001000000050000000004000"
    "001000000002000001000b000000000003000a000000000000a0000000040000"
    "0000000002000000000001000000010000200000001000000000000010000000"
    "0000000000000000007000008806000000900000000400000000000000000000"
    "000000000000000000800000d004000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
# (name, virtual_size, RVA, raw_size, raw_pointer, characteristics)
SECTIONS = (
    (b"BEGTEXT", 0, 0x1000, 0x3A00, 0x400, 0x60000020),
    (b"DGROUP", 0, 0x5000, 0xE00, 0x3E00, 0xC0000040),
    (b".bss", 0, 0x6000, 0x200, 0, 0xC0000080),
    (b".idata", 0, 0x7000, 0x800, 0x4C00, 0xC0000040),
    (b".reloc", 0, 0x8000, 0x600, 0x5400, 0x42000040),
    (b".rsrc", 0, 0x9000, 0x400, 0x5A00, 0x40000040),
)
THUNKS = {
    "DispatchMessageA": (0x40488E, 0x3C8E, 0x4070E4, "user32.dll"),
    "TranslateMessage": (0x404894, 0x3C94, 0x407118, "user32.dll"),
    "PeekMessageA": (0x4048A0, 0x3CA0, 0x4070FC, "user32.dll"),
    "PostQuitMessage": (0x40486A, 0x3C6A, 0x407100, "user32.dll"),
    "WaitForSingleObject": (0x404972, 0x3D72, 0x40726C, "kernel32.dll"),
}
RELOCATION_BLOCKS = ((0x1000, 0x110), (0x2000, 0xE0), (0x3000, 0x198),
                     (0x4000, 0xF4), (0x5000, 0x54))
HEADER_UPDATES = (
    (0x9C, 0x3A00, 0x3C00),  # SizeOfCode
    (0x188, 0x3A00, 0x3C00),  # BEGTEXT SizeOfRawData
    (0x1B4, 0x3E00, 0x4000),
    (0x204, 0x4C00, 0x4E00),
    (0x22C, 0x5400, 0x5600),
    (0x254, 0x5A00, 0x5C00),
)


def section_record(section: tuple) -> bytes:
    name, virtual_size, rva, raw_size, raw_pointer, flags = section
    return struct.pack("<8sIIIIIIHHI", name.ljust(8, b"\0"), virtual_size,
                       rva, raw_size, raw_pointer, 0, 0, 0, 0, flags)


class _Code:
    """Small encoder for our own helper; not a game disassembler."""
    def __init__(self):
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.branches: list[tuple[int, str]] = []

    def emit(self, value: str):
        self.data.extend(bytes.fromhex(value))

    def label(self, name: str):
        self.labels[name] = len(self.data)

    def branch(self, opcode: str, name: str):
        self.emit(opcode + "00")
        self.branches.append((len(self.data) - 1, name))

    def call(self, name: str):
        destination = THUNKS[name][0]
        self.data.append(0xE8)
        self.data.extend(struct.pack("<i", destination - (HELPER_VA + len(self.data) + 4)))

    def finish(self) -> bytes:
        for position, name in self.branches:
            self.data[position:position + 1] = struct.pack("b", self.labels[name] - position - 1)
        if len(self.data) > INSERT_SIZE:
            raise ValueError("Wachthelper past niet in de gecontroleerde codesectie-uitbreiding.")
        return bytes(self.data)


def helper_code() -> bytes:
    """stdcall helper(HANDLE, INFINITE); only our call site is redirected.

    EBX=quit pending, ESI=per-batch budget, EDI=handle, EBP=32-byte MSG buffer.
    Preserve nonvolatile registers, consume both original stdcall arguments,
    and retain the terminal wait result in EAX. There is no API call after a
    terminal wait result, including WAIT_FAILED, so GetLastError is preserved.

    WM_QUIT is immediately reposted with its original exit code. Subsequent
    peeks use PM_NOREMOVE, leaving quit for the native outer loop after child
    completion. These peeks still service synchronous sent messages. The
    helper never terminates a child or dismisses an error dialog.
    """
    code = _Code()
    code.emit("5356575583ec208b7c243489e531db")
    code.label("wait")
    code.emit("6a1457")
    code.call("WaitForSingleObject")
    code.emit("3d02010000")  # WAIT_TIMEOUT
    code.branch("75", "done")
    code.emit("be20000000")
    code.label("pump")
    code.emit("85db0f94c00fb6c0506a006a006a0055")  # PM_REMOVE unless quit pending
    code.call("PeekMessageA")
    code.emit("85c0")
    code.branch("74", "wait")
    code.emit("85db")
    code.branch("75", "wait")
    code.emit("837d0412")  # MSG.message == WM_QUIT
    code.branch("74", "quit")
    code.emit("55")
    code.call("TranslateMessage")
    code.emit("55")
    code.call("DispatchMessageA")
    code.emit("4e")
    code.branch("75", "pump")
    code.branch("eb", "wait")
    code.label("quit")
    code.emit("ff7508")
    code.call("PostQuitMessage")
    code.emit("bb01000000")
    code.branch("eb", "wait")
    code.label("done")
    code.emit("83c4205d5f5e5bc20800")
    return code.finish()


def _rva_offset(rva: int, length: int = 1) -> int:
    for _, _, start, size, offset, _ in SECTIONS:
        if offset and start <= rva and rva + length <= start + size:
            return offset + rva - start
    raise ValueError("RVA heeft geen gecontroleerde filebytes voor de wachtreparatie.")


def _import_targets(data: bytes) -> dict[int, tuple[str, str]]:
    def u32(offset: int) -> int:
        return struct.unpack_from("<I", data, offset)[0]

    def string(rva: int) -> str:
        offset = _rva_offset(rva)
        end = data.find(b"\0", offset, min(len(data), offset + 256))
        if end < 0:
            raise ValueError("Onbegrensde importnaam voor de wachtreparatie.")
        # Strings must not run out of .idata into another section.
        _rva_offset(rva, end - offset + 1)
        try:
            return data[offset:end].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("Ongeldige importnaam voor de wachtreparatie.") from error

    result = {}
    for index in range(64):
        offset = _rva_offset(0x7000 + index * 20, 20)
        original, stamp, chain, name, first = struct.unpack_from("<IIIII", data, offset)
        if not any((original, stamp, chain, name, first)):
            return result
        module = string(name).lower()
        for item in range(256):
            symbol = u32(_rva_offset((original or first) + item * 4, 4))
            if not symbol:
                break
            address = IMAGE_BASE + first + item * 4
            _rva_offset(first + item * 4, 4)
            if address in result:
                raise ValueError("Overlappende imports voor de wachtreparatie.")
            result[address] = (module, f"ordinal:{symbol & 0xffff}" if symbol & 0x80000000
                               else string(symbol + 2))
        else:
            raise ValueError("Onbegrensde importtabel voor de wachtreparatie.")
    raise ValueError("Onbegrensde importdescriptors voor de wachtreparatie.")


def _validate_relocations(data: bytes):
    position = 0x5400
    count = 0
    sites = set()
    for page, length in RELOCATION_BLOCKS:
        if struct.unpack_from("<II", data, position) != (page, length):
            raise ValueError("Afwijkende relocatiestructuur voor de wachtreparatie.")
        for item in range(position + 8, position + length, 2):
            value = struct.unpack_from("<H", data, item)[0]
            kind, site = value >> 12, page + (value & 0xFFF)
            if kind == 0:
                continue
            if kind != 3 or site in sites:
                raise ValueError("Afwijkende relocatie voor de wachtreparatie.")
            _rva_offset(site, 4)
            if 0x4A00 <= site < 0x5000:
                raise ValueError("Relocatie verwijst naar de gewenste helperruimte.")
            sites.add(site)
            count += 1
        position += length
    if position != 0x58D0 or count != 592:
        raise ValueError("Afwijkend aantal relocaties voor de wachtreparatie.")
    for _, file_offset, _, _ in THUNKS.values():
        if file_offset - 0x400 + 0x1000 + 2 not in sites:
            raise ValueError("Importthunk mist de oorspronkelijke adresrelocatie.")


def validate_source(data: bytes):
    """Fail closed on both the version pin and the exact PE/ABI assumptions."""
    if len(data) != SOURCE_SIZE or hashlib.sha256(data).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Onbekende binaryversie voor de experimentele parent-wachtreparatie: A2.EXE.")
    if (data[:2] != b"MZ" or struct.unpack_from("<I", data, 0x3C)[0] != PE_OFFSET
            or data[PE_OFFSET:PE_OFFSET + 4] != b"PE\0\0"
            or data[PE_OFFSET + 4:OPTIONAL_OFFSET] != EXPECTED_COFF
            or data[OPTIONAL_OFFSET:SECTION_TABLE_OFFSET] != EXPECTED_OPTIONAL):
        raise ValueError("Afwijkende PE-header voor de parent-wachtreparatie.")
    for index, section in enumerate(SECTIONS):
        start = SECTION_TABLE_OFFSET + index * 40
        if data[start:start + 40] != section_record(section):
            raise ValueError("Afwijkende PE-sectie voor de parent-wachtreparatie.")
    if data[WAIT_CONTEXT_OFFSET:WAIT_CONTEXT_OFFSET + len(WAIT_CONTEXT)] != WAIT_CONTEXT:
        raise ValueError("Afwijkende wachtinstructies voor de parent-wachtreparatie.")
    if data[INTRO_OFFSET:INTRO_OFFSET + len(INTRO_CALL)] != INTRO_CALL:
        raise ValueError("Afwijkende intro-instructie voor de parent-wachtreparatie.")
    if data[0x3DC6:INSERT_OFFSET] != bytes(58):
        raise ValueError("Afwijkende codesectiegrens voor de parent-wachtreparatie.")
    imports = _import_targets(data)
    for symbol, (_, offset, iat, module) in THUNKS.items():
        if (data[offset:offset + 6] != b"\xff\x25" + struct.pack("<I", iat)
                or imports.get(iat) != (module, symbol)):
            raise ValueError("Afwijkende importthunk voor de parent-wachtreparatie.")
    _validate_relocations(data)


def checked_patch(data: bytes, omit_native_intro: bool = False) -> bytes:
    """Return a complete planned copy, composing intro omission from source."""
    validate_source(data)
    if not isinstance(omit_native_intro, bool):
        raise ValueError("De native-introkeuze moet een boolean zijn.")
    helper = helper_code()
    result = bytearray(data[:INSERT_OFFSET] + helper.ljust(INSERT_SIZE, b"\0") + data[INSERT_OFFSET:])
    for offset, before, after in HEADER_UPDATES:
        if struct.unpack_from("<I", data, offset)[0] != before:
            raise ValueError("Afwijkend sectieveld voor de parent-wachtreparatie.")
        struct.pack_into("<I", result, offset, after)
    result[WAIT_CALL_OFFSET:WAIT_CALL_OFFSET + 5] = b"\xe8" + struct.pack("<i", HELPER_VA - WAIT_CALL_VA - 5)
    if omit_native_intro:
        result[INTRO_OFFSET:INTRO_OFFSET + 5] = b"\x90" * 5
    # Existing mapped section bytes must be identical apart from the two named
    # call sites. Header raw pointers change, their memory addresses do not.
    original_code = bytearray(data[0x400:INSERT_OFFSET])
    original_code[WAIT_CALL_OFFSET - 0x400:WAIT_CALL_OFFSET - 0x400 + 5] = result[WAIT_CALL_OFFSET:WAIT_CALL_OFFSET + 5]
    if omit_native_intro:
        original_code[INTRO_OFFSET - 0x400:INTRO_OFFSET - 0x400 + 5] = b"\x90" * 5
    if result[0x400:INSERT_OFFSET] != original_code or result[INSERT_OFFSET + INSERT_SIZE:] != data[INSERT_OFFSET:]:
        raise ValueError("Bestaande gemapte bytes veranderden buiten de geplande wachtreparatie.")
    return bytes(result)


def plan_fixes(source: Path, omit_native_intro: bool = False) -> list[dict]:
    """Compatible with game_fixes.apply_fixes; no write and no implicit default.

    When enabled, this plan replaces the separate A2.EXE intro plan. Both
    changes are composed from the exact original bytes, not patched twice.
    """
    path = source / "A2.EXE"
    if not path.is_file() or path.stat().st_size != SOURCE_SIZE:
        raise ValueError("A2.EXE ontbreekt of heeft een onbekende grootte voor de parent-wachtreparatie.")
    data = path.read_bytes()
    fixed = checked_patch(data, omit_native_intro)
    offsets = [item[0] for item in HEADER_UPDATES] + [WAIT_CALL_OFFSET, INSERT_OFFSET]
    if omit_native_intro:
        offsets.append(INTRO_OFFSET)
    return [{"path": "A2.EXE", "purpose": "parent-message-pump-experimental",
             "purposes": ["parent-message-pump-experimental"] + (["omit-native-intro"] if omit_native_intro else []),
             "source_path": str(path), "before_sha256": hashlib.sha256(data).hexdigest(),
             "after_sha256": hashlib.sha256(fixed).hexdigest(), "data": fixed,
             "offsets": offsets, "inserted_bytes": INSERT_SIZE,
             "helper_va": HELPER_VA, "poll_ms": POLL_MS,
             "message_budget": MESSAGE_BUDGET, "runtime_verified": False}]
