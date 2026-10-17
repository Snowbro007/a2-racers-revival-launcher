from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
from tools import i_frontend_state as model
from tools import launcher_model as launcher

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = dict(GELUID=0, RESOLUTIE=1, VIEW=1, DISPLAY_MODE=0, HORIZON=0,
               DASHBORD=1, DETAIL=1, CAMERA=0, VMUZIEK=3, VEFFECT=4)


def fixture():
    folder = ROOT / 'local/test-fixtures';folder.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix='i-hd-menu-', dir=folder)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = model.mutate(model.initial_state(), 'new', {'name': 'Robin'})

    def pending(self):
        data, pending = model.race_input(self.state, OPTIONS)
        self.state['pending'] = pending
        return data, pending['token']

    def test_first_race_has_native_contract_and_resets_finish(self):
        data, _ = self.pending()
        self.assertIn(b'RACE_KLAAR=0', data)
        self.assertIn(b'ETAPPE=0', data)
        self.assertIn(b'GELD=1000', data)
        self.assertIn(b'KEY_GAS=38', data)
        self.assertIn(b'DASHBORD=1', data)
        self.assertIn(b'RACER_5=5', data)

    def test_completed_stage_updates_once_and_keeps_native_position_order(self):
        data, token = self.pending()
        data = data.replace(b'RACE_KLAAR=0', b'RACE_KLAAR=1').replace(b'TIJD=0', b'TIJD=720')
        data = data.replace(b'POSITIE=0', b'POSITIE=6').replace(b'GELD=1000', b'GELD=1250')
        result = model.finish_race(self.state, data, token, 0)
        p = model.profile(result)
        self.assertEqual((p['stage'], p['times'], p['money']), (1, [720], 1250))
        next_input, _ = model.race_input(result, OPTIONS)
        self.assertIn(b'ETAPPE=1', next_input)
        self.assertIn(b'RACER_1=0', next_input)
        self.assertIsNotNone(self.state['pending'])
        with self.assertRaises(ValueError):model.finish_race(result, data, token, 0)

    def test_crash_and_abort_preserve_progress_and_budget(self):
        data, token = self.pending()
        for exit_code in (-1073741819, 0):
            result = model.finish_race(self.state, data, token, exit_code)
            self.assertEqual(model.profile(result), model.profile(self.state))
            self.assertIsNone(result['pending'])

    def test_wrong_token_stage_slot_and_incomplete_positions_refused(self):
        data, token = self.pending()
        cases = [(data, '0'*32), (data.replace(b'ETAPPE=0', b'ETAPPE=1'), token),
                 (data.replace(b'ACTIVE_SLOT=0', b'ACTIVE_SLOT=1'), token),
                 (data.replace(b'RACE_KLAAR=0', b'RACE_KLAAR=1').replace(b'TIJD=0', b'TIJD=1'), token)]
        for raw, identity in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                model.finish_race(self.state, raw, identity, 0)

    def test_six_stages_then_restart_preserves_identity(self):
        for _ in range(6):
            data, token = self.pending()
            data = data.replace(b'RACE_KLAAR=0', b'RACE_KLAAR=1').replace(b'TIJD=0', b'TIJD=600')
            # This fixture gives consistent finished ranks for every stage.
            for i in range(1, 6):
                import re
                data = re.sub(rb'RACER_'+str(i).encode()+rb'=[0-9]+', b'RACER_'+str(i).encode()+b'='+str(i).encode(), data)
            data = data.replace(b'POSITIE=0', b'POSITIE=6')
            self.state = model.finish_race(self.state, data, token, 0)
        with self.assertRaises(ValueError):model.race_input(self.state, OPTIONS)
        identity = self.state['selected'];self.state = model.mutate(self.state, 'restart', {})
        self.assertEqual((self.state['selected'], model.profile(self.state)['stage']), (identity, 0))

    def test_name_and_key_validation(self):
        for name in ('', ' ', 'x'*16, 'newline\n'):
            with self.assertRaises(ValueError):model.mutate(self.state, 'new', {'name': name})
        for keys in ({**model.KEYS, 'KEY_GAS': 37}, {**model.KEYS, 'KEY_GAS': 115}):
            with self.assertRaises(ValueError):model.mutate(self.state, 'keys', {'keys': keys})
        self.assertEqual(model.profile(model.mutate(self.state, 'new', {'name': 'Röbin'}))['name'], 'Röbin')

    def test_pending_prevents_menu_mutations(self):
        self.pending()
        with self.assertRaises(ValueError):model.mutate(self.state, 'restart', {})
        with self.assertRaises(ValueError):model.mutate(self.state, 'clear_scores', {'confirmed': True})
        with self.assertRaises(ValueError):model.race_input(self.state, OPTIONS)

    def test_clear_all_scores_preserves_campaign_and_accepts_new_results(self):
        self.state = model.mutate(self.state, 'new', {'name': 'Frits'})
        for p in self.state['profiles']:
            p.update(stage=2, times=[600, 720], money=1500)
        before = copy.deepcopy(self.state)
        for confirmed in (None, False, 1, 'yes'):
            with self.assertRaises(ValueError):
                model.mutate(self.state, 'clear_scores', {'confirmed': confirmed})
        self.assertEqual(self.state, before)
        self.state = model.mutate(self.state, 'clear_scores', {'confirmed': True})
        for old, p in zip(before['profiles'], self.state['profiles']):
            self.assertEqual({k:v for k,v in p.items() if k != 'score_start'},
                             {k:v for k,v in old.items() if k != 'score_start'})
            self.assertEqual(p['times'][p['score_start']:], [])
        self.assertEqual(self.state['keys'], before['keys'])
        data, token = self.pending()
        data = data.replace(b'RACE_KLAAR=0', b'RACE_KLAAR=1').replace(b'TIJD=0', b'TIJD=900').replace(b'POSITIE=0', b'POSITIE=6')
        import re
        for i in range(1, 6):
            data = re.sub(rb'RACER_'+str(i).encode()+rb'=[0-9]+', b'RACER_'+str(i).encode()+b'='+str(i).encode(), data)
        p = model.profile(model.finish_race(self.state, data, token, 0))
        self.assertEqual(p['times'][p['score_start']:], [900])
        self.assertEqual(p['stage'], 3)

    def test_legacy_migration_and_score_boundary_validation(self):
        legacy = copy.deepcopy(self.state);legacy['schema'] = 1
        for p in legacy['profiles']:del p['score_start']
        before = copy.deepcopy(legacy)
        upgraded = model.validate_state(legacy)
        self.assertEqual(legacy, before)
        self.assertEqual(upgraded['schema'], 2)
        self.assertEqual(model.profile(upgraded)['score_start'], 0)
        for boundary in (-1, 1, True):
            invalid = copy.deepcopy(upgraded);model.profile(invalid)['score_start'] = boundary
            with self.assertRaises(ValueError):model.validate_state(invalid)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = fixture();self.addCleanup(self.temp.cleanup);self.root = Path(self.temp.name)
        self.base = self.root / 'local/experiments/a2racer1/fixture';(self.base / 'game').mkdir(parents=True)
        self.cfg = {'schema': 1, 'game': 'a2racer1', 'native_menu_used': False, 'options': OPTIONS,
                    'display': '1920x1080', 'state_path': str(self.root / 'local/launcher/i-hd-menu/players.json')}
        (self.base / 'Frontend.json').write_text(json.dumps(self.cfg))

    def test_check_writes_nothing_and_state_survives_new_trial(self):
        model.dispatch(self.base, 'check', {})
        self.assertFalse(Path(self.cfg['state_path']).exists())
        result = model.dispatch(self.base, 'new', {'name': 'Robin'})['state']
        self.assertEqual(model.dispatch(self.base, 'check', {})['state'], result)
        model.dispatch(self.base, 'start', {})
        reset = model.dispatch(self.base, 'load', {})['state']
        self.assertIsNone(reset['pending'])
        self.assertEqual(model.profile(reset)['money'], 1000)

    def test_transaction_restores_ini_if_saving_fails(self):
        model.dispatch(self.base, 'new', {'name': 'Robin'})
        path = self.base / 'game/INFIO.INI';path.write_bytes(b'synthetic previous result')
        before = Path(self.cfg['state_path']).read_bytes()
        with patch.object(model, 'save', side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):model.dispatch(self.base, 'start', {})
        self.assertEqual(path.read_bytes(), b'synthetic previous result')
        self.assertEqual(Path(self.cfg['state_path']).read_bytes(), before)

    def test_legacy_check_is_read_only_and_clear_persists_with_backup(self):
        state = model.mutate(model.initial_state(), 'new', {'name': 'Robin'})
        model.profile(state).update(stage=1, times=[600])
        state['schema'] = 1
        for p in state['profiles']:del p['score_start']
        path = Path(self.cfg['state_path']);path.parent.mkdir(parents=True)
        before = json.dumps(state).encode('ascii');path.write_bytes(before)
        self.assertEqual(model.dispatch(self.base, 'check', {})['state']['schema'], 2)
        self.assertEqual(path.read_bytes(), before)
        model.dispatch(self.base, 'clear_scores', {'confirmed': True})
        self.assertEqual(path.with_name('players.previous.json').read_bytes(), before)
        loaded = model.dispatch(self.base, 'check', {})['state']
        self.assertEqual(model.profile(loaded)['score_start'], 1)
        self.assertEqual(model.profile(loaded)['times'], [600])

    def test_source_or_external_state_path_refused(self):
        with self.assertRaises(ValueError):model.dispatch(self.root / 'local/games/a2racer1', 'check', {})
        self.cfg['state_path'] = str(self.root / 'local/games/a2racer1/SLOT.A2R')
        (self.base / 'Frontend.json').write_text(json.dumps(self.cfg))
        with self.assertRaises(ValueError):model.dispatch(self.base, 'new', {'name': 'Oops'})

    def test_trial_profile_never_writes_launcher_players(self):
        launcher_path = Path(self.cfg['state_path'])
        self.cfg.update(profile_scope='trial', state_path=str(self.base / 'players.json'))
        (self.base / 'Frontend.json').write_text(json.dumps(self.cfg))
        model.dispatch(self.base, 'new', {'name': 'AI Test'})
        self.assertTrue((self.base / 'players.json').is_file())
        self.assertFalse(launcher_path.exists())
        self.cfg['state_path'] = str(launcher_path)
        (self.base / 'Frontend.json').write_text(json.dumps(self.cfg))
        with self.assertRaises(ValueError):model.dispatch(self.base, 'check', {})

    def test_native_save_files_not_touched(self):
        for name in ('SLOT.A2R', 'SCORE.A2R', 'OPTIE.A2R'):(self.base / 'game' / name).write_bytes(b'preserve')
        model.dispatch(self.base, 'new', {'name': 'Robin'});model.dispatch(self.base, 'start', {})
        for name in ('SLOT.A2R', 'SCORE.A2R', 'OPTIE.A2R'):
            self.assertEqual((self.base / 'game' / name).read_bytes(), b'preserve')

    def test_wpf_buttons_name_field_and_hidden_lifetime_without_game(self):
        shell = shutil.which('pwsh')
        if not shell:self.skipTest('WPF runtime unavailable')
        self.cfg.update(python=sys.executable, files=[], synthetic_fixture=True,
                        profile_scope='trial', state_path=str(self.base / 'players.json'))
        assets = self.base / 'assets';assets.mkdir()
        def chunk(kind, data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\x20\x30\x40'))+chunk(b'IEND',b'')
        for name in model.ART:(assets / name).write_bytes(png)
        for source,target in [('i_frontend.ps1','Menu.ps1'),('i_frontend_state.py','Backend.py'),('ii_owned_session.ps1','OwnedSession.ps1')]:
            shutil.copyfile(ROOT / 'tools' / source, self.base / target)
        (self.base / 'Frontend.json').write_text(json.dumps(self.cfg))
        run = subprocess.run([str(shell),'-NoProfile','-STA','-File',str(self.base / 'Menu.ps1'),'-UiCheck'], capture_output=True, text=True, timeout=45)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        result = json.loads(run.stdout)
        self.assertFalse(result['game_started']);self.assertFalse(result['hook_started'])
        self.assertTrue(result['hidden_lifetime_passed'])
        self.assertTrue(result['score_clear_confirm_and_cancel'])


class LauncherTests(unittest.TestCase):
    def test_hd_is_optional_and_uses_new_host_with_selected_race_options(self):
        temp = fixture();self.addCleanup(temp.cleanup);root = Path(temp.name)
        settings = copy.deepcopy(launcher.DEFAULT_SETTINGS['games']['a2racer1'])
        self.assertEqual(settings['menu_profile'], 'original')
        settings.update(menu_profile='hd-fullscreen', fps=30, intro=False, texture_profile='hd-revival-v1')
        # Synthetic availability, no original game or raster assets.
        with patch.object(launcher,'game_availability',return_value={'ready':True}), patch.object(launcher,'require_texture'), patch.object(launcher,'require_menu'):
            session = launcher.create_session(root,'a2racer1',settings)
            plan = launcher.launch_plan(root, session['run_name'])
        self.assertEqual(plan['script'],'Start-IHDMenu.ps1')
        args = plan['arguments']
        self.assertNotIn('-MenuProfile',args);self.assertNotIn('-Intro',args)
        self.assertEqual(args[args.index('-RaceFPSLimit')+1],'30')
        self.assertEqual(args[args.index('-TextureProfile')+1],'hd-expanded-v1')
        self.assertEqual(args[args.index('-HudProfile')+1],'hd-cockpit-v3')


if __name__ == '__main__':unittest.main()
