"""The panel and the preview under an application stylesheet (0.3.7 fix). QGIS's Night Mapping and Blend of Gray UI
themes set a stylesheet on the whole application (QgsApplication.setUITheme: the install's style.qss with the
@variables of its variables.qss, then its palette.txt on the application palette). Under it a widget's own
setStyleSheet re-polishes the widget, and the polish sets its palette: a PaletteChange. 0.3.6's check card answered
that by setting its stylesheet again and recursed until the stack overflowed (building the panel crashed).

Under each theme, through QGIS's own setUITheme and the real theme files, and with none: the whole XSectionsDock and
its PreviewWidget docked in a main window, built under it; every section opened, every row's editor (each tab of an
exploration row), every option popup, a check card, the Size list and a Symbol list; Verbose on and off; the palette
light, dark and back; the application stylesheet switched at runtime with the card open and the preview full screen.
Every changeEvent and _apply_theme of xsections.ui is counted (Recorder): no _apply_theme may run inside itself on one
widget, no changeEvent may answer a change with the same change again and again, and once the events have settled
none may keep coming.

0.3.7 finish (the review of that fix): CardHeight, the check card's wrapped labels exactly as tall as their text with
and without a theme; Readable, under each theme the real dock's text measured on grabs (4.5:1 or better on its
surfaces; Blend of Gray's #0e0e0e was 1.2:1), a disabled field label on no box, and the Size list's foot padding and
box border."""
import functools
import importlib
import pkgutil
import unittest
from collections import Counter
from typing import Optional
from unittest import mock

from tests.fixtures import (TOLERANCE, area_row, load_project, make_areas_layer, make_others_layer, make_seeps_layer,
                            make_streams_layer, make_supply_layer, point_row, seep_row, start_app, stream_row)

APP = start_app()

from qgis.core import QgsApplication  # noqa: E402
from qgis.gui import QgsDockWidget  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QPoint, QRect, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFontMetrics, QPalette  # noqa: E402
from qgis.PyQt.QtTest import QTest  # noqa: E402
from qgis.PyQt.QtWidgets import (QCheckBox, QLabel, QMainWindow, QStyle, QStyleOptionButton,  # noqa: E402
                                 QVBoxLayout, QWidget)

import xsections.ui  # noqa: E402
from tests.test_panel_036 import water_table  # noqa: E402
from tests.test_panel_widgets import light_palette, night_palette  # noqa: E402
from tests.test_preview_tools import settle as settle_preview  # noqa: E402
from tests.test_ui import make_iface  # noqa: E402
from xsections.core.model import Settings  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402
from xsections.ui.dock import XSectionsDock  # noqa: E402
from xsections.ui.point_rows import TAB_KEYS  # noqa: E402
from xsections.ui.preview import PreviewWidget  # noqa: E402

THEMES = ("Night Mapping", "Blend of Gray")
THEME_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange, QEvent.Type.StyleChange,
                QEvent.Type.FontChange, QEvent.Type.ApplicationFontChange)
WATCHED = ("changeEvent", "_apply_theme")


def settle(n=12):
    for _ in range(n):
        APP.processEvents()


def ui_classes():
    """Every class defined in a module of xsections.ui (all of them imported)."""
    out = []
    for info in pkgutil.iter_modules(xsections.ui.__path__):
        mod = importlib.import_module(f"xsections.ui.{info.name}")
        out += [c for c in vars(mod).values() if isinstance(c, type) and c.__module__ == mod.__name__]
    return out


