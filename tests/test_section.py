import math
import unittest

import numpy as np

from tests.fixtures import (CELL, CRS, HOLE, LINE, NX, NY, X0, Y0, default_settings, line_length, load_project,
                            plane_z, start_app)
from tests.test_units import FTUS, make_tiny_dem

start_app()

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject, QgsRasterLayer)

from xsections.core.model import SectionError, Settings  # noqa: E402
from xsections.core.section import (RasterSampler, compass_point, ground_profile, raster_sampler,  # noqa: E402
                                    resolve_line, section_crs, vertex_stations)

EPS = 1e-3          # ft; bilinear is exact on a plane (float32 DEM)


def _xy(line):
    return [(v.x(), v.y()) for v in line.vertices()]


def _wkt(pts):
    return "LineString (" + ", ".join(f"{float(x)!r} {float(y)!r}" for x, y in pts) + ")"


class SectionCrs(unittest.TestCase):
    def test_dem_crs_when_projected(self):
        prj, dem, pts, lines = load_project()
        self.assertEqual(section_crs(dem, prj).authid(), CRS)

    def test_project_crs_when_dem_geographic(self):
        prj = QgsProject.instance()
        prj.clear()
        prj.setCrs(QgsCoordinateReferenceSystem("EPSG:2926"))
        geo = QgsRasterLayer(make_tiny_dem(epsg=4326, origin=(-122.3, 47.1), cell=0.0001), "geo")
        self.assertEqual(section_crs(geo, prj).authid(), "EPSG:2926")

    def test_both_geographic_raises(self):
        prj = QgsProject.instance()
        prj.clear()
        prj.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        geo = QgsRasterLayer(make_tiny_dem(epsg=4326, origin=(-122.3, 47.1), cell=0.0001), "geo")
        with self.assertRaises(SectionError) as cm:
            section_crs(geo, prj)
        self.assertIn("geographic", str(cm.exception))

    def test_compass(self):
        self.assertEqual([compass_point(a) for a in (0, 44, 46, 90, 180, 270, 337.4, 337.6, 359.9)],
                         ["N", "NE", "NE", "E", "S", "W", "NW", "N", "N"])
        self.assertEqual(compass_point(22.6, 16), "NNE")
        self.assertEqual(compass_point(270, 16), "W")


