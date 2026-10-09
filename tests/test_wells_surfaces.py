"""Other surfaces (decision 15) and screens / water levels (decision 16): core, plan and drawing."""
import json
import math
import os
import tempfile
import unittest

import numpy as np

from tests.fixtures import (CRS, LINE, X0, Y0, default_settings, load_project, plane_z, point_at, start_app)
from tests.test_units import FTUS

start_app()

from matplotlib.figure import Figure  # noqa: E402
from qgis.core import (QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer,  # noqa: E402
                       QgsVectorLayer)
from qgis.PyQt.QtCore import QDate, QDateTime, QMetaType, QTime  # noqa: E402

from xsections.core import explorations as E  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import (SETTINGS_VERSION, SURFACE_DEFAULTS, Settings, WaterLevel,  # noqa: E402
                                  clean_surface, clean_surfaces, migrate_settings)
from xsections.core.section import cells_profile, raster_sampler, resolve_line  # noqa: E402
from xsections.render import figure as F  # noqa: E402
from xsections.render import scales as S  # noqa: E402
from xsections.ui import settings_store  # noqa: E402

# a coarse "model" raster over the fixture area: 100 ft cells, every cell a different value, its edges offset
# from the section line's vertices so that no stretch of the line runs along an edge
RX0, RY1, RCELL, RNX, RNY = X0 + 25.0, Y0 + 4150.0, 100.0, 60, 42


def cell_value(col, row, band=1):
    return 400.0 + col * 1.0 + row * 0.1 + (band - 1) * 1000.0


def make_raster(path=None, bands=1, offset=0.0, nodata_cols=()):
    from osgeo import gdal, osr
    gdal.UseExceptions()
    path = path or os.path.join(tempfile.mkdtemp(prefix="xsec_"), "surface.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, RNX, RNY, bands, gdal.GDT_Float32)
    ds.SetGeoTransform((RX0, RCELL, 0, RY1, 0, -RCELL))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2927)
    ds.SetProjection(srs.ExportToWkt())
    cols, rows = np.meshgrid(np.arange(RNX), np.arange(RNY))
    for b in range(1, bands + 1):
        arr = cell_value(cols, rows, b) + offset
        for c in nodata_cols:
            arr[:, c] = -9999.0
        band = ds.GetRasterBand(b)
        band.SetNoDataValue(-9999.0)
        band.WriteArray(arr.astype("float32"))
        band.SetUnitType("ft")
    ds.FlushCache()
    ds = None
    return path


def map_xy(station_ft):
    """Map x, y of a station (ft) along the fixture line."""
    return point_at(station_ft / FTUS)


