"""Bounded PCX v5 codec for the observed 8-bit, one-plane A2-I resources.

Only file-format conversion is provided: no scaling, texture generation or game
execution. Pixels are palette indices. Decoding retains row padding and header
metadata, but re-encoding uses canonical per-row RLE, not original RLE bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

MAX_DIMENSION = 4096
MAX_PIXELS = 16 * 1024 * 1024
MAX_PCX_BYTES = 40 * 1024 * 1024
HEADER_BYTES = 128
PALETTE_BYTES = 768


@dataclass(frozen=True)
class IndexedImage:
    width: int
    height: int
    pixels: bytes
    palette: bytes
    header: bytes = b""
    row_padding: bytes = b""


def _dimensions(width: int, height: int) -> None:
    if (type(width) is not int or type(height) is not int or
            not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION or
            width * height > MAX_PIXELS):
        raise ValueError("PCX-afmetingen vallen buiten de gecontroleerde limiet.")


def _validate_image(image: IndexedImage) -> None:
    _dimensions(image.width, image.height)
    if not isinstance(image.pixels, bytes) or len(image.pixels) != image.width * image.height:
        raise ValueError("PCX-pixels moeten precies één paletindex per pixel bevatten.")
    if not isinstance(image.palette, bytes) or len(image.palette) != PALETTE_BYTES:
        raise ValueError("PCX vereist precies 256 RGB-paletkleuren.")


def decode_pcx(data: bytes) -> IndexedImage:
    """Decode exactly the observed format, rejecting truncated or ambiguous rows."""
    if not isinstance(data, bytes) or not HEADER_BYTES + 1 + PALETTE_BYTES <= len(data) <= MAX_PCX_BYTES:
        raise ValueError("PCX-bestand ontbreekt, is afgekapt of te groot.")
    header = data[:HEADER_BYTES]
    if header[:4] != bytes((10, 5, 1, 8)) or header[65] != 1:
        raise ValueError("Alleen PCX v5, RLE, 8 bits en één plane zijn gecontroleerd.")
    xmin, ymin, xmax, ymax = struct.unpack_from("<4H", header, 4)
    if xmax < xmin or ymax < ymin:
        raise ValueError("Ongeldige PCX-coördinaten.")
    width, height = xmax - xmin + 1, ymax - ymin + 1
    _dimensions(width, height)
    bytes_per_line = struct.unpack_from("<H", header, 66)[0]
    if bytes_per_line < width or bytes_per_line % 2 or bytes_per_line > MAX_DIMENSION:
        raise ValueError("Ongeldige PCX BytesPerLine of rijpadding.")
    if data[-PALETTE_BYTES - 1] != 12:
        raise ValueError("PCX mist het expliciete 256-kleurenpalet.")
    compressed_end = len(data) - PALETTE_BYTES - 1
    cursor = HEADER_BYTES
    pixels = bytearray()
    padding = bytearray()
    for _ in range(height):
        row = bytearray()
        while len(row) < bytes_per_line:
            if cursor >= compressed_end:
                raise ValueError("PCX RLE-rij is afgekapt.")
            value = data[cursor]
            cursor += 1
            if value & 0xC0 == 0xC0:
                count = value & 0x3F
                if count == 0 or cursor >= compressed_end:
                    raise ValueError("Ongeldige of afgekapt PCX RLE-run.")
                value = data[cursor]
                cursor += 1
            else:
                count = 1
            if len(row) + count > bytes_per_line:
                raise ValueError("PCX RLE-run overschrijdt de rijgrens.")
            row.extend(bytes((value,)) * count)
        pixels.extend(row[:width])
        padding.extend(row[width:])
    if cursor != compressed_end:
        raise ValueError("PCX bevat onverwachte bytes na de laatste RLE-rij.")
    return IndexedImage(width, height, bytes(pixels), data[-PALETTE_BYTES:], header, bytes(padding))


def _encode_row(row: bytes) -> bytes:
    result = bytearray()
    cursor = 0
    while cursor < len(row):
        value = row[cursor]
        count = 1
        while cursor + count < len(row) and row[cursor + count] == value and count < 63:
            count += 1
        if count > 1 or value >= 0xC0:
            result.append(0xC0 | count)
        result.append(value)
        cursor += count
    return bytes(result)


def encode_pcx(image: IndexedImage, *, template_header: bytes | None = None) -> bytes:
    """Encode indices without changing their colour palette or resampling them.

    A template preserves unmodified header metadata. Image coordinates and row
    size are adjusted to the supplied dimensions; a new image uses zero origin.
    The PCX format has no alpha channel. Transparency meaning belongs to the
    game loader, so this codec never invents a transparent palette index.
    """
    _validate_image(image)
    source_header = template_header if template_header is not None else image.header
    if source_header:
        if (not isinstance(source_header, bytes) or len(source_header) != HEADER_BYTES or
                source_header[:4] != bytes((10, 5, 1, 8)) or source_header[65] != 1):
            raise ValueError("PCX-headertemplate heeft een ongecontroleerd formaat.")
        header = bytearray(source_header)
        xmin, ymin = struct.unpack_from("<2H", header, 4)
    else:
        header = bytearray(HEADER_BYTES)
        xmin = ymin = 0
        struct.pack_into("<2H", header, 12, 72, 72)
        struct.pack_into("<H", header, 68, 1)
    if xmin + image.width - 1 > 65535 or ymin + image.height - 1 > 65535:
        raise ValueError("PCX-afmetingen passen niet bij de headeroorsprong.")
    header[:4] = bytes((10, 5, 1, 8))
    header[65] = 1
    struct.pack_into("<4H", header, 4, xmin, ymin, xmin + image.width - 1, ymin + image.height - 1)
    bytes_per_line = (image.width + 1) & ~1
    struct.pack_into("<H", header, 66, bytes_per_line)
    padding_width = bytes_per_line - image.width
    if image.row_padding and (not isinstance(image.row_padding, bytes) or
                              len(image.row_padding) != padding_width * image.height):
        raise ValueError("PCX-rijpadding past niet bij de opgegeven afmetingen.")
    padding = image.row_padding or bytes(padding_width * image.height)
    compressed = bytearray()
    for row_index in range(image.height):
        row = image.pixels[row_index * image.width:(row_index + 1) * image.width]
        row += padding[row_index * padding_width:(row_index + 1) * padding_width]
        compressed.extend(_encode_row(row))
    result = bytes(header) + bytes(compressed) + b"\x0c" + image.palette
    if len(result) > MAX_PCX_BYTES:
        raise ValueError("Gecodeerde PCX overschrijdt de bestandsgroottelimiet.")
    return result
