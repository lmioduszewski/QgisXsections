"""The preview's "Full screen" toggle (0.3.7): the toolbar's last button floats the preview's dock and fills the screen
the dock is on with it, and the section fits; the button again, or Esc, puts the dock back where it was (docked in its
area at its size, or floating at its geometry) and fits again. Closed or hidden while full screen, the dock is put
back hidden and shows there next time (floated by hand later, where it floated before); QGIS closing, a project
closed and the plugin's unload put it back first, and QGIS's Ctrl+Tab leaves it full screen (it hides docked panels
only). F11 stays QGIS's, Esc is the preview's only while it is full screen, and nothing is remembered.

A shown main window with the preview in a QgsDockWidget, as plugin.py puts it, on the offscreen platform's one 800 x
800 screen; the multi-monitor case runs in a new Python on two offscreen screens (the platform's configfile), the
plugin's own wiring with qgis.testing's iface around a real main window (tests/test_e2e.py).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.fixtures import ROOT, budget, load_project, start_app

APP = start_app()

from qgis.core import QgsProject  # noqa: E402
from qgis.gui import QgsDockWidget  # noqa: E402
from qgis.PyQt import sip  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QPoint, QRect, QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import (QAction, QCloseEvent, QColor, QGuiApplication, QIcon, QKeyEvent,  # noqa: E402
                             QKeySequence, QPalette)
from qgis.PyQt.QtTest import QTest  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

from tests.test_preview_tools import (TOGGLE_KEYS, key, make_model, make_plan, make_settings, mouse,  # noqa: E402
                                      move, restore_user_values, save_user_values, settle, vp_of)
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.preview import BASE_DPI, PreviewWidget  # noqa: E402
from xsections.ui.widgets import tip_text  # noqa: E402

Bottom, LeftArea, RightArea = (Qt.DockWidgetArea.BottomDockWidgetArea, Qt.DockWidgetArea.LeftDockWidgetArea,
                               Qt.DockWidgetArea.RightDockWidgetArea)
NoMod = Qt.KeyboardModifier.NoModifier
LeftButton = Qt.MouseButton.LeftButton
TIP = "Full screen: the section fills the screen; click again or press Esc to put it back"
SIZE_TOL = 2                    # px: the dock's size in its area when it is back
TWO_SCREENS_ENV = "XSECTIONS_TWO_SCREENS"    # set in the new Python on two screens
TWO_SCREENS = [dict(name="Left", x=0, y=0, width=1600, height=900, logicalDpi=96, logicalBaseDpi=96, dpr=1),
               dict(name="Right", x=1600, y=0, width=1920, height=1080, logicalDpi=96, logicalBaseDpi=96, dpr=1)]


def orientation(area):
    return (Qt.Orientation.Vertical if area in (Qt.DockWidgetArea.TopDockWidgetArea, Bottom)
            else Qt.Orientation.Horizontal)


def spin(n=3):
    """Pending events and the zero-time timers (the dock's hides and shows are looked at once they are done)."""
    for _ in range(n):
        APP.processEvents()
        QTest.qWait(1)


def ink(icon, state, size=48):
    """The colours of an icon's opaque pixels for `state`."""
    img = icon.pixmap(size, size, QIcon.Mode.Normal, state).toImage()
    return {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())
            if img.pixelColor(x, y).alpha() == 255}


def run_on_two_screens(test_id):
    """Run a test of this module in a new Python on two offscreen screens side by side (TWO_SCREENS, the left one the
    primary); (exit code, output). (The platform's arguments are split at ":", so the file is named relative to the
    child's folder, and the project comes in on PYTHONPATH.)"""
    folder = tempfile.mkdtemp(prefix="xsec_screens_")
    with open(os.path.join(folder, "screens.json"), "w", encoding="utf-8") as f:
        json.dump({"screens": TWO_SCREENS}, f)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen:configfile=screens.json", **{TWO_SCREENS_ENV: "1"})
    env["PYTHONPATH"] = os.pathsep.join(p for p in (ROOT, os.environ.get("PYTHONPATH", "")) if p)
    out = subprocess.run([sys.executable, "-m", "unittest", "-v", test_id], cwd=folder, env=env,
                         capture_output=True, text=True, timeout=budget(600))
    return out.returncode, (out.stdout or "") + (out.stderr or "")


