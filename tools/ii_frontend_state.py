"""II replacement menu state and INI bridge. Never execute native game code.

The CLI is scoped to a new local frontend copy. Native binaries remain intact;
MENU.DAT/options.ras/SLOTS.RAS are not read, patched or launched by this bridge.
"""
from __future__ import annotations

import argparse
import configparser
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import uuid

CAR_NAMES = ('Brabant', 'Opol Astro', 'Wolfswagen', 'BWM Z3.5',
             'Parche 913', 'Mersedes SLK GTR', 'Lambdaghini')
TRACK_NAMES = ('Amsterdam', 'Amsterdam → Den Haag', 'Den Haag',
               'Den Haag → Rotterdam', 'Rotterdam',
               'Rotterdam → Amsterdam', 'Amsterdam finale')
UPGRADES = {'motor': ('MOTOR', 1), 'tires': ('BANDEN', 2),
            'turbo': ('TURBO', 4), 'brakes': ('ABS', 5),
            'gears': ('VERSNELLINGSBAK', 6)}
STAT_KEYS = ('speed', 'acceleration', 'braking', 'handling')
MAX_STATE_BYTES = 256 * 1024
RACE_DISPLAYS = {
    'classic': {'binary': 'SPEL.DAT', 'profile': 'profiles/classic.conf',
                'sha256': '551484bcf472407fd67ee8933c6f26b5a937d428e9e0cdf0cd72988dd003c2f9',
                'profile_sha256': '6de487f0edbab8ec5d60d826211631ea3bc0a0d8ddc10a0bbe7eeca2b7f8c2f5'},
    'widescreen': {'binary': 'SPEL-WIDE.DAT', 'profile': 'profiles/widescreen.conf',
                   'sha256': '1e5cef6499bd001ace3f22ff0a818101fe43bcf80b2ff086f0d912e6f3891016',
                   'profile_sha256': '3efd468f9844e8031b1f804c761d23c94f0a2fed66fa7b7d35dbac44faa33d3a'},
}

HORIZON_OFF60_SHA256 = 'cea74cf07d38bacaf213d3b1d9559b31b7f15a773525faab6f3e782989eab560'
FLAT_SKY60_SHA256 = '933a144a0484982e8c126af45204947aca21b66aba6e8e40e3637f2c141e7521'


def race_binary_sha(config: dict, mode: str, standard_sha: str | None = None) -> str:
    variant = config.get('wide_race_variant', 'standard')
    if variant not in ('standard', 'horizon-off60', 'flat-sky60') or type(variant) is not str:
        raise ValueError('Onbekende racevariant.')
    if variant == 'horizon-off60' and mode == 'widescreen':
        return HORIZON_OFF60_SHA256
    if variant == 'flat-sky60' and mode == 'widescreen':
        return FLAT_SKY60_SHA256
    return standard_sha if standard_sha is not None else RACE_DISPLAYS[mode]['sha256']


def validate_ancestors(path: Path) -> None:
    for candidate in (path.absolute(), *path.absolute().parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)):
                raise ValueError('Menupad bevat een link of gedeeld bestand.')


