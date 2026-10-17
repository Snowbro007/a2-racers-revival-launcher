"""Local standard per-user MSI authoring. Does not install/run payload or upload anything."""
from pathlib import Path, PurePosixPath
import argparse,hashlib,json,os,re,shutil,stat,subprocess,sys,uuid,zipfile

HERE=Path(__file__).resolve().parent
NAMESPACE=uuid.UUID('0bd74d8d-6bee-49b8-9545-9cba32540cee')
UPGRADE_CODE='{'+str(uuid.uuid5(NAMESPACE,'A2 Racers Revival per-user MSI')).upper()+'}'
VERSION='0.1.5'
NAME='A2 Racers Revival'
INSTALLER_REGISTRY_KEY=r'Software\A2 Racers Revival\Installer'

def sha(data):return hashlib.sha256(data).hexdigest()
def identifier(prefix,value):return prefix+sha(value.casefold().encode('ascii'))[:24]
def guid(value):return '{'+str(uuid.uuid5(NAMESPACE,value.casefold())).upper()+'}'
def short_name(name):
    # Unique explicit 8.3 aliases; CAB members use stable File identifiers instead.
    suffix=PurePosixPath(name).suffix[1:]
    ext='.'+suffix.upper() if re.fullmatch('[A-Za-z0-9]{1,3}',suffix) else ''
    return sha(name.casefold().encode('ascii'))[:8].upper()+ext+'|'+name

def safe_name(value):
    if not value or not value.isascii() or '\\' in value or value.startswith('/'):
        raise ValueError('Non-portable archive path: '+repr(value))
    parts=value.split('/')
    reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
    for part in parts:
        if not part or part in ('.','..') or part.rstrip(' .')!=part or any(c in part for c in ':<>"|?*') or any(ord(c)<32 or ord(c)==127 for c in part):
            raise ValueError('Unsafe archive path: '+repr(value))
        if part.split('.')[0].upper() in reserved:raise ValueError('Reserved Windows filename.')
    lower=[p.casefold() for p in parts]
    if not (len(parts)>1 and lower[0]=='app') and value!=NAME+'.exe':
        raise ValueError('Unexpected payload root: '+value)
    if len(parts)>1 and lower[:2] in (['app','local'],['app','payload']):
        raise ValueError('Protected user data is never an installer component.')
    return '/'.join(parts)

def read_payload(path):
    files={};seen=set();total=0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                if info.filename.rstrip('/').casefold()!='app':safe_name(info.filename.rstrip('/'))
                continue
            name=safe_name(info.filename)
            if name.casefold() in seen:raise ValueError('Case-insensitive duplicate.')
            seen.add(name.casefold())
            if stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1:raise ValueError('Links/encryption are not allowed.')
            if info.file_size>512*1024*1024:raise ValueError('Oversized member.')
            total+=info.file_size
            if total>1024*1024*1024 or len(files)>=10000:raise ValueError('Oversized payload.')
            files[name]=archive.read(info)
    if NAME+'.exe' not in files:raise ValueError('Native launcher absent.')
    lowered={p.casefold() for p in files}
    for path in files:
        parent=PurePosixPath(path).parent
        while str(parent)!='.':
            if str(parent).casefold() in lowered:raise ValueError('File/directory collision.')
            parent=parent.parent
    return files

