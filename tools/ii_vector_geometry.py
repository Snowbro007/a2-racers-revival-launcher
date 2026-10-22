"""Rebind the player-owned Vector mesh to our paint; no game I/O."""
from collections import Counter
import math,struct
from tools.vehicle_mesh import VehicleMesh
ATLAS_ROWS=(0.,443/1774,886/1774,1278/1774,1.)
ATLAS_COLUMNS=(0.,443/887,1.)
ROOF=frozenset((136,145,148,157))
NOSE=frozenset((71,74,77,80))
WING=frozenset((162,163,166,167,168,169,170,171,172,173))
HOOD=frozenset((140,142,143,152,154,155,160,161))

def dot(a,b):return sum(x*y for x,y in zip(a,b))


def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def unit(v):
    length=math.sqrt(dot(v,v))
    return tuple(x/length for x in v) if length>1e-12 else (0,1,0)


def clamp(v):return min(.98,max(.02,v))


def tile_uv(tile,u,v):
    left,right=ATLAS_COLUMNS[tile%2:tile%2+2];top,bottom=ATLAS_ROWS[tile//2:tile//2+2]
    return (left+(right-left)*clamp(u),top+(bottom-top)*clamp(v))


def encode_mesh(mesh):
    return (struct.pack('<II',len(mesh.vertices),len(mesh.triangles))
            +b''.join(struct.pack('<8fB',*v) for v in mesh.vertices)
            +b''.join(struct.pack('<3H3B',*t) for t in mesh.triangles))


def base_body(source):
    glass_groups=(frozenset((139,144,151,156)),frozenset((138,146,150,158)),frozenset((14,)),frozenset((96,)))
    glass=frozenset.union(*glass_groups)
    vents=frozenset((137,147,149,159))
    hood=frozenset((140,142,143,152,154,155,160,161))
    rear=frozenset((56,58,62,64))
    side=frozenset((10,11,92,93))
    vertices=[];faces=[];materials=[]
    def add(vs,material):
        n=len(vertices);vertices.extend(vs);faces.append((n,n+1,n+2,0,7,1));materials.append(material)
    glass_bounds={}
    for group in glass_groups:
        points=[source.vertices[i] for face_id in group for i in source.triangles[face_id][:3]]
        axes=(0,2) if len(group)>1 else (2,1)
        bounds=[(min(p[a] for p in points),max(p[a] for p in points)) for a in axes]
        for face_id in group:glass_bounds[face_id]=(axes,bounds)
    for face_id,face in enumerate(source.triangles):
        material='glass' if face_id in glass else 'vents' if face_id in vents else 'hood' if face_id in hood else 'rear' if face_id in rear else 'side' if face_id in side else 'paint'
        vs=[]
        for index in face[:3]:
            v=source.vertices[index];x,y,z=v[:3]
            if material=='glass':
                axes,bounds=glass_bounds[face_id]
                values=[(v[a]-lo)/(hi-lo) for a,(lo,hi) in zip(axes,bounds)]
                uv=tile_uv(1,values[0],1-values[1])
            elif material=='vents':uv=tile_uv(2,(x+9)/18,(-z-12)/10)
            elif material=='hood':uv=tile_uv(4,(x+10.2)/20.4,(z-11.4)/10.5)
            elif material=='rear':uv=tile_uv(5,(x+10.1)/20.2,(8.82-y)/2.64)
            elif material=='side':uv=tile_uv(6,(z+22.2)/34.5,(8.75-y)/3.05)
            else:uv=tile_uv(0,(x+10.3)/20.6,(z+22.2)/44.4)
            vs.append(v[:6]+uv+v[8:])
        add(vs,material)
    # Narrow seal overlays only on each connected glass group's perimeter.
    # Original 180 surfaces remain first and unchanged in their position/normal records.
    def key(v):return tuple(round(x,3) for x in v[:3])
    def edge(a,b):return tuple(sorted((key(a),key(b))))
    for group in glass_groups:
        counts=Counter(edge(source.vertices[t[j]],source.vertices[t[(j+1)%3]]) for i in group for t in (source.triangles[i],) for j in range(3))
        for i in sorted(group):
            tri=[source.vertices[k] for k in source.triangles[i][:3]]
            normal=unit(cross(tuple(tri[1][a]-tri[0][a] for a in range(3)),tuple(tri[2][a]-tri[0][a] for a in range(3))))
            for j in range(3):
                a,b,c=tri[j],tri[(j+1)%3],tri[(j+2)%3]
                if counts[edge(a,b)]!=1:continue
                points=[]
                for p in (a,b,tuple(b[k]*.967+c[k]*.033 for k in range(9)),tuple(a[k]*.967+c[k]*.033 for k in range(9))):
                    points.append(tuple(p[k]+normal[k]*.012 for k in range(3))+normal+tile_uv(3,.5,.5)+(1,))
                add((points[0],points[1],points[2]),'window_seal')
                add((points[0],points[2],points[3]),'window_seal')
    return VehicleMesh(tuple(vertices),tuple(faces)),materials


def make_body(source):
    body,materials=base_body(source)
    vertices=list(body.vertices)
    for i,triangle in enumerate(body.triangles[:180]):
        face_normal=tuple(sum(vertices[k][a] for k in triangle[:3]) for a in (3,4,5))
        paint_axis=max(range(3),key=lambda a:abs(face_normal[a]))
        for index in triangle[:3]:
            v=vertices[index];x,y,z=v[:3];uv=None
            if i in ROOF:
                uv=tile_uv(3,(x+6.1)/12.2,(z+7.1)/8.0);materials[i]='graphite_canopy_cap'
            elif i in NOSE:
                uv=tile_uv(2,(x+6.6)/13.2,(5.5-y)/2.4);materials[i]='mechanical_nose_louvres'
            elif i in WING:
                uv=tile_uv(3,(x+9)/18,(z+22)/4);materials[i]='graphite_wing_panel'
            elif i in HOOD:
                # Sample the intended bonnet, ending before the generated bottom border.
                # Exclude the material atlas border from the bonnet samples.
                uv=tile_uv(4,(x+10.2)/20.4,min(.84,.025+.95*clamp((z-11.4)/10.5)))
            elif materials[i]=='paint':
                # Planar paint on each dominant surface, including vertical doors/bumper.
                # A top-only X/Z projection stretches one texture column over their height.
                if paint_axis==0:uv=tile_uv(0,(z+22.2)/44.4,(13-y)/13)
                elif paint_axis==2:uv=tile_uv(0,(x+10.3)/20.6,(13-y)/13)
                else:uv=tile_uv(0,(x+10.3)/20.6,(z+22.2)/44.4)
            if uv is not None:vertices[index]=v[:6]+uv+v[8:]
    result=VehicleMesh(tuple(vertices),body.triangles)
    for i,t in enumerate(source.triangles):
        if [result.vertices[k][:6] for k in result.triangles[i][:3]]!=[source.vertices[k][:6] for k in t[:3]]:
            raise ValueError('Original body surface changed.')
    return result,materials
