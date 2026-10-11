"""Stage Q2 of 0.3.7 (ui/widgets.py) on its own: offscreen, small widgets, no project. The option buttons
(OptionButton), their popups (OptionPopup and its shadow plate) and OptionGrid's opening, closing, following and room
rules; SheetSizeCombo (the Size list: a check box per sheet size, an exclusive Custom, a foot line); ElidedComboBox and
_combo(elide=); the four stylesheet rules. QgsSettings only in the test profile fixtures.start_app sets (Verbose,
restored)."""
import time
import unittest

from tests.fixtures import budget, start_app, timing_test

APP = start_app()

from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QFontMetrics, QKeyEvent, QMouseEvent, QPalette  # noqa: E402
from qgis.PyQt.QtTest import QTest  # noqa: E402
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFrame,  # noqa: E402
                                 QGraphicsDropShadowEffect, QLabel, QLineEdit, QScrollArea, QStyle,
                                 QStyleOptionSlider, QVBoxLayout, QWidget)

from tests.test_panel_widgets import PALETTES, dist, light_palette, night_palette, px  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402

TITLES = ("All layers", "Depths", "Water & screens", "Plotted")
TIP_ALL = "Within, labels and label text, for every layer"
SIZES = [("letter", "Letter", "8.5 × 11 in"), ("tabloid", "Tabloid", "11 × 17 in"), ("ansic", "ANSI C", "17 × 22 in"),
         ("archc", "ARCH C", "18 × 24 in"), ("ansid", "ANSI D", "22 × 34 in"), ("archd", "ARCH D", "24 × 36 in")]
CUSTOM = ("custom", "Custom", "cut to the drawing")
FOOT = "Several: the smallest that fits · One: just that · None: Letter"
LeftButton, NoMod = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier


def settle(n=12):
    for _ in range(n):
        APP.processEvents()


def describe(keys, custom):
    """The tests' stand-in for the dock's size_text."""
    return ("custom" if custom else (", ".join(keys) or "none"), "tip")


def close_popups():
    """Close any popup window a test left open (a combo's list, the Size list)."""
    for _ in range(5):
        w = QApplication.activePopupWidget()
        if w is None:
            return
        w.close()
        settle(2)


def bar_part(bar, part):
    """The rectangle of a scroll bar's part (QStyle.SubControl: its handle, the groove below it), in bar
    coordinates."""
    opt = QStyleOptionSlider()
    bar.initStyleOption(opt)
    return bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, opt, part, bar)


class Count:
    def __init__(self, signal):
        self.args = []
        signal.connect(lambda *a: self.args.append(a))

    def __len__(self):
        return len(self.args)


class Panel:
    """A "panel" as the dock's: a top-level window holding a scroll area (no frame, no horizontal bar) whose content
    is the overlay. In the
    overlay: a spacer, a "section" (a 16 px heading over the OptionGrid: four options, each popup holding a field_box
    with a QDoubleSpinBox, a field_box with a _combo, and a Hint), then a "below" widget built after the grid (a later
    sibling of the popups). 25 px side margins: the grid is 290 px wide at 340, as a section body's inner width in the
    340 px dock. The panel stylesheet on the overlay; `pal` is set as the application's palette (as QGIS does: a
    stylesheet drops a palette set on a parent widget) and restored by close()."""

    def __init__(self, width=340, height=700, pal=None, below=300):
        self.old_pal = None
        if pal is not None:
            self.old_pal = QPalette(APP.palette())
            APP.setPalette(pal)
        self.window = QWidget()
        wl = QVBoxLayout(self.window)
        wl.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        wl.addWidget(self.scroll)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.overlay = QWidget()
        self.lay = QVBoxLayout(self.overlay)
        self.lay.setContentsMargins(25, 10, 25, 10)
        self.lay.setSpacing(8)
        self.spacer = QWidget()
        self.spacer.setFixedHeight(20)
        self.lay.addWidget(self.spacer)
        self.section = QWidget()
        sl = QVBoxLayout(self.section)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        head = QLabel("OPTIONS")
        head.setFixedHeight(16)
        sl.addWidget(head)
        self.grid = W.OptionGrid(self.overlay)
        self.spins, self.combos, self.hints = [], [], []
        for title in TITLES:
            _b, p = self.grid.add_option(title, TIP_ALL if title == "All layers" else f"tip: {title}")
            spin = QDoubleSpinBox()
            combo = W._combo([("Vertical", "v"), ("Horizontal", "h")])
            hint = W.Hint("A hint that shows only with Verbose on; long enough to wrap onto a second line here.")
            p.addWidget(W.field_box("Within", spin))
            p.addWidget(W.field_box("Labels", combo))
            p.addWidget(hint)
            self.spins.append(spin)
            self.combos.append(combo)
            self.hints.append(hint)
        sl.addWidget(self.grid)
        self.lay.addWidget(self.section)
        self.below = QWidget()
        self.below.setFixedHeight(max(1, below))
        self.lay.addWidget(self.below)
        self.lay.addStretch(1)
        self.scroll.setWidget(self.overlay)
        self.overlay.setStyleSheet(W.panel_stylesheet(W.theme_for(self.scroll.palette())))
        self.window.resize(width, height)
        self.window.show()
        self.window.activateWindow()                       # (the keyboard tests need the focus in it)
        QTest.qWaitForWindowActive(self.window, 1000)
        settle()

    def at(self, w, pt=QPoint(0, 0)):
        """`pt` of `w` in overlay coordinates."""
        return w.mapTo(self.overlay, pt)

    def close(self):
        if self.scroll is None:
            return
        close_popups()
        try:
            self.grid.close_popup()
            self.window.close()
            self.window.deleteLater()
        except RuntimeError:
            pass
        self.scroll = None
        if self.old_pal is not None:
            APP.setPalette(self.old_pal)
        settle(2)


