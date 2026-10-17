"""Synthetic fixtures only. No installer invocation, game data, real registry or shortcuts."""
from pathlib import Path
import io,json,stat,struct,tempfile,unittest,zipfile,zlib
from unittest.mock import patch
try:
    from . import build_msi as build
    from .cab_codec import read_cab
except ImportError:
    import build_msi as build
    from cab_codec import read_cab

class MSITests(unittest.TestCase):
    def temp(self):
        root=build.HERE/'test-output';root.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=root)
        if not Path(temp.name).resolve().is_relative_to(root.resolve()):raise ValueError('Fixture escaped workspace.')
        self.addCleanup(temp.cleanup)
        return temp
    def archive(self,rows):
        temp=self.temp()
        target=Path(temp.name)/'fixture.zip'
        with zipfile.ZipFile(target,'w') as z:
            for name,data in rows:z.writestr(name,data)
        return target

    def test_safe_payload_preserves_bytes_and_accepts_directory_entries(self):
        path=self.archive([('app/',b''),('app/source.txt',b'fixture\0bytes'),(build.NAME+'.exe',b'synthetic exe sentinel')])
        self.assertEqual(build.read_payload(path),{'app/source.txt':b'fixture\0bytes',build.NAME+'.exe':b'synthetic exe sentinel'})
        icon=path.parent/'fixture.ico';icon.write_bytes(b'synthetic icon sentinel')
        output=path.parent/'new-build'
        self.assertEqual(build.prepare_paths(path,icon,output),(path.absolute(),icon.absolute(),output.absolute()))
        with self.assertRaises(FileExistsError):build.prepare_paths(path,icon,output)

    def test_unsafe_and_protected_paths_are_rejected(self):
        for name in ('../bad','/app/bad','C:/app/bad','app/../bad','app/a:stream','app/a.','app/a ',
                     'app/NUL.txt','app/COM1','app/a\\b','app/a\nb','app/a\x01b','other/source','app/LOCAL/profile.json',
                     'app/Payload/game.bin','app/local','app/payload'):
            with self.subTest(name=name),self.assertRaises(ValueError):build.safe_name(name)

    def test_duplicate_case_and_file_directory_collisions_fail(self):
        for rows in ([('app/a',b'1'),('APP/A',b'2')],[('app/a',b'1'),('app/a/b',b'2')]):
            path=self.archive([(build.NAME+'.exe',b'fixture')]+rows)
            with self.assertRaises(ValueError):build.read_payload(path)

    def test_links_and_missing_native_launcher_fail(self):
        path=self.archive([('app/a',b'fixture')])
        with patch.object(Path,'lstat',return_value=type('FakeStat',(),{'st_mode':stat.S_IFLNK,'st_file_attributes':0})()):
            with self.assertRaises(ValueError):build.checked_path(path)
        with self.assertRaises(ValueError):build.checked_path(Path('parent')/'..'/'escape')
        for device in ('\\\\?\\C:\\fixture','\\\\.\\fixture'):
            with self.assertRaises(ValueError):build.checked_path(Path(device))
        with self.assertRaises(ValueError):build.read_payload(path)
        temp=self.temp()
        path=Path(temp.name)/'link.zip'
        entry=zipfile.ZipInfo('app/link');entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
        with zipfile.ZipFile(path,'w') as z:z.writestr(entry,'target')
        with self.assertRaises(ValueError):build.read_payload(path)

    def test_powershell_selection_prefers_explicit_then_pwsh_then_windows_powershell(self):
        temp=self.temp();root=Path(temp.name)
        modern=root/'pwsh.exe';legacy=root/'powershell.exe'
        modern.write_bytes(b'Synthetic shell path fixture');legacy.write_bytes(b'Synthetic shell path fixture')
        with patch.object(build.shutil,'which',side_effect=lambda name:str(modern) if name=='pwsh' else str(legacy)):
            self.assertEqual(build.powershell_path(),modern.absolute())
            self.assertEqual(build.powershell_path(legacy),legacy.absolute())
        with patch.object(build.shutil,'which',side_effect=lambda name:None if name=='pwsh' else str(legacy)):
            self.assertEqual(build.powershell_path(),legacy.absolute())
        with patch.object(build.shutil,'which',return_value=None):
            with self.assertRaises(FileNotFoundError):build.powershell_path()
        other=root/'unexpected.exe';other.write_bytes(b'Not PowerShell')
        with self.assertRaises(ValueError):build.powershell_path(other)

    def plan(self,version='0.1.5'):return build.build_plan({build.NAME+'.exe':b'sentinel','app/tools/fixture.py':b'fixture'},Path('synthetic-stage'),Path('synthetic.ico'),version)
    def test_component_and_upgrade_identity_survive_future_version(self):
        first=self.plan()
        second=self.plan('0.1.6')
        self.assertEqual(first['upgrade_code'],second['upgrade_code']);self.assertNotEqual(first['product_code'],second['product_code'])
        def components(plan):return next(t['rows'] for t in plan['tables'] if t['name']=='Component')
        self.assertEqual(components(first),components(second));self.assertNotEqual(first['package_code'],self.plan()['package_code'])
        for value in ('0.1.5-beta5','256.0.1','1.0.65536','1.2','1.2.3.4','01.2.3'):
            with self.subTest(version=value),self.assertRaises(ValueError):build.validate_version(value)

    def test_plan_is_per_user_and_uses_standard_actions(self):
        plan=self.plan();tables={t['name']:t['rows'] for t in plan['tables']};props=dict(tables['Property'])
        self.assertNotIn('ALLUSERS',props);self.assertEqual(props['MSIINSTALLPERUSER'],'1')
        self.assertNotIn('CustomAction',tables);self.assertNotIn('RemoveFile',tables)
        self.assertIn('NOT ALLUSERS',dict(tables['LaunchCondition']));self.assertIn('VersionNT64',dict(tables['LaunchCondition']))
        self.assertTrue(all(row[-1].isupper() for row in tables['Upgrade']))
        self.assertEqual(set(props['SecureCustomProperties'].split(';')),{'INSTALLDIR','OLDPRODUCTS','NEWERVERSIONDETECTED'})
        self.assertTrue(all(row[3]==260 for row in tables['Component']))
        self.assertTrue(all(row[1]==1 and row[2] in (build.INSTALLER_REGISTRY_KEY,build.INSTALLER_REGISTRY_KEY+r'\Components') for row in tables['Registry']))
        actions={a:sequence for a,c,sequence in tables['InstallExecuteSequence']}
        self.assertLess(actions['InstallInitialize'],actions['RemoveExistingProducts']);self.assertLess(actions['RemoveExistingProducts'],actions['ProcessComponents'])
        self.assertTrue(any(row[9]=='Installeren' for row in tables['Control']))

    def test_previous_folder_is_found_before_costing_and_saved_by_its_own_component(self):
        tables={t['name']:t['rows'] for t in self.plan()['tables']}
        self.assertEqual(tables['AppSearch'],[['INSTALLDIR','PreviousInstallDir']])
        self.assertEqual(tables['RegLocator'],[['PreviousInstallDir',1,build.INSTALLER_REGISTRY_KEY,'InstallDir',16]])
        self.assertIn('Signature',tables)
        self.assertFalse(tables['Signature'],'Directory searches must not be authored as file signatures.')
        for sequence in ('InstallUISequence','InstallExecuteSequence'):
            actions={action:number for action,condition,number in tables[sequence]}
            self.assertLess(actions['FindRelatedProducts'],actions['AppSearch'])
            self.assertLess(actions['AppSearch'],actions['CostInitialize'])
        row=next(row for row in tables['Registry'] if row[0]=='R_InstallDir')
        self.assertEqual(row[1:],[1,build.INSTALLER_REGISTRY_KEY,'InstallDir','[INSTALLDIR]','C_InstallDir'])
        component=next(row for row in tables['Component'] if row[0]=='C_InstallDir')
        self.assertEqual(component[2:],[ 'INSTALLDIR',260,None,'R_InstallDir'])
        self.assertIn(['MainFeature','C_InstallDir'],tables['FeatureComponents'])

    def test_folder_controls_validate_before_install_and_cancel_undoes_browse_changes(self):
        tables={t['name']:t['rows'] for t in self.plan()['tables']}
        controls={(row[0],row[1]):row for row in tables['Control']}
        self.assertEqual(controls['WelcomeDlg','InstallPath'][2],'PathEdit')
        for name in ('DirectoryCombo','DirectoryList','Path'):
            self.assertEqual(controls['BrowseDlg',name][8],'INSTALLDIR')
        events=tables['ControlEvent']
        install=sorted((row for row in events if row[:2]==['WelcomeDlg','Install']),key=lambda row:row[5])
        self.assertEqual([(row[2],row[3]) for row in install],[('SetTargetPath','INSTALLDIR'),('EndDialog','Return')])
        choose=sorted((row for row in events if row[:2]==['BrowseDlg','Choose']),key=lambda row:row[5])
        self.assertEqual([(row[2],row[3]) for row in choose],[('SetTargetPath','INSTALLDIR'),('EndDialog','Return')])
        cancel=sorted((row for row in events if row[:2]==['BrowseDlg','Cancel']),key=lambda row:row[5])
        self.assertEqual([(row[2],row[3]) for row in cancel],[('Reset','0'),('EndDialog','Return')])
        self.assertTrue(all(row[4]=='NOT Installed AND NOT OLDPRODUCTS' for row in events if row[2] in ('SetTargetPath','SpawnDialog')))
        for control in ('InstallPath','Browse'):
            self.assertIn(['WelcomeDlg',control,'Disable','Installed OR OLDPRODUCTS'],tables['ControlCondition'])
        self.assertFalse(any(row[0]=='MaintenanceDlg' and row[2]=='SetTargetPath' for row in events))

    def test_dialog_tab_chains_and_event_references_have_no_dead_controls(self):
        tables={t['name']:t['rows'] for t in self.plan()['tables']}
        controls={(row[0],row[1]):row for row in tables['Control']}
        for row in tables['Dialog']:
            self.assertIsNotNone(row[7], row[0]+' needs Control_First')
            for identifier in row[7:]:
                if identifier:self.assertIn((row[0],identifier),controls)
            if row[8]:self.assertEqual(controls[row[0],row[8]][2],'PushButton')
        welcome=next(row for row in tables['Dialog'] if row[0]=='WelcomeDlg')
        self.assertEqual(welcome[7:10],['InstallPath','Install','Cancel'])
        self.assertEqual(controls['WelcomeDlg',welcome[7]][2],'PathEdit')
        for dialog,control,event,argument,condition,order in tables['ControlEvent']:
            self.assertIn((dialog,control),controls)
            if event=='SpawnDialog':self.assertIn(argument,{row[0] for row in tables['Dialog']})
        for row in tables['Control']:
            if row[10]:self.assertIn((row[0],row[10]),controls)
        for name,first in (('WelcomeDlg','InstallPath'),('BrowseDlg','FolderLabel')):
            visited=set();current=first
            while current not in visited:
                visited.add(current);current=controls[name,current][10]
                self.assertIsNotNone(current)
            active={row[1] for row in tables['Control'] if row[0]==name and row[2] not in ('Text','Line')}
            self.assertTrue(active<=visited)

    def test_error_dialog_displays_path_errors_with_standard_response_buttons(self):
        tables={t['name']:t['rows'] for t in self.plan()['tables']}
        self.assertEqual(dict(tables['Property'])['ErrorDialog'],'ErrorDlg')
        error=next(row for row in tables['Dialog'] if row[0]=='ErrorDlg')
        self.assertEqual(error[5]&65536,65536)
        self.assertEqual(error[7:10],['ErrorText',None,None])
        controls={row[1]:row for row in tables['Control'] if row[0]=='ErrorDlg'}
        self.assertEqual(controls['ErrorText'][2],'Text')
        expected={'A':'ErrorAbort','C':'ErrorCancel','I':'ErrorIgnore','N':'ErrorNo',
                  'O':'ErrorOk','R':'ErrorRetry','Y':'ErrorYes'}
        self.assertEqual(set(controls),set(expected)|{'ErrorText'})
        self.assertTrue(all(controls[bid][2]=='PushButton' for bid in expected))
        self.assertEqual({tuple(controls[bid][3:7]) for bid in expected},{(146,235,78,20)})
        self.assertTrue(all(row[10] is None for row in controls.values()))
        events=[row for row in tables['ControlEvent'] if row[0]=='ErrorDlg']
        self.assertEqual({row[1]:row[3] for row in events},expected)
        self.assertTrue(all(row[2]=='EndDialog' and row[4]=='1' for row in events))

    def test_shortcut_target_is_native_launcher_and_short_names_are_stable(self):
        tables={t['name']:t['rows'] for t in self.plan()['tables']}
        expected='[#'+build.identifier('F_',build.NAME+'.exe')+']'
        self.assertEqual(len(tables['Shortcut']),2)
        self.assertTrue(all(row[4]==expected and row[8]=='A2Icon' for row in tables['Shortcut']))
        self.assertEqual(build.short_name('example.py'),build.short_name('EXAMPLE.py').split('|')[0]+'|example.py')

    def synthetic_cab(self):
        files={'F_one':bytes(range(256))*190,'F_two':b'known synthetic text'*900}
        raw=b''.join(files.values());blocks=[];previous=b''
        for start in range(0,len(raw),32768):
            block=raw[start:start+32768];compressor=zlib.compressobj(wbits=-15,zdict=previous[-32768:])
            packed=b'CK'+compressor.compress(block)+compressor.flush()
            blocks.append(struct.pack('<IHH',0,len(packed),len(block))+packed);previous+=block
        file_table=b'';offset=0
        for name,contents in files.items():
            file_table+=struct.pack('<IIHHHH',len(contents),offset,0,0,0,0)+name.encode()+b'\0';offset+=len(contents)
        body=struct.pack('<IHH',44+len(file_table),len(blocks),1)+file_table+b''.join(blocks)
        header=struct.pack('<4sIIIIIBBHHHHH',b'MSCF',0,36+len(body),0,44,0,3,1,1,len(files),0,0,0)
        return header+body,files

    def test_mszip_multiple_blocks_and_dictionary_restore_every_byte(self):
        cab,files=self.synthetic_cab();self.assertEqual(read_cab(cab),files)
        with self.assertRaises(ValueError):read_cab(cab[:-1])
        bad=bytearray(cab);bad[30]=1
        with self.assertRaises(ValueError):read_cab(bad)

if __name__=='__main__':unittest.main(verbosity=2)
