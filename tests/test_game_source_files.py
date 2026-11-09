"""Synthetic source recognition/import only; never original games or native code."""
import hashlib
import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import game_source_files as sources, local_game_data, game_installation

class GameSourceFilesTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures';parent.mkdir(parents=True,exist_ok=True)
        tmp=tempfile.TemporaryDirectory(prefix='source-layout-',dir=parent);self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name)
        self.values={
            'a2racer1':{'A2.EXE':b'synthetic i parent','A2SPEL.DAT':b'synthetic i race','A2.INI':b'[test]\r\nx=1','RCS.IMG':b'synthetic i assets'},
            'a2racer2':{'A2_II.EXE':b'synthetic ii parent','SPEL.DAT':b'synthetic ii race','RASER.INI':b'[test]\r\nx=2','RCS.IMG':b'synthetic ii assets'},
        }
        self.profiles={game:{name:{'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in rows.items()} for game,rows in self.values.items()}
        changes=[patch.dict(sources.CORE_FILES,self.profiles),
                 patch.object(local_game_data,'SOURCE_PROFILE',{'core':self.profiles['a2racer1'],'essential':{}}),
                 patch.object(game_installation,'EXPECTED_BINARIES',{'a2racer1':{'A2.EXE':self.profiles['a2racer1']['A2.EXE']['sha256']}})]
        for change in changes:change.start();self.addCleanup(change.stop)

    def fixture(self,game,*,data=False,lower=False,extra=True):
        root=self.base/(game+('-data' if data else '-flat')+('-lower' if lower else ''));root.mkdir()
        folder=root/('data' if lower else 'DATA') if data else root
        folder.mkdir(exist_ok=True)
        for name,raw in self.values[game].items():(folder/(name.lower() if lower else name)).write_bytes(raw)
        if extra:
            (root/'dxsetup').mkdir();(root/'dxsetup/old.exe').write_bytes(b'not executable installer fixture')
            (root/'Helpdesk').mkdir();(root/'Helpdesk/notes.txt').write_bytes(b'ignored synthetic help')
            (root/'unrecognized.dll').write_bytes(b'never copied or executed')
        return root

    def snapshot(self,folder):
        return {p.relative_to(folder).as_posix():(p.read_bytes(),p.stat().st_mtime_ns) for p in folder.rglob('*') if p.is_file()}

    def test_cd_installed_data_and_case_variants_have_one_content_identity(self):
        for game in self.values:
            hashes=set()
            for data,lower in ((False,False),(True,True)) if game=='a2racer2' else ((False,False),(False,True)):
                source=self.fixture(game,data=data,lower=lower);before=self.snapshot(source)
                result=sources.verify_game_files(source,game)
                self.assertEqual(result['source_files'],len(self.values[game]));self.assertFalse(result['native_game_executed'])
                self.assertEqual(before,self.snapshot(source));hashes.add(result['source_tree_sha256'])
                self.assertEqual(len(result['file_map']),len(self.values[game]))
                if data:
                    self.assertEqual(sources.verify_game_files(source/'data',game)['source_tree_sha256'],result['source_tree_sha256'])
            self.assertEqual(len(hashes),1)

    def test_missing_changed_binary_resource_or_configuration_is_named_and_refused(self):
        source=self.fixture('a2racer2',data=True)
        for name in self.values['a2racer2']:
            path=source/'DATA'/name;original=path.read_bytes()
            path.write_bytes(b'X'*len(original))
            with self.assertRaisesRegex(ValueError,re.escape(name)):sources.verify_game_files(source,'a2racer2')
            path.unlink()
            with self.assertRaisesRegex(ValueError,re.escape(name)):sources.verify_game_files(source,'a2racer2')
            path.write_bytes(original)

    def test_unrelated_installer_files_do_not_change_the_content_identity(self):
        source=self.fixture('a2racer1');before=sources.verify_game_files(source,'a2racer1')
        (source/'dxsetup/old.exe').write_bytes(b'a different unused fixture')
        (source/'README.txt').write_bytes(b'extra download note')
        self.assertEqual(before,sources.verify_game_files(source,'a2racer1'))

    def test_both_imports_copy_only_verified_files_with_canonical_layout_and_keep_sources(self):
        for game in self.values:
            source=self.fixture(game,lower=True);before=self.snapshot(source);launcher=self.base/('launcher-'+game)
            launcher.mkdir()
            result=game_installation.import_installation(launcher,source,game)
            target=launcher/'local/games'/game
            actual={p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()}
            prefix='DATA/' if game=='a2racer2' else ''
            self.assertEqual(actual,{prefix+name:raw for name,raw in self.values[game].items()})
            self.assertEqual(before,self.snapshot(source));self.assertTrue(result['source_unchanged']);self.assertFalse(result['game_started'])
            self.assertEqual(sources.verify_game_files(target,game)['source_tree_sha256'],result['source_tree_sha256'])

    def test_failed_import_never_creates_cache_or_receipt(self):
        source=self.fixture('a2racer2');(source/'SPEL.DAT').write_bytes(b'unsupported')
        launcher=self.base/'rejected';launcher.mkdir()
        with self.assertRaisesRegex(ValueError,'SPEL'):game_installation.import_installation(launcher,source,'a2racer2')
        self.assertFalse((launcher/'local').exists())

    def test_source_change_during_copy_prevents_promotion(self):
        source=self.fixture('a2racer2');launcher=self.base/'changing';launcher.mkdir()
        real=game_installation.copy_file
        def change(incoming,outgoing):
            real(incoming,outgoing)
            if incoming.name=='SPEL.DAT':incoming.write_bytes(b'X'*incoming.stat().st_size)
        with patch.object(game_installation,'copy_file',side_effect=change),self.assertRaises(ValueError):
            game_installation.import_installation(launcher,source,'a2racer2')
        self.assertFalse((launcher/'local/games/a2racer2').exists())
        self.assertFalse((launcher/'local/launcher/installation-a2racer2.json').exists())

    def test_case_collisions_are_rejected_instead_of_choosing_one(self):
        source=self.fixture('a2racer1',extra=False);real=Path.iterdir
        def entries(path):
            rows=list(real(path))
            if path==source:rows.append(source/'a2.exe')
            return iter(rows)
        with patch.object(Path,'iterdir',entries),self.assertRaisesRegex(ValueError,'Dubbele'):
            sources.verify_game_files(source,'a2racer1')

    def test_scan_budgets_are_rejected_before_copy(self):
        source=self.fixture('a2racer1');before=self.snapshot(source)
        for name,value in (('MAX_FILES',1),('MAX_ENTRIES',1),('MAX_BYTES',1)):
            with patch.object(sources,name,value),self.assertRaises(ValueError):sources.verify_game_files(source,'a2racer1')
        self.assertEqual(before,self.snapshot(source))

    def test_shared_source_file_is_rejected_without_creating_a_hardlink(self):
        source=self.fixture('a2racer1');target=source/'A2.EXE';real=Path.stat
        def shared(path,*args,**kwargs):
            value=real(path,*args,**kwargs)
            if path==target:
                fields={name:getattr(value,name) for name in dir(value) if name.startswith('st_')}
                fields['st_nlink']=2
                fields['st_file_attributes']=fields.get('st_file_attributes') or 0
                return SimpleNamespace(**fields)
            return value
        with patch.object(Path,'stat',shared),self.assertRaisesRegex(ValueError,'gekoppeld'):
            sources.verify_game_files(source,'a2racer1')

    def test_image_folder_has_actionable_guidance_without_extracting_or_mounting(self):
        source=self.base/'images';source.mkdir();(source/'game.bin').write_bytes(b'synthetic not a disc')
        with self.assertRaisesRegex(ValueError,'ZIP'):sources.verify_game_files(source,'a2racer2')
        self.assertEqual(list(source.iterdir()),[source/'game.bin'])

if __name__=='__main__':unittest.main()