class Recorder:
    """Counts each call of the changeEvent and _apply_theme that a class of xsections.ui defines, and notes each run
    inside itself on one widget (a super() call into a base class's own is not one) with the event types of the nest,
    outermost first. Some are Qt's own and end there (a StyleChange brings a ContentsRectChange; the check card's
    PaletteChange sets its stylesheet, which brings a StyleChange and a PaletteChange it leaves alone); a loop is a
    nest holding one type a third time (a change answered by the same change, answered again), or an _apply_theme
    inside itself. A call deeper than CAP is not made, and is noted: a loop fails the test instead of overflowing the
    stack."""

    CAP = 8

    def __init__(self, case: unittest.TestCase):
        self.calls: Counter = Counter()          # (class name, method) -> calls
        self.events: Counter = Counter()         # theme event types (THEME_EVENTS) that reached a changeEvent
        self.nests: dict = {}                    # (class name, method) -> {(type names of a nest, outermost first)}
        self.refused: Counter = Counter()        # (class name, method) -> calls not made (past CAP)
        self._running: dict = {}                 # (widget id, class, method) -> the type names running now
        for cls in ui_classes():
            for name in WATCHED:
                if name in vars(cls):
                    patcher = mock.patch.object(cls, name, self._wrap(cls, name, vars(cls)[name]))
                    patcher.start()
                    case.addCleanup(patcher.stop)

    def _wrap(self, cls, name, orig):
        key = (cls.__name__, name)

        @functools.wraps(orig)
        def counted(obj, *args):
            self.calls[key] += 1
            et = args[0].type() if name == "changeEvent" and args else None
            if et in THEME_EVENTS:
                self.events[et] += 1
            k = (id(obj), cls, name)
            running = self._running.setdefault(k, [])
            running.append(et.name if et is not None else name)
            try:
                if len(running) > 1:
                    self.nests.setdefault(key, set()).add(tuple(running))
                if len(running) > self.CAP:
                    self.refused[key] += 1
                    return None
                return orig(obj, *args)
            finally:
                running.pop()
                if not running:
                    del self._running[k]
        return counted

    def loops(self):
        """(class, method, nest) of every loop: an _apply_theme inside itself, a type a third time in a nest."""
        return sorted((c, m, nest) for (c, m), nests in self.nests.items() for nest in nests
                      if m == "_apply_theme" or max(Counter(nest).values()) > 2)


class StylesheetCase(unittest.TestCase):
    def setUp(self):
        self.old_pal = QPalette(APP.palette())
        self.addCleanup(self._restore)
        self.rec = Recorder(self)

    def _restore(self):
        QgsApplication.setUITheme("default")              # (no stylesheet; QGIS leaves the palette as it was)
        APP.setPalette(self.old_pal)
        settle()

    def set_theme(self, name: str) -> None:
        """As QGIS applies its UI theme `name` ("default": none): QgsApplication.setUITheme, the install's files."""
        if name != "default" and name not in QgsApplication.uiThemes():
            self.skipTest(f"this QGIS has no {name} theme")
        QgsApplication.setUITheme(name)
        self.assertEqual(bool(APP.styleSheet()), name != "default", name)

    def assertClean(self, step: str) -> None:
        self.assertEqual(self.rec.loops(), [], step)
        self.assertEqual(dict(self.rec.refused), {}, step)


# ------------------------------------------------------------------ the check card on its own
class CardAlone(StylesheetCase):
    def test_the_card_sets_its_stylesheet_only_when_it_changes(self):
        for theme in ("default",) + THEMES:
            with self.subTest(theme=theme):
                self.card_under(theme)

    def card_under(self, theme: str) -> None:
        """A check card shown under `theme`, then the palette light, dark, dark again and light: its colours follow
        the palette, and its stylesheet is set once when they change, never when they do not."""
        self.set_theme(theme)
        self.addCleanup(APP.setPalette, QPalette(APP.palette()))
        host = QWidget()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.hide)
        host.resize(420, 320)
        host.show()
        card = W.CheckCard(host)
        card.set_content([W.CardInfo("1 exploration flagged", "Explorations · ExploDepth", [("MW-2", "no depth", "")],
                                     note="A note.")], [("open", "Open")])
        card.show()
        settle()
        patcher = mock.patch.object(card, "setStyleSheet", wraps=card.setStyleSheet)
        sets = patcher.start()
        self.addCleanup(patcher.stop)
        for pal in (light_palette(), night_palette(), night_palette(), light_palette()):
            sets.reset_mock()
            before = card.styleSheet()
            APP.setPalette(pal)
            settle()
            t = W.theme_for(card.palette())
            self.assertIn(W.css(t.muted), card.styleSheet())
            title = card.findChild(QLabel, "xsCardTitle")
            self.assertEqual(title.palette().color(QPalette.ColorRole.WindowText).name(), t.ink.name())
            self.assertEqual(sets.call_count, int(card.styleSheet() != before))
        self.assertClean(theme)
        self.assertGreater(self.rec.calls["CheckCard", "_apply_theme"], 0)


