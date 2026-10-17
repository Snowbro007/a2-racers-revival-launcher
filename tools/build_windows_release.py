"""Build a native launcher and audited payload for the standard MSI installer.

Input must be an already audited public portable ZIP. No downloads, game data,
signing keys, uploads, installation, or system-security changes are performed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compiler() -> Path:
    return Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'


def compile_cs(sources: list[Path], output: Path, *, icon: Path | None = None,
               resource: Path | None = None, main: str | None = None, window: bool = True) -> None:
    args = [str(compiler()), '/nologo', '/optimize+', '/platform:x64', '/utf8output',
            '/target:' + ('winexe' if window else 'exe'), '/out:' + str(output),
            '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
            '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll']
    if icon: args.append('/win32icon:' + str(icon))
    if resource: args.append('/resource:' + str(resource) + ',A2.Payload.zip')
    if main: args.append('/main:' + main)
    subprocess.run(args + [str(path) for path in sources], check=True, capture_output=True, text=True)


def build(source: Path, portable: Path, output: Path, version: str) -> dict:
    if not re.fullmatch(r'\d+\.\d+\.\d+-beta\.\d+', version):
        raise ValueError('Onbekende betaversie.')
    from tools import portable_launcher
    from tools.trial_manifest import validate_ancestors
    for path in (source, portable, output): validate_ancestors(path)
    if output.exists(): raise ValueError('Buildmap bestaat al; kies een nieuwe map.')
    portable_launcher.audit(portable, source)
    with zipfile.ZipFile(portable) as archive:
        manifest = json.loads(archive.read(portable_launcher.PREFIX + 'release-manifest.json'))
        if manifest['audience'] != 'launcher-public' or manifest['game_archive_included']:
            raise ValueError('Alleen een gecontroleerd openbaar pakket zonder game is toegestaan.')
        config = json.loads(archive.read(portable_launcher.PREFIX + 'public-release.json'))
        if config['version'] != version: raise ValueError('Pakketversie wijkt af van de setupversie.')
    existing_icon = source / 'tools/launcher_art/a2-revival.ico'
    validate_ancestors(existing_icon)
    if not existing_icon.is_file():
        raise FileNotFoundError('Het gecontroleerde A2-icoon ontbreekt; de build maakt of start geen icoonhulpprogramma.')
    output.mkdir()
    native = source / 'tools/windows'
    icon = output / 'a2-revival.ico'
    shutil.copyfile(existing_icon, icon)
    assembly = output / 'Version.cs'
    numeric = version.split('-')[0] + '.' + version.rsplit('.', 1)[1]
    assembly.write_text('using System.Reflection;\n[assembly: AssemblyTitle("A2 Racers Revival")]\n'
                        '[assembly: AssemblyCompany("A2 Racers Revival fanproject")]\n'
                        '[assembly: AssemblyProduct("A2 Racers Revival")]\n'
                        '[assembly: AssemblyCopyright("MIT - eigen launchercode; games uitgesloten")]\n'
                        f'[assembly: AssemblyVersion("{numeric}")]\n[assembly: AssemblyFileVersion("{numeric}")]\n'
                        f'[assembly: AssemblyInformationalVersion("{version}")]\n', encoding='utf-8')
    launcher = output / 'A2 Racers Revival.exe'
    compile_cs([native / 'NativeCommon.cs', native / 'Launcher.cs', assembly], launcher, icon=icon)
    payload = output / 'installation-payload.zip'
    with zipfile.ZipFile(portable) as original, zipfile.ZipFile(payload, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in original.namelist():
            archive.writestr('app/' + name.removeprefix(portable_launcher.PREFIX), original.read(name))
        archive.write(launcher, launcher.name)
    result = {'schema': 2, 'version': version, 'kind': 'native-launcher-and-msi-payload',
              'launcher': launcher.name, 'payload': payload.name, 'icon': icon.name,
              'launcher_sha256': digest(launcher), 'payload_sha256': digest(payload), 'icon_sha256': digest(icon),
              'portable_sha256': digest(portable), 'games_bundled': False, 'signed': False,
              'smart_screen_verified': False, 'published': False}
    (output / 'build-receipt.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--portable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.source.resolve(), args.portable.resolve(), args.output.resolve(), args.version)))
        return 0
    except subprocess.CalledProcessError as error:
        print(error.stdout or error.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