class Main(QMainWindow):
    """A main window that notes, when it is closed, whether the preview's dock is floating or full screen (QGIS saves
    its layout then); it stays open."""

    def __init__(self):
        super().__init__()
        self.closed_with = []

    def closeEvent(self, event):
        dock = self.findChild(QgsDockWidget, "XSectionsPreviewDock")
        self.closed_with.append((dock.isFloating(), dock.isFullScreen()))
        event.ignore()


class FullScreenCase(unittest.TestCase):
    def setUp(self):
        self._user = save_user_values(TOGGLE_KEYS)
        for k in TOGGLE_KEYS:
            settings_store.set_user_value(k, "1")

    def tearDown(self):
        restore_user_values(self._user)

    def docked(self, area=Bottom, size=260, at=(20, 20, 760, 700)):
        """A shown main window at `at` (x, y, width, height) with the preview, a section drawn, in a QgsDockWidget
        docked in `area`, `size` px across it."""
        win = Main()
        self.addCleanup(self._close, win)
        central = QWidget()
        central.setMinimumSize(200, 100)
        win.setCentralWidget(central)
        dock = QgsDockWidget("XSections preview", win)
        dock.setObjectName("XSectionsPreviewDock")
        pv = PreviewWidget(dock)
        dock.setWidget(pv)
        win.addDockWidget(area, dock)
        win.setGeometry(*at)
        win.show()
        APP.processEvents()
        win.resizeDocks([dock], [size], orientation(area))
        APP.processEvents()
        pv.draw(make_model(), make_settings(), make_plan())
        settle(pv)
        across = dock.height() if orientation(area) == Qt.Orientation.Vertical else dock.width()
        self.assertEqual(across, size)
        return win, dock, pv

    @staticmethod
    def _close(win):
        win.hide()
        win.deleteLater()
        APP.processEvents()

    def toggle(self, pv):
        pv.act_full.trigger()
        spin()
        settle(pv)

    def assertFullScreen(self, dock, pv, screen=None):
        screen = screen or QGuiApplication.primaryScreen()
        self.assertTrue(pv.is_full_screen())
        self.assertTrue(pv.act_full.isChecked())
        self.assertTrue(dock.isFloating())
        self.assertTrue(dock.isFullScreen())
        self.assertTrue(dock.isVisible())
        self.assertEqual(dock.geometry(), screen.geometry())
        self.assertIs(dock.screen(), screen)
        vp = pv.scroll.viewport()
        self.assertEqual(pv._vp, (vp.width(), vp.height()), "laid out for the full screen")
        self.assertEqual(pv.zoom, 1.0, "fitted")
        self.assertEqual((pv.canvas.width(), pv.canvas.height()), pv._vp)
        w, h = pv.figure.get_size_inches()
        self.assertAlmostEqual(w * BASE_DPI, vp.width(), delta=1.0)
        self.assertAlmostEqual(h * BASE_DPI, vp.height(), delta=1.0)

    def assertDocked(self, win, dock, pv, area=Bottom, size=260):
        self.assertFalse(pv.is_full_screen())
        self.assertFalse(pv.act_full.isChecked())
        self.assertFalse(dock.isFloating())
        self.assertFalse(dock.isFullScreen())
        self.assertEqual(win.dockWidgetArea(dock), area)
        across = dock.height() if orientation(area) == Qt.Orientation.Vertical else dock.width()
        self.assertLessEqual(abs(across - size), SIZE_TOL, (across, size))
        self.assertEqual(pv.zoom, 1.0, "fitted")


