"""Prepare a local update approval from exact build and installed-app evidence.

Never publishes, uploads or signs. --approve is the maintainer's explicit final
decision after reviewing installation/UI and antivirus results for these bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.launcher_updates import checked_path, msi_name, read_json


def create_review(installer: Path, build: dict, smoke: dict, *, approved: bool) -> dict:
    if approved is not True:
        raise ValueError('Review the exact installer and explicitly approve before enabling updates.')
    installer = checked_path(installer)
    version = build['version']
    if installer.name != msi_name(version):
        raise ValueError('Installer name does not match its version.')
    data = installer.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) or len(data) > 128 * 1024 * 1024:
        raise ValueError('Not a supported MSI database.')
    if (build.get('sha256') != digest or build.get('file') != installer.name
            or build.get('games_bundled') is not False
            or build.get('source_payload_cabinet_and_database_verified') is not True
            or build.get('synthetic_tests_passed') is not True
            or build.get('text_fixture_installer_lifecycle_verified') is not True):
        raise ValueError('Exact source/payload/MSI evidence is incomplete.')
    if (smoke.get('msi_sha256') != digest or smoke.get('launcher_sha256') != build.get('launcher_sha256')
            or smoke.get('complete') is not True or smoke.get('first-run_verified') is not True
            or smoke.get('cached-run_verified') is not True
            or smoke.get('bundled_runtimes_verified') is not True
            or smoke.get('user_data_and_cache_preserved') is not True
            or smoke.get('game_executed') is not False or smoke.get('native_helper_executed') is not False):
        raise ValueError('Exact installed-app test evidence is incomplete.')
    # This is an approval record, not a claim that signing/AV checks passed.
    return {'schema': 1, 'product': 'A2 Racers Revival', 'version': version,
            'file': installer.name, 'sha256': digest, 'bytes': len(data),
            'games_bundled': False, 'update_approved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--build-review', type=Path, required=True)
    parser.add_argument('--app-test', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--approve', action='store_true', required=True)
    args = parser.parse_args()
    build = read_json(checked_path(args.build_review).read_bytes())
    smoke = read_json(checked_path(args.app_test).read_bytes())
    review = create_review(args.installer, build, smoke, approved=args.approve)
    output = checked_path(args.output)
    if output.name != 'release-review.json':
        raise ValueError('Use the exact release-review.json attachment name.')
    with output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(review, indent=2) + '\n')
    print('Local review created; nothing was published or uploaded.')


if __name__ == '__main__':
    main()
