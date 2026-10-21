"""Prepare a local update approval from build, smoke and human acceptance evidence.

Never publishes, uploads, signs, scans or runs software. The separate acceptance
JSON records a human's findings for exact bytes; it is not tool verification of
Windows compatibility, signatures or antivirus safety. --approve remains the
maintainer's explicit final decision after reviewing all three evidence records.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.launcher_updates import checked_path, msi_name, read_json


def _record(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('Missing or unknown human acceptance fields: ' + label)
    return value


def _text(value, label):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 2048:
        raise ValueError('Invalid human acceptance text: ' + label)
    return value


def validate_acceptance(acceptance: dict | None, msi_sha256: str, launcher_sha256: str) -> None:
    """Validate a human declaration's structure and byte binding, not its truth."""
    acceptance = _record(acceptance, (
        'schema', 'evidence_kind', 'reviewed_by', 'reviewed_at', 'msi_sha256',
        'launcher_sha256', 'windows11', 'signatures', 'antivirus'), 'acceptance')
    if (type(acceptance['schema']) is not int or acceptance['schema'] != 1
            or acceptance['evidence_kind'] != 'human-release-acceptance'):
        raise ValueError('Unsupported human acceptance declaration.')
    _text(acceptance['reviewed_by'], 'reviewed_by')
    timestamp = _text(acceptance['reviewed_at'], 'reviewed_at')
    try:
        reviewed_at = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise ValueError('Human acceptance requires an ISO date/time with a timezone.') from exc
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError('Human acceptance requires an ISO date/time with a timezone.')
    for key, expected in (('msi_sha256', msi_sha256), ('launcher_sha256', launcher_sha256)):
        value = acceptance[key]
        if (type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None
                or type(expected) is not str or value != expected):
            raise ValueError('Human acceptance does not identify the exact bytes: ' + key)
    checks = ('interactive', 'first_start', 'cached_start', 'game_import_and_return',
              'update_with_save_preservation', 'uninstall_with_save_preservation')
    windows = _record(acceptance['windows11'], (*checks, 'evidence_reference'), 'windows11')
    if any(windows[key] is not True for key in checks):
        raise ValueError('Interactive Windows 11 acceptance is incomplete.')
    _text(windows['evidence_reference'], 'windows11.evidence_reference')
    signatures = _record(acceptance['signatures'], ('installer', 'launcher'), 'signatures')
    identities = []
    for artifact in ('installer', 'launcher'):
        signature = _record(signatures[artifact], ('status', 'thumbprint', 'publisher'), 'signatures.' + artifact)
        if (signature['status'] != 'Valid' or type(signature['thumbprint']) is not str
                or re.fullmatch('[0-9A-Fa-f]{40}', signature['thumbprint']) is None):
            raise ValueError('Human acceptance requires a valid signature and certificate thumbprint: ' + artifact)
        identities.append((signature['thumbprint'].upper(), _text(signature['publisher'], artifact + '.publisher')))
    if identities[0] != identities[1]:
        raise ValueError('Installer and launcher must use the same reviewed signing identity.')
    antivirus = _record(acceptance['antivirus'], ('installer', 'launcher'), 'antivirus')
    for artifact, digest in (('installer', msi_sha256), ('launcher', launcher_sha256)):
        review = _record(antivirus[artifact], ('sha256', 'reviewed', 'open_detections', 'product', 'evidence_reference'), 'antivirus.' + artifact)
        if (type(review['sha256']) is not str or review['sha256'] != digest
                or review['reviewed'] is not True or type(review['open_detections']) is not int
                or review['open_detections'] != 0):
            raise ValueError('Human antivirus review is incomplete or has open detections: ' + artifact)
        _text(review['product'], 'antivirus.' + artifact + '.product')
        _text(review['evidence_reference'], 'antivirus.' + artifact + '.evidence_reference')


def create_review(installer: Path, build: dict, smoke: dict, *, approved: bool,
                  acceptance: dict | None = None) -> dict:
    if approved is not True:
        raise ValueError('Review the exact installer and explicitly approve before enabling updates.')
    if type(build) is not dict or type(smoke) is not dict or type(build.get('version')) is not str:
        raise ValueError('Build and installed-app evidence must be objects with a version.')
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
    validate_acceptance(acceptance, digest, build.get('launcher_sha256'))
    # Existing updater contract: the input declaration is not a safety guarantee.
    return {'schema': 1, 'product': 'A2 Racers Revival', 'version': version,
            'file': installer.name, 'sha256': digest, 'bytes': len(data),
            'games_bundled': False, 'update_approved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--build-review', type=Path, required=True)
    parser.add_argument('--app-test', type=Path, required=True)
    parser.add_argument('--acceptance', type=Path, required=True,
                        help='Separate human Windows 11, signing and antivirus acceptance JSON for these exact hashes.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--approve', action='store_true', required=True)
    args = parser.parse_args()
    build = read_json(checked_path(args.build_review).read_bytes())
    smoke = read_json(checked_path(args.app_test).read_bytes())
    acceptance = read_json(checked_path(args.acceptance).read_bytes())
    review = create_review(args.installer, build, smoke, approved=args.approve, acceptance=acceptance)
    output = checked_path(args.output)
    if output.name != 'release-review.json':
        raise ValueError('Use the exact release-review.json attachment name.')
    with output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(review, indent=2) + '\n')
    print('Local review created; nothing was published or uploaded.')


if __name__ == '__main__':
    main()
