"""0.3.5 (fixes he found in 0.3.4, and two requests).

1. Each exploration row's "Screens are" reads Elevations | Depths, in the order of "Levels are" (the stored values,
   the default "depth" and the tooltips unchanged).
2. Numbers stored as text: his "Boring Summary" table is a CSV that OGR opens with every column a String, so the
   numeric-only Water level box listed nothing and would not open. Every number box now lists number and text fields
   (widgets.NUMBER_BOX_FILTERS); the guesses still prefer number fields and ignore punctuation and a trailing unit
   ("GW Elev. (ft)" is GW_Elev); a text that is a plain number is read (" 642 ", "1e3", "1,234.5"), any other text is
   left out as NULL is and flagged: one model warning per table field, a flag per exploration (and other point) for
   its own fields. Real CSV files are written to the run's temp folder and opened with the `ogr` provider; a `.csvt`
   (typed columns) and a GeoPackage table behave as before. A text field is guessed only when its values are numbers
   (point_rows.number_texts: CDF_wells' Elevation_ is not), and a box that needs a field and gets none shows none
   (never the name column QgsFieldComboBox would pick by itself).
3. "In elevation range" sits beside Total depth, and the table box reads "Water levels from a table (CSV, Excel…)";
   every other text says "table of water levels".
"""
import csv
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests.fixtures import (CRS, EXPLORATIONS, REALDATA, TOLERANCE, load_project, plane_z, point_at, point_row,
                            seep_row, start_app, write_gpkg)

APP = start_app()

from matplotlib.figure import Figure  # noqa: E402
from qgis.core import QgsCoordinateReferenceSystem, QgsFeature, QgsField, QgsVectorLayer  # noqa: E402
from qgis.core import QgsFieldProxyModel  # noqa: E402
from qgis.gui import QgsFieldComboBox  # noqa: E402
from qgis.PyQt.QtCore import QMetaType  # noqa: E402
from qgis.PyQt.QtWidgets import QCheckBox, QLabel  # noqa: E402

from xsections.core import explorations as E  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import POINT_LAYER_DEFAULTS, SectionError, Settings, layer_rows  # noqa: E402
from xsections.render import figure as F  # noqa: E402
from xsections.render import scales as S  # noqa: E402
from xsections.ui import point_guess as G  # noqa: E402
from xsections.ui import point_rows as R  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402

# his table's columns (Cumberland.qgz, layer "Boring Summary"; the 11th has no name: OGR calls it field_11)
BORING_SUMMARY = ["Boring", "GS Elev", "DTW", "Depth BOH", "Depth Bot Aq", "Aquifer Material", "GW Elev. (ft)",
                  "BOH Elev", "Aq Bot Elev", "Notes", "field_11"]
LEVEL = "GW Elev. (ft)"
NOT_NUMBERS_3 = "Boring Summary: 3 water levels in GW Elev. (ft) are not numbers (left out)."


class Count:
    def __init__(self, signal):
        self.n = 0
        signal.connect(self)

    def __call__(self, *args):
        self.n += 1


def lidar(name):
    """The LIDAR (the fixture's plane) at the fixture exploration `name`."""
    st, off = next((st, off) for n, _t, st, off, *_rest in EXPLORATIONS if n == name)
    return plane_z(*point_at(st, off))


def write_csv(name, header, rows, csvt=None):
    """A CSV file in a new folder of the run's temp folder (tests.fixtures.RUN_TMP); `csvt`: the column types of a
    .csvt next to it. Returns its path."""
    path = os.path.join(tempfile.mkdtemp(prefix="xsec_csv_"), f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["" if h.startswith("field_") else h for h in header])
        w.writerows(rows)
    if csvt:
        with open(path[:-4] + ".csvt", "w", newline="", encoding="utf-8") as fh:
            fh.write(",".join(f'"{t}"' for t in csvt) + "\n")
    return path


def open_ogr(path, name, xy=False):
    """`path` opened with the ogr provider (as QGIS opens a CSV dropped on it); `xy`: points from its X and Y
    columns, in the fixture CRS."""
    uri = path + ("|option:X_POSSIBLE_NAMES=X|option:Y_POSSIBLE_NAMES=Y" if xy else "")
    lyr = QgsVectorLayer(uri, name, "ogr")
    assert lyr.isValid(), path
    assert lyr.providerType() == "ogr"
    if xy:
        lyr.setCrs(QgsCoordinateReferenceSystem(CRS))
    return lyr


def field_head(widget):
    """The field label (widgets.field_label) above `widget` in its field_box."""
    return next(lab for lab in widget.parentWidget().findChildren(QLabel) if lab.objectName() == "xsFieldLabel")


def summary_rows():
    """His table's shape: one row per fixture exploration. GW Elev. (ft) is LIDAR - 10 (B-1), LIDAR - 8 with spaces
    around it (MW-1), empty (TP-1: no value, as NULL), three texts that are not numbers (B-2 dry, MW-2 NA, CPT-1
    "... ft") and 5e2 (B-3, no top: kept at 500); DTW the depths (two not numbers: MW-2, CPT-1)."""
    gw = {"B-1": f"{lidar('B-1') - 10:.2f}", "MW-1": f" {lidar('MW-1') - 8:.1f} ", "TP-1": "", "B-2": "dry",
          "MW-2": "NA", "CPT-1": f"{lidar('CPT-1') - 20:.1f} ft", "B-3": "5e2"}
    dtw = {"B-1": "10", "MW-1": " 8.5 ", "TP-1": "", "B-2": "12", "MW-2": "NA", "CPT-1": "dry", "B-3": ""}
    out = []
    for name in gw:
        out.append([name, f"{lidar(name):.1f}", dtw[name], "30", "80", "Qva sand", gw[name], "", "", "", ""])
    out.append(["Nowhere", "500", "9", "30", "", "", "490", "", "", "not on any line", ""])
    return out


def layer_rows_view(s):
    """The view (model.layer_view) of the first row of `s`, as build_section gives read_wl_table."""
    from xsections.core.model import layer_view
    return layer_view(s, layer_rows(s)[0])


