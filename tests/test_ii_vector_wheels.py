"""Synthetic geometry checks; no original game fixtures or native execution."""
import math
import unittest
from tools.ii_vector_wheels import make_wheel,encode_wheel,RADIUS,HALF_WIDTH
from tools.vehicle_mesh import decode_vehicle_mesh

class VectorWheelTests(unittest.TestCase):
    def setUp(self):
        self.materials={'rubber':(.1,.1),'recess':(.2,.2),'alloy':(.3,.3),'edge':(.4,.4)}
        self.mesh=make_wheel(self.materials)

    def test_round_profile_stays_inside_original_rolling_radius_and_width(self):
        self.assertTrue(all(abs(v[0])<=HALF_WIDTH+1e-6 and math.hypot(v[1],v[2])<=RADIUS+1e-6 for v in self.mesh.vertices))
        tread={(round(v[1],5),round(v[2],5)) for v in self.mesh.vertices if abs(math.hypot(v[1],v[2])-RADIUS)<1e-5}
        self.assertEqual(len(tread),32)
        self.assertAlmostEqual(max(math.hypot(v[1],v[2]) for v in self.mesh.vertices),RADIUS,places=5)

    def test_native_serialization_has_valid_indices_uv_flags_and_nondegenerate_outward_faces(self):
        mesh=decode_vehicle_mesh(encode_wheel(self.mesh))
        self.assertEqual((len(mesh.vertices),len(mesh.triangles)),(1424,832))
        for t in mesh.triangles:
            self.assertEqual(t[3:],(0,7,1))
            a,b,c=[mesh.vertices[i] for i in t[:3]]
            ab=[b[i]-a[i] for i in range(3)];ac=[c[i]-a[i] for i in range(3)]
            cross=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
            self.assertGreater(sum(cross[i]*a[3+i] for i in range(3)),1e-5)
        self.assertTrue(all(abs(sum(v*v for v in row[3:6])-1)<1e-5 for row in mesh.vertices))
        self.assertEqual({tuple(round(v,3) for v in row[6:8]) for row in mesh.vertices},set(self.materials.values()))

    def test_invalid_or_incomplete_materials_fail(self):
        for values in ({},dict(self.materials,alloy=(math.nan,.2)),dict(self.materials,alloy=(-.1,.2)),dict(self.materials,extra=(.5,.5))):
            with self.subTest(values=values),self.assertRaises(ValueError):make_wheel(values)

if __name__=='__main__':unittest.main()
