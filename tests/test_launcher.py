"""Synthetic launcher settings, plans and Windows helper tests; no real games."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

from tools import launcher_model as lm
from tools import local_game_data, portable_test

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_ii_verified_source_does_not_require_original_menu_registration(self):
        with patch.object(lm.ii_original_launcher, 'availability', return_value={'available':False,'reason':'original menu missing'}):
            available = lm.game_availability(self.root, 'a2racer2')
        self.assertTrue(available['source_ready'])
        self.assertFalse(available['ready'])
        first = next(iter(self.pins['a2racer2']))
        (self.root/'local/games/a2racer2'/first).write_bytes(b'unsupported version')
        rejected = lm.game_availability(self.root, 'a2racer2')
        self.assertFalse(rejected['source_ready'])
        self.assertFalse(rejected['ready'])

    def setUp(self):
        parent = ROOT / "local/test-fixtures"; parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="launcher-tests-", dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        from tests.test_ii_original_launcher import install_fixture
        install_fixture(self, self.root)
        self.pins = deepcopy(lm.EXPECTED_BINARIES)
        for game, files in self.pins.items():
            for name in files:
                data = b"non-executable launcher fixture " + name.encode()
                path = self.root / "local/games" / game / name
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
                files[name] = hashlib.sha256(data).hexdigest()
            image = self.root / "local/media" / game / "iso2048/disc.iso"
            image.parent.mkdir(parents=True, exist_ok=True); image.write_bytes(b"synthetic, not a disc")
        pinned = patch.object(lm, "EXPECTED_BINARIES", self.pins); pinned.start(); self.addCleanup(pinned.stop)
        self.data_source = self.root / "local/games/a2racer1"
        essential = {}
        for name in local_game_data.SOURCE_PROFILE["essential"]:
            data = b"non-executable resource fixture " + name.encode()
            (self.data_source / name).write_bytes(data)
            essential[name] = (len(data), hashlib.sha256(data).hexdigest())
        source_profile = deepcopy(local_game_data.SOURCE_PROFILE)
        source_profile["essential"] = essential
        profile = patch.object(local_game_data, "SOURCE_PROFILE", source_profile)
        profile.start(); self.addCleanup(profile.stop)

    def test_snapshot_is_read_only_and_defaults_are_per_game(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = lm.snapshot(self.root)
        self.assertTrue(all(game["ready"] for game in result["games"].values()))
        self.assertTrue(result["games"]["a2racer2"]["experimental"])
        self.assertFalse(result['iii_preparation']['ready'])
        self.assertFalse(result['iii_preparation']['tours']['1']['source_present'])
        self.assertNotIn('a2racer3', result['settings']['games'])
        self.assertEqual(result["settings"]["games"]["a2racer1"]["fps"], 20)
        self.assertTrue(result["settings"]["games"]["a2racer1"]["dashboard"])
        self.assertEqual(result["settings"]["games"]["a2racer1"]["menu_profile"], "original")
        self.assertEqual(result["settings"]["games"]["a2racer2"]["fps"], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_settings_survive_save_for_other_game_and_defaults_are_not_mutated(self):
        initial = deepcopy(lm.DEFAULT_SETTINGS)
        first = deepcopy(initial["games"]["a2racer1"]); first.update(dashboard=False, fps=30)
        lm.save_preferences(self.root, "a2racer1", first)
        second = deepcopy(initial["games"]["a2racer2"]); second["intro"] = False
        saved = lm.save_preferences(self.root, "a2racer2", second)
        self.assertEqual(lm.load_settings(self.root), saved)
        self.assertEqual(saved["games"]["a2racer1"], first)
        self.assertEqual(saved["games"]["a2racer2"], second)
        self.assertEqual(lm.DEFAULT_SETTINGS, initial)

    def test_bad_persisted_settings_are_preserved_without_new_session(self):
        path = self.root / "local/launcher/settings.json"; path.parent.mkdir(parents=True)
        for data in (b"{}", b"not json", b" " * 16385):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                lm.create_session(self.root, "a2racer1", lm.DEFAULT_SETTINGS["games"]["a2racer1"])
            self.assertEqual(path.read_bytes(), data)
            self.assertFalse((path.parent / "sessions").exists())

    def test_untrusted_preferences_cannot_supply_code_paths_or_ii_fps(self):
        invalid = []
        for field, value in (("graphics", "../../evil.ps1"), ("graphics", []), ("fps", True),
                             ("fps", 120), ("dashboard", 1), ("intro", "false"), ("debug", 1)):
            prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs[field] = value; invalid.append(("a2racer1", prefs))
        prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer2"]); prefs["fps"] = 20; invalid.append(("a2racer2", prefs))
        prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs["script"] = "evil.ps1"; invalid.append(("a2racer1", prefs))
        for game, prefs in invalid:
            with self.subTest(prefs=prefs), self.assertRaises(ValueError):
                lm.save_preferences(self.root, game, prefs)
        self.assertFalse((self.root / "local/launcher").exists())

    def test_session_is_frozen_normal_game_is_not_time_limited_and_hd_is_real_3d(self):
        prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs.update(display_profile="hd-1280x960", camera_profile="original")
        session = lm.create_session(self.root, "a2racer1", prefs)
        folder = Path(session["session_path"]); before = (folder / "request.json").read_bytes()
        prefs["fps"] = 30; lm.save_preferences(self.root, "a2racer1", prefs)
        plan = lm.launch_plan(self.root, session["run_name"])
        args = plan["arguments"]
        self.assertEqual(plan["script"], "Invoke-A2WithIntro.ps1")
        self.assertEqual(args[args.index("-RaceFPSLimit") + 1], "20")
        self.assertEqual(args[args.index("-NativeGraphics") + 1], "accelerated-640")
        self.assertEqual(args[args.index("-DisplayProfile") + 1], "hd-1280x960")
        self.assertNotIn("-StopAtEnd", args); self.assertNotIn("-EnableGameDebug", args)
        self.assertEqual((folder / "request.json").read_bytes(), before)
        self.assertFalse(Path(plan["trial_path"]).exists())

    def test_skip_intro_uses_same_fixes_and_diagnosis_has_explicit_limits(self):
        prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs.update(intro=False, debug=True, dashboard=False)
        session = lm.create_session(self.root, "a2racer1", prefs)
        plan = lm.launch_plan(self.root, session["run_name"]); args = plan["arguments"]
        self.assertEqual(plan["script"], "Invoke-A2Trial.ps1")
        for flag in ("-OmitNativeIntro", "-AnyKeyWelcome", "-KeepNativeOptions", "-HideWatermark", "-EnableGameDebug", "-StopAtEnd"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("-NativeDashboard") + 1], "0")
        self.assertEqual(args[args.index("-DurationSeconds") + 1], "180")

    def test_all_part_i_play_routes_use_approved_start_fix_with_or_without_intro(self):
        for intro in (True, False):
            for display, profile in lm.DISPLAY_PROFILES.items():
                for renderer in lm.GRAPHICS:
                    if profile["native_graphics"] not in (None, renderer):
                        continue
                    prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"])
                    prefs.update(intro=intro, graphics=renderer, display_profile=display,
                                 camera_profile=profile["camera_profile"])
                    if renderer == "software-640":
                        prefs.update(render_distance_profile="original", race_focus_recovery=False)
                    session = lm.create_session(self.root, "a2racer1", prefs)
                    args = lm.launch_plan(self.root, session["run_name"])["arguments"]
                    with self.subTest(intro=intro, display=display, renderer=renderer):
                        self.assertEqual(args.count("-PumpLauncherMessages"), 1)
                        self.assertEqual(args.count("-LocalGameData"), 1)
                        self.assertEqual(args[args.index("-DisplayProfile") + 1], display)
                        self.assertEqual(args[args.index("-NativeGraphics") + 1], renderer)
                        self.assertEqual(args[args.index("-RaceFPSLimit") + 1], "20")
                        self.assertNotIn("-StopAtEnd", args)
                        self.assertEqual("-CameraProfile" in args, profile["camera_profile"] != "original")
                        self.assertEqual("-RaceFocusRecovery" in args, renderer == "accelerated-640")
        self.assertEqual(lm.DEFAULT_SETTINGS["games"]["a2racer1"]["display_profile"], "hd-1920x1080-camera")

    def test_ii_gets_native_route_and_separate_movie_setting(self):
        prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer2"]); prefs["intro"] = False
        prefs['menu_profile']='original'
        session = lm.create_session(self.root, "a2racer2", prefs)
        args = lm.launch_plan(self.root, session["run_name"])["arguments"]
        self.assertEqual(args, [])
        for flag in ("-RaceFPSLimit", "-NativeGraphics", "-NativeDashboard", "-GraphicsWrapper", "-StopAtEnd",
                     "-PumpLauncherMessages", "-RenderDistanceProfile", "-CameraProfile", "-NativeHorizon",
                     "-ObjectDistanceProfile", "-TextureProfile", "-RaceFocusRecovery", "-LocalGameData"):
            self.assertNotIn(flag, args)

    def test_part_i_needs_complete_local_resources_without_any_disc_image(self):
        for game in ("a2racer1", "a2racer2"):
            (self.root / "local/media" / game / "iso2048/disc.iso").unlink()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertTrue(lm.game_availability(self.root, "a2racer1")["ready"])
        self.assertTrue(lm.game_availability(self.root, "a2racer2")["ready"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        for intro in (True, False):
            prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs["intro"] = intro
            session = lm.create_session(self.root, "a2racer1", prefs)
            args = lm.launch_plan(self.root, session["run_name"])["arguments"]
            self.assertEqual(args.count("-LocalGameData"), 1)

    def test_missing_or_changed_local_resource_blocks_before_writing_session(self):
        resource = self.data_source / "A2MRC.IMG"
        original = resource.read_bytes()
        for changed in (None, original + b"changed", b"x" * len(original)):
            with self.subTest(changed=changed):
                if changed is None:
                    resource.unlink()
                else:
                    resource.write_bytes(changed)
                available = lm.game_availability(self.root, "a2racer1")
                self.assertFalse(available["ready"])
                self.assertIn("A2MRC.IMG", available["reason"])
                with self.assertRaisesRegex(ValueError, "A2MRC.IMG"):
                    lm.create_session(self.root, "a2racer1", lm.DEFAULT_SETTINGS["games"]["a2racer1"])
                self.assertFalse((self.root / "local/launcher").exists())
                resource.write_bytes(original)

    def test_frozen_session_rechecks_local_resources_without_rewriting_request(self):
        session = lm.create_session(self.root, "a2racer1", lm.DEFAULT_SETTINGS["games"]["a2racer1"])
        request = Path(session["session_path"]) / "request.json"
        before = request.read_bytes()
        (self.data_source / "A2WIN.SMK").unlink()
        with self.assertRaisesRegex(ValueError, "A2WIN.SMK"):
            lm.launch_plan(self.root, session["run_name"])
        self.assertEqual(request.read_bytes(), before)

    def test_independent_distance_object_and_resolution_choices_are_frozen(self):
        for intro in (True, False):
            for distance in lm.RENDER_DISTANCES:
                for object_distance in lm.OBJECT_DISTANCES:
                    prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"])
                    prefs.update(intro=intro, render_distance_profile=distance,
                                 object_distance_profile=object_distance, display_profile="hd-2880x2160",
                                 camera_profile="original", native_horizon=1, fps=30, race_focus_recovery=False)
                    session = lm.create_session(self.root, "a2racer1", prefs)
                    args = lm.launch_plan(self.root, session["run_name"])["arguments"]
                    with self.subTest(intro=intro, distance=distance, object_distance=object_distance):
                        self.assertEqual(args[args.index("-DisplayProfile") + 1], "hd-2880x2160")
                        self.assertEqual(args[args.index("-NativeGraphics") + 1], "accelerated-640")
                        self.assertEqual(args[args.index("-NativeHorizon") + 1], "1")
                        self.assertEqual(args[args.index("-RaceFPSLimit") + 1], "30")
                        self.assertNotIn("-RaceFocusRecovery", args)
                        self.assertNotIn("-StopAtEnd", args)
                        for flag, choice in (("-RenderDistanceProfile", distance), ("-ObjectDistanceProfile", object_distance)):
                            self.assertEqual(flag in args, choice != "original")
                            if choice != "original":
                                self.assertEqual(args[args.index(flag) + 1], choice)

    def test_schema_one_migration_is_read_only_and_preserves_all_legacy_choices(self):
        path = self.root / "local/launcher/settings.json"
        path.parent.mkdir(parents=True)
        for key, graphic in lm.LEGACY_GRAPHICS.items():
            original = {"schema": 1, "selected_game": "a2racer2", "games": {
                "a2racer1": {"graphics": key, "dashboard": False, "fps": 30, "intro": False, "debug": True},
                "a2racer2": {"graphics": "native", "dashboard": None, "fps": 0, "intro": False, "debug": False}}}
            before = json.dumps(original).encode("ascii"); path.write_bytes(before)
            result = lm.load_settings(self.root)
            with self.subTest(graphics=key):
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(result["schema"], 4)
                self.assertEqual(result["selected_game"], "a2racer2")
                self.assertEqual(result["games"]["a2racer2"], dict(original["games"]["a2racer2"],menu_profile='original',race_display='classic',developer_mode=False,vector_car=False,cheats=lm.launcher_cheats.DEFAULTS['a2racer2'],**lm.ii_launcher_graphics.DEFAULTS))
                prefs = result["games"]["a2racer1"]
                self.assertEqual(prefs["graphics"], graphic["native"])
                self.assertEqual(prefs["display_profile"], graphic["display"])
                self.assertEqual(prefs["render_distance_profile"], graphic.get("render_distance_profile", "original"))
                self.assertEqual(prefs["native_horizon"], -1)
                self.assertFalse(prefs["race_focus_recovery"])
                self.assertFalse(prefs["dashboard"])
                self.assertEqual(prefs["fps"], 30)
                self.assertFalse(prefs["intro"])
                self.assertTrue(prefs["debug"])
                self.assertEqual(prefs["object_distance_profile"], "original")
                self.assertEqual(prefs["camera_profile"], "original")
                self.assertEqual(prefs["texture_profile"], "original")
                self.assertEqual(prefs["menu_profile"], "original")

    def test_schema_one_frozen_session_uses_legacy_choices_without_rewriting_request(self):
        folder = self.root / "local/launcher/sessions/launcher-legacy-test"
        folder.mkdir(parents=True)
        request = {"schema": 1, "run_name": folder.name, "game": "a2racer1", "created_utc": "synthetic",
                   "preferences": {"graphics": "accelerated-hd-distance-10", "fps": 30, "dashboard": False,
                                   "intro": False, "debug": False}}
        before = json.dumps(request).encode("ascii")
        (folder / "request.json").write_bytes(before)
        args = lm.launch_plan(self.root, folder.name)["arguments"]
        self.assertEqual(args[args.index("-RenderDistanceProfile") + 1], "extended-10")
        self.assertEqual(args[args.index("-NativeHorizon") + 1], "-1")
        self.assertNotIn("-ObjectDistanceProfile", args)
        self.assertNotIn("-RaceFocusRecovery", args)
        self.assertNotIn("-MenuProfile", args)
        self.assertEqual(args.count("-LocalGameData"), 1)
        self.assertEqual((folder / "request.json").read_bytes(), before)

    def test_unknown_schema_and_extra_keys_are_preserved_and_rejected(self):
        path = self.root / "local/launcher/settings.json"; path.parent.mkdir(parents=True)
        malformed = []
        for schema in (0, 5, True, "2"):
            value = deepcopy(lm.DEFAULT_SETTINGS); value["schema"] = schema; malformed.append(value)
        value = deepcopy(lm.DEFAULT_SETTINGS); value["games"]["a2racer1"]["script"] = "evil.ps1"; malformed.append(value)
        value = deepcopy(lm.DEFAULT_SETTINGS); del value["games"]["a2racer1"]["camera_profile"]; malformed.append(value)
        value = deepcopy(lm.DEFAULT_SETTINGS); value["games"]["a2racer2"]["object_distance_profile"] = "loaded-all"; malformed.append(value)
        for value in malformed:
            before = json.dumps(value).encode("ascii"); path.write_bytes(before)
            with self.subTest(value=value), self.assertRaises(ValueError):
                lm.save_preferences(self.root, "a2racer1", lm.DEFAULT_SETTINGS["games"]["a2racer1"])
            self.assertEqual(path.read_bytes(), before)

    def test_mismatched_camera_resolution_and_untrusted_new_fields_are_rejected(self):
        malformed = []
        for field, value in (("graphics", "native"), ("display_profile", "../../escape"),
                             ("camera_profile", "original"), ("render_distance_profile", []),
                             ("object_distance_profile", "max-all-memory"), ("native_horizon", True),
                             ("native_horizon", 2), ("race_focus_recovery", 1)):
            prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs[field] = value; malformed.append(prefs)
        prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs["display_profile"] = "hd-1280x960"; malformed.append(prefs)
        prefs = deepcopy(lm.DEFAULT_SETTINGS["games"]["a2racer1"]); prefs["graphics"] = "software-640"; prefs["display_profile"] = "original"; malformed.append(prefs)
        for prefs in malformed:
            with self.subTest(prefs=prefs), self.assertRaises(ValueError): lm.validate_preferences("a2racer1", prefs)
        self.assertFalse((self.root / "local/launcher").exists())

    def test_save_current_schema_migrates_only_on_explicit_save_and_preserves_other_game(self):
        path = self.root / "local/launcher/settings.json"; path.parent.mkdir(parents=True)
        original = {"schema": 1, "selected_game": "a2racer1", "games": {
            "a2racer1": {"graphics": "software-4-3", "fps": 30, "dashboard": False, "intro": False, "debug": False},
            "a2racer2": {"graphics": "native", "fps": 0, "dashboard": None, "intro": False, "debug": True}}}
        path.write_text(json.dumps(original), encoding="ascii")
        before = lm.load_settings(self.root)
        first = deepcopy(before["games"]["a2racer1"]); first["fps"] = 20
        lm.save_preferences(self.root, "a2racer1", first)
        saved = lm.load_settings(self.root)
        self.assertEqual(json.loads(path.read_text())["schema"], 4)
        self.assertEqual(saved["games"]["a2racer2"], dict(original["games"]["a2racer2"],menu_profile='original',race_display='classic',developer_mode=False,vector_car=False,cheats=lm.launcher_cheats.DEFAULTS['a2racer2'],**lm.ii_launcher_graphics.DEFAULTS))
        self.assertEqual(saved["games"]["a2racer1"], first)

    def test_cli_new_options_and_legacy_callers_save_validated_choices(self):
        base = ["launcher_model.py", "save", "--game", "a2racer1", "--graphics", "accelerated-640", "--fps", "30",
                "--dashboard", "0", "--intro", "0", "--debug", "0"]
        new = ["--display-profile", "hd-3840x2160-camera", "--camera-profile", "camera-16-9",
               "--render-distance-profile", "extended-20", "--object-distance-profile", "loaded-all",
               "--native-horizon", "0", "--race-focus-recovery", "1"]
        with patch.object(lm, "ROOT", self.root), patch.object(sys, "argv", base + new), patch("sys.stdout", io.StringIO()):
            self.assertEqual(lm.main(), 0)
        first = lm.load_settings(self.root)["games"]["a2racer1"]
        self.assertEqual(first["display_profile"], "hd-3840x2160-camera")
        self.assertEqual(first["object_distance_profile"], "loaded-all")
        self.assertTrue(first["race_focus_recovery"])
        self.assertEqual(first["native_horizon"], 0)
        self.assertEqual(first["fps"], 30)
        self.assertEqual(first["menu_profile"], "original")
        legacy = base.copy(); legacy[legacy.index("--graphics") + 1] = "accelerated-hd-distance-10"
        with patch.object(lm, "ROOT", self.root), patch.object(sys, "argv", legacy), patch("sys.stdout", io.StringIO()):
            self.assertEqual(lm.main(), 0)
        saved = lm.load_settings(self.root)["games"]["a2racer1"]
        self.assertEqual(saved["render_distance_profile"], "extended-10")
        self.assertEqual(saved["native_horizon"], -1)
        self.assertFalse(saved["race_focus_recovery"])
        self.assertEqual(saved["object_distance_profile"], "original")
        self.assertEqual(saved["menu_profile"], "original")

    def test_cli_partial_new_options_or_part_ii_extras_fail_without_writes(self):
        base = ["launcher_model.py", "save", "--game", "a2racer1", "--graphics", "accelerated-640", "--fps", "20",
                "--dashboard", "1", "--intro", "1", "--debug", "0"]
        combinations = [base + ["--object-distance-profile", "loaded-all"],
                        base + ["--native-horizon", "0", "--race-focus-recovery", "1"],
                        ["launcher_model.py", "save", "--game", "a2racer2", "--graphics", "native", "--fps", "0",
                         "--dashboard", "-1", "--intro", "1", "--debug", "0", "--object-distance-profile", "original"]]
        for arguments in combinations:
            with self.subTest(arguments=arguments), patch.object(lm, "ROOT", self.root), patch.object(sys, "argv", arguments), patch("sys.stderr", io.StringIO()):
                self.assertEqual(lm.main(), 1)
            self.assertFalse((self.root / "local/launcher").exists())

    def test_changed_binary_blocks_but_ii_image_is_not_required(self):
        prefs = lm.DEFAULT_SETTINGS["games"]["a2racer1"]
        session = lm.create_session(self.root, "a2racer1", prefs)
        binary = self.root / "local/games/a2racer1/A2.EXE"; binary.write_bytes(b"changed fixture")
        with self.assertRaisesRegex(ValueError, "binaryversie"):
            lm.launch_plan(self.root, session["run_name"])
        with self.assertRaises(ValueError): lm.create_session(self.root, "a2racer1", prefs)
        (self.root / "local/media/a2racer2/iso2048/disc.iso").unlink()
        self.assertTrue(lm.game_availability(self.root, "a2racer2")["ready"])

    def test_session_name_and_extra_request_fields_are_rejected(self):
        for name in ("../escape", "launcher-../../outside", "other-session"):
            with self.subTest(name=name), self.assertRaises(ValueError): lm.launch_plan(self.root, name)
        session = lm.create_session(self.root, "a2racer1", lm.DEFAULT_SETTINGS["games"]["a2racer1"])
        path = Path(session["session_path"]) / "request.json"
        request = json.loads(path.read_text()); request["script"] = "evil.ps1"; path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError, "startverzoek"): lm.launch_plan(self.root, session["run_name"])

    def test_last_session_survives_reopen_and_never_returns_a_report_path(self):
        session = lm.create_session(self.root, "a2racer1", lm.DEFAULT_SETTINGS["games"]["a2racer1"])
        self.assertIsNone(lm.latest_session(self.root))
        status = Path(session["session_path"]) / "status.json"
        status.write_text(json.dumps({"run_name": session["run_name"], "state": "finished", "report_path": "../../outside"}))
        self.assertEqual(lm.snapshot(self.root)["latest_session"], session["run_name"])
        status.write_text("[]")
        self.assertIsNone(lm.latest_session(self.root))

    @unittest.skipUnless(os.name == "nt", "Windows process helper")
    def test_process_guard_is_scoped_without_querying_or_stopping_processes(self):
        script = self.root / "process-fixture.ps1"
        script.write_text(r'''param([string]$Common,[string]$Fixture)
Set-StrictMode -Version Latest; $ErrorActionPreference = 'Stop'
. $Common
$now=[DateTime]::UtcNow
# No operating-system process is queried or stopped in this fixture.
$script:processFixtures=@(
  [PSCustomObject]@{Id=11; Path=(Join-Path $Fixture 'own.exe'); StartTime=$now; HasExited=$false},
  [PSCustomObject]@{Id=12; Path=(Join-Path ($Fixture+'-neighbor') 'other.exe'); StartTime=$now; HasExited=$false},
  [PSCustomObject]@{Id=13; Path=(Join-Path $Fixture 'old.exe'); StartTime=$now.AddSeconds(-5); HasExited=$false},
  [PSCustomObject]@{Id=14; Path=(Join-Path $Fixture 'closed.exe'); StartTime=$now; HasExited=$true})
function Get-Process { $script:processFixtures }
@{owned=@(Get-LauncherProcesses $Fixture $now.AddSeconds(-1) | ForEach-Object {$_.Id})} | ConvertTo-Json -Compress
''', encoding="utf-8-sig")
        runtime = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(runtime), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                 "-Common", str(ROOT / "tools/launcher_common.ps1"), "-Fixture", str(self.root)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip())["owned"], [11])

    @unittest.skipUnless(os.name == "nt", "Windows WPF image loading")
    def test_cover_artwork_loads_from_moved_folder_and_releases_file(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        data = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"\0\x10\x20\x30")) + chunk(b"IEND", b""))
        first = self.root / "first location"; first.mkdir()
        artwork = first / "synthetic.png"; artwork.write_bytes(data)
        moved = self.root / "Moved A2 é"; first.rename(moved)
        artwork = moved / "synthetic.png"
        script = self.root / "cover-load.ps1"
        script.write_text(r'''param($Source, $Common, $Artwork)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
. $Common
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Launcher parser error' }
$definition=$ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Set-CoverArtwork'},$false)
if (@($definition).Count -ne 1) { throw 'Artwork loader not found' }
Invoke-Expression $definition[0].Extent.Text
$image=New-Object Windows.Controls.Image
Set-CoverArtwork $image $Artwork
$exclusive=[IO.File]::Open($Artwork,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$exclusive.Dispose()
@{width=$image.Source.PixelWidth; height=$image.Source.PixelHeight; frozen=$image.Source.IsFrozen} | ConvertTo-Json -Compress
''', encoding="utf-8-sig")
        runtime = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(runtime), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                 "-Source", str(ROOT / "tools/Show-A2Launcher.ps1"), "-Common", str(ROOT / "tools/launcher_common.ps1"),
                                 "-Artwork", str(artwork)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), {"width": 1, "height": 1, "frozen": True})
        self.assertEqual(artwork.read_bytes(), data)


    @unittest.skipUnless(os.name == "nt", "Windows UI routing helper")
    def test_devtools_button_routes_only_own_viewer_and_runtime_failure_stops_launch(self):
        script = self.root / "devtools-route.ps1"
        script.write_text('''param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Parser failure' }
$definition=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Open-Devtools'},$false))[0]
Invoke-Expression $definition.Extent.Text
$script:PowerShellPath='C:\\fixture tools\\pwsh.exe'
$script:PythonPath='C:\\fixture tools\\python.exe'
$script:game='a2racer2'
$workspacePath=Split-Path -Parent (Split-Path -Parent $Source)
$script:runtimeAvailable=$true; $script:calls=@(); $script:disposed=0; $script:status=$null; $script:messages=@()
function Load-Runtimes { return $script:runtimeAvailable }
function Assert-LauncherPath([string]$Path) { if (-not $Path.EndsWith('Show-A2Devtools.ps1')) { throw 'Unexpected viewer' } }
function Set-Status([string]$Title,[string]$Message) { $script:status=$Title; $script:messages+=@($Message) }
function New-LauncherProcess([string]$Executable,[string[]]$Arguments,[switch]$Detached) {
    $script:calls+=@{executable=$Executable; arguments=@($Arguments); detached=[bool]$Detached}
    $process=New-Object PSObject
    $process | Add-Member ScriptMethod Dispose { $script:disposed++ }
    return @{process=$process}
}
Open-Devtools
$script:runtimeAvailable=$false
Open-Devtools
@{calls=@($script:calls); disposed=$script:disposed; failure=$script:status; messages=@($script:messages)} | ConvertTo-Json -Depth 5 -Compress
''', encoding="utf-8-sig")
        runtime = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(runtime), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                 "-Source", str(ROOT / "tools/Show-A2Launcher.ps1")], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip())
        self.assertEqual(len(data["calls"]), 1, data)
        call = data["calls"][0]
        self.assertTrue(call["detached"])
        self.assertEqual(call["executable"], r"C:\fixture tools\pwsh.exe")
        self.assertEqual(call["arguments"][-4:], ["-PythonPath", r"C:\fixture tools\python.exe", "-Game", "a2racer2"])
        self.assertTrue(call["arguments"][call["arguments"].index("-File") + 1].endswith("Show-A2Devtools.ps1"))
        self.assertEqual(data["disposed"], 1)
        self.assertEqual(data["failure"], "Devtools niet geopend")

    @unittest.skipUnless(os.name == "nt", "Windows argv roundtrip")
    def test_windows_arguments_are_literal_for_spaced_unicode_quotes_slashes_and_shell_characters(self):
        values = ["normal", "C:\\A2 space\\", 'quote"value', 'back\\\\"quote', "Nederland × dashboard", "$(not-a-command); & echo", ""]
        script = self.root / "argv.ps1"
        script.write_text('''param([string]$Common,[string]$Python,[string]$Values)
. $Common
$decoded = Get-Content -LiteralPath $Values -Raw | ConvertFrom-Json
$arguments = @('-c','import sys,json; print(json.dumps(sys.argv[1:]))') + @($decoded)
$info = New-Object Diagnostics.ProcessStartInfo
$info.FileName = $Python; $info.Arguments = ConvertTo-LauncherArguments $arguments
$info.UseShellExecute = $false; $info.RedirectStandardOutput = $true
$process = [Diagnostics.Process]::Start($info)
$result = $process.StandardOutput.ReadToEnd(); $process.WaitForExit()
if ($process.ExitCode -ne 0) { throw 'Synthetic argv failed' }
$result
''', encoding="utf-8-sig")
        path = self.root / "values.json"; path.write_text(json.dumps(values), encoding="ascii")
        runtime = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(runtime), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                 "-Common", str(ROOT / "tools/launcher_common.ps1"), "-Python", sys.executable,
                                 "-Values", str(path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), values)


if __name__ == "__main__":
    unittest.main()
