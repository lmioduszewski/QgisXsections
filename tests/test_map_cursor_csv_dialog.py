"""The hover cursor on the map (MapFeedback.show_cursor / hide_cursor) and the Surfaces CSV… dialog.

The cursor runs on a real QgsMapCanvas (offscreen) with the fixture LINE (EPSG:2927, one bend at 2,500 ft), in the
section CRS and in EPSG:3857, also turned. The dialog runs on the hand-made model of tests/test_hover_csv.py (a DEM
gap, an MF6-like line with a nan vertex, a cells-mode line, two lines named "Model top"), its preview text checked
line by line. The real-data cases (the CDF A-A′ section with MODFLOW 6 surfaces) run only when XSECTIONS_REALDATA
is set.
"""
import math
import os
import shutil
import tempfile
import time
import unittest

from tests.fixtures import CRS, LINE, REALDATA, budget, line_length, point_at, start_app, timing_test

APP = start_app()

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject, QgsSettings)
from qgis.gui import QgsMapCanvas  # noqa: E402
from qgis.PyQt.QtCore import QPointF  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

from tests.test_hover_csv import make_model as csv_model  # noqa: E402
from xsections.core.hover import hover_lines  # noqa: E402
from xsections.core.model import GroundProfile, Hit, SectionModel, Settings  # noqa: E402
from xsections.core.surfaces_csv import unique_names, write_surfaces_csv  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui import surfaces_csv_dialog as D  # noqa: E402
from xsections.ui.map_feedback import CursorMarker, MapFeedback, MapLabel  # noqa: E402

L = line_length()
LINE_GEOM = QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE])
SECTION_CRS_WKT = QgsCoordinateReferenceSystem(CRS).toWkt()     # as a built model carries it


def hit(fid, label, station, offset_left):
    """An exploration `offset_left` ft left of the line (negative: right) at `station`."""
    x, y = point_at(station, offset_left)
    return Hit(fid=fid, label=label, type_value="Boring", x=x, y=y, station=station, offset=abs(offset_left),
               side="L" if offset_left > 0 else "R", direction="N", ground_at_station=500.0, ground_at_point=500.0,
               top=500.0, top_source="dem", bottom=470.0)


def cursor_model(**over):
    """The fixture LINE as a SectionModel: B-1 40 ft left at 300 ft, MW-1 60 ft right at 900 ft, MW-2 50 ft right
    past the bend at 3,200 ft."""
    kw = dict(length=L, vertex_stations=[0.0, 2500.0, L], azimuth=82.0,
              ground=GroundProfile(stations=[0.0, 2500.0, L], z=[500.0, 525.0, 560.0], step=3.0),
              hits=[hit(1, "B-1", 300.0, 40.0), hit(2, "MW-1", 900.0, -60.0), hit(3, "MW-2", 3200.0, -50.0)],
              section_crs_wkt=SECTION_CRS_WKT, line_wkt=LINE_GEOM.asWkt(),
              dem_name="LIDAR", dist_factor=1.0)
    kw.update(over)
    return SectionModel(**kw)


def make_canvas(crs=CRS, rotation=0.0):
    """A shown 800 x 500 canvas in `crs` around the fixture line."""
    canvas = QgsMapCanvas()
    canvas.resize(800, 500)
    canvas.show()
    APP.processEvents()
    dest = QgsCoordinateReferenceSystem(crs)
    canvas.setDestinationCrs(dest)
    box = QgsGeometry.fromRect(LINE_GEOM.boundingBox().buffered(400.0))
    if crs != CRS:
        box.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem(CRS), dest, QgsProject.instance()))
    canvas.setExtent(box.boundingBox())
    if rotation:
        canvas.setRotation(rotation)
    settle(canvas)
    return canvas


def settle(canvas, timeout_s=5.0):
    """Let the canvas finish drawing (it moves its items when a render ends)."""
    canvas.refresh()
    t0 = time.perf_counter()
    APP.processEvents()
    while canvas.isDrawing() and time.perf_counter() - t0 < budget(timeout_s):
        APP.processEvents()
    APP.processEvents()


def to_crs(point, crs):
    """A section CRS point in `crs` (the transform MapFeedback builds: from the model's WKT)."""
    if crs == CRS:
        return QgsPointXY(point)
    ct = QgsCoordinateTransform(QgsCoordinateReferenceSystem.fromWkt(SECTION_CRS_WKT),
                                QgsCoordinateReferenceSystem(crs), QgsProject.instance())
    return ct.transform(point)


def foot(station):
    return LINE_GEOM.interpolate(station).asPoint()


