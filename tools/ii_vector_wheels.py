"""Code-native round tyre and vented aero rim; no image editing or game I/O."""
import math
import struct
from tools.vehicle_mesh import VehicleMesh

RADIUS = 3.6574180126190186
HALF_WIDTH = 1.3879139423370361
SEGMENTS = 32


def make_wheel(materials):
    """Use four constant UV samples from the existing wheel texture.

    Rotation/steering remain the native WIEL animation. The profile stays within
    its original radius and width; the vents are geometry, not a blurry decal.
    """
    if set(materials) != {'rubber', 'recess', 'alloy', 'edge'}:
        raise ValueError('Onvolledige wielmaterialen.')
    if any(len(uv) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v < 1 for v in uv)
           for uv in materials.values()):
        raise ValueError('Onjuiste wieltexturecoordinaten.')
    vertices, triangles, seen = [], [], {}

    def face(points, normal, material):
        # Explicit outward winding, independent of side or profile order.
        a, b, c = points[:3]
        ab = tuple(b[i]-a[i] for i in range(3)); ac = tuple(c[i]-a[i] for i in range(3))
        cross = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
        if sum(cross[i]*normal[i] for i in range(3)) < 0:
            points = tuple(reversed(points))
        indices = []
        for p in points:
            packed = struct.pack('<8fB', *p, *normal, *materials[material], 1)
            if packed not in seen:
                seen[packed] = len(vertices); vertices.append(struct.unpack('<8fB', packed))
            indices.append(seen[packed])
        for j in range(1, len(indices)-1):
            triangles.append((indices[0], indices[j], indices[j+1], 0, 7, 1))

    def point(x, radius, angle):
        return (x, radius*math.sin(angle), radius*math.cos(angle))

    def ring(x1, r1, x2, r2, material, outward=None):
        for i in range(SEGMENTS):
            a, b = i*math.tau/SEGMENTS, (i+1)*math.tau/SEGMENTS
            m = (a+b)/2
            # Normal of the lathed profile; tread radial, shoulders bevelled.
            dx, dr = x2-x1, r2-r1
            normal = (-dr, dx*math.sin(m), dx*math.cos(m))
            if outward is not None and normal[0]*outward < 0:
                normal = tuple(-v for v in normal)
            length = math.sqrt(sum(v*v for v in normal)); normal = tuple(v/length for v in normal)
            face((point(x1,r1,a),point(x2,r2,a),point(x2,r2,b),point(x1,r1,b)),normal,material)

    ring(-HALF_WIDTH,3.22,-1.08,RADIUS,'rubber')
    ring(-1.08,RADIUS,1.08,RADIUS,'rubber')
    ring(1.08,RADIUS,HALF_WIDTH,3.22,'rubber')
    for side in (-1,1):
        x = side*HALF_WIDTH; normal = (side,0,0)
        for outer, inner, material in ((3.22,2.66,'rubber'),(2.66,2.43,'edge'),(2.43,0.0,'recess')):
            face_x = x-side*.18 if material == 'recess' else x
            for i in range(SEGMENTS):
                a,b=i*math.tau/SEGMENTS,(i+1)*math.tau/SEGMENTS
                points = ((face_x,0,0),point(face_x,outer,a),point(face_x,outer,b)) if inner == 0 else (
                    point(face_x,inner,a),point(face_x,outer,a),point(face_x,outer,b),point(face_x,inner,b))
                face(points,normal,material)
        # A broad dished metal centre and short vents match the menu aero rims.
        # A shallow inset keeps all geometry within the original wheel width.
        ring(x-side*.12,1.81,x-side*.012,.50,'alloy',outward=side)
        for i in range(SEGMENTS):
            a=i*math.tau/SEGMENTS
            points=(point(x-side*.012,1.79,a),point(x-side*.13,2.39,a+.025),
                    point(x-side*.012,2.39,a+.16),point(x-side*.13,1.79,a+.15))
            for indices in ((0,1,2),(0,2,3)):
                p,q,r=(points[j] for j in indices)
                ab=tuple(q[j]-p[j] for j in range(3));ac=tuple(r[j]-p[j] for j in range(3))
                n=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
                length=math.sqrt(sum(v*v for v in n));sign=side if n[0]>=0 else -side
                n=tuple(v*sign/length for v in n)
                face((p,q,r),n,'alloy')
        for i in range(SEGMENTS):
            a,b=i*math.tau/SEGMENTS,(i+1)*math.tau/SEGMENTS
            face(((x,0,0),point(x,.50,a),point(x,.50,b)),normal,'edge')
    return VehicleMesh(tuple(vertices),tuple(triangles))


def encode_wheel(mesh):
    return (struct.pack('<II',len(mesh.vertices),len(mesh.triangles))
            +b''.join(struct.pack('<8fB',*v) for v in mesh.vertices)
            +b''.join(struct.pack('<3H3B',*t) for t in mesh.triangles))
