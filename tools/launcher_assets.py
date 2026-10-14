"""Pinned release artwork only; never include generation inputs or reports."""
from __future__ import annotations
import hashlib
from pathlib import Path
from tools.trial_manifest import validate_ancestors


def asset_catalog() -> dict[str, str]:
    from tools.resource_archive import texture_asset_specs
    from tools.sprite_archive import sprite_asset_specs
    from tools import hud_hd_fix, hud_fine_assets, hud_refined_cockpit_fix
    from tools.hud_refined_cockpit_assets import ASSET_ROOT_V2
    from tools.i_frontend_state import ART
    assets = {}
    for spec in (*texture_asset_specs('hd-expanded-v1'), *sprite_asset_specs('hd-expanded-v1')):
        assets[spec['path']] = spec['sha256']
    for spec in hud_hd_fix.ASSETS:
        assets[spec.path] = spec.sha256
    for name, pin in hud_fine_assets.ASSET_PINS.items():
        assets[f'{hud_fine_assets.ASSET_ROOT}/{name}.rgb565'] = pin
    for name, pin in hud_refined_cockpit_fix.ASSET_PINS_V2.items():
        assets[f'{ASSET_ROOT_V2}/{name}.rgb565'] = pin
    for name, pin in ART.items():
        assets[f'local/mods/a2racer1/menu-hd-v1/{name}'] = pin
    return dict(sorted(assets.items()))


def package_path(target: str) -> str:
    if target not in asset_catalog():
        raise ValueError('Onbekend release-artbestand.')
    return 'assets/' + target.removeprefix('local/mods/')


def checked_asset(path: Path, pin: str) -> bytes:
    validate_ancestors(path)
    if not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024**2:
        raise ValueError('Release-art ontbreekt of is te groot: ' + path.name)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin:
        raise ValueError('Release-art wijkt af: ' + path.name)
    return data


def install_assets(root: Path) -> int:
    """Validate the entire set before writes; never overwrite existing data."""
    checked = []
    for target, pin in asset_catalog().items():
        source = root / package_path(target)
        data = checked_asset(source, pin)
        destination = root / target
        validate_ancestors(destination)
        if destination.exists():
            checked_asset(destination, pin)
        else:
            checked.append((destination, data))
    for destination, data in checked:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(data)
    return len(checked)
