"""The rows of the redesigned panel (0.3.6, DESIGN.md decision 27; stage P2 of the panel build): Other features rows
of three kinds (points, lines, polygons) with the grouped symbol drop-down, exploration rows with the tabs Layer |
Depths | Water, their subtitles and header icons, the guesses he has not checked (`guessed`, the "check" badge and
card, "Looks right"), problems shown on a row, the Plotted subsection, and the row lists that space the cards and
let their section's body paint the open ones. The rows on their own, without the dock, on the fixture layers."""
import copy
import time
import unittest
from collections import Counter

from tests.fixtures import (area_row, budget, make_areas_layer, make_others_layer, make_points_layer,
                            make_seeps_layer, make_streams_layer, make_supply_layer, point_row, seep_row, start_app,
                            stream_row, timing_test)

APP = start_app()

from qgis.core import QgsFeature, QgsField, QgsProject, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QMetaType, QPoint, QPointF, Qt  # noqa: E402
from qgis.PyQt.QtGui import QFont, QMouseEvent  # noqa: E402
from qgis.PyQt.QtTest import QTest  # noqa: E402
from qgis.PyQt.QtWidgets import QLabel, QScrollArea, QStyle, QStyleFactory, QVBoxLayout, QWidget  # noqa: E402

from xsections.core import model as M  # noqa: E402
from xsections.render import symbols as SY  # noqa: E402
from xsections.ui import point_guess as G  # noqa: E402
from xsections.ui import point_rows as R  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402

SUPPLY_GUESSED = ["label_field", "type_field", "top_field", "depth_field", "atd_field", "atd_date_field"]
SUPPLY_HINT = ("Guessed from the field names (check them): <b>AESI_MapLabel, ExploType_resolved, ExploElev, "
               "WellCompleteDepth</b>; water <b>GW_Elev_ATD</b> as ATD elevations.")


class Count:
    """Counts a signal's emissions (and keeps their arguments)."""

    def __init__(self, signal):
        self.n = 0
        self.args = []
        signal.connect(self)

    def __call__(self, *args):
        self.n += 1
        self.args.append(args)


def settle(n=12):
    for _ in range(n):
        APP.processEvents()


def water_table(name="Boring Summary"):
    lyr = QgsVectorLayer("None", name, "memory")
    lyr.dataProvider().addAttributes([QgsField("ExploName", QMetaType.Type.QString),
                                      QgsField("DTW", QMetaType.Type.Double)])
    lyr.updateFields()
    f = QgsFeature(lyr.fields())
    f.setAttributes(["B-1", 12.0])
    lyr.dataProvider().addFeatures([f])
    return lyr


class _Rows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prj = QgsProject.instance()
        prj.clear()
        cls.prj = prj
        cls.pts, cls.others, cls.supply = make_points_layer(), make_others_layer(), make_supply_layer()
        cls.seeps, cls.streams, cls.areas = make_seeps_layer(), make_streams_layer(), make_areas_layer()
        cls.table = water_table()
        prj.addMapLayers([cls.pts, cls.others, cls.supply, cls.seeps, cls.streams, cls.areas, cls.table])

    def take(self, row, layer):
        """`layer` out of the project as the dock sees it (the row told before and after); returns it."""
        row.set_removing(True)
        out = self.prj.takeMapLayer(layer)
        row.set_removing(False)
        return out

    def back(self, row, layer):
        self.prj.addMapLayer(layer)
        row.sync_layer()

    @staticmethod
    def shown(seg):
        return [b.text() for b in seg.buttons() if not b.isHidden()]


