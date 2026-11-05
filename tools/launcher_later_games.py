"""Small CLI bridge for owned IV/Vakantieracer files and the fixed menu host.

Catalog and launch planning never prepare or start a game. The Windows UI owns
the selected session token; stopping publishes a complete command and leaves
the native supervisor alive to perform cleanup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import later_game_control as control
from tools import later_game_installation as installation
from tools.trial_manifest import validate_ancestors

GAMES = {'a2racer4': 'De Politie Slaat Terug', 'vakantieracer': 'Vakantieracer'}
PROFILES = ('compat', 'hd1080')
START_SCRIPT = 'tools/Start-LaterGame.ps1'
STOP_BYTES = b'stop\n'


def _runtime():
    from tools import later_games_runtime
    return later_games_runtime


def _selection(game, profile='hd1080'):
    if type(game) is not str or game not in GAMES:
        raise ValueError('Kies Vakantieracer of De Politie Slaat Terug.')
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError('Onbekende beeldoptie voor deze game.')


def _root(root):
    value = Path(os.path.abspath(root))
    validate_ancestors(value)
    return value


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_nlink


def _regular(path):
    validate_ancestors(path)
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError('Start- of stopbestand bevat een link of is geen gewoon bestand.')
    return value


def _read_small(path, maximum):
    before = _regular(path)
    if before.st_size > maximum: raise ValueError('Start- of stopbestand is te groot.')
    with path.open('rb') as handle:
        if _identity(os.fstat(handle.fileno())) != _identity(before):
            raise ValueError('Start- of stopbestand veranderde tijdens openen.')
        raw = handle.read(maximum + 1)
        if _identity(os.fstat(handle.fileno())) != _identity(before):
            raise ValueError('Start- of stopbestand veranderde tijdens lezen.')
    if len(raw) != before.st_size or _identity(_regular(path)) != _identity(before):
        raise ValueError('Start- of stopbestand veranderde tijdens lezen.')
    return raw, before


def catalog(root):
    root = _root(root)
    games = []
    for game, title in GAMES.items():
        value = installation.status(root, game)
        games.append({'id': game, 'title': title, 'ready': value['ready'],
                      'source_ready': value['ready'], 'reason': value['reason'],
                      'default_profile': 'hd1080'})
    return {'schema': 1, 'kind': 'later-game-catalog', 'games': games,
            'profiles': [
                {'id': 'hd1080', 'label': 'HD 1080p · aanbevolen', 'confirmed_by_user': True,
                 'description': 'Bevestigde HD-basis met de oorspronkelijke 4:3-verhouding; intern 1440 × 1080, schermvullend weergegeven.'},
                {'id': 'compat', 'label': 'Origineel 640 × 480', 'confirmed_by_user': True,
                 'description': 'Bevestigde lage-resolutiebasis als terugvaloptie.'}],
            'defaults': {game: 'hd1080' for game in GAMES},
            'game_started': False}


def _import_summary(value):
    return {'schema': 1, 'kind': 'later-game-import-result', 'game': value['game'],
            'ready': value['ready'], 'source_ready': value['ready'],
            'source_path': value['source_path'], 'files': len(value['files']),
            'game_imported': value['game_imported'], 'game_started': False,
            'message': 'Eigen gamebestanden toegevoegd. Kies je beeldoptie en start de game.'}


def import_installation(root, folder, game):
    _selection(game)
    if folder is None: raise ValueError('Kies je volledige eigen gamemap.')
    return _import_summary(installation.import_installation(_root(root), Path(folder), game))


def import_game(root, archive, game):
    _selection(game)
    if archive is None: raise ValueError('Kies je volledige eigen installatie-ZIP.')
    return _import_summary(installation.import_archive(_root(root), Path(archive), game))


def _game_path(root, game, profile):
    return root / _runtime().game_base(game, profile) / 'game'


def prepare(root, game, profile='hd1080', token=None):
    _selection(game, profile); control.validate_token(token); root = _root(root)
    value = _runtime().run(root, game, profile=profile, check_only=True, control_token=token)
    if value.get('ready') is not True or value.get('game_started') is not False:
        raise ValueError('De bestandscontrole gaf geen geldige voorbereiding terug.')
    return {'schema': 1, 'kind': 'later-game-preparation-result', 'game': game,
            'profile': profile, 'ready': True, 'game_started': False,
            'game_path': str(_game_path(root, game, profile)),
            'message': 'Gamebestanden gecontroleerd en eigen speelkopie klaargezet.'}


def plan(root, game, profile='hd1080', token=None):
    """Only identify our one fixed host; never execute or prepare its payload."""
    _selection(game, profile); control.validate_token(token); root = _root(root)
    value = installation.status(root, game)
    if not value['ready']: raise ValueError(value['reason'])
    token = uuid.uuid4().hex if token is None else token
    request = control.stop_path(root, token)
    if request.exists(): raise ValueError('Deze sessietoken is al gebruikt; begin een nieuwe spelsessie.')
    script = root / START_SCRIPT
    raw, _ = _read_small(script, 64 * 1024)
    return {'schema': 1, 'kind': 'later-game-launch-plan', 'game': game,
            'profile': profile, 'control_token': token,
            'start_script': str(script), 'start_script_sha256': hashlib.sha256(raw).hexdigest(),
            'arguments': ['-Game', game, '-Profile', profile, '-ControlToken', token],
            'game_path': str(_game_path(root, game, profile)),
            'original_menu_required': True, 'game_started': False}


def _cleanup_temporary(path, owned):
    if owned is None: return
    try: current = _regular(path)
    except FileNotFoundError: return
    if (current.st_dev, current.st_ino) != owned:
        raise ValueError('Tijdelijk stopbestand is vervangen; opruimen geweigerd.')
    path.unlink()


def stop(root, token):
    """Windows atomic no-replace publication; never kill a supervising process."""
    control.validate_token(token)
    if token is None: raise ValueError('Een stopverzoek vereist de actieve sessietoken.')
    root = _root(root); destination = control.stop_path(root, token)
    if control.stop_requested(root, token):
        return {'kind': 'later-game-stop-request', 'control_token': token,
                'stop_requested': True, 'game_started': False}
    # os.rename is atomic and refuses an existing destination on Windows. The
    # POSIX overwrite semantics do not provide this contract; do not substitute
    # a hardlink because the strict reader could observe two links transiently.
    if os.name != 'nt': raise OSError('Stopopdrachten publiceren wordt alleen op Windows ondersteund.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    validate_ancestors(destination)
    temporary = destination.parent / (token + '.' + uuid.uuid4().hex + '.tmp')
    validate_ancestors(temporary); owned = None
    try:
        with temporary.open('xb') as handle:
            value = os.fstat(handle.fileno()); owned = value.st_dev, value.st_ino
            if value.st_nlink != 1: raise ValueError('Tijdelijk stopbestand heeft een hardlink.')
            handle.write(STOP_BYTES); handle.flush(); os.fsync(handle.fileno())
        raw, value = _read_small(temporary, 5)
        if raw != STOP_BYTES or (value.st_dev, value.st_ino) != owned:
            raise ValueError('Tijdelijk stopbestand veranderde vóór publiceren.')
        validate_ancestors(destination)
        try: temporary.rename(destination)
        except OSError:
            # A second publisher may have won the no-replace rename. Only an
            # unchanged, ordinary, exact command is an idempotent success.
            if not control.stop_requested(root, token): raise
        if not control.stop_requested(root, token): raise ValueError('Stopopdracht werd niet gepubliceerd.')
    finally:
        _cleanup_temporary(temporary, owned)
    return {'kind': 'later-game-stop-request', 'control_token': token,
            'stop_requested': True, 'game_started': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('catalog', 'import-installation', 'import-game', 'prepare', 'plan', 'stop'))
    parser.add_argument('--game', choices=tuple(GAMES))
    parser.add_argument('--profile', choices=PROFILES, default='hd1080')
    parser.add_argument('--folder'); parser.add_argument('--archive'); parser.add_argument('--token')
    args = parser.parse_args(argv)
    try:
        if args.action == 'catalog': value = catalog(ROOT)
        elif args.action == 'import-installation': value = import_installation(ROOT, args.folder, args.game)
        elif args.action == 'import-game': value = import_game(ROOT, args.archive, args.game)
        elif args.action == 'prepare': value = prepare(ROOT, args.game, args.profile, args.token)
        elif args.action == 'plan': value = plan(ROOT, args.game, args.profile, args.token)
        else: value = stop(ROOT, args.token)
        print(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        print('Latere game: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
