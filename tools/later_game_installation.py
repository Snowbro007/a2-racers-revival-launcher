"""Import the player's exact supported NL IV/VR files; never run or download.

Both original DATA/MENUDATA and flattened installed layouts map to a private,
unchanged original tree. Only the published filename/size/hash inventory enters
the launcher package. Source paths, disc archives and game bytes do not.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import uuid
import zipfile

from tools.game_installation import promote_import
from tools.trial_manifest import validate_ancestors

ROOT = Path(__file__).resolve().parents[1]
METADATA = 'assets/later-game-sources.json'
METADATA_SHA256 = '6a304ebd8279a7fcbb4bbb5553393370f5c269a36c205f46e7fb5232be0abba5'
PARENTS = {'a2racer4': 'A2RACER4.EXE', 'vakantieracer': 'VRACER.EXE'}
MAX_FILES = 4096
MAX_BYTES = 1024 ** 3
MAX_FILE_BYTES = 512 * 1024 ** 2
MAX_RECORD_BYTES = 256 * 1024
EXECUTABLE_SUFFIXES = {'.exe', '.dll', '.ocx', '.sys', '.com', '.bat', '.cmd',
                       '.ps1', '.py', '.pyd', '.vbs', '.js', '.scr', '.msi', '.msp', '.cpl', '.drv'}


def _game(game):
    if type(game) is not str or game not in PARENTS:
        raise ValueError('Onbekende game voor eigen gamebestanden.')


def _parts(name):
    if type(name) is not str or not name or len(name) > 512 or '\\' in name:
        raise ValueError('Ongeldig gamebestandspad.')
    parts = name.split('/')
    if len(parts) > 16:
        raise ValueError('Gamebestandspad is te diep.')
    for part in parts:
        if (not part or part in ('.', '..') or part[-1] in ' .'
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise ValueError('Ongeldig of gereserveerd gamebestandspad.')
    return tuple(parts)


def _plain(path, *, directory=False):
    validate_ancestors(path)
    value = path.lstat()
    if directory:
        if not stat.S_ISDIR(value.st_mode):
            raise ValueError('Kies een gewone game-installatiemap.')
    elif not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError('Gamebestand is geen gewoon bestand of heeft een hardlink.')
    return value


def _identity(value):
    # On Windows, path stat and descriptor fstat can expose different legacy
    # ctime meanings. Compare stable identity/size/mtime/link fields instead;
    # every imported content stream must independently match its full hash.
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_nlink)


def _stream_file(path, *, expected=None, target=None, limit=MAX_FILE_BYTES):
    before = _plain(path)
    if before.st_size > limit or (expected is not None and before.st_size != expected['size']):
        raise ValueError('Gamebestand heeft een andere grootte: ' + path.name)
    digest = hashlib.sha256(); count = 0
    with path.open('rb') as incoming:
        if _identity(os.fstat(incoming.fileno())) != _identity(before):
            raise ValueError('Bronbestand veranderde tijdens openen.')
        outgoing = target.open('xb') if target is not None else None
        try:
            while block := incoming.read(min(1024 ** 2, limit + 1 - count)):
                count += len(block)
                if count > limit or count > before.st_size:
                    raise ValueError('Bronbestand groeide tijdens lezen.')
                digest.update(block)
                if outgoing is not None: outgoing.write(block)
        finally:
            if outgoing is not None: outgoing.close()
        if _identity(os.fstat(incoming.fileno())) != _identity(before):
            raise ValueError('Bronbestand veranderde tijdens lezen.')
    if _identity(_plain(path)) != _identity(before) or count != before.st_size:
        raise ValueError('Bronbestand veranderde tijdens lezen.')
    value = digest.hexdigest()
    if expected is not None and value != expected['sha256']:
        raise ValueError('Andere of gewijzigde Nederlandse gameversie: ' + expected['path'])
    return value


def _json(path, limit=MAX_RECORD_BYTES):
    before = _plain(path)
    if before.st_size > limit: raise ValueError('Gamebestandregistratie is te groot.')
    with path.open('rb') as handle: raw = handle.read(limit + 1)
    if len(raw) != before.st_size or _identity(_plain(path)) != _identity(before):
        raise ValueError('Gamebestandregistratie veranderde tijdens lezen.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Dubbele sleutel in gamebestandregistratie.')
            result[key] = value
        return result
    return raw, json.loads(raw.decode('utf-8'), object_pairs_hook=unique)


def _profile(game):
    _game(game)
    raw, data = _json(ROOT / METADATA)
    if hashlib.sha256(raw).hexdigest() != METADATA_SHA256 or data.get('schema') != 1:
        raise ValueError('De ondersteunde gamebestandenlijst is gewijzigd.')
    value = data['games'][game]
    if value.get('parent') != PARENTS[game]: raise ValueError('Onjuiste oorspronkelijke gameparent.')
    rows = value['files']; seen = set(); total = 0
    if type(rows) is not list or not 1 <= len(rows) <= MAX_FILES:
        raise ValueError('Ongeldige gamebestandenlijst.')
    for row in rows:
        _parts(row['path']); key = row['path'].casefold()
        if key in seen or type(row['size']) is not int or not 0 <= row['size'] <= MAX_FILE_BYTES:
            raise ValueError('Dubbel bestand of ongeldige gamebestandsgrootte.')
        if type(row['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', row['sha256']):
            raise ValueError('Ongeldige gamebestandhash.')
        seen.add(key); total += row['size']
    if total > MAX_BYTES: raise ValueError('Gamebestandenlijst is te groot.')
    _no_file_parents(seen)
    for name, pin in value['core_pins'].items():
        if not any(r['path'] == name and r['sha256'] == pin for r in rows):
            raise ValueError('Kernbinary ontbreekt in de ondersteunde gamebestandenlijst.')
    return value


def _no_file_parents(names):
    for name in names:
        parts = name.split('/')
        if any('/'.join(parts[:i]) in names for i in range(1, len(parts))):
            raise ValueError('Een gamebestand blokkeert een map.')


def _inventory(source):
    _plain(source, directory=True)
    result = {}; names = set(); directories = 0; total = 0
    def fail(error): raise error
    for parent, children, files in os.walk(source, followlinks=False, onerror=fail):
        parent = Path(parent); directories += 1
        if directories > MAX_FILES or len(parent.relative_to(source).parts) > 16:
            raise ValueError('Gamemap is te groot of te diep.')
        for name in children + files:
            path = parent / name; relative = path.relative_to(source).as_posix()
            _parts(relative); key = relative.casefold()
            if key in names: raise ValueError('Gamemap bevat dubbele namen met verschillend hoofdlettergebruik.')
            names.add(key)
            value = _plain(path, directory=name in children)
            if name in files:
                total += value.st_size
                if value.st_size > MAX_FILE_BYTES or total > MAX_BYTES or len(result) >= MAX_FILES:
                    raise ValueError('Kies alleen de volledige gamemap, maximaal 1 GiB.')
                result[relative] = (path, _identity(value))
    return result


def _layout(entries, profile, *, wrapper=False):
    expected = {row['path'].casefold(): row for row in profile['files']}
    choices = [()]
    if wrapper:
        choices += [(name,) for name in sorted({p.split('/')[0] for p in entries if '/' in p})]
    matches = []
    for prefix in choices:
        subset = [(tuple(name.split('/'))[len(prefix):], value) for name, value in entries.items()
                  if tuple(name.split('/'))[:len(prefix)] == prefix and len(name.split('/')) > len(prefix)]
        disc = any(parts[0].casefold() == 'data' for parts, _ in subset)
        mapped = {}; extra_executables = []
        for parts, value in subset:
            if disc:
                if parts[0].casefold() != 'data': continue
                parts = parts[1:]
            if parts and parts[0].casefold() == 'menudata': parts = parts[1:]
            if not parts: continue
            key = '/'.join(parts).casefold()
            if key in mapped: raise ValueError('Twee bronbestanden krijgen hetzelfde vlakke gamepad.')
            mapped[key] = value
            if key not in expected and Path(parts[-1]).suffix.casefold() in EXECUTABLE_SUFFIXES:
                extra_executables.append('/'.join(parts))
        if expected.keys() <= mapped.keys():
            if extra_executables:
                raise ValueError('Onbekende uitvoerbare code in de gamedata: ' + extra_executables[0])
            matches.append({row['path']: mapped[key] for key, row in expected.items()})
    if len(matches) != 1:
        raise ValueError('Kies de volledige ondersteunde Nederlandse gamemap/ZIP met DATA en MENUDATA, of de volledige geïnstalleerde bestanden; geen ISO/BIN of losse installer.')
    return matches[0]


def _paths(root, game):
    _game(game); root = Path(os.path.abspath(root)); validate_ancestors(root)
    destination = root / 'local/games' / game / 'original'
    receipt = root / 'local/launcher' / ('installation-' + game + '.json')
    for path in (destination, receipt): validate_ancestors(path)
    return root, destination, receipt


def _record(game, profile):
    rows = profile['files']
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'schema': 1, 'kind': 'later-owned-game-installation', 'game': game,
            'version': profile['version'], 'parent': profile['parent'],
            'source_path': 'local/games/' + game + '/original',
            'files': rows, 'source_tree_sha256': digest}


def _verify_flat(source, profile, full):
    entries = _inventory(source)
    actual = {name.casefold(): value for name, value in entries.items()}
    if set(actual) != {row['path'].casefold() for row in profile['files']}:
        raise ValueError('De beheerde oorspronkelijke gamebestanden zijn niet compleet of bevatten extra bestanden.')
    for row in profile['files']:
        path, signature = actual[row['path'].casefold()]
        if signature[2] != row['size']:
            raise ValueError('De beheerde oorspronkelijke gamebestandsgrootte wijkt af: ' + row['path'])
        if full: _stream_file(path, expected=row)


def check(root, game, full=True):
    """Verify the receipt and immutable managed tree; return flat original records."""
    if type(full) is not bool: raise ValueError('Bestandscontrole vereist een boolean.')
    _, source, receipt = _paths(root, game); profile = _profile(game)
    _, value = _json(receipt)
    if value != _record(game, profile): raise ValueError('De gamebestandregistratie wijkt af; importeer opnieuw in een lege launcher.')
    _verify_flat(source, profile, full)
    return {**value, 'source_path': str(source), 'ready': True, 'source_ready': True,
            'validation': 'complete-original-files' if full else 'receipt-and-file-metadata',
            'metadata': {'version': profile['version'], 'files': len(profile['files'])},
            'game_started': False, 'disc_image_required': False}


def status(root, game):
    """Fast startup availability: small records and file stats, no content hashes."""
    _game(game)
    try:
        return {**check(root, game, full=False), 'reason': 'Eigen Nederlandse gamebestanden zijn toegevoegd.'}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {'game': game, 'ready': False, 'source_ready': False, 'reason': str(error),
                'game_started': False, 'disc_image_required': False}


def _stage(root, game):
    root, destination, receipt = _paths(root, game)
    if destination.exists() or receipt.exists():
        raise ValueError('Er zijn al gekoppelde gamebestanden; overschrijven geweigerd.')
    destination.parent.mkdir(parents=True, exist_ok=True); receipt.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / ('.original-import-' + uuid.uuid4().hex)
    validate_ancestors(stage); stage.mkdir()
    return stage, destination, receipt


def _cleanup(stage, destination):
    if stage.exists():
        validate_ancestors(stage)
        if (stage.absolute().parent != destination.absolute().parent or
                not re.fullmatch(r'\.original-import-[a-f0-9]{32}', stage.name)):
            raise ValueError('Onverwacht stagingpad; opruimen geweigerd.')
        _inventory(stage)  # Never recursively remove a substituted linked tree.
        shutil.rmtree(stage)


def _finish(root, game, profile, stage, destination, receipt):
    _verify_flat(stage, profile, True)
    promote_import(stage, destination, receipt, _record(game, profile),
                   verify_stage=lambda: _verify_flat(stage, profile, True))
    return {**check(root, game), 'game_imported': True, 'source_unchanged': True}


def import_installation(root, source, game):
    _game(game); root, _, _ = _paths(root, game)
    source = Path(os.path.abspath(source)); validate_ancestors(source)
    storage = root / 'local/games'
    if source == storage or source.is_relative_to(storage) or storage.is_relative_to(source):
        raise ValueError('Bronmap en beheerde gameopslag mogen elkaar niet overlappen.')
    profile = _profile(game); before = _inventory(source); mapped = _layout(before, profile)
    for row in profile['files']: _stream_file(mapped[row['path']][0], expected=row)
    stage, destination, receipt = _stage(root, game)
    try:
        for row in profile['files']:
            target = stage.joinpath(*_parts(row['path'])); target.parent.mkdir(parents=True, exist_ok=True)
            _stream_file(mapped[row['path']][0], expected=row, target=target)
        if _inventory(source) != before: raise ValueError('Bronmap veranderde tijdens importeren.')
        for row in profile['files']: _stream_file(mapped[row['path']][0], expected=row)
        return _finish(root, game, profile, stage, destination, receipt)
    finally: _cleanup(stage, destination)


def _zip_entries(source):
    entries = {}; names = set(); files = set(); spellings = {}; total = 0
    values = source.infolist()
    if len(values) > MAX_FILES * 2: raise ValueError('ZIP bevat te veel onderdelen.')
    for item in values:
        if item.orig_filename != item.filename:
            raise ValueError('ZIP bevat een afgekapt of anders genormaliseerd bestandspad.')
        name = item.filename[:-1] if item.is_dir() else item.filename
        _parts(name); key = name.casefold()
        if key in names: raise ValueError('ZIP bevat dubbele of hoofdletter-botsende paden.')
        names.add(key)
        parts = name.split('/')
        for index in range(1, len(parts) + 1):
            spelling = '/'.join(parts[:index]); folded = spelling.casefold()
            if folded in spellings and spellings[folded] != spelling:
                raise ValueError('ZIP bevat botsend hoofdlettergebruik in een mapnaam.')
            spellings[folded] = spelling
        mode = item.external_attr >> 16
        if (item.flag_bits & 1 or item.external_attr & 0x400 or
                stat.S_IFMT(mode) not in (0, stat.S_IFDIR if item.is_dir() else stat.S_IFREG)):
            raise ValueError('ZIP bevat versleutelde, gekoppelde of bijzondere bestanden.')
        extra = item.extra
        while extra:
            if len(extra) < 4: raise ValueError('Ongeldig ZIP-extra-veld.')
            tag, size = struct.unpack('<HH', extra[:4])
            if len(extra) < 4 + size or tag in (0x000d, 0x756e):
                raise ValueError('ZIP-linkmetadata of beschadigd extra-veld geweigerd.')
            extra = extra[4 + size:]
        if item.is_dir(): continue
        if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError('ZIP-compressie wordt niet ondersteund; gebruik een gewone ZIP.')
        total += item.file_size; files.add(key)
        if (item.file_size > MAX_FILE_BYTES or total > MAX_BYTES or len(entries) >= MAX_FILES):
            raise ValueError('Uitgepakte ZIP overschrijdt de gamebestandlimiet van 1 GiB.')
        entries[name] = item
    _no_file_parents(files)
    for name in names:
        if any('/'.join(name.split('/')[:i]) in files for i in range(1, len(name.split('/')))):
            raise ValueError('ZIP-bestand blokkeert een map.')
    return entries


def import_archive(root, archive, game):
    """Read a bounded complete-installation ZIP directly into our staging tree."""
    _game(game); profile = _profile(game); archive = Path(os.path.abspath(archive))
    before = _plain(archive)
    if not 0 < before.st_size <= MAX_BYTES: raise ValueError('Kies een volledige game-installatie-ZIP van maximaal 1 GiB.')
    stage = destination = None
    try:
        with archive.open('rb') as handle:
            if _identity(os.fstat(handle.fileno())) != _identity(before): raise ValueError('ZIP veranderde tijdens openen.')
            with zipfile.ZipFile(handle) as source:
                mapped = _layout(_zip_entries(source), profile, wrapper=True)
                stage, destination, receipt = _stage(root, game)
                for row in profile['files']:
                    info = mapped[row['path']]
                    if info.file_size != row['size']: raise ValueError('Andere gamebestandsgrootte in ZIP: ' + row['path'])
                    target = stage.joinpath(*_parts(row['path'])); target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256(); count = 0
                    with source.open(info) as incoming, target.open('xb') as outgoing:
                        while block := incoming.read(min(1024 ** 2, row['size'] + 1 - count)):
                            count += len(block)
                            if count > row['size']: raise ValueError('ZIP-onderdeel overschrijdt de gamebestandsgrootte.')
                            digest.update(block); outgoing.write(block)
                    if count != row['size'] or digest.hexdigest() != row['sha256']:
                        raise ValueError('Andere of gewijzigde Nederlandse gameversie in ZIP: ' + row['path'])
            if _identity(os.fstat(handle.fileno())) != _identity(before): raise ValueError('ZIP veranderde tijdens importeren.')
        if _identity(_plain(archive)) != _identity(before): raise ValueError('ZIP veranderde tijdens importeren.')
        return _finish(root, game, profile, stage, destination, receipt)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise ValueError('ZIP is beschadigd, versleuteld of wordt niet ondersteund.') from error
    finally:
        if stage is not None: _cleanup(stage, destination)
