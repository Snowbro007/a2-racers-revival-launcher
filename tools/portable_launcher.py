"""Build and audit a clean offline launcher download, without development data."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import portable_test as kit
from tools.launcher_assets import asset_catalog, package_path, checked_asset, install_assets
from tools.trial_manifest import validate_ancestors

PREFIX = 'A2-Racers-Revival/'
MAX_PACKAGE_BYTES = 1024 * 1024**2
PUBLIC_FILES = ('LICENSE', 'VERSION.txt', 'tools/prepare_public_release.py', 'docs/public-readme.md',
                'tools/check_public_docs.py',
                'docs/release-third-party-notices.md', 'docs/public-release.json',
                'docs/public-gitignore.txt', 'docs/public-release-notes.md',
                'tools/build_windows_release.py',
                'tools/windows/Branding.cs', 'tools/windows/NativeCommon.cs',
                'tools/windows/Launcher.cs',
                'tools/windows/msi/build_msi.py', 'tools/windows/msi/write_database.ps1',
                'tools/windows/msi/cab_codec.py', 'tools/windows/msi/test_msi_builder.py',
                'tools/windows/msi/README.md', 'tools/windows/msi/.gitignore',
                'tools/windows/msi/audit_msi.ps1')
EXTRA_FILES = (
    'tools/ii_frontend_art/hud-pixels.json',
    'tools/ii_frontend_art/vector-paint.json', 'tools/ii_frontend_art/vector-preview.png',
    'Controleren.cmd',
    'tools/launcher_art/a2-revival.ico',
    'tools/portable_launcher.py', 'tools/launcher_assets.py', 'tools/launcher_updates.py',
    'tools/Start-IHDMenu.ps1', 'tools/i_frontend.ps1',
    'tools/i_frontend_state.py', 'tools/i_frontend_prepare.py',
    'tools/ii_frontend_prepare.py', 'tools/ii_frontend_fullscreen.py',
)


def app_files(root: Path) -> list[str]:
    """Follow literal Python imports and script references from fixed entrypoints."""
    # The private legacy test kit still supports its own shortcut script. The
    # modern launcher uses Launcher.cmd or the MSI's native shortcuts instead.
    names = {name for name in kit.APP_FILES
             if not name.startswith('docs/') and name != 'Maak-snelkoppeling.ps1'}
    names.update(EXTRA_FILES)
    pending = list(names)
    while pending:
        name = pending.pop()
        path = root / name
        validate_ancestors(path)
        if not path.is_file():
            raise ValueError('Launcheronderdeel ontbreekt: ' + name)
        dependencies = set()
        if path.suffix == '.py':
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module in ('tools', 'a2revival'):
                        dependencies.update(node.module + '/' + alias.name + '.py' for alias in node.names)
                    elif node.module.startswith(('tools.', 'a2revival.')):
                        dependencies.add(node.module.replace('.', '/') + '.py')
                elif isinstance(node, ast.Import):
                    dependencies.update(alias.name.replace('.', '/') + '.py' for alias in node.names
                                        if alias.name.startswith(('tools.', 'a2revival.')))
        # Runtime script paths also appear in Python preparation code.
        if path.suffix in ('.ps1', '.py'):
            dependencies.update('tools/' + value for value in
                re.findall(r"['\"]([A-Za-z0-9_-]+\.(?:ps1|xaml))['\"]", path.read_text(encoding='utf-8-sig'))
                if (root / 'tools' / value).is_file())
        for dependency in dependencies - names:
            names.add(dependency);pending.append(dependency)
    return sorted(names)


def records(root: Path, game_archive: Path | None = None, *, public: bool = False) -> list[tuple[str, Path, str | None]]:
    if public and game_archive is not None:
        raise ValueError('Een openbare release mag geen gamearchief bevatten.')
    app_names = app_files(root)
    inputs = [(name, root / name, None) for name in app_names]
    if 'tools/ii_portable_prepare.py' in app_names:
        from tools.ii_portable_prepare import ART_PINS
        inputs += [('tools/ii_frontend_art/'+name, root/'tools/ii_frontend_art'/name, pin) for name,pin in ART_PINS.items()]
    inputs.append(('LEESMIJ.txt', root / ('docs/public-readme.md' if public else 'docs/portable-launcher.md'), None))
    if public:
        inputs += [(name, root / name, None) for name in PUBLIC_FILES if name not in {row[0] for row in inputs}]
        inputs += [('public-release.json', root / 'docs/public-release.json', None),
                   ('README.md', root / 'docs/public-readme.md', None),
                   ('.gitignore', root / 'docs/public-gitignore.txt', None),
                   ('RELEASE-NOTES.md', root / 'docs/public-release-notes.md', None),
                   ('THIRD-PARTY-NOTICES.md', root / 'docs/release-third-party-notices.md', None)]
    else:
        for name, pin, source in kit.PAYLOADS.values():
            inputs.append(('payload/' + name, root / source, pin))
        inputs += [('NOTICES/cnc-ddraw-MIT.txt', root / 'local/components/cnc-ddraw/v7.0.0.0/LICENSE-v7.0.0.0.txt', None),
                   ('NOTICES/dgVoodoo-readme.html', root / 'local/components/dgvoodoo/v2.87.5/author-readme-general.html', None)]
    inputs += [(package_path(target), root / target if (root / target).exists() else root / package_path(target), pin)
               for target, pin in asset_catalog().items()]
    if game_archive is not None:
        inputs.append((kit.GAME_ARCHIVE_NAME, game_archive, kit.GAME_ARCHIVE_SHA256))
    return sorted(inputs)


def file_record(name: str, path: Path, pin: str | None) -> dict:
    validate_ancestors(path)
    limit = kit.MAX_GAME_ARCHIVE if name == kit.GAME_ARCHIVE_NAME else kit.MAX_ZIP
    digest = kit.file_hash(path, limit)
    if pin and digest != pin:
        raise ValueError('Pakketbron heeft een onbekende hash: ' + name)
    return {'path': name, 'size': path.stat().st_size, 'sha256': digest}


def build(root: Path, destination: Path, game_archive: Path | None = None, *, public: bool = False) -> dict:
    validate_ancestors(destination)
    checksum = destination.with_suffix(destination.suffix + '.sha256')
    validate_ancestors(checksum)
    if destination.exists() or checksum.exists():
        raise ValueError('Pakket bestaat al; kies een nieuwe bestandsnaam.')
    inputs = records(root, game_archive, public=public)
    manifest = {'schema': 1, 'kind': 'portable-launcher', 'game_archive_included': game_archive is not None,
                'audience': 'launcher-public' if public else 'personal-private' if game_archive else 'launcher-only',
                'gameplay_verified_on_second_pc': False, 'files': [file_record(*item) for item in inputs]}
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            created = True
            for name, path, _ in inputs:
                archive.write(path, PREFIX + name, compress_type=zipfile.ZIP_STORED
                              if name.startswith('payload/') or name == kit.GAME_ARCHIVE_NAME else zipfile.ZIP_DEFLATED)
            archive.writestr(PREFIX + 'release-manifest.json', json.dumps(manifest, indent=2).encode('ascii'))
        audit(destination, root)
        # Recheck input identities after packaging; preserve the supplied source.
        if [file_record(*item) for item in inputs] != manifest['files']:
            raise ValueError('Bronbestanden veranderden tijdens verpakken.')
    except Exception:
        # Remove only the newly-created incomplete package, never an existing ZIP.
        if created and destination.is_file():
            destination.unlink()
        raise
    digest = kit.file_hash(destination, MAX_PACKAGE_BYTES)
    with checksum.open('x', encoding='ascii') as stream:
        stream.write(digest + '  ' + destination.name + '\n')
    return {'archive': str(destination), 'sha256': digest, 'files_checked': len(manifest['files']) + 1,
            'game_archive_included': game_archive is not None, 'published': False}


def validate_manifest(value: dict, expected_names: set[str]) -> dict[str, dict]:
    if (not isinstance(value, dict) or set(value) != {'schema', 'kind', 'game_archive_included', 'audience', 'gameplay_verified_on_second_pc', 'files'}
            or type(value['schema']) is not int or value['schema'] != 1 or value['kind'] != 'portable-launcher'
            or type(value['game_archive_included']) is not bool or value['gameplay_verified_on_second_pc'] is not False
            or value['audience'] not in (('personal-private',) if value['game_archive_included'] else ('launcher-only','launcher-public'))
            or not isinstance(value['files'], list)):
        raise ValueError('Onbekend release-manifest.')
    rows = {}
    for row in value['files']:
        if (not isinstance(row, dict) or set(row) != {'path', 'size', 'sha256'} or not isinstance(row['path'], str)
                or type(row['size']) is not int or not 0 < row['size'] <= MAX_PACKAGE_BYTES
                or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Ongeldige release-bestandsregel.')
        name = row['path'];path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                or name in rows or name not in expected_names):
            raise ValueError('Onverwacht bestand in release: ' + name)
        rows[name] = row
    if set(rows) != expected_names:
        raise ValueError('Release mist vereiste launcherbestanden.')
    pins = {} if value['audience'] == 'launcher-public' else {'payload/' + item[0]: item[1] for item in kit.PAYLOADS.values()}
    pins.update({package_path(target): pin for target, pin in asset_catalog().items()})
    if 'tools/ii_portable_prepare.py' in expected_names:
        from tools.ii_portable_prepare import ART_PINS
        pins.update({'tools/ii_frontend_art/'+name:pin for name,pin in ART_PINS.items()})
    if value['game_archive_included']:
        pins[kit.GAME_ARCHIVE_NAME] = kit.GAME_ARCHIVE_SHA256
    if any(rows[name]['sha256'] != pin for name, pin in pins.items()):
        raise ValueError('Release mist de vaste component-/art-/gamehashes.')
    return rows


def audit(path: Path, source_root: Path = ROOT) -> int:
    validate_ancestors(path)
    with zipfile.ZipFile(path) as archive:
        info = archive.infolist();names = [entry.filename for entry in info]
        if (len(names) > 2000 or len(set(name.casefold() for name in names)) != len(names)
                or sum(entry.file_size for entry in info) > MAX_PACKAGE_BYTES
                or any(entry.is_dir() or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16) for entry in info)):
            raise ValueError('Onveilige of te grote release-ZIP.')
        manifest_info = archive.getinfo(PREFIX + 'release-manifest.json')
        if manifest_info.file_size > 256 * 1024:
            raise ValueError('Release-manifest is te groot.')
        manifest = json.loads(archive.read(manifest_info))
        public = manifest.get('audience') == 'launcher-public'
        expected = {name for name, _, _ in records(source_root, public=public)}
        if manifest.get('game_archive_included') is True:
            expected.add(kit.GAME_ARCHIVE_NAME)
        rows = validate_manifest(manifest, expected)
        intended = {name: file_record(name, source, pin) for name, source, pin in records(source_root, public=public)}
        if any(rows[name] != row for name, row in intended.items()):
            raise ValueError('Verpakte launcher wijkt af van de bedoelde buildbronnen.')
        if set(names) != {PREFIX + name for name in rows} | {PREFIX + 'release-manifest.json'}:
            raise ValueError('Onverwachte daadwerkelijke release-inhoud.')
        for name, row in rows.items():
            entry = archive.getinfo(PREFIX + name)
            with archive.open(entry) as stream:
                digest = kit.stream_hash(stream)
            if entry.file_size != row['size'] or digest != row['sha256']:
                raise ValueError('Release-inhoud wijkt af: ' + name)
        return len(names)


def bundled_import_needed(root: Path) -> bool:
    """Only the explicit personal complete release may automatically import."""
    manifest_path = root / 'release-manifest.json'
    validate_ancestors(manifest_path)
    if not manifest_path.is_file() or manifest_path.stat().st_size > 256 * 1024:
        raise ValueError('Release-manifest ontbreekt of is te groot.')
    manifest = json.loads(manifest_path.read_text(encoding='ascii'))
    expected = {name for name, _, _ in records(root, public=manifest.get('audience') == 'launcher-public')}
    if manifest.get('game_archive_included') is True:
        expected.add(kit.GAME_ARCHIVE_NAME)
    validate_manifest(manifest, expected)
    return manifest['game_archive_included'] and not (root / 'local/games/a2racer1').exists()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('build', 'audit', 'setup-assets', 'initialize'))
    p.add_argument('--output', type=Path)
    p.add_argument('--archive', type=Path)
    p.add_argument('--include-game-archive', type=Path)
    p.add_argument('--public', action='store_true')
    args = p.parse_args()
    try:
        if args.action == 'build' and args.output:
            result = build(ROOT, args.output, args.include_game_archive, public=args.public)
        elif args.action == 'audit' and args.archive:
            result = {'files_checked': audit(args.archive)}
        elif args.action == 'setup-assets':
            result = {'assets_installed': install_assets(ROOT), 'game_started': False}
        elif args.action == 'initialize':
            result = {'assets_installed': install_assets(ROOT), 'game_started': False}
            if bundled_import_needed(ROOT):
                result.update(kit.import_game(ROOT, ROOT / kit.GAME_ARCHIVE_NAME))
        else:
            raise ValueError('Geef de vereiste pakketargumenten.')
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        p.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
