import math
import os
import unittest

import numpy as np

from tests.fixtures import (CELL, CRS, LINE, REALDATA, STANDARD_LAYOUT, TOLERANCE, X0, Y0, default_settings,
                            line_length, load_project, make_points_layer, start_app, terrain_z)
from tests.test_units import FTUS, make_tiny_dem

start_app()

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject,  # noqa: E402
                       QgsRasterLayer, QgsVectorLayer)

from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import NO_POINTS, SectionError, SectionModel, Settings  # noqa: E402
from xsections.render.scales import plan  # noqa: E402

PLOTTED = ["B-1", "MW-1", "TP-1", "B-2", "MW-2", "CPT-1", "B-3"]


def _wkt(pts):
    return "LineString (" + ", ".join(f"{float(x)!r} {float(y)!r}" for x, y in pts) + ")"


class BuildFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.settings = default_settings(cls.prj, cls.dem, cls.pts, cls.lines)
        cls.model = build_section(cls.settings, cls.prj)

    def test_model(self):
        m = self.model
        self.assertIsInstance(m, SectionModel)
        self.assertAlmostEqual(m.dist_factor, FTUS, delta=1e-12)
        self.assertAlmostEqual(m.length, line_length() * FTUS, delta=1e-6)
        self.assertEqual(len(m.vertex_stations), 3)
        self.assertEqual(m.vertex_stations[0], 0.0)
        self.assertAlmostEqual(m.vertex_stations[1], 2500.0 * FTUS, delta=1e-6)
        self.assertEqual(m.vertex_stations[-1], m.length)
        self.assertEqual(m.bend_stations, m.vertex_stations[1:-1])
        dx, dy = LINE[-1][0] - LINE[0][0], LINE[-1][1] - LINE[0][1]
        self.assertAlmostEqual(m.azimuth, math.degrees(math.atan2(dx, dy)), delta=1e-9)
        self.assertAlmostEqual(m.azimuth, 82.405, delta=1e-3)
        line = QgsGeometry.fromWkt(m.line_wkt)
        self.assertEqual([(v.x(), v.y()) for v in line.vertices()], LINE)
        self.assertTrue(QgsCoordinateReferenceSystem.fromWkt(m.section_crs_wkt).isValid())
        self.assertEqual(m.dem_name, "LIDAR_DEM_3ft")
        self.assertEqual(m.points_name, "Explorations")

    def test_ground_and_hits(self):
        m = self.model
        self.assertAlmostEqual(m.ground.step, CELL * FTUS, delta=1e-9)
        self.assertEqual(m.ground.stations[-1], m.length)
        self.assertEqual(len(m.ground.gaps), 1)
        self.assertLess(m.ground.coverage, 1.0)
        self.assertEqual([h.label for h in m.hits], PLOTTED)
        self.assertEqual(sorted(m.beyond_ends), ["B-post", "B-pre"])
        self.assertEqual(m.near_count, 0)
        stations = [h.station for h in m.hits]
        self.assertEqual(stations, sorted(stations))

    def test_warnings(self):
        text = "\n".join(self.model.warnings)
        self.assertIn("No DEM data along", text)
        self.assertIn("B-pre", text)
        self.assertIn("MW-2: ExploElev 205.6 ft ignored", text)
        self.assertIn("B-3: station in a DEM gap", text)
        self.assertNotIn("elevation units", text)                    # band unit "ft" is stated

    def test_drawn_line_same_as_feature(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines, line_layer_id="", line_fid=None,
                             line_wkt=_wkt(LINE), line_crs_authid=CRS)
        m = build_section(s, self.prj)
        self.assertEqual([h.label for h in m.hits], PLOTTED)
        self.assertEqual(m.length, self.model.length)
        self.assertEqual(m.ground.z[:50], self.model.ground.z[:50])

    def test_z_units_setting(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines, dem_z_units="m")
        m = build_section(s, self.prj)
        i = 10
        self.assertAlmostEqual(m.ground.z[i], self.model.ground.z[i] * 3.280839895, delta=1e-6)

    def test_default_project(self):
        m = build_section(self.settings)                              # QgsProject.instance()
        self.assertEqual(len(m.hits), len(self.model.hits))


