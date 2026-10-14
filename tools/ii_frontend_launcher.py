"""Read-only registration check for the locally prepared II Revival menu."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from tools.ii_frontend_state import read_regular, RACE_DISPLAYS, race_binary_sha
from tools.trial_manifest import EXPECTED_BINARIES, validate_slug

MENU_PROFILES = {
    'revival': {'label': 'Revival-menu (aanbevolen)',
                'description': 'Schermvullend menu met één Windows-cursor, eigen spelers, garage en records. Aanbevolen 16:9-race zonder cd-image: 60 baanstukken, egale lucht, horizon en wolken uit. Klassieke 4:3-keuze bij Opties.'},
    'original': {'label': 'Origineel menu (instabiel)',
                 'description': 'Oorspronkelijk MENU.DAT. Bekende problemen met cursor, knipperen en Alt+Tab. Start zonder cd-image via de eigen menu/race-host.'},
}
SOURCE_FILES = {'Menu.ps1': 'ii_frontend.ps1', 'Menu.xaml': 'ii_frontend.xaml',
                'Backend.py': 'ii_frontend_state.py', 'OwnedSession.ps1': 'ii_owned_session.ps1'}
PART_ART_NAMES = ('motor', 'tires', 'turbo', 'brakes', 'gears')
PART_ART_FILES = {f'assets/part-{name}.png' for name in PART_ART_NAMES}
RACE_DISPLAY_FILES = {'game/DATA/SPEL-WIDE.DAT','profiles/classic.conf','profiles/widescreen.conf'}


def registered_menu(root: Path) -> dict:
    registration = json.loads(read_regular(root/'local/ii-parallel/frontend-current.json', 4096))
    if (not isinstance(registration, dict) or set(registration) != {'schema','run_name','frontend_sha256'}
            or type(registration['schema']) is not int or registration['schema'] != 1):
        raise ValueError('Onjuiste Revival-menuregistratie.')
    validate_slug(registration['run_name'])
    if not registration['run_name'].startswith('ii-frontend'):
        raise ValueError('Onbekende Revival-menukopie.')
    base = root/'local/ii-parallel'/registration['run_name']
    raw = read_regular(base/'Frontend.json', 65536)
    if hashlib.sha256(raw).hexdigest() != registration['frontend_sha256']:
        raise ValueError('Revival-menuregistratie komt niet overeen met de kopie.')
    config = json.loads(raw)
    if (not isinstance(config,dict) or config.get('schema') != 1 or config.get('game') != 'a2racer2'
            or config.get('native_menu_used') is not False or config.get('synthetic_fixture')
            or not isinstance(config.get('files'), list)):
        raise ValueError('Onjuiste Revival-menuconfiguratie.')
    # A sealed copy must point at its own game and its own report directory.
    # Copying a frontend without updating these fields used to pass readiness.
    if (config.get('game_path') != str(base/'game') or
            config.get('report_path') != str(root/'reports/a2racer2-next'/base.name)):
        raise ValueError('Revival-menu verwijst niet naar zijn eigen game- en rapportmap.')
    required = set(SOURCE_FILES) | {'game/DATA/SPEL.DAT','game/DATA/DDraw.dll',
        'game/DATA/D3DImm.dll','game/DATA/GARAGE.INI',
        'assets/wheel.json','assets/arrow32.cur','assets/arrow48.cur'}
    required |= {f'assets/car{i}.json' for i in range(7)} | {f'assets/texture{i}.png' for i in range(4)}
    required |= PART_ART_FILES
    required |= RACE_DISPLAY_FILES
    if config.get('wide_race_variant') == 'flat-sky60':
        required |= {'game/DATA/RCS.IND', 'game/DATA/RCS.IMG'}
    if config.get('preview_detail_revision') == '20261013':
        required.add('assets/car4-preview.png')
    if config.get('fleet_preview_revision') == '20261013':
        required |= {f'assets/car{i}-preview.png' for i in range(7)}
    if type(config.get('race_display_version')) is not int or config.get('race_display_version') != 1:
        raise ValueError('Revival-menu moet opnieuw worden voorbereid voor de raceweergave.')
    if config.get('menu_music_revision') == '20261013':
        from tools.ii_menu_music import MUSIC_FILES
        required |= MUSIC_FILES
    entries = config['files']
    if (len(entries) != len(required) or any(not isinstance(e,dict) or set(e) != {'path','sha256'} for e in entries)
            or any(not isinstance(e['path'],str) or e['path'] not in required for e in entries)
            or {e['path'] for e in entries} != required):
        raise ValueError('Revival-menu mist zijn vaste bestandcontracten.')
    for entry in entries:
        maximum = 64*1024*1024 if entry['path'] == 'game/DATA/RCS.IMG' else 8*1024*1024
        content = read_regular(base/entry['path'], maximum)
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('Revival-menubestand veranderde: '+entry['path'])
        if config.get('menu_music_revision') == '20261013' and entry['path'].startswith('assets/music/'):
            from tools.ii_menu_music import TRACK_SHA256
            if entry['sha256'] != TRACK_SHA256.get(entry['path'].split('/')[-1]):
                raise ValueError('Andere originele menumuziek.')
        if entry['path'] in SOURCE_FILES and content != read_regular(root/'tools'/SOURCE_FILES[entry['path']], 1024*1024):
            raise ValueError('Revival-menu moet opnieuw worden voorbereid: '+entry['path'])
        if entry['path'] == 'game/DATA/SPEL.DAT' and entry['sha256'] != EXPECTED_BINARIES['a2racer2']['DATA/SPEL.DAT']:
            raise ValueError('Andere deel-II-racebinary.')
        if entry['path'] == 'game/DATA/SPEL-WIDE.DAT' and entry['sha256'] != race_binary_sha(config, 'widescreen', RACE_DISPLAYS['widescreen']['sha256']):
            raise ValueError('Andere deel-II-breedbeeldbinary.')
        for spec in RACE_DISPLAYS.values():
            if entry['path'] == spec['profile'] and entry['sha256'] != spec['profile_sha256']:
                raise ValueError('Andere deel-II-raceweergaveconfiguratie.')
    read_regular(base/'game/DATA/dgVoodoo.conf', 65536)  # mutable active selection
    for track in range(7):
        for ext in ('CMP','DMP','OMP','PMP','PTH','RMP'):
            read_regular(base/f'game/DATA/ETAPPE{track}.{ext}', 8*1024*1024)
    return {'base': str(base), 'report_path': str(root/'reports/a2racer2-next'/registration['run_name']),
            'menu_revision': config.get('menu_revision')}


def availability(root: Path) -> dict:
    result = {'available': False, 'reason': 'Het Revival-menu moet lokaal worden voorbereid.'}
    try:
        registered_menu(root)
        result.update(available=True, reason='Revival-menu en oorspronkelijke racebestanden gecontroleerd.')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if (root/'local/ii-parallel/frontend-current.json').exists():
            result['reason'] = str(exc)
    return result
