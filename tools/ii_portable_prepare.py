"""Build native II frontend sources from the player's verified files, never run games.

Public releases carry code and our PNG artwork, not game/archive/font binaries.
Native 720p/1080p/4K is reproducible. Existing local HD sources remain supported
by ii_launcher_graphics; the public native builder does not claim to supply them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import ii_frontend_prepare as art, ii_frontend_launcher as frontend
from tools import ii_frontend_state as state, ii_next_wrapper_probe as wrapper
from tools import ii_frontend_fullscreen as fullscreen, ii_resolution_trials as resolutions
from tools import ii_playtest_check, trial_manifest
from tools.ii_hd_hud_assets import replace_resources
from tools.pcx_codec import IndexedImage, decode_pcx, encode_pcx
from tools.vehicle_mesh import decode_vehicle_mesh

NATIVE_RESOLUTIONS = {'720p': (1280,720), '1080p': (1920,1080), '4k': (3840,2160)}
PROFILE_PINS = {
    '720p': '3efd468f9844e8031b1f804c761d23c94f0a2fed66fa7b7d35dbac44faa33d3a',
    '1080p': 'c0f3c9d1d4b7d919371d6240ae2f742abcd8661317f4d5eb84e974e22533d556',
    '4k': 'ae7f4f8dd9fbfa70f8e2eb34b69a308b6febbf0b4a7a7adbb98b1120e8740722',
}
ART_PINS = {
    'part-motor.png': 'a3bf5d2df290a73c08cdd1c0cce9342ef069e5ae9d7ff348013e0d3f81dd9fd2',
    'part-tires.png': '155c1981d33b4baa6eb19742f93b8725299b10e8da7414a0fe8fd0bf7472839c',
    'part-turbo.png': '0396943cfac5e0f817cbccf1e9034bcb6cce3a9ecfc542aca3b884ec22880d95',
    'part-brakes.png': 'bf7b6bb371eee25cc886c53d23ba1a2f6a51b8d73e0695143b0aec9d5501493f',
    'part-gears.png': '9ce7ca7e90d55fc420fccdd8527607264a526cc87e89d4c7126891283e5f833b',
    'car0-preview.png': '8346d0c393232ebb702b5b931286bb075bb854afa3173e93ec33cb4ad51587a3',
    'car1-preview.png': '330ade9c760291505873b7abd0661672b6defc51b347268638c3ceb445b1f3e0',
    'car2-preview.png': '7afdcb76b4318399b16650386a7198f4b5fac5dc405e7d7c0fe64a48d75413d8',
    'car3-preview.png': '7c628e3cd6bd15879166cffafd9c96e3fde4b3caf93b6a360c035657f4b9140b',
    'car4-preview.png': 'cdc487e71277343d3175f4181c58458843d4eaeb6fe19fdf54cfcdc8f6f1ec0c',
    'car5-preview.png': '716b14a274738f865c55fb0b760df3b78e721a53fb3a649dff0ca2306a390c20',
    'car6-preview.png': '6c08478ae06f82d6e1cef9f0d270a34b70805311528cb9a52cac546848e05713',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2)+'\n').encode('utf-8')


def filesystem_path(path):
    """Keep the complete original driver/help tree on Windows long paths."""
    path=Path(path).absolute()
    value=str(path)
    if os.name=='nt' and not value.startswith('\\\\?\\'):
        value=('\\\\?\\UNC\\'+value[2:]) if value.startswith('\\\\') else '\\\\?\\'+value
    return Path(value)


def promote_directory(source,target):
    """A brief Windows scanner handle must not make a sealed build unusable."""
    state.validate_ancestors(source);state.validate_ancestors(target)
    for attempt in range(4):
        if target.exists(): raise ValueError('Voorbereidingsmap bestaat al; overschrijven geweigerd.')
        try:
            source.rename(target)
            return
        except PermissionError as exc:
            if os.name!='nt' or getattr(exc,'winerror',None) not in (5,32,33) or attempt==3:
                raise
            time.sleep(0.05)


def native_folder(root, resolution):
    if resolution not in NATIVE_RESOLUTIONS:
        raise ValueError('Onbekende native deel-II-resolutie.')
    return root/'local/ii-parallel'/('ii-source-native-'+resolution+'-v1')


def native_config(resolution):
    from tools.ii_launcher_graphics import NATIVE_ASSETS, SOURCES
    native_folder(Path(), resolution)  # validate choice
    pins = {'game/DATA/'+name: pin for name,pin in NATIVE_ASSETS.items()}
    pins.update({'game/DATA/SPEL-WIDE.DAT': SOURCES[(resolution,'native')][2],
                 'profiles/widescreen.conf': PROFILE_PINS[resolution]})
    return {'schema':1, 'game':'a2racer2', 'portable_native_source':1,
            'resolution':resolution, 'hud':'native',
            'files':[{'path':name,'sha256':pin} for name,pin in sorted(pins.items())]}


def native_payload(root, resolution):
    """Path-independent metadata, fixed binary/profile/archive pins in code."""
    return _native_payload_at(native_folder(root,resolution),resolution)


def _native_payload_at(base,resolution):
    expected = native_config(resolution)
    if state.read_regular(base/'Frontend.json',65536) != encoded(expected):
        raise ValueError('Portable deel-II-bronregistratie veranderde.')
    payload = {}
    for entry in expected['files']:
        raw = state.read_regular(base/entry['path'],64*1024**2)
        if sha(raw) != entry['sha256']:
            raise ValueError('Portable deel-II-bron veranderde: '+entry['path'])
        payload[entry['path']] = raw
    return payload


def classic_profile(provider_config):
    """Recreate the accepted profile from the already verified provider config."""
    result = wrapper.wrapper_config(provider_config,60)
    for section,key,before,after in (
        (b'General',b'ScalingMode',b'unspecified',b'stretched_ar'),
        (b'General',b'CaptureMouse',b'true',b'false'),
        (b'General',b'CenterAppWindow',b'false',b'true'),
        (b'GeneralExt',b'WindowedAttributes',b'',b'borderless,fullscreensize'),
        (b'GeneralExt',b'SystemHookFlags',b'',b'cursor'),
        (b'DirectXExt',b'PrimarySurfaceBatchedUpdate',b'false',b'true')):
        result = wrapper.replace_setting(result,section,key,before,after)
    if sha(result) != fullscreen.BASE_PROFILE_SHA256:
        raise ValueError('Andere providerconfig; native deel-II-profiel geweigerd.')
    return result


def build_native_binaries(original):
    from tools.ii_launcher_graphics import SOURCES
    baseline,_ = fullscreen.build_race(original)
    values = {'720p':baseline}
    for resolution,display in NATIVE_RESOLUTIONS.items():
        if resolution != '720p':
            values[resolution],_ = resolutions.build_trial(baseline,display)
        if sha(values[resolution]) != SOURCES[(resolution,'native')][2]:
            raise ValueError('Andere uitvoerhash van native deel-II-race.')
    return values


def flat_background(index,image):
    """Generate only seven flat PCXs from the player's archive and metadata."""
    replacements = {}
    for i in range(1,8):
        name = f'back{i}.pcx'
        old = decode_pcx(art.resource(index,image,name))
        palette = bytes((85,115,145))+old.palette[3:]
        replacements[name] = encode_pcx(IndexedImage(old.width,old.height,
            bytes(old.width*old.height),palette))
    return replace_resources(index,image,replacements)