class CanvasCase(unittest.TestCase):
    crs = CRS
    rotation = 0.0

    def setUp(self):
        self.canvas = make_canvas(self.crs, self.rotation)
        self.items_before = len(self.canvas.scene().items())
        self.fb = MapFeedback(self.canvas)
        self.model = cursor_model()
        self.fb.show_model(self.model, Settings())

    def tearDown(self):
        if self.fb.cursor is not None:
            self.fb.remove()
        self.canvas.close()
        self.canvas.deleteLater()
        APP.processEvents()

    def screen(self, point_canvas_crs) -> QPointF:
        p = self.canvas.getCoordinateTransform().transform(point_canvas_crs)
        return QPointF(p.x(), p.y())

    def assertNear(self, a: QgsPointXY, b: QgsPointXY, tol=1e-6, msg=None):
        self.assertLess(math.hypot(a.x() - b.x(), a.y() - b.y()), tol, msg or f"{a} != {b}")

    def label_centre(self) -> QPointF:
        """The distance text's centre, screen px."""
        return self.fb.cursor.mapToScene(self.fb.cursor.text_rect().center())

    def dot(self) -> QPointF:
        return self.fb.cursor.pos()

    def side_of_line(self, station, pt: QPointF) -> float:
        """> 0 when screen point `pt` is left of the line at `station` (looking from A to A′), < 0 right."""
        a = self.screen(to_crs(foot(max(station - 1.0, 0.0)), self.crs))
        b = self.screen(to_crs(foot(min(station + 1.0, L)), self.crs))
        dx, dy = b.x() - a.x(), b.y() - a.y()
        f = self.screen(to_crs(foot(station), self.crs))
        # screen y points down: left of (dx, dy) is (dy, -dx)
        return (pt.x() - f.x()) * dy + (pt.y() - f.y()) * -dx

    def assertSquareToLine(self, station):
        """The distance's text sits square to the line on screen (its centre straight out from the dot)."""
        a = self.screen(to_crs(foot(station - 1.0), self.crs))
        b = self.screen(to_crs(foot(station + 1.0), self.crs))
        d = QPointF(b.x() - a.x(), b.y() - a.y())
        off = self.label_centre() - self.dot()
        cos = (d.x() * off.x() + d.y() * off.y()) / (math.hypot(d.x(), d.y()) * math.hypot(off.x(), off.y()))
        self.assertLess(abs(cos), 1e-5)


