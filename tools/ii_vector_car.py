"""Local optional Vector vehicle preparation; never starts games or changes sources.

The menu bonus car uses native car 6 only while selected. Normal race resources
remain sealed alongside its overlay, so the seven ordinary cars stay available.
"""
from pathlib import Path
import hashlib,json,struct
from tools.ii_frontend_state import read_regular
from tools.ii_frontend_prepare import resource
from tools.ii_hd_hud_assets import replace_resources
from tools.vehicle_mesh import decode_vehicle_mesh

ART_FOLDER='local/ii-menu-art/vector-native-v4c'
ART_FILES={
    'vector-body.d3d':'4d93caea5ae025418c2bee320c3f03acb48904f26cb1ba8a38c0e420e27327a9',
    'racer01-vector.pcx':'8d5e62514a2c51f6a8b4ffae75e5dfb4e0874c2924fe3a6e934dd6d1f5b1da6b',
    'racer01-vector.tga':'9d801b3cfebeb9ed44223f84a2e736af65856296de967facfa2b79b463831bfd',
    'vector-menu-front-v3.png':'44fed17a8b382b6eda148752b9d9fb8f099d15c4ad7d9a02af9c8ebe71470fee',
    'vector-wheel.d3d':'ab7f82993942fad85b8336d734325e9eeb5f9bab35c825a9b65cf03390e12f42',
}
SOURCE_RESOURCES={
    'r_diablo.d3d':'8ced46b8664c73dbb28d519b105f6fec0d396d2a27a2c7f31caf61a12d4004eb',
    'RACER01.PCX':'974fab3e24eb2f342d343ac7e2d7ec4217009e33a66931b4afc7a0f997bd6c0c',
    'RACER01.TGA':'04e52821e88c116b9781c8b8f6dff21382017daf683b76b0a883e19111652040',
    'WIEL.d3d':'9f86a9367659df46d0b18cd9d576670047192eba6ea6e11bafe00b3759cccff9',
}
WHEEL_VA=0x486198+6*48
WHEEL_BEFORE=struct.pack('<12f',-8,3.7,14,8,3.7,14,-8.3,3.7,-14.8,8.3,3.7,-14.8)
WHEEL_AFTER=struct.pack('<12f',-8.8,3.7,8.01,8.8,3.7,8.01,-8.8,3.7,-16.48,8.8,3.7,-16.48)

def sha(data):return hashlib.sha256(data).hexdigest()

def wheel_offset(binary):
    if type(binary) is not bytes or not 1024<=len(binary)<=2*1024**2 or binary[:2]!=b'MZ':raise ValueError('Andere Vector-racebinary.')
    pe=struct.unpack_from('<I',binary,0x3c)[0]
    if pe+256>len(binary) or binary[pe:pe+4]!=b'PE\0\0':raise ValueError('Onjuiste PE-layout.')
    if struct.unpack_from('<H',binary,pe+4)[0]!=0x14c:raise ValueError('Andere native architectuur.')
    optional=pe+24
    if struct.unpack_from('<H',binary,optional)[0]!=0x10b or struct.unpack_from('<I',binary,optional+28)[0]!=0x400000:raise ValueError('Andere native adresindeling.')
    count=struct.unpack_from('<H',binary,pe+6)[0];table=optional+struct.unpack_from('<H',binary,pe+20)[0]
    if not 1<=count<=24 or table+count*40>len(binary):raise ValueError('Onjuiste PE-secties.')
    found=[];rva=WHEEL_VA-0x400000
    for i in range(count):
        start,size,raw=struct.unpack_from('<III',binary,table+i*40+12)
        if start<=rva and rva+48<=start+size:
            offset=raw+rva-start
            if offset+48>len(binary):raise ValueError('Wieltabel buiten bestand.')
            found.append(offset)
    if len(found)!=1:raise ValueError('Geen unieke native wieltabel.')
    return found[0]

def patch_wheels(binary):
    offset=wheel_offset(binary)
    if binary[offset:offset+48]!=WHEEL_BEFORE:raise ValueError('Andere native wielcontext; Vector geweigerd.')
    return binary[:offset]+WHEEL_AFTER+binary[offset+48:]

def checked_art(root):
    files={}
    for name,pin in ART_FILES.items():
        raw=read_regular(root/ART_FOLDER/name,1024**2)
        if sha(raw)!=pin:raise ValueError('Lokale Vector-afbeelding/model ontbreekt of veranderde: '+name)
        files[name]=raw
    mesh=decode_vehicle_mesh(files['vector-body.d3d'])
    if len(mesh.vertices)!=301 or len(mesh.triangles)!=216:raise ValueError('Andere Vector-geometrie.')
    wheel=decode_vehicle_mesh(files['vector-wheel.d3d'])
    if len(wheel.vertices)!=1424 or len(wheel.triangles)!=832:raise ValueError('Andere Vector-wielgeometrie.')
    return files

def availability(root):
    try:checked_art(root);return {'available':True,'reason':'Lokale Vector V3 met sportauto-afstelling beschikbaar.'}
    except (OSError,ValueError) as exc:return {'available':False,'reason':str(exc)}

def overlay(index,image,art):
    for name,pin in SOURCE_RESOURCES.items():
        if sha(resource(index,image,name))!=pin:raise ValueError('Andere native Vector-bron: '+name)
    return replace_resources(index,image,{'r_diablo.d3d':art['vector-body.d3d'],
        'RACER01.PCX':art['racer01-vector.pcx'],'RACER01.TGA':art['racer01-vector.tga'],
        'WIEL.d3d':art['vector-wheel.d3d']})

def prepare(root,target):
    """Only call on a fresh owned launcher copy, before its manifest is sealed."""
    target=Path(target)
    if target.parent!=root/'local/ii-parallel' or not target.name.startswith('ii-launcher-'):
        raise ValueError('Vector vereist een eigen launcher-startkopie.')
    art=checked_art(root);data=target/'game/DATA'
    index,image=read_regular(data/'RCS.IND',64*1024**2),read_regular(data/'RCS.IMG',64*1024**2)
    vector_index,vector_image=overlay(index,image,art)
    binaries={}
    for mode,name in (('classic','SPEL.DAT'),('widescreen','SPEL-WIDE.DAT')):
        binary=read_regular(data/name,2*1024**2);variant='SPEL-VECTOR'+('-WIDE' if mode=='widescreen' else '')+'.DAT'
        binaries[mode]={'binary':variant,'sha256':sha(patch_wheels(binary)),'data':patch_wheels(binary)}
    folder=target/'vector-vehicle';folder.mkdir(exist_ok=False)
    files=set();resources={}
    for mode,pair in (('normal',(index,image)),('vector',(vector_index,vector_image))):
        (folder/mode).mkdir();resources[mode]=[]
        for name,raw in zip(('RCS.IND','RCS.IMG'),pair):
            relative='vector-vehicle/'+mode+'/'+name;(target/relative).write_bytes(raw);files.add(relative)
            resources[mode].append({'path':relative,'target':name,'sha256':sha(raw)})
    for spec in binaries.values():
        (data/spec['binary']).write_bytes(spec.pop('data'));files.add('game/DATA/'+spec['binary'])
    (target/'assets/car7-preview.png').write_bytes(art['vector-menu-front-v3.png']);files.add('assets/car7-preview.png')
    return {'schema':1,'enabled':True,'menu_car':7,'native_car':6,
            'stats_source':'Lambdaghini sportauto-afstelling; geen oorspronkelijke Vector-stats',
            'binaries':binaries,'resources':resources,'runtime_tested':False},files