# ------------------------------------------------------------------ the whole panel and the preview
class PanelCase(StylesheetCase):
    def build(self):
        """The fixture project with every kind of row (explorations of three layers, one with a water table; seeps,
        a creek and a site), the dock restored on it and its PreviewWidget, both docked in a shown main window as
        QGIS has them, the section built by the real pipeline."""
        prj, dem, pts, lines = load_project()
        others, supply, seeps = make_others_layer(), make_supply_layer(), make_seeps_layer()
        creeks, site = make_streams_layer(name="Creeks"), make_areas_layer(name="Project site", names=["Project site"])
        table = water_table()
        prj.addMapLayers([others, supply, seeps, creeks, site, table])
        s = Settings(line_layer_id=lines.id(), line_fid=1, dem_layer_id=dem.id(), tolerance_ft=TOLERANCE,
                     point_layers=[
                         point_row(pts, label_field="ExploName", type_field="ExploType", top_field="ExploElev",
                                   depth_field="ExploDepth"),
                         point_row(others, label_field="ExploName", type_field="ExploType_resolved",
                                   top_field="ExploElev", depth_field="ExploDepth", look="gray", wl_table_id=table.id(),
                                   wl_table_name_field="ExploName", wl_table_elev_field="DTW", wl_values="depth"),
                         point_row(supply, label_field="AESI_MapLabel", type_field="ExploType_resolved",
                                   top_field="ExploElev", depth_field="ExploDepth", look="color")],
                     other_points=[seep_row(seeps, label_field="Name", elev="field", elev_field="Elev_ft"),
                                   stream_row(creeks, label_field="Name", name="Creeks"),
                                   area_row(site, label_field="Name", name="Project site")])
        win = QMainWindow()                            # as in QGIS: both docked in the main window
        central = QWidget()
        central.setMinimumSize(200, 100)
        win.setCentralWidget(central)
        view_dock = QgsDockWidget("XSections preview", win)
        view_dock.setObjectName("XSectionsPreviewDock")
        pv = PreviewWidget(view_dock)
        view_dock.setWidget(pv)
        win.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, view_dock)
        d = XSectionsDock(make_iface(), pv)
        win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, d)
        self.addCleanup(self._drop, win, d)
        settings_store.save(prj, s)
        d.restore_from_project()
        win.setGeometry(0, 0, 800, 800)
        win.show()
        settle()
        win.resizeDocks([d], [340], Qt.Orientation.Horizontal)
        win.resizeDocks([view_dock], [260], Qt.Orientation.Vertical)
        settle()
        d.refresh()
        settle_preview(pv)
        settle()
        self.assertEqual(d.last_error, "")
        self.assertIsNotNone(pv._ax)                   # the section drawn
        return d, pv

    @staticmethod
    def _drop(win, d):
        d.cleanup()
        win.hide()
        win.deleteLater()
        settle()

    def open_only(self, d, *sections):
        d.collapse_all()
        for sec in sections:
            sec.setCollapsed(False)
        settle()