# ================================================================ Other features rows (D7)
class Kinds(_Rows):
    def test_three_kinds(self):
        """A point, line or polygon layer makes the row's kind and its editor (the mockup's per kind)."""
        p = R.OtherPointsRow(seep_row(self.seeps, label_field="Name"))
        self.assertEqual((p.kind(), p.value()["kind"]), ("point", "point"))
        self.assertFalse(p.symbol_row.isHidden() or p.elev_box.isHidden())
        self.assertTrue(p.bracket_box.isHidden() and p.edges_box.isHidden() and p.area_style_row.isHidden())
        self.assertTrue(p.symbol_row.isAncestorOf(p.color_btn))
        self.assertEqual(self.shown(p.elev_seg), ["Ground line", "LIDAR", "Field"])
        line = R.OtherPointsRow(stream_row(self.streams, label_field="Name"))
        self.assertEqual(line.kind(), "line")
        self.assertEqual([line.elev_seg.itemText(i) for i in range(3)], ["Ground line", "LIDAR", "Field"])
        self.assertEqual(self.shown(line.elev_seg), ["Ground line", "Field"])        # LIDAR hidden for lines
        self.assertEqual(self.shown(line.empty_seg), ["Line", "Off"])
        self.assertFalse(line.symbol_row.isHidden())
        area = R.OtherPointsRow(area_row(self.areas, label_field="Name"))
        self.assertEqual(area.kind(), "polygon")
        self.assertFalse(area.bracket_box.isHidden() or area.edges_box.isHidden() or area.area_style_row.isHidden())
        self.assertTrue(area.symbol_row.isHidden() and area.elev_box.isHidden() and area.elev_field_row.isHidden())
        self.assertTrue(area.area_style_row.isAncestorOf(area.color_btn))             # Color | Line
        self.assertEqual([area.bracket_seg.itemText(i) for i in range(2)], ["In the frame", "Above the frame"])
        self.assertEqual([area.edges_seg.itemText(i) for i in range(3)], ["Off", "To ground", "Full height"])
        self.assertEqual([area.bracket_style_seg.itemText(i) for i in range(2)], ["Solid", "Dashed"])
        self.assertEqual([b.toolTip() for b in area.bracket_seg.buttons()],
                         ["Inside the frame, above the ground and the exploration labels", "In a row over the frame"])
        self.assertEqual((area.color_btn.toolTip(), line.color_btn.toolTip(), area.visible_box.toolTip()),
                         ("Color of the bracket and its label", "Color of the symbol",
                          "Draw a bracket where the section runs through these areas"))
        self.assertEqual(area.type_field.emptyText(), "(none: every feature)")
        # the layer's kind wins over the row's; a missing layer keeps the row's
        row = R.OtherPointsRow(seep_row(self.streams, label_field="Name"))      # stored "point", a line layer
        self.assertEqual((row.kind(), row.value()["kind"]), ("line", "line"))
        row = R.OtherPointsRow(stream_row(self.streams, label_field="Name"))
        lyr = self.take(row, self.streams)
        try:
            self.assertTrue(row.is_missing())
            self.assertEqual((row.kind(), row.value()["kind"]), ("line", "line"))
            self.assertEqual(row.sub_label.text(), "lines · layer not in the project")
        finally:
            self.back(row, lyr)
        self.assertFalse(row.is_missing())

    def test_a_line_row_keeps_a_stored_lidar(self):
        """A line row offers Ground line | Field; a hand-made "lidar" still shows its LIDAR button."""
        row = R.OtherPointsRow(stream_row(self.streams, label_field="Name", elev="lidar", elev_empty="lidar"))
        self.assertEqual(self.shown(row.elev_seg), ["Ground line", "LIDAR", "Field"])
        self.assertEqual(self.shown(row.empty_seg), ["Line", "LIDAR", "Off"])
        self.assertEqual(row.value()["elev"], "lidar")

    def test_round_trips(self):
        ch = None
        for d in (stream_row(self.streams, label_field="Name", type_field="Type", types=["Ditch"]),
                  area_row(self.areas, label_field="Name", bracket="above", edges="full", bracket_style="dash",
                           color="#123456"),
                  seep_row(self.seeps, label_field="Name", shape="spring", color="#00aa00", elev="field",
                           elev_field="Elev_ft", elev_empty="off")):
            row = R.OtherPointsRow()
            ch = Count(row.changed)
            row.set_value(copy.deepcopy(d))
            self.assertEqual(row.value(), d)
            self.assertEqual(list(row.value()), list(M.OTHER_POINT_DEFAULTS))
            self.assertEqual(ch.n, 0)
        # a 0.3.5 point row (its 12 keys) loads as a point row with the four 0.3.6 defaults
        old = {k: v for k, v in seep_row(self.seeps, label_field="Name").items()
               if k not in ("kind", "bracket", "bracket_style", "edges")}
        self.assertEqual(len(old), 12)
        row = R.OtherPointsRow(old)
        self.assertEqual(row.value(), dict(old, kind="point", bracket="inside", bracket_style="solid", edges="off"))
        self.assertEqual(row.kind(), "point")

    def test_a_layer_of_another_kind(self):
        """His layer of another kind: the untouched default symbol and colour become the new kind's; his own stay."""
        row = R.OtherPointsRow(seep_row(self.seeps, label_field="Name"))
        ch = Count(row.changed)
        row.layer_combo.setLayer(self.streams)
        v = row.value()
        self.assertEqual((v["kind"], v["shape"], v["color"]), ("line", "stream", SY.usual_color("stream")))
        self.assertEqual(ch.n, 1)
        row.layer_combo.setLayer(self.areas)                              # line -> polygon
        v = row.value()
        self.assertEqual((v["kind"], v["shape"], v["color"]), ("polygon", "asterisk", M.AREA_COLOR_DEFAULT))
        self.assertTrue(row.symbol_row.isHidden() and row.area_style_row.isAncestorOf(row.color_btn))
        row.layer_combo.setLayer(self.seeps)                              # polygon -> point
        v = row.value()
        self.assertEqual((v["kind"], v["shape"], v["color"]), ("point", "asterisk", "#1f6fb2"))
        mine = R.OtherPointsRow(seep_row(self.seeps, label_field="Name", shape="well", color="#aa0000"))
        mine.layer_combo.setLayer(self.streams)
        v = mine.value()
        self.assertEqual((v["kind"], v["shape"], v["color"]), ("line", "well", "#aa0000"))


