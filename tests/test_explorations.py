import math
import unittest

from tests.fixtures import (CELL, CRS, EXPLORATIONS, LINE, default_settings, load_project, make_line_layer,
                            plane_z, point_at, start_app)
from tests.test_units import FTUS

start_app()

from qgis.core import QgsCoordinateReferenceSystem, QgsProject  # noqa: E402

from xsections.core.explorations import (BOTTOM_AGREE_FT, find_explorations, fmt_ft, to_number,  # noqa: E402
                                         top_and_bottom, usable)
from xsections.core.model import SectionError, Settings  # noqa: E402
from xsections.core.section import ground_profile, raster_sampler, resolve_line  # noqa: E402

TRUTH = {row[0]: row for row in EXPLORATIONS}
PLOTTED = ["B-1", "MW-1", "TP-1", "B-2", "MW-2", "CPT-1", "B-3"]
EPS = 1e-3


def _compass8(dx, dy):
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    az = math.degrees(math.atan2(dx, dy)) % 360
    return names[int((az + 22.5) // 45) % 8]


def _left_normal(station):
    """Unit normal pointing left of the line at `station` (map units)."""
    acc = 0.0
    for (x1, y1), (x2, y2) in zip(LINE, LINE[1:]):
        L = math.dist((x1, y1), (x2, y2))
        if station <= acc + L:
            return -(y2 - y1) / L, (x2 - x1) / L
        acc += L


class Explorations(unittest.TestCase):
    @staticmethod
    def run_find(points_crs=CRS, bot_elev=False, **over):
        prj, dem, pts, lines = load_project(points_crs=points_crs, bot_elev=bot_elev)
        s = default_settings(prj, dem, pts, lines, **over)
        crs = QgsCoordinateReferenceSystem(CRS)
        line = resolve_line(s, prj, crs)
        sampler = raster_sampler(dem, 1, crs, 1.0)
        ground = ground_profile(line, sampler, CELL * FTUS, FTUS)
        hits, beyond, near = find_explorations(line, pts, s, crs, sampler, FTUS, prj, ground=ground)
        return hits, beyond, near, ground

    @classmethod
    def setUpClass(cls):
        cls.hits, cls.beyond, cls.near, cls.ground = cls.run_find()
        cls.by = {h.label: h for h in cls.hits}

    def test_plotted_set_and_order(self):
        self.assertEqual([h.label for h in self.hits], PLOTTED)       # truth table is in station order
        self.assertNotIn("B-far", self.by)
        self.assertEqual(sorted(self.beyond), ["B-post", "B-pre"])
        self.assertEqual(self.near, 0)                                 # B-far is 400 ft > 2.5 x 150 ft

    def test_station_offset_side_direction(self):
        for h in self.hits:
            name, typ, st, off, depth, top = TRUTH[h.label]
            self.assertAlmostEqual(h.station, st * FTUS, delta=0.01, msg=name)
            self.assertAlmostEqual(h.station, st, delta=0.01, msg=name)   # ftUS vs ft is 2 ppm
            self.assertAlmostEqual(h.offset, abs(off) * FTUS, delta=0.01, msg=name)
            self.assertEqual(h.side, "L" if off > 0 else "R", name)
            nx, ny = _left_normal(st)
            sign = 1 if off > 0 else -1
            self.assertEqual(h.direction, _compass8(sign * nx, sign * ny), name)
            self.assertEqual(h.type_value, typ)
            x, y = point_at(st, off)
            self.assertAlmostEqual(h.x, x, delta=1e-6)
            self.assertAlmostEqual(h.y, y, delta=1e-6)
        self.assertEqual(self.by["B-1"].direction, "N")
        self.assertEqual(self.by["MW-1"].direction, "S")

    def test_ground(self):
        for h in self.hits:
            name, typ, st, off, depth, top = TRUTH[h.label]
            x, y = point_at(st, off)
            if name == "B-3":
                self.assertTrue(math.isnan(h.ground_at_point))       # inside the nodata hole
                continue
            self.assertAlmostEqual(h.ground_at_point, plane_z(x, y), delta=EPS, msg=name)
            fx, fy = point_at(st)
            self.assertAlmostEqual(h.ground_at_station, plane_z(fx, fy), delta=EPS, msg=name)
            self.assertFalse(h.in_gap)

    def test_top_sources(self):
        want = {"B-1": "field", "MW-1": "dem", "TP-1": "dem", "B-2": "field", "MW-2": "dem",
                "CPT-1": "field", "B-3": "none"}
        self.assertEqual({h.label: h.top_source for h in self.hits}, want)
        for h in self.hits:
            name, typ, st, off, depth, top = TRUTH[h.label]
            x, y = point_at(st, off)
            if h.top_source == "dem":
                self.assertAlmostEqual(h.top, plane_z(x, y), delta=EPS, msg=name)
            elif h.top_source == "field":
                extra = 6.0 if top == "dem+6" else 0.0
                self.assertAlmostEqual(h.top, round(plane_z(x, y) + extra, 2), delta=1e-9, msg=name)

    def test_bottoms(self):
        """No bottom-elevation field: every bottom is top - depth, and the total depth is the depth field."""
        for h in self.hits:
            depth = TRUTH[h.label][4]
            if depth is None or h.top is None:
                self.assertIsNone(h.bottom, h.label)
                self.assertEqual(h.bottom_source, "none", h.label)
                self.assertIsNone(h.total_depth, h.label)
            else:
                self.assertAlmostEqual(h.bottom, h.top - depth, delta=1e-9, msg=h.label)
                self.assertEqual(h.bottom_source, "depth", h.label)
                self.assertEqual(h.total_depth, depth, h.label)

    def test_tick_base(self):
        b2 = self.by["B-2"]
        self.assertGreater(b2.top, b2.ground_at_station)
        self.assertEqual(b2.tick_base(True), b2.top)
        self.assertEqual(b2.tick_base(False), b2.ground_at_station)
        mw1 = self.by["MW-1"]                                    # top (LIDAR at the point) below the line
        self.assertEqual(mw1.tick_base(True), mw1.ground_at_station)

    def test_flags(self):
        mw2 = self.by["MW-2"]
        self.assertEqual(len(mw2.flags), 1)
        diff = abs(205.6 - mw2.ground_at_point)
        self.assertEqual(mw2.flags[0], f"ExploElev 205.6 ft ignored: {diff:.1f} ft from LIDAR")
        for name in ("B-1", "MW-1", "TP-1", "B-2", "CPT-1"):
            self.assertEqual(self.by[name].flags, [], name)

    def test_b3_in_gap(self):
        b3 = self.by["B-3"]
        self.assertTrue(b3.in_gap)
        self.assertIn("station in a DEM gap", b3.flags)
        self.assertEqual(b3.ground_at_station, self.ground.nearest_valid(b3.station))
        self.assertTrue(math.isfinite(b3.ground_at_station))
        self.assertIsNone(b3.bottom)
        self.assertIsNone(b3.top)
        a, b = self.ground.gaps[0]
        self.assertTrue(a < b3.station < b)

    def test_type_filter(self):
        hits, beyond, near, _ = self.run_find(types=["Boring"])
        self.assertEqual([h.label for h in hits], ["B-1", "B-2", "B-3"])
        self.assertTrue(all(h.type_value == "Boring" for h in hits))
        self.assertEqual(sorted(beyond), ["B-post", "B-pre"])
        hits, beyond, near, _ = self.run_find(types=["Monitoring Well", "CPT"])
        self.assertEqual([h.label for h in hits], ["MW-1", "MW-2", "CPT-1"])
        self.assertEqual(beyond, [])
        # a numeric "type" field: values arrive as text from the UI
        hits, beyond, near, _ = self.run_find(type_field="ExploDepth", types=["30", "45.0"])
        self.assertEqual([h.label for h in hits], ["B-1", "B-2"])
        self.assertEqual(sorted(beyond), ["B-post", "B-pre"])

    def test_points_in_wgs84(self):
        hits, beyond, near, _ = self.run_find(points_crs="EPSG:4326")
        self.assertEqual([h.label for h in hits], PLOTTED)
        self.assertEqual(sorted(beyond), ["B-post", "B-pre"])
        for h in hits:
            st, off = TRUTH[h.label][2], TRUTH[h.label][3]
            self.assertAlmostEqual(h.station, st * FTUS, delta=0.05, msg=h.label)
            self.assertAlmostEqual(h.offset, abs(off) * FTUS, delta=0.05, msg=h.label)
            x, y = point_at(st, off)
            self.assertAlmostEqual(h.x, x, delta=0.05)
            self.assertAlmostEqual(h.y, y, delta=0.05)

    def test_near_count(self):
        hits, beyond, near, _ = self.run_find(tolerance_ft=100.0)      # B-2 (120 ft) near, B-far (400) not
        self.assertNotIn("B-2", [h.label for h in hits])
        self.assertEqual(near, 1)
        hits, beyond, near, _ = self.run_find(tolerance_ft=170.0)      # 2.5 x 170 = 425 > 400: B-far near
        self.assertEqual([h.label for h in hits], PLOTTED)
        self.assertEqual(near, 1)
        self.assertEqual(sorted(beyond), ["B-post", "B-pre"])          # never counted as near
        hits, beyond, near, _ = self.run_find(tolerance_ft=70.0, types=["Monitoring Well"])
        self.assertEqual([h.label for h in hits], ["MW-1"])
        self.assertEqual(near, 1)                                      # MW-2 at 90 ft
        hits, beyond, near, _ = self.run_find(tolerance_ft=5.0)        # only B-3 (10 ft) is within 12.5 ft
        self.assertEqual(hits, [])
        self.assertEqual(near, 1)
        self.assertEqual(beyond, [])                                   # B-pre/B-post are > 5 ft away

    def test_zero_not_missing(self):
        hits, *_ = self.run_find(zero_is_missing=False)
        tp1 = [h for h in hits if h.label == "TP-1"][0]
        self.assertEqual(tp1.top_source, "dem")                        # 0 is > 25 ft from LIDAR
        self.assertTrue(tp1.flags and "ExploElev 0 ft ignored" in tp1.flags[0])

    def test_top_modes(self):
        hits, *_ = self.run_find(top_mode="dem")
        by = {h.label: h for h in hits}
        self.assertTrue(all(by[n].top_source == "dem" for n in PLOTTED if n != "B-3"))
        self.assertEqual(by["MW-2"].flags, [])
        hits, *_ = self.run_find(top_mode="field")
        by = {h.label: h for h in hits}
        self.assertEqual((by["MW-2"].top, by["MW-2"].top_source), (205.6, "field"))
        self.assertIn("from LIDAR", by["MW-2"].flags[0])
        self.assertEqual((by["MW-1"].top, by["MW-1"].top_source), (None, "none"))
        self.assertEqual(by["B-1"].top_source, "field")
        hits, *_ = self.run_find(top_max_diff_ft=500.0)
        by = {h.label: h for h in hits}
        self.assertEqual((by["MW-2"].top, by["MW-2"].top_source), (205.6, "field"))
        hits, *_ = self.run_find(top_field="")                          # no top field at all
        self.assertTrue(all(h.top_source in ("dem", "none") for h in hits))

    def test_bottom_elevation_field_only(self):
        hits, *_ = self.run_find(bottom_elev_field="ExploDepth", depth_field="")   # ExploDepth read as an elevation
        by = {h.label: h for h in hits}
        self.assertEqual((by["B-1"].bottom, by["B-1"].bottom_source), (30.0, "field"))
        self.assertAlmostEqual(by["B-1"].total_depth, by["B-1"].top - 30.0, delta=1e-9)   # top - bottom
        self.assertIsNone(by["B-3"].bottom)
        hits, *_ = self.run_find(depth_field="")
        self.assertTrue(all(h.bottom is None and h.bottom_source == "none" for h in hits))
        self.assertTrue(all(h.total_depth is None for h in hits))

    def test_labels(self):
        hits, *_ = self.run_find(label_field="")
        self.assertTrue(all(h.label.startswith("#") for h in hits))
        self.assertEqual(sorted(h.fid for h in hits), sorted(h.fid for h in self.hits))

    def test_errors(self):
        with self.assertRaises(SectionError):
            self.run_find(type_field="NoSuchField")
        with self.assertRaises(SectionError):
            self.run_find(tolerance_ft=0.0)
        prj, dem, pts, lines = load_project()
        s = default_settings(prj, dem, pts, lines)
        crs = QgsCoordinateReferenceSystem(CRS)
        line = resolve_line(s, prj, crs)
        sampler = raster_sampler(dem, 1, crs, 1.0)
        with self.assertRaises(SectionError):
            find_explorations(line, make_line_layer(), s, crs, sampler, FTUS, prj)
        with self.assertRaises(SectionError):
            find_explorations(line, None, s, crs, sampler, FTUS, prj)

    def test_without_ground_profile(self):
        prj, dem, pts, lines = load_project()
        s = default_settings(prj, dem, pts, lines)
        crs = QgsCoordinateReferenceSystem(CRS)
        line = resolve_line(s, prj, crs)
        hits, beyond, near = find_explorations(line, pts, s, crs, raster_sampler(dem, 1, crs, 1.0), FTUS, prj)
        self.assertEqual([h.label for h in hits], PLOTTED)
        self.assertTrue([h for h in hits if h.label == "B-3"][0].in_gap)

    def test_flat_end_caps(self):
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
        prj, dem, pts, lines = load_project()
        lyr = QgsVectorLayer(f"Point?crs={CRS}&field=ExploName:string", "caps", "memory")
        (ax, ay), (bx, by) = LINE[0], LINE[-1]
        ux, uy = (LINE[-1][0] - LINE[-2][0]), (LINE[-1][1] - LINE[-2][1])
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        spots = {"at-A": (ax, ay + 50.0), "behind-A": (ax - 1.0, ay + 50.0),
                 "at-A'": (bx - uy * 50.0, by + ux * 50.0), "past-A'": (bx - uy * 50.0 + ux, by + ux * 50.0 + uy),
                 # outside the bend, on the bisector of the two right-hand normals: nearest point is the bend
                 "bend-outside": (LINE[1][0] + 20.0 * 0.1452, LINE[1][1] - 20.0 * 0.9894)}
        feats = []
        for name, (x, y) in spots.items():
            f = QgsFeature(lyr.fields())
            f.setAttributes([name])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        s = default_settings(prj, dem, pts, lines, type_field="", top_field="", depth_field="")
        crs = QgsCoordinateReferenceSystem(CRS)
        line = resolve_line(s, prj, crs)
        hits, beyond, near = find_explorations(line, lyr, s, crs, raster_sampler(dem, 1, crs, 1.0), FTUS, prj)
        self.assertEqual(sorted(h.label for h in hits), ["at-A", "at-A'", "bend-outside"])
        self.assertEqual(sorted(beyond), ["behind-A", "past-A'"])
        by = {h.label: h for h in hits}
        self.assertAlmostEqual(by["at-A"].station, 0.0, delta=1e-6)
        self.assertAlmostEqual(by["at-A'"].station, line.length() * FTUS, delta=1e-3)
        self.assertAlmostEqual(by["bend-outside"].station, 2500.0 * FTUS, delta=1e-3)   # projects to the bend
        self.assertAlmostEqual(by["bend-outside"].offset, 20.0 * FTUS, delta=1e-3)
        self.assertEqual(by["bend-outside"].side, "R")


NAN = math.nan
S0 = dict(top_field="ExploElev", bottom_elev_field="BotElev", depth_field="ExploDepth")
NO_BOTTOM = "no bottom elevation or depth (BotElev and ExploDepth empty or 0): no top-to-bottom line"

# The precedence of decision 2 as a truth table. Each row: (case, (table top, LIDAR, table bottom, depth),
# settings overrides, (top, top_source, bottom, bottom_source, total_depth), flags). LIDAR 101 ft unless noted.
MATRIX = [
    ("T,B,D", (100.0, 101.0, 70.0, 30.0), {}, (100.0, "field", 70.0, "field", 30.0), []),
    ("T,-,D", (100.0, 101.0, None, 30.0), {}, (100.0, "field", 70.0, "depth", 30.0), []),
    ("-,-,D: LIDAR - depth", (None, 101.0, None, 30.0), {}, (101.0, "dem", 71.0, "depth", 30.0), []),
    ("T,B,-", (100.0, 101.0, 70.0, None), {}, (100.0, "field", 70.0, "field", 30.0), []),
    ("-,B,-: LIDAR top, table bottom", (None, 101.0, 70.0, None), {}, (101.0, "dem", 70.0, "field", 31.0), []),
    ("T, B = T, D: back to depth", (100.0, 101.0, 100.0, 30.0), {}, (100.0, "field", 70.0, "depth", 30.0),
     ["BotElev 100 ft is not below the top (100 ft): used top minus ExploDepth"]),
    ("T, B > T, D: back to depth", (100.0, 101.0, 120.0, 30.0), {}, (100.0, "field", 70.0, "depth", 30.0),
     ["BotElev 120 ft is not below the top (100 ft): used top minus ExploDepth"]),
    ("T, B > T, -: no line", (100.0, 101.0, 120.0, None), {}, (100.0, "field", None, "none", None),
     ["BotElev 120 ft is not below the top (100 ft): no top-to-bottom line"]),
    ("T,B,D 8 ft apart: table bottom + info", (100.0, 101.0, 62.0, 30.0), {}, (100.0, "field", 62.0, "field", 30.0),
     ["BotElev 62 ft used; top minus ExploDepth would give 70 ft"]),
    ("T,B,D 5 ft apart: no info", (100.0, 101.0, 65.0, 30.0), {}, (100.0, "field", 65.0, "field", 30.0), []),
    ("zeros missing", (0.0, 101.0, 0.0, 30.0), {}, (101.0, "dem", 71.0, "depth", 30.0), []),
    ("zero depth missing", (100.0, 101.0, None, 0.0), {}, (100.0, "field", None, "none", None), [NO_BOTTOM]),
    ("zeros kept: the table bottom is off top - depth too", (0.0, 101.0, 0.0, 30.0), {"zero_is_missing": False},
     (101.0, "dem", 71.0, "depth", 30.0),
     ["ExploElev 0 ft ignored: 101.0 ft from LIDAR", "BotElev 0 ft ignored: 71.0 ft from top minus ExploDepth (71 ft)"]),
    ("zero depth kept is still no depth", (100.0, 101.0, None, 0.0), {"zero_is_missing": False},
     (100.0, "field", None, "none", None), [NO_BOTTOM]),
    ("depth of about 0 is no depth", (100.0, 101.0, None, 0.04), {}, (100.0, "field", None, "none", None), [NO_BOTTOM]),
    # the table comes first: with the table's own top, a disagreeing table bottom is kept and flagged;
    # only a top that is not the table's (rejected, or LIDAR tops) makes top - depth win
    ("T,B,D 30 ft apart: table bottom kept", (100.0, 101.0, 40.0, 30.0), {}, (100.0, "field", 40.0, "field", 30.0),
     ["BotElev 40 ft used; top minus ExploDepth would give 70 ft"]),
    ("T,B,D 30 ft apart, LIDAR top", (100.0, 101.0, 40.0, 30.0), {"top_mode": "dem"}, (101.0, "dem", 71.0, "depth", 30.0),
     ["BotElev 40 ft ignored: 31.0 ft from top minus ExploDepth (71 ft)"]),
    ("T,B,D 30 ft apart, table only", (100.0, 101.0, 40.0, 30.0), {"top_mode": "field"},
     (100.0, "field", 40.0, "field", 30.0), ["BotElev 40 ft used; top minus ExploDepth would give 70 ft"]),
    ("T,B,D 30 ft apart, checks off", (100.0, 101.0, 40.0, 30.0), {"top_max_diff_ft": 0.0},
     (100.0, "field", 40.0, "field", 30.0), ["BotElev 40 ft used; top minus ExploDepth would give 70 ft"]),
    # the real MW-35R case: ExploElev 205.6 (meters), BotElev worked out from it, ExploDepth 15
    ("wrong top and bottom, depth: LIDAR - depth", (205.6, 674.6, 190.6, 15.0), {}, (674.6, "dem", 659.6, "depth", 15.0),
     ["ExploElev 205.6 ft ignored: 469.0 ft from LIDAR (205.6 m would match: XSections reads table values as feet)",
      "BotElev 190.6 ft ignored: 469.0 ft from top minus ExploDepth (659.6 ft)"]),
    ("wrong top and bottom, no depth: bottom shifted", (200.5, 614.0, 185.5, None), {},
     (614.0, "dem", 599.0, "shifted", 15.0),
     ["ExploElev 200.5 ft ignored: 413.5 ft from LIDAR",
      "BotElev 185.5 ft shifted with the top: 599 ft (15 ft below it, as in the table)"]),
    ("wrong top, bottom above it, no depth: bottom as it is", (200.5, 614.0, 590.5, None), {},
     (614.0, "dem", 590.5, "field", 23.5), ["ExploElev 200.5 ft ignored: 413.5 ft from LIDAR"]),
    ("wrong top, no depth, table only: no shift", (200.5, 614.0, 185.5, None), {"top_mode": "field"},
     (200.5, "field", 185.5, "field", 15.0), ["ExploElev 200.5 ft is 413.5 ft from LIDAR"]),
    ("top in meters, table only", (205.6, 674.6, None, 15.0), {"top_mode": "field"},
     (205.6, "field", 190.6, "depth", 15.0),
     ["ExploElev 205.6 ft is 469.0 ft from LIDAR (205.6 m would match: XSections reads table values as feet)"]),
    ("B a hair below T: not below", (100.0, 101.0, 99.99, None), {}, (100.0, "field", None, "none", None),
     ["BotElev 99.99 ft is not below the top (100 ft): no top-to-bottom line"]),
    ("B a hair below T, D: top - depth", (100.0, 101.0, 99.99, 30.0), {}, (100.0, "field", 70.0, "depth", 30.0),
     ["BotElev 99.99 ft is not below the top (100 ft): used top minus ExploDepth"]),
    ("far top, table then LIDAR", (10.0, 101.0, None, 20.0), {}, (101.0, "dem", 81.0, "depth", 20.0),
     ["ExploElev 10 ft ignored: 91.0 ft from LIDAR"]),
    ("far top, LIDAR only", (10.0, 101.0, None, 20.0), {"top_mode": "dem"}, (101.0, "dem", 81.0, "depth", 20.0), []),
    ("far top, table only", (10.0, 101.0, None, 20.0), {"top_mode": "field"}, (10.0, "field", -10.0, "depth", 20.0),
     ["ExploElev 10 ft is 91.0 ft from LIDAR"]),
    ("far top, check off", (10.0, 101.0, None, 20.0), {"top_max_diff_ft": 0.0}, (10.0, "field", -10.0, "depth", 20.0), []),
    ("table top, no LIDAR", (100.0, NAN, None, 20.0), {}, (100.0, "field", 80.0, "depth", 20.0), []),
    ("-,-,-: no line", (None, 101.0, None, None), {}, (101.0, "dem", None, "none", None), [NO_BOTTOM]),
    ("-,-,- zeros kept", (None, 101.0, None, None), {"zero_is_missing": False}, (101.0, "dem", None, "none", None),
     ["no bottom elevation or depth (BotElev and ExploDepth empty): no top-to-bottom line"]),
    ("-,-,- no line wanted", (None, 101.0, None, None), {"depth_line": False}, (101.0, "dem", None, "none", None), []),
    ("-,-,- no fields chosen", (None, 101.0, None, None), {"bottom_elev_field": "", "depth_field": ""},
     (101.0, "dem", None, "none", None), []),
    ("no top anywhere", (None, NAN, 70.0, 30.0), {}, (None, "none", None, "none", 30.0),
     ["no top elevation (no ExploElev value and no LIDAR at the point)"]),
    ("no LIDAR, LIDAR only", (100.0, NAN, None, 30.0), {"top_mode": "dem"}, (None, "none", None, "none", 30.0),
     ["no top elevation (no LIDAR at the point)"]),
    ("negative depth", (100.0, 101.0, None, -20.0), {}, (100.0, "field", 80.0, "depth", 20.0),
     ["ExploDepth -20 ft is negative; used 20 ft"]),
    ("NaN values are missing", (NAN, 101.0, NAN, NAN), {}, (101.0, "dem", None, "none", None), [NO_BOTTOM]),
]


class TopAndBottom(unittest.TestCase):
    def test_matrix(self):
        for case, (t, lidar, b, d), over, want, flags in MATRIX:
            s = Settings(**{**S0, **over})
            got = top_and_bottom(t, lidar, b, d, s)
            with self.subTest(case):
                self.assertEqual(tuple(got)[:5], want)
                self.assertEqual(got.flags, flags)

    def test_bottom_agreement_limit(self):
        self.assertEqual(BOTTOM_AGREE_FT, 5.0)
        s = Settings(**S0)
        self.assertEqual(top_and_bottom(100.0, 101.0, 64.9, 30.0, s).flags,
                         ["BotElev 64.9 ft used; top minus ExploDepth would give 70 ft"])

    def test_names_when_no_field_is_named(self):
        s = Settings(top_mode="field", depth_field="")
        self.assertEqual(top_and_bottom(None, 101.0, None, None, s).flags, ["no top elevation (no top field value)"])
        s = Settings(bottom_elev_field="", depth_field="")
        self.assertEqual(top_and_bottom(100.0, 101.0, None, -5.0, s).flags, ["depth -5 ft is negative; used 5 ft"])

    def test_usable(self):
        self.assertEqual([usable(v, True) for v in (None, NAN, math.inf, 0.0, -0.0, 3.5, "7")],
                         [None, None, None, None, None, 3.5, 7.0])
        self.assertEqual([usable(v, False) for v in (0.0, None, NAN)], [0.0, None, None])

    def test_to_number(self):
        self.assertEqual([to_number(v) for v in (None, "", "abc", "12.5", 3, float("nan"), 0.0)],
                         [None, None, None, 12.5, 3.0, None, 0.0])


class BottomElevationField(unittest.TestCase):
    """The fixture's BotElev variant: a bottom-elevation field next to ExploDepth (tests/fixtures.BOT_ELEV)."""

    @classmethod
    def setUpClass(cls):
        hits, cls.beyond, _, _ = Explorations.run_find(bot_elev=True, bottom_elev_field="BotElev")
        cls.by = {h.label: h for h in hits}

    def botelev(self, name):
        lyr = [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == "Explorations"][0]
        f = next(f for f in lyr.getFeatures() if f["ExploName"] == name)
        return f["BotElev"]

    def test_sources(self):
        want = {"B-1": ("field", "field"), "MW-1": ("dem", "depth"), "TP-1": ("dem", "field"),
                "B-2": ("field", "depth"), "MW-2": ("dem", "field"), "CPT-1": ("field", "depth"),
                "B-3": ("none", "none")}
        self.assertEqual({n: (h.top_source, h.bottom_source) for n, h in self.by.items()}, want)
        self.assertEqual(sorted(self.beyond), ["B-post", "B-pre"])

    def test_values_and_total_depth(self):
        for name, h in self.by.items():
            depth = TRUTH[name][4]
            if h.bottom_source == "field":
                self.assertAlmostEqual(h.bottom, self.botelev(name), delta=1e-9, msg=name)
            elif h.bottom_source == "depth":
                self.assertAlmostEqual(h.bottom, h.top - depth, delta=1e-9, msg=name)
            self.assertEqual(h.total_depth, depth, name)          # the depth field whenever it has a value
        self.assertIsNone(self.by["B-3"].bottom)
        self.assertIsNone(self.by["B-3"].total_depth)

    def test_flags(self):
        b1, tp1, b2, mw2 = (self.by[n] for n in ("B-1", "TP-1", "B-2", "MW-2"))
        self.assertEqual(b1.flags, [])                               # BotElev agrees with top - depth
        self.assertEqual(len(tp1.flags), 1)
        self.assertRegex(tp1.flags[0], r"^BotElev [\d.]+ ft used; top minus ExploDepth would give [\d.]+ ft$")
        self.assertAlmostEqual((tp1.top - 10.0) - tp1.bottom, 8.0, delta=0.01)
        self.assertEqual(b2.flags, [f"BotElev {fmt_ft(self.botelev('B-2'))} ft is not below the top "
                                    f"({fmt_ft(b2.top)} ft): used top minus ExploDepth"])
        self.assertTrue(mw2.flags[0].startswith("ExploElev 205.6 ft ignored"))
        self.assertEqual(len(mw2.flags), 1)
        self.assertEqual(self.by["CPT-1"].flags, [])                # BotElev 0 counts as missing

    def test_depth_field_alone_matches_the_truth_table(self):
        hits, *_ = Explorations.run_find(bot_elev=True)             # BotElev present but not chosen
        self.assertTrue(all(h.bottom_source in ("depth", "none") for h in hits))


if __name__ == "__main__":
    unittest.main()