class PanelAndPreview(PanelCase):
    def walk(self, theme: str) -> None:
        """Everything under `theme` (the dock and the preview built under it), then the other themes at runtime and
        back to it; the Recorder checked after each step."""
        self.set_theme(theme)
        theme_pal = QPalette(APP.palette())
        d, pv = self.build()
        self.assertClean("built")
        for sec in d.sections:                                       # every section, one at a time
            self.open_only(d, sec)
            self.assertFalse(sec.isCollapsed())
            self.assertClean(f"section {sec.title()}")
        self.open_only(d, d.grp_explo)                               # every row's editor, each exploration tab
        for row in d.explo_rows:
            for tab in TAB_KEYS:
                row.show_tab(tab)
                settle()
                self.assertEqual((row.editor_open(), row.current_tab()), (True, tab))
            row.set_editor_open(False)
        self.assertClean("exploration rows")
        for button in d.opt_grid.buttons():                          # every option popup
            self.assertTrue(d.opt_grid.open_popup(button), button.title())
            settle()
            self.assertTrue(d.opt_grid.current().isVisible(), button.title())
            self.assertClean(f"popup {button.title()}")
        d.opt_grid.close_popup()
        self.open_only(d, d.grp_other)
        self.assertEqual(len(d.other_rows), 3)
        lists = 0
        for row in d.other_rows:
            row.set_editor_open(True)
            settle()
            if row.symbol_combo.isVisible():                         # (a polygon row has no symbol)
                row.symbol_combo.showPopup()                         # the Symbol list
                settle()
                self.assertTrue(row.symbol_combo.view().isVisible())
                row.symbol_combo.hidePopup()
                lists += 1
            row.set_editor_open(False)
        self.assertEqual(lists, 2)                                   # the seeps' and the creek's
        self.assertClean("other features rows")
        self.open_only(d, d.grp_ground)
        for row in [d.ground_row] + d.surface_rows:
            row.set_editor_open(True)
            settle()
            row.set_editor_open(False)
        badge = d.ground_row.badge                                   # a check card (the fixture DEM's hole)
        self.assertFalse(badge.isHidden())
        d.scroll.ensureWidgetVisible(badge, 0, 0)
        settle()
        QTest.mouseClick(badge, Qt.MouseButton.LeftButton)
        settle()
        self.assertTrue(d.card_host.is_open() and d.card_host.card.isVisible())
        self.assertClean("check card")
        d.card_host.close()
        self.open_only(d, d.grp_export)                              # the Size list
        d.sheet.showPopup()
        settle()
        self.assertTrue(d.sheet.list_frame().isVisible())
        d.sheet.hidePopup()
        self.assertClean("size list")
        self.open_only(d, *d.sections)                               # all open: Verbose, palettes, themes
        self.addCleanup(W.set_verbose, False)
        for on in (True, False):
            W.set_verbose(on)
            settle()
            self.assertClean(f"verbose {on}")
        for pal in (light_palette(), night_palette(), theme_pal):
            APP.setPalette(pal)
            settle_preview(pv)
            settle()
            self.assertClean("palette")
        d.scroll.ensureWidgetVisible(badge, 0, 0)                    # the card open and the preview full screen
        settle()                                                     # while the themes switch
        QTest.mouseClick(badge, Qt.MouseButton.LeftButton)
        settle()
        self.assertTrue(d.card_host.is_open())
        pv.act_full.trigger()
        settle_preview(pv)
        settle()
        self.assertTrue(pv.is_full_screen())
        self.assertClean("full screen")
        for other in [t for t in THEMES if t != theme] + ["default"] + ([theme] if theme != "default" else []):
            if other != "default" and other not in QgsApplication.uiThemes():
                continue
            QgsApplication.setUITheme(other)
            settle_preview(pv)
            settle()
            self.assertClean(f"runtime switch to {other}")
        pv.act_full.trigger()
        settle_preview(pv)
        settle()
        self.assertFalse(pv.is_full_screen())
        d.card_host.close()
        # every theme hook ran (none inside itself: assertClean); settled, no theme event keeps coming
        for cls in ("CheckCard", "XSectionsDock", "PreviewWidget"):
            self.assertGreater(self.rec.calls[cls, "_apply_theme"], 0, cls)
        settle(30)
        self.rec.events.clear()
        settle(30)
        self.assertEqual(dict(self.rec.events), {}, "theme events after settling")
        self.assertClean("settled")

    def test_no_stylesheet(self):
        self.walk("default")

    def test_night_mapping(self):
        self.walk("Night Mapping")

    def test_blend_of_gray(self):
        self.walk("Blend of Gray")


# ------------------------------------------------------------------ 0.3.7 finish: what each theme shows
LONG_TITLE = "3 explorations have a top elevation that disagrees with LIDAR by more than 25 ft"


