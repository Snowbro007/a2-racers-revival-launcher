"""Pinned local native-menu host; uses the game's built-in NOCD route."""
import hashlib
import json
from pathlib import Path
from tools.ii_frontend_state import read_regular

RUN_NAME = 'ii-session-a-20261012'
PINS = {
    'local/ii-parallel/'+RUN_NAME+'/Start-Probe.ps1': 'b7c0a4ac6f518d16395ff5289f1b1e472b8558a4a2dede8da7479e053388a162',
    'reports/a2racer2-next/'+RUN_NAME+'/prepared.json': '86a5511e97fea8cac7d0413b0121164dff994fd0e4abf94a26ee3f09187c09e1',
    'reports/a2racer2-next/'+RUN_NAME+'/copy-prepared.json': '9c0e2f25363e45c29ac36bf62b38cf7b77911e68625fd7409296d94c3c733c7b',
}

def registered_menu(root: Path) -> dict:
    for relative, expected in PINS.items():
        if hashlib.sha256(read_regular(root/relative, 4*1024*1024)).hexdigest() != expected:
            raise ValueError('De oorspronkelijke menu-startprocedure veranderde: '+relative)
    base = root/'local/ii-parallel'/RUN_NAME
    manifest = json.loads(read_regular(root/'reports/a2racer2-next'/RUN_NAME/'copy-prepared.json', 4*1024*1024))
    for entry in manifest['files']:
        relative = entry['path']
        if relative.startswith('DATA/') and (relative.endswith(('.DAT','.EXE','.dll')) or relative in {'DATA/MENURC.IND','DATA/MENURC.IMG','DATA/MRCS.IND','DATA/MRCS.IMG'}):
            if hashlib.sha256(read_regular(base/'game'/relative, 32*1024*1024)).hexdigest() != entry['sha256']:
                raise ValueError('Oorspronkelijk menubestand veranderde: '+relative)
    return {'base': str(base), 'report_path': str(root/'reports/a2racer2-next'/RUN_NAME)}

def availability(root: Path) -> dict:
    try:
        registered_menu(root)
        return {'available': True, 'reason': 'Oorspronkelijk menu lokaal gereed, zonder cd-image. Cursor en Alt+Tab blijven experimenteel.'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'available': False, 'reason': str(exc)}
