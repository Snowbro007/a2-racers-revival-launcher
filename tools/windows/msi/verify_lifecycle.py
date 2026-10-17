"""Exercise MSI install/upgrade/repair/removal with text-only, isolated fixtures.

Default: author and audit two synthetic MSI databases. --execute additionally
uses Windows Installer for this uniquely named test product. No payload, game,
compiled helper or launcher is executed. No existing A2 installation is touched.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.windows.msi import build_msi as builder
from tools.trial_manifest import validate_ancestors

TEST_NAMESPACE = uuid.UUID('286429f5-dc23-4aeb-8e09-c88899775657')


def identity(token: str) -> dict:
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Use one generated lowercase UUID test token.')
    namespace = uuid.uuid5(TEST_NAMESPACE, token)
    return {
        'NAMESPACE': namespace,
        'NAME': 'A2 Revival installer test ' + token[:12],
        'UPGRADE_CODE': '{' + str(uuid.uuid5(namespace, 'test-upgrade')).upper() + '}',
        'INSTALLER_REGISTRY_KEY': r'Software\A2 Revival Installer Tests' + chr(92) + token,
    }


def fixture_files(name: str, version: str) -> dict[str, bytes]:
    # The required .exe filename contains plain text, never PE/MZ machine code.
    return {
        name + '.exe': ('Synthetic text only; never execute. Version ' + version).encode('ascii'),
        'app/tools/fixture.txt': ('Owned fixture version ' + version).encode('ascii'),
    }


def claim_output(output: Path) -> Path:
    allowed = ROOT / 'local/installer-validation'
    if '..' in output.parts:
        raise ValueError('Traversal is not allowed in installer test output.')
    validate_ancestors(output)
    full = output.absolute()
    full.relative_to(allowed.absolute())
    if full == allowed.absolute():
        raise ValueError('Use a unique child of local/installer-validation.')
    if output.exists():
        raise FileExistsError('Test output already exists; no existing files are overwritten.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    return full


def author_fixture(folder: Path, test_identity: dict, version: str, shell: Path) -> dict:
    payload = folder / ('fixture-' + version + '.zip')
    files = fixture_files(test_identity['NAME'], version)
    if any(data.startswith(b'MZ') for data in files.values()):
        raise ValueError('Executable fixture data is forbidden.')
    with zipfile.ZipFile(payload, 'x') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    output = folder / ('build-' + version)
    argv = ['build_msi.py', '--payload', str(payload), '--icon',
            str(ROOT / 'tools/launcher_art/a2-revival.ico'), '--output', str(output),
            '--version', version, '--powershell', str(shell)]
    with patch.multiple(builder, **test_identity), patch.object(sys, 'argv', argv):
        with contextlib.redirect_stdout(io.StringIO()):
            builder.main()
    subprocess.run([str(shell), '-NoLogo', '-NoProfile', '-File',
                    str(HERE / 'audit_msi.ps1'), '-Spec', str(output / 'build-plan.json')],
                   check=True, capture_output=True, text=True, timeout=60)
    plan = json.loads((output / 'build-plan.json').read_text(encoding='utf-8-sig'))
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if {row['path']: row['sha256'] for row in plan['manifest']} != expected:
        raise ValueError('Synthetic MSI manifest does not match its text fixture.')
    if plan['upgrade_code'] != test_identity['UPGRADE_CODE']:
        raise ValueError('Synthetic MSI uses a foreign product identity.')
    registry = next(table['rows'] for table in plan['tables'] if table['name'] == 'Registry')
    if any(row[1] != 1 or not (row[2] == test_identity['INSTALLER_REGISTRY_KEY']
                              or row[2].startswith(test_identity['INSTALLER_REGISTRY_KEY'] + chr(92)))
           for row in registry):
        raise ValueError('Synthetic MSI would write outside its isolated HKCU test key.')
    return plan


def verify_files(target: Path, name: str, version: str) -> None:
    validate_ancestors(target)
    for relative, expected in fixture_files(name, version).items():
        path = target / relative
        validate_ancestors(path)
        if path.read_bytes() != expected:
            raise ValueError('Installed fixture mismatch: ' + relative)


def verify_shortcuts(shell: Path, target: Path, name: str) -> list[str]:
    result = subprocess.run([str(shell), '-NoLogo', '-NoProfile', '-File',
                             str(HERE / 'read_test_shortcuts.ps1'), '-ProductName', name],
                            check=True, capture_output=True, text=True, encoding='utf-8', timeout=30)
    rows = json.loads(result.stdout)
    icon_hash = hashlib.sha256((ROOT / 'tools/launcher_art/a2-revival.ico').read_bytes()).hexdigest()
    if len(rows) != 2:
        raise ValueError('Expected exactly two test shortcuts.')
    for row in rows:
        if Path(row['target']).resolve() != (target / (name + '.exe')).resolve() or row['arguments']:
            raise ValueError('Shortcut targets a different program.')
        icon = Path(row['icon'].rsplit(',', 1)[0].strip('"'))
        if hashlib.sha256(icon.read_bytes()).hexdigest() != icon_hash:
            raise ValueError('Shortcut does not use the expected A2 icon bytes.')
    return [row['path'] for row in rows]


def msi_command(installer: Path, arguments: list[str], log: Path, properties=None) -> str:
    # Msiexec parses PROPERTY="value with spaces" itself. CRT/list2cmdline's
    # "PROPERTY=value with spaces" instead opens its usage dialog, even /qn.
    # No command shell is used; metacharacters in a folder remain literal.
    command = subprocess.list2cmdline([str(installer), *arguments, '/qn', '/norestart', '/l*v', str(log)])
    for name, value in (properties or {}).items():
        if not re.fullmatch('[A-Z][A-Z0-9_]*', name) or any(c in value for c in '\x00\r\n"'):
            raise ValueError('Invalid MSI test property.')
        command += ' ' + name + '="' + value + '"'
    return command


def execute_trial(folder: Path, test_identity: dict, plans: list[dict], shell: Path) -> dict:
    import winreg
    target = folder / 'Installatie met spaties - é'
    if target.exists():
        raise FileExistsError('Synthetic installation target already exists.')
    key = test_identity['INSTALLER_REGISTRY_KEY']
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise FileExistsError('Synthetic registry identity already exists.')
    except FileNotFoundError:
        pass
    installer = Path(os.environ['SystemRoot']) / 'System32/msiexec.exe'
    phases = []
    receipt = {'schema': 1, 'text_fixtures_only': True, 'payload_executed': False,
               'test_identity': {k: str(v) for k, v in test_identity.items()},
               'target': str(target), 'phases': phases, 'complete': False}
    receipt_path = folder / 'lifecycle-result.json'

    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')

    def invoke(phase, arguments, *, failure_expected=False, properties=None):
        log = folder / (phase + '.log')
        process = subprocess.run(msi_command(installer, arguments, log, properties), timeout=120)
        row = {'phase': phase, 'exit_code': process.returncode, 'log': log.name}
        phases.append(row)
        save()
        if failure_expected:
            if process.returncode in (0, 3010):
                raise ValueError('Downgrade unexpectedly succeeded.')
            if 'Er is al een nieuwere versie' not in log.read_text(encoding='utf-16', errors='replace'):
                raise ValueError('Downgrade failed for an unverified reason.')
        elif process.returncode not in (0, 3010):
            raise RuntimeError('Windows Installer failed at ' + phase + ': ' + str(process.returncode))

    user_files = {'app/local/launcher/settings.json': b'{"synthetic":"preserve settings"}',
                  'app/local/players/progress.txt': b'Synthetic save: preserve every byte',
                  'app/payload/cache.txt': b'Synthetic cached component: preserve every byte'}

    def verify_user_data():
        for relative, data in user_files.items():
            if (target / relative).read_bytes() != data:
                raise ValueError('Synthetic user data changed: ' + relative)

    def verify_registered_folder():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as handle:
            installed, _ = winreg.QueryValueEx(handle, 'InstallDir')
        if Path(installed).resolve() != target.resolve():
            raise ValueError('Installer did not retain the selected folder.')

    save()
    try:
        invoke('install', ['/i', plans[0]['output']], properties={'INSTALLDIR': str(target)})
        verify_files(target, test_identity['NAME'], '0.1.5')
        verify_registered_folder()
        shortcut_paths = verify_shortcuts(shell, target, test_identity['NAME'])
        receipt['shortcuts_and_icon_verified'] = True
        for relative, data in user_files.items():
            path = target / relative
            validate_ancestors(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
        invoke('upgrade', ['/i', plans[1]['output']])
        verify_files(target, test_identity['NAME'], '0.1.6')
        verify_registered_folder()
        verify_user_data()
        verify_shortcuts(shell, target, test_identity['NAME'])
        invoke('downgrade-refused', ['/i', plans[0]['output']], failure_expected=True)
        verify_files(target, test_identity['NAME'], '0.1.6')
        verify_user_data()
        # Delete only the exact owned text fixture after checking its bytes.
        (target / 'app/tools/fixture.txt').unlink()
        invoke('repair', ['/fa', plans[1]['output']])
        verify_files(target, test_identity['NAME'], '0.1.6')
        verify_user_data()
        invoke('uninstall', ['/x', plans[1]['product_code']])
        verify_user_data()
        if any((target / relative).exists() for relative in fixture_files(test_identity['NAME'], '0.1.6')):
            raise ValueError('Owned fixture files survived uninstall.')
        if any(Path(path).exists() for path in shortcut_paths):
            raise ValueError('Test shortcuts survived uninstall.')
        receipt['complete'] = True
        receipt['settings_progress_and_cache_preserved'] = True
        receipt['shortcuts_removed'] = True
    except BaseException as error:
        receipt['error'] = str(error)
        # The log is retained. Never claim success or change security settings.
        # Cleanup only our generated, uniquely named product codes.
        for number, plan in reversed(list(enumerate(plans))):
            try:
                result = subprocess.run([str(installer), '/x', plan['product_code'], '/qn', '/norestart',
                                         '/l*v', str(folder / ('cleanup-' + str(number) + '.log'))], timeout=120)
                phases.append({'phase': 'cleanup-' + str(number), 'exit_code': result.returncode})
            except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                phases.append({'phase': 'cleanup-' + str(number), 'error': str(cleanup_error)})
        raise
    finally:
        save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--powershell', type=Path)
    parser.add_argument('--execute', action='store_true', help='Install only the generated text-only test product.')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Windows is required for this integration test.')
    shell = builder.powershell_path(args.powershell)
    folder = claim_output(args.output)
    test_identity = identity(uuid.uuid4().hex)
    plans = [author_fixture(folder, test_identity, version, shell) for version in ('0.1.5', '0.1.6')]
    if args.execute:
        print(json.dumps(execute_trial(folder, test_identity, plans, shell)))
    else:
        print(json.dumps({'authored_and_audited': True, 'installed': False, 'payload_executed': False}))


if __name__ == '__main__':
    main()
