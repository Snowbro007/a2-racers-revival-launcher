"""Synthetic persistent native menu, manifest guards and frozen routing."""
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from tools import ii_original_launcher as native, launcher_model as launcher
from tools import ii_original_prepare as builder, ii_portable_prepare as portable

MENU = b'synthetic menu; never executable'
RACE = b'synthetic race; never executable'
PROFILE = b'[GeneralExt]\r\nFPSLimit=0\r\n[DirectXExt]\r\nPrimarySurfaceBatchedUpdate=false\r\n'
RASER = b'[PROGRAM]\r\nRESOLUTION=3\r\n[SOUND]\r\nMUSICVOLUME=0\r\nSFXVOLUME=100\r\n[MOVIES]\r\nON=0\r\n'


def install_fixture(case, root):
    for module, name, value in ((native, 'PATCHED_SHA256', portable.sha(MENU)),
                                (builder, 'MENU_PROFILE_SHA256', portable.sha(PROFILE))):
        mock = patch.object(module, name, value); mock.start(); case.addCleanup(mock.stop)
    pins = deepcopy(native.EXPECTED_BINARIES)
    pins['a2racer2']['DATA/SPEL.DAT'] = portable.sha(RACE)
    mock = patch.object(native, 'EXPECTED_BINARIES', pins); mock.start(); case.addCleanup(mock.stop)
    base = root/'local/ii-parallel/ii-original-a3-v1-synthetic'
    payload = {'DATA/MENU.DAT': MENU, 'DATA/SPEL.DAT': RACE,
               'DATA/RASER.INI': RASER, 'DATA/dgVoodoo.conf': PROFILE}
    for name in ('DDraw.dll', 'D3DImm.dll', 'MENURC.IMG', 'MENURC.IND', 'RCS.IMG', 'RCS.IND'):
        payload['DATA/'+name] = b'synthetic '+name.encode()
    for name, raw in payload.items():
        path = base/'game'/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    (base/'profiles').mkdir()
    race = builder.race_profile(PROFILE)
    for name, raw in {'menu.conf': PROFILE, 'race.conf': race, 'RASER.INI': RASER}.items():
        (base/'profiles'/name).write_bytes(raw)
    config = {'schema': 1, 'revision': builder.REVISION, 'game': 'a2racer2',
              'menu_sha256': portable.sha(MENU),
              'profiles': {'menu': portable.sha(PROFILE), 'race': portable.sha(race)},
              'files': [{'path': name, 'size': len(raw), 'sha256': portable.sha(raw)} for name, raw in payload.items()]}
    raw = portable.encoded(config); (base/'Original.json').write_bytes(raw)
    (base.parent/'original-current.json').write_bytes(portable.encoded({
        'schema': 1, 'run_name': base.name, 'manifest_sha256': portable.sha(raw)}))
    return base


class OriginalMenuTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'local/test-fixtures'; parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.base = install_fixture(self, self.root)

    def test_registration_is_portable_and_refuses_changed_code_and_profiles(self):
        self.assertTrue(native.availability(self.root)['available'])
        self.assertFalse((self.root/'local/media').exists())
        (self.base/'game/DATA/MENU.DAT').write_bytes(b'changed menu')
        self.assertFalse(native.availability(self.root)['available'])

    def test_stage_switch_and_saved_volume_survive_repeated_registration(self):
        native.select_stage(self.root, 'race')
        self.assertEqual((self.base/'game/DATA/dgVoodoo.conf').read_bytes(), builder.race_profile(PROFILE))
        (self.base/'game/DATA/RASER.INI').write_bytes(RASER.replace(b'MUSICVOLUME=0', b'MUSICVOLUME=3100'))
        (self.base/'game/DATA/player.sav').write_bytes(b'synthetic progress')
        native.select_stage(self.root, 'menu')
        self.assertTrue(native.availability(self.root)['available'])
        self.assertEqual((self.base/'game/DATA/player.sav').read_bytes(), b'synthetic progress')
        (self.base/'game/DATA/RASER.INI').write_bytes(RASER.replace(b'ON=0', b'ON=1'))
        self.assertFalse(native.availability(self.root)['available'])

    def test_registration_rejects_traversal_even_with_matching_manifest_digest(self):
        config = json.loads((self.base/'Original.json').read_bytes())
        config['files'].append({'path': '../outside.dat', 'size': 0, 'sha256': '0'*64})
        raw = portable.encoded(config); (self.base/'Original.json').write_bytes(raw)
        pin = self.base.parent/'original-current.json'; value = json.loads(pin.read_bytes())
        value['manifest_sha256'] = portable.sha(raw); pin.write_bytes(portable.encoded(value))
        with self.assertRaisesRegex(ValueError, 'Onveilig'):
            native.registered_menu(self.root)

    def test_existing_preparation_preserves_persistent_copy_without_source_or_execution(self):
        with patch.object(portable, 'inspect_source', side_effect=AssertionError('must not rebuild')):
            result = builder.prepare(self.root)
        self.assertFalse(result['prepared']); self.assertFalse(result['native_game_executed'])

    def test_original_frozen_plan_uses_owned_host_without_mount_or_timer(self):
        folder = self.root/'local/launcher/sessions/launcher-synthetic'; folder.mkdir(parents=True)
        prefs = deepcopy(launcher.DEFAULT_SETTINGS['games']['a2racer2']); prefs['menu_profile'] = 'original'
        (folder/'request.json').write_text(json.dumps(dict(schema=4, run_name=folder.name,
            game='a2racer2', preferences=prefs, created_utc='synthetic')))
        plan = launcher.launch_plan(self.root, folder.name)
        self.assertEqual(plan['script'], 'Invoke-IIOriginalMenu.ps1'); self.assertFalse(plan['requires_disc'])
        self.assertEqual(plan['arguments'], []); self.assertEqual(Path(plan['trial_path']).name, 'game')

    def test_saved_config_rejects_out_of_range_and_duplicate_values(self):
        for raw in (RASER.replace(b'SFXVOLUME=100', b'SFXVOLUME=3101'),
                    RASER.replace(b'RESOLUTION=3', b'RESOLUTION=2'),
                    RASER.replace(b'RESOLUTION=3', b'RESOLUTION=3\r\nRESOLUTION=3')):
            with self.assertRaises(ValueError): native.config_signature(raw)

    def test_runner_has_no_disc_mount_and_check_precedes_native_helper(self):
        root = Path(__file__).resolve().parents[1]
        adapter = (root/'tools/Invoke-IIOriginalMenu.ps1').read_text()
        self.assertIn('-CheckOnly:$CheckOnly', adapter)
        host = (root/'tools/ii_original_session.ps1').read_text()
        self.assertLess(host.index('if ($CheckOnly)'), host.index('Import-IIOwnedSession'))
        self.assertNotIn('maxSeconds', host); self.assertNotIn('Stopwatch', host)
        self.assertNotIn('A2_II.EXE', host); self.assertNotIn('Mount-', host)
        self.assertIn('if ($code -ne 40)', host)
        self.assertIn("Invoke-OriginalStage 'race' ''", host)
        self.assertIn('if ($session.StopRequested) { break }', host)


if __name__ == '__main__': unittest.main()