class ResolveLine(unittest.TestCase):
    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.crs = QgsCoordinateReferenceSystem(CRS)

    def _drawn(self, wkt, authid=CRS):
        return Settings(line_wkt=wkt, line_crs_authid=authid)

    def test_feature(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines)
        line = resolve_line(s, self.prj, self.crs)
        self.assertEqual(_xy(line), LINE)
        self.assertEqual(line.wkbType(), QgsGeometry.fromWkt("LineString (0 0, 1 1)").wkbType())

    def test_drawn_other_crs(self):
        ct = QgsCoordinateTransform(self.crs, QgsCoordinateReferenceSystem("EPSG:4326"), self.prj)
        ll = [ct.transform(QgsPointXY(x, y)) for x, y in LINE]
        line = resolve_line(self._drawn(_wkt([(p.x(), p.y()) for p in ll]), "EPSG:4326"), self.prj, self.crs)
        for (x, y), (ex, ey) in zip(_xy(line), LINE):
            self.assertAlmostEqual(x, ex, delta=0.01)
            self.assertAlmostEqual(y, ey, delta=0.01)

    def test_drawn_crs_as_wkt(self):
        line = resolve_line(self._drawn(_wkt(LINE), self.crs.toWkt()), self.prj, self.crs)
        self.assertEqual(_xy(line), LINE)

    def test_feature_wins_over_drawn(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines,
                             line_wkt=_wkt([(X0, Y0), (X0 + 10, Y0)]), line_crs_authid=CRS)
        self.assertEqual(_xy(resolve_line(s, self.prj, self.crs)), LINE)
        s.line_fid = None                                   # drawn line used once the feature is cleared
        self.assertEqual(len(_xy(resolve_line(s, self.prj, self.crs))), 2)

    def test_multipart_merged(self):
        (a, b, c) = LINE
        wkt = f"MultiLineString (({a[0]} {a[1]}, {b[0]} {b[1]}), ({b[0]} {b[1]}, {c[0]} {c[1]}))"
        self.assertEqual(_xy(resolve_line(self._drawn(wkt), self.prj, self.crs)), LINE)

    def test_single_part_multi(self):
        wkt = "MultiLineString ((" + ", ".join(f"{x} {y}" for x, y in LINE) + "))"
        self.assertEqual(_xy(resolve_line(self._drawn(wkt), self.prj, self.crs)), LINE)

    def test_disjoint_multipart_raises(self):
        wkt = f"MultiLineString (({X0} {Y0}, {X0 + 100} {Y0}), ({X0 + 200} {Y0}, {X0 + 300} {Y0}))"
        with self.assertRaises(SectionError) as cm:
            resolve_line(self._drawn(wkt), self.prj, self.crs)
        self.assertIn("parts", str(cm.exception))

    def test_curve_segmentized(self):
        wkt = (f"CompoundCurve (({X0 + 500} {Y0 + 2000}, {X0 + 1000} {Y0 + 2000}), "
               f"CircularString ({X0 + 1000} {Y0 + 2000}, {X0 + 1200} {Y0 + 2200}, {X0 + 1400} {Y0 + 2000}))")
        line = resolve_line(self._drawn(wkt), self.prj, self.crs)
        xy = _xy(line)
        self.assertGreater(len(xy), 10)
        self.assertEqual(xy[0], (X0 + 500, Y0 + 2000))
        self.assertAlmostEqual(xy[-1][0], X0 + 1400, delta=1e-6)
        self.assertFalse(line.isMultipart())
        self.assertAlmostEqual(line.length(), 500 + math.pi * 200, delta=1.0)

    def test_duplicate_vertices_and_z_dropped(self):
        wkt = f"LineStringZ ({X0} {Y0} 5, {X0} {Y0} 5, {X0 + 100} {Y0} 7)"
        line = resolve_line(self._drawn(wkt), self.prj, self.crs)
        self.assertEqual(_xy(line), [(X0, Y0), (X0 + 100, Y0)])

    def test_degenerate_raises(self):
        for wkt in (f"LineString ({X0} {Y0}, {X0} {Y0})", f"Point ({X0} {Y0})", "nonsense"):
            with self.assertRaises(SectionError, msg=wkt):
                resolve_line(self._drawn(wkt), self.prj, self.crs)

    def test_no_line_raises(self):
        with self.assertRaises(SectionError) as cm:
            resolve_line(Settings(), self.prj, self.crs)
        self.assertIn("section line", str(cm.exception))

    def test_missing_layer_raises(self):
        with self.assertRaises(SectionError):
            resolve_line(Settings(line_layer_id="gone", line_fid=1), self.prj, self.crs)