class BuildGroundOnly(unittest.TestCase):
    """No explorations layer: a ground line only, with a warning, and the sheet still plans (R4)."""

    def test_ground_only(self):
        prj, dem, pts, lines = load_project()
        full = build_section(default_settings(prj, dem, pts, lines), prj)
        s = default_settings(prj, dem, pts, lines, points_layer_id="")
        m = build_section(s, prj)
        self.assertEqual((m.hits, m.beyond_ends, m.near_count), ([], [], 0))
        self.assertFalse(m.has_explorations)
        self.assertTrue(full.has_explorations)
        self.assertEqual(m.points_name, "")
        self.assertIn(NO_POINTS, m.warnings)
        self.assertFalse(any(w.startswith("No explorations within") for w in m.warnings))
        self.assertEqual(m.ground.z[:100], full.ground.z[:100])
        self.assertEqual(m.length, full.length)
        p = plan(m, s)
        self.assertTrue(p.fits, p.message)
        self.assertEqual(p.warnings, [])


class BuildBottomElevations(unittest.TestCase):
    """The BotElev variant through build_section: sources, total depth and flags reach the model."""

    def test_botelev(self):
        prj, dem, pts, lines = load_project(bot_elev=True)
        m = build_section(default_settings(prj, dem, pts, lines, bottom_elev_field="BotElev"), prj)
        by = {h.label: h for h in m.hits}
        self.assertEqual([h.label for h in m.hits], PLOTTED)
        self.assertEqual({n: h.bottom_source for n, h in by.items()},
                         {"B-1": "field", "MW-1": "depth", "TP-1": "field", "B-2": "depth", "MW-2": "field",
                          "CPT-1": "depth", "B-3": "none"})
        self.assertEqual({n: h.total_depth for n, h in by.items()},
                         {"B-1": 30.0, "MW-1": 25.0, "TP-1": 10.0, "B-2": 45.0, "MW-2": 35.0, "CPT-1": 60.0,
                          "B-3": None})
        text = "\n".join(m.warnings)
        self.assertRegex(text, r"TP-1: BotElev [\d.]+ ft used; top minus ExploDepth would give")
        self.assertRegex(text, r"B-2: BotElev [\d.]+ ft is not below the top \([\d.]+ ft\): used top minus ExploDepth")
        with self.assertRaises(SectionError) as cm:
            build_section(default_settings(prj, dem, pts, lines, bottom_elev_field="NoSuch"), prj)
        self.assertIn("bottom elevation field “NoSuch”", str(cm.exception))

    def test_bottom_on_the_rejected_tops_datum(self):
        """MW-2's ExploElev (205.6) is rejected; a BotElev worked out from it (205.6 - 35 = 170.6) must not
        draw a 370-ft line or stretch the sheet: top - depth is used, or without a depth the table bottom
        moves with the top (decision 2)."""
        prj, dem, pts, lines = load_project(bot_elev=True)
        # the standard layout: no fill, so the elevation range shows any stretch
        s = default_settings(prj, dem, pts, lines, bottom_elev_field="BotElev", **STANDARD_LAYOUT)
        good = build_section(s, prj)
        f = next(f for f in pts.getFeatures() if f["ExploName"] == "MW-2")
        bot_i, dep_i = pts.fields().lookupField("BotElev"), pts.fields().lookupField("ExploDepth")
        pts.dataProvider().changeAttributeValues({f.id(): {bot_i: 170.6}})
        m = build_section(s, prj)
        mw2 = next(h for h in m.hits if h.label == "MW-2")
        self.assertEqual((mw2.top_source, mw2.bottom_source, mw2.total_depth), ("dem", "depth", 35.0))
        self.assertAlmostEqual(mw2.bottom, mw2.top - 35.0, delta=1e-9)
        self.assertTrue(any(fl.startswith("BotElev 170.6 ft ignored:") for fl in mw2.flags), mw2.flags)
        self.assertEqual(plan(m, s).z_min, plan(good, s).z_min)          # the sheet is not stretched
        pts.dataProvider().changeAttributeValues({f.id(): {dep_i: None}})
        m = build_section(s, prj)
        mw2 = next(h for h in m.hits if h.label == "MW-2")
        self.assertEqual((mw2.bottom_source, mw2.total_depth), ("shifted", 35.0))
        self.assertAlmostEqual(mw2.bottom, mw2.top - 35.0, delta=1e-6)
        self.assertEqual(plan(m, s).z_min, plan(good, s).z_min)


