"""The dock's hover wiring (0.3.1): the preview's hover moves the marker on the map, the map cursor near the line
moves the preview's guide, and the preview's Surfaces CSV… button writes the file.

A real PreviewWidget and a real (offscreen) map canvas, the fixture project of tests/fixtures.py (the bent LINE in
EPSG:2927, seven explorations within the 150 ft tolerance) built by the real pipeline, plus a raster surface on the
same DEM so the CSV has two lines.
"""
import csv
import math
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from tests.fixtures import (CRS, LINE, TOLERANCE, _explo_xy, budget, default_settings, load_project, point_at,
                            start_app)

APP = start_app()

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject)
from qgis.gui import QgsRubberBand  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from qgis.PyQt.QtGui import QMouseEvent  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QDialog  # noqa: E402

from tests.test_preview_tools import (data_at, leave, move, restore_user_values, save_user_values,  # noqa: E402
                                      settle, vp_of)
from tests.test_ui import make_iface, show_canvas  # noqa: E402
from xsections.core.hover import distance_text, hover_lines  # noqa: E402
from xsections.core.model import SURFACE_DEFAULTS, SectionError  # noqa: E402
from xsections.core.surfaces_csv import LONG_COLUMNS, MAP_COLUMNS, unique_names, wide_stations  # noqa: E402
from xsections.ui import dock as DK  # noqa: E402
from xsections.ui import preview as P  # noqa: E402
from xsections.ui import readout as R  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui import surfaces_csv_dialog as D  # noqa: E402
from xsections.ui.dock import LineLocator, XSectionsDock  # noqa: E402
from xsections.ui.map_feedback import MapLabel  # noqa: E402
from xsections.ui.preview import PreviewWidget  # noqa: E402
from xsections.ui.surfaces_csv_dialog import SurfacesCsvDialog  # noqa: E402

LINE_GEOM = QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE])
USER_KEYS = (P.STRIP_KEY, P.POPUP_KEY, D.LAYOUT_KEY, D.STEP_KEY, D.MAP_XY_KEY, "last_export_dir")
NEAR = DK.MAP_HOVER_TOLERANCES * TOLERANCE          # 375 ft: the map hover's reach with explorations


def our_items(canvas):
    return [i for i in canvas.scene().items() if isinstance(i, (QgsRubberBand, MapLabel))]


def pt(station, offset_left=0.0):
    """The fixture map point `offset_left` ft left (negative: right) of LINE at `station` (CRS units)."""
    return QgsPointXY(*point_at(station, offset_left))


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.reader(fh))