class SymbolDropDown(_Rows):
    def test_items(self):
        """The five groups' headers (never selectable) and the 30 symbols in grouped() order, each with its picture
        and its description; "General shapes" last, the Asterisk first in it."""
        c = R.SymbolCombo()
        heads = [i for i in range(c.count()) if c.itemData(i, R.HEADER_ROLE)]
        self.assertEqual([c.itemText(i) for i in heads], [g for g, _items in SY.grouped()])
        self.assertEqual(c.itemText(heads[-1]), "General shapes")
        for i in heads:
            self.assertEqual(c.model().item(i).flags(), Qt.ItemFlag.NoItemFlags)
            self.assertIsNone(c.itemData(i))
        keys = [c.itemData(i) for i in range(c.count()) if c.itemData(i)]
        self.assertEqual(keys, [s.key for _g, items in SY.grouped() for s in items])
        self.assertEqual(len(keys), 30)
        self.assertEqual(c.itemData(heads[-1] + 1), "asterisk")             # the first of General shapes
        self.assertEqual(set(R.SYMBOL_TIPS), set(SY.CHOICE_KEYS))
        for i in range(c.count()):
            key = c.itemData(i)
            if key:
                self.assertFalse(c.itemIcon(i).isNull(), key)
                self.assertEqual(c.itemData(i, Qt.ItemDataRole.ToolTipRole), R.SYMBOL_TIPS[key])
                self.assertTrue(R.SYMBOL_TIPS[key])
                self.assertEqual(c.itemText(i), SY.SYMBOLS[key].name)
        self.assertEqual(R.SYMBOL_TIPS["asterisk"], "Seeps and anything else.")
        self.assertEqual(SY.GROUPS[-1], "General shapes")                    # D8 (3.7)
        # a list under the box with a scroll bar (not Fusion's menu over the box, whose list has none)
        self.assertEqual(c.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup, None, c), 0)
        self.assertNotEqual(c.view().verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual((c.view().objectName(), c.view().minimumWidth(), c.maxVisibleItems()),
                         ("xsSymbolList", 262, 13))

    def test_a_pick_sets_the_usual_color(self):
        row = R.OtherPointsRow(seep_row(self.seeps, label_field="Name", color="#aa0000"))
        c = row.symbol_combo
        self.assertEqual((c.current_key(), c.currentText()), ("asterisk", "Asterisk"))
        ch, picked = Count(row.changed), Count(c.symbolChosen)
        c.set_symbol("spring", "#123456")                                    # silent
        c.set_symbol("asterisk", "#aa0000")
        self.assertEqual((ch.n, picked.n), (0, 0))
        i = c.findData("wq")
        c.setCurrentIndex(i)
        c.activated.emit(i)                                                  # his pick
        v = row.value()
        self.assertEqual((v["shape"], v["color"]), ("wq", "#2e7d32"))
        self.assertEqual((ch.n, picked.args), (1, [("wq",)]))
        self.assertEqual((row.swatch.shape(), row.swatch.color()), ("wq", "#2e7d32"))
        self.assertEqual((c.currentText(), c.color()), ("Water-quality sample site", "#2e7d32"))
        self.assertEqual(row.color_btn.color().name(), "#2e7d32")

    def test_headers_are_never_current(self):
        c = R.SymbolCombo()
        c.set_symbol("wetland")
        QTest.keyClick(c, Qt.Key.Key_Down)                                   # over the next group's header
        self.assertEqual(c.current_key(), "well")
        QTest.keyClick(c, Qt.Key.Key_Up)
        self.assertEqual(c.current_key(), "wetland")
        c.set_symbol("spring")
        QTest.keyClick(c, Qt.Key.Key_Up)                                     # the first header: stays
        self.assertEqual(c.current_key(), "spring")

    def test_a_click_on_a_header_picks_nothing(self):
        """Under Fusion (his QGIS style) the open list follows the pointer, but a header never becomes its current item:
        a click on a header must not pick the item hovered last (nor reset his colour). A symbol's click still picks."""
        row = R.OtherPointsRow(seep_row(self.seeps, label_field="Name", shape="spring", color="#aa0000"))
        c = row.symbol_combo
        fusion = QStyleFactory.create("Fusion")
        c.setStyle(fusion)
        # (the style is Python's: back to the application's before the row goes, else a garbage collection that frees
        # the style first leaves the combo's stylesheet proxy on a deleted base and the process crashes later)
        self.addCleanup(c.setStyle, None)
        self.assertEqual(c.style().styleHint(QStyle.StyleHint.SH_ComboBox_ListMouseTracking, None, c), 1)
        row.resize(320, 600)
        row.show()
        row.set_editor_open(True)
        settle()
        ch, picked = Count(row.changed), Count(c.symbolChosen)
        c.showPopup()
        settle(20)
        QTest.qWait(APP.doubleClickInterval() + 50)              # (the popup ignores a release just after it opened)
        view, m = c.view(), c.model()
        vp = view.viewport()
        self.addCleanup(c.hidePopup)
        self.assertTrue(view.isVisible())

        def send(kind, pt, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.NoButton):
            APP.sendEvent(vp, QMouseEvent(kind, QPointF(pt), QPointF(vp.mapToGlobal(pt)), button, buttons,
                                          Qt.KeyboardModifier.NoModifier))
            settle(2)

        def click(pt):
            send(QEvent.Type.MouseButtonPress, pt, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
            send(QEvent.Type.MouseButtonRelease, pt, Qt.MouseButton.LeftButton)
            settle(20)

        # the pointer straight onto a header, no symbol hovered on the way: the box's own symbol is not picked
        # again (nor his colour reset to its usual one)
        first = next(i for i in range(c.count()) if c.itemData(i, R.HEADER_ROLE))
        self.assertLess(first, c.currentIndex())                             # "Water at the surface", over Spring
        view.scrollTo(m.index(first, 0))
        settle()
        top = view.visualRect(m.index(first, 0)).center()
        send(QEvent.Type.MouseMove, top)
        self.assertEqual(view.currentIndex().row(), c.currentIndex())        # (a header never becomes current)
        click(top)
        v = row.value()
        self.assertTrue(view.isVisible())
        self.assertEqual((v["shape"], v["color"], c.current_key()), ("spring", "#aa0000", "spring"))
        self.assertEqual((ch.n, picked.n), (0, 0))
        # from the last symbol of a group down onto the next group's header
        head = next(i for i in range(c.count()) if c.itemData(i, R.HEADER_ROLE) and i > c.currentIndex())
        view.scrollTo(m.index(head, 0))
        settle()
        above = view.visualRect(m.index(head - 1, 0)).center()               # Wetland, the last of its group
        on = view.visualRect(m.index(head, 0)).center()                      # "Wells shown as points (no log)"
        for y in range(above.y(), on.y() + 1, 3):
            send(QEvent.Type.MouseMove, QPoint(on.x(), y))
        self.assertEqual(view.currentIndex().row(), head - 1)                # the hovered item stays current
        click(on)
        v = row.value()
        self.assertTrue(view.isVisible())                                    # the list stays open
        self.assertEqual((v["shape"], v["color"], c.current_key()), ("spring", "#aa0000", "spring"))
        self.assertEqual((ch.n, picked.n), (0, 0))
        # a symbol's own click still picks it (and sets its usual colour)
        well = view.visualRect(m.index(head + 1, 0)).center()
        send(QEvent.Type.MouseMove, well)
        click(well)
        v = row.value()
        self.assertFalse(view.isVisible())
        self.assertEqual((v["shape"], v["color"]), ("well", SY.usual_color("well")))
        self.assertEqual((ch.n, picked.args), (1, [("well",)]))

    def test_the_legacy_star(self):
        """A row holding the star lists it last, under its own header, until another symbol is chosen."""
        row = R.OtherPointsRow(seep_row(self.seeps, label_field="Name", shape="star"))
        c = row.symbol_combo
        self.assertEqual(c.count(), 37)
        self.assertEqual((c.itemText(c.count() - 2), c.itemText(c.count() - 1)), ("Kept from an older version", "Star"))
        self.assertEqual((c.current_key(), row.value()["shape"]), ("star", "star"))
        i = c.findData("circle")
        c.setCurrentIndex(i)
        c.activated.emit(i)
        self.assertEqual((row.value()["shape"], c.count(), c.findData("star")), ("circle", 35, -1))

    @timing_test
    def test_budget(self):
        """Twenty Other features rows, each with its drop-down (the pictures are made once)."""
        R.OtherPointsRow(seep_row(self.seeps, label_field="Name"))           # (the pictures, once)
        t0 = time.perf_counter()
        rows = [R.OtherPointsRow(seep_row(self.seeps, label_field="Name")) for _ in range(20)]
        dt = time.perf_counter() - t0
        self.assertLessEqual(dt, budget(1.5), f"20 Other features rows: {dt:.2f} s")
        self.assertEqual(len(rows), 20)


class Subtitles(_Rows):
    def test_other_features(self):
        p = R.OtherPointsRow(seep_row(self.seeps, label_field="Name"))
        self.assertEqual(p.sub_label.text(), "points · Name · ground line")
        self.assertEqual(p.sub_label.keyPart(), "Name")
        p.elev_seg.setCurrentIndex(p.elev_seg.findData("lidar"))
        self.assertEqual(p.sub_label.text(), "points · Name · LIDAR")
        p.elev_seg.setCurrentIndex(p.elev_seg.findData("field"))
        self.assertEqual(p.sub_label.text(), "points · Name · (no field)")
        p.elev_field.setField("Elev_ft")
        self.assertEqual(p.sub_label.text(), "points · Name · Elev_ft")
        line = R.OtherPointsRow(stream_row(self.streams, label_field="Name"))
        self.assertEqual(line.sub_label.text(), "lines · Name")
        line.set_counts(Counter({"": 2}))
        self.assertEqual(line.sub_label.text(), "lines · Name · 2 crossings")
        line.set_counts(Counter({"Ditch": 1}))
        self.assertEqual(line.sub_label.text(), "lines · Name · 1 crossing")
        area = R.OtherPointsRow(area_row(self.areas, label_field="Name"))
        self.assertEqual(area.sub_label.text(), "areas · Name · bracket in the frame")
        area.bracket_seg.setCurrentIndex(area.bracket_seg.findData("above"))
        self.assertEqual(area.sub_label.text(), "areas · Name · bracket above the frame")
        self.assertEqual(R.OtherPointsRow().sub_label.text(), "no layer chosen")
        self.assertEqual(R.OtherPointsRow().name_label.text(), "(choose a layer)")
        row = R.OtherPointsRow(seep_row(self.seeps, label_field="Name"))
        lyr = self.take(row, self.seeps)
        try:
            self.assertEqual(row.sub_label.text(), "points · layer not in the project")
            self.assertEqual(row.sub_label.keyPart(), "")
        finally:
            self.back(row, lyr)

    def test_explorations(self):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName", type_field="ExploType",
                                         types=["Boring", "CPT"]))
        self.assertEqual(row.sub_label.text(), "ExploName · 2 of 4 types · black")
        self.assertEqual(row.sub_label.keyPart(), "ExploName")
        row.look_seg.setCurrentIndex(row.look_seg.findData("gray"))
        self.assertEqual(row.sub_label.text(), "ExploName · 2 of 4 types · gray")
        row.look_seg.setCurrentIndex(row.look_seg.findData("color"))
        self.assertEqual(row.sub_label.text(), "ExploName · 2 of 4 types · color")
        row.wl_table.setLayer(self.table)
        self.assertEqual(row.sub_label.text(), "ExploName · 2 of 4 types · color · table Boring Summary")
        lyr = self.take(row, self.pts)
        try:
            self.assertEqual(row.sub_label.text(), "layer not in the project · color")
        finally:
            self.back(row, lyr)
        self.assertEqual(R.ExplorationRow().sub_label.text(), "no layer chosen")

    def test_header_icons(self):
        area = R.OtherPointsRow(area_row(self.areas, label_field="Name", bracket_style="dash", color="#123456"))
        self.assertEqual((area.swatch.kind(), area.swatch.bracket_style(), area.swatch.color()),
                         ("bracket", "dash", "#123456"))
        self.assertEqual(area.swatch.toolTip(), "The bracket of these areas")
        p = R.OtherPointsRow(seep_row(self.seeps, label_field="Name", shape="spring"))
        self.assertEqual((p.swatch.kind(), p.swatch.shape(), p.swatch.color()), ("symbol", "spring", "#1f6fb2"))
        self.assertEqual(p.swatch.toolTip(), "The symbol of these points")

    def test_an_open_row_is_semibold(self):
        row = R.OtherPointsRow(seep_row(self.seeps, label_field="Name"))
        self.assertEqual(row.sub_label.font().weight(), QFont.Weight.Normal)
        row.set_editor_open(True)
        self.assertEqual((row.name_label.font().weight(), row.sub_label.font().weight()),
                         (QFont.Weight.DemiBold, QFont.Weight.DemiBold))
        row.set_editor_open(False)
        self.assertEqual(row.sub_label.font().weight(), QFont.Weight.Normal)


