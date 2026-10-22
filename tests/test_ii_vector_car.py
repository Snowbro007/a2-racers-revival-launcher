"""Synthetic fixtures only: optional vehicle state, resources and native data layout."""
import copy,hashlib,json,struct,unittest
from pathlib import Path
from unittest.mock import patch
from tools import ii_frontend_state as state,ii_vector_car as vector,launcher_model as launcher
from tools.ii_frontend_prepare import resource
from tests.test_ii_frontend import GAME,RASER,fixture,fixture_temp

def synthetic_pe():
    raw=bytearray(2048);raw[:2]=b'MZ';struct.pack_into('<I',raw,0x3c,0x80);raw[0x80:0x84]=b'PE\0\0'
    struct.pack_into('<HH',raw,0x84,0x14c,1);struct.pack_into('<H',raw,0x94,224)
    struct.pack_into('<H',raw,0x98,0x10b);struct.pack_into('<I',raw,0x98+28,0x400000)
    table=0x98+224;raw[table:table+8]=b'.fixture'
    struct.pack_into('<IIII',raw,table+8,1024,vector.WHEEL_VA-0x400000,1024,1024)
    raw[1024:1072]=vector.WHEEL_BEFORE
    return bytes(raw)

def archive(rows):
    index=bytearray(struct.pack('<H',len(rows)));image=bytearray()
    for name,data in rows:
        index.extend(struct.pack('<20sI',name.encode(),len(image)));image.extend(data)
    return bytes(index),bytes(image)

class VectorNativeTests(unittest.TestCase):
    def test_pinned_wheel_data_patch_changes_only_own_48_bytes(self):
        raw=synthetic_pe();result=vector.patch_wheels(raw)
        self.assertEqual(result[:1024],raw[:1024]);self.assertEqual(result[1072:],raw[1072:])
        self.assertEqual(result[1024:1072],vector.WHEEL_AFTER)
        bad=bytearray(raw);bad[1024]^=1
        with self.assertRaises(ValueError):vector.patch_wheels(bytes(bad))
        with self.assertRaises(ValueError):vector.patch_wheels(result)

    def test_nonmatching_native_layouts_are_rejected(self):
        for at,value in ((0,b'NO'),(0x84,b'\x64\x86'),(0x98,b'\x0b\x02'),(0x98+28,b'\0'*4)):
            raw=bytearray(synthetic_pe());raw[at:at+len(value)]=value
            with self.subTest(at=at),self.assertRaises(ValueError):vector.patch_wheels(bytes(raw))

    def test_archive_overlay_preserves_every_unrelated_record(self):
        rows=[('r_diablo.d3d',b'synthetic body'),('RACER01.PCX',b'synthetic palette'),('RACER01.TGA',b'synthetic tga'),('WIEL.d3d',b'synthetic wheel'),('back1.pcx',b'synthetic sky'),('same.bin',b'one'),('same.bin',b'two')]
        index,image=archive(rows);pins={name:hashlib.sha256(data).hexdigest() for name,data in rows[:4]}
        art={'vector-body.d3d':b'new body','racer01-vector.pcx':b'new palette','racer01-vector.tga':b'new tga','vector-wheel.d3d':b'new wheel'}
        with patch.dict(vector.SOURCE_RESOURCES,pins,clear=True):new_index,new_image=vector.overlay(index,image,art)
        self.assertEqual(resource(new_index,new_image,'back1.pcx'),b'synthetic sky')
        self.assertEqual(resource(new_index,new_image,'r_diablo.d3d'),b'new body')
        self.assertEqual(resource(new_index,new_image,'WIEL.d3d'),b'new wheel')
        self.assertEqual(index,archive(rows)[0]);self.assertEqual(image,archive(rows)[1])

