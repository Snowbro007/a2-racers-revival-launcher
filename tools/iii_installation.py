"""Import an explicitly chosen III tour directory without running game code."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile

from tools import iii_local_launcher as native
from tools.game_installation import bounded_files, copy_file, promote_import
from tools.trial_manifest import validate_ancestors, validate_tree

SAVED_NAMES={'scores.dat','current.rcr','memreport.ini','debug.txt'}


def digest(path):
    validate_ancestors(path)
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def inspect(root,source,tour):
    records=native.source_records(root,tour)
    source=Path(os.path.abspath(source))
    files=bounded_files(source,max_bytes=1024**3)
    paths={p.relative_to(source).as_posix().casefold():p for p in files}
    if len(paths)!=len(files):
        raise ValueError('Gamemap bevat overlappende bestandsnamen.')
    prefix='' if 'spel.dat' in paths else 'data/'
    race=paths.get(prefix+'spel.dat')
    if race:
        pin=digest(race)
        from tools.iii_graphics_trial import SOURCE_SHA256
        detected=next((n for n,h in SOURCE_SHA256.items() if h==pin),None)
        if detected is not None and detected!=tour:
            raise ValueError(f'Deze map hoort bij Tour {detected}; kies eerst die tour.')
    selected={}
    for record in records:
        name=native.target_name(record['path'])
        candidates={prefix+name.casefold(),prefix+record['path'].casefold()}
        matches=[paths[key] for key in candidates if key in paths]
        if len(matches)!=1:
            raise ValueError('Kies de volledige ondersteunde deel-III-gamemap; ontbreekt of dubbel: '+name)
        path=matches[0]
        size=path.stat().st_size
        pin=digest(path)
        if name.casefold() in native.MUTABLE:
            if not 1<=size<=128*1024:
                raise ValueError('Ongeldige opgeslagen deel-III-instellingen: '+name)
        elif size!=record['bytes'] or pin!=record['sha256']:
            raise ValueError('Andere deel-III-versie of gewijzigd gamebestand: '+name)
        selected[name]={'source':path,'bytes':size,'sha256':pin}
    # Retain native saved players, not unrelated installers or executables.
    for key,path in paths.items():
        relative=key.removeprefix(prefix)
        if not key.startswith(prefix) or '/' in relative or relative in {n.casefold() for n in selected}:
            continue
        if relative in SAVED_NAMES or relative.endswith('.rcr'):
            size=path.stat().st_size
            if size>16*1024**2:
                raise ValueError('Opgeslagen deel-III-bestand is te groot.')
            selected[path.name]={'source':path,'bytes':size,'sha256':digest(path)}
    payload=[{'path':name,'bytes':row['bytes'],'sha256':row['sha256']} for name,row in sorted(selected.items())]
    tree_pin=hashlib.sha256(json.dumps(payload,sort_keys=True).encode('ascii')).hexdigest()
    return {'tour':tour,'source':source,'files':selected,'source_tree_sha256':tree_pin}


def import_folder(root,source,tour):
    root=root.absolute();source=Path(os.path.abspath(source))
    target=native.game_folder(root,tour);parent=target.parent
    receipt=root/f'local/launcher/installation-a2racer3-tour{tour}.json'
    for path in (parent,target,receipt):validate_ancestors(path)
    if source==parent or source.is_relative_to(parent) or parent.is_relative_to(source):
        raise ValueError('Bron en lokale speelopslag mogen elkaar niet overlappen.')
    if target.exists() or receipt.exists():
        raise ValueError('Deze tour is al gekoppeld; bestaande spelgegevens worden niet overschreven.')
    before=inspect(root,source,tour)
    parent.mkdir(parents=True,exist_ok=True);receipt.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.iii-import-',dir=parent) as directory:
        stage=Path(directory)/'tour';stage.mkdir()
        for name,row in before['files'].items():
            output=stage/name;output.parent.mkdir(parents=True,exist_ok=True)
            copy_file(row['source'],output)
            if output.stat().st_size!=row['bytes'] or digest(output)!=row['sha256']:
                raise ValueError('Gamegegevens veranderden tijdens het kopiëren.')
        after=inspect(root,source,tour)
        if after['source_tree_sha256']!=before['source_tree_sha256']:
            raise ValueError('Gamegegevens veranderden tijdens het koppelen.')
        validate_tree(stage)
        native.local_movie_path(stage)
        native.check_folder(root,tour,stage)
        data={'schema':1,'tour':tour,'source_path':str(source),'game_path':str(target),
              'source_tree_sha256':before['source_tree_sha256'],'source_unchanged':True,
              'game_imported':True,'game_started':False,'disc_image_required':False}
        promote_import(stage,target,receipt,data)
    native.check(root,tour)
    return data
