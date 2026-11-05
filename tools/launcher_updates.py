"""Opt-in release checks, verified MSI downloads and portable self-updates.

Only releases from the fixed project repository are eligible. MSI installations
get a reviewed installer that the user opens; this module never executes it.
A portable (unzipped) launcher can replace its own app files from a published,
checksum-verified release ZIP after the user agrees. Files under local/ (saves,
settings, imported games, runtimes) are never touched by an update. A failed
check or update never changes game settings, saves, or Windows security.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

REPOSITORY = 'Snowbro007/a2-racers-revival-launcher'
RELEASES_URL = 'https://api.github.com/repos/' + REPOSITORY + '/releases?per_page=30'
PAGE_URL = 'https://github.com/' + REPOSITORY + '/releases'
DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
MAX_MSI = 128 * 1024 * 1024
MAX_ZIP = 256 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024
APP_FOLDER = 'A2-Racers-Revival/'  # Same prefix as tools/portable_launcher.PREFIX.
NATIVE_LAUNCHER = 'A2 Racers Revival.exe'
REQUIRED_APP_FILES = ('Launcher.cmd', 'VERSION.txt', 'public-release.json',
                      'tools/Show-A2Launcher.ps1', 'tools/launcher_updates.py', 'tools/launcher_updates.ps1')
WINDOWS_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$', re.IGNORECASE)
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


def install_kind(root: Path) -> str:
    """'msi' for the installed app, 'portable' for an unzipped public release, else 'development'.

    A development checkout is never self-updated: only a release folder that
    carries the public release markers next to Launcher.cmd is replaced.
    """
    root = Path(root)
    if root.name.casefold() == 'app' and (root.parent / NATIVE_LAUNCHER).is_file():
        return 'msi'
    if (all((root / name).is_file() for name in ('Launcher.cmd', 'release-manifest.json', 'public-release.json'))
            and not (root / '.git').exists()):
        return 'portable'
    return 'development'


def zip_name(version: str) -> str:
    version_key(version)
    return 'A2-Racers-Revival-' + version + '-Windows-x64.zip'


def portable_assets(release: dict, version: str) -> dict:
    if release.get('draft') is not False or release.get('tag_name') != 'v' + version:
        raise ValueError('Geen openbare update.')
    if release.get('html_url') != PAGE_URL + '/tag/v' + version:
        raise ValueError('Onverwachte releasepagina.')
    names = (zip_name(version), zip_name(version) + '.sha256')
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
                or type(size) is not int or not 0 < size <= (MAX_ZIP if name.endswith('.zip') else 512)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
            raise ValueError('Updatebijlage is niet volledig controleerbaar.')
        result[name] = {'url': url, 'size': size, 'sha256': digest[7:]}
    if set(result) != set(names):
        raise ValueError('Deze release heeft geen controleerbare launcher-ZIP.')
    return result


def portable_offer(release: dict, version: str, reader=fetch) -> dict:
    assets = portable_assets(release, version)
    package = assets[zip_name(version)]
    checksum = assets[zip_name(version) + '.sha256']
    data = reader(checksum['url'], 512)
    if len(data) != checksum['size'] or hashlib.sha256(data).hexdigest() != checksum['sha256']:
        raise ValueError('Checksumbestand wijkt af van GitHub.')
    # The workflow writes '<sha256>  <file name>' next to the ZIP; both sources must agree.
    if data.decode('ascii', 'strict').strip() != package['sha256'] + '  ' + zip_name(version):
        raise ValueError('Checksum van de launcher-ZIP klopt niet.')
    return {'kind': 'portable', 'version': version, 'file': zip_name(version), **package,
            'release_url': release['html_url']}


def check(root: Path, *, automatic=False, reader=fetch) -> dict:
    preference = settings(root)
    current = current_version(root)
    kind = install_kind(root)
    result = {'current_version': current, **preference, 'release_page': PAGE_URL, 'install_kind': kind}
    if automatic and not preference['automatic_check']:
        return {**result, 'state': 'disabled', 'message': 'Automatische updatecontrole staat uit.'}
    assets_for, offer_for = (portable_assets, portable_offer) if kind == 'portable' else (release_assets, reviewed_offer)
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
            assets_for(release, version)
        except (ValueError, TypeError, AttributeError):
            continue
        candidates.append((version_key(version), version, release))
    for _, version, release in sorted(candidates, reverse=True, key=lambda row: row[0]):
        try:
            offer = offer_for(release, version, reader)
        except (ValueError, OSError, UnicodeError):
            continue
        return {**result, 'state': 'available', 'offer': offer,
                'message': 'Versie ' + version + ' is beschikbaar.'}
    return {**result, 'state': 'current', 'message': 'Je hebt de nieuwste versie.' if kind == 'portable'
            else 'Geen nieuwere vrijgegeven installer gevonden.'}


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
    if offer.get('kind') == 'portable':
        return download_portable(root, offer, reader, marker)
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
    portable = receipt_kind(root, receipt) == 'portable'
    verify = verify_portable_download if portable else verify_download
    previous = verify(root, receipt)
    offer = check(root, reader=reader).get('offer')
    keys = ('version', 'file', 'sha256', 'size', 'url', 'release_url') + (('kind',) if portable else ())
    if not offer or any(previous[key] != offer.get(key) for key in keys):
        raise ValueError('Deze update is niet meer vrijgegeven. Controleer opnieuw.')
    return verify(root, receipt)


# --- Portable self-update -------------------------------------------------
# The unzipped launcher folder holds app files listed in release-manifest.json
# and the user's own data under local/. An update only ever replaces or removes
# files that a release manifest lists, never anything under local/.

def receipt_kind(root: Path, receipt: Path) -> str:
    base = checked_path(root / 'local/launcher/updates')
    receipt = checked_path(receipt)
    receipt.relative_to(base)
    if receipt.name != 'download.json' or receipt.stat().st_size > 16384:
        raise ValueError('Onbekend updatebewijs.')
    value = read_json(receipt.read_bytes())
    if not isinstance(value, dict):
        raise ValueError('Ongeldig updatebewijs.')
    return 'portable' if value.get('kind') == 'portable' else 'msi'


def safe_member(name: str) -> str:
    parts = name.split('/') if isinstance(name, str) else ['']
    if (not name or PurePosixPath(name).is_absolute() or '\\' in name or ':' in name
            or any(part in ('', '.', '..') or part != part.strip() or part.endswith('.')
                   or WINDOWS_RESERVED.match(part.split('.')[0]) for part in parts)
            or parts[0].casefold() in ('local', '.git')):
        raise ValueError('Onveilig bestand in update: ' + str(name))
    return name


def package_rows(manifest) -> dict:
    """Validate a public portable release manifest; return {path: row}."""
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema', 'kind', 'game_archive_included', 'audience', 'gameplay_verified_on_second_pc', 'files'}
            or type(manifest['schema']) is not int or manifest['schema'] != 1
            or manifest['kind'] != 'portable-launcher' or manifest['audience'] != 'launcher-public'
            or manifest['game_archive_included'] is not False
            or not isinstance(manifest['files'], list) or len(manifest['files']) > 3000):
        raise ValueError('Onbekend release-manifest in de update.')
    rows, seen, total = {}, set(), 0
    for row in manifest['files']:
        if (not isinstance(row, dict) or set(row) != {'path', 'size', 'sha256'}
                or type(row['size']) is not int or not 0 < row['size'] <= MAX_UNPACKED
                or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Ongeldige regel in het release-manifest.')
        name = safe_member(row['path'])
        if name.casefold() in seen or name.casefold() == 'release-manifest.json':
            raise ValueError('Dubbel bestand in het release-manifest.')
        seen.add(name.casefold())
        total += row['size']
        rows[name] = row
    if total > MAX_UNPACKED:
        raise ValueError('Update is te groot.')
    missing = [name for name in REQUIRED_APP_FILES if name not in rows]
    if missing:
        raise ValueError('Update mist launcherbestanden: ' + ', '.join(missing))
    return rows


def file_sha256(stream) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1 << 20), b''):
        digest.update(block)
    return digest.hexdigest()


def read_package(path: Path, version: str) -> tuple[bytes, dict]:
    """Check every entry of a release ZIP; return (manifest bytes, rows)."""
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.infolist()
            names = [entry.filename for entry in info]
            if (len(info) > 3001 or len({name.casefold() for name in names}) != len(names)
                    or any(entry.is_dir() or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16) for entry in info)
                    or sum(entry.file_size for entry in info) > MAX_UNPACKED):
                raise ValueError('Onveilige of te grote update-ZIP.')
            entry = archive.getinfo(APP_FOLDER + 'release-manifest.json')
            if entry.file_size > 256 * 1024:
                raise ValueError('Release-manifest in de update is te groot.')
            manifest = archive.read(entry)
            rows = package_rows(read_json(manifest))
            if set(names) != {APP_FOLDER + name for name in rows} | {APP_FOLDER + 'release-manifest.json'}:
                raise ValueError('Update-ZIP bevat onverwachte of ontbrekende bestanden.')
            for name, row in rows.items():
                member = archive.getinfo(APP_FOLDER + name)
                with archive.open(member) as stream:
                    if member.file_size != row['size'] or file_sha256(stream) != row['sha256']:
                        raise ValueError('Inhoud van de update wijkt af: ' + name)
            if archive.read(APP_FOLDER + 'VERSION.txt').decode('utf-8-sig').strip() != version:
                raise ValueError('Versienummer in de update klopt niet.')
    except (KeyError, zipfile.BadZipFile, UnicodeError) as error:
        raise ValueError('De update-ZIP is onvolledig of beschadigd.') from error
    return manifest, rows


def stage_package(path: Path, staged: Path, manifest: bytes, rows: dict) -> None:
    staged.mkdir(exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for name, row in rows.items():
            target = checked_path(staged / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with archive.open(APP_FOLDER + name) as source, target.open('xb') as output:
                for block in iter(lambda: source.read(1 << 20), b''):
                    digest.update(block)
                    output.write(block)
            if digest.hexdigest() != row['sha256']:
                raise ValueError('Uitpakken van de update wijkt af: ' + name)
    with checked_path(staged / 'release-manifest.json').open('xb') as output:
        output.write(manifest)


def staged_rows(staged: Path) -> tuple[bytes, dict]:
    manifest = checked_path(staged / 'release-manifest.json').read_bytes()
    rows = package_rows(read_json(manifest))
    for name, row in rows.items():
        path = checked_path(staged / name)
        with path.open('rb') as stream:
            if path.stat().st_size != row['size'] or file_sha256(stream) != row['sha256']:
                raise ValueError('Klaargezette update is veranderd: ' + name)
    return manifest, rows


def download_portable(root: Path, offer: dict, reader=fetch, marker=mark_download) -> dict:
    if install_kind(root) != 'portable':
        raise ValueError('Alleen een uitgepakte launcher kan zichzelf bijwerken.')
    base = checked_path(root / 'local/launcher/updates')
    base.mkdir(parents=True, exist_ok=True)
    folder = checked_path(base / uuid.uuid4().hex)
    folder.mkdir(exist_ok=False)
    try:
        data = reader(offer['url'], MAX_ZIP)
        if len(data) != offer['size'] or hashlib.sha256(data).hexdigest() != offer['sha256']:
            raise ValueError('Update komt niet overeen met de vrijgegeven SHA-256.')
        if not data.startswith(b'PK\x03\x04'):
            raise ValueError('De download is geen ZIP-bestand.')
        target = checked_path(folder / offer['file'])
        with target.open('xb') as stream:
            stream.write(data)
        marker(target, offer['url'])
        manifest, rows = read_package(target, offer['version'])
        stage_package(target, checked_path(folder / 'staged'), manifest, rows)
        value = {'schema': 1, 'kind': 'portable',
                 **{key: offer[key] for key in ('version', 'file', 'sha256', 'size', 'url', 'release_url')}}
        receipt = checked_path(folder / 'download.json')
        with receipt.open('xb') as stream:
            stream.write((json.dumps(value, indent=2) + '\n').encode('utf-8'))
        return verify_portable_download(root, receipt)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def verify_portable_download(root: Path, receipt: Path) -> dict:
    base = checked_path(root / 'local/launcher/updates')
    receipt = checked_path(receipt)
    receipt.relative_to(base)
    if receipt.name != 'download.json' or receipt.stat().st_size > 16384:
        raise ValueError('Onbekend updatebewijs.')
    value = read_json(receipt.read_bytes())
    if (not isinstance(value, dict)
            or set(value) != {'schema', 'kind', 'version', 'file', 'sha256', 'size', 'url', 'release_url'}
            or value['schema'] != 1 or value['kind'] != 'portable'):
        raise ValueError('Ongeldig updatebewijs.')
    version = value['version']
    if (version_key(version) <= version_key(current_version(root)) or value['file'] != zip_name(version)
            or not re.fullmatch('[0-9a-f]{64}', value['sha256']) or type(value['size']) is not int
            or not 0 < value['size'] <= MAX_ZIP
            or value['url'] != 'https://github.com/' + REPOSITORY + '/releases/download/v' + version + '/' + value['file']
            or value['release_url'] != PAGE_URL + '/tag/v' + version):
        raise ValueError('Updatebewijs hoort niet bij een nieuwere projectrelease.')
    path = checked_path(receipt.parent / value['file'])
    with path.open('rb') as stream:
        if path.stat().st_size != value['size'] or file_sha256(stream) != value['sha256']:
            raise ValueError('De gedownloade update is veranderd of onvolledig.')
    if os.name == 'nt':
        zone = Path(str(path) + ':Zone.Identifier').read_text(encoding='utf-8')
        if zone != '[ZoneTransfer]\nZoneId=3\nHostUrl=' + value['url'] + '\n':
            raise ValueError('De internetherkomst van de update ontbreekt.')
    manifest, _ = read_package(path, version)
    if staged_rows(checked_path(receipt.parent / 'staged'))[0] != manifest:
        raise ValueError('Klaargezette update hoort niet bij deze download.')
    return {'state': 'downloaded', 'path': str(path), 'receipt': str(receipt), **value,
            'message': 'Update ' + version + ' is gecontroleerd en klaargezet.'}


class LauncherStillOpen(ValueError):
    """The old launcher did not close; nothing was changed and nothing is restarted."""


def wait_for_exit(pids, timeout: float = 60.0) -> None:
    """Wait until the launcher processes that started the update have closed."""
    if os.name != 'nt' or not pids:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    deadline = time.monotonic() + timeout
    for pid in pids:
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only.
        if not handle:
            continue  # Already closed.
        try:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if kernel.WaitForSingleObject(handle, remaining) != 0:
                raise LauncherStillOpen('De launcher sloot niet af; de update is niet uitgevoerd.')
        finally:
            kernel.CloseHandle(handle)


def replace_file(source: Path, target: Path) -> None:
    target = checked_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = checked_path(target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp'))
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_notice(root: Path, value: dict) -> None:
    path = checked_path(root / 'local/launcher/updates/notice.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = checked_path(path.with_name('notice-' + uuid.uuid4().hex + '.tmp'))
    with temporary.open('xb') as stream:
        stream.write((json.dumps({'schema': 1, **value}) + '\n').encode('utf-8'))
    os.replace(temporary, path)


def take_notice(root: Path) -> dict:
    """Return and clear the outcome of the last portable update (shown once)."""
    path = checked_path(root / 'local/launcher/updates/notice.json')
    if not path.is_file():
        return {'state': 'none'}
    try:
        value = read_json(path.read_bytes()) if path.stat().st_size <= 16384 else None
    finally:
        path.unlink()
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('state') not in ('updated', 'failed'):
        return {'state': 'none'}
    return {'state': 'notice', 'outcome': value['state'], 'message': str(value.get('message', ''))[:500]}


def apply_portable(root: Path, receipt: Path, wait_pids=(), waiter=wait_for_exit) -> dict:
    """Replace the app files of a closed portable launcher; restore everything on failure."""
    if install_kind(root) != 'portable':
        raise ValueError('Alleen een uitgepakte launcher kan zichzelf bijwerken.')
    waiter(wait_pids)
    try:
        state = verify_portable_download(root, receipt)
        folder = Path(state['receipt']).parent
        staged = checked_path(folder / 'staged')
        _, new_rows = staged_rows(staged)
        old_rows = package_rows(read_json(checked_path(root / 'release-manifest.json').read_bytes()))
    except (OSError, ValueError, KeyError) as error:
        detail = str(error) if isinstance(error, ValueError) else 'De klaargezette update is niet leesbaar.'
        write_notice(root, {'state': 'failed', 'message': 'Update niet uitgevoerd; er is niets veranderd. ' + detail})
        raise ValueError(detail) from error
    previous, version = current_version(root), state['version']
    new_names = {name.casefold() for name in new_rows}
    obsolete = [name for name in old_rows if name.casefold() not in new_names]
    touched = sorted(set(old_rows) | set(new_rows)) + ['release-manifest.json']
    base = checked_path(root / 'local/launcher/updates')
    backup = checked_path(base / ('backup-' + previous + '-' + uuid.uuid4().hex[:8]))
    backup.mkdir()
    for name in touched:
        source = checked_path(root / name)
        if source.is_file():
            target = checked_path(backup / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    try:
        for name in new_rows:
            replace_file(staged / name, root / name)
        for name in obsolete:
            path = checked_path(root / name)
            if path.is_file():
                path.unlink()
        replace_file(staged / 'release-manifest.json', root / 'release-manifest.json')
        for name, row in new_rows.items():
            path = checked_path(root / name)
            with path.open('rb') as stream:
                if path.stat().st_size != row['size'] or file_sha256(stream) != row['sha256']:
                    raise ValueError('Bijgewerkt bestand klopt niet: ' + name)
        if current_version(root) != version:
            raise ValueError('Versienummer na bijwerken klopt niet.')
    except BaseException as error:
        restore_errors = []
        for name in touched:
            try:
                saved, target = checked_path(backup / name), checked_path(root / name)
                if saved.is_file():
                    replace_file(saved, target)
                elif target.is_file():
                    target.unlink()
            except OSError as problem:
                restore_errors.append(name + ': ' + str(problem))
        message = ('Bijwerken naar ' + version + ' is mislukt; versie ' + previous + ' is teruggezet. '
                   + (str(error) if isinstance(error, ValueError) else 'Een bestand was niet te vervangen.'))
        if restore_errors:
            message = ('Bijwerken is mislukt en niet alles kon worden teruggezet. Download de launcher opnieuw; '
                       'je saves en instellingen in local blijven bewaard.')
        write_notice(root, {'state': 'failed', 'message': message})
        raise ValueError(message) from error
    write_notice(root, {'state': 'updated', 'message': 'Bijgewerkt van ' + previous + ' naar ' + version + '.'})
    shutil.rmtree(folder, ignore_errors=True)
    for old in base.glob('backup-*'):  # Keep only the newest previous version.
        if old != backup and old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
    return {'state': 'updated', 'from': previous, 'version': version, 'backup': str(backup),
            'message': 'Bijgewerkt van ' + previous + ' naar ' + version + '.'}


def restart_launcher(root: Path) -> None:
    script = checked_path(root / 'Launcher.cmd')
    shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'cmd.exe'
    subprocess.Popen([str(shell), '/c', str(script)], cwd=root,
                     creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0), close_fds=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('action', choices=('settings', 'check', 'download', 'verify', 'apply', 'notice'))
    parser.add_argument('--automatic', action='store_true')
    parser.add_argument('--set-automatic', choices=('0', '1'))
    parser.add_argument('--version')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--wait', type=int, action='append', default=[], help='Launcherproces dat eerst moet sluiten.')
    parser.add_argument('--restart', action='store_true', help='Start de launcher opnieuw na apply.')
    args = parser.parse_args()
    try:
        root = checked_path(args.root)
        if args.action == 'settings':
            result = settings(root) if args.set_automatic is None else save_settings(root, args.set_automatic == '1')
            result = {**result, 'current_version': current_version(root), 'state': 'settings',
                      'install_kind': install_kind(root)}
        elif args.action == 'check':
            result = check(root, automatic=args.automatic)
        elif args.action == 'download':
            result = download(root, args.version or '')
        elif args.action == 'notice':
            result = take_notice(root)
        elif args.action == 'apply':
            if args.receipt is None:
                raise ValueError('Updatebewijs ontbreekt.')
            try:
                result = apply_portable(root, args.receipt, args.wait)
            except LauncherStillOpen:
                raise  # The old launcher is still running; never open a second one.
            except BaseException:
                if args.restart:
                    restart_launcher(root)  # Restored version shows the failure notice.
                raise
            if args.restart:
                restart_launcher(root)
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