class VectorStateTests(unittest.TestCase):
    def test_vehicle_switch_preserves_both_cars_and_shared_campaign(self):
        s=state.initial_state();p=state.profile(s);p['damage']=23;p['upgrades']['motor']=True
        p['records']={'0':12345};p['next_track']=1
        normal=state.vehicle_snapshot(p);budget=p['money'];pid=p['id']
        state.select_vector(p,True);self.assertEqual(p['car'],7);state.validate_state(s)
        p['damage']=11;p['upgrades']['brakes']=True
        state.select_vector(p,False);self.assertEqual(state.vehicle_snapshot(p),normal)
        self.assertEqual((p['id'],p['money'],p['records'],p['next_track']),(pid,budget,{'0':12345},1))
        state.select_vector(p,True);self.assertEqual(p['damage'],11);self.assertTrue(p['upgrades']['brakes'])

    def test_orphan_bonus_and_bad_native_mapping_fail(self):
        s=state.initial_state();state.profile(s)['car']=7
        with self.assertRaises(ValueError):state.validate_state(s)
        s=state.initial_state();p=state.profile(s);state.select_vector(p,True)
        _,_,pending=state.race_inputs(s,GAME,RASER);pending['native_car']=0;s['pending']=pending
        with self.assertRaises(ValueError):state.validate_state(s)

    def test_native_bridge_uses_sport_slot_but_retains_bonus_identity_and_results(self):
        s=state.initial_state();p=state.profile(s);state.select_vector(p,True)
        game,_,pending=state.race_inputs(s,GAME,RASER)
        self.assertEqual(state.read_ini(game).getint('PLAYER','car'),6);self.assertEqual(pending['car'],7)
        finished=state.replace_ini(game,{('PLAYER','finished'):1,('PLAYER','tracktime'):12345,('PLAYER','damage'):12})
        s['pending']=pending;s=state.finish_race(s,finished,token=pending['token'],exit_code=0)
        self.assertEqual(state.profile(s)['car'],7);self.assertEqual(state.profile(s)['damage'],12)
        state.select_vector(state.profile(s),False);self.assertEqual(state.profile(s)['damage'],0)
        self.assertEqual(state.profile(s)['next_track'],1)

    def test_catalog_opt_in_and_turn_off_restore_normal_vehicle_without_disk_mutation(self):
        with fixture_temp() as temp:
            base=Path(temp);fixture(base);s=state.initial_state();state.select_vector(state.profile(s),True);state.save_state(base,s)
            saved=(base/'menu-state.json').read_bytes()
            off=state.dispatch(base,'check',{});self.assertEqual(state.profile(off['state'])['car'],0)
            self.assertEqual(len(off['catalog']['cars']),7);self.assertEqual((base/'menu-state.json').read_bytes(),saved)
            (base/'Frontend.json').write_text(json.dumps({'vector_vehicle':{'enabled':True}}))
            cat=state.catalog(base);self.assertEqual(len(cat['cars']),8)
            self.assertEqual({k:cat['cars'][7][k] for k in state.STAT_KEYS},{k:cat['cars'][6][k] for k in state.STAT_KEYS})

    def test_free_bonus_selection_and_free_return_do_not_spend_budget(self):
        with fixture_temp() as temp:
            base=Path(temp);fixture(base);(base/'Frontend.json').write_text(json.dumps({'vector_vehicle':{'enabled':True}}))
            cat=state.catalog(base);s=state.initial_state();state.profile(s)['money']=0
            s=state.mutate(s,'buy',{'car':7},cat);self.assertEqual(state.profile(s)['money'],0)
            s=state.mutate(s,'buy',{'car':0},cat);self.assertEqual(state.profile(s)['money'],0)

    def test_resource_plan_rejects_traversal_and_modified_overlay_before_write(self):
        with fixture_temp() as temp:
            base=Path(temp);s=state.initial_state();state.select_vector(state.profile(s),True)
            cfg={'vector_vehicle':{'schema':1,'enabled':True,'native_car':6,'menu_car':7,'resources':{'vector':[{'path':'../escape','target':'RCS.IND'},{}]}}}
            with self.assertRaises(ValueError):state.vector_race_files(base,s,cfg,'widescreen')

    def test_repeated_bonus_and_normal_starts_switch_sealed_resources_and_reject_tampering(self):
        with fixture_temp() as temp:
            base=Path(temp);data=fixture(base);s=state.initial_state();state.select_vector(state.profile(s),True)
            resources={}
            for variant in ('normal','vector'):
                resources[variant]=[]
                for name in ('RCS.IND','RCS.IMG'):
                    path=f'vector-vehicle/{variant}/{name}';raw=(variant+' synthetic '+name).encode()
                    (base/path).parent.mkdir(parents=True,exist_ok=True);(base/path).write_bytes(raw)
                    resources[variant].append({'path':path,'target':name,'sha256':hashlib.sha256(raw).hexdigest()})
                    (data/name).write_bytes(b'active initial resource')
            binary=b'synthetic inert native bytes';(data/'SPEL-VECTOR.DAT').write_bytes(binary)
            cfg={'vector_vehicle':{'schema':1,'enabled':True,'native_car':6,'menu_car':7,'resources':resources,
                 'binaries':{'classic':{'binary':'SPEL-VECTOR.DAT','sha256':hashlib.sha256(binary).hexdigest()}}}}
            (base/'Frontend.json').write_text(json.dumps(cfg))
            for chosen in (True,False,True):
                state.select_vector(state.profile(s),chosen);s=state.start_race(base,s)
                for name in ('RCS.IND','RCS.IMG'):
                    self.assertEqual((data/name).read_bytes(),(base/f'vector-vehicle/{"vector" if chosen else "normal"}/{name}').read_bytes())
                self.assertEqual(s['pending'].get('binary'),'SPEL-VECTOR.DAT' if chosen else None)
                s['pending']=None
            before=(data/'GAME.INI').read_bytes();(base/'vector-vehicle/vector/RCS.IMG').write_bytes(b'tampered')
            with self.assertRaises(ValueError):state.start_race(base,s)
            self.assertEqual((data/'GAME.INI').read_bytes(),before)

    def test_launcher_old_settings_migrate_off_and_optional_flags_are_typed(self):
        p=copy.deepcopy(launcher.DEFAULT_SETTINGS['games']['a2racer2']);p.pop('vector_car')
        migrated=launcher.validate_preferences('a2racer2',p);self.assertFalse(migrated['vector_car'])
        for bad in (1,'true',None):
            with self.subTest(bad=bad),self.assertRaises(ValueError):launcher.validate_preferences('a2racer2',dict(migrated,vector_car=bad))
        with self.assertRaises(ValueError):launcher.validate_preferences('a2racer2',dict(migrated,vector_car=True,menu_profile='original'))

if __name__=='__main__':unittest.main()