# ----------------------------------------------------------------------------- the cursor on the map
class CursorTest(CanvasCase):
    def test_on_the_line_and_following_the_bend(self):
        for st in (0.0, 300.0, 1000.0, 2500.0, 3000.0, L):
            self.fb.show_cursor(st)
            c = self.fb.cursor
            self.assertTrue(c.isVisible(), st)
            self.assertTrue(self.fb.cursor_shown())
            self.assertNear(c.point, foot(st), msg=f"station {st}")
            self.assertAlmostEqual(c.pos().x(), self.screen(c.point).x(), places=6)
            self.assertAlmostEqual(c.pos().y(), self.screen(c.point).y(), places=6)
        self.fb.show_cursor(1240.4)
        self.assertEqual(self.fb.cursor.text, "1,240 ft")
        self.fb.show_model(self.model, Settings(distance_labels="station"))
        self.fb.show_cursor(1240.4)
        self.assertEqual(self.fb.cursor.text, "12+40")

    def test_feet_per_unit(self):
        # a section CRS in units of 2 ft: the dot goes to station / 2 along the line
        self.fb.show_model(cursor_model(length=2.0 * L, vertex_stations=[0.0, 5000.0, 2.0 * L], dist_factor=2.0),
                           Settings())
        self.fb.show_cursor(3000.0)
        self.assertNear(self.fb.cursor.point, foot(1500.0))
        self.assertEqual(self.fb.cursor.text, "3,000 ft")
        self.fb.show_cursor(2.0 * L + 1.0)
        self.assertFalse(self.fb.cursor.isVisible())

    def test_hidden_past_the_ends(self):
        for st in (-0.5, -1e-3, L + 0.01, L + 50.0, math.nan, math.inf, None):
            self.fb.show_cursor(1000.0, hit=self.model.hits[1], map_point=QgsPointXY(*point_at(1000.0, 30.0)))
            self.fb.show_cursor(st)
            self.assertFalse(self.fb.cursor.isVisible(), st)
            self.assertFalse(self.fb.cursor_shown())
            for band in (self.fb.ring, self.fb.projection, self.fb.connector):
                self.assertEqual(band.numberOfVertices(), 0, st)
        # the ends themselves are on the line (and the last digits of the length are forgiven)
        for st in (0.0, L, L * (1 + 1e-12)):
            self.fb.show_cursor(st)
            self.assertTrue(self.fb.cursor.isVisible(), st)
        self.assertNear(self.fb.cursor.point, QgsPointXY(*LINE[-1]))

    def test_ring_and_projection_for_an_exploration(self):
        mw1 = self.model.hits[1]
        self.fb.show_cursor(mw1.station, hit=mw1)
        self.assertEqual(self.fb.ring.numberOfVertices(), 1)
        self.assertNear(self.fb.ring.asGeometry().vertexAt(0), QgsPointXY(mw1.x, mw1.y))
        line = self.fb.projection.asGeometry().asPolyline()
        self.assertEqual(len(line), 2)
        self.assertNear(line[0], QgsPointXY(mw1.x, mw1.y))
        self.assertNear(line[1], foot(mw1.station))
        self.assertNear(line[1], self.fb.cursor.point)
        self.assertAlmostEqual(math.hypot(line[0].x() - line[1].x(), line[0].y() - line[1].y()), 60.0, places=6)
        # another exploration moves them; none takes them away
        mw2 = self.model.hits[2]                       # past the bend
        self.fb.show_cursor(mw2.station, hit=mw2)
        self.assertNear(self.fb.ring.asGeometry().vertexAt(0), QgsPointXY(mw2.x, mw2.y))
        self.assertNear(self.fb.projection.asGeometry().asPolyline()[1], foot(3200.0))
        self.fb.show_cursor(1500.0)
        self.assertEqual(self.fb.ring.numberOfVertices(), 0)
        self.assertEqual(self.fb.projection.numberOfVertices(), 0)
        # the same exploration again after hide_cursor is drawn again
        self.fb.show_cursor(mw2.station, hit=mw2)
        self.fb.hide_cursor()
        self.fb.show_cursor(mw2.station, hit=mw2)
        self.assertEqual(self.fb.ring.numberOfVertices(), 1)
        self.assertEqual(self.fb.projection.numberOfVertices(), 2)

    def test_connector_from_the_map_cursor(self):
        p = QgsPointXY(*point_at(1800.0, -45.0))
        self.fb.show_cursor(1800.0, map_point=p)
        line = self.fb.connector.asGeometry().asPolyline()
        self.assertEqual(len(line), 2)
        self.assertNear(line[0], p)
        self.assertNear(line[1], foot(1800.0))
        self.assertEqual(self.fb.ring.numberOfVertices(), 0)
        self.fb.show_cursor(1800.0)
        self.assertEqual(self.fb.connector.numberOfVertices(), 0)

    def test_label_side(self):
        b1, mw1, mw2 = self.model.hits
        # nothing to keep clear of: the left (north of the first leg, so above it)
        self.fb.show_cursor(1000.0)
        self.assertLess(self.label_centre().y(), self.dot().y())
        self.assertGreater(self.side_of_line(1000.0, self.label_centre()), 0)
        # away from the exploration
        self.fb.show_cursor(b1.station, hit=b1)        # B-1 is left: the distance goes right (below)
        self.assertGreater(self.label_centre().y(), self.dot().y())
        self.fb.show_cursor(mw1.station, hit=mw1)      # MW-1 is right: left (above)
        self.assertLess(self.label_centre().y(), self.dot().y())
        # away from the map cursor
        self.fb.show_cursor(1000.0, map_point=QgsPointXY(*point_at(1000.0, 30.0)))
        self.assertLess(self.side_of_line(1000.0, self.label_centre()), 0)
        self.fb.show_cursor(1000.0, map_point=QgsPointXY(*point_at(1000.0, -30.0)))
        self.assertGreater(self.side_of_line(1000.0, self.label_centre()), 0)
        # past the bend: square to the leg on screen, away from MW-2 (right)
        self.fb.show_cursor(mw2.station, hit=mw2)
        self.assertGreater(self.side_of_line(mw2.station, self.label_centre()), 0)
        self.assertSquareToLine(mw2.station)

    def test_text_clear_of_the_dot(self):
        c = self.fb.cursor
        for st, h in ((1000.0, None), (300.0, self.model.hits[0]), (3200.0, self.model.hits[2]),
                      (4000.0, None)):
            self.fb.show_cursor(st, hit=h)
            r = c.text_rect()
            nx = min(max(0.0, r.left()), r.right())
            ny = min(max(0.0, r.top()), r.bottom())
            self.assertGreaterEqual(math.hypot(nx, ny), CursorMarker.CLEAR - 1e-6, st)
            self.assertTrue(c.boundingRect().contains(r), st)

    def test_geometry_changes_reach_the_scene(self):
        # (prepareGeometryChange: the scene's index must know the new text box, or the canvas keeps stale paint)
        scene = self.canvas.scene()
        c = self.fb.cursor
        for st, h in ((1.0, None), (4000.0, self.model.hits[2]), (2500.0, None), (300.0, self.model.hits[0])):
            self.fb.show_cursor(st, hit=h)
            box = c.mapRectToScene(c.text_rect())
            self.assertIn(c, scene.items(box), st)
            self.assertTrue(c.sceneBoundingRect().contains(box), st)

    def test_set_visible(self):
        fb = self.fb
        fb.show_cursor(900.0, hit=self.model.hits[1], map_point=QgsPointXY(*point_at(900.0, 20.0)))
        items = [fb.cursor, fb.ring, fb.projection, fb.connector]
        self.assertTrue(all(i.isVisible() for i in items))
        fb.set_visible(False)                          # the panel closed
        self.assertFalse(any(i.isVisible() for i in items))
        fb.show_cursor(1000.0, hit=self.model.hits[1])  # moves on, still hidden
        self.assertFalse(any(i.isVisible() for i in items))
        self.assertNear(fb.cursor.point, foot(1000.0))
        fb.set_visible(True)
        self.assertTrue(fb.cursor.isVisible())
        fb.hide_cursor()
        fb.set_visible(False)
        fb.set_visible(True)
        self.assertFalse(fb.cursor.isVisible())       # no cursor to show

    def test_a_new_model_or_clear_hides_it(self):
        fb = self.fb
        fb.show_cursor(900.0, hit=self.model.hits[1])
        fb.show_model(cursor_model(), Settings())
        self.assertFalse(fb.cursor.isVisible())
        self.assertFalse(fb.cursor_shown())
        self.assertEqual(fb.ring.numberOfVertices(), 0)
        fb.show_cursor(900.0)
        self.assertTrue(fb.cursor.isVisible())
        fb.clear()                                     # the section failed
        self.assertFalse(fb.cursor.isVisible())
        fb.show_cursor(900.0)                          # no section: nothing to show
        self.assertFalse(fb.cursor.isVisible())
        fb.show_line(LINE_GEOM, QgsCoordinateReferenceSystem(CRS), "A", "A'")
        fb.show_cursor(900.0)
        self.assertFalse(fb.cursor.isVisible())

    @timing_test
    def test_no_leftovers(self):
        fb = self.fb
        self.assertIsInstance(fb.cursor, MapLabel)     # (tests/test_e2e and test_ui count MapLabel items)
        scene = self.canvas.scene()
        fb.show_cursor(100.0)
        count = len(scene.items())
        t0 = time.perf_counter()
        for k in range(400):
            st = 11.3 * k
            fb.show_cursor(st, hit=self.model.hits[k % 3] if k % 4 == 0 else None,
                           map_point=QgsPointXY(*point_at(min(st, L), 25.0)) if k % 4 == 2 else None)
        self.assertLess(time.perf_counter() - t0, budget(5.0))
        self.assertEqual(len(scene.items()), count)
        bands, labels = len(fb._bands()), len(fb.labels)
        self.assertEqual((bands, labels), (7, 2))
        self.assertEqual(fb.item_count(), bands + labels + 1)
        items = fb._bands() + [fb.cursor]
        fb.remove()
        APP.processEvents()
        self.assertEqual(len(scene.items()), self.items_before)
        self.assertEqual(fb.item_count(), 0)
        for item in items:
            self.assertIsNone(item.scene())
        fb.show_cursor(100.0)                          # after unload: nothing happens
        fb.hide_cursor()
        fb.set_visible(True)


