"""Explain fixed game-input folders without scanning or moving game data.

The input library is optional. Only the explicit folder action creates it;
snapshot inspection never imports, downloads, launches or changes a game.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from tools.trial_manifest import validate_ancestors


GAME_LABELS = {'a2racer1': 'A2 Racer I', 'a2racer2': 'A2 Racer II'}
MAX_RECEIPT_BYTES = 16 * 1024

LIBRARY_HELP = """EIGEN GAMEBESTANDEN

Deze launcher bevat geen games en downloadt ze niet automatisch.

A2 Racer I/   - je eigen ondersteunde Nederlandse deel-I-archief of gamemap
A2 Racer II/  - je eigen ondersteunde Nederlandse deel-II-archief of gamemap

1. Je mag je eigen game hier bewaren. Staat die al ergens anders, laat hem
   daar gerust staan: verplaatsen of opnieuw kopieren is niet nodig.
2. Open de launcher en kies A2 Racer I of A2 Racer II.
3. Kies 'Ik heb een gamemap' voor een complete installatie, of
   'Ik heb een ZIP-bestand'
   voor het ondersteunde originele Nederlandse gamearchief.

Bestanden alleen in deze map zetten voegt de game nog niet toe. Gebruik de
keuzeknop in de launcher; er wordt niet automatisch naar games gezocht.
Een minimale cd-installatie kan bestanden missen. Bij deel II hoort de
volledige DATA-map bij de game.

De launcher controleert je gekozen bron en maakt een eigen kopie onder
local/games. Je oorspronkelijke map of ZIP blijft behouden. De launcher
beheert zijn speelkopie, instellingen en logs zelf; plaats eigen gamebestanden
niet tussen tools, payload of local/portable-runtime.
Bewaar bij een portable update zowel Gamebestanden/ als local/; verwijder je
eigen bronnen of opgeslagen voortgang niet bij het vervangen van de launcher.
"""


def _root(root: Path) -> Path:
    root = Path(os.path.abspath(root))
    validate_ancestors(root)
    if not root.is_dir():
        raise ValueError('De uitgepakte launchermap ontbreekt.')
    return root


def _game(game: str) -> str:
    if game not in GAME_LABELS:
        raise ValueError('Kies A2 Racer I of A2 Racer II voor de gamebestandenmap.')
    return GAME_LABELS[game]


def _metadata(path: Path) -> dict | None:
    """Read a bounded local receipt only; its path strings stay display data."""
    validate_ancestors(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_RECEIPT_BYTES:
        raise ValueError('Het lokale bronrecord kan niet veilig worden weergegeven.')
    with path.open('rb') as handle:
        raw = handle.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('Het lokale bronrecord is te groot.')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Het lokale bronrecord is ongeldig.')
    return value


def _display_path(value) -> str | None:
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(ord(char) < 32 for char in value) or not Path(value).is_absolute()):
        return None
    return value


def _source(root: Path, game: str, imported: bool) -> tuple[str | None, str]:
    if not imported:
        return None, 'none'
    receipt_name = 'installation.json' if game == 'a2racer1' else 'installation-a2racer2.json'
    receipt = _metadata(root / 'local/launcher' / receipt_name)
    if receipt and type(receipt.get('schema')) is int and receipt['schema'] == 1 and receipt.get('game') == game:
        path = _display_path(receipt.get('source_path'))
        if path:
            return path, 'installation'
    extracted = _metadata(root / 'local/media' / game / 'extraction.json')
    if extracted and extracted.get('game') == game:
        path = _display_path(extracted.get('archive'))
        if path:
            return path, 'archive'
    return None, 'managed'


def describe_library(root: Path) -> dict:
    """Return explanations and fixed paths, without creating or searching folders."""
    root = _root(root)
    library = root / 'Gamebestanden'
    entries = {}
    for game, label in GAME_LABELS.items():
        input_path = library / label
        managed = root / 'local/games' / game
        entry = {'label': label, 'input_path': str(input_path), 'managed_path': str(managed),
                 'source_path': None, 'source_kind': 'none', 'imported': False,
                 'folder_available': True, 'note': 'Nog geen game toegevoegd. Kies je eigen gamemap of ZIP.'}
        try:
            for path in (managed, input_path):
                validate_ancestors(path)
                if path.exists() and not path.is_dir():
                    raise ValueError('Een vaste gamebestandenmap is geen gewone map.')
                if path == managed:
                    entry['imported'] = managed.is_dir()
            entry['source_path'], entry['source_kind'] = _source(root, game, entry['imported'])
            if entry['imported']:
                entry['note'] = 'Een beheerde gameopslagmap is aanwezig. De launcher controleert apart of de game compleet is.'
        except (OSError, ValueError, UnicodeError) as exc:
            # A broken optional inbox/receipt must not hide already configured games.
            entry['folder_available'] = False
            entry['note'] = 'Mapinformatie niet beschikbaar: ' + str(exc)
        entries[game] = entry
    return {'schema': 1, 'root_path': str(library), 'games': entries,
            'note': 'Games worden niet meegeleverd. Je eigen bestanden mogen hier of op hun huidige plek blijven staan.'}


def ensure_game_folder(root: Path, game: str) -> dict:
    """Create just the fixed explanatory folders, only after an explicit UI action."""
    label = _game(game)
    root = _root(root)
    library = root / 'Gamebestanden'
    folders = [library, *(library / name for name in GAME_LABELS.values())]
    help_files = [folder / 'LEESMIJ.txt' for folder in folders]
    # Check every destination before writing; never use receipt data as a target.
    for folder in folders:
        validate_ancestors(folder)
        if folder.exists() and not folder.is_dir():
            raise ValueError('De gamebestandenmap wordt geblokkeerd door een bestaand bestand.')
    for path in help_files:
        validate_ancestors(path)
        if path.exists() and not path.is_file():
            raise ValueError('Een bestaand LEESMIJ-bestand wordt niet vervangen.')
    created = []
    for folder in folders:
        validate_ancestors(folder)
        folder.mkdir(exist_ok=True)
    for path in help_files:
        validate_ancestors(path)
        try:
            with path.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(LIBRARY_HELP)
            created.append(str(path))
        except FileExistsError:
            # User-authored instructions or other files remain untouched.
            pass
    return {'schema': 1, 'game': game, 'path': str(library / label),
            'root_path': str(library), 'created_help_files': created,
            'game_imported': False, 'game_started': False}