def dist(a: QColor, b: QColor) -> int:
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def text_contrast(img, rect: QRect) -> float:
    """The contrast of the text in `rect` (logical px) of a grab: the box's most common colour (the ground under the
    text) against the one farthest from it (the core of the letters)."""
    dpr = img.devicePixelRatio()
    counts: Counter = Counter()
    for y in range(int(rect.top() * dpr), int((rect.bottom() + 1) * dpr)):
        for x in range(int(rect.left() * dpr), int((rect.right() + 1) * dpr)):
            counts[img.pixel(x, y)] += 1
    ground = QColor.fromRgba(counts.most_common(1)[0][0])
    far = max((QColor.fromRgba(c) for c in counts), key=lambda c: dist(c, ground))
    return W.contrast(far, ground)


def in_(w: QWidget, top: QWidget, rect: Optional[QRect] = None) -> QRect:
    """`rect` of `w` (its whole rect when None) in `top`'s coordinates."""
    r = w.rect() if rect is None else rect
    return QRect(w.mapTo(top, r.topLeft()), r.size())


def pixel_at(img, pt: QPoint) -> str:
    dpr = img.devicePixelRatio()
    return img.pixelColor(int(pt.x() * dpr), int(pt.y() * dpr)).name()


class CardHeight(StylesheetCase):
    def test_each_wrapped_line_shows(self):
        for theme in ("default",) + THEMES:
            with self.subTest(theme=theme):
                self.card_under(theme)

    def card_under(self, theme: str) -> None:
        """A card of two blocks (a three-line title, long sources and notes, a one-line note) opened by CardHost
        from a badge in a 340 px panel under `theme`. Each wrapped label is as tall as its text at its width: its
        heightForWidth kept (0.3.7 finish: the fix of the card's stylesheet had dropped it without a theme, so the
        card was sized by sizeHint: the title's third line cut off, a one-line note given two lines)."""
        self.set_theme(theme)
        panel = QWidget()
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.hide)
        panel.resize(340, 900)
        lay = QVBoxLayout(panel)
        badge = W.CheckBadge(panel)
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight)
        lay.addStretch(1)
        panel.show()
        settle()
        host = W.CardHost(panel)
        badge.blocks = [
            W.CardInfo(LONG_TITLE, "Explorations by others · ExploElev, checked against LIDAR_DEM_3ft at each "
                                   "exploration", [("MW-2", "205.6 ft ignored: LIDAR 339.0 ft", " · top")],
                       note="Their tops come from LIDAR instead. Fix the table, or raise the limit under Depths."),
            W.CardInfo("2 water levels are not numbers; left out", "Boring Summary · DTW", [("O-1", "n/a", "")],
                       note="Text such as dry is left out.")]
        badge.actions = [("open_depths", "Open Depths"), ("open_water", "Open Water")]
        host.open(badge)
        settle()
        card = host.card
        self.assertTrue(card.isVisible())
        self.assertTrue(card.hasHeightForWidth())
        self.assertEqual(card.height(), card.heightForWidth(card.width()))
        wrapped = [lab for lab in card.findChildren(QLabel) if lab.isVisible() and lab.wordWrap()]
        self.assertEqual(len(wrapped), 6)                     # the titles, the sources, the notes
        for lab in wrapped:
            self.assertTrue(lab.hasHeightForWidth(), lab.text())
            self.assertEqual(lab.height(), lab.heightForWidth(lab.width()), lab.text())
        title = card.findChild(QLabel, "xsCardTitle")
        self.assertEqual(title.text(), LONG_TITLE)
        self.assertGreater(title.height(), 1.5 * QFontMetrics(title.font()).lineSpacing())     # (it wraps)
        host.close()
        self.assertClean(theme)