def typed_table(name="Water levels"):
    """The same table in a memory layer with typed columns (Boring, GW_Elev, DTW), the numbers only."""
    t = QgsVectorLayer("None", name, "memory")
    t.dataProvider().addAttributes([QgsField("Boring", QMetaType.Type.QString),
                                    QgsField("GW_Elev", QMetaType.Type.Double), QgsField("DTW", QMetaType.Type.Double)])
    t.updateFields()
    feats = []
    for name_, gw, dtw in (("B-1", round(lidar("B-1") - 10, 2), 10.0), ("MW-1", round(lidar("MW-1") - 8, 1), 8.5),
                           ("B-3", 500.0, None)):
        f = QgsFeature(t.fields())
        f.setAttributes([name_, gw, dtw])
        feats.append(f)
    t.dataProvider().addFeatures(feats)
    return t


# ================================================================ pure
class TextNumbers(unittest.TestCase):
    def test_plain_numbers_and_us_thousands(self):
        good = {"642.3": 642.3, " 642 ": 642.0, "-12.5": -12.5, "1e3": 1000.0, "1,234.5": 1234.5, "+7": 7.0,
                "\t5.\n": 5.0, ".5": 0.5, "1,234,567": 1234567.0, "-1,234": -1234.0, "2.5E-1": 0.25}
        for text, x in good.items():
            self.assertEqual(E.to_number(text), x, repr(text))
            self.assertEqual(E.not_number_text(text), "", repr(text))
        bad = ["NA", "dry", "642.3 ft", "1.234,5", "12,34", "1_000", "nan", "inf", "-", "0x10", "1e999", "١٢٣",
               ">50", "5'"]
        for text in bad:
            self.assertIsNone(E.to_number(text), repr(text))
            self.assertEqual(E.not_number_text(text), text.strip(), repr(text))
        for empty in ("", "   ", None):                        # no value, as NULL: not counted
            self.assertIsNone(E.to_number(empty))
            self.assertEqual(E.not_number_text(empty), "")
        # numbers stay numbers (the 0.3.4 behaviour)
        self.assertEqual([E.to_number(v) for v in (3, 2.5, 0.0, float("nan"))], [3.0, 2.5, 0.0, None])
        self.assertEqual(E.not_number_text(12.5), "")
        self.assertEqual(E.not_number_flag("DTW", "dry"), "DTW “dry” is not a number: left out")
        long = "see the boring log for the details"
        self.assertEqual(E.not_number_flag("DTW", long), f"DTW “{long[:23]}…” is not a number: left out")

    def test_name_matching(self):
        """Punctuation and a trailing unit in parentheses are ignored; a qualifier that is not a unit is not."""
        self.assertEqual(G._norm("GW Elev. (ft)"), "gwelev")
        self.assertEqual(G._norm("Depth (ft bgs)"), "depth")
        self.assertEqual(G._norm("Elev (m)"), "elev")
        self.assertEqual(G._norm("GW Elev (ATD)"), "gwelevatd")
        self.assertEqual(G._norm("Depth_to-GW"), "depthtogw")                          # as before
        self.assertEqual(G.guess_field(BORING_SUMMARY, ["GW_Elev"]), LEVEL)
        self.assertEqual(G.guess_field(BORING_SUMMARY, ["GWElev"]), LEVEL)
        self.assertEqual(G.guess_field(BORING_SUMMARY, G.TOP_NAMES), "GS Elev")
        self.assertEqual(G.guess_field(BORING_SUMMARY, G.DEPTH_NAMES), "Depth BOH")
        self.assertEqual(G.guess_field(BORING_SUMMARY, G.BOTTOM_ELEV_NAMES), "BOH Elev")
        self.assertEqual(G.guess_field(["Elev (mm)"], ["Elev"]), "")

    def test_number_fields_first(self):
        """A number box takes text fields, but a name that matches a number field wins, a text field is guessed only
        when no number field matches, the fallback of a box that needs a field is a number field, and a date never
        goes in a number box."""
        text = [(n, False) for n in BORING_SUMMARY]
        self.assertEqual(G.pick_field(text, set(), "", G.TABLE_ELEV_NAMES, numeric=True, required=True),
                         (LEVEL, True))
        self.assertEqual(G.pick_field(text, set(), "Notes", [], numeric=True), ("Notes", False))   # a saved one
        mixed = [("Elev_txt", False), ("WL_Elev_t", False), ("Elevation", True), ("WL Elev", False)]
        self.assertEqual(G.pick_field(mixed, set(), "", G.TABLE_ELEV_NAMES, numeric=True), ("Elevation", True))
        self.assertEqual(G.pick_field([("WL Elev", False), ("Lvl", True)], set(), "", ["X"], numeric=True,
                                      required=True), ("Lvl", False))       # the fallback: a number field
        self.assertEqual(G.pick_field([("WL Elev", False)], set(), "", ["X"], numeric=True, required=True),
                         ("", False))                                       # never a text field by default
        dates = [("WL_Elev", None), ("Name", False)]
        self.assertEqual(G.pick_field(dates, set(), "WL_Elev", ["WL_Elev"], numeric=True), ("", False))
        self.assertEqual(G.pick_field(dates, set(), "WL_Elev", []), ("WL_Elev", False))  # (a date box takes it)
        # a saved text field is kept (his choice); carried over to a newly chosen layer (fresh) it gives way to a
        # number field the guesses match (test_panel.ScreenTests.test_fields_follow_the_points_layer)
        wells = [("Name", False), ("GW_Elev", False), ("DepthToGW", True)]
        self.assertEqual(G.pick_field(wells, set(), "GW_Elev", G.WL_NAMES, numeric=True), ("GW_Elev", False))
        self.assertEqual(G.pick_field(wells, set(), "GW_Elev", G.WL_NAMES, numeric=True, fresh=True),
                         ("DepthToGW", True))
        self.assertEqual(G.pick_field([("GW_Elev", False)], set(), "GW_Elev", G.WL_NAMES, numeric=True, fresh=True),
                         ("GW_Elev", False))
        g, _h = G.guess_point_row(wells, set(), "x", saved=dict(wl_field="GW_Elev"), guess_fields=True)
        self.assertEqual((g["wl_field"], g["wl_values"]), ("DepthToGW", "depth"))
        g, _h = G.guess_point_row(wells, set(), "x", saved=dict(wl_field="GW_Elev"), guess_fields=False)
        self.assertEqual(g["wl_field"], "GW_Elev")
        # his typed layers guess as before (tests.test_point_rows.Guesses keeps their whole answers)
        g, _h = G.guess_point_row([("Name", False), ("DepthToGW", False), ("GW_Elev", True)], set(), "x")
        self.assertEqual((g["wl_field"], g["wl_values"]), ("GW_Elev", "elevation"))

    def test_table_guess_follows_levels_are(self):
        text = [(n, False) for n in BORING_SUMMARY]
        t = G.guess_table_fields(text, set())
        self.assertEqual(t, dict(wl_table_name_field="Boring", wl_table_elev_field=LEVEL, wl_table_date_field="",
                                 wl_table_kind_field=""))
        self.assertEqual(G.guess_table_fields(text, set(), wl_values="depth")["wl_table_elev_field"], "DTW")
        self.assertEqual(G.guess_table_fields(text, set(), saved=dict(wl_values="depth"))["wl_table_elev_field"],
                         "DTW")
        # depths without a depth name: the elevation names, as 0.3.4 guessed
        typed = [("id", True), ("ExploName", False), ("WL_Elev", True)]
        self.assertEqual(G.guess_table_fields(typed, {"id"}, wl_values="depth")["wl_table_elev_field"], "WL_Elev")
        self.assertEqual(G.guess_table_fields(typed, {"id"})["wl_table_elev_field"], "WL_Elev")

    def test_a_text_field_only_when_its_values_are_numbers(self):
        """text_ok (the panel: point_rows.number_texts) says which text fields hold numbers: a text field is guessed
        only then, so a typed layer's text columns are not (CDF_wells' Elevation_, survey sources), while his CSV
        and a mixed delimited-text table still are."""
        from tests.test_point_rows import CDF
        self.assertEqual(G.guess_other_row(CDF, set(), "CDF_wells", text_ok=set())["elev_field"], "")   # as 0.3.4
        self.assertEqual(G.guess_other_row(CDF, set(), "CDF_wells")["elev_field"], "Elevation_")    # (unchecked)
        g, _h = G.guess_point_row(CDF, set(), "CDF_wells", text_ok=set())
        self.assertEqual(g, G.guess_point_row(CDF, set(), "CDF_wells")[0])     # its exploration row: as before
        # his CSV: every column a text that holds numbers
        text = [(n, False) for n in BORING_SUMMARY]
        ok = set(BORING_SUMMARY) - {"Aquifer Material", "Notes", "field_11", "Boring"}
        self.assertEqual(G.guess_table_fields(text, set(), text_ok=ok)["wl_table_elev_field"], LEVEL)
        self.assertEqual(G.guess_table_fields(text, set(), text_ok=ok, wl_values="depth")["wl_table_elev_field"],
                         "DTW")
        # a mixed table ("Detect field types" on: the clean columns numbers, the level a text because of an "NA"):
        # the level, never GS Elev by the fallback
        mixed = [("Boring", False), ("GS Elev", True), ("DTW", False), (LEVEL, False), ("BOH Elev", True)]
        asked = []

        def numbers(name):
            asked.append(name)
            return name in (LEVEL, "DTW")
        self.assertEqual(G.guess_table_fields(mixed, set(), text_ok=numbers)["wl_table_elev_field"], LEVEL)
        self.assertEqual(asked, [LEVEL])                    # asked only of the field a guess would take
        self.assertEqual(G.guess_table_fields(mixed, set(), text_ok={LEVEL})["wl_table_elev_field"], LEVEL)
        # a text field that is not numbers gives way to the next name that is
        both = [("Name", False), ("Elevation", False), ("Elev", False)]
        self.assertEqual(G.guess_other_row(both, set(), "x", text_ok={"Elev"})["elev_field"], "Elev")
        self.assertEqual(G.guess_other_row(both, set(), "x", text_ok=lambda n: False)["elev_field"], "")
        # a saved text field is kept whatever its values (his choice)
        self.assertEqual(G.guess_other_row(CDF, set(), "x", saved=dict(elev_field="Elevation_"),
                                           text_ok=set())["elev_field"], "Elevation_")

    def test_a_level_that_matches_no_name(self):
        """The table's level on an all-text table whose column matches no name: none (never the name column, never
        a text field by default); measured-level names after the others ("Water Level (ft)" is WaterLevel)."""
        for cols in (["Boring", "Reading", "Date"], ["Well ID", "SWL (ft)", "Notes"]):
            text = [(n, False) for n in cols]
            for wl_values in ("elevation", "depth"):
                t = G.guess_table_fields(text, set(), wl_values=wl_values, text_ok=set(cols))
                self.assertEqual((t["wl_table_name_field"] in cols, t["wl_table_elev_field"]), (True, ""), cols)
        text = [("Boring", False), ("Water Level (ft)", False), ("Date", False)]
        self.assertEqual(G.guess_table_fields(text, set())["wl_table_elev_field"], "Water Level (ft)")
        self.assertEqual(G.guess_table_fields(text, set(), wl_values="depth")["wl_table_elev_field"],
                         "Water Level (ft)")
        self.assertEqual(G.TABLE_ELEV_NAMES[:6], ["WL_Elev", "WaterElev", "Water_Elev", "GW_Elev", "Elevation",
                                                  "Elev"])                     # the 0.3.4 names first, as before
        typed = [("id", True), ("Name", False), ("Elevation", True), ("WaterLevel", True)]
        self.assertEqual(G.guess_table_fields(typed, {"id"})["wl_table_elev_field"], "Elevation")


