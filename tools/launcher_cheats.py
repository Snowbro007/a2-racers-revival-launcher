"""Optional frontend cheats in disposable player copies, never native patches.

Only the existing, version-bound I/II menu bridges consume these profile fields.
There are no injected keys, native helpers, executable patches or memory writes.
Prepared cheat sessions cannot merge their results into ordinary player saves.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys


DEFAULTS = {
    'a2racer1': {'enabled': False, 'extra_money': False},
    'a2racer2': {'enabled': False, 'extra_money': False,
                 'all_tracks': False, 'all_upgrades': False},
    'a2racer3': {'enabled': False},
}
START_MONEY = 1_000_000
SESSION_MARKER = 'cheat-session.json'


def validate(game: str, value: dict) -> dict:
    """Accept complete, strictly boolean preferences, including disabled ones."""
    if type(game) is not str or game not in DEFAULTS:
        raise ValueError('Onbekende game voor cheats.')
    if (type(value) is not dict or set(value) != set(DEFAULTS[game])
            or any(type(v) is not bool for v in value.values())):
        raise ValueError('Ontbrekende of ongeldige cheatkeuze.')
    if game == 'a2racer3' and value['enabled']:
        raise ValueError('Voor deel III zijn nog geen cheats ondersteund.')
    return deepcopy(value)


def active(game: str, value: dict) -> bool:
    value = validate(game, value)
    return value['enabled'] and any(flag for key, flag in value.items() if key != 'enabled')


def catalog(game: str) -> dict:
    if type(game) is not str or game not in DEFAULTS:
        raise ValueError('Onbekende game voor cheats.')
    validate(game, DEFAULTS[game])
    options = []
    if game != 'a2racer3':
        options.append({'id': 'extra_money', 'label': 'Extra startgeld',
                        'description': 'Geeft gekopieerde spelers bij deze start minstens ƒ 1.000.000.'})
    if game == 'a2racer2':
        options += [
            {'id': 'all_tracks', 'label': 'Alle etappes vrij',
             'description': 'Maakt alle zeven etappes kiesbaar in de aparte cheatsessie.'},
            {'id': 'all_upgrades', 'label': 'Alle onderdelen',
             'description': 'Monteert alle vijf garage-upgrades op de huidige auto van gekopieerde spelers.'},
        ]
    return {'available': bool(options),
            'requires_menu': {'a2racer1': 'hd-fullscreen', 'a2racer2': 'revival'}.get(game),
            'options': options, 'defaults': deepcopy(DEFAULTS[game]),
            'isolation_note': ('Cheats gebruiken een aparte spelerkopie. Geld, tijden en voortgang '
                               'uit deze sessie komen niet in je gewone profiel. Alles staat standaard uit.'),
            'runtime_tested': False,
            'reason': '' if options else 'Voor deel III zijn nog geen cheats ondersteund.'}


def prepare_state(game: str, state: dict, choices: dict) -> dict:
    """Copy validated menu state and seed only documented, existing profile fields.

    This is a start-of-session grant, not infinite money or invincibility. Buying
    another car uses normal garage rules; upgrades apply to the current car only.
    """
    choices = validate(game, choices)
    if game == 'a2racer3':
        raise ValueError('Voor deel III bestaat geen cheatprofielbrug.')
    if game == 'a2racer1':
        from tools import i_frontend_state as backend
    else:
        from tools import ii_frontend_state as backend
    result = backend.validate_state(deepcopy(state))
    if not active(game, choices):
        return result
    if result['pending'] is not None:
        raise ValueError('Sluit de vorige race eerst af voordat je cheats gebruikt.')
    if not result['profiles']:
        player = backend.new_profile('Cheatspeler')
        result['profiles'].append(player)
        result['selected'] = player['id']
    for player in result['profiles']:
        if choices['extra_money']:
            player['money'] = max(player['money'], START_MONEY)
        if game == 'a2racer2':
            if choices['all_tracks']:
                player['next_track'] = 7
            if choices['all_upgrades']:
                player['upgrades'] = {key: True for key in backend.UPGRADES}
    message_key = 'message' if game == 'a2racer1' else 'last_message'
    result[message_key] = 'Cheatsessie: aparte spelerkopie; gewone voortgang blijft behouden.'
    return backend.validate_state(result)


def session_metadata(game: str, choices: dict) -> dict:
    choices = validate(game, choices)
    if not active(game, choices):
        raise ValueError('Een cheatsessie vereist minstens één ingeschakelde cheat.')
    return {'schema': 1, 'game': game, 'options': choices,
            'progress_scope': 'session-only', 'runtime_tested': False}


def validate_session_metadata(value: dict, game: str) -> dict:
    if (type(value) is not dict or set(value) != {
            'schema', 'game', 'options', 'progress_scope', 'runtime_tested'}
            or type(value['schema']) is not int or value['schema'] != 1
            or value['game'] != game or value['progress_scope'] != 'session-only'
            or value['runtime_tested'] is not False):
        raise ValueError('Onbekende cheatsessieregistratie; normale voortgang niet geschreven.')
    if not active(game, value['options']):
        raise ValueError('Ongeldige cheatsessieregistratie; normale voortgang niet geschreven.')
    return deepcopy(value)


def main() -> int:
    parser = argparse.ArgumentParser(description='Valideer optionele cheatkeuzes zonder bestanden of games aan te raken.')
    parser.add_argument('--game', required=True, choices=tuple(DEFAULTS))
    parser.add_argument('--cheats', required=True, help='Volledig JSON-object met uitsluitend booleaanse keuzes.')
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.game, json.loads(args.cheats)), separators=(',', ':')))
        return 0
    except (ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
