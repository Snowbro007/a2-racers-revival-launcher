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
import zlib
from unittest.mock import patch

from tools import ii_frontend_state as model
from tools import ii_frontend_prepare as prepare
from tools.pcx_codec import IndexedImage, encode_pcx
from tools.vehicle_mesh import VehicleMesh

ROOT = Path(__file__).resolve().parents[1]
GAME = b'''[INPUT]\r\nDEVICE=1\r\nLEFT=37\r\nRIGHT=39\r\nUP=38\r\nDOWN=40\r\nEXTRA1=17\r\nEXTRA2=18\r\n[OPTIONS]\r\nDifficulty=1\r\nNrlaps=2\r\ncollisionoff=0 ; guard\r\n[ETAPPE]\r\netappe=5\r\n[PLAYER]\r\nfinished=1\r\ncar=0\r\ncopland=0\r\ndamage=0\r\nmoney=812000\r\ntracktime=149348\r\nposition=0\r\nMOTOR=1\r\nBANDEN=1\r\nABS=1\r\nTURBO=1\r\nVERSNELLINGSBAK=1\r\nDAMAGE_MESH=-1,-1,-1,-1,-1,0,-1,-1\r\nDAMAGE_VALUE=-1,-1,-1,-1,-1,0,-1,-1\r\n[RACERS]\r\ncount=3\r\n0=5,3,158283\r\n1=3,1,151668\r\n2=6,2,158088\r\n'''
RASER = b'[PROGRAM]\nRESOLUTION=0\n[MOVIES]\nON=0\n[HELPDESK]\nDEBUGON=1\n[SOUND]\nMUSICVOLUME=0\nSFXVOLUME=100\nON=1\n'


def garage():
    lines = ['[prices]']
    for i in range(1, 8):
        lines.append(f'car{i}={i*15000}')
        for j in range(1, 7): lines.append(f'item{j}_car{i}={j*500}')
    lines.append('[percents]')
    for item in range(1, 7):
        for j in range(1, 5):
            lines.append(f'item{item}_perc{j}={15 if item in (1,6) and j==1 else 50 if (item,j) in ((2,4),(5,3)) else 20 if (item,j)==(6,2) else 0}')
    for i in range(1, 8):
        for j in range(1, 5): lines.append(f'car{i}_perc{j}={150 if j==1 else 30}')
    return ('\n'.join(lines)+'\n').encode()


def fixture(base):
    data=base/'game/DATA'; data.mkdir(parents=True)
    (data/'GAME.INI').write_bytes(GAME); (data/'RASER.INI').write_bytes(RASER)
    (data/'GARAGE.INI').write_bytes(garage())
    for track in range(7):
        for ext in ('CMP','DMP','OMP','PMP','PTH','RMP'):
            (data/f'ETAPPE{track}.{ext}').write_bytes(b'synthetic map')
    return data


def fixture_temp():
    folder=ROOT/'local/ii-frontend-fixtures'
    folder.mkdir(parents=True,exist_ok=True)
    return tempfile.TemporaryDirectory(dir=folder)


