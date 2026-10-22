"""Read-only registration and stage selection for the restored native II menu."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from tools.ii_frontend_state import read_regular, validate_ancestors
from tools.trial_manifest import EXPECTED_BINARIES, validate_slug
from tools.ii_menu_cursor_edge_fix import PATCHED_SHA256


def config_signature(raw: bytes) -> bytes:
    """Only the three native menu settings may differ from our safe baseline."""
    parts = raw.splitlines(keepends=True)
    section = b''
    found = set()
    for index, line in enumerate(parts):
        heading = re.fullmatch(rb'\[([^\]]+)\][ \t]*(?:\r?\n)?', line)
        if heading:
            section = heading[1].upper()
        match = re.fullmatch(rb'([ \t]*(RESOLUTION|MUSICVOLUME|SFXVOLUME)[ \t]*=[ \t]*)([0-9]+)([ \t]*(?:;[^\r\n]*)?)(\r?\n)?', line, re.I)
        if not match:
            continue
        key = match[2].upper()
        if (section == b'PROGRAM' and key == b'RESOLUTION') or (section == b'SOUND' and key in (b'MUSICVOLUME', b'SFXVOLUME')):
            if (section, key) in found:
                raise ValueError('Dubbele opgeslagen game-instelling.')
            found.add((section, key))
            value = int(match[3])
            if (key == b'RESOLUTION' and value not in (0, 1, 3)) or (key != b'RESOLUTION' and value > 3100):
                raise ValueError('Ongeldige opgeslagen game-instelling.')
            parts[index] = match[1]+b'<saved>'+match[4]+(match[5] or b'')
    return b''.join(parts)


def registered_menu(root: Path) -> dict:
    from tools.ii_original_prepare import REVISION, MENU_PROFILE_SHA256, race_profile
    pin = json.loads(read_regular(root/'local/ii-parallel/original-current.json', 4096))
    if not isinstance(pin, dict) or set(pin) != {'schema', 'run_name', 'manifest_sha256'} or type(pin['schema']) is not int or pin['schema'] != 1:
        raise ValueError('Onjuiste oorspronkelijke-menuregistratie.')
    validate_slug(pin['run_name'])
    if not pin['run_name'].startswith('ii-original-'+REVISION+'-'):
        raise ValueError('Oorspronkelijk menu moet opnieuw worden voorbereid.')
    base = root/'local/ii-parallel'/pin['run_name']
    raw = read_regular(base/'Original.json', 512*1024)
    if hashlib.sha256(raw).hexdigest() != pin['manifest_sha256']:
        raise ValueError('Oorspronkelijk menumanifest veranderde.')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1
            or manifest.get('revision') != REVISION or manifest.get('game') != 'a2racer2'
            or manifest.get('menu_sha256') != PATCHED_SHA256 or not isinstance(manifest.get('files'), list)):
        raise ValueError('Onjuist oorspronkelijk menumanifest.')
    menu = read_regular(base/'profiles/menu.conf', 65536)
    profiles = {'menu': MENU_PROFILE_SHA256, 'race': hashlib.sha256(race_profile(menu)).hexdigest()}
    if manifest.get('profiles') != profiles:
        raise ValueError('Onverwachte oorspronkelijke-menuprofielen.')
    for stage, expected in profiles.items():
        if hashlib.sha256(read_regular(base/'profiles'/(stage+'.conf'), 65536)).hexdigest() != expected:
            raise ValueError('Menu/raceprofiel veranderde: '+stage)
    current = read_regular(base/'game/DATA/dgVoodoo.conf', 65536)
    if hashlib.sha256(current).hexdigest() not in profiles.values():
        raise ValueError('Actief wrapperprofiel veranderde.')
    files = {}
    for entry in manifest['files']:
        if not isinstance(entry, dict) or set(entry) != {'path', 'size', 'sha256'} or not isinstance(entry['path'], str):
            raise ValueError('Ongeldig menumanifestbestand.')
        name = entry['path']
        parts = PurePosixPath(name)
        if (parts.is_absolute() or any(p in ('..', '.') for p in parts.parts) or ':' in name or '\\' in name
                or not parts.parts or name != parts.as_posix() or name.casefold() in files):
            raise ValueError('Onveilig of dubbel menumanifestpad.')
        files[name.casefold()] = entry
    for name, expected in {'DATA/MENU.DAT': PATCHED_SHA256, 'DATA/SPEL.DAT': EXPECTED_BINARIES['a2racer2']['DATA/SPEL.DAT']}.items():
        if files.get(name.casefold(), {}).get('sha256') != expected:
            raise ValueError('Andere menu/racebinary: '+name)
    for name in ('DATA/DDraw.dll', 'DATA/D3DImm.dll', 'DATA/MENURC.IMG', 'DATA/MENURC.IND', 'DATA/RCS.IMG', 'DATA/RCS.IND', 'DATA/RASER.INI'):
        if name.casefold() not in files:
            raise ValueError('Onvolledige oorspronkelijke menukopie: '+name)
    for entry in files.values():
        name = entry['path']
        # Saves and INIs stay in this persistent copy. Code, resources and
        # tracks cannot change between menu and race.
        if Path(name).suffix.lower() in ('.dat', '.exe', '.dll', '.img', '.ind', '.cmp', '.dmp', '.omp', '.pmp', '.pth', '.rmp'):
            content = read_regular(base/'game'/name, 64*1024**2)
            if len(content) != entry['size'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
                raise ValueError('Oorspronkelijk menubestand veranderde: '+name)
    baseline = read_regular(base/'profiles/RASER.INI', 65536)
    if hashlib.sha256(baseline).hexdigest() != files['data/raser.ini']['sha256']:
        raise ValueError('Referentie van game-instellingen veranderde.')
    if config_signature(baseline) != config_signature(read_regular(base/'game/DATA/RASER.INI', 65536)):
        raise ValueError('Game-instellingen buiten de normale menu-opties veranderden.')
    return {'base': str(base), 'report_path': str(base/'logs'), 'baseline': REVISION,
            'race_runtime_tested': False, 'profiles': profiles}


def select_stage(root: Path, stage: str) -> dict:
    if stage not in ('menu', 'race'):
        raise ValueError('Onbekende oorspronkelijke-menufase.')
    plan = registered_menu(root)
    base = Path(plan['base'])
    target = base/'game/DATA/dgVoodoo.conf'
    validate_ancestors(target)
    target.write_bytes(read_regular(base/'profiles'/(stage+'.conf'), 65536))
    return {**plan, 'stage': stage}


def availability(root: Path) -> dict:
    try:
        registered_menu(root)
        return {'available': True, 'reason': 'Gerestaureerd menu met oorspronkelijke handcursor. Raceovergang en Alt+Tab nog te testen.'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'available': False, 'reason': 'Kies Game voorbereiden voor het oorspronkelijke menu. '+str(exc)}
