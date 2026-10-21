"""Freeze and verify a clean public launcher candidate; never push or upload."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools import portable_launcher as package
from tools.trial_manifest import validate_ancestors
from tools.check_public_docs import check_paths

FORBIDDEN_PARTS={'.git','.codex','.agents','local','reports','game-media','gamebestanden','payload','prompts'}
FORBIDDEN_SUFFIXES={'.exe','.dll','.zip','.iso','.bin','.cue','.sav','.dat','.img','.ind','.smk','.avi','.wav','.mp3'}

def source_files(root:Path):
    result=package.records(root,public=True)
    names=set()
    for name,path,pin in result:
        parts=Path(name).parts
        if any(part.casefold() in FORBIDDEN_PARTS for part in parts) or Path(name).suffix.casefold() in FORBIDDEN_SUFFIXES or 'agents' in name.casefold():
            raise ValueError('Persoonlijk/game/componentbestand in openbare bestandsset: '+name)
        if name.casefold() in names:raise ValueError('Dubbele openbare bestandsnaam.')
        names.add(name.casefold())
    check_paths(row[0] for row in result)
    return result

def freeze(root:Path,destination:Path):
    validate_ancestors(destination)
    if destination.exists():raise ValueError('Publicatiekopie bestaat al; kies een nieuwe map.')
    inputs=source_files(root)
    before=[package.file_record(*row) for row in inputs]
    destination.mkdir(parents=True)
    for (name,path,_),row in zip(inputs,before):
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Bron veranderde tijdens bevriezen.')
        target=destination/name;validate_ancestors(target)
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(data)
    if before!=[package.file_record(*row) for row in inputs]:raise ValueError('Bronnen veranderden tijdens bevriezen; kopie niet vrijgegeven.')
    return {'source_copy':str(destination),'files':before,'games_included':False,'published':False}

def prepare(root:Path,source:Path,output:Path):
    receipt=freeze(root,source)
    result=package.build(source,output,public=True)
    with zipfile.ZipFile(output) as archive:
        actual={name.removeprefix(package.PREFIX) for name in archive.namelist()}
    expected={row['path'] for row in receipt['files']}|{'release-manifest.json'}
    if actual!=expected:raise ValueError('Werkelijke openbare ZIP wijkt af van de bevroren kopie.')
    return {**result,'source_copy':str(source),'public_ready':True,'external_binaries_bundled':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    try:print(json.dumps(prepare(ROOT,args.source,args.output)));return 0
    except (OSError,ValueError,KeyError) as exc:print(str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