class PureScreens(unittest.TestCase):
    def s(self, **kw):
        return Settings(**kw)

    def test_depths_below_the_top(self):
        r = E.screen_and_levels(600.0, 560.0, 25.0, 35.0, [], self.s())
        self.assertEqual((r.screen_top, r.screen_bottom), (575.0, 565.0))
        self.assertEqual(r.flags, [])
        r = E.screen_and_levels(600.0, 560.0, 35.0, 25.0, [], self.s())          # either order
        self.assertEqual((r.screen_top, r.screen_bottom), (575.0, 565.0))

    def test_elevations(self):
        r = E.screen_and_levels(600.0, 560.0, 565.0, 575.0, [], self.s(screen_values="elevation"))
        self.assertEqual((r.screen_top, r.screen_bottom), (575.0, 565.0))

    def test_half_a_screen_or_no_top(self):
        r = E.screen_and_levels(600.0, 560.0, 25.0, None, [], self.s())
        self.assertIsNone(r.screen_top)
        self.assertIn("screen top given without the bottom", r.flags[0])
        r = E.screen_and_levels(None, None, 25.0, 35.0, [], self.s())
        self.assertIsNone(r.screen_top)
        self.assertIn("no top elevation", r.flags[0])

    def test_screen_beyond_the_exploration(self):
        # elevations given while depths are expected: entirely below the bottom -> left out
        r = E.screen_and_levels(600.0, 560.0, 565.0, 575.0, [], self.s())
        self.assertIsNone(r.screen_top)
        self.assertIn("left out", r.flags[0])
        self.assertIn("depths below the top", r.flags[0])
        # partly below: drawn, flagged
        r = E.screen_and_levels(600.0, 560.0, 30.0, 45.0, [], self.s())
        self.assertEqual((r.screen_top, r.screen_bottom), (570.0, 555.0))
        self.assertIn("below the bottom", r.flags[0])

    def test_levels(self):
        levels = [(575.5, "measured", "6/12/2025", "WL_Elev"), (590.0, "atd", "", "ATD"), (0.0, "atd", "", "x"),
                  (None, "measured", "", "y"), (575.5, "measured", "6/12/2025", "table"),     # a duplicate
                  (20.0, "measured", "", "z"), (750.0, "atd", "", "t")]
        r = E.screen_and_levels(600.0, 560.0, None, None, levels, self.s())
        self.assertEqual([(w.elev, w.kind) for w in r.levels], [(590.0, "atd"), (575.5, "measured")])
        self.assertEqual(r.levels[1].date, "6/12/2025")
        self.assertTrue(any("20 ft is below the bottom" in f and "left out" in f for f in r.flags))
        self.assertTrue(any("750 ft is 150 ft above the top" in f for f in r.flags))
        # 0 counts as a value when zeros are not missing (and is then far below the bottom)
        r = E.screen_and_levels(600.0, 560.0, None, None, [(0.0, "atd", "", "x")], self.s(zero_is_missing=False))
        self.assertEqual(r.levels, [])
        self.assertIn("left out", r.flags[0])

    def test_levels_as_depths(self):
        s = self.s(wl_values="depth")
        levels = [(12.0, "measured", "", "DTW"), (-2.0, "atd", "", "ATD"), (50.0, "atd", "", "ATD"),
                  (0.0, "measured", "", "DTW")]
        r = E.screen_and_levels(600.0, 560.0, None, None, levels, s)
        self.assertEqual([(w.elev, w.kind) for w in r.levels], [(602.0, "atd"), (588.0, "measured")])
        self.assertEqual(len(r.flags), 1)
        self.assertIn("depth 50 ft (550 ft) is below the bottom", r.flags[0])
        self.assertIn("read as depths below the top", r.flags[0])
        r = E.screen_and_levels(None, None, None, None, [(12.0, "measured", "", "DTW")], s)
        self.assertEqual(r.levels, [])
        self.assertIn("no top elevation", r.flags[0])

    def test_atd_kind(self):
        self.assertEqual(E.atd_kind("Measured", self.s()), "atd")                        # no kind field
        s = self.s(wl_table_kind_field="Kind")
        self.assertEqual(E.atd_kind("ATD", s), "atd")
        self.assertEqual(E.atd_kind("atd (drilling)", s), "atd")
        self.assertEqual(E.atd_kind("Static", s), "measured")
        s = self.s(wl_table_kind_field="Kind", wl_atd_values=["Drilling"])
        self.assertEqual(E.atd_kind("Drilling", s), "atd")
        self.assertEqual(E.atd_kind("ATD", s), "measured")

    def test_date_text_and_name_key(self):
        self.assertEqual(E.date_text(QDate(2025, 6, 12)), "6/12/2025")
        self.assertEqual(E.date_text(QDateTime(QDate(2024, 1, 3), QTime(10, 30))), "1/3/2024")
        self.assertEqual(E.date_text(" 2025-06 "), "2025-06")
        self.assertEqual(E.date_text(None), "")
        self.assertEqual(E.date_text(QDate()), "")
        self.assertEqual(E.name_key("  MW 1 "), E.name_key("mw 1"))
        self.assertNotEqual(E.name_key("MW-1"), E.name_key("MW1"))