class BuildTerrain(unittest.TestCase):
    def test_valley(self):
        prj, dem, pts, lines = load_project(kind="terrain", hole=False)
        m = build_section(default_settings(prj, dem, pts, lines), prj)
        self.assertEqual(m.ground.gaps, [])
        self.assertEqual(m.ground.coverage, 1.0)
        i = m.ground.stations.index(m.vertex_stations[1])            # the bend sits at the valley floor
        self.assertAlmostEqual(m.ground.z[i], terrain_z(*LINE[1]), delta=0.01)
        self.assertEqual([h.label for h in m.hits], PLOTTED)
        self.assertFalse(any(h.in_gap for h in m.hits))


class BuildErrors(unittest.TestCase):
    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()

    def _raises(self, settings, *words, prj=None):
        with self.assertRaises(SectionError) as cm:
            build_section(settings, prj or self.prj)
        for w in words:
            self.assertIn(w, str(cm.exception))
        return str(cm.exception)

    def test_no_dem(self):
        self._raises(default_settings(self.prj, self.dem, self.pts, self.lines, dem_layer_id=""), "DEM")
        self._raises(default_settings(self.prj, self.dem, self.pts, self.lines, dem_layer_id=self.pts.id()), "DEM")

    def test_bad_band(self):
        self._raises(default_settings(self.prj, self.dem, self.pts, self.lines, dem_band=3), "band 3")

    def test_points_layer_gone(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines)
        self.prj.removeMapLayer(self.pts.id())
        self._raises(s, "explorations (points) layer is no longer in the project")
        self._raises(default_settings(self.prj, self.dem, self.dem, self.lines), "explorations")   # a raster

    def test_no_line(self):
        self._raises(default_settings(self.prj, self.dem, self.pts, self.lines, line_layer_id="", line_fid=None),
                     "section line")

    def test_geographic_only(self):
        prj = QgsProject.instance()
        prj.clear()
        prj.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        geo = QgsRasterLayer(make_tiny_dem(epsg=4326, origin=(-122.3, 47.1), cell=0.0001), "geo")
        pts = QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory")
        prj.addMapLayers([geo, pts])
        s = Settings(dem_layer_id=geo.id(), points_layer_id=pts.id(),
                     line_wkt="LineString (-122.2999 47.1001, -122.2995 47.1005)", line_crs_authid="EPSG:4326")
        self._raises(s, "geographic", prj=prj)

    def test_line_off_dem(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines, line_layer_id="", line_fid=None,
                             line_wkt=_wkt([(X0 - 5000.0, Y0), (X0 - 1000.0, Y0 + 500.0)]), line_crs_authid=CRS)
        self._raises(s, "does not cross the DEM")

    def test_missing_field(self):
        self._raises(default_settings(self.prj, self.dem, self.pts, self.lines, label_field="Nope"), "Nope")

    def test_far_points_hint_at_the_crs(self):
        """WA South coordinates in a layer labelled WA North land about 115 mi away: the warning says
        how far and points at the layer CRS. No hint when nothing of the chosen types exists."""
        wrong = make_points_layer(name="mislabelled")
        wrong.setCrs(QgsCoordinateReferenceSystem("EPSG:2926"))
        self.prj.addMapLayer(wrong)
        m = build_section(default_settings(self.prj, self.dem, wrong, self.lines), self.prj)
        self.assertEqual(m.hits, [])
        note = next(w for w in m.warnings if w.startswith("No explorations within"))
        self.assertRegex(note, r"The nearest is 1\d\d\.\d mi away: .*check the point layer's CRS")
        m = build_section(default_settings(self.prj, self.dem, wrong, self.lines, types=["Nope"]), self.prj)
        self.assertIn(f"No explorations within {TOLERANCE:g} ft of the line.", m.warnings)