class FrontendModelTests(unittest.TestCase):
    def test_tweak_mode_survives_repeated_race_starts_and_profile_reset(self):
        for enabled in (0,1):
            original=RASER.replace(b'DEBUGON=1',f'TWEAK_MODE={enabled} ; keep\nDEBUGON=1'.encode())
            state=model.initial_state()
            for attempt in range(3):
                game,raser,pending=model.race_inputs(state,GAME,original)
                self.assertEqual(model.read_ini(raser)['HELPDESK']['TWEAK_MODE'],str(enabled))
                self.assertIn(f'TWEAK_MODE={enabled} ; keep'.encode(),raser)
                self.assertEqual(model.read_ini(raser)['HELPDESK']['DEBUGON'],'0')
                running=copy.deepcopy(state);running['pending']=pending
                state=model.finish_race(running,game,token=pending['token'],exit_code=1)
                original=raser
            state=model.initial_state()
            self.assertEqual(model.read_ini(model.race_inputs(state,GAME,original)[1])['HELPDESK']['TWEAK_MODE'],str(enabled))

    def test_distance_trial_survives_race_start_without_touching_other_choices(self):
        for count in (30, 50):
            original = GAME.replace(b'collisionoff=0 ; guard',
                                    b'visiblechunks='+str(count).encode()+b'\r\ncollisionoff=0 ; guard')
            planned, _, _ = model.race_inputs(model.initial_state(), original, RASER)
            ini = model.read_ini(planned)
            self.assertEqual(ini.getint('OPTIONS', 'visiblechunks'), count)
            self.assertEqual(ini.getint('OPTIONS', 'collisionoff'), 0)

    def setUp(self):
        self.temp=fixture_temp(); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)/'local/ii-parallel/fixture-menu'; self.data=fixture(self.base)
        self.cat=model.catalog(self.base); self.state=model.initial_state()

    def complete(self, state, *, finished=1, time=78000, exit_code=0):
        game,_,pending=model.race_inputs(state,GAME,RASER)
        running=copy.deepcopy(state);running['pending']=pending
        game=model.replace_ini(game,{('PLAYER','finished'):finished,('PLAYER','tracktime'):time})
        return model.finish_race(running,game,token=pending['token'],exit_code=exit_code)

    def test_campaign_unlocks_sequentially_and_finale_stops_at_seven(self):
        state=self.state
        for track in range(7):
            self.assertEqual(state['track'],track)
            self.assertEqual(model.profile(state)['next_track'],track)
            if track < 6:
                with self.assertRaises(ValueError):model.mutate(state,'track',{'track':track+1},self.cat)
            state=self.complete(state)
            self.assertEqual(model.profile(state)['next_track'],track+1)
        self.assertEqual(state['track'],6)
        self.assertIn('Finale voltooid',state['last_message'])
        self.assertEqual(model.profile(self.complete(state))['next_track'],7)

    def test_replay_crash_abort_and_missing_time_cannot_unlock(self):
        for args in ({'finished':0},{'time':0},{'exit_code':1}):
            result=self.complete(self.state,**args)
            self.assertEqual(model.profile(result)['next_track'],0)
            self.assertEqual(result['track'],0)
        unlocked=self.complete(self.state)
        replay=model.mutate(unlocked,'track',{'track':0},self.cat)
        self.assertEqual(model.profile(self.complete(replay))['next_track'],1)

    def test_locked_start_refused_before_native_configs_or_state_are_written(self):
        self.state['track']=1
        with self.assertRaises(ValueError):model.start_race(self.base,self.state)
        self.assertEqual((self.data/'GAME.INI').read_bytes(),GAME)
        self.assertEqual((self.data/'RASER.INI').read_bytes(),RASER)
        self.assertFalse((self.base/'menu-state.json').exists())

    def test_each_profile_has_independent_progress_and_reset_starts_at_first(self):
        first=self.complete(self.state);first_id=first['selected']
        second=model.mutate(first,'player',{'new_name':'Second'},self.cat)
        self.assertEqual(second['track'],0)
        self.assertEqual(model.profile(second)['next_track'],0)
        switched=model.mutate(second,'player',{'id':first_id},self.cat)
        self.assertEqual(switched['track'],1)
        self.assertEqual(model.profile(switched)['next_track'],1)
        reset=model.mutate(switched,'reset',{'confirmed':True},self.cat)
        self.assertEqual(reset['track'],0)
        self.assertEqual(model.profile(reset)['next_track'],0)
        self.assertEqual(model.profile(reset)['records'],{})

    def test_old_profiles_migrate_consecutive_records_and_clamp_saved_track(self):
        for records,next_track in [({'3':73000},0),({'0':1,'1':2,'3':3},2),({str(i):1 for i in range(7)},7)]:
            with self.subTest(records=records):
                old=copy.deepcopy(self.state);p=model.profile(old)
                del p['next_track'];p['records']=records;old['track']=6
                (self.base/'menu-state.json').write_text(json.dumps(old),encoding='utf-8')
                before=(self.base/'menu-state.json').read_bytes()
                migrated=model.dispatch(self.base,'check',{})['state']
                self.assertEqual(model.profile(migrated)['next_track'],next_track)
                self.assertEqual(migrated['track'],min(next_track,6))
                self.assertEqual(model.profile(migrated)['records'],records)
                self.assertEqual((self.base/'menu-state.json').read_bytes(),before)

    def test_progress_rejects_invalid_values_and_locked_pending_result(self):
        for value in (-1,8,True,'1'):
            invalid=copy.deepcopy(self.state);model.profile(invalid)['next_track']=value
            with self.subTest(value=value),self.assertRaises(ValueError):model.validate_state(invalid)
        game,_,pending=model.race_inputs(self.state,GAME,RASER)
        pending['track']=2;self.state['pending']=pending
        game=model.replace_ini(game,{('ETAPPE','etappe'):2,('PLAYER','finished'):1,('PLAYER','tracktime'):100})
        with self.assertRaises(ValueError):model.finish_race(self.state,game,token=pending['token'],exit_code=0)

    def test_start_resets_stale_finish_and_only_changes_native_contract(self):
        self.state['track']=2;self.state['settings']['laps']=3
        model.profile(self.state)['next_track']=2
        self.state['settings']['keys']['UP']=87
        game,raser,pending=model.race_inputs(self.state,GAME,RASER)
        parsed=model.read_ini(game)
        self.assertEqual(parsed.getint('PLAYER','finished'),0)
        self.assertEqual(parsed.getint('PLAYER','tracktime'),0)
        self.assertEqual(parsed.getint('PLAYER','money'),35000)
        self.assertEqual(parsed.getint('ETAPPE','etappe'),2)
        self.assertEqual(parsed.getint('INPUT','UP'),87)
        self.assertEqual(parsed.getint('OPTIONS','Nrlaps'),3)
        self.assertIn(b'collisionoff=0 ; guard\r\n',game)
        self.assertEqual(game.split(b'[RACERS]')[1],GAME.split(b'[RACERS]')[1])
        self.assertEqual(model.read_ini(raser).getint('PROGRAM','RESOLUTION'),3)
        self.assertEqual(model.read_ini(raser).getint('HELPDESK','DEBUGON'),0)
        self.assertEqual(pending['track'],2)

    def test_garage_compares_installed_and_candidate_bonuses_without_inventing_speed(self):
        before = model.garage_stats(self.state, self.cat)
        self.assertEqual(before['base']['speed'],150)
        self.assertEqual(before['bars']['speed'],25)
        self.assertEqual(before['bars_after_purchase']['motor']['speed'],40)
        self.assertEqual(before['after_purchase']['motor']['speed'],15)
        upgraded=model.mutate(self.state,'upgrade',{'item':'motor'},self.cat)
        stats=model.garage_stats(upgraded,self.cat)
        self.assertEqual(stats['base']['speed'],150)
        self.assertEqual(stats['bonuses']['speed'],15)
        self.assertEqual(stats['bars']['speed'],40)
        self.assertEqual(stats['bars_after_purchase']['motor']['speed'],40)
        self.assertEqual(stats['bars_after_purchase']['gears']['speed'],55)
        self.assertEqual(stats['after_purchase']['motor']['speed'],15)
        self.assertEqual(stats['after_purchase']['gears']['speed'],30)
        self.assertEqual(stats['after_purchase']['gears']['acceleration'],20)
        self.assertEqual(stats['after_purchase']['turbo'],stats['bonuses'])
        self.assertEqual(model.profile(self.state)['upgrades']['motor'],False)

    def test_garage_bars_keep_one_scale_and_saturate_without_wrapping(self):
        catalog=copy.deepcopy(self.cat)
        catalog['cars'][0]['handling']=80
        self.state['profiles'][0]['upgrades']['tires']=True
        stats=model.garage_stats(self.state,catalog)
        self.assertEqual(stats['bars']['handling'],100)
        self.assertEqual(stats['bars_after_purchase']['tires']['handling'],100)
        self.assertEqual(stats['bars']['speed'],25)
        self.assertEqual(stats['bars_after_purchase']['motor']['speed'],40)
        self.assertTrue(all(0 <= value <= 100 for value in stats['bars'].values()))

    def test_transaction_rolls_back_both_configs_if_state_write_fails(self):
        with patch.object(model,'save_state',side_effect=OSError('fixture write failure')):
            with self.assertRaises(OSError):model.start_race(self.base,self.state)
        self.assertEqual((self.data/'GAME.INI').read_bytes(),GAME)
        self.assertEqual((self.data/'RASER.INI').read_bytes(),RASER)
        self.assertFalse((self.base/'menu-state.json').exists())

    def test_map_missing_refused_before_any_write(self):
        (self.data/'ETAPPE0.RMP').unlink()
        with self.assertRaises(ValueError):model.start_race(self.base,self.state)
        self.assertEqual((self.data/'GAME.INI').read_bytes(),GAME)

    def test_completed_race_saves_time_once_and_rejects_wrong_token(self):
        game,_,pending=model.race_inputs(self.state,GAME,RASER);self.state['pending']=pending
        game=model.replace_ini(game,{('PLAYER','finished'):1,('PLAYER','tracktime'):78000,
                                    ('PLAYER','money'):37000,('PLAYER','damage'):20})
        with self.assertRaises(ValueError):model.finish_race(self.state,game,token='0'*32,exit_code=0)
        result=model.finish_race(self.state,game,token=pending['token'],exit_code=0)
        self.assertEqual(model.profile(result)['records'],{'0':78000})
        self.assertEqual(model.profile(result)['money'],37000)
        self.assertEqual(model.profile(result)['next_track'],1)
        self.assertEqual(result['track'],1)
        with self.assertRaises(ValueError):model.finish_race(result,game,token=pending['token'],exit_code=0)

    def test_crash_does_not_accept_partial_or_stale_finish(self):
        _,_,pending=model.race_inputs(self.state,GAME,RASER);self.state['pending']=pending
        result=model.finish_race(self.state,GAME,token=pending['token'],exit_code=-1073741819)
        self.assertEqual(model.profile(result)['money'],35000)
        self.assertEqual(model.profile(result)['records'],{})
        self.assertIn('C0000005',result['last_message'])

    def test_wrong_native_car_and_track_refused(self):
        game,_,pending=model.race_inputs(self.state,GAME,RASER);self.state['pending']=pending
        for key,value in [(('PLAYER','car'),1),(('ETAPPE','etappe'),6)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                model.finish_race(self.state,model.replace_ini(game,{key:value}),token=pending['token'],exit_code=0)

    def test_affordability_duplicate_upgrade_and_car_reset(self):
        upgraded=model.mutate(self.state,'upgrade',{'item':'motor'},self.cat)
        self.assertTrue(model.profile(upgraded)['upgrades']['motor'])
        with self.assertRaises(ValueError):model.mutate(upgraded,'upgrade',{'item':'motor'},self.cat)
        with self.assertRaises(ValueError):model.mutate(upgraded,'buy',{'car':6},self.cat)
        purchased=model.mutate(upgraded,'buy',{'car':1},self.cat)
        self.assertEqual(model.profile(purchased)['car'],1)
        self.assertFalse(any(model.profile(purchased)['upgrades'].values()))

    def test_keyboard_names_and_unavailable_tracks_validated(self):
        for command,payload in [('name',{'name':'  '}),('track',{'track':7}),('settings',{'keys':{**self.state['settings']['keys'],'UP':37}}),('settings',{'laps':0})]:
            with self.subTest(command=command),self.assertRaises(ValueError):model.mutate(self.state,command,payload,self.cat)
        self.assertEqual(model.mutate(self.state,'name',{'name':'Röbin'},self.cat)['profiles'][0]['name'],'Röbin')

    def test_check_does_not_write_and_interrupted_race_resets_without_import(self):
        model.dispatch(self.base,'check',{})
        self.assertFalse((self.base/'menu-state.json').exists())
        model.start_race(self.base,self.state)
        result=model.dispatch(self.base,'load',{})
        self.assertIsNone(result['state']['pending'])
        self.assertEqual(model.profile(result['state'])['records'],{})

    def test_duplicate_keys_no_mutation_and_state_backup(self):
        with self.assertRaises(Exception):model.race_inputs(self.state,GAME+b'[PLAYER]\ncar=1\n',RASER)
        model.save_state(self.base,self.state)
        changed=model.mutate(self.state,'name',{'name':'Robin'},self.cat);model.save_state(self.base,changed)
        self.assertEqual(json.loads((self.base/'menu-state.previous.json').read_bytes())['profiles'][0]['name'],'Speler')

    def test_reset_wipes_all_profiles_records_settings_and_previous_state(self):
        changed=model.mutate(self.state,'name',{'name':'Old player'},self.cat)
        changed=model.mutate(changed,'player',{'new_name':'Second'},self.cat)
        p=model.profile(changed);p.update(car=4,money=11,damage=23,records={'3':73000})
        p['upgrades']['motor']=True;changed['settings']['laps']=9;changed['track']=6
        model.save_state(self.base,changed)
        before=(self.base/'menu-state.json').read_bytes()
        for payload in ({},{'confirmed':False},{'confirmed':1}):
            with self.assertRaises(ValueError):model.dispatch(self.base,'reset',payload)
            self.assertEqual((self.base/'menu-state.json').read_bytes(),before)
        result=model.dispatch(self.base,'reset',{'confirmed':True})['state']
        self.assertEqual(len(result['profiles']),1)
        self.assertNotIn(result['selected'],{p['id'] for p in changed['profiles']})
        expected=model.initial_state();expected['selected']=result['selected'];expected['profiles'][0]['id']=result['selected']
        expected['last_message']=result['last_message'];self.assertEqual(result,expected)
        self.assertEqual(json.loads((self.base/'menu-state.previous.json').read_bytes()),result)
        self.assertEqual((self.data/'GAME.INI').read_bytes(),GAME)

    def test_reset_refuses_active_race_and_keeps_state(self):
        model.start_race(self.base,self.state);before=(self.base/'menu-state.json').read_bytes()
        with self.assertRaises(ValueError):model.dispatch(self.base,'reset',{'confirmed':True})
        self.assertEqual((self.base/'menu-state.json').read_bytes(),before)


class FrontendAssetTests(unittest.TestCase):
    def test_preview_isolates_original_white_skin_and_separate_wheel_positions(self):
        mesh=VehicleMesh(((-8.,3.,-12.,0.,0.,1.,0.,0.,1),
                          (8.,3.,12.,0.,0.,1.,.5,.5,1),
                          (0.,14.,0.,0.,0.,1.,.2,.3,1)),((0,1,2,0,7,1),))
        porsche=prepare.preview_mesh(mesh,4)
        self.assertEqual(porsche['uv'],[[.5/128,.5/128],[127.5/128,127.5/128],[.4,.6]])
        self.assertEqual(porsche['texture_index'],3)
        self.assertEqual(porsche['paint_color'],'#D51E26')
        self.assertEqual(prepare.preview_mesh(mesh,1)['uv'],porsche['uv'])
        self.assertEqual(porsche['positions'],[list(v[:3]) for v in mesh.vertices])
        self.assertEqual(len(porsche['wheel_centers']),4)
        self.assertEqual(len({v[2] for v in porsche['wheel_centers']}),2)
        self.assertEqual(prepare.preview_mesh(mesh,0)['uv'],[list(v[6:8]) for v in mesh.vertices])
        self.assertEqual(prepare.preview_mesh(mesh,0)['texture_index'],1)
        for invalid in (True,-1,7):
            with self.assertRaises(ValueError):prepare.preview_mesh(mesh,invalid)

    def test_cursor_and_index_bounds(self):
        for size in (32,48):
            data=prepare.cursor_bytes(size)
            self.assertEqual(struct.unpack_from('<HHH',data),(0,2,1))
            self.assertEqual(struct.unpack_from('<ii',data,26),(size,size*2))
        image=b'abcdef'
        index=struct.pack('<H20sI20sI',2,b'Car.d3d',0,b'Car.d3d',3)
        with self.assertRaises(ValueError):prepare.resource(index,image,'Car.d3d')
        with self.assertRaises(ValueError):prepare.resource(index[:-1],image,'Car.d3d')

    def test_painted_roof_preserves_geometry_and_keeps_windows_textured(self):
        vertices=tuple((x,y,z,0.,1.,0.,.1,.3,1) for x,y,z in
                       ((-3,12,0),(3,12,0),(0,12,4),(0,0,0),(0,8,4)))
        mesh=VehicleMesh(vertices,((0,1,2,0,7,1),(0,3,4,0,7,1)))
        preview=prepare.preview_mesh(mesh,4)
        self.assertEqual(preview['roof_triangles'],[[0,1,2]])
        self.assertEqual(preview['triangles'],[[0,3,4]])
        self.assertEqual(preview['positions'],[list(v[:3]) for v in vertices])
        self.assertEqual(prepare.preview_mesh(mesh,0)['roof_triangles'],[])

    def test_pcx_bmp_orientation_and_no_native_execution_in_bridge(self):
        palette=bytes([255,0,0,0,0,255])+bytes(762)
        data=prepare.bmp_from_pcx(encode_pcx(IndexedImage(2,2,bytes([0,0,1,1]),palette)))
        self.assertEqual(data[:2],b'BM')
        self.assertEqual(data[54:57],bytes([255,0,0]))
        self.assertNotIn('subprocess',Path(model.__file__).read_text())

    def test_porsche_preview_materials_preserve_every_face_and_position(self):
        vertices=tuple((x,y,z,0.,1.,0.,.1,.3,1) for x,y,z in
                       ((-3,12,-3),(3,12,-3),(0,12,0),
                        (-3,12,1),(3,12,1),(0,8,8),
                        (-3,6,12),(3,6,12),(0,6,20),
                        (-3,0,-10),(3,0,-10),(0,3,-10)))
        triangles=tuple((i,i+1,i+2,0,7,1) for i in range(0,12,3))
        preview=prepare.preview_mesh(VehicleMesh(vertices,triangles),4)
        groups=[preview[key] for key in ('triangles','roof_triangles','glass_triangles','paint_triangles')]
        self.assertEqual([len(group) for group in groups],[1,1,1,1])
        self.assertCountEqual([tuple(t) for group in groups for t in group],[t[:3] for t in triangles])
        self.assertEqual(preview['positions'],[list(v[:3]) for v in vertices])

    def test_ii_mask_indices_are_transparent_but_black_remains_opaque(self):
        palette=bytes(254*3)+bytes((255,0,127,255,0,255))
        data=prepare.png_from_pcx(encode_pcx(IndexedImage(4,1,bytes([0,254,255,0]),palette)))
        offset=8;compressed=b''
        while offset<len(data):
            size=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8]
            if kind==b'IDAT':compressed+=data[offset+8:offset+8+size]
            offset+=12+size
        self.assertEqual(zlib.decompress(compressed),b'\0'+bytes((0,0,0,255))+bytes(8)+bytes((0,0,0,255)))

    def test_isolated_skin_excludes_adjacent_car_pixels_and_retains_mask(self):
        palette=bytes([100,120,140,250,0,0])+bytes(756)+bytes([255,0,127,255,0,255])
        pixels=bytearray([1]*65536)
        for y in range(128):pixels[y*256:y*256+128]=bytes(128)
        pixels[0]=255
        data=prepare.isolated_white_skin(encode_pcx(IndexedImage(256,256,bytes(pixels),palette)))
        self.assertEqual(struct.unpack_from('>II',data,16),(128,128))
        offset=8;compressed=b''
        while offset<len(data):
            size=struct.unpack_from('>I',data,offset)[0]
            if data[offset+4:offset+8]==b'IDAT':compressed+=data[offset+8:offset+8+size]
            offset+=12+size
        decoded=zlib.decompress(compressed)
        self.assertEqual(decoded[1:5],bytes(4));self.assertEqual(decoded[5:9],bytes([100,120,140,255]))
        self.assertNotIn(bytes([250,0,0,255]),decoded)