class SurfaceSettings(unittest.TestCase):
    def test_clean_surface(self):
        self.assertIsNone(clean_surface("x"))
        d = clean_surface({"layer_id": "r1", "band": 2.0, "style": "zigzag", "width": 99, "mode": "cells",
                           "visible": "yes", "extra": 1})
        self.assertEqual(set(d), set(SURFACE_DEFAULTS))
        self.assertEqual((d["layer_id"], d["band"], d["style"], d["width"], d["mode"], d["visible"]),
                         ("r1", 2, "solid", 4.0, "cells", True))
        self.assertEqual(clean_surfaces([{"layer_id": "a"}, 3, None]), [dict(SURFACE_DEFAULTS, layer_id="a")])

    def test_round_trip_and_migration(self):
        s = Settings(surfaces=[dict(SURFACE_DEFAULTS, layer_id="r1", name="WT", color="#123456")],
                     screen_top_field="ScrTop", wl_atd_values=["ATD"], wl_label="elev_date")
        back = Settings.from_json(s.to_json())
        self.assertEqual(back, s)
        self.assertEqual(SETTINGS_VERSION, 7)
        old = json.loads(Settings().to_json())
        old["version"] = 4
        for k in ("surfaces", "screens", "screen_top_field", "wl_label"):
            old.pop(k)
        self.assertEqual(Settings.from_json(json.dumps(old)), Settings())
        self.assertEqual(migrate_settings({"surfaces": [{"band": 0}, "x"]})["surfaces"], [dict(SURFACE_DEFAULTS)])

    def test_store_coerces_surfaces(self):
        start_app()
        prj = QgsProject.instance()
        prj.clear()
        data = json.loads(Settings().to_json())
        data["surfaces"] = [{"layer_id": "r1", "width": "thick"}, 7]
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(data))
        s = settings_store.load(prj)
        self.assertEqual(s.surfaces, [dict(SURFACE_DEFAULTS, layer_id="r1")])
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(dict(data, surfaces="nope")))
        self.assertEqual(settings_store.load(prj).surfaces, [])


class CellsProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.layer = QgsRasterLayer(make_raster(), "model_layer")
        cls.prj.addMapLayer(cls.layer)

    def test_steps_fall_on_cell_edges(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines)
        crs = self.layer.crs()
        line = resolve_line(s, self.prj, crs)
        samp = raster_sampler(self.layer, 1, crs, 1.0)
        st, z, cov = cells_profile(line, samp, FTUS, RCELL * FTUS)
        self.assertAlmostEqual(cov, 1.0)
        self.assertEqual(st[0], 0.0)
        self.assertGreater(len(st), 40)
        self.assertEqual(len(st) % 2, 0)
        for i in range(0, len(st), 2):                          # each flat piece: the cell under its middle
            a, b = st[i], st[i + 1]
            self.assertGreater(b, a)
            self.assertEqual(z[i], z[i + 1])
            x, y = map_xy((a + b) / 2.0)
            col, row = math.floor((x - RX0) / RCELL), math.floor((RY1 - y) / RCELL)
            self.assertAlmostEqual(z[i], cell_value(col, row), places=3)
        for i in range(1, len(st) - 1, 2):                      # every step sits on a cell edge
            self.assertAlmostEqual(st[i], st[i + 1], delta=1e-9)
            x, y = map_xy(st[i])
            fx, fy = (x - RX0) / RCELL, (RY1 - y) / RCELL
            self.assertTrue(abs(fx - round(fx)) < 1e-6 or abs(fy - round(fy)) < 1e-6, (x, y))
        self.assertAlmostEqual(st[-1], line.length() * FTUS, delta=1e-6)


class SurfacesInTheModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.wt = QgsRasterLayer(make_raster(offset=110.0), "wt_2024")       # 510 + ... : under the 500-560 ground
        cls.deep = QgsRasterLayer(make_raster(bands=2, offset=-300.0), "mf6_botm")   # band 1 ~100-160 ft
        cls.prj.addMapLayers([cls.wt, cls.deep])

    def settings(self, **kw):
        surfaces = [dict(SURFACE_DEFAULTS, layer_id=self.wt.id(), name="Water table 2024", marks=True,
                         style="dash"),
                    dict(SURFACE_DEFAULTS, layer_id=self.deep.id(), band=1, mode="cells", color="#8c5a3c",
                         in_range=kw.pop("deep_in_range", True))]
        return default_settings(self.prj, self.dem, self.pts, self.lines, surfaces=surfaces, **kw)

    def test_profiles(self):
        m = build_section(self.settings(), self.prj)
        self.assertEqual([sp.name for sp in m.surfaces], ["Water table 2024", "mf6_botm band 1"])
        wt, deep = m.surfaces
        self.assertEqual((wt.style, wt.mode, wt.marks), ("dash", "smooth", True))
        self.assertEqual(deep.mode, "cells")
        self.assertAlmostEqual(wt.coverage, 1.0)
        # bilinear on cell centres: halfway between two centres along x is their mean
        x, y = map_xy(1000.0)
        i = int(np.argmin(np.abs(np.asarray(wt.stations) - 1000.0)))
        self.assertLess(abs(wt.stations[i] - 1000.0), 5.0)
        self.assertTrue(500.0 < wt.z[i] < 580.0)
        self.assertEqual(len(deep.stations) % 2, 0)

    def test_warnings_not_errors(self):
        s = self.settings()
        s.surfaces.append(dict(SURFACE_DEFAULTS, layer_id="gone", name="Old"))
        s.surfaces.append(dict(SURFACE_DEFAULTS, layer_id=self.deep.id(), band=5))
        s.surfaces.append(dict(SURFACE_DEFAULTS, layer_id=self.wt.id(), visible=False))
        m = build_section(s, self.prj)
        self.assertEqual(len(m.surfaces), 2)
        self.assertTrue(any("“Old”" in w and "no longer in the project" in w for w in m.warnings))
        self.assertTrue(any("has no band 5" in w for w in m.warnings))

    def test_elevation_range(self):
        s_in = self.settings(**S_STANDARD)
        s_out = self.settings(deep_in_range=False, **S_STANDARD)
        p_in = S.plan(build_section(s_in, self.prj), s_in)
        p_out = S.plan(build_section(s_out, self.prj), s_out)
        self.assertLess(p_in.z_min, 200.0)                   # the model bottom (~100-160 ft) is on the sheet
        self.assertGreaterEqual(p_out.z_min, 350.0)          # clipped at the frame instead
        self.assertIn("mf6_botm band 1", p_in.lowest_what)


S_STANDARD = dict(compact_layout=False, fill_grid="off", sheet="custom", v_scale=50.0, h_scale=500.0)


def _wells_layer():
    lyr = QgsVectorLayer(f"Point?crs={CRS}", "wells", "memory")
    lyr.dataProvider().addAttributes([
        QgsField("ExploName", QMetaType.Type.QString), QgsField("ExploType", QMetaType.Type.QString),
        QgsField("ExploDepth", QMetaType.Type.Double), QgsField("ExploElev", QMetaType.Type.Double),
        QgsField("ScrTop", QMetaType.Type.Double), QgsField("ScrBot", QMetaType.Type.Double),
        QgsField("WL_Elev", QMetaType.Type.Double), QgsField("WL_Date", QMetaType.Type.QDate),
        QgsField("ATD_Elev", QMetaType.Type.Double), QgsField("DTW", QMetaType.Type.Double)])
    lyr.updateFields()
    rows = [  # name, station, offset, depth, scr top, scr bot, WL (relative to LIDAR), WL date, ATD (relative)
        ("W-1", 900.0, 20.0, 40.0, 25.0, 35.0, -8.0, QDate(2025, 6, 12), -5.0),
        ("W-2", 2000.0, -30.0, 30.0, 10.0, None, None, None, None),
        ("B-9", 3000.0, 15.0, 25.0, None, None, None, None, 0.0),
        ("W-3", 3500.0, -10.0, 30.0, None, None, "abs20", None, None),
    ]
    feats = []
    for name, st, off, depth, sa, sb, wl, date, atd in rows:
        x, y = point_at(st, off)
        z = plane_z(x, y)
        f = QgsFeature(lyr.fields())
        wl_v = 20.0 if wl == "abs20" else (None if wl is None else round(z + wl, 2))
        atd_v = None if atd is None else (0.0 if atd == 0.0 else round(z + atd, 2))
        f.setAttributes([name, "Well", depth, None, sa, sb, wl_v, date, atd_v, 8.0 if name == "W-1" else None])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()
    return lyr


