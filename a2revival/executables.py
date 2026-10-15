"""Bounded, read-only inspection of DOS, NE and PE executable headers.

Import entries are observations from file tables. They do not demonstrate that
an API is called, that a DLL is installed, or that the program runs successfully.
No executable bytes are loaded as code by this module.
"""

from __future__ import annotations

import os
from pathlib import Path
import struct
from typing import BinaryIO


MAX_SECTIONS = 4096
MAX_IMPORT_MODULES = 4096
MAX_IMPORT_SYMBOLS = 65536
MAX_STRING_BYTES = 4096


class _InvalidExecutable(Exception):
    """An expected, reportable malformed or unsupported table condition."""


class _Reader:
    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.size = os.fstat(stream.fileno()).st_size

    def read(self, offset: int, size: int, label: str) -> bytes:
        if offset < 0 or size < 0 or offset > self.size or size > self.size - offset:
            raise _InvalidExecutable(f"{label}: bereik valt buiten het bestand (afgebroken of ongeldig).")
        self.stream.seek(offset)
        data = self.stream.read(size)
        if len(data) != size:
            raise _InvalidExecutable(f"{label}: bestand veranderde of is afgebroken tijdens het lezen.")
        return data


class _PEInspector:
    def __init__(self, reader: _Reader, result: dict, header_offset: int):
        self.reader = reader
        self.result = result
        self.header_offset = header_offset
        self.sections: list[tuple[int, int, int, int]] = []
        self.header_size = 0
        self.thunk_size = 0
        self.symbol_count = 0

    def inspect(self) -> None:
        coff = self.reader.read(self.header_offset + 4, 20, "PE COFF-header")
        machine, section_count = struct.unpack_from("<HH", coff)
        optional_size = struct.unpack_from("<H", coff, 16)[0]
        self.result["machine"] = f"0x{machine:04x}"
        self.result["architecture"] = {
            0x014C: "x86", 0x8664: "x86_64", 0x01C0: "arm",
            0x01C4: "armv7", 0xAA64: "arm64", 0x0200: "ia64",
        }.get(machine)
        if section_count > MAX_SECTIONS:
            raise _InvalidExecutable("PE: aantal secties overschrijdt de veilige inspectielimiet.")
        optional = self.reader.read(self.header_offset + 24, optional_size, "PE optional-header")
        if len(optional) < 2:
            raise _InvalidExecutable("PE: optional-header ontbreekt of is afgebroken.")
        magic = struct.unpack_from("<H", optional)[0]
        if magic == 0x010B:
            directories_offset, count_offset, self.thunk_size = 96, 92, 4
            self.result["optional_header"] = "PE32"
        elif magic == 0x020B:
            directories_offset, count_offset, self.thunk_size = 112, 108, 8
            self.result["optional_header"] = "PE32+"
        else:
            raise _InvalidExecutable(f"PE: niet-ondersteunde optional-header magic 0x{magic:04x}.")
        if len(optional) < directories_offset:
            raise _InvalidExecutable("PE: optional-header is te kort voor de vaste velden.")
        self.header_size = struct.unpack_from("<I", optional, 60)[0]
        directory_count = struct.unpack_from("<I", optional, count_offset)[0]
        if directory_count > (len(optional) - directories_offset) // 8:
            raise _InvalidExecutable("PE: aantal data-directories past niet in de optional-header.")
        section_offset = self.header_offset + 24 + optional_size
        section_end = section_offset + section_count * 40
        if self.header_size < section_end or self.header_size > self.reader.size:
            raise _InvalidExecutable("PE: SizeOfHeaders is kleiner dan de headertabellen of groter dan het bestand.")
        for index in range(section_count):
            section = self.reader.read(section_offset + index * 40, 40, "PE sectietabel")
            virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", section, 8)
            span = max(virtual_size, raw_size)
            characteristics = struct.unpack_from("<I", section, 36)[0]
            if raw_size and raw_offset == 0 and characteristics & 0x80 and not characteristics & 0x60:
                # Some historical linkers put the BSS length in SizeOfRawData
                # with a zero PointerToRawData. It does not identify file bytes.
                self.result["issues"].append(
                    f"PE: ongeïnitialiseerde sectie {index + 1} heeft een legacy raw-lengte zonder bestandspositie; niet als bestandsdata gelezen."
                )
                raw_size = 0
            if raw_size and (raw_offset > self.reader.size or raw_size > self.reader.size - raw_offset):
                raise _InvalidExecutable(f"PE: bestandsdata van sectie {index + 1} valt buiten het bestand.")
            self.sections.append((rva, span, raw_offset, raw_size))
        if directory_count <= 1:
            return
        import_rva, import_size = struct.unpack_from("<II", optional, directories_offset + 8)
        if not import_rva and not import_size:
            return
        if not import_rva or import_size < 20:
            raise _InvalidExecutable("PE: import-directory heeft een ongeldige RVA of lengte.")
        self._inspect_imports(import_rva, import_size)

    def _map_rva(self, rva: int, size: int, label: str) -> tuple[int, int]:
        if rva < 0 or rva > 0xFFFFFFFF or size > 0x100000000 - rva:
            raise _InvalidExecutable(f"{label}: ongeldige RVA of RVA-overloop.")
        candidates: list[tuple[int, int]] = []
        if rva < self.header_size:
            candidates.append((rva, self.header_size - rva))
        for section_rva, virtual_size, raw_offset, raw_size in self.sections:
            if section_rva <= rva < section_rva + virtual_size:
                delta = rva - section_rva
                if delta < raw_size:
                    candidates.append((raw_offset + delta, raw_size - delta))
                else:
                    raise _InvalidExecutable(f"{label}: RVA wijst naar een virtueel sectiedeel zonder bestandsdata.")
        if len(candidates) != 1:
            reason = "meerdere overlappende secties" if candidates else "geen bestandssectie"
            raise _InvalidExecutable(f"{label}: RVA verwijst naar {reason}.")
        offset, available = candidates[0]
        if size > available:
            raise _InvalidExecutable(f"{label}: tabel overschrijdt het beschikbare sectiedeel.")
        return offset, available

    def _read_rva(self, rva: int, size: int, label: str) -> bytes:
        offset, _ = self._map_rva(rva, size, label)
        return self.reader.read(offset, size, label)

    def _string(self, rva: int, label: str) -> str:
        offset, available = self._map_rva(rva, 1, label)
        data = self.reader.read(offset, min(available, MAX_STRING_BYTES), label)
        end = data.find(b"\0")
        if end < 0:
            raise _InvalidExecutable(f"{label}: nulterminator ontbreekt binnen de veilige leesgrens.")
        if end == 0:
            raise _InvalidExecutable(f"{label}: lege naam.")
        try:
            return data[:end].decode("ascii")
        except UnicodeDecodeError as error:
            raise _InvalidExecutable(f"{label}: naam bevat ongeldige ASCII-bytes.") from error

    def _inspect_imports(self, rva: int, size: int) -> None:
        descriptor_count = min(size // 20, MAX_IMPORT_MODULES)
        for index in range(descriptor_count):
            descriptor = self._read_rva(rva + index * 20, 20, "PE import-descriptor")
            original_thunk, timestamp, forwarder, name_rva, first_thunk = struct.unpack("<IIIII", descriptor)
            if not any((original_thunk, timestamp, forwarder, name_rva, first_thunk)):
                return
            if not name_rva:
                raise _InvalidExecutable("PE import-descriptor: DLL-naam-RVA ontbreekt.")
            dll = self._string(name_rva, "PE DLL-naam")
            module = {"dll": dll, "symbols": []}
            self.result["imports"].append(module)
            if original_thunk == 0 and timestamp:
                self.result["issues"].append(
                    f"PE: {dll} heeft gebonden imports zonder lookup-tabel; symbolnamen zijn niet afleidbaar."
                )
                continue
            thunk_rva = original_thunk or first_thunk
            if thunk_rva:
                self._inspect_symbols(thunk_rva, module["symbols"])
        if size // 20 > MAX_IMPORT_MODULES:
            raise _InvalidExecutable("PE: aantal import-descriptors overschrijdt de veilige inspectielimiet.")
        raise _InvalidExecutable("PE import-directory: afsluitende nuldescriptor ontbreekt binnen de opgegeven lengte.")

    def _inspect_symbols(self, thunk_rva: int, symbols: list[str]) -> None:
        ordinal_flag = 1 << (self.thunk_size * 8 - 1)
        thunk_format = "<I" if self.thunk_size == 4 else "<Q"
        for index in range(MAX_IMPORT_SYMBOLS + 1):
            thunk = self._read_rva(thunk_rva + index * self.thunk_size, self.thunk_size, "PE import-thunk")
            value = struct.unpack(thunk_format, thunk)[0]
            if value == 0:
                return
            if self.symbol_count >= MAX_IMPORT_SYMBOLS:
                raise _InvalidExecutable("PE: aantal importsymbolen overschrijdt de veilige inspectielimiet.")
            if value & ordinal_flag:
                if value & ~(ordinal_flag | 0xFFFF):
                    raise _InvalidExecutable("PE import-thunk: ordinaal bevat ongeldige gereserveerde bits.")
                symbol = f"#{value & 0xFFFF}"
            else:
                self._read_rva(value, 2, "PE import-name hint")
                symbol = self._string(value + 2, "PE importsymbool")
            symbols.append(symbol)
            self.symbol_count += 1


def _inspect_ne(reader: _Reader, result: dict, offset: int) -> None:
    header = reader.read(offset, 64, "NE-header")
    result["architecture"] = "x86-16"
    module_count = struct.unpack_from("<H", header, 0x1E)[0]
    reference_offset, names_offset = struct.unpack_from("<HH", header, 0x28)
    if module_count > MAX_IMPORT_MODULES:
        raise _InvalidExecutable("NE: aantal importmodules overschrijdt de veilige inspectielimiet.")
    if module_count:
        if reference_offset < 64 or names_offset < 64:
            raise _InvalidExecutable("NE: importtabellen overlappen de vaste header.")
        references = reader.read(offset + reference_offset, module_count * 2, "NE module-referentietabel")
        for index in range(module_count):
            name_offset = struct.unpack_from("<H", references, index * 2)[0]
            name_position = offset + names_offset + name_offset
            length = reader.read(name_position, 1, "NE importnaam-lengte")[0]
            if not length:
                raise _InvalidExecutable("NE: lege importmodulenaam.")
            raw_name = reader.read(name_position + 1, length, "NE importmodulenaam")
            # NE names use the historical Windows byte encoding, not Unicode.
            name = raw_name.decode("cp1252", errors="replace")
            result["imports"].append({"dll": name, "symbols": []})
    result["issues"].append("NE: alleen module-importnamen geïnspecteerd; importsymbolen en relocaties zijn niet geanalyseerd.")


def inspect_executable(path: Path) -> dict:
    """Return bounded static observations; never execute or modify ``path``.

    ``status`` is ``invalid`` for malformed supported structures, ``unknown``
    for unrecognized or unsupported formats, and ``inspected`` otherwise.
    Partial import observations can remain in an invalid result. Ordinals are
    rendered as ``#123``. Delay imports and NE symbol relocations are not parsed.
    """
    result = {
        "format": "unknown", "status": "unknown", "issues": [],
        "architecture": None, "imports": [],
    }
    try:
        with Path(path).open("rb") as stream:
            reader = _Reader(stream)
            if reader.size < 2 or reader.read(0, 2, "Bestandssignatuur") != b"MZ":
                return result
            result["format"] = "DOS"
            if reader.size < 28:
                raise _InvalidExecutable("DOS MZ-header is afgebroken.")
            # Old DOS programs may have a header shorter than the later 64-byte
            # extended header. Their code at offset 60 is not an e_lfanew field.
            dos = reader.read(0, min(reader.size, 64), "DOS MZ-header")
            header_size = struct.unpack_from("<H", dos, 8)[0] * 16
            if len(dos) < 64 or header_size < 64:
                if header_size < 28 or header_size > reader.size:
                    raise _InvalidExecutable("DOS MZ-header heeft een ongeldige headerlengte.")
                result["status"] = "inspected"
                result["architecture"] = "x86-16"
                return result
            header_offset = struct.unpack_from("<I", dos, 60)[0]
            if header_offset == 0:
                if header_size > reader.size:
                    raise _InvalidExecutable("DOS MZ-header is groter dan het bestand.")
                result["status"] = "inspected"
                result["architecture"] = "x86-16"
                return result
            relocation_count = struct.unpack_from("<H", dos, 6)[0]
            relocation_offset = struct.unpack_from("<H", dos, 24)[0]
            relocation_end = relocation_offset + relocation_count * 4
            if relocation_count and relocation_offset <= 60 < relocation_end:
                if relocation_offset < 28 or relocation_end > header_size or header_size > reader.size:
                    raise _InvalidExecutable("DOS MZ-relocatietabel valt buiten de header.")
                result["status"] = "inspected"
                result["architecture"] = "x86-16"
                result["issues"].append("Klassiek DOS: offset 60 behoort tot de relocatietabel en is geen uitgebreide-headerpointer.")
                return result
            if relocation_offset != 64 and (header_offset < 64 or header_offset > reader.size - 2):
                result["architecture"] = "x86-16"
                result["issues"].append(
                    "Klassiek DOS-headerpatroon: offset 60 is geen betrouwbare uitgebreide-headerpointer; verdere inhoud is niet geanalyseerd."
                )
                return result
            if header_offset < 64:
                raise _InvalidExecutable("DOS e_lfanew verwijst naar de DOS-header zelf.")
            signature = reader.read(header_offset, 2, "Uitgebreide executable-signatuur")
            if signature == b"PE":
                result["format"] = "PE"
                if reader.read(header_offset, 4, "PE-signatuur") != b"PE\0\0":
                    raise _InvalidExecutable("PE-signatuur mist de twee nulbytes.")
                _PEInspector(reader, result, header_offset).inspect()
            elif signature == b"NE":
                result["format"] = "NE"
                _inspect_ne(reader, result, header_offset)
            elif signature in (b"LE", b"LX"):
                result["format"] = signature.decode("ascii")
                result["issues"].append("LE/LX-signatuur herkend; verdere header- en importanalyse wordt niet ondersteund.")
                return result
            else:
                result["issues"].append("DOS: onbekende uitgebreide signatuur; inhoud is niet verder geanalyseerd.")
                return result
            result["status"] = "inspected"
    except _InvalidExecutable as error:
        result["status"] = "invalid"
        result["issues"].append(str(error))
    except (OSError, ValueError) as error:
        result["status"] = "invalid"
        result["issues"].append(f"Bestand kon niet veilig worden gelezen: {error}")
    return result
