"""Point-layer rows of the panel (0.3.3, DESIGN.md decision 22), stage C1: the field guesses (ui.point_guess) on his
exact field names, and the row widgets (ui.point_rows: ExplorationRow, OtherPointsRow, TypeList, PlottedList,
PointRowList) on their own, without the dock, on memory layers and on a layer written to a GeoPackage. Also the
widgets.py additions (moved helpers, set_field, icon buttons, swatches).

0.3.4 (DESIGN.md decision 23): Drawn in Black | Gray | Color, and a Color row's style box (StyleBox): what the row
reads from its layer's own QGIS style, on memory layers with fixed renderers (a memory layer's default symbol has a
random colour)."""
import ast
import copy
import os
import time
import unittest
from collections import Counter

from tests.fixtures import (CRS, CUMBERLAND_AESI, OTHERS, ROOT, SUPPLY, budget, categorized_renderer,
                            make_dense_layer, make_others_layer, make_points_layer, make_seeps_layer, make_supply_layer,
                            point_row, rule_renderer, seep_row, single_renderer, start_app, timing_test, write_gpkg)

APP = start_app()

from qgis.core import (QgsFeature, QgsField, QgsGraduatedSymbolRenderer, QgsHeatmapRenderer,  # noqa: E402
                       QgsMarkerSymbol, QgsProject, QgsRendererRange, QgsVectorLayer)
from qgis.gui import QgsFieldComboBox  # noqa: E402
from qgis.PyQt.QtCore import QMetaType, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402
from qgis.PyQt.QtWidgets import QToolButton  # noqa: E402

from xsections.core.model import (LOOK_GRAY, NO_ATD, NO_TYPES, OTHER_POINT_DEFAULTS,  # noqa: E402
                                  POINT_LAYER_DEFAULTS)
from xsections.core.symbology import read_styles  # noqa: E402
from xsections.render.symbols import CHOICE_KEYS  # noqa: E402
from xsections.ui import point_guess as G  # noqa: E402
from xsections.ui import point_rows as R  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402

UI = os.path.join(ROOT, "xsections", "ui")


def fields(spec):
    """(name, is_numeric) from "name name# ..." (# = a number field)."""
    return [(t.rstrip("#"), t.endswith("#")) for t in spec.split()]


# his three GeoPackage layers (Explorations.gpkg, PRAGMA table_info of a copy) and CDF_wells.dbf, in field order;
# INTEGER, REAL, SMALLINT, MEDIUMINT are number fields; DATETIME and TEXT are not; `id` is the GeoPackage fid (pk)
AESI = fields("id# AESI_ProjNumYr AESI_ProjNumTxt AESI_ProjName Phase ExploType_resolved ExploType ExploName "
              "ExploDepth# ExploDate# Year# ExploMonYr Well_Tag_N LocatConf_resolved LocatConf Comments FillDepth# "
              "DepthToQvt# DepthToQva# DepthToQvr# DepthToGW# GW_Elev# ExploElev# Elevation_Method_resolved "
              "Elevation_Method Surveyor Document_Link Document_Date# Document_ID# DataSource Radiocarbon "
              "Editor_resolved Editor EditDate# CreationDate# Creator EditDate_1# Editor_1 ExploNameYear")
OTHER = fields("id# ExploType_resolved ExploType ExploName ExploDepth# ExploDate# Year# ExploMonYr Well_Tag_N "
               "LocatConf_resolved LocatConf Comments ExploElev# Elevation_Method_resolved Elevation_Method "
               "Document_Title Document_Date# Document_Author_resolved Document_Author Document_Link GlobalID")
SUPPLY_F = fields("id# AESI_ProjNum# AESI_ProjName ExploType ExploType_resolved WellStatus Pwsid WELL_LOG_ID# "
                  "WELL_TAG_NR NIT_ID_NR AESI_internal AESI_MapLabel ExploElev# ExploElevSource VertDatum "
                  "VertDatum_resolved ExploDepth# WellCompleteDepth# ExploDate Year# DepthToGW_ATD# GW_Elev_ATD# "
                  "WellDataSource_resolved WellLocInfo WellLocInfo_resolved ParcelID LocComm Comment Editor EditDate "
                  "AltNames")
CDF = fields("AESI_ProjN AESI_Pro_1 AESI_Pro_2 Phase ExploType ExploName ExploDepth# ExploDate Year# ExploMonYr "
             "Well_Tag_N LocatConf Comments FillDepth# DepthToQvt# DepthToQva# DepthToQvr# DepthToGW# GW_Elev# "
             "ExploElev# Elevation_ Surveyor Document_L Document_D Document_I# DataSource Radiocarbo Editor EditDate "
             "GlobalID CreationDa Creator EditDate_1 Editor_1 Field_1# botqvr# Document_T Document_A layer path")
PK = {"id"}


def names(fl):
    return [n for n, _num in fl]


class Count:
    """Counts a signal's emissions (and keeps their arguments)."""

    def __init__(self, signal):
        self.n = 0
        self.args = []
        signal.connect(self)

    def __call__(self, *args):
        self.n += 1
        self.args.append(args)


def wl_table():
    """A water-level table (no geometry): ExploName, WL_Elev, Date, Kind (Measured / ATD / Drilling)."""
    lyr = QgsVectorLayer("None", "Water levels", "memory")
    T = QMetaType.Type
    lyr.dataProvider().addAttributes([QgsField("ExploName", T.QString), QgsField("WL_Elev", T.Double),
                                      QgsField("Date", T.QString), QgsField("Kind", T.QString)])
    lyr.updateFields()
    feats = []
    for name, z, date, kind in (("B-1", 510.0, "2024-01-02", "Measured"), ("B-1", 512.0, "2020-05-01", "ATD"),
                                ("MW-1", 505.0, "2024-01-02", "Drilling")):
        f = QgsFeature(lyr.fields())
        f.setAttributes([name, z, date, kind])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


