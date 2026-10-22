"""Build the restored native II menu from the player's verified source.

Only a separate local copy is modified. Never execute game code here.
"""
from __future__ import annotations
from pathlib import Path
import shutil
import uuid
from tools import ii_frontend_state as state, ii_portable_prepare as portable
from tools import ii_menu_cursor_edge_fix as cursor, ii_next_wrapper_probe as wrapper
from tools import trial_manifest

REVISION = 'a3-v1'
MENU_PROFILE_SHA256 = 'f88c9576a6d26f8b49af19b42ba1d60bf44595650aeefbf179c04f64a9401af6'


def menu_profile(provider: bytes) -> bytes:
    config = wrapper.wrapper_config(provider, 0)
    for section, key, before, after in (
        (b'General', b'OutputAPI', b'd3d11_fl11_0', b'd3d11_fl11_0'),
        (b'General', b'FullScreenMode', b'false', b'false'),
        (b'General', b'ScalingMode', b'unspecified', b'unspecified'),
        (b'General', b'CaptureMouse', b'true', b'false'),
        (b'General', b'CenterAppWindow', b'false', b'true'),
        (b'GeneralExt', b'PresentationModel', b'auto', b'discard'),
        (b'GeneralExt', b'FreeMouse', b'false', b'true'),
        (b'GeneralExt', b'CursorScaleFactor', b'0', b'0'),
        (b'GeneralExt', b'WindowedAttributes', b'', b''),
        (b'GeneralExt', b'SystemHookFlags', b'', b''),
        (b'DirectX', b'Resolution', b'unforced', b'unforced'),
        (b'DirectX', b'AppControlledScreenMode', b'false', b'false'),
        (b'DirectX', b'DisableAltEnterToToggleScreenMode', b'true', b'true'),
        (b'DirectXExt', b'PrimarySurfaceBatchedUpdate', b'false', b'false'),
    ):
        config = wrapper.replace_setting(config, section, key, before, after)
    if portable.sha(config) != MENU_PROFILE_SHA256:
        raise ValueError('Andere wrapperconfiguratie; oorspronkelijke menuvoorbereiding geweigerd.')
    return config


def race_profile(menu: bytes) -> bytes:
    config = wrapper.replace_setting(menu, b'GeneralExt', b'FPSLimit', b'0', b'60')
    return wrapper.replace_setting(config, b'DirectXExt', b'PrimarySurfaceBatchedUpdate', b'false', b'true')


def prepare(root: Path, *, source: Path | None = None) -> dict:
    from tools.ii_original_launcher import registered_menu
    root = root.absolute()
    registration = root/'local/ii-parallel/original-current.json'
    state.validate_ancestors(registration)
    if registration.exists():
        return {**registered_menu(root), 'prepared': False, 'native_game_executed': False}
    source = source or root/'local/games/a2racer2'
    original = portable.inspect_source(source)
    dependencies = trial_manifest.plan_graphics_wrapper(root, 'a2racer2', source, 'dgvoodoo-windowed')
    provider = next(item['data'] for item in dependencies if item['relative_path'] == 'DATA/dgVoodoo.conf')
    menu = menu_profile(provider)
    profiles = {'menu': menu, 'race': race_profile(menu)}
    patched, _ = cursor.patch_menu_cursor_edges(state.read_regular(source/'DATA/MENU.DAT', 1024**2))
    run_name = 'ii-original-'+REVISION+'-'+uuid.uuid4().hex[:12]
    base = registration.parent/run_name
    stage = registration.parent/('.ii-original-build-'+uuid.uuid4().hex)
    state.validate_ancestors(stage)
    stage.mkdir(parents=True)
    try:
        shutil.copytree(portable.filesystem_path(source), portable.filesystem_path(stage/'game'))
        if portable.inspect_source(stage/'game') != original:
            raise ValueError('Oorspronkelijke menukopie verschilt van de bron.')
        trial_manifest.apply_graphics_wrapper(stage/'game', dependencies)
        data = stage/'game/DATA'
        (data/'MENU.DAT').write_bytes(patched)
        (data/'RASER.INI').write_bytes(state.replace_ini((data/'RASER.INI').read_bytes(), {
            ('MOVIES', 'ON'): 0, ('HELPDESK', 'DEBUGON'): 0}))
        (data/'dgVoodoo.conf').write_bytes(menu)
        (stage/'profiles').mkdir()
        for name, raw in profiles.items():
            (stage/'profiles'/(name+'.conf')).write_bytes(raw)
        (stage/'profiles/RASER.INI').write_bytes((data/'RASER.INI').read_bytes())
        files = []
        for path in sorted((stage/'game').rglob('*')):
            if path.is_file():
                raw = state.read_regular(path, 64*1024**2)
                files.append({'path': path.relative_to(stage/'game').as_posix(),
                              'size': len(raw), 'sha256': portable.sha(raw)})
        config = {'schema': 1, 'revision': REVISION, 'game': 'a2racer2',
                  'menu_sha256': cursor.PATCHED_SHA256,
                  'profiles': {name: portable.sha(raw) for name, raw in profiles.items()},
                  'source_tree_sha256': original['source_tree_sha256'], 'files': files}
        raw = portable.encoded(config)
        (stage/'Original.json').write_bytes(raw)
        if portable.inspect_source(source) != original:
            raise ValueError('Gamebron veranderde tijdens voorbereiding.')
        portable.promote_directory(stage, base)
        pointer = portable.encoded({'schema': 1, 'run_name': run_name, 'manifest_sha256': portable.sha(raw)})
        with registration.open('xb') as stream:
            stream.write(pointer)
        try:
            registered_menu(root)
        except Exception:
            if state.read_regular(registration, 4096) == pointer:
                registration.unlink()
            raise
        return {**registered_menu(root), 'prepared': True, 'source_unchanged': True,
                'native_game_executed': False, 'race_runtime_tested': False}
    finally:
        if stage.exists():
            state.validate_ancestors(stage)
            if stage.resolve().parent != registration.parent.resolve() or not stage.name.startswith('.ii-original-build-'):
                raise ValueError('Onverwachte voorbereidingsmap; opruimen geweigerd.')
            shutil.rmtree(portable.filesystem_path(stage))