# ================================================================ exploration rows: tabs (D4)
class Tabs(_Rows):
    def test_tabs_and_panes(self):
        row = R.ExplorationRow(point_row(self.others, label_field="ExploName", type_field="ExploType_resolved"))
        self.assertEqual([row.tabs.tabText(i) for i in range(row.tabs.count())], ["Layer", "Depths", "Water"])
        self.assertEqual((row.tabs.currentIndex(), row.current_tab()), (0, "layer"))
        self.assertTrue(row.tabs.isHidden() and not row.editor_open())
        self.assertEqual([p.isHidden() for p in (row.pane_layer, row.pane_depths, row.pane_water)],
                         [False, True, True])
        panes = {row.pane_layer: (row.layer_combo, row.name_edit, row.look_seg, row.look_hint, row.style_box,
                                  row.label_field, row.type_field, row.type_list),
                 row.pane_depths: (row.top_field, row.bottom_elev_field, row.depth_field, row.in_range_box,
                                   row.range_hint, row.depths_hint),
                 row.pane_water: (row.wl_field, row.wl_date_field, row.atd_field, row.atd_date_field,
                                  row.screen_top_field, row.screen_bottom_field, row.wl_values, row.screen_values,
                                  row.wl_table, row.table_box, row.water_hint)}
        for pane, widgets in panes.items():
            for w in widgets:
                self.assertTrue(pane.isAncestorOf(w), w)
        self.assertFalse(hasattr(row, "more") or hasattr(row, "more_hint") or hasattr(row, "water_head"))
        # the guess's hint and the tabs: between the header and the editor, outside it
        lay = row.card_layout
        self.assertEqual([lay.indexOf(w) for w in (row.header, row.guess_hint, row.tabs, row.editor)], [0, 1, 2, 3])
        self.assertFalse(row.editor.isAncestorOf(row.guess_hint) or row.editor.isAncestorOf(row.tabs))
        row.show_tab("water")
        self.assertTrue(row.editor_open() and not row.tabs.isHidden())
        self.assertEqual((row.tabs.currentIndex(), row.current_tab()), (2, "water"))
        self.assertEqual([p.isHidden() for p in (row.pane_layer, row.pane_depths, row.pane_water)],
                         [True, True, False])
        row.tabs.setCurrentIndex(1)
        self.assertEqual([p.isHidden() for p in (row.pane_layer, row.pane_depths, row.pane_water)],
                         [True, False, True])
        row.set_editor_open(False)
        self.assertTrue(row.tabs.isHidden())

    def test_the_water_tab(self):
        """Dimmed (still a tab) for a layer without water-level or screen fields, with its tooltip and hint."""
        row = R.ExplorationRow(point_row(self.others, label_field="ExploName"))
        self.assertTrue(row.tabs.isTabDimmed(2))
        self.assertEqual(row.tabs.tabToolTip(2), "No water-level or screen fields")
        self.assertTrue(row.water_hint.wanted())
        self.assertEqual(row.water_hint.text(), "This layer has no water-level or screen fields, so none are drawn "
                                                "for it.")
        sup = R.ExplorationRow()
        sup.set_value(dict(layer_id=self.supply.id()), guess_fields=True)             # its ATD field guessed
        self.assertFalse(sup.tabs.isTabDimmed(2))
        self.assertEqual(sup.tabs.tabToolTip(2), "")
        self.assertFalse(sup.water_hint.wanted())
        self.assertFalse(R.ExplorationRow().tabs.isTabDimmed(2))                       # no layer: nothing to say

    def test_rule_y_and_texts(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        lay.addWidget(row)
        panel.resize(340, 700)
        panel.show()
        self.addCleanup(panel.deleteLater)
        settle()
        self.assertIsNone(row.rule_y())
        row.set_editor_open(True)
        settle()
        self.assertEqual(row.rule_y(), row.tabs.geometry().bottom())
        self.assertGreater(row.rule_y(), row.header.geometry().bottom())
        # the explanations that left the panel: tooltips, and Verbose hints
        head = row.look_seg.parentWidget().findChild(QLabel, "xsFieldLabel")
        self.assertEqual((head.text(), head.toolTip()), ("Drawn in", R.LOOK_HINT))
        self.assertEqual(row.look_seg.toolTip(), R.LOOK_HINT)
        self.assertEqual(row.look_hint.text(), "Black like your own explorations; Gray sets a layer apart; Color "
                                               "takes each exploration’s color from the layer’s style in QGIS.")
        self.assertEqual(row.depths_hint.text(), "Top from the table, else LIDAR; bottom from the table, else top "
                                                 "− depth.")
        self.assertTrue(row.depths_hint.wanted() and row.depths_hint.isHidden())      # Verbose is off
        W.set_verbose(True)
        self.addCleanup(W.set_verbose, False)
        row.show_tab("depths")
        settle()
        self.assertTrue(row.depths_hint.isVisible())
        self.assertTrue(row.style_box.foot.isHidden())                                 # (Black: no style box)
        self.assertEqual(row.style_box.toolTip(), "Change them in Layer Properties > Symbology; the sheet follows.")
        self.assertEqual([w.text() for w in row.editor.findChildren(QLabel, "xsFieldLabel")
                          if w.text() in ("Legend", "Label", "Type", "Types")], ["Legend", "Label", "Type", "Types"])


# ================================================================ guesses and "Looks right" (D14, D15)
class Guesses(_Rows):
    def fresh(self):
        row = R.ExplorationRow()
        row.set_value(dict(layer_id=self.supply.id(), in_range=False), guess_fields=True)
        return row

    def test_a_fresh_row_to_check(self):
        row = self.fresh()
        self.assertEqual(row.value()["guessed"], SUPPLY_GUESSED)
        self.assertEqual(row.stored()["guessed"], SUPPLY_GUESSED)
        self.assertEqual(row.guess_hint.text(), SUPPLY_HINT)
        self.assertFalse(row.guess_hint.wanted())                         # over the tabs: only while open
        row.set_editor_open(True)
        self.assertTrue(row.guess_hint.wanted() and row.guess_hint.isWarn())
        self.assertFalse(row.badge.isHidden())
        self.assertEqual((row.badge.text(), row.check_text()), ("check", ""))
        self.assertTrue(row.problem_label.isHidden())
        # the card, opened by a click on the badge
        panel = QWidget()
        panel._xs_card_host = host = W.CardHost(panel)
        QVBoxLayout(panel).addWidget(row)
        row.set_editor_open(False)
        panel.resize(340, 600)
        panel.show()
        self.addCleanup(panel.deleteLater)
        settle()
        row.badge.click()
        self.assertTrue(host.is_open())
        self.assertEqual(host.card.titles(), ["Fields were guessed"])
        self.assertEqual(host.card.items(), [("Label", "AESI_MapLabel", ""), ("Type", "ExploType_resolved", ""),
                                             ("Top", "ExploElev", ""), ("Total depth", "WellCompleteDepth", ""),
                                             ("ATD level", "GW_Elev_ATD", " · elevations"),
                                             ("ATD date", "ExploDate", "")])
        self.assertEqual([b.text() for b in host.card.buttons()], ["Open Depths", "Looks right"])
        self.assertEqual(row.badge.blocks[0].source, "Supply wells · from the field names")
        # Looks right (the card's primary button): the guess goes for good, saved with the row
        saved, items = row.value(), list(row.badge.blocks[0].items)
        ch = Count(row.changed)
        host.card.buttons()[1].click()
        self.assertFalse(host.is_open())
        self.assertEqual((row.value()["guessed"], row.stored()["guessed"]), ([], []))
        self.assertTrue(row.badge.isHidden())
        self.assertEqual(row.guess_hint.text(), "")
        self.assertEqual(ch.n, 1)
        row.confirm_guess()                                               # nothing left to confirm
        self.assertEqual(ch.n, 1)
        # the saved row, before he confirmed: the badge and the same card again
        again = R.ExplorationRow(saved)
        self.assertEqual(again.value()["guessed"], SUPPLY_GUESSED)
        self.assertFalse(again.badge.isHidden())
        self.assertEqual(list(again.badge.blocks[0].items), items)

    def test_his_own_choices(self):
        """His edit of a guessed box makes it his; a change of Levels are, its two levels; a new layer guesses
        afresh; a missing layer writes the stored list back."""
        row = self.fresh()
        ch = Count(row.changed)
        row.type_field.setField("WellStatus")
        self.assertEqual(row.value()["guessed"], [k for k in SUPPLY_GUESSED if k != "type_field"])
        row.top_field.setField("")
        self.assertNotIn("top_field", row.value()["guessed"])
        row.wl_values.setCurrentIndex(row.wl_values.findData("depth"))
        self.assertEqual(row.value()["guessed"], ["label_field", "depth_field", "atd_date_field"])
        self.assertEqual(ch.n, 3)
        self.assertEqual([t for t, _v, _s in row.badge.blocks[0].items], ["Label", "Total depth", "ATD date"])
        self.assertEqual(row.badge.actions, [("open_depths", "Open Depths"), ("looks_right", "Looks right")])
        # only Layer-tab boxes left: "Open Layer"
        row.depth_field.setField("ExploDepth")
        row.atd_date_field.setField("")
        self.assertEqual(row.badge.actions, [("open_layer", "Open Layer"), ("looks_right", "Looks right")])
        # a water box first: "Open Water"
        w = R.ExplorationRow(point_row(self.supply, label_field="AESI_MapLabel", atd_field="GW_Elev_ATD",
                                       guessed=["atd_field", "label_field"]))
        self.assertEqual(w.value()["guessed"], ["label_field", "atd_field"])
        self.assertEqual(w.badge.actions[0], ("open_water", "Open Water"))
        # a missing layer: the stored list written back; back, the badge again
        lyr = self.take(w, self.supply)
        try:
            self.assertEqual(w.value()["guessed"], ["label_field", "atd_field"])
            self.assertTrue(w.badge.isHidden())                          # nothing to check on a missing layer
        finally:
            self.back(w, lyr)
        self.assertEqual(w.value()["guessed"], ["label_field", "atd_field"])
        self.assertFalse(w.badge.isHidden())
        # a stored guess whose box is empty now is dropped
        e = R.ExplorationRow(point_row(self.supply, label_field="AESI_MapLabel", guessed=["label_field", "wl_field"]))
        self.assertEqual(e.value()["guessed"], ["label_field"])
        # his new layer: guessed afresh (his Total depth, which the new layer has too, is kept: not a guess)
        row.layer_combo.setLayer(self.others)
        self.assertEqual(row.value()["guessed"], ["label_field", "type_field", "top_field"])
        self.assertEqual(row.value()["depth_field"], "ExploDepth")

    def test_a_saved_field_the_layer_lost(self):
        """A saved field the layer no longer has (renamed in the layer) is guessed again on load: a guess to check
        (the badge, the card, the guess hint), with the boxes left to check from before; never a silent change."""
        d = point_row(self.supply, label_field="AESI_MapLabel", type_field="ExploType_resolved",
                      top_field="TopElev_old", depth_field="WellCompleteDepth", atd_field="GW_Elev_ATD",
                      guessed=["label_field"])
        row = R.ExplorationRow(d)
        v = row.value()
        self.assertEqual((v["top_field"], v["guessed"], row.guessed()),
                         ("ExploElev", ["label_field", "top_field"], ["label_field", "top_field"]))
        self.assertEqual((row.badge.isHidden(), row.badge.text(), row.check_text()), (False, "check", ""))
        self.assertEqual([(t, val) for t, val, _s in row.badge.blocks[0].items],
                         [("Label", "AESI_MapLabel"), ("Top", "ExploElev")])
        self.assertEqual(row.guess_hint.text(),
                         "Guessed from the field names (check them): <b>AESI_MapLabel, ExploElev</b>.")
        # only the lost one: the badge all the same
        row = R.ExplorationRow(dict(d, guessed=[]))
        self.assertEqual((row.guessed(), row.badge.isHidden()), (["top_field"], False))
        # his saved fields, all in the layer: nothing new to check
        self.assertEqual(R.ExplorationRow(dict(d, top_field="ExploElev", guessed=[])).guessed(), [])
        # the layer taken back with a renamed field (take_layer: a missing layer added again)
        gone = R.ExplorationRow(dict(d, layer_id="gone_layer_id", guessed=[]))
        self.assertTrue(gone.is_missing())
        gone.take_layer(self.supply)
        self.assertEqual((gone.value()["top_field"], gone.guessed(), gone.badge.isHidden()),
                         ("ExploElev", ["top_field"], False))

    def test_the_model_and_the_guess_functions(self):
        self.assertEqual(M.GUESS_KEYS, G.GUESS_KEYS)
        self.assertEqual(list(M.POINT_LAYER_DEFAULTS)[-1], "guessed")
        self.assertEqual(M.POINT_LAYER_DEFAULTS["guessed"], [])
        self.assertEqual(M.clean_point_layer({"guessed": ["wl_field", "label_field", "nope", "label_field"]})
                         ["guessed"], ["label_field", "wl_field"])
        self.assertEqual(M.clean_point_layer({"guessed": ["label_field", 3]})["guessed"], [])
        self.assertEqual(M.clean_point_layer({})["guessed"], [])
        fields = [(f.name(), W.field_kind(f)) for f in self.supply.fields()]
        g, hint, keys = G.guess_point_fields(fields, set(), "Supply wells")
        self.assertEqual((g, hint), G.guess_point_row(fields, set(), "Supply wells"))
        self.assertEqual((hint, keys), (SUPPLY_HINT, SUPPLY_GUESSED))
        self.assertEqual(G.guess_hint(g, keys, g["wl_values"]), SUPPLY_HINT)
        self.assertEqual(G.guess_hint(g, [], "elevation"), "")
        self.assertEqual(G.guess_hint(g, ["top_field", "atd_field"], "elevation"),
                         "Guessed from the field names (check them): <b>ExploElev</b>; water <b>GW_Elev_ATD</b> as "
                         "ATD elevations.")
        # a date guessed for his own level (his layer change kept his fields; only the empty date was guessed)
        dates = dict(g, wl_field="GW_Elev_ATD", wl_date_field="ExploDate")
        self.assertEqual(G.guess_hint(g, ["atd_date_field"], "elevation"),
                         "Guessed from the field names (check them): ATD date <b>ExploDate</b>.")
        self.assertEqual(G.guess_hint(dates, ["wl_date_field"], "elevation"),
                         "Guessed from the field names (check them): measured date <b>ExploDate</b>.")
        self.assertEqual(G.guess_hint(dates, ["top_field", "wl_date_field", "atd_date_field"], "elevation"),
                         "Guessed from the field names (check them): <b>ExploElev</b>; measured date "
                         "<b>ExploDate</b>; ATD date <b>ExploDate</b>.")
        self.assertEqual(G.guess_hint(g, ["nope"], "elevation"), "")              # never ": ."
        row = R.ExplorationRow(point_row(self.supply, label_field="AESI_MapLabel", atd_field="GW_Elev_ATD",
                                         atd_date_field="ExploDate", guessed=["atd_date_field"]))
        self.assertEqual(row.guess_hint.text(), "Guessed from the field names (check them): ATD date <b>ExploDate</b>.")
        # nothing guessed for a saved row whose fields the layer has
        _g, hint, keys = G.guess_point_fields(fields, set(), "x", saved=dict(label_field="AESI_MapLabel"),
                                              guess_fields=False)
        self.assertEqual((hint, keys), ("", []))
        # Other features rows have no guesses to check
        self.assertNotIn("guessed", R.OtherPointsRow(seep_row(self.seeps)).value())


class Problems(_Rows):
    def test_set_problems(self):
        row = R.ExplorationRow(point_row(self.others, label_field="ExploName"))
        cc = Count(row.checksChanged)
        probs = [W.Problem("a", W.CardInfo("t", actions=[("open_water", "Open Water")]), 2),
                 W.Problem("b", W.CardInfo("u"))]
        row.set_problems(probs)
        self.assertEqual((row.badge.text(), row.check_text(), row.problem_label.toolTip()), ("3", "a · +1 more",
                                                                                           "a\nb"))
        self.assertFalse(row.badge.isHidden() or row.problem_label.isHidden())
        self.assertEqual(cc.n, 1)
        row.set_problems(probs)                                           # the same: nothing changed
        row.refresh_labels()
        self.assertEqual(cc.n, 1)
        self.assertEqual(row.problems(), probs)
        row.badge.actionTriggered.emit("open_water")                     # the card's button
        self.assertTrue(row.editor_open())
        self.assertEqual(row.current_tab(), "water")
        row.set_problems([])
        self.assertTrue(row.badge.isHidden() and row.problem_label.isHidden())
        self.assertEqual((cc.n, row.check_text()), (2, ""))
        # a problem and a guess: the count, both blocks, the guess's buttons last
        sup = R.ExplorationRow()
        sup.set_value(dict(layer_id=self.supply.id()), guess_fields=True)
        sup.set_problems([W.Problem("Style not read; drawn in black",
                                    W.CardInfo("Style not read", actions=[("open_layer", "Open Layer")]))])
        self.assertEqual(sup.badge.text(), "1")
        self.assertEqual([b.title for b in sup.badge.blocks], ["Style not read", "Fields were guessed"])
        self.assertEqual(sup.badge.actions, [("open_layer", "Open Layer"), ("open_depths", "Open Depths"),
                                             ("looks_right", "Looks right")])
        # "open" on an Other features row opens it
        o = R.OtherPointsRow(seep_row(self.seeps, label_field="Name"))
        o.badge.actionTriggered.emit("open")
        self.assertTrue(o.editor_open())

    def test_reveal(self):
        """A card's button scrolls the row into view."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        lay = QVBoxLayout(content)
        spacer = QWidget()
        spacer.setFixedHeight(1500)
        lay.addWidget(spacer)
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        lay.addWidget(row)
        area.setWidget(content)
        area.resize(340, 400)
        area.show()
        self.addCleanup(area.deleteLater)
        settle()
        self.assertEqual(area.verticalScrollBar().value(), 0)
        row.show_tab("depths")
        settle()
        self.assertGreater(area.verticalScrollBar().value(), 1000)


# ================================================================ Plotted (D11) and the row lists
class PlottedAndLists(_Rows):
    def test_plotted(self):
        pl = R.PlottedList()
        self.assertEqual((pl.heading.title(), pl.heading.label.text()), ("Plotted", "PLOTTED"))
        self.assertTrue(pl.heading.isAncestorOf(pl.btn_show_all) and not pl.btn_show_all.isHidden())
        self.assertEqual(pl.btn_show_all.text(), "Show all")
        self.assertIsInstance(pl.count_label, W.Hint)
        self.assertIsInstance(pl.hint, W.Hint)
        self.assertEqual(pl.hint.text(), "Untick one to leave it off this section only.")
        self.assertEqual((pl.count_label.text(), pl.count_label.wanted()), ("", False))
        self.assertEqual((pl.text(), pl.heading.toolTip()), ("Plotted explorations", "Plotted explorations"))
        pl.set_entries([("Explorations", [(self.pts.id(), 1, "B-1", "300 ft", True), (self.pts.id(), 2, "B-2",
                                                                                      "900 ft", True),
                                          (self.pts.id(), 3, "B-3", "1,200 ft", False)])])
        self.assertEqual(pl.text(), "Plotted explorations (2 of 3, 1 left off by you)")
        self.assertEqual(pl.heading.toolTip(), pl.text())
        self.assertEqual((pl.count_label.text(), pl.count_label.wanted()), ("2 of 3", True))
        self.assertTrue(pl.count_label.isHidden())                        # Verbose only
        W.set_verbose(True)
        self.addCleanup(W.set_verbose, False)
        self.assertFalse(pl.count_label.isHidden())
        # never folded (stage P3 deleted the two shims of stage P2)
        self.assertFalse(hasattr(pl, "expandedChanged"))
        self.assertFalse(pl.tree.isHidden())

    def test_lists_space_and_host_the_cards(self):
        body = W.SectionBody()
        lst = R.PointRowList(R.ExplorationRow)
        body.body_layout.addWidget(lst)
        cc = Count(lst.checksChanged)
        lst.set_rows([point_row(self.pts, label_field="ExploName"), point_row(self.others, label_field="ExploName"),
                      point_row(self.supply, label_field="AESI_MapLabel")])
        lst.set_band_host(body)
        self.assertIs(lst.band_host(), body)
        self.assertEqual(body.watched(), lst.rows)
        self.assertEqual((lst.layout().spacing(), lst.layout().contentsMargins().left()), (4, 0))
        a, b, c = lst.rows
        a.set_editor_open(True)
        b.set_editor_open(True)
        self.assertEqual((a.gaps(), b.gaps(), c.gaps()), ((4, 8), (0, 8), (0, 0)))    # (link_cards)
        c.set_editor_open(True)
        self.assertEqual(c.gaps(), (0, 0))                                 # the last: nothing under it
        d = lst.append(point_row(self.pts, label_field="ExploName"))
        self.assertIn(d, body.watched())
        self.assertEqual(c.gaps(), (0, 8))
        lst.remove(a)
        self.assertNotIn(a, body.watched())
        ch = Count(a.changed)                                              # going: its boxes' moves are no choices
        a.layer_combo.setLayer(None)                                       # (layers removed before it is deleted)
        self.assertEqual((ch.n, a.stored()["layer_id"]), (0, self.pts.id()))
        self.assertEqual(b.gaps(), (4, 8))                                 # first now
        d.set_problems([W.Problem("x", W.CardInfo("t"))])
        self.assertEqual(cc.n, 1)
        lst.set_band_host(None)
        self.assertEqual(body.watched(), [])
        self.assertIsInstance(b, W.LayerCard)

    def test_the_type_list_box(self):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName", type_field="ExploType"))
        self.assertIs(row.type_box.inner, row.type_list)
        self.assertTrue(row.type_box.isEnabled() and row.type_list.isEnabled())
        self.assertEqual(row.type_list.sizeHintForRow(0), R.TypeList.ROW_H)
        row.type_field.setField("")
        self.assertFalse(row.type_box.isEnabled() or row.type_list.isEnabled())
        head = row.type_box.parentWidget().findChild(QLabel, "xsFieldLabel")
        self.assertEqual(head.text(), "Types")
        self.assertFalse(head.isEnabled())                                # the label greys with the box


if __name__ == "__main__":
    unittest.main()