def _wl_table():
    t = QgsVectorLayer("None", "water_levels", "memory")
    t.dataProvider().addAttributes([QgsField("Name", QMetaType.Type.QString), QgsField("Elev", QMetaType.Type.Double),
                                    QgsField("Date", QMetaType.Type.QString), QgsField("Kind", QMetaType.Type.QString)])
    t.updateFields()
    feats = []
    x2, y2 = point_at(2000.0, -30.0)
    x9, y9 = point_at(3000.0, 15.0)
    for name, elev, date, kind in [("W-2", plane_z(x2, y2) - 6.0, "1/5/2024", "ATD"),
                                   ("W-2", plane_z(x2, y2) - 18.0, "1/6/2024", "ATD"),
                                   (" w-1 ", 512.0, "3/1/2025", "Static"),
                                   ("B-9", plane_z(x9, y9) - 4.0, "", "atd drilling"),
                                   ("Nowhere", 500.0, "", "ATD")]:
        f = QgsFeature(t.fields())
        f.setAttributes([name, elev, date, kind])
        feats.append(f)
    t.dataProvider().addFeatures(feats)
    return t


class ScreensInTheModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.wells = _wells_layer()
        cls.table = _wl_table()
        cls.prj.addMapLayers([cls.wells, cls.table])

    def settings(self, **kw):
        base = dict(points_layer_id=self.wells.id(), type_field="", screen_top_field="ScrTop",
                    screen_bottom_field="ScrBot", wl_field="WL_Elev", wl_date_field="WL_Date", atd_field="ATD_Elev",
                    wl_table_id=self.table.id(), wl_table_name_field="Name", wl_table_elev_field="Elev",
                    wl_table_date_field="Date", wl_table_kind_field="Kind")
        base.update(kw)
        return default_settings(self.prj, self.dem, self.wells, self.lines, **base)

    def hits(self, **kw):
        return {h.label: h for h in build_section(self.settings(**kw), self.prj).hits}

    def test_screens_and_levels(self):
        h = self.hits()
        w1 = h["W-1"]
        self.assertAlmostEqual(w1.screen_top, w1.top - 25.0, places=6)
        self.assertAlmostEqual(w1.screen_bottom, w1.top - 35.0, places=6)
        self.assertEqual([w.kind for w in w1.water_levels], ["atd", "measured", "measured"])
        self.assertEqual([w.source for w in w1.water_levels], ["ATD_Elev", "WL_Elev", "table"])
        self.assertEqual(w1.water_levels[1].date, "6/12/2025")
        self.assertEqual(w1.water_levels[2].elev, 512.0)                     # " w-1 " matches W-1
        w2 = h["W-2"]
        self.assertIsNone(w2.screen_top)
        self.assertTrue(any("screen top given without the bottom" in f for f in w2.flags))
        self.assertEqual([w.kind for w in w2.water_levels], ["atd", "atd"])
        self.assertGreater(w2.water_levels[0].elev, w2.water_levels[1].elev)
        b9 = h["B-9"]
        self.assertEqual([w.kind for w in b9.water_levels], ["atd"])         # the 0 ATD field is missing
        w3 = h["W-3"]
        self.assertEqual(w3.water_levels, [])
        self.assertTrue(any("left out" in f for f in w3.flags))

    def test_depths_to_water(self):
        h = self.hits(wl_values="depth", wl_field="DTW", atd_field="", wl_table_id="")
        w1 = h["W-1"]
        self.assertEqual([(round(w.elev, 6), w.kind, w.source) for w in w1.water_levels],
                         [(round(w1.top - 8.0, 6), "measured", "DTW")])
        self.assertTrue(all(not x.water_levels for k, x in h.items() if k != "W-1"))
        s = self.settings(wl_values="depth", wl_field="DTW", atd_field="", wl_table_id="")
        m = build_section(s, self.prj)
        notes = " ".join(t for t, _ in F.notes_text(m, s, S.plan(m, s), S.plan(m, s).pages[0]))
        self.assertIn("water levels: DTW (depths below the top)", notes)

    def test_points_csv(self):
        import csv
        from xsections.ui.dock import write_hits_csv
        s = self.settings()
        m = build_section(s, self.prj)
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_csv_"), "pts.csv")
        write_hits_csv(out, m, s)
        with open(out, newline="", encoding="utf-8-sig") as fh:
            rows = {r["name"]: r for r in csv.DictReader(fh)}
        w1 = next(h for h in m.hits if h.label == "W-1")
        self.assertAlmostEqual(float(rows["W-1"]["screen_top_ft"]), w1.screen_top, places=2)
        self.assertAlmostEqual(float(rows["W-1"]["screen_bottom_ft"]), w1.screen_bottom, places=2)
        self.assertIn("measured 6/12/2025", rows["W-1"]["water_levels"])
        self.assertIn("512 measured 3/1/2025", rows["W-1"]["water_levels"])
        self.assertEqual(rows["W-2"]["water_levels"].count("ATD"), 2)
        self.assertEqual(rows["W-2"]["screen_top_ft"], "")

    def test_off_and_missing(self):
        h = self.hits(screens=False)
        self.assertTrue(all(x.screen_top is None and not x.water_levels for x in h.values()))
        h = self.hits(wl_table_kind_field="")                                # no kind field: all table rows ATD
        self.assertEqual([w.kind for w in h["W-1"].water_levels], ["atd", "measured", "atd"])
        from xsections.core.model import SectionError
        with self.assertRaises(SectionError):
            build_section(self.settings(wl_table_id="gone"), self.prj)
        with self.assertRaises(SectionError):
            build_section(self.settings(wl_table_elev_field="Nope"), self.prj)

    def test_range_includes_levels(self):
        s = self.settings(depth_line=False, **S_STANDARD)
        m = build_section(s, self.prj)
        lo, hi, _, what = S._data_extent(m, s)
        lowest = min(w.elev for x in m.hits for w in x.water_levels)
        self.assertLessEqual(lo, min(lowest, min(x.screen_bottom for x in m.hits if x.screen_bottom)))

    def test_drawing(self):
        s = self.settings(wl_label="elev_date", sheet="custom", h_scale=500.0, v_scale=20.0)
        m = build_section(s, self.prj)
        p = S.plan(m, s)
        fig = Figure()
        F.draw_page(fig, m, s, p, p.pages[0])
        ax = fig.axes[0]
        gid = lambda g: [a for a in ax.get_children() if a.get_gid() == g]   # noqa: E731
        self.assertEqual(len(gid(F.SCREEN_GID)), 1)                           # W-1 only
        self.assertEqual(len(gid(F.LEADER_GID)), 2)                           # its two measured levels
        tri_open, tri_full = gid(F.WL_GID), gid(F.ATD_GID)
        self.assertEqual(len(tri_open), 2)
        self.assertEqual(len(tri_full), 4)                                    # W-1, W-2 x2, B-9
        w1 = next(h for h in m.hits if h.label == "W-1")
        tip = tri_full[0].get_xy()[0]                                          # tips on the levels
        atd = w1.water_levels[0]
        pg = p.pages[0]
        kx = pg.plot_w / (pg.x_max - pg.x_min)
        self.assertAlmostEqual(tip[0], w1.station - S.WL_DX_IN / kx, places=6)     # just left of the line
        self.assertAlmostEqual(tip[1], atd.elev, places=6)
        for t in tri_open:
            self.assertEqual(tuple(t.get_facecolor()[:3]), (1.0, 1.0, 1.0))
            self.assertLess(t.get_xy()[0][0], w1.station)                     # out on the leader, left of the line
        self.assertTrue(all(tuple(t.get_facecolor()[:3]) != (1.0, 1.0, 1.0) for t in tri_full))
        texts = [a.get_text() for a in gid(F.WL_TEXT_GID)]
        self.assertIn(f"{w1.water_levels[1].elev:,.1f} (6/12/2025)", texts)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        renderer = FigureCanvasAgg(fig).get_renderer()
        boxes = [t.get_window_extent(renderer) for t in gid(F.WL_TEXT_GID)]
        for i in range(len(boxes)):                                           # labels never overlap
            for j in range(i + 1, len(boxes)):
                self.assertFalse(boxes[i].overlaps(boxes[j]), (texts[i], texts[j]))
        # leader: out from the middle of the screen, then up to the level
        mid = (w1.screen_top + w1.screen_bottom) / 2.0
        xs, ys = gid(F.LEADER_GID)[0].get_data()
        self.assertAlmostEqual(ys[0], mid)
        self.assertAlmostEqual(ys[1], mid)
        self.assertAlmostEqual(xs[1], xs[2])
        # legend
        legend = [t.get_text() for t in fig.texts]
        for txt in ("Legend:", "Screen", "Water level", "Water at time of drilling (ATD)"):
            self.assertIn(txt, legend)

    def test_labels_off_and_screens_off(self):
        s = self.settings(sheet="custom", h_scale=500.0, v_scale=20.0)
        m = build_section(s, self.prj)
        fig = Figure()
        p = S.plan(m, s)
        F.draw_page(fig, m, s, p, p.pages[0])
        self.assertFalse([a for a in fig.axes[0].get_children() if a.get_gid() == F.WL_TEXT_GID])
        s.screens = False
        m = build_section(s, self.prj)
        p = S.plan(m, s)
        F.draw_page(fig, m, s, p, p.pages[0])
        kids = fig.axes[0].get_children()
        self.assertFalse([a for a in kids if a.get_gid() in (F.SCREEN_GID, F.WL_GID, F.ATD_GID)])
        self.assertNotIn("Legend:", [t.get_text() for t in fig.texts])


