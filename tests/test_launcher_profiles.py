from copy import deepcopy
from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch
from tools import launcher_model as model


class LauncherProfileTests(unittest.TestCase):
    def test_ii_cli_defaults_to_full_hd_and_preserves_explicit_resolution(self):
        base = ['launcher_model.py', 'save', '--game', 'a2racer2', '--graphics', 'native',
                '--fps', '0', '--dashboard', '-1', '--intro', '0', '--debug', '0',
                '--menu-profile', 'revival', '--race-display', 'widescreen']
        for supplied, expected in (([], '1080p'), (['--race-resolution', '720p'], '720p')):
            with self.subTest(expected=expected), patch('sys.argv', base + supplied), \
                    patch.object(model, 'save_preferences', return_value={}) as save, redirect_stdout(io.StringIO()):
                self.assertEqual(model.main(), 0)
                choice = model.validate_preferences('a2racer2', save.call_args.args[2])
                self.assertEqual(choice['race_resolution'], expected)

    def test_ii_profiles_keep_the_stable_menu_and_defaults(self):
        defaults = deepcopy(model.DEFAULT_SETTINGS)
        for profile in model.II_PROFILES.values():
            choice = model.validate_preferences('a2racer2', profile['preferences'])
            self.assertFalse(choice['debug'])
            self.assertEqual(choice['menu_profile'], 'revival')
        self.assertEqual(model.II_PROFILES['recommended']['preferences'], defaults['games']['a2racer2'])
        self.assertEqual(model.II_PROFILES['recommended']['preferences']['race_resolution'], '1080p')
        original = model.II_PROFILES['original']['preferences']
        self.assertEqual((original['race_display'], original['sky_mode'], original['race_distance']), ('classic', 'original', 'auto'))
        maximum = model.II_PROFILES['max']['preferences']
        self.assertEqual((maximum['race_resolution'], maximum['race_hud'], maximum['race_distance']), ('4k', 'hd', '60'))
        self.assertEqual(defaults, model.DEFAULT_SETTINGS)

    def test_profiles_are_valid_and_do_not_change_defaults(self):
        defaults = deepcopy(model.DEFAULT_SETTINGS)
        for profile in model.I_PROFILES.values():
            choice = model.validate_preferences('a2racer1', profile['preferences'])
            self.assertFalse(choice['debug'])
            self.assertTrue(choice['dashboard'])
        self.assertEqual(defaults, model.DEFAULT_SETTINGS)
        recommended = model.I_PROFILES['recommended']['preferences']
        self.assertEqual(recommended, defaults['games']['a2racer1'])
        self.assertEqual(recommended['texture_profile'], 'original')
        original = model.I_PROFILES['original']['preferences']
        self.assertEqual(original['display_profile'], 'original')
        self.assertEqual(original['native_horizon'], 1)
        maximum = model.I_PROFILES['max']['preferences']
        self.assertEqual(maximum['fps'], 30)
        self.assertEqual(maximum['display_profile'], 'hd-3840x2160-camera')
        self.assertEqual(maximum['object_distance_profile'], 'loaded-all')
        self.assertEqual(maximum['texture_profile'], 'hd-revival-v1')
        self.assertEqual(maximum['menu_profile'], 'hd-fullscreen')