class Readable(PanelCase):
    """The panel's text on its own surfaces under each theme (0.3.7 finish), measured on grabs of the real dock:
    a layer row's name (closed and open), the open row's current tab, an option popup's title and check box, the
    check card's title and value read at WCAG's 4.5:1 or better (Blend of Gray: theme_for's own_ink; its text #0e0e0e
    was 1.2:1 there); a disabled field label sits on no box (Night Mapping's QWidget:disabled background) and, dark,
    reads at 2:1 or better; the Size list's foot has its padding and rule and its box its border."""

    def test_no_stylesheet(self):
        self.check("default")

    def test_night_mapping(self):
        self.check("Night Mapping")

    def test_blend_of_gray(self):
        self.check("Blend of Gray")

    def check(self, theme: str) -> None:
        self.set_theme(theme)
        d, _pv = self.build()
        t = W.theme_for(d.palette())
        self.assertEqual(t.own_ink, theme == "Blend of Gray")
        if t.dark:
            for surface in (t.open_body, t.row_open, t.pop):
                self.assertGreaterEqual(W.contrast(t.ink, surface), W.MIN_INK_CONTRAST)
            self.assertGreaterEqual(W.contrast(t.disabled, t.row_open), W.MIN_DISABLED_CONTRAST)
        content = d.content
        texts = {}
        # the rows: a closed one, the open one on its Water tab (its disabled Date labels)
        self.open_only(d, d.grp_explo)
        closed, row = d.explo_rows[0], d.explo_rows[1]
        row.show_tab("water")
        settle()
        img = content.grab().toImage()
        texts["closed row name"] = text_contrast(img, in_(closed.name_label, content))
        texts["open row name"] = text_contrast(img, in_(row.name_label, content))
        tab = row.tabs.tabRect(row.tabs.currentIndex()).adjusted(0, 0, 0, -3)          # (not its underline)
        texts["current tab"] = text_contrast(img, in_(row.tabs, content, tab))
        off = [lab for lab in row.findChildren(QLabel, "xsFieldLabel") if lab.isVisible() and not lab.isEnabled()]
        self.assertTrue(off)
        for lab in off:
            g = in_(lab, content)
            inside = pixel_at(img, QPoint(g.right() - 1, g.center().y()))             # (right of its text)
            outside = pixel_at(img, QPoint(g.left() - 3, g.center().y()))
            self.assertEqual(inside, outside, (theme, lab.text()))                    # no box behind it
            if t.dark:
                self.assertGreaterEqual(text_contrast(img, g), 2.0, (theme, lab.text()))
        row.set_editor_open(False)
        # the Depths popup: its title and a check box's text
        self.assertTrue(d.opt_grid.open_popup(d.opt_depths))
        settle()
        pop = d.opt_grid.current()
        d.scroll.ensureWidgetVisible(pop, 0, 0)
        settle()
        img = content.grab().toImage()
        texts["popup title"] = text_contrast(img, in_(pop.title_label, content))
        box = [b for b in pop.findChildren(QCheckBox) if b.isVisible()][0]
        opt = QStyleOptionButton()
        opt.initFrom(box)
        opt.text = box.text()
        words = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, opt, box)
        texts["popup check box"] = text_contrast(img, in_(box, content, words))
        d.opt_grid.close_popup()
        # the check card (a child of the dock's widget, over the content)
        self.open_only(d, d.grp_ground)
        badge = d.ground_row.badge
        d.scroll.ensureWidgetVisible(badge, 0, 0)
        settle()
        QTest.mouseClick(badge, Qt.MouseButton.LeftButton)
        settle()
        card, outer = d.card_host.card, d.widget()
        self.assertTrue(card.isVisible())
        img = outer.grab().toImage()
        texts["card title"] = text_contrast(img, in_(card.findChild(QLabel, "xsCardTitle"), outer))
        value = card.findChild(W.ElidedLabel, "xsCardValue")
        texts["card value"] = text_contrast(img, in_(value, outer, QRect(0, 0, value.sizeHint().width(),
                                                                         value.height())))
        d.card_host.close()
        for what, ratio in texts.items():
            self.assertGreaterEqual(ratio, W.MIN_INK_CONTRAST, (theme, what, round(ratio, 2)))
        # the Size list: the foot's padding (6 10 7 10) and rule, the box's 1 px border
        self.open_only(d, d.grp_export)
        d.sheet.showPopup()
        settle()
        lf = d.sheet.list_frame()
        self.assertTrue(lf.isVisible())
        m = lf.foot.contentsMargins()
        self.assertIn((m.left(), m.top(), m.right(), m.bottom()), [(10, 7, 10, 7), (11, 7, 11, 8)], theme)
        self.assertEqual(lf.box.frameWidth(), 1, theme)
        self.assertGreater(lf.foot.geometry().left(), 0, theme)                       # (inside the border)
        d.sheet.hidePopup()
        settle()
        self.assertClean(theme)


if __name__ == "__main__":
    unittest.main()