class Sampler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.crs = QgsCoordinateReferenceSystem(CRS)

    def test_plane_exact(self):
        rng = np.random.default_rng(1)
        x = X0 + rng.uniform(10, NX * CELL - 10, 2000)
        y = Y0 + rng.uniform(10, 1800, 2000)                # below the hole
        z = raster_sampler(self.dem, 1, self.crs, 1.0)(x, y)
        self.assertTrue(np.all(np.isfinite(z)))
        self.assertLess(np.max(np.abs(z - plane_z(x, y))), EPS)

    def test_z_factor_and_shape(self):
        s = raster_sampler(self.dem, 1, self.crs, 3.0)
        x = np.array([[X0 + 100.0, X0 + 200.0]])
        y = np.array([[Y0 + 100.0, Y0 + 100.0]])
        z = s(x, y)
        self.assertEqual(z.shape, (1, 2))
        self.assertAlmostEqual(float(z[0, 1]), 3.0 * plane_z(X0 + 200.0, Y0 + 100.0), delta=3 * EPS)

    def test_outside_and_nodata_are_nan(self):
        s = raster_sampler(self.dem, 1, self.crs, 1.0)
        cx, cy, r = HOLE
        z = s(np.array([X0 - 10.0, X0 + 100.0, X0 + NX * CELL + 5, cx, cx + r - 10]),
              np.array([Y0 + 100.0, Y0 - 10.0, Y0 + 100.0, cy, cy]))
        self.assertTrue(np.all(np.isnan(z)), z)

    def test_windowed_reads(self):
        s = raster_sampler(self.dem, 1, self.crs, 1.0)
        self.assertIsInstance(s, RasterSampler)
        x = np.linspace(X0 + 5, X0 + NX * CELL - 5, 5000)
        y = np.linspace(Y0 + 5, Y0 + NY * CELL - 5, 5000)      # full diagonal
        z = s(x, y)
        full = math.ceil(NX / s.TILE) * math.ceil(NY / s.TILE)
        self.assertLess(s.block_reads, full)                     # only tiles the diagonal touches
        for arr in s._tiles.values():
            self.assertLessEqual(arr.size, (s.TILE + 1) ** 2)
        ok = np.isfinite(z)
        self.assertGreater(ok.mean(), 0.97)
        self.assertLess(np.max(np.abs(z[ok] - plane_z(x[ok], y[ok]))), EPS)
        reads = s.block_reads
        s(x, y)                                                  # cached
        self.assertEqual(s.block_reads, reads)

    def test_other_section_crs(self):
        utm = QgsCoordinateReferenceSystem("EPSG:32610")
        ct = QgsCoordinateTransform(self.crs, utm, self.prj)
        src = [(X0 + 123.4, Y0 + 456.7), (X0 + 4000.0, Y0 + 1000.0), (X0 + 5555.5, Y0 + 3999.0)]
        pts = [ct.transform(QgsPointXY(x, y)) for x, y in src]
        z = raster_sampler(self.dem, 1, utm, 1.0, self.prj.transformContext())(
            np.array([p.x() for p in pts]), np.array([p.y() for p in pts]))
        for zz, (x, y) in zip(z, src):
            self.assertAlmostEqual(float(zz), plane_z(x, y), delta=EPS)

    def test_bad_band_raises(self):
        with self.assertRaises(SectionError):
            raster_sampler(self.dem, 2, self.crs, 1.0)


