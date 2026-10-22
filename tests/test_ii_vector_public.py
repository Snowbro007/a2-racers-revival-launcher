"""Synthetic Vector geometry and transactional local-art publication."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ii_vector_public as public, ii_vector_geometry as geometry
from tools.vehicle_mesh import VehicleMesh, decode_vehicle_mesh


class PublicVectorTests(unittest.TestCase):
    def test_repaint_preserves_all_native_surfaces_and_stays_within_own_tiles(self):
        source = VehicleMesh(tuple(tuple(p) + (0., 1., 0., .1, .2, 1) for p in
            ((0., 0., 0.), (1., 2., 3.), (2., 1., 4.))), ((0, 1, 2, 0, 7, 1),) * 180)
        body, materials = geometry.make_body(source)
        decoded = decode_vehicle_mesh(geometry.encode_mesh(body))
        for before, after in zip(source.triangles, decoded.triangles):
            self.assertEqual([source.vertices[i][:6] for i in before[:3]],
                             [decoded.vertices[i][:6] for i in after[:3]])
        self.assertEqual(len(materials), len(body.triangles))
        self.assertTrue(all(0. < v[6] < 1. and 0. < v[7] < 1. for v in decoded.vertices))

    def test_changed_paint_stops_before_reading_any_native_resources(self):
        with patch.object(public, 'resource') as native:
            with self.assertRaises(ValueError): public.compile_resources(b'', b'', b'changed', b'')
            native.assert_not_called()

    def test_atomic_publication_reuses_valid_art_and_preserves_changed_art(self):
        parent = Path(__file__).resolve().parents[1] / 'local/test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            for relative in (public.PAINT, public.PREVIEW, 'local/games/a2racer2/DATA/RCS.IND',
                             'local/games/a2racer2/DATA/RCS.IMG'):
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'synthetic')
            outputs = {name: ('fixture-' + name).encode() for name in public.vector.ART_FILES}
            for name, vertices, triangles in (('vector-body.d3d',301,216),('vector-wheel.d3d',1424,832)):
                vertex=(0.,0.,0.,0.,1.,0.,.5,.5,1)
                outputs[name]=geometry.encode_mesh(VehicleMesh((vertex,)*vertices,((0,1,2,0,7,1),)*triangles))
            pins = {name: public.vector.sha(raw) for name, raw in outputs.items()}
            with patch.object(public, 'compile_resources', return_value=outputs) as compile_art, patch.object(public.vector, 'ART_FILES', pins):
                self.assertTrue(public.prepare(root)['prepared'])
                self.assertTrue(public.prepare(root)['already_prepared'])
                self.assertEqual(compile_art.call_count, 1)
                target = root / public.vector.ART_FOLDER
                changed = target / next(iter(outputs)); changed.write_bytes(b'changed')
                with self.assertRaises(ValueError): public.prepare(root)
                self.assertEqual(changed.read_bytes(), b'changed')
                self.assertFalse(list(target.parent.glob('.vector-build-*')))


if __name__ == '__main__': unittest.main()
