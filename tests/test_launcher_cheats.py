"""Synthetic optional cheats: profile grants, bridge input and save isolation."""
from copy import deepcopy
from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import launcher_cheats as cheats
from tools import i_frontend_state as one, i_frontend_prepare as prep_one
from tools import ii_frontend_state as two, ii_launcher_graphics as prep_two


class CheatPreferencesTests(unittest.TestCase):
    def test_defaults_are_off_catalogs_are_independent_and_runtime_is_not_claimed(self):
        for game in cheats.DEFAULTS:
            with self.subTest(game=game):
                self.assertFalse(cheats.active(game, cheats.DEFAULTS[game]))
                self.assertFalse(any(cheats.DEFAULTS[game].values()))
                catalog = cheats.catalog(game)
                self.assertFalse(catalog['runtime_tested'])
                catalog['defaults']['enabled'] = True
                self.assertFalse(cheats.DEFAULTS[game]['enabled'])
        self.assertEqual(cheats.catalog('a2racer1')['requires_menu'], 'hd-fullscreen')
        self.assertEqual(cheats.catalog('a2racer2')['requires_menu'], 'revival')
        self.assertFalse(cheats.catalog('a2racer3')['available'])

    def test_partial_unknown_and_nonboolean_values_are_refused_even_when_disabled(self):
        for value in ({}, None, [], {'enabled': False},
                      dict(cheats.DEFAULTS['a2racer2'], extra_money=1),
                      dict(cheats.DEFAULTS['a2racer2'], all_tracks='false'),
                      dict(cheats.DEFAULTS['a2racer2'], invincible=True)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cheats.validate('a2racer2', value)
        for game in ('other', None, []):
            with self.subTest(game=game), self.assertRaises(ValueError):
                cheats.catalog(game)
        with self.assertRaises(ValueError):
            cheats.validate('a2racer3', {'enabled': True})

    def test_master_off_and_no_selected_options_have_no_effect(self):
        state = two.initial_state()
        for flags in (dict(cheats.DEFAULTS['a2racer2'], all_tracks=True),
                      dict(cheats.DEFAULTS['a2racer2'], enabled=True)):
            self.assertFalse(cheats.active('a2racer2', flags))
            self.assertEqual(cheats.prepare_state('a2racer2', state, flags), state)

    def test_explicit_null_cli_preferences_are_rejected_before_preparation_or_check(self):
        with patch.object(sys,'argv',['prepare','--run-name','launcher-invalid','--python-path',sys.executable,
                                    '--cheats','null']), patch.object(prep_one,'prepare') as prepare, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped: prep_one.main()
            self.assertEqual(stopped.exception.code,1)
            prepare.assert_not_called()
        with patch.object(sys,'argv',['graphics','check','--cheats','null']), patch.object(prep_two,'check_options') as check, redirect_stderr(io.StringIO()):
            self.assertEqual(prep_two.main(),1)
            check.assert_not_called()


class CheatStateTests(unittest.TestCase):
    def test_i_budget_uses_existing_infio_contract_without_changing_progress(self):
        state = one.mutate(one.initial_state(), 'new', {'name': 'Racer'})
        before = deepcopy(state)
        selected = dict(cheats.DEFAULTS['a2racer1'], enabled=True, extra_money=True)
        result = cheats.prepare_state('a2racer1', state, selected)
        self.assertEqual(state, before)
        self.assertEqual(one.profile(result)['money'], 1_000_000)
        expected = deepcopy(before['profiles'][0]); expected['money'] = 1_000_000
        self.assertEqual(result['profiles'][0], expected)
        options = {key: 0 for key in ('GELUID', 'RESOLUTIE', 'VIEW', 'DISPLAY_MODE',
                   'HORIZON', 'DASHBORD', 'DETAIL', 'CAMERA', 'VMUZIEK', 'VEFFECT')}
        raw, _ = one.race_input(result, options)
        self.assertIn(b'GELD=1000000', raw)
        self.assertIn(b'ETAPPE=0', raw)

    def test_i_fresh_cheat_player_is_only_created_in_the_copy_and_large_budget_is_kept(self):
        initial = one.initial_state()
        flags = dict(cheats.DEFAULTS['a2racer1'], enabled=True, extra_money=True)
        result = cheats.prepare_state('a2racer1', initial, flags)
        self.assertEqual(initial['profiles'], [])
        self.assertEqual(one.profile(result)['name'], 'Cheatspeler')
        one.profile(result)['money'] = 2_000_000
        self.assertEqual(one.profile(cheats.prepare_state('a2racer1', result, flags))['money'], 2_000_000)

    def test_ii_grants_do_not_fabricate_records_results_or_damage_repair(self):
        state = two.initial_state()
        player = two.profile(state)
        player.update(money=17000, damage=30, next_track=1, records={'0': 12345})
        before = deepcopy(state)
        flags = {key: True for key in cheats.DEFAULTS['a2racer2']}
        result = cheats.prepare_state('a2racer2', state, flags)
        changed = two.profile(result)
        self.assertEqual(state, before)
        self.assertEqual(changed['money'], 1_000_000)
        self.assertEqual(changed['next_track'], 7)
        self.assertTrue(all(changed['upgrades'].values()))
        for key in ('id', 'name', 'car', 'damage', 'damage_mesh', 'damage_value', 'records'):
            self.assertEqual(changed[key], player[key])
        result = two.mutate(result, 'track', {'track': 6}, {})
        self.assertEqual(result['track'], 6)

    def test_ii_options_are_independent_and_apply_to_all_copied_profiles(self):
        state = two.initial_state(); state['profiles'].append(two.new_profile('Tweede'))
        for key in ('extra_money', 'all_tracks', 'all_upgrades'):
            flags = dict(cheats.DEFAULTS['a2racer2'], enabled=True, **{key: True})
            result = cheats.prepare_state('a2racer2', state, flags)
            for before, after in zip(state['profiles'], result['profiles']):
                expected = deepcopy(before)
                if key == 'extra_money': expected['money'] = 1_000_000
                if key == 'all_tracks': expected['next_track'] = 7
                if key == 'all_upgrades': expected['upgrades'] = dict.fromkeys(two.UPGRADES, True)
                self.assertEqual(after, expected)

    def test_pending_or_invalid_state_is_not_cloned_into_a_cheat_session(self):
        state = two.initial_state()
        state['pending'] = {'token': 'a'*32, 'profile': state['selected'], 'track': 0, 'car': 0}
        before = deepcopy(state)
        flags = dict(cheats.DEFAULTS['a2racer2'], enabled=True, extra_money=True)
        with self.assertRaisesRegex(ValueError, 'vorige race'):
            cheats.prepare_state('a2racer2', state, flags)
        self.assertEqual(state, before)
        state['profiles'][0]['money'] = True
        with self.assertRaises(ValueError): cheats.prepare_state('a2racer2', state, flags)


class CheatPreparationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='cheat-state-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_standalone_cli_has_no_frontend_dependencies_or_filesystem_writes(self):
        # Copy only the validator: no tools package, backend, game or source tree.
        script = self.root/'validator.py'
        script.write_bytes(Path(cheats.__file__).read_bytes())
        sentinel = self.root/'existing-save.bin'; sentinel.write_bytes(b'synthetic untouched save')
        before = {p.name:p.read_bytes() for p in self.root.iterdir()}
        for game, flags in cheats.DEFAULTS.items():
            result = subprocess.run([sys.executable,'-I','-B',str(script),'--game',game,'--cheats',json.dumps(flags)],
                                    cwd=self.root,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),flags)
            self.assertEqual(result.stderr,'')
        for payload in ('null','[]','{}','{"enabled":false,"extra_money":1}',
                        '{"enabled":false,"extra_money":false,"unknown":false}','{bad json'):
            result = subprocess.run([sys.executable,'-I','-B',str(script),'--game','a2racer1','--cheats',payload],
                                    cwd=self.root,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,1)
            self.assertEqual(result.stdout,'')
            self.assertTrue(result.stderr.strip())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_i_preparation_seals_marker_and_keeps_normal_profiles_byte_identical(self):
        (self.root/'tools').mkdir()
        for name in ('i_frontend.ps1', 'i_frontend_state.py', 'ii_owned_session.ps1'):
            (self.root/'tools'/name).write_text('synthetic source', encoding='ascii')
        art = self.root/'local/mods/a2racer1/menu-hd-v1'; art.mkdir(parents=True)
        for name in one.ART: (art/name).write_bytes(b'synthetic image')
        normal = self.root/'local/launcher/i-hd-menu/players.json'; normal.parent.mkdir(parents=True)
        state = one.mutate(one.initial_state(), 'new', {'name': 'Gewoon'})
        original = json.dumps(state, indent=2).encode(); normal.write_bytes(original)
        def fake_trial(root, game, run_name, *args, **kwargs):
            base = root/'local/experiments/a2racer1'/run_name
            (base/'game').mkdir(parents=True)
            (base/'game/OPTIE.A2R').write_bytes(struct.pack('<10H', *([0]*10)))
            (base/'game/resource.dat').write_bytes(b'synthetic resource')
            report = root/'reports'/run_name; report.mkdir(parents=True)
            return {'trial_path': str(base/'game'), 'report_path': str(report)}
        flags = dict(cheats.DEFAULTS['a2racer1'], enabled=True, extra_money=True)
        with patch.object(prep_one, 'validate_art'), patch.object(prep_one.trial_manifest, 'prepare_trial', side_effect=fake_trial):
            result = prep_one.prepare(self.root, 'launcher-cheat-one', sys.executable, cheats=flags)
        base = Path(result['base']); config = one.config(base)
        self.assertTrue(result['cheat_session'])
        self.assertEqual(config['profile_scope'], 'trial')
        self.assertEqual(Path(config['state_path']), base/'players.json')
        self.assertEqual(one.profile(one.load(base, config))['money'], 1_000_000)
        self.assertEqual(normal.read_bytes(), original)
        self.assertFalse(normal.with_name('players.previous.json').exists())
        pins = {entry['path']: entry['sha256'] for entry in config['files']}
        self.assertEqual(pins[cheats.SESSION_MARKER], hashlib.sha256((base/cheats.SESSION_MARKER).read_bytes()).hexdigest())
        # Changes/results in the copied player file never select the ordinary path.
        one.dispatch(base, 'restart', {})
        self.assertEqual(normal.read_bytes(), original)

    def ii_fixture(self):
        current = self.root/'local/ii-parallel/ii-synthetic-canonical'
        (current/'game/DATA').mkdir(parents=True); (current/'profiles').mkdir()
        (self.root/'tools').mkdir()
        payload = {'game/DATA/SPEL-WIDE.DAT': b'synthetic binary',
                   'profiles/widescreen.conf': b'synthetic profile'}
        for name in prep_two.NATIVE_ASSETS: payload['game/DATA/'+name] = b'synthetic '+name.encode()
        for name, raw in payload.items(): (current/name).write_bytes(raw)
        (current/'game/DATA/GAME.INI').write_bytes(b'[OPTIONS]\nvisiblechunks=30\n[GFX OPTIONS]\nclouds=1\n')
        (current/'game/DATA/RASER.INI').write_bytes(b'[HELPDESK]\nTWEAK_MODE=0\n')
        backend = (prep_two.frontend.RACE_DISPLAYS['widescreen']['sha256']+'\n'+
                   prep_two.frontend.RACE_DISPLAYS['widescreen']['profile_sha256']).encode()
        for name, raw in (('ii_frontend_state.py', backend), ('ii_frontend.ps1', b'synthetic menu')):
            (self.root/'tools'/name).write_bytes(raw)
        (current/'Frontend.json').write_text(json.dumps({'files': []}), encoding='utf-8')
        two.save_state(current, two.initial_state())
        mocked = patch.object(prep_two.frontend, 'registered_menu', return_value={'base': str(current)})
        mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch.object(prep_two, 'source_payload', return_value=payload)
        mocked.start(); self.addCleanup(mocked.stop)
        return current

    def test_ii_cheat_session_never_syncs_budget_records_or_unlocks_to_normal_state(self):
        current = self.ii_fixture()
        before = {p.relative_to(current): p.read_bytes() for p in current.rglob('*') if p.is_file()}
        flags = {key: True for key in cheats.DEFAULTS['a2racer2']}
        result = prep_two.prepare(self.root, 'launcher-cheat-two', prep_two.DEFAULTS, cheats=flags)
        target = Path(result['base']); state = two.load_state(target)
        self.assertEqual(two.profile(state)['next_track'], 7)
        two.profile(state).update(money=9999999, records={'6': 3000})
        two.save_state(target, state)
        sync = prep_two.sync_progress(self.root, 'launcher-cheat-two', current.name)
        self.assertEqual(sync['progress_saved'], False)
        self.assertTrue(sync['cheat_session'])
        self.assertEqual(before, {p.relative_to(current): p.read_bytes() for p in current.rglob('*') if p.is_file()})
        # Independent marker blocks merging even after the config flag disappears.
        config = json.loads((target/'Frontend.json').read_bytes())
        del config['launcher_cheats']; (target/'Frontend.json').write_text(json.dumps(config))
        self.assertFalse(prep_two.sync_progress(self.root, 'launcher-cheat-two', current.name)['progress_saved'])
        self.assertEqual(before, {p.relative_to(current): p.read_bytes() for p in current.rglob('*') if p.is_file()})

    def test_ii_missing_or_malformed_session_marker_refuses_sync_and_cheat_source_is_rejected(self):
        current = self.ii_fixture()
        flags = dict(cheats.DEFAULTS['a2racer2'], enabled=True, extra_money=True)
        result = prep_two.prepare(self.root, 'launcher-cheat-marker', prep_two.DEFAULTS, cheats=flags)
        target = Path(result['base']); marker = target/cheats.SESSION_MARKER
        for content in ('{}', '[]'):
            marker.write_text(content)
            with self.assertRaises(ValueError): prep_two.sync_progress(self.root, 'launcher-cheat-marker', current.name)
        marker.unlink()
        with self.assertRaises(ValueError): prep_two.sync_progress(self.root, 'launcher-cheat-marker', current.name)
        (current/cheats.SESSION_MARKER).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'bronregistratie'):
            prep_two.prepare(self.root, 'launcher-refused-source', prep_two.DEFAULTS)

    def test_vector_and_cheats_keep_both_sealed_file_sets_and_never_sync(self):
        current = self.ii_fixture()
        flags = dict(cheats.DEFAULTS['a2racer2'], enabled=True, extra_money=True)
        def vector_fixture(root, target):
            output = target/'synthetic-vector.txt'
            output.write_bytes(b'synthetic vector overlay; never executed')
            return {'fixture': True}, {'synthetic-vector.txt'}
        with patch('tools.ii_vector_car.checked_art', return_value={}), \
                patch('tools.ii_vector_car.prepare', side_effect=vector_fixture):
            result = prep_two.prepare(self.root, 'launcher-cheat-vector', prep_two.DEFAULTS, vector_car=True, cheats=flags)
        target = Path(result['base'])
        sealed = {row['path']: row['sha256'] for row in json.loads((target/'Frontend.json').read_bytes())['files']}
        for name in (cheats.SESSION_MARKER, 'synthetic-vector.txt'):
            self.assertEqual(sealed[name], hashlib.sha256((target/name).read_bytes()).hexdigest())
        self.assertFalse(prep_two.sync_progress(self.root, 'launcher-cheat-vector', current.name)['progress_saved'])
        self.assertFalse(prep_two.target_folder(self.root, 'launcher-refused-source').exists())


if __name__ == '__main__':
    unittest.main()
