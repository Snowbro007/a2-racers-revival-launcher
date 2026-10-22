"""Synthetic II menu installation, launch routing and registration integrity."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ii_frontend_launcher as frontend
from tools import launcher_model as launcher
from tools import ii_portable_prepare as portable, ii_frontend_state as state


class FrontendLauncherTests(unittest.TestCase):
    def test_developer_preferences_migrate_off_and_reject_non_boolean_or_original_menu(self):
        prefs=deepcopy(launcher.DEFAULT_SETTINGS['games']['a2racer2'])
        for profile in launcher.II_PROFILES.values():
            self.assertFalse(profile['preferences']['developer_mode'])
        old={key:value for key,value in prefs.items() if key not in ('developer_mode','vector_car')}
        self.assertEqual(launcher.validate_preferences('a2racer2',old),prefs)
        for enabled in (False,True):
            self.assertIs(launcher.validate_preferences('a2racer2',dict(prefs,developer_mode=enabled))['developer_mode'],enabled)
        for value in (None,1,'on'):
            with self.assertRaises(ValueError):launcher.validate_preferences('a2racer2',dict(prefs,developer_mode=value))
        with self.assertRaisesRegex(ValueError,'Revival'):
            launcher.validate_preferences('a2racer2',dict(prefs,developer_mode=True,menu_profile='original'))

    def test_developer_session_freezes_choice_independently_of_later_saved_defaults(self):
        prefs=dict(launcher.DEFAULT_SETTINGS['games']['a2racer2'],developer_mode=True)
        with patch.object(launcher.ii_launcher_graphics,'check_options',return_value={'available':True}):
            session=launcher.create_session(self.root,'a2racer2',prefs)
            launcher.save_preferences(self.root,'a2racer2',dict(prefs,developer_mode=False))
            plan=launcher.launch_plan(self.root,session['run_name'])
        self.assertIn('-DeveloperMode',plan['arguments'])
        self.assertIn('-RunName',plan['arguments'])
        self.assertFalse(plan['debug'])
        self.assertTrue(plan['preferences']['developer_mode'])
        self.assertFalse(launcher.load_settings(self.root)['games']['a2racer2']['developer_mode'])

    def setUp(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='ii-launcher-',dir=parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.assertTrue(self.root.resolve().is_relative_to(parent.resolve()))
        self.base=self.root/'local/ii-parallel/ii-frontend-fixture'
        (self.base/'assets').mkdir(parents=True);(self.base/'game/DATA').mkdir(parents=True)
        (self.root/'tools').mkdir()
        files={name:b'synthetic script, never executed' for name in frontend.SOURCE_FILES}
        files.update({f'assets/car{i}.json':b'{}' for i in range(7)})
        files.update({f'assets/texture{i}.png':b'synthetic image' for i in range(4)})
        files.update({name:b'synthetic part image' for name in frontend.PART_ART_FILES})
        files.update({f'assets/{name}':b'synthetic asset' for name in ('wheel.json','arrow32.cur','arrow48.cur')})
        files.update({f'game/DATA/{name}':b'synthetic data' for name in ('SPEL.DAT','DDraw.dll','D3DImm.dll','dgVoodoo.conf','GARAGE.INI')})
        files.pop('game/DATA/dgVoodoo.conf')
        files.update({name:('synthetic '+name).encode() for name in frontend.RACE_DISPLAY_FILES})
        (self.base/'profiles').mkdir()
        (self.base/'game/DATA/dgVoodoo.conf').write_bytes(b'synthetic active profile')
        for name,content in files.items():(self.base/name).write_bytes(content)
        for destination,source in frontend.SOURCE_FILES.items():(self.root/'tools'/source).write_bytes(files[destination])
        for track in range(7):
            for ext in ('CMP','DMP','OMP','PMP','PTH','RMP'):(self.base/f'game/DATA/ETAPPE{track}.{ext}').write_bytes(b'synthetic map')
        entries=[{'path':name,'sha256':hashlib.sha256(content).hexdigest()} for name,content in files.items()]
        raw=json.dumps({'schema':1,'game':'a2racer2','menu_revision':37,'race_display_version':1,'native_menu_used':False,'files':entries,
                        'game_path':str(self.base/'game'),
                        'report_path':str(self.root/'reports/a2racer2-next'/self.base.name)}).encode()
        (self.base/'Frontend.json').write_bytes(raw)
        self.registration=self.base.parent/'frontend-current.json'
        self.registration.write_text(json.dumps({'schema':1,'run_name':self.base.name,'frontend_sha256':hashlib.sha256(raw).hexdigest()}))
        expected=deepcopy(frontend.EXPECTED_BINARIES)
        expected['a2racer2']['DATA/SPEL.DAT']=hashlib.sha256(files['game/DATA/SPEL.DAT']).hexdigest()
        mock=patch.object(frontend,'EXPECTED_BINARIES',expected);mock.start();self.addCleanup(mock.stop)
        displays=deepcopy(frontend.RACE_DISPLAYS)
        displays['widescreen']['sha256']=hashlib.sha256(files['game/DATA/SPEL-WIDE.DAT']).hexdigest()
        for spec in displays.values():spec['profile_sha256']=hashlib.sha256(files[spec['profile']]).hexdigest()
        mock=patch.object(frontend,'RACE_DISPLAYS',displays);mock.start();self.addCleanup(mock.stop)
        mock=patch.object(launcher.ii_launcher_graphics,'check_options',return_value={'available':True});mock.start();self.addCleanup(mock.stop)

    def test_recommended_menu_runs_without_source_cd_and_keeps_frozen_selection(self):
        self.assertTrue(frontend.availability(self.root)['available'])
        prefs=deepcopy(launcher.DEFAULT_SETTINGS['games']['a2racer2'])
        session=launcher.create_session(self.root,'a2racer2',prefs)
        request=Path(session['session_path'])/'request.json';before=request.read_bytes()
        launcher.save_preferences(self.root,'a2racer2',dict(prefs,menu_profile='original'))
        plan=launcher.launch_plan(self.root,session['run_name'])
        self.assertEqual(plan['script'],'Invoke-IIFrontend.ps1')
        self.assertEqual(plan['arguments'][plan['arguments'].index('-RaceResolution')+1], '1080p')
        self.assertFalse(plan['requires_disc']);self.assertEqual(plan['arguments'][:2],['-RaceDisplay','widescreen']);self.assertIn('-SkyMode',plan['arguments']);self.assertEqual(plan['arguments'][plan['arguments'].index('-SkyMode')+1],'flat')
        self.assertEqual(plan['trial_path'],str(launcher.ii_launcher_graphics.target_folder(self.root,session['run_name'])/'game'))
        self.assertEqual(request.read_bytes(),before)
        self.assertFalse((self.root/'local/media').exists())

    def stale_menu(self):
        players=state.initial_state()
        state.profile(players)['money']=123456
        state.profile(players)['records']={'0':12345}
        state.save_state(self.base,players)
        (self.root/'tools/ii_frontend_state.py').write_bytes(b'new synthetic backend; never run')
        self.assertFalse(frontend.availability(self.root)['available'])
        return {path.relative_to(self.base):path.read_bytes()
                for path in self.base.rglob('*') if path.is_file()}

    def test_prepare_refreshes_stale_own_code_in_a_new_copy_preserving_players_and_game(self):
        old=self.stale_menu()
        result=portable.prepare(self.root,'not executed',run_name='ii-frontend-refreshed')
        new=Path(result['base'])
        self.assertTrue(result['refreshed']);self.assertTrue(result['players_preserved'])
        self.assertFalse(result['native_game_executed'])
        self.assertEqual(result['previous_base'],str(self.base))
        self.assertNotEqual(new,self.base)
        for name,raw in old.items():
            self.assertEqual((self.base/name).read_bytes(),raw)
            if str(name)!='Frontend.json' and str(name) not in frontend.SOURCE_FILES:
                self.assertEqual((new/name).read_bytes(),raw)
        self.assertEqual((new/'Backend.py').read_bytes(),b'new synthetic backend; never run')
        self.assertEqual(frontend.registered_menu(self.root)['base'],str(new))
        self.assertFalse((self.registration.parent/'.frontend-refresh.lock').exists())

    def test_refresh_never_repairs_a_changed_sealed_game_file(self):
        self.stale_menu();before=self.registration.read_bytes()
        (self.base/'game/DATA/SPEL.DAT').write_bytes(b'changed synthetic game')
        with self.assertRaisesRegex(ValueError,'veranderde'):
            portable.prepare(self.root,'not executed',run_name='ii-frontend-refused')
        self.assertEqual(self.registration.read_bytes(),before)
        self.assertFalse((self.base.parent/'ii-frontend-refused').exists())

    def test_refresh_failure_before_publication_preserves_registration_and_old_state(self):
        old=self.stale_menu();before=self.registration.read_bytes()
        read=state.read_regular
        def fail_new_source(path,maximum):
            if path==self.root/'tools/ii_frontend.ps1':raise OSError('synthetic read failure')
            return read(path,maximum)
        with patch.object(state,'read_regular',side_effect=fail_new_source):
            with self.assertRaisesRegex(OSError,'synthetic read failure'):
                portable.prepare(self.root,'not executed',run_name='ii-frontend-refused')
        self.assertEqual(self.registration.read_bytes(),before)
        self.assertEqual((self.base/'menu-state.json').read_bytes(),old[Path('menu-state.json')])
        self.assertFalse((self.registration.parent/'.frontend-refresh.lock').exists())

    def test_refresh_rolls_back_its_pointer_after_final_verification_failure(self):
        self.stale_menu();before=self.registration.read_bytes()
        registered=frontend.registered_menu
        def fail_new_copy(root,**kwargs):
            current=json.loads(self.registration.read_bytes())['run_name']
            if current=='ii-frontend-refused':raise ValueError('synthetic final failure')
            return registered(root,**kwargs)
        with patch.object(frontend,'registered_menu',side_effect=fail_new_copy):
            with self.assertRaisesRegex(ValueError,'synthetic final failure'):
                portable.prepare(self.root,'not executed',run_name='ii-frontend-refused')
        self.assertEqual(self.registration.read_bytes(),before)
        self.assertFalse((self.registration.parent/'.frontend-refresh.lock').exists())

    def test_refresh_refuses_concurrent_updates_and_unsafe_names(self):
        self.stale_menu();before=self.registration.read_bytes()
        lock=self.registration.parent/'.frontend-refresh.lock'
        lock.write_bytes(b'other update')
        with self.assertRaises(FileExistsError):
            portable.prepare(self.root,'not executed',run_name='ii-frontend-refused')
        self.assertEqual(lock.read_bytes(),b'other update')
        for name in ('../escape','wrong-prefix'):
            with self.assertRaises(ValueError):portable.refresh_menu_sources(self.root,name)
        self.assertEqual(self.registration.read_bytes(),before)

    def test_refresh_refuses_a_player_save_changed_during_copy(self):
        self.stale_menu();before=self.registration.read_bytes()
        read=state.read_regular
        changed=None
        def save_while_updating(path,maximum):
            nonlocal changed
            raw=read(path,maximum)
            if path==self.root/'tools/ii_frontend_state.py' and changed is None:
                players=state.load_state(self.base)
                state.profile(players)['money']=654321
                state.save_state(self.base,players)
                changed=(self.base/'menu-state.json').read_bytes()
            return raw
        with patch.object(state,'read_regular',side_effect=save_while_updating):
            with self.assertRaisesRegex(ValueError,'veranderde tijdens bijwerken'):
                portable.prepare(self.root,'not executed',run_name='ii-frontend-refused')
        self.assertIsNotNone(changed)
        self.assertEqual((self.base/'menu-state.json').read_bytes(),changed)
        self.assertEqual(self.registration.read_bytes(),before)

    def test_missing_or_changed_menu_blocks_before_session_write(self):
        for name in ('Menu.xaml','assets/part-motor.png','game/DATA/SPEL-WIDE.DAT','profiles/widescreen.conf'):
            path=self.base/name;original=path.read_bytes()
            for content in (None,b'changed'):
                if content is None:path.unlink()
                else:path.write_bytes(content)
                self.assertFalse(frontend.availability(self.root)['available'])
                with self.assertRaises(ValueError):launcher.create_session(self.root,'a2racer2',launcher.DEFAULT_SETTINGS['games']['a2racer2'])
                self.assertFalse((self.root/'local/launcher').exists())
                path.write_bytes(original)

    def test_changed_tool_or_missing_map_cannot_start(self):
        (self.root/'tools/ii_frontend.ps1').write_bytes(b'changed tool')
        with self.assertRaisesRegex(ValueError,'opnieuw'):frontend.registered_menu(self.root)
        (self.root/'tools/ii_frontend.ps1').write_bytes((self.base/'Menu.ps1').read_bytes())
        (self.base/'game/DATA/ETAPPE4.PTH').unlink()
        self.assertFalse(frontend.availability(self.root)['available'])

    def test_flat_sky_registration_requires_both_sealed_background_archives(self):
        config=json.loads((self.base/'Frontend.json').read_bytes())
        config['wide_race_variant']='flat-sky60'
        for name in ('RCS.IND','RCS.IMG'):
            relative='game/DATA/'+name
            content=('synthetic flat background '+name).encode()
            (self.base/relative).write_bytes(content)
            config['files'].append({'path':relative,'sha256':hashlib.sha256(content).hexdigest()})
        raw=json.dumps(config).encode();(self.base/'Frontend.json').write_bytes(raw)
        reg=json.loads(self.registration.read_bytes());reg['frontend_sha256']=hashlib.sha256(raw).hexdigest()
        self.registration.write_text(json.dumps(reg))
        with patch.object(frontend,'race_binary_sha',return_value=frontend.RACE_DISPLAYS['widescreen']['sha256']):
            self.assertTrue(frontend.availability(self.root)['available'])
            for name in ('RCS.IND','RCS.IMG'):
                path=self.base/'game/DATA'/name;original=path.read_bytes()
                path.write_bytes(b'changed background')
                self.assertFalse(frontend.availability(self.root)['available'])
                path.unlink()
                self.assertFalse(frontend.availability(self.root)['available'])
                path.write_bytes(original)

    def test_active_profile_switch_does_not_invalidate_frozen_choices(self):
        (self.base/'game/DATA/dgVoodoo.conf').write_bytes(b'different active selection')
        self.assertTrue(frontend.availability(self.root)['available'])

    def test_preview_revision_requires_hash_pinned_sprite(self):
        config=json.loads((self.base/'Frontend.json').read_bytes())
        config['preview_detail_revision']='20261013'
        sprite=self.base/'assets/car4-preview.png';sprite.write_bytes(b'synthetic sprite')
        config['files'].append({'path':'assets/car4-preview.png','sha256':hashlib.sha256(sprite.read_bytes()).hexdigest()})
        raw=json.dumps(config).encode();(self.base/'Frontend.json').write_bytes(raw)
        reg=json.loads(self.registration.read_bytes());reg['frontend_sha256']=hashlib.sha256(raw).hexdigest()
        self.registration.write_text(json.dumps(reg),encoding='utf-8')
        self.assertTrue(frontend.availability(self.root)['available'])
        sprite.write_bytes(b'changed sprite')
        self.assertFalse(frontend.availability(self.root)['available'])
        sprite.unlink()
        self.assertFalse(frontend.availability(self.root)['available'])

    def test_registry_cannot_supply_arbitrary_paths(self):
        initial=json.loads(self.registration.read_bytes())
        for name in ('../../tools','unknown-run',r'C:\evil'):
            self.registration.write_text(json.dumps(dict(initial,run_name=name)))
            with self.assertRaises(ValueError):frontend.registered_menu(self.root)

    def test_sealed_manifest_with_stale_copy_paths_is_not_ready(self):
        config=json.loads((self.base/'Frontend.json').read_bytes())
        for key in ('game_path','report_path'):
            changed=dict(config, **{key:str(self.root/'previous-copy')})
            raw=json.dumps(changed).encode()
            (self.base/'Frontend.json').write_bytes(raw)
            reg=json.loads(self.registration.read_bytes())
            reg['frontend_sha256']=hashlib.sha256(raw).hexdigest()
            self.registration.write_text(json.dumps(reg))
            self.assertFalse(frontend.availability(self.root)['available'])
            self.assertFalse((self.root/'local/launcher').exists())

    def test_fleet_contract_requires_every_sealed_preview(self):
        config=json.loads((self.base/'Frontend.json').read_text())
        config['fleet_preview_revision']='20261013'
        for index in range(7):
            name=f'assets/car{index}-preview.png'
            content=f'synthetic preview {index}'.encode()
            (self.base/name).write_bytes(content)
            config['files'].append({'path':name,'sha256':hashlib.sha256(content).hexdigest()})
        raw=json.dumps(config).encode();(self.base/'Frontend.json').write_bytes(raw)
        reg=json.loads(self.registration.read_text());reg['frontend_sha256']=hashlib.sha256(raw).hexdigest()
        self.registration.write_text(json.dumps(reg))
        self.assertTrue(frontend.availability(self.root)['available'])
        (self.base/'assets/car1-preview.png').unlink()
        self.assertFalse(frontend.availability(self.root)['available'])

    def test_old_five_field_preferences_keep_original_route(self):
        value={k:v for k,v in launcher.DEFAULT_SETTINGS['games']['a2racer2'].items() if k in launcher.LEGACY_PREFERENCE_KEYS}
        value['intro']=True
        restored=launcher.validate_preferences('a2racer2',value)
        self.assertEqual(restored['menu_profile'],'original');self.assertTrue(restored['intro'])
        self.assertEqual(frontend.MENU_PROFILES['original']['label'],'Origineel menu · gerestaureerd · unstable (Alt+Tab)')
        self.assertEqual(frontend.MENU_PROFILES['revival']['label'],'Revival-menu (aanbevolen)')

    def test_previous_preferences_migrate_and_display_selection_is_frozen(self):
        prefs=deepcopy(launcher.DEFAULT_SETTINGS['games']['a2racer2'])
        previous={k:v for k,v in prefs.items() if k in launcher.LEGACY_PREFERENCE_KEYS | {'menu_profile'}}
        self.assertEqual(launcher.validate_preferences('a2racer2',previous)['race_display'],'widescreen')
        prefs['race_display']='classic'
        session=launcher.create_session(self.root,'a2racer2',prefs)
        launcher.save_preferences(self.root,'a2racer2',dict(prefs,race_display='widescreen'))
        self.assertEqual(launcher.launch_plan(self.root,session['run_name'])['arguments'][:2],['-RaceDisplay','classic'])
        for invalid in (None, True, 'stretched'):
            with self.assertRaises(ValueError):launcher.validate_preferences('a2racer2',dict(prefs,race_display=invalid))


if __name__=='__main__':unittest.main()