# ================================================================ guesses (pure)
class Guesses(unittest.TestCase):
    def test_his_three_layers(self):
        """Section 5: AESI, Other and Supply, never `id`."""
        g, hint = G.guess_point_row(AESI, PK, "Explor_AESI_pt")
        self.assertEqual((g["label_field"], g["type_field"], g["top_field"], g["bottom_elev_field"],
                          g["depth_field"], g["wl_field"], g["wl_values"], g["wl_date_field"], g["atd_field"],
                          g["atd_date_field"], g["screen_top_field"], g["screen_bottom_field"]),
                         ("ExploName", "ExploType_resolved", "ExploElev", "", "ExploDepth", "DepthToGW", "depth",
                          "ExploDate", "", "", "", ""))
        self.assertEqual(hint, "Guessed from the field names (check them): <b>ExploName, ExploType_resolved, "
                               "ExploElev, ExploDepth</b>; water <b>DepthToGW</b> as measured depths dated by "
                               "ExploDate.")          # the mockup's text
        self.assertEqual(tuple(g), G.POINT_FIELD_KEYS)
        g, hint = G.guess_point_row(OTHER, PK, "Explor_Other_pt")
        self.assertEqual((g["label_field"], g["type_field"], g["top_field"], g["depth_field"], g["wl_field"],
                          g["atd_field"], g["wl_date_field"], g["atd_date_field"], g["wl_values"]),
                         ("ExploName", "ExploType_resolved", "ExploElev", "ExploDepth", "", "", "", "", "elevation"))
        self.assertEqual(hint, "Guessed from the field names (check them): <b>ExploName, ExploType_resolved, "
                               "ExploElev, ExploDepth</b>.")
        g, hint = G.guess_point_row(SUPPLY_F, PK, "Well_Supply_pt")
        self.assertEqual((g["label_field"], g["type_field"], g["top_field"], g["depth_field"], g["wl_field"],
                          g["atd_field"], g["wl_values"], g["atd_date_field"], g["wl_date_field"]),
                         ("AESI_MapLabel", "ExploType_resolved", "ExploElev", "WellCompleteDepth", "", "GW_Elev_ATD",
                          "elevation", "ExploDate", ""))
        self.assertEqual(hint, "Guessed from the field names (check them): <b>AESI_MapLabel, ExploType_resolved, "
                               "ExploElev, WellCompleteDepth</b>; water <b>GW_Elev_ATD</b> as ATD elevations.")
        self.assertFalse(G.guess_in_range("Well_Supply_pt", names(SUPPLY_F)))
        self.assertTrue(G.guess_in_range("Explor_AESI_pt", names(AESI)))
        self.assertTrue(G.guess_in_range("Explor_Other_pt", names(OTHER)))
        for fl in (AESI, OTHER, SUPPLY_F):
            g, _h = G.guess_point_row(fl, PK, "x")
            self.assertNotIn("id", g.values())

    def test_cdf_fresh_guess(self):
        """CDF_wells (DepthToGW, GW_Elev and the date ExploDate): depths dated by ExploDate (0.3.2: GW_Elev, no date;
        changed on purpose, spec 11.21)."""
        g, _hint = G.guess_point_row(CDF, set(), "CDF_wells")
        self.assertEqual((g["wl_field"], g["wl_values"], g["wl_date_field"]), ("DepthToGW", "depth", "ExploDate"))
        self.assertEqual((g["label_field"], g["type_field"], g["top_field"], g["bottom_elev_field"],
                          g["depth_field"]), ("ExploName", "ExploType", "ExploElev", "", "ExploDepth"))
        # 0.3.5: as an Other points row, no elevation field (its text Elevation_ holds survey sources: the panel's
        # text_ok, point_rows.number_texts, says it holds no numbers), as 0.3.4 guessed
        self.assertEqual(G.guess_other_row(CDF, set(), "CDF_wells", text_ok=set())["elev_field"], "")

    def test_the_primary_key_is_never_guessed(self):
        fl = [("id", True), ("Code", False), ("Depth", True)]
        g, _h = G.guess_point_row(fl, {"id"}, "x")
        self.assertEqual(g["label_field"], "Code")              # "ID" would match id: not the key, nor names[0]
        g, _h = G.guess_point_row(fl, set(), "x")
        self.assertEqual(g["label_field"], "id")                # (without the key rule it would be)
        g, _h = G.guess_point_row([("id", True)], {"id"}, "x")
        self.assertEqual(g["label_field"], "")
        g, _h = G.guess_point_row(fl, {"id"}, "x", saved=dict(label_field="id"), guess_fields=False)
        self.assertEqual(g["label_field"], "id")                # a saved key field is kept
        t = G.guess_table_fields([("id", True), ("Foo", False), ("Lvl", True)], {"id"})
        self.assertEqual((t["wl_table_name_field"], t["wl_table_elev_field"]), ("Foo", "Lvl"))
        t = G.guess_table_fields([("id", True), ("Foo", False), ("Lvl", True)], {"id"},
                                 saved=dict(wl_table_name_field="id", wl_table_elev_field="id"))
        self.assertEqual((t["wl_table_name_field"], t["wl_table_elev_field"]), ("id", "id"))
        o = G.guess_other_row([("id", True), ("Code", False)], {"id"}, "Seeps")
        self.assertEqual(o["label_field"], "Code")
        self.assertEqual(G.pick_field([("id", True)], {"id"}, "", ["ID"], required=True), ("", False))

    def test_water_rules(self):
        """The ATD level is never of the other kind than the measured one; "Levels are" follows the guess."""
        def water(spec, **kw):
            g, _h = G.guess_point_row(fields(spec), set(), "x", **kw)
            return g["wl_field"], g["atd_field"], g["wl_values"]
        self.assertEqual(water("DTW# ATD_Elev# DTW_ATD#"), ("DTW", "DTW_ATD", "depth"))
        self.assertEqual(water("DTW# ATD_Elev#"), ("DTW", "", "depth"))
        self.assertEqual(water("DTW# ATD#"), ("DTW", "ATD", "depth"))
        self.assertEqual(water("WL_Elev# DTW_ATD# ATD_Elev#"), ("WL_Elev", "ATD_Elev", "elevation"))
        self.assertEqual(water("DepthToGW# GW_Elev#"), ("DepthToGW", "", "depth"))     # depths first
        self.assertEqual(water("GW_Elev_ATD# DepthToGW_ATD#"), ("", "GW_Elev_ATD", "elevation"))
        self.assertEqual(water("DepthToGW_ATD#"), ("", "DepthToGW_ATD", "depth"))
        self.assertEqual(water("ATD#"), ("", "ATD", "elevation"))                      # either kind: unchanged
        self.assertEqual(water("ATD#", saved=dict(wl_values="depth")), ("", "ATD", "depth"))
        self.assertEqual(water("Other#"), ("", "", "elevation"))
        self.assertEqual(water("Other"), ("", "", "elevation"))                        # no name matches
        self.assertEqual(water("DepthToGW"), ("DepthToGW", "", "depth"))   # 0.3.5: a text field, by its name
        self.assertEqual(water("DepthToGW GW_Elev#"), ("GW_Elev", "", "elevation"))    # ... after number fields
        # a saved field: kept, and "Levels are" never changed for it
        self.assertEqual(water("DTW# DTW_ATD# ATD_Elev#", saved=dict(wl_field="DTW", wl_values="elevation")),
                         ("DTW", "ATD_Elev", "elevation"))
        self.assertEqual(water("DTW# ATD_Elev#", saved=dict(atd_field="ATD_Elev", wl_values="depth"),
                               guess_fields=False), ("", "ATD_Elev", "depth"))

    def test_dates_only_with_their_level(self):
        g, _h = G.guess_point_row(fields("Name ExploDate WL_Date ATD_Date"), set(), "x")
        self.assertEqual((g["wl_date_field"], g["atd_date_field"]), ("", ""))
        g, _h = G.guess_point_row(fields("Name DTW# ExploDate"), set(), "x")
        self.assertEqual((g["wl_date_field"], g["atd_date_field"]), ("ExploDate", ""))
        g, _h = G.guess_point_row(fields("Name ATD_Elev# ExploDate"), set(), "x")
        self.assertEqual((g["wl_date_field"], g["atd_date_field"]), ("", "ExploDate"))
        g, _h = G.guess_point_row(fields("Name ExploDate"), set(), "x", saved=dict(wl_date_field="ExploDate"),
                                  guess_fields=False)
        self.assertEqual(g["wl_date_field"], "ExploDate")       # a saved date the layer has is kept

    def test_saved_fields(self):
        """Kept where the layer has them; empty optional ones stay empty unless guess_fields; missing ones guessed."""
        saved = dict(label_field="ExploName", type_field="", top_field="", depth_field="Gone", wl_field="",
                     wl_values="elevation")
        g, hint = G.guess_point_row(OTHER, PK, "x", saved=saved, guess_fields=False)
        self.assertEqual((g["label_field"], g["type_field"], g["top_field"], g["depth_field"]),
                         ("ExploName", "", "", "ExploDepth"))
        self.assertEqual(hint, "Guessed from the field names (check them): <b>ExploDepth</b>.")
        g, _h = G.guess_point_row(OTHER, PK, "x", saved=saved, guess_fields=True)
        self.assertEqual((g["type_field"], g["top_field"]), ("ExploType_resolved", "ExploElev"))
        kept = dict(label_field="ExploName", type_field="ExploType", top_field="ExploElev", depth_field="ExploDepth")
        g, hint = G.guess_point_row(OTHER, PK, "x", saved=kept, guess_fields=False)
        self.assertEqual((g["type_field"], hint), ("ExploType", ""))       # nothing guessed: no hint

    def test_hint_escapes_names(self):
        _g, hint = G.guess_point_row([("Name<b>", False), ("Name", False)], set(), "x")
        self.assertIn("<b>Name</b>", hint)
        _g, hint = G.guess_point_row([("ExploName", False), ("Type", False)], set(), "x")
        self.assertNotIn("<i>", hint)
        self.assertEqual(G._esc("a<b>&"), "a&lt;b&gt;&amp;")

    def test_table_and_other_rows(self):
        t = G.guess_table_fields(fields("id# ExploName WL_Elev# Date Kind"), PK)
        self.assertEqual(t, dict(wl_table_name_field="ExploName", wl_table_elev_field="WL_Elev",
                                 wl_table_date_field="Date", wl_table_kind_field="Kind"))
        t = G.guess_table_fields(fields("id# ExploName WL_Elev# Date Kind"), PK,
                                 saved=dict(wl_table_date_field="", wl_table_kind_field=""), keep_empty=True)
        self.assertEqual((t["wl_table_date_field"], t["wl_table_kind_field"]), ("", ""))
        self.assertEqual(tuple(t), G.TABLE_FIELD_KEYS)
        seeps = fields("Name Type Elev_ft#")
        self.assertEqual(G.guess_other_row(seeps, set(), "Seeps"),
                         dict(label_field="Name", type_field="", elev_field="Elev_ft"))   # the type is not guessed
        self.assertEqual(G.guess_other_row(seeps, set(), "Seeps", saved=dict(type_field="Type", elev_field=""),
                                           guess_fields=False),
                         dict(label_field="Name", type_field="Type", elev_field=""))
        self.assertEqual(G.guess_other_row(seeps, set(), "Seeps", saved=dict(type_field="Gone"))["type_field"], "")
        self.assertEqual(G.guess_other_row(fields("Name Elevation Z#"), set(), "x")["elev_field"], "Z")

    def test_layer_name_hints_and_range(self):
        self.assertFalse(G.guess_in_range("Supply wells", []))
        self.assertFalse(G.guess_in_range("wells", ["well_complete_depth"]))     # normalised
        self.assertTrue(G.guess_in_range("Wells", ["ExploDepth"]))
        self.assertTrue(G.is_point_hint("Explor_AESI_pt") and G.is_point_hint("Well_Supply_pt"))
        self.assertFalse(G.is_point_hint("Seeps"))
        self.assertTrue(G.is_other_hint("Seeps_pt") and G.is_other_hint("SPRINGS"))
        self.assertFalse(G.is_other_hint("Explorations"))

    def test_lists(self):
        """The section 5 lists, and the 0.3.2 ones still in ui.dock until stage C2."""
        self.assertEqual(G.WL_NAMES, G.WL_DEPTH_NAMES + G.WL_ELEV_NAMES)
        self.assertEqual(G.LABEL_NAMES[:2], ["ExploName", "AESI_MapLabel"])
        self.assertEqual(G.TYPE_NAMES[0], "ExploType_resolved")
        self.assertEqual(G.DEPTH_NAMES[:2], ["WellCompleteDepth", "ExploDepth"])
        self.assertEqual(G.OTHER_HINTS, ("seep", "spring"))
        self.assertEqual(G.guess_field(["exploname", "x"], ["ExploName"]), "exploname")
        self.assertEqual(G.guess_field(["botqvr"], G.BOTTOM_ELEV_NAMES), "")       # whole names only