def read_regular(path: Path, maximum: int) -> bytes:
    validate_ancestors(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('Lokaal menubestand ontbreekt of is te groot: ' + path.name)
    return path.read_bytes()


def read_ini(data: bytes) -> configparser.ConfigParser:
    if type(data) is not bytes or not 1 <= len(data) <= 128 * 1024:
        raise ValueError('INI ontbreekt of is te groot.')
    parser = configparser.ConfigParser(interpolation=None, strict=True,
                                      inline_comment_prefixes=(';',), empty_lines_in_values=False)
    parser.read_string(data.decode('latin1'))
    return parser


def integer(parser, section, key, low, high):
    value = parser.get(section, key)
    if not re.fullmatch(r'-?[0-9]+', value):
        raise ValueError('Geen geldige gamewaarde: ' + key)
    return bounded(int(value), low, high, key)


def bounded(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Ongeldige waarde: ' + label)
    return value


def replace_ini(data: bytes, changes: dict[tuple[str, str], str]) -> bytes:
    """Change unique values only; preserve comments, order and every other byte."""
    read_ini(data)  # rejects duplicate sections/keys before any change
    active = ''
    seen = set()
    output = []
    changes = {(s.lower(), k.lower()): str(v) for (s, k), v in changes.items()}
    for line in data.decode('latin1').splitlines(keepends=True):
        header = re.fullmatch(r'[ \t]*\[([^\]]+)\][ \t]*(?:\r?\n)?', line)
        if header:
            active = header[1].lower()
        match = re.fullmatch(r'([ \t]*([^=;\r\n]+?)[ \t]*=[ \t]*)([^;\r\n]*?)([ \t]*(?:;[^\r\n]*)?)(\r?\n)?', line)
        if match and (active, match[2].strip().lower()) in changes:
            key = (active, match[2].strip().lower())
            if key in seen:
                raise ValueError('Dubbele INI-keuze.')
            seen.add(key)
            line = match[1] + changes[key] + match[4] + (match[5] or '')
        output.append(line)
    if seen != set(changes):
        raise ValueError('Vereiste INI-keuze ontbreekt.')
    result = ''.join(output).encode('latin1')
    read_ini(result)
    return result


def new_profile(name: str) -> dict:
    if type(name) is not str or not 1 <= len(name.strip()) <= 24 or any(ord(c) < 32 for c in name):
        raise ValueError('Gebruik een naam van 1 tot 24 leesbare tekens.')
    return {'id': uuid.uuid4().hex, 'name': name.strip(), 'car': 0, 'money': 35000,
            'damage': 0, 'upgrades': {key: False for key in UPGRADES}, 'records': {}, 'next_track': 0,
            'damage_mesh': '-1,-1,-1,-1,-1,-1,-1,-1',
            'damage_value': '-1,-1,-1,-1,-1,-1,-1,-1'}


def initial_state() -> dict:
    profile = new_profile('Speler')
    return {'schema': 1, 'profiles': [profile], 'selected': profile['id'], 'track': 0,
            'settings': {'effects': 100, 'music': 0, 'menu_music': 600, 'difficulty': 0, 'laps': 2,
                         'large_cursor': True, 'center_cursor': True, 'race_display': 'widescreen',
                         'keys': {'LEFT': 37, 'RIGHT': 39, 'UP': 38, 'DOWN': 40,
                                  'EXTRA1': 17, 'EXTRA2': 18}},
            'pending': None, 'last_message': 'Klaar voor de start.'}


def damage_array(value: str, *, mesh: bool) -> str:
    if type(value) is not str or len(value) > 256:
        raise ValueError('Ongeldige schadegegevens.')
    parts = value.split(',')
    if len(parts) != 8:
        raise ValueError('Schadegegevens bevatten geen acht waarden.')
    for part in parts:
        number = int(part) if mesh else float(part)
        if not math.isfinite(number) or not -1 <= number <= 1000000:
            raise ValueError('Schadegegevens buiten bereik.')
    return value


def validate_state(state: dict) -> dict:
    if type(state) is not dict or state.get('schema') != 1:
        raise ValueError('Onbekende menustatus.')
    profiles = state.get('profiles')
    if type(profiles) is not list or not 1 <= len(profiles) <= 8:
        raise ValueError('Ongeldige spelerslijst.')
    ids = set()
    for p in profiles:
        if type(p) is not dict or not re.fullmatch('[a-f0-9]{32}', p.get('id', '')) or p['id'] in ids:
            raise ValueError('Ongeldige speler-ID.')
        ids.add(p['id'])
        new_profile(p.get('name'))  # same name validation, no native save conversion
        for key, high in [('car', 6), ('money', 1000000000), ('damage', 100)]:
            bounded(p.get(key), 0, high, key)
        if set(p.get('upgrades', {})) != set(UPGRADES) or any(type(v) is not bool for v in p['upgrades'].values()):
            raise ValueError('Ongeldige onderdelen.')
        damage_array(p.get('damage_mesh'), mesh=True)
        damage_array(p.get('damage_value'), mesh=False)
        if type(p.get('records')) is not dict or len(p['records']) > 7:
            raise ValueError('Ongeldige records.')
        for key, value in p['records'].items():
            if key not in {str(i) for i in range(7)}:
                raise ValueError('Onbekende recordbaan.')
            bounded(value, 1, 86400000, 'record')
        if 'next_track' not in p:
            # Migrate only consecutive finishes: a later free-race record cannot skip stages.
            p['next_track'] = 0
            while p['next_track'] < 7 and str(p['next_track']) in p['records']:
                p['next_track'] += 1
        bounded(p['next_track'], 0, 7, 'next_track')
    if state.get('selected') not in ids:
        raise ValueError('Spelerselectie ontbreekt.')
    bounded(state.get('track'), 0, 6, 'track')
    settings = state.get('settings', {})
    # Old profiles acquire only a display preference; player data is retained.
    settings.setdefault('race_display', 'widescreen')
    settings.setdefault('menu_music', 600)
    if type(settings['race_display']) is not str or settings['race_display'] not in RACE_DISPLAYS:
        raise ValueError('Onbekende raceweergave.')
    for key, high in [('effects', 3100), ('music', 3100), ('menu_music', 3100), ('difficulty', 1), ('laps', 20)]:
        bounded(settings.get(key), 1 if key == 'laps' else 0, high, key)
    for key in ['large_cursor', 'center_cursor']:
        if type(settings.get(key)) is not bool:
            raise ValueError('Ongeldige cursorinstelling.')
    keys = settings.get('keys', {})
    if set(keys) != {'LEFT', 'RIGHT', 'UP', 'DOWN', 'EXTRA1', 'EXTRA2'}:
        raise ValueError('Vereiste racetoets ontbreekt.')
    for value in keys.values():
        bounded(value, 1, 254, 'racetoets')
        if value in (1, 2, 4, 27, 115):
            raise ValueError('Gebruik een gewone racetoets.')
    if len(set(keys.values())) != 6:
        raise ValueError('Kies zes verschillende racetoetsen.')
    pending = state.get('pending')
    if pending is not None:
        if (type(pending) is not dict or not re.fullmatch('[a-f0-9]{32}', pending.get('token', ''))
                or pending.get('profile') not in ids):
            raise ValueError('Ongeldige lopende race.')
        bounded(pending.get('track'), 0, 6, 'pending track')
        bounded(pending.get('car'), 0, 6, 'pending car')
        if (type(pending.get('race_display', 'classic')) is not str or
                pending.get('race_display', 'classic') not in RACE_DISPLAYS):
            raise ValueError('Onbekende lopende raceweergave.')
    if type(state.get('last_message')) is not str or len(state['last_message']) > 500:
        raise ValueError('Ongeldige menumelding.')
    return state


def profile(state: dict) -> dict:
    return next(p for p in state['profiles'] if p['id'] == state['selected'])


def atomic_write(path: Path, data: bytes) -> None:
    validate_ancestors(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(data)
            stream.flush()
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def load_state(base: Path) -> dict:
    validate_ancestors(base)
    path = base / 'menu-state.json'
    if not path.exists():
        return initial_state()
    state = validate_state(json.loads(read_regular(path, MAX_STATE_BYTES)))
    state['track'] = min(state['track'], profile(state)['next_track'], 6)
    return state


def save_state(base: Path, state: dict) -> None:
    validate_state(state)
    path = base / 'menu-state.json'
    if path.exists():
        atomic_write(base / 'menu-state.previous.json', read_regular(path, MAX_STATE_BYTES))
    atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2).encode())


def catalog(base: Path) -> dict:
    ini = read_ini(read_regular(base / 'game/DATA/GARAGE.INI', 16384))
    cars = []
    for i, name in enumerate(CAR_NAMES):
        cars.append({'id': i, 'name': name, 'price': integer(ini, 'prices', f'car{i+1}', 1, 1000000),
                     'speed': integer(ini, 'percents', f'car{i+1}_perc1', 1, 1000),
                     'acceleration': integer(ini, 'percents', f'car{i+1}_perc2', 0, 100),
                     'braking': integer(ini, 'percents', f'car{i+1}_perc3', 0, 100),
                     'handling': integer(ini, 'percents', f'car{i+1}_perc4', 0, 100),
                     'repair': integer(ini, 'prices', f'item3_car{i+1}', 1, 10000),
                     'upgrades': {key: integer(ini, 'prices', f'item{item}_car{i+1}', 1, 1000000)
                                  for key, (_, item) in UPGRADES.items()}})
    effects = {key: {stat_key: integer(ini, 'percents', f'item{item}_perc{j}', 0, 100)
                     for j, stat_key in enumerate(STAT_KEYS, 1)}
               for key, (_, item) in UPGRADES.items()}
    return {'cars': cars, 'upgrade_effects': effects, 'tracks': [{'id': i, 'name': name, 'city': i in (0, 2, 4, 6)}
                                    for i, name in enumerate(TRACK_NAMES)]}


def garage_stats(state: dict, catalog_data: dict) -> dict:
    """Original garage figures, keeping bonus points separate from km/h.

    GARAGE.INI is a menu specification, not a measured physics contract. Do
    not convert its item*_perc values into an invented maximum race speed.
    """
    p = profile(validate_state(state))
    car = catalog_data['cars'][p['car']]
    effects = catalog_data['upgrade_effects']
    bonuses = {key: sum(effects[item][key] for item in UPGRADES if p['upgrades'][item])
               for key in STAT_KEYS}
    after = {item: {key: bonuses[key] + (0 if p['upgrades'][item] else effects[item][key])
                    for key in STAT_KEYS} for item in UPGRADES}
    # Relative garage display, never an assertion about measured race km/h.
    # Speed uses a 100..300 reference range; other source figures use 0..100.
    reference = {key: (car[key]-100)/2 if key == 'speed' else car[key]
                 for key in STAT_KEYS}
    clamp = lambda value: max(0, min(100, value))
    bars = {key: clamp(reference[key]+bonuses[key]) for key in STAT_KEYS}
    previews = {item: {key: clamp(reference[key]+after[item][key]) for key in STAT_KEYS}
                for item in UPGRADES}
    return {'base': {key: car[key] for key in STAT_KEYS}, 'bonuses': bonuses,
            'after_purchase': after, 'bars': bars, 'bars_after_purchase': previews}


def mutate(state: dict, command: str, payload: dict, catalog_data: dict) -> dict:
    state = copy.deepcopy(validate_state(state))
    if state['pending'] and command != 'discard':
        raise ValueError('Rond de vorige race eerst af of probeer opnieuw.')
    p = profile(state)
    if command == 'reset':
        if (not isinstance(payload, dict) or set(payload) != {'confirmed'}
                or payload['confirmed'] is not True):
            raise ValueError('Bevestig eerst dat je opnieuw wilt beginnen.')
        state = initial_state()
        state['last_message'] = 'Opnieuw begonnen. Je hebt een nieuwe speler en ƒ 35.000.'
        return state
    if command == 'name':
        p['name'] = new_profile(payload['name'])['name']
    elif command == 'player':
        if 'new_name' in payload:
            if len(state['profiles']) == 8:
                raise ValueError('Er zijn al acht spelers.')
            p = new_profile(payload['new_name'])
            state['profiles'].append(p)
            state['selected'] = p['id']
        elif payload.get('id') in {p['id'] for p in state['profiles']}:
            state['selected'] = payload['id']
        else:
            raise ValueError('Onbekende speler.')
        state['track'] = min(profile(state)['next_track'], 6)
    elif command == 'track':
        track = bounded(payload['track'], 0, 6, 'track')
        if track > p['next_track']:
            raise ValueError('Deze etappe is nog vergrendeld. Voltooi eerst de vorige race.')
        state['track'] = track
    elif command == 'settings':
        if not set(payload) <= set(state['settings']):
            raise ValueError('Onbekende instelling.')
        state['settings'].update(payload)
    elif command == 'buy':
        car = bounded(payload['car'], 0, 6, 'car')
        if car == p['car']:
            raise ValueError('Deze auto heb je al.')
        cost = catalog_data['cars'][car]['price']
        if cost > p['money']:
            raise ValueError('Niet genoeg geld voor deze auto.')
        p.update(car=car, money=p['money'] - cost, damage=0,
                 upgrades={key: False for key in UPGRADES},
                 damage_mesh='-1,-1,-1,-1,-1,-1,-1,-1',
                 damage_value='-1,-1,-1,-1,-1,-1,-1,-1')
    elif command in ('upgrade', 'repair'):
        car = catalog_data['cars'][p['car']]
        if command == 'repair':
            if p['damage'] == 0:
                raise ValueError('Je auto heeft geen schade.')
            cost = p['damage'] * car['repair']
        else:
            item = payload['item']
            if item not in UPGRADES or p['upgrades'][item]:
                raise ValueError('Dit onderdeel is al gemonteerd of onbekend.')
            cost = car['upgrades'][item]
        if cost > p['money']:
            raise ValueError('Niet genoeg geld.')
        p['money'] -= cost
        if command == 'repair':
            p.update(damage=0, damage_mesh='-1,-1,-1,-1,-1,-1,-1,-1',
                     damage_value='-1,-1,-1,-1,-1,-1,-1,-1')
        else:
            p['upgrades'][item] = True
    elif command == 'discard':
        state['pending'] = None
    else:
        raise ValueError('Onbekende menuactie.')
    state['last_message'] = 'Opgeslagen.'
    return validate_state(state)


def race_inputs(state: dict, game_ini: bytes, raser_ini: bytes) -> tuple[bytes, bytes, dict]:
    validate_state(state)
    if state['pending']:
        raise ValueError('Er staat al een race klaar.')
    p, s = profile(state), state['settings']
    if state['track'] > p['next_track']:
        raise ValueError('Deze etappe is nog vergrendeld. Voltooi eerst de vorige race.')
    changes = {('ETAPPE', 'etappe'): state['track'], ('PLAYER', 'car'): p['car'],
               ('PLAYER', 'money'): p['money'], ('PLAYER', 'damage'): p['damage'],
               ('PLAYER', 'finished'): 0, ('PLAYER', 'tracktime'): 0, ('PLAYER', 'position'): 0,
               ('PLAYER', 'copland'): 0, ('PLAYER', 'DAMAGE_MESH'): p['damage_mesh'],
               ('PLAYER', 'DAMAGE_VALUE'): p['damage_value'], ('INPUT', 'DEVICE'): 1,
               ('OPTIONS', 'Difficulty'): s['difficulty'], ('OPTIONS', 'Nrlaps'): s['laps']}
    changes.update({('PLAYER', native): int(p['upgrades'][key]) for key, (native, _) in UPGRADES.items()})
    changes.update({('INPUT', key): value for key, value in s['keys'].items()})
    result_game = replace_ini(game_ini, changes)
    result_raser = replace_ini(raser_ini, {('PROGRAM', 'RESOLUTION'): 3,
                    ('MOVIES', 'ON'): 0, ('HELPDESK', 'DEBUGON'): 0,
                    ('SOUND', 'MUSICVOLUME'): s['music'], ('SOUND', 'SFXVOLUME'): s['effects']})
    pending = {'token': uuid.uuid4().hex, 'profile': p['id'], 'track': state['track'], 'car': p['car']}
    return result_game, result_raser, pending


def race_display_files(base: Path, state: dict) -> tuple[str, bytes | None]:
    config_path = base / 'Frontend.json'
    if not config_path.exists():
        return 'classic', None  # legacy, synthetic model-only fixtures
    config = json.loads(read_regular(config_path, 65536))
    if type(config.get('race_display_version')) is not int or config.get('race_display_version') != 1:
        return 'classic', None  # older locally prepared menu
    mode = state['settings']['race_display']
    spec = RACE_DISPLAYS[mode]
    binary = read_regular(base / 'game/DATA' / spec['binary'], 1024*1024)
    profile_bytes = read_regular(base / spec['profile'], 65536)
    if (hashlib.sha256(binary).hexdigest() != race_binary_sha(config, mode) or
            hashlib.sha256(profile_bytes).hexdigest() != spec['profile_sha256']):
        raise ValueError('Raceweergavebestanden veranderden; race niet gestart.')
    return mode, profile_bytes


def start_race(base: Path, state: dict) -> dict:
    data = base / 'game/DATA'
    original = {n: read_regular(data / n, 128 * 1024) for n in ('GAME.INI', 'RASER.INI')}
    game, raser, pending = race_inputs(state, original['GAME.INI'], original['RASER.INI'])
    mode, display_profile = race_display_files(base, state)
    pending['race_display'] = mode
    if display_profile is not None:
        original['dgVoodoo.conf'] = read_regular(data/'dgVoodoo.conf', 65536)
    # Validate map components before committing any chosen values or pending state.
    for ext in ('CMP', 'DMP', 'OMP', 'PMP', 'PTH', 'RMP'):
        read_regular(data / f'ETAPPE{state["track"]}.{ext}', 8 * 1024 * 1024)
    planned = copy.deepcopy(state)
    planned['pending'] = pending
    planned['last_message'] = 'Race wordt gestart: ' + ('16:9 fullscreen.' if mode == 'widescreen' else 'klassiek 4:3.')
    try:
        changes = [('GAME.INI', game), ('RASER.INI', raser)]
        if display_profile is not None:
            changes.append(('dgVoodoo.conf', display_profile))
        for n, content in changes:
            atomic_write(data / n, content)
        save_state(base, planned)
    except Exception:
        for n, content in original.items():
            atomic_write(data / n, content)
        raise
    return planned


def finish_race(state: dict, data: bytes, *, token: str, exit_code: int) -> dict:
    state = copy.deepcopy(validate_state(state))
    pending = state['pending']
    if not pending or pending['token'] != token:
        raise ValueError('Resultaat hoort niet bij de gestarte race.')
    state['pending'] = None
    if exit_code != 0:
        state['last_message'] = f'Race sloot met foutcode 0x{exit_code & 0xffffffff:08X}. Je menustatus is behouden.'
        return state
    ini = read_ini(data)
    if (integer(ini, 'ETAPPE', 'etappe', 0, 6) != pending['track'] or
            integer(ini, 'PLAYER', 'car', 0, 6) != pending['car']):
        raise ValueError('Racegegevens komen niet overeen met baan en auto.')
    p = next(p for p in state['profiles'] if p['id'] == pending['profile'])
    if pending['track'] > p['next_track']:
        raise ValueError('Resultaat hoort bij een vergrendelde etappe.')
    p['money'] = integer(ini, 'PLAYER', 'money', 0, 1000000000)
    p['damage'] = integer(ini, 'PLAYER', 'damage', 0, 100)
    p['damage_mesh'] = damage_array(ini.get('PLAYER', 'DAMAGE_MESH'), mesh=True)
    p['damage_value'] = damage_array(ini.get('PLAYER', 'DAMAGE_VALUE'), mesh=False)
    finished = integer(ini, 'PLAYER', 'finished', 0, 1)
    time = integer(ini, 'PLAYER', 'tracktime', 0, 86400000)
    if finished and time > 0:
        key = str(pending['track'])
        p['records'][key] = min(p['records'].get(key, time), time)
        state['last_message'] = 'Race voltooid. Tijd, budget en schade zijn opgeslagen.'
        if pending['track'] == p['next_track']:
            p['next_track'] += 1
            if state['selected'] == p['id']:
                state['track'] = min(p['next_track'], 6)
            state['last_message'] = ('Race voltooid. Volgende etappe ontgrendeld: ' + TRACK_NAMES[p['next_track']] + '.'
                                     if p['next_track'] < 7 else 'Finale voltooid! Alle etappes zijn uitgespeeld.')
    else:
        state['last_message'] = 'Terug uit de race. Budget en schade zijn opgeslagen.'
    return validate_state(state)


def dispatch(base: Path, command: str, payload: dict) -> dict:
    state = load_state(base)
    cat = catalog(base)
    if command == 'check':
        cat['garage_stats'] = garage_stats(state, cat)
        return {'state': state, 'catalog': cat}
    if command == 'load':
        if state['pending']:
            state['pending'] = None
            state['last_message'] = 'Vorige race is onderbroken. Je kunt opnieuw starten.'
    elif command == 'start':
        state = start_race(base, state)
    elif command == 'finish':
        state = finish_race(state, read_regular(base / 'game/DATA/GAME.INI', 128 * 1024),
                            token=payload['token'], exit_code=payload['exit_code'])
    else:
        state = mutate(state, command, payload, cat)
    if command != 'start':
        save_state(base, state)
        if command == 'reset':
            # The normal previous-state copy must not retain wiped profiles.
            atomic_write(base / 'menu-state.previous.json',
                         json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8'))
    cat['garage_stats'] = garage_stats(state, cat)
    return {'state': state, 'catalog': cat}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--command', required=True)
    parser.add_argument('--payload', default='{}')
    args = parser.parse_args()
    try:
        base = args.base.absolute()
        if base.parent.name != 'ii-parallel' or base.parent.parent.name != 'local':
            raise ValueError('Menuactie buiten de eigen frontendkopie geweigerd.')
        result = dispatch(base, args.command, json.loads(args.payload))
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, configparser.Error) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