def build_plan(files,stage,icon,version=VERSION):
    validate_version(version)
    tables=[]
    def table(name,columns,key,rows):
        definitions=', '.join('`'+n+'` '+t for n,t in columns)
        sql='CREATE TABLE `'+name+'` ('+definitions+' PRIMARY KEY '+', '.join('`'+k+'`' for k in key)+')'
        tables.append({'name':name,'columns':[n for n,t in columns],'sql':sql,'rows':rows})
    product=guid('Product/'+version)
    table('Property',[('Property','CHAR(72) NOT NULL'),('Value','CHAR(0) LOCALIZABLE')],['Property'],[
        ['ProductCode',product],['ProductVersion',version],['ProductName',NAME],['Manufacturer','A2 Revival fan project'],
        ['ProductLanguage','1043'],['UpgradeCode',UPGRADE_CODE],['MSIINSTALLPERUSER','1'],['ARPNOMODIFY','1'],
        ['ARPPRODUCTICON','A2Icon'],['ARPCONTACT','A2 Revival fan project'],['INSTALLLEVEL','1'],
        ['SecureCustomProperties','INSTALLDIR;OLDPRODUCTS;NEWERVERSIONDETECTED'],['DefaultUIFont','NormalFont'],
        ['ErrorDialog','ErrorDlg']])
    # Directory searches deliberately have no matching Signature row. The empty
    # Signature table is still required by the AppSearch standard action.
    table('Signature',[('Signature','CHAR(72) NOT NULL'),('FileName','CHAR(255) NOT NULL LOCALIZABLE'),('MinVersion','CHAR(20)'),('MaxVersion','CHAR(20)'),('MinSize','LONG'),('MaxSize','LONG'),('MinDate','LONG'),('MaxDate','LONG'),('Languages','CHAR(255)')],['Signature'],[])
    table('AppSearch',[('Property','CHAR(72) NOT NULL'),('Signature_','CHAR(72) NOT NULL')],['Property','Signature_'],[['INSTALLDIR','PreviousInstallDir']])
    table('RegLocator',[('Signature_','CHAR(72) NOT NULL'),('Root','SHORT NOT NULL'),('Key','CHAR(255) NOT NULL'),('Name','CHAR(255)'),('Type','SHORT')],['Signature_'],[['PreviousInstallDir',1,INSTALLER_REGISTRY_KEY,'InstallDir',16]])
    directories=[['TARGETDIR',None,'SourceDir'],['LocalAppDataFolder','TARGETDIR','.'],
                 ['INSTALLDIR','LocalAppDataFolder',short_name(NAME)],['ProgramMenuFolder','TARGETDIR','.'],
                 ['ProgramMenuDir','ProgramMenuFolder',short_name(NAME)],['DesktopFolder','TARGETDIR','.']]
    paths=set()
    for path in files:
        parent=PurePosixPath(path).parent
        while str(parent)!='.':paths.add(str(parent));parent=parent.parent
    for path in sorted(paths,key=lambda p:(p.count('/'),p.casefold())):
        parent=str(PurePosixPath(path).parent)
        directories.append([identifier('D_',path),'INSTALLDIR' if parent=='.' else identifier('D_',parent),short_name(PurePosixPath(path).name)])
    table('Directory',[('Directory','CHAR(72) NOT NULL'),('Directory_Parent','CHAR(72)'),('DefaultDir','CHAR(255) NOT NULL LOCALIZABLE')],['Directory'],directories)
    components=[];registry=[];file_rows=[];feature_rows=[];manifest=[]
    for sequence,path in enumerate(sorted(files,key=str.casefold),1):
        fid=identifier('F_',path);cid=identifier('C_',path);rid=identifier('R_',path)
        parent=str(PurePosixPath(path).parent);directory='INSTALLDIR' if parent=='.' else identifier('D_',parent)
        components.append([cid,guid('Component/'+path),directory,260,None,rid])
        registry.append([rid,1,INSTALLER_REGISTRY_KEY+r'\Components',cid,'[ProductVersion]',cid])
        file_rows.append([fid,cid,short_name(PurePosixPath(path).name),len(files[path]),None,None,512,sequence])
        feature_rows.append(['MainFeature',cid]);manifest.append({'path':path,'id':fid,'component':cid,'size':len(files[path]),'sha256':sha(files[path]),'sequence':sequence})
    components.append(['C_Shortcuts',guid('Component/Shortcuts'),'INSTALLDIR',260,None,'R_Shortcuts'])
    registry.append(['R_Shortcuts',1,INSTALLER_REGISTRY_KEY+r'\Components','Shortcuts','[ProductVersion]','C_Shortcuts'])
    feature_rows.append(['MainFeature','C_Shortcuts'])
    components.append(['C_InstallDir',guid('Component/InstallDir'),'INSTALLDIR',260,None,'R_InstallDir'])
    registry.append(['R_InstallDir',1,INSTALLER_REGISTRY_KEY,'InstallDir','[INSTALLDIR]','C_InstallDir'])
    feature_rows.append(['MainFeature','C_InstallDir'])
    table('Component',[('Component','CHAR(72) NOT NULL'),('ComponentId','CHAR(38)'),('Directory_','CHAR(72) NOT NULL'),('Attributes','SHORT NOT NULL'),('Condition','CHAR(255)'),('KeyPath','CHAR(72)')],['Component'],components)
    table('Registry',[('Registry','CHAR(72) NOT NULL'),('Root','SHORT NOT NULL'),('Key','CHAR(255) NOT NULL LOCALIZABLE'),('Name','CHAR(255) LOCALIZABLE'),('Value','CHAR(0) LOCALIZABLE'),('Component_','CHAR(72) NOT NULL')],['Registry'],registry)
    table('File',[('File','CHAR(72) NOT NULL'),('Component_','CHAR(72) NOT NULL'),('FileName','CHAR(255) NOT NULL LOCALIZABLE'),('FileSize','LONG NOT NULL'),('Version','CHAR(72)'),('Language','CHAR(20)'),('Attributes','SHORT'),('Sequence','LONG NOT NULL')],['File'],file_rows)
    table('Feature',[('Feature','CHAR(38) NOT NULL'),('Feature_Parent','CHAR(38)'),('Title','CHAR(64) LOCALIZABLE'),('Description','CHAR(255) LOCALIZABLE'),('Display','SHORT'),('Level','SHORT NOT NULL'),('Directory_','CHAR(72)'),('Attributes','SHORT NOT NULL')],['Feature'],[['MainFeature',None,NAME,'Launcher en gamevrije appbestanden',2,1,'INSTALLDIR',0]])
    table('FeatureComponents',[('Feature_','CHAR(38) NOT NULL'),('Component_','CHAR(72) NOT NULL')],['Feature_','Component_'],feature_rows)
    table('Media',[('DiskId','SHORT NOT NULL'),('LastSequence','LONG NOT NULL'),('DiskPrompt','CHAR(64) LOCALIZABLE'),('Cabinet','CHAR(255)'),('VolumeLabel','CHAR(32)'),('Source','CHAR(72)')],['DiskId'],[[1,len(files),None,'#payload.cab',None,None]])
    table('Icon',[('Name','CHAR(72) NOT NULL'),('Data','OBJECT NOT NULL')],['Name'],[['A2Icon',{'stream':str(icon)}]])
    target='[#'+identifier('F_',NAME+'.exe')+']'
    table('Shortcut',[('Shortcut','CHAR(72) NOT NULL'),('Directory_','CHAR(72) NOT NULL'),('Name','CHAR(128) NOT NULL LOCALIZABLE'),('Component_','CHAR(72) NOT NULL'),('Target','CHAR(255) NOT NULL'),('Arguments','CHAR(255)'),('Description','CHAR(255) LOCALIZABLE'),('Hotkey','SHORT'),('Icon_','CHAR(72)'),('IconIndex','SHORT'),('ShowCmd','SHORT'),('WkDir','CHAR(72)')],['Shortcut'],[
        ['DesktopShortcut','DesktopFolder',short_name(NAME),'C_Shortcuts',target,None,NAME,None,'A2Icon',0,1,'INSTALLDIR'],
        ['MenuShortcut','ProgramMenuDir',short_name(NAME),'C_Shortcuts',target,None,NAME,None,'A2Icon',0,1,'INSTALLDIR']])
    table('CreateFolder',[('Directory_','CHAR(72) NOT NULL'),('Component_','CHAR(72) NOT NULL')],['Directory_','Component_'],[['ProgramMenuDir','C_Shortcuts']])
    table('Upgrade',[('UpgradeCode','CHAR(38) NOT NULL'),('VersionMin','CHAR(20)'),('VersionMax','CHAR(20)'),('Language','CHAR(255)'),('Attributes','LONG NOT NULL'),('Remove','CHAR(255)'),('ActionProperty','CHAR(72) NOT NULL')],['UpgradeCode','VersionMin','VersionMax','Language','Attributes'],[
        [UPGRADE_CODE,None,version,None,1,'ALL','OLDPRODUCTS'],[UPGRADE_CODE,version,None,None,2,None,'NEWERVERSIONDETECTED']])
    table('LaunchCondition',[('Condition','CHAR(255) NOT NULL'),('Description','CHAR(255) NOT NULL LOCALIZABLE')],['Condition'],[
        ['NOT ALLUSERS','Deze installatie is alleen voor de huidige gebruiker.'],
        ['VersionNT64','A2 Racers Revival vereist een 64-bits versie van Windows.'],
        ['Installed OR NOT NEWERVERSIONDETECTED','Er is al een nieuwere versie van A2 Racers Revival geinstalleerd.']])
    execute=[('FindRelatedProducts',25),('AppSearch',50),('LaunchConditions',100),('CostInitialize',800),('FileCost',900),('CostFinalize',1000),('MigrateFeatureStates',1200),('InstallValidate',1400),('InstallInitialize',1500),('RemoveExistingProducts',1510),('ProcessComponents',1600),('UnpublishFeatures',1800),('RemoveRegistryValues',2600),('RemoveShortcuts',3200),('RemoveFiles',3500),('RemoveFolders',3600),('CreateFolders',3700),('InstallFiles',4000),('CreateShortcuts',4500),('WriteRegistryValues',5000),('RegisterUser',6000),('RegisterProduct',6100),('PublishFeatures',6300),('PublishProduct',6400),('InstallFinalize',6600)]
    table('InstallExecuteSequence',[('Action','CHAR(72) NOT NULL'),('Condition','CHAR(255)'),('Sequence','SHORT')],['Action'],[[a,'OLDPRODUCTS' if a=='RemoveExistingProducts' else None,s] for a,s in execute])
    ui=[['FindRelatedProducts',None,25],['AppSearch',None,50],['LaunchConditions',None,100],['CostInitialize',None,800],['FileCost',None,900],['CostFinalize',None,1000],['MigrateFeatureStates',None,1200],['WelcomeDlg','NOT Installed',1230],['MaintenanceDlg','Installed',1240],['ProgressDlg',None,1280],['ExecuteAction',None,1300],['ExitDlg',None,-1],['UserExitDlg',None,-2],['FatalDlg',None,-3]]
    table('InstallUISequence',[('Action','CHAR(72) NOT NULL'),('Condition','CHAR(255)'),('Sequence','SHORT')],['Action'],ui)
    table('TextStyle',[('TextStyle','CHAR(72) NOT NULL'),('FaceName','CHAR(32) NOT NULL'),('Size','SHORT NOT NULL'),('Color','LONG'),('StyleBits','SHORT')],['TextStyle'],[['NormalFont','Segoe UI',9,0,0],['TitleFont','Segoe UI',14,0,1]])
    dialogs=[];controls=[];events=[]
    def dialog(name,title,body,buttons,modal=True):
        dialogs.append([name,50,50,370,270,3 if modal else 1,NAME,buttons[0][0] if buttons else None,buttons[0][0] if buttons else None,buttons[-1][0] if buttons else None])
        controls.extend([[name,'Title','Text',18,15,334,32,3,None,r'{\TitleFont}'+title,None,None],
                         [name,'Body','Text',18,60,334,125,3,None,body,None,None]])
        for i,(bid,label,actions) in enumerate(buttons):
            controls.append([name,bid,'PushButton',352-84*(len(buttons)-i),235,78,20,3,None,label,buttons[(i+1)%len(buttons)][0],None])
            for order,(event,arg) in enumerate(actions,1):events.append([name,bid,event,arg,'1',order])
    dialog('WelcomeDlg','A2 Racers Revival installeren',f'Versie {version}\n\nInstalleert de launcher voor jouw Windows-account. Er zijn geen gamekopieen inbegrepen.',[
        ('Install','Installeren',[('EndDialog','Return')]),('Cancel','Annuleren',[('EndDialog','Exit')])])
    # Full UI: validate the edited path before permitting Install. Existing
    # products cannot be moved safely merely by changing a Directory property.
    # During a major update, AppSearch restores the previous folder and the UI
    # locks it. Maintenance never publishes SetTargetPath.
    for row in controls:
        if row[:2]==['WelcomeDlg','Body']:row[6]=60
        elif row[:2]==['WelcomeDlg','Cancel']:row[10]='PathLabel'
    for row in dialogs:
        if row[0]=='WelcomeDlg':row[7]='InstallPath'
    controls.extend([
        ['WelcomeDlg','PathLabel','Text',18,125,334,14,3,None,'Installatiemap:','InstallPath',None],
        ['WelcomeDlg','InstallPath','PathEdit',18,144,252,20,3,'INSTALLDIR',None,'Browse',None],
        ['WelcomeDlg','Browse','PushButton',276,144,76,20,3,None,'Bladeren...','Install',None],
        ['WelcomeDlg','FolderHint','Text',18,176,334,38,3,None,'Kies een map waarin jouw Windows-account mag schrijven. Bij updates blijft je gekozen map behouden.',None,None]])
    events.insert(0,['WelcomeDlg','Install','SetTargetPath','INSTALLDIR','NOT Installed AND NOT OLDPRODUCTS',1])
    for row in events:
        if row[:3]==['WelcomeDlg','Install','EndDialog']:row[5]=2
    events.append(['WelcomeDlg','Browse','SpawnDialog','BrowseDlg','NOT Installed AND NOT OLDPRODUCTS',1])
    dialogs.append(['BrowseDlg',50,50,370,270,3,NAME,'FolderLabel','Choose','Cancel'])
    controls.extend([
        ['BrowseDlg','Title','Text',18,15,334,32,3,None,r'{\TitleFont}Kies de installatiemap',None,None],
        ['BrowseDlg','FolderLabel','Text',18,56,334,14,3,None,'Map:','DirectoryCombo',None],
        ['BrowseDlg','DirectoryCombo','DirectoryCombo',18,74,244,80,196611,'INSTALLDIR','Mappen en stations','Up',None],
        ['BrowseDlg','Up','PushButton',268,74,84,20,3,None,'Een map hoger','DirectoryList',None],
        ['BrowseDlg','DirectoryList','DirectoryList',18,104,334,84,7,'INSTALLDIR','Mappen','NewFolder',None],
        ['BrowseDlg','NewFolder','PushButton',18,197,88,20,3,None,'Nieuwe map','PathLabel',None],
        ['BrowseDlg','PathLabel','Text',114,183,238,14,3,None,'Volledig pad:','Path',None],
        ['BrowseDlg','Path','PathEdit',114,197,238,20,3,'INSTALLDIR',None,'Choose',None],
        ['BrowseDlg','Choose','PushButton',184,235,80,20,3,None,'Map kiezen','Cancel',None],
        ['BrowseDlg','Cancel','PushButton',272,235,80,20,3,None,'Annuleren','DirectoryCombo',None]])
    events.extend([
        ['BrowseDlg','Up','DirectoryListUp','0','1',1],
        ['BrowseDlg','NewFolder','DirectoryListNew','0','1',1],
        ['BrowseDlg','Choose','SetTargetPath','INSTALLDIR','NOT Installed AND NOT OLDPRODUCTS',1],
        ['BrowseDlg','Choose','EndDialog','Return','NOT Installed AND NOT OLDPRODUCTS',2],
        ['BrowseDlg','Cancel','Reset','0','1',1],
        ['BrowseDlg','Cancel','EndDialog','Return','1',2]])
    dialog('MaintenanceDlg','Installatie beheren','Herstel de appbestanden of verwijder de geinstalleerde launcher. Je eigen gamebestanden en voortgang blijven behouden.',[
        ('Repair','Herstellen',[('[REINSTALL]','ALL'),('[REINSTALLMODE]','amus'),('EndDialog','Return')]),
        ('Remove','Verwijderen',[('[REMOVE]','ALL'),('EndDialog','Return')]),('Cancel','Annuleren',[('EndDialog','Exit')])])
    dialog('ProgressDlg','A2 Racers Revival','Windows Installer verwerkt de appbestanden. Dit kan even duren.',[],False)
    next(row for row in dialogs if row[0]=='ProgressDlg')[7]='Status'
    controls.extend([['ProgressDlg','Status','Text',18,155,334,40,3,None,'Bezig...',None,None],['ProgressDlg','Progress','ProgressBar',18,205,334,14,65539,None,None,None,None]])
    for name,title,body in (('ExitDlg','Gereed','Windows Installer heeft de bewerking voltooid.'),('UserExitDlg','Geannuleerd','De bewerking is geannuleerd.'),('FatalDlg','Installatie niet voltooid','Windows Installer kon de bewerking niet voltooien. Bekijk het MSI-log voor details.')):
        dialog(name,title,body,[('Finish','Sluiten',[('EndDialog','Return')])])
    # Windows Installer fills ErrorText and selects/repositions the applicable
    # buttons. Without ErrorDialog, SetTargetPath failures are only logged and
    # the user cannot see why the folder chooser refuses the selected path.
    # Error buttons must not participate in a normal Control_Next tab chain.
    dialogs.append(['ErrorDlg',50,50,370,270,65539,NAME,'ErrorText',None,None])
    controls.append(['ErrorDlg','ErrorText','Text',18,30,334,165,3,None,None,None,None])
    for bid,label,result in (('A','Afbreken','ErrorAbort'),('C','Annuleren','ErrorCancel'),
                             ('I','Negeren','ErrorIgnore'),('N','Nee','ErrorNo'),
                             ('O','OK','ErrorOk'),('R','Opnieuw','ErrorRetry'),('Y','Ja','ErrorYes')):
        controls.append(['ErrorDlg',bid,'PushButton',146,235,78,20,3,None,label,None,None])
        events.append(['ErrorDlg',bid,'EndDialog',result,'1',1])
    table('Dialog',[('Dialog','CHAR(72) NOT NULL'),('HCentering','SHORT NOT NULL'),('VCentering','SHORT NOT NULL'),('Width','SHORT NOT NULL'),('Height','SHORT NOT NULL'),('Attributes','LONG'),('Title','CHAR(128) LOCALIZABLE'),('Control_First','CHAR(50)'),('Control_Default','CHAR(50)'),('Control_Cancel','CHAR(50)')],['Dialog'],dialogs)
    table('Control',[('Dialog_','CHAR(72) NOT NULL'),('Control','CHAR(50) NOT NULL'),('Type','CHAR(20) NOT NULL'),('X','SHORT NOT NULL'),('Y','SHORT NOT NULL'),('Width','SHORT NOT NULL'),('Height','SHORT NOT NULL'),('Attributes','LONG'),('Property','CHAR(72)'),('Text','CHAR(0) LOCALIZABLE'),('Control_Next','CHAR(50)'),('Help','CHAR(50) LOCALIZABLE')],['Dialog_','Control'],controls)
    table('ControlEvent',[('Dialog_','CHAR(72) NOT NULL'),('Control_','CHAR(50) NOT NULL'),('Event','CHAR(50) NOT NULL'),('Argument','CHAR(255) NOT NULL'),('Condition','CHAR(255)'),('Ordering','SHORT')],['Dialog_','Control_','Event','Argument','Condition'],events)
    table('ControlCondition',[('Dialog_','CHAR(72) NOT NULL'),('Control_','CHAR(50) NOT NULL'),('Action','CHAR(50) NOT NULL'),('Condition','CHAR(255) NOT NULL')],['Dialog_','Control_','Action','Condition'],[
        ['WelcomeDlg',control,action,condition]
        for control in ('InstallPath','Browse')
        for action,condition in (('Disable','Installed OR OLDPRODUCTS'),('Enable','NOT Installed AND NOT OLDPRODUCTS'))])
    table('EventMapping',[('Dialog_','CHAR(72) NOT NULL'),('Control_','CHAR(50) NOT NULL'),('Event','CHAR(50) NOT NULL'),('Attribute','CHAR(50) NOT NULL')],['Dialog_','Control_','Event','Attribute'],[['ProgressDlg','Status','ActionText','Text'],['ProgressDlg','Progress','SetProgress','Progress'],['BrowseDlg','DirectoryCombo','IgnoreChange','IgnoreChange']])
    return {'version':version,'product_code':product,'upgrade_code':UPGRADE_CODE,'tables':tables,'manifest':manifest,
            'cab':str(stage/'payload.cab'),'icon':str(icon),'package_code':'{'+str(uuid.uuid4()).upper()+'}'}

