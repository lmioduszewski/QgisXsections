import math
import unittest

from tests.fixtures import LINE, line_length, load_project, plane_z, point_at, start_app

start_app()


class FixtureSanity(unittest.TestCase):
    def test_layers_load(self):
        prj, dem, pts, lines = load_project()
        self.assertTrue(dem.isValid())
        self.assertEqual(pts.featureCount(), 10)
        self.assertEqual(lines.featureCount(), 1)
        v, ok = dem.dataProvider().sample(__import__("qgis.core", fromlist=["QgsPointXY"]).QgsPointXY(*point_at(100.0)), 1)
        self.assertTrue(ok)
        x, y = point_at(100.0)
        self.assertAlmostEqual(v, plane_z(x, y), delta=0.05)  # sample() is nearest-cell, not bilinear

    def test_line_length(self):
        self.assertAlmostEqual(line_length(), 2500.0 + math.hypot(2000.0, 600.0), places=6)


if __name__ == "__main__":
    unittest.main()