# ------------------------------------------------------------------ the button
class ButtonTest(FullScreenCase):
    def test_the_last_button_of_the_toolbar(self):
        pv = PreviewWidget()
        self.addCleanup(pv.deleteLater)
        acts = pv.toolbar.actions()
        self.assertIs(acts[-1], pv.act_full)
        self.assertTrue(acts[-2].isSeparator())
        self.assertIs(acts[-3], pv.act_popup)
        a = pv.act_full
        self.assertEqual((a.text(), tip_text(a.toolTip())), ("Full screen", TIP))     # (0.3.7 finish: it wraps)
        self.assertTrue(a.isCheckable() and a.isEnabled())
        self.assertFalse(a.isChecked() or pv.is_full_screen())
        # F11 stays QGIS's; Esc is no shortcut while the preview is not full screen
        shortcuts = [s.toString() for act in pv.toolbar.actions() + pv.actions() for s in act.shortcuts()]
        self.assertEqual(shortcuts, [])

    def test_the_icon_points_out_and_checked_in(self):
        pv = PreviewWidget()
        self.addCleanup(pv.deleteLater)
        icon = pv.act_full.icon()
        off = icon.pixmap(24, 24, QIcon.Mode.Normal, QIcon.State.Off).toImage()
        on = icon.pixmap(24, 24, QIcon.Mode.Normal, QIcon.State.On).toImage()
        self.assertNotEqual(off, on)
        for x, y in ((3, 3), (20, 3), (3, 20), (20, 20)):                 # the square's corners
            self.assertGreater(off.pixelColor(x, y).alpha(), 128, (x, y))
            self.assertEqual(on.pixelColor(x, y).alpha(), 0, (x, y))
        for x, y in ((9, 9), (14, 9), (9, 14), (14, 14)):                 # 5 units in: the checked corners
            self.assertGreater(on.pixelColor(x, y).alpha(), 128, (x, y))
            self.assertEqual(off.pixelColor(x, y).alpha(), 0, (x, y))
        self.assertEqual(off.pixelColor(12, 12).alpha(), 0)               # nothing in the middle
        self.assertEqual(on.pixelColor(12, 12).alpha(), 0)

    def test_the_theme_s_text_colour(self):
        # as the hover toggles: the text colour (QGIS's dark themes leave the button text to the system), and a
        # theme change draws it again
        host = QWidget()
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
        for state in (QIcon.State.Off, QIcon.State.On):
            self.assertEqual(ink(pv.act_full.icon(), state), {"#aaaaaa"}, state)
        QApplication.setPalette(old)
        APP.processEvents()
        for state in (QIcon.State.Off, QIcon.State.On):
            self.assertEqual(ink(pv.act_full.icon(), state), {old.color(QPalette.ColorRole.WindowText).name()})

    def test_without_a_shown_dock_nothing_happens(self):
        pv = PreviewWidget()                               # a window of its own: no dock to float
        self.addCleanup(pv.deleteLater)
        pv.resize(600, 300)
        pv.show()
        APP.processEvents()
        pv.act_full.trigger()
        APP.processEvents()
        self.assertFalse(pv.is_full_screen() or pv.act_full.isChecked() or pv.isFullScreen())
        win, dock, pv = self.docked()
        dock.hide()
        pv.set_full_screen(True)                           # (a hidden dock: nothing to show)
        spin()
        self.assertFalse(pv.is_full_screen() or pv.act_full.isChecked() or dock.isFloating())
        pv.leave_full_screen()                             # (not full screen: nothing to put back)
        self.assertFalse(dock.isFloating())


