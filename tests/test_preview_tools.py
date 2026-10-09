"""The preview's tools (0.3.1, 0.3.2; the compact strip 0.3.4): the toolbar, the whole-plot zoom, the readout strip of
equal tiles, the hover popup, the two hover toggles and the hover marks.

A hand-made section on the fixture line (a DEM gap, two explorations, a model top that crosses the ground, a
cells-mode water table with a no-data cell and a model bottom below the plot) in a shown preview, driven with real
Qt mouse, wheel and key events. Two classes run the real CDF section when XSECTIONS_REALDATA is set (one with six
CDF_Mounding surfaces, the compact strip's section). The toggles' user values are set for each test and put back
afterwards (in the test run's own profile, tests/fixtures.py).
"""
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests.fixtures import LINE, REALDATA, ROOT, budget, line_length, start_app, timing_test

APP = start_app()

import numpy as np  # noqa: E402
from qgis.core import QgsGeometry, QgsPointXY, QgsSettings  # noqa: E402
from qgis.gui import QgsDockWidget  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPalette, QWheelEvent  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QLabel, QMainWindow, QWidget  # noqa: E402

from xsections.core.hover import (NO_VALUE, depth_text, distance_text, elev_text, hit_cells,  # noqa: E402
                                  hover_lines, hover_values, strip_cells)
from xsections.core.model import (GroundProfile, Hit, PageLayout, Plan, SectionModel, Settings,  # noqa: E402
                                  SurfaceProfile, WaterLevel)
from xsections.core.surfaces_csv import MapXY  # noqa: E402
from xsections.render import figure as F  # noqa: E402
from xsections.ui import popup as U  # noqa: E402
from xsections.ui import preview as P  # noqa: E402
from xsections.ui import readout as R  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.preview import PreviewWidget, zoom_limit, zoom_step  # noqa: E402
from xsections.ui.widgets import theme_for  # noqa: E402

NAN = math.nan
L = line_length()                       # 4,588.06 ft, bend at 2,500
NoButton, Left = Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton
NoMod = Qt.KeyboardModifier.NoModifier
TOGGLE_KEYS = (P.STRIP_KEY, P.POPUP_KEY)
# the shown preview's size ("1500x600"), and the screen ratio it must have: set for the runs at 250 % in a child
# process (SpeedTest, ScreenTest)
SIZE_ENV, RATIO_ENV = "XSECTIONS_PREVIEW_SIZE", "XSECTIONS_EXPECT_RATIO"


# ------------------------------------------------------------------ the section
def make_model(line_wkt=None, extra_surfaces=0):
    ground = GroundProfile(stations=[0.0, 1000.0, 2000.0, 2500.0, 3000.0, 3900.0, 3960.0, L],
                           z=[505.0, 515.0, 525.0, 530.0, 540.0, NAN, NAN, 560.0], step=3.0,
                           gaps=[(3900.0, 3960.0)], coverage=0.97)
    surfaces = [
        # crosses the ground: below it at A, above it from ~500 ft on (bgs <-> ags)
        SurfaceProfile(name="Model top", color="#555555", style="dot", width=1.0, mode="smooth",
                       stations=[0.0, 1500.0, 3000.0, L], z=[500.0, 530.0, 560.0, 555.0], source="mf6"),
        # flat across cells, one without data
        SurfaceProfile(name="Water table (SP 49)", color="#1f6fb2", style="dash", width=1.25, mode="cells",
                       stations=[0.0, 1000.0, 1000.0, 2000.0, 2000.0, 3000.0, 3000.0, L],
                       z=[490.0, 490.0, 495.0, 495.0, NAN, NAN, 500.0, 500.0], source="mf6"),
        # below the plot (left out of the elevation range): listed, never dotted
        SurfaceProfile(name="Model bottom", color="#8c5a3c", style="solid", width=1.0, mode="smooth",
                       stations=[0.0, L], z=[300.0, 310.0], in_range=False, source="mf6"),
    ]
    for k in range(extra_surfaces):                 # more layers, each crossing the ground somewhere
        surfaces.append(SurfaceProfile(name=f"Layer {k + 1} bottom", color="#2e7d57", style="dash", width=1.0,
                                       mode="smooth", stations=np.linspace(0.0, L, 40),
                                       z=470.0 + 10.0 * k + 40.0 * np.sin(np.linspace(0.0, 6.0 + k, 40)),
                                       source="mf6"))
    hits = [
        Hit(fid=1, label="B-1", type_value="Boring", x=LINE[0][0] + 300, y=LINE[0][1] + 40, station=300.0,
            offset=40.0, side="L", direction="N", ground_at_station=508.0, ground_at_point=508.2, top=508.2,
            top_source="field", bottom=478.2, bottom_source="depth", total_depth=30.0),
        Hit(fid=5, label="MW-2", type_value="Monitoring Well", x=LINE[1][0] - 100, y=LINE[1][1] + 90,
            station=2900.0, offset=90.0, side="R", direction="S", ground_at_station=538.0, ground_at_point=539.0,
            top=539.0, top_source="dem", bottom=504.0, bottom_source="depth", total_depth=35.0,
            screen_top=525.0, screen_bottom=510.0,
            water_levels=[WaterLevel(elev=530.0, kind="measured", date="6/12/2024"),
                          WaterLevel(elev=528.0, kind="atd")]),
    ]
    wkt = line_wkt or QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE]).asWkt()
    return SectionModel(length=L, vertex_stations=[0.0, 2500.0, L], azimuth=82.0, ground=ground, hits=hits,
                        line_wkt=wkt, dem_name="LIDAR_DEM_3ft", points_name="Explorations", dist_factor=1.0,
                        surfaces=surfaces)


def make_settings(**over):
    s = Settings(h_scale=1000.0, v_scale=200.0, wl_field="WL", tolerance_ft=150.0)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def make_plan():
    pages = [PageLayout(11, 8.5, "Letter 11 × 8.5 in, landscape", 2.0, 2.3, 4.6, 5.0, 0.0, 4600.0)]
    return Plan(z_min=400.0, z_max=650.0, plot_length=4600.0, h_major=1000.0, h_minor=100.0, v_major=50.0,
                v_minor=5.0, pages=pages)


# ------------------------------------------------------------------ the user values
def save_user_values(keys):
    """The user values `keys` as they are now (None: not set), for restore_user_values."""
    return {k: settings_store.user_value(k, None) for k in keys}


def restore_user_values(saved):
    """Put user values back as save_user_values found them (removing those that were not set)."""
    for k, v in saved.items():
        if v is None:
            QgsSettings().remove(settings_store.USER_PREFIX + k)
        else:
            settings_store.set_user_value(k, v)


# ------------------------------------------------------------------ driving the widget
def settle(pv):
    """Let Qt and matplotlib catch up: pending events, a due re-layout, the full draw."""
    APP.processEvents()
    if pv._resize_timer.isActive():
        pv._resize_timer.stop()
        pv._request()
    APP.processEvents()
    if pv._stale:
        pv.canvas.draw()
    APP.processEvents()


def vp_of(pv, station, z):
    """Where data point (station, z) is in the viewport, logical px."""
    c = pv.canvas
    r = c.device_pixel_ratio
    dx, dy = pv._ax.transData.transform((station, z))
    return QPointF(dx / r + c.x(), c.height() - dy / r + c.y())


def data_at(pv, vp):
    """(station, elevation) under a viewport point."""
    return tuple(float(v) for v in pv._ax.transData.inverted().transform(pv._display_xy(QPointF(vp))))


def mouse(pv, typ, vp, button=NoButton, buttons=NoButton):
    c = pv.canvas
    local = QPointF(vp) - QPointF(c.pos())
    glob = QPointF(pv.scroll.viewport().mapToGlobal(QPointF(vp)))       # the viewport stays put while dragging
    QApplication.sendEvent(c, QMouseEvent(typ, local, glob, button, buttons, NoMod))


def move(pv, vp, buttons=NoButton):
    mouse(pv, QEvent.Type.MouseMove, vp, buttons=buttons)


def wheel(pv, vp, dy=120, dx=0, mods=NoMod):
    c = pv.canvas
    local = QPointF(vp) - QPointF(c.pos())
    QApplication.sendEvent(c, QWheelEvent(local, QPointF(c.mapToGlobal(local)), QPoint(0, 0), QPoint(dx, dy),
                                          NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False))


def key(pv, k, text=""):
    QApplication.sendEvent(pv.canvas, QKeyEvent(QEvent.Type.KeyPress, k, NoMod, text))


def leave(pv):
    QApplication.sendEvent(pv.canvas, QEvent(QEvent.Type.Leave))


def buffer(pv):
    return np.array(pv.canvas.buffer_rgba(), copy=True)


def icon_ink(action):
    """The colours of an action's icon's opaque pixels (48 px)."""
    img = action.icon().pixmap(48, 48).toImage()
    return {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())
            if img.pixelColor(x, y).alpha() == 255}


class Watch(QObject):
    """Records events of one type on a widget: `record(widget, event)` -> a list entry (kept in `seen`)."""

    def __init__(self, widget, kind, record):
        super().__init__()
        self.kind, self.record, self.seen = kind, record, []
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == self.kind:
            self.seen.append(self.record(obj, event))
        return False


def screen(widget):
    """The window's pixels as they are on the screen (the offscreen platform's backing store: what the partial
    repaints left there, not a fresh paint like QWidget.grab). (At a ratio over 1 the offscreen platform gives only
    the window's top left, its logical size in device px.)"""
    APP.processEvents()
    img = QApplication.primaryScreen().grabWindow(widget.window().winId()).toImage()
    return np.array(img.constBits().asarray(img.sizeInBytes()), np.uint8).reshape(img.height(),
                                                                                   img.bytesPerLine()).copy()


def env_size(default=(1000, 460)):
    """The preview size a child run asks for (SIZE_ENV), else `default`."""
    text = os.environ.get(SIZE_ENV, "")
    return tuple(int(v) for v in text.split("x")) if text else default


def run_child(test_ids, **env):
    """Run tests in a new Python (a new QgsApplication, e.g. at another screen ratio); (exit code, output). (The
    child gets this environment, XSECTIONS_TIME_FACTOR included.)"""
    full = dict(os.environ, **env)
    out = subprocess.run([sys.executable, "-m", "unittest", "-v", *test_ids], cwd=ROOT, env=full,
                         capture_output=True, text=True, timeout=budget(600))
    return out.returncode, (out.stdout or "") + (out.stderr or "")


