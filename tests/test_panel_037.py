"""The panel of 0.3.7 (DESIGN.md decision 28; stage Q3 of the build): Explorations' Options (four buttons with live
summaries whose popups hold All layers, Depths, Water & screens and the Plotted checklist; how a popup opens, follows
its button and closes), the Depths popup without the Checks pill, Scale & sheet (Distances under Scale; Room below
lowest | Fill sheet under Auto with their tooltips; the Sheet row Size | Format, the Size list's check boxes and how
they map onto Settings.sheet and allowed_sheets), Sheet style › Grid › Custom with None (the legend line, the grayed
colour and width, the table at 340 and 260 px), the narrow panels, both themes.

The fixture project with explorations by others, supply wells and seeps (tests.test_panel_036.PanelCase); the core and
render pipeline is stubbed with tests.test_ui's hand-made model where the test is about the panel."""
import dataclasses
import json
import os
import unittest

from tests.fixtures import start_app

APP = start_app()

from matplotlib.figure import Figure  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QPoint, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPalette  # noqa: E402
from qgis.PyQt.QtTest import QTest  # noqa: E402
from qgis.PyQt.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QGraphicsOpacityEffect, QLabel,  # noqa: E402
                                 QStyle, QStyleOptionSlider, QToolTip, QWidget)

from tests.test_panel_036 import PanelCase, explo_row, field_label_of, flagged_model, settle, subsection  # noqa: E402
from tests.test_panel_036 import subsections  # noqa: E402
from tests.test_panel_widgets import dist, night_palette, px  # noqa: E402
from xsections.core.model import Settings  # noqa: E402
from xsections.render import figure as F  # noqa: E402
from xsections.render.scales import plan as make_plan  # noqa: E402
from xsections.ui import dock as D  # noqa: E402
from xsections.ui import point_rows as R  # noqa: E402
from xsections.ui import problems as P  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui import preview as PV  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402
from xsections.ui.preview import PreviewWidget  # noqa: E402

TITLES = ["All layers", "Depths", "Water & screens", "Plotted"]
TIPS = ["Within, labels and label text, for every layer", "Depth lines, TD labels and where tops come from",
        "Screens, water levels and what is printed beside them",
        "Every exploration on this section: untick one to leave it off"]
FILL_TIPS = ["Off: leave the paper left over on the sheet blank.",
             "Below (the default): fill the paper left over with whole grid squares under the section, down to the "
             "margin. Room to draw the geology deeper.",
             "Both: fill it with grid squares above and below the section, the larger half below."]
ROOM_TIP = "Grid kept under the lowest point (the lowest bottom or TD label), in paper inches"
FILL_TIP = "What to do with the paper left over on the sheet"
FILL_CUSTOM_TIP = "Not used with a custom page size: the page is cut to the drawing"
TOPS_TIP = "Where each exploration's top comes from (all layers)"
TOPS_FULL = "Table, else LIDAR at the exploration"
LeftButton, NoMod = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier


def in_content(d, w, pt=None):
    """`w`'s point `pt` (its top-left) in the dock's scroll content."""
    return w.mapTo(d.content, pt if pt is not None else QPoint(0, 0))


def tick(d, label, on=False):
    """A user's tick in the Plotted list: the exploration named `label`."""
    key = next(e for e in d.plotted.items() if e[2] == label)
    d.plotted.item_for(key[0], key[1]).setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def custom_grid(d):
    """Sheet style › Grid › Look: Custom, clicked."""
    d.grid_color.buttons()[d.grid_color.findData("custom")].click()


def grid_lines(fig):
    """The preview's minor (zorder 0.5) and major (0.6) grid lines (as tests.test_grid_none)."""
    return [ln for ln in fig.axes[0].lines if ln.get_zorder() in (0.5, 0.6)]


def handle_of(bar):
    """The centre of a scroll bar's handle, in bar coordinates."""
    opt = QStyleOptionSlider()
    bar.initStyleOption(opt)
    return bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, opt, QStyle.SubControl.SC_ScrollBarSlider,
                                      bar).center()


def luma(c):
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


class Case(PanelCase):
    def shown(self, width=340, height=900, **over):
        """The dock restored on the fixture rows, shown, Explorations open (its rows closed)."""
        d = self.restore(self.settings(**over))
        self.show(d, width=width, height=height)
        d.grp_explo.setCollapsed(False)
        settle()
        return d


# ------------------------------------------------------------------ 7.3-1: places
class Layout(Case):
    def test_places_titles_and_gone_names(self):
        d = self.restore(self.settings())
        self.assertEqual([s.title() for s in subsections(d.grp_explo)], ["Layers", "Options"])
        self.assertIs(subsection(d.grp_explo, "Options"), d.options_sub)
        lay = d.options_sub.body_layout
        self.assertEqual([lay.indexOf(w) for w in (d.options_sub.heading, d.opt_grid, d.options_hint)], [0, 1, 2])
        self.assertEqual(d.options_hint.text(), "Each button opens its options. A second click, ✕, Esc or a click "
                                                "anywhere else closes them.")
        body = d.grp_explo.body_layout
        self.assertIs(body.itemAt(body.count() - 1).widget(), d.explo_readout)
        # the buttons, their tooltips (the explanation over the summary) and their popups
        buttons, popups = d.opt_grid.buttons(), d.opt_grid.popups()
        self.assertEqual(buttons, [d.opt_all, d.opt_depths, d.opt_water, d.opt_plotted])
        self.assertEqual(popups, [d.pop_all, d.pop_depths, d.pop_water, d.pop_plotted])
        self.assertEqual(([b.title() for b in buttons], [p.title() for p in popups]), (TITLES, TITLES))
        self.assertEqual((D.OPT_TITLES, D.OPT_TIPS), (TITLES, TIPS))
        for b, tip in zip(buttons, TIPS):
            self.assertTrue(b.summary(), b.title())
            self.assertEqual(b.toolTip(), f"{tip}\n{b.summary()}")
        self.assertEqual((d.grp_depth, d.grp_screens), (d.pop_depths, d.pop_water))
        content = d.content.layout()
        for p in popups:
            self.assertIs(p.parentWidget(), d.content)
            self.assertEqual(content.indexOf(p), -1)                  # in no layout
            self.assertTrue(p.isHidden())
            self.assertEqual(p.close_button.toolTip(), "Close (Esc)")
        # every moved control in its new place (spec 4.5)
        where = {
            d.pop_all: [d.tolerance, d.label_dir, d.label_text, d.within_hint],
            d.pop_depths: [d.depth_line, d.td_label, d.top_mode, d.zero_missing, d.top_max_diff, d.top_max_diff_row,
                           d.depth_readout],
            d.pop_water: [d.screens, d.wl_label, d.screens_readout],
            d.pop_plotted: [d.plotted, d.plotted.tree, d.plotted.empty_label, d.plotted.hint],
            d.pop_plotted.header: [d.plotted.count_label, d.plotted.btn_show_all],
            subsection(d.grp_export, "Scale"): [d.distance_labels],
            d.z_auto_row: [d.below_in, d.fill_grid],
            subsection(d.grp_export, "Elevations"): [d.z_auto_row, d.z_auto_hint, d.z_range_row],
            d.sheet_row: [d.sheet, d.fmt],
            subsection(d.grp_export, "Sheet"): [d.sheet_row, d.orientation, d.title_text, d.export_readout],
            d.grid_custom_box: [d.grid_table],
            d.grid_table: [getattr(d, f"grid_{p}_{k}") for p in ("major", "minor") for k in ("color", "width",
                                                                                              "style")],
        }
        for box, widgets in where.items():
            for w in widgets:
                self.assertTrue(box.isAncestorOf(w), (box, w))
        self.assertFalse(d.grp_style.isAncestorOf(d.fill_grid) or d.grp_style.isAncestorOf(d.below_in))
        self.assertEqual(d._disclosures, [d.units_more])
        for name in ("checks_more", "distances_more", "allowed_sheets"):
            self.assertFalse(hasattr(d, name), name)
        self.assertFalse(hasattr(D, "SHEET_CHOICES"))
        self.assertFalse(hasattr(d.plotted, "heading"))
        # the Plotted popup's title tells the whole count: before a build, after one and after a tick
        title = d.pop_plotted.title_label
        self.assertEqual(title.toolTip(), d.plotted.text())
        self.assertEqual(title.toolTip(), "Plotted explorations")
        d.refresh()
        n = len(d.model.hits)
        self.assertEqual(title.toolTip(), f"Plotted explorations ({n} of {n})")
        tick(d, "B-1")
        self.assertEqual(title.toolTip(), f"Plotted explorations ({n - 1} of {n}, 1 left off by you)")
        self.assertEqual(title.toolTip(), d.plotted.text())