class CursorOtherCrsTest(CanvasCase):
    """The canvas in Web Mercator: the dot, ring and lines land where the section CRS points transform to."""
    crs = "EPSG:3857"

    def test_positions(self):
        mw2 = self.model.hits[2]
        p = QgsPointXY(*point_at(1500.0, 70.0))
        for st, h, mp in ((1234.5, None, None), (mw2.station, mw2, None), (1500.0, None, p)):
            self.fb.show_cursor(st, hit=h, map_point=mp)
            self.assertNear(self.fb.cursor.point, to_crs(foot(st), self.crs), tol=1e-4, msg=str(st))
            self.assertAlmostEqual(self.fb.cursor.pos().x(), self.screen(self.fb.cursor.point).x(), places=4)
        self.fb.show_cursor(mw2.station, hit=mw2)
        self.assertNear(self.fb.ring.asGeometry().vertexAt(0), to_crs(QgsPointXY(mw2.x, mw2.y), self.crs), 1e-4)
        self.assertNear(self.fb.projection.asGeometry().asPolyline()[1], to_crs(foot(3200.0), self.crs), 1e-4)
        self.assertGreater(self.side_of_line(mw2.station, self.label_centre()), 0)
        self.fb.show_cursor(1500.0, map_point=p)
        self.assertNear(self.fb.connector.asGeometry().asPolyline()[0], to_crs(p, self.crs), 1e-4)
        self.assertLess(self.side_of_line(1500.0, self.label_centre()), 0)

    def test_canvas_crs_change_keeps_the_cursor(self):
        mw1 = self.model.hits[1]
        self.fb.show_cursor(mw1.station, hit=mw1)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem(CRS))
        APP.processEvents()
        self.assertTrue(self.fb.cursor.isVisible())
        self.assertNear(self.fb.cursor.point, foot(mw1.station), tol=1e-6)
        self.assertNear(self.fb.ring.asGeometry().vertexAt(0), QgsPointXY(mw1.x, mw1.y), tol=1e-6)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        APP.processEvents()
        self.assertNear(self.fb.cursor.point, to_crs(foot(mw1.station), "EPSG:4326"), tol=1e-8)
        self.fb.hide_cursor()
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem(CRS))
        self.assertFalse(self.fb.cursor.isVisible())


class CursorTurnedCanvasTest(CanvasCase):
    """A turned map: the distance still goes square to the line, on the side it should."""
    rotation = 70.0

    def test_label_square_to_the_line(self):
        for st, h in ((1000.0, None), (3200.0, self.model.hits[2]), (300.0, self.model.hits[0])):
            self.fb.show_cursor(st, hit=h)
            self.assertSquareToLine(st)
            side = self.side_of_line(st, self.label_centre())
            self.assertGreater(side, 0) if h is None or h.side == "R" else self.assertLess(side, 0)
        self.fb.show_cursor(1000.0)
        self.canvas.setRotation(-20.0)                 # turned while shown: the text follows
        settle(self.canvas)
        self.assertSquareToLine(1000.0)
        self.assertGreater(self.side_of_line(1000.0, self.label_centre()), 0)


