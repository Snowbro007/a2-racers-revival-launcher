"""Version-bound II launcher choices, immutable composition and isolated copies.

This module never starts a native game. The existing owned frontend runs the
prepared result. Original copies and the accepted recommended registration stay
unchanged; progress is transferred only while the caller holds its menu lock.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools import ii_distance_trial as distance, ii_sky_off_trial as horizon
from tools import ii_sky_layer_trial as sky, ii_frontend_launcher as frontend
from tools.ii_frontend_state import read_regular, replace_ini, load_state, save_state
from tools.ii_frontend_prepare import resource
from tools.ii_hd_hud_assets import replace_resources
from tools.trial_manifest import validate_tree, validate_slug, validate_ancestors
from tools import launcher_cheats

CHOICES = {
    'race_resolution': {'720p': '1280 × 720 · 16:9', '1080p': '1920 × 1080 · 16:9', '4k': '3840 × 2160 · 16:9'},
    'race_hud': {'native': 'Originele HUD', 'hd': 'HD HUD · tekst en kaders', 'hd-map': 'HD HUD + radar en meldingen · untested'},
    'sky_mode': {'original': 'Originele horizon en lucht', 'horizon-off': 'Horizon uit · wolken behouden', 'flat': 'Egale lucht · aanbevolen'},
    'race_distance': {'auto': 'Origineel · automatische afstand', '50': 'Ver vooruit · 50 baanstukken', '60': 'Maximaal · 60 baanstukken · aanbevolen'},
}
DEFAULTS = {'race_resolution': '720p', 'race_hud': 'native', 'sky_mode': 'flat', 'race_distance': '60'}
# Exact previously prepared versions, not filesystem discovery or invented offsets.
SOURCES = {
 ('720p','native'): ('ii-frontend37-20261012','7aacb74d20262ba2f72e58f54737fc8102b2dbd6359ea28250c67345cf45a3a5','1e5cef6499bd001ace3f22ff0a818101fe43bcf80b2ff086f0d912e6f3891016'),
 ('1080p','native'): ('ii-frontend38-1080p-20261013','aa78e6094069e2082142ce4d8c25a0bfa01abf0dc3cbbe40d20662b799fa5d10','d71f20a7ac6f6fa27b0355fe41dfe51be96a25fa87711bc31b6ee7b32590eff1'),
 ('4k','native'): ('ii-frontend39-4k-20261013','409a34052e3ccde1366050ab814a855710c1e76f9b61d5a98f35b8bb8532537f','1c29bf35586ef96865a762df0e59c9d68a7f65a86952963e64d7a736685aa1a8'),
 ('1080p','hd'): ('ii-frontend55-hd-hud-spacing-20261013','49c5d88d718bb68b452b5255f09c2c3ec7b1db9aa88b32d8906149feb9d06403','0f4bfa843409a67eefd7c55a25e42d190680f5bbaca4e0ee44ac2d00602bc579'),
 ('4k','hd'): ('ii-frontend56-hd-hud-spacing-20261013','2b84e9adad7cfcd1519e786a1860995a08c272ff83a6bd065a1d2f0f91f31931','031f8bc4af3f595d2958494abc4c0aacb9f5f4e7acb6c838daae7ce8db311b81'),
 ('1080p','hd-map'): ('ii-frontend57-hud-map-dialog-1080p-20261013','59dea559b7c092ee98ad7c62f4794779371b98120fc638da744533168a217c57','4c3d244c44ca54484d4388165c5bd8c7851ea8aaf756f24437944aa8d178d454'),
 ('4k','hd-map'): ('ii-frontend58-hud-map-dialog-2160p-20261013','35d40e6ef1cdef54d108fd6c598f9b710eed79cf961e34be8b6187213643467a','25262d7b2ecffd7aad57533aa772957d474527bea6c8534cf2f3d9813ee9a532'),
}
NATIVE_ASSETS = {
 'RC.IND': '19f489843c483b3b78bd40f19698f7d7c17b34f6e96bf9eb36b83a4150b414b0',
 'RC.IMG': 'c017c5a950a7cffc8c2718ac2836f93ef5f2482774cd961a373211912b46388a',
 'RCS.IND': '5944312c0a9a643ace4cfaf96266d903461f627701bd2b97d525000053d6594d',
 'RCS.IMG': '825bdace8b55f2abe81275078f307d4cd29391a0bf40c8f4676fb2f400603e38',
}
FLAT_BACKGROUND_NAMES = tuple(f'back{i}.pcx' for i in range(1,8))
SOURCE_CACHE_NAME = 'ii-graphics-sources-v1'

def sha(data): return hashlib.sha256(data).hexdigest()

def merge_flat_background(index, image, flat_index, flat_image):
    """Keep the selected HUD archive; replace only its seven sky resources."""
    replacements = {name:resource(flat_index,flat_image,name) for name in FLAT_BACKGROUND_NAMES}
    return replace_resources(index,image,replacements)

def validate_options(options):
    if not isinstance(options, dict) or set(options) != set(CHOICES):
        raise ValueError('Ontbrekende of onbekende deel-II-beeldopties.')
    for key, values in CHOICES.items():
        if type(options[key]) is not str or options[key] not in values:
            raise ValueError('Onbekende deel-II-keuze: '+key)
    if (options['race_resolution'], options['race_hud']) not in SOURCES:
        raise ValueError('HD HUD vereist 1080p of 4K; kies de originele HUD voor 720p.')
    return deepcopy(options)

def compose_world(source: bytes, options: dict) -> bytes:
    """Compose only audited, nonoverlapping main-code regions on pinned inputs."""
    validate_options(options)
    if type(source) is not bytes or sha(source) != SOURCES[(options['race_resolution'],options['race_hud'])][2]:
        raise ValueError('Andere resolutie/HUD-basis; wereldopties geweigerd.')
    output = bytearray(source)
    # All supported resolutions/HUDs keep these original main-code contexts.
    contexts = [(distance.CONTEXT_OFFSET, distance.CONTEXT),
                (distance.LIMIT_OFFSET, distance.LIMIT_CONTEXT),
                (horizon.CONTEXT_OFFSET, horizon.CONTEXT)]
    for offset, expected in contexts:
        if source[offset:offset+len(expected)] != expected:
            raise ValueError('Andere afstand/clearcontext; combinatie geweigerd.')
    if options['race_distance'] != 'auto':
        output[distance.PATCH_OFFSET] = 0x90
        if options['race_distance'] == '60':
            output[distance.LIMIT_OFFSET+2] = 60
            output[distance.LIMIT_OFFSET+11] = 60
    if options['sky_mode'] != 'original':
        for offset, before, after in horizon.PATCHES:
            if source[offset:offset+len(before)] != before:
                raise ValueError('Andere horizonroute; combinatie geweigerd.')
            output[offset:offset+len(before)] = after
    if options['sky_mode'] == 'flat':
        for offset, before in (sky.CLOUD_CALL, sky.BITMAP_CALL):
            if source[offset:offset+len(before)] != before:
                raise ValueError('Andere luchtlaag; combinatie geweigerd.')
            output[offset:offset+len(before)] = b'\x90'*len(before)
    return bytes(output)

def source_cache_folder(root: Path, options: dict) -> Path:
    """Return the explicit regular-file provider cache; never populate it.

    Each entry uses the exact existing source identifier, Frontend.json and
    payload pins. A present invalid cache is an error, never a fallback hint.
    """
    options = validate_options(options)
    name = SOURCES[(options['race_resolution'], options['race_hud'])][0]
    validate_slug(name)
    folder = root/'local/ii-parallel'/SOURCE_CACHE_NAME/name
    # Check even missing entries: a dangling link or linked ancestor must not
    # be mistaken for an absent cache and silently select another provider.
    validate_ancestors(folder)
    return folder

def source_payload(root, options):
    options = validate_options(options)
    name, config_pin, binary_pin = SOURCES[(options['race_resolution'],options['race_hud'])]
    from tools.ii_portable_prepare import native_folder, native_payload
    cached = source_cache_folder(root, options)
    if cached.exists():
        if not cached.is_dir():
            raise ValueError('Deel-II-broncache is geen gewone map.')
        base = cached
    elif options['race_hud'] == 'native' and native_folder(root,options['race_resolution']).exists():
        payload = native_payload(root,options['race_resolution'])
        base = None
    else:
        base = root/'local/ii-parallel'/name
    if base is not None:
        validate_ancestors(base)
        if (not base.exists() and options['race_hud'] in ('hd','hd-map')
                and (root/'tools/ii_frontend_art/hud-pixels.json').exists()):
            from tools.ii_public_hd_sources import source_payload as public_hd_payload
            payload = public_hd_payload(root, options['race_resolution'], options['race_hud'])
            base = None
    if base is not None:
        # Preserve the original seven local trial contracts, including HD art.
        raw = read_regular(base/'Frontend.json', 65536)
        if sha(raw) != config_pin: raise ValueError('Deel-II-proefregistratie veranderde: '+name)
        config = json.loads(raw)
        entries = {entry['path']: entry['sha256'] for entry in config['files']}
        payload = {}
        for relative in ('game/DATA/SPEL-WIDE.DAT','profiles/widescreen.conf',
                         'game/DATA/RC.IND','game/DATA/RC.IMG','game/DATA/RCS.IND','game/DATA/RCS.IMG'):
            data = read_regular(base/relative, 64*1024**2)
            expected = entries.get(relative, NATIVE_ASSETS.get(Path(relative).name))
            if expected is None or sha(data) != expected:
                raise ValueError('Deel-II-bron veranderde: '+relative)
            payload[relative] = data
    if sha(payload['game/DATA/SPEL-WIDE.DAT']) != binary_pin:
        raise ValueError('Onbekende deel-II-racebinary.')
    payload['game/DATA/SPEL-WIDE.DAT'] = compose_world(payload['game/DATA/SPEL-WIDE.DAT'], options)
    if options['sky_mode'] == 'flat':
        current = Path(frontend.registered_menu(root)['base'])
        config = json.loads(read_regular(current/'Frontend.json', 65536))
        if config.get('wide_race_variant') != 'flat-sky60':
            raise ValueError('De geregistreerde egale-luchtbron ontbreekt.')
        flat_index = read_regular(current/'game/DATA/RCS.IND',64*1024**2)
        flat_image = read_regular(current/'game/DATA/RCS.IMG',64*1024**2)
        index,image = merge_flat_background(payload['game/DATA/RCS.IND'],
            payload['game/DATA/RCS.IMG'],flat_index,flat_image)
        payload['game/DATA/RCS.IND'],payload['game/DATA/RCS.IMG'] = index,image
    return payload

def check_options(root, options):
    source_payload(root, options)
    return {'available': True, 'reason': 'Resolutie, HUD, lucht en afstand gecontroleerd; nieuwe combinaties nog niet speelgetest.'}

def target_folder(root, run_name):
    validate_slug(run_name)
    if not run_name.startswith('launcher-'): raise ValueError('Ongeldige launcherstart.')
    target = root/'local/ii-parallel'/('ii-'+run_name)
    validate_ancestors(target)
    return target

def prepare(root, run_name, options, mode='widescreen', *, developer_mode=False, vector_car=False,
            cheats=None):
    cheats = launcher_cheats.validate('a2racer2', launcher_cheats.DEFAULTS['a2racer2'] if cheats is None else cheats)
    cheat_session = launcher_cheats.active('a2racer2', cheats)
    if type(developer_mode) is not bool:
        raise ValueError('Ongeldige ontwikkelaarsmodus.')
    if type(vector_car) is not bool:
        raise ValueError('Ongeldige Vector-keuze.')
    if vector_car:
        from tools.ii_vector_car import checked_art
        checked_art(root)
    if mode not in ('classic','widescreen'): raise ValueError('Onbekende raceweergave.')
    options = validate_options(options)
    if mode == 'classic':
        options = {'race_resolution':'720p','race_hud':'native','sky_mode':'original','race_distance':'auto'}
    current = Path(frontend.registered_menu(root)['base'])
    source_config = json.loads(read_regular(current/'Frontend.json',65536))
    if ((current/launcher_cheats.SESSION_MARKER).exists()
            or source_config.get('launcher_cheats') is not None):
        raise ValueError('Een cheatsessie kan niet als normale bronregistratie worden gebruikt.')
    state = load_state(current)
    if state['pending']: raise ValueError('Sluit de eerdere race eerst normaal af.')
    if cheat_session:
        state = launcher_cheats.prepare_state('a2racer2', state, cheats)
    payload = source_payload(root, options)
    minimap_change = None
    if options['race_resolution'] == '4k' and options['race_hud'] == 'hd-map':
        from tools.ii_minimap_size import patch as enlarge_minimap
        payload['game/DATA/SPEL-WIDE.DAT'], minimap_change = enlarge_minimap(payload['game/DATA/SPEL-WIDE.DAT'])
    target = target_folder(root, run_name)
    from tools.ii_portable_prepare import filesystem_path
    validate_tree(filesystem_path(current))
    if target.exists(): raise ValueError('Deze beeldsessie is al voorbereid; start opnieuw via de launcher.')
    # A source lock is held by Invoke-IIFrontend throughout preparation/run/sync.
    shutil.copytree(filesystem_path(current), filesystem_path(target),
                    ignore=shutil.ignore_patterns('menu.lock', 'menu-state.previous.json'))
    report = root/'reports/a2racer2-next'/target.name
    validate_ancestors(report)
    report.mkdir(parents=True, exist_ok=False)
    for relative, data in payload.items(): (target/relative).write_bytes(data)
    config = json.loads(read_regular(current/'Frontend.json',65536))
    config.update(game_path=str(target/'game'), report_path=str(report),
                  wide_race_variant='standard', resolution_trial={'720p':[1280,720],'1080p':[1920,1080],'4k':[3840,2160]}[options['race_resolution']],
                  distance_diagnostics=True, visiblechunks_trial=60 if options['race_distance']=='60' else 50,
                  launcher_graphics=options, launcher_graphics_runtime_tested=False,
                  developer_mode=developer_mode)
    if minimap_change is not None: config['minimap_size'] = minimap_change
    backend = read_regular(root/'tools/ii_frontend_state.py',1024**2)
    old = frontend.RACE_DISPLAYS['widescreen']['sha256'].encode()
    if backend.count(old) != 1: raise ValueError('Andere backend-layout.')
    backend = backend.replace(old, sha(payload['game/DATA/SPEL-WIDE.DAT']).encode())
    old_profile = frontend.RACE_DISPLAYS['widescreen']['profile_sha256'].encode()
    if backend.count(old_profile) != 1: raise ValueError('Andere backend-profielpin.')
    backend = backend.replace(old_profile, sha(payload['profiles/widescreen.conf']).encode())
    (target/'Backend.py').write_bytes(backend)
    # Correct menu/log descriptions without changing the owned race lifecycle.
    menu = read_regular(root/'tools/ii_frontend.ps1',1024**2)
    width,height = config['resolution_trial']
    menu = menu.replace('Schermvullend 16:9 (1280 × 720)'.encode(), f'Schermvullend 16:9 ({width} × {height})'.encode())
    menu = menu.replace(b'@(1280,720)',f'@({width},{height})'.encode())
    if options['race_hud'] != 'native':
        menu = menu.replace(",'Klassiek 4:3 (640 × 480)'".encode(), b'')
    (target/'Menu.ps1').write_bytes(menu)
    ini = read_regular(target/'game/DATA/GAME.INI',128*1024)
    ini = replace_ini(ini,{('OPTIONS','visiblechunks'):30 if options['race_distance']=='auto' else int(options['race_distance']),
                         ('GFX OPTIONS','clouds'):0 if options['sky_mode']=='flat' else 1})
    (target/'game/DATA/GAME.INI').write_bytes(ini)
    # The race backend preserves HELPDESK/TWEAK_MODE across starts and returns.
    # Always write both on and off in this independent session copy.
    raser = read_regular(target/'game/DATA/RASER.INI',128*1024)
    raser = replace_ini(raser,{('HELPDESK','TWEAK_MODE'):int(developer_mode)})
    (target/'game/DATA/RASER.INI').write_bytes(raser)
    extra_paths = set()
    config.pop('launcher_cheats', None)
    if cheat_session:
        marker = target/launcher_cheats.SESSION_MARKER
        if marker.exists():
            raise ValueError('De normale registratie bevat al een cheatsessie; starten geweigerd.')
        marker.write_text(json.dumps(launcher_cheats.session_metadata('a2racer2', cheats),indent=2),encoding='utf-8')
        extra_paths.add(launcher_cheats.SESSION_MARKER)
        config['launcher_cheats'] = cheats
    config.pop('vector_vehicle', None)
    if vector_car:
        from tools.ii_vector_car import prepare as prepare_vector
        config['vector_vehicle'], vector_paths = prepare_vector(root, target)
        extra_paths.update(vector_paths)
    paths = {entry['path'] for entry in config['files']} | set(payload) | {'game/DATA/RASER.INI'} | extra_paths
    if vector_car:
        # Active RCS files switch between sealed normal/bonus snapshots per race.
        # Pin both immutable snapshots, rather than rejecting a valid next open.
        paths.difference_update({'game/DATA/RCS.IND','game/DATA/RCS.IMG'})
    config['files'] = [{'path':name,'sha256':sha(read_regular(target/name,64*1024**2))} for name in sorted(paths)]
    (target/'Frontend.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    state['settings']['race_display'] = mode
    save_state(target,state)
    result = {'base':str(target),'canonical_base':str(current),'canonical_run':current.name,'report_path':str(report),
              'options':options,'developer_mode':developer_mode,'vector_car':vector_car,'runtime_tested':False,'disc_image_used':False}
    result['cheat_session'] = cheat_session
    (report/'launcher-graphics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

def sync_progress(root, run_name, canonical_run):
    target = target_folder(root, run_name)
    # This guard is independent of the current launcher settings. Turning cheats
    # off later must never turn an old cheat session into ordinary progression.
    marker = target/launcher_cheats.SESSION_MARKER
    config = json.loads(read_regular(target/'Frontend.json',65536))
    config_cheats = config.get('launcher_cheats')
    if marker.exists() or config_cheats is not None:
        metadata = launcher_cheats.validate_session_metadata(
            json.loads(read_regular(marker,16384)), 'a2racer2')
        if config_cheats is not None and launcher_cheats.validate('a2racer2',config_cheats) != metadata['options']:
            raise ValueError('Cheatsessieregistratie veranderde; normale voortgang niet geschreven.')
        return {'progress_saved':False,'cheat_session':True,
                'reason':'Cheatvoortgang blijft uitsluitend in de aparte sessiekopie.'}
    state = load_state(target)
    if state['pending']: raise ValueError('Onderbroken race; voortgang blijft in de sessiekopie behouden.')
    current = Path(frontend.registered_menu(root)['base'])
    if current.name != canonical_run:
        raise ValueError('De aanbevolen registratie veranderde; voortgang blijft in de sessiekopie behouden.')
    save_state(current,state)
    return {'progress_saved':True}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','sync','check'))
    parser.add_argument('--run-name')
    parser.add_argument('--canonical-run')
    parser.add_argument('--mode',choices=('classic','widescreen'),default='widescreen')
    parser.add_argument('--developer-mode',type=int,choices=(0,1),default=0)
    parser.add_argument('--vector-car',type=int,choices=(0,1),default=0)
    parser.add_argument('--cheats',default=None)
    for key, choices in CHOICES.items(): parser.add_argument('--'+key.replace('_','-'),choices=tuple(choices),default=DEFAULTS[key])
    args=parser.parse_args()
    options={key:getattr(args,key) for key in CHOICES}
    try:
        cheats = (launcher_cheats.validate('a2racer2',json.loads(args.cheats))
                  if args.cheats is not None else None)
        result = check_options(ROOT,options) if args.action=='check' else sync_progress(ROOT,args.run_name,args.canonical_run) if args.action=='sync' else prepare(ROOT,args.run_name,options,args.mode,developer_mode=bool(args.developer_mode),vector_car=bool(args.vector_car),cheats=cheats)
        print(json.dumps(result));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1

if __name__=='__main__': raise SystemExit(main())
