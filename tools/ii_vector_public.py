"""Build optional Vector resources from verified player data and our own paint.

Only our material pixels/preview and transformation code are distributed.
Native model, atlas, palette and compiled game records stay on the player's PC.
"""
import base64
import json
from pathlib import Path
import shutil
import struct
import uuid

from tools import ii_vector_car as vector, ii_vector_geometry as geometry
from tools.ii_vector_wheels import make_wheel, encode_wheel
from tools.ii_frontend_prepare import resource
from tools.ii_frontend_state import read_regular
from tools.pcx_codec import IndexedImage, decode_pcx, encode_pcx
from tools.vehicle_mesh import decode_vehicle_mesh, VehicleMesh
from tools.trial_manifest import validate_ancestors

PAINT='tools/ii_frontend_art/vector-paint.json'
PREVIEW='tools/ii_frontend_art/vector-preview.png'
PAINT_SHA256='6c7a1327806c200d55b64aa4021e24e95033419293cbf46232c49f4609c5742f'
VECTOR_SOURCE_SHA256='409d1438e44b14443a01a0e2ade62405e61ee6f93d1eab9072e0c9a7f24239ab'


def compile_resources(index,image,paint,preview):
    """Pure, pinned compilation; preserve all other cars and the native palette."""
    if vector.sha(paint)!=PAINT_SHA256 or vector.sha(preview)!=vector.ART_FILES['vector-menu-front-v3.png']:
        raise ValueError('De eigen Vector-materialen veranderden.')
    spec=json.loads(paint)
    if (spec.get('schema'),spec.get('width'),spec.get('height'))!=(1,124,124):
        raise ValueError('Andere Vector-verfindeling.')
    rgb=base64.b64decode(spec['rgb'],validate=True)
    indices=base64.b64decode(spec['indices'],validate=True)
    if len(rgb)!=124*124*3 or len(indices)!=124*124 or max(indices)>253:
        raise ValueError('Andere Vector-pixelgegevens.')
    raw=resource(index,image,'R_VECTOR.d3d')
    if vector.sha(raw)!=VECTOR_SOURCE_SHA256:raise ValueError('Andere oorspronkelijke Vector.')
    for name in ('RACER01.PCX','RACER01.TGA'):
        if vector.sha(resource(index,image,name))!=vector.SOURCE_RESOURCES[name]:
            raise ValueError('Andere oorspronkelijke Vector-atlas.')
    body,_=geometry.make_body(decode_vehicle_mesh(raw))
    vertices=[];triangles=[];seen={}
    for triangle in body.triangles:
        current=[]
        for key in triangle[:3]:
            vertex=body.vertices[key]
            native=vertex[:6]+((130.5+vertex[6]*123)/256,(130.5+vertex[7]*123)/256)+vertex[8:]
            packed=struct.pack('<8fB',*native)
            if packed not in seen:
                seen[packed]=len(vertices);vertices.append(struct.unpack('<8fB',packed))
            current.append(seen[packed])
        triangles.append(tuple(current)+triangle[3:])
    pcx=decode_pcx(resource(index,image,'RACER01.PCX'));pixels=bytearray(pcx.pixels)
    tga=bytearray(resource(index,image,'RACER01.TGA'))
    for y in range(124):
        pixels[(130+y)*256+130:(130+y)*256+254]=indices[y*124:(y+1)*124]
        for x in range(124):
            pos=18+((255-(y+130))*256+x+130)*3;source=(y*124+x)*3
            tga[pos:pos+3]=rgb[source:source+3][::-1]
    # Fixed samples lie inside the native wheel material; this exact source is pinned.
    cars=resource(index,image,'cars01.pcx')
    if vector.sha(cars)!='5fa6b9abe1dd72e8989385639a74e6fc9e917a80800e6bbd2f56a346e105011a':
        raise ValueError('Andere wielmaterialen.')
    materials={name:((x+.5)/256,(y+.5)/256) for name,(x,y) in
               {'rubber':(35,132),'recess':(35,132),'alloy':(42,144),'edge':(42,144)}.items()}
    result={'vector-body.d3d':geometry.encode_mesh(VehicleMesh(tuple(vertices),tuple(triangles))),
            'vector-wheel.d3d':encode_wheel(make_wheel(materials)),
            'racer01-vector.pcx':encode_pcx(IndexedImage(256,256,bytes(pixels),pcx.palette)),
            'racer01-vector.tga':bytes(tga),'vector-menu-front-v3.png':preview}
    if {name:vector.sha(raw) for name,raw in result.items()}!=vector.ART_FILES:
        raise ValueError('Vector-opbouw wijkt af van de gecontroleerde lokale versie.')
    return result


def prepare(root):
    root=Path(root).absolute()
    # Older packages/fixtures may lack optional art; normal play remains available.
    if not (root/PAINT).exists():return {'available':False,'reason':'De eigen Vector-materialen ontbreken.'}
    target=root/vector.ART_FOLDER;validate_ancestors(target)
    if target.exists():vector.checked_art(root);return {'available':True,'already_prepared':True}
    data=root/'local/games/a2racer2/DATA'
    result=compile_resources(read_regular(data/'RCS.IND',65536),read_regular(data/'RCS.IMG',64*1024**2),
                             read_regular(root/PAINT,128*1024),read_regular(root/PREVIEW,1024**2))
    target.parent.mkdir(parents=True,exist_ok=True)
    stage=target.with_name('.vector-build-'+uuid.uuid4().hex);validate_ancestors(stage);stage.mkdir()
    try:
        for name,raw in result.items():(stage/name).write_bytes(raw)
        if target.exists():raise ValueError('Vector is tijdens voorbereiden elders aangemaakt.')
        stage.rename(target)
    finally:
        if stage.exists():shutil.rmtree(stage)
    vector.checked_art(root)
    return {'available':True,'prepared':True,'native_game_executed':False}