class PreviewCase(unittest.TestCase):
    def setUp(self):
        self._user = save_user_values(TOGGLE_KEYS)
        for k in TOGGLE_KEYS:
            settings_store.set_user_value(k, "1")

    def tearDown(self):
        restore_user_values(self._user)

    def shown(self, w=1000, h=460, model=None, settings=None, plan=None):
        pv = PreviewWidget()
        self.addCleanup(self._close, pv)
        pv.resize(w, h)
        pv.show()
        APP.processEvents()
        pv.draw(model or make_model(), settings or make_settings(), plan or make_plan())
        settle(pv)
        self.events = []
        pv.hoverChanged.connect(lambda st, i: self.events.append(("changed", st, i)))
        pv.hoverLeft.connect(lambda: self.events.append(("left",)))
        return pv

    @staticmethod
    def _close(pv):
        pv.hide()
        pv.deleteLater()
        APP.processEvents()

    def assertNear(self, a, b, tol=1.0, msg=None):
        self.assertLessEqual(math.hypot(a.x() - b.x(), a.y() - b.y()), tol, msg)

    def assertGrid(self, ro, msg=None):
        """The tiles painted are the first of the fixed grid: every tile the same width and height, in columns of
        tile_width() from the strip's padding, wrapped every per_line tiles."""
        rects = ro.tile_rects()
        self.assertEqual(len(rects), ro.columns, msg)
        w, pitch = ro.tile_width(), ro.pitch
        top = rects[0].top() if rects else 0.0
        for i, r in enumerate(rects):
            self.assertEqual(r.width(), w - 2 * R.TILE_MX, msg)
            self.assertEqual(r.height(), pitch - 2 * R.TILE_MY, msg)
            self.assertEqual(r.left(), R.ROW_PAD_X + (i % ro.per_line) * w + R.TILE_MX, msg)
            self.assertEqual(r.top(), top + (i // ro.per_line) * pitch, msg)
            self.assertLessEqual(r.right(), ro.width() - R.ROW_PAD_X + 0.01, msg)
        shown = ro.shown()
        self.assertEqual([QRectF(r) for r, _ in shown], rects[:len(shown)], msg)


# ------------------------------------------------------------------ pure helpers
class HelpersTest(unittest.TestCase):
    def test_zoom_limit_is_a_pixel_budget(self):
        self.assertEqual(zoom_limit(1200, 420, 1.0), 8.0)
        self.assertAlmostEqual(zoom_limit(1200, 420, 1.5), math.sqrt(40e6 / (1200 * 420 * 2.25)))   # ~5.9
        self.assertAlmostEqual(zoom_limit(2400, 600, 1.5), 3.51, places=2)
        self.assertEqual(zoom_limit(8000, 3000, 2.0), 2.0)                    # never under 200 %

    def test_ladder(self):
        up, z = [], 1.0
        for _ in range(8):
            z = zoom_step(z, 1)
            up.append(z)
        self.assertEqual(up, [1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 8.0, 8.0])
        self.assertEqual([zoom_step(z, -1) for z in (8.0, 6.0, 1.5, 1.0)], [6.0, 4.0, 1.0, 1.0])
        self.assertEqual((zoom_step(2.5, 1), zoom_step(2.5, -1)), (3.0, 2.0))   # off the ladder (the wheel)
        self.assertEqual((zoom_step(4.0, 1, 5.9), zoom_step(5.9, 1, 5.9), zoom_step(5.9, -1, 5.9)), (5.9, 5.9, 4.0))

    def test_past_text(self):
        s = Settings()
        self.assertEqual(R.past_text(1600.0, s, 1585.4), "Past A′: the line runs from 0 to 1,585 ft.")
        self.assertEqual(R.past_text(-3.0, s, 1585.4), "Past A: the line runs from 0 to 1,585 ft.")
        self.assertEqual(R.past_text(1600.0, Settings(distance_labels="station", end_label="B'"), 1585.4),
                         "Past B′: the line runs from 0+00 to 15+85.")

    def test_strip_layout(self):
        # tiles per line = min(N, floor(room / need)), at least one; lines = ceil(N / per line)
        self.assertEqual(R.strip_layout(7, 150.0, 1084.0), (7, 1))
        self.assertEqual(R.strip_layout(7, 174.0, 1084.0), (6, 2))
        self.assertEqual(R.strip_layout(7, 174.0, 400.0), (2, 4))
        self.assertEqual(R.strip_layout(7, 500.0, 300.0), (1, 7))          # narrower than one tile: one a line
        self.assertEqual(R.strip_layout(3, 50.0, 2000.0), (3, 1))           # never more than N
        self.assertEqual(R.strip_layout(0, 50.0, 2000.0), (1, 1))

    def test_elevation_span(self):
        # the lines' lowest and highest values, and the plot's range (the cursor goes anywhere in it); a range that
        # is not a number is left out; (0, 100) with nothing at all
        lines = hover_lines(make_model())
        self.assertEqual(R.elevation_span(lines), (300.0, 560.0))
        self.assertEqual(R.elevation_span(lines, (400.0, 650.0)), (300.0, 650.0))
        self.assertEqual(R.elevation_span(lines, (-150.0, 1150.0)), (-150.0, 1150.0))
        self.assertEqual(R.elevation_span(lines, (None, mock.Mock())), (300.0, 560.0))
        self.assertEqual(R.elevation_span([], (NAN, 20.0)), (20.0, 20.0))
        self.assertEqual(R.elevation_span([]), (0.0, 100.0))

    def test_split_unit(self):
        self.assertEqual(R.split_unit("652.3 ft"), ("652.3", "ft"))
        self.assertEqual(R.split_unit("655.9–645.9 ft"), ("655.9–645.9", "ft"))
        self.assertEqual(R.split_unit("7+60"), ("7+60", ""))
        self.assertEqual(R.split_unit(NO_VALUE), (NO_VALUE, ""))

    def test_place_card(self):
        vw, vh, w, h = 1000.0, 400.0, 240.0, 150.0
        self.assertEqual(U.place_card(500, 300, w, h, vw, vh), (516.0, 138.0))      # right of and above
        self.assertEqual(U.place_card(900, 300, w, h, vw, vh), (644.0, 138.0))      # near the right edge: left
        self.assertEqual(U.place_card(500, 60, w, h, vw, vh), (516.0, 78.0))        # near the top: below
        self.assertEqual(U.place_card(900, 60, w, h, vw, vh), (644.0, 78.0))        # top right: left and below
        self.assertEqual(U.place_card(500, 390, w, h, vw, vh), (516.0, 228.0))
        self.assertEqual(U.place_card(-50, -40, w, h, vw, vh), (6.0, 4.0))           # (a guide off the view)
        self.assertEqual(U.place_card(300, 200, 1200.0, 500.0, vw, vh), (6.0, 4.0))  # too big: its top left
        for cx in range(0, 1001, 50):                                             # always inside when it fits
            for cy in range(0, 401, 25):
                x, y = U.place_card(cx, cy, w, h, vw, vh)
                self.assertTrue(U.INSIDE_X <= x <= vw - w - U.INSIDE_X and U.INSIDE_Y <= y <= vh - h - U.INSIDE_Y)

    def test_xy_text(self):
        self.assertEqual(U.xy_text((1249180.4, 641329.6)), "X 1,249,180 · Y 641,330")
        self.assertEqual(U.xy_text((380745.26, 5150321.94), 3.28084), "X 380,745.3 · Y 5,150,321.9")   # metres
        self.assertEqual(U.xy_text(None), "")


# ------------------------------------------------------------------ toolbar
class ToolbarTest(PreviewCase):
    def test_actions(self):
        pv = PreviewWidget()
        self.addCleanup(pv.deleteLater)
        names = [a.text() for a in pv.toolbar.actions() if a.text()]
        self.assertEqual(names, ["Fit", "Zoom out", "Zoom in", "Surfaces CSV…", "Readout row", "Popup"])
        for a in (pv.act_fit, pv.act_zoom_out, pv.act_zoom_in, pv.act_csv, pv.act_strip, pv.act_popup):
            self.assertFalse(a.icon().isNull(), a.text())
        self.assertIs(pv.toolbar.widgetForAction(pv.act_csv).toolButtonStyle(),
                      Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.assertEqual(pv.act_csv.iconText(), "Surfaces CSV…")
        self.assertIn(pv.zoom_label, pv.toolbar.findChildren(QLabel))
        acts = pv.toolbar.actions()
        self.assertEqual(acts.index(pv.act_popup), acts.index(pv.act_strip) + 1)      # side by side
        for a in (pv.act_strip, pv.act_popup):
            self.assertTrue(a.isCheckable() and a.isChecked() and a.isEnabled())      # preferences, always there
        self.assertEqual(pv.act_strip.toolTip(), "Readout row above the plot (on)")
        self.assertEqual(pv.act_popup.toolTip(), "Popup next to the cursor (on)")
        pv.act_popup.setChecked(False)
        self.assertEqual(pv.act_popup.toolTip(), "Popup next to the cursor (off)")
        # no section yet: nothing to zoom or export
        self.assertEqual([a.isEnabled() for a in (pv.act_fit, pv.act_zoom_out, pv.act_zoom_in, pv.act_csv)],
                         [False] * 4)
        self.assertFalse(hasattr(pv, "act_hover"), "the single crosshair toggle is gone")

    def test_enabled_states_follow_the_zoom(self):
        pv = self.shown()
        acts = (pv.act_fit, pv.act_zoom_out, pv.act_zoom_in, pv.act_csv)
        self.assertEqual([a.isEnabled() for a in acts], [False, False, True, True])
        self.assertEqual(pv.zoom_label.text(), "100%")
        steps = []
        while pv.act_zoom_in.isEnabled():
            pv.act_zoom_in.trigger()
            steps.append(pv.zoom_label.text())
        want = [f"{round(z * 100)}%" for z in P.ZOOM_LADDER[1:] if z < pv._z_max] + [f"{round(pv._z_max * 100)}%"]
        self.assertEqual(steps, want)                       # 150 % ... 800 % (less on a high-resolution screen)
        self.assertEqual([a.isEnabled() for a in acts], [True, True, False, True])
        pv.act_zoom_out.trigger()
        self.assertEqual(pv.zoom, zoom_step(pv._z_max, -1, pv._z_max))
        pv.act_fit.trigger()
        self.assertEqual((pv.zoom, pv.zoom_label.text()), (1.0, "100%"))
        pv.show_message("Choose a DEM")
        settle(pv)
        self.assertEqual([a.isEnabled() for a in acts], [False, False, False, False])

    def test_theme_colours(self):
        # QGIS's dark themes (Night Mapping, Blend of Gray) set the text colour but leave the button text to the
        # system (black in Windows' light mode): both toggles take the text colour; the status text the panel's
        # muted text for the theme (readable on a dark panel); both follow a theme change
        host = QWidget()                                   # (in a panel, as in QGIS: not a window of its own)
        self.addCleanup(host.deleteLater)
        pv = PreviewWidget(host)
        old = QApplication.palette()
        self.addCleanup(QApplication.setPalette, old)
        pal = QPalette(old)
        pal.setColor(QPalette.ColorRole.Window, QColor("#323232"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#aaaaaa"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
        QApplication.setPalette(pal)
        APP.processEvents()
        for a in (pv.act_strip, pv.act_popup):
            self.assertEqual(icon_ink(a), {"#aaaaaa"}, a.text())
        self.assertEqual(pv.status.styleSheet(), f"color: {theme_for(pal).muted.name()};")
        self.assertGreater(theme_for(pal).muted.lightness() - QColor("#323232").lightness(), 70)
        QApplication.setPalette(old)
        APP.processEvents()
        for a in (pv.act_strip, pv.act_popup):
            self.assertEqual(icon_ink(a), {old.color(QPalette.ColorRole.WindowText).name()}, a.text())
        self.assertEqual(pv.status.styleSheet(), f"color: {theme_for(old).muted.name()};")

    def test_the_two_icons_differ(self):
        pv = PreviewWidget()
        self.addCleanup(pv.deleteLater)
        a = pv.act_strip.icon().pixmap(24, 24).toImage()
        b = pv.act_popup.icon().pixmap(24, 24).toImage()
        self.assertNotEqual(a, b)
        # the row of three cells: two dividers inside one frame (ink in three columns across the middle row)
        mid = [a.pixelColor(x, 12).alpha() > 128 for x in range(24)]
        runs = sum(1 for x in range(1, 24) if mid[x] and not mid[x - 1])
        self.assertEqual(runs, 4, mid)

    def test_surfaces_csv_only_with_a_section(self):
        pv = PreviewWidget()
        self.addCleanup(pv.deleteLater)
        asked = []
        pv.exportSurfacesRequested.connect(lambda: asked.append(1))
        pv.act_csv.trigger()
        pv._export_surfaces()
        self.assertEqual(asked, [])
        pv.draw(make_model(), make_settings(), make_plan())
        self.assertTrue(pv.act_csv.isEnabled())
        pv.act_csv.trigger()
        self.assertEqual(asked, [1])
        pv.show_message("Choose a DEM")
        self.assertFalse(pv.act_csv.isEnabled())
        pv._export_surfaces()
        self.assertEqual(asked, [1])



# ------------------------------------------------------------------ zoom
class ZoomTest(PreviewCase):
    def test_zoom_keeps_the_figure_size_and_the_point_under_the_anchor(self):
        pv = self.shown()
        fig = pv.figure
        inches = fig.get_size_inches().copy()
        self.assertAlmostEqual(inches[0], pv._vp[0] / P.BASE_DPI)
        pt = (1700.0, 530.0)
        anchor = vp_of(pv, *pt)
        for z in (1.2, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 5.0, 2.5, 1.3, 1.0):
            pv.set_zoom(z, anchor)
            self.assertAlmostEqual(pv.zoom, min(z, pv._z_max))
            self.assertAlmostEqual(fig.get_size_inches()[0], inches[0], places=9)
            self.assertAlmostEqual(fig.get_size_inches()[1], inches[1], delta=1.0 / fig.dpi)
            self.assertAlmostEqual(fig.dpi, P.BASE_DPI * pv.canvas.width() / pv._vp[0] * pv.canvas.device_pixel_ratio)
            self.assertEqual(pv.canvas.width(), max(pv._vp[0], round(pv._vp[0] * pv.zoom)))
            self.assertNear(vp_of(pv, *pt), anchor, 1.0, f"zoom {z}")
        settle(pv)
        self.assertEqual(pv.canvas.size(), pv.scroll.viewport().size())

    def test_zoom_never_lays_the_plot_out_again_but_a_new_panel_size_does(self):
        pv = self.shown()
        dpis = []
        real = F.draw_preview

        def counted(fig, *args):
            dpis.append(fig.dpi)
            return real(fig, *args)

        with mock.patch("xsections.render.figure.draw_preview", side_effect=counted):
            mid = QPointF(500.0, 200.0)
            pv.set_zoom(2.0, mid)
            settle(pv)
            wheel(pv, mid)
            pv._flush_wheel()
            settle(pv)
            wheel(pv, mid, dy=-120, mods=Qt.KeyboardModifier.ShiftModifier)    # pan
            pv.set_zoom(4.0)
            settle(pv)
            self.assertEqual(dpis, [], "no re-layout while zooming and panning")
            pv.resize(900, 460)                                                   # the panel changes size
            settle(pv)
            self.assertGreaterEqual(len(dpis), 1)
            self.assertEqual(set(dpis), {P.BASE_DPI * pv.canvas.device_pixel_ratio}, "laid out at the 100 % dpi")
        self.assertEqual(pv.zoom, 4.0)                                            # the zoom is kept
        self.assertAlmostEqual(pv.figure.dpi,
                               P.BASE_DPI * pv.canvas.width() / pv._vp[0] * pv.canvas.device_pixel_ratio)
        self.assertAlmostEqual(pv.figure.get_size_inches()[0], pv._vp[0] / P.BASE_DPI)

    def test_the_same_line_keeps_the_zoom_a_new_line_fits(self):
        pv = self.shown()
        pv.set_zoom(3.0)
        pv.draw(make_model(), make_settings(), make_plan())               # a refresh of the same line
        settle(pv)
        self.assertEqual(pv.zoom, 3.0)
        self.assertEqual(pv.canvas.width(), round(pv._vp[0] * 3.0))
        other = QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in reversed(LINE)]).asWkt()
        pv.draw(make_model(line_wkt=other), make_settings(), make_plan())
        settle(pv)
        self.assertEqual(pv.zoom, 1.0)
        pv.set_zoom(2.0)
        pv.show_message("Choose a DEM")                                   # a message is never zoomed
        settle(pv)
        self.assertEqual((pv.zoom, pv.canvas.size()), (1.0, pv.scroll.viewport().size()))
        pv.set_zoom(2.0)
        self.assertEqual(pv.zoom, 1.0)

    def test_zoom_limit_follows_the_panel(self):
        pv = self.shown()
        vw, vh = pv._vp
        self.assertEqual(pv._z_max, zoom_limit(vw, vh, pv.canvas.device_pixel_ratio))
        pv.set_zoom(50.0)
        self.assertEqual(pv.zoom, pv._z_max)
        self.assertFalse(pv.act_zoom_in.isEnabled())
        pv.resize(2000, 1000)                                             # a big panel: a lower limit
        settle(pv)
        self.assertLess(pv._z_max, 8.0)
        self.assertEqual(pv._z_max, zoom_limit(*pv._vp, pv.canvas.device_pixel_ratio))
        self.assertEqual(pv.zoom, pv._z_max)

    def test_a_new_screen_ratio_keeps_the_pixel_budget(self):
        # moved to a screen of another ratio: the same logical size (no Resize), matplotlib redraws at the new ratio
        pv = self.shown()
        canvas = pv.canvas
        r0 = canvas.device_pixel_ratio
        self.addCleanup(self._unstub_ratio, canvas)
        pv.set_zoom(6.0)
        settle(pv)
        self.assertEqual(pv.zoom, 6.0)
        inches = pv.figure.get_size_inches().copy()
        canvas.devicePixelRatioF = lambda: 2.0 * r0
        canvas._update_pixel_ratio()
        settle(pv)
        self.assertEqual(canvas.device_pixel_ratio, 2.0 * r0)
        self.assertAlmostEqual(pv._z_max, zoom_limit(*pv._vp, 2.0 * r0))
        self.assertLess(pv._z_max, 6.0)
        self.assertAlmostEqual(pv.zoom, pv._z_max)                     # lowered to the new limit
        w, h = canvas.get_width_height(physical=True)
        self.assertLessEqual(w * h, P.PIXEL_BUDGET * 1.01)
        np.testing.assert_allclose(pv.figure.get_size_inches(), inches, atol=0.02)   # the same layout size
        self.assertFalse(pv.act_zoom_in.isEnabled())
        self.assertEqual(pv.zoom_label.text(), f"{round(pv.zoom * 100)}%")
        self._unstub_ratio(canvas)                                      # back on the first screen
        settle(pv)
        self.assertAlmostEqual(pv._z_max, zoom_limit(*pv._vp, r0))
        self.assertTrue(pv.act_zoom_in.isEnabled())
        with mock.patch.object(pv, "_ratio_changed") as changed:       # a show with the same ratio: nothing
            canvas._update_pixel_ratio()
        changed.assert_not_called()

    @staticmethod
    def _unstub_ratio(canvas):
        if "devicePixelRatioF" in canvas.__dict__:
            del canvas.devicePixelRatioF
            canvas._update_pixel_ratio()

    def test_a_new_panel_size_keeps_the_spot_in_the_middle(self):
        for (w0, h0), (w1, h1) in (((1000, 460), (1000, 300)), ((1800, 330), (1000, 330)),
                                   ((1000, 460), (1600, 460))):
            pv = self.shown(w=w0, h=h0)
            pv.set_zoom(6.0, vp_of(pv, 900.0, 500.0))
            settle(pv)
            spot = data_at(pv, QPointF(pv._vp[0] / 2.0, pv._vp[1] / 2.0))
            pv.resize(w1, h1)
            settle(pv)
            self.assertEqual(pv.zoom, 6.0)
            self.assertNear(vp_of(pv, *spot), QPointF(pv._vp[0] / 2.0, pv._vp[1] / 2.0), 2.0, (w0, h0, w1, h1))
        # a refresh of the same line with another elevation range: the same spot stays in the middle too
        pv = self.shown()
        pv.set_zoom(6.0, vp_of(pv, 900.0, 500.0))
        settle(pv)
        mid = QPointF(pv._vp[0] / 2.0, pv._vp[1] / 2.0)
        spot = data_at(pv, mid)
        plan = make_plan()
        plan.z_max = 700.0
        pv.draw(make_model(), make_settings(), plan)
        settle(pv)
        self.assertEqual(pv.zoom, 6.0)
        self.assertEqual(pv._ax.get_ylim()[1], 700.0)
        self.assertNear(vp_of(pv, *spot), mid, 2.0)

    def test_a_new_readout_height_lays_the_plot_out_once(self):
        # narrow: the section's readout wraps onto more lines than the message's one line
        pv = self.shown(w=420, h=300)
        pv.show_message("Choose a DEM")
        settle(pv)
        before = pv.readout.height()
        sizes = []
        real = F.draw_preview

        def counted(fig, *args):
            sizes.append(tuple(fig.get_size_inches()))
            return real(fig, *args)

        with mock.patch("xsections.render.figure.draw_preview", side_effect=counted):
            pv.draw(make_model(), make_settings(), make_plan())
            settle(pv)
            APP.processEvents()
        self.assertGreater(pv.readout.height(), before)
        self.assertEqual(len(sizes), 1, "laid out once")
        self.assertAlmostEqual(sizes[0][1], pv._vp[1] / P.BASE_DPI, places=6)   # for the final viewport
        self.assertEqual(pv.scroll.viewport().height(), pv._vp[1])
        self.assertFalse(pv._resize_timer.isActive())

    def test_wheel_zooms_around_the_mouse_in_one_step_per_burst(self):
        pv = self.shown()
        pt = (2200.0, 520.0)
        at = vp_of(pv, *pt)
        with mock.patch.object(pv, "set_zoom", wraps=pv.set_zoom) as sz:
            wheel(pv, at)
            wheel(pv, at)                                    # two notches before the timer fires: one step
            self.assertTrue(pv._wheel_timer.isActive())
            pv._wheel_timer.stop()
            pv._flush_wheel()
            self.assertEqual(sz.call_count, 1)
        self.assertAlmostEqual(pv.zoom, 1.2 ** 2)
        self.assertNear(vp_of(pv, *pt), at, 1.0)
        wheel(pv, at, dy=-60)                                # half a notch out (a fine wheel or touchpad)
        pv._flush_wheel()
        self.assertAlmostEqual(pv.zoom, 1.2 ** 1.5)
        pv.set_zoom(1.0)
        wheel(pv, at, dy=-120)                               # out at 100 %: nothing
        pv._flush_wheel()
        self.assertEqual(pv.zoom, 1.0)

    def test_shift_wheel_and_sideways_wheel_pan(self):
        pv = self.shown()
        pv.set_zoom(3.0)
        bar = pv.scroll.horizontalScrollBar()
        x0 = bar.value()
        wheel(pv, QPointF(400.0, 200.0), dy=-120, mods=Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(bar.value(), x0 + 60)
        wheel(pv, QPointF(400.0, 200.0), dx=240)
        self.assertEqual(bar.value(), x0 - 60)
        self.assertEqual(pv.zoom, 3.0)
        self.assertAlmostEqual(pv._fx, (bar.value() + pv._vp[0] / 2.0) / pv.canvas.width())

    def test_drag_pans_and_double_click_fits(self):
        pv = self.shown()
        pv.set_zoom(3.0)
        settle(pv)
        h, v = pv.scroll.horizontalScrollBar(), pv.scroll.verticalScrollBar()
        h0, v0 = h.value(), v.value()
        start, end = QPointF(500.0, 200.0), QPointF(400.0, 150.0)
        pt = data_at(pv, start)
        move(pv, start)
        self.assertTrue(pv._marks_on)
        mouse(pv, QEvent.Type.MouseButtonPress, start, Left, Left)
        self.assertIsNotNone(pv._drag)
        self.assertFalse(pv._marks_on, "the marks hide while dragging")
        move(pv, QPointF(450.0, 180.0), buttons=Left)
        move(pv, end, buttons=Left)
        mouse(pv, QEvent.Type.MouseButtonRelease, end, Left, NoButton)
        self.assertIsNone(pv._drag)
        self.assertEqual((h.value(), v.value()), (h0 + 100, v0 + 50))
        self.assertNear(vp_of(pv, *pt), end, 1.0, "the plot moved with the mouse")
        self.assertTrue(pv._marks_on, "back after the drag")
        mouse(pv, QEvent.Type.MouseButtonDblClick, end, Left, Left)
        self.assertEqual(pv.zoom, 1.0)
        mouse(pv, QEvent.Type.MouseButtonPress, end, Left, Left)        # at 100 % a press is not a drag
        self.assertIsNone(pv._drag)
        mouse(pv, QEvent.Type.MouseButtonRelease, end, Left, NoButton)

    def test_keys(self):
        pv = self.shown()
        key(pv, Qt.Key.Key_Plus, "+")
        self.assertEqual(pv.zoom, 1.5)
        key(pv, Qt.Key.Key_Equal, "=")
        self.assertEqual(pv.zoom, 2.0)
        key(pv, Qt.Key.Key_Minus, "-")
        self.assertEqual(pv.zoom, 1.5)
        key(pv, Qt.Key.Key_0, "0")
        self.assertEqual(pv.zoom, 1.0)
        override = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Plus, NoMod, "+")
        override.ignore()
        QApplication.sendEvent(pv.canvas, override)
        self.assertTrue(override.isAccepted(), "+ belongs to the preview while it has the focus")
        ctrl = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier, "+")
        ctrl.ignore()
        QApplication.sendEvent(pv.canvas, ctrl)
        self.assertFalse(ctrl.isAccepted(), "Ctrl++ stays the main window's")
        self.assertEqual(pv.zoom, 1.0)



# ------------------------------------------------------------------ hover: the readout strip
class HoverTest(PreviewCase):
    def expect_values(self, pv, station, cz):
        """The strip's tiles for a hover at (station, cz), from core.hover."""
        s, m = pv._settings, pv._model
        lines = hover_lines(m)
        hv = hover_values(lines, station, m.length, cz)
        cells = [(f"{distance_text(station, s)} from A", elev_text(cz), depth_text(hv.ground_z, cz), False)]
        for i, (ln, v) in enumerate(zip(lines, hv.values)):
            name = "Ground" if ln.ground else ln.name
            if math.isfinite(v):
                cells.append((name, elev_text(v), "" if ln.ground else depth_text(hv.ground_z, v), i == hv.nearest))
            else:
                cells.append((name, NO_VALUE, "no DEM data" if ln.ground else "no data", False))
        return hv, cells

    def test_hover_reads_out_the_core_values(self):
        pv = self.shown()
        for station, z in ((1500.0, 520.0), (200.0, 503.0), (3950.0, 450.0), (2500.0, 600.0)):
            at = vp_of(pv, station, z)
            move(pv, at)
            st, cz = data_at(pv, at)
            hv, cells = self.expect_values(pv, st, cz)
            self.assertEqual(pv.readout.mode, "values")
            self.assertEqual(pv.readout.cells(), cells, station)
            self.assertEqual(self.events[-1][0], "changed")
            self.assertAlmostEqual(self.events[-1][1], st)
            self.assertEqual(self.events[-1][2], -1)
        # in the DEM gap the ground reads "—" and "no DEM data", and nothing has a depth
        move(pv, vp_of(pv, 3950.0, 450.0))
        cells = pv.readout.cells()
        self.assertEqual(cells[1][1:3], (NO_VALUE, "no DEM data"))
        self.assertEqual([c[2] for c in cells[2:]], ["", "", ""])
        # the dots: one per line with a value inside the plot (not the model bottom, below it)
        move(pv, vp_of(pv, 1500.0, 520.0))
        visible = [d.get_visible() for d in pv._marks.dots]
        self.assertEqual(visible, [True, True, True, False])
        hv, _ = self.expect_values(pv, *data_at(pv, vp_of(pv, 1500.0, 520.0)))
        self.assertEqual(hv.nearest, 0)
        self.assertEqual(pv._marks.dots[0].get_markersize(), P.DOT_NEAR_MS)
        self.assertEqual(pv._marks.dots[1].get_markersize(), P.DOT_MS)
        self.assertTrue(pv._marks.cursor.get_visible() and pv._marks.ytag.get_visible())
        self.assertEqual(pv._marks.xtag.get_text(), "1,500")

    def test_the_strip_is_a_grid_of_equal_tiles(self):
        pv = self.shown()
        ro = pv.readout
        m = pv._model
        rows = [len(hit_cells(h, pv._settings)) for h in m.hits]
        self.assertEqual(ro.columns, max([1 + len(hover_lines(m))] + rows))   # 7: MW-2's row is the longest
        self.assertEqual(ro.columns, 7)
        self.assertEqual(ro.per_line, min(ro.columns, int((ro.width() - 2 * R.ROW_PAD_X) // ro.tile_need)))
        self.assertEqual(ro.tile_width(), math.floor((ro.width() - 2 * R.ROW_PAD_X) / ro.per_line))
        self.assertGreaterEqual(ro.tile_width(), ro.tile_need)
        self.assertEqual(ro.height(), ro.line_count * ro.pitch + 2 * R.ROW_PAD_Y + 1)
        self.assertGrid(ro)
        move(pv, vp_of(pv, 1500.0, 520.0))
        self.assertEqual(len(ro.shown()), 5)                       # a shorter row: its last tiles left empty
        self.assertGrid(ro)
        move(pv, vp_of(pv, 2900.0, 520.0))
        self.assertEqual(len(ro.shown()), 7)
        self.assertGrid(ro)
        # the tiles' text: a muted label (swatch / water level symbol), the value, the detail; the nearest tinted
        tiles = [t for _, t in ro.shown()]
        self.assertTrue(tiles[0].lead and tiles[0].value == "MW-2")
        self.assertIsNotNone(tiles[5].icon)
        move(pv, vp_of(pv, 1500.0, 520.0))
        tiles = [t for _, t in ro.shown()]
        self.assertEqual([t.swatch is not None for t in tiles], [False, True, True, True, True])
        self.assertEqual([t.hi for t in tiles], [False, True, False, False, False])

    def test_every_tile_the_same_width_always(self):
        # hundreds of hovers: the line (bgs and ags, the DEM gap, a no-data cell), explorations, guides from the
        # map (on and off view), notes: the tiles never change width, place or height, and the text fits them
        pv = self.shown()
        ro = pv.readout
        rects = [QRectF(r) for r in ro.tile_rects()]
        widths = {r.width() for r in rects}
        self.assertEqual(len(widths), 1)
        height = ro.height()
        seen, modes = set(), set()

        def check(where):
            self.assertEqual(ro.tile_rects(), rects, where)
            self.assertEqual(ro.height(), height, where)
            self.assertEqual(ro.overflows(), [], (where, ro.text()))
            self.assertGrid(ro, where)
            for _, t in ro.shown():                                # (sized once for the widest number any can show)
                if not t.lead:                                     # (a name is not measured: cut to fit)
                    self.assertLessEqual(ro._tile_need(t), ro.tile_need, (where, t))
            modes.add(ro.mode)
            for _, t in ro.shown():
                if t.detail.endswith(("bgs", "ags")):
                    seen.add(t.detail[-3:])
                elif t.detail.startswith("no "):
                    seen.add(t.detail)
                elif t.detail.endswith("off view"):
                    seen.add("off view")

        for station in np.linspace(0.0, L, 61):
            for z in (410.0, 498.0, 512.0, 545.0, 640.0):
                move(pv, vp_of(pv, float(station), z))
                check((station, z))
        for h in pv._model.hits:
            for z in (h.top, (h.top + h.bottom) / 2.0, h.bottom):
                move(pv, vp_of(pv, h.station, z))
                self.assertEqual(ro.mode, "cells")
                check(h.label)
        for station in np.linspace(0.0, L, 40):
            pv.show_guide(float(station), 37.0 + station / 10.0, "L" if station % 2 else "R")
            check(("map", station))
        pv.set_zoom(4.0, QPointF(10.0, pv._vp[1] / 2.0))
        settle(pv)
        for station in (100.0, 2500.0, 4400.0):
            pv.show_guide(station, 20.0, "R")                     # in view, then off it
            check(("map zoomed", station))
        pv.fit()
        move(pv, vp_of(pv, L + 5.0, 520.0))                        # past the end: a note
        check("past")
        leave(pv)
        check("left")
        self.assertEqual(seen, {"bgs", "ags", "no DEM data", "no data", "off view"})
        self.assertEqual(modes, {"values", "cells", "idle"})

    def test_a_tall_plot_still_fits_the_cursor(self):
        # a plot range far beyond the lines (a manual elevation range): the cursor's elevation and depth anywhere in
        # it (here four digits, the lines only three) still fit the tiles, and the popup's card keeps its size
        plan = make_plan()
        plan.z_min, plan.z_max = -150.0, 1150.0
        pv = self.shown(plan=plan)
        ro, pp = pv.readout, pv.popup
        rects = [QRectF(r) for r in ro.tile_rects()]
        size = None
        for station in (1200.0, 1700.0, 2200.0):                  # (away from the explorations)
            for z in (1140.0, 1000.0, 700.0, -140.0):
                move(pv, vp_of(pv, station, z))
                self.assertEqual(ro.mode, "values")
                self.assertEqual(ro.overflows(), [], ro.text())
                self.assertEqual(ro.tile_rects(), rects)
                for _, t in ro.shown():                                # measured for: within the width a tile needs
                    if not t.lead:
                        self.assertLessEqual(ro._tile_need(t), ro.tile_need, t)
                size = size or pp.card_rect().size()
                self.assertEqual(pp.card_rect().size(), size)
                right = pp.header()[1]
                self.assertLessEqual(pp.m_head.horizontalAdvance(pp.header()[0]) + U.HEAD_GAP
                                     + pp.m_text.horizontalAdvance(right),
                                     size.width() - U.PAD_L - U.PAD_R - 2.0, right)
        self.assertEqual(ro.cells()[0][1], elev_text(data_at(pv, vp_of(pv, 2200.0, -140.0))[1]))
        self.assertRegex(pv.readout.cells()[0][2], r"^\d{3}\.\d bgs$")

    def test_the_strip_wraps_when_narrow_and_keeps_equal_tiles(self):
        pv = self.shown(w=420)
        ro = pv.readout
        self.assertLess(ro.per_line, ro.columns)
        self.assertGreater(ro.line_count, 1)
        self.assertEqual(ro.line_count, -(-ro.columns // ro.per_line))
        self.assertGreater(len({r.top() for r in ro.tile_rects()}), 1)
        self.assertEqual(len({r.width() for r in ro.tile_rects()}), 1)
        self.assertGrid(ro)
        height = ro.height()
        self.assertEqual(height, ro.line_count * ro.pitch + 2 * R.ROW_PAD_Y + 1)
        rects = [QRectF(r) for r in ro.tile_rects()]
        for station, z in ((100.0, 520.0), (1500.0, 520.0), (3950.0, 450.0), (2900.0, 520.0), (300.0, 495.0)):
            move(pv, vp_of(pv, station, z))
            self.assertEqual(ro.height(), height)
            self.assertEqual(ro.overflows(), [])
            self.assertEqual(ro.tile_rects(), rects, station)
            self.assertGrid(ro, station)
        pv.resize(1400, 460)                                       # wider: fewer lines, the same rule
        settle(pv)
        self.assertLess(ro.height(), height)
        self.assertGrid(ro)
        self.assertEqual(len({r.width() for r in ro.tile_rects()}), 1)

    def test_pointing_at_an_exploration(self):
        pv = self.shown()
        s = pv._settings
        hits = pv._model.hits
        move(pv, vp_of(pv, 2900.0, 520.0))                             # on MW-2's line
        self.assertEqual(self.events[-1], ("changed", 2900.0, 1))
        self.assertEqual(pv.readout.mode, "cells")
        self.assertEqual([c[:3] for c in pv.readout.cells()], [c[:3] for c in strip_cells(hits[1], s, pv._model)])
        titles = [c[0] for c in pv.readout.cells()]
        self.assertEqual(titles, ["Monitoring Well", "From A", "Top", "Total depth", "Screen", "6/12/2024", "ATD"])
        m = pv._marks
        self.assertTrue(m.band.get_visible() and m.guide.get_visible())
        self.assertFalse(m.cursor.get_visible() or m.ytag.get_visible() or any(d.get_visible() for d in m.dots))
        self.assertEqual(m.xtag.get_text(), "2,900")
        # the label above the top counts; a little beside the line does not
        r = pv.canvas.device_pixel_ratio
        above = vp_of(pv, 300.0, 508.2) - QPointF(0.0, 0.5 * pv.figure.dpi / r)
        move(pv, above)
        self.assertEqual(self.events[-1], ("changed", 300.0, 0))
        self.assertEqual(pv.readout.cells()[0][:2], ("Boring", "B-1"))
        self.assertEqual(pv.readout.cells()[-1][:3], ("Water level", NO_VALUE, "none"))
        beside = vp_of(pv, 300.0, 495.0) + QPointF(P.HIT_DX_PX + 2.0, 0.0)
        move(pv, beside)
        self.assertEqual(self.events[-1][2], -1)
        self.assertEqual(pv.readout.mode, "values")

    def test_past_the_end_and_leaving(self):
        pv = self.shown()
        move(pv, vp_of(pv, 1000.0, 520.0))
        move(pv, vp_of(pv, 4594.0, 520.0))                             # inside the frame, past A'
        self.assertEqual(pv.readout.idle_text, R.past_text(4594.0, pv._settings, L))
        self.assertIn("Past A′: the line runs from 0 to 4,588 ft.", pv.readout.idle_text)
        self.assertEqual(self.events[-1], ("left",))
        self.assertFalse(pv._marks_on)
        self.assertFalse(pv.popup.isVisible())
        move(pv, vp_of(pv, 1000.0, 520.0))
        self.assertEqual(self.events[-1][0], "changed")
        move(pv, QPointF(5.0, 5.0))                                    # off the frame
        self.assertEqual(self.events[-1], ("left",))
        self.assertEqual(pv.readout.idle_text, R.IDLE_TEXT)
        move(pv, vp_of(pv, 1000.0, 520.0))
        leave(pv)
        self.assertEqual(self.events[-1], ("left",))
        self.assertEqual(pv.readout.idle_text, R.IDLE_TEXT)
        self.assertEqual(pv.readout.mode, "idle")
        leave(pv)
        self.assertEqual(self.events.count(("left",)), 3, "hoverLeft once per hover")

    def test_marks_are_blitted_and_wiped(self):
        pv = self.shown()
        pv.act_popup.setChecked(False)                                  # (the card would be in the buffer's way)
        pv.set_zoom(2.0, QPointF(300.0, 200.0))
        settle(pv)
        clean = buffer(pv)
        at = vp_of(pv, 2200.0, 520.0)
        move(pv, at)
        shown = buffer(pv)
        x = int(round(pv._display_xy(at)[0]))
        changed = (shown[:, x, :3] != clean[:, x, :3]).any(axis=1)
        bb, win = pv._ax.bbox, pv._window()
        in_view = min(bb.y1, win.y1) - max(bb.y0, win.y0)               # (the marks are clipped to the view)
        self.assertGreater(changed.sum(), 0.9 * in_view, "the guide runs down the frame in the buffer")
        rows = np.flatnonzero(changed)
        self.assertGreaterEqual(rows.min(), pv.canvas.height() * pv.canvas.device_pixel_ratio - win.y1 - 1)
        self.assertLessEqual(rows.max(), pv.canvas.height() * pv.canvas.device_pixel_ratio - win.y0 + 1)
        self.assertLess(shown[changed, x, :3].mean(), 128, "a dark (navy) guide")
        wheel(pv, at, dy=-240, mods=Qt.KeyboardModifier.ShiftModifier)   # pan with the marks on
        self.assertFalse(np.array_equal(buffer(pv), clean))
        leave(pv)
        self.assertTrue(np.array_equal(buffer(pv), clean), "no marks left anywhere in the buffer")
        self.assertTrue(all(a.get_animated() for a in pv._marks.artists()), "never part of a full draw")
        self.assertFalse(any(a in pv._ax.get_children() for a in pv._marks.artists()))

    def test_the_popup_never_reaches_the_plot_buffer(self):
        pv = self.shown()
        clean = buffer(pv)
        move(pv, vp_of(pv, 1500.0, 520.0))
        self.assertTrue(pv.popup.isVisible())
        card = pv.popup.card_rect()
        r = pv.canvas.device_pixel_ratio
        x0, y0 = int((card.left() - pv.canvas.x()) * r) + 2, int((card.top() - pv.canvas.y()) * r) + 2
        x1, y1 = int((card.right() - pv.canvas.x()) * r) - 2, int((card.bottom() - pv.canvas.y()) * r) - 2
        guide_x = int(round(pv._display_xy(vp_of(pv, 1500.0, 520.0))[0]))
        cols = [c for c in range(x0, x1) if abs(c - guide_x) > 6]
        self.assertTrue(np.array_equal(buffer(pv)[y0:y1, cols], clean[y0:y1, cols]), "a widget over the plot")

    def test_tags_are_painted_over_the_plot_not_into_it(self):
        pv = self.shown()
        pv.act_popup.setChecked(False)
        clean = buffer(pv)
        at = vp_of(pv, 1500.0, 520.0)
        move(pv, at)
        m = pv._marks
        cz = data_at(pv, at)[1]
        self.assertEqual((m.xtag.get_text(), m.ytag.get_text()), ("1,500", elev_text(cz).removesuffix(" ft")))
        r = pv.canvas.device_pixel_ratio
        H = pv.canvas.height() * r
        shot = pv.canvas.grab().toImage()
        for t in (m.xtag, m.ytag):
            b = t.get_window_extent()
            # the box's corner just inside it: navy on screen; the plot's buffer there unchanged
            x, y = int(b.x0 + 1.5 * r), int(H - b.y1 + 1.5 * r)
            self.assertEqual(shot.pixelColor(int(x / r), int(y / r)).name(), R.NAVY, t.get_text())
            self.assertTrue(np.array_equal(buffer(pv)[y, x], clean[y, x]))
            self.assertTrue(pv._window().x0 <= b.x0 and b.x1 <= pv._window().x1)
        leave(pv)
        shot = pv.canvas.grab().toImage()
        b = m.xtag.get_window_extent()
        x, y = int((b.x0 + 1.5 * r) / r), int((H - b.y1 + 1.5 * r) / r)
        self.assertNotEqual(shot.pixelColor(x, y).name(), R.NAVY, "gone with the hover")

    def test_marks_keep_their_size_on_screen(self):
        pv = self.shown()
        r = pv.canvas.device_pixel_ratio
        at = vp_of(pv, 1500.0, 520.0)
        sizes = []
        for z in (1.0, 2.0, 4.0, 8.0):
            pv.set_zoom(z, at)
            settle(pv)
            move(pv, at)
            z = pv.zoom                                              # (8 may be over the limit)
            m = pv._marks
            self.assertAlmostEqual(m.guide.get_linewidth(), P.GUIDE_LW / z)
            self.assertAlmostEqual(m.cursor.get_linewidth(), P.CURSOR_LW / z)
            self.assertAlmostEqual(m.dots[1].get_markersize(), P.DOT_MS / z)
            ext = m.xtag.get_window_extent(pv.canvas.get_renderer())
            sizes.append((ext.width / r, ext.height / r))
            win = pv._window()                                       # the tags stay inside the view
            for t in (m.xtag, m.ytag):
                e = t.get_window_extent(pv.canvas.get_renderer())
                self.assertTrue(win.x0 <= e.x0 and e.x1 <= win.x1 and win.y0 <= e.y0 and e.y1 <= win.y1, z)
        for w, h in sizes[1:]:
            self.assertAlmostEqual(w, sizes[0][0], delta=1.5)
            self.assertAlmostEqual(h, sizes[0][1], delta=1.5)

    def test_guide_from_the_map(self):
        pv = self.shown()
        pv.show_guide(1500.0, 49.6, "L")
        cells = pv.readout.cells()
        self.assertEqual(cells[0], ("1,500 ft from A", "50 ft", "left of the line", False))
        hv = hover_values(hover_lines(pv._model), 1500.0, L)
        self.assertEqual([c[1] for c in cells[1:]], [elev_text(v) if math.isfinite(v) else NO_VALUE
                                                     for v in hv.values])
        self.assertFalse(any(c[3] for c in cells), "no cursor: no line is nearest")
        m = pv._marks
        self.assertTrue(m.guide.get_visible() and m.xtag.get_visible())
        self.assertFalse(m.cursor.get_visible() or m.ytag.get_visible() or m.edge.get_visible())
        self.assertEqual(self.events, [], "the map already knows: no hoverChanged")
        # zoomed in on the start: a spot near the end is out of view; an edge tag points to it, no scrolling
        pv.set_zoom(4.0, QPointF(0.0, pv._vp[1] / 2.0))
        scroll = (pv.scroll.horizontalScrollBar().value(), pv.scroll.verticalScrollBar().value())
        pv.show_guide(4000.0, 20.0, "R")
        self.assertEqual(pv.readout.cells()[0], ("4,000 ft from A", "20 ft", "right of the line · off view", False))
        self.assertTrue(m.edge.get_visible())
        self.assertEqual(m.edge.get_text(), "4,000 ft ▸")
        self.assertFalse(m.guide.get_visible() or m.xtag.get_visible())
        self.assertEqual((pv.scroll.horizontalScrollBar().value(), pv.scroll.verticalScrollBar().value()), scroll)
        e = m.edge.get_window_extent(pv.canvas.get_renderer())
        self.assertLessEqual(e.x1, pv._window().x1)
        pv.show_guide(100.0, 20.0, "R")                               # in view again
        self.assertFalse(m.edge.get_visible())
        self.assertEqual(pv.readout.cells()[0][2], "right of the line")
        pv.show_guide(5000.0, 20.0, "R")                               # off the line: nothing
        self.assertFalse(pv._marks_on)
        pv.show_guide(100.0, 20.0, "R")
        pv.hide_guide()
        self.assertEqual((pv.readout.idle_text, pv._marks_on), (R.IDLE_TEXT, False))
        # a hover with the mouse is not the map's to hide
        move(pv, vp_of(pv, 300.0, 600.0))
        pv.hide_guide()
        self.assertEqual(pv.readout.mode, "values")
        self.assertEqual(self.events.count(("left",)), 0)

    def test_zoom_and_pan_rehover_under_a_still_mouse(self):
        pv = self.shown()
        at = QPointF(600.0, 250.0)
        move(pv, at)
        before = self.events[-1][1]
        pv.set_zoom(3.0)                                                # about the centre: the plot moves
        st, _ = data_at(pv, at)
        self.assertNotAlmostEqual(st, before, places=0)
        self.assertAlmostEqual(self.events[-1][1], st)
        wheel(pv, at, dy=-120, mods=Qt.KeyboardModifier.ShiftModifier)
        st2, _ = data_at(pv, at)
        self.assertGreater(st2, st)
        self.assertAlmostEqual(self.events[-1][1], st2)
        self.assertEqual(pv.popup.header()[0], f"{distance_text(st2, pv._settings)} from A")

    def test_a_new_drawing_ends_the_hover(self):
        pv = self.shown()
        move(pv, vp_of(pv, 1500.0, 520.0))
        pv.draw(make_model(), make_settings(distance_labels="station"), make_plan())
        settle(pv)
        self.assertEqual(self.events[-1], ("left",))
        self.assertEqual(pv.readout.idle_text, R.IDLE_TEXT)
        self.assertFalse(pv.popup.isVisible())
        move(pv, vp_of(pv, 1500.0, 520.0))
        self.assertEqual(pv.readout.cells()[0][0], "15+00 from A")
        self.assertEqual(pv.popup.header()[0], "15+00 from A")
        self.assertEqual(pv._marks.xtag.get_text(), "15+00")
        pv.show_message("Choose a DEM")
        self.assertEqual(self.events[-1], ("left",))
        self.assertFalse(pv.popup.isVisible())
        settle(pv)
        move(pv, QPointF(400.0, 200.0))
        self.assertEqual(self.events[-1], ("left",))
        self.assertIsNone(pv._marks)

    def test_the_note_asks_for_a_hover_only_with_a_section(self):
        fresh = PreviewWidget()
        self.addCleanup(fresh.deleteLater)
        self.assertEqual((fresh.readout.mode, fresh.readout.idle_text), ("idle", ""))
        pv = self.shown()
        self.assertEqual(pv.readout.idle_text, R.IDLE_TEXT)
        pv.show_message("No DEM data along the line.")
        settle(pv)
        self.assertEqual(pv.readout.idle_text, "")
        pv.draw(make_model(), make_settings(), make_plan())          # the first section after a message
        settle(pv)
        self.assertEqual(pv.readout.idle_text, R.IDLE_TEXT)
        with mock.patch("xsections.render.figure.draw_preview", side_effect=RuntimeError("boom")):
            pv.draw(make_model(), make_settings(), make_plan())
            settle(pv)
        self.assertIn("boom", pv.last_error)
        self.assertEqual(pv.readout.idle_text, "")                  # "Preview failed": nothing to point at
        pv.render_pending()
        settle(pv)
        self.assertEqual(pv.readout.idle_text, R.IDLE_TEXT)

    def test_failed_preview_has_no_hover(self):
        pv = self.shown()
        with mock.patch("xsections.render.figure.draw_preview", side_effect=RuntimeError("boom")):
            pv.render_pending()
        settle(pv)
        self.assertIn("boom", pv.last_error)
        move(pv, QPointF(400.0, 200.0))
        self.assertEqual(self.events, [])
        self.assertEqual(pv.readout.mode, "idle")
        self.assertFalse(pv.popup.isVisible())


# ------------------------------------------------------------------ the compact strip (0.3.4)
SEGOE = ("Segoe UI", 9)                 # the application's font on his PC (the test run's own font is narrower)


class CompactStripTest(PreviewCase):
    """0.3.4, compact always: small type, one row of equal tiles down to a 700 px preview (the strip 4 px narrower),
    every number whole, labels, details and names cut with "…" (a detail's " · off view" / " · +N here" kept
    whole), the first tile "1,500 ft from A" (its distance in navy), the ground tile "Ground"."""

    def segoe(self, pv):
        """The strip in Segoe UI 9 pt (it lays itself out again for the font)."""
        pv.readout.setFont(QFont(*SEGOE))
        settle(pv)
        return pv.readout

    def test_the_height_of_one_row(self):
        for font in (None, SEGOE):
            pv = self.shown(700, 460)
            ro = pv.readout if font is None else self.segoe(pv)

            def em(f):
                return f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF() * ro.logicalDpiY() / 72.0

            block = R.LINE_K * (em(ro.f_label) + max(em(ro.f_value), em(ro.f_unit)) + em(ro.f_detail))
            self.assertEqual(ro.pitch, math.ceil(block + 3) + 2, font)
            self.assertEqual(ro.line_count, 1, font)
            self.assertEqual(ro.height(), ro.pitch + 2 * R.ROW_PAD_Y + 1, font)
            if ro.logicalDpiY() == 96:
                self.assertEqual(ro.height(), 45, font)              # 10.8 + 13.2 + 10.8, + 3, + 2, + 4, + 1
            r = ro.devicePixelRatioF()
            self.assertEqual({pm.size() for pm in ro._swatches},
                             {QSize(round(R.STRIP_SWATCH_W * r), round(R.STRIP_SWATCH_H * r))})
            self.assertEqual({pm.size() for pm in ro._icons.values()},
                             {QSize(round(R.STRIP_ICON_W * r), round(R.STRIP_ICON_H * r))})
            self.assertEqual(R.swatch_pixmap(pv._lines[0]).size(), QSize(R.SWATCH_W, R.SWATCH_H))   # (the popup's)
            self.assertEqual(R.level_icon("atd").size(), QSize(R.ICON_W, R.ICON_H))

    def test_one_row_of_equal_tiles_in_a_700_px_preview(self):
        for font in (None, SEGOE):
            pv = self.shown(700, 460)
            ro = pv.readout if font is None else self.segoe(pv)
            avail = ro.width() - 2 * R.ROW_PAD_X                     # (the preview's margins: never hard-coded)
            msg = (font, ro.columns, ro.tile_need, avail)
            self.assertEqual((ro.per_line, ro.line_count), (ro.columns, 1), msg)
            self.assertEqual(ro.tile_width(), math.floor(avail / ro.columns), msg)
            self.assertGrid(ro)
            for station, z in ((1500.0, 520.0), (3950.0, 450.0), (2900.0, 520.0), (300.0, 495.0)):
                move(pv, vp_of(pv, station, z))
                self.assertEqual(ro.overflows(), [], (font, station, ro.text()))
                self.assertGrid(ro, station)
            pv.show_guide(1500.0, 50.0, "R")
            self.assertEqual(ro.overflows(), [])

    def test_ten_surfaces_wrap_only_when_the_numbers_do_not_fit(self):
        # the ground and 10 surfaces (12 tiles) in a 700 px preview: without a screen ONE row in both fonts (his
        # decision: a second row only when even the values cannot fit, "about 11 tiles at 700 px"; measured 48 px a
        # tile in Segoe UI 9 pt, 41 px in the test font, of 688 px); MW-2's screen ("525.0–510.0 ft") is the widest
        # number any hover gives, and with it 8 tiles a line in Segoe UI 9 pt (81 px each, section 6.6): 8 + 4
        with_screen = {}
        for screen in (True, False):
            model = make_model(extra_surfaces=7)
            if not screen:
                model.hits[1].screen_top = model.hits[1].screen_bottom = None
            for font in (None, SEGOE):
                pv = self.shown(700, 460, model=model)
                ro = pv.readout if font is None else self.segoe(pv)
                avail = ro.width() - 2 * R.ROW_PAD_X
                msg = (screen, font, ro.columns, ro.tile_need, avail)
                self.assertEqual(ro.columns, 12, msg)
                self.assertGrid(ro)
                if screen:
                    with_screen[font] = ro.tile_need
                    self.assertEqual(ro.line_count, 2, msg)
                    if font == SEGOE:
                        self.assertEqual(ro.per_line, 8, msg)
                else:
                    self.assertEqual((ro.line_count, ro.per_line), (1, 12), msg)
                    self.assertLess(ro.tile_need, with_screen[font], msg)

    def test_numbers_are_never_cut_labels_and_details_are(self):
        # a long surface name and a long start label in a 700 px preview: the name ends in "…" (whole in cells()
        # and the popup), the first tile's distance never cut (" from …" is), no number cut, ever
        model = make_model()
        name = "Upper glacial till aquifer top"                      # (the popup's own cap is wider)
        model.surfaces[0].name = name
        pv = self.shown(700, 460, model=model, settings=make_settings(start_label="Northwest corner of the site"))
        ro = self.segoe(pv)
        move(pv, vp_of(pv, 1500.0, 520.0))
        ro.grab()                                                        # (paints)
        i = [c[0] for c in ro.cells()].index(name)
        self.assertIn(i, ro.elided())
        self.assertEqual(ro.overflows(), [])
        label = ro.painted()[i][0]
        self.assertTrue(label.endswith("…") and name.startswith(label[:-1]), label)
        self.assertEqual(ro.cells()[i][0], name)
        self.assertIn(name, [r[0] for r in pv.popup.rows()])
        first = ro.painted()[0][0]
        self.assertEqual(ro.cells()[0][0], "1,500 ft from Northwest corner of the site")
        self.assertTrue(first.startswith("1,500 ft from") and first.endswith("…"), first)
        self.assertIn(0, ro.elided())
        self.assertEqual([p[1] for p in ro.painted()], [c[1] for c in ro.cells()])   # every number whole
        for station in np.linspace(0.0, L, 25):                          # and anywhere
            move(pv, vp_of(pv, float(station), 512.0))
            self.assertEqual(ro.overflows(), [], (station, ro.text()))

    def test_a_long_name_is_cut_never_the_row(self):
        # his longest supply-well label on an 8-tile section (where you are, the ground and 6 lines): one row, the
        # same tile as without it (a name is not measured), the name cut in the strip, whole in cells() and the popup
        name = "Sammamish Plateau Water and Sewer Well #8"
        plain = self.shown(700, 460, model=make_model(extra_surfaces=3))
        need = self.segoe(plain).tile_need
        model = make_model(extra_surfaces=3)
        model.hits[1].label = name
        pv = self.shown(700, 460, model=model)
        ro = self.segoe(pv)
        self.assertEqual(ro.columns, 8)
        self.assertEqual((ro.line_count, ro.tile_need), (1, need))
        move(pv, vp_of(pv, 2900.0, 520.0))
        self.assertEqual(ro.mode, "cells")
        self.assertEqual(ro.cells()[0][1], name)
        self.assertEqual(pv.popup.header()[0], name)
        self.assertEqual(ro.overflows(), [])
        self.assertIn(0, ro.elided())
        ro.grab()
        cut = ro.painted()[0][1]
        self.assertTrue(cut.endswith("…") and name.startswith(cut[:-1]), cut)
        self.assertEqual([p[1] for p in ro.painted()[1:]], [c[1] for c in ro.cells()[1:]])   # the numbers whole

    def test_a_detail_keeps_its_off_view(self):
        # an 8-tile section in a 700 px preview, the map's guide off the zoomed view: "right of the line · off view"
        # (96 px in Segoe UI 9 pt) is wider than the tile's 76 px; it is cut before its ending, never the ending
        pv = self.shown(700, 460, model=make_model(extra_surfaces=3))
        ro = self.segoe(pv)
        self.assertEqual((ro.columns, ro.line_count), (8, 1))
        pv.set_zoom(4.0, QPointF(0.0, pv._vp[1] / 2.0))
        settle(pv)
        pv.show_guide(4000.0, 20.0, "R")
        full = ro.cells()[0][2]
        self.assertEqual(full, "right of the line · off view")
        room = ro.tile_rects()[0].width() - 2 * R.TILE_PAD_X
        self.assertGreater(ro.m_detail.horizontalAdvance(full), room)
        ro.grab()
        d = ro.painted()[0][2]
        self.assertTrue(d.endswith(" · off view") and d.startswith("right of") and "…" in d, d)
        self.assertIn(0, ro.elided())
        self.assertEqual(ro.overflows(), [])
        self.assertEqual(ro.painted()[0][1], "20 ft")

    def test_a_lead_detail_keeps_its_here_count(self):
        m, s = make_model(), make_settings()
        ro = R.HoverReadout()
        self.addCleanup(ro.deleteLater)
        ro.setFont(QFont(*SEGOE))
        ro.set_lines(hover_lines(m), s, m, (400.0, 650.0))
        ro.fit_width(360)                                                # (4 tiles a line)
        cells = list(strip_cells(m.hits[0], s, m))
        cells[0] = ("Boring", "B-1", "Explorations by others · +1 here", "")
        ro.show_cells(cells)
        ro.grab()
        d = ro.painted()[0][2]
        self.assertTrue(d.endswith(" · +1 here") and d.startswith("E") and "…" in d, d)
        self.assertEqual(ro.cells()[0][2], "Explorations by others · +1 here")
        # a strip narrower than one tile (a last guard): only the ending, cut too
        ro.fit_width(40)
        ro.grab()
        d = ro.painted()[0][2]
        self.assertTrue(d and "Explor" not in d and "+1 here".startswith(d.removesuffix("…")), d)
        hv = hover_values(hover_lines(m), 4000.0, m.length, None)
        ro.show_values(hv, "4,000 ft", "20 ft", "right of the line", off_view=True)
        ro.grab()
        d = ro.painted()[0][2]
        self.assertTrue(d and "right" not in d and "off view".startswith(d.removesuffix("…")), d)
        self.assertEqual(ro.cells()[0], ("4,000 ft from A", "20 ft", "right of the line · off view", False))

    def test_the_first_tile_reads_its_distance_in_navy(self):
        pv = self.shown(700, 460)
        ro = self.segoe(pv)
        move(pv, vp_of(pv, 1500.0, 520.0))
        t = ro.shown()[0][1]
        self.assertEqual((t.label, t.strong, t.lead), ("1,500 ft from A", "1,500 ft", False))
        img = ro.grab().toImage()
        r = img.devicePixelRatio()
        box = ro.tile_rects()[0]
        top = box.top() + (box.height() - ro._block_h) / 2.0
        split = box.left() + R.TILE_PAD_X + ro.m_strong.horizontalAdvance(t.strong)

        def darkest(x0, x1):                                     # the darkest ink (r + g + b) in the label line
            return min(sum(img.pixelColor(x, y).getRgb()[:3]) for x in range(int(x0 * r), int(x1 * r))
                       for y in range(int(top * r), int(math.ceil((top + ro._lh_label) * r))))

        navy, muted = (sum(QColor(c).getRgb()[:3]) for c in (R.NAVY, R.MUTED))
        self.assertLess(darkest(box.left(), split), (navy + muted) / 2.0, "the distance in navy")
        rest = darkest(split + 1.0, box.right())
        self.assertGreaterEqual(rest, muted - 12, "the rest muted, no navy")
        self.assertLess(rest, 3 * 200, "(ink there)")

    def test_ground_and_water_levels_in_the_strip_only(self):
        pv = self.shown()
        move(pv, vp_of(pv, 1500.0, 520.0))
        self.assertEqual(pv.readout.cells()[1][0], "Ground")
        self.assertEqual(hover_lines(pv._model)[0].name, "Ground (LIDAR_DEM_3ft)")       # the popup's, the CSV's
        self.assertEqual(pv.popup.rows()[0][0], "Ground (LIDAR_DEM_3ft)")
        move(pv, vp_of(pv, 2900.0, 520.0))                                # MW-2: a dated level and an ATD
        tiles = [t for _, t in pv.readout.shown()]
        self.assertEqual([(t.label, t.value, t.detail, t.icon) for t in tiles[-2:]],
                         [("6/12/2024", "530.0 ft", "9 below top", "measured"),
                          ("ATD", "528.0 ft", "11 below top", "atd")])
        self.assertEqual(pv.popup.levels(), [("measured", "530.0 ft", "measured 6/12/2024"),
                                             ("atd", "528.0 ft", "ATD")])


# ------------------------------------------------------------------ hover: the popup
class PopupTest(PreviewCase):
    def test_the_card_for_the_lines(self):
        pv = self.shown()
        pp = pv.popup
        self.assertIs(pp.parentWidget(), pv.scroll.viewport())
        self.assertTrue(pp.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertFalse(pp.isVisible())
        lines = hover_lines(pv._model)
        xy = MapXY(pv._model)
        size = None
        for station, z in ((1500.0, 522.0), (200.0, 503.0), (3950.0, 450.0), (2500.0, 600.0), (1000.0, 480.0)):
            at = vp_of(pv, station, z)
            move(pv, at)
            st, cz = data_at(pv, at)
            hv = hover_values(lines, st, L, cz)
            self.assertTrue(pp.isVisible())
            self.assertEqual(pp.mode, "values")
            self.assertEqual(pp.header(), (f"{distance_text(st, pv._settings)} from A", f"Cursor {elev_text(cz)}"))
            rows = pp.rows()
            self.assertEqual([r[0] for r in rows], [ln.name for ln in lines])
            for i, ((_, elev, depth, hi), ln, v) in enumerate(zip(rows, lines, hv.values)):
                if math.isfinite(v):
                    self.assertEqual(elev, elev_text(v).removesuffix(" ft"))
                    self.assertEqual(depth, "" if ln.ground else depth_text(hv.ground_z, v))
                else:
                    self.assertEqual((elev, depth), (NO_VALUE, "no DEM data" if ln.ground else "no data"))
                self.assertEqual(hi, i == hv.nearest)
            self.assertEqual(sum(r[3] for r in rows), 1)              # one line nearest the cursor
            self.assertEqual(pp.footer(), U.xy_text(xy.at(st)))
            self.assertRegex(pp.footer(), r"^X 1,2\d\d,\d\d\d · Y 65\d,\d\d\d$")
            size = size or pp.card_rect().size()
            self.assertEqual(pp.card_rect().size(), size, "one size per section: it never changes while hovering")
        # in the DEM gap
        move(pv, vp_of(pv, 3950.0, 450.0))
        self.assertEqual(pp.rows()[0][1:3], (NO_VALUE, "no DEM data"))
        # with station labels
        pv.draw(make_model(), make_settings(distance_labels="station", start_label="B"), make_plan())
        settle(pv)
        move(pv, vp_of(pv, 760.0, 520.0))
        self.assertRegex(pp.header()[0], r"^7\+\d\d from B$")

    def test_the_card_for_an_exploration(self):
        pv = self.shown()
        pp = pv.popup
        move(pv, vp_of(pv, 2900.0, 520.0))
        self.assertEqual(pp.mode, "hit")
        self.assertEqual(pp.header(), ("MW-2", "Monitoring Well"))
        self.assertEqual(pp.items(), [("From A", "2,900 ft", "90 ft right"), ("Top", "539.0 ft", "LIDAR"),
                                      ("Total depth", "35 ft", "bottom 504.0"),
                                      ("Screen", "525.0–510.0 ft", "14–29 below top")])
        self.assertEqual(pp.levels(), [("measured", "530.0 ft", "measured 6/12/2024"), ("atd", "528.0 ft", "ATD")])
        self.assertEqual(pp.footer(), "")
        self.assertEqual(pp.rows(), [])
        move(pv, vp_of(pv, 300.0, 495.0))                              # B-1: no levels
        self.assertEqual(pp.header(), ("B-1", "Boring"))
        self.assertEqual(pp.levels(), [])
        self.assertEqual(pp.footer(), "No water level")
        self.assertEqual([k for k, _, _ in pp.items()], ["From A", "Top", "Total depth"])
        pv.draw(make_model(), make_settings(wl_field="", atd_field=""), make_plan())   # levels not read: nothing
        settle(pv)
        move(pv, vp_of(pv, 300.0, 495.0))
        self.assertEqual((pp.header(), pp.footer()), (("B-1", "Boring"), ""))

    def test_a_long_type_is_cut_short_never_the_name(self):
        # a type can be a list ("MW, EB-1W, TW, OBW" in the CDF wells) or any field chosen as the type: the header
        # keeps the exploration's name whole and cuts the type short ("…") to the room left, both inside the card;
        # a name wider than the card on its own is cut short, without the type
        pv = self.shown()
        pp = pv.popup

        def wider_than_the_card(text, more, metrics):
            while metrics.horizontalAdvance(text) <= U.MAX_W:               # (whatever the application's font)
                text += more
            return text

        model = make_model()
        model.hits[1].type_value = wider_than_the_card("Monitoring well, 2-in. PVC, flush-mount monument",
                                                       ", nested pair", pp.m_text)
        model.hits[0].type_value = wider_than_the_card("MW, EB-1W, TW, OBW", ", EB-2W, B, TP", pp.m_text)
        pv.draw(model, make_settings(), make_plan())
        settle(pv)
        for station, z, label in ((2900.0, 520.0, "MW-2"), (300.0, 495.0, "B-1")):
            move(pv, vp_of(pv, station, z))
            self.assertEqual(pp.mode, "hit")
            name, kind = pp.header()
            self.assertEqual(name, label, "the name whole")
            self.assertTrue(kind.endswith("…") and len(kind) > 4, kind)
            full = model.hits[0 if label == "B-1" else 1].type_value
            self.assertTrue(full.startswith(kind[:-1]), kind)
            room = pp.card_rect().width() - U.PAD_L - U.PAD_R - 2.0
            self.assertLessEqual(pp.m_head.horizontalAdvance(name) + U.HEAD_GAP + pp.m_text.horizontalAdvance(kind),
                                 room + 0.01)
            self.assertLessEqual(pp.card_rect().width(), U.MAX_W)
            pp.grab()                                                   # (paints)
        # a short type is left whole
        model = make_model()
        model.hits[1].type_value = "MW, EB-1W, TW, OBW"
        pv.draw(model, make_settings(), make_plan())
        settle(pv)
        move(pv, vp_of(pv, 2900.0, 520.0))
        self.assertEqual(pp.header(), ("MW-2", "MW, EB-1W, TW, OBW"))
        # a name longer than the card
        model.hits[1].label = wider_than_the_card("Monitoring well MW-2 (the deep one of the nested pair)",
                                                  ", replaced 2019", pp.m_head)
        pv.draw(model, make_settings(), make_plan())
        settle(pv)
        move(pv, vp_of(pv, 2900.0, 520.0))
        name, kind = pp.header()
        self.assertTrue(name.endswith("…") and name.startswith("Monitoring well"), name)
        self.assertEqual(kind, "")
        self.assertLessEqual(pp.m_head.horizontalAdvance(name), pp.card_rect().width() - U.PAD_L - U.PAD_R - 2.0)
        self.assertEqual(pv.readout.cells()[0][1], model.hits[1].label)   # (the strip's tile has it: cut when drawn)

    def test_placed_by_the_cursor_inside_the_view(self):
        pv = self.shown()
        pp = pv.popup
        vp = pv.scroll.viewport()
        view = QRect(0, 0, vp.width(), vp.height()).adjusted(int(U.INSIDE_X), int(U.INSIDE_Y), -int(U.INSIDE_X),
                                                            -int(U.INSIDE_Y))
        ylim = pv._ax.get_ylim()
        spots = {"middle": (2000.0, 520.0), "left": (20.0, 520.0), "right": (L - 20.0, 520.0),
                 "top": (2000.0, ylim[1] - 2.0), "bottom": (2000.0, ylim[0] + 2.0),
                 "top left": (20.0, ylim[1] - 2.0), "top right": (L - 20.0, ylim[1] - 2.0),
                 "bottom right": (L - 20.0, ylim[0] + 2.0)}
        for name, (station, z) in spots.items():
            at = vp_of(pv, station, z)
            move(pv, at)
            self.assertEqual(pv.readout.mode, "values", name)
            card = pp.card_rect()
            self.assertTrue(view.contains(card), (name, card, view))
            want = U.place_card(at.x(), at.y(), card.width(), card.height(), vp.width(), vp.height())
            self.assertEqual((card.left(), card.top()), (round(want[0]), round(want[1])), name)
            self.assertFalse(QRectF(card).contains(at), f"{name}: never under the mouse")
            if name == "middle":
                self.assertEqual(card.left(), round(at.x() + U.OFF_X))          # right of and above the cursor
                self.assertEqual(card.top() + card.height(), round(at.y() - U.OFF_ABOVE))
            if "right" in name:
                self.assertLess(card.right(), at.x())                            # flipped to the left
            if "top" in name:
                self.assertGreater(card.top(), at.y())                           # flipped below
        # the plot under the card still gets the mouse
        card = pp.card_rect()
        self.assertIs(vp.childAt(card.center()), pv.canvas)
        # zoomed in: still inside the view
        pv.set_zoom(4.0, vp_of(pv, 2000.0, 520.0))
        settle(pv)
        for at in (QPointF(5.0, 5.0), QPointF(vp.width() - 5.0, vp.height() - 5.0), QPointF(vp.width() / 2, 30.0)):
            move(pv, at)
            if pv.readout.mode == "values":
                self.assertTrue(view.contains(pp.card_rect()), at)

    def test_a_guide_from_the_map_puts_it_by_the_guide(self):
        pv = self.shown()
        pp = pv.popup
        pv.show_guide(1200.0, 49.6, "R")
        self.assertTrue(pp.isVisible())
        self.assertEqual(pp.header(), ("1,200 ft from A", "50 ft right of the line"))
        self.assertFalse(any(r[3] for r in pp.rows()), "no cursor: no line is nearest")
        foot = vp_of(pv, 1200.0, hover_values(hover_lines(pv._model), 1200.0, L).ground_z)
        vp = pv.scroll.viewport()
        card = pp.card_rect()
        want = U.place_card(foot.x(), foot.y() - 10.0, card.width(), card.height(), vp.width(), vp.height())
        self.assertEqual((card.left(), card.top()), (round(want[0]), round(want[1])))
        pv.show_guide(3930.0, 20.0, "L")                           # in the DEM gap: under the plot's top
        top = pv.canvas.height() - pv._ax.bbox.y1 / pv.canvas.device_pixel_ratio + pv.canvas.y()
        card = pp.card_rect()
        x = vp_of(pv, 3930.0, 500.0).x()
        want = U.place_card(x, top + 40.0, card.width(), card.height(), vp.width(), vp.height())
        self.assertEqual((card.left(), card.top()), (round(want[0]), round(want[1])))
        pv.hide_guide()
        self.assertFalse(pp.isVisible())

    def test_hidden_off_view_on_leave_and_while_dragging(self):
        pv = self.shown()
        pp = pv.popup
        pv.set_zoom(4.0, QPointF(0.0, pv._vp[1] / 2.0))
        settle(pv)
        pv.show_guide(4000.0, 20.0, "R")                           # off view: only the edge tag
        self.assertTrue(pv._marks.edge.get_visible())
        self.assertFalse(pp.isVisible())
        pv.show_guide(100.0, 20.0, "R")
        self.assertTrue(pp.isVisible())
        pv.hide_guide()
        at = QPointF(300.0, 200.0)
        move(pv, at)
        self.assertTrue(pp.isVisible())
        leave(pv)
        self.assertFalse(pp.isVisible())
        move(pv, at)
        self.assertTrue(pp.isVisible())
        mouse(pv, QEvent.Type.MouseButtonPress, at, Left, Left)
        self.assertIsNotNone(pv._drag)
        self.assertFalse(pp.isVisible(), "hidden while drag-panning")
        move(pv, QPointF(250.0, 180.0), buttons=Left)
        self.assertFalse(pp.isVisible())
        mouse(pv, QEvent.Type.MouseButtonRelease, QPointF(250.0, 180.0), Left, NoButton)
        self.assertTrue(pp.isVisible(), "back after the drag")
        card = pp.card_rect()
        self.assertEqual(card.left(), round(250.0 + U.OFF_X))


# ------------------------------------------------------------------ another screen ratio
class PixelRatioTest(PreviewCase):
    def test_swatches_and_symbols_follow_the_screen_ratio(self):
        # QGIS moved to a screen of another ratio (a laptop at 250 %, a monitor at 100 %), or the display scale
        # changed: the next paint makes the strip's and the card's swatches and water level symbols again for it
        # (they were made once per section, and scaled from the old ratio looked blurred), whatever caused it
        pv = self.shown()
        ro, pp = pv.readout, pv.popup
        move(pv, vp_of(pv, 1500.0, 520.0))
        r0 = ro.devicePixelRatioF()

        def ratios(w):
            return {pm.devicePixelRatio() for pm in list(w._swatches) + list(w._icons.values())}

        self.assertEqual((ratios(ro), ratios(pp)), ({r0}, {r0}))
        tiles = [t for _, t in ro.shown()]
        self.assertEqual([t.swatch for t in tiles], [None, 0, 1, 2, 3], "the tiles keep the line, not a pixmap")
        before = ro._swatches[0]
        ro.repaint()
        self.assertIs(ro._swatches[0], before, "the same ratio: nothing made again")
        new = r0 * 2.0
        with mock.patch.object(R.HoverReadout, "devicePixelRatioF", return_value=new), \
                mock.patch.object(U.HoverPopup, "devicePixelRatioF", return_value=new):
            ro.repaint()
            pp.repaint()
            self.assertEqual((ratios(ro), ratios(pp)), ({new}, {new}))
            self.assertEqual(len(ro._swatches), len(pv._lines))
            self.assertEqual(ro._swatches[0].size(),
                             R.swatch_pixmap(pv._lines[0], new, R.STRIP_SWATCH_W, R.STRIP_SWATCH_H).size())
            move(pv, vp_of(pv, 2900.0, 520.0))                         # MW-2: the level symbols
            ro.repaint()
            pp.repaint()
            self.assertEqual([t.icon for _, t in ro.shown()][-2:], ["measured", "atd"])
            self.assertEqual(ratios(ro), {new})
        ro.repaint()                                                    # and back
        pp.repaint()
        self.assertEqual((ratios(ro), ratios(pp)), ({r0}, {r0}))


# ------------------------------------------------------------------ hover: the two toggles
class ToggleTest(PreviewCase):
    def test_both_start_on_and_are_remembered(self):
        restore_user_values({k: None for k in TOGGLE_KEYS})        # never set: the first time
        first = PreviewWidget()
        self.addCleanup(first.deleteLater)
        self.assertTrue(first.act_strip.isChecked() and first.act_popup.isChecked())
        self.assertTrue(first.hover_enabled())
        self.assertFalse(first.readout.isHidden())
        first.act_strip.setChecked(False)
        self.assertEqual(settings_store.user_value(P.STRIP_KEY), "0")
        self.assertEqual(settings_store.user_value(P.POPUP_KEY, None), None, "only what was changed is written")
        second = PreviewWidget()                                   # the next session
        self.addCleanup(second.deleteLater)
        self.assertEqual((second.act_strip.isChecked(), second.act_popup.isChecked()), (False, True))
        self.assertTrue(second.readout.isHidden())
        self.assertTrue(second.hover_enabled())
        second.act_popup.setChecked(False)
        self.assertEqual(settings_store.user_value(P.POPUP_KEY), "0")
        third = PreviewWidget()
        self.addCleanup(third.deleteLater)
        self.assertEqual((third.act_strip.isChecked(), third.act_popup.isChecked()), (False, False))
        self.assertFalse(third.hover_enabled())
        third.act_strip.setChecked(True)
        third.act_popup.setChecked(True)
        self.assertEqual([settings_store.user_value(k) for k in TOGGLE_KEYS], ["1", "1"])
        fourth = PreviewWidget()
        self.addCleanup(fourth.deleteLater)
        self.assertTrue(fourth.act_strip.isChecked() and fourth.act_popup.isChecked())
        settings_store.set_user_value("hover_readout", "0")       # 0.3.1's single toggle is not read
        self.addCleanup(QgsSettings().remove, settings_store.USER_PREFIX + "hover_readout")
        fifth = PreviewWidget()
        self.addCleanup(fifth.deleteLater)
        self.assertTrue(fifth.hover_enabled() and fifth.act_strip.isChecked())

    def test_the_strip_off_hides_the_row_and_gives_the_plot_its_room(self):
        pv = self.shown()
        ro = pv.readout
        h_strip, h_view = ro.height(), pv.scroll.viewport().height()
        layouts = []
        real = F.draw_preview

        def counted(fig, *args):
            layouts.append(tuple(fig.get_size_inches()))
            return real(fig, *args)

        with mock.patch("xsections.render.figure.draw_preview", side_effect=counted):
            pv.act_strip.setChecked(False)
            settle(pv)
            self.assertTrue(ro.isHidden())
            self.assertEqual(pv.scroll.viewport().height(), h_view + h_strip)
            self.assertEqual(len(layouts), 1, "laid out again for the bigger plot")
            self.assertAlmostEqual(layouts[0][1], pv._vp[1] / P.BASE_DPI, places=6)
            # the hover goes on: the guide, the popup, the map marker's signal
            move(pv, vp_of(pv, 1500.0, 520.0))
            self.assertEqual(self.events[-1][0], "changed")
            self.assertTrue(pv._marks_on and pv.popup.isVisible())
            pv.show_guide(1000.0, 30.0, "L")
            self.assertTrue(pv.popup.isVisible())
            self.assertTrue(pv._marks.guide.get_visible())
            pv.hide_guide()
            # back on: the row again, with the plot laid out for the smaller room
            pv.act_strip.setChecked(True)
            settle(pv)
        self.assertFalse(ro.isHidden())
        self.assertEqual(ro.height(), h_strip)
        self.assertEqual(pv.scroll.viewport().height(), h_view)
        self.assertEqual(len(layouts), 2)
        move(pv, vp_of(pv, 1500.0, 520.0))
        self.assertEqual(ro.mode, "values")
        self.assertGrid(ro)

    def test_the_popup_on_and_off(self):
        pv = self.shown()
        at = vp_of(pv, 1500.0, 520.0)
        move(pv, at)
        self.assertTrue(pv.popup.isVisible())
        pv.act_popup.setChecked(False)
        self.assertFalse(pv.popup.isVisible(), "off: gone at once")
        self.assertTrue(pv._marks_on, "the strip's hover goes on")
        self.assertEqual(pv.readout.mode, "values")
        n = len(self.events)
        move(pv, vp_of(pv, 1600.0, 520.0))
        self.assertFalse(pv.popup.isVisible())
        self.assertEqual(len(self.events), n + 1)
        pv.show_guide(1000.0, 30.0, "L")
        self.assertFalse(pv.popup.isVisible())
        pv.hide_guide()
        move(pv, at)
        pv.act_popup.setChecked(True)                               # on: at the hover's place, no move needed
        self.assertTrue(pv.popup.isVisible())
        self.assertEqual(pv.popup.card_rect().left(), round(at.x() + U.OFF_X))
        self.assertTrue(pv.readout.isVisible())

    def test_both_off_is_no_hover(self):
        pv = self.shown()
        move(pv, vp_of(pv, 1500.0, 520.0))
        pv.act_strip.setChecked(False)
        self.assertTrue(pv.hover_enabled())
        self.assertEqual(self.events[-1][0], "changed")
        pv.act_popup.setChecked(False)
        self.assertFalse(pv.hover_enabled())
        self.assertEqual(self.events[-1], ("left",))                # the map marker goes
        self.assertFalse(pv._marks_on or pv.popup.isVisible())
        settle(pv)
        n = len(self.events)
        for station in (300.0, 1600.0, 2900.0):
            move(pv, vp_of(pv, station, 520.0))
        pv.show_guide(1600.0, 10.0, "L")
        self.assertEqual(len(self.events), n, "no hoverChanged")
        self.assertFalse(pv._marks_on or pv.popup.isVisible())
        self.assertIsNone(pv._hover)
        pv.act_popup.setChecked(True)                               # one on: the hover is back
        move(pv, vp_of(pv, 1600.0, 520.0))
        self.assertEqual(self.events[-1][0], "changed")
        self.assertTrue(pv.popup.isVisible() and pv._marks_on)
        self.assertTrue(pv.readout.isHidden())
        # a guide from the map (no hoverChanged for it), then both off: it goes, and hoverLeft tells the dock (the
        # map's marker goes with it)
        leave(pv)
        pv.show_guide(1200.0, 20.0, "R")
        self.assertTrue(pv._marks_on and pv.popup.isVisible())
        n = len(self.events)
        pv.act_popup.setChecked(False)
        self.assertEqual(self.events[n:], [("left",)])
        self.assertFalse(pv._marks_on or pv.popup.isVisible())
        self.assertIsNone(pv._hover)
        pv.act_strip.setChecked(True)                               # back on: nothing until the next hover
        self.assertEqual(self.events[n:], [("left",)])
        self.assertEqual((pv.readout.mode, pv.readout.idle_text), ("idle", R.IDLE_TEXT))

    # ---- in a bottom dock, as the plugin puts it: the row never makes the dock taller
    def docked(self, strip, show_dock=True):
        """A preview in the bottom dock of a shown 1400 x 900 main window (as plugin.py puts it), the dock 330 px
        tall; the readout row's user value `strip` from the start ("0": turned off in an earlier session)."""
        settings_store.set_user_value(P.STRIP_KEY, strip)
        win = QMainWindow()
        self.addCleanup(self._close_window, win)
        central = QWidget()
        central.setMinimumSize(200, 100)
        win.setCentralWidget(central)
        dock = QgsDockWidget("XSections preview", win)
        pv = PreviewWidget(dock)
        dock.setWidget(pv)
        win.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        win.resize(1400, 900)
        if not show_dock:
            dock.hide()
        win.show()
        APP.processEvents()
        if show_dock:
            win.resizeDocks([dock], [330], Qt.Orientation.Vertical)
            APP.processEvents()
        return win, dock, pv

    @staticmethod
    def _close_window(win):
        win.hide()
        win.deleteLater()
        APP.processEvents()

    def turn_the_row_on(self, pv):
        """Turn the readout row on; (its height and lines when it showed, the viewport's sizes on the way)."""
        ro = pv.readout
        shown = Watch(ro, QEvent.Type.Show, lambda w, e: (w.height(), w.line_count, w.width()))
        sizes = Watch(pv.scroll.viewport(), QEvent.Type.Resize, lambda w, e: (e.size().width(), e.size().height()))
        pv.act_strip.setChecked(True)
        settle(pv)
        APP.processEvents()
        return shown.seen, sizes.seen

    def assertLaidOutForItsWidth(self, ro):
        per, lines = R.strip_layout(ro.columns, ro.tile_need, ro.width() - 2 * R.ROW_PAD_X)
        self.assertEqual((ro.per_line, ro.line_count), (per, lines))
        self.assertEqual(ro.height(), lines * ro.pitch + 2 * R.ROW_PAD_Y + 1)

    def test_turning_the_row_on_keeps_the_dock_s_height(self):
        # the row off since an earlier session, a section drawn, then "Readout row" on: the row comes laid out for
        # the panel's width at once (hidden, it had Qt's first 100 px: every tile on a line of its own, ~470 px,
        # and showing that pushed the dock from 330 to ~650 px, for good)
        win, dock, pv = self.docked("0")
        pv.draw(make_model(), make_settings(), make_plan())          # (the tile this section needs)
        settle(pv)
        ro = pv.readout
        need = ro.tile_need
        per = int((pv.scroll.width() - 2 * R.ROW_PAD_X) // need)    # compact tiles: this many fit a line here
        # where you are, the ground, 3 surfaces and per - 4 more: per + 1 tiles, two lines
        pv.draw(make_model(extra_surfaces=per - 4), make_settings(), make_plan())
        settle(pv)
        self.assertEqual((ro.tile_need, ro.columns), (need, per + 1))
        self.assertTrue(ro.isHidden())
        self.assertEqual(dock.height(), 330)
        shown, sizes = self.turn_the_row_on(pv)
        self.assertFalse(ro.isHidden())
        self.assertEqual(dock.height(), 330, "the dock keeps its height")
        self.assertEqual(ro.width(), pv.scroll.width())
        self.assertLaidOutForItsWidth(ro)
        self.assertEqual(ro.line_count, 2)
        self.assertEqual(shown, [(ro.height(), ro.line_count, ro.width())], "its final height when it showed")
        self.assertEqual(len(sizes), 1, f"the plot laid out once: {sizes}")
        move(pv, vp_of(pv, 1500.0, 520.0))
        self.assertGrid(ro)

    def test_turning_the_row_on_after_the_panel_narrowed(self):
        # the row off, the panel narrowed (the hidden row keeps its old width), a section drawn, the row on: it is
        # laid out for the new width before it shows (more lines), and the plot gets the room left once
        win, dock, pv = self.docked("1")
        pv.draw(make_model(), make_settings(), make_plan())          # (the tile this section needs)
        settle(pv)
        ro = pv.readout
        extra = int((ro.width() - 2 * R.ROW_PAD_X) // ro.tile_need) - 5    # 5 + extra tiles: one full line, wide
        pv.draw(make_model(extra_surfaces=extra), make_settings(), make_plan())
        settle(pv)
        wide_lines = ro.line_count
        self.assertEqual(wide_lines, 1)
        pv.act_strip.setChecked(False)
        settle(pv)
        win.resize(700, 900)
        APP.processEvents()
        win.resizeDocks([dock], [330], Qt.Orientation.Vertical)
        APP.processEvents()
        pv.draw(make_model(extra_surfaces=extra), make_settings(), make_plan())
        settle(pv)
        self.assertEqual(dock.height(), 330)
        shown, sizes = self.turn_the_row_on(pv)
        self.assertEqual(dock.height(), 330)
        self.assertEqual(ro.width(), pv.scroll.width())
        self.assertLaidOutForItsWidth(ro)
        self.assertGreater(ro.line_count, wide_lines)
        self.assertEqual(shown, [(ro.height(), ro.line_count, ro.width())])
        self.assertEqual(len(sizes), 1, f"the plot laid out once: {sizes}")

    def test_the_first_show_after_a_section_was_drawn_hidden(self):
        # the preview's dock not shown yet in this session while the panel draws a section into it: the row is
        # laid out on one line (its least height), not for Qt's first 100 px (~470 px tall, which made the dock
        # ~800 px tall when first shown); shown at full width it is the same height
        win, dock, pv = self.docked("1", show_dock=False)
        pv.draw(make_model(), make_settings(), make_plan())
        APP.processEvents()
        ro = pv.readout
        before = (ro.height(), pv.minimumSizeHint().height())
        self.assertEqual(ro.line_count, 1)
        dock.show()
        settle(pv)
        APP.processEvents()
        self.assertLaidOutForItsWidth(ro)
        self.assertEqual(ro.line_count, 1, "a 1400 px panel has room for the 7 tiles")
        self.assertEqual((ro.height(), pv.minimumSizeHint().height()), before)
        self.assertLess(dock.height(), 600)


# ------------------------------------------------------------------ speed
class SpeedTest(PreviewCase):
    @timing_test
    def test_a_hover_update_is_quick(self):
        # a 6-line section (the ground and five surfaces), the strip and the popup on: the median hover update
        # (the readout, the popup, the blitted marks, and Qt painting them) stays under ~15 ms at 100 % and 400 %
        # (the best of three rounds: another program busy on the machine slows a round down, not the preview)
        pv = self.shown(*env_size(), model=make_model(extra_surfaces=2))
        if os.environ.get(RATIO_ENV):
            self.assertEqual(pv.canvas.device_pixel_ratio, float(os.environ[RATIO_ENV]))
        self.assertEqual(len(pv._lines), 6)
        for z in (1.0, 4.0):
            pv.set_zoom(z, QPointF(500.0, 200.0))
            settle(pv)
            vp = pv.scroll.viewport()
            xs = np.linspace(0.15 * vp.width(), 0.85 * vp.width(), 60)
            medians = []
            for _ in range(3):
                times = []
                for i, x in enumerate(xs):
                    at = QPointF(float(x), vp.height() * (0.35 + 0.3 * (i % 5) / 4.0))
                    t0 = time.perf_counter()
                    move(pv, at)
                    APP.processEvents()                             # the strip and the card painted
                    times.append(time.perf_counter() - t0)
                medians.append(statistics.median(times[5:]) * 1000.0)
                self.assertEqual([pv.readout.mode, pv.popup.isVisible()], ["values", True], z)
            self.assertLess(min(medians), budget(15.0),
                            f"median hover update {min(medians):.1f} ms at {round(z * 100)} %")

    def test_a_hover_repaints_only_what_it_changes(self):
        # the plot copied to the screen on a hover move: thin strips where the marks and tags were and are (and
        # the popup's old and new place), not the whole view (a 1500 x 600 view at 250 % is 22 MB a move)
        pv = self.shown(model=make_model(extra_surfaces=2))
        vp = pv.scroll.viewport()
        view = vp.width() * vp.height()
        for popup in (False, True):
            pv.act_popup.setChecked(popup)
            move(pv, QPointF(300.0, 150.0))
            APP.processEvents()
            areas = []
            real = P.PreviewCanvas._copy_buffer

            def counted(canvas, painter, rects):
                areas.append(sum(q.width() * q.height() for q in rects))
                return real(canvas, painter, rects)

            with mock.patch.object(P.PreviewCanvas, "_copy_buffer", autospec=True, side_effect=counted):
                for i, x in enumerate(np.linspace(320.0, 700.0, 20)):
                    move(pv, QPointF(float(x), 150.0 + 4.0 * (i % 3)))
                    APP.processEvents()
            self.assertEqual(pv.readout.mode, "values")
            self.assertTrue(areas)
            self.assertLess(statistics.median(areas), (0.5 if popup else 0.15) * view, (popup, areas))   # (all: 1.0)

    @timing_test
    def test_quick_at_250_percent_on_a_large_preview(self):
        # this PC's screen (3840 x 2400 at 250 %) and a full-width bottom dock: the same test in a new Python at
        # that ratio (a running application keeps its ratio), 1500 x 600 (it was ~20 ms with whole-view repaints)
        code, out = run_child(["tests.test_preview_tools.SpeedTest.test_a_hover_update_is_quick"],
                              QT_SCALE_FACTOR="2.5", **{SIZE_ENV: "1500x600", RATIO_ENV: "2.5"})
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("OK", out)


# ------------------------------------------------------------------ the screen: nothing left behind
class ScreenTest(PreviewCase):
    """The hover repaints parts of the plot: what is on the screen (the backing store) is still what a full
    repaint gives, at every step, and the buffer is the plot again when the hover ends."""

    def test_partial_repaints_leave_nothing_behind(self):
        pv = self.shown(*env_size(), model=make_model(extra_surfaces=2))
        r = pv.canvas.device_pixel_ratio
        if os.environ.get(RATIO_ENV):
            self.assertEqual(r, float(os.environ[RATIO_ENV]))
        clean = buffer(pv)
        vp = pv.scroll.viewport()
        win = pv.window()
        # (at a ratio over 1 the offscreen screen grab is the window's top left: hover there)
        origin = QPointF(vp.mapFrom(win, QPoint(0, 0)))
        seen = QRectF(origin, origin + QPointF(win.width() / r, win.height() / r))
        frame, c = pv._ax.bbox, pv.canvas
        plot = QRectF(QPointF(frame.x0 / r + c.x(), c.height() - frame.y1 / r + c.y()),
                      QPointF(frame.x1 / r + c.x(), c.height() - frame.y0 / r + c.y())).intersected(seen)
        self.assertGreater(plot.width(), 100.0)
        self.assertGreater(plot.height(), 40.0)
        pts = [QPointF(x, y) for x in np.linspace(plot.left() + 5.0, plot.right() - 5.0, 24)
               for y in (plot.top() + 0.3 * plot.height(), plot.top() + 0.75 * plot.height())]

        def check(where):
            now = screen(pv)
            pv.canvas.repaint()                     # (the whole canvas from the buffer, the tags, the card)
            pv.popup.repaint()
            full = screen(pv)
            bad = np.argwhere(now != full)
            self.assertEqual(len(bad), 0, (where, bad[:4].tolist()))

        for i, at in enumerate(pts):
            move(pv, at)
            if i % 6 == 0:
                check(("move", i))
        for h in pv._model.hits:                                      # explorations: the band, no dots
            move(pv, vp_of(pv, h.station, (h.top + h.bottom) / 2.0))
            check(h.label)
        for z in (2.0, 4.0):
            pv.set_zoom(z, pts[0])
            settle(pv)
            for at in pts[::4]:
                move(pv, at)
            check(("zoom", z))
            wheel(pv, pts[0], dy=-120, mods=Qt.KeyboardModifier.ShiftModifier)    # a pan under a still mouse
            check(("panned", z))
            leave(pv)
            pv.show_guide(1000.0, 30.0, "L")
            check(("map guide", z))
            pv.show_guide(4300.0, 30.0, "R")                          # out of view: the edge tag
            check(("edge tag", z))
            pv.hide_guide()
            check(("guide gone", z))
        pv.fit()
        settle(pv)
        for at in pts[:8]:
            move(pv, at)
        leave(pv)
        check("left")
        self.assertTrue(np.array_equal(buffer(pv), clean), "the plot again, no marks anywhere in the buffer")

    def test_at_250_percent(self):
        code, out = run_child(["tests.test_preview_tools.ScreenTest.test_partial_repaints_leave_nothing_behind"],
                              QT_SCALE_FACTOR="2.5", **{SIZE_ENV: "1500x600", RATIO_ENV: "2.5"})
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("OK", out)


# ------------------------------------------------------------------ real data
@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealDataTest(PreviewCase):
    """The CDF A-A′ section (DEM and wells): every exploration can be pointed at, values are core's, the tiles keep
    their width and the zoom anchor holds on the real drawing."""

    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
        from tests.test_e2e import copy_realdata, line_through_points
        from xsections.core.build import build_section
        from xsections.render.scales import plan

        cls.tmp = tempfile.mkdtemp(prefix="xsec_preview_real_")
        dem_path, wells_path = copy_realdata(cls.tmp)
        prj = QgsProject.instance()
        prj.clear()
        dem = QgsRasterLayer(dem_path, "cdf_lidar")
        wells = QgsVectorLayer(wells_path, "CDF_wells", "ogr")
        prj.addMapLayers([dem, wells])
        prj.setCrs(dem.crs())
        geom, tol = line_through_points(wells, dem.crs(), prj)
        cls.settings = Settings(line_wkt=geom.asWkt(), line_crs_authid=dem.crs().toWkt(), dem_layer_id=dem.id(),
                                points_layer_id=wells.id(), label_field="ExploName", type_field="ExploType",
                                top_field="ExploElev", depth_field="ExploDepth", tolerance_ft=tol, h_scale=200.0,
                                v_scale=20.0, wl_values="depth", wl_field="DepthToGW", wl_date_field="ExploDate")
        cls.model = build_section(cls.settings, prj)
        cls.plan = plan(cls.model, cls.settings)
        prj.clear()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_real_section(self):
        pv = self.shown(1200, 480, self.model, self.settings, self.plan)
        m, s = self.model, self.settings
        self.assertGreater(len(m.hits), 3)
        ro = pv.readout
        height = ro.height()
        rects = [QRectF(r) for r in ro.tile_rects()]
        self.assertEqual(ro.columns, max([1 + len(hover_lines(m))] + [len(hit_cells(h, s)) for h in m.hits]))
        (x0, _), (x1, _) = pv._ax.transData.transform([(0.0, 0.0), (1.0, 0.0)])
        px_per_ft = x1 - x0
        for i, h in enumerate(m.hits):
            zs = [v for v in (h.top, h.bottom, h.ground_at_station) if v is not None and math.isfinite(v)]
            move(pv, vp_of(pv, h.station, (min(zs) + max(zs)) / 2.0))
            got = self.events[-1]
            self.assertEqual(got[0], "changed")
            near = [j for j, o in enumerate(m.hits)
                    if abs(o.station - h.station) * px_per_ft <= P.HIT_DX_PX * pv.canvas.device_pixel_ratio]
            self.assertIn(got[2], near)                                 # this one, or a neighbour as close
            self.assertEqual(got[1], m.hits[got[2]].station)
            self.assertEqual([c[:3] for c in ro.cells()], [c[:3] for c in strip_cells(m.hits[got[2]], s, m)])
            self.assertEqual(pv.popup.header()[0], ro.cells()[0][1])
            self.assertEqual(ro.height(), height)
            self.assertEqual(ro.tile_rects(), rects)
            self.assertEqual(ro.overflows(), [])
        lines = hover_lines(m)
        rng = np.random.default_rng(3)
        z0, z1 = self.plan.z_min, self.plan.z_max
        for station in rng.uniform(0.0, m.length, 60):
            at = vp_of(pv, float(station), float(rng.uniform(z0, z1)))
            move(pv, at)
            if ro.mode != "values":
                continue                                                # an exploration is there
            st, cz = data_at(pv, at)
            hv = hover_values(lines, st, m.length, min(max(cz, z0), z1))
            self.assertEqual([c[1] for c in ro.cells()[1:]],
                             [elev_text(v) if math.isfinite(v) else NO_VALUE for v in hv.values])
            self.assertEqual([r[1] for r in pv.popup.rows()],
                             [elev_text(v).removesuffix(" ft") if math.isfinite(v) else NO_VALUE for v in hv.values])
            self.assertEqual(ro.overflows(), [])
            self.assertEqual(ro.height(), height)
            self.assertEqual(ro.tile_rects(), rects)
        pt = (m.length * 0.6, (z0 + z1) / 2.0)
        anchor = vp_of(pv, *pt)
        for z in (2.0, 4.0, pv._z_max, 3.0, 1.0):
            pv.set_zoom(z, anchor)
            self.assertNear(vp_of(pv, *pt), anchor, 1.0, f"zoom {z}")
        settle(pv)
        self.assertEqual(pv.last_error, "")


@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealDataStripTest(PreviewCase):
    """The compact strip's section (the mockup's): his CDF A-A′ with six CDF_Mounding surfaces (where you are, the
    ground and 6 lines: 8 tiles), in a 700 px preview in Segoe UI 9 pt: one row, 45 px tall, every number whole
    wherever the mouse goes. (Core only, as RealDataTest; CDF_Mounding has one model layer.)"""

    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
        from tests.test_e2e import copy_realdata, line_through_points
        from xsections.core.build import build_section
        from xsections.core.model import SURFACE_DEFAULTS
        from xsections.render.scales import plan

        cls.tmp = tempfile.mkdtemp(prefix="xsec_strip_real_")
        dem_path, wells_path = copy_realdata(cls.tmp)
        cdf = os.path.join(REALDATA, "mf6", "CDF_Mounding")             # (only read)
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
            depth_field="ExploDepth", tolerance_ft=tol, h_scale=200.0, v_scale=20.0, wl_values="depth",
            wl_field="DepthToGW", wl_date_field="ExploDate",
            surfaces=[mf6("top", color="#555555", style="dot"),
                      mf6("botm", color="#8c5a3c", mf6_layer=1, in_range=False),
                      mf6("head", color="#d95f02", mf6_layer=1),
                      mf6("wt", color="#1f6fb2", style="dash"),
                      mf6("top", color="#999999", mode="cells"),
                      mf6("wt", color="#2e8b57", mode="cells")])
        cls.model = build_section(cls.settings, prj)
        cls.plan = plan(cls.model, cls.settings)
        prj.clear()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_one_row_at_700_px(self):
        m, s = self.model, self.settings
        self.assertEqual(len(m.surfaces), 6)
        self.assertEqual(len(hover_lines(m)), 7)
        self.assertGreater(len(m.hits), 3)
        pv = self.shown(700, 480, m, s, self.plan)
        ro = pv.readout
        ro.setFont(QFont(*SEGOE))
        settle(pv)
        self.assertEqual(ro.columns, 8)                                  # (a CDF well's row: at most 6 tiles)
        avail = ro.width() - 2 * R.ROW_PAD_X
        msg = f"N {ro.columns}, tile_need {ro.tile_need}, room {avail}"
        self.assertEqual((ro.line_count, ro.per_line), (1, 8), msg)      # no fallback: a wrap fails
        self.assertEqual(ro.tile_width(), math.floor(avail / 8), msg)
        if ro.logicalDpiY() == 96:
            self.assertEqual(ro.height(), 45)
        height, rects = ro.height(), [QRectF(r) for r in ro.tile_rects()]
        self.assertGrid(ro)
        modes = set()
        for h in m.hits:                                                 # every exploration
            zs = [v for v in (h.top, h.bottom, h.ground_at_station) if v is not None and math.isfinite(v)]
            move(pv, vp_of(pv, h.station, (min(zs) + max(zs)) / 2.0))
            modes.add(ro.mode)
            self.assertEqual(ro.overflows(), [], (h.label, ro.text()))
            self.assertEqual((ro.height(), ro.tile_rects()), (height, rects))
        rng = np.random.default_rng(5)
        z0, z1 = self.plan.z_min, self.plan.z_max
        for station in rng.uniform(0.0, m.length, 60):                   # values over the plot
            move(pv, vp_of(pv, float(station), float(rng.uniform(z0, z1))))
            modes.add(ro.mode)
            self.assertEqual(ro.overflows(), [], (station, ro.text()))
            self.assertEqual((ro.height(), ro.tile_rects()), (height, rects))
        self.assertEqual(modes, {"cells", "values"})
        self.assertEqual(pv.last_error, "")


if __name__ == "__main__":
    unittest.main()