# ------------------------------------------------------------------ on and off
class ToggleTest(FullScreenCase):
    def test_docked_goes_full_screen_and_back(self):
        win, dock, pv = self.docked()
        width = dock.width()
        pv.set_zoom(3.0)
        self.assertEqual(pv.zoom, 3.0)
        self.toggle(pv)
        self.assertFullScreen(dock, pv)
        self.assertTrue(pv.toolbar.isVisible() and pv.readout.isVisible())
        self.assertIs(QApplication.activeWindow(), dock)
        self.assertIs(QApplication.focusWidget(), pv.canvas)
        # the zoom, the readout row and the hover work full screen
        pv.act_zoom_in.trigger()
        self.assertEqual(pv.zoom, 1.5)
        pv.act_fit.trigger()
        settle(pv)
        self.events = []
        pv.hoverChanged.connect(lambda st, i: self.events.append(st))
        move(pv, vp_of(pv, 1500.0, 520.0))
        self.assertEqual(pv.readout.mode, "values")
        self.assertAlmostEqual(self.events[-1], 1500.0, delta=5.0)
        self.toggle(pv)                                    # the button again
        self.assertDocked(win, dock, pv)
        self.assertEqual(dock.width(), width)
        self.assertTrue(dock.isVisible())
        vp = pv.scroll.viewport()
        self.assertEqual(pv._vp, (vp.width(), vp.height()), "laid out for the dock again")
        # floated by hand later: where it floated before, not over the whole screen
        dock.setFloating(True)
        APP.processEvents()
        self.assertEqual(dock.size(), QSize(width, 260))
        self.assertNotEqual(dock.geometry(), QGuiApplication.primaryScreen().geometry())

    def test_floating_goes_full_screen_and_back_to_its_place(self):
        win, dock, pv = self.docked()
        dock.setFloating(True)
        dock.setGeometry(QRect(120, 140, 520, 300))
        APP.processEvents()
        g = dock.geometry()
        self.toggle(pv)
        self.assertFullScreen(dock, pv)
        self.toggle(pv)
        self.assertFalse(pv.is_full_screen() or pv.act_full.isChecked())
        self.assertTrue(dock.isFloating() and dock.isVisible())
        self.assertFalse(dock.isFullScreen())
        self.assertEqual(dock.geometry(), g)
        self.assertEqual(pv.zoom, 1.0)
        dock.setFloating(False)                            # (its place in the area is still there)
        APP.processEvents()
        self.assertEqual(win.dockWidgetArea(dock), Bottom)

    def test_a_side_dock_comes_back_at_its_width(self):
        win, dock, pv = self.docked(LeftArea, 330)
        height = dock.height()
        self.toggle(pv)
        self.assertFullScreen(dock, pv)
        self.toggle(pv)
        self.assertDocked(win, dock, pv, LeftArea, 330)
        self.assertEqual(dock.height(), height)

    def test_a_tabbed_dock_comes_back_into_its_tabs(self):
        win, dock, pv = self.docked()
        other = QgsDockWidget("Another panel", win)
        other.setObjectName("AnotherDock")
        other.setWidget(QWidget())
        win.addDockWidget(Bottom, other)
        win.tabifyDockWidget(other, dock)
        dock.raise_()
        APP.processEvents()
        win.resizeDocks([dock], [300], Qt.Orientation.Vertical)
        APP.processEvents()
        self.assertEqual(win.tabifiedDockWidgets(dock), [other])
        height = dock.height()                             # (resizeDocks sized the tabs, their bar too)
        self.assertLess(height, 300)
        self.toggle(pv)
        self.assertFullScreen(dock, pv)
        win.resizeDocks([other], [120], Qt.Orientation.Vertical)    # (the tab left behind made lower meanwhile)
        APP.processEvents()
        self.assertEqual(other.height(), 120)
        self.toggle(pv)
        self.assertDocked(win, dock, pv, size=height)
        self.assertEqual(win.tabifiedDockWidgets(dock), [other])
        self.assertFalse(dock.visibleRegion().isEmpty(), "its tab in front")

    def test_the_size_comes_back_even_when_the_area_changed_meanwhile(self):
        # the main window made smaller and larger again while the preview was full screen (the empty bottom area
        # had no size of its own then): the dock is sized again in its area
        win, dock, pv = self.docked(size=300)
        self.toggle(pv)
        win.resize(700, 420)
        APP.processEvents()
        win.resize(760, 700)
        APP.processEvents()
        self.toggle(pv)
        self.assertDocked(win, dock, pv, size=300)

    def test_the_size_comes_back_when_another_panel_took_the_area(self):
        # another panel docked at the bottom while the preview was full screen, the area made lower for it: the
        # preview comes back beside it at its own height
        win, dock, pv = self.docked(size=300)
        self.toggle(pv)
        other = QgsDockWidget("Another panel", win)
        other.setObjectName("AnotherDock")
        other.setWidget(QWidget())
        win.addDockWidget(Bottom, other)
        APP.processEvents()
        win.resizeDocks([other], [120], Qt.Orientation.Vertical)
        APP.processEvents()
        self.assertEqual(other.height(), 120)
        self.toggle(pv)
        self.assertDocked(win, dock, pv, size=300)
        self.assertTrue(other.isVisible())
        self.assertEqual(win.dockWidgetArea(other), Bottom)

    def test_nothing_is_remembered(self):
        before = settings_store.user_value("full_screen", None)
        win, dock, pv = self.docked()
        self.toggle(pv)
        self.toggle(pv)
        self.assertEqual(settings_store.user_value("full_screen", None), before)
        again = PreviewWidget()                            # a new preview never starts full screen
        self.addCleanup(again.deleteLater)
        self.assertFalse(again.is_full_screen() or again.act_full.isChecked())


