"""Separate A2-I HD-menu profiles and the version-bound INFIO race bridge.

No original SLOT/SCORE/OPTIE files are written. See docs/a2-racer-i-hd-menu.md.
"""
from __future__ import annotations
import argparse
import configparser
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import uuid

KEYS = {'KEY_LINKS': 37, 'KEY_RECHTS': 39, 'KEY_GAS': 38,
        'KEY_REM': 40, 'KEY_ACTIE1': 32, 'KEY_ACTIE2': 13}
ART = {'main-hd-v2.png': 'a1eeffe0f4f5ec779761fd8836e3d98d484192525855a2af20d94140ec59fa7b',
       'players-hd.png': '81821214b2abc1981bf8ec66139ef99c8c60053b1646e6c9c2a78d423f4a471a'}


def safe_path(path: Path) -> None:
    for p in (path, *path.parents):
        if p.is_symlink() or p.is_junction():
            raise ValueError('Menupad bevat een link.')
        if p.exists() and p.is_file() and p.stat().st_nlink != 1:
            raise ValueError('Gedeeld bestand geweigerd.')


def read_regular(path: Path, limit: int = 65536) -> bytes:
    safe_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Menubestand ontbreekt of is te groot: ' + path.name)
    with path.open('rb') as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Menubestand is te groot.')
    return data