def inspect_source(source):
    """Strict supported-version check and complete, stable, read-only tree hash."""
    from tools.ii_launcher_graphics import NATIVE_ASSETS
    source=filesystem_path(source)
    if ii_playtest_check._source_count(source) != ii_playtest_check.EXPECTED_SOURCE_FILES:
        raise ValueError('De complete ondersteunde Nederlandse deel-II-bron is vereist.')
    for relative,pin in ii_playtest_check.SOURCE_PINS.items():
        if not ii_playtest_check._fingerprint(source/relative,pin)['verified']:
            raise ValueError('Andere/onvolledige deel-II-bron: '+relative)
    for name,pin in NATIVE_ASSETS.items():
        if sha(state.read_regular(source/'DATA'/name,64*1024**2)) != pin:
            raise ValueError('Andere deel-II-resourceversie: '+name)
    music_index,music_image=source/'DATA/MRCS.IND',source/'DATA/MRCS.IMG'
    if music_index.exists() or music_image.exists():
        from tools.ii_menu_music import INDEX_SHA256,IMAGE_SHA256
        for path,pin in ((music_index,INDEX_SHA256),(music_image,IMAGE_SHA256)):
            if sha(state.read_regular(path,64*1024**2))!=pin:
                raise ValueError('Andere/onvolledige originele menumuziek: '+path.name)
    for track in range(7):
        for ext in ('CMP','DMP','OMP','PMP','PTH','RMP'):
            state.read_regular(source/f'DATA/ETAPPE{track}.{ext}',8*1024**2)
    files=[];total=0
    paths=sorted(p for p in source.rglob('*') if p.is_file())
    for path in paths:
        before=path.stat()
        raw=state.read_regular(path,64*1024**2)
        after=path.stat()
        if ((before.st_size,before.st_mtime_ns,before.st_ino) !=
                (after.st_size,after.st_mtime_ns,after.st_ino) or len(raw)!=before.st_size):
            raise ValueError('Deel-II-bron veranderde tijdens inspectie.')
        total+=len(raw)
        if total>1024**3: raise ValueError('Deel-II-bron is te groot.')
        files.append({'path':path.relative_to(source).as_posix(),'size':len(raw),'sha256':sha(raw)})
    if (len(files)!=ii_playtest_check.EXPECTED_SOURCE_FILES or
            ii_playtest_check._source_count(source)!=len(files) or
            sorted(p for p in source.rglob('*') if p.is_file())!=paths):
        raise ValueError('Deel-II-bronboom veranderde tijdens inspectie.')
    return {'game':'a2racer2','source_tree_sha256':sha(encoded(files)),
            'source_files':len(files),'files':len(files),'bytes':total,
            'source_bytes':total,'native_game_executed':False}