class Case(unittest.TestCase):
    def panel(self, **kw):
        p = Panel(**kw)
        self.addCleanup(p.close)
        return p

    def tearDown(self):
        close_popups()


# ================================================================ 1. the button
class Button(Case):
    def test_paint_and_texts(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            host = QWidget()
            host.setPalette(pal)
            self.addCleanup(host.deleteLater)
            b = W.OptionButton("All layers", TIP_ALL, host)
            b.setGeometry(0, 0, 142, 42)
            host.resize(160, 60)
            host.show()
            settle()
            w = b.width()
            img = b.grab().toImage()
            self.assertLess(dist(px(img, 71, 21), t.field), 8, name)                    # closed: field
            self.assertLess(dist(px(img, 0, 21), t.field_line), dist(px(img, 0, 21), t.field), name)  # its border
            self.assertLess(dist(px(img, w - 16, 11), t.muted), 12, name)               # the chevron points down:
            self.assertLess(dist(px(img, w - 16, 14), t.field), 12, name)               # wide at its top
            b.setOpen(True)
            self.assertTrue(b.isOpen())
            img = b.grab().toImage()
            self.assertLess(dist(px(img, 71, 21), t.row_open), 8, name)                 # open: the band's fill
            self.assertLess(dist(px(img, 2, 21), t.row_rail), 8, name)                  # the rail-blue left edge
            self.assertLess(dist(px(img, 0, 21), t.band_line), dist(px(img, 0, 21), t.row_open), name)
            self.assertLess(dist(px(img, w - 13, 12), t.row_rail), dist(px(img, w - 13, 12), t.row_open), name)
            self.assertLess(dist(px(img, w - 16, 14), t.row_rail), 12, name)            # up: wide at its bottom
            self.assertLess(dist(px(img, w - 16, 11), t.row_open), 12, name)
            host.close()

    def test_summary_tooltip_size(self):
        b = W.OptionButton("All layers", TIP_ALL)
        self.addCleanup(b.deleteLater)
        self.assertEqual(b.toolTip(), TIP_ALL)
        b.setSummary("150 ft · vertical · name only")
        self.assertEqual(b.summary(), "150 ft · vertical · name only")
        self.assertEqual(b.toolTip(), TIP_ALL + "\n150 ft · vertical · name only")   # the full summary
        self.assertEqual((b.title(), b.accessibleName(), b.accessibleDescription()),
                         ("All layers", "All layers", "150 ft · vertical · name only"))
        b.resize(90, 42)
        shown = b.shownSummary()
        self.assertTrue(shown.endswith("…"), shown)
        self.assertLess(len(shown), len(b.summary()))
        b.resize(400, 42)
        self.assertEqual(b.shownSummary(), b.summary())
        self.assertEqual(b.sizeHint().height(), 42)
        self.assertEqual(b.minimumSizeHint(), QSize(60, 42))
        self.assertEqual(b.focusPolicy(), Qt.FocusPolicy.TabFocus)
        self.assertEqual(b.text(), "")                     # (no mnemonic from "Water & screens")
        b.setTip("other")
        self.assertEqual(b.toolTip(), "other\n150 ft · vertical · name only")
        self.assertEqual(W.OPT_H, 42)


# ================================================================ 2. the grid's layout
class GridLayout(Case):
    def test_two_columns_then_one(self):
        p = self.panel()
        g, bs = p.grid, p.grid.buttons()
        self.assertEqual(g.width(), 290)
        self.assertEqual(g.columns(), 2)
        self.assertEqual([b.title() for b in bs], list(TITLES))
        self.assertEqual([b.width() for b in bs], [142] * 4)
        self.assertEqual([(b.x(), b.y()) for b in bs], [(0, 0), (148, 0), (0, 48), (148, 48)])   # 6 px apart
        self.assertEqual(g.height(), 2 * 42 + 6)
        # one column while a half would cut the longest title ("Water & screens"; the 260 px dock with Segoe UI 9,
        # the panel shots; the tests' font is narrower, so the widths come from the titles' own need)
        need = max(b.sizeHint().width() for b in bs)
        self.assertEqual(need, max(29 + QFontMetrics(b._title_font()).horizontalAdvance(b.title()) for b in bs))
        narrow = 2 * need + W.OPT_GAP - 2
        p.window.resize(narrow + 50, 700)
        settle()
        self.assertEqual(g.width(), narrow)
        self.assertEqual(g.columns(), 1)
        self.assertEqual([(b.x(), b.y(), b.width()) for b in bs], [(0, 48 * i, narrow) for i in range(4)])
        self.assertEqual(g.height(), 4 * 42 + 3 * 6)
        p.window.resize(2 * need + W.OPT_GAP + 50, 700)    # just wide enough: two columns again
        settle()
        self.assertEqual(g.columns(), 2)
        p.window.resize(340, 700)
        settle()
        self.assertEqual((g.columns(), bs[1].x()), (2, 148))


# ================================================================ 3. opening
class Opening(Case):
    def test_a_click_opens_it_under_its_button(self):
        p = self.panel()
        g = p.grid
        toggled = Count(g.popupToggled)
        b1 = g.buttons()[1]
        QTest.mouseClick(b1, LeftButton)
        settle()
        pop, plate = g.popups()[1], g.plates()[1]
        self.assertIs(g.current(), pop)
        self.assertEqual(g.current_index(), 1)
        self.assertTrue(b1.isOpen())
        self.assertFalse(any(b.isOpen() for b in g.buttons() if b is not b1))
        self.assertTrue(pop.isVisible() and plate.isVisible())
        self.assertEqual(toggled.args, [(1, True)])
        gx = p.at(g).x()
        geo = pop.geometry()
        self.assertEqual(geo.x(), gx)
        self.assertEqual(geo.width(), g.width())
        self.assertEqual(geo.y(), p.at(b1, QPoint(0, b1.height())).y())                # the notch touches it
        self.assertEqual(plate.geometry(), pop.box_rect().translated(geo.topLeft()))     # under the box
        self.assertEqual(plate.geometry().y(), geo.y() + W.NOTCH_H)
        self.assertEqual(pop.notch_x(), p.at(b1, QPoint(b1.width() // 2, 0)).x() - gx)  # over its centre
        self.assertGreater(geo.height(), 36 + W.NOTCH_H)
        self.assertGreater(geo.bottom(), p.below.geometry().top())                     # over the "below" sibling
        spot = QPoint(geo.x() + 4, geo.bottom() - 3)
        self.assertTrue(p.below.geometry().contains(spot))
        self.assertTrue(W._within(p.overlay.childAt(spot), pop))                         # ... and above it
        kids = [k for k in p.overlay.children() if isinstance(k, QWidget)]              # (stacking order)
        self.assertGreater(kids.index(plate), kids.index(p.below))                      # its shadow too,
        self.assertEqual(kids.index(pop), kids.index(plate) + 1)                        # just under the popup
        self.assertIs(pop.parentWidget(), p.overlay)
        self.assertIs(plate.parentWidget(), p.overlay)
        self.assertEqual(p.overlay.layout().indexOf(pop), -1)                           # in no layout
        self.assertTrue(g.filtering())
        self.assertEqual(p.overlay.minimumHeight(), 0)                                  # it fits: no room asked
        self.assertTrue(g.open_popup(1))                                                # already open
        self.assertEqual(len(toggled), 1)

    def test_api_and_hidden_grid(self):
        p = self.panel()
        g = p.grid
        g.toggle(g.popups()[2])
        self.assertEqual(g.current_index(), 2)
        g.toggle(2)
        self.assertEqual(g.current_index(), -1)
        g.toggle(g.buttons()[3])
        self.assertIs(g.current(), g.popups()[3])
        g.close_popup()
        self.assertIsNone(g.current())
        self.assertFalse(g.open_popup(7))
        p.section.hide()
        self.assertFalse(g.open_popup(0))                  # the grid not visible: nothing opens
        self.assertEqual((g.current_index(), g.filtering()), (-1, False))


# ================================================================ 4. closing
class Closing(Case):
    def opened(self, p, i=1):
        g = p.grid
        g.close_popup()
        QTest.mouseClick(g.buttons()[i], LeftButton)
        settle()
        self.assertEqual(g.current_index(), i)
        return g.popups()[i]

    def closed(self, p):
        g = p.grid
        self.assertEqual(g.current_index(), -1)
        self.assertFalse(any(b.isOpen() for b in g.buttons()))
        self.assertFalse(any(x.isVisible() for x in g.popups() + g.plates()))
        self.assertFalse(g.filtering())                    # no application filter left

    def test_every_way_it_closes(self):
        p = self.panel()
        g = p.grid
        toggled = Count(g.popupToggled)
        self.opened(p)
        QTest.mouseClick(g.buttons()[1], LeftButton)       # a second click on its button
        settle()
        self.closed(p)
        self.assertEqual(toggled.args, [(1, True), (1, False)])
        pop = self.opened(p)
        QTest.mouseClick(pop.close_button, LeftButton)     # the ✕
        settle()
        self.closed(p)
        self.assertEqual(pop.close_button.toolTip(), "Close (Esc)")
        self.assertEqual(pop.close_button.accessibleName(), "Close")
        self.opened(p)
        QTest.mouseClick(p.below, LeftButton)              # a press anywhere else
        settle()
        self.closed(p)
        self.opened(p)
        QTest.mouseClick(p.spacer, LeftButton)
        self.closed(p)
        g.close_popup()                                    # twice: harmless
        g.close_popup()
        self.closed(p)
        QTest.mouseClick(p.below, LeftButton)              # a press with nothing open changes nothing
        self.closed(p)
        self.assertEqual(len(toggled), 8)

    def test_esc_in_the_panel_only(self):
        p = self.panel()
        g = p.grid
        self.opened(p)
        spin = p.spins[1]
        spin.setFocus()
        settle()
        self.assertTrue(W._within(QApplication.focusWidget(), p.overlay))
        ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Escape, NoMod)
        ev.ignore()
        QApplication.sendEvent(spin, ev)
        self.assertTrue(ev.isAccepted(), "Esc belongs to the open popup while the focus is in the panel")
        self.assertEqual(g.current_index(), 1)
        QTest.keyClick(spin, Qt.Key.Key_Escape)
        settle()
        self.closed(p)
        # a mouse open: Qt's click focus goes past the TabFocus button to the scroll area around the content
        self.assertTrue(g.buttons()[1].hasFocus())         # (back on its button after the close)
        QTest.mouseClick(p.spacer, LeftButton)
        self.opened(p)
        self.assertIs(QApplication.focusWidget(), p.scroll)
        QTest.keyClick(p.scroll, Qt.Key.Key_Escape)
        settle()
        self.closed(p)
        ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Escape, NoMod)          # closed: not taken
        ev.ignore()
        QApplication.sendEvent(spin, ev)
        self.assertFalse(ev.isAccepted())
        # the focus elsewhere (the map canvas cancelling a tool): Esc is left alone and the popup stays
        self.opened(p)
        other = QLineEdit()
        self.addCleanup(other.deleteLater)
        other.show()
        other.activateWindow()
        other.setFocus()
        settle()
        self.assertIs(QApplication.focusWidget(), other)
        ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Escape, NoMod)
        ev.ignore()
        QApplication.sendEvent(other, ev)
        self.assertFalse(ev.isAccepted())
        QTest.keyClick(other, Qt.Key.Key_Escape)
        self.assertEqual(g.current_index(), 1)
        other.close()
        g.close_popup()

    def test_what_never_closes_it(self):
        p = self.panel()
        g = p.grid
        pop = self.opened(p)
        QTest.mouseClick(p.spins[1], LeftButton)           # a press on a field inside
        QTest.mouseClick(pop, LeftButton, NoMod, QPoint(20, 3))      # beside the notch: the popup's own
        QTest.mouseClick(pop.header, LeftButton)
        QApplication.sendEvent(pop, QEvent(QEvent.Type.Leave))      # the pointer leaving
        QApplication.sendEvent(p.window, QEvent(QEvent.Type.WindowDeactivate))
        QTest.qWait(250)
        settle()
        self.assertEqual(g.current_index(), 1)
        self.assertTrue(pop.isVisible())
        # a drop-down list inside (a window whose parent chain leads into the popup)
        combo = p.combos[1]
        combo.showPopup()
        settle()
        self.assertIsNotNone(QApplication.activePopupWidget())
        QTest.mousePress(combo.view().viewport(), LeftButton)
        self.assertEqual(g.current_index(), 1)
        ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Escape, NoMod)          # Esc is the list's
        ev.ignore()
        g._presses.eventFilter(combo.view(), ev)
        self.assertFalse(ev.isAccepted())
        combo.hidePopup()
        settle()
        self.assertEqual(g.current_index(), 1)
        g.close_popup()

    def test_another_button_in_one_click(self):
        p = self.panel()
        g = p.grid
        toggled = Count(g.popupToggled)
        self.opened(p, 1)
        QTest.mouseClick(g.buttons()[2], LeftButton)
        settle()
        self.assertEqual(g.current_index(), 2)
        self.assertEqual([b.isOpen() for b in g.buttons()], [False, False, True, False])
        self.assertEqual([x.isVisible() for x in g.popups()], [False, False, True, False])
        self.assertEqual(toggled.args, [(1, True), (1, False), (2, True)])
        g.close_popup()
        self.closed(p)

    def test_the_panels_scroll_bar_keeps_it_open(self):
        """(0.3.7 fix) A press or a drag on the panel's own scroll bar scrolls the open popup with the content, as the
        wheel does (it never closes on a scroll); a press on another scroll area's bar is a press elsewhere."""
        p = self.panel(height=260)
        g = p.grid
        bar = p.scroll.verticalScrollBar()
        pop = self.opened(p, 2)
        self.assertTrue(bar.isVisible() and bar.maximum() > 0)
        handle = bar_part(bar, QStyle.SubControl.SC_ScrollBarSlider).center()
        QTest.mousePress(bar, LeftButton, NoMod, handle)               # a drag on its handle
        self.assertEqual(g.current_index(), 2)
        QTest.mouseMove(bar, handle + QPoint(0, 20))
        QTest.mouseRelease(bar, LeftButton, NoMod, handle + QPoint(0, 20))
        settle()
        self.assertEqual(g.current_index(), 2)
        self.assertTrue(pop.isVisible() and g.filtering())
        v = bar.value()
        self.assertGreater(v, 0)                                       # (it scrolled)
        bar.setValue(0)
        settle()
        page = bar_part(bar, QStyle.SubControl.SC_ScrollBarAddPage).center()
        QTest.mouseClick(bar, LeftButton, NoMod, page)                 # a click on the groove: a page down
        settle()
        self.assertGreater(bar.value(), 0)
        self.assertEqual(g.current_index(), 2)
        self.assertEqual(pop.mapTo(p.scroll, QPoint(0, 0)).y(), pop.y() - bar.value())   # (with the content)
        other = QScrollArea()                                          # another scroll area's bar: closes it
        inner = QWidget()
        inner.setFixedHeight(600)
        other.setWidget(inner)
        other.resize(120, 100)
        other.show()
        self.addCleanup(other.deleteLater)
        self.addCleanup(other.close)
        settle()
        QTest.mouseClick(other.verticalScrollBar(), LeftButton)
        settle()
        self.closed(p)


