"""Bounded II variable-glyph font and archive contracts, no game execution."""
import struct

FONT_PREFIX = 2056
SCALE = 3
FONT_INDICES = (0, 1, 6, 10, 11, 12, 13)
FONT_NAMES = ('OLFNT03.FNT', 'HiMid.fnt', 'OLFNT07.FNT', 'OLFNT01.FNT',
              'OLFNT02.FNT', 'OLFNT04.FNT', 'OLFNT06.FNT')


def decode_font(data):
    if type(data) is not bytes or not FONT_PREFIX <= len(data) <= 8*1024*1024:
        raise ValueError('Onjuist racelettertype.')
    glyphs = {}
    regions = []
    for code in range(256):
        width, height, offset = struct.unpack_from('<hhI', data, code*8)
        if (width, height, offset) == (-1, -1, 0xFFFFFFFF):
            continue
        if not (0 < width <= 1024 and 0 < height <= 1024 and
                FONT_PREFIX <= offset <= len(data)-width*height):
            raise ValueError('Onjuiste glyphgeometrie.')
        regions.append((offset, offset+width*height))
        glyphs[code] = (width, height, data[offset:offset+width*height])
    regions.sort()
    if (not regions or regions[0][0] != FONT_PREFIX or regions[-1][1] != len(data)
            or any(a[1] != b[0] for a, b in zip(regions, regions[1:]))):
        raise ValueError('Glyphs zijn niet exact aansluitend.')
    return data[2048:2056], glyphs


def encode_hd_font(source, pixels):
    header, glyphs = decode_font(source)
    if set(pixels) != set(glyphs):
        raise ValueError('Tekenset moet behouden blijven.')
    result = bytearray(b'\xff'*2048 + header)
    for code, (width, height, _) in sorted(glyphs.items()):
        value = pixels[code]
        if type(value) is not bytes or len(value) != width*height*SCALE*SCALE:
            raise ValueError('Onjuiste HD-glyph.')
        struct.pack_into('<hhI', result, code*8, width*SCALE, height*SCALE, len(result))
        result.extend(value)
    decode_font(bytes(result))
    return bytes(result)


def replace_resources(index, image, replacements):
    """Keep duplicate unrelated II names; selected names must be unique."""
    if type(index) is not bytes or type(image) is not bytes or len(index) < 2:
        raise ValueError('Onjuist archief.')
    count = struct.unpack_from('<H', index)[0]
    if not count or len(index) != 2+count*24:
        raise ValueError('Onjuist aantal archiefrecords.')
    records = [struct.unpack_from('<20sI', index, 2+24*i) for i in range(count)]
    offsets = [o for _, o in records]
    if offsets[0] != 0 or any(a >= b for a, b in zip(offsets, offsets[1:])) or offsets[-1] >= len(image):
        raise ValueError('Onjuiste archiefgrenzen.')
    names = [n.split(b'\0')[0].decode('ascii').casefold() for n, _ in records]
    selected = {name.casefold(): data for name, data in replacements.items()}
    if (len(selected) != len(replacements) or any(names.count(n) != 1 for n in selected)
            or any(type(v) is not bytes or not v for v in selected.values())):
        raise ValueError('Vervangingsnaam ontbreekt of is dubbel.')
    out_index = bytearray(index); out_image = bytearray()
    for i, (_, offset) in enumerate(records):
        end = offsets[i+1] if i+1<count else len(image)
        struct.pack_into('<I', out_index, 2+24*i+20, len(out_image))
        out_image.extend(selected.get(names[i], image[offset:end]))
    return bytes(out_index), bytes(out_image)


def source_rect(rect):
    if len(rect) != 4 or any(type(v) is not int or v < 0 for v in rect):
        raise ValueError('Onjuiste bronrechthoek.')
    return tuple(v*SCALE for v in rect)


def glyph_ink_layout(width, height, pixels):
    """Keep the original ink position inside its advance cell at HD scale.

    Cropping every fresh vector glyph to fill the complete advance cell turns
    a short dash into a tall block and removes punctuation side bearings.
    The cell dimensions/advance stay independent of the visible ink bounds.
    """
    if (type(width) is not int or type(height) is not int or
            not 1 <= width <= 1024 or not 1 <= height <= 1024 or
            type(pixels) is not bytes or len(pixels) != width*height):
        raise ValueError('Onjuiste glyphcel voor HD-plaatsing.')
    occupied = [i for i, value in enumerate(pixels) if value != 255]
    if not occupied:
        return None
    left=min(i%width for i in occupied)*SCALE
    top=min(i//width for i in occupied)*SCALE
    right=(max(i%width for i in occupied)+1)*SCALE
    bottom=(max(i//width for i in occupied)+1)*SCALE
    border=max(1,min((right-left-1)//2,(bottom-top-1)//2,
                     round(min(right-left,bottom-top)*0.055)))
    return {'ink':(left,top,right,bottom),
            'body':(left+border,top+border,right-border,bottom-border),
            'border':border,'cell':(width*SCALE,height*SCALE)}