class WiringCase(unittest.TestCase):
    def setUp(self):
        self._user = save_user_values(USER_KEYS)
        for k in (P.STRIP_KEY, P.POPUP_KEY):
            settings_store.set_user_value(k, "1")
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.iface = make_iface()
        self.canvas = self.iface.mapCanvas()
        show_canvas(self.canvas, [self.lines])
        self.items_before = len(our_items(self.canvas))
        self.receivers_before = self.canvas.receivers(self.canvas.xyCoordinates)
        self.crs_receivers_before = self.canvas.receivers(self.canvas.destinationCrsChanged)
        self.pv = PreviewWidget()
        self.pv.resize(1000, 460)
        self.pv.show()
        APP.processEvents()
        self.dock = XSectionsDock(self.iface, self.pv)
        self.fb = self.dock.feedback
        self.cleaned = False
        self.build()
        self.events = []
        self.pv.hoverChanged.connect(lambda st, i: self.events.append(("changed", st, i)))
        self.pv.hoverLeft.connect(lambda: self.events.append(("left",)))

    def tearDown(self):
        if not self.cleaned:
            self.dock.cleanup()
        self.dock.deleteLater()
        self.pv.hide()
        self.pv.deleteLater()
        APP.processEvents()
        restore_user_values(self._user)
        self.prj.clear()

    def build(self, **over):
        """The fixture section through the real pipeline, with a second line (a raster surface on the DEM)."""
        kw = dict(h_scale=1000.0, v_scale=50.0,
                  surfaces=[dict(SURFACE_DEFAULTS, layer_id=self.dem.id(), name="Water table", color="#1f6fb2",
                                 style="dash")])
        kw.update(over)
        self.dock.apply_settings(default_settings(self.prj, self.dem, self.pts, self.lines, **kw))
        self.dock.refresh()
        self.assertEqual(self.dock.last_error, "")
        settle(self.pv)
        self.model, self.s = self.dock.model, self.dock._settings
        self.f = self.model.dist_factor

    # ---- driving
    def mid_z(self):
        z0, z1 = sorted(self.pv._ax.get_ylim())
        return (z0 + z1) / 2.0

    def map_xy(self, point):
        """The map cursor at `point` (canvas CRS), and the coalescing timer run."""
        self.canvas.xyCoordinates.emit(QgsPointXY(point))
        self.flush()

    def flush(self):
        t0 = time.perf_counter()
        while self.dock._map_timer.isActive() and time.perf_counter() - t0 < budget(2.0):
            APP.processEvents()
            time.sleep(0.002)
        APP.processEvents()

    def map_leave(self):
        QApplication.sendEvent(self.canvas.viewport(), QEvent(QEvent.Type.Leave))

    def foot(self, station_ft):
        return LINE_GEOM.interpolate(station_ft / self.f).asPoint()

    def map_station(self):
        """The station the map cursor put the preview's guide and the map marker at (one and the same)."""
        self.assertEqual(self.pv._hover[0], "map")
        self.assertEqual(self.fb._cursor[0], self.pv._hover[1])
        return self.pv._hover[1]

    def assertNear(self, a, b, tol=1e-6, msg=None):
        self.assertLess(math.hypot(a.x() - b.x(), a.y() - b.y()), tol, msg or f"{a} != {b}")

    def assertNoCursor(self):
        self.assertFalse(self.fb.cursor_shown())
        self.assertFalse(self.fb.cursor.isVisible())
        for band in (self.fb.ring, self.fb.projection, self.fb.connector):
            self.assertEqual(band.numberOfVertices(), 0)

    def assertGuide(self, station_ft, off_text):
        """The map's guide in the preview: the first tile "1,500 ft from A" over "50 ft" and "right of the line"
        (`off_text` "50 ft right of the line"), the guide on the plot and the popup by it."""
        cells = self.pv.readout.cells()
        self.assertEqual(self.pv.readout.mode, "values")
        value, detail = off_text.split(" ft ", 1)
        self.assertEqual(cells[0][:3], (f"{distance_text(station_ft, self.s)} from A", f"{value} ft", detail))
        self.assertTrue(self.pv._marks_on and self.pv._marks.guide.get_visible())
        if self.pv.popup_enabled():
            self.assertTrue(self.pv.popup.isVisible())
            self.assertEqual(self.pv.popup.header(), (f"{distance_text(station_ft, self.s)} from A", off_text))


