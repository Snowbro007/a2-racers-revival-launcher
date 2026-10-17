"""Read-only installation discovery and verified copying of supported A2-I data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from tools.local_game_data import check_local_source, MAX_BYTES, MAX_FILES
from tools.trial_manifest import EXPECTED_BINARIES, validate_ancestors

MAX_CANDIDATES = 16
UNINSTALL_KEY = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'


def registry_locations() -> list[Path]:
    """Only matching uninstall metadata; never enumerate drives or execute commands."""
    if os.name != 'nt':
        return []
    import winreg
    result = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view) as parent:
                    count = min(winreg.QueryInfoKey(parent)[0], 4096)
                    for index in range(count):
                        try:
                            with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as item:
                                title, kind = winreg.QueryValueEx(item, 'DisplayName')
                                if kind != winreg.REG_SZ or not isinstance(title, str) or not re.fullmatch(
                                        r'A2\s*Racer(?:\s*(?:1|I))?(?:\s*\([^)]{0,60}\))?', title.strip(), re.I):
                                    continue
                                value, kind = winreg.QueryValueEx(item, 'InstallLocation')
                                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str) and len(value) <= 1024:
                                    candidate = Path(os.path.expandvars(value.strip().strip('"')))
                                    if candidate.is_absolute() and str(candidate).casefold() not in {str(p).casefold() for p in result}:
                                        result.append(candidate)
                                        if len(result) == MAX_CANDIDATES:
                                            return result
                        except OSError:
                            continue
            except OSError:
                continue
    return result


def bounded_files(source: Path, *, max_bytes: int | None = None) -> list[Path]:
    validate_ancestors(source)
    if not source.is_dir() or not source.is_absolute():
        raise ValueError('Kies een bestaande absolute game-installatiemap.')
    paths = []
    size = 0
    directories = 0
    def fail(error):
        raise error
    for parent, children, files in os.walk(source, followlinks=False, onerror=fail):
        current = Path(parent)
        directories += 1
        if directories > MAX_FILES or len(current.relative_to(source).parts) > 16:
            raise ValueError('Installatiemap is te groot of te diep; kies alleen de gamemap.')
        for name in children + files:
            validate_ancestors(current / name)
        for name in files:
            path = current / name
            if not path.is_file():
                raise ValueError('Installatie bevat geen gewoon bestand.')
            size += path.stat().st_size
            paths.append(path)
            if len(paths) > MAX_FILES or size > (MAX_BYTES if max_bytes is None else max_bytes):
                raise ValueError('Installatiemap is te groot; kies alleen de gamemap.')
    return paths


def inspect_installation(source: Path, game: str = 'a2racer1') -> dict:
    if game == 'a2racer2':
        from tools.ii_portable_prepare import inspect_source
        return inspect_source(source)
    if game != 'a2racer1':
        raise ValueError('Onbekende game voor installatiekoppeling.')
    paths = bounded_files(source)
    for name, pin in EXPECTED_BINARIES['a2racer1'].items():
        path = source / name
        if not path.is_file() or path.stat().st_size > 2 * 1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != pin:
            raise ValueError('Deze gameversie is niet ondersteund of onvolledig: ' + name)
    return {**check_local_source(source, full=True), 'files': len(paths)}


def copy_file(source: Path, target: Path) -> None:
    """A changing input cannot grow the output past its previously checked size."""
    remaining = source.stat().st_size
    if remaining > MAX_BYTES:
        raise ValueError('Bronbestand is te groot.')
    validate_ancestors(source)
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        while remaining:
            block = incoming.read(min(remaining, 1024**2))
            if not block:
                raise ValueError('Installatie veranderde tijdens koppelen.')
            outgoing.write(block)
            remaining -= len(block)
        if incoming.read(1):
            raise ValueError('Installatie veranderde tijdens koppelen.')


def promote_import(stage: Path, destination: Path, receipt: Path, data: dict) -> None:
    """Finish metadata before publishing game data; roll back only our own record.

    A record and game directory are separate filesystem entries. This handles
    ordinary write/promotion failures without deleting game files; it is not a
    claim of a single crash-durable transaction across both locations.
    """
    for path in (stage, destination, receipt):
        validate_ancestors(path)
    if destination.exists() or receipt.exists():
        raise ValueError('Gamegegevens of koppelingsrecord bestaan al; overschrijven geweigerd.')
    owned_record = None
    promoted = False
    try:
        # Exclusive creation preserves any competing or pre-existing record.
        # A disk-full/permission error happens while only our staging is live.
        with receipt.open('x', encoding='utf-8') as handle:
            metadata = os.fstat(handle.fileno())
            owned_record = (metadata.st_dev, metadata.st_ino)
            json.dump(data, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        validate_ancestors(destination)
        if destination.exists():
            raise ValueError('Gamegegevens zijn intussen toegevoegd; import gestopt.')
        stage.rename(destination)
        promoted = True
    finally:
        if owned_record is not None and not promoted:
            validate_ancestors(receipt)
            try:
                metadata = receipt.stat()
            except FileNotFoundError:
                pass
            else:
                if ((metadata.st_dev, metadata.st_ino) != owned_record
                        or not receipt.is_file() or metadata.st_nlink != 1):
                    raise ValueError('Koppelingsrecord is intussen veranderd; opruimen geweigerd.')
                receipt.unlink()


def discover(root: Path, *, candidates: list[Path] | None = None) -> dict:
    """Candidates are Windows registrations, or explicit paths in synthetic tests."""
    locations = registry_locations() if candidates is None else candidates
    found = []
    seen = set()
    for location in locations[:MAX_CANDIDATES]:
        source = Path(os.path.abspath(location))
        key = str(source).casefold()
        if key in seen or source == root / 'local/games/a2racer1':
            continue
        seen.add(key)
        item = {'path': str(source), 'supported': False, 'reason': ''}
        try:
            inspect_installation(source)
            item.update(supported=True, reason='Ondersteunde volledige Nederlandse deel-I-versie.')
        except (OSError, ValueError) as exc:
            item['reason'] = str(exc) + ' Kies anders je volledige gamearchief.'
        found.append(item)
    return {'game': 'a2racer1', 'installations': found,
            'searched': 'Alleen geregistreerde A2 Racer I-installaties; geen schijfscan.',
            'download_url': None}


def import_installation(root: Path, source: Path, game: str = 'a2racer1') -> dict:
    if game not in ('a2racer1','a2racer2'):
        raise ValueError('Deze game kan nog niet worden gekoppeld.')
    root = root.resolve()
    source = Path(os.path.abspath(source))
    parent = root / 'local/games'
    destination = parent / game
    validate_ancestors(parent)
    validate_ancestors(destination)
    if destination.exists():
        raise ValueError('Er zijn al gekoppelde gamebestanden; deze worden niet overschreven.')
    if source == parent or source.is_relative_to(parent) or parent.is_relative_to(source):
        raise ValueError('Bron en lokale speelopslag mogen elkaar niet overlappen.')
    receipt = root / ('local/launcher/installation.json' if game == 'a2racer1' else 'local/launcher/installation-a2racer2.json')
    validate_ancestors(receipt)
    if receipt.exists():
        raise ValueError('Een bestaande installatiekoppeling wordt niet overschreven.')
    inspected = inspect_installation(source, game) if game != 'a2racer1' else inspect_installation(source)
    parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    stage = parent / ('.'+game+'-import-' + uuid.uuid4().hex)
    stage.mkdir()
    try:
        if game == 'a2racer2':
            from tools.ii_portable_prepare import filesystem_path
        else:
            filesystem_path = lambda path: path
        for path in bounded_files(source, max_bytes=1024**3) if game == 'a2racer2' else bounded_files(source):
            target = filesystem_path(stage / path.relative_to(source))
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_file(filesystem_path(path), target)
        copied = inspect_installation(stage, game) if game != 'a2racer1' else inspect_installation(stage)
        after = inspect_installation(source, game) if game != 'a2racer1' else inspect_installation(source)
        if copied['source_tree_sha256'] != inspected['source_tree_sha256'] or after['source_tree_sha256'] != inspected['source_tree_sha256']:
            raise ValueError('Gamebestanden veranderden tijdens koppelen.')
        if destination.exists():
            raise ValueError('Lokale gamebestanden zijn intussen toegevoegd; import gestopt.')
        data = {'schema': 1, 'game': game, 'source_path': str(source),
                'source_tree_sha256': inspected['source_tree_sha256'], 'source_unchanged': True}
        promote_import(stage, destination, receipt, data)
        return {**data, 'game_imported': True, 'game_started': False, 'disc_image_required': False}
    finally:
        # Only this uniquely named staging directory inside our own game cache.
        if stage.exists():
            if stage.resolve().parent != parent.resolve() or not stage.name.startswith('.'+game+'-import-'):
                raise ValueError('Onverwacht stagingpad; opruimen geweigerd.')
            validate_ancestors(stage)
            shutil.rmtree(filesystem_path(stage))