# ================================================================ 5. following the grid and its own height
class Following(Case):
    def test_moves_resizes_grows_and_closes(self):
        p = self.panel()
        g = p.grid
        QTest.mouseClick(g.buttons()[0], LeftButton)
        settle()
        pop, plate = g.popups()[0], g.plates()[0]
        y0 = pop.y()
        p.spacer.setFixedHeight(60)                        # something above grows 40 px
        settle()
        self.assertEqual(pop.y(), y0 + 40)
        self.assertEqual(plate.y(), y0 + 40 + W.NOTCH_H)
        p.window.resize(300, 700)                          # a narrower panel
        settle()
        self.assertEqual(g.width(), 250)
        self.assertEqual((pop.x(), pop.width(), plate.width()), (p.at(g).x(), 250, 250))
        h0 = pop.height()
        self.assertTrue(p.hints[0].isHidden())
        W.set_verbose(True)                                # the hint inside shows: the popup grows
        self.addCleanup(W.set_verbose, False)
        settle()
        self.assertFalse(p.hints[0].isHidden())
        self.assertGreater(pop.height(), h0 + 10)
        self.assertEqual(plate.height(), pop.height() - W.NOTCH_H)
        W.set_verbose(False)
        settle()
        self.assertEqual(pop.height(), h0)
        p.section.hide()                                   # its section closing
        settle()
        self.assertEqual(g.current_index(), -1)
        self.assertFalse(pop.isVisible() or plate.isVisible() or g.filtering())

    def test_placed_at_its_final_height_when_it_opens(self):
        """(0.3.7 fix) A pair inside restacks as the popup shows (the panel narrowed while it was hidden) and asks
        its parents again one posted event per level: the popup is placed at its final height before open_popup
        returns, so what scrolls it into view (the dock, after one event loop pass) scrolls the whole of it."""
        p = self.panel()
        g = p.grid
        pop = g.popups()[2]
        box = QCheckBox("Draw them")
        seg = W._segmented([("Off", "off"), ("Elev.", "elev"), ("+ date", "elev_date")])
        two = pop.addWidget(W.pair(box, W.field_box("Print beside", seg)))
        need = 2 * max(W._needed_width(box), W._needed_width(seg)) + W._Pair.SPACING   # side by side from here
        QTest.mouseClick(g.buttons()[2], LeftButton)
        settle()
        offset = p.window.width() - two.width()            # (the pair: the panel less its margins, the popup's)
        g.close_popup()
        p.window.resize(need + 10 + offset, 700)
        settle()
        QTest.mouseClick(g.buttons()[2], LeftButton)
        settle()
        self.assertFalse(two.stacked())
        wide = pop.height()
        g.close_popup()
        p.window.resize(need - 10 + offset, 700)           # narrower while it is hidden: it stacks when it shows
        settle()
        QTest.mouseClick(g.buttons()[2], LeftButton)       # (no event loop pass yet)
        h = pop.height()
        self.assertTrue(two.stacked())
        self.assertGreater(h, wide + 10)                   # (one over the other: taller)
        settle()
        self.assertEqual(pop.height(), h)                  # nothing more to come
        self.assertEqual(g.plates()[2].height(), h - W.NOTCH_H)
        g.close_popup()

    def test_as_tall_as_its_rows_at_its_width(self):
        """(0.3.7 fix) The popup is its height for its width: the Plotted list (a Fixed box: its minimum is its
        sizeHint, its word-wrapped hint's height at another width) once left a band of empty room round the hint."""
        from xsections.ui.point_rows import PlottedList    # (no project: a list filled by hand)
        W.set_verbose(True)                                # (its hint shows)
        self.addCleanup(W.set_verbose, False)
        p = self.panel()
        g = p.grid
        pop = g.popups()[3]
        pl = PlottedList()
        pop.addWidget(pl)
        pl.set_entries([("Explorations", [("L", i, f"B-{i}", f"{i * 100} ft · 20 ft L · S", True)
                                          for i in range(1, 30)])])
        QTest.mouseClick(g.buttons()[3], LeftButton)
        settle()
        self.assertFalse(pl.hint.isHidden())
        self.assertGreater(pop.minimumSizeHint().height(), pop.heightForWidth(pop.width()))   # (the case)
        self.assertEqual(pop.height(), pop.heightForWidth(pop.width()))
        self.assertEqual(pl.hint.height(), pl.hint.heightForWidth(pl.hint.width()))   # no empty band round it
        self.assertEqual(pl.hint.y(), pl.tree.geometry().bottom() + 1 + pl.layout().spacing())
        self.assertLessEqual(pop.height() - pl.mapTo(pop, QPoint(0, pl.height())).y(), 12)  # (the body's margin)
        g.close_popup()