def checked_inputs(root,source=None):
    source = source or root/'local/games/a2racer2'
    inspect_source(source)
    own_art = {}
    for name,pin in ART_PINS.items():
        raw = state.read_regular(root/'tools/ii_frontend_art'/name,8*1024**2)
        if sha(raw) != pin or raw[:8] != b'\x89PNG\r\n\x1a\n' or len(raw)<33 or raw[25]!=6:
            raise ValueError('Eigen deel-II-menuafbeelding ontbreekt/veranderde: '+name)
        own_art[name] = raw
    dependencies = trial_manifest.plan_graphics_wrapper(root,'a2racer2',source,'dgvoodoo-windowed')
    provider_config = next(x['data'] for x in dependencies if x['relative_path']=='DATA/dgVoodoo.conf')
    profile = classic_profile(provider_config)
    for name in frontend.SOURCE_FILES.values():
        state.read_regular(root/'tools'/name,1024**2)
    return source,own_art,dependencies,profile


def availability(root):
    """Read-only support for the UI, separating import/build from ready sources."""
    from tools import ii_launcher_graphics as graphics
    result = {'game':'a2racer2','can_prepare':False,'reason':'','native_game_executed':False,
              'families':{resolution:{} for resolution in NATIVE_RESOLUTIONS}}
    try:
        checked_inputs(root)
        result.update(can_prepare=True,reason='Native 720p/1080p/4K lokaal opbouwbaar.')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result['reason'] = str(exc)
    for resolution in NATIVE_RESOLUTIONS:
        for hud in ('native','hd','hd-map'):
            item = {'available':False,'reason':'HD HUD vereist aanvullende lokale HD-bronnen.'}
            if resolution=='720p' and hud!='native':
                item['reason']='HD HUD vereist 1080p of 4K.'
            else:
                try:
                    graphics.source_payload(root,{'race_resolution':resolution,'race_hud':hud,
                        'sky_mode':'flat','race_distance':'60'})
                    item.update(available=True,reason='Resolutie/HUD-bron en egale lucht gecontroleerd.')
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    if hud=='native': item['reason']=str(exc)
            result['families'][resolution][hud]=item
    return result


