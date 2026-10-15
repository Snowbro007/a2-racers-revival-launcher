"""Static preparation of the new II WPF menu and original standalone race."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from a2revival.inventory import write_json
from tools import ii_next_wrapper_probe as base
from tools import ii_frontend_state as state
from tools import trial_manifest
from tools.pcx_codec import decode_pcx, encode_pcx, IndexedImage
from tools.vehicle_mesh import decode_vehicle_mesh
from tools.ii_frontend_launcher import PART_ART_NAMES
from tools.ii_frontend_fullscreen import build_race, race_profile

RACE_PROFILE_SHA = '6de487f0edbab8ec5d60d826211631ea3bc0a0d8ddc10a0bbe7eeca2b7f8c2f5'
MESH_NAMES = ('r_trabbi.d3d', 'r_astra.d3d', 'r_beetle.d3d', 'r_bmw.d3d',
              'r_porche.d3d', 'r_clk.d3d', 'r_diablo.d3d')
# Preview placement follows the observed wheel-arch boundaries of these meshes.
# It is not a native game physics/vehicle-parameter patch.
WHEEL_ARCH_CENTERS = ((-9.55,12.88),(-12.51,14.10),(-11.87,11.58),
                      (-12.54,12.71),(-12.17,13.22),(-14.40,14.20),(-14.81,13.99))
PORCHE_MESH_SHA = '077b61fdb4d32c0dbac387ba0fb205b08dfb2a7dab3a090f94d6972cb2e13b76'
# Statically inspected faces of this exact model: retain lamps/bumpers/doors,
# separate windshield, side/rear glass, roof and bonnet from the Astra skin.
PORCHE_GLASS_FACES = frozenset((3,17,18,25,39,40,52,53,54,55,56,57,58,63,64,69))
PORCHE_ROOF_FACES = frozenset(range(44,52))
PORCHE_PAINT_FACES = frozenset((74,86,87,89,101,102,103,104,105,106,107,108))
PORCHE_HEADLAMP_FACES = frozenset((78,81,93,96))
PORCHE_TRIM_FACES = frozenset((60,62,66,68,70,71,75,76,77,79,90,91,92,94,109,110,111))


def preview_mesh(mesh, car_id: int) -> dict:
    if type(car_id) is not int or not 0 <= car_id < len(MESH_NAMES):
        raise ValueError('Onbekende previewauto.')
    referenced = {i for triangle in mesh.triangles for i in triangle[:3]}
    half_width = max(abs(mesh.vertices[i][0]) for i in referenced)
    side = max(0.0, half_width - 1.1)
    # Astra keeps an isolated white skin. The pinned Porsche preview uses
    # dedicated paint/glass/trim materials instead of this incompatible skin.
    isolated = car_id in (1, 4)
    # These older meshes reuse their side-window UVs on the roof. Split only
    # nearly horizontal upper faces for a clean paint material in the preview.
    low = min(mesh.vertices[i][1] for i in referenced)
    high = max(mesh.vertices[i][1] for i in referenced)
    roof, body, glass, paint, lamps, trim = [], [], [], [], [], []
    front = max(mesh.vertices[i][2] for i in referenced)
    encoded = (struct.pack('<II',len(mesh.vertices),len(mesh.triangles))
               + b''.join(struct.pack('<8fB',*v) for v in mesh.vertices)
               + b''.join(struct.pack('<3H3B',*t) for t in mesh.triangles))
    pinned_porche = car_id == 4 and hashlib.sha256(encoded).hexdigest() == PORCHE_MESH_SHA
    for face_id,t in enumerate(mesh.triangles):
        a,b,c = [mesh.vertices[i][:3] for i in t[:3]]
        ab,ac = [b[i]-a[i] for i in range(3)],[c[i]-a[i] for i in range(3)]
        normal = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
        is_roof = isolated and min(a[1],b[1],c[1]) >= low+.8*(high-low) and abs(normal[1]) > 3*(abs(normal[0])+abs(normal[2]))
        # The observed r_porche preview reuses the Astra atlas on sloping glass
        # and upper paint panels. Keep the exact geometry; give these regions
        # their own neutral preview materials instead of stretched window strips.
        is_glass = (car_id == 4 and front > 0
                    and min(a[1],b[1],c[1]) >= low+.6*(high-low)
                    and min(a[2],b[2],c[2]) >= -.7*front
                    and max(a[2],b[2],c[2]) <= .42*front)
        is_paint = (car_id == 4 and
                    (min(a[1],b[1],c[1]) >= low+.8*(high-low) or
                     (not is_glass and min(a[1],b[1],c[1]) >= low+.35*(high-low)
                      and abs(normal[1]) > abs(normal[0])+abs(normal[2]))))
        if pinned_porche:
            is_roof = face_id in PORCHE_ROOF_FACES
            is_glass = face_id in PORCHE_GLASS_FACES
            is_paint = (face_id in PORCHE_PAINT_FACES or
                        (abs(sum(v[2] for v in (a,b,c))/3) > 15 and
                         abs(normal[0]) > abs(normal[2])))
            if face_id in PORCHE_HEADLAMP_FACES:
                lamps.append(list(t[:3]))
                continue
            if face_id in PORCHE_TRIM_FACES:
                trim.append(list(t[:3]))
                continue
        (roof if is_roof else glass if is_glass else paint if is_paint else body).append(list(t[:3]))
    def uv(v):
        if not isolated:
            return list(v[6:8])
        return [min(127.5/128, max(.5/128, coordinate*2)) for coordinate in v[6:8]]
    return {'positions':[list(v[:3]) for v in mesh.vertices],
            'normals':[list(v[3:6]) for v in mesh.vertices],
            'uv':[uv(v) for v in mesh.vertices],
            'triangles':body, 'roof_triangles':roof, 'glass_triangles':glass, 'paint_triangles':paint,
            'headlamp_triangles':lamps,
            'trim_triangles':trim,
            'body_color':'#D51E26' if pinned_porche else None,
            'headlamp_centers':[[-6.35,8.35,19.45],[6.35,8.35,19.45]] if pinned_porche else [],
            'texture_index':3 if isolated else 1 if car_id in (0,2) else 0,
            'paint_color':'#D51E26' if car_id == 4 else '#C4C7CC',
            'wheel_centers':[[x,3.4784109592437744,z] for x in (-side,side)
                             for z in WHEEL_ARCH_CENTERS[car_id]]}


def bmp_from_pcx(data: bytes) -> bytes:
    image = decode_pcx(data)
    stride = (image.width * 3 + 3) & ~3
    rows = bytearray()
    for y in range(image.height - 1, -1, -1):
        for x in range(image.width):
            i = image.pixels[y * image.width + x] * 3
            r, g, b = image.palette[i:i+3]
            rows.extend((b, g, r))
        rows.extend(bytes(stride - image.width * 3))
    return (struct.pack('<2sIHHI', b'BM', 54 + len(rows), 0, 0, 54)
            + struct.pack('<IiiHHIIiiII', 40, image.width, image.height, 1, 24, 0,
                          len(rows), 2835, 2835, 0, 0) + rows)


def png_from_pcx(data: bytes) -> bytes:
    image = decode_pcx(data)
    raw = bytearray()
    for y in range(image.height):
        raw.append(0)
        for x in range(image.width):
            index = image.pixels[y * image.width + x]
            i = index * 3
            rgb = image.palette[i:i+3]
            # II's two reserved mask indices are hot pink and magenta.
            # Do not turn ordinary black body/glass pixels into holes.
            raw.extend(b'\0\0\0\0' if index in (254, 255) else rgb + b'\xff')
    def chunk(kind, content):
        return struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',image.width,image.height,8,6,0,0,0))
            +chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))


def isolated_white_skin(data: bytes) -> bytes:
    image = decode_pcx(data)
    if image.width != 256 or image.height != 256:
        raise ValueError('De previewatlas heeft een andere afmeting.')
    pixels = b''.join(image.pixels[y*256:y*256+128] for y in range(128))
    return png_from_pcx(encode_pcx(IndexedImage(128,128,pixels,image.palette)))


def resource(index: bytes, image: bytes, target: str) -> bytes:
    """II index can contain duplicate unrelated names; require a unique target."""
    if len(index) < 2 or len(image) > 64 * 1024 * 1024:
        raise ValueError('Onjuist lokaal resourcearchief.')
    count = struct.unpack_from('<H', index)[0]
    if not 1 <= count <= 4096 or len(index) != 2 + count * 24:
        raise ValueError('Onjuiste resource-indexlengte.')
    records = [struct.unpack_from('<20sI', index, 2 + i * 24) for i in range(count)]
    offsets = [row[1] for row in records] + [len(image)]
    if offsets[0] != 0 or any(a >= b for a, b in zip(offsets, offsets[1:])):
        raise ValueError('Resourcegrenzen zijn niet strikt oplopend.')
    found = []
    for i, (raw, start) in enumerate(records):
        name, zero, _ = raw.partition(b'\0')
        if not zero:
            raise ValueError('Onbegrensde resourcenaam.')
        if name.decode('latin1').lower() == target.lower():
            if offsets[i+1] - start > 8 * 1024 * 1024:
                raise ValueError('Resource is te groot.')
            found.append(image[start:offsets[i+1]])
    if len(found) != 1:
        raise ValueError('Resource ontbreekt of is dubbel: ' + target)
    return found[0]


def cursor_bytes(size: int) -> bytes:
    if size not in (32, 48):
        raise ValueError('Onjuiste cursorgrootte.')
    # Own white arrow with a thick dark outline; one Windows hardware cursor.
    shape = ((.08,.03),(.08,.83),(.29,.63),(.48,.96),(.63,.87),(.45,.56),(.76,.56))
    points = [(round(x*size), round(y*size)) for x,y in shape]
    def inside(x, y):
        hit = False
        for (a,b),(c,d) in zip(points,points[1:]+points[:1]):
            if (b>y)!=(d>y) and x < (c-a)*(y-b)/(d-b)+a:
                hit = not hit
        return hit
    pixels = bytearray(); mask = bytearray()
    stride = ((size + 31)//32)*4
    for y in range(size-1,-1,-1):
        row = bytearray(stride)
        for x in range(size):
            filled = inside(x+.5,y+.5)
            edge = filled and any(not inside(x+dx+.5,y+dy+.5)
                                   for dx,dy in ((-2,0),(2,0),(0,-2),(0,2)))
            value = 20 if edge else 255
            pixels.extend((value,value,value,255) if filled else (0,0,0,0))
            if not filled: row[x//8] |= 0x80 >> (x%8)
        mask.extend(row)
    dib = struct.pack('<IiiHHIIiiII',40,size,size*2,1,32,0,len(pixels)+len(mask),0,0,0,0)+pixels+mask
    return struct.pack('<HHH',0,2,1)+struct.pack('<BBBBHHII',size,size,0,0,3,2,len(dib),22)+dib


def prepare(workspace: Path, run_name: str, python_path: str) -> dict:
    workspace = workspace.absolute()
    trial_manifest.validate_slug(run_name)
    trial_manifest.validate_ancestors(Path(python_path))
    if not Path(python_path).is_file():
        raise ValueError('Python ontbreekt.')
    helper = workspace / 'tools/ii_owned_session.ps1'
    trial_manifest.validate_ancestors(helper)
    race = workspace / 'local/ii-parallel/ii-session-a-20261012/profiles/race.conf'
    race_bytes = state.read_regular(race, 65536)
    if base.fingerprint(race_bytes) != RACE_PROFILE_SHA:
        raise ValueError('De bestaande racebaseline veranderde.')
    part_art = {}
    for name in PART_ART_NAMES:
        raw = state.read_regular(workspace/f'local/ii-menu-art/classic-v1/part-{name}.png',8*1024*1024)
        if len(raw) < 33 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[25] != 6:
            raise ValueError('Onjuiste transparante onderdelenafbeelding: '+name)
        part_art[name] = raw
    prepared = base.prepare_probe(workspace, run_name, 60)
    folder = workspace / 'local/ii-parallel' / run_name
    report = workspace / 'reports/a2racer2-next' / run_name
    data = folder / 'game/DATA'
    (data / 'dgVoodoo.conf').write_bytes(race_bytes)
    wide_race, wide_plan = build_race((data/'SPEL.DAT').read_bytes())
    (data/'SPEL-WIDE.DAT').write_bytes(wide_race)
    (folder/'profiles').mkdir(exist_ok=True)
    (folder/'profiles/classic.conf').write_bytes(race_bytes)
    (folder/'profiles/widescreen.conf').write_bytes(race_profile(race_bytes))
    write_json(report/'fullscreen-plan.json',wide_plan)
    raser = state.replace_ini((data/'RASER.INI').read_bytes(),
        {('PROGRAM','RESOLUTION'):3,('HELPDESK','DEBUGON'):0})
    (data/'RASER.INI').write_bytes(raser)
    assets = folder / 'assets'; assets.mkdir()
    for name,raw in part_art.items():
        (assets/f'part-{name}.png').write_bytes(raw)
    music_available = (data/'MRCS.IND').exists() and (data/'MRCS.IMG').exists()
    if music_available:
        from tools.ii_menu_music import extract_tracks
        tracks = extract_tracks((data/'MRCS.IND').read_bytes(), (data/'MRCS.IMG').read_bytes())
        (assets/'music').mkdir()
        for name,raw in tracks.items(): (folder/name).write_bytes(raw)
    for car_id in range(7):
        preview_sprite = workspace/f'local/ii-menu-art/classic-v1/car{car_id}-preview.png'
        if preview_sprite.exists():
            (assets/preview_sprite.name).write_bytes(state.read_regular(preview_sprite,8*1024*1024))
    index, image = (data/'RCS.IND').read_bytes(), (data/'RCS.IMG').read_bytes()
    evidence = []
    for i,name in enumerate(MESH_NAMES):
        raw = resource(index,image,name); mesh = decode_vehicle_mesh(raw)
        value = preview_mesh(mesh,i)
        (assets/f'car{i}.json').write_text(json.dumps(value),encoding='utf-8')
        evidence.append({'name':name,'sha256':base.fingerprint(raw),
                         'vertices':len(mesh.vertices),'triangles':len(mesh.triangles)})
    raw = resource(index,image,'WIEL.d3d');mesh = decode_vehicle_mesh(raw)
    wheel = {'positions':[list(v[:3]) for v in mesh.vertices],
             'uv':[list(v[6:8]) for v in mesh.vertices],
             'triangles':[list(t[:3]) for t in mesh.triangles]}
    (assets/'wheel.json').write_text(json.dumps(wheel),encoding='utf-8')
    evidence.append({'name':'WIEL.d3d','sha256':base.fingerprint(raw),
                     'vertices':len(mesh.vertices),'triangles':len(mesh.triangles)})
    for i,name in enumerate(('RACER01.PCX','RACER02.PCX','cars01.pcx')):
        raw = resource(index,image,name)
        (assets/f'texture{i}.png').write_bytes(png_from_pcx(raw))
        evidence.append({'name':name,'sha256':base.fingerprint(raw)})
    (assets/'texture3.png').write_bytes(isolated_white_skin(resource(index,image,'RACER01.PCX')))
    for size in (32,48): (assets/f'arrow{size}.cur').write_bytes(cursor_bytes(size))
    for source, destination in [('ii_frontend.ps1','Menu.ps1'),('ii_frontend.xaml','Menu.xaml'),
                                ('ii_frontend_state.py','Backend.py'),('ii_owned_session.ps1','OwnedSession.ps1')]:
        source_path = workspace/'tools'/source
        trial_manifest.validate_ancestors(source_path)
        shutil.copyfile(source_path,folder/destination)
    # Clean, separate menu profile; never copy used native slots/options.
    state.save_state(folder,state.initial_state())
    files = []
    for path in sorted(p for p in assets.rglob("*") if p.is_file()):
        files.append({'path':path.relative_to(folder).as_posix(),
                      'sha256':base.fingerprint(path.read_bytes())})
    for name in ('Menu.ps1','Menu.xaml','Backend.py','OwnedSession.ps1',
                 'game/DATA/SPEL.DAT','game/DATA/DDraw.dll','game/DATA/D3DImm.dll',
                 'game/DATA/GARAGE.INI','game/DATA/SPEL-WIDE.DAT',
                 'profiles/classic.conf','profiles/widescreen.conf'):
        files.append({'path':name,'sha256':base.fingerprint((folder/name).read_bytes())})
    config = {'schema':1,'game':'a2racer2','menu_revision':37,'python':python_path,'files':files,
              'race_binary_original':True,'native_menu_used':False,'race_fps':60,'race_display_version':1,
              'runtime_tested':False,'game_path':str(folder/'game'),
              'report_path':str(report),'resource_evidence':evidence}
    if (assets/'car4-preview.png').exists():
        config['preview_detail_revision'] = '20261013'
    if all((assets/f'car{i}-preview.png').exists() for i in range(7)):
        config['fleet_preview_revision'] = '20261013'
    write_json(folder/'Frontend.json',config)
    powershell = shutil.which('pwsh')
    (folder/'Start.cmd').write_text('@echo off\n"'+powershell.replace('%','%%')+
        '" -NoLogo -NoProfile -STA -WindowStyle Hidden -File "%~dp0Menu.ps1"\n',encoding='utf-8')
    (folder/'Start-Probe.ps1').unlink()  # own generated legacy entry; never an original
    (folder/'Lees-eerst.txt').write_text(
        'A2 Racer II - aanbevolen schermvullend Revival-menu (37)\n\n'
        'Open Start.cmd. Dit start het nieuwe menu, geen MENU.DAT.\n'
        'Kies je naam, baan en auto. Start race gebruikt de gekozen raceweergave.\n'
        'Eén duidelijke Windows-cursor; geen muisworker of globale DPI-wijziging.\n'
        'Tab en Enter bedienen de knoppen; Esc keert terug. Alt+F4 sluit de sessie.\n'
        'Vrij racen op de zeven lokaal aanwezige banen, met eigen spelers en records.\n'
        'De oude campagne, native slots en eerdere saves blijven apart behouden.\n'
        'Opties > Alles wissen en opnieuw beginnen zet dit nieuwe menu terug.\n'
        'De nieuwe raceweergave vraagt 1280x720, met camera- en HUD-correctie.\n'
        'Opties > Raceweergave biedt ook de eerdere klassieke 4:3-stand.\n'
        'Geen cd-image nodig. Geen game uitgevoerd tijdens voorbereiding.\n'
        'Controleer race-entry, terugkeer, cursor, focus en afsluiten tijdens spelen.\n',encoding='utf-8')
    if music_available:
        config['menu_music_revision']='20261013'
        write_json(folder/'Frontend.json',config)
    source_after = base.stable_manifest(workspace/'local/games/a2racer2',report)
    before = json.loads((report/'source-before.json').read_text(encoding='utf-8'))
    if any(trial_manifest.manifest_diff(before,source_after).values()):
        raise ValueError('De oorspronkelijke bron veranderde.')
    final = base.stable_manifest(folder/'game',report)
    write_json(report/'copy-frontend.json',final)
    write_json(report/'frontend-prepared.json',config)
    return config | {'start_file':str(folder/'Start.cmd'),'source_unchanged':True,
                     'source_files':len(source_after['files'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name',required=True)
    parser.add_argument('--python',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(ROOT,args.run_name,args.python),ensure_ascii=True,indent=2))


if __name__=='__main__': main()