# ================================================================ 6. room under it
class Room(Case):
    def test_room_at_the_bottom_then_given_back(self):
        p = self.panel(height=200, below=0)
        g, ov = p.grid, p.overlay
        self.assertEqual(ov.minimumHeight(), 0)
        QTest.mouseClick(g.buttons()[2], LeftButton)
        settle()
        pop = g.popups()[2]
        bottom = pop.y() + pop.height()
        self.assertGreater(bottom, ov.layout().sizeHint().height())
        self.assertEqual(ov.minimumHeight(), bottom + W.POP_ROOM)
        self.assertGreaterEqual(ov.height(), bottom + W.POP_ROOM)
        bar = p.scroll.verticalScrollBar()                 # it scrolls with the content, still open
        self.assertGreater(bar.maximum(), 0)
        y = pop.mapTo(p.scroll, QPoint(0, 0)).y()
        bar.setValue(bar.maximum())
        settle()
        self.assertEqual(g.current_index(), 2)
        self.assertEqual(pop.mapTo(p.scroll, QPoint(0, 0)).y(), y - bar.maximum())
        g.close_popup()
        settle()
        self.assertEqual(ov.minimumHeight(), 0)

    def test_a_popup_that_fits_asks_nothing(self):
        p = self.panel()
        QTest.mouseClick(p.grid.buttons()[3], LeftButton)
        settle()
        self.assertEqual(p.overlay.minimumHeight(), 0)
        p.grid.close_popup()
        self.assertEqual(p.overlay.minimumHeight(), 0)