# ================================================================ the rows and the build on real CSV files
class _Project(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.csv_path = write_csv("Boring Summary", BORING_SUMMARY, summary_rows())
        cls.table = open_ogr(cls.csv_path, "Boring Summary")
        cls.prj.addMapLayer(cls.table)

    def settings(self, rows, others=(), **kw):
        s = Settings(line_layer_id=self.lines.id(), line_fid=next(self.lines.getFeatures()).id(),
                     dem_layer_id=self.dem.id(), tolerance_ft=TOLERANCE, point_layers=list(rows),
                     other_points=list(others))
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def build(self, rows, others=(), **kw):
        return build_section(self.settings(rows, others, **kw), self.prj)

    def explo(self, **kw):
        base = dict(label_field="ExploName", type_field="", top_field="ExploElev", depth_field="ExploDepth",
                    wl_table_id=self.table.id(), wl_table_name_field="Boring", wl_table_elev_field=LEVEL)
        base.update(kw)
        return point_row(self.pts, **base)


class ScreensAre(_Project):
    def test_same_order_as_levels_are(self):
        row = R.ExplorationRow()
        for seg in (row.wl_values, row.screen_values):
            self.assertEqual([seg.itemText(i) for i in range(seg.count())], ["Elevations", "Depths"])
            self.assertEqual([seg.itemData(i) for i in range(seg.count())], ["elevation", "depth"])
        self.assertEqual([b.toolTip() for b in row.screen_values.buttons()],
                         ["Elevations, ft", "Feet below the top of the exploration"])
        self.assertEqual(row.value()["screen_values"], POINT_LAYER_DEFAULTS["screen_values"])
        self.assertEqual(POINT_LAYER_DEFAULTS["screen_values"], "depth")               # the default unchanged
        self.assertEqual(row.screen_values.currentText(), "Depths")
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        row.set_shared(True, "field_then_dem", True)
        self.assertEqual(row.screen_values.currentText(), "Depths")
        ch = Count(row.changed)
        row.screen_values.buttons()[0].click()                                          # the first: Elevations
        self.assertEqual((row.value()["screen_values"], ch.n), ("elevation", 1))
        row.screen_values.buttons()[1].click()
        self.assertEqual((row.value()["screen_values"], ch.n), ("depth", 2))
        row.set_value(point_row(self.pts, label_field="ExploName", screen_values="elevation"))
        self.assertEqual(row.screen_values.currentText(), "Elevations")
        self.assertEqual(row.value()["screen_values"], "elevation")


class CsvTable(_Project):
    def test_ogr_reads_every_column_as_text(self):
        flds = self.table.fields()
        self.assertEqual(flds.names(), BORING_SUMMARY)
        self.assertEqual({flds.at(i).type() for i in range(flds.count())}, {QMetaType.Type.QString})
        self.assertFalse(any(flds.at(i).isNumeric() for i in range(flds.count())))
        self.assertFalse(self.table.isSpatial())
        # 0.3.4's numeric-only box lists nothing (his "it won't let me")
        old = QgsFieldComboBox()
        old.setFilters(QgsFieldProxyModel.Filter.Numeric)
        old.setLayer(self.table)
        self.assertEqual(old.count(), 0)

    def test_the_water_level_box_lists_text_fields_and_can_be_set(self):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        row.set_shared(True, "field_then_dem", True)
        ch = Count(row.changed)
        row.wl_table.setLayer(self.table)                                    # as his choice in the box does
        box = row.wl_table_elev_field
        self.assertEqual(box.filters(), W.NUMBER_BOX_FILTERS)
        self.assertEqual([box.itemText(i) for i in range(box.count())], BORING_SUMMARY)
        self.assertTrue(box.isEnabled() and not row.table_box.isHidden())
        v = row.value()
        self.assertEqual((v["wl_table_id"], v["wl_table_name_field"], v["wl_table_elev_field"],
                          v["wl_table_date_field"], v["wl_table_kind_field"]),
                         (self.table.id(), "Boring", LEVEL, "", ""))           # guessed: GW Elev. (ft)
        self.assertEqual(ch.n, 1)
        box.showPopup()                                                      # it opens
        self.assertTrue(box.view().isVisible())
        box.hidePopup()
        box.setField("DTW")                                                  # and he can choose
        self.assertEqual((row.value()["wl_table_elev_field"], ch.n), ("DTW", 2))
        self.assertEqual(row.stored()["wl_table_elev_field"], "DTW")
        # set again from the stored row (a project read back): the text field is kept
        row.set_value(row.value())
        self.assertEqual(row.wl_table_elev_field.currentField(), "DTW")

    def test_depths_guess_dtw(self):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName", wl_values="depth"))
        row.set_shared(True, "field_then_dem", True)
        row.wl_table.setLayer(self.table)
        self.assertEqual(row.value()["wl_table_elev_field"], "DTW")
        row.set_value(dict(row.value(), wl_table_elev_field="Gone"))         # a saved field it lacks: guessed
        self.assertEqual(row.value()["wl_table_elev_field"], "DTW")
        row.set_value(dict(row.value(), wl_values="elevation", wl_table_elev_field="Gone"))
        self.assertEqual(row.value()["wl_table_elev_field"], LEVEL)

    def test_every_number_box_lists_text_fields(self):
        row = R.ExplorationRow()
        boxes = [row.top_field, row.bottom_elev_field, row.depth_field, row.screen_top_field, row.screen_bottom_field,
                 row.wl_field, row.atd_field, row.wl_table_elev_field, R.OtherPointsRow().elev_field]
        for b in boxes:
            self.assertEqual(b.filters(), W.NUMBER_BOX_FILTERS, b.toolTip())
        for b in (row.label_field, row.type_field, row.wl_date_field, row.wl_table_name_field,
                  row.wl_table_date_field, row.wl_table_kind_field):
            self.assertNotEqual(b.filters(), W.NUMBER_BOX_FILTERS)

    def test_the_build_draws_the_table_levels(self):
        m = self.build([self.explo()])
        h = {x.label: x for x in m.hits}
        self.assertEqual([w.elev for w in h["B-1"].water_levels], [float(f"{lidar('B-1') - 10:.2f}")])
        self.assertEqual([w.elev for w in h["MW-1"].water_levels], [float(f"{lidar('MW-1') - 8:.1f}")])
        self.assertEqual([(w.kind, w.source) for w in h["B-1"].water_levels], [("atd", "table")])   # no Kind column
        self.assertEqual([w.elev for w in h["B-3"].water_levels], [500.0])                        # 5e2
        for name in ("TP-1", "B-2", "MW-2", "CPT-1"):                       # empty, dry, NA, "... ft": left out
            self.assertEqual(h[name].water_levels, [], name)
        self.assertEqual(m.warnings.count(NOT_NUMBERS_3), 1)
        self.assertFalse([w for w in m.warnings if "not a number" in w])     # (the table: no per-hit flags)
        # drawn: the ATD triangles' tips on those levels
        s = self.settings([self.explo()], sheet="custom", h_scale=500.0, v_scale=20.0)
        p = S.plan(m, s)
        fig = Figure()
        F.draw_page(fig, m, s, p, p.pages[0])
        tips = [t.get_xy()[0][1] for t in fig.axes[0].get_children() if t.get_gid() == F.ATD_GID]
        for name in ("B-1", "MW-1"):
            self.assertTrue([y for y in tips if abs(y - h[name].water_levels[0].elev) < 1e-6], (name, tips))
        # depths: DTW below each top
        m = self.build([self.explo(wl_values="depth", wl_table_elev_field="DTW")])
        h = {x.label: x for x in m.hits}
        self.assertAlmostEqual(h["B-1"].water_levels[0].elev, h["B-1"].top - 10.0, places=6)
        self.assertAlmostEqual(h["MW-1"].water_levels[0].elev, h["MW-1"].top - 8.5, places=6)
        self.assertEqual(h["B-2"].water_levels[0].elev, h["B-2"].top - 12.0)
        self.assertIn("Boring Summary: 2 water levels in DTW are not numbers (left out).", m.warnings)
        self.assertNotIn(NOT_NUMBERS_3, m.warnings)

    def test_one_warning_per_table_field(self):
        """Two rows reading the same table field: one warning; another field of it: its own."""
        m = self.build([self.explo(), self.explo(name="Again"), self.explo(name="Third", wl_table_kind_field="Notes")])
        self.assertEqual(m.warnings.count(NOT_NUMBERS_3), 1)
        m = self.build([self.explo(), self.explo(name="Depths", wl_values="depth", wl_table_elev_field="DTW")])
        self.assertEqual(m.warnings.count(NOT_NUMBERS_3), 1)
        self.assertEqual(m.warnings.count("Boring Summary: 2 water levels in DTW are not numbers (left out)."), 1)
        rows = E.read_wl_table(layer_rows_view(self.settings([self.explo()])), self.prj)
        self.assertEqual((rows.not_numbers, rows.warning), (3, NOT_NUMBERS_3))
        self.assertEqual(rows[E.name_key("b-1")][0][0], float(f"{lidar('B-1') - 10:.2f}"))
        self.assertIsNone(rows[E.name_key("B-2")][0][0])

    def test_one_level_not_a_number(self):
        path = write_csv("One", ["Boring", "Level"], [["B-1", "dry"], ["MW-1", "500"]])
        t = open_ogr(path, "One")
        self.prj.addMapLayer(t)
        self.addCleanup(self.prj.removeMapLayer, t.id())
        m = self.build([self.explo(wl_table_id=t.id(), wl_table_elev_field="Level")])
        self.assertIn("One: 1 water level in Level is not a number (left out).", m.warnings)

    def test_zero_is_missing_unchanged(self):
        path = write_csv("Zeros", ["Boring", "Level"], [["B-1", "0"], ["MW-1", " 0.0 "]])
        t = open_ogr(path, "Zeros")
        self.prj.addMapLayer(t)
        self.addCleanup(self.prj.removeMapLayer, t.id())
        row = self.explo(wl_table_id=t.id(), wl_table_elev_field="Level")
        m = self.build([row], zero_is_missing=True)                         # "0" is a 0: missing
        h = {x.label: x for x in m.hits}
        self.assertEqual((h["B-1"].water_levels, h["MW-1"].water_levels), ([], []))
        self.assertFalse([f for f in h["B-1"].flags + h["MW-1"].flags if "water level" in f])
        self.assertFalse([w for w in m.warnings if "not a number" in w or "not numbers" in w])
        m = self.build([row], zero_is_missing=False)                        # a 0 ft level: read, below the bottom
        h = {x.label: x for x in m.hits}
        self.assertTrue([f for f in h["B-1"].flags if f.startswith("ATD water level 0 ft is below the bottom")])
        self.assertTrue([f for f in h["MW-1"].flags if f.startswith("ATD water level 0 ft is below the bottom")])
        self.assertFalse([w for w in m.warnings if "not a number" in w or "not numbers" in w])


class TypedTables(_Project):
    """A .csvt next to the CSV (typed columns) and a GeoPackage table: as before (number fields, no warning)."""

    def test_csvt(self):
        types = ["String", "Real", "Real", "Real", "Real", "String", "Real", "Real", "Real", "String", "String"]
        rows = [r for r in summary_rows() if r[0] in ("B-1", "MW-1", "B-3")]
        rows = [r[:6] + [str(float(r[6]))] + r[7:] for r in rows]          # numbers only, as a typed column holds
        path = write_csv("Typed summary", BORING_SUMMARY, rows, csvt=types)
        t = open_ogr(path, "Typed summary")
        self.prj.addMapLayer(t)
        self.addCleanup(self.prj.removeMapLayer, t.id())
        self.assertTrue(t.fields().field(LEVEL).isNumeric())
        self.assertFalse(t.fields().field("Boring").isNumeric())
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        row.set_shared(True, "field_then_dem", True)
        row.wl_table.setLayer(t)
        self.assertEqual(row.value()["wl_table_elev_field"], LEVEL)          # a number field matches first
        m = self.build([self.explo(wl_table_id=t.id())])
        h = {x.label: x for x in m.hits}
        self.assertEqual([w.elev for w in h["B-1"].water_levels], [float(f"{lidar('B-1') - 10:.2f}")])
        self.assertEqual([w.elev for w in h["MW-1"].water_levels], [float(f"{lidar('MW-1') - 8:.1f}")])
        self.assertFalse([w for w in m.warnings if "not numbers" in w or "not a number" in w])

    def test_geopackage_table_as_before(self):
        mem = typed_table()
        gpkg = write_gpkg(mem, "Water levels")
        self.prj.addMapLayers([mem, gpkg])
        self.addCleanup(self.prj.removeMapLayers, [mem.id(), gpkg.id()])
        self.assertEqual([gpkg.fields().at(i).name() for i in gpkg.primaryKeyAttributes()], ["id"])
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        row.set_shared(True, "field_then_dem", True)
        row.wl_table.setLayer(gpkg)
        v = row.value()
        self.assertEqual((v["wl_table_name_field"], v["wl_table_elev_field"]), ("Boring", "GW_Elev"))
        box = row.wl_table_elev_field
        self.assertEqual([box.itemText(i) for i in range(box.count())], ["id", "Boring", "GW_Elev", "DTW"])
        levels = []
        for t in (mem, gpkg):
            m = self.build([self.explo(wl_table_id=t.id(), wl_table_elev_field="GW_Elev")])
            levels.append({x.label: [(w.elev, w.kind) for w in x.water_levels] for x in m.hits})
            self.assertFalse([w for w in m.warnings if "not numbers" in w or "not a number" in w])
        self.assertEqual(levels[0], levels[1])
        self.assertEqual(levels[0]["B-1"], [(round(lidar("B-1") - 10, 2), "atd")])


class CsvPoints(_Project):
    """An exploration row (and an Other points row) on a CSV point layer: every number a text."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        rows = []
        spec = {"B-1": (f"{lidar('B-1'):.2f}", "30", "10"), "MW-1": ("NA", " 25 ", "dry"),
                "B-2": (f"{lidar('B-2') + 6:.2f}", "45.0", ""), "TP-1": ("", "10 ft", "4")}
        for name, (gs, depth, dtw) in spec.items():
            st, off = next((st, off) for n, _t, st, off, *_rest in EXPLORATIONS if n == name)
            x, y = point_at(st, off)
            rows.append([name, f"{x:.3f}", f"{y:.3f}", gs, depth, dtw])
        cls.pts_csv = open_ogr(write_csv("Borings", ["Boring", "X", "Y", "GS Elev", "Depth BOH", "DTW"], rows),
                               "Borings", xy=True)
        cls.prj.addMapLayer(cls.pts_csv)

    def test_fields_and_guesses(self):
        flds = self.pts_csv.fields()
        self.assertEqual([flds.field(n).isNumeric() for n in ("Boring", "GS Elev", "Depth BOH", "DTW")],
                         [False] * 4)
        row = R.ExplorationRow()
        row.set_value(dict(layer_id=self.pts_csv.id()), guess_fields=True)
        v = row.value()
        self.assertEqual((v["label_field"], v["top_field"], v["depth_field"], v["wl_field"], v["wl_values"]),
                         ("Boring", "GS Elev", "Depth BOH", "DTW", "depth"))
        self.assertIn("GS Elev", [row.top_field.itemText(i) for i in range(row.top_field.count())])

    def test_build_reads_text_numbers_and_flags_the_rest(self):
        r = point_row(self.pts_csv, label_field="Boring", top_field="GS Elev", depth_field="Depth BOH",
                      wl_field="DTW", wl_values="depth")
        m = self.build([r])
        h = {x.label: x for x in m.hits}
        self.assertEqual(sorted(h), ["B-1", "B-2", "MW-1", "TP-1"])
        self.assertEqual((h["B-1"].top, h["B-1"].top_source), (float(f"{lidar('B-1'):.2f}"), "field"))
        self.assertAlmostEqual(h["B-1"].bottom, h["B-1"].top - 30.0, places=6)
        self.assertAlmostEqual(h["B-1"].water_levels[0].elev, h["B-1"].top - 10.0, places=6)
        self.assertEqual((h["B-2"].top, h["B-2"].top_source), (float(f"{lidar('B-2') + 6:.2f}"), "field"))
        self.assertEqual(h["B-2"].total_depth, 45.0)
        self.assertEqual(h["MW-1"].top_source, "dem")                       # GS Elev NA: LIDAR
        self.assertAlmostEqual(h["MW-1"].bottom, h["MW-1"].top - 25.0, places=6)
        self.assertIn("GS Elev “NA” is not a number: left out", h["MW-1"].flags)
        self.assertIn("DTW “dry” is not a number: left out", h["MW-1"].flags)
        self.assertEqual(h["MW-1"].water_levels, [])
        self.assertIn("Depth BOH “10 ft” is not a number: left out", h["TP-1"].flags)
        self.assertFalse([f for f in h["B-1"].flags + h["B-2"].flags if "not a number" in f])
        self.assertFalse([f for f in h["TP-1"].flags if "GS Elev" in f and "not a number" in f])   # empty: no value
        self.assertIn("MW-1: GS Elev “NA” is not a number: left out", m.warnings)

    def test_other_points_on_text_elevations(self):
        o = seep_row(self.pts_csv, label_field="Boring", elev="field", elev_field="GS Elev", elev_empty="line")
        m = self.build([], [o])
        p = {x.label: x for x in m.other_points}
        self.assertEqual((p["B-1"].how, p["B-1"].z), ("field", float(f"{lidar('B-1'):.2f}")))
        self.assertEqual(p["MW-1"].how, "line")
        self.assertIn("GS Elev “NA” is not a number: on the ground line", p["MW-1"].flags)
        self.assertEqual(p["TP-1"].how, "line")
        self.assertFalse([f for f in p["TP-1"].flags + p["B-1"].flags if "not a number" in f])
        self.assertIn("MW-1: GS Elev “NA” is not a number: on the ground line", m.warnings)
        m = self.build([], [dict(o, elev_empty="off")])
        self.assertEqual(sorted(x.label for x in m.other_points), ["B-1", "B-2"])
        self.assertEqual(sorted(m.other_layers[0].no_elevation), ["MW-1", "TP-1"])
        row = R.OtherPointsRow(o)
        self.assertEqual(row.value()["elev_field"], "GS Elev")               # a text field is kept
        self.assertIn("GS Elev", [row.elev_field.itemText(i) for i in range(row.elev_field.count())])


class NumberTexts(_Project):
    """point_rows.number_texts on a real CSV: a text field holds numbers when one of its first values that are not
    empty is a plain number; read once, only when asked."""

    def test_which_text_fields_hold_numbers(self):
        rows = [["B-1", "512.3", "NA", "dry", ""], ["MW-1", " 500 ", "dry", "NA", ""], ["B-2", "", "498.5", "", ""]]
        t = open_ogr(write_csv("Mixed", ["Boring", "Level", "Mixed", "Words", "Empty"], rows), "Mixed")
        with mock.patch.object(t, "getFeatures", wraps=t.getFeatures) as reads:
            ok = R.number_texts(t)
            self.assertEqual(reads.call_count, 0)                            # nothing read until asked
            self.assertEqual([ok(n) for n in ("Level", "Mixed", "Words", "Empty", "Boring", "Gone")],
                             [True, True, False, False, False, False])
            self.assertEqual(reads.call_count, 5)                            # ("Gone" is not a field: no read)
            self.assertTrue(ok("Level") and not ok("Words"))
            self.assertEqual(reads.call_count, 5)                            # once per field

    def test_cdf_wells_like_layer(self):
        """A typed layer (number fields, a text column of survey sources named like an elevation): its Other points
        row guesses no elevation field, as 0.3.4 did."""
        lyr = QgsVectorLayer(f"Point?crs={CRS}", "wells", "memory")
        T = QMetaType.Type
        lyr.dataProvider().addAttributes([QgsField("ExploName", T.QString), QgsField("ExploElev", T.Double),
                                          QgsField("Elevation_", T.QString)])
        lyr.updateFields()
        feats = []
        for name, z, src in (("W-1", 512.0, "L Green R 2017"), ("W-2", 498.0, "Survey, NAVD 88")):
            f = QgsFeature(lyr.fields())
            f.setAttributes([name, z, src])
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        self.prj.addMapLayer(lyr)
        self.addCleanup(self.prj.removeMapLayer, lyr.id())
        row = R.OtherPointsRow()
        row.set_value(dict(layer_id=lyr.id()), guess_fields=True)
        self.assertEqual((row.value()["label_field"], row.value()["elev_field"]), ("ExploName", ""))
        self.assertEqual(row.elev_field.currentField(), "")
        self.assertIn("Elevation_", [row.elev_field.itemText(i) for i in range(row.elev_field.count())])  # listed
        row.set_value(dict(layer_id=lyr.id(), elev_field="Elevation_"))     # his choice is kept
        self.assertEqual(row.value()["elev_field"], "Elevation_")


class UnmatchedLevel(_Project):
    """An all-text table whose level column matches no name: the Water level box shows none (0.3.4 left it empty;
    0.3.5's first build showed QgsFieldComboBox's own first field, the name column), lists every field, and the build
    asks him to choose; once chosen, it is read."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        rows = [["B-1", f"{lidar('B-1') - 10:.2f}", "2024-01-05"], ["MW-1", f"{lidar('MW-1') - 8:.1f}", ""]]
        cls.readings = open_ogr(write_csv("Readings", ["Boring", "Reading", "Date"], rows), "Readings")
        cls.prj.addMapLayer(cls.readings)

    def row(self, **kw):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName", **kw))
        row.set_shared(True, "field_then_dem", True)
        return row

    def test_the_box_shows_none(self):
        flds = self.readings.fields()
        self.assertEqual({flds.at(i).type() for i in range(flds.count())}, {QMetaType.Type.QString})
        for wl_values in ("elevation", "depth"):
            row = self.row(wl_values=wl_values)
            row.wl_table.setLayer(self.readings)
            box = row.wl_table_elev_field
            self.assertEqual([box.itemText(i) for i in range(box.count())], ["Boring", "Reading", "Date"])
            self.assertEqual((box.currentIndex(), box.currentField()), (-1, ""), wl_values)
            v = row.value()
            self.assertEqual((v["wl_table_name_field"], v["wl_table_elev_field"]), ("Boring", ""), wl_values)
            self.assertEqual(row.wl_table_name_field.currentField(), "Boring")

    def test_switching_from_his_table(self):
        row = self.row()
        row.wl_table.setLayer(self.table)
        self.assertEqual(row.wl_table_elev_field.currentField(), LEVEL)
        row.wl_table.setLayer(self.readings)
        self.assertEqual(row.wl_table_elev_field.currentField(), "")        # not "Boring"
        self.assertEqual(row.value()["wl_table_elev_field"], "")
        row.wl_table.setLayer(self.table)
        self.assertEqual(row.wl_table_elev_field.currentField(), LEVEL)

    def test_the_build_asks_and_then_reads_it(self):
        row = self.row()
        row.wl_table.setLayer(self.readings)
        with self.assertRaises(SectionError) as cm:
            self.build([row.value()])
        self.assertEqual(str(cm.exception), "Choose the name and level fields of the table of water levels Readings.")
        ch = Count(row.changed)
        row.wl_table_elev_field.setField("Reading")                          # he chooses it
        self.assertEqual((row.value()["wl_table_elev_field"], ch.n), ("Reading", 1))
        m = self.build([row.value()])
        h = {x.label: x for x in m.hits}
        self.assertEqual([w.elev for w in h["B-1"].water_levels], [float(f"{lidar('B-1') - 10:.2f}")])
        row.set_value(row.value())                                           # read back: kept
        self.assertEqual(row.wl_table_elev_field.currentField(), "Reading")

    def test_water_level_ft_is_guessed(self):
        rows = [["B-1", "500.5", "512"], ["MW-1", "498", "510"]]
        t = open_ogr(write_csv("Levels", ["Boring", "Water Level (ft)", "GS Elev"], rows), "Levels")
        self.prj.addMapLayer(t)
        self.addCleanup(self.prj.removeMapLayer, t.id())
        row = self.row()
        row.wl_table.setLayer(t)
        self.assertEqual(row.value()["wl_table_elev_field"], "Water Level (ft)")


class TableTexts(_Project):
    """"Water levels from a table (CSV, Excel…)" and "table of water levels" in every text (his request)."""

    def test_the_errors(self):
        with self.assertRaises(SectionError) as cm:
            self.build([self.explo(wl_table_id="gone")])
        self.assertEqual(str(cm.exception),
                         "The table of water levels is no longer in the project. Choose it again, or none.")
        lost = QgsVectorLayer(os.path.join(tempfile.mkdtemp(prefix="xsec_lost_"), "Boring Summary.csv"),
                              "Boring Summary", "ogr")
        self.assertFalse(lost.isValid())

        class Prj:                       # a layer QGIS keeps unavailable (a moved file): its name is known
            def mapLayer(self, _id):
                return lost
        with self.assertRaises(SectionError) as cm:
            E.read_wl_table(layer_rows_view(self.settings([self.explo()])), Prj())
        self.assertEqual(str(cm.exception), "The table of water levels (Boring Summary) is no longer in the project. "
                                            "Choose it again, or none.")
        with self.assertRaises(SectionError) as cm:
            self.build([self.explo(wl_table_elev_field="")])
        self.assertEqual(str(cm.exception),
                         "Choose the name and level fields of the table of water levels Boring Summary.")
        with self.assertRaises(SectionError) as cm:
            self.build([self.explo(wl_table_elev_field="Nope")])
        self.assertEqual(str(cm.exception), "The level field “Nope” of the table of water levels is not in Boring "
                                            "Summary. Choose another field.")
        with self.assertRaises(SectionError) as cm:
            self.build([self.explo(wl_table_kind_field="Kind")])
        self.assertEqual(str(cm.exception), "The kind field “Kind” of the table of water levels is not in Boring "
                                            "Summary. Choose another field.")

    def test_the_row_texts(self):
        row = R.ExplorationRow(point_row(self.pts, label_field="ExploName"))
        self.assertEqual(row.wl_table.toolTip(),
                         "A spreadsheet-style table (CSV, Excel sheet, or any layer; no geometry needed) with one row "
                         "per water-level reading: the exploration's name, the level, and optionally its date and kind "
                         "(measured or ATD).")
        head = field_head(row.wl_table)
        self.assertEqual(head.text(), "WATER LEVELS FROM A TABLE (CSV, EXCEL…)")
        self.assertEqual(row.wl_values.toolTip(), "Applies to the measured and ATD fields and to the table of water "
                                                  "levels")
        self.assertEqual(row.in_range_box.text(), "In elevation range")
        self.assertEqual(row.in_range_box.toolTip(),
                         "Include this layer's explorations in the automatic elevation range. Unticked, deeper ones "
                         "stop at the frame with an arrow and their TD.")
        texts = [w.text() for w in row.editor.findChildren(QLabel)] + [b.text() for b in
                                                                       row.editor.findChildren(QCheckBox)]
        self.assertFalse([t for t in texts if "water-level table" in t.lower() or "include in the" in t.lower()])

    def test_in_the_panel_at_340_px(self):
        """In the dock 340 px wide: "In elevation range" is the right half of the Total depth pair, bottoms
        aligned, shown whole; its hint follows the pair; the table's label fits the editor's width."""
        from tests.test_ui import make_iface
        from xsections.ui.dock import XSectionsDock
        d = XSectionsDock(make_iface(), None)
        try:
            d.restore_from_project()
            d.resize(340, 900)
            d.show()
            d.grp_explo.setCollapsed(False)
            row = d.explo_rows[0]
            row.set_editor_open(True)
            row.more.setExpanded(True)
            row.in_range_box.setChecked(False)
            APP.processEvents()
            box, depth, pair_w = row.in_range_box, row.depth_field, row.depth_pair
            self.assertTrue(box.isVisible() and depth.isVisible())
            self.assertIs(box.parentWidget(), pair_w)
            self.assertTrue(pair_w.isAncestorOf(depth))

            def rect(w):
                tl = w.mapTo(row.editor, w.rect().topLeft())
                return tl.x(), tl.y(), tl.x() + w.width(), tl.y() + w.height()
            bx0, by0, bx1, by1 = rect(box)
            dx0, dy0, dx1, dy1 = rect(depth)
            self.assertGreaterEqual(bx0, dx1)                                 # right of the box
            self.assertTrue(by0 < dy1 and dy0 < by1, (rect(box), rect(depth)))  # in the same row
            self.assertEqual(by1, dy1)                                        # bottoms aligned
            self.assertGreaterEqual(box.width(), box.sizeHint().width(), (box.width(), box.sizeHint().width()))
            self.assertLessEqual(box.sizeHint().width(), pair_w.width() // 2 - 4)
            lay = row.more.body_layout
            self.assertEqual(lay.indexOf(row.range_hint), lay.indexOf(pair_w) + 1)   # the hint follows the pair
            self.assertTrue(row.range_hint.isVisible())
            self.assertGreater(rect(row.range_hint)[1], by1)
            self.assertLess(rect(row.range_hint)[3], rect(row.water_head)[1])
            self.assertEqual(lay.indexOf(box), -1)                          # (no longer under the table)
            head = field_head(row.wl_table)
            self.assertTrue(head.isVisible())
            self.assertLessEqual(head.fontMetrics().horizontalAdvance(head.text()), head.contentsRect().width(),
                                 (head.text(), head.width()))
            self.assertGreaterEqual(head.width(), row.wl_table.width() - 1)
            self.assertFalse(d.scroll.horizontalScrollBar().isVisible())
            self.assertEqual(box.text(), "In elevation range")
            # the narrowest panel (260 px): "In range", whole, the tooltip unchanged; back at 340 px the whole text
            d.resize(260, 900)
            APP.processEvents()
            self.assertEqual(box.text(), "In range")
            self.assertGreaterEqual(box.width(), box.sizeHint().width(), (box.width(), box.sizeHint().width()))
            self.assertTrue(box.toolTip().startswith("Include this layer's explorations"))
            self.assertLessEqual(head.fontMetrics().horizontalAdvance(head.text()), head.contentsRect().width())
            d.resize(340, 900)
            APP.processEvents()
            self.assertEqual(box.text(), "In elevation range")
        finally:
            d.hide()
            d.cleanup()
            d.deleteLater()
            APP.processEvents()


@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealCdfWells(unittest.TestCase):
    """CDF_wells (a copy in the run's temp folder): its String field Elevation_ holds survey sources, so its Other
    points row guesses no elevation field (as 0.3.4); its exploration row guesses as before."""

    def test_cdf_wells_rows(self):
        from qgis.core import QgsProject
        dest = tempfile.mkdtemp(prefix="xsec_cdf_")
        for name in ("CDF_wells.cpg", "CDF_wells.dbf", "CDF_wells.prj", "CDF_wells.shp", "CDF_wells.shx"):
            shutil.copy2(os.path.join(REALDATA, name), dest)
        wells = QgsVectorLayer(os.path.join(dest, "CDF_wells.shp"), "CDF_wells", "ogr")
        self.assertTrue(wells.isValid())
        self.assertEqual(wells.fields().field("Elevation_").type(), QMetaType.Type.QString)
        prj = QgsProject.instance()
        prj.addMapLayer(wells)
        self.addCleanup(prj.removeMapLayer, wells.id())
        self.assertFalse(R.number_texts(wells)("Elevation_"))
        row = R.OtherPointsRow()
        row.set_value(dict(layer_id=wells.id()), guess_fields=True)
        self.assertEqual((row.value()["label_field"], row.value()["elev_field"]), ("ExploName", ""))
        e = R.ExplorationRow()
        e.set_value(dict(layer_id=wells.id()), guess_fields=True)
        v = e.value()
        self.assertEqual((v["label_field"], v["type_field"], v["top_field"], v["depth_field"], v["wl_field"],
                          v["wl_values"], v["wl_date_field"]),
                         ("ExploName", "ExploType", "ExploElev", "ExploDepth", "DepthToGW", "depth", "ExploDate"))


class DockFlow(_Project):
    """His steps in the panel: the explorations row, Water levels from a table = Boring Summary, the Water level
    box."""

    def test_choose_the_table_and_the_level_in_the_dock(self):
        from tests.test_ui import make_iface
        from xsections.ui.dock import XSectionsDock
        dock = XSectionsDock(make_iface(), None)
        try:
            dock.restore_from_project()
            row = dock.explo_rows[0]
            self.assertEqual(row.layer().id(), self.pts.id())
            row.wl_table.setLayer(self.table)
            box = row.wl_table_elev_field
            self.assertTrue(box.isEnabled())
            self.assertGreater(box.count(), 0)
            self.assertEqual(box.currentField(), LEVEL)
            s = dock.settings()
            self.assertEqual(layer_rows(s)[0]["wl_table_elev_field"], LEVEL)
            m = build_section(s, self.prj)
            h = {x.label: x for x in m.hits}
            self.assertEqual([w.elev for w in h["B-1"].water_levels], [float(f"{lidar('B-1') - 10:.2f}")])
            self.assertIn(NOT_NUMBERS_3, m.warnings)
        finally:
            dock.cleanup()
            dock.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