# ----------------------------------------------------------------------------- the dialog
KEYS = (D.LAYOUT_KEY, D.STEP_KEY, D.MAP_XY_KEY)

LONG_PREVIEW = """surface,part,distance_ft,elevation_ft
Ground (lidar),1,0.0,100.0
Ground (lidar),1,50.0,100.5
Ground (lidar),1,100.0,101.0
…
Ground (lidar),,400.0,  ← no data: blank elevation
… 18 more Ground (lidar) rows
Model top,1,20.0,104.0
Model top,1,220.0,106.0
Model top,1,420.0,108.0
…
Model top,,520.0,  ← no data: blank elevation
… 3 more Model top rows
Water table,1,0.0,95.0
Water table,1,250.0,95.0
Water table,1,250.0,97.0
…
Water table,,500.0,  ← no data: blank elevation
… 4 more Water table rows
Model top (2),1,0.0,90.0
Model top (2),1,1000.0,92.0"""

WIDE_PREVIEW = """distance_ft,Ground (lidar),Water table,Model top (2)
0.0,100.0,95.0,90.0
10.0,100.1,95.0,90.02
20.0,100.2,95.0,90.04
30.0,100.3,95.0,90.06
…
360.0,,97.0,90.72  ← no data: blank
… 95 more rows in all
1000.0,110.0,99.0,92.0"""

WIDE_SHORT_PREVIEW = """distance_ft,Ground (lidar),Model top,Water table,Model top (2)
0.0,100.0,,95.0,90.0  ← no data: blank
500.0,105.0,,,91.0
610.0,106.1,,,91.22
1000.0,110.0,,99.0,92.0"""


class UserValues:
    """Keeps the remembered dialog choices of the (throwaway) test profile as they were."""

    def setUp(self):
        s = QgsSettings()
        self._saved = {k: s.value(settings_store.USER_PREFIX + k) if s.contains(settings_store.USER_PREFIX + k)
                       else None for k in KEYS}
        for k in KEYS:
            s.remove(settings_store.USER_PREFIX + k)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        s = QgsSettings()
        for k, v in self._saved.items():
            if v is None:
                s.remove(settings_store.USER_PREFIX + k)
            else:
                s.setValue(settings_store.USER_PREFIX + k, v)


