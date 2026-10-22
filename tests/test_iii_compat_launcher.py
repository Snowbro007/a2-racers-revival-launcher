"""Synthetic directory/configuration contracts; never launch a native game."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from tools import iii_compat_launcher as launcher
from tools import iii_local_launcher as native
from tools import iii_installation as installation


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures';parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'chosen DATA'
        payload={'A2 Racer III Tour 1.exe':b'synthetic-parent','spel.dat':b'synthetic-race',
                 'MenuData/menu.exe':b'synthetic-menu',
                 'MenuData/menu.ini':b'[General]\r\nINTROAVI=\\DATA\\INTRO.AVI\r\nExitCode=40\r\n',
                 'game.ini':b'[GFX OPTIONS]\r\nclouds=1\r\n[PLAYER]\r\nName=Saved player\r\n',
                 'Raser.ini':b'[PROGRAM]\r\nRESOLUTION=0\r\n[MUSIC]\r\ncount=11\r\ncount=6\r\n'}
        self.records=[]
        for name,raw in payload.items():
            path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            self.records.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        self.wrappers={'DDraw.dll':b'synthetic-wrapper','D3DImm.dll':b'synthetic-3d','dgVoodoo.conf':b'synthetic-config'}
        for target,name,value in ((native,'CATALOG',{1:self.records}),(launcher.graphics,'SOURCE_SHA256',{1:hashlib.sha256(payload['spel.dat']).hexdigest()})):
            mocked=patch.object(target,name,value)
            mocked.start();self.addCleanup(mocked.stop)
        mocked=patch.object(launcher,'wrapper_inputs',return_value=self.wrappers);mocked.start();self.addCleanup(mocked.stop)

    def imported(self):return installation.import_folder(self.root,self.source,1)

    def test_folder_import_without_private_reports_retains_saves_and_source(self):
        (self.source/'Alice.rcr').write_bytes(b'synthetic-player-save')
        before=launcher.tree_bytes(self.source);result=self.imported()
        folder=native.game_folder(self.root,1)
        self.assertEqual(launcher.tree_bytes(self.source),before)
        self.assertEqual((folder/'Alice.rcr').read_bytes(),b'synthetic-player-save')
        self.assertEqual((folder/'game.ini').read_bytes(),before['game.ini'])
        self.assertEqual((folder/'menu.exe').read_bytes(),b'synthetic-menu')
        self.assertIn(b'INTROAVI=.\\intro.avi',(folder/'menu.ini').read_bytes())
        self.assertFalse(result['game_started']);self.assertFalse(result['disc_image_required'])
        self.assertEqual(native.prepare(self.root,1),folder)
        self.assertTrue((self.root/'local/launcher/installation-a2racer3-tour1.json').is_file())

    def test_changed_immutable_or_missing_file_never_creates_destination(self):
        (self.source/'spel.dat').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.imported()
        self.assertFalse(native.game_folder(self.root,1).exists())

    def test_reimport_does_not_overwrite_existing_player(self):
        self.imported();folder=native.game_folder(self.root,1)
        (folder/'game.ini').write_bytes(b'new saved state')
        with self.assertRaises(ValueError):self.imported()
        self.assertEqual((folder/'game.ini').read_bytes(),b'new saved state')

    def test_flat_data_subfolder_and_changed_saved_options_are_supported(self):
        (self.source/'menu.exe').write_bytes((self.source/'MenuData/menu.exe').read_bytes())
        (self.source/'menu.ini').write_bytes((self.source/'MenuData/menu.ini').read_bytes())
        (self.source/'MenuData/menu.exe').unlink();(self.source/'MenuData/menu.ini').unlink()
        (self.source/'game.ini').write_bytes(b'[PLAYER]\r\nName=Different saved player\r\n')
        disc=self.root/'chosen disc';disc.mkdir();self.source.rename(disc/'DATA');self.source=disc
        result=self.imported()
        self.assertEqual(result['tour'],1)
        self.assertIn(b'Different saved player',(native.game_folder(self.root,1)/'game.ini').read_bytes())

    def test_wrong_tour_and_duplicate_native_files_are_rejected(self):
        pin=installation.digest(self.source/'spel.dat')
        with patch.object(launcher.graphics,'SOURCE_SHA256',{2:pin}),self.assertRaisesRegex(ValueError,'Tour 2'):
            installation.inspect(self.root,self.source,1)
        (self.source/'menu.exe').write_bytes(b'synthetic-menu')
        with self.assertRaisesRegex(ValueError,'dubbel'):self.imported()

    def test_final_native_validation_failure_leaves_no_receipt_or_tour(self):
        with patch.object(native,'check_folder',side_effect=ValueError('synthetic final rejection')),self.assertRaises(ValueError):
            self.imported()
        self.assertFalse(native.game_folder(self.root,1).exists())
        self.assertFalse((self.root/'local/launcher/installation-a2racer3-tour1.json').exists())

    def test_changing_source_during_copy_rolls_back_final_candidate(self):
        original=installation.copy_file
        def copy_then_mutate(source,target):
            original(source,target)
            (self.source/'game.ini').write_bytes(b'new state')
        with patch.object(installation,'copy_file',side_effect=copy_then_mutate),self.assertRaises(ValueError):self.imported()
        self.assertFalse(native.game_folder(self.root,1).exists())
        self.assertEqual(list((self.root/'local/iii-play').iterdir()),[])

    def test_config_overrides_preserve_duplicate_music_keys_and_player_values(self):
        raw=(self.source/'Raser.ini').read_bytes()
        changed=launcher.override_ini(raw,{('PROGRAM','RESOLUTION'):3})
        self.assertEqual(changed,raw.replace(b'RESOLUTION=0',b'RESOLUTION=3'))
        for invalid in (raw.replace(b'RESOLUTION=0',b'UNKNOWN=0'),raw+b'[PROGRAM]\r\nRESOLUTION=0\r\n'):
            with self.assertRaises(ValueError):launcher.override_ini(invalid,{('PROGRAM','RESOLUTION'):3})

    def test_compat_candidate_is_separate_and_rejects_changed_binary(self):
        self.imported();seed=native.game_folder(self.root,1);before=launcher.tree_bytes(seed)
        folder=launcher.prepare(self.root,1,'compat')
        self.assertNotEqual(folder,seed);self.assertEqual(launcher.tree_bytes(seed),before)
        self.assertEqual((folder/'spel.dat').read_bytes(),b'synthetic-race')
        (folder/'game.ini').write_bytes(b'new player state')
        self.assertEqual(launcher.prepare(self.root,1,'compat'),folder)
        self.assertEqual((folder/'game.ini').read_bytes(),b'new player state')
        (folder/'spel.dat').write_bytes(b'changed')
        with self.assertRaises(ValueError):launcher.prepare(self.root,1,'compat')

    def test_manifest_cannot_authorize_unknown_executable(self):
        self.imported();folder=launcher.prepare(self.root,1,'compat')
        (folder/'unknown.exe').write_bytes(b'synthetic extra')
        with self.assertRaises(ValueError):launcher.check(self.root,1,'compat')

    def test_native_generated_font_caches_allow_restart_with_size_limits(self):
        self.imported();folder=launcher.prepare(self.root,1,'compat')
        for name in ('MenuFont1.dat','MenuFont2.dat','MenuFont1.res','MenuFont2.res'):
            (folder/name).write_bytes(b'synthetic font cache')
        self.assertEqual(launcher.prepare(self.root,1,'compat'),folder)
        (folder/'MenuFont1.dat').write_bytes(b'x'*65537)
        with self.assertRaises(ValueError):launcher.check(self.root,1,'compat')

    def test_fullhd_start_restores_only_display_options_and_reports_unverified(self):
        self.imported();output=b'synthetic-patched-race';pin=hashlib.sha256(output).hexdigest()
        with patch.object(launcher.graphics,'build',return_value=(output,{'runtime_tested':False})),patch.dict(launcher.graphics.OUTPUT_SHA256,{(1,True):pin}):
            folder=launcher.prepare(self.root,1,'fullhd-skyoff')
            self.assertIn(b'clouds=0',(folder/'game.ini').read_bytes())
            saved=(folder/'game.ini').read_bytes().replace(b'clouds=0',b'clouds=1')
            (folder/'game.ini').write_bytes(saved)
            with patch.object(launcher.iii_guarded_start,'run',return_value=9) as guarded,patch.object(launcher.subprocess,'Popen') as spawn:
                self.assertEqual(launcher.start(self.root,1,'fullhd-skyoff'),9)
                guarded.assert_called_once_with(self.root,1,'fullhd-skyoff',folder)
                spawn.assert_not_called()
            self.assertEqual((folder/'game.ini').read_bytes(),saved.replace(b'clouds=1',b'clouds=0'))


if __name__=='__main__':unittest.main()
