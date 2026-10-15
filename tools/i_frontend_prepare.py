"""Prepare an optional HD WPF menu beside a fresh, pinned A2-I race copy."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import i_frontend_state as state
from tools import trial_manifest


def validate_art(root: Path) -> None:
    for name, expected in state.ART.items():
        data = state.read_regular(root / 'local/mods/a2racer1/menu-hd-v1' / name, 4 * 1024 * 1024)
        if (hashlib.sha256(data).hexdigest() != expected or data[:8] != b'\x89PNG\r\n\x1a\n'
                or struct.unpack_from('>II', data, 16) != (1448, 1086)):
            raise ValueError('Onbekend HD-menubeeld: ' + name)


def prepare(root: Path, run_name: str, python: str, choices: dict | None = None, debug: bool = False,
            isolated_state: bool = False) -> dict:
    root = root.absolute()
    trial_manifest.validate_slug(run_name)
    state.safe_path(Path(python))
    if not Path(python).is_absolute() or not Path(python).is_file():
        raise ValueError('Een bestaande Python-runtime is vereist.')
    validate_art(root)
    values = dict(display_profile='hd-1920x1080-camera', camera_profile='camera-16-9',
                  race_fps_limit=20, render_distance_profile='extended-20', native_horizon=0,
                  native_dashboard=1, native_graphics='accelerated-640', texture_profile='original',
                  hud_profile='original', object_distance_profile='original', race_focus_recovery=True)
    if choices:
        if set(choices) - set(values):
            raise ValueError('Onbekende HD-menu-raceoptie.')
        values.update(choices)
    descriptor = trial_manifest.prepare_trial(root, 'a2racer1', run_name, 'launcher', debug,
        graphics_wrapper='hybrid-dgvoodoo', local_game_data=True, omit_native_intro=True,
        any_key_welcome=True, pump_launcher_messages=True, hide_watermark=True,
        keep_native_options=False, **values)
    base = Path(descriptor['trial_path']).parent
    assets = base / 'assets'; assets.mkdir()
    for name in state.ART:
        shutil.copyfile(root / 'local/mods/a2racer1/menu-hd-v1' / name, assets / name)
    for source, destination in (('i_frontend.ps1', 'Menu.ps1'), ('i_frontend_state.py', 'Backend.py'),
                                ('ii_owned_session.ps1', 'OwnedSession.ps1')):
        shutil.copyfile(root / 'tools' / source, base / destination)
    fields = struct.unpack('<10H', state.read_regular(base / 'game/OPTIE.A2R'))
    # OPTIE's native order differs from the INFIO OPTION key order.
    options = dict(zip(('RESOLUTIE', 'VIEW', 'GELUID', 'DISPLAY_MODE', 'HORIZON',
                        'DASHBORD', 'DETAIL', 'CAMERA', 'VMUZIEK', 'VEFFECT'), fields))
    files = []
    paths = [base / name for name in ('Menu.ps1', 'Backend.py', 'OwnedSession.ps1')]
    paths += list(assets.iterdir())
    # Immutable race resources/configs, not native save files or outputs.
    paths += [p for p in (base / 'game').rglob('*') if p.is_file()
              and p.suffix.lower() not in ('.a2r', '.log') and p.name.lower() != 'infio.ini']
    for path in sorted(paths):
        state.safe_path(path)
        files.append({'path': path.relative_to(base).as_posix(),
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    cfg = {'schema': 1, 'game': 'a2racer1', 'python': python, 'native_menu_used': False,
           'state_path': str(base / 'players.json' if isolated_state else root / 'local/launcher/i-hd-menu/players.json'),
           'profile_scope': 'trial' if isolated_state else 'launcher',
           'debug_log_limit_bytes': 64 * 1024**2 if debug else 0,
           'display': values['display_profile'].removeprefix('hd-').removesuffix('-camera'),
           'options': options, 'files': files, 'optional': True, 'default_enabled': False,
           'race_choices': values, 'runtime_verified': False}
    (base / 'Frontend.json').write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    result = {'base': str(base), 'script': str(base / 'Menu.ps1'), 'game': 'a2racer1',
              'native_menu_used': False, 'game_started': False, 'runtime_verified': False,
              'optional': True, 'state_path': cfg['state_path'], 'race_choices': values,
              'source_snapshot': str(Path(descriptor['report_path']) / 'source-before.json')}
    (Path(descriptor['report_path']) / 'hd-menu-prepared.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name', required=True)
    parser.add_argument('--python-path', required=True)
    parser.add_argument('--choices', default='{}')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--isolated-state', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(ROOT, args.run_name, args.python_path, json.loads(args.choices), args.debug,
                                 args.isolated_state)))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