class SurfacesDrawn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.wt = QgsRasterLayer(make_raster(offset=110.0), "wt_2024")
        cls.prj.addMapLayer(cls.wt)

    def test_lines_marks_and_legend(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines, sheet="custom",
                             surfaces=[dict(SURFACE_DEFAULTS, layer_id=self.wt.id(), name="WT", style="dash",
                                            color="#1f6fb2", width=1.5, marks=True)])
        m = build_section(s, self.prj)
        p = S.plan(m, s)
        for compact in (True, False):
            s.compact_layout = compact
            p = S.plan(m, s)
            fig = Figure()
            F.draw_page(fig, m, s, p, p.pages[0])
            kids = fig.axes[0].get_children()
            lines = [a for a in kids if a.get_gid() == F.SURFACE_GID]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].get_color(), "#1f6fb2")
            self.assertEqual(lines[0].get_linewidth(), 1.5)
            self.assertNotEqual(lines[0].get_linestyle(), "-")
            marks = [a for a in kids if a.get_gid() == F.MARK_GID]
            self.assertGreaterEqual(len(marks), 1)                # crowded: the marks step aside or drop out
            pg = p.pages[0]
            kx = pg.plot_w / (pg.x_max - pg.x_min)
            for mk in marks:                                     # never on an exploration or its water levels
                tip = mk.get_xy()[0][0]
                for h in m.hits:
                    dx = (tip - h.station) * kx
                    self.assertFalse(-(S.LEADER_DX_IN + S.LEADER_STEP_IN + F.MARK_CLEAR_IN) < dx < F.MARK_CLEAR_IN,
                                     (h.label, dx))
            texts = [t.get_text() for t in fig.texts]
            self.assertIn("Legend:", texts)
            self.assertIn("WT", texts)


if __name__ == "__main__":
    unittest.main()
