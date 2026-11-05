"""Real PowerShell entry contract with a synthetic Python backend; no games."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which('pwsh')
FAKE_BACKEND = b'''import json, pathlib, sys
p = pathlib.Path(__file__).parent
(p / 'arguments.json').write_text(json.dumps(sys.argv[1:]))
fixture = json.loads((p / 'fixture.json').read_text())
print(json.dumps(fixture['result']))
raise SystemExit(fixture.get('backend_exit', 0))
'''


@unittest.skipUnless(PWSH and os.name == 'nt', 'Requires PowerShell 7 on Windows')
class LaterUiContractTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-later-ui-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        self.script = self.tools / 'Start-LaterGame.ps1'
        source = (ROOT / 'tools/Start-LaterGame.ps1').read_text(encoding='utf-8-sig')
        (self.tools / 'later_games_runtime.py').write_bytes(FAKE_BACKEND)
        pin = hashlib.sha256(FAKE_BACKEND).hexdigest()
        source, count = re.subn(r"(?<=\$pin -ne ')[0-9a-f]{64}(?=')", pin, source)
        self.assertEqual(count, 1)
        for name in set(re.findall(r"Join-Path \$PSScriptRoot '(later_[a-z0-9_]+\.py)'", source)):
            if name != 'later_games_runtime.py':
                (self.tools / name).write_bytes((ROOT / 'tools' / name).read_bytes())
        self.script.write_text(source, encoding='utf-8-sig')

    def run_ui(self, result, *extra, backend_exit=0, python=None):
        (self.tools / 'fixture.json').write_text(json.dumps({'result': result, 'backend_exit': backend_exit}))
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        process = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', str(self.script), '-Game', 'a2racer4', '-Profile', 'hd1080',
            '-PythonPath', str(python or sys.executable), '-UiResult', *extra],
            cwd=self.root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertLess(len(process.stdout), 5000)
        try:
            payload = json.loads(process.stdout.lstrip('\ufeff'))
        except json.JSONDecodeError as error:
            self.fail(f'No compact result: {process.stdout!r}; {process.stderr[-1000:]!r}: {error}')
        return process, payload

    def session(self, *, code=0, reason='exited', restored=True, stop=False):
        return {'game': 'a2racer4', 'profile': 'hd1080',
                'game_path': str(self.root / 'synthetic-game'), 'report': str(self.root / 'synthetic-report'),
                'game_started': True, 'stop_requested': stop,
                'guard': {'reason': reason},
                'stages': [{'stage': 'race', 'guard': {'reason': reason}, 'exit_code': code}],
                'display_restore': {'verified': restored},
                'diagnostics': 'x' * 100000}

    def test_closed_session_returns_compact_summary_without_diagnostics_or_dialog(self):
        process, result = self.run_ui(self.session())
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result['kind'], 'later-game-session-result')
        self.assertEqual(result['status'], 'closed')
        self.assertTrue(result['game_started'])
        self.assertFalse(result['stop_requested'])
        self.assertNotIn('diagnostics', result)
        self.assertEqual(result['game_path'], str(self.root / 'synthetic-game'))

    def test_native_exit_errors_remain_errors_even_if_stop_was_requested(self):
        for code in (1, 3221225477):
            with self.subTest(code=code):
                process, result = self.run_ui(self.session(code=code, stop=True))
                self.assertEqual(process.returncode, 1)
                self.assertEqual(result['status'], 'error')
                self.assertIn(str(code), result['message'])
                self.assertTrue(result['stop_requested'])

    def test_cooperative_stop_propagates_token_and_returns_stopped(self):
        token = '1' * 32
        process, result = self.run_ui(self.session(code=None, reason='user_requested_stop', stop=True),
                                     '-ControlToken', token)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result['status'], 'stopped')
        args = json.loads((self.tools / 'arguments.json').read_text())
        self.assertEqual(args[args.index('--control-token') + 1], token)
        self.assertEqual(args[args.index('--profile') + 1], 'hd1080')

    def test_hang_and_display_restore_failure_are_not_hidden_as_normal_stops(self):
        for session in (self.session(code=None, reason='unresponsive'),
                        self.session(code=None, reason='user_requested_stop', restored=False, stop=True)):
            process, result = self.run_ui(session)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(result['status'], 'error')

    def test_deadline_and_hotkey_remain_expected_stops(self):
        for reason in ('time_limit', 'emergency_hotkey'):
            process, result = self.run_ui(self.session(code=None, reason=reason))
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(result['status'], 'stopped')

    def test_backend_failure_is_compact_error_without_native_process_start(self):
        process, result = self.run_ui({'error': 'synthetic failure'}, backend_exit=1)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(result['status'], 'error')
        self.assertFalse(result['game_started'])

    def test_missing_runtime_fails_before_backend_and_has_no_personal_runtime_literal(self):
        process, result = self.run_ui({}, python=self.root / 'missing/python.exe')
        self.assertEqual(process.returncode, 1)
        self.assertEqual(result['status'], 'error')
        self.assertFalse((self.tools / 'arguments.json').exists())
        source = (ROOT / 'tools/Start-LaterGame.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('.cache/codex-runtimes', source)
        self.assertNotIn('.cache\\codex-runtimes', source)


if __name__ == '__main__':
    unittest.main()