# ------------------------------------------------------------------ the preview -> the map
class PreviewToMapTest(WiringCase):
    def test_hover_moves_the_marker_along_the_line(self):
        self.assertEqual([h.label for h in self.model.hits], ["B-1", "MW-1", "TP-1", "B-2", "MW-2", "CPT-1", "B-3"])
        for station in (1800.0, 2600.0, 50.0):         # (no exploration near; the second past the bend)
            at = vp_of(self.pv, station, self.mid_z())
            move(self.pv, at)
            st, _ = data_at(self.pv, at)
            self.assertEqual(self.events[-1][0], "changed")
            self.assertAlmostEqual(self.events[-1][1], st)
            self.assertEqual(self.events[-1][2], -1)
            self.assertTrue(self.fb.cursor_shown() and self.fb.cursor.isVisible())
            self.assertNear(self.fb.cursor.point, self.foot(st))           # canvas CRS = section CRS here
            self.assertEqual(self.fb.cursor.text, distance_text(st, self.s))
            self.assertEqual(self.fb.ring.numberOfVertices(), 0)
            self.assertEqual(self.fb.connector.numberOfVertices(), 0)
            self.assertEqual(self.dock._cursor_from, "preview")

    def test_pointing_at_an_exploration_rings_it(self):
        h = self.model.hits[1]                                             # MW-1, 60 ft right at 900 ft
        move(self.pv, vp_of(self.pv, h.station, (h.top + h.bottom) / 2.0))
        self.assertEqual(self.events[-1], ("changed", h.station, 1))
        self.assertEqual(self.pv.readout.mode, "cells")
        self.assertNear(self.fb.cursor.point, self.foot(h.station))
        self.assertEqual(self.fb.ring.numberOfVertices(), 1)
        self.assertNear(self.fb.ring.asGeometry().vertexAt(0), QgsPointXY(h.x, h.y))
        line = self.fb.projection.asGeometry().asPolyline()
        self.assertEqual(len(line), 2)
        self.assertNear(line[0], QgsPointXY(h.x, h.y))
        self.assertNear(line[1], self.foot(h.station))
        # on to the line: the ring goes, the marker stays
        move(self.pv, vp_of(self.pv, 1800.0, self.mid_z()))
        self.assertEqual(self.fb.ring.numberOfVertices(), 0)
        self.assertTrue(self.fb.cursor_shown())

    def test_leaving_hides_the_marker(self):
        h = self.model.hits[0]
        move(self.pv, vp_of(self.pv, h.station, (h.top + h.bottom) / 2.0))
        self.assertEqual(self.fb.ring.numberOfVertices(), 1)
        leave(self.pv)
        self.assertEqual(self.events[-1], ("left",))
        self.assertNoCursor()
        self.assertEqual(self.dock._cursor_from, "")
        # past A' inside the frame: the same
        move(self.pv, vp_of(self.pv, 1800.0, self.mid_z()))
        self.assertTrue(self.fb.cursor_shown())
        move(self.pv, vp_of(self.pv, self.model.length + 5.0, self.mid_z()))
        self.assertNoCursor()

    def test_a_rebuild_or_a_failure_hides_the_marker(self):
        move(self.pv, vp_of(self.pv, 1800.0, self.mid_z()))
        self.assertTrue(self.fb.cursor_shown())
        self.dock.refresh()
        self.assertNoCursor()
        settle(self.pv)
        move(self.pv, vp_of(self.pv, 1800.0, self.mid_z()))
        self.assertTrue(self.fb.cursor_shown())
        self.dock._pipeline = lambda s: (_ for _ in ()).throw(SectionError("No DEM"))
        self.dock.refresh()
        self.assertNoCursor()
        self.assertFalse(self.pv.has_section())
        self.dock.project_cleared()
        self.assertNoCursor()

    def test_closing_the_panel_hides_the_marker(self):
        move(self.pv, vp_of(self.pv, 1800.0, self.mid_z()))
        self.assertTrue(self.fb.cursor_shown())
        self.dock.closedStateChanged.emit(True)
        self.assertNoCursor()
        move(self.pv, vp_of(self.pv, 1900.0, self.mid_z()))              # the readout works; the map stays clear
        self.assertEqual(self.events[-1][0], "changed")
        self.assertNoCursor()
        self.dock.closedStateChanged.emit(False)
        move(self.pv, vp_of(self.pv, 2000.0, self.mid_z()))
        self.assertTrue(self.fb.cursor.isVisible())