class DialogTest(UserValues, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.model = csv_model()
        self.dlg = D.SurfacesCsvDialog(self.model)

    def tearDown(self):
        self.dlg.deleteLater()
        APP.processEvents()
        super().tearDown()

    def test_defaults(self):
        d = self.dlg
        self.assertEqual(d.windowTitle(), "Export surfaces to CSV")
        self.assertEqual(d.options(), dict(layout="long", step_ft=10.0, include=[0, 1, 2, 3], map_xy=False))
        self.assertEqual([b.text() for b in d.boxes], ["Ground (lidar)", "Model top", "Water table", "Model top (2)"])
        self.assertTrue(all(b.isChecked() for b in d.boxes))
        self.assertTrue(all(not b.icon().isNull() for b in d.boxes))
        counts = [lab.text() for lab in d.list_area.widget().findChildren(D.QLabel)]
        self.assertEqual(counts, ["22 points", "7 points", "8 points", "2 points"])
        self.assertEqual([d.layout_seg.itemText(i) for i in range(2)],
                         ["One row per point, as drawn", "One column per surface"])
        self.assertEqual((d.step.minimum(), d.step.maximum(), d.step.value()), (1, 500, 10))
        self.assertTrue(d.step_row.isHidden())
        self.assertTrue(d.help.text().startswith("Exactly the points drawn"))
        self.assertEqual(d.map_xy.text(), "Also map coordinates (map_x, map_y)")
        self.assertTrue(d.map_xy.isEnabled())
        self.assertEqual(d.save_button.text(), "Save CSV…")
        self.assertTrue(d.save_button.isEnabled())
        self.assertEqual(d.summary.text(), "39 rows · about 1 KB")

    def test_options_follow_the_controls(self):
        d = self.dlg
        d.boxes[1].setChecked(False)
        self.assertEqual(d.options()["include"], [0, 2, 3])
        d.layout_seg.setCurrentIndex(1)
        self.assertEqual(d.options()["layout"], "wide")
        self.assertFalse(d.step_row.isHidden())
        d.step.setValue(25)
        self.assertEqual(d.options()["step_ft"], 25.0)
        self.assertIn("every 25 ft and at each bend", d.help.text())
        self.assertIn("(every 25 ft)", d.summary.text())
        d.map_xy.setChecked(True)
        self.assertTrue(d.options()["map_xy"])
        d.step.setValue(0)                              # a spin box: 1 to 500 ft
        self.assertEqual(d.options()["step_ft"], 1.0)
        d.step.setValue(9999)
        self.assertEqual(d.options()["step_ft"], 500.0)

    def test_long_preview(self):
        self.assertEqual(self.dlg.preview_text(), LONG_PREVIEW)
        self.assertEqual(self.dlg.preview.toPlainText(), LONG_PREVIEW)

    def test_wide_preview_with_a_gap_further_down(self):
        d = self.dlg
        d.layout_seg.setCurrentIndex(1)
        d.boxes[1].setChecked(False)                   # (Model top has no value at 0 ft)
        self.assertEqual(d.preview_text(), WIDE_PREVIEW)
        self.assertEqual(d.summary.text(), "101 rows (every 10 ft) · about 2 KB")

    def test_short_wide_file_shown_whole(self):
        d = self.dlg
        d.layout_seg.setCurrentIndex(1)
        d.step.setValue(500)                           # 0, 500, the bend at 610 and the end
        self.assertEqual(d.preview_text(), WIDE_SHORT_PREVIEW)
        self.assertEqual(d.summary.text(), "4 rows (every 500 ft) · about 1 KB")

    def test_map_coordinates(self):
        d = self.dlg
        d.map_xy.setChecked(True)
        lines = d.preview_text().splitlines()
        self.assertEqual(lines[0], "surface,part,distance_ft,elevation_ft,map_x,map_y")
        self.assertEqual(lines[1], "Ground (lidar),1,0.0,100.0,1000.0,2000.0")
        d.layout_seg.setCurrentIndex(1)
        lines = d.preview_text().splitlines()
        self.assertEqual(lines[0], "distance_ft,Ground (lidar),Model top,Water table,Model top (2),map_x,map_y")
        self.assertEqual(lines[-1], "1000.0,110.0,,99.0,92.0,1305.0,2195.0")
        self.assertIn("section's CRS", d.map_xy.toolTip())

    def test_nothing_ticked(self):
        d = self.dlg
        for b in d.boxes:
            b.setChecked(False)
        self.assertEqual(d.preview_text(), "surface,part,distance_ft,elevation_ft\n(no surfaces ticked)")
        self.assertEqual(d.summary.text(), "Tick at least one surface")
        self.assertFalse(d.save_button.isEnabled())
        d.layout_seg.setCurrentIndex(1)
        self.assertEqual(d.preview_text(), "distance_ft\n(no surfaces ticked)")
        d.accept()                                     # (Enter with nothing ticked): stays open, remembers nothing
        self.assertEqual(d.result(), 0)
        self.assertEqual(settings_store.user_value(D.LAYOUT_KEY, ""), "")
        d.boxes[2].setChecked(True)
        self.assertTrue(d.save_button.isEnabled())
        self.assertEqual(d.options()["include"], [2])

    def test_preview_and_size_match_the_file(self):
        d = self.dlg
        tmp = tempfile.mkdtemp(prefix="xsec_csvdlg_")
        self.addCleanup(shutil.rmtree, tmp, True)
        for layout, step, include, xy in (("long", 10, [0, 1, 2, 3], False), ("long", 10, [1, 3], True),
                                          ("wide", 10, [0, 2], False), ("wide", 7, [0, 1, 2, 3], True)):
            d.layout_seg.setCurrentIndex(d.layout_seg.findData(layout))
            d.step.setValue(step)
            d.map_xy.setChecked(xy)
            for i, b in enumerate(d.boxes):
                b.setChecked(i in include)
            o = d.options()
            path = os.path.join(tmp, f"{layout}_{step}_{xy}.csv")
            n = write_surfaces_csv(path, self.model, **o)
            header, rows = d.rows()
            self.assertEqual(len(rows), n)
            self.assertEqual(D.file_size(header, rows), os.path.getsize(path))
            self.assertTrue(d.summary.text().startswith(f"{n:,} rows"))
            with open(path, encoding="utf-8-sig", newline="") as fh:
                text = fh.read().split("\r\n")
            shown = [ln.split("  ← ")[0] for ln in d.preview_text().splitlines() if not ln.startswith("…")]
            for line in shown:                         # every row shown is a row of the file
                self.assertIn(line, text)

    def test_remembered(self):
        d = self.dlg
        d.layout_seg.setCurrentIndex(1)
        d.step.setValue(25)
        d.map_xy.setChecked(True)
        d.accept()
        self.assertEqual(d.result(), 1)
        self.assertEqual([settings_store.user_value(k) for k in KEYS], ["wide", "25", "1"])
        d2 = D.SurfacesCsvDialog(self.model)
        self.addCleanup(d2.deleteLater)
        self.assertEqual(d2.options(), dict(layout="wide", step_ft=25.0, include=[0, 1, 2, 3], map_xy=True))
        self.assertFalse(d2.step_row.isHidden())
        d2.layout_seg.setCurrentIndex(0)               # Cancel forgets
        d2.reject()
        self.assertEqual(settings_store.user_value(D.LAYOUT_KEY), "wide")
        # map coordinates stay off for a model without a line to read them from
        d3 = D.SurfacesCsvDialog(csv_model(line_wkt=""))
        self.addCleanup(d3.deleteLater)
        self.assertFalse(d3.map_xy.isEnabled())
        self.assertFalse(d3.options()["map_xy"])

    def test_unreadable_remembered_values(self):
        for layout, step, xy, want in (("weird", "abc", "yes", ("long", 10, False)),
                                       ("wide", "0", "1", ("wide", 10, True)),
                                       ("long", "501", "0", ("long", 10, False)),
                                       ("wide", "12.0", "", ("wide", 12, False))):
            settings_store.set_user_value(D.LAYOUT_KEY, layout)
            settings_store.set_user_value(D.STEP_KEY, step)
            settings_store.set_user_value(D.MAP_XY_KEY, xy)
            self.assertEqual(D.remembered(), want)

    def test_swatch_on_a_white_chip(self):
        img = D.swatch_pixmap("#ff0000", "solid", 1.0).toImage()
        w, h = img.width(), img.height()
        self.assertEqual((w, h), (D.SWATCH.width(), D.SWATCH.height()))
        self.assertEqual(img.pixelColor(2, 2), QColor("#ffffff"))
        self.assertLess(img.pixelColor(0, 0).alpha(), 255)        # rounded corner
        mid = img.pixelColor(w // 2, h // 2)
        self.assertGreater(mid.red(), 200)
        self.assertLess(mid.green(), 120)
        dots = D.swatch_pixmap("#000000", "dot", 1.0).toImage()
        along = [dots.pixelColor(x, h // 2).lightness() for x in range(5, w - 5)]
        self.assertTrue(any(v > 200 for v in along) and any(v < 120 for v in along))   # dots with white between
        hi = D.swatch_pixmap("#000000", "dash", 2.0, dpr=2.0)
        self.assertEqual((hi.width(), hi.height()), (2 * w, 2 * h))
        self.assertEqual(hi.devicePixelRatio(), 2.0)


class PreviewHelpersTest(unittest.TestCase):
    def test_csv_line_quotes_like_the_file(self):
        self.assertEqual(D.csv_line(["Head, layer 1", 1, 2.5, ""]), '"Head, layer 1",1,2.5,')
        self.assertEqual(D.csv_line(['Say "hi"', 0.0]), '"Say ""hi""",0.0')

    def test_long_gap_in_the_first_rows_is_not_repeated(self):
        rows = [["A", "", 0.0, ""], ["A", 1, 1.0, 5.0], ["A", 1, 2.0, 6.0], ["A", 1, 3.0, 7.0], ["A", 1, 4.0, 8.0]]
        out = D.preview_plain(D.preview_lines("long", ["surface", "part", "distance_ft", "elevation_ft"], rows, 1))
        self.assertEqual(out.splitlines(), ["surface,part,distance_ft,elevation_ft", "A,,0.0,", "A,1,1.0,5.0",
                                            "A,1,2.0,6.0", "… 2 more A rows"])

    def test_wide_gap_on_the_last_row_is_shown_once(self):
        rows = [[float(k), 1.0] for k in range(9)] + [[9.0, ""]]
        lines = D.preview_plain(D.preview_lines("wide", ["distance_ft", "A"], rows, 1)).splitlines()
        self.assertEqual(lines, ["distance_ft,A", "0.0,1.0", "1.0,1.0", "2.0,1.0", "3.0,1.0",
                                 "… 5 more rows in all", "9.0,  ← no data: blank"])

    def test_html_is_escaped_and_muted(self):
        lines = [("a<b,&", False, ""), ("…", True, ""), ("x,", False, "← no data: blank")]
        out = D.preview_html(lines, "#5a6b74")
        self.assertIn("a&lt;b,&amp;", out)
        self.assertEqual(out.count('color:#5a6b74; font-style:italic'), 2)

    def test_summary(self):
        self.assertEqual(D.summary_text("long", 1713, 52 * 1024, 10, 4), "1,713 rows · about 52 KB")
        self.assertEqual(D.summary_text("wide", 155, 300, 10.0, 4), "155 rows (every 10 ft) · about 1 KB")
        self.assertEqual(D.summary_text("long", 1, 1600, 10, 1), "1 row · about 2 KB")
        self.assertEqual(D.summary_text("wide", 155, 300, 10, 0), "Tick at least one surface")


# ----------------------------------------------------------------------------- the real CDF section
@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the folder of the real data")
class RealDataTest(UserValues, unittest.TestCase):
    """The CDF A-A′ section (section CRS from the DEM's WKT, no authid) with the CDF_Mounding MODFLOW 6 surfaces."""

    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsRasterLayer, QgsVectorLayer
        from tests.test_e2e import copy_realdata, folder_state, line_through_points
        from xsections.core.build import build_section
        from xsections.core.model import SURFACE_DEFAULTS

        cls.folder_state = staticmethod(folder_state)
        cls.state = folder_state(REALDATA)
        cls.tmp = tempfile.mkdtemp(prefix="xsec_cursor_real_")
        dem_path, wells_path = copy_realdata(cls.tmp)
        cdf = os.path.join(REALDATA, "mf6", "CDF_Mounding")
        grb, hds = os.path.join(cdf, "CDF_Mounding.disu.grb"), os.path.join(cdf, "CDF_Mounding.hds")

        def mf6(var, **kw):
            return dict(SURFACE_DEFAULTS, source="mf6", mf6_path=grb, mf6_head_path=hds, mf6_var=var,
                        z_units="ftUS", **kw)

        prj = QgsProject.instance()
        prj.clear()
        dem = QgsRasterLayer(dem_path, "cdf_lidar")
        wells = QgsVectorLayer(wells_path, "CDF_wells", "ogr")
        prj.addMapLayers([dem, wells])
        prj.setCrs(dem.crs())
        geom, tol = line_through_points(wells, dem.crs(), prj)
        cls.settings = Settings(
            line_wkt=geom.asWkt(), line_crs_authid=dem.crs().toWkt(), dem_layer_id=dem.id(),
            points_layer_id=wells.id(), label_field="ExploName", type_field="ExploType", top_field="ExploElev",
            depth_field="ExploDepth", tolerance_ft=tol,
            surfaces=[mf6("top", color="#555555", style="dot"), mf6("wt", color="#1f6fb2", style="dash"),
                      mf6("top", color="#999999", mode="cells")])
        cls.model = build_section(cls.settings, prj)
        prj.clear()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def tearDown(self):
        super().tearDown()
        self.assertEqual(self.folder_state(REALDATA), self.state, "nothing written next to the real data")

    @timing_test
    def test_dialog(self):
        m = self.model
        t0 = time.perf_counter()
        d = D.SurfacesCsvDialog(m)
        self.addCleanup(d.deleteLater)
        self.assertLess(time.perf_counter() - t0, budget(3.0))
        names = [b.text() for b in d.boxes]
        self.assertEqual(names, unique_names(ln.name for ln in hover_lines(m)))
        self.assertEqual(names[0], "Ground (cdf_lidar)")
        self.assertEqual(len(set(names)), 4)
        crs = QgsCoordinateReferenceSystem.fromWkt(m.section_crs_wkt)
        self.assertEqual(crs.authid(), "")
        self.assertIn(crs.userFriendlyIdentifier(), d.map_xy.toolTip())
        text = d.preview_text()
        gz = m.ground.z
        shown = 4 if any(math.isnan(z) for z in gz[3:]) else 3
        self.assertIn(f"… {len(gz) - shown:,} more Ground (cdf_lidar) rows", text)
        tmp = tempfile.mkdtemp(prefix="xsec_csvdlg_real_")
        self.addCleanup(shutil.rmtree, tmp, True)
        for layout, step in (("long", 10), ("wide", 10), ("wide", 1)):
            d.layout_seg.setCurrentIndex(d.layout_seg.findData(layout))
            d.map_xy.setChecked(True)
            t0 = time.perf_counter()
            d.step.setValue(step)
            d.refresh()
            self.assertLess(time.perf_counter() - t0, budget(3.0))
            path = os.path.join(tmp, f"{layout}{step}.csv")
            n = write_surfaces_csv(path, m, **d.options())
            self.assertTrue(d.summary.text().startswith(f"{n:,} rows"), d.summary.text())
            header, rows = d.rows()
            self.assertEqual(D.file_size(header, rows), os.path.getsize(path))

    def test_cursor(self):
        m = self.model
        crs = QgsCoordinateReferenceSystem.fromWkt(m.section_crs_wkt)
        line = QgsGeometry.fromWkt(m.line_wkt)
        canvas = QgsMapCanvas()
        canvas.resize(900, 500)
        canvas.show()
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        ct = QgsCoordinateTransform(crs, canvas.mapSettings().destinationCrs(), QgsProject.instance())
        box = QgsGeometry.fromRect(line.boundingBox().buffered(300.0))
        box.transform(ct)
        canvas.setExtent(box.boundingBox())
        APP.processEvents()
        fb = MapFeedback(canvas)

        def cleanup():
            fb.remove()
            canvas.close()
            canvas.deleteLater()
            APP.processEvents()
        self.addCleanup(cleanup)
        fb.show_model(m, self.settings)
        f = m.dist_factor
        self.assertTrue(m.hits)
        for h in m.hits:
            fb.show_cursor(h.station, hit=h)
            want = ct.transform(line.interpolate(h.station / f).asPoint())
            got = fb.cursor.point
            self.assertLess(math.hypot(got.x() - want.x(), got.y() - want.y()), 1e-3, h.label)
            ring = fb.ring.asGeometry().vertexAt(0)
            at = ct.transform(QgsPointXY(h.x, h.y))
            self.assertLess(math.hypot(ring.x() - at.x(), ring.y() - at.y()), 1e-3, h.label)
            # the distance goes on the other side of the line from the exploration (on screen)
            if h.offset > 1.0:
                px = canvas.getCoordinateTransform().transform(at)
                dot, lab = fb.cursor.pos(), fb.cursor.mapToScene(fb.cursor.text_rect().center())
                a = canvas.getCoordinateTransform().transform(
                    ct.transform(line.interpolate(max(h.station / f - 1.0, 0.0)).asPoint()))
                b = canvas.getCoordinateTransform().transform(
                    ct.transform(line.interpolate(min(h.station / f + 1.0, line.length())).asPoint()))
                dx, dy = b.x() - a.x(), b.y() - a.y()
                s_hit = (px.x() - dot.x()) * dy - (px.y() - dot.y()) * dx
                s_lab = (lab.x() - dot.x()) * dy - (lab.y() - dot.y()) * dx
                self.assertLess(s_hit * s_lab, 0, h.label)
        fb.show_cursor(m.length + 1.0)
        self.assertFalse(fb.cursor.isVisible())


if __name__ == "__main__":
    unittest.main()