# ------------------------------------------------------------------ 7.3-2: the popups from the dock
class Popups(Case):
    def test_each_button_opens_its_popup_under_it(self):
        d = self.shown()
        g = d.opt_grid
        self.assertEqual(g.columns(), 2)
        gx = in_content(d, g).x()
        for b, p in zip(g.buttons(), g.popups()):
            QTest.mouseClick(b, Qt.MouseButton.LeftButton)
            settle()
            self.assertIs(g.current(), p, b.title())
            self.assertTrue(b.isOpen() and p.isVisible())
            self.assertEqual([x.isVisible() for x in g.popups()].count(True), 1)      # one at a time
            self.assertEqual([x.isOpen() for x in g.buttons()].count(True), 1)
            geo = p.geometry()
            self.assertEqual((geo.x(), geo.width()), (gx, g.width()), b.title())
            self.assertEqual(geo.y(), in_content(d, b, QPoint(0, b.height())).y(), b.title())
            self.assertAlmostEqual(p.notch_x(), in_content(d, b, QPoint(b.width() // 2, 0)).x() - gx, delta=1)
            self.assertTrue(g.filtering())
        QTest.mouseClick(d.opt_plotted, Qt.MouseButton.LeftButton)          # a second click on its button
        settle()
        self.assertIsNone(g.current())
        self.assertFalse(d.opt_plotted.isOpen() or g.filtering())
        # the Plotted header: its title, the count and Show all, the ✕
        hl = d.pop_plotted.header.layout()
        self.assertEqual(hl.indexOf(d.pop_plotted.title_label), 0)
        self.assertEqual(hl.indexOf(d.plotted.count_label), 1)
        self.assertTrue(d.pop_plotted.header.isAncestorOf(d.plotted.btn_show_all))
        g.open_popup(d.opt_depths)
        settle()
        QTest.mouseClick(d.pop_depths.close_button, Qt.MouseButton.LeftButton)  # the ✕
        self.assertIsNone(g.current())
        g.open_popup(d.opt_depths)
        settle()
        d.activateWindow()
        d.top_mode.setFocus()
        QTest.keyClick(d.top_mode, Qt.Key.Key_Escape)                         # Esc (the focus in the popup)
        self.assertIsNone(g.current())

    def test_a_press_elsewhere_closes_it_and_still_does_its_job(self):
        d = self.shown()
        g = d.opt_grid
        g.open_popup(d.opt_depths)
        settle()
        QTest.mouseClick(d.zero_missing, Qt.MouseButton.LeftButton)          # inside: works, stays open
        self.assertIs(g.current(), d.pop_depths)
        self.assertTrue(d.grp_line.isCollapsed())
        QTest.mouseClick(d.grp_line.header, Qt.MouseButton.LeftButton)       # the Line header: closes it, opens Line
        settle()
        self.assertIsNone(g.current())
        self.assertFalse(d.grp_line.isCollapsed() or g.filtering())
        g.open_popup(d.opt_all)
        settle()
        QApplication.sendEvent(d.pop_all, QEvent(QEvent.Type.Leave))         # never on the pointer leaving
        QTest.qWait(250)
        self.assertIs(g.current(), d.pop_all)

    def test_what_else_closes_it(self):
        d = self.shown()
        g = d.opt_grid
        for close in (d.collapse_all, d.hide, d.restore_from_project, d.project_cleared, d.cleanup):
            if not d.isVisible():
                self.show(d)
            d.grp_explo.setCollapsed(False)
            settle()
            self.assertTrue(g.open_popup(d.opt_water), close.__name__)
            self.assertTrue(g.filtering())
            close()
            settle()
            self.assertIsNone(g.current(), close.__name__)
            self.assertTrue(d.pop_water.isHidden(), close.__name__)
            self.assertFalse(g.filtering() or d.opt_water.isOpen(), close.__name__)
        # its section closing closes it too
        self.show(d)
        d.grp_explo.setCollapsed(False)
        settle()
        g.open_popup(d.opt_water)
        d.grp_explo.setCollapsed(True)
        self.assertIsNone(g.current())
        self.assertFalse(g.filtering())

    def test_it_follows_the_grid_and_stays_open_while_scrolling(self):
        d = self.shown(height=520, other_points=[])
        self.stub(model=flagged_model(["no bottom elevation or depth"]))
        d.refresh()
        settle()
        g = d.opt_grid
        g.open_popup(d.opt_water)
        settle()
        y0 = d.pop_water.y()
        explo_row(d, 0).set_editor_open(True)                               # a row above the grid opens
        settle()
        self.assertIs(g.current(), d.pop_water)
        self.assertGreater(d.pop_water.y(), y0)
        self.assertEqual(d.pop_water.y(), in_content(d, d.opt_water, QPoint(0, d.opt_water.height())).y())
        self.assertEqual(d.opt_grid.plates()[2].geometry().top(), d.pop_water.y() + W.NOTCH_H)
        # scrolling the panel keeps it open; the check card closes as before
        row = explo_row(d, 1)
        d.scroll.ensureWidgetVisible(row.badge, 0, 0)
        settle()
        d.card_host.open(row.badge)
        self.assertTrue(d.card_host.is_open())
        bar = d.scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum() if bar.value() < bar.maximum() else 0)
        settle()
        self.assertFalse(d.card_host.is_open())
        self.assertIs(g.current(), d.pop_water)
        self.assertTrue(d.pop_water.isVisible())

    def test_one_opened_low_scrolls_into_view(self):
        d = self.shown(height=420)
        bar = d.scroll.verticalScrollBar()
        bar.setValue(0)
        settle()
        g = d.opt_grid
        g.open_popup(d.opt_plotted)
        settle(30)
        view = d.scroll.viewport()
        bottom = d.pop_plotted.mapTo(view, QPoint(0, d.pop_plotted.height())).y()
        top = d.pop_plotted.mapTo(view, QPoint(0, 0)).y()
        self.assertTrue(bottom <= view.height() or top <= 8, (top, bottom, view.height()))

    def test_a_tall_popup_in_a_short_dock(self):
        """(0.3.7 fix) A popup taller than the view (Plotted in a short dock, stacked with Layers) opens with its top
        in view (its header: the title, the count, Show all, the ✕), not centred with both ends cut off; the panel's
        scroll bar, pressed or dragged, scrolls the rest into view and keeps it open, as the wheel does."""
        d = self.shown(height=300)
        d.refresh()
        settle()
        g, pop = d.opt_grid, d.pop_plotted
        view, bar = d.scroll.viewport(), d.scroll.verticalScrollBar()
        QTest.mouseClick(d.opt_plotted, LeftButton)
        settle(30)
        self.assertIs(g.current(), pop)
        self.assertGreater(pop.height(), view.height())                          # (the case)
        self.assertEqual(pop.mapTo(view, QPoint(0, 0)).y(), D.POPUP_VIEW_MARGIN)  # its top (the notch) in view
        self.assertGreaterEqual(pop.header.mapTo(view, QPoint(0, 0)).y(), 0)
        v = bar.value()
        handle = handle_of(bar)
        QTest.mousePress(bar, LeftButton, NoMod, handle)                         # a drag on the panel's bar
        self.assertIs(g.current(), pop)
        QTest.mouseMove(bar, handle + QPoint(0, 30))
        QTest.mouseRelease(bar, LeftButton, NoMod, handle + QPoint(0, 30))
        settle()
        self.assertIs(g.current(), pop)
        self.assertTrue(pop.isVisible() and g.filtering())
        self.assertGreater(bar.value(), v)
        self.assertEqual(pop.mapTo(view, QPoint(0, 0)).y(), pop.y() - bar.value())   # (with the content)
        QTest.mouseClick(d.grp_line.header, LeftButton)                          # a press elsewhere still closes it
        settle()
        self.assertIsNone(g.current())
        self.assertFalse(g.filtering())


# ------------------------------------------------------------------ 7.3-3: the summaries
class Summaries(Case):
    def test_pure_functions(self):
        self.assertEqual(D.all_layers_summary(150.0, True, False), "150 ft · vertical · name only")
        self.assertEqual(D.all_layers_summary(12.34, False, True), "12.3 ft · horizontal · name + offset")
        self.assertEqual(D.depths_summary(True, True, "field_then_dem"), "line · TD · table, else LIDAR")
        self.assertEqual(D.depths_summary(True, False, "dem"), "line · no TD · LIDAR")
        self.assertEqual(D.depths_summary(True, True, "field"), "line · TD · table only")
        self.assertEqual(D.depths_summary(False, True, "dem"), "no line")
        self.assertEqual(D.water_summary(True, "elev"), "drawn · elevation beside")
        self.assertEqual(D.water_summary(True, "off"), "drawn · nothing beside")
        self.assertEqual(D.water_summary(True, "elev_date"), "drawn · elev. + date beside")
        self.assertEqual(D.water_summary(False, "elev"), "off")
        self.assertEqual(D.plotted_summary(None), "–")
        self.assertEqual(D.plotted_summary((0, 0, 0)), "none")
        self.assertEqual(D.plotted_summary((15, 16, 1)), "15 of 16 · 1 off")
        self.assertEqual(D.plotted_summary((16, 16, 0)), "16 of 16 · all shown")

    def test_from_the_dock_and_live(self):
        d = self.restore(self.settings())
        summaries = lambda: [b.summary() for b in d.opt_grid.buttons()]   # noqa: E731
        self.assertEqual(summaries(), ["150 ft · vertical · name only", "line · TD · table, else LIDAR",
                                       "drawn · nothing beside", "–"])
        d.tolerance.setValue(77.0)
        self.assertEqual(d.opt_all.summary(), "77 ft · vertical · name only")
        d.label_dir.setCurrentIndex(d.label_dir.findData(False))
        self.assertEqual(d.opt_all.summary(), "77 ft · horizontal · name only")
        d.label_text.setCurrentIndex(d.label_text.findData(True))
        self.assertEqual(d.opt_all.summary(), "77 ft · horizontal · name + offset")
        self.assertEqual(d.opt_all.toolTip(), f"{TIPS[0]}\n77 ft · horizontal · name + offset")
        d.depth_line.setChecked(False)
        self.assertEqual(d.opt_depths.summary(), "no line")
        d.depth_line.setChecked(True)
        d.top_mode.setCurrentIndex(d.top_mode.findData("dem"))
        self.assertEqual(d.opt_depths.summary(), "line · TD · LIDAR")
        d.td_label.setChecked(False)
        self.assertEqual(d.opt_depths.summary(), "line · no TD · LIDAR")
        d.screens.setChecked(False)
        self.assertEqual(d.opt_water.summary(), "off")
        d.screens.setChecked(True)
        d.wl_label.setCurrentIndex(d.wl_label.findData("elev_date"))
        self.assertEqual(d.opt_water.summary(), "drawn · elev. + date beside")
        # Plotted: "–" before a build, then the counts, at once after a tick and after the rebuild
        d.refresh()
        n = len(d.model.hits)
        self.assertEqual(d.opt_plotted.summary(), f"{n} of {n} · all shown")
        tick(d, "B-1")
        self.assertEqual(d.opt_plotted.summary(), f"{n - 1} of {n} · 1 off")
        d.refresh()
        self.assertEqual(d.opt_plotted.summary(), f"{n - 1} of {n} · 1 off")
        self.stub(exc=D.SectionError("Choose a DEM (ground surface raster)."))
        d.refresh()                                                     # a failed build: no counts
        self.assertEqual(d.opt_plotted.summary(), "–")
        # a restore shows the restored values
        d = self.restore(self.settings(tolerance_ft=40.0, label_vertical=False, depth_line=False, screens=False))
        self.assertEqual(summaries()[:3], ["40 ft · horizontal · name only", "no line", "off"])
        d.project_cleared()
        self.assertEqual(summaries(), ["150 ft · vertical · name only", "line · TD · table, else LIDAR",
                                       "drawn · nothing beside", "–"])


# ------------------------------------------------------------------ 7.3-4: the Plotted checklist
class PlottedChecklist(Case):
    def test_the_verbose_popup_is_tight(self):
        """(0.3.7 fix) With Verbose, the Plotted popup is as tall as its rows at its width: its hint right under the
        list, no band of empty room round it."""
        self.verbose()
        d = self.shown()
        d.refresh()
        settle()
        pop, pl = d.pop_plotted, d.plotted
        QTest.mouseClick(d.opt_plotted, LeftButton)
        settle(30)
        self.assertIs(d.opt_grid.current(), pop)
        self.assertFalse(pl.hint.isHidden())
        self.assertEqual(pop.height(), pop.heightForWidth(pop.width()))
        self.assertEqual(pl.height(), pl.heightForWidth(pl.width()))
        self.assertEqual(pl.hint.height(), pl.hint.heightForWidth(pl.hint.width()))
        self.assertEqual(pl.hint.y(), pl.tree.geometry().bottom() + 1 + pl.layout().spacing())
        self.assertLessEqual(pop.height() - pl.mapTo(pop, QPoint(0, pl.height())).y(), 10)  # (its 9 px margin, edge)

    def test_in_the_dock(self):
        d = self.restore(self.settings())
        self.assertTrue(d.plotted.count_label.isHidden())               # no model: no count
        d.refresh()
        n, m, _k = d.plotted.counts()
        self.assertFalse(W.verbose())
        self.assertEqual(d.plotted.count_label.text(), f"{n} of {m}")
        self.assertFalse(d.plotted.count_label.isHidden())              # shown with Verbose off
        self.assertEqual(d.plotted.count_label.objectName(), "xsPopCount")
        tree = d.plotted.tree
        items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        titles = [it for it in items if not it.data(0, R.PlottedList.KEY)]
        names = [it for it in items if it.data(0, R.PlottedList.KEY)]
        self.assertTrue(titles and names)
        for it in titles:
            self.assertTrue(it.font(0).bold())
            self.assertEqual(it.text(0), it.text(0).upper())
        for it in names:
            self.assertEqual(it.font(0).weight(), QFont.Weight.DemiBold)
        # the detail: "station · offset side · direction" (no direction on the line)
        h = next(h for h in d.model.hits if h.direction)
        it = d.plotted.item_for(h.layer_id, h.fid)
        self.assertTrue(it.text(1).endswith(f" ft {h.side} · {h.direction}"), it.text(1))
        on_line = SimpleHit(station=120.0, offset=0.0, side="L", direction="")
        self.assertEqual(d._plotted_detail(on_line, d.settings()), "120 ft · 0 ft L")
        # a tick keeps the name semibold (and struck through)
        tick(d, h.label)
        it = d.plotted.item_for(h.layer_id, h.fid)
        self.assertEqual((it.font(0).weight(), it.font(0).strikeOut()), (QFont.Weight.DemiBold, True))
        self.assertEqual(R.PLOTTED_MAX_H, 252)
        self.assertLessEqual(tree.maximumHeight(), R.PLOTTED_MAX_H)

    def test_it_keeps_its_scroll_position(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        pl = R.PlottedList(host)
        groups = [("Explorations", [("lid", i, f"X-{i:02d}", f"{i * 10} ft · 5 ft L · S", True) for i in range(40)])]
        pl.set_entries(groups)
        host.resize(300, 400)
        pl.resize(300, 400)
        host.show()
        settle()
        self.assertEqual(pl.tree.height(), R.PLOTTED_MAX_H)
        bar = pl.tree.verticalScrollBar()
        self.assertGreater(bar.maximum(), 100)
        bar.setValue(100)
        pl.set_entries(groups)                                           # the refill after a tick
        settle()
        self.assertEqual(bar.value(), 100)
        pl.item_for("lid", 30).setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(bar.value(), 100)
        pl.set_entries(groups[:1])
        self.assertEqual(bar.value(), 100)


class SimpleHit:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ------------------------------------------------------------------ 7.3-5: the Depths popup without Checks
class DepthsPopup(Case):
    def test_no_checks_pill(self):
        d = self.restore(self.settings())
        lay = d.pop_depths.body_layout
        items = [lay.itemAt(i).widget() for i in range(lay.count())]
        tops = items.index(d.top_mode.parentWidget())                    # the Tops from field box
        self.assertEqual(items[tops + 1:tops + 3], [d.zero_missing, d.top_max_diff_row])
        self.assertIs(items[-1], d.depth_readout)
        self.assertEqual([m.text() for m in d.content.findChildren(W.Disclosure)], ["Units & datum"])
        label = next(lab for lab in d.top_max_diff_row.findChildren(QLabel)
                     if lab.text() == "Ignore a table top off LIDAR by over")
        self.assertEqual(label.toolTip(), d.top_max_diff.toolTip())
        # the 0.3.6 rules: the depth line drives Tops from, 0 means missing, TD label and the LIDAR check
        d.depth_line.setChecked(False)
        self.assertFalse(any(w.isEnabled() for w in (d.top_mode, d.zero_missing, d.td_label, d.top_max_diff_row)))
        d.depth_line.setChecked(True)
        self.assertTrue(all(w.isEnabled() for w in (d.top_mode, d.zero_missing, d.td_label, d.top_max_diff_row)))
        d.top_mode.setCurrentIndex(d.top_mode.findData("dem"))            # no row has both a bottom and a depth
        self.assertFalse(d.top_max_diff_row.isEnabled())
        self.assertTrue(d.zero_missing.isEnabled())


# ------------------------------------------------------------------ 7.3-6: Scale & sheet
class ScaleAndSheet(Case):
    def test_scale_and_elevations(self):
        d = self.shown()
        d.grp_export.setCollapsed(False)
        settle()
        lay = subsection(d.grp_export, "Scale").body_layout
        box = d.distance_labels.parentWidget()
        self.assertEqual(lay.indexOf(box), lay.indexOf(d.h_scale.parentWidget().parentWidget().parentWidget()) + 1)
        self.assertEqual(box.width(), d.h_scale.parentWidget().parentWidget().parentWidget().width())   # full width
        self.assertEqual(field_label_of(d.distance_labels), "Distances")
        label = next(lab for lab in box.findChildren(QLabel) if lab.objectName() == "xsFieldLabel")
        self.assertEqual(W.tip_text(label.toolTip()),
                         "How distances along the line are written: 1,250 ft, or as stations 12+50")
        self.assertEqual([b.toolTip() for b in d.distance_labels.buttons()],
                         ["Distances in feet: 1,250", "Distances as stations: 12+50"])
        # Auto: Room below lowest | Fill sheet (and its hint); Manual: Lowest | Highest
        self.assertEqual(d.z_mode.currentData(), "auto")
        self.assertEqual((d.z_auto_row.isHidden(), d.z_range_row.isHidden(), d.z_auto_hint.wanted()),
                         (False, True, True))
        self.assertLess(in_content(d, d.below_in).x(), in_content(d, d.fill_grid).x())
        self.assertEqual([field_label_of(w) for w in (d.below_in, d.fill_grid)], ["Room below lowest", "Fill sheet"])
        d.z_mode.buttons()[d.z_mode.findData("manual")].click()
        self.assertEqual((d.z_auto_row.isHidden(), d.z_range_row.isHidden(), d.z_auto_hint.wanted()),
                         (True, False, False))
        d.z_mode.buttons()[d.z_mode.findData("auto")].click()
        self.assertEqual((d.z_auto_row.isHidden(), d.z_range_row.isHidden()), (False, True))
        self.assertEqual(d.z_auto_hint.text(), "Auto picks the range from your data plus the room below. Fill sheet "
                                               "turns the paper left over into whole grid squares.")
        # the tooltips (exactly the mockup's; their text: 0.3.7 finish, a long one wraps), and Fill sheet grayed with
        # a custom page
        def tips(ws):
            return [W.tip_text(w.toolTip()) for w in ws]

        labels = {field_label_of(w): next(lab for lab in w.parentWidget().findChildren(QLabel)
                                          if lab.objectName() == "xsFieldLabel") for w in (d.below_in, d.fill_grid)}
        self.assertEqual(tips([labels["Room below lowest"], d.below_in]), [ROOM_TIP, ROOM_TIP])
        self.assertEqual(tips([labels["Fill sheet"], d.fill_grid]), [FILL_TIP, FILL_TIP])
        self.assertEqual(tips(d.fill_grid.buttons()), FILL_TIPS)
        d.sheet.setChecks([], custom=True, emit=True)
        self.assertFalse(d.fill_grid.isEnabled() or d.orientation.isEnabled())
        self.assertEqual(tips(d.fill_grid.buttons()), [FILL_CUSTOM_TIP] * 3)
        self.assertEqual(tips([d.fill_grid]), [FILL_CUSTOM_TIP])
        d.sheet.setChecks(["tabloid"], emit=True)
        self.assertTrue(d.fill_grid.isEnabled() and d.orientation.isEnabled())
        self.assertEqual(tips(d.fill_grid.buttons()), FILL_TIPS)
        self.assertEqual(tips([d.fill_grid]), [FILL_TIP])

    def test_the_sheet_row(self):
        d = self.restore(self.settings())
        self.assertIsInstance(d.sheet_row, W._Pair)
        self.assertIsInstance(d.sheet, W.SheetSizeCombo)
        self.assertIsInstance(d.fmt, W.ElidedComboBox)
        self.assertEqual((d.fmt.currentText(), d.fmt.toolTip()), ("PDF (vector)", "PDF (vector)"))
        size_label = next(lab for lab in d.sheet.parentWidget().findChildren(QLabel)
                          if lab.objectName() == "xsFieldLabel")
        self.assertEqual((size_label.text(), W.tip_text(size_label.toolTip())),
                         ("Size", "Check several: the smallest that fits. One: just that sheet. None: Letter."))
        lst = d.sheet.list_frame()
        self.assertEqual([(r.key, r.box.text(), r.detail.text()) for r in lst.rows],
                         [("letter", "Letter", "8.5 × 11 in"), ("tabloid", "Tabloid", "11 × 17 in"),
                          ("ansic", "ANSI C", "17 × 22 in"), ("archc", "ARCH C", "18 × 24 in"),
                          ("ansid", "ANSI D", "22 × 34 in"), ("archd", "ARCH D", "24 × 36 in")])
        self.assertEqual((lst.custom_row.key, lst.custom_row.box.text(), lst.custom_row.detail.text()),
                         ("custom", "Custom", "cut to the drawing"))
        self.assertEqual(lst.foot.text(), "Several: the smallest that fits · One: just that · None: Letter")
        for width in (340, 260):                                         # side by side (both elide)
            self.show(d, width=width, height=900)
            d.grp_export.setCollapsed(False)
            settle()
            self.assertFalse(d.sheet_row.stacked(), width)
            self.assertLess(in_content(d, d.sheet).x(), in_content(d, d.fmt).x())
            self.assertEqual(in_content(d, d.sheet).y(), in_content(d, d.fmt).y())
            self.assertFalse(d.scroll.horizontalScrollBar().isVisible())
            d.hide()

    def test_size_pure_functions(self):
        self.assertEqual(D.size_text([], True), ("Custom", "Custom: the page is cut to the drawing"))
        self.assertEqual(D.size_text([], False), ("Letter", "Nothing checked: Letter"))
        self.assertEqual(D.size_text(["tabloid"], False), ("Tabloid", "Tabloid only"))
        self.assertEqual(D.size_text(["tabloid", "letter"], False),
                         ("Letter or Tabloid", "Letter or Tabloid: the smallest that fits"))
        self.assertEqual(D.size_text(["ansid", "letter", "tabloid"], False),
                         ("Smallest of 3 sizes", "Letter, Tabloid, ANSI D: the smallest that fits"))
        self.assertEqual(D.size_text(["letter"], True)[0], "Custom")
        self.assertEqual(D.sheet_from_checks([], True), ("custom", ["letter", "tabloid"]))
        self.assertEqual(D.sheet_from_checks([], False), ("letter", ["letter"]))
        self.assertEqual(D.sheet_from_checks(["ansic"], False), ("ansic", ["ansic"]))
        self.assertEqual(D.sheet_from_checks(["ansid", "letter"], False), ("smallest", ["letter", "ansid"]))
        self.assertEqual(D.checks_from_sheet("smallest", ["letter", "tabloid"]), (["letter", "tabloid"], False))
        self.assertEqual(D.checks_from_sheet("smallest", []), (["letter", "tabloid"], False))
        self.assertEqual(D.checks_from_sheet("smallest", ["ansid", "letter"]), (["letter", "ansid"], False))
        self.assertEqual(D.checks_from_sheet("tabloid", ["letter", "tabloid"]), (["tabloid"], False))
        self.assertEqual(D.checks_from_sheet("custom", ["letter"]), ([], True))
        self.assertEqual(D.checks_from_sheet("bogus", ["tabloid"]), (["tabloid"], False))
        self.assertEqual(D.checks_from_sheet("smallest", ["bogus"]), (["letter", "tabloid"], False))
        self.assertEqual((D.SIZE_DETAIL, [k for k, _n, _d in D.SIZE_ITEMS]),
                         ({"letter": "8.5 × 11 in", "tabloid": "11 × 17 in", "ansic": "17 × 22 in",
                           "archc": "18 × 24 in", "ansid": "22 × 34 in", "archd": "24 × 36 in"}, D.SHEET_KEYS))

    def test_the_size_list_from_the_dock(self):
        d = self.restore(self.settings())
        self.assertEqual((d.sheet.checked(), d.sheet.isCustom(), d.sheet.fullText()),
                         (["letter", "tabloid"], False, "Letter or Tabloid"))
        boxes = d.sheet.boxes()

        def stored():
            s = d.settings()
            return s.sheet, s.allowed_sheets
        boxes["ansid"].click()                                           # his clicks in the list
        self.assertEqual((stored(), d.sheet.fullText()), (("smallest", ["letter", "tabloid", "ansid"]),
                                                          "Smallest of 3 sizes"))
        self.assertTrue(d._user_changed)
        boxes["letter"].click()
        boxes["ansid"].click()
        self.assertEqual((stored(), d.sheet.fullText(), W.tip_text(d.sheet.toolTip())),
                         (("tabloid", ["tabloid"]), "Tabloid", "Tabloid only"))
        boxes["tabloid"].click()
        self.assertEqual((stored(), d.sheet.fullText()), (("letter", ["letter"]), "Letter"))
        boxes["custom"].click()
        self.assertEqual((stored(), d.sheet.fullText()), (("custom", ["letter", "tabloid"]), "Custom"))
        self.assertFalse(d.orientation.isEnabled() or d.fill_grid.isEnabled())
        self.assertEqual(d.orientation.toolTip(), D.ORIENT_CUSTOM_TIP)
        boxes["archc"].click()                                           # a size clears Custom
        self.assertEqual((d.sheet.isCustom(), stored()), (False, ("archc", ["archc"])))
        self.assertTrue(d.orientation.isEnabled() and d.fill_grid.isEnabled())
        boxes["custom"].click()
        boxes["letter"].click()
        self.assertEqual((d.sheet.isCustom(), d.sheet.checked()), (False, ["letter"]))
        # round trips through the widgets
        for sheet, allowed in (("smallest", ["letter", "tabloid", "ansid"]), ("tabloid", ["tabloid"]),
                               ("letter", ["letter"]), ("custom", ["letter", "tabloid"])):
            d.apply_settings(self.settings(sheet=sheet, allowed_sheets=allowed))
            self.assertEqual(stored(), (sheet, allowed))
        # an old project's fixed Tabloid with two allowed: Tabloid only, the same pages as 0.3.6 drew
        old = self.settings(sheet="tabloid", allowed_sheets=["letter", "tabloid"])
        d = self.restore(old)
        self.assertEqual((d.sheet.checked(), d.sheet.fullText()), (["tabloid"], "Tabloid"))
        d.refresh()
        written = d.settings()
        self.assertEqual((written.sheet, written.allowed_sheets), ("tabloid", ["tabloid"]))
        names = lambda p: [pg.sheet_name for pg in p.pages]                  # noqa: E731
        self.assertEqual(names(make_plan(d.model, old)), names(make_plan(d.model, written)))
        self.assertTrue(all(n.startswith("Tabloid") for n in names(d.plan)))
        # the default of an old project: Letter and Tabloid checked
        d = self.restore(self.settings(sheet="smallest", allowed_sheets=["letter", "tabloid"]))
        self.assertEqual((d.sheet.checked(), d.sheet.fullText()), (["letter", "tabloid"], "Letter or Tabloid"))

    def test_the_pages_it_gives(self):
        d = self.restore(self.settings())
        d.h_scale.setEditText("100")
        d.sheet.setChecks(["letter", "tabloid", "ansid"], emit=True)
        d.refresh()
        s = d.settings()
        self.assertEqual((s.sheet, s.allowed_sheets), ("smallest", ["letter", "tabloid", "ansid"]))
        p = d.plan
        self.assertTrue(p.fits, p.message)
        names = [pg.sheet_name for pg in p.pages]
        self.assertEqual(names, [pg.sheet_name for pg in make_plan(d.model, dataclasses.replace(
            s, sheet="smallest", allowed_sheets=["letter", "tabloid", "ansid"])).pages])
        self.assertTrue(all(n.startswith(("Letter", "Tabloid", "ANSI D")) for n in names), names)
        if len(names) > 1:                                               # tiled: on the largest checked
            self.assertTrue(all(n.startswith("ANSI D") for n in names), names)
        self.assertEqual(d.grp_export.chipText(), f"100′ / {D.fmt_scale(s.v_scale)}′ · {D.sheet_short(names[0])}" +
                         (f" · {len(names)} sheets" if len(names) > 1 else ""))
        d.sheet.setChecks(["letter"], emit=True)
        d.refresh()
        self.assertTrue(d.plan.pages)
        self.assertTrue(all(pg.sheet_name.startswith("Letter") for pg in d.plan.pages))
        self.assertIn("Letter", d.grp_export.chipText())


# ------------------------------------------------------------------ 7.3-7: grid lines None
class GridNone(Case):
    def test_the_none_buttons(self):
        d = self.restore(self.settings())
        for part in ("major", "minor"):
            seg = getattr(d, f"grid_{part}_style")
            self.assertEqual([seg.itemData(i) for i in range(seg.count())], ["solid", "dash", "dot", "none"])
            self.assertEqual([seg.itemText(i) for i in range(seg.count())], ["Solid", "Dashed", "Dotted", "None"])
            self.assertEqual([b.toolTip() for b in seg.buttons()], ["Solid", "Dashed", "Dotted", "No lines"])
            styles = [b.toolButtonStyle() for b in seg.buttons()]
            self.assertEqual(styles, [Qt.ToolButtonStyle.ToolButtonIconOnly] * 3
                             + [Qt.ToolButtonStyle.ToolButtonTextOnly])
            self.assertEqual(seg.buttons()[3].text(), "None")
            self.assertIsNone(seg.itemIcon(3))
        self.assertEqual(D.GRID_STYLE_WORDS, {"solid": "solid", "dash": "dashed", "dot": "dotted", "none": "none"})

    def test_choosing_none(self):
        d = self.restore(self.settings())
        custom_grid(d)
        self.assertEqual(d.grid_info.text(), "Major: solid · Minor: solid")
        self.assertEqual((d.grid_info.isHidden(), d.grid_custom_box.isHidden()), (False, False))
        seg = d.grid_minor_style
        seg.buttons()[seg.findData("none")].click()
        self.assertEqual(d.settings().grid_minor_style, "none")
        self.assertFalse(d.grid_minor_color.isEnabled() or d.grid_minor_width.isEnabled())
        self.assertTrue(d.grid_major_color.isEnabled() and d.grid_major_width.isEnabled())
        self.assertEqual(d.grid_info.text(), "Major: solid · Minor: none")
        d.grid_major_style.buttons()[d.grid_major_style.findData("dash")].click()
        self.assertEqual(d.grid_info.text(), "Major: dashed · Minor: none")
        d.grid_major_style.buttons()[d.grid_major_style.findData("none")].click()
        self.assertEqual(d.grid_info.text(), "Major: none · Minor: none · no grid")
        self.assertFalse(any(w.isEnabled() for w in (d.grid_major_color, d.grid_major_width, d.grid_minor_color,
                                                     d.grid_minor_width)))
        self.assertEqual(D.XSectionsDock._grid_custom_text("dot", "solid"), "Major: dotted · Minor: solid")
        seg.buttons()[seg.findData("dot")].click()
        self.assertTrue(d.grid_minor_color.isEnabled() and d.grid_minor_width.isEnabled())
        # stored "none" round trip: the widgets and the project
        s = self.settings(grid_color="custom", grid_major_style="none", grid_minor_style="dash", grid_custom_used=True)
        d.apply_settings(s)
        got = d.settings()
        self.assertEqual((got.grid_major_style, got.grid_minor_style), ("none", "dash"))
        self.assertEqual(d.grid_major_style.currentData(), "none")
        self.assertFalse(d.grid_major_color.isEnabled())
        d.save_settings()
        stored = json.loads(settings_store.stored_json(self.prj))
        self.assertEqual((stored["grid_major_style"], stored["grid_minor_style"]), ("none", "dash"))
        d2 = self.new_dock()
        d2.restore_from_project()
        self.assertEqual((d2.settings().grid_major_style, d2.grid_info.text()),
                         ("none", "Major: none · Minor: dashed"))
        # Green / Gray: the preset line; the Custom widgets keep his values
        custom = [(getattr(d, f"grid_{p}_style").currentData(), getattr(d, f"grid_{p}_width").value())
                  for p in ("major", "minor")]
        for preset in ("gray", "green"):
            d.grid_color.buttons()[d.grid_color.findData(preset)].click()
            self.assertEqual(d.grid_info.text(), d._grid_info_text(preset))
            self.assertTrue(d.grid_custom_box.isHidden())
            self.assertEqual([(getattr(d, f"grid_{p}_style").currentData(), getattr(d, f"grid_{p}_width").value())
                              for p in ("major", "minor")], custom)
            self.assertEqual((d.settings().grid_major_style, d.settings().grid_minor_style), ("none", "dash"))

    def test_a_none_swatch_is_dimmed(self):
        """(0.3.7 fix) On a dark panel a None part's colour swatch is the live swatch dimmed (GRID_DIM_OPACITY, the
        mockup's), not Qt's disabled icon: a flat light gray, brighter than the live swatch beside it."""
        old = QPalette(APP.palette())
        self.addCleanup(APP.setPalette, old)
        APP.setPalette(night_palette())
        d = self.restore(self.settings())
        self.show(d, height=900)
        d.grp_style.setCollapsed(False)
        settle()
        custom_grid(d)
        seg = d.grid_minor_style
        seg.buttons()[seg.findData("none")].click()
        settle()
        minor, major = d.grid_minor_color, d.grid_major_color
        self.assertIsInstance(minor, D.QgsColorButton)
        self.assertFalse(minor.isEnabled())
        dim = minor.graphicsEffect()
        self.assertIsInstance(dim, QGraphicsOpacityEffect)
        self.assertAlmostEqual(dim.opacity(), D.GRID_DIM_OPACITY)
        self.assertIsNone(major.graphicsEffect())
        img = d.content.grab().toImage()

        def at(w, pt):
            p = w.mapTo(d.content, pt)
            return px(img, p.x(), p.y())

        got = at(minor, minor.rect().center())
        ground = at(minor, QPoint(-2, minor.height() // 2))           # (what is under it: the section's ground)
        c, k = minor.color(), D.GRID_DIM_OPACITY
        want = QColor(*(round(k * a + (1 - k) * b) for a, b in ((c.red(), ground.red()), (c.green(), ground.green()),
                                                                 (c.blue(), ground.blue()))))
        self.assertLess(dist(got, want), 24, (got.name(), want.name()))
        self.assertLess(luma(got), luma(at(major, major.rect().center())))    # dimmer than the live one
        seg.buttons()[seg.findData("solid")].click()
        self.assertTrue(minor.isEnabled())
        self.assertIsNone(minor.graphicsEffect())

    def test_a_build_without_a_grid(self):
        d = self.restore(self.settings(grid_color="custom", grid_major_style="none", grid_minor_style="none",
                                       grid_custom_used=True))
        d.refresh()
        self.assertIsNotNone(d.model)
        self.assertTrue(d.plan.fits, d.plan.message)
        fig = Figure(figsize=(9.0, 3.5))
        F.draw_preview(fig, d.model, d.settings(), d.plan)
        self.assertEqual(grid_lines(fig), [])
        F.draw_preview(fig, d.model, dataclasses.replace(d.settings(), grid_major_style="solid"), d.plan)
        self.assertTrue(grid_lines(fig))                                 # (the same figure with a grid has them)


# ------------------------------------------------------------------ 7.3-8: the Custom grid table
class GridTable(Case):
    def test_340_and_260(self):
        d = self.restore(self.settings())
        custom_grid(d)
        t = d.grid_table
        self.assertEqual(t.COLS, (36, 32, 70))
        for width in (340, 260):
            self.show(d, width=width, height=700)
            for s in d.sections:
                s.setCollapsed(False)
            settle()
            self.assertTrue(d.scroll.verticalScrollBar().isVisible())
            need = max(getattr(d, f"grid_{p}_style").neededWidth() for p in ("major", "minor"))
            self.assertEqual(t.wrapped(), t.line_room() < need, width)
            self.assertEqual(t.wrapped(), width == 260)
            self.assertEqual(t.line_head.isHidden(), width == 260)
            for part in ("major", "minor"):
                color, wid, style = (getattr(d, f"grid_{part}_{k}") for k in ("color", "width", "style"))
                for b in style.buttons():                                # no button cut
                    room = (b.fontMetrics().horizontalAdvance(b.text()) if b.toolButtonStyle() ==
                            Qt.ToolButtonStyle.ToolButtonTextOnly else b.iconSize().width())
                    self.assertGreaterEqual(b.width(), room + 6, (width, part, b.accessibleName() or b.text()))
                x = [in_content(d, w).x() for w in (color, wid)]
                self.assertLess(x[0], x[1])
                if width == 340:
                    self.assertLess(x[1], in_content(d, style).x())       # colour, width, line in a row
                    mid = [in_content(d, w).y() + w.height() / 2.0 for w in (style, wid)]
                    self.assertLessEqual(abs(mid[0] - mid[1]), 3.0)        # (one row)
                else:                                                    # its own row, the full width
                    self.assertGreater(in_content(d, style).y(), in_content(d, wid).y() + wid.height() - 1)
                    self.assertEqual((in_content(d, style).x(), style.width()), (in_content(d, t).x(), t.width()))
            self.assertFalse(d.scroll.horizontalScrollBar().isVisible())
            d.hide()


# ------------------------------------------------------------------ 7.3-9: narrow panels
class Narrow(Case):
    def test_each_popup_at_260_and_340(self):
        self.verbose()
        d = self.restore(self.settings())
        d.refresh()
        g = d.opt_grid
        for width in (260, 340):
            self.show(d, width=width, height=700)
            d.grp_explo.setCollapsed(False)
            settle()
            need = max(b.sizeHint().width() for b in g.buttons())
            self.assertEqual(g.columns(), 2 if (g.width() - W.OPT_GAP) / 2.0 >= need else 1, width)
            for b in g.buttons():                                        # titles whole
                self.assertGreaterEqual(b.width(), need if g.columns() == 1 else b.sizeHint().width(), width)
            for p in g.popups():
                g.open_popup(p)
                settle()
                self.assertIs(g.current(), p)
                self.assertFalse(d.scroll.horizontalScrollBar().isVisible(), (width, p.title()))
                self.assertLessEqual(d.content.minimumSizeHint().width(), d.scroll.viewport().width())
                geo = p.geometry()
                self.assertTrue(geo.x() >= 0 and geo.right() < d.content.width(), (width, p.title(), geo))
                self.assertEqual(geo.width(), g.width())
                for seg in p.findChildren(W.SegmentedControl):
                    for b in seg.buttons():
                        if b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly:
                            self.assertGreaterEqual(b.width(), b.fontMetrics().horizontalAdvance(b.text()) + 5,
                                                    (width, p.title(), b.text()))
                for box in p.findChildren(QCheckBox):
                    if box.isVisible() and box.text():
                        self.assertGreaterEqual(box.width(), box.sizeHint().width(), (width, p.title(), box.text()))
                for spin in p.findChildren(QAbstractSpinBox):
                    if spin.isVisible():
                        self.assertGreaterEqual(spin.width(), W._spin_needed(spin), (width, p.title(), spin.text()))
                for h in p.findChildren(W.Hint):
                    if h.wanted():
                        self.assertTrue(h.isVisible(), (width, h.text()))
            g.close_popup()
            d.hide()


# ------------------------------------------------------------------ (0.3.7 fixes) the widths of his font
class SegoeUI(Case):
    """The widths that depend on the font, in Segoe UI 9 pt (QGIS's on his PC; the test run's own font is narrower:
    skipped where Segoe UI is not installed), the 340 px dock with its scroll bar (the popup body 268 px)."""

    def setUp(self):
        fonts = os.path.join(os.environ.get("WINDIR", ""), "Fonts")
        if not os.path.isfile(os.path.join(fonts, "segoeui.ttf")):
            self.skipTest("Segoe UI is not installed")
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            if os.path.isfile(os.path.join(fonts, name)):
                QFontDatabase.addApplicationFont(os.path.join(fonts, name))
        old = QFont(APP.font())
        APP.setFont(QFont("Segoe UI", 9))
        self.addCleanup(APP.setFont, old)
        super().setUp()                                    # (the dock made in that font)

    def test_water_and_the_lidar_check_at_340(self):
        """Draw them beside Print beside (0.3.6's 5 : 4 pair stacked them there: Print beside 1.4 px short), and the
        LIDAR check's label on one line (with the 76 px box "over" wrapped onto a line of its own)."""
        d = self.shown(height=500)
        self.assertTrue(d.scroll.verticalScrollBar().isVisible())
        g = d.opt_grid
        g.open_popup(d.opt_water)
        settle()
        two = d.screens.parentWidget()
        self.assertIsInstance(two, W._Pair)
        self.assertEqual(two.width(), 268)
        self.assertFalse(two.stacked())
        self.assertGreater(in_content(d, d.wl_label).x(), in_content(d, d.screens).x() + d.screens.width())
        g.open_popup(d.opt_depths)
        settle()
        lab = d.top_max_diff_row.findChildren(QLabel)[0]
        self.assertEqual(lab.text(), "Ignore a table top off LIDAR by over")
        self.assertGreaterEqual(lab.width(), lab.fontMetrics().horizontalAdvance(lab.text()))     # one line
        self.assertLess(lab.heightForWidth(lab.width()), 2 * lab.fontMetrics().lineSpacing())
        self.assertEqual(d.top_max_diff.width(), D.TOP_MAX_DIFF_W)
        for v in (25.0, 9999.0):                           # its number still whole
            d.top_max_diff.setValue(v)
            self.assertGreaterEqual(d.top_max_diff.width(), W._spin_needed(d.top_max_diff), v)
        self.assertEqual((d.top_mode.displayText(), d.top_mode.toolTip()), (TOPS_FULL, TOPS_TIP))
        g.close_popup()

    def test_tops_from_at_260(self):
        """Tops from ends its text with "…" in the 260 px dock (a Fusion combo cut it through a letter) and its
        tooltip gives the full text under its own."""
        d = self.shown(width=260, height=500)
        g = d.opt_grid
        g.open_popup(d.opt_depths)
        settle()
        c = d.top_mode
        self.assertIsInstance(c, W.ElidedComboBox)
        self.assertEqual(c.fullText(), TOPS_FULL)
        shown = c.displayText()
        self.assertTrue(shown.endswith("…") and TOPS_FULL.startswith(shown[:-1]), shown)
        self.assertLessEqual(c.fontMetrics().horizontalAdvance(shown), c._room(c._option()))
        self.assertEqual(c.toolTip(), f"{TOPS_TIP}\n{TOPS_FULL}")
        self.show(d, width=340, height=500)                # wide again: whole, its own tooltip alone
        settle()
        self.assertEqual((c.displayText(), c.toolTip()), (TOPS_FULL, TOPS_TIP))
        g.close_popup()

    def test_a_popup_opened_low_after_it_restacked(self):
        """Water & screens opened side by side, then, the dock narrower, opened again with its buttons at the bottom
        of the view: it is placed at its stacked height as it opens, so it scrolls into view whole (it was measured
        before its pair restacked, and its foot was left under the view's edge)."""
        d = self.shown(height=500)
        bar, view = d.scroll.verticalScrollBar(), d.scroll.viewport()
        g, pop = d.opt_grid, d.pop_water
        two = d.screens.parentWidget()
        g.open_popup(d.opt_water)
        settle()
        self.assertFalse(two.stacked())
        wide = pop.height()
        need = 2 * max(W._needed_width(d.screens), W._needed_width(d.wl_label)) + W._Pair.SPACING
        offset = d.width() - two.width()
        g.close_popup()
        self.show(d, width=max(260, need - 6 + offset), height=500)
        settle()
        self.assertTrue(bar.isVisible())
        bottom = in_content(d, g, QPoint(0, g.height())).y()
        bar.setValue(max(0, bottom - view.height() + 4))  # the buttons at the bottom of the view
        settle()
        QTest.mouseClick(d.opt_water, LeftButton)
        h = pop.height()                                   # (no event loop pass yet)
        self.assertTrue(two.stacked())
        self.assertGreater(h, wide + 10)
        settle(30)
        self.assertEqual(pop.height(), h)
        self.assertGreaterEqual(pop.mapTo(view, QPoint(0, 0)).y(), 0)
        self.assertLessEqual(pop.mapTo(view, QPoint(0, h)).y(), view.height())    # whole in view
        g.close_popup()

    def test_the_long_tooltips_wrap(self):
        """Qt's own tooltip window (0.3.7 finish, wrap_tip): Fill sheet's Below and Both, Room below lowest's, the
        Size label's, Distances' and the preview's Full screen wrap at TIP_W (Qt showed each on one line: Below
        747 px wide); Off, 260 px, stays on one line; the texts are the same."""
        d = self.shown()
        d.grp_export.setCollapsed(False)
        settle()
        pv = PreviewWidget()
        self.addCleanup(pv.deleteLater)
        pv.resize(700, 300)
        pv.show()
        settle()

        def label(w):
            return next(lab for lab in w.parentWidget().findChildren(QLabel) if lab.objectName() == "xsFieldLabel")

        off, below, both = d.fill_grid.buttons()
        full = pv.toolbar.widgetForAction(pv.act_full)
        cases = [(below, FILL_TIPS[1], True), (both, FILL_TIPS[2], True), (d.below_in, ROOM_TIP, True),
                 (label(d.below_in), ROOM_TIP, True), (label(d.sheet), D.SIZE_TIP, True),
                 (label(d.distance_labels), D.DISTANCES_TIP, True), (full, PV.FULL_TIP, True),
                 (off, FILL_TIPS[0], False)]
        for w, text, wraps in cases:
            self.assertEqual(W.tip_text(w.toolTip()), text)
            QToolTip.showText(w.mapToGlobal(QPoint(2, 2)), w.toolTip(), w)
            settle()
            tip = [x for x in QApplication.topLevelWidgets()
                   if x.metaObject().className() == "QTipLabel" and x.isVisible()][0]
            line = tip.fontMetrics().lineSpacing()
            if wraps:
                self.assertLessEqual(tip.width(), W.TIP_W + 16, text)
                self.assertGreater(tip.height(), 1.5 * line, text)                 # (two lines or more)
            else:
                self.assertEqual(w.toolTip(), text)
                self.assertLess(tip.height(), 1.5 * line + 8, text)                # (one)
                self.assertLessEqual(tip.width(), W.TIP_MAX + 16, text)
            QToolTip.hideText()
            settle()


class WrapTip(unittest.TestCase):
    def test_wrap_and_back(self):
        """wrap_tip leaves a tooltip that fits in TIP_MAX as it is, wraps a longer one in a table TIP_W wide (its
        lines kept, & < > escaped), leaves rich text alone; tip_text gives the text back."""
        text = "Room & more <here>: " + "a word " * 60
        self.assertGreater(QFontMetrics(QToolTip.font()).horizontalAdvance(text), W.TIP_MAX)
        self.assertEqual((W.wrap_tip("Solid"), W.wrap_tip("")), ("Solid", ""))
        wrapped = W.wrap_tip(text + "\nsecond")
        self.assertTrue(wrapped.startswith(f'<table width="{W.TIP_W}"'), wrapped[:40])
        self.assertIn("Room &amp; more &lt;here&gt;", wrapped)
        self.assertIn("<br>second", wrapped)
        self.assertEqual(W.tip_text(wrapped), text + "\nsecond")
        self.assertEqual(W.wrap_tip(wrapped), wrapped)
        self.assertEqual(W.tip_text("Solid"), "Solid")
        rich = "<b>" + text + "</b>"
        self.assertEqual(W.wrap_tip(rich), rich)


# ------------------------------------------------------------------ 7.3-10, 7.3-11: the status line, both themes
class StatusAndThemes(Case):
    def test_the_status_line_and_the_style_chip(self):
        self.assertEqual(P.shown("Every exploration within 50 ft of the line is left off (see Plotted explorations)."),
                         "Every exploration within 50 ft of the line is left off (see Explorations › Plotted).")
        self.assertNotIn("fill_grid", D.STYLE_KEYS)
        d = self.restore(self.settings(fill_grid="both"))
        self.assertEqual(d.grp_style.chipText(), "Defaults")              # the fill is a Scale & sheet setting

    def test_both_themes(self):
        old = QPalette(APP.palette())
        self.addCleanup(APP.setPalette, old)
        dark = QPalette(old)
        for role, c in ((QPalette.ColorRole.Window, "#323232"), (QPalette.ColorRole.WindowText, "#dddddd"),
                        (QPalette.ColorRole.Base, "#202020"), (QPalette.ColorRole.Text, "#dddddd"),
                        (QPalette.ColorRole.Button, "#535353"), (QPalette.ColorRole.Highlight, "#d7801a")):
            dark.setColor(role, QColor(c))
        d = self.shown()
        d.opt_grid.open_popup(d.opt_depths)
        settle()
        for pal in (old, dark):
            APP.setPalette(pal)
            settle()
            self.assertFalse(d.content.grab().toImage().isNull())
            t = W.theme_for(d.pop_depths.palette())
            self.assertEqual(t.dark, pal is dark)
            img = d.pop_depths.grab().toImage()
            dpr = img.devicePixelRatio()
            px = img.pixelColor(int(5 * dpr), int((W.NOTCH_H + 18) * dpr))   # the header's ground, left of its title
            self.assertEqual(px.name(), t.row_open.name(), pal is dark)
            self.assertIs(d.opt_grid.current(), d.pop_depths)


if __name__ == "__main__":
    unittest.main()