# ------------------------------------------------------------------ the map -> the preview
class MapToPreviewTest(WiringCase):
    def test_the_map_cursor_moves_the_guide(self):
        self.map_xy(pt(1500.0, -50.0))                                     # 50 ft right of the line
        self.assertGuide(1500.0 * self.f, "50 ft right of the line")
        self.assertEqual(self.events, [], "the guide from the map sends no hoverChanged")
        self.assertTrue(self.fb.cursor.isVisible())
        self.assertNear(self.fb.cursor.point, pt(1500.0))
        self.assertAlmostEqual(self.map_station(), 1500.0 * self.f, places=6)
        con = self.fb.connector.asGeometry().asPolyline()
        self.assertEqual(len(con), 2)
        self.assertNear(con[0], pt(1500.0, -50.0))
        self.assertNear(con[1], pt(1500.0))
        self.assertEqual(self.fb.ring.numberOfVertices(), 0)
        # past the bend, on the left
        self.map_xy(pt(3600.0, 120.0))
        self.assertGuide(3600.0 * self.f, "120 ft left of the line")
        self.assertNear(self.fb.cursor.point, pt(3600.0))
        # leaving the map takes both away
        self.map_leave()
        self.assertEqual(self.pv.readout.mode, "idle")
        self.assertEqual(self.pv.readout.idle_text, R.IDLE_TEXT)
        self.assertFalse(self.pv._marks_on)
        self.assertNoCursor()

    def test_a_real_mouse_move_on_the_map(self):
        target = pt(2000.0, 30.0)
        px = self.canvas.getCoordinateTransform().transform(target)
        pos = QPoint(int(round(px.x())), int(round(px.y())))
        vp = self.canvas.viewport()
        sent = []
        self.canvas.xyCoordinates.connect(lambda p: sent.append(QgsPointXY(p)))
        QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(vp.mapToGlobal(pos)),
                                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                               Qt.KeyboardModifier.NoModifier))
        self.flush()
        self.assertEqual(len(sent), 1)                              # (the pixel's map point, as the canvas says)
        dist, off, side, _ = LineLocator(LINE_GEOM).locate(sent[0])
        self.assertEqual(side, "L")
        self.assertGuide(dist * self.f, f"{round(off * self.f):,} ft left of the line")
        self.assertAlmostEqual(self.map_station(), dist * self.f, places=6)
        self.assertLess(abs(dist - 2000.0), 2.0 * self.canvas.mapUnitsPerPixel())
        self.map_leave()
        self.assertNoCursor()

    def test_points_past_the_ends_or_far_away_are_ignored(self):
        for far in (QgsPointXY(*_explo_xy(-80.0, 10.0)),           # before A, 10 ft beside the line's direction
                    QgsPointXY(*_explo_xy(None, None)),            # 80 ft past A'
                    pt(1500.0, -(NEAR + 20.0)), pt(1500.0, NEAR + 20.0)):
            self.map_xy(pt(1500.0, -50.0))
            self.assertTrue(self.fb.cursor_shown())
            self.map_xy(far)
            self.assertEqual(self.pv.readout.mode, "idle", far)
            self.assertFalse(self.pv._marks_on)
            self.assertNoCursor()
        # just inside the reach: 2.5 x the tolerance
        self.map_xy(pt(1500.0, -(NEAR - 20.0)))
        self.assertGuide(1500.0 * self.f, f"{round((NEAR - 20.0) * self.f):,} ft right of the line")

    def test_the_pixel_rule_on_a_ground_only_section(self):
        mupp = self.canvas.mapUnitsPerPixel()
        self.assertLess(20.0 * mupp, NEAR)                         # (with explorations 20 px is near enough)
        self.map_xy(pt(1500.0, -20.0 * mupp))
        self.assertTrue(self.fb.cursor_shown())
        self.build(points_layer_id="")
        self.assertFalse(self.model.has_explorations)
        self.map_xy(pt(1500.0, -10.0 * mupp))                      # 10 px: near
        self.assertGuide(1500.0 * self.f, f"{round(10.0 * mupp * self.f):,} ft right of the line")
        self.map_xy(pt(1500.0, -20.0 * mupp))                      # 20 px: not
        self.assertEqual(self.pv.readout.mode, "idle")
        self.assertNoCursor()

    def test_either_toggle_keeps_the_hover_both_off_end_it(self):
        # the readout row off, the popup on: the hover goes on both ways (the popup and the marks show it)
        self.pv.act_strip.setChecked(False)
        settle(self.pv)
        self.assertTrue(self.pv.readout.isHidden())
        self.map_xy(pt(1500.0, -50.0))
        self.assertGuide(1500.0 * self.f, "50 ft right of the line")
        self.assertTrue(self.fb.cursor_shown())
        self.map_leave()
        move(self.pv, vp_of(self.pv, 1800.0, self.mid_z()))
        self.assertEqual(self.events[-1][0], "changed")
        self.assertTrue(self.fb.cursor_shown() and self.pv.popup.isVisible())
        # the popup off as well: no hover at all, either way, and the marker goes at once
        self.pv.act_popup.setChecked(False)
        self.assertFalse(self.pv.hover_enabled())
        self.assertEqual(self.events[-1], ("left",))
        self.assertNoCursor()
        n = len(self.events)
        self.map_xy(pt(1500.0, -50.0))
        self.assertNoCursor()
        self.assertFalse(self.pv._marks_on or self.pv.popup.isVisible())
        move(self.pv, vp_of(self.pv, 1900.0, self.mid_z()))
        self.assertEqual(len(self.events), n, "no hoverChanged")
        self.assertNoCursor()
        # the popup back on: both ways again
        self.pv.act_popup.setChecked(True)
        self.map_xy(pt(1500.0, -50.0))
        self.assertGuide(1500.0 * self.f, "50 ft right of the line")
        self.assertTrue(self.fb.cursor_shown())
        # turned off while the map's guide shows: the guide and the marker go at once, and stay away
        self.pv.act_popup.setChecked(False)
        self.assertNoCursor()
        self.assertEqual(self.dock._cursor_from, "")
        self.assertFalse(self.pv._marks_on or self.pv.popup.isVisible())
        self.assertEqual(self.pv.readout.mode, "idle")
        self.map_xy(pt(1600.0, -50.0))
        self.assertNoCursor()
        # the readout row alone (as 0.3.1's hover): both ways, no popup
        self.pv.act_strip.setChecked(True)
        settle(self.pv)
        self.map_xy(pt(1500.0, -50.0))
        self.assertGuide(1500.0 * self.f, "50 ft right of the line")
        self.assertFalse(self.pv.popup.isVisible())
        self.assertTrue(self.fb.cursor_shown())

    def test_nothing_from_the_map_while_the_preview_or_the_panel_is_closed(self):
        self.pv.hide()
        self.map_xy(pt(1500.0, -50.0))
        self.assertNoCursor()
        self.pv.show()
        settle(self.pv)
        self.map_xy(pt(1500.0, -50.0))
        self.assertTrue(self.fb.cursor_shown())
        self.dock.closedStateChanged.emit(True)                    # the panel closed: the marker goes at once
        self.assertNoCursor()
        self.assertEqual(self.pv.readout.mode, "idle")
        self.map_xy(pt(1500.0, -50.0))
        self.assertNoCursor()
        self.assertEqual(self.pv.readout.mode, "idle")
        self.dock.closedStateChanged.emit(False)
        self.map_xy(pt(1500.0, -50.0))
        self.assertTrue(self.fb.cursor.isVisible())

    def test_moves_coalesce_and_a_leave_drops_a_waiting_move(self):
        with mock.patch.object(self.pv, "show_guide", wraps=self.pv.show_guide) as guide:
            for st in (1000.0, 1100.0, 1200.0, 1300.0):
                self.canvas.xyCoordinates.emit(pt(st, -50.0))
            self.assertTrue(self.dock._map_timer.isActive())
            self.flush()
            self.assertEqual(guide.call_count, 1)                  # one update, for the latest move
            self.assertAlmostEqual(guide.call_args[0][0], 1300.0 * self.f, places=6)
            self.canvas.xyCoordinates.emit(pt(1400.0, -50.0))
            self.map_leave()
            self.flush()
            self.assertEqual(guide.call_count, 1)
        self.assertNoCursor()

    def test_a_new_section_or_a_failure_ends_the_map_hover(self):
        self.map_xy(pt(1500.0, -50.0))
        self.assertTrue(self.fb.cursor_shown())
        self.dock.refresh()
        settle(self.pv)
        self.assertNoCursor()
        self.assertEqual(self.pv.readout.mode, "idle")
        self.map_xy(pt(1500.0, -50.0))                             # the new model is read
        self.assertGuide(1500.0 * self.f, "50 ft right of the line")
        self.dock._pipeline = lambda s: (_ for _ in ()).throw(SectionError("No DEM"))
        self.dock.refresh()
        self.assertNoCursor()
        self.map_xy(pt(1500.0, -50.0))
        self.assertNoCursor()

    def test_another_canvas_crs(self):
        web = QgsCoordinateReferenceSystem("EPSG:3857")
        self.canvas.setDestinationCrs(web)
        APP.processEvents()
        ct = QgsCoordinateTransform(QgsCoordinateReferenceSystem(CRS), web, QgsProject.instance())
        self.map_xy(ct.transform(pt(1500.0, -50.0)))
        cells = self.pv.readout.cells()
        self.assertEqual(cells[0][0], "1,500 ft from A")
        self.assertEqual(cells[0][1:3], ("50 ft", "right of the line"))
        self.assertAlmostEqual(self.map_station(), 1500.0 * self.f, delta=1e-3)
        self.assertNear(self.fb.cursor.point, ct.transform(pt(1500.0)), tol=1e-3)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem(CRS))    # and back
        APP.processEvents()
        self.map_xy(pt(2000.0, 40.0))
        self.assertEqual(self.pv.readout.cells()[0][1:3], ("40 ft", "left of the line"))
        self.assertNear(self.fb.cursor.point, pt(2000.0))


