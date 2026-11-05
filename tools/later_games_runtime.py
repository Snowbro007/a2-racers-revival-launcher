"""Prepare fan-owned IV/Vakantieracer and run only through the original menu.

No private archives, inventory reports or developer runtime are required.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools import trial_manifest
from tools import later_native as native
from tools import later_game_installation as installation
from tools import later_session_backend as diagnostic
from tools import later_game_control as control
from tools.iii_session_guard import PlayPolicy, supervise

SPECS=native.SPECS
PROFILES=native.PROFILES
BASE='local/launcher/later-sessions'
REPORTS='reports/later-games'
MUTABLE={'game.ini','menu.ini','raser.ini','debug.ini','static.ini'}
sha=native.sha
patch_binary=native.patch_binary
profile_binary=native.profile_binary
set_ini=native.set_ini
race_ini=native.race_ini
profile_metadata=native.profile_metadata
validate_profile=native.validate_profile
WRAPPER_PINS={'cnc_ddraw':trial_manifest.CNC_DDRAW_COMPONENTS['ddraw.dll'],
              'dg_ddraw':trial_manifest.DGVOODOO_COMPONENTS['DDraw.dll']}

def game_base(game,profile='hd1080'):
    validate_profile(game,profile)
    return 'local/experiments/later/'+game+'/'+profile

def previous_progress(root,game,profile='hd1080'):
    # First-time copies already include the selected owner's imported saves.
    return {}

def previous_progress_folder(root,game,profile='hd1080'):
    return None

def load_probe(root):
    specs={game:SimpleNamespace(game=game,parent=parent,
        source='local/games/'+game+'/original') for game,parent in
        (('a2racer4','A2RACER4.EXE'),('vakantieracer','VRACER.EXE'))}
    def checked(root,spec):
        value=installation.check(root,spec.game)
        expected=Path(root)/spec.source
        if Path(value['source_path']).absolute()!=expected.absolute():
            raise ValueError('Onbekende beheerde bronmap.')
        return [{'source':r['path'],'target':r['path'],'size':r['size'],'sha256':r['sha256']} for r in value['files']]
    def copy(root,spec,records,target):
        plain_directory(target)
        target.mkdir(parents=True,exist_ok=False)
        for row in records:
            source=Path(root)/spec.source/row['source'];destination=target/row['target']
            plain(source);plain(destination);destination.parent.mkdir(parents=True,exist_ok=True)
            before=source.stat();digest=hashlib.sha256();count=0
            with source.open('rb') as incoming,destination.open('xb') as outgoing:
                while block:=incoming.read(min(1024*1024,row['size']-count+1)):
                    count+=len(block)
                    if count>row['size']: raise ValueError('Bron groeide tijdens kopieren.')
                    digest.update(block);outgoing.write(block)
            plain(source);after=source.stat()
            if ((before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino)
                    or count!=row['size'] or digest.hexdigest()!=row['sha256']):
                raise ValueError('Bron veranderde tijdens kopieren.')
        return [dict(row) for row in records]
    return SimpleNamespace(SOURCES=specs,check_source=checked,prepare=copy,
        MenuDiagnostics=diagnostic.MenuDiagnostics,DiagnosticMenuBackend=diagnostic.DiagnosticMenuBackend)

def plain_directory(path):
    trial_manifest.validate_ancestors(Path(path))
    if path.exists() and not path.is_dir(): raise ValueError('Verwachte map is geen gewone map.')

def component_plan(root,game='vakantieracer',profile='hd1080'):
    validate_profile(game,profile)
    cnc=Path(root)/'local/components/cnc-ddraw'/trial_manifest.CNC_DDRAW_VERSION/'extracted'
    dg=Path(root)/'local/components/dgvoodoo'/trial_manifest.DGVOODOO_VERSION/'extracted'
    menu=trial_manifest._read_pinned_component(cnc/'ddraw.dll',WRAPPER_PINS['cnc_ddraw'],'menu')
    race=trial_manifest._read_pinned_component(dg/'MS/x86/DDraw.dll',WRAPPER_PINS['dg_ddraw'],'race')
    d3d=trial_manifest._read_pinned_component(dg/'MS/x86/D3DImm.dll',trial_manifest.DGVOODOO_COMPONENTS['D3DImm.dll'],'D3DImm')
    cfg=trial_manifest._read_pinned_component(dg.parent/trial_manifest.DGVOODOO_CONFIG_SOURCE['source'],trial_manifest.DGVOODOO_CONFIG_SOURCE,'race config')
    return {'profiles/menu/DDraw.dll':menu,'profiles/race/DDraw.dll':race,
            'DDraw.dll':menu,'D3DImm.dll':d3d,'ddraw.ini':native.MENU_CONFIG,
            'dgVoodoo.conf':native.race_config(cfg,profile)}

def is_mutable(name):
    key=name.casefold()
    return key in MUTABLE or re.fullmatch(r'savegame[0-9]{1,3}\.rcr',key) is not None


def plain(path):
    trial_manifest.validate_ancestors(path)
    if path.exists():
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
            raise ValueError('Bestand is geen enkelvoudig gewoon bestand.')


def write_new(path,raw):
    path=Path(path);plain(path);path.parent.mkdir(parents=True,exist_ok=True);plain(path)
    with path.open('xb') as stream: stream.write(raw)


def write_json(path,value): write_new(path,(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode())


def verify(game_dir,metadata):
    expected={r['path'].casefold():r for r in metadata['files']};actual=set()
    for path in game_dir.rglob('*'):
        trial_manifest.validate_ancestors(path)
        if path.is_dir(): continue
        plain(path);name=path.relative_to(game_dir).as_posix().casefold();actual.add(name)
        if name in expected:
            if is_mutable(name):
                limit=1024*1024 if name in MUTABLE else 4*1024*1024
                if path.stat().st_size>limit: raise ValueError('Spelersdata overschrijden de grens.')
                continue
            row=expected[name]
            digest=sha(path.read_bytes())
            if name=='ddraw.dll' and digest in {WRAPPER_PINS[k]['sha256'] for k in ('cnc_ddraw','dg_ddraw')}:
                continue
            if path.stat().st_size!=row['size'] or digest!=row['sha256']:
                raise ValueError('Speelkopie wijkt af: '+name)
        elif path.suffix.lower() in ('.exe','.dll','.ocx','.sys','.com','.bat','.cmd','.ps1','.py','.vbs'):
            raise ValueError('Onverwachte uitvoerbare code in de speelkopie.')
    if not set(expected)<=actual: raise ValueError('Speelkopie is onvolledig.')


def prepare(root,game,profile='compat'):
    validate_profile(game,profile)
    provider=load_probe(root);spec=provider.SOURCES[game];mapped=provider.check_source(root,spec)
    wrappers=component_plan(root,game,profile);parent=root/game_base(game,profile);metadata_path=parent/'prepared.json';game_dir=parent/'game'
    baseline='native-wide1080-v1-horplus-hud' if profile=='wide1080' else 'wrapper-hd1080-v3-mouse-shutdown' if profile=='hd1080' else 'compat640-v2-mouse-shutdown'
    if metadata_path.exists():
        plain(metadata_path)
        if metadata_path.stat().st_size>4*1024*1024: raise ValueError('Voorbereidingsrecord is te groot.')
        metadata=json.loads(metadata_path.read_bytes())
        if (metadata.get('game')!=game or metadata.get('baseline')!=baseline
                or metadata.get('parent')!=spec.parent or metadata.get('profile','compat')!=profile):
            raise ValueError('Andere baseline-registratie; bestaande map behouden.')
        expected={r['target'].casefold():r['sha256'] for r in mapped}
        for kind,name in [('menu','menu.exe'),('race','spel.dat')]:
            source=next(r for r in mapped if r['target'].casefold()==name)
            expected[name]=profile_binary((root/spec.source/source['source']).read_bytes(),game,kind,profile)[1]['sha256']
        expected.update({name.casefold():sha(raw) for name,raw in wrappers.items()})
        if {r['path'].casefold():r['sha256'] for r in metadata['files'] if not is_mutable(r['path'])}!={k:v for k,v in expected.items() if not is_mutable(k)}:
            raise ValueError('Baseline-manifest wijkt af van de eigen bron.')
        verify(game_dir,metadata)
        # Report the current requested startup policy without rewriting the
        # historical preparation manifest or its original mutable-file hashes.
        metadata['startup_behavior']=startup_behavior()
        metadata.update(profile_metadata(profile))
        return metadata
    if parent.exists(): raise ValueError('Onvolledige voorbereiding; bestaande map behouden.')
    final_parent=parent;final_game_dir=game_dir
    parent=final_parent.with_name('.build-'+profile+'-'+uuid.uuid4().hex)
    game_dir=parent/'game'
    progress=previous_progress(root,game,profile)
    copied=provider.prepare(root,spec,mapped,game_dir);patches=[]
    for name,raw in progress.items():
        target=game_dir/name;plain(target);target.write_bytes(raw)
    menu_ini=next(game_dir/r['target'] for r in copied if r['target'].casefold()=='menu.ini')
    menu_ini.write_bytes(set_ini(menu_ini.read_bytes(),'GENERAL','INTROAVI',str(final_game_dir/'INTRO1.MPG')))
    for kind,name in [('menu','menu.exe'),('race','spel.dat')]:
        row=next(r for r in copied if r['target'].casefold()==name);path=game_dir/row['target']
        updated,details=profile_binary(path.read_bytes(),game,kind,profile);path.write_bytes(updated);patches.append(details)
    ini=next(game_dir/r['target'] for r in copied if r['target'].casefold()=='raser.ini')
    ini.write_bytes(race_ini(ini.read_bytes(),game,profile))
    for name,raw in wrappers.items(): write_new(game_dir/name,raw)
    files=[]
    for path in game_dir.rglob('*'):
        if path.is_file():
            plain(path);files.append({'path':path.relative_to(game_dir).as_posix(),'size':path.stat().st_size,'sha256':sha(path.read_bytes())})
    metadata={'schema':1,'game':game,'baseline':baseline,'parent':spec.parent,'files':files,'patches':patches,
              'game_path':str(final_game_dir),'no_cd':'builtin-child-environment','race_canvas_requested':[640,480],
              'menu_output_requested':[1920,1080],'runtime_verified':False,'source_content_verified':True}
    metadata['virtual_desktop_bitdepth_requested']=16
    metadata.update(profile_metadata(profile))
    metadata['virtual_vram_mb_requested']=32
    if game=='a2racer4': metadata['vram_probe_max_handles']=1024
    metadata['graphics_revision']=('native-wide1080-horplus-hud-v1' if profile=='wide1080' else 'hd1080-appfullscreen-windowed4:3-v2-20261105' if profile=='hd1080'
                                   else 'compat640-native16-chain-v2-20261104')
    metadata['graphics_runtime_verified']=False
    metadata['race_startup_grace_seconds']=RaceBaselinePolicy.startup_seconds
    metadata['startup_behavior']=startup_behavior()
    metadata['shutdown_mouse_revision']='cleanup-pump-no-idle-input-v1-20261105'
    metadata['shutdown_mouse_runtime_verified']=False
    if game in ('vakantieracer','a2racer4'):
        metadata['input_revision']=('mouse-joystick-recovery-v7-20261102' if game=='vakantieracer'
                                    else 'iv-mouse-joystick-recovery-v2-20261104')
        previous=previous_progress_folder(root,game,profile)
        metadata['progress_migration']={'source':str(previous) if previous is not None else None,
            'files':[{'name':name,'size':len(raw),'sha256':sha(raw)} for name,raw in progress.items()]}
    write_json(parent/'prepared.json',metadata);verify(game_dir,metadata)
    trial_manifest.validate_ancestors(final_parent)
    if final_parent.exists(): raise ValueError('De speelkopie is intussen toegevoegd; bestaande data behouden.')
    parent.rename(final_parent)
    return metadata


class BaselinePolicy(PlayPolicy):
    startup_seconds=8
    def __init__(self,started,seconds):
        super().__init__(started,seconds);self.startup_deadline=started+self.startup_seconds
    def stop_reason(self,observation,now):
        if now<self.startup_deadline: observation=replace(observation,responsive=None)
        return super().stop_reason(observation,now)


class RaceBaselinePolicy(BaselinePolicy):
    # Native level loading does not pump messages; the last real VR run was
    # stopped at 18s while loading ETAPPE0, not with a native crash code.
    # Only startup responsiveness has extra grace. Emergency/deadline/cursor
    # protections remain active, and later hangs keep the normal ten seconds.
    startup_seconds=45


def startup_behavior():
    return {'revision':'quiet-loading-20261105',
            'race_debug_logging_requested':False,
            'race_startup_grace_seconds':RaceBaselinePolicy.startup_seconds,
            'loading_hang_fix_verified':False}


def centered_if_outside(rect,width,height):
    left,top,right,bottom=rect;w,h=right-left,bottom-top
    if not 0<w<=width or not 0<h<=height: return None
    if left<0 or top<0 or right>width or bottom>height:
        return ((width-w)//2,(height-h)//2)
    return None


def run(root,game,*,profile='compat',check_only=False,seconds=14400,supervisor=None,display_factory=None,
        control_token=None):
    validate_profile(game,profile)
    control.validate_token(control_token)
    if type(seconds) is not int or not 2<=seconds<=14400: raise ValueError('Speeltijd moet 2 tot 14400 seconden zijn.')
    root=Path(root).absolute();lock=root/BASE/'session.lock';plain(lock);lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('xb') as handle: handle.write(str(os.getpid()).encode())
    try:
        metadata=prepare(root,game,profile)
        if check_only: return {'game':game,'profile':profile,'ready':True,'game_started':False,'metadata':metadata}
        name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-')+game+('-hd1080-' if profile=='hd1080' else '-')+uuid.uuid4().hex[:8]
        report=root/REPORTS/name;report.mkdir(parents=True,exist_ok=False);game_dir=root/game_base(game,profile)/'game'
        if not re.fullmatch('[a-zA-Z]:',game_dir.drive): raise ValueError('NOCD vereist een gewone lokale schijfletter.')
        environment={k:v for k,v in os.environ.items() if k.casefold()!='nocd'};environment['NOCD']=game_dir.drive[0].upper()
        provider=load_probe(root)
        if display_factory is None:
            from tools.later_display import WindowsDisplaySession
            display_factory=WindowsDisplaySession
        display=display_factory();before=display.snapshot()
        result={'game':game,'profile':profile,'game_path':str(game_dir),
                'game_started':False,'runtime_verified':False,'report':str(report),'seconds':seconds,
                'stop_requested':False,
                'startup_behavior':startup_behavior(),
                'environment_override':{'NOCD':environment['NOCD']}}
        result.update(profile_metadata(profile))
        write_json(report/'start-request.json',result)
        result['stages']=[]
        started=time.monotonic();deadline=started+seconds
        def control_requested():
            if control.stop_requested(root,control_token):
                result['stop_requested']=True
                return True
            return False
        menu_ini=next(p for p in game_dir.iterdir() if p.name.casefold()=='menu.ini')
        stage='menu';first=True
        try:
            while time.monotonic()<deadline:
                if control_requested():
                    result['guard']={'reason':'user_requested_stop',
                        'elapsed_seconds':round(time.monotonic()-started,3),
                        'cleanup_verified':True,'game_compatibility_verified':False}
                    break
                wrapper=game_dir/'profiles'/stage/'DDraw.dll'
                plain(wrapper);plain(game_dir/'DDraw.dll')
                (game_dir/'DDraw.dll').write_bytes(wrapper.read_bytes())
                if stage=='menu':
                    plain(menu_ini)
                    ini_bytes=set_ini(set_ini(menu_ini.read_bytes(),'GENERAL','EXITCODE','0'),
                                      'GENERAL','INTROAVI',str(game_dir/'INTRO1.MPG'))
                    if first: ini_bytes=set_ini(ini_bytes,'GENERAL','PREVSTATE','0')
                    menu_ini.write_bytes(ini_bytes)
                else:
                    race_ini_path=next(p for p in game_dir.iterdir() if p.name.casefold()=='raser.ini')
                    plain(race_ini_path)
                    race_ini_path.write_bytes(race_ini(race_ini_path.read_bytes(),game,profile))
                exe=next(p for p in game_dir.iterdir() if p.name.casefold()==('menu.exe' if stage=='menu' else 'spel.dat'))
                argv=[str(exe)]
                if stage=='menu': argv.append('/Default')
                options={'seconds':max(2,min(14400,int(deadline-time.monotonic()))),
                         'policy_factory':RaceBaselinePolicy if stage=='race' else BaselinePolicy}
                diagnostics=provider.MenuDiagnostics() if supervisor is None else None
                if diagnostics is not None:
                    class StageBackend(provider.DiagnosticMenuBackend):
                        def observe(self):
                            observation=super().observe()
                            if control_requested(): return replace(observation,emergency=True)
                            if stage!='menu': return observation
                            from ctypes import wintypes as w
                            c=self.c;user=self.user
                            callback_type=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
                            user.EnumWindows.argtypes=[callback_type,w.LPARAM];user.EnumWindows.restype=w.BOOL
                            user.IsWindowVisible.argtypes=[w.HWND];user.IsWindowVisible.restype=w.BOOL
                            user.GetWindowRect.argtypes=[w.HWND,c.POINTER(w.RECT)];user.GetWindowRect.restype=w.BOOL
                            user.GetSystemMetrics.argtypes=[c.c_int];user.GetSystemMetrics.restype=c.c_int
                            user.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT];user.SetWindowPos.restype=w.BOOL
                            def position(hwnd,unused):
                                if not user.IsWindowVisible(hwnd) or not self.own_window(hwnd): return True
                                rect=w.RECT()
                                if user.GetWindowRect(hwnd,c.byref(rect)):
                                    target=centered_if_outside((rect.left,rect.top,rect.right,rect.bottom),user.GetSystemMetrics(0),user.GetSystemMetrics(1))
                                    if target: user.SetWindowPos(hwnd,None,target[0],target[1],0,0,0x15)
                                return True
                            user.EnumWindows(callback_type(position),0)
                            return observation
                        def resume(self):
                            super().resume()
                            write_json(report/('stage-'+str(len(result['stages']))+'-binding.json'),
                                       {'pid':int(self.process.pid),'image':str(exe),'stage':stage})
                    options['backend_factory']=lambda:StageBackend(diagnostics)
                outcome=(supervisor or supervise)(argv,game_dir,environment,**options)
                entry={'stage':stage,'guard':outcome}
                if diagnostics is not None:
                    entry['diagnostics']=diagnostics.snapshot()
                    roots=[p for p in (diagnostics.before_cleanup or []) if p.get('image_basename','').lower()==exe.name.lower()]
                    entry['exit_code']=roots[0].get('exit_code') if len(roots)==1 else None
                else: entry['exit_code']=outcome.get('exit_code')
                result['stages'].append(entry);result['game_started']=True;result['guard']=outcome
                if outcome['reason']!='exited' or entry['exit_code']!=0: break
                if stage=='race': stage='menu';first=False;continue
                import configparser
                config=configparser.ConfigParser(interpolation=None)
                config.read_string(menu_ini.read_bytes().decode('cp1252'))
                sections=[s for s in config.sections() if s.lower()=='general']
                code=config.getint(sections[0],'exitcode',fallback=0) if len(sections)==1 else 0
                entry['menu_ini_exitcode']=code
                if code!=40: break
                stage='race'
        finally:
            try:
                plain(game_dir/'DDraw.dll')
                (game_dir/'DDraw.dll').write_bytes((game_dir/'profiles/menu/DDraw.dll').read_bytes())
            finally:
                result['display_restore']=display.restore(before);write_json(report/'result.json',result)
        return result
    finally: lock.unlink()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--game',choices=tuple(SPECS),required=True)
    parser.add_argument('--profile',choices=PROFILES,default='hd1080')
    parser.add_argument('--check-only',action='store_true');parser.add_argument('--seconds',type=int,default=14400)
    parser.add_argument('--control-token')
    args=parser.parse_args(argv)
    try:
        print(json.dumps(run(ROOT,args.game,profile=args.profile,check_only=args.check_only,seconds=args.seconds,
                             control_token=args.control_token),ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Baseline kon niet starten: '+str(error),file=sys.stderr);return 1

if __name__=='__main__': raise SystemExit(main())
