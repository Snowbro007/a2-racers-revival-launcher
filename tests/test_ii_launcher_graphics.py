"""Synthetic II options/composition/progress fixtures; never execute a game."""
from copy import deepcopy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import shutil
import sys
import struct

from tools import ii_launcher_graphics as g
from tools.ii_frontend_state import initial_state, save_state, load_state, read_ini
from tools import launcher_model as model
from tools.ii_hd_hud_assets import FONT_NAMES, decode_font, encode_hd_font


def fixture_archive(records):
    index=bytearray(struct.pack('<H',len(records)));image=bytearray()
    for name,data in records:
        index.extend(struct.pack('<20sI',name.encode(),len(image)))
        image.extend(data)
    return bytes(index),bytes(image)


def fixture_font(hd=False):
    source=bytearray(b'\xff'*2048+b'\0'*8)
    struct.pack_into('<hhI',source,48*8,2,3,2056)
    source.extend(b'\x01'*6)
    return encode_hd_font(bytes(source),{48:b'\x02'*54}) if hd else bytes(source)


class ResourceCompositionTests(unittest.TestCase):
    def test_flat_background_keeps_hd_fonts_duplicates_and_every_other_record(self):
        font=fixture_font(True)
        before=[(name,font) for name in FONT_NAMES]
        before += [('duplicate.bin',b'first duplicate'),('duplicate.bin',b'second duplicate')]
        before += [(name,b'original '+name.encode()) for name in g.FLAT_BACKGROUND_NAMES]
        before += [('last.bin',b'last unchanged resource')]
        replacements=[(name,b'new flat sky '+bytes([n])*37) for n,name in enumerate(g.FLAT_BACKGROUND_NAMES)]
        flat_index,flat_image=fixture_archive(replacements+[('OLFNT03.FNT',fixture_font())])
        index,image=fixture_archive(before)
        new_index,new_image=g.merge_flat_background(index,image,flat_index,flat_image)
        # Independently rebuild the expected entire archive, including offsets.
        selected=dict(replacements)
        expected=fixture_archive([(name,selected.get(name,data)) for name,data in before])
        self.assertEqual((new_index,new_image),expected)
        for name in FONT_NAMES:
            self.assertEqual(g.resource(new_index,new_image,name),font)
            self.assertEqual(decode_font(g.resource(new_index,new_image,name))[1][48][:2],(6,9))
        self.assertEqual(index,fixture_archive(before)[0])
        self.assertEqual(image,fixture_archive(before)[1])

    def test_missing_duplicate_or_invalid_background_archives_are_refused(self):
        records=[(name,b'background '+name.encode()) for name in g.FLAT_BACKGROUND_NAMES]
        index,image=fixture_archive(records+[('OLFNT03.FNT',fixture_font(True))])
        flat_index,flat_image=fixture_archive(records)
        for bad_records in (records[:-1],records+[records[0]]):
            bad_index,bad_image=fixture_archive(bad_records)
            with self.assertRaises(ValueError):g.merge_flat_background(index,image,bad_index,bad_image)
        for bad_records in (records[:-1],records+[records[0]]):
            bad_index,bad_image=fixture_archive(bad_records)
            with self.assertRaises(ValueError):g.merge_flat_background(bad_index,bad_image,flat_index,flat_image)
        broken=bytearray(index);struct.pack_into('<I',broken,22,1)
        with self.assertRaises(ValueError):g.merge_flat_background(bytes(broken),image,flat_index,flat_image)

    def test_flat_payload_preserves_pinned_font_and_rc_family_for_all_seven_variants(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            root=Path(temp);area=root/'local/ii-parallel';current=area/'ii-frontend-flat-synthetic'
            (current/'game/DATA').mkdir(parents=True)
            flat_records=[(name,b'synthetic accepted flat '+name.encode()) for name in g.FLAT_BACKGROUND_NAMES]
            flat_index,flat_image=fixture_archive(flat_records+[('OLFNT03.FNT',fixture_font()),('other.bin',b'wrong canonical content')])
            (current/'game/DATA/RCS.IND').write_bytes(flat_index)
            (current/'game/DATA/RCS.IMG').write_bytes(flat_image)
            (current/'Frontend.json').write_text(json.dumps({'wide_race_variant':'flat-sky60'}))
            sources={};originals={}
            for key,(name,_,_) in g.SOURCES.items():
                base=area/name;(base/'game/DATA').mkdir(parents=True);(base/'profiles').mkdir()
                binary=('synthetic binary '+repr(key)).encode()
                profile=('synthetic profile '+key[0]).encode()
                font=fixture_font(key[1]!='native')
                records=[(name,font) for name in FONT_NAMES]+[(name,b'old sky') for name in g.FLAT_BACKGROUND_NAMES]
                records += [('other.bin',('chosen '+repr(key)).encode())]
                index,image=fixture_archive(records)
                rc_image=b'\0\0'+struct.pack('<4H',2,2,0,0)+b'\x02'*4
                rc_index=struct.pack('<HI',1,2)
                content={'game/DATA/SPEL-WIDE.DAT':binary,'profiles/widescreen.conf':profile,
                    'game/DATA/RC.IND':rc_index,'game/DATA/RC.IMG':rc_image,
                    'game/DATA/RCS.IND':index,'game/DATA/RCS.IMG':image}
                for path,data in content.items():(base/path).write_bytes(data)
                raw=json.dumps({'files':[{'path':path,'sha256':g.sha(data)} for path,data in content.items()]}).encode()
                (base/'Frontend.json').write_bytes(raw)
                sources[key]=(base.name,g.sha(raw),g.sha(binary));originals[key]=content
            with patch.object(g,'SOURCES',sources),patch.object(g.frontend,'registered_menu',return_value={'base':str(current)}),patch.object(g,'compose_world',side_effect=lambda source,options:source):
                for resolution,hud in sources:
                    with self.subTest(resolution=resolution,hud=hud):
                        options=dict(g.DEFAULTS,race_resolution=resolution,race_hud=hud)
                        payload=g.source_payload(root,options);before=originals[(resolution,hud)]
                        expected_records=[(name,fixture_font(hud!='native')) for name in FONT_NAMES]+flat_records
                        expected_records += [('other.bin',('chosen '+repr((resolution,hud))).encode())]
                        expected_index,expected_image=fixture_archive(expected_records)
                        self.assertEqual(payload['game/DATA/RCS.IND'],expected_index)
                        self.assertEqual(payload['game/DATA/RCS.IMG'],expected_image)
                        for relative in ('game/DATA/RC.IND','game/DATA/RC.IMG','profiles/widescreen.conf','game/DATA/SPEL-WIDE.DAT'):
                            self.assertEqual(payload[relative],before[relative])
                        for name in FONT_NAMES:
                            self.assertEqual(g.resource(expected_index,expected_image,name),fixture_font(hud!='native'))
                        for path,data in before.items():self.assertEqual((area/sources[(resolution,hud)][0]/path).read_bytes(),data)
                # Source hash enforcement still happens before archive composition.
                source=area/sources[('4k','hd')][0]/'game/DATA/RCS.IMG'
                source.write_bytes(b'changed pinned source')
                with self.assertRaisesRegex(ValueError,'bron veranderde'):
                    g.source_payload(root,dict(g.DEFAULTS,race_resolution='4k',race_hud='hd'))


class CompositionTests(unittest.TestCase):
    def setUp(self):
        source=bytearray(b'\xCC'*0x50000)
        for off,data in ((g.distance.CONTEXT_OFFSET,g.distance.CONTEXT),
                         (g.distance.LIMIT_OFFSET,g.distance.LIMIT_CONTEXT),
                         (g.horizon.CONTEXT_OFFSET,g.horizon.CONTEXT)):
            source[off:off+len(data)]=data
        for off,before,_ in g.horizon.PATCHES:source[off:off+len(before)]=before
        for off,before in (g.sky.CLOUD_CALL,g.sky.BITMAP_CALL):source[off:off+len(before)]=before
        self.source=bytes(source)
        sources={key:(values[0],values[1],g.sha(self.source)) for key,values in g.SOURCES.items()}
        mock=patch.object(g,'SOURCES',sources);mock.start();self.addCleanup(mock.stop)

    def test_all_supported_resolution_hud_sky_distance_combinations_preserve_other_bytes(self):
        for resolution,hud in g.SOURCES:
            for sky,distance in itertools.product(g.CHOICES['sky_mode'],g.CHOICES['race_distance']):
                with self.subTest(resolution=resolution,hud=hud,sky=sky,distance=distance):
                    options=dict(g.DEFAULTS,race_resolution=resolution,race_hud=hud,sky_mode=sky,race_distance=distance)
                    output=g.compose_world(self.source,options)
                    self.assertEqual(len(output),len(self.source))
                    allowed={g.distance.PATCH_OFFSET,g.distance.LIMIT_OFFSET+2,g.distance.LIMIT_OFFSET+11}
                    for off,before,_ in g.horizon.PATCHES:allowed.update(range(off,off+len(before)))
                    for off,before in (g.sky.CLOUD_CALL,g.sky.BITMAP_CALL):allowed.update(range(off,off+len(before)))
                    changed={i for i,(a,b) in enumerate(zip(self.source,output)) if a!=b}
                    self.assertTrue(changed.issubset(allowed))
                    self.assertEqual(output[g.distance.PATCH_OFFSET],0x48 if distance=='auto' else 0x90)
                    self.assertEqual(output[g.distance.LIMIT_OFFSET+2],60 if distance=='60' else 50)
                    if sky=='original':
                        for off,before,_ in g.horizon.PATCHES:self.assertEqual(output[off:off+len(before)],before)
                    if sky=='flat':
                        for off,before in (g.sky.CLOUD_CALL,g.sky.BITMAP_CALL):self.assertEqual(output[off:off+len(before)],b'\x90'*len(before))

    def test_original_auto_is_byte_identical(self):
        self.assertEqual(g.compose_world(self.source,dict(g.DEFAULTS,sky_mode='original',race_distance='auto')),self.source)

    def test_unknown_binary_and_matching_hash_with_wrong_context_are_rejected(self):
        changed=bytearray(self.source);changed[g.distance.CONTEXT_OFFSET]^=1
        with self.assertRaises(ValueError):g.compose_world(bytes(changed),g.DEFAULTS)
        values=g.SOURCES[('720p','native')]
        with patch.dict(g.SOURCES,{('720p','native'):(values[0],values[1],g.sha(changed))}):
            with self.assertRaisesRegex(ValueError,'context'):g.compose_world(bytes(changed),g.DEFAULTS)

    def test_options_refuse_paths_unknown_values_partial_fields_and_hd_at_720p(self):
        for options in ({},dict(g.DEFAULTS,sky_mode='../evil'),dict(g.DEFAULTS,race_distance=60),
                        dict(g.DEFAULTS,race_hud='hd'),dict(g.DEFAULTS,script='run.exe')):
            with self.subTest(options=options),self.assertRaises(ValueError):g.validate_options(options)

    def test_old_seven_fields_migrate_read_only_and_new_choices_survive_validation(self):
        old={key:value for key,value in model.DEFAULT_SETTINGS['games']['a2racer2'].items() if key not in {*g.CHOICES,'developer_mode','vector_car'}}
        original=deepcopy(old)
        migrated=model.validate_preferences('a2racer2',old)
        self.assertEqual(old,original)
        self.assertEqual({key:migrated[key] for key in g.CHOICES},g.DEFAULTS)
        selected=dict(migrated,race_resolution='4k',race_hud='hd-map',sky_mode='horizon-off',race_distance='50')
        self.assertEqual(model.validate_preferences('a2racer2',selected),selected)


class CopyProgressTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.current=self.root/'local/ii-parallel/ii-frontend-synthetic'
        (self.current/'game/DATA').mkdir(parents=True)
        (self.current/'profiles').mkdir()
        (self.root/'tools').mkdir()
        self.payload={'game/DATA/SPEL-WIDE.DAT':b'synthetic chosen binary',
                      'profiles/widescreen.conf':b'synthetic chosen profile',
                      **{'game/DATA/'+n:b'synthetic '+n.encode() for n in g.NATIVE_ASSETS}}
        for path,data in self.payload.items():(self.current/path).write_bytes(data)
        (self.current/'game/DATA/GAME.INI').write_bytes(b'[OPTIONS]\r\nvisiblechunks=30\r\n[GFX OPTIONS]\r\nclouds=1\r\n')
        (self.current/'game/DATA/RASER.INI').write_bytes(b'[HELPDESK]\r\nTWEAK_MODE=0 ; untouched comment\r\nDEBUGON=0\r\n')
        backend=(g.frontend.RACE_DISPLAYS['widescreen']['sha256']+'\n'+g.frontend.RACE_DISPLAYS['widescreen']['profile_sha256']).encode()
        menu="Schermvullend 16:9 (1280 × 720)','Klassiek 4:3 (640 × 480)' @(1280,720)".encode()
        for dest,content in (('Backend.py',backend),('Menu.ps1',menu)):
            (self.current/dest).write_bytes(content)
        (self.root/'tools/ii_frontend_state.py').write_bytes(backend)
        (self.root/'tools/ii_frontend.ps1').write_bytes(menu)
        files=[{'path':p,'sha256':g.sha((self.current/p).read_bytes())} for p in ('Menu.ps1','Backend.py',*self.payload)]
        (self.current/'Frontend.json').write_text(json.dumps({'files':files}),encoding='utf-8')
        state=initial_state();state['profiles'][0]['money']=76543;state['profiles'][0]['upgrades']['motor']=True
        state['profiles'][0]['records']={'0':12345};state['profiles'][0]['next_track']=1
        save_state(self.current,state)
        mock=patch.object(g.frontend,'registered_menu',return_value={'base':str(self.current)})
        mock.start();self.addCleanup(mock.stop)
        mock=patch.object(g,'source_payload',return_value=self.payload)
        mock.start();self.addCleanup(mock.stop)

    def test_copy_preserves_originals_and_progress_and_seals_chosen_payload(self):
        before={p.relative_to(self.current):p.read_bytes() for p in self.current.rglob('*') if p.is_file()}
        options=dict(g.DEFAULTS,race_resolution='4k',race_hud='hd')
        result=g.prepare(self.root,'launcher-synthetic-options',options)
        target=Path(result['base'])
        self.assertEqual(before,{p.relative_to(self.current):p.read_bytes() for p in self.current.rglob('*') if p.is_file()})
        self.assertEqual(load_state(target)['profiles'],load_state(self.current)['profiles'])
        ini=read_ini((target/'game/DATA/GAME.INI').read_bytes())
        self.assertEqual(ini['OPTIONS']['visiblechunks'],'60');self.assertEqual(ini['GFX OPTIONS']['clouds'],'0')
        config=json.loads((target/'Frontend.json').read_bytes())
        self.assertEqual(config['launcher_graphics'],options)
        self.assertEqual(config['resolution_trial'],[3840,2160])
        for file in config['files']:self.assertEqual(g.sha((target/file['path']).read_bytes()),file['sha256'])
        self.assertNotIn('Klassiek 4:3',(target/'Menu.ps1').read_text(encoding='utf-8'))
        self.assertFalse(result['runtime_tested'])

    def test_bonus_session_pins_both_snapshots_but_active_resources_can_switch(self):
        def prepare_vector(root,target):
            paths=set()
            for mode in ('normal','vector'):
                for name in ('RCS.IND','RCS.IMG'):
                    relative=f'vector-vehicle/{mode}/{name}'
                    (target/relative).parent.mkdir(parents=True,exist_ok=True)
                    (target/relative).write_bytes(f'synthetic {mode} {name}'.encode());paths.add(relative)
            return {'schema':1,'enabled':True},paths
        with patch('tools.ii_vector_car.checked_art'),patch('tools.ii_vector_car.prepare',side_effect=prepare_vector):
            result=g.prepare(self.root,'launcher-bonus-synthetic',g.DEFAULTS,vector_car=True)
        target=Path(result['base']);cfg=json.loads((target/'Frontend.json').read_bytes())
        paths={row['path'] for row in cfg['files']}
        self.assertNotIn('game/DATA/RCS.IMG',paths);self.assertNotIn('game/DATA/RCS.IND',paths)
        for mode in ('normal','vector'):
            for name in ('RCS.IND','RCS.IMG'):
                self.assertIn(f'vector-vehicle/{mode}/{name}',paths)
                (target/'game/DATA'/name).write_bytes((target/f'vector-vehicle/{mode}/{name}').read_bytes())
            for row in cfg['files']:
                self.assertEqual(g.sha((target/row['path']).read_bytes()),row['sha256'])

    def test_sync_preserves_new_records_and_refuses_pending_or_changed_registration(self):
        result=g.prepare(self.root,'launcher-synthetic-sync',g.DEFAULTS)
        target=Path(result['base']);state=load_state(target)
        state['profiles'][0]['money']=80000;save_state(target,state)
        g.sync_progress(self.root,'launcher-synthetic-sync',self.current.name)
        self.assertEqual(load_state(self.current)['profiles'][0]['money'],80000)
        with self.assertRaises(ValueError):g.sync_progress(self.root,'launcher-synthetic-sync','other-registration')
        # A valid pending race cannot silently replace the canonical profile.
        state['pending']={'token':'a'*32,'profile':state['selected'],'track':0,'car':0,'race_display':'widescreen'}
        save_state(target,state)
        with self.assertRaises(ValueError):g.sync_progress(self.root,'launcher-synthetic-sync',self.current.name)

    def test_developer_mode_is_scoped_to_copy_and_off_overrides_a_previous_on_value(self):
        original=b'[HELPDESK]\r\nTWEAK_MODE=1 ; untouched comment\r\nDEBUGON=0\r\n'
        source=self.current/'game/DATA/RASER.INI';source.write_bytes(original)
        for enabled,mode in ((True,'widescreen'),(False,'classic')):
            result=g.prepare(self.root,'launcher-developer-'+str(enabled).lower(),g.DEFAULTS,mode,developer_mode=enabled)
            target=Path(result['base'])
            expected=original.replace(b'TWEAK_MODE=1',b'TWEAK_MODE='+str(int(enabled)).encode())
            self.assertEqual((target/'game/DATA/RASER.INI').read_bytes(),expected)
            self.assertEqual(source.read_bytes(),original)
            self.assertIs(result['developer_mode'],enabled)
            self.assertIs(json.loads((target/'Frontend.json').read_bytes())['developer_mode'],enabled)
            self.assertEqual(load_state(target)['profiles'],load_state(self.current)['profiles'])
        for value in (1,'on',None):
            with self.assertRaises(ValueError):g.prepare(self.root,'launcher-invalid-developer',g.DEFAULTS,developer_mode=value)
        self.assertFalse(g.target_folder(self.root,'launcher-invalid-developer').exists())

    def test_classic_uses_original_world_and_does_not_overwrite_existing_session(self):
        result=g.prepare(self.root,'launcher-synthetic-classic',dict(g.DEFAULTS,race_resolution='4k',race_hud='hd'),'classic')
        self.assertEqual(result['options'],{'race_resolution':'720p','race_hud':'native','sky_mode':'original','race_distance':'auto'})
        with self.assertRaises(ValueError):g.prepare(self.root,'launcher-synthetic-classic',g.DEFAULTS)
        for name in ('../elsewhere','not-a-session'):
            with self.assertRaises(ValueError):g.target_folder(self.root,name)

    def test_runner_forwards_frozen_options_holds_source_lock_and_saves_after_menu(self):
        runtime=Path(sys.executable).parent.parent/'native/powershell/pwsh.exe'
        if not runtime.exists():self.skipTest('PowerShell 7 ontbreekt.')
        tools=self.root/'tools'
        shutil.copyfile(g.ROOT/'tools/Invoke-IIFrontend.ps1',tools/'Invoke-IIFrontend.ps1')
        shutil.copyfile(g.ROOT/'tools/launcher_common.ps1',tools/'launcher_common.ps1')
        plan={'base':str(self.current)}
        (tools/'launcher_model.py').write_text('import json\nprint(json.dumps('+repr(plan)+'))\n',encoding='utf-8')
        target=self.root/'local/ii-parallel/ii-launcher-synthetic-runner';target.mkdir()
        result={'base':str(target),'canonical_run':self.current.name}
        event=self.root/'events.jsonl'
        (tools/'ii_launcher_graphics.py').write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'with Path('+repr(str(event))+').open("a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
            'print(json.dumps('+repr(result)+'))\n',encoding='utf-8')
        # This script is synthetic; it starts no game, hook or window.
        lock=str(self.current/'menu.lock').replace("'","''")
        (target/'Menu.ps1').write_text("param([string]$RaceDisplay)\nif($RaceDisplay -ne 'widescreen'){throw 'Wrong display'}\n"
            "$locked=$false\ntry{$probe=[IO.File]::Open('"+lock+"',[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$probe.Dispose()}catch{$locked=$true}\n"
            "if(-not $locked){throw 'Source state was not locked'}\n",encoding='utf-8-sig')
        run=subprocess.run([str(runtime),'-NoProfile','-File',str(tools/'Invoke-IIFrontend.ps1'),
            '-PythonPath',sys.executable,'-FanNoticeShown','-RunName','launcher-synthetic-runner',
            '-RaceDisplay','widescreen','-RaceResolution','4k','-RaceHud','hd-map','-SkyMode','flat','-RenderDistance','60','-DeveloperMode'],
            capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)
        events=[json.loads(line) for line in event.read_text().splitlines()]
        self.assertEqual([line[0] for line in events],['prepare','sync'])
        for flag,value in (('--race-resolution','4k'),('--race-hud','hd-map'),('--sky-mode','flat'),('--race-distance','60'),('--developer-mode','1')):
            self.assertEqual(events[0][events[0].index(flag)+1],value)
        self.assertEqual(events[1][-1],self.current.name)


if __name__=='__main__':unittest.main()