class LocatorTest(unittest.TestCase):
    def test_stations_offsets_and_sides_as_core(self):
        loc = LineLocator(LINE_GEOM)
        # (inside the bend a point can be nearer the other segment: these are not)
        for station, off in ((0.0, 5.0), (300.0, 40.0), (2400.0, 60.0), (2499.0, -60.0), (2501.0, -30.0),
                             (4000.0, -120.0), (LINE_GEOM.length(), 1.0)):
            dist, d, side, foot = loc.locate(pt(station, off))
            self.assertAlmostEqual(dist, station, places=6)
            self.assertAlmostEqual(d, abs(off), places=6)
            self.assertEqual(side, "L" if off > 0 else "R")
            self.assertAlmostEqual(dist, LINE_GEOM.lineLocatePoint(QgsGeometry.fromPointXY(foot)), places=6)
        self.assertIsNone(loc.locate(QgsPointXY(*_explo_xy(-1.0, 0.0))))
        self.assertIsNone(loc.locate(QgsPointXY(*_explo_xy(None, None))))
        self.assertIsNone(LineLocator(QgsGeometry.fromWkt("LineString (0 0)")).locate(QgsPointXY(0, 0)))


# ------------------------------------------------------------------ Surfaces CSV…
class SurfacesCsvTest(WiringCase):
    def run_export(self, configure=None, path=None, accept=True):
        """export_surfaces_csv with the dialog set by `configure` and Save CSV… (or Cancel) pressed, and the file
        dialog answered by `path`. Returns (result, the file dialog mock, dialogs opened)."""
        opened = []

        def fake_exec(dlg):
            opened.append(dlg)
            if configure is not None:
                configure(dlg)
            if not accept:
                return QDialog.DialogCode.Rejected
            dlg.accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(SurfacesCsvDialog, "exec", new=fake_exec), \
                mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName",
                           return_value=(path or "", "CSV (*.csv)")) as files:
            result = self.dock.export_surfaces_csv()
        return result, files, opened

    def out(self, name):
        folder = tempfile.mkdtemp(prefix="xsec_wiring_")
        self.addCleanup(shutil.rmtree, folder, True)
        return os.path.join(folder, name)

    def message(self):
        return self.iface.messageBar().currentItem()

    def test_long_layout(self):
        lines = hover_lines(self.model)
        names = unique_names(ln.name for ln in lines)
        self.assertEqual(names, ["Ground (LIDAR_DEM_3ft)", "Water table"])
        target = self.out("long")
        result, files, opened = self.run_export(lambda d: d.layout_seg.setCurrentIndex(d.layout_seg.findData("long")),
                                                target)
        self.assertEqual(result, target + ".csv")                    # the extension is added
        self.assertEqual(len(opened), 1)
        args = files.call_args[0]
        self.assertEqual(args[1], "Export surfaces to CSV")
        self.assertEqual(os.path.basename(args[2]), "Section A-A' surfaces.csv")
        rows = read_csv(result)
        self.assertEqual(rows[0], LONG_COLUMNS)
        for name, ln in zip(names, lines):
            self.assertEqual(sum(1 for r in rows[1:] if r[0] == name), ln.stations.size, name)
        self.assertEqual(rows[1][0], names[0])                       # the ground first
        n = len(rows) - 1
        self.assertEqual(self.message().text(), f"Wrote 2 surfaces ({n:,} rows) to {result}")
        self.assertEqual(settings_store.user_value("last_export_dir"), os.path.dirname(result))

    def test_wide_layout_one_surface_with_map_coordinates(self):
        def configure(d):
            d.layout_seg.setCurrentIndex(d.layout_seg.findData("wide"))
            d.step.setValue(25)
            d.boxes[0].setChecked(False)
            d.map_xy.setChecked(True)
        target = self.out("wide.csv")
        result, _, _ = self.run_export(configure, target)
        self.assertEqual(result, target)
        rows = read_csv(result)
        self.assertEqual(rows[0], ["distance_ft", "Water table"] + MAP_COLUMNS)
        grid = wide_stations(self.model, 25.0)
        self.assertEqual(len(rows) - 1, grid.size)
        self.assertEqual([float(r[0]) for r in rows[1:4]], [0.0, 25.0, 50.0])
        x, y = (float(v) for v in rows[2][2:4])
        self.assertAlmostEqual(x, pt(25.0 / self.f).x(), places=2)
        self.assertAlmostEqual(y, pt(25.0 / self.f).y(), places=2)
        self.assertEqual(self.message().text(), f"Wrote 1 surface ({grid.size:,} rows) to {result}")
        self.assertEqual(D.remembered(), ("wide", 25, True))         # the dialog's choices, for next time

    def test_cancelled(self):
        result, files, opened = self.run_export(accept=False)
        self.assertEqual(result, "")
        self.assertEqual(len(opened), 1)
        files.assert_not_called()
        result, files, _ = self.run_export(path="")                  # the file dialog cancelled
        self.assertEqual(result, "")
        files.assert_called_once()

    def test_a_locked_file_is_a_message(self):
        target = self.out("locked.csv")
        os.mkdir(target)                                             # open() fails like a CSV Excel holds open
        result, _, _ = self.run_export(path=target)
        self.assertEqual(result, "")
        item = self.message()
        self.assertIn("Could not write locked.csv: it is probably open in Excel", item.text())

    def test_no_section(self):
        self.dock._pipeline = lambda s: (_ for _ in ()).throw(SectionError("Choose a DEM"))
        self.dock._stale = True
        result, files, opened = self.run_export(path=self.out("x.csv"))
        self.assertEqual((result, opened), ("", []))
        files.assert_not_called()
        self.assertEqual(self.message().text(), "No surfaces to export: Choose a DEM")

    def test_the_preview_button_asks_the_dock(self):
        opened = []
        with mock.patch.object(SurfacesCsvDialog, "exec",
                               new=lambda dlg: opened.append(dlg.model) or QDialog.DialogCode.Rejected):
            self.pv.act_csv.trigger()
        self.assertEqual(opened, [self.model])