def _assets(data,assets,own_art):
    assets.mkdir()
    for name,raw in own_art.items(): (assets/name).write_bytes(raw)
    index,image = (data/'RCS.IND').read_bytes(),(data/'RCS.IMG').read_bytes()
    for car,name in enumerate(art.MESH_NAMES):
        mesh=decode_vehicle_mesh(art.resource(index,image,name))
        (assets/f'car{car}.json').write_bytes(encoded(art.preview_mesh(mesh,car)))
    wheel=decode_vehicle_mesh(art.resource(index,image,'WIEL.d3d'))
    (assets/'wheel.json').write_bytes(encoded({'positions':[list(v[:3]) for v in wheel.vertices],
        'uv':[list(v[6:8]) for v in wheel.vertices],'triangles':[list(t[:3]) for t in wheel.triangles]}))
    for i,name in enumerate(('RACER01.PCX','RACER02.PCX','cars01.pcx')):
        (assets/f'texture{i}.png').write_bytes(art.png_from_pcx(art.resource(index,image,name)))
    (assets/'texture3.png').write_bytes(art.isolated_white_skin(art.resource(index,image,'RACER01.PCX')))
    for size in (32,48): (assets/f'arrow{size}.cur').write_bytes(art.cursor_bytes(size))
    music=False
    if (data/'MRCS.IND').is_file() and (data/'MRCS.IMG').is_file():
        from tools.ii_menu_music import extract_tracks
        tracks=extract_tracks(state.read_regular(data/'MRCS.IND',64*1024**2),
                              state.read_regular(data/'MRCS.IMG',64*1024**2))
        (assets/'music').mkdir()
        for name,raw in tracks.items(): (assets.parent/name).write_bytes(raw)
        music=True
    return music