@unittest.skipUnless(sys.platform=='win32' and shutil.which('pwsh'),'Windows WPF required')
class FrontendWpfTests(unittest.TestCase):
    def test_real_controls_with_synthetic_backend_and_fake_race(self):
        with fixture_temp() as temp:
            base=Path(temp)/'local/ii-parallel/fixture-menu';fixture(base)
            assets=base/'assets';assets.mkdir()
            for size in (32,48):(assets/f'arrow{size}.cur').write_bytes(prepare.cursor_bytes(size))
            mesh={'positions':[[-8,0,0],[8,0,0],[0,16,0]],'uv':[[0,0],[1,0],[.5,1]],'triangles':[[0,1,2]]}
            (assets/'wheel.json').write_text(json.dumps(mesh))
            for i in range(7):(assets/f'car{i}.json').write_text(json.dumps(mesh|{'texture_index':0,'wheel_centers':[[-2,0,-2],[2,0,-2],[-2,0,2],[2,0,2]]}))
            palette=bytes([80,120,240])+bytes(765)
            image=prepare.png_from_pcx(encode_pcx(IndexedImage(2,2,bytes(4),palette)))
            for i in range(4):(assets/f'texture{i}.png').write_bytes(image)
            for name in prepare.PART_ART_NAMES:(assets/f'part-{name}.png').write_bytes(image)
            for car_id in range(7):
                (assets/f'car{car_id}-preview.png').write_bytes(image)
            for source,destination in [('ii_frontend.ps1','Menu.ps1'),('ii_frontend.xaml','Menu.xaml'),('ii_frontend_state.py','Backend.py'),('ii_owned_session.ps1','OwnedSession.ps1')]:
                shutil.copyfile(ROOT/'tools'/source,base/destination)
            files=[{'path':p.relative_to(base).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in base.rglob('*') if p.is_file()]
            (base/'Frontend.json').write_text(json.dumps({'schema':1,'game':'a2racer2','native_menu_used':False,'files':files,'python':sys.executable,'report_path':str(base),'synthetic_fixture':True}))
            check=subprocess.run([shutil.which('pwsh'),'-NoProfile','-STA','-File',str(base/'Menu.ps1'),'-CheckOnly'],capture_output=True,text=True,timeout=60)
            self.assertEqual(check.returncode,0,check.stdout+check.stderr)
            self.assertFalse((base/'menu-state.json').exists())
            result=subprocess.run([shutil.which('pwsh'),'-NoProfile','-STA','-File',str(base/'Menu.ps1'),'-UiCheck'],capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            record=json.loads(result.stdout)
            self.assertTrue(record['ui_actions_passed']);self.assertFalse(record['game_started'])
            self.assertEqual(record['fake_races_started'],2)
            self.assertEqual(record['fake_races_disposed'],2)
            self.assertTrue(record['close_request_passed'])
            self.assertTrue(record['race_lifetime_passed'])


if __name__=='__main__':unittest.main()