# ================================================================ 7. paint (light and dark)
class Paint(Case):
    def test_popup_box_notch_and_rule(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            host = QWidget()
            host.setPalette(pal)
            self.addCleanup(host.deleteLater)
            pop = W.OptionPopup("Depths", parent=host)
            pop.setGeometry(0, 0, 290, 160)
            pop.set_notch_x(60)
            pop.show()
            host.resize(300, 180)
            host.show()
            settle()
            self.assertEqual(pop.notch_x(), 60)
            img = pop.grab().toImage()
            self.assertLess(dist(px(img, 145, 80), t.row_open), 8, name)                # the box
            self.assertLess(dist(px(img, 289, 80), t.band_line), 12, name)              # its outline
            self.assertLess(dist(px(img, 60, 3), t.row_open), 8, name)                  # inside the notch
            self.assertEqual(px(img, 40, 3).alpha(), 0, name)                            # beside it: transparent
            self.assertLess(dist(px(img, 60, W.NOTCH_H), t.row_open), 8, name)          # no top border under it
            self.assertLess(dist(px(img, 100, W.NOTCH_H), t.band_line), 12, name)       # the top border elsewhere
            self.assertEqual(pop.header.height() + 1, 36)
            self.assertLess(dist(px(img, 145, W.NOTCH_H + 36), t.field_line), 8, name)  # the header's rule
            self.assertEqual(pop.box_rect(), QRect(0, W.NOTCH_H, 290, 160 - W.NOTCH_H))
            pop.set_notch_x(2)                                                          # clamped clear of corners
            self.assertEqual(pop.notch_x(), W.POP_RADIUS + W.NOTCH_HALF + 2)
            pop.set_notch_x(1000)
            self.assertEqual(pop.notch_x(), 290 - W.POP_RADIUS - W.NOTCH_HALF - 2)
            self.assertEqual((pop.title(), pop.title_label.text(), pop.title_label.objectName(), pop.objectName()),
                             ("Depths", "Depths", "xsPopTitle", "xsOptionPopup"))
            m = pop.body_layout.contentsMargins()
            self.assertEqual((m.left(), m.top(), m.right(), m.bottom(), pop.body_layout.spacing()), (10, 9, 10, 11, 8))
            host.close()

    def test_the_shadow_plate(self):
        for name, make in PALETTES:
            p = self.panel(pal=make())
            plate = p.grid.plates()[0]
            eff = plate.graphicsEffect()
            self.assertIsInstance(eff, QGraphicsDropShadowEffect)
            self.assertEqual((eff.blurRadius(), eff.offset()), (24.0, QPointF(0, 6)))
            want = (0, 0, 0, 102) if name == "dark" else (16, 32, 40, 51)
            self.assertEqual(eff.color().getRgb(), want, name)
            self.assertTrue(plate.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
            self.assertIsNone(p.grid.popups()[0].graphicsEffect())          # nothing over the popup's fields
        plate = W._ShadowPlate()
        self.addCleanup(plate.deleteLater)
        plate.setPalette(light_palette())
        self.assertEqual(plate.shadow().color().getRgb(), (16, 32, 40, 51))
        plate.setPalette(night_palette())                  # re-read on a palette change
        self.assertEqual(plate.shadow().color().getRgb(), (0, 0, 0, 102))

    def test_in_both_themes_in_the_panel(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            p = self.panel(pal=pal)
            QTest.mouseClick(p.grid.buttons()[0], LeftButton)
            settle()
            pop = p.grid.current()
            img = p.overlay.grab().toImage()
            spot = p.at(pop, QPoint(pop.width() - 6, pop.height() - 6))
            self.assertLess(dist(px(img, spot.x(), spot.y()), t.row_open), 8, name)
            b = p.grid.buttons()[0]
            spot = p.at(b, QPoint(b.width() // 2, 21))
            self.assertLess(dist(px(img, spot.x(), spot.y()), t.row_open), 8, name)       # the open button
            p.close()


# ================================================================ 8. the keyboard
class Keyboard(Case):
    def test_space_return_and_esc(self):
        p = self.panel()
        g = p.grid
        b0 = g.buttons()[0]
        b0.setFocus(Qt.FocusReason.TabFocusReason)
        settle()
        self.assertTrue(b0.hasFocus())
        QTest.keyClick(b0, Qt.Key.Key_Space)
        settle()
        self.assertEqual(g.current_index(), 0)
        fw = QApplication.focusWidget()
        self.assertTrue(W._within(fw, g.popups()[0].body), fw)          # a keyboard open: the focus in its body
        QTest.keyClick(fw, Qt.Key.Key_Escape)
        settle()
        self.assertEqual(g.current_index(), -1)
        self.assertTrue(b0.hasFocus())                                  # back on its button
        QTest.keyClick(b0, Qt.Key.Key_Return)
        settle()
        self.assertEqual(g.current_index(), 0)
        self.assertTrue(W._within(QApplication.focusWidget(), g.popups()[0]))
        g.close_popup()
        self.assertTrue(b0.hasFocus())
        QTest.mouseClick(g.buttons()[1], LeftButton)                    # a mouse click: not a keyboard open
        settle()
        self.assertEqual(g.current_index(), 1)
        self.assertFalse(g.buttons()[1].hasFocus())                     # (TabFocus: Qt's click focus passes it)
        self.assertFalse(W._within(QApplication.focusWidget(), g.popups()[1]))
        g.close_popup()


# ================================================================ 9. the Size list
class SizeList(Case):
    def combo(self, width=300):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        c = W.SheetSizeCombo(SIZES, CUSTOM, FOOT, describe)
        lay.addWidget(c)
        lay.addStretch(1)
        host.setStyleSheet(W.panel_stylesheet(W.theme_for(host.palette())))
        host.resize(width, 200)
        host.show()
        settle()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        return c

    def test_checks(self):
        c = self.combo()
        changed = Count(c.checksChanged)
        self.assertEqual(c.count(), 0)                     # no items of its own
        self.assertEqual(list(c.boxes()), [k for k, _n, _d in SIZES] + ["custom"])
        self.assertEqual((c.checked(), c.isCustom(), c.fullText()), ([], False, "none"))
        c.setChecks(["tabloid", "letter", "bogus"])        # silent; list order; unknown keys ignored
        self.assertEqual(len(changed), 0)
        self.assertEqual(c.checked(), ["letter", "tabloid"])
        self.assertEqual(c.fullText(), "letter, tabloid")
        self.assertEqual(c.toolTip(), "tip")
        c.setChecks(["ansid"], emit=True)
        self.assertEqual((len(changed), c.checked()), (1, ["ansid"]))
        c.setChecks(["letter"], custom=True)               # custom wins
        self.assertEqual((c.checked(), c.isCustom(), c.fullText()), ([], True, "custom"))
        c.setChecks(["letter", "tabloid"])
        c.showPopup()
        settle()
        boxes = c.boxes()
        QTest.mouseClick(boxes["ansid"], LeftButton)       # his click: toggles it, emits once
        self.assertEqual((c.checked(), len(changed)), (["letter", "tabloid", "ansid"], 2))
        QTest.mouseClick(boxes["custom"], LeftButton)      # custom clears every size
        self.assertEqual((c.checked(), c.isCustom(), len(changed)), ([], True, 3))
        self.assertFalse(any(boxes[k].isChecked() for k, _n, _d in SIZES))
        QTest.mouseClick(boxes["archc"], LeftButton)       # a size clears custom
        self.assertEqual((c.checked(), c.isCustom(), len(changed)), (["archc"], False, 4))
        QTest.mouseClick(boxes["archc"], LeftButton)       # unchecking the last leaves none
        self.assertEqual((c.checked(), c.isCustom(), len(changed), c.fullText()), ([], False, 5, "none"))
        row = c.list_frame().rows[1]
        QTest.mouseClick(row.detail, LeftButton)           # a click anywhere on the row toggles its box
        self.assertEqual((c.checked(), len(changed)), (["tabloid"], 6))
        QTest.mouseClick(row, LeftButton, NoMod, QPoint(row.width() - 60, row.height() // 2))
        self.assertEqual((c.checked(), len(changed)), ([], 7))
        self.assertTrue(c.list_frame().isVisible())        # it stays open while he checks
        c.hidePopup()
        self.assertFalse(c.list_frame().isVisible())

    def test_the_open_list(self):
        c = self.combo()
        c.setChecks(["letter", "tabloid"])
        lf = c.list_frame()
        self.assertFalse(lf.isVisible())
        self.assertTrue(lf.isWindow())
        self.assertEqual(lf.box.objectName(), "xsSizeList")       # (the styled frame inside the window)
        c.showPopup()
        settle()
        self.assertTrue(lf.isVisible())
        self.assertIs(QApplication.activePopupWidget(), lf)
        t = W.theme_for(c.palette())                       # the stylesheet's field and its border
        img = lf.grab().toImage()
        y = lf.rows[2].mapTo(lf, QPoint(0, W.SIZE_ROW_H // 2)).y()
        self.assertLess(dist(px(img, lf.width() // 2, y), t.field), 8)
        self.assertLess(dist(px(img, 0, y), t.field_line), 8)
        self.assertLess(dist(px(img, lf.width() - 1, y), t.field_line), 8)
        self.assertEqual(lf.width(), max(W.SIZE_LIST_W, c.width()))
        self.assertEqual(lf.pos(), c.mapToGlobal(QPoint(0, c.height())) + QPoint(0, 2))
        self.assertEqual([(r.key, r.box.text(), r.detail.text()) for r in lf.rows], SIZES)
        self.assertEqual([r.height() for r in lf.rows], [W.SIZE_ROW_H] * len(SIZES))
        rows_y = [r.y() for r in lf.rows]
        self.assertEqual(rows_y, sorted(rows_y))
        self.assertTrue(lf.rule_box.findChildren(W._Rule))
        self.assertGreater(lf.rule_box.y(), lf.rows[-1].y())
        cr = lf.custom_row
        self.assertEqual((cr.key, cr.box.text(), cr.detail.text()), CUSTOM)
        self.assertGreater(cr.y(), lf.rule_box.y())
        self.assertEqual(lf.foot.text(), FOOT)
        self.assertEqual(lf.foot.objectName(), "xsSizeFoot")
        self.assertGreater(lf.foot.y(), cr.y())
        self.assertLessEqual(lf.foot.geometry().bottom(), lf.height())
        self.assertIs(QApplication.focusWidget(), c.boxes()["letter"])        # the focus on the first box
        QTest.keyClick(lf, Qt.Key.Key_Escape)              # Esc closes
        settle()
        self.assertFalse(lf.isVisible())
        c.showPopup()
        settle()
        QTest.mousePress(lf, LeftButton, NoMod, QPoint(-5, -5))    # a press outside it closes
        settle()
        self.assertFalse(lf.isVisible())
        self.assertFalse(lf.testAttribute(Qt.WidgetAttribute.WA_NoMouseReplay))
        c.showPopup()
        settle()
        gp = c.mapToGlobal(c.rect().center())              # a press on the combo: closed, not replayed (reopened)
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(lf.mapFromGlobal(gp)), QPointF(gp), LeftButton,
                         LeftButton, NoMod)
        QApplication.sendEvent(lf, ev)
        settle()
        self.assertFalse(lf.isVisible())
        self.assertTrue(lf.testAttribute(Qt.WidgetAttribute.WA_NoMouseReplay))
        c.showPopup()                                      # (reset when it opens again)
        settle()
        self.assertFalse(lf.testAttribute(Qt.WidgetAttribute.WA_NoMouseReplay))
        QTest.keyClick(lf, Qt.Key.Key_Return)              # Return closes it too
        self.assertFalse(lf.isVisible())
        QTest.keyClick(c, Qt.Key.Key_Space)                # Space on the box opens it (QComboBox's own path)
        settle()
        self.assertTrue(lf.isVisible())
        c.hidePopup()

    def test_closed_box(self):
        c = self.combo()
        c.setChecks(["letter", "tabloid"])
        self.assertEqual(c.displayText(), "letter, tabloid")
        c.setFixedWidth(60)                                # (80 with Segoe UI; the tests' font is narrower)
        settle()
        self.assertTrue(c.displayText().endswith("…"), c.displayText())
        self.assertEqual(c.fullText(), "letter, tabloid")
        self.assertEqual(c.toolTip(), "tip")
        img = c.grab()                                     # paints without raising
        self.assertFalse(img.isNull())
        c.showPopup()                                      # the list: at least SIZE_LIST_W wide
        settle()
        self.assertEqual(c.list_frame().width(), W.SIZE_LIST_W)
        c.hidePopup()

    def test_a_short_screen(self):
        """(0.3.7 fix) With room for the list on neither side of the box (a screen about 450 px tall), it goes on the
        side with more room, moved to stay on the screen; on a screen shorter than the list, its top on it."""
        c = self.combo()
        c.window().move(0, 300)                            # (every place below on the real screen too)
        settle()
        lf = c.list_frame()
        c.showPopup()
        settle()
        h = lf.height()
        self.assertEqual(lf.pos(), c.mapToGlobal(QPoint(0, c.height() + 2)))     # (room below: under the box)
        c.hidePopup()
        top = c.mapToGlobal(QPoint(0, 0)).y()
        x = c.mapToGlobal(QPoint(0, 0)).x()
        for above, below, want in ((h // 2, h - h // 2, "below"), (h // 2 + 10, h - h // 2 - 10, "above")):
            screen = QRect(0, top - above, 2000, above + c.height() + below)   # (neither side has room for it)
            lf._available = lambda r=screen: r
            c.showPopup()
            settle()
            self.assertEqual(lf.height(), h)
            self.assertGreaterEqual(lf.y(), screen.top(), want)
            self.assertLessEqual(lf.y() + h, screen.bottom() + 1, want)             # on the screen
            self.assertEqual(lf.y(), screen.top() if want == "above" else screen.bottom() + 1 - h, want)
            self.assertEqual(lf.x(), x)
            c.hidePopup()
        screen = QRect(0, top - 40, 2000, h - 20)          # shorter than the list: its top on the screen
        lf._available = lambda: screen
        c.showPopup()
        settle()
        self.assertEqual(lf.y(), screen.top())
        c.hidePopup()
        del lf._available
        settle()


# ================================================================ 10. ElidedComboBox
class Elided(Case):
    def test_elides_tips_and_list_width(self):
        items = [("PNG, 600 dpi", "png600"), ("PDF (vector)", "pdf"), ("A much longer format name to show", "x")]
        c = W._combo(items, elide=True)
        self.assertIsInstance(c, W.ElidedComboBox)
        self.assertIs(type(W._combo(items)), QComboBox)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.addWidget(c)
        host.resize(320, 80)
        host.show()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        settle()
        self.assertEqual(c.fullText(), c.currentText())
        self.assertEqual(c.toolTip(), "PNG, 600 dpi")
        c.setFixedWidth(60)
        settle()
        self.assertTrue(c.displayText().endswith("…"), c.displayText())
        c.setFixedWidth(300)
        settle()
        self.assertEqual(c.displayText(), "PNG, 600 dpi")
        c.setItemData(1, "Vector: sharp at any zoom", Qt.ItemDataRole.ToolTipRole)
        c.setCurrentIndex(1)
        self.assertEqual(c.toolTip(), "Vector: sharp at any zoom")      # its ToolTipRole
        c.setCurrentIndex(2)
        self.assertEqual(c.toolTip(), "A much longer format name to show")
        c.setFixedWidth(60)
        settle()
        c.showPopup()
        settle()
        v = c.view()
        self.assertGreaterEqual(v.minimumWidth(), min(360, v.sizeHintForColumn(0)))
        self.assertGreater(v.minimumWidth(), 60)
        c.hidePopup()

    def test_a_lead_tip(self):
        """(0.3.7 fix: Tops from) A tooltip of its own: alone while the box shows its text whole, with the full text
        under it while the shown box cuts it."""
        items = [("PNG, 600 dpi", "png600"), ("PDF (vector)", "pdf"), ("A much longer format name to show", "x")]
        c = W._combo(items, elide=True)
        c.setLeadTip("Where it comes from")
        self.assertEqual(c.toolTip(), "Where it comes from")             # (not shown: nothing cut)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.addWidget(c)
        host.resize(320, 80)
        host.show()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        settle()
        self.assertEqual(c.displayText(), "PNG, 600 dpi")
        self.assertEqual(c.toolTip(), "Where it comes from")
        c.setFixedWidth(60)                                              # cut: the full text under the lead
        settle()
        self.assertTrue(c.displayText().endswith("…"), c.displayText())
        self.assertEqual(c.toolTip(), "Where it comes from\nPNG, 600 dpi")
        c.setCurrentIndex(2)
        self.assertEqual(c.toolTip(), "Where it comes from\nA much longer format name to show")
        c.setFixedWidth(300)
        settle()
        c.setCurrentIndex(1)
        self.assertEqual(c.toolTip(), "Where it comes from")
        c.setItemData(1, "Vector: sharp at any zoom", Qt.ItemDataRole.ToolTipRole)   # (the lead wins)
        c.syncTip()
        self.assertEqual(c.toolTip(), "Where it comes from")


# ================================================================ 11. the stylesheet
class Stylesheet(unittest.TestCase):
    def test_rules(self):
        for _name, make in PALETTES:
            t = W.theme_for(make())
            sheet = W.panel_stylesheet(t)
            self.assertIn(f"QLabel#xsPopTitle {{ color: {W.css(t.ink)}; }}", sheet)
            self.assertIn(f"QLabel#xsPopCount {{ color: {W.css(t.muted)}; }}", sheet)
            self.assertIn(f"QFrame#xsSizeList {{ background: {W.css(t.field)}; border: 1px solid "
                          f"{W.css(t.field_line)}; }}", sheet)
            self.assertIn("QLabel#xsSizeFoot {", sheet)
            self.assertIn("background: palette(window)", sheet)
            self.assertIn(f"border-top: 1px solid {W.css(t.rule)}", sheet)
            self.assertNotIn("xsOptionPopup", sheet)       # painted, no rule
            self.assertNotIn("xsOptionButton", sheet)


# ================================================================ 12. budget
@timing_test
class Budget(Case):
    def test_building(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        t0 = time.perf_counter()
        for _ in range(20):
            box = QWidget(host)
            g = W.OptionGrid(host, box)
            for title in TITLES:
                _b, p = g.add_option(title, "tip")
                p.addWidget(W.field_box("Within", QDoubleSpinBox()))
                p.addWidget(W.Hint("A hint"))
        took = time.perf_counter() - t0
        self.assertLess(took, budget(0.5), f"{took:.3f} s for 20 grids of four options")
        host.resize(300, 200)
        host.show()
        settle()
        t0 = time.perf_counter()
        for _ in range(20):
            c = W.SheetSizeCombo(SIZES, CUSTOM, FOOT, describe, host)
            c.show()
            c.showPopup()
            c.hidePopup()
        took = time.perf_counter() - t0
        self.assertLess(took, budget(0.3), f"{took:.3f} s for 20 Size combos, each list opened and closed")
        host.close()


if __name__ == "__main__":
    unittest.main()