# ================================================================ imports and moved helpers
class Modules(unittest.TestCase):
    def imports(self, name):
        with open(os.path.join(UI, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                out.append("." * node.level + (node.module or ""))
            elif isinstance(node, ast.Import):
                out += [a.name for a in node.names]
        return out

    def test_no_cycle(self):
        """point_rows imports only qgis, core.model, core.symbology (0.3.4), core.explorations (0.3.5: text_number),
        core.others, render.scales, render.symbols, ui.point_guess, ui.widgets and ui.symbol_icons (0.3.6); point_guess
        no Qt; neither imports ui.dock."""
        rows = self.imports("point_rows.py")
        allowed = {"..core.model", "..core.symbology", "..core.explorations", "..core.others", "..render.scales",
                   "..render.symbols", ".", ".widgets", ".symbol_icons", "__future__", "copy", "collections",
                   "functools", "typing"}
        self.assertFalse([m for m in rows if not (m.startswith("qgis.") or m in allowed)], rows)
        self.assertNotIn(".dock", rows)
        guess = self.imports("point_guess.py")
        self.assertFalse([m for m in guess if m.startswith(("qgis", "PyQt", "."))], guess)

    def test_dock_imports_the_moved_names_back(self):
        from xsections.ui import dock as D
        for name in ("_combo", "_segmented", "_narrow", "_spin", "_set_combo_data", "_field_combo",
                     "_numeric_field_combo", "_cbox", "_note", "_esc"):
            self.assertIs(getattr(D, name), getattr(W, name), name)
        self.assertIs(D.guess_field, G.guess_field)
        self.assertIs(D._norm, G._norm)
        self.assertEqual(D._esc("<a&b>"), "&lt;a&amp;b&gt;")

    def test_set_field(self):
        lyr = QgsVectorLayer(f"Point?crs={CRS}", "t", "memory")
        T = QMetaType.Type
        lyr.dataProvider().addAttributes([QgsField("id", T.Int), QgsField("Code", T.QString),
                                          QgsField("Name", T.QString), QgsField("Elev", T.Double)])
        lyr.updateFields()
        c = QgsFieldComboBox()
        c.setLayer(lyr)
        self.assertFalse(W.set_field(c, "Code", ["Name"]))
        self.assertEqual(c.currentField(), "Code")                       # kept
        self.assertTrue(W.set_field(c, "Gone", ["Name"]))
        self.assertEqual(c.currentField(), "Name")                       # guessed
        self.assertFalse(W.set_field(c, "", ["X"]))
        self.assertEqual(c.currentField(), "id")                         # 0.3.2: the first field
        self.assertFalse(W.set_field(c, "", ["X", "ID"], pk={"id"}))
        self.assertEqual(c.currentField(), "Code")                       # never the key
        e = QgsFieldComboBox()
        e.setAllowEmptyFieldName(True)
        e.setLayer(lyr)
        self.assertFalse(W.set_field(e, "", ["Elev"], allow_empty=True, keep_empty=True))
        self.assertEqual(e.currentField(), "")                           # none chosen, kept
        self.assertTrue(W.set_field(e, "", ["Elev"], allow_empty=True))
        self.assertEqual(e.currentField(), "Elev")
        self.assertFalse(W.set_field(e, "Name", [], allow_empty=True, numeric=True))
        self.assertEqual(e.currentField(), "Name")                       # 0.3.5: a number box keeps a text field

    def test_widget_additions(self):
        self.assertEqual(W.ICONS["other"], '<circle cx="3.5" cy="3.5" r="2" fill="currentColor"/><path d="M8 2.5c1.5 '
                                           '1.2 3 1.2 4.5 0" stroke="currentColor" stroke-width="1.3" fill="none"/>'
                                           '<path d="M2 12.5V9.5h10v3" stroke="currentColor" stroke-width="1.3" '
                                           'fill="none"/>')
        d = W.Disclosure("More")
        d.setText("Plotted explorations (1 of 2)")
        self.assertEqual(d.text(), "Plotted explorations (1 of 2)")
        seg = W.SegmentedControl([("Circle", "circle"), ("Square", "square")])
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">{}</svg>'     # (0.3.5's shape icons)
        seg.setItemIcon(0, svg.format('<circle cx="6" cy="6" r="4.2" fill="currentColor"/>'))
        b = seg.buttons()[0]
        self.assertEqual(b.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.assertFalse(b.icon().isNull())
        self.assertEqual(b.accessibleName(), "Circle")
        self.assertEqual(seg.buttons()[1].toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonTextOnly)
        pm = W.svg_pixmap(svg.format('<rect x="2" y="2" width="8" height="8" fill="currentColor"/>'), "#ff0000", 12)
        img = pm.toImage()
        self.assertEqual(img.pixelColor(img.width() // 2, img.height() // 2).name(), "#ff0000")
        box = W.field_box("Within", W._spin(0, 10, 1, 1), note="all layers")
        self.assertEqual(box.note.text(), "all layers")
        sheet = W.panel_stylesheet(W.theme_for(APP.palette()))
        for name in ("xsStyleBox", "xsMoreBody", "xsHint", "xsAdd", "xsCardButton", "xsCardPrimary", "xsSymbolList",
                     "xsStatus"):
            self.assertIn(name, sheet)

    def test_swatches(self):
        def ink(w, color):
            """Pixels inside the chip's border that are not white, once the closest one is the colour."""
            img = w.grab().toImage()
            c = QColor(color)
            px = [img.pixelColor(x, y) for x in range(1, img.width() - 1) for y in range(1, img.height() - 1)]
            near = min(max(abs(p.red() - c.red()), abs(p.green() - c.green()), abs(p.blue() - c.blue())) for p in px)
            self.assertLess(near, 30, color)
            return sum(1 for p in px if max(255 - p.red(), 255 - p.green(), 255 - p.blue()) > 60)
        e = W.ExploSwatch("#b5651d")
        self.assertEqual((e.width(), e.height()), (22, 16))
        self.assertGreater(ink(e, "#b5651d"), 8)
        e.set_color(LOOK_GRAY)
        self.assertEqual(e.color(), LOOK_GRAY)
        s = W.SymbolSwatch("asterisk", "#1f6fb2")
        self.assertGreater(ink(s, "#1f6fb2"), 20)
        areas = {}
        for shape in ("circle", "square", "diamond", "star", "triangle"):
            s.set_symbol(shape, "#1f6fb2")
            areas[shape] = ink(s, "#1f6fb2")
            self.assertGreater(areas[shape], 20, shape)
        self.assertGreater(areas["square"], areas["star"])


# ================================================================ the widgets
class _Layers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prj = QgsProject.instance()
        prj.clear()
        cls.prj = prj
        cls.pts = make_points_layer()
        cls.others = make_others_layer()
        cls.supply = make_supply_layer()
        cls.seeps = make_seeps_layer()
        cls.table = wl_table()
        cls.gpkg = write_gpkg(make_others_layer(), "Explor_Other_pt")
        prj.addMapLayers([cls.pts, cls.others, cls.supply, cls.seeps, cls.table, cls.gpkg])

    def take(self, row_or_rows, layer):
        """Remove `layer` from the project as the dock sees it (rows told before and after); returns it."""
        rows = row_or_rows if isinstance(row_or_rows, (list, tuple)) else [row_or_rows]
        for r in rows:
            r.set_removing(True)
        out = self.prj.takeMapLayer(layer)
        for r in rows:
            r.set_removing(False)
        return out

    def back(self, rows, layer):
        self.prj.addMapLayer(layer)
        for r in (rows if isinstance(rows, (list, tuple)) else [rows]):
            r.sync_layer()


class Explorations(_Layers):
    def full_row(self):
        return point_row(self.supply, visible=False, name="Supply", look="color", in_range=False,
                         label_field="AESI_MapLabel", type_field="ExploType_resolved", types=["PUBLIC SUPPLY", ""],
                         top_field="ExploElev", bottom_elev_field="", depth_field="WellCompleteDepth",
                         screen_top_field="DepthToGW_ATD", screen_bottom_field="", screen_values="elevation",
                         wl_values="depth", wl_field="", wl_date_field="", atd_field="DepthToGW_ATD",
                         atd_date_field="ExploDate", wl_table_id=self.table.id(), wl_table_name_field="ExploName",
                         wl_table_elev_field="WL_Elev", wl_table_date_field="", wl_table_kind_field="Kind",
                         wl_atd_values=["Drilling", "ATD"])

    def test_round_trip_of_every_key(self):
        for d in (self.full_row(),
                  point_row(self.pts, label_field="ExploName", type_field="ExploType", types=["CPT", "Boring"],
                            top_field="ExploElev", depth_field="ExploDepth"),
                  point_row(self.pts, label_field="ExploName", type_field="ExploType", types=[NO_TYPES]),
                  point_row(self.gpkg, label_field="ExploName", type_field="ExploType_resolved", types=[""],
                            look="gray"),
                  point_row(self.pts, label_field="ExploName", wl_table_id=self.table.id(),
                            wl_table_name_field="ExploName", wl_table_elev_field="WL_Elev",
                            wl_table_kind_field="Kind", wl_atd_values=[NO_ATD])):
            row = R.ExplorationRow()
            ch = Count(row.changed)
            row.set_value(copy.deepcopy(d))
            v = row.value()
            self.assertEqual(v, d)
            self.assertEqual(list(v), list(POINT_LAYER_DEFAULTS))
            self.assertEqual(row.stored(), d)
            self.assertEqual(ch.n, 0)
        # an unset row: the defaults
        row = R.ExplorationRow()
        self.assertEqual(row.value(), POINT_LAYER_DEFAULTS)
        self.assertEqual(row.name_label.text(), "(choose a point layer)")
        self.assertFalse(row.is_missing())

    def test_fresh_guess_and_hint(self):
        row = R.ExplorationRow()
        row.set_value(dict(layer_id=self.supply.id(), in_range=False), guess_fields=True)
        v = row.value()
        self.assertEqual((v["label_field"], v["type_field"], v["top_field"], v["depth_field"], v["atd_field"],
                          v["atd_date_field"], v["wl_values"], v["in_range"]),
                         ("AESI_MapLabel", "ExploType_resolved", "ExploElev", "WellCompleteDepth", "GW_Elev_ATD",
                          "ExploDate", "elevation", False))
        self.assertEqual(row.stored(), v)
        row.set_editor_open(True)                          # (0.3.6: the guess's hint is over the open row's tabs)
        self.assertTrue(row.guess_hint.wanted())
        self.assertEqual(row.guess_hint.text(), "Guessed from the field names (check them): <b>AESI_MapLabel, "
                                                "ExploType_resolved, ExploElev, WellCompleteDepth</b>; water "
                                                "<b>GW_Elev_ATD</b> as ATD elevations.")
        row.set_value(dict(layer_id=self.others.id()), guess_fields=True)
        self.assertEqual(row.water_hint.text(), "This layer has no water-level or screen fields, so none are drawn "
                                                "for it.")
        self.assertTrue(row.water_hint.wanted())
        row.set_value(point_row(self.supply, label_field="AESI_MapLabel", atd_field="GW_Elev_ATD"))
        self.assertFalse(row.guess_hint.wanted())                         # nothing guessed now
        # the GeoPackage layer: never its fid column `id`
        row.set_value(dict(layer_id=self.gpkg.id()), guess_fields=True)
        self.assertEqual([self.gpkg.fields().at(i).name() for i in self.gpkg.primaryKeyAttributes()], ["id"])
        v = row.value()
        self.assertEqual((v["label_field"], v["type_field"]), ("ExploName", "ExploType_resolved"))
        self.assertNotIn("id", [v[k] for k in G.POINT_FIELD_KEYS])

    def test_look_and_swatch(self):
        W.set_verbose(True)                                # (0.3.6: the look hint is a Verbose hint)
        self.addCleanup(W.set_verbose, False)
        self.addCleanup(self.supply.setRenderer, self.supply.renderer().clone())
        self.supply.setRenderer(single_renderer("#00ff00"))
        row = R.ExplorationRow(point_row(self.supply, label_field="AESI_MapLabel"))
        ch = Count(row.changed)
        self.assertNotIn("color_btn", vars(row))                            # (0.3.4: no colour picker)
        self.assertTrue(row.style_box.isHidden())
        self.assertFalse(row.look_hint.isHidden())
        self.assertEqual(row.swatch.color(), "#111111")
        row.look_seg.setCurrentIndex(row.look_seg.findData("color"))        # as a click does
        self.assertFalse(row.style_box.isHidden())
        self.assertTrue(row.look_hint.isHidden())
        self.assertEqual(row.value()["look"], "color")
        self.assertNotIn("color", row.value())
        self.assertEqual(row.swatch.colors(), ["#00ff00"])                   # the layer's single symbol
        self.assertEqual(row.sub_label.text(), "AESI_MapLabel · all points · color")
        row.look_seg.setCurrentIndex(row.look_seg.findData("gray"))
        self.assertTrue(row.style_box.isHidden())
        self.assertFalse(row.look_hint.isHidden())
        self.assertEqual(row.swatch.color(), LOOK_GRAY)
        self.assertEqual(row.sub_label.text(), "AESI_MapLabel · all points · gray")
        self.assertEqual(ch.n, 2)
        row.look_seg.setCurrentIndex(row.look_seg.findData("black"))
        self.assertEqual(row.swatch.colors(), ["#111111"])
        self.assertEqual(ch.n, 3)
        self.assertEqual(row.stored()["look"], "black")

    def test_labels(self):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName", type_field="ExploType",
                                         types=["Boring", "CPT"]))
        self.assertEqual(row.name_label.text(), "Explorations")
        self.assertEqual(row.sub_label.text(), "ExploName · 2 of 4 types · black")
        row.set_counts(Counter({"Boring": 3, "CPT": 1}), left_off=1)
        self.assertEqual(row.sub_label.text(), "ExploName · 2 of 4 types · black")     # (0.3.6: no counts)
        self.assertEqual(row.type_list.item_for("Boring").text(1), "3 / 6")
        self.assertEqual(row.type_list.item_for("Test Pit").text(1), "0 / 1")
        row.set_counts(None)
        self.assertEqual(row.type_list.item_for("Boring").text(1), "6")
        row.name_edit.setText("Ours")
        self.assertEqual(row.name_label.text(), "Ours")
        self.assertEqual(row.name_edit.placeholderText(), "Explorations")
        row.visible_box.setChecked(False)
        self.assertEqual(row.sub_label.text(), "ExploName · 2 of 4 types · black")     # (0.3.6: the tick says it)
        row.type_field.setField("")
        self.assertEqual(row.sub_label.text(), "ExploName · all points · black")
        self.assertTrue(row.type_list.isEnabled() is False and row.btn_types_all.isEnabled() is False)
        self.assertEqual(row.value()["types"], [])

    def test_user_layer_change(self):
        """Fields kept where the new layer has them, else guessed; types all ticked; in_range re-guessed; the legend
        name kept; layerSwapped tells the dock the old and new ids."""
        row = R.ExplorationRow(point_row(self.pts, name="Mine", label_field="ExploName", type_field="ExploType",
                                         types=["Boring"], top_field="ExploElev", depth_field="ExploDepth"))
        ch, sw = Count(row.changed), Count(row.layerSwapped)
        row.layer_combo.setLayer(self.supply)
        v = row.value()
        self.assertEqual((v["layer_id"], v["name"], v["label_field"], v["type_field"], v["types"], v["top_field"],
                          v["depth_field"], v["in_range"]),
                         (self.supply.id(), "Mine", "AESI_MapLabel", "ExploType_resolved", [], "ExploElev",
                          "ExploDepth", False))
        self.assertEqual((ch.n, sw.args), (1, [(self.pts.id(), self.supply.id(), "Explorations")]))
        self.assertTrue(row.guess_hint.text().startswith("Guessed from the field names"))
        self.assertEqual(row.stored(), v)
        row.layer_combo.setLayer(self.others)
        self.assertTrue(row.value()["in_range"])
        row.layer_combo.setLayer(None)                     # the user chose none: a row without a layer
        self.assertEqual((row.value()["layer_id"], row.name_label.text()), ("", "Mine"))
        self.assertFalse(row.is_missing())
        self.assertEqual(ch.n, 3)

    def test_table_boxes(self):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        row.set_shared(True, "field_then_dem", True)
        ch = Count(row.changed)
        self.assertTrue(row.table_box.isHidden())
        row.wl_table.setLayer(self.table)
        self.assertFalse(row.table_box.isHidden())
        v = row.value()
        self.assertEqual((v["wl_table_id"], v["wl_table_name_field"], v["wl_table_elev_field"],
                          v["wl_table_date_field"], v["wl_table_kind_field"], v["wl_atd_values"]),
                         (self.table.id(), "ExploName", "WL_Elev", "Date", "Kind", []))
        checked = [row.wl_atd_values.itemText(i) for i in range(row.wl_atd_values.count())
                   if row.wl_atd_values.itemCheckState(i) == Qt.CheckState.Checked]
        self.assertEqual(checked, ["ATD"])                                  # automatic: the values with ATD
        self.assertTrue(row.wl_atd_values.isEnabled())
        self.assertEqual(ch.n, 1)
        i = row.wl_atd_values.findText("Drilling")
        row.wl_atd_values.setItemCheckState(i, Qt.CheckState.Checked)
        self.assertEqual(sorted(row.value()["wl_atd_values"]), ["ATD", "Drilling"])
        self.assertEqual(ch.n, 2)
        row.wl_table_kind_field.setField("")
        self.assertFalse(row.wl_atd_values.isEnabled())
        self.assertEqual(row.value()["wl_atd_values"], [])
        row.wl_table.setLayer(None)
        self.assertTrue(row.table_box.isHidden())
        v = row.value()
        self.assertEqual((v["wl_table_id"], v["wl_table_name_field"], v["wl_atd_values"]), ("", "", []))
        self.assertEqual(row.uses_layer_ids(), {self.pts.id()})
        row.wl_table.setLayer(self.table)
        self.assertEqual(row.uses_layer_ids(), {self.pts.id(), self.table.id()})

    def test_shared_enabling(self):
        W.set_verbose(True)                                # (0.3.6: the range hint is a Verbose hint)
        self.addCleanup(W.set_verbose, False)
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName", depth_field="ExploDepth"))
        row.set_shared(False, "dem", False)
        for w in (row.bottom_elev_field, row.depth_field, row.top_field, row.screen_top_field, row.wl_field,
                  row.atd_field, row.wl_values, row.screen_values, row.wl_table, row.wl_date_field):
            self.assertFalse(w.isEnabled(), w)
        row.set_shared(True, "dem", True)
        self.assertTrue(row.depth_field.isEnabled() and row.wl_field.isEnabled())
        self.assertFalse(row.top_field.isEnabled())                         # tops from LIDAR
        self.assertFalse(row.wl_date_field.isEnabled())                     # a date only with its level
        row.set_shared(True, "field", True)
        self.assertTrue(row.top_field.isEnabled())
        row.wl_field.setField("ExploElev")
        self.assertTrue(row.wl_date_field.isEnabled())
        self.assertFalse(row.has_bottom_and_depth())
        row.bottom_elev_field.setField("ExploElev")
        self.assertTrue(row.has_bottom_and_depth())
        self.assertTrue(row.range_hint.isHidden())
        row.in_range_box.setChecked(False)
        self.assertFalse(row.range_hint.isHidden())
        self.assertEqual(row.range_hint.text(), "Deeper ones stop at the frame with an arrow and their TD.")

    def test_layer_removed_keeps_every_key(self):
        """The row's layer leaves the project: amber, its stored keys written back with only the header applied;
        back again (the same id), the boxes show it."""
        d = self.full_row()
        row = R.ExplorationRow(copy.deepcopy(d))
        ch = Count(row.changed)
        self.assertEqual(row.last_layer_name(), "Supply wells")
        lyr = self.take(row, self.supply)
        try:
            self.assertTrue(row.is_missing())
            self.assertTrue(row.name_label.isWarn())
            self.assertEqual(row.sub_label.text(), "layer not in the project · color")
            self.assertEqual(row.value(), d)
            self.assertEqual(row.uses_layer_ids(), {self.supply.id(), self.table.id()})
            row.name_edit.setText("Wells")
            row.visible_box.setChecked(True)
            row.look_seg.setCurrentIndex(row.look_seg.findData("gray"))
            row.in_range_box.setChecked(True)
            self.assertEqual(ch.n, 4)
            want = dict(d, name="Wells", visible=True, look="gray", in_range=True)
            self.assertEqual(row.value(), want)
            row.type_list.check_all(False)               # boxes of a missing layer write nothing
            row.wl_values.setCurrentIndex(0)
            self.assertEqual(row.value(), want)
            self.assertEqual(row.name_label.text(), "Wells")
            row.sync_layer()
            self.assertEqual(row.value(), want)
        finally:
            self.back(row, lyr)
        self.assertFalse(row.is_missing())
        self.assertEqual(row.label_field.currentField(), "AESI_MapLabel")
        self.assertEqual(row.depth_field.currentField(), "WellCompleteDepth")
        self.assertEqual(row.type_list.checked_types(), ["PUBLIC SUPPLY", ""])
        self.assertEqual(row.value(), want)
        self.assertEqual(ch.n, 4)

    def test_own_layer_picked_again(self):
        """A missing row's own layer back (the same id) and picked in its box: what it stored, no user edit."""
        d = point_row(self.pts, label_field="ExploName", type_field="ExploType", types=["CPT"], top_field="ExploElev")
        row = R.ExplorationRow(copy.deepcopy(d))
        ch = Count(row.changed)
        lyr = self.take(row, self.pts)
        self.prj.addMapLayer(lyr)                          # back, but the row not told yet
        self.assertEqual(row.value(), d)
        row.layer_combo.setLayer(lyr)
        self.assertEqual((row.value(), ch.n), (d, 0))
        self.assertEqual(row.label_field.currentField(), "ExploName")

    def test_reload_values(self):
        """Refresh reads the type values again, keeping the ticks (a new value: ticked only when all were)."""
        lyr = make_points_layer(name="Copy")
        self.prj.addMapLayer(lyr)
        try:
            some = R.ExplorationRow(point_row(lyr, label_field="ExploName", type_field="ExploType", types=["CPT"]))
            every = R.ExplorationRow(point_row(lyr, label_field="ExploName", type_field="ExploType"))
            ch = Count(some.changed)
            f = QgsFeature(lyr.fields())
            f.setAttributes(["V-1", "Vibracore", 10.0, None])
            lyr.dataProvider().addFeatures([f])
            some.reload_values()
            every.reload_values()
            self.assertIn("Vibracore", [v for v, _on in some.type_list.values()])
            self.assertEqual(some.value()["types"], ["CPT"])
            self.assertEqual(every.value()["types"], [])
            self.assertEqual(dict(every.type_list.values())["Vibracore"], True)
            self.assertEqual(ch.n, 0)
        finally:
            for r in (some, every):
                r.set_removing(True)
            self.prj.removeMapLayer(lyr.id())

    def test_table_removed_keeps_its_keys(self):
        d = self.full_row()
        row = R.ExplorationRow(copy.deepcopy(d))
        tbl = self.take(row, self.table)
        try:
            self.assertIsNone(row.wl_table.currentLayer())                  # the box shows none
            self.assertTrue(row.table_box.isHidden())
            self.assertEqual(row.value(), d)
            row.name_edit.setText("X")
            row.top_field.setField("")                                      # the layer is there: recorded
            self.assertEqual(row.value(), dict(d, name="X", top_field=""))
        finally:
            self.back(row, tbl)
        self.assertIs(row.wl_table.currentLayer(), self.table)
        self.assertEqual(row.wl_table_kind_field.currentField(), "Kind")
        self.assertEqual(row.value(), dict(d, name="X", top_field=""))

    def test_take_layer_and_combo_moves(self):
        """A layer added again (a new id, same name) taken back with every key; the layer box moving by itself while
        layers are removed is no choice."""
        d = point_row(self.pts, label_field="ExploName", type_field="ExploType", types=["Boring"],
                      top_field="ExploElev")
        row = R.ExplorationRow(copy.deepcopy(d))
        ch = Count(row.changed)
        lyr = self.take(row, self.pts)
        try:
            self.assertIsNone(row.layer_combo.currentLayer())
            again = make_points_layer()
            self.prj.addMapLayer(again)
            row.sync_layer()
            self.assertTrue(row.is_missing())                               # another id: still missing
            self.assertEqual(row.last_layer_name(), again.name())
            row.take_layer(again)
            self.assertEqual(row.value(), dict(d, layer_id=again.id()))
            self.assertEqual(ch.n, 0)
            self.take(row, again)
        finally:
            self.back([], lyr)

    def test_silent_filling(self):
        row = R.ExplorationRow()
        ch, tl = Count(row.changed), Count(row.type_list.changed)
        row.set_value(point_row(self.pts, label_field="ExploName", type_field="ExploType"))
        row.type_list.fill(self.pts, "ExploType", ["Boring"])
        row.type_list.set_plotted(Counter({"Boring": 2}))
        row.type_list.check_all(True)
        row.set_counts(Counter({"Boring": 2}), 1)
        row.set_counts(None)
        row.reload_values()
        row.sync_layer()
        row.set_shared(True, "dem", True)
        row.set_end_labels("B", "B′")
        row.set_value(self.full_row(), guess_fields=True)
        row.set_value(point_row(self.pts, label_field="ExploName", type_field="ExploType"))
        self.assertEqual((ch.n, tl.n), (0, 0))
        it = row.type_list.item_for("CPT")
        it.setCheckState(0, Qt.CheckState.Unchecked)                         # a user's tick
        self.assertEqual((ch.n, tl.n), (1, 1))
        self.assertEqual(row.value()["types"], ["Boring", "Monitoring Well", "Test Pit"])
        it.setCheckState(0, Qt.CheckState.Unchecked)                         # no change: nothing
        it.setText(1, "x")                                                   # not a tick
        self.assertEqual((ch.n, tl.n), (1, 1))
        row.btn_types_none.click()
        self.assertEqual(row.value()["types"], [NO_TYPES])
        row.btn_types_none.click()                                           # already none: no change
        row.btn_types_all.click()
        self.assertEqual(row.value()["types"], [])
        self.assertEqual(ch.n, 3)
        pl = R.PlottedList()
        tg = Count(pl.toggled)
        pl.set_entries([("Explorations", [(self.pts.id(), 1, "B-1", "300 ft · 40 ft L", True)])])
        pl.set_entries([("Explorations", [(self.pts.id(), 1, "B-1", "300 ft · 40 ft L", False)])])
        self.assertEqual(tg.n, 0)
        pl.item_for(self.pts.id(), 1).setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(tg.args, [(self.pts.id(), 1, True)])


class TypeLists(_Layers):
    def test_values_counts_and_no_value(self):
        tl = R.TypeList()
        tl.fill(self.others, "ExploType_resolved", [])
        self.assertEqual([v for v, _on in tl.values()], ["Boring", "Monitoring Well", ""])
        n = Counter(t or "" for _n, t, *_rest in OTHERS)
        self.assertEqual(tl.totals, Counter({"Boring": n["Boring"], "Monitoring Well": 1, "": 2}))
        last = tl.topLevelItem(tl.topLevelItemCount() - 1)
        self.assertEqual(last.text(0), "(no value)")
        self.assertTrue(last.font(0).italic())
        self.assertEqual(tl.topLevelItem(0).text(1), str(n["Boring"]))
        tl.set_plotted(Counter({"Boring": 2, "": 1}))
        self.assertEqual([tl.topLevelItem(i).text(1) for i in range(3)], [f"2 / {n['Boring']}", "0 / 1", "1 / 2"])
        self.assertEqual(tl.topLevelItem(0).textAlignment(1) & int(Qt.AlignmentFlag.AlignRight),
                         int(Qt.AlignmentFlag.AlignRight))
        self.assertEqual(tl.checked_types(), [])
        tl.fill(self.others, "ExploType_resolved", [NO_TYPES])
        self.assertEqual(tl.checked_types(), [NO_TYPES])
        self.assertEqual(tl.topLevelItem(0).text(1), f"2 / {n['Boring']}")       # the counts stay with a model
        tl.fill(self.others, "ExploType_resolved", [""])
        self.assertEqual([on for _v, on in tl.values()], [False, False, True])
        self.assertEqual(tl.checked_types(), [""])
        tl.fill(self.others, "ExploType_resolved", ["Monitoring Well", "Boring"])
        self.assertEqual(tl.checked_types(), ["Monitoring Well", "Boring"])      # in the order given
        tl.item_for("Monitoring Well").setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(tl.checked_types(), ["Boring"])
        tl.check_all(True)
        self.assertEqual(tl.checked_types(), [])
        # a layer without NULL types has no "(no value)" row; a type field of numbers
        tl.fill(self.pts, "ExploType", [])
        self.assertNotIn("", [v for v, _on in tl.values()])
        tl.fill(self.pts, "ExploDepth", [])
        self.assertIn("30.0", [v for v, _on in tl.values()])
        tl.fill(None, "", ["Boring"])
        self.assertEqual((tl.topLevelItemCount(), tl.checked_types()), (0, []))
        # the GeoPackage copy counts the same
        tl.fill(self.gpkg, "ExploType_resolved", [])
        self.assertEqual(tl.totals, Counter({"Boring": n["Boring"], "Monitoring Well": 1, "": 2}))
        tl.fill(self.supply, "ExploType_resolved", [])
        self.assertIn("SPRING WELL , GRP A/B/DOM", [v for v, _on in tl.values()])
        self.assertEqual(tl.totals[""], sum(1 for row in SUPPLY if not row[1]))

    @timing_test
    def test_fit_and_budget(self):
        tl = R.TypeList()
        dense = make_dense_layer()
        t0 = time.perf_counter()
        tl.fill(dense, "ExploType_resolved", [])
        dt = time.perf_counter() - t0
        self.assertLessEqual(dt, budget(0.75), f"TypeList.fill of {dense.featureCount()} points: {dt:.3f} s")
        self.assertEqual(tl.topLevelItemCount(), 13)                       # 12 types and (no value)
        self.assertEqual(sum(tl.totals.values()), dense.featureCount())
        h6 = tl.height()
        tl.fill(self.pts, "ExploType", [])
        self.assertLess(tl.height(), h6)


class Plotted(_Layers):
    def entries(self, n_off=1):
        a = [(self.pts.id(), 1, "B-1", "300 ft · 40 ft L", True), (self.pts.id(), 4, "B-2", "2,200 ft · 120 ft R",
                                                                  n_off == 0)]
        b = [(self.others.id(), 1, "B-2x", "2,200 ft · 119.4 ft R", True)]
        return [("Explorations", a), ("Explorations by others", b)]

    def test_title_groups_and_ticks(self):
        pl = R.PlottedList()
        self.assertEqual(pl.text(), "Plotted explorations")
        self.assertFalse(pl.empty_label.isHidden())
        self.assertTrue(pl.tree.isHidden())
        self.assertIsNone(pl.counts())
        pl.set_entries(self.entries())
        self.assertEqual(pl.text(), "Plotted explorations (2 of 3, 1 left off by you)")
        self.assertEqual(pl.counts(), (2, 3, 1))
        self.assertTrue(pl.empty_label.isHidden())
        top = [pl.tree.topLevelItem(i) for i in range(pl.tree.topLevelItemCount())]
        self.assertEqual([t.text(0) for t in top], ["EXPLORATIONS", "B-1", "B-2", "EXPLORATIONS BY OTHERS", "B-2x"])
        self.assertFalse(top[0].flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertTrue(top[0].font(0).bold())
        self.assertTrue(top[2].font(0).strikeOut())                         # left off: struck through
        self.assertFalse(top[1].font(0).strikeOut())
        self.assertEqual(top[2].checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(top[1].text(1), "300 ft · 40 ft L")
        self.assertEqual(pl.items()[2], (self.others.id(), 1, "B-2x", "2,200 ft · 119.4 ft R", True))
        pl.set_entries(self.entries(n_off=0))
        self.assertEqual(pl.text(), "Plotted explorations (3 of 3)")
        tg, sa = Count(pl.toggled), Count(pl.showAllRequested)
        pl.item_for(self.others.id(), 1).setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(tg.args, [(self.others.id(), 1, False)])
        self.assertEqual(pl.text(), "Plotted explorations (2 of 3, 1 left off by you)")
        self.assertTrue(pl.item_for(self.others.id(), 1).font(0).strikeOut())
        pl.btn_show_all.click()
        self.assertEqual(sa.n, 1)
        self.assertEqual(pl.btn_show_all.toolTip(), "Plot every exploration you left off on this section")
        self.assertEqual(pl.hint.text(), "Untick one to leave it off this section only.")
        pl.set_entries([])
        self.assertEqual(pl.text(), "Plotted explorations (0 of 0)")
        self.assertFalse(pl.empty_label.isHidden())
        self.assertEqual(pl.empty_label.text(), "Nothing chosen yet.")
        pl.set_entries(None)
        self.assertEqual(pl.text(), "Plotted explorations")
        self.assertEqual(tg.n, 1)
        self.assertLessEqual(pl.tree.maximumHeight(), 210)

    @timing_test
    def test_budget(self):
        pl = R.PlottedList()
        groups = [(f"Layer {g}", [(f"layer{g}", i, f"X-{i:04d}", f"{i * 10:,} ft · {i % 150} ft L", i % 7 != 0)
                                  for i in range(250)]) for g in range(4)]
        t0 = time.perf_counter()
        pl.set_entries(groups)
        dt = time.perf_counter() - t0
        self.assertLessEqual(dt, budget(0.3), f"PlottedList.set_entries of 1,000 entries: {dt:.3f} s")
        self.assertEqual(len(pl.items()), 1000)
        self.assertEqual(pl.tree.height(), R.PLOTTED_MAX_H)


class RowLists(_Layers):
    def test_append_move_remove(self):
        lst = R.PointRowList(R.ExplorationRow)
        ch, rc, em = Count(lst.changed), Count(lst.rowsChanged), Count(lst.emptied)
        rows = [point_row(self.pts, label_field="ExploName"), point_row(self.others, label_field="ExploName")]
        lst.set_rows(rows)
        self.assertEqual((len(lst.rows), ch.n, rc.n), (2, 0, 1))
        self.assertEqual(lst.values(), rows)
        r3 = lst.append(dict(layer_id=self.supply.id()), open_editor=True, guess=True)
        self.assertEqual((ch.n, rc.n), (0, 2))
        self.assertTrue(r3.editor_open())
        self.assertEqual(r3.value()["label_field"], "AESI_MapLabel")        # guessed
        self.assertEqual(lst.uses_layer_ids(), {self.pts.id(), self.others.id(), self.supply.id()})
        a, b, c = lst.rows
        self.assertEqual([(r.act_up.isEnabled(), r.act_down.isEnabled()) for r in (a, b, c)],
                         [(False, True), (True, True), (True, False)])
        self.assertEqual([r.property("first") for r in (a, b, c)], [True, False, False])
        lst.move(c, -1)
        self.assertEqual(lst.rows, [a, c, b])
        self.assertEqual((ch.n, rc.n), (1, 3))
        a.act_down.trigger()                                                # the ⋯ menu
        self.assertEqual(lst.rows, [c, a, b])
        self.assertEqual([r.property("first") for r in lst.rows], [True, False, False])
        lst.move(c, -1)                                                     # already first: nothing
        self.assertEqual(ch.n, 2)
        b.name_edit.setText("B")                                            # a row's edit
        self.assertEqual(ch.n, 3)
        b.act_remove.trigger()
        self.assertEqual((lst.rows, ch.n, em.n), ([c, a], 4, 0))
        lst.remove(c)
        lst.remove(a)
        self.assertEqual((lst.rows, ch.n, em.n), ([], 6, 1))
        lst.set_rows(rows)
        lst.set_rows([])                                                    # not the user: not emptied
        self.assertEqual((em.n, ch.n), (1, 6))
        self.assertTrue(lst.isHidden())

    def test_other_rows_list(self):
        lst = R.PointRowList(R.OtherPointsRow)
        lst.set_rows([seep_row(self.seeps, label_field="Name")])
        self.assertIsInstance(lst.rows[0], R.OtherPointsRow)
        self.assertEqual(lst.values(), [seep_row(self.seeps, label_field="Name")])


class OtherPoints(_Layers):
    def test_round_trip_and_guess(self):
        d = seep_row(self.seeps, visible=False, name="Seeps!", label_field="Name", type_field="Type",
                     types=["Seep"], shape="star", color="#00aa00", size=9.5, elev="field", elev_field="Elev_ft",
                     elev_empty="off")
        row = R.OtherPointsRow()
        ch = Count(row.changed)
        row.set_value(copy.deepcopy(d))
        self.assertEqual(row.value(), d)
        self.assertEqual(list(row.value()), list(OTHER_POINT_DEFAULTS))
        row.set_value(dict(d, size=7.25))
        self.assertEqual(row.value()["size"], 7.25)                       # kept as stored
        self.assertEqual(ch.n, 0)
        row.set_value(dict(layer_id=self.seeps.id()), guess_fields=True)
        v = row.value()
        self.assertEqual((v["label_field"], v["type_field"], v["elev_field"], v["shape"], v["color"], v["size"],
                          v["elev"], v["elev_empty"]), ("Name", "", "Elev_ft", "asterisk", "#1f6fb2", 7.0, "line",
                                                        "line"))
        self.assertTrue(row.types_box.isHidden())
        self.assertEqual(row.type_field.emptyText(), "(none: every feature)")
        self.assertTrue(row.type_field.allowEmptyFieldName())
        self.assertEqual(row.swatch.shape(), "asterisk")
        self.assertEqual(row.uses_layer_ids(), {self.seeps.id()})

    def test_editor(self):
        row = R.OtherPointsRow(seep_row(self.seeps, name="Seeps", label_field="Name", elev_field="Elev_ft"))
        ch = Count(row.changed)
        c = row.symbol_combo                               # (0.3.6: the drop-down replaces the six shape buttons)
        symbols = [i for i in range(c.count()) if c.itemData(i)]
        self.assertEqual([c.itemData(i) for i in symbols], list(CHOICE_KEYS))
        self.assertTrue(all(c.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in symbols))
        self.assertTrue(all(not c.itemIcon(i).isNull() for i in symbols))
        self.assertEqual([row.elev_seg.itemText(i) for i in range(3)], ["Ground line", "LIDAR", "Field"])
        self.assertEqual([b.toolTip() for b in row.empty_seg.buttons()],
                         ["On the ground line", "LIDAR at the point", "Leave the point off"])
        self.assertEqual((row.size_spin.minimum(), row.size_spin.maximum(), row.size_spin.singleStep(),
                          row.size_spin.suffix()), (3.0, 20.0, 0.5, " pt"))
        self.assertTrue(row.elev_field_row.isHidden())
        self.assertEqual(row.sub_label.text(), "points · Name · ground line")
        self.assertEqual(row.elev_hint.text(), "Each point sits on the ground line drawn along A–A′, just touching "
                                               "it. Choose LIDAR or a field to show its own elevation.")
        row.set_end_labels("B", "B′")
        self.assertIn("drawn along B–B′,", row.elev_hint.text())
        row.elev_seg.setCurrentIndex(1)
        self.assertTrue(row.elev_field_row.isHidden())
        self.assertEqual(row.elev_hint.text(), "The LIDAR at each point's own location, which can differ from the "
                                               "ground line drawn along B–B′. The centre of the symbol marks the "
                                               "elevation.")
        self.assertEqual(row.sub_label.text(), "points · Name · LIDAR")
        row.elev_seg.setCurrentIndex(2)
        self.assertFalse(row.elev_field_row.isHidden())
        for i, (then, how) in enumerate((("sits on the ground line", "Elev_ft, else on the ground line"),
                                         ("uses the LIDAR at the point", "Elev_ft, else LIDAR"),
                                         ("is left out", "Elev_ft only"))):
            row.empty_seg.setCurrentIndex(i)
            self.assertEqual(row.elev_hint.text(), "The centre of the symbol marks the elevation. Where Elev_ft is "
                                                   f"empty, the point {then}.")
            self.assertEqual(row.how_text(), how)
            self.assertEqual(row.sub_label.text(), "points · Name · Elev_ft")
        row.set_counts(Counter({"": 2}))
        self.assertEqual(row.sub_label.text(), "points · Name · Elev_ft")       # (0.3.6: no counts)
        i = c.findData("circle")
        c.setCurrentIndex(i)
        c.activated.emit(i)                                                    # his pick
        row.color_btn.setColor(QColor("#aa0000"))
        self.assertEqual((row.swatch.shape(), row.swatch.color()), ("circle", "#aa0000"))
        row.type_field.setField("Type")
        self.assertFalse(row.types_box.isHidden())
        self.assertEqual(row.type_list.checked_types(), [])
        v = row.value()
        self.assertEqual((v["elev"], v["elev_empty"], v["shape"], v["color"], v["type_field"]),
                         ("field", "off", "circle", "#aa0000", "Type"))
        self.assertEqual(ch.n, 7)

    def test_layer_removed(self):
        d = seep_row(self.seeps, name="", label_field="Name", type_field="Type", types=["Spring"], elev="field",
                     elev_field="Elev_ft")
        row = R.OtherPointsRow(copy.deepcopy(d))
        lyr = self.take(row, self.seeps)
        try:
            self.assertTrue(row.is_missing() and row.name_label.isWarn())
            self.assertEqual(row.name_label.text(), "Seeps")                  # the name it had
            row.size_spin.setValue(10.0)
            row.elev_seg.setCurrentIndex(0)
            self.assertEqual(row.value(), dict(d, size=10.0, elev="line"))
        finally:
            self.back(row, lyr)
        self.assertEqual(row.value(), dict(d, size=10.0, elev="line"))
        self.assertEqual(row.label_field.currentField(), "Name")



# ================================================================ Drawn in: Color, the layer's style (0.3.4)
class StyleBox(_Layers):
    """A Color row's style box: the kind of style, up to four chips (the plotted ones first), "+ N more", the items
    switched off in QGIS, the foot; the header swatch; the Black / Gray hint."""

    HEAD = "From the layer's style in QGIS: "

    def setUp(self):
        W.set_verbose(True)                                # (0.3.6: the foot and the look hint are Verbose hints)
        self.addCleanup(W.set_verbose, False)

    def styled(self, renderer, layer=None):
        """`layer` (default: the fixtures' explorations) drawn with `renderer` for this test."""
        lyr = layer or self.pts
        self.addCleanup(lyr.setRenderer, lyr.renderer().clone())
        lyr.setRenderer(renderer)
        return lyr

    def color_row(self, layer=None):
        return R.ExplorationRow(point_row(layer or self.pts, label_field="ExploName", type_field="ExploType",
                                          look="color"))

    def box(self, row):
        b = row.style_box
        return b.head.text(), b.chips.items(), b.chips.more(), b.off_note.text(), b.foot.isHidden()

    def test_single_symbol(self):
        self.styled(single_renderer("#987db7"))
        row = self.color_row()
        self.assertEqual(self.box(row), (self.HEAD + "<b>Single symbol</b>", [("every exploration", "#987db7")], 0,
                                         "", True))
        self.assertTrue(row.style_box.off_note.isHidden())
        self.assertFalse(row.style_box.isHidden())
        self.assertEqual(row.swatch.colors(), ["#987db7"])
        self.assertEqual(row.look_color(), "#987db7")
        # a white marker with a coloured outline: its outline
        self.styled(single_renderer("#ffffff", outline="#c2185b"))
        row.refresh_style()
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#c2185b")])
        self.assertEqual(row.swatch.colors(), ["#c2185b"])

    def test_categorized(self):
        lyr = self.styled(categorized_renderer("ExploType", CUMBERLAND_AESI))
        row = self.color_row()
        head, chips, more, off, foot_hidden = self.box(row)
        self.assertEqual(head, self.HEAD + "<b>Categorized by ExploType</b> · 13 categories")
        self.assertEqual(chips, [(lab, c) for _v, lab, c in CUMBERLAND_AESI[:4]])          # legend order
        self.assertEqual((more, off, foot_hidden), (9, "", False))
        self.assertEqual(row.style_box.chips.more_text(), "+ 9 more")
        self.assertEqual(row.style_box.foot.text(), "Change them in Layer Properties &gt; Symbology; the sheet "
                                                    "follows.")
        self.assertEqual(row.swatch.colors(), [c for _v, _l, c in CUMBERLAND_AESI[:3]])
        st = row.current_style()
        self.assertEqual((st.kind, st.field, len(st.items), st.items[-1].label), ("categorized", "ExploType", 13,
                                                                                  "(no value)"))
        # the plotted categories first (legend order), then the rest
        row.set_plotted_styles({st.items[7].key, st.items[5].key})
        self.assertEqual([lab for lab, _c in row.style_box.chips.items()],
                         [CUMBERLAND_AESI[i][1] for i in (5, 7, 0, 1)])
        self.assertEqual(row.style_box.chips.more(), 9)
        self.assertEqual(row.swatch.colors(), [CUMBERLAND_AESI[i][2] for i in (5, 7, 0)])
        row.set_plotted_styles(None)
        self.assertEqual(row.style_box.chips.items()[0][0], CUMBERLAND_AESI[0][1])
        # a category switched off in the Layers panel: one muted line, not a chip
        lyr.renderer().checkLegendSymbolItem(st.items[0].key, False)
        row.refresh_style()
        self.assertEqual(row.style_box.off_note.text(), "1 switched off in QGIS: their explorations are drawn in "
                                                        "black.")
        self.assertFalse(row.style_box.off_note.isHidden())
        self.assertNotIn(CUMBERLAND_AESI[0][1], [lab for lab, _c in row.style_box.chips.items()])
        self.assertEqual((len(row.style_box.chips.items()), row.style_box.chips.more()), (4, 8))
        # every one off: no chips, the swatch black (its lines are all drawn black)
        for it in st.items:
            lyr.renderer().checkLegendSymbolItem(it.key, False)
        row.refresh_style()
        self.assertEqual((row.style_box.chips.items(), row.style_box.chips.more()), ([], 0))
        self.assertTrue(row.style_box.chips.isHidden())
        self.assertEqual(row.style_box.off_note.text().split(" ")[0], "13")
        self.assertEqual(row.swatch.colors(), [R.BLACK_INK])
        # one left on: one chip, the swatch its colour
        lyr.renderer().checkLegendSymbolItem(st.items[2].key, True)
        row.refresh_style()
        self.assertEqual(row.style_box.chips.items(), [(CUMBERLAND_AESI[2][1], CUMBERLAND_AESI[2][2])])
        self.assertEqual(row.swatch.colors(), [CUMBERLAND_AESI[2][2]])
        self.assertEqual(row.style_box.off_note.text().split(" ")[0], "12")

    def test_graduated(self):
        lyr = QgsVectorLayer(f"Point?crs={CRS}&field=ExploName:string&field=Depth:double", "Graded", "memory")
        self.prj.addMapLayer(lyr)
        self.addCleanup(self.prj.removeMapLayer, lyr.id())
        ranges = [QgsRendererRange(0.0, 20.0, QgsMarkerSymbol.createSimple({"color": "#1f6fb2"}), ""),
                  QgsRendererRange(20.0, 100.0, QgsMarkerSymbol.createSimple({"color": "#d95f02"}), "Deep")]
        lyr.setRenderer(QgsGraduatedSymbolRenderer("Depth", ranges))
        row = R.ExplorationRow(point_row(lyr, label_field="ExploName", look="color"))
        head, chips, more, off, foot_hidden = self.box(row)
        self.assertEqual(head, self.HEAD + "<b>Graduated by Depth</b> · 2 ranges")
        self.assertEqual(chips, [("0 - 20", "#1f6fb2"), ("Deep", "#d95f02")])
        self.assertEqual((more, off, foot_hidden), (0, "", False))
        lyr.setRenderer(QgsGraduatedSymbolRenderer("Depth", ranges[:1]))
        row.refresh_style()
        self.assertEqual(row.style_box.head.text(), self.HEAD + "<b>Graduated by Depth</b> · 1 range")

    def test_rule_based(self):
        lyr = self.styled(rule_renderer([("\"ExploType\" = 'Boring'", "Borings", "#df9560", True),
                                         ("\"ExploType\" = 'Monitoring Well'", "Wells", "#3fcaa2", True),
                                         ("ELSE", "", "#987db7", True)]))
        row = self.color_row()
        head, chips, more, off, foot_hidden = self.box(row)
        self.assertEqual(head, self.HEAD + "<b>Rule-based</b> · 3 rules")
        self.assertEqual(chips, [("Borings", "#df9560"), ("Wells", "#3fcaa2"), ("(other values)", "#987db7")])
        self.assertEqual((more, off, foot_hidden), (0, "", False))
        # the Borings rule switched off: its line, and on the sheet its explorations are black (not taken by ELSE)
        key = row.current_style().items[0].key
        lyr.renderer().checkLegendSymbolItem(key, False)
        row.refresh_style()
        self.assertEqual(row.style_box.off_note.text(), "1 switched off in QGIS: their explorations are drawn in "
                                                        "black.")
        self.assertEqual([lab for lab, _c in row.style_box.chips.items()], ["Wells", "(other values)"])
        fids = {f["ExploName"]: f.id() for f in lyr.getFeatures()}
        _st, got = read_styles(lyr, list(fids.values()))
        self.assertEqual(got[fids["B-1"]], (-1, ""))
        self.assertEqual(got[fids["MW-1"]], (1, "#3fcaa2"))
        self.assertEqual(got[fids["CPT-1"]], (2, "#987db7"))
        self.assertEqual(sum(1 for v in got.values() if v == (-1, "")),
                         sum(1 for f in lyr.getFeatures() if f["ExploType"] == "Boring"))

    def test_no_symbols_and_missing(self):
        self.styled(QgsHeatmapRenderer())
        row = self.color_row()
        self.assertEqual(self.box(row), (self.HEAD + "no symbols (the lines are drawn in black)", [], 0, "", True))
        self.assertEqual(row.swatch.colors(), [R.BLACK_INK])
        # the layer leaves the project: no chips; back: its style again
        self.styled(single_renderer("#b7484b"), self.supply)
        row = self.color_row(self.supply)
        self.assertEqual(row.swatch.colors(), ["#b7484b"])
        lyr = self.take(row, self.supply)
        try:
            self.assertEqual(self.box(row), (self.HEAD + "the layer is not in the project.", [], 0, "", True))
            self.assertEqual(row.swatch.colors(), [R.BLACK_INK])
            self.assertIsNone(row.current_style())
        finally:
            self.back(row, lyr)
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#b7484b")])
        # no layer chosen
        row = R.ExplorationRow(point_row(look="color"))
        self.assertEqual(self.box(row), (self.HEAD + "no layer chosen.", [], 0, "", True))

    def test_hint_and_box_by_look(self):
        self.styled(categorized_renderer("ExploType", CUMBERLAND_AESI))
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        self.assertEqual(row.look_hint.text(), "Black like your own explorations; Gray sets a layer apart; Color takes "
                                               "each exploration’s color from the layer’s style in QGIS.")
        self.assertEqual([row.look_seg.itemText(i) for i in range(3)], ["Black", "Gray", "Color"])
        self.assertEqual([row.look_seg.buttons()[i].toolTip() for i in range(3)],
                         ["Black, like your own explorations", "Gray, to set this layer apart",
                          "Each exploration in its color in this layer's style in QGIS"])
        for look, box_hidden, colors in (("gray", True, [LOOK_GRAY]),
                                         ("color", False, [c for _v, _l, c in CUMBERLAND_AESI[:3]]),
                                         ("black", True, [R.BLACK_INK])):
            row.look_seg.setCurrentIndex(row.look_seg.findData(look))
            self.assertEqual((row.style_box.isHidden(), row.look_hint.isHidden()), (box_hidden, not box_hidden), look)
            self.assertEqual(row.swatch.colors(), colors, look)
        self.assertNotIn("color", row.value())
        self.assertEqual(list(row.value()), list(POINT_LAYER_DEFAULTS))

    def test_swatch_bars(self):
        def near(img, x, color):
            """Within 40 per channel of `color` somewhere in column x (y 3 to 13)."""
            c = QColor(color)
            return any(max(abs(p.red() - c.red()), abs(p.green() - c.green()), abs(p.blue() - c.blue())) < 40
                       for p in (img.pixelColor(x, y) for y in range(3, 14)))
        e = W.ExploSwatch()
        self.assertEqual(e.colors(), ["#111111"])
        e.set_colors(["#df9560", "#3fcaa2", "#80a7ea", "#cec063"])              # three at most
        self.assertEqual(e.colors(), ["#df9560", "#3fcaa2", "#80a7ea"])
        self.assertEqual(e.color(), "#df9560")
        img = e.grab().toImage()
        for x, color in ((6, "#df9560"), (11, "#3fcaa2"), (16, "#80a7ea")):
            self.assertTrue(near(img, x, color), (x, color))
        self.assertFalse(near(img, 11, "#df9560"))
        e.set_colors([])                                                        # (a guard): black
        self.assertEqual(e.colors(), ["#111111"])
        e.set_color("#b5651d")
        self.assertEqual(e.colors(), ["#b5651d"])
        img = e.grab().toImage()
        self.assertTrue(near(img, 11, "#b5651d"))                               # one colour: the line and cap
        self.assertFalse(near(img, 6, "#b5651d"))

    def test_chips_wrap_and_cut(self):
        c = W.StyleChips()
        items = [(lab, col) for _v, lab, col in CUMBERLAND_AESI[:4]]
        c.set_items(items, 9)
        self.assertEqual((c.items(), c.more(), c.more_text()), (items, 9, "+ 9 more"))
        self.assertEqual(c.toolTip().split("\n"), [lab for lab, _c in items])
        self.assertTrue(c.hasHeightForWidth())
        wide, narrow = c.heightForWidth(2000), c.heightForWidth(120)
        self.assertGreater(narrow, wide)
        c.resize(2000, wide)
        self.assertEqual([t for t, _c in c.painted()], [lab for lab, _c in items] + ["+ 9 more"])
        long = "A category label much wider than the whole row of chips"
        c.set_items([(long, "#123456")], 0)
        c.resize(120, c.heightForWidth(120))
        (text, color), = c.painted()
        self.assertTrue(text.endswith("…") and len(text) < len(long), text)
        self.assertEqual((c.items(), color), ([(long, "#123456")], "#123456"))
        c.set_items([], 0)
        self.assertEqual(c.heightForWidth(300), 0)


if __name__ == "__main__":
    unittest.main()