# ------------------------------------------------------------------ teardown
class CleanupTest(WiringCase):
    def receivers(self):
        c, pv = self.canvas, self.pv
        return (c.receivers(c.xyCoordinates), c.receivers(c.destinationCrsChanged), pv.receivers(pv.hoverChanged),
                pv.receivers(pv.hoverLeft), pv.receivers(pv.exportSurfacesRequested))

    def test_cleanup_leaves_nothing_connected(self):
        self.map_xy(pt(1500.0, -50.0))
        self.assertTrue(self.fb.cursor_shown())
        self.assertEqual(self.receivers()[2:], (2, 2, 1))           # the dock's and this test's
        self.assertGreater(self.receivers()[0], self.receivers_before)
        self.dock.cleanup()
        self.cleaned = True
        self.assertEqual(self.receivers(), (self.receivers_before, self.crs_receivers_before, 1, 1, 0))
        self.assertEqual(len(our_items(self.canvas)), self.items_before)
        self.assertEqual(self.pv.readout.mode, "idle")              # the map's guide went with the marker
        # whatever happens now reaches nothing of the dock's
        with mock.patch.object(self.dock, "_hide_cursor") as hide:
            self.canvas.xyCoordinates.emit(pt(1600.0, -50.0))
            self.assertFalse(self.dock._map_timer.isActive())
            self.assertIsNone(self.dock._map_point)
            self.map_leave()                                        # (the event filter is gone)
            self.flush()
            self.pv.hoverChanged.emit(100.0, -1)
            self.pv.hoverLeft.emit()
            hide.assert_not_called()
        self.assertEqual(self.pv.readout.mode, "idle")
        self.assertEqual(len(our_items(self.canvas)), self.items_before)
        with mock.patch.object(SurfacesCsvDialog, "exec") as dialog:
            self.pv.exportSurfacesRequested.emit()
        dialog.assert_not_called()

    def test_a_stand_in_preview(self):
        stand_in = mock.Mock()
        d = XSectionsDock(self.iface, stand_in)
        try:
            stand_in.hoverChanged.connect.assert_called_once_with(d._on_preview_hover)
            stand_in.hoverLeft.connect.assert_called_once_with(d._on_preview_left)
            stand_in.exportSurfacesRequested.connect.assert_called_once_with(d.export_surfaces_csv)
            self.canvas.xyCoordinates.emit(pt(1500.0, -50.0))          # no model yet: nothing to do
            self.flush()
            stand_in.show_guide.assert_not_called()
        finally:
            d.cleanup()
            d.deleteLater()
        stand_in.hoverChanged.disconnect.assert_called_once_with(d._on_preview_hover)
        stand_in.exportSurfacesRequested.disconnect.assert_called_once_with(d.export_surfaces_csv)
        none = XSectionsDock(self.iface, None)                          # no preview at all
        none.cleanup()
        none.deleteLater()
        APP.processEvents()


if __name__ == "__main__":
    unittest.main()
