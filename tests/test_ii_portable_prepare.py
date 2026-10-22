"""Synthetic portable source/version/registration fixtures; no native game runs."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import ii_portable_prepare as portable, ii_launcher_graphics as graphics
from tools import ii_frontend_launcher as frontend, ii_frontend_state as state
from tools.pcx_codec import IndexedImage, decode_pcx, encode_pcx
from tests.test_ii_launcher_graphics import fixture_archive


class PortableFixtures(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='ii-portable-',dir=parent)
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.stack=ExitStack();self.addCleanup(self.stack.close)

    def patched(self,obj,name,value):
        return self.stack.enter_context(patch.object(obj,name,value))

    def sources(self):
        archives={'RC.IND':b'index','RC.IMG':b'images',
                  'RCS.IND':b'resources','RCS.IMG':b'resource images'}
        self.patched(graphics,'NATIVE_ASSETS',{name:portable.sha(raw) for name,raw in archives.items()})
        values=deepcopy(graphics.SOURCES)
        for res in portable.NATIVE_RESOLUTIONS:
            old=values[res,'native'];values[res,'native']=(old[0],old[1],portable.sha(('binary '+res).encode()))
        self.patched(graphics,'SOURCES',values)
        self.patched(portable,'PROFILE_PINS',{res:portable.sha(('profile '+res).encode())
            for res in portable.NATIVE_RESOLUTIONS})
        for res in portable.NATIVE_RESOLUTIONS:
            base=portable.native_folder(self.root,res)
            (base/'game/DATA').mkdir(parents=True);(base/'profiles').mkdir()
            for name,raw in archives.items():(base/'game/DATA'/name).write_bytes(raw)
            (base/'game/DATA/SPEL-WIDE.DAT').write_bytes(('binary '+res).encode())
            (base/'profiles/widescreen.conf').write_bytes(('profile '+res).encode())
            (base/'Frontend.json').write_bytes(portable.encoded(portable.native_config(res)))
        return archives

    def test_native_metadata_relocates_and_cannot_replace_binary_or_profile_pins(self):
        self.sources()
        moved=self.root/'moved portable copy'
        shutil.copytree(self.root/'local',moved/'local')
        for res in portable.NATIVE_RESOLUTIONS:
            self.assertEqual(portable.native_payload(self.root,res),portable.native_payload(moved,res))
        base=portable.native_folder(moved,'4k')
        target=base/'game/DATA/SPEL-WIDE.DAT';target.write_bytes(b'unknown game')
        config=json.loads((base/'Frontend.json').read_bytes())
        next(e for e in config['files'] if e['path']=='game/DATA/SPEL-WIDE.DAT')['sha256']=portable.sha(target.read_bytes())
        (base/'Frontend.json').write_bytes(portable.encoded(config))
        with self.assertRaisesRegex(ValueError,'registratie'):portable.native_payload(moved,'4k')

    def test_changed_source_cannot_fall_back_to_old_trial_or_ignore_missing_archive(self):
        self.sources()
        options=dict(graphics.DEFAULTS,sky_mode='original')
        self.patched(graphics,'compose_world',lambda raw,opts:raw)
        old=graphics.SOURCES['720p','native'][0]
        self.assertFalse((self.root/'local/ii-parallel'/old).exists())
        self.assertEqual(graphics.source_payload(self.root,options)['game/DATA/SPEL-WIDE.DAT'],b'binary 720p')
        (portable.native_folder(self.root,'720p')/'game/DATA/RC.IMG').unlink()
        with self.assertRaises(ValueError):graphics.source_payload(self.root,options)

    def test_links_and_unknown_resolution_are_refused(self):
        self.sources()
        with self.assertRaises(ValueError):portable.native_folder(self.root,'1080;command')
        base=portable.native_folder(self.root,'1080p')
        target=base/'profiles/widescreen.conf'
        # The Windows sandbox forbids creating hardlinks. Simulate the exact
        # filesystem metadata observed by the existing ancestor validator.
        from types import SimpleNamespace
        original=Path.lstat
        def shared(path):
            value=original(path)
            return SimpleNamespace(st_mode=value.st_mode,st_nlink=2,st_file_attributes=0) if path==target else value
        with patch.object(Path,'lstat',shared):
            with self.assertRaisesRegex(ValueError,'gedeeld'):portable.native_payload(self.root,'1080p')

    def test_flat_sky_replaces_only_seven_resources_and_keeps_hud_and_duplicates(self):
        old=encode_pcx(IndexedImage(4,2,b'\x02'*8,bytes(range(256))*3))
        records=[(f'back{i}.pcx',old) for i in range(1,8)]
        records += [('font.fnt',b'synthetic original font'),('same.bin',b'one'),('same.bin',b'two')]
        index,image=fixture_archive(records)
        new_index,new_image=portable.flat_background(index,image)
        replacements={}
        for i in range(1,8):
            name=f'back{i}.pcx';raw=graphics.resource(new_index,new_image,name)
            value=decode_pcx(raw);self.assertEqual((value.width,value.height),(4,2))
            self.assertEqual(value.pixels,bytes(8));self.assertEqual(value.palette[:3],bytes((85,115,145)))
            replacements[name]=raw
        self.assertEqual((new_index,new_image),fixture_archive([(name,replacements.get(name,raw)) for name,raw in records]))

    def test_full_tree_hash_includes_unpinned_data_and_refuses_wrong_supported_version(self):
        source=self.root/'source';data=source/'DATA';data.mkdir(parents=True)
        for name in ('SPEL.DAT','RC.IND','RC.IMG','RCS.IND','RCS.IMG','extra.bin'):
            (data/name).write_bytes(('synthetic '+name).encode())
        for track in range(7):
            for ext in ('CMP','DMP','OMP','PMP','PTH','RMP'):(data/f'ETAPPE{track}.{ext}').write_bytes(b'map')
        self.patched(portable.ii_playtest_check,'EXPECTED_SOURCE_FILES',48)
        raw=(data/'SPEL.DAT').read_bytes()
        self.patched(portable.ii_playtest_check,'SOURCE_PINS',{'DATA/SPEL.DAT':{'size':len(raw),'sha256':portable.sha(raw)}})
        self.patched(graphics,'NATIVE_ASSETS',{n:portable.sha((data/n).read_bytes()) for n in graphics.NATIVE_ASSETS})
        before=portable.inspect_source(source)
        self.assertEqual(before['source_files'],48);self.assertFalse(before['native_game_executed'])
        (data/'extra.bin').write_bytes(b'other raw extra.bin')
        self.assertNotEqual(before['source_tree_sha256'],portable.inspect_source(source)['source_tree_sha256'])
        (data/'SPEL.DAT').write_bytes(b'wrong source version')
        with self.assertRaisesRegex(ValueError,'bron'):portable.inspect_source(source)
        self.assertFalse((self.root/'reports').exists())

    def test_support_distinguishes_available_native_from_missing_hd_without_writing(self):
        self.sources()
        self.patched(portable,'checked_inputs',lambda root:None)
        self.patched(graphics,'compose_world',lambda raw,options:raw)
        # No canonical needed for original sky. Support always checks flat; provide
        # a synthetic isolated canonical with the same duplicate-safe sky contract.
        current=self.root/'canonical';(current/'game/DATA').mkdir(parents=True)
        index,image=fixture_archive([(name,b'synthetic flat') for name in graphics.FLAT_BACKGROUND_NAMES])
        (current/'Frontend.json').write_text(json.dumps({'wide_race_variant':'flat-sky60'}))
        (current/'game/DATA/RCS.IND').write_bytes(index);(current/'game/DATA/RCS.IMG').write_bytes(image)
        self.patched(graphics.frontend,'registered_menu',lambda root:{'base':str(current)})
        self.patched(graphics,'merge_flat_background',lambda ind,img,*other:(ind,img))
        result=portable.availability(self.root)
        self.assertTrue(result['can_prepare'])
        for res in portable.NATIVE_RESOLUTIONS:
            self.assertTrue(result['families'][res]['native']['available'])
            self.assertFalse(result['families'][res]['hd']['available'])
        self.assertFalse((self.root/'local/launcher/settings.json').exists())

    def test_existing_canonical_is_reused_without_reading_source_or_resetting_players(self):
        area=self.root/'local/ii-parallel';area.mkdir(parents=True)
        registration=area/'frontend-current.json';registration.write_bytes(b'preserved pointer')
        self.patched(frontend,'registered_menu',lambda root:{'base':'preserved canonical'})
        self.patched(portable,'checked_inputs',lambda *args: self.fail('Existing menu must not be rebuilt'))
        result=portable.prepare(self.root,'nonexistent Python is unused')
        self.assertFalse(result['prepared']);self.assertTrue(result['already_ready'])
        self.assertEqual(registration.read_bytes(),b'preserved pointer')

    def test_bad_preparation_inputs_create_no_output_and_unknown_name_is_rejected(self):
        self.patched(portable,'checked_inputs',lambda *args: (_ for _ in ()).throw(ValueError('missing input')))
        for name in ('../escape','bad-name','ii-frontend-portable-v1'):
            with self.assertRaises(ValueError):portable.prepare(self.root,'unused',name)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_first_build_registers_isolated_native_sources_and_preserves_source_and_retries(self):
        source=self.root/'player source';data=source/'DATA';data.mkdir(parents=True)
        pcx=encode_pcx(IndexedImage(2,2,b'\x01'*4,bytes(range(256))*3))
        index,image=fixture_archive([(f'back{i}.pcx',pcx) for i in range(1,8)]+[('font.fnt',b'unchanged')])
        contents={'SPEL.DAT':b'synthetic original executable','RC.IND':b'RC index','RC.IMG':b'RC sprites',
                  'RCS.IND':index,'RCS.IMG':image,'GARAGE.INI':b'fixture garage',
                  'GAME.INI':b'[OPTIONS]\nvisiblechunks=30\n[GFX OPTIONS]\nclouds=1\n',
                  'RASER.INI':b'[PROGRAM]\nRESOLUTION=0\n[MOVIES]\nON=1\n[HELPDESK]\nDEBUGON=1\n'}
        for name,raw in contents.items():(data/name).write_bytes(raw)
        for track in range(7):
            for ext in ('CMP','DMP','OMP','PMP','PTH','RMP'):(data/f'ETAPPE{track}.{ext}').write_bytes(b'fixture map')
        before={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
        (self.root/'tools').mkdir()
        for name in frontend.SOURCE_FILES.values():(self.root/'tools'/name).write_bytes(b'synthetic tool; never run')
        runtime=self.root/'python.fixture';runtime.write_bytes(b'not an executable')
        own_art={name:b'synthetic authored image' for name in portable.ART_PINS}
        self.patched(portable,'checked_inputs',lambda *args:(source,own_art,[],b'classic profile'))
        binaries={res:('fixture binary '+res).encode() for res in portable.NATIVE_RESOLUTIONS}
        self.patched(portable,'build_native_binaries',lambda raw:binaries)
        profiles={res:('fixture profile '+res).encode() for res in portable.NATIVE_RESOLUTIONS}
        self.patched(portable.fullscreen,'race_profile',lambda raw:profiles['720p'])
        self.patched(portable.resolutions,'trial_profile',lambda raw,display:profiles['1080p' if display==(1920,1080) else '4k'])
        self.patched(portable,'PROFILE_PINS',{res:portable.sha(raw) for res,raw in profiles.items()})
        self.patched(graphics,'NATIVE_ASSETS',{n:portable.sha(contents[n]) for n in graphics.NATIVE_ASSETS})
        variants=deepcopy(graphics.SOURCES)
        for res,blob in binaries.items():
            old=variants[res,'native'];variants[res,'native']=(old[0],old[1],portable.sha(blob))
        self.patched(graphics,'SOURCES',variants)
        self.patched(graphics,'compose_world',lambda raw,options:b'fixture flat race')
        self.patched(state,'FLAT_SKY60_SHA256',portable.sha(b'fixture flat race'))
        expected=deepcopy(frontend.EXPECTED_BINARIES)
        expected['a2racer2']['DATA/SPEL.DAT']=portable.sha(contents['SPEL.DAT'])
        self.patched(frontend,'EXPECTED_BINARIES',expected)
        displays=deepcopy(frontend.RACE_DISPLAYS)
        displays['classic']['profile_sha256']=portable.sha(b'classic profile')
        displays['widescreen']['profile_sha256']=portable.sha(profiles['720p'])
        self.patched(frontend,'RACE_DISPLAYS',displays)
        def install(game,dependencies):
            for name in ('DDraw.dll','D3DImm.dll'):(game/'DATA'/name).write_bytes(b'fixture wrapper')
        self.patched(portable.trial_manifest,'apply_graphics_wrapper',install)
        def assets(data,folder,images):
            folder.mkdir()
            for name,raw in images.items():(folder/name).write_bytes(raw)
            for car in range(7):(folder/f'car{car}.json').write_bytes(b'{}')
            for tex in range(4):(folder/f'texture{tex}.png').write_bytes(b'fixture texture')
            for name in ('wheel.json','arrow32.cur','arrow48.cur'):(folder/name).write_bytes(b'fixture asset')
            return False
        self.patched(portable,'_assets',assets)
        # A failure before source-family creation keeps the original and removes
        # only this invocation's staging tree; a fresh generated name can retry.
        with patch.object(portable,'_assets',side_effect=ValueError('fixture build failure')):
            with self.assertRaisesRegex(ValueError,'build failure'):portable.prepare(self.root,str(runtime))
        self.assertFalse((self.root/'local/ii-parallel/frontend-current.json').exists())
        self.assertFalse(list((self.root/'local/ii-parallel').glob('.ii-native-build-*')))
        result=portable.prepare(self.root,str(runtime))
        self.assertTrue(result['prepared']);self.assertFalse(result['hd_sources_built'])
        self.assertEqual(before,{p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()})
        self.assertEqual(frontend.registered_menu(self.root)['base'],result['base'])
        for res in portable.NATIVE_RESOLUTIONS:
            self.assertEqual(portable.native_payload(self.root,res)['game/DATA/SPEL-WIDE.DAT'],binaries[res])
        self.assertTrue(portable.prepare(self.root,str(runtime))['already_ready'])


if __name__=='__main__': unittest.main()
