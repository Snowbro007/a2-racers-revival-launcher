"""Synthetic no-disc native-menu registration and frozen launcher routing."""
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from tools import ii_original_launcher as native, launcher_model as launcher

def install_fixture(case, root):
    pins = {}
    for relative in native.PINS:
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({'files': []}).encode() if relative.endswith('.json') else b'synthetic host, never executed'
        path.write_bytes(raw)
        pins[relative] = hashlib.sha256(raw).hexdigest()
    mock = patch.object(native, 'PINS', pins)
    mock.start()
    case.addCleanup(mock.stop)

class OriginalMenuTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        install_fixture(self, self.root)

    def test_registration_needs_no_image_and_refuses_changed_host(self):
        self.assertTrue(native.availability(self.root)['available'])
        self.assertFalse((self.root/'local/media').exists())
        (self.root/next(iter(native.PINS))).write_bytes(b'changed host')
        self.assertFalse(native.availability(self.root)['available'])

    def test_original_frozen_plan_uses_owned_host_without_mount_or_timer(self):
        folder = self.root/'local/launcher/sessions/launcher-synthetic'
        folder.mkdir(parents=True)
        prefs = deepcopy(launcher.DEFAULT_SETTINGS['games']['a2racer2'])
        prefs['menu_profile'] = 'original'
        request = dict(schema=4, run_name=folder.name, game='a2racer2', preferences=prefs, created_utc='synthetic')
        (folder/'request.json').write_text(json.dumps(request))
        plan = launcher.launch_plan(self.root, folder.name)
        self.assertEqual(plan['script'], 'Invoke-IIOriginalMenu.ps1')
        self.assertFalse(plan['requires_disc'])
        self.assertEqual(plan['arguments'], [])
        self.assertEqual(Path(plan['trial_path']).name, 'game')

    def test_runner_has_no_disc_mount_and_adapter_can_check_without_start(self):
        root = Path(__file__).resolve().parents[1]
        self.assertNotIn('Mount-A2Disc.ps1', (root/'tools/Invoke-A2LauncherSession.ps1').read_text())
        adapter = (root/'tools/Invoke-IIOriginalMenu.ps1').read_text()
        self.assertIn('-CheckOnly:$CheckOnly', adapter)
        self.assertIn("$env:II_PROBE_NONINTERACTIVE='1'", adapter)