def atomic_write(path: Path, data: bytes) -> None:
    safe_path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def integer(value, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Menuwaarde valt buiten het toegestane bereik.')
    return value


def player_name(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 15:
        raise ValueError('Gebruik een naam van 1 tot 15 tekens.')
    if any(ord(c) < 32 or ord(c) > 255 for c in value):
        raise ValueError('Gebruik gewone letters en cijfers in je naam.')
    return value.strip()


def new_profile(name: str) -> dict:
    return {'id': uuid.uuid4().hex, 'name': player_name(name), 'stage': 0,
            'money': 1000, 'times': [], 'score_start': 0, 'ranks': [6, 1, 2, 3, 4, 5]}


def initial_state() -> dict:
    return {'schema': 2, 'profiles': [], 'selected': None, 'keys': dict(KEYS),
            'pending': None, 'message': 'Kies Nieuwe speler om te beginnen.'}


def validate_state(state: dict) -> dict:
    if not isinstance(state, dict) or set(state) != set(initial_state()) or type(state['schema']) is not int or state['schema'] not in (1, 2):
        raise ValueError('Onbekende menustatus; bestand wordt behouden.')
    if not isinstance(state['profiles'], list) or len(state['profiles']) > 10:
        raise ValueError('Onbekende spelerlijst.')
    if state['schema'] == 1:
        # Upgrade in memory; CheckOnly must never rewrite an existing save.
        state = copy.deepcopy(state)
        for p in state['profiles']:
            if not isinstance(p, dict) or set(p) != {'id', 'name', 'stage', 'money', 'times', 'ranks'}:
                raise ValueError('Onbekend spelerprofiel.')
            p['score_start'] = 0
        state['schema'] = 2
    ids = []
    for p in state['profiles']:
        if not isinstance(p, dict) or set(p) != {'id', 'name', 'stage', 'money', 'times', 'score_start', 'ranks'}:
            raise ValueError('Onbekend spelerprofiel.')
        if not isinstance(p['id'], str) or not re.fullmatch('[0-9a-f]{32}', p['id']):
            raise ValueError('Onbekende speleridentiteit.')
        ids.append(p['id'])
        player_name(p['name'])
        integer(p['stage'], 0, 6)
        integer(p['score_start'], 0, p['stage'])
        integer(p['money'], 0, 1000000000)
        if not isinstance(p['times'], list) or len(p['times']) != p['stage']:
            raise ValueError('Etappetijden passen niet bij het profiel.')
        for t in p['times']:
            integer(t, 1, 100000000)
        if not isinstance(p['ranks'], list) or sorted(p['ranks']) != [1, 2, 3, 4, 5, 6]:
            raise ValueError('Onbekende racevolgorde.')
        for rank in p['ranks']:
            integer(rank, 1, 6)
    if len(set(ids)) != len(ids) or state['selected'] not in [None, *ids]:
        raise ValueError('Spelerkeuze is ongeldig.')
    if not isinstance(state['keys'], dict) or set(state['keys']) != set(KEYS):
        raise ValueError('Onbekende racetoetsen.')
    for v in state['keys'].values():
        integer(v, 8, 254)
        if v in (27, 115):
            raise ValueError('Escape en F4 zijn gereserveerd.')
    if len(set(state['keys'].values())) != 6:
        raise ValueError('Elke raceactie heeft een eigen toets nodig.')
    pending = state['pending']
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) != {'token', 'profile', 'stage', 'input_sha256'}:
            raise ValueError('Onbekend raceverzoek.')
        if pending['profile'] not in ids or pending['profile'] != state['selected']:
            raise ValueError('Race hoort bij een andere speler.')
        if not re.fullmatch('[0-9a-f]{32}', pending['token']) or not re.fullmatch('[0-9a-f]{64}', pending['input_sha256']):
            raise ValueError('Ongeldige race-identiteit.')
        integer(pending['stage'], 0, 5)
        if profile(state)['stage'] != pending['stage']:
            raise ValueError('Race hoort bij een andere etappe.')
    if not isinstance(state['message'], str) or len(state['message']) > 1024:
        raise ValueError('Onbekende menumelding.')
    return state


def profile(state: dict) -> dict:
    for p in state['profiles']:
        if p['id'] == state['selected']:
            return p
    raise ValueError('Kies eerst een speler.')


def mutate(state: dict, command: str, payload: dict) -> dict:
    result = copy.deepcopy(validate_state(state))
    if result['pending']:
        raise ValueError('Sluit eerst de lopende race af.')
    if command == 'new':
        if len(result['profiles']) >= 10:
            raise ValueError('Er zijn al tien spelers; verwijder eerst een profiel.')
        p = new_profile(payload['name'])
        result['profiles'].append(p)
        result['selected'] = p['id']
    elif command == 'select':
        if payload['id'] not in [p['id'] for p in result['profiles']]:
            raise ValueError('Speler bestaat niet.')
        result['selected'] = payload['id']
    elif command == 'delete':
        target = payload['id']
        if target not in [p['id'] for p in result['profiles']]:
            raise ValueError('Speler bestaat niet.')
        result['profiles'] = [p for p in result['profiles'] if p['id'] != target]
        if result['selected'] == target:
            result['selected'] = result['profiles'][0]['id'] if result['profiles'] else None
    elif command == 'restart':
        p = profile(result)
        fresh = new_profile(p['name'])
        fresh['id'] = p['id']
        p.update(fresh)
    elif command == 'keys':
        result['keys'] = payload['keys']
    elif command == 'clear_scores':
        if payload.get('confirmed') is not True:
            raise ValueError('Bevestig eerst het wissen van het hele scoreboard.')
        # Campaign times still drive progression; hide only existing score entries.
        for p in result['profiles']:
            p['score_start'] = p['stage']
    else:
        raise ValueError('Onbekende menuactie.')
    result['message'] = ('Scoreboard gewist. Spelers en voortgang zijn behouden.'
                         if command == 'clear_scores' else 'Opgeslagen.')
    return validate_state(result)


def race_input(state: dict, options: dict) -> tuple[bytes, dict]:
    state = validate_state(state)
    if state['pending']:
        raise ValueError('Er staat al een race klaar.')
    p = profile(state)
    if p['stage'] >= 6:
        raise ValueError('Alle etappes zijn voltooid. Kies Opnieuw.')
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser['GAME'] = {'RACE_KLAAR': '0', 'TIJD': '0', 'ACTIVE_SLOT': '0',
                      'GELD': str(p['money']), 'ETAPPE': str(p['stage']),
                      'EINDE_DOOR': '0', 'POSITIE': '0', 'FINALE': '0'}
    for i in range(1, 6):
        parser['GAME']['RACER_' + str(i)] = str(i if p['stage'] == 0 else p['ranks'][i] - 1)
        parser['GAME']['TIJD_' + str(i)] = '0'
    parser['CONTROL'] = {'BEDIENING': '0', **{k: str(v) for k, v in state['keys'].items()}}
    expected = {'GELUID', 'RESOLUTIE', 'VIEW', 'DISPLAY_MODE', 'HORIZON',
                'DASHBORD', 'DETAIL', 'CAMERA', 'VMUZIEK', 'VEFFECT'}
    if set(options) != expected:
        raise ValueError('Onbekende raceopties.')
    parser['OPTION'] = {k: str(integer(v, 0, 4)) for k, v in options.items()}
    out = io.StringIO()
    parser.write(out, space_around_delimiters=False)
    data = out.getvalue().encode('ascii')
    pending = {'token': uuid.uuid4().hex, 'profile': p['id'], 'stage': p['stage'],
               'input_sha256': hashlib.sha256(data).hexdigest()}
    return data, pending


def finish_race(state: dict, data: bytes, token: str, exit_code: int) -> dict:
    result = copy.deepcopy(validate_state(state))
    pending = result['pending']
    if not pending or token != pending['token']:
        raise ValueError('Resultaat hoort niet bij deze race.')
    integer(exit_code, -2147483648, 4294967295)
    result['pending'] = None
    if exit_code != 0:
        result['message'] = 'Race sloot met een fout. Je profiel is behouden.'
        return result
    if len(data) > 65536:
        raise ValueError('Racegegevens zijn te groot.')
    ini = configparser.ConfigParser(interpolation=None)
    ini.read_string(data.decode('ascii'))
    def get(key, low, high):
        value = ini.get('GAME', key)
        if not re.fullmatch('-?[0-9]{1,10}', value):
            raise ValueError('Onbekend raceresultaat: ' + key)
        return integer(int(value), low, high)
    if get('ETAPPE', 0, 5) != pending['stage'] or get('ACTIVE_SLOT', 0, 9) != 0:
        raise ValueError('Race hoort bij een andere etappe of speler.')
    if not get('RACE_KLAAR', 0, 1):
        result['message'] = 'Race afgebroken. Je profiel is behouden.'
        return result
    time = get('TIJD', 1, 100000000)
    money = get('GELD', 0, 1000000000)
    ranks = [get('POSITIE', 1, 6)] + [get('RACER_' + str(i), 1, 6) for i in range(1, 6)]
    if sorted(ranks) != [1, 2, 3, 4, 5, 6]:
        raise ValueError('Raceposities zijn onvolledig; profiel blijft behouden.')
    p = profile(result)
    p['times'].append(time)
    p.update(stage=p['stage'] + 1, money=money, ranks=ranks)
    result['message'] = ('Alle zes etappes voltooid!' if p['stage'] == 6 else
                         'Etappe voltooid. Geld en reistijd zijn opgeslagen.')
    return validate_state(result)


def config(base: Path) -> dict:
    base = base.absolute()
    if base.parent.name != 'a2racer1' or base.parent.parent.name != 'experiments' or base.parent.parent.parent.name != 'local':
        raise ValueError('Menuactie buiten de eigen deel-I-kopie geweigerd.')
    value = json.loads(read_regular(base / 'Frontend.json', 2 * 1024 * 1024))
    if value['schema'] != 1 or value['game'] != 'a2racer1' or value['native_menu_used'] is not False:
        raise ValueError('Onbekend menucontract.')
    root = base.parents[3]
    scope = value.get('profile_scope', 'launcher')
    if scope not in ('launcher', 'trial'):
        raise ValueError('Onbekende profielscope.')
    expected = base / 'players.json' if scope == 'trial' else root / 'local/launcher/i-hd-menu/players.json'
    if Path(value['state_path']) != expected:
        raise ValueError('Profielpad ligt buiten de eigen HD-menugegevens.')
    safe_path(expected)
    return value


def load(base: Path, cfg: dict) -> dict:
    path = Path(cfg['state_path'])
    return validate_state(json.loads(read_regular(path))) if path.exists() else initial_state()


def save(cfg: dict, state: dict) -> None:
    validate_state(state)
    path = Path(cfg['state_path'])
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        previous = read_regular(path)
        validate_state(json.loads(previous))
        atomic_write(path.with_name('players.previous.json'), previous)
    atomic_write(path, json.dumps(state, ensure_ascii=True, indent=2).encode('ascii'))


def dispatch(base: Path, command: str, payload: dict) -> dict:
    cfg = config(base)
    state = load(base, cfg)
    if command == 'check':
        return {'state': state, 'display': cfg['display']}
    if command in ('load', 'discard'):
        if state['pending']:
            state['pending'] = None
            state['message'] = 'Vorige race onderbroken. Je profiel is behouden.'
    elif command == 'start':
        data, pending = race_input(state, cfg['options'])
        state['pending'] = pending
        path = base / 'game/INFIO.INI'
        previous = read_regular(path) if path.exists() else None
        try:
            atomic_write(path, data)
            save(cfg, state)
        except Exception:
            if previous is None:
                safe_path(path)
                if path.exists():
                    path.unlink()
            else:
                atomic_write(path, previous)
            raise
        return {'state': state, 'display': cfg['display']}
    elif command == 'finish':
        state = finish_race(state, read_regular(base / 'game/INFIO.INI'), payload['token'], payload['exit_code'])
    else:
        state = mutate(state, command, payload)
    save(cfg, state)
    return {'state': state, 'display': cfg['display']}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--command', required=True)
    p.add_argument('--payload', default='{}')
    args = p.parse_args()
    try:
        print(json.dumps(dispatch(args.base, args.command, json.loads(args.payload))))
        return 0
    except (OSError, ValueError, TypeError, KeyError, configparser.Error) as error:
        print(json.dumps({'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