def prepare(root,python_path,run_name=None,*,source=None):
    """First-use native build. An existing registration is never replaced."""
    from tools import ii_launcher_graphics as graphics
    root=root.absolute()
    run_name=run_name or ('ii-frontend-portable-'+uuid.uuid4().hex[:12])
    trial_manifest.validate_slug(run_name)
    if not run_name.startswith('ii-frontend'):
        raise ValueError('Ongeldige portable menu-naam.')
    registration=root/'local/ii-parallel/frontend-current.json'
    state.validate_ancestors(registration)
    if registration.exists():
        existing=frontend.registered_menu(root)
        return {**existing,'prepared':False,'already_ready':True,'native_game_executed':False}
    source,own_art,dependencies,profile=checked_inputs(root,source)
    runtime=Path(python_path)
    state.read_regular(runtime,64*1024**2)
    base=root/'local/ii-parallel'/run_name
    report=root/'reports/a2racer2-next'/run_name
    destinations=[base,report]
    for res in NATIVE_RESOLUTIONS:
        folder=native_folder(root,res)
        state.validate_ancestors(folder)
        if folder.exists(): native_payload(root,res)  # reuse only complete pinned sources
    for path in destinations:
        state.validate_ancestors(path)
        if path.exists(): raise ValueError('Portable voorbereiding bestaat al; overschrijven geweigerd.')
    # Precompute pinned outputs before creating any copies.
    binaries=build_native_binaries(state.read_regular(source/'DATA/SPEL.DAT',1024**2))
    profiles={'720p':fullscreen.race_profile(profile)}
    for res,display in NATIVE_RESOLUTIONS.items():
        if res!='720p': profiles[res]=resolutions.trial_profile(profiles['720p'],display)
        if sha(profiles[res])!=PROFILE_PINS[res]: raise ValueError('Andere native wrapperuitvoer.')
    report.mkdir(parents=True)
    before=wrapper.stable_manifest(source,report)
    stage=base.parent/('.ii-native-build-'+uuid.uuid4().hex)
    stage.mkdir(parents=True)
    try:
        shutil.copytree(filesystem_path(source),filesystem_path(stage/'game'))
        copied=wrapper.stable_manifest(filesystem_path(stage/'game'),report)
        if any(trial_manifest.manifest_diff(before,copied).values()):
            raise ValueError('Deel-II-kopie verschilt van de bron.')
        data=stage/'game/DATA'
        trial_manifest.apply_graphics_wrapper(stage/'game',dependencies)
        (stage/'profiles').mkdir()
        (stage/'profiles/classic.conf').write_bytes(profile)
        (stage/'profiles/widescreen.conf').write_bytes(profiles['720p'])
        (data/'dgVoodoo.conf').write_bytes(profiles['720p'])
        music=_assets(data,stage/'assets',own_art)
        for target,original in frontend.SOURCE_FILES.items():
            (stage/target).write_bytes(state.read_regular(root/'tools'/original,1024**2))
        initial=state.initial_state()
        state.save_state(stage,initial)
        flat_index,flat_image=flat_background((data/'RCS.IND').read_bytes(),(data/'RCS.IMG').read_bytes())
        options={'race_resolution':'720p','race_hud':'native','sky_mode':'flat','race_distance':'60'}
        wide=graphics.compose_world(binaries['720p'],options)
        if sha(wide)!=state.FLAT_SKY60_SHA256: raise ValueError('Andere aanbevolen race-uitvoer.')
        (data/'SPEL-WIDE.DAT').write_bytes(wide)
        (data/'RCS.IND').write_bytes(flat_index);(data/'RCS.IMG').write_bytes(flat_image)
        for name,changes in (
            ('GAME.INI',{('OPTIONS','visiblechunks'):60,('GFX OPTIONS','clouds'):0}),
            ('RASER.INI',{('PROGRAM','RESOLUTION'):3,('MOVIES','ON'):0,('HELPDESK','DEBUGON'):0})):
            (data/name).write_bytes(state.replace_ini((data/name).read_bytes(),changes))
        paths={p.relative_to(stage).as_posix() for p in (stage/'assets').rglob('*') if p.is_file()}
        paths |= set(frontend.SOURCE_FILES) | frontend.RACE_DISPLAY_FILES | {
            'game/DATA/SPEL.DAT','game/DATA/DDraw.dll','game/DATA/D3DImm.dll',
            'game/DATA/GARAGE.INI','game/DATA/RCS.IND','game/DATA/RCS.IMG'}
        config={'schema':1,'game':'a2racer2','menu_revision':37,'python':str(runtime),
            'native_menu_used':False,'race_binary_original':True,'race_fps':60,
            'race_display_version':1,'wide_race_variant':'flat-sky60',
            'preview_detail_revision':'20261013','fleet_preview_revision':'20261013',
            'background_rgb':[85,115,145],'portable_native_builder':1,
            'runtime_tested':False,'game_path':str(base/'game'),'report_path':str(report),
            'files':[{'path':name,'sha256':sha(state.read_regular(stage/name,64*1024**2))}
                     for name in sorted(paths)]}
        if music: config['menu_music_revision']='20261013'
        (stage/'Frontend.json').write_bytes(encoded(config))
        after=wrapper.stable_manifest(source,report)
        if any(trial_manifest.manifest_diff(before,after).values()):
            raise ValueError('De originele deel-II-bron veranderde tijdens kopiëren.')
        # Each source contains only the six pinned files; no machine-specific paths.
        source_stage=stage/'native-sources'
        source_stage.mkdir()
        for res in NATIVE_RESOLUTIONS:
            folder=native_folder(root,res)
            if folder.exists():
                native_payload(root,res)
                continue
            candidate=source_stage/res
            (candidate/'game/DATA').mkdir(parents=True)
            (candidate/'profiles').mkdir()
            for name in graphics.NATIVE_ASSETS:
                (candidate/'game/DATA'/name).write_bytes(state.read_regular(source/'DATA'/name,64*1024**2))
            (candidate/'game/DATA/SPEL-WIDE.DAT').write_bytes(binaries[res])
            (candidate/'profiles/widescreen.conf').write_bytes(profiles[res])
            (candidate/'Frontend.json').write_bytes(encoded(native_config(res)))
            _native_payload_at(candidate,res)
            promote_directory(candidate,folder)
            native_payload(root,res)
        source_stage.rmdir()
        promote_directory(stage,base)
        raw=encoded({'schema':1,'run_name':run_name,'frontend_sha256':sha(encoded(config))})
        with registration.open('xb') as stream: stream.write(raw)
        try:
            frontend.registered_menu(root)
        except Exception:
            # Remove only our exact new pointer, leaving copies/reports for diagnosis.
            if registration.read_bytes()==raw: registration.unlink()
            raise
        result={'base':str(base),'report_path':str(report),'prepared':True,
            'native_resolutions':list(NATIVE_RESOLUTIONS),'hd_sources_built':False,
            'source_unchanged':True,'disc_image_used':False,'native_game_executed':False}
        (report/'portable-native-prepared.json').write_bytes(encoded(result))
        return result
    finally:
        if stage.exists():
            state.validate_ancestors(stage)
            if stage.resolve().parent!=base.parent.resolve() or not stage.name.startswith('.ii-native-build-'):
                raise ValueError('Onverwachte voorbereidingsmap; opruimen geweigerd.')
            shutil.rmtree(filesystem_path(stage))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','prepare'))
    parser.add_argument('--python',default=sys.executable)
    args=parser.parse_args()
    try:
        print(json.dumps(availability(ROOT) if args.action=='check' else prepare(ROOT,args.python)))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())