# ------------------------------------------------------------------ keys
class KeyTest(FullScreenCase):
    def override(self, widget, k):
        """Whether `widget` takes key `k` before the shortcuts (ShortcutOverride accepted)."""
        ev = QKeyEvent(QEvent.Type.ShortcutOverride, k, NoMod)
        ev.ignore()
        QApplication.sendEvent(widget, ev)
        return ev.isAccepted()

    def test_esc_puts_it_back_and_the_zoom_keys_still_work(self):
        win, dock, pv = self.docked()
        self.assertFalse(self.override(pv.canvas, Qt.Key.Key_Escape), "docked: Esc is QGIS's")
        key(pv, Qt.Key.Key_Escape)
        self.assertFalse(pv.is_full_screen() or dock.isFloating())
        self.toggle(pv)
        self.assertFullScreen(dock, pv)
        self.assertTrue(self.override(pv.canvas, Qt.Key.Key_Escape))
        self.assertFalse(self.override(pv.canvas, Qt.Key.Key_F11), "F11 stays QGIS's")
        key(pv, Qt.Key.Key_Plus, "+")
        self.assertEqual(pv.zoom, 1.5)
        key(pv, Qt.Key.Key_Minus, "-")
        self.assertEqual(pv.zoom, 1.0)
        key(pv, Qt.Key.Key_Plus, "+")
        key(pv, Qt.Key.Key_0, "0")
        self.assertEqual(pv.zoom, 1.0)
        self.assertTrue(pv.is_full_screen())
        pv.set_zoom(2.0)                                   # Esc in the middle of a drag: the drag ends too
        mouse(pv, QEvent.Type.MouseButtonPress, vp_of(pv, 1500.0, 520.0), LeftButton, LeftButton)
        self.assertIsNotNone(pv._drag)
        key(pv, Qt.Key.Key_Escape)
        spin()
        settle(pv)
        self.assertDocked(win, dock, pv)
        self.assertIsNone(pv._drag)
        self.assertNotEqual(pv.canvas.cursor().shape(), Qt.CursorShape.ClosedHandCursor)
        self.assertFalse(self.override(pv.canvas, Qt.Key.Key_Escape))

    def test_esc_with_the_focus_elsewhere_in_the_window(self):
        win, dock, pv = self.docked()
        self.toggle(pv)
        pv.canvas.clearFocus()
        dock.setFocus()
        APP.processEvents()
        self.assertIs(QApplication.activeWindow(), dock)
        self.assertIsNot(QApplication.focusWidget(), pv.canvas)
        QTest.keyClick(dock, Qt.Key.Key_Escape)            # (through the shortcut map, as a real key press)
        spin()
        settle(pv)
        self.assertDocked(win, dock, pv)

    def test_esc_is_qgis_s_while_docked(self):
        # a main-window Esc shortcut (a map tool's, say) keeps working while the preview is docked, and does not fire
        # while the preview is full screen with the focus in it
        win, dock, pv = self.docked()
        fired = []
        esc = QAction("Cancel", win)
        esc.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        esc.triggered.connect(lambda: fired.append(1))
        win.addAction(esc)
        win.activateWindow()
        win.centralWidget().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        win.centralWidget().setFocus()
        APP.processEvents()
        QTest.keyClick(win.centralWidget(), Qt.Key.Key_Escape)
        self.assertEqual(fired, [1])
        pv.canvas.setFocus()
        QTest.keyClick(pv.canvas, Qt.Key.Key_Escape)       # docked, the focus on the plot: still QGIS's
        self.assertEqual(fired, [1, 1])
        self.assertFalse(pv.is_full_screen())
        self.toggle(pv)
        QTest.keyClick(pv.canvas, Qt.Key.Key_Escape)
        spin()
        settle(pv)
        self.assertEqual(fired, [1, 1])
        self.assertDocked(win, dock, pv)