def validate_version(version):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):
        raise ValueError('Use three numeric MSI version fields, for example 0.1.5.')
    major,minor,build=map(int,version.split('.'))
    if major>255 or minor>255 or build>65535:raise ValueError('MSI version field out of range.')
    return version

def checked_path(path,must_exist=True):
    path=Path(path)
    if '..' in path.parts or str(path).startswith(('\\\\?\\','\\\\.\\')):
        raise ValueError('Traversal/device paths are not build inputs.')
    absolute=path.absolute()
    for part in reversed((absolute,*absolute.parents)):
        try:metadata=part.lstat()
        except FileNotFoundError:
            if part==absolute and not must_exist:continue
            raise
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata,'st_file_attributes',0)&0x400:
            raise ValueError('Links/junctions/reparse points are not build inputs: '+str(part))
    return absolute

def prepare_paths(payload,icon,output):
    payload=checked_path(payload);icon=checked_path(icon)
    if not payload.is_file() or not icon.is_file():raise ValueError('Payload and icon must be regular files.')
    output=checked_path(output,must_exist=False)
    if os.path.lexists(output):raise FileExistsError('Use a new exclusive output folder; existing builds are never overwritten.')
    # Claim the directory atomically. Never remove it automatically after a failure.
    output.mkdir(mode=0o700,parents=False,exist_ok=False)
    return payload,icon,output