class Profile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.crs = QgsCoordinateReferenceSystem(CRS)
        s = default_settings(cls.prj, cls.dem, cls.pts, cls.lines)
        cls.line = resolve_line(s, cls.prj, cls.crs)
        cls.f = FTUS
        cls.sampler = raster_sampler(cls.dem, 1, cls.crs, 1.0)
        cls.g = ground_profile(cls.line, cls.sampler, CELL * FTUS, FTUS)

    def _xy_at(self, station_ft):
        p = self.line.interpolate(station_ft / self.f).asPoint()
        return p.x(), p.y()

    def test_stations(self):
        st = np.array(self.g.stations)
        vs = vertex_stations(self.line, self.f)
        self.assertEqual(len(vs), 3)
        self.assertAlmostEqual(vs[-1], line_length() * self.f, delta=1e-6)
        self.assertTrue(np.all(np.diff(st) > 0))
        self.assertEqual(st[0], 0.0)
        self.assertEqual(st[-1], vs[-1])
        for v in vs:
            self.assertIn(v, self.g.stations)
        self.assertLessEqual(np.max(np.diff(st)), CELL * self.f + 1e-9)
        self.assertEqual(len(st), len(self.g.z))
        self.assertAlmostEqual(self.g.step, CELL * self.f)

    def test_plane_along_line(self):
        worst = 0.0
        for s, z in zip(self.g.stations, self.g.z):
            if math.isnan(z):
                continue
            x, y = self._xy_at(s)
            worst = max(worst, abs(z - plane_z(x, y)))
        self.assertLess(worst, EPS)

    def test_one_gap_from_hole(self):
        cx, cy, r = HOLE
        # the hole centre relative to the line's second leg
        (ax, ay), (bx, by) = LINE[1], LINE[2]
        L = math.dist((ax, ay), (bx, by))
        ux, uy = (bx - ax) / L, (by - ay) / L
        along = (cx - ax) * ux + (cy - ay) * uy
        d = abs(-(cx - ax) * uy + (cy - ay) * ux)
        self.assertLess(d, r)
        half = math.sqrt(r * r - d * d)
        centre = math.dist(LINE[0], LINE[1]) + along
        lo, hi = (centre - half) * self.f, (centre + half) * self.f
        slop = math.sqrt(2) * CELL + CELL + 0.01             # bilinear footprint + one step
        self.assertEqual(len(self.g.gaps), 1)
        a, b = self.g.gaps[0]
        self.assertTrue(lo - slop <= a <= lo + slop, (a, lo))
        self.assertTrue(hi - slop <= b <= hi + slop, (b, hi))
        self.assertLess(self.g.coverage, 1.0)
        self.assertGreater(self.g.coverage, 0.95)
        expected_cov = 1 - (b - a) / self.g.stations[-1]
        self.assertAlmostEqual(self.g.coverage, expected_cov, delta=0.005)
        self.assertTrue(math.isnan(self.g.z_at((a + b) / 2)))
        self.assertFalse(math.isnan(self.g.z_at(a - 1)))

    def test_pixel_edge_lines(self):
        cases = [
            [(X0 + 100.0, Y0 + 2100.0), (X0 + 1000.0, Y0 + 2100.0)],          # on an interior row edge
            [(X0 + 300.0, Y0 + 100.0), (X0 + 300.0, Y0 + 1000.0)],            # on an interior column edge
            [(X0 + 100.0, Y0 + NY * CELL), (X0 + 900.0, Y0 + NY * CELL)],     # on the raster's top edge
            [(X0, Y0 + 100.0), (X0, Y0 + 900.0)],                             # on the raster's left edge
        ]
        for pts in cases:
            line = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
            g = ground_profile(line, self.sampler, CELL, 1.0)
            self.assertGreater(len(g.z), 100, pts)
            self.assertEqual(g.coverage, 1.0, pts)
            self.assertEqual(g.gaps, [])
        # interior edges are still exact
        line = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in cases[0]])
        g = ground_profile(line, self.sampler, CELL, 1.0)
        for s, z in zip(g.stations, g.z):
            self.assertAlmostEqual(z, plane_z(X0 + 100.0 + s, Y0 + 2100.0), delta=EPS)

    def test_gap_at_start(self):
        line = QgsGeometry.fromPolylineXY([QgsPointXY(X0 - 300.0, Y0 + 500.0), QgsPointXY(X0 + 700.0, Y0 + 500.0)])
        g = ground_profile(line, self.sampler, CELL, 1.0)
        self.assertEqual(len(g.gaps), 1)
        self.assertEqual(g.gaps[0][0], 0.0)
        self.assertAlmostEqual(g.gaps[0][1], 300.0, delta=CELL)
        self.assertAlmostEqual(g.coverage, 0.7, delta=0.01)

    def test_off_dem_zero_coverage(self):
        line = QgsGeometry.fromPolylineXY([QgsPointXY(X0 - 3000.0, Y0), QgsPointXY(X0 - 1000.0, Y0)])
        g = ground_profile(line, self.sampler, CELL, 1.0)
        self.assertEqual(g.coverage, 0.0)
        self.assertEqual(g.gaps, [(0.0, g.stations[-1])])


if __name__ == "__main__":
    unittest.main()
