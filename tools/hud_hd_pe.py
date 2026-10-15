"""Pure-byte, pinned A2-I section planner for an own HD HUD prototype.

This module does not read/write files, execute native code or install hooks.
Only the 32 independently pinned existing race compositions are accepted.
Caller-owned code must use image-relative/PIC references: no new relocations
or imports are added. The bounded encoder below supports that contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct

from tools import object_distance_fix as objects
from tools import race_focus_fix as focus

IMAGE_BASE = focus.IMAGE_BASE
SECTION_ALIGNMENT, FILE_ALIGNMENT = 0x1000, 0x200
CODE_NAME, STATE_NAME = b".hudrx", b".hudrw"
CODE_FLAGS, STATE_FLAGS = 0x60000020, 0xC0000040
# The optional cockpit atlas set exceeds32MiB; keep a hard64MiB section cap.
# This does not alter any existing v2 section size, layout or output bytes.
MAX_CODE_BYTES, MAX_STATE_BYTES = 0x10000, 0x4000000
UINT32_MAX = 0xFFFFFFFF
NEW_HEADER_OFFSET = focus.SECTION_TABLE_OFFSET + len(focus.SECTIONS) * 40
ALLOWED_HEADER_CHANGES = (
    (focus.PE_OFFSET + 6, focus.PE_OFFSET + 8),
    (focus.OPTIONAL_OFFSET + 4, focus.OPTIONAL_OFFSET + 12),
    (focus.OPTIONAL_OFFSET + 56, focus.OPTIONAL_OFFSET + 60),
    (NEW_HEADER_OFFSET, NEW_HEADER_OFFSET + 80),
)


@dataclass(frozen=True)
class Variant:
    focus_recovery: bool
    render_distance: str
    camera: str
    object_distance: str


KNOWN_VARIANTS = {
    sha: Variant(*key, object_profile)
    for object_profile, table in (
        ("original", objects.BASE_SHA256_BY_VARIANT),
        ("loaded-all", objects.EXPECTED_PATCHED_SHA256_BY_VARIANT),
    )
    for key, sha in table.items()
}


@dataclass(frozen=True)
class SectionLayout:
    input_sha256: str
    input_size: int
    variant: Variant
    code_rva: int
    state_rva: int
    code_offset: int
    state_offset: int
    code_size: int
    state_size: int
    code_raw_size: int
    state_raw_size: int
    state_virtual_size: int
    image_size: int
    size_of_code: int
    size_of_initialized_data: int

    @property
    def code_va(self) -> int:
        return IMAGE_BASE + self.code_rva

    @property
    def state_va(self) -> int:
        return IMAGE_BASE + self.state_rva


@dataclass(frozen=True)
class AppendPlan:
    data: bytes
    layout: SectionLayout
    output_sha256: str
    allowed_header_changes: tuple[tuple[int, int], ...] = ALLOWED_HEADER_CHANGES
    runtime_verified: bool = False


def _u32(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= UINT32_MAX:
        raise ValueError(f"Ongeldige 32-bitwaarde: {label}.")
    return value


def _add(first: int, second: int, label: str) -> int:
    return _u32(_u32(first, label) + _u32(second, label), label)


def checked_align(value: int, alignment: int) -> int:
    """Checked alignment shared by the byte planner and synthetic tests."""
    _u32(value, "alignment input")
    if type(alignment) is not int or not 0 < alignment <= 0x10000 or alignment & (alignment - 1):
        raise ValueError("Afwijkende PE-alignment.")
    return _add(value, alignment - 1, "alignment overflow") & -alignment


def expected_sections(use_focus: bool) -> tuple[tuple, ...]:
    """Exact previously audited layout; no section is inferred or relocated."""
    if type(use_focus) is not bool:
        raise ValueError("Afwijkende focusvariant.")
    sections = list(focus.SECTIONS)
    if use_focus:
        sections[0] = (*sections[0][:3], 0x40000, 0x400, sections[0][5])
        sections[1] = (*sections[1][:3], 0x19600, 0x40400, sections[1][5])
        sections[3] = (*sections[3][:4], 0x59A00, sections[3][5])
        sections[4] = (*sections[4][:4], 0x5AC00, sections[4][5])
    return tuple(sections)


def _mapped_offset(data: bytes, sections: tuple[tuple, ...], rva: int, size: int = 1) -> int:
    end = _add(rva, size, "mapped extent")
    for _, _, section_rva, raw_size, raw, _ in sections:
        if raw and section_rva <= rva and end <= section_rva + raw_size:
            offset = raw + rva - section_rva
            if offset + size <= len(data):
                return offset
    raise ValueError("HUD-importadres valt buiten gecontroleerde filebytes.")


def _check_imports(data: bytes, sections: tuple[tuple, ...]) -> None:
    def word(rva):
        return struct.unpack_from("<I", data, _mapped_offset(data, sections, rva, 4))[0]

    def string(rva):
        offset = _mapped_offset(data, sections, rva)
        end = data.find(b"\0", offset, min(len(data), offset + 256))
        if end < 0:
            raise ValueError("Onbegrensde HUD-importnaam.")
        _mapped_offset(data, sections, rva, end - offset + 1)
        try:
            return data[offset:end].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("Niet-ASCII HUD-importnaam.") from error

    expected = {va: (module, name) for name, (va, module) in focus.THUNKS.items()}
    seen = {}
    import_rva, import_size = struct.unpack_from("<II", data, focus.OPTIONAL_OFFSET + 104)
    directory_end = _add(import_rva, import_size, "import directory")
    for index in range(64):
        descriptor = _add(import_rva, index * 20, "import descriptor")
        if descriptor + 20 > directory_end:
            raise ValueError("HUD-importdescriptor buiten directory.")
        lookup, stamp, chain, name, first = struct.unpack_from(
            "<5I", data, _mapped_offset(data, sections, descriptor, 20))
        if not any((lookup, stamp, chain, name, first)):
            break
        module = string(name).lower()
        if not module or not first:
            raise ValueError("Onvolledige HUD-importdescriptor.")
        for entry in range(1024):
            symbol = word(_add(lookup or first, entry * 4, "import lookup"))
            iat_rva = _add(first, entry * 4, "import IAT")
            _mapped_offset(data, sections, iat_rva, 4)
            if not symbol:
                break
            identity = (f"ordinal:{symbol & 0xffff}" if symbol & 0x80000000
                        else string(_add(symbol, 2, "import hint")))
            address = IMAGE_BASE + iat_rva
            if address in expected:
                if address in seen:
                    raise ValueError("Dubbel HUD-importslot.")
                seen[address] = (module, identity)
        else:
            raise ValueError("Onbegrensde HUD-importthunks.")
    else:
        raise ValueError("Onbegrensde HUD-importdescriptors.")
    if seen != expected:
        raise ValueError("Afwijkende bestaande API-imports voor HUD-helper.")


def _validate_input(data: bytes, expected_sha256: str) -> tuple[Variant, tuple[tuple, ...]]:
    if type(data) is not bytes or type(expected_sha256) is not str or expected_sha256 not in KNOWN_VARIANTS:
        raise ValueError("HUD-helper vereist een bekende exacte A2-I inputhash.")
    variant = KNOWN_VARIANTS[expected_sha256]
    expected_size = objects.SIZE_BY_FOCUS[variant.focus_recovery]
    if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("HUD-helper input wijkt af van zijn gepinde racevariant.")
    optional = bytearray(focus.EXPECTED_OPTIONAL)
    if variant.focus_recovery:
        struct.pack_into("<II", optional, 4, 0x40000, 0x19600)
    if (data[:2] != b"MZ" or struct.unpack_from("<I", data, 0x3C)[0] != focus.PE_OFFSET
            or data[focus.PE_OFFSET:focus.PE_OFFSET + 4] != b"PE\0\0"
            or data[focus.PE_OFFSET + 4:focus.OPTIONAL_OFFSET] != focus.EXPECTED_COFF
            or data[focus.OPTIONAL_OFFSET:focus.SECTION_TABLE_OFFSET] != bytes(optional)):
        raise ValueError("Afwijkende gepinde MZ/PE/COFF/optional HUD-header.")
    sections = expected_sections(variant.focus_recovery)
    raw_extents, mapped_extents = [], []
    for index, section in enumerate(sections):
        header = focus.SECTION_TABLE_OFFSET + index * 40
        if data[header:header + 40] != focus.section_record(section):
            raise ValueError("Afwijkende gepinde HUD-inputsectie.")
        name, virtual_size, rva, raw_size, raw, _ = section
        if name in (CODE_NAME, STATE_NAME):
            raise ValueError("HUD-secties bestaan reeds.")
        if rva % SECTION_ALIGNMENT or raw_size % FILE_ALIGNMENT or (raw and raw % FILE_ALIGNMENT):
            raise ValueError("Afwijkende bestaande HUD-sectiealignment.")
        mapped_extents.append((rva, checked_align(_add(rva, max(virtual_size, raw_size), "section extent"), SECTION_ALIGNMENT)))
        if raw:
            raw_end = _add(raw, raw_size, "raw section extent")
            if raw < 0x400 or raw_end > len(data):
                raise ValueError("HUD-inputsectie buiten bestand/headergrens.")
            raw_extents.append((raw, raw_end))
    for extents in (raw_extents, mapped_extents):
        ordered = sorted(extents)
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
            raise ValueError("Overlappende bestaande HUD-inputsecties.")
    if max(end for _, end in raw_extents) != len(data):
        raise ValueError("HUD-input bevat een ongecontroleerde file-overlay.")
    if max(end for _, end in mapped_extents) != 0x8D000:
        raise ValueError("Afwijkende bestaande HUD-imagegrens.")
    first_raw = min(start for start, _ in raw_extents)
    if NEW_HEADER_OFFSET + 80 > min(first_raw, 0x400) or data[NEW_HEADER_OFFSET:NEW_HEADER_OFFSET + 80] != bytes(80):
        raise ValueError("Twee lege HUD-sectionheaders ontbreken.")
    _check_imports(data, sections)
    return variant, sections


def plan_layout(data: bytes, expected_sha256: str, code_size: int, state_size: int, *,
                state_virtual_size: int | None = None) -> SectionLayout:
    """Determine own code/state addresses before the final PIC encoding pass."""
    variant, _ = _validate_input(data, expected_sha256)
    if type(code_size) is not int or not 1 <= code_size <= MAX_CODE_BYTES:
        raise ValueError("HUD-helpercode heeft een ongeldige/begrenzingoverschrijdende lengte.")
    if type(state_size) is not int or not 0 <= state_size <= MAX_STATE_BYTES:
        raise ValueError("HUD-initdata heeft een ongeldige/begrenzingoverschrijdende lengte.")
    virtual_size = max(4, state_size) if state_virtual_size is None else state_virtual_size
    if type(virtual_size) is not int or not max(4, state_size) <= virtual_size <= MAX_STATE_BYTES:
        raise ValueError("HUD-RW virtual size is onvoldoende of onbegrensd.")
    code_raw_size = checked_align(code_size, FILE_ALIGNMENT)
    state_raw_size = checked_align(state_size, FILE_ALIGNMENT) if state_size else 0
    code_rva, code_offset = 0x8D000, checked_align(len(data), FILE_ALIGNMENT)
    state_rva = checked_align(_add(code_rva, code_raw_size, "HUD RX image extent"), SECTION_ALIGNMENT)
    state_offset = _add(code_offset, code_raw_size, "HUD RX file extent")
    image_size = checked_align(_add(state_rva, max(virtual_size, state_raw_size), "HUD RW image extent"), SECTION_ALIGNMENT)
    _add(IMAGE_BASE, image_size, "HUD image VA overflow")
    size_of_code, size_of_data = struct.unpack_from("<II", data, focus.OPTIONAL_OFFSET + 4)
    return SectionLayout(expected_sha256, len(data), variant, code_rva, state_rva,
                         code_offset, state_offset, code_size, state_size,
                         code_raw_size, state_raw_size, virtual_size, image_size,
                         _add(size_of_code, code_raw_size, "SizeOfCode"),
                         _add(size_of_data, state_raw_size, "SizeOfInitializedData"))


def append_sections(data: bytes, expected_sha256: str, code: bytes, state: bytes = b"", *,
                    state_virtual_size: int | None = None) -> AppendPlan:
    """Return checked appended bytes; this deliberately has no file writer/CLI."""
    if type(code) is not bytes or type(state) is not bytes:
        raise ValueError("HUD-code en initdata moeten immutable bytes zijn.")
    layout = plan_layout(data, expected_sha256, len(code), len(state), state_virtual_size=state_virtual_size)
    result = bytearray(data)
    struct.pack_into("<H", result, focus.PE_OFFSET + 6, 7)
    struct.pack_into("<II", result, focus.OPTIONAL_OFFSET + 4,
                     layout.size_of_code, layout.size_of_initialized_data)
    struct.pack_into("<I", result, focus.OPTIONAL_OFFSET + 56, layout.image_size)
    rx = (CODE_NAME, len(code), layout.code_rva, layout.code_raw_size, layout.code_offset, CODE_FLAGS)
    rw = (STATE_NAME, layout.state_virtual_size, layout.state_rva,
          layout.state_raw_size, layout.state_offset if layout.state_raw_size else 0, STATE_FLAGS)
    result[NEW_HEADER_OFFSET:NEW_HEADER_OFFSET + 80] = focus.section_record(rx) + focus.section_record(rw)
    result.extend(bytes(layout.code_offset - len(result)))
    result.extend(code)
    result.extend(bytes(layout.code_raw_size - len(code)))
    result.extend(state)
    result.extend(bytes(layout.state_raw_size - len(state)))
    output = bytes(result)
    # Enforce the scope independently of how bytes above were assembled.
    for start, end in ((0, ALLOWED_HEADER_CHANGES[0][0]),
                       *[(left[1], right[0]) for left, right in zip(ALLOWED_HEADER_CHANGES, ALLOWED_HEADER_CHANGES[1:])],
                       (ALLOWED_HEADER_CHANGES[-1][1], len(data))):
        if output[start:end] != data[start:end]:
            raise ValueError("HUD-append veranderde bestaande bytes buiten de headerwhitelist.")
    if len(output) != layout.state_offset + layout.state_raw_size:
        raise ValueError("Afwijkende HUD-append filelengte.")
    return AppendPlan(output, layout, hashlib.sha256(output).hexdigest())


class PicX86:
    """Bounded own-code encoder; callers preserve EBP before calling base().

    Native rel32 calls and EBP-relative image addresses survive whole-image
    relocation. Its address helpers emit no absolute VA immediates or PE relocations.
    emit() is intentionally restricted to trusted own instruction bytes.
    """
    def __init__(self, code_va: int, state_va: int):
        self.code_va = _u32(code_va, "PIC code VA")
        self.state_va = _u32(state_va, "PIC state VA")
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.branches: list[tuple[int, str]] = []

    def emit(self, value: bytes) -> None:
        if type(value) is not bytes or len(self.data) + len(value) > MAX_CODE_BYTES:
            raise ValueError("Ongeldige of te lange eigen x86-code.")
        self.data.extend(value)

    def hex(self, value: str) -> None:
        self.emit(bytes.fromhex(value))

    def label(self, name: str) -> None:
        if type(name) is not str or not name or name in self.labels:
            raise ValueError("Ongeldig of dubbel eigen x86-label.")
        self.labels[name] = len(self.data)

    @staticmethod
    def _signed(value: int) -> bytes:
        if not -(1 << 31) <= value < (1 << 31):
            raise ValueError("Eigen x86-displacement valt buiten signed rel32.")
        return struct.pack("<i", value)

    def branch(self, opcode: bytes, label: str) -> None:
        if (type(opcode) is not bytes or type(label) is not str or not label
                or (opcode not in (b"\xe8", b"\xe9") and not
                    (len(opcode) == 2 and opcode[0] == 0x0F and 0x80 <= opcode[1] <= 0x8F))):
            raise ValueError("Ongeldige eigen rel32-opcode.")
        self.emit(opcode)
        self.branches.append((len(self.data), label))
        self.emit(bytes(4))

    def call_native(self, address: int) -> None:
        self.emit(b"\xe8" + self._signed(_u32(address, "native call VA") - self.code_va - len(self.data) - 5))

    def jump_native(self, address: int) -> None:
        self.emit(b"\xe9" + self._signed(_u32(address, "native jump VA") - self.code_va - len(self.data) - 5))

    def relative(self, opcode: bytes, address: int) -> None:
        if type(opcode) is not bytes or len(opcode) not in (2, 3) or opcode[-1] & 0xC7 != 0x85:
            raise ValueError("Eigen image-reference vereist een EBP+disp32 ModR/M-opcode.")
        self.emit(opcode + self._signed(_u32(address, "image-relative VA") - self.code_va))

    def state(self, opcode: bytes, offset: int) -> None:
        self.relative(opcode, _add(self.state_va, offset, "own state VA"))

    def base(self) -> None:
        return_offset = len(self.data) + 5
        self.emit(b"\xe8\0\0\0\0\x5d\x81\xed" + struct.pack("<I", return_offset))

    def finish(self) -> bytes:
        result = bytearray(self.data)
        for position, label in self.branches:
            if label not in self.labels:
                raise ValueError("Onopgelost eigen x86-label.")
            result[position:position + 4] = self._signed(self.labels[label] - position - 4)
        return bytes(result)
