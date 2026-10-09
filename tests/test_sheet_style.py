"""Sheet style in the panel (0.3.4, DESIGN.md decision 23): the grid (Green | Gray | Custom, the Custom table of
colours, widths and line styles, "Start from Green · Gray"), the depth line widths (Black and gray, Color, Reset, the
NEW badge), the section's chip, and how the values are kept: with the project only (never QgsSettings), the first
Custom of a project starting from the preset in use and later ones keeping his values. "Data lines" is gone.

The texts are the approved mockup's (scratchpad mockup_style/body.html)."""
import dataclasses
import json
import unittest
from unittest import mock

from tests.fixtures import load_project, start_app

APP = start_app()

from qgis.core import QgsProject  # noqa: E402
from qgis.PyQt.QtCore import QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

from tests.test_ui import make_iface  # noqa: E402
from xsections.core.model import (DEPTH_LW_BLACK, DEPTH_LW_COLOR, GRID_PRESETS, GRID_W_MAX, GRID_W_MIN,  # noqa: E402
                                  Settings)
from xsections.ui import dock as D  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402
from xsections.ui.dock import XSectionsDock  # noqa: E402

GREEN, GRAY = GRID_PRESETS["green"], GRID_PRESETS["gray"]
GREEN_LINE = ('<span style="color:#5f9a72">━━</span> Major 0.7 pt &nbsp; <span style="color:#a8c8b2">──</span> '
              'Minor 0.35 pt &nbsp; solid · the default')
GRAY_LINE = ('<span style="color:#6e6e6e">━━</span> Major 0.7 pt &nbsp; <span style="color:#b4b4b4">──</span> '
             'Minor 0.35 pt &nbsp; solid')
NEW_KEYS = ("grid_major_color", "grid_major_width", "grid_major_style", "grid_minor_color", "grid_minor_width",
            "grid_minor_style", "grid_custom_used", "depth_lw_black", "depth_lw_color")


class StyleCase(unittest.TestCase):
    """The fixture project and a dock on it (restored: nothing saved yet)."""

    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.dock = XSectionsDock(make_iface(), None)
        self.dock.restore_from_project()
        self.addCleanup(self._drop, self.dock)

    @staticmethod
    def _drop(d):
        d.cleanup()
        d.deleteLater()
        APP.processEvents()

    def new_dock(self) -> XSectionsDock:
        d = XSectionsDock(make_iface(), None)
        self.addCleanup(self._drop, d)
        d.restore_from_project()
        return d

    @staticmethod
    def click(seg, data) -> None:
        """What a click on a segmented button does."""
        seg.buttons()[seg.findData(data)].click()

    @staticmethod
    def custom(d):
        """((major colour, width, style), (minor ...)) as the Custom widgets show them."""
        return tuple((getattr(d, f"grid_{p}_color").color().name(), getattr(d, f"grid_{p}_width").value(),
                      getattr(d, f"grid_{p}_style").currentData()) for p in ("major", "minor"))

    def chip(self, d=None):
        return (d or self.dock).grp_style.chipText()