# ------------------------------------------------------------------ never lost
class NeverLostTest(FullScreenCase):
    def test_closed_or_hidden_while_full_screen_comes_back_docked(self):
        for how in ("Alt+F4", "hidden"):
            for floated in (False, True):
                with self.subTest(how=how, floated_before=floated):
                    self.check_closed_or_hidden(how, floated)

    def check_closed_or_hidden(self, how, floated):
        win, dock, pv = self.docked(size=320)
        if floated:                                        # floated by hand once before, then docked again
            dock.setFloating(True)
            dock.setGeometry(QRect(100, 100, 500, 260))
            APP.processEvents()
            dock.setFloating(False)
            APP.processEvents()
            win.resizeDocks([dock], [320], Qt.Orientation.Vertical)
            APP.processEvents()
            floats_at = QRect(100, 100, 500, 260)
        else:                                              # (Qt floats it the first time where it is docked)
            floats_at = QRect(dock.mapToGlobal(QPoint(0, 0)), dock.size())
        self.toggle(pv)
        self.assertFullScreen(dock, pv)
        if how == "Alt+F4":
            self.assertTrue(dock.close())
        else:
            dock.hide()                                    # (the plugin's button)
        spin()
        self.assertTrue(dock.isHidden())
        self.assertFalse(pv.is_full_screen() or pv.act_full.isChecked())
        self.assertFalse(dock.isFloating() or dock.isFullScreen())
        self.assertEqual(win.dockWidgetArea(dock), Bottom)
        other = QgsDockWidget("Another panel", win)        # (the bottom area lower meanwhile, for another)
        other.setObjectName("AnotherDock")
        other.setWidget(QWidget())
        win.addDockWidget(Bottom, other)
        APP.processEvents()
        win.resizeDocks([other], [120], Qt.Orientation.Vertical)
        APP.processEvents()
        self.assertEqual(other.height(), 120)
        dock.show()
        spin()
        settle(pv)
        self.assertTrue(dock.isVisible())
        self.assertDocked(win, dock, pv, size=320)
        # floated by hand later (its title bar's button): where it floated before, not over the whole screen
        dock.setFloating(True)
        APP.processEvents()
        self.assertTrue(dock.isFloating() and not dock.isFullScreen())
        self.assertEqual(dock.geometry(), floats_at)

    def test_qgis_toggle_panels_leaves_it_full_screen(self):
        # QGIS's Toggle Panels Visibility (Ctrl+Tab) hides only the docked panels (QgisApp::toggleReducedView skips
        # floating ones): the full-screen preview stays, the panels behind it go and come back, and it docks again
        win, dock, pv = self.docked()
        other = QgsDockWidget("Another panel", win)
        other.setObjectName("AnotherDock")
        other.setWidget(QWidget())
        win.addDockWidget(RightArea, other)
        APP.processEvents()
        self.toggle(pv)
        hidden = [d for d in win.findChildren(QgsDockWidget)
                  if d.isVisible() and not d.isFloating()
                  and win.dockWidgetArea(d) != Qt.DockWidgetArea.NoDockWidgetArea]
        self.assertEqual(hidden, [other])
        for d in hidden:
            d.hide()
        spin()
        settle(pv)
        self.assertFullScreen(dock, pv)
        for d in hidden:                                   # (Ctrl+Tab again)
            d.show()
        spin()
        self.assertFullScreen(dock, pv)
        self.toggle(pv)
        self.assertDocked(win, dock, pv)
        self.assertTrue(other.isVisible())

    def test_qgis_closing_puts_it_back_before_it_saves_the_layout(self):
        win, dock, pv = self.docked()
        self.toggle(pv)
        QApplication.sendEvent(win, QCloseEvent())
        self.assertEqual(win.closed_with, [(False, False)], "docked when the main window saw the close")
        spin()
        settle(pv)
        self.assertDocked(win, dock, pv)