def powershell_path(explicit=None):
    selected=explicit or shutil.which('pwsh') or shutil.which('powershell.exe')
    if selected is None:raise FileNotFoundError('PowerShell 7 (pwsh) or Windows PowerShell is required for MSI authoring.')
    selected=checked_path(selected)
    if not selected.is_file():raise ValueError('PowerShell must be a regular executable file.')
    if selected.name.casefold() not in ('pwsh.exe','powershell.exe','pwsh'):
        raise ValueError('Expected a PowerShell executable (pwsh.exe or powershell.exe).')
    return selected

def main():
    parser=argparse.ArgumentParser(description='Build a transparent per-user x64 MSI without running or installing its payload.')
    parser.add_argument('--payload',required=True,type=Path)
    parser.add_argument('--icon',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path,help='A new, nonexistent build directory with an existing parent.')
    parser.add_argument('--version',required=True,type=validate_version)
    parser.add_argument('--powershell',type=Path,help='Optional PowerShell executable; defaults to pwsh on PATH, then Windows PowerShell.')
    args=parser.parse_args()
    if sys.platform!='win32':raise SystemExit('Windows is required for WindowsInstaller COM and makecab.')
    shell=powershell_path(args.powershell)
    payload,icon,output=prepare_paths(args.payload,args.icon,args.output)
    archive_hash=sha(payload.read_bytes());icon_hash=sha(icon.read_bytes())
    files=read_payload(payload);stage=output/'stage';stage.mkdir(exist_ok=False)
    plan=build_plan(files,stage,icon,args.version)
    # Relative ASCII DDF paths also work when the build directory has Unicode in its name.
    lines=['.OPTION EXPLICIT','.Set Cabinet=ON','.Set Compress=ON','.Set CompressionType=MSZIP',
           '.Set MaxDiskSize=0','.Set MaxCabinetSize=0','.Set CabinetNameTemplate=payload.cab',
           '.Set DiskDirectoryTemplate=.','.Set InfFileName=payload.inf','.Set RptFileName=payload.rpt']
    for item in plan['manifest']:
        source=stage/'input'/item['id'];source.parent.mkdir(exist_ok=True)
        source.write_bytes(files[item['path']])
        lines.append(f'"input\\{item["id"]}" "{item["id"]}"')
    (stage/'payload.ddf').write_text('\n'.join(lines)+'\n',encoding='ascii')
    with (output/'makecab.log').open('w') as log:
        subprocess.run(['makecab.exe','/F','payload.ddf'],check=True,stdout=log,stderr=subprocess.STDOUT,cwd=stage)
    msi=output/f'A2-Racers-Revival-{args.version}.msi'
    plan.update({'output':str(msi),'payload_sha256':archive_hash,'icon_sha256':icon_hash})
    spec=output/'build-plan.json';spec.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    subprocess.run([str(shell),'-NoLogo','-NoProfile','-File',str(HERE/'write_database.ps1'),'-Spec',str(spec)],check=True,cwd=output)
    if sha(payload.read_bytes())!=archive_hash or sha(icon.read_bytes())!=icon_hash:raise ValueError('Input changed during build.')
    result={'output':str(msi),'sha256':sha(msi.read_bytes()),'bytes':msi.stat().st_size,
            'version':args.version,'upgrade_code':UPGRADE_CODE,'payload_files':len(files),
            'payload_sha256':archive_hash,'icon_sha256':icon_hash,'installed':False,'native_runtime_tested':False}
    (output/'build-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