class Layout(StyleCase):
    def test_data_lines_are_gone(self):
        d = self.dock
        self.assertFalse(hasattr(d, "data_color"))
        self.assertNotIn("data_color", {f.name for f in dataclasses.fields(Settings)})
        self.assertNotIn("data_color", D.STYLE_KEYS)

    def test_the_mockup_order(self):
        """Grid, its preset line or the Custom table (with the spacing note and Start from), Depth lines (NEW, Reset),
        Black and gray | Color, the hint, Printer edge | Fill with grid under a dashed rule, the checkboxes, the
        note."""
        d = self.dock
        body = d.grp_style.body_layout
        top = [body.itemAt(i).widget() for i in range(body.count())]

        def index(w):
            return next(i for i, t in enumerate(top) if t is w or t.isAncestorOf(w))

        order = [d.grid_color, d.grid_info, d.grid_custom_box, d.depth_lw_head, d.depth_lw_black, d.depth_lw_hint,
                 d.edge_margin, d.compact_layout]
        self.assertEqual([index(w) for w in order], list(range(len(order))))
        self.assertIs(top[index(d.edge_margin)], d.style_rule)
        self.assertTrue(d.style_rule.isAncestorOf(d.fill_grid))
        self.assertEqual((d.style_rule.objectName(), d.depth_lw_head.objectName()), ("xsRuleTop", "xsSubheadRow"))
        self.assertEqual(top[-1].text(), "The defaults leave the most room to draw and the paper clear for colored "
                                         "pencil.")
        self.assertTrue(d.depth_lw_head.isAncestorOf(d.btn_lw_reset) and d.depth_lw_head.isAncestorOf(d.depth_lw_new))
        self.assertEqual(d.depth_lw_hint.text(), "Which layers are black, gray or in color is set for each layer, under "
                                                 "Explorations &gt; <b>Drawn in</b>.")
        self.assertEqual([d.grid_color.itemText(i) for i in range(3)], ["Green", "Gray", "Custom"])
        self.assertEqual([b.toolTip() for b in d.grid_color.buttons()],
                         ["Green engineering pad (the default)", "Gray, for black-and-white printers",
                          "Your own colors, widths and line styles"])
        # shown: Custom's table, column by column; Major over Minor; the spacing note and Start from under it
        self.click(d.grid_color, "custom")
        d.resize(340, 900)
        d.show()
        for s in d.sections:
            s.setCollapsed(s is not d.grp_style)
        APP.processEvents()
        try:
            def pos(w):
                return w.mapTo(d.grp_style, w.rect().topLeft())
            for part in ("major", "minor"):
                xs = [pos(getattr(d, f"grid_{part}_{k}")).x() for k in ("color", "width", "style")]
                self.assertEqual(xs, sorted(xs), part)
            self.assertLess(pos(d.grid_major_color).y(), pos(d.grid_minor_color).y())
            self.assertLess(pos(d.grid_minor_color).y(), pos(d.grid_spacing_note).y())
            self.assertLess(pos(d.grid_spacing_note).x(), pos(d.btn_grid_from_green).x())
            self.assertLess(pos(d.btn_grid_from_green).x(), pos(d.btn_grid_from_gray).x())
            self.assertLess(pos(d.grid_spacing_note).y(), pos(d.depth_lw_head).y())
            self.assertGreaterEqual(d.grid_major_width.width(), 68)
            heads = [w.text() for w in d.grid_custom_box.findChildren(W.QLabel) if w.objectName() == "xsFieldLabel"]
            self.assertEqual(heads, ["COLOR", "WIDTH", "LINE"])
            self.assertFalse(d.scroll.horizontalScrollBar().isVisible())
        finally:
            d.hide()

    def test_preset_lines_and_the_custom_box(self):
        d = self.dock
        self.assertEqual(d.grid_color.currentData(), "green")
        self.assertEqual(d.grid_info.text(), GREEN_LINE)
        self.assertEqual(d.grid_info.textFormat(), Qt.TextFormat.RichText)
        self.assertEqual((d.grid_info.isHidden(), d.grid_custom_box.isHidden()), (False, True))
        self.click(d.grid_color, "gray")
        self.assertEqual(d.grid_info.text(), GRAY_LINE)
        self.assertEqual((d.grid_info.isHidden(), d.grid_custom_box.isHidden()), (False, True))
        self.click(d.grid_color, "custom")
        self.assertEqual((d.grid_info.isHidden(), d.grid_custom_box.isHidden()), (True, False))
        self.click(d.grid_color, "green")
        self.assertEqual((d.grid_info.text(), d.grid_custom_box.isHidden()), (GREEN_LINE, True))

    def test_line_style_buttons(self):
        d = self.dock
        for part in ("major", "minor"):
            seg = getattr(d, f"grid_{part}_style")
            self.assertEqual(seg.toolTip(), f"{part.capitalize()} grid line style")
            self.assertEqual([seg.itemData(i) for i in range(seg.count())], ["solid", "dash", "dot"])
            for b, name in zip(seg.buttons(), ("Solid", "Dashed", "Dotted")):
                self.assertEqual(b.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
                self.assertEqual((b.accessibleName(), b.toolTip()), (name, name))
                self.assertEqual(b.iconSize(), QSize(22, 8))
                self.assertFalse(b.icon().isNull())
                pm = b.icon().pixmap(QSize(22, 8))
                self.assertEqual((pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()), (22, 8))
        for v, svg in W.LINE_STYLE_ICONS.items():
            self.assertTrue(svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 8"'), v)
            self.assertIn("currentColor", svg)
        self.assertIn('stroke-dasharray="5 2.5"', W.LINE_STYLE_ICONS["dash"])
        self.assertIn('stroke-dasharray="0.1 3.2" stroke-linecap="round"', W.LINE_STYLE_ICONS["dot"])
        pm = W.svg_pixmap(W.LINE_STYLE_ICONS["solid"], "#ff0000", 22, height=8)
        img = pm.toImage()
        self.assertEqual((img.width(), img.height()), (44, 16))
        self.assertEqual(img.pixelColor(22, 8).name(), "#ff0000")        # the line through the middle
        self.assertEqual(img.pixelColor(22, 1).alpha(), 0)

    def test_colour_buttons_and_spins(self):
        d = self.dock
        for part in ("major", "minor"):
            word = part.capitalize()
            b = getattr(d, f"grid_{part}_color")
            self.assertEqual((b.showMenu(), b.allowOpacity(), b.width(), b.height()), (False, False, 30, 24))
            self.assertEqual((b.colorDialogTitle(), b.toolTip()), (f"{word} grid color", f"{word} grid color"))
            s = getattr(d, f"grid_{part}_width")
            self.assertEqual((s.minimum(), s.maximum(), s.singleStep(), s.decimals(), s.suffix(), s.toolTip()),
                             (GRID_W_MIN, GRID_W_MAX, 0.05, 2, " pt", f"{word} grid width"))
        for s, hi, tip in ((d.depth_lw_black, 3.0, "Width of black and gray depth lines"),
                           (d.depth_lw_color, 4.0, "Width of colored depth lines")):
            self.assertEqual((s.minimum(), s.maximum(), s.singleStep(), s.decimals(), s.suffix(), s.toolTip()),
                             (0.25, hi, 0.05, 2, " pt", tip))
        self.assertEqual((d.depth_lw_black.value(), d.depth_lw_color.value()), (0.75, 1.6))
        # the NEW badge and Reset
        self.assertFalse(d.depth_lw_new.isHidden())
        self.assertEqual((d.depth_lw_new.text(), d.depth_lw_new.objectName(), d.depth_lw_new.toolTip()),
                         ("NEW", "xsNewBadge", "New in 0.3.4"))
        self.assertEqual(D.NEW_BADGE_VERSION, "0.3.4")
        self.assertEqual((d.btn_lw_reset.text(), d.btn_lw_reset.toolTip()), ("Reset", "Back to 0.75 pt and 1.6 pt"))
        d.depth_lw_black.setValue(1.0)
        d.depth_lw_color.setValue(2.25)
        self.assertEqual((d.settings().depth_lw_black, d.settings().depth_lw_color), (1.0, 2.25))
        d.btn_lw_reset.click()
        self.assertEqual((d.depth_lw_black.value(), d.depth_lw_color.value()), (DEPTH_LW_BLACK, DEPTH_LW_COLOR))
        self.assertEqual((d.settings().depth_lw_black, d.settings().depth_lw_color), (0.75, 1.6))
        # the widths and Reset follow the depth line
        d.depth_line.setChecked(False)
        self.assertEqual([w.isEnabled() for w in (d.depth_lw_black, d.depth_lw_color, d.btn_lw_reset)],
                         [False, False, False])
        d.depth_line.setChecked(True)
        self.assertEqual([w.isEnabled() for w in (d.depth_lw_black, d.depth_lw_color, d.btn_lw_reset)],
                         [True, True, True])

    def test_the_spacing_note_follows_the_automatic_grid(self):
        d = self.dock
        self.click(d.grid_color, "custom")
        self.assertTrue(d.grid_auto.isChecked())
        self.assertEqual(d.grid_spacing_note.text(), "Major lines every inch, minor every tenth.")
        d.grid_auto.setChecked(False)
        self.assertEqual(d.grid_spacing_note.text(), "Major and minor lines at the spacing set under Scale & sheet.")
        d.grid_auto.setChecked(True)
        self.assertEqual(d.grid_spacing_note.text(), "Major lines every inch, minor every tenth.")
        d.apply_settings(Settings(grid_auto=False, grid_color="custom"))
        self.assertEqual(d.grid_spacing_note.text(), "Major and minor lines at the spacing set under Scale & sheet.")


class CustomGrid(StyleCase):
    def test_the_first_custom_starts_from_the_preset_in_use(self):
        d = self.dock
        self.assertFalse(d._grid_custom_used)
        self.click(d.grid_color, "gray")
        self.click(d.grid_color, "custom")
        self.assertEqual(self.custom(d), GRAY)                            # from Gray, the preset in use
        self.assertTrue(d._grid_custom_used)
        s = d.settings()
        self.assertEqual((s.grid_color, s.grid_custom_used), ("custom", True))
        # his edits, Green, Custom again: his edits back (Green and Gray never touch them)
        d.grid_major_width.setValue(1.5)
        self.click(d.grid_major_style, "dash")
        d.grid_minor_color.setColor(QColor("#c2185b"))
        mine = (("#6e6e6e", 1.5, "dash"), ("#c2185b", 0.35, "solid"))
        self.assertEqual(self.custom(d), mine)
        self.click(d.grid_color, "green")
        self.assertEqual(self.custom(d), mine)
        self.assertEqual(d.settings().grid_major_width, 1.5)               # remembered under a preset too
        self.click(d.grid_color, "custom")
        self.assertEqual(self.custom(d), mine)
        # saved with the project, reopened, Green, then Custom: still his
        d.save_settings()
        stored = json.loads(settings_store.stored_json(self.prj))
        self.assertEqual((stored["grid_color"], stored["grid_custom_used"], stored["grid_major_style"]),
                         ("custom", True, "dash"))
        again = self.new_dock()
        self.assertEqual((again.grid_color.currentData(), self.custom(again)), ("custom", mine))
        self.click(again.grid_color, "green")
        self.click(again.grid_color, "custom")
        self.assertEqual(self.custom(again), mine)
        # saved under Green after Custom: the next Custom keeps his values too (grid_custom_used)
        self.click(again.grid_color, "gray")
        again.save_settings()
        third = self.new_dock()
        self.assertEqual((third.grid_color.currentData(), third._grid_custom_used), ("gray", True))
        self.click(third.grid_color, "custom")
        self.assertEqual(self.custom(third), mine)

    def test_first_custom_from_green_and_on_a_fresh_project(self):
        d = self.dock
        self.click(d.grid_color, "custom")
        self.assertEqual(self.custom(d), GREEN)
        d.project_cleared()
        self.assertFalse(d._grid_custom_used)
        self.click(d.grid_color, "gray")
        d.grid_major_width.setValue(2.0)            # (hidden under Gray: not his Custom yet)
        self.click(d.grid_color, "custom")
        self.assertEqual(self.custom(d), GRAY)

    def test_start_from_is_one_save_and_one_rebuild(self):
        d = self.dock
        self.click(d.grid_color, "custom")
        d.grid_major_width.setValue(2.5)
        d._timer.stop()
        d._user_changed = False
        starts = []
        real_start = d._timer.start
        with mock.patch.object(d._timer, "start", side_effect=lambda *a: (starts.append(1), real_start(*a))), \
                mock.patch.object(d, "save_settings", wraps=d.save_settings) as save, \
                mock.patch.object(d, "refresh") as refresh, mock.patch.object(d, "isVisible", return_value=True):
            d.btn_grid_from_gray.click()
            self.assertEqual(len(starts), 1)
            self.assertEqual(self.custom(d), GRAY)
            self.assertTrue(d._user_changed)
            d._timer.stop()
            d._on_timer()
            self.assertEqual((save.call_count, refresh.call_count), (1, 1))
            starts.clear()
            d.btn_grid_from_green.click()
            self.assertEqual((len(starts), self.custom(d)), (1, GREEN))
            starts.clear()
            d.depth_lw_black.setValue(2.0)
            d.depth_lw_color.setValue(3.0)
            starts.clear()
            d.btn_lw_reset.click()
            self.assertEqual(len(starts), 1)
        stored = json.loads(settings_store.stored_json(self.prj))
        self.assertEqual((stored["grid_major_color"], stored["grid_major_width"], stored["grid_minor_color"]),
                         ("#6e6e6e", 0.7, "#b4b4b4"))

    def test_edits_mark_the_user(self):
        d = self.dock
        self.click(d.grid_color, "custom")
        for change in (lambda: d.grid_major_color.setColor(QColor("#123456")),
                       lambda: d.grid_minor_width.setValue(0.8),
                       lambda: self.click(d.grid_minor_style, "dot"),
                       lambda: d.depth_lw_color.setValue(2.0)):
            d._timer.stop()
            d._user_changed = False
            change()
            self.assertTrue(d._user_changed and d._timer.isActive())
        s = d.settings()
        self.assertEqual((s.grid_major_color, s.grid_minor_width, s.grid_minor_style, s.depth_lw_color),
                         ("#123456", 0.8, "dot", 2.0))


class Chip(StyleCase):
    def test_the_four_states(self):
        d = self.dock
        self.assertEqual(self.chip(), "Defaults")
        self.click(d.grid_color, "gray")
        self.assertEqual(self.chip(), "Gray grid")
        self.click(d.grid_color, "custom")
        self.assertEqual(self.chip(), "Custom grid")
        self.click(d.grid_color, "green")
        self.assertEqual(self.chip(), "Defaults")
        d.depth_lw_black.setValue(1.0)
        d.depth_lw_color.setValue(2.25)
        self.assertEqual(self.chip(), "Green grid · lines 1 / 2.25 pt")
        self.click(d.grid_color, "gray")
        self.assertEqual(self.chip(), "Gray grid · lines 1 / 2.25 pt")
        d.btn_lw_reset.click()
        self.click(d.grid_color, "green")
        self.assertEqual(self.chip(), "Defaults")
        d.shade_below.setChecked(True)                 # only a non-grid key differs
        self.assertEqual(self.chip(), "Green grid")
        d.shade_below.setChecked(False)
        d.grid_major_width.setValue(2.0)               # a Custom value under Green: still the defaults
        self.assertEqual(self.chip(), "Defaults")
        self.assertEqual(D.STYLE_KEYS, ("grid_color", "depth_lw_black", "depth_lw_color", "shade_below", "show_bends",
                                        "compact_layout", "edge_margin_in", "show_notes", "fill_grid"))


class Keeping(StyleCase):
    def test_project_cleared_and_never_qgssettings(self):
        d = self.dock
        with mock.patch.object(settings_store, "QgsSettings") as qs:
            self.click(d.grid_color, "custom")
            d.grid_major_width.setValue(2.0)
            d.depth_lw_black.setValue(1.5)
            d.save_settings()
            self.assertIn('"grid_major_width": 2.0', settings_store.stored_json(self.prj))
            d.project_cleared()
            self.assertEqual(qs.return_value.setValue.call_count, 0)    # nothing goes to QgsSettings
        s = d.settings()
        self.assertEqual((s.grid_color, s.depth_lw_black, s.depth_lw_color, s.grid_custom_used),
                         ("green", 0.75, 1.6, False))
        self.assertEqual(self.custom(d), GREEN)
        self.assertEqual([getattr(s, k) for k in NEW_KEYS], [getattr(Settings(), k) for k in NEW_KEYS])
        self.assertEqual((d.grid_info.isHidden(), d.grid_custom_box.isHidden(), self.chip()), (False, True,
                                                                                               "Defaults"))

    def test_round_trip_of_every_new_key(self):
        d = self.dock
        for s in (Settings(grid_color="custom", grid_major_color="#1f6fb2", grid_major_width=1.25,
                           grid_major_style="dash", grid_minor_color="#c2185b", grid_minor_width=0.5,
                           grid_minor_style="dot", grid_custom_used=True, depth_lw_black=1.0, depth_lw_color=2.25),
                  Settings(grid_color="gray", grid_major_color="#123456", grid_major_width=3.0,
                           grid_major_style="dot", grid_minor_color="#abcdef", grid_minor_width=0.1,
                           grid_minor_style="dash", grid_custom_used=True, depth_lw_black=0.25, depth_lw_color=4.0),
                  Settings(grid_color="green", grid_major_width=0.333, depth_lw_color=1.234),     # kept as stored
                  Settings()):
            d.apply_settings(s)
            got = d.settings()
            self.assertEqual([(k, getattr(got, k)) for k in ("grid_color",) + NEW_KEYS],
                             [(k, getattr(s, k)) for k in ("grid_color",) + NEW_KEYS])
        # a Custom grid stored without grid_custom_used (a hand-made one) is his: it counts as used
        d.apply_settings(Settings(grid_color="custom", grid_major_width=2.0))
        self.assertTrue(d.settings().grid_custom_used)

    def test_bad_stored_values(self):
        """The store path: bad values dropped (their defaults) or clamped, before the widgets see them."""
        data = json.loads(Settings().to_json())
        data.update(grid_color="custom", grid_major_color="#ABCDEF", grid_major_width=9.0, grid_major_style="wavy",
                    grid_minor_color="blue", grid_minor_width=0.01, grid_minor_style="dot", grid_custom_used="yes",
                    depth_lw_black=-1, depth_lw_color="2")
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(data))
        d = self.new_dock()
        self.assertEqual(self.custom(d), (("#abcdef", 3.0, "solid"), ("#a8c8b2", 0.1, "dot")))
        self.assertEqual((d.depth_lw_black.value(), d.depth_lw_color.value()), (0.25, 1.6))
        s = d.settings()
        self.assertEqual((s.grid_color, s.grid_custom_used), ("custom", True))
        data.update(grid_color="neon", grid_custom_used=False, depth_lw_black=True)
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(data))
        d = self.new_dock()
        self.assertEqual((d.grid_color.currentData(), d._grid_custom_used, d.depth_lw_black.value()),
                         ("green", False, 0.75))
        self.assertFalse(d._user_changed)                             # loading never saves


if __name__ == "__main__":
    unittest.main()
