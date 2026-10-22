"""Cheat preference migration and frozen plans, with synthetic availability only."""
from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import launcher_model as model


class CheatLaunchPlanTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_old_settings_and_all_presets_keep_cheats_off_without_writing(self):
        old = deepcopy(model.DEFAULT_SETTINGS)
        for game in old['games']: del old['games'][game]['cheats']
        path = self.root/'local/launcher/settings.json'; path.parent.mkdir(parents=True)
        original = json.dumps(old).encode(); path.write_bytes(original)
        restored = model.load_settings(self.root)
        for game, choices in restored['games'].items():
            self.assertFalse(any(choices['cheats'].values()))
        self.assertEqual(path.read_bytes(), original)
        for presets in (model.I_PROFILES, model.II_PROFILES):
            for preset in presets.values(): self.assertFalse(any(preset['preferences']['cheats'].values()))

    def test_active_cheats_require_own_menu_and_reject_invalid_json_types(self):
        for game, required in (('a2racer1','hd-fullscreen'), ('a2racer2','revival')):
            prefs = deepcopy(model.DEFAULT_SETTINGS['games'][game])
            prefs['cheats'].update(enabled=True, extra_money=True)
            prefs['menu_profile'] = 'original'
            with self.assertRaisesRegex(ValueError, 'Cheats vereisen'): model.validate_preferences(game,prefs)
            prefs['menu_profile'] = required
            self.assertTrue(model.validate_preferences(game,prefs)['cheats']['extra_money'])
            for value in (None, 1, {'enabled':False}, dict(prefs['cheats'],extra_money=1)):
                with self.subTest(game=game,value=value), self.assertRaises(ValueError):
                    model.validate_preferences(game,dict(prefs,cheats=value))

    def test_both_routes_freeze_explicit_cheats_independent_of_later_saved_defaults(self):
        for game, menu, script in (('a2racer1','hd-fullscreen','Start-IHDMenu.ps1'),
                                    ('a2racer2','revival','Invoke-IIFrontend.ps1')):
            prefs = deepcopy(model.DEFAULT_SETTINGS['games'][game]); prefs['menu_profile'] = menu
            prefs['cheats'].update(enabled=True, extra_money=True)
            with ExitStack() as stack:
                stack.enter_context(patch.object(model,'game_availability',return_value={'ready':True}))
                stack.enter_context(patch.object(model,'require_texture'))
                stack.enter_context(patch.object(model,'require_menu'))
                stack.enter_context(patch.object(model.ii_frontend_launcher,'availability',return_value={'available':True,'reason':'fixture'}))
                stack.enter_context(patch.object(model.ii_frontend_launcher,'registered_menu',return_value={
                    'base':str(self.root/'local/ii-parallel/ii-frontend-fixture'), 'report_path':str(self.root/'reports/fixture')}))
                stack.enter_context(patch.object(model.ii_launcher_graphics,'check_options'))
                result = model.create_session(self.root,game,prefs)
                request = Path(result['session_path'])/'request.json'; before = request.read_bytes()
                model.save_preferences(self.root,game,model.DEFAULT_SETTINGS['games'][game])
                plan = model.launch_plan(self.root,result['run_name'])
            self.assertEqual(plan['script'],script)
            arguments = plan['arguments']
            self.assertEqual(json.loads(arguments[arguments.index('-CheatsJson')+1]),prefs['cheats'])
            self.assertEqual(request.read_bytes(), before)
            self.assertFalse(any(model.load_settings(self.root)['games'][game]['cheats'].values()))
            self.assertFalse(Path(plan['trial_path']).exists())