@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class BuildRealData(unittest.TestCase):
    def test_cdf_tiled_match_notes(self):
        """The reviewer's sheet: the CDF wells at 1 in = 100 / 10 ft tiled on Tabloid. MW-40 (4 ft past
        match line 7+00) and MW-37 have TD labels near mid-height; the match notes must not cover them,
        nor any exploration label, on any sheet, and every well's TD label is drawn."""
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from xsections.render import figure as F
        m, s = self._cdf()
        s.h_scale, s.v_scale, s.sheet = 100.0, 10.0, "tabloid"
        p = plan(m, s)
        self.assertTrue(p.fits and len(p.pages) > 1, p.message)
        self.assertEqual(p.warnings, [])
        seen = set()
        for page in p.pages:
            fig = Figure(dpi=100)
            FigureCanvasAgg(fig)
            F.draw_page(fig, m, s, p, page)
            fig.canvas.draw()
            r = fig.canvas.get_renderer()
            ax = fig.axes[0]
            notes = [t for t in ax.texts if t.get_text().startswith("MATCH LINE")]
            self.assertEqual(len(notes), 2 * sum(x is not None for x in (page.match_left, page.match_right)))
            tds = [t for t in ax.texts if t.get_gid() == F.TD_GID]
            names = [t for t in ax.texts if t.get_text() in {h.label for h in m.hits}]
            seen |= {t.get_text() for t in names}
            for note in notes:
                nb = note.get_window_extent(r)
                for t in tds + names:
                    tb = t.get_window_extent(r)
                    clash = min(nb.x1, tb.x1) - max(nb.x0, tb.x0) > 0 and min(nb.y1, tb.y1) - max(nb.y0, tb.y0) > 0
                    self.assertFalse(clash, f"sheet {page.tile_index}: the match note covers {t.get_text()}")
        self.assertEqual(seen, {h.label for h in m.hits})

    def _cdf(self):
        """The CDF wells and LIDAR (read only), a line along the wells, and the built section."""
        prj = QgsProject.instance()
        prj.clear()
        dem = QgsRasterLayer(os.path.join(REALDATA, "cdf_lidar.tif"), "cdf_lidar")
        wells = QgsVectorLayer(os.path.join(REALDATA, "CDF_wells.shp"), "CDF_wells", "ogr")
        self.assertTrue(dem.isValid() and wells.isValid())
        prj.addMapLayers([dem, wells])
        prj.setCrs(dem.crs())
        ct = QgsCoordinateTransform(wells.crs(), dem.crs(), prj)
        xy = [ct.transform(f.geometry().asPoint()) for f in wells.getFeatures()]
        P = np.array([(q.x(), q.y()) for q in xy])
        c = P.mean(axis=0)
        axis = np.linalg.svd(P - c)[2][0]
        along = (P - c) @ axis
        perp = (P - c) @ np.array([-axis[1], axis[0]])
        a, b = c + axis * (along.min() - 300.0), c + axis * (along.max() + 300.0)
        s = Settings(line_wkt=_wkt([tuple(a), tuple(b)]), line_crs_authid=dem.crs().toWkt(),
                     dem_layer_id=dem.id(), points_layer_id=wells.id(), label_field="ExploName",
                     type_field="ExploType", tolerance_ft=float(math.ceil(np.abs(perp).max() + 10.0)),
                     top_field="ExploElev", depth_field="ExploDepth")
        return build_section(s, prj), s

    def test_cdf(self):
        prj = QgsProject.instance()
        prj.clear()
        dem = QgsRasterLayer(os.path.join(REALDATA, "cdf_lidar.tif"), "cdf_lidar")
        wells = QgsVectorLayer(os.path.join(REALDATA, "CDF_wells.shp"), "CDF_wells", "ogr")
        self.assertTrue(dem.isValid() and wells.isValid())
        prj.addMapLayers([dem, wells])
        prj.setCrs(dem.crs())
        ct = QgsCoordinateTransform(wells.crs(), dem.crs(), prj)
        xy = []
        for f in wells.getFeatures():
            p = ct.transform(f.geometry().asPoint())
            xy.append((p.x(), p.y()))
        P = np.array(xy)
        c = P.mean(axis=0)
        axis = np.linalg.svd(P - c)[2][0]                              # main axis of the well cluster
        along = (P - c) @ axis
        perp = (P - c) @ np.array([-axis[1], axis[0]])
        a = c + axis * (along.min() - 300.0)
        b = c + axis * (along.max() + 300.0)
        tol = float(math.ceil(np.abs(perp).max() + 10.0))               # catches every well
        # the CDF layer has a total depth and a (sometimes wrong) top, but no bottom elevation field
        s = Settings(line_wkt=_wkt([tuple(a), tuple(b)]), line_crs_authid=dem.crs().toWkt(),
                     dem_layer_id=dem.id(), points_layer_id=wells.id(), label_field="ExploName",
                     type_field="ExploType", tolerance_ft=tol, top_field="ExploElev", depth_field="ExploDepth")
        m = build_section(s, prj)
        st = np.array(m.ground.stations)
        z = np.array(m.ground.z)
        self.assertTrue(np.all(np.diff(st) > 0))
        self.assertAlmostEqual(m.length, float(along.max() - along.min() + 600.0) * m.dist_factor, delta=0.01)
        self.assertEqual(m.ground.coverage, 1.0)
        self.assertTrue(np.all((z >= 520) & (z <= 700)), (np.nanmin(z), np.nanmax(z)))
        self.assertAlmostEqual(m.ground.step, 1.0, delta=1e-4)
        self.assertEqual(len(m.hits), 8)
        self.assertEqual([h.station for h in m.hits], sorted(h.station for h in m.hits))
        by = {h.label: h for h in m.hits}
        mw35 = by["MW-35R"]
        self.assertEqual(mw35.top_source, "dem")
        self.assertTrue(any("ExploElev 205.6 ft ignored" in f for f in mw35.flags), mw35.flags)
        # 205.6 m is 674.5 ft, next to LIDAR there: the flag says the value looks like meters
        self.assertTrue(any(f.endswith("(205.6 m would match: XSections reads table values as feet)")
                            for f in mw35.flags), mw35.flags)
        self.assertTrue(520 <= mw35.top <= 700)
        self.assertAlmostEqual(mw35.bottom, mw35.top - 15.0, delta=1e-9)
        depths = {f["ExploName"]: f["ExploDepth"] for f in wells.getFeatures()}
        for h in m.hits:
            self.assertTrue(300.0 * m.dist_factor - 0.5 <= h.station <= m.length - 300.0 * m.dist_factor + 0.5)
            if h.label != "MW-35R":
                self.assertEqual(h.top_source, "field", h.label)
            # every bottom is top - depth (no bottom elevation field), and TD is the depth field
            self.assertEqual(h.bottom_source, "depth", h.label)
            self.assertAlmostEqual(h.bottom, h.top - depths[h.label], delta=1e-9, msg=h.label)
            self.assertEqual(h.total_depth, depths[h.label], h.label)
        print(f"\n  real data: length {m.length:.1f} ft, azimuth {m.azimuth:.1f}, tolerance {tol:g} ft, "
              f"{len(st)} ground samples, z {z.min():.1f}-{z.max():.1f} ft")
        print(f"  {'label':7s} {'station':>8s} {'offset':>7s} side dir {'ground':>7s} {'LIDAR@pt':>8s} "
              f"{'top':>7s} src   {'bottom':>7s} src   {'TD':>5s} flags")
        for h in m.hits:
            print(f"  {h.label:7s} {h.station:8.1f} {h.offset:7.1f} {h.side:4s} {h.direction:3s} "
                  f"{h.ground_at_station:7.1f} {h.ground_at_point:8.1f} {h.top:7.1f} {h.top_source:5s} "
                  f"{h.bottom:7.1f} {h.bottom_source:5s} {h.total_depth:5.1f} {'; '.join(h.flags)}")


if __name__ == "__main__":
    unittest.main()
