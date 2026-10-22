"""Separate III compatibility / 1080p candidates with verified local providers.

Never edit original sources or prior saved copies. Preparation is static;
only the explicitly requested start action launches the original tour parent.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools import iii_local_launcher as baseline, iii_graphics_trial as graphics
from tools import trial_manifest as manifest
from tools.ii_frontend_state import read_regular
from tools.ii_next_wrapper_probe import replace_setting
from tools.local_game_data import launch_environment
from tools import iii_start_safety
from tools import iii_guarded_start

PROFILES={
    'compat':{'label':'Compatibiliteit · originele resolutie · untested',
              'description':'untested · Variant voor de schermfout bij racestart. Originele graphics en lucht; speelbaarheid nog te bevestigen.'},
    'fullhd-skyoff':{'label':'1080p · horizon en wolken uit · untested',
                    'description':'Horizon en wolken uit. De HUD houdt voorlopig zijn oorspronkelijke grootte. Deze 1080p-variant is untested.'},
}
MUTABLE={'game.ini','raser.ini','menu.ini','scores.dat','current.rcr','memreport.ini','debug.txt'}
FONT_CACHE_LIMITS={'menufont1.dat':65536,'menufont2.dat':65536,
                   'menufont1.res':4096,'menufont2.res':4096}
MUTABLE.update(FONT_CACHE_LIMITS)
MAX_FILE_BYTES=256*1024**2  # Original Tour 2 RCS.IMG is 139,537,368 bytes.


def sha(raw): return hashlib.sha256(raw).hexdigest()


def override_ini(raw,changes):
    """Preserve unrelated duplicate native keys (III MUSIC has two counts)."""
    if type(raw) is not bytes or not 1<=len(raw)<=128*1024:
        raise ValueError('Ongeldige deel-III-instellingen.')
    wanted={(s.casefold(),k.casefold()):str(v) for (s,k),v in changes.items()}
    seen=set();section='';headers={s:0 for s,k in wanted};lines=[]
    for line in raw.decode('latin1').splitlines(keepends=True):
        header=re.fullmatch(r'[ \t]*\[([^\]]+)\][ \t]*(?:\r?\n)?',line)
        if header:
            section=header[1].casefold()
            if section in headers: headers[section]+=1
        value=re.fullmatch(r'([ \t]*([^=;\r\n]+?)[ \t]*=[ \t]*)([^;\r\n]*?)([ \t]*(?:;[^\r\n]*)?)(\r?\n)?',line)
        if value:
            key=(section,value[2].strip().casefold())
            if key in wanted:
                if key in seen: raise ValueError('Dubbele gevraagde deel-III-instelling.')
                seen.add(key);line=value[1]+wanted[key]+value[4]+(value[5] or '')
        lines.append(line)
    if seen!=set(wanted) or any(count!=1 for count in headers.values()):
        raise ValueError('Gevraagde deel-III-instelling ontbreekt of is dubbel.')
    return ''.join(lines).encode('latin1')


def folder(root,tour,profile):
    if type(tour) is not int or tour not in (1,2) or profile not in PROFILES:
        raise ValueError('Onbekende deel-III-tour of beeldkeuze.')
    return root/'local/iii-trials'/f'tour{tour}-{profile}'


def wrapper_inputs(root,profile):
    if profile not in PROFILES: raise ValueError('Onbekende deel-III-beeldkeuze.')
    component=root/'local/components/dgvoodoo'/manifest.DGVOODOO_VERSION/'extracted'
    payload={name:manifest._read_pinned_component(component/spec['source'],spec,name)
             for name,spec in manifest.DGVOODOO_COMPONENTS.items()}
    config=manifest.dgvoodoo_windowed_config(component)
    for section,key,before,after in (
        (b'General',b'ScalingMode',b'unspecified',b'stretched_ar'),
        (b'General',b'CaptureMouse',b'true',b'false'),
        (b'General',b'CenterAppWindow',b'false',b'true'),
        (b'GeneralExt',b'WindowedAttributes',b'',b'borderless,fullscreensize'),
        (b'GeneralExt',b'SystemHookFlags',b'',b'cursor'),
        (b'DirectXExt',b'PrimarySurfaceBatchedUpdate',b'false',b'true'),
        (b'DirectX',b'dgVoodooWatermark',b'true',b'false')):
        config=replace_setting(config,section,key,before,after)
    if profile=='fullhd-skyoff':
        config=replace_setting(config,b'DirectXExt',b'ExtraEnumeratedResolutions',b'',b'1920x1080')
    payload['dgVoodoo.conf']=config
    return payload


def tree_bytes(source):
    manifest.validate_tree(source)
    entries={};total=0
    for path in sorted(source.rglob('*')):
        if path.is_file():
            raw=read_regular(path,MAX_FILE_BYTES);total+=len(raw)
            if len(entries)>=1000 or total>1024**3:
                raise ValueError('Onverwacht grote deel-III-speelkopie.')
            entries[path.relative_to(source).as_posix()]=raw
    return entries


def prepare(root,tour,profile):
    target=folder(root,tour,profile)
    manifest.validate_ancestors(target)
    if target.exists():
        check(root,tour,profile)
        return target
    # Existing user saves/configs are copied after immutable baseline validation.
    seed=baseline.prepare(root,tour)
    before=tree_bytes(seed)
    wrappers=wrapper_inputs(root,profile)
    if any(name in before for name in wrappers):
        raise ValueError('Wrapper bestaat al in de bron; samenvoegen geweigerd.')
    result=dict(before);patch_plan=None
    if profile=='fullhd-skyoff':
        native={name.casefold():name for name in before}
        race,settings,state=(native[name] for name in ('spel.dat','raser.ini','game.ini'))
        result[race],patch_plan=graphics.build(before[race],tour,True)
        result[settings]=override_ini(before[settings],{('PROGRAM','RESOLUTION'):3})
        result[state]=override_ini(before[state],{('GFX OPTIONS','clouds'):0})
    result.update(wrappers)
    target.parent.mkdir(parents=True,exist_ok=True)
    record={'schema':1,'tour':tour,'profile':profile,'source_unchanged':True,
        'runtime_verified':False,'native_game_executed':False,'disc_image_used':False,
        'binary_modified':profile=='fullhd-skyoff','wrapper':manifest.DGVOODOO_VERSION,
        'patch_plan':patch_plan,'seed':str(seed),
        'files':[{'path':name,'sha256':sha(raw)} for name,raw in sorted(result.items())
                 if Path(name).name.casefold() not in MUTABLE and not name.casefold().endswith('.rcr')]}
    # Commit only a completely checked candidate. A failed preparation leaves
    # the prior player copy and the final candidate path untouched.
    with tempfile.TemporaryDirectory(prefix='.iii-stage-',dir=target.parent) as directory:
        stage=Path(directory)/'candidate';stage.mkdir()
        for name,raw in result.items():
            output=stage/name;output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(raw)
        if tree_bytes(seed)!=before:
            raise ValueError('Deel-III-spelersbron veranderde; kandidaat niet geregistreerd.')
        (stage/'compatibility.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        check_path(root,tour,profile,stage)
        stage.rename(target)
    return target


def check(root,tour,profile):
    target=folder(root,tour,profile)
    return check_path(root,tour,profile,target)


def check_path(root,tour,profile,target):
    folder(root,tour,profile)
    manifest.validate_tree(target)
    raw=read_regular(target/'compatibility.json',65536);record=json.loads(raw)
    if (record.get('schema')!=1 or record.get('tour')!=tour or record.get('profile')!=profile
            or not isinstance(record.get('files'),list)):
        raise ValueError('Onjuiste deel-III-proefregistratie.')
    # Manifest pins are checked against independent original and provider pins.
    original={baseline.target_name(r['path']):r['sha256'] for r in baseline.source_records(root,tour)}
    wrappers=wrapper_inputs(root,profile)
    expected={name:pin for name,pin in original.items() if Path(name).name.casefold() not in MUTABLE}
    expected.update({name:sha(value) for name,value in wrappers.items()})
    if profile=='fullhd-skyoff':
        race=next(name for name in expected if name.casefold()=='spel.dat')
        expected[race]=graphics.OUTPUT_SHA256[tour,True]
    actual={entry['path']:entry['sha256'] for entry in record['files']}
    # Added saved files are mutable; no arbitrary executable may join the manifest.
    if actual!=expected or len(actual)!=len(record['files']):
        raise ValueError('Andere deel-III-bestandcontracten.')
    names={path.relative_to(target).as_posix() for path in target.rglob('*') if path.is_file()}
    unexpected={name for name in names if name not in expected and name!='compatibility.json'
                and Path(name).name.casefold() not in MUTABLE and not name.casefold().endswith('.rcr')}
    if unexpected:
        raise ValueError('Onbekende bestanden in de deel-III-speelkopie.')
    for name in names:
        maximum=FONT_CACHE_LIMITS.get(name.casefold())
        if maximum is not None:read_regular(target/name,maximum)
    for name,pin in expected.items():
        content=read_regular(target/name,MAX_FILE_BYTES)
        if sha(content)!=pin: raise ValueError('Deel-III-proefbestand veranderde: '+name)
    return {'tour':tour,'profile':profile,'game_path':str(target),'launch_ready':True,
            'runtime_verified':False,'disc_image_used':False,'binary_modified':profile=='fullhd-skyoff'}


def available(root,tour,profile):
    try:
        folder(root,tour,profile)
        baseline.check(root,tour)
        wrapper_inputs(root,profile)
        return {'available':True,'reason':PROFILES[profile]['description']}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'available':False,'reason':str(exc)}


def start(root,tour,profile):
    iii_start_safety.assert_start_allowed(tour, profile)
    target=prepare(root,tour,profile)
    if profile=='fullhd-skyoff':
        for path,changes in ((target/'raser.ini',{('PROGRAM','RESOLUTION'):3}),
                             (target/'game.ini',{('GFX OPTIONS','clouds'):0})):
            raw=read_regular(path,128*1024)
            value=override_ini(raw,changes)
            if value!=raw:path.write_bytes(value)
    return iii_guarded_start.run(root, tour, profile, target)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','check','start'))
    parser.add_argument('--tour',type=int,choices=(1,2),required=True)
    parser.add_argument('--profile',choices=tuple(PROFILES),default='compat')
    args=parser.parse_args()
    try:
        if args.action=='start':return start(ROOT,args.tour,args.profile)
        if args.action=='prepare':prepare(ROOT,args.tour,args.profile)
        print(json.dumps(check(ROOT,args.tour,args.profile)));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
