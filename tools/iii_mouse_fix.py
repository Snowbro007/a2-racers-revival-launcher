"""Pinned Tour 1 DirectInput mouse-sharing fix; pure bytes, never execute/write."""
import hashlib
from tools import iii_graphics_trial as graphics

SIZE = 659456
CONTEXT = (0x45050, 0x90, 'eceaf62bab745c1b68ca31b900bec95d6854c4cbf150a505b5e6bae3856ca4f7')
MOUSE_GUID_OFFSET = 0x816C0
MOUSE_GUID = bytes.fromhex('602b1d6fa0d5cf11bfc7444553540000')
FLAGS_OFFSET = 0x45090
PINS = {
    graphics.SOURCE_SHA256[1]: '767b3d3869aded880e9cfc9c3073e01f457cee97af590e22716752dd77e4a021',
    graphics.OUTPUT_SHA256[1, True]: '44943b00edfa64bc4001aac814d5e232a8a2fcfbf5740089d1763ef729d93f43',
}


def build(source):
    if type(source) is not bytes or len(source) != SIZE:
        raise ValueError('Onbekende Tour-1-muisbinary.')
    pin = hashlib.sha256(source).hexdigest()
    if pin not in PINS:
        raise ValueError('Onbekende Tour-1-muishash; geen patch gemaakt.')
    offset, size, expected = CONTEXT
    if (hashlib.sha256(source[offset:offset+size]).hexdigest() != expected
            or source[MOUSE_GUID_OFFSET:MOUSE_GUID_OFFSET+16] != MOUSE_GUID
            or source[FLAGS_OFFSET-1:FLAGS_OFFSET+8] != bytes.fromhex('6a05528b0850ff5134')):
        raise ValueError('Andere SysMouse-/SetCooperativeLevel-context.')
    output = source[:FLAGS_OFFSET] + b'\x06' + source[FLAGS_OFFSET+1:]
    digest = hashlib.sha256(output).hexdigest()
    if digest != PINS[pin]:
        raise ValueError('Onverwachte muispatch-uitvoer.')
    return output, {'name': 'iii-tour1-shared-mouse', 'source_sha256': pin,
                    'sha256': digest, 'offset': FLAGS_OFFSET, 'before': '05', 'after': '06',
                    'device': 'GUID_SysMouse', 'cooperative_level': 'NONEXCLUSIVE|FOREGROUND',
                    'keyboard_modified': False, 'runtime_verified': False}
