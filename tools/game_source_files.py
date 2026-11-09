"""Read-only, bounded recognition of original NL game files in CD/install layouts.

Only selected, independently pinned game files are copied by the importer.
Names are Windows-case-insensitive. Unknown executable/resource bytes never
become supported merely because a folder contains the right filenames.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
from tools.game_source_profiles import CORE_FILES
from tools.trial_manifest import validate_ancestors

MAX_FILES = 5000
MAX_ENTRIES = 10000
MAX_BYTES = 1024**3


def case_path(parent, name):
    matches = [p for p in Path(parent).iterdir() if p.name.casefold() == name.casefold()]
    if len(matches) > 1:
        raise ValueError('Dubbele bestandsnamen met andere hoofdletters: ' + name)
    path = matches[0] if matches else Path(parent) / name
    validate_ancestors(path)
    return path


def scan_files(source):
    source = Path(source)
    validate_ancestors(source)
    if not source.is_dir():
        raise ValueError('Kies een bestaande gamemap of het cd-station.')
    paths = {}; seen = set(); total = entries = 0; stack = [source]
    while stack:
        current = stack.pop()
        if len(current.relative_to(source).parts) > 16:
            raise ValueError('De bronmap is te diep; kies alleen de gamemap.')
        validate_ancestors(current)
        for path in current.iterdir():
            entries += 1
            if entries > MAX_ENTRIES:
                raise ValueError('De bronmap bevat te veel onderdelen; kies alleen de gamemap.')
            validate_ancestors(path)
            relative = path.relative_to(source).as_posix()
            key = relative.casefold()
            if key in seen:
                raise ValueError('Dubbele bestandsnamen met andere hoofdletters: ' + relative)
            seen.add(key)
            info = path.stat()
            if stat.S_ISDIR(info.st_mode):
                stack.append(path)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
                paths[key] = path
                if len(paths) > MAX_FILES or total > MAX_BYTES:
                    raise ValueError('De bronmap is te groot; kies alleen de gamemap.')
            else:
                raise ValueError('De bron bevat een gekoppeld of niet-gewoon bestand: ' + relative)
    return source, paths


def verify_game_files(source, game, *, profile=None):
    if game not in CORE_FILES:
        raise ValueError('Onbekende game voor broncontrole.')
    profile = CORE_FILES[game] if profile is None else profile
    source, paths = scan_files(source)
    prefix = ''
    target_prefix = '' if game == 'a2racer1' else 'DATA/'
    if game == 'a2racer2' and ('data/spel.dat' in paths or
            ('spel.dat' not in paths and case_path(source, 'DATA').is_dir())):
        prefix = 'data/'
    records = []; mapping = []; snapshots = []
    for name, pin in sorted(profile.items()):
        target = target_prefix + name
        path = paths.get(prefix + name.casefold())
        if path is None:
            image = any(Path(key).suffix in ('.bin', '.cue', '.iso', '.nrg') for key in paths)
            if image:
                raise ValueError('Deze map bevat een cd-image. Kies je ZIP via Ik heb een ZIP-bestand, '
                                 'of selecteer de uitgepakte gamemap of het cd-station.')
            raise ValueError('De bron mist spelbestand ' + target + '. Kies de volledige Nederlandse gamemap, '
                             'de DATA-map van deel II, het cd-station of je originele ZIP.')
        before = path.stat()
        if before.st_size != pin['size']:
            raise ValueError('De bron bevat een andere grootte van ' + target + '. Kies een originele, ongewijzigde bron of ZIP.')
        digest = hashlib.sha256(); count = 0
        with path.open('rb') as stream:
            while block := stream.read(min(1024**2, pin['size'] + 1 - count)):
                digest.update(block); count += len(block)
                if count > pin['size']:
                    raise ValueError('Het spelbestand veranderde tijdens controle: ' + target)
        validate_ancestors(path); after = path.stat()
        identity = (before.st_size, before.st_mtime_ns, before.st_ino)
        if identity != (after.st_size, after.st_mtime_ns, after.st_ino) or count != before.st_size:
            raise ValueError('Het spelbestand veranderde tijdens controle: ' + target)
        if digest.hexdigest() != pin['sha256']:
            kind = 'gewijzigde instellingen in ' if name.casefold().endswith('.ini') else 'een andere versie van '
            raise ValueError('De bron bevat ' + kind + target + '. Kies een originele, ongewijzigde bron of ZIP.')
        records.append({'path':target,'size':count,'sha256':digest.hexdigest()})
        mapping.append({'source':path.relative_to(source).as_posix(),'target':target})
        snapshots.append((path, identity))
    for path, before in snapshots:
        validate_ancestors(path); after = path.stat()
        if before != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('De spelbestanden veranderden tijdens controle; probeer opnieuw.')
    fingerprint = hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')).hexdigest()
    return {'game':game,'validation':'verified-game-files','source_tree_sha256':fingerprint,
            'source_files':len(records),'files':len(records),'source_bytes':sum(r['size'] for r in records),
            'bytes':sum(r['size'] for r in records),'file_map':mapping,
            'native_game_executed':False}
