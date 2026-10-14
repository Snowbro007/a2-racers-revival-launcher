"""Local, version-bound III start using the original built-in NOCD route."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.local_game_data import launch_environment
from tools.trial_manifest import validate_ancestors, validate_tree
from tools.iii_source_catalog import CATALOG

PINS = {1: '506df78dffc4712f30a14975b9252827ba6a76c9403819816ad4bc87453eeda7',
        2: '2a9170a6efce4fcf27dc3683643183967023c8352a5e4922dd82dca8fd52f23c'}
MUTABLE = {'game.ini', 'raser.ini', 'menu.ini'}


def digest(path: Path) -> str:
    validate_ancestors(path)
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_records(root: Path, tour: int) -> list[dict]:
    if type(tour) is not int or tour not in PINS:
        raise ValueError('Kies Tour 1 of Tour 2.')
    report = root / f'reports/a2racer3/tours-20261013/tour{tour}-files.json'
    if report.exists():
        if digest(report) != PINS[tour]:
            raise ValueError('De deel-III-bronregistratie wijkt af.')
        records = json.loads(report.read_text(encoding='utf-8'))['files']
    else:
        records = CATALOG[tour]
    for record in records:
        relative = PurePosixPath(record['path'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in record['path'] or ':' in record['path']:
            raise ValueError('Ongeldig bronpad.')
    return records


def target_name(relative: str) -> str:
    # CD separates MenuData; the original tour parent requests menu.exe and
    # spel.dat from the same working directory. No binary changes are needed.
    return relative.removeprefix('MenuData/')


def game_folder(root: Path, tour: int) -> Path:
    return root / f'local/iii-play/tour{tour}'


def local_movie_path(target: Path) -> None:
    """Replace only the original CD-root movie path in the working copy."""
    path = target / 'menu.ini'
    content = path.read_bytes()
    old = b'INTROAVI=\\DATA\\INTRO.AVI'
    if old in content:
        path.write_bytes(content.replace(old, b'INTROAVI=.\\intro.avi'))


def prepare(root: Path, tour: int) -> Path:
    records = source_records(root, tour)
    target = game_folder(root, tour)
    validate_ancestors(target)
    if target.exists():
        check(root, tour)
        local_movie_path(target)
        return target
    source = root / f'local/iii-prepared/baseline-20261013/tour{tour}'
    validate_tree(source)
    names = [target_name(r['path']).lower() for r in records]
    if len(names) != len(set(names)):
        raise ValueError('Menu- en racedata hebben overlappende namen.')
    for record in records:
        path = source / record['path']
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError('De oorspronkelijke bron wijkt af: ' + record['path'])
    target.mkdir(parents=True)
    for record in records:
        path = target / target_name(record['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / record['path'], path)
    check(root, tour)
    local_movie_path(target)
    return target


def check(root: Path, tour: int) -> dict:
    target = game_folder(root, tour)
    return check_folder(root, tour, target)


def check_folder(root: Path, tour: int, target: Path) -> dict:
    records = source_records(root, tour)
    validate_tree(target)
    for record in records:
        path = target / target_name(record['path'])
        validate_ancestors(path)
        if not path.is_file():
            raise ValueError('Lokale gamegegevens ontbreken: ' + record['path'])
        if path.name.lower() not in MUTABLE and digest(path) != record['sha256']:
            raise ValueError('Lokale gamegegevens wijken af: ' + record['path'])
    return {'tour': tour, 'game_path': str(target), 'launch_ready': True,
            'runtime_verified': False, 'disc_image_used': False,
            'mode': 'builtin-NOCD-local-files', 'binary_modified': False}


def start(root: Path, tour: int) -> int:
    target = prepare(root, tour)
    environment = {**os.environ, **launch_environment(target)}
    # The original parent owns menu/race transitions, including Menu.ini's
    # ExitCode 40. We do not transplant II offsets or reinterpret race state.
    child = subprocess.Popen([str(target / f'A2 Racer III Tour {tour}.exe')],
                             cwd=target, env=environment)
    return child.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'check', 'start'))
    parser.add_argument('--tour', type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    try:
        if args.action == 'start':
            return start(ROOT, args.tour)
        if args.action == 'prepare':
            prepare(ROOT, args.tour)
        print(json.dumps(check(ROOT, args.tour)))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
