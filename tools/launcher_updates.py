"""Opt-in release checks and verified MSI downloads; never executes an installer.

Only reviewed releases from the fixed project repository are eligible. A failed
check never changes game settings, saves, an installation, or Windows security.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.parse
import urllib.request
import uuid

REPOSITORY = 'Snowbro007/a2-racers-revival-launcher'
RELEASES_URL = 'https://api.github.com/repos/' + REPOSITORY + '/releases?per_page=30'
PAGE_URL = 'https://github.com/' + REPOSITORY + '/releases'
DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
MAX_MSI = 128 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


def checked_path(path: Path) -> Path:
    path = Path(path)
    if '..' in path.parts or str(path).startswith(('\\\\?\\', '\\\\.\\')):
        raise ValueError('Ongeldig updatepad.')
    full = path.absolute()
    for ancestor in (full, *full.parents):
        try:
            entry = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(entry.st_mode) or getattr(entry, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Updatepad bevat een koppeling.')
        if stat.S_ISREG(entry.st_mode) and entry.st_nlink != 1:
            raise ValueError('Updatebestand bevat een hardlink.')
    return full


def version_key(version: str) -> tuple[int, ...]:
    match = re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-beta\.([1-9][0-9]*))?', version)
    if not match or any(len(part or '') > 6 for part in match.groups()):
        raise ValueError('Onbekende launcherversie.')
    major, minor, patch = map(int, match.groups()[:3])
    beta = match.group(4)
    return major, minor, patch, int(beta is None), int(beta or 0)


def msi_name(version: str) -> str:
    major, minor, patch, stable, beta = version_key(version)
    numeric = f'{major}.{minor}.{patch * 1000 + (1000 if stable else beta)}'
    if major > 255 or minor > 255 or patch > 64 or beta > 999:
        raise ValueError('Updateversie past niet in Windows Installer.')
    return f'A2-Racers-Revival-{numeric}' + ('' if stable else f'-beta{beta}') + '.msi'


def read_json(data: bytes):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('Dubbel updateveld.')
            result[key] = value
        return result
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Ongeldig getal.')))


def safe_url(url: str, *, api=False) -> str:
    parsed = urllib.parse.urlsplit(url)
    hosts = {'api.github.com'} if api else DOWNLOAD_HOSTS
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('Onverwachte updateserver.')
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        safe_url(newurl, api=urllib.parse.urlsplit(request.full_url).hostname == 'api.github.com')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(url: str, limit: int) -> bytes:
    safe_url(url, api=url.startswith('https://api.github.com/'))
    request = urllib.request.Request(url, headers={'User-Agent': 'A2-Racers-Revival-update-check',
                                                  'Accept': 'application/vnd.github+json' if url.startswith('https://api.') else 'application/octet-stream'})
    with urllib.request.build_opener(Redirects()).open(request, timeout=15) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Updatebestand is te groot.')
        return data


def current_version(root: Path) -> str:
    path = checked_path(root / 'VERSION.txt')
    version = path.read_text(encoding='utf-8-sig').strip()
    version_key(version)
    return version


def settings(root: Path) -> dict:
    path = checked_path(root / 'local/launcher/update-settings.json')
    if not path.exists():
        return {'schema': 1, 'automatic_check': (root / 'public-release.json').is_file()}
    if path.stat().st_size > 4096:
        raise ValueError('Updatevoorkeur is te groot.')
    value = read_json(path.read_bytes())
    if not isinstance(value, dict) or set(value) != {'schema', 'automatic_check'} or value['schema'] != 1 or type(value['automatic_check']) is not bool:
        raise ValueError('Ongeldige updatevoorkeur. Je spelinstellingen zijn niet gewijzigd.')
    return value


def save_settings(root: Path, automatic: bool) -> dict:
    path = checked_path(root / 'local/launcher/update-settings.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {'schema': 1, 'automatic_check': automatic}
    temporary = checked_path(path.with_name('update-settings-' + uuid.uuid4().hex + '.tmp'))
    with temporary.open('xb') as stream:
        stream.write((json.dumps(value) + '\n').encode('utf-8'))
    try:
        checked_path(path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return value


def release_assets(release: dict, version: str) -> dict:
    if release.get('draft') is not False or release.get('tag_name') != 'v' + version:
        raise ValueError('Geen openbare update.')
    if release.get('html_url') != PAGE_URL + '/tag/v' + version:
        raise ValueError('Onverwachte releasepagina.')
    names = (msi_name(version), 'release-review.json')
    result = {}
    for asset in release.get('assets', []):
        name = asset.get('name')
        if name not in names:
            continue
        if name in result:
            raise ValueError('Dubbele updatebijlage.')
        url = 'https://github.com/' + REPOSITORY + '/releases/download/v' + version + '/' + name
        size = asset.get('size')
        digest = asset.get('digest', '')
        if (asset.get('browser_download_url') != url or asset.get('state') != 'uploaded'
                or type(size) is not int or not 0 < size <= (MAX_MSI if name.endswith('.msi') else 16384)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
            raise ValueError('Updatebijlage is niet volledig controleerbaar.')
        result[name] = {'url': url, 'size': size, 'sha256': digest[7:]}
    if set(result) != set(names):
        raise ValueError('Deze release heeft nog geen gecontroleerde installer.')
    return result


def reviewed_offer(release: dict, version: str, reader=fetch) -> dict:
    assets = release_assets(release, version)
    record_asset = assets['release-review.json']
    data = reader(record_asset['url'], 16384)
    if len(data) != record_asset['size'] or hashlib.sha256(data).hexdigest() != record_asset['sha256']:
        raise ValueError('Releasecontrole wijkt af van GitHub.')
    review = read_json(data)
    installer = assets[msi_name(version)]
    expected = {'schema': 1, 'product': 'A2 Racers Revival', 'version': version,
                'file': msi_name(version), 'sha256': installer['sha256'], 'bytes': installer['size'],
                'games_bundled': False, 'update_approved': True}
    if (not isinstance(review, dict) or review != expected or type(review.get('schema')) is not int or type(review.get('bytes')) is not int
            or review.get('games_bundled') is not False or review.get('update_approved') is not True):
        raise ValueError('Deze installer is nog niet vrijgegeven voor updates.')
    return {'version': version, 'file': msi_name(version), **installer,
            'release_url': release['html_url']}


def check(root: Path, *, automatic=False, reader=fetch) -> dict:
    preference = settings(root)
    current = current_version(root)
    result = {'current_version': current, **preference, 'release_page': PAGE_URL}
    if automatic and not preference['automatic_check']:
        return {**result, 'state': 'disabled', 'message': 'Automatische updatecontrole staat uit.'}
    releases = read_json(reader(RELEASES_URL, 2 * 1024 * 1024))
    if not isinstance(releases, list) or len(releases) > 100:
        raise ValueError('Onverwacht antwoord van GitHub.')
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get('draft') is not False:
            continue
        tag = release.get('tag_name', '')
        try:
            version = tag.removeprefix('v')
            if version_key(version) <= version_key(current):
                continue
            release_assets(release, version)
        except (ValueError, TypeError, AttributeError):
            continue
        candidates.append((version_key(version), version, release))
    for _, version, release in sorted(candidates, reverse=True, key=lambda row: row[0]):
        try:
            offer = reviewed_offer(release, version, reader)
        except (ValueError, OSError):
            continue
        return {**result, 'state': 'available', 'offer': offer,
                'message': 'Versie ' + version + ' is beschikbaar.'}
    return {**result, 'state': 'current', 'message': 'Geen nieuwere vrijgegeven installer gevonden.'}


def mark_download(path: Path, url: str) -> None:
    # Preserve Internet-zone handling. Never unblock a file or alter SmartScreen.
    if os.name != 'nt':
        raise OSError('Windows is vereist om de internetherkomst te bewaren.')
    safe_url(url)
    with Path(str(path) + ':Zone.Identifier').open('x', encoding='utf-8') as stream:
        stream.write('[ZoneTransfer]\nZoneId=3\nHostUrl=' + url + '\n')


def verify_download(root: Path, receipt: Path) -> dict:
    base = checked_path(root / 'local/launcher/updates')
    receipt = checked_path(receipt)
    receipt.relative_to(base)
    if receipt.name != 'download.json':
        raise ValueError('Onbekend updatebewijs.')
    if receipt.stat().st_size > 16384:
        raise ValueError('Updatebewijs is te groot.')
    value = read_json(receipt.read_bytes())
    if not isinstance(value, dict) or set(value) != {'schema', 'version', 'file', 'sha256', 'size', 'url', 'release_url'} or value['schema'] != 1:
        raise ValueError('Ongeldig updatebewijs.')
    version = value['version']
    if (version_key(version) <= version_key(current_version(root)) or value['file'] != msi_name(version)
            or not re.fullmatch('[0-9a-f]{64}', value['sha256']) or type(value['size']) is not int
            or not 0 < value['size'] <= MAX_MSI
            or value['url'] != 'https://github.com/' + REPOSITORY + '/releases/download/v' + version + '/' + value['file']
            or value['release_url'] != PAGE_URL + '/tag/v' + version):
        raise ValueError('Updatebewijs hoort niet bij een nieuwere projectrelease.')
    path = checked_path(receipt.parent / value['file'])
    if path.stat().st_size != value['size']:
        raise ValueError('De grootte van de installer is veranderd.')
    data = path.read_bytes()
    if (len(data) != value['size'] or hashlib.sha256(data).hexdigest() != value['sha256']
            or not data.startswith(bytes.fromhex('d0cf11e0a1b11ae1'))):
        raise ValueError('De gedownloade installer is veranderd of onvolledig.')
    if os.name == 'nt':
        zone = Path(str(path) + ':Zone.Identifier').read_text(encoding='utf-8')
        if zone != '[ZoneTransfer]\nZoneId=3\nHostUrl=' + value['url'] + '\n':
            raise ValueError('De internetherkomst van de update ontbreekt.')
    return {'state': 'downloaded', 'path': str(path), 'receipt': str(receipt), **value,
            'message': 'Installer gecontroleerd. Je kunt de update nu openen.'}


def download(root: Path, version: str, reader=fetch, marker=mark_download) -> dict:
    # Re-fetch the public offer; never trust a cached arbitrary URL or local offer.
    state = check(root, reader=reader)
    offer = state.get('offer')
    if not offer or offer['version'] != version:
        raise ValueError('Deze update is niet meer de nieuwste vrijgegeven installer. Controleer opnieuw.')
    base = checked_path(root / 'local/launcher/updates')
    base.mkdir(parents=True, exist_ok=True)
    folder = checked_path(base / uuid.uuid4().hex)
    folder.mkdir(exist_ok=False)
    data = reader(offer['url'], MAX_MSI)
    if len(data) != offer['size'] or hashlib.sha256(data).hexdigest() != offer['sha256']:
        raise ValueError('Update komt niet overeen met de vrijgegeven SHA-256.')
    if not data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        raise ValueError('De download is geen MSI-database.')
    target = checked_path(folder / offer['file'])
    with target.open('xb') as stream:
        stream.write(data)
    marker(target, offer['url'])
    value = {'schema': 1, **{key: offer[key] for key in ('version', 'file', 'sha256', 'size', 'url', 'release_url')}}
    receipt = checked_path(folder / 'download.json')
    with receipt.open('xb') as stream:
        stream.write((json.dumps(value, indent=2) + '\n').encode('utf-8'))
    return verify_download(root, receipt)


def verify_for_install(root: Path, receipt: Path, reader=fetch) -> dict:
    previous = verify_download(root, receipt)
    offer = check(root, reader=reader).get('offer')
    if not offer or any(previous[key] != offer[key] for key in ('version', 'file', 'sha256', 'size', 'url', 'release_url')):
        raise ValueError('Deze update is niet meer vrijgegeven. Controleer opnieuw.')
    return verify_download(root, receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('action', choices=('settings', 'check', 'download', 'verify'))
    parser.add_argument('--automatic', action='store_true')
    parser.add_argument('--set-automatic', choices=('0', '1'))
    parser.add_argument('--version')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    try:
        root = checked_path(args.root)
        if args.action == 'settings':
            result = settings(root) if args.set_automatic is None else save_settings(root, args.set_automatic == '1')
            result = {**result, 'current_version': current_version(root), 'state': 'settings'}
        elif args.action == 'check':
            result = check(root, automatic=args.automatic)
        elif args.action == 'download':
            result = download(root, args.version or '')
        else:
            if args.receipt is None:
                raise ValueError('Updatebewijs ontbreekt.')
            result = verify_for_install(root, args.receipt)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        message = str(error) if isinstance(error, ValueError) else 'Updatecontrole of download niet beschikbaar. Je kunt gewoon blijven spelen.'
        print(json.dumps({'state': 'error', 'message': message}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