# ------------------------------------------------------------------ the plugin
class PluginTest(FullScreenCase):
    def setUp(self):
        super().setUp()
        from tests.test_e2e import flush_deletes, make_qgis_window
        from xsections import classFactory
        self.flush = flush_deletes
        load_project()
        self.iface, self.mw = make_qgis_window(760, 700)
        self.plugin = classFactory(self.iface)
        self.plugin.initGui()
        self.addCleanup(self._unload)
        self.plugin.action.trigger()                       # both panels open
        APP.processEvents()
        self.pv, self.pdock = self.plugin.preview, self.plugin.preview_dock
        self.mw.resizeDocks([self.pdock], [240], Qt.Orientation.Vertical)
        APP.processEvents()
        self.pv.draw(make_model(), make_settings(), make_plan())
        settle(self.pv)
        self.height = self.pdock.height()

    def _unload(self):
        if self.plugin.dock is not None:
            self.plugin.unload()
        self.mw.hide()
        self.mw.deleteLater()
        self.flush()

    def test_the_plugin_s_button_while_full_screen(self):
        size = self.pdock.size()
        self.toggle(self.pv)
        self.assertFullScreen(self.pdock, self.pv)
        self.plugin.action.trigger()                       # both panels closed
        spin()
        self.assertTrue(self.pdock.isHidden())
        self.assertFalse(self.pv.is_full_screen() or self.pdock.isFloating())
        self.plugin.action.trigger()                       # open again: docked, at its height
        spin()
        settle(self.pv)
        self.assertDocked(self.mw, self.pdock, self.pv, Bottom, self.height)
        self.pdock.setFloating(True)                       # floated by hand: at its size, not the screen's
        APP.processEvents()
        self.assertEqual(self.pdock.size(), size)
        self.assertNotEqual(self.pdock.geometry(), QGuiApplication.primaryScreen().geometry())

    def test_a_project_closed_puts_it_back(self):
        self.toggle(self.pv)
        QgsProject.instance().clear()
        spin()
        settle(self.pv)
        self.assertTrue(self.pdock.isVisible())
        self.assertDocked(self.mw, self.pdock, self.pv, Bottom, self.height)

    def test_unload_while_full_screen_puts_it_back_first(self):
        self.toggle(self.pv)
        self.assertFullScreen(self.pdock, self.pv)
        seen = []

        def removed(dock):
            seen.append((dock.objectName(), dock.isFloating(), dock.isFullScreen(), self.mw.dockWidgetArea(dock)))
            self.mw.removeDockWidget(dock)

        self.iface.removeDockWidget.side_effect = removed
        pdock = self.pdock
        self.plugin.unload()
        self.flush()
        self.assertIn(("XSectionsPreviewDock", False, False, Bottom), seen)
        self.assertTrue(sip.isdeleted(pdock))
        self.assertIsNone(self.plugin.preview_dock)


# ------------------------------------------------------------------ two screens
class TwoScreensTest(FullScreenCase):
    """The dock fills the screen it is on, not always the primary one (a new Python on two offscreen screens)."""

    def test_on_two_screens(self):
        if os.environ.get(TWO_SCREENS_ENV):
            self.skipTest("(runs in the new Python only)")
        code, out = run_on_two_screens("tests.test_preview_fullscreen.TwoScreensTest.check_two_screens")
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("OK", out)

    def check_two_screens(self):
        if not os.environ.get(TWO_SCREENS_ENV):
            self.skipTest("(on two screens only: test_on_two_screens)")
        left, right = QGuiApplication.screens()
        self.assertEqual((left.name(), right.name()), ("Left", "Right"))
        self.assertIs(QGuiApplication.primaryScreen(), left)
        # the main window mostly on the left screen, its right dock on the right one: that one
        win, dock, pv = self.docked(RightArea, 400, at=(200, 40, 1700, 860))
        self.assertIs(win.screen(), left)
        self.assertIs(QGuiApplication.screenAt(dock.mapToGlobal(dock.rect().center())), right)
        self.toggle(pv)
        self.assertFullScreen(dock, pv, right)
        self.toggle(pv)
        self.assertDocked(win, dock, pv, RightArea, 400)
        # floating on the left screen: the left one
        dock.setFloating(True)
        dock.setGeometry(QRect(100, 120, 600, 300))
        APP.processEvents()
        g = dock.geometry()
        self.toggle(pv)
        self.assertFullScreen(dock, pv, left)
        self.toggle(pv)
        self.assertEqual(dock.geometry(), g)
        self.assertTrue(dock.isFloating() and not dock.isFullScreen())
        # the main window all on the right screen, the dock docked at the bottom: the right one
        dock.setFloating(False)
        win.removeDockWidget(dock)
        win.addDockWidget(Bottom, dock)
        dock.show()
        win.setGeometry(1700, 40, 1400, 900)
        APP.processEvents()
        win.resizeDocks([dock], [300], Qt.Orientation.Vertical)
        APP.processEvents()
        self.toggle(pv)
        self.assertFullScreen(dock, pv, right)
        self.toggle(pv)
        self.assertDocked(win, dock, pv, Bottom, 300)


if __name__ == "__main__":
    unittest.main()
