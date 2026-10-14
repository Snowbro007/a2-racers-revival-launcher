"""Pinned A2-I font measurement guard for optional fullscreen menu copies.

This module constructs immutable bytes only. It does not execute a game,
load a DLL, change originals, or claim Windows runtime compatibility. The
native successful measurement is retained. A failed/invalid surface result
is measured once on an independent memory DC with the same native HFONT.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import struct

from tools import game_fixes
from tools.hud_hd_pe import PicX86

NAME = 'A2MENU.DAT'
SOURCE_SIZE = 295936
SOURCE_SHA256 = '45b883ec76872622241beb75afb3966723d9bee806d76741c29c6642df6ff6e6'
ANY_KEY_SHA256 = '27a87ce4dd5f16683f4726ec0e38f31ba6a179060be481f359663571d710a372'
INPUT_HASHES = {SOURCE_SHA256: False, ANY_KEY_SHA256: True}
OUTPUT_HASHES = {
    False: '8ac03ec6842489153903902008f6673ecd2f3a985a647544c46c156d304b6d21',
    True: 'c08b404ae759f0ebcb757dc6a4eb142985afe71ec4368afff2d9e96d1e7dca19',
}
IMAGE_BASE, PE_OFFSET, OPTIONAL_OFFSET, SECTION_TABLE_OFFSET = 0x400000, 0x80, 0x98, 0x178
SECTION_ALIGNMENT, FILE_ALIGNMENT = 0x1000, 0x200
CODE_RVA, CODE_OFFSET, NEW_HEADER_OFFSET = 0x48000, SOURCE_SIZE, 0x240
CODE_VA = IMAGE_BASE + CODE_RVA
SECTION_NAME, SECTION_FLAGS = b'.mnuinp\0', 0x60000020
COFF = bytes.fromhex('4c01050067e369330000000000000000e0008281')
SECTIONS = (
    (b'BEGTEXT\0', 0, 0x1000, 0x23800, 0x400, 0x60000020),
    (b'DGROUP\0\0', 0, 0x25000, 0x11A00, 0x23C00, 0xC0000040),
    (b'.bss\0\0\0\0', 0, 0x37000, 0xBC00, 0, 0xC0000080),
    (b'.idata\0\0', 0, 0x43000, 0xE00, 0x35600, 0xC0000040),
    (b'.reloc\0\0', 0, 0x44000, 0x3800, 0x36400, 0x42000040),
)
HEIGHT_VA, HEIGHT_OFFSET = 0x4123D8, 0x117D8
HEIGHT_BEFORE = bytes.fromhex(
    '535156575583ec0c89c689d38d4c2408a130814300518b1050ff524485c075d2'
    '833d2c83430000741ba1985e4300c1e0048b889c5e4300518b7c240c57'
    '2eff156c31440089e05053568b6c2414552eff15683144008b542408'
    'a130814300528b1850ff53688b442404eb8c')
FONT_HANDLE_VA = 0x4130FB
FONT_HANDLE_BEFORE = bytes.fromhex(
    '528b15985e430083faff740d89d0c1e0048b809c5e43005ac331c05ac3')
EDIT_CHECK_VA = 0x418128
EDIT_CHECK_BEFORE = bytes.fromhex(
    'ba01000000b8d6fd4200e8a1a2ffff0faf460c3b46047e2b')
SURFACE_VA, FONT_ENABLED_VA, FONT_SLOT_VA = 0x438130, 0x43832C, 0x435E98
ERROR_VA, ERROR_FILE_VA = 0x40BF81, 0x42FDDA
THUNKS = {
    'GetTextExtentPoint32A': (0x443168, 'gdi32.dll'),
    'SelectObject': (0x44316C, 'gdi32.dll'),
    'GetModuleHandleA': (0x443498, 'kernel32.dll'),
    'GetProcAddress': (0x44349C, 'kernel32.dll'),
    'ExitProcess': (0x44345C, 'kernel32.dll'),
}
MAX_FONT_HEIGHT = 480
PROFILES = ('original', 'classic-fullscreen', 'refreshed-fullscreen')


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _section_record(section: tuple) -> bytes:
    name, virtual, rva, raw_size, raw, flags = section
    return struct.pack('<8sIIIIIIHHI', name, virtual, rva, raw_size, raw, 0, 0, 0, 0, flags)


def _offset(va: int, size: int = 1) -> int:
    if type(va) is not int or type(size) is not int or size <= 0:
        raise ValueError('Ongeldige menufont-adresgrens.')
    for _, _, rva, raw_size, raw, _ in SECTIONS:
        if raw and IMAGE_BASE+rva <= va and va+size <= IMAGE_BASE+rva+raw_size:
            return raw+va-IMAGE_BASE-rva
    raise ValueError('Menufont-adres valt buiten gepinde bestandsbytes.')


def _check_imports(data: bytes) -> None:
    def word(rva):
        return struct.unpack_from('<I', data, _offset(IMAGE_BASE+rva, 4))[0]
    def string(rva):
        pos = _offset(IMAGE_BASE+rva)
        end = data.find(b'\0', pos, min(len(data), pos+256))
        if end < 0:
            raise ValueError('Onbegrensde menufont-importnaam.')
        _offset(IMAGE_BASE+rva, end-pos+1)
        try:
            return data[pos:end].decode('ascii')
        except UnicodeDecodeError as error:
            raise ValueError('Niet-ASCII menufont-importnaam.') from error
    irva, size = struct.unpack_from('<II', data, OPTIONAL_OFFSET+104)
    end = irva+size
    expected = {va: (dll, name) for name, (va, dll) in THUNKS.items()}
    seen = {}
    for i in range(64):
        rva = irva+i*20
        if rva+20 > end:
            raise ValueError('Menufont-importdescriptor buiten directory.')
        lookup, stamp, chain, module, first = struct.unpack_from(
            '<5I', data, _offset(IMAGE_BASE+rva, 20))
        if not any((lookup, stamp, chain, module, first)):
            break
        dll = string(module).lower()
        if not first:
            raise ValueError('Menufont-IAT ontbreekt.')
        for index in range(1024):
            symbol = word((lookup or first)+index*4)
            if not symbol:
                break
            va = IMAGE_BASE+first+index*4
            _offset(va, 4)
            if va in expected:
                if va in seen or symbol & 0x80000000:
                    raise ValueError('Dubbel of afwijkend menufont-importslot.')
                seen[va] = (dll, string(symbol+2))
        else:
            raise ValueError('Onbegrensde menufont-importlijst.')
    else:
        raise ValueError('Onbegrensde menufont-importdirectory.')
    if seen != expected:
        raise ValueError('Afwijkende bestaande menufont-API-imports.')


def _validate_input(data: bytes) -> bool:
    if type(data) is not bytes or len(data) != SOURCE_SIZE:
        raise ValueError('Menufont-herstel vereist de gepinde deel-I-menubinary.')
    sha = fingerprint(data)
    if sha not in INPUT_HASHES:
        raise ValueError('Onbekende binaryversie voor menufont-herstel.')
    use_key = INPUT_HASHES[sha]
    if type(use_key) is not bool:
        raise ValueError('Afwijkende menufont-variantpin.')
    if (data[:2] != b'MZ' or struct.unpack_from('<I', data, 60)[0] != PE_OFFSET
            or data[PE_OFFSET:PE_OFFSET+4] != b'PE\0\0'
            or data[PE_OFFSET+4:OPTIONAL_OFFSET] != COFF
            or struct.unpack_from('<H', data, OPTIONAL_OFFSET)[0] != 0x10B
            or struct.unpack_from('<I', data, OPTIONAL_OFFSET+28)[0] != IMAGE_BASE
            or struct.unpack_from('<II', data, OPTIONAL_OFFSET+32) != (SECTION_ALIGNMENT,FILE_ALIGNMENT)
            or struct.unpack_from('<II', data, OPTIONAL_OFFSET+56) != (CODE_RVA,0x400)
            or struct.unpack_from('<I', data, OPTIONAL_OFFSET+4)[0] != 0x23800):
        raise ValueError('Afwijkende gepinde menufont-PE-header.')
    for i, section in enumerate(SECTIONS):
        start = SECTION_TABLE_OFFSET+i*40
        if data[start:start+40] != _section_record(section):
            raise ValueError('Afwijkende gepinde menufont-sectie.')
    if (NEW_HEADER_OFFSET+40 > 0x400 or data[NEW_HEADER_OFFSET:NEW_HEADER_OFFSET+40] != bytes(40)
            or CODE_OFFSET % FILE_ALIGNMENT or CODE_RVA % SECTION_ALIGNMENT):
        raise ValueError('Menufont-sectieheader/ruimte is niet beschikbaar.')
    for va, before in ((HEIGHT_VA,HEIGHT_BEFORE),(FONT_HANDLE_VA,FONT_HANDLE_BEFORE),
                       (EDIT_CHECK_VA,EDIT_CHECK_BEFORE)):
        pos = _offset(va,len(before))
        if data[pos:pos+len(before)] != before:
            raise ValueError('Afwijkend native menufont-codecontract.')
    welcome = (b'\xe8'+struct.pack('<i',game_fixes.KEY_CAVE_VA-game_fixes.WELCOME_CALL_VA-5)
               if use_key else game_fixes.WELCOME_CALL)
    cave = game_fixes.any_key_code() if use_key else bytes(game_fixes.KEY_CAVE_SIZE)
    if (data[game_fixes.WELCOME_CALL_OFFSET:game_fixes.WELCOME_CALL_OFFSET+5] != welcome
            or data[game_fixes.KEY_CAVE_OFFSET:game_fixes.KEY_CAVE_OFFSET+game_fixes.KEY_CAVE_SIZE] != cave):
        raise ValueError('Menufont-variant wijkt af van de behouden welkomstfix.')
    _check_imports(data)
    return use_key


def helper_bundle() -> tuple[bytes, dict[str, int]]:
    """Encode a Watcom register-ABI function with existing stdcall APIs.

    EAX=text, EDX=count. All six saved registers are restored on return.
    Stack locals are SIZE, primary HDC, three resolved function pointers,
    memory HDC, previous HFONT, validated height and selected font. EBP is obtained
    through call/pop; every image reference and native call is relative.
    """
    c = PicX86(CODE_VA, CODE_VA)
    c.label('entry')
    c.hex('53515256575583ec2889c689d3')
    c.base()
    c.hex('31c0')
    for offset in range(0,40,4):
        c.emit(b'\x89\x44\x24'+bytes([offset]))
    c.hex('8d44240850')
    c.relative(b'\x8b\x85',SURFACE_VA)
    c.hex('8b1050ff524485c0')
    c.branch(b'\x0f\x85','native_getdc_failed')
    c.relative(b'\x83\xbd',FONT_ENABLED_VA); c.hex('00')
    c.branch(b'\x0f\x84','primary_measure')
    c.relative(b'\x8b\x85',FONT_SLOT_VA)
    c.hex('83f805'); c.branch(b'\x0f\x87','release_primary')
    c.call_native(FONT_HANDLE_VA)
    c.hex('50ff74240c')
    c.relative(b'\xff\x95',THUNKS['SelectObject'][0])
    c.label('primary_measure')
    c.hex('89e7575356ff742414')
    c.relative(b'\xff\x95',THUNKS['GetTextExtentPoint32A'][0])
    c.hex('85c0'); c.branch(b'\x0f\x84','fallback')
    c.hex('8b470483f800'); c.branch(b'\x0f\x8e','fallback')
    c.hex('3de0010000'); c.branch(b'\x0f\x87','fallback')
    c.hex('8944241c'); c.branch(b'\xe9','release_primary')
    c.label('fallback')
    # Names are in this same RX section. Their offsets are resolved below.
    string_refs=[]
    def text_address(label):
        c.emit(b'\x8d\x85'); string_refs.append((len(c.data),label)); c.emit(bytes(4))
    text_address('gdi_name'); c.hex('50')
    c.relative(b'\xff\x95',THUNKS['GetModuleHandleA'][0])
    c.hex('85c0'); c.branch(b'\x0f\x84','release_primary')
    c.hex('89c7')
    for name, slot in (('create_name',12),('delete_name',16)):
        text_address(name); c.hex('5057')
        c.relative(b'\xff\x95',THUNKS['GetProcAddress'][0])
        c.hex('85c0'); c.branch(b'\x0f\x84','release_primary')
        c.emit(b'\x89\x44\x24'+bytes([slot]))
    c.relative(b'\x83\xbd',FONT_ENABLED_VA); c.hex('00')
    c.branch(b'\x0f\x84','default_font')
    c.relative(b'\x8b\x85',FONT_SLOT_VA)
    c.hex('83f805'); c.branch(b'\x0f\x87','release_primary')
    c.call_native(FONT_HANDLE_VA)
    c.hex('85c0'); c.branch(b'\x0f\x84','release_primary')
    c.hex('89442424'); c.branch(b'\xe9','create_memory')
    c.label('default_font')
    # A new memory DC's stock font need not equal the actual surface DC font.
    text_address('current_name'); c.hex('5057')
    c.relative(b'\xff\x95',THUNKS['GetProcAddress'][0])
    c.hex('85c0'); c.branch(b'\x0f\x84','release_primary')
    c.hex('894424206a06ff74240cff54242885c0')
    c.branch(b'\x0f\x84','release_primary')
    c.hex('89442424')
    c.label('create_memory')
    c.hex('6a00ff5424108944241485c0')
    c.branch(b'\x0f\x84','release_primary')
    c.hex('ff742424ff742418')
    c.relative(b'\xff\x95',THUNKS['SelectObject'][0])
    c.hex('85c0'); c.branch(b'\x0f\x84','delete_memory')
    c.hex('83f8ff'); c.branch(b'\x0f\x84','delete_memory')
    c.hex('89442418')
    c.label('fallback_measure')
    c.hex('31c08904248944240489e7575356ff742420')
    c.relative(b'\xff\x95',THUNKS['GetTextExtentPoint32A'][0])
    c.hex('85c0'); c.branch(b'\x0f\x84','restore_font')
    c.hex('8b470483f800'); c.branch(b'\x0f\x8e','restore_font')
    c.hex('3de0010000'); c.branch(b'\x0f\x87','restore_font')
    c.hex('8944241c')
    c.label('restore_font')
    c.hex('8b44241885c0'); c.branch(b'\x0f\x84','delete_memory')
    c.hex('50ff742418')
    c.relative(b'\xff\x95',THUNKS['SelectObject'][0])
    c.label('delete_memory')
    c.hex('ff742414ff54241485c0'); c.branch(b'\x0f\x85','release_primary')
    c.hex('31c08944241c')
    c.label('release_primary')
    c.hex('ff742408')
    c.relative(b'\x8b\x85',SURFACE_VA)
    c.hex('8b1050ff52688b44241c85c0')
    c.branch(b'\x0f\x85','return')
    # Preserve the existing fatal reporter after both DCs have been released.
    c.hex('c7c0a700000050')
    c.relative(b'\x8d\x85',ERROR_FILE_VA); c.hex('50')
    text_address('error_text'); c.hex('50')
    c.call_native(ERROR_VA)
    c.hex('83c40c6a01')
    c.relative(b'\xff\x95',THUNKS['ExitProcess'][0])
    c.branch(b'\xe9','exit_returned')
    c.label('exit_returned'); c.branch(b'\xe9','exit_returned')
    c.label('native_getdc_failed'); c.hex('c7c0ffffffff')
    c.label('return'); c.hex('83c4285d5f5e5a595bc3')
    for label,text in (
        ('gdi_name',b'GDI32.dll\0'),('create_name',b'CreateCompatibleDC\0'),
        ('delete_name',b'DeleteDC\0'),
        ('current_name',b'GetCurrentObject\0'),
        ('error_text',b'Naamveld: lettergrootte kon niet worden bepaald.\0'),
    ):
        c.label(label); c.emit(text)
    for position,label in string_refs:
        struct.pack_into('<i',c.data,position,c.labels[label])
    return c.finish(),dict(c.labels)


def _patch_unverified(data: bytes) -> bytes:
    code, _ = helper_bundle()
    raw_size = (len(code)+FILE_ALIGNMENT-1)&-FILE_ALIGNMENT
    if not 0 < len(code) <= 0x2000 or CODE_OFFSET+raw_size > SOURCE_SIZE+0x2000:
        raise ValueError('Menufont-helper overschrijdt zijn begrensde sectie.')
    result = bytearray(data)
    result[HEIGHT_OFFSET:HEIGHT_OFFSET+5] = b'\xe9'+struct.pack('<i',CODE_VA-HEIGHT_VA-5)
    struct.pack_into('<H',result,PE_OFFSET+6,6)
    struct.pack_into('<I',result,OPTIONAL_OFFSET+4,0x23800+raw_size)
    struct.pack_into('<I',result,OPTIONAL_OFFSET+56,CODE_RVA+SECTION_ALIGNMENT)
    result[NEW_HEADER_OFFSET:NEW_HEADER_OFFSET+40] = _section_record(
        (SECTION_NAME,len(code),CODE_RVA,raw_size,CODE_OFFSET,SECTION_FLAGS))
    result.extend(code.ljust(raw_size,b'\0'))
    return bytes(result)


def checked_patch(data: bytes) -> tuple[bytes, dict]:
    """Accept only the exact original or preserved welcome-key composition."""
    use_key = _validate_input(data)
    output = _patch_unverified(data)
    if fingerprint(output) != OUTPUT_HASHES.get(use_key):
        raise ValueError('Afwijkende uitvoerhash voor menufont-herstel.')
    code, labels = helper_bundle()
    return output,{
        'purpose':'menu-font-measurement-fallback','runtime_verified':False,
        'source_sha256':fingerprint(data),'patched_sha256':fingerprint(output),
        'height_function_va':HEIGHT_VA,'height_function_offset':HEIGHT_OFFSET,
        'code_section_rva':CODE_RVA,'code_section_offset':CODE_OFFSET,
        'helper_bytes':len(code),'helper_sha256':fingerprint(code),
        'native_success_preserved':True,'native_font_reused':True,
        'measurement_dc':'CreateCompatibleDC(NULL)',
        'fallback_attempts':1,'failure_policy':'release-resources-then-native-fatal',
        'welcome_any_key_preserved':use_key,'overlay_preserved':True,
        'labels':labels,
    }


def _read_source(path: Path) -> bytes:
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != SOURCE_SIZE or path.is_symlink():
            raise ValueError('Gepinde bron voor menufont-herstel ontbreekt of is ongeschikt.')
        with path.open('rb') as reader:
            original = reader.read(SOURCE_SIZE+1)
        after = path.stat()
        if (not stat.S_ISREG(after.st_mode) or after.st_size != SOURCE_SIZE
                or path.is_symlink() or len(original) != SOURCE_SIZE
                or fingerprint(original) != SOURCE_SHA256):
            raise ValueError('Onbekende oorspronkelijke menubinary voor menufont-herstel.')
    except OSError as error:
        raise ValueError('Gepinde bron voor menufont-herstel kon niet worden gelezen.') from error
    return original


def compose_fixes(source: Path, existing_plans: list[dict], profile: str = 'original') -> list[dict]:
    """Fold this opt-in into one A2MENU plan, preserving unrelated plans."""
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError('Onbekend menuprofiel voor menufont-herstel.')
    if type(existing_plans) is not list or any(type(p) is not dict for p in existing_plans):
        raise ValueError('Menufont-herstel vereist expliciete bestaande byteplannen.')
    plans = list(existing_plans)
    if profile == 'original':
        return plans
    path = Path(source)/NAME
    original = _read_source(path)
    matches = [i for i,p in enumerate(plans) if p.get('path') == NAME]
    if len(matches) > 1:
        raise ValueError('Meerdere menuplannen kunnen niet veilig worden gecombineerd.')
    if matches:
        index = matches[0]
        plan = dict(plans[index])
        if (plan.get('before_sha256') != SOURCE_SHA256
                or Path(plan.get('source_path','')).absolute() != path.absolute()
                or type(plan.get('data')) is not bytes
                or fingerprint(plan['data']) != plan.get('after_sha256')):
            raise ValueError('Bestaand menuplan verwijst niet naar de gepinde bron/data.')
        base = plan['data']
    else:
        index = len(plans)
        base = original
        plan = {'path':NAME,'source_path':str(path),'before_sha256':SOURCE_SHA256}
    output,metadata = checked_patch(base)
    purposes = plan.get('purposes',[plan.get('purpose')])
    if not isinstance(purposes,list):
        raise ValueError('Afwijkende bestaande menuplandoelen.')
    purposes = [p for p in purposes if p]
    purposes.append(metadata['purpose'])
    plan.update({'purpose':'+'.join(purposes),'purposes':purposes,'data':output,
                 'after_sha256':fingerprint(output),'runtime_verified':False,
                 'menu_input_fix':metadata})
    if index == len(plans): plans.append(plan)
    else: plans[index] = plan
    return plans
