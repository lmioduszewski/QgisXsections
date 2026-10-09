"""The panel with several point layers (0.3.3, DESIGN.md decision 22), stage C2: the exploration and Other points rows
in the dock (guessed, added, moved, removed, missing), the left-off list (Plotted explorations, Settings.hidden_points)
and how it follows the section line, the readouts, chips and the points CSV, the layer signals, and the budgets.

The fixture project: the explorations of tests.fixtures, explorations by others (B-2x 0.6 ft from B-2), supply wells
(HW-1 400 ft and HW-3 160 ft deep, out of the elevation range) and seeps, all in EPSG:2927.

0.3.4 (StyleFollow): an exploration row drawn in Color follows its layer's QGIS style (styleChanged)."""
import csv
import os
import tempfile
import time
import unittest
from collections import Counter
from unittest import mock

from tests.fixtures import (CRS, LINE, TOLERANCE, _memory_points, budget, categorized_renderer, explo_row,
                            load_project, make_dem, make_dense_layer, make_line_layer, make_others_layer,
                            make_points_layer, make_seeps_layer, make_supply_layer, other_row, plane_z, point_at,
                            point_row, seep_row, single_renderer, start_app, timing_test, wait_ms, write_gpkg)

APP = start_app()

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject, QgsRasterLayer, QgsVectorLayer)
from qgis.PyQt.QtCore import QEventLoop, Qt, QTimer  # noqa: E402

from tests.test_ui import make_iface  # noqa: E402
from xsections.core.model import Settings, hidden_key, layer_rows  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import CSV_COLUMNS, XSectionsDock  # noqa: E402
from xsections.ui.preview import PreviewWidget  # noqa: E402


def wait(ms: int) -> None:
    """Run the event loop for `ms` (the panel's 300 ms rebuild timer), times fixtures.TIME_FACTOR."""
    loop = QEventLoop()
    QTimer.singleShot(wait_ms(ms), loop.quit)
    loop.exec()


def water_table(name="water_levels"):
    """A table without geometry: one row per water level (Boring, WL_Elev, Date, Kind)."""
    tbl = QgsVectorLayer("None?field=Boring:string&field=WL_Elev:double&field=Date:string&field=Kind:string",
                         name, "memory")
    feats = []
    for row in (("B-2x", 480.0, "3/1/2024", "Measured"), ("O-1", 470.0, "5/2/2019", "Drilling")):
        f = QgsFeature(tbl.fields())
        f.setAttributes(list(row))
        feats.append(f)
    tbl.dataProvider().addFeatures(feats)
    return tbl


def fid_of(layer, label, field="ExploName"):
    return next(f.id() for f in layer.getFeatures() if f[field] == label)


class LayersCase(unittest.TestCase):
    """The fixture project with the four point layers and a dock on it (nothing restored yet)."""

    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.others, self.supply, self.seeps = make_others_layer(), make_supply_layer(), make_seeps_layer()
        self.prj.addMapLayers([self.others, self.supply, self.seeps])
        self.iface = make_iface()
        self.dock = self.new_dock()

    def new_dock(self) -> XSectionsDock:
        d = XSectionsDock(self.iface, None)
        self.addCleanup(self._drop, d)
        return d

    @staticmethod
    def _drop(d) -> None:
        d.cleanup()
        d.deleteLater()
        APP.processEvents()

    def rows_settings(self, **over) -> Settings:
        """Saved v6 settings: the three exploration rows (supply wells out of the elevation range), the seeps row,
        the standard layout."""
        s = Settings(line_layer_id=self.lines.id(), line_fid=1, dem_layer_id=self.dem.id(), tolerance_ft=TOLERANCE,
                     compact_layout=False, fill_grid="off",
                     point_layers=[
                         point_row(self.pts, label_field="ExploName", type_field="ExploType", top_field="ExploElev",
                                   depth_field="ExploDepth"),
                         point_row(self.others, label_field="ExploName", type_field="ExploType_resolved",
                                   top_field="ExploElev", depth_field="ExploDepth"),
                         point_row(self.supply, label_field="AESI_MapLabel", type_field="ExploType_resolved",
                                   top_field="ExploElev", depth_field="WellCompleteDepth", atd_field="GW_Elev_ATD",
                                   atd_date_field="ExploDate", in_range=False)],
                     other_points=[seep_row(self.seeps, label_field="Name", elev_field="Elev_ft")])
        for k, v in over.items():
            setattr(s, k, v)
        return s

    def restore(self, s: Settings, dock=None) -> XSectionsDock:
        d = dock or self.dock
        settings_store.save(self.prj, s)
        d.restore_from_project()
        return d

    def chips(self, d=None):
        return {sec.title(): (sec.chipText(), sec.chipWarn()) for sec in (d or self.dock).sections}

    def untick(self, layer, label, field="ExploName", d=None) -> None:
        """What a click on an exploration's box in Plotted explorations does."""
        d = d or self.dock
        item = d.plotted.item_for(layer.id(), fid_of(layer, label, field))
        self.assertIsNotNone(item, label)
        item.setCheckState(0, Qt.CheckState.Unchecked)

    @staticmethod
    def labels(model):
        return [h.label for h in model.hits], [h.label for h in model.left_off]


# ------------------------------------------------------------------ guessed rows
class GuessedRows(LayersCase):
    def test_fresh_project(self):
        """A row per layer named like explorations, in the layers panel's order, supply wells last and unticked (out
        of the elevation range); seeps under Other points. Guesses are never saved by themselves."""
        self.prj.setDirty(False)
        d = self.dock
        d.restore_from_project()
        tree = [n.layer() for n in self.prj.layerTreeRoot().findLayers()]
        named = [l for l in tree if l in (self.pts, self.others)]
        self.assertEqual([r.layer() for r in d.explo_rows], named + [self.supply])
        rows = layer_rows(d.settings())
        self.assertEqual([(r["visible"], r["in_range"]) for r in rows], [(True, True), (True, True), (False, False)])
        sup = rows[2]
        self.assertEqual((sup["label_field"], sup["type_field"], sup["depth_field"], sup["atd_field"], sup["wl_values"],
                          sup["atd_date_field"]),
                         ("AESI_MapLabel", "ExploType_resolved", "WellCompleteDepth", "GW_Elev_ATD", "elevation",
                          "ExploDate"))
        self.assertEqual([r.layer() for r in d.other_rows], [self.seeps])
        self.assertEqual((other_row(d).value()["label_field"], other_row(d).value()["elev_field"]), ("Name", "Elev_ft"))
        d.refresh()
        d._on_timer()
        self.assertFalse(d._user_changed)
        self.assertFalse(self.prj.isDirty())
        self.assertEqual(settings_store.stored_json(self.prj), "")
        self.assertEqual(self.chips()["Explorations"], ("2 of 3 on · 12 plotted", False))
        self.assertEqual(self.chips()["Other points"], ("Seeps · 4 plotted", False))

    def test_only_seeps(self):
        """A project whose only point layer is named like seeps: no exploration row, one Other points row."""
        self.prj.removeMapLayers([self.pts.id(), self.others.id(), self.supply.id()])
        d = self.dock
        d.restore_from_project()
        self.assertEqual(d.explo_rows, [])
        self.assertEqual([r.layer() for r in d.other_rows], [self.seeps])
        self.assertEqual(self.chips()["Explorations"], ("None", False))
        self.assertEqual(self.chips()["Other points"], ("Seeps", False))
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertFalse(d.model.has_explorations)
        self.assertEqual(len(d.model.other_points), 4)
        self.assertEqual(self.chips()["Other points"], ("Seeps · 4 plotted", False))

    def test_layers_added_later(self):
        """File > New, then the layers are added: the rows are guessed from them (quietly), once."""
        d = self.dock
        self.prj.clear()
        d.project_cleared()
        d.restore_from_project()
        self.assertEqual((d.explo_rows, d.other_rows), ([], []))
        self.prj.setDirty(False)
        seeps, supply, others = make_seeps_layer(), make_supply_layer(), make_others_layer()
        self.prj.addMapLayers([seeps, supply, others])
        self.assertEqual([r.layer() for r in d.explo_rows], [others, supply])
        self.assertEqual([r.value()["visible"] for r in d.explo_rows], [True, False])
        self.assertEqual([r.layer() for r in d.other_rows], [seeps])
        self.assertFalse(d._user_changed)
        self.prj.addMapLayers([make_points_layer(name="more_wells"), make_seeps_layer(name="Springs")])
        self.assertEqual((len(d.explo_rows), len(d.other_rows)), (2, 1))          # only while the lists are empty


# ------------------------------------------------------------------ adding, moving, removing rows
class RowManagement(LayersCase):
    def setUp(self):
        super().setUp()
        self.restore(self.rows_settings())

    def test_add_move_remove(self):
        d = self.dock
        hydrants = QgsVectorLayer(f"Point?crs={CRS}", "Hydrants", "memory")
        borings = make_points_layer(name="Borings 2020")
        self.prj.addMapLayers([hydrants, borings])
        d._user_changed = False
        row = d.add_point_layer()                                  # a layer no row uses, named like explorations
        self.assertIs(row.layer(), borings)
        self.assertTrue(row.editor_open())
        self.assertTrue(d._user_changed)
        self.assertEqual(row.value()["label_field"], "ExploName")   # fields guessed
        self.assertIs(d.add_point_layer(open_editor=False).layer(), hydrants)    # then any free one
        tree = [n.layer() for n in self.prj.layerTreeRoot().findLayers()]
        first = next(l for l in tree if isinstance(l, QgsVectorLayer) and l.geometryType() == Qgis.GeometryType.Point)
        self.assertIs(d.add_point_layer().layer(), first)           # none free: the first point layer
        self.assertEqual(len(d.settings().point_layers), 6)
        # move (the dock's method and the row's menu)
        rows = d.explo_rows
        d.move_explo_row(rows[1], -1)
        self.assertEqual(d.explo_rows[:2], [rows[1], rows[0]])
        self.assertEqual(layer_rows(d.settings())[0]["layer_id"], self.others.id())
        rows[1].act_down.trigger()
        self.assertEqual(d.explo_rows[:2], [rows[0], rows[1]])
        # remove: the last one removed leaves a ground line only, kept when layers are added
        for r in d.explo_rows:
            r.act_remove.trigger()
        self.assertEqual((d.explo_rows, d.settings().point_layers, d._points_none), ([], [], True))
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertFalse(d.model.has_explorations)
        self.prj.addMapLayer(make_points_layer(name="Wells 2021"))
        self.assertEqual(d.explo_rows, [])
        # the same for Other points
        d.remove_other_row(other_row(d))
        self.assertEqual((d.other_rows, d._others_none), ([], True))
        self.prj.addMapLayer(make_seeps_layer(name="Seeps 2"))
        self.assertEqual(d.other_rows, [])
        self.assertEqual(self.chips()["Explorations"], ("None", False))
        self.assertEqual(self.chips()["Other points"], ("None", False))
        # File > New: rows are guessed again for the layers added next
        self.prj.clear()
        d.project_cleared()
        self.assertEqual((d._points_none, d._others_none, d._hidden), (False, False, []))
        self.prj.addMapLayers([make_points_layer(name="Explorations"), make_seeps_layer()])
        self.assertEqual((len(d.explo_rows), len(d.other_rows)), (1, 1))
        self.assertTrue(d.add_other_points().editor_open())

    def test_missing_layer(self):
        """A row whose layer is gone stays (amber), the chip warns and the build says so; an Other points row whose
        layer is gone is left out with a warning, and the section is still built."""
        d = self.dock
        sid = self.supply.id()
        self.prj.removeMapLayer(sid)
        APP.processEvents()
        row = explo_row(d, 2)
        self.assertTrue(row.is_missing() and row.name_label.isWarn())
        self.assertEqual(row.name_label.text(), "Supply wells")
        self.assertEqual(self.chips()["Explorations"], ("1 layer missing", True))
        # (FIX 0.3.3) the removal rebuilds by itself: the preview, the map and an export never show the old section
        self.assertTrue(d._stale and d._timer.isActive())
        d.refresh()
        self.assertIsNone(d.model)
        self.assertIn("is no longer in the project", d.last_error)
        self.assertIn("“row 3”", d.last_error)                     # several rows: it names the row
        self.assertEqual(layer_rows(d.settings())[2]["layer_id"], sid)
        row.visible_box.setChecked(False)                          # untick its row: built without it
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertEqual(self.chips()["Explorations"], ("2 of 3 on · 12 plotted", False))
        # Other points
        d.refresh()
        self.prj.removeMapLayer(self.seeps.id())
        APP.processEvents()
        self.assertTrue(other_row(d).name_label.isWarn())
        self.assertTrue(d._stale and d._timer.isActive())
        d.refresh()
        self.assertIsNotNone(d.model)
        self.assertIn("its layer is no longer in the project; left out.", d.message.text())
        self.assertEqual(self.chips()["Other points"], ("Layer missing", True))

    def test_type_counts_with_no_value(self):
        """"plotted / in the layer", the NULL-or-empty type as "(no value)"; the subtitles count the row."""
        d = self.dock
        d.refresh()
        tl = explo_row(d, 1).type_list
        texts = {tl.topLevelItem(i).text(0): tl.topLevelItem(i).text(1) for i in range(tl.topLevelItemCount())}
        self.assertEqual(texts, {"Boring": "2 / 3", "Monitoring Well": "1 / 1", "(no value)": "2 / 2"})
        self.assertEqual(explo_row(d, 1).sub_label.text(),
                         "Explorations by others · ExploName · 2 of 2 types · 5 plotted")
        self.untick(self.others, "O-2")
        d.refresh()
        self.assertEqual(tl.item_for("").text(1), "1 / 2")          # left off: not plotted
        self.assertEqual(explo_row(d, 1).sub_label.text(),
                         "Explorations by others · ExploName · 2 of 2 types · 4 plotted, 1 off")


# ------------------------------------------------------------------ a missing layer loses nothing
class LostNothing(LayersCase):
    def check(self, gone_id: str) -> None:
        tbl = water_table()
        self.prj.addMapLayer(tbl)
        s = self.rows_settings()
        s.point_layers[1].update(types=["Boring", ""], wl_table_id=tbl.id(), wl_table_name_field="Boring",
                                 wl_table_elev_field="WL_Elev", wl_table_date_field="Date", wl_table_kind_field="Kind",
                                 wl_atd_values=["Drilling"], name="By others", look="color")
        d = self.restore(s)
        want = layer_rows(d.settings())[1]
        self.assertEqual(want, s.point_layers[1])
        self.prj.removeMapLayer({"layer": self.others.id(), "table": tbl.id()}[gone_id])
        APP.processEvents()
        d.tolerance.setValue(77.0)                                 # a user change: saved with the row as it was
        d.save_settings()
        again = self.restore(settings_store.load(self.prj), self.new_dock())
        self.assertEqual(layer_rows(again.settings())[1], want)
        self.assertEqual(again.settings().tolerance_ft, 77.0)

    def test_layer_gone(self):
        self.check("layer")

    def test_table_gone(self):
        self.check("table")


# ------------------------------------------------------------------ layer signals
class LayerSignals(LayersCase):
    def edit(self, layer) -> None:
        layer.startEditing()
        layer.changeAttributeValue(next(layer.getFeatures()).id(), layer.fields().lookupField("ExploDepth"), 77.0)
        layer.rollBack()

    def test_rows_layers_rebuild_the_section(self):
        d = self.restore(self.rows_settings())
        new = make_points_layer(name="Borings B")
        self.prj.addMapLayer(new)
        explo_row(d, 1).layer_combo.setLayer(new)                  # chosen in row 2
        d.refresh()
        self.assertFalse(d._timer.isActive() or d._stale)
        self.edit(new)
        self.assertTrue(d._stale and d._timer.isActive())
        # a row added with "+ Add point layer"
        self.prj.addMapLayer(make_points_layer(name="Pits C"))
        d.btn_add_points.click()
        added = explo_row(d, 3).layer()
        self.assertIsNotNone(added)
        self.assertNotIn(added, (self.pts, new, self.supply))
        d.refresh()
        self.edit(added)
        self.assertTrue(d._stale and d._timer.isActive())
        # a removed row's layer is no longer connected (two rows of one layer: connected once)
        explo_row(d, 0).layer_combo.setLayer(added)
        self.assertEqual(sum(1 for lid, name, _s in d._layer_conns if lid == added.id() and name == "dataChanged"), 1)
        d.remove_explo_row(explo_row(d, 3))
        d.remove_explo_row(explo_row(d, 0))
        self.assertNotIn(added.id(), {lid for lid, _n, _s in d._layer_conns})
        d.refresh()
        self.edit(added)
        self.assertFalse(d._timer.isActive() or d._stale)


# ------------------------------------------------------------------ the left-off list
class LeftOff(LayersCase):
    def setUp(self):
        super().setUp()
        self.restore(self.rows_settings())
        self.dock.refresh()

    def drawn(self, dy=0.0):
        return QgsGeometry.fromPolylineXY([QgsPointXY(x, y + dy) for x, y in LINE])

    def test_plotted_list(self):
        d = self.dock
        lk = f"{self.lines.id()}#1"
        self.assertEqual(d.model.line_key, lk)
        n = len(d.model.hits)
        self.assertEqual(d.plotted.text(), f"Plotted explorations ({n} of {n})")
        items = d.plotted.items()
        self.assertEqual(len(items), n)
        tree = d.plotted.tree
        titles = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())
                  if not tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)]
        self.assertEqual(titles, ["EXPLORATIONS", "EXPLORATIONS BY OTHERS", "SUPPLY WELLS"])        # row order
        for lid in (self.pts.id(), self.others.id(), self.supply.id()):
            st = [h.station for h in d.model.hits if h.layer_id == lid]
            self.assertEqual([e[2] for e in items if e[0] == lid],
                             [h.label for h in sorted((h for h in d.model.hits if h.layer_id == lid),
                                                      key=lambda h: (h.station, h.label))])
            self.assertEqual(st, sorted(st))
        b1 = next(e for e in items if e[2] == "B-1")
        self.assertEqual(b1[3], "300 ft · 40 ft L")
        # untick B-2: left off this line (the sheet, the CSV and the map highlights), saved for this line
        self.untick(self.pts, "B-2")
        b2 = hidden_key(lk, self.pts.id(), fid_of(self.pts, "B-2"))
        self.assertEqual(d.settings().hidden_points, [b2])
        self.assertTrue(d._user_changed)
        self.assertEqual(d.plotted.text(), f"Plotted explorations ({n - 1} of {n}, 1 left off by you)")
        d.refresh()
        plotted, left = self.labels(d.model)
        self.assertNotIn("B-2", plotted)
        self.assertEqual(left, ["B-2"])
        self.assertIn("B-2x", plotted)                              # the other layer's twin stays
        self.assertTrue(d.model.other_points)                       # the seeps are ringed too (7.2)
        self.assertEqual(d.feedback.points.numberOfVertices(), n - 1 + len(d.model.other_points))
        self.assertIn(f"Plotted <b>{n - 1}</b>", d.explo_readout.text())
        self.assertIn("1 left off by you", d.explo_readout.text())
        self.assertEqual(d.plotted.text(), f"Plotted explorations ({n - 1} of {n}, 1 left off by you)")
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_layers_"), "pts.csv")
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(out, "CSV (*.csv)")):
            self.assertEqual(d.export_points_csv(), out)
        with open(out, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], CSV_COLUMNS)
        self.assertEqual(CSV_COLUMNS[-1], "layer")
        self.assertEqual([r[0] for r in rows[1:]], plotted)
        self.assertNotIn("B-2", [r[0] for r in rows[1:]])
        by = {r[0]: r[-1] for r in rows[1:]}
        self.assertEqual((by["B-1"], by["B-2x"], by["HW-1"]), ("Explorations", "Explorations by others",
                                                               "Supply wells"))
        # the box ticked again: plotted again (and saved)
        d.plotted.item_for(self.pts.id(), fid_of(self.pts, "B-2")).setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(d.settings().hidden_points, [])

    def test_the_list_follows_the_line(self):
        d = self.dock
        lk = f"{self.lines.id()}#1"
        self.untick(self.pts, "B-2")
        # another line: not left off there
        d.set_drawn_line(self.drawn(), QgsCoordinateReferenceSystem(CRS))
        d.refresh()
        self.assertEqual(d.model.line_key, "drawn")
        self.assertIn("B-2", self.labels(d.model)[0])
        self.untick(self.pts, "MW-1")                               # left off the drawn line
        # back to the feature: B-2 left off again, MW-1 plotted
        d.select_feature(self.lines, 1)
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], ["B-2"])
        # Show all clears this line only
        d.plotted.btn_show_all.click()
        self.assertEqual(d._hidden, [hidden_key("drawn", self.pts.id(), fid_of(self.pts, "MW-1"))])
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], [])
        # Reverse: the new line has exactly the old one's entries (both ways)
        self.untick(self.pts, "B-2")
        d.reverse_line()
        self.assertEqual(d.model.line_key, "drawn")
        self.assertEqual(self.labels(d.model)[1], ["B-2"])
        self.assertNotIn("MW-1", self.labels(d.model)[1])
        d.reverse_line()
        self.assertEqual(d.model.line_key, lk)
        self.assertEqual(self.labels(d.model)[1], ["B-2"])
        # a new drawing starts with nothing left off: the "drawn" entries go, the feature's stay
        d.set_drawn_line(self.drawn(30.0), QgsCoordinateReferenceSystem(CRS))
        self.assertFalse([e for e in d._hidden if e.startswith("drawn|")])
        self.assertEqual(d._hidden, [hidden_key(lk, self.pts.id(), fid_of(self.pts, "B-2"))])

    def test_save_line_to_layer_keeps_them(self):
        """Untick one on a drawn line, save the line to the lines layer, draw a new line, pick the saved feature:
        still left off."""
        d = self.dock
        d.set_drawn_line(self.drawn(), QgsCoordinateReferenceSystem(CRS))
        d.refresh()
        self.untick(self.pts, "TP-1")
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], ["TP-1"])
        layer = d.save_line_to_layer()
        fid = max(layer.allFeatureIds())
        self.assertIn(hidden_key(f"{layer.id()}#{fid}", self.pts.id(), fid_of(self.pts, "TP-1")), d._hidden)
        d.set_drawn_line(self.drawn(50.0), QgsCoordinateReferenceSystem(CRS))
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], [])
        d.select_feature(layer, fid)
        d.refresh()
        self.assertEqual(d.model.line_key, f"{layer.id()}#{fid}")
        self.assertEqual(self.labels(d.model)[1], ["TP-1"])

    def test_same_layer_added_again(self):
        """Remove a row's layer and add it again (a new id, the same features): the row takes it by itself and what
        he left off stays left off. A layer of another name chosen in a missing row does not take his entries."""
        d = self.dock
        self.untick(self.others, "O-1")
        d.save_settings()
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], ["O-1"])
        old = self.others.id()
        self.prj.removeMapLayer(old)
        APP.processEvents()
        self.assertTrue(explo_row(d, 1).is_missing())
        again = make_others_layer()
        self.prj.addMapLayer(again)
        self.assertIs(explo_row(d, 1).layer(), again)               # taken back by itself ...
        self.assertFalse(d._user_changed)                           # ... quietly
        self.assertEqual(d._hidden, [hidden_key(f"{self.lines.id()}#1", again.id(), fid_of(again, "O-1"))])
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], ["O-1"])
        self.assertEqual(explo_row(d, 1).value()["type_field"], "ExploType_resolved")
        # (FIX 0.3.3) once the layer boxes have the new layer, the row shows it, and his later edits reach the row
        APP.processEvents()
        row = explo_row(d, 1)
        self.assertIs(row.layer_combo.currentLayer(), again)
        self.assertFalse(row._frozen())
        self.assertFalse(d._user_changed)
        row.label_field.setField("ExploType")
        self.assertEqual(row.value()["label_field"], "ExploType")
        row.type_list.item_for("Boring").setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(sorted(row.value()["types"]), ["", "Monitoring Well"])
        self.assertTrue(d._user_changed)
        row.label_field.setField("ExploName")
        row.type_list.item_for("Boring").setCheckState(0, Qt.CheckState.Checked)
        # gone again; another layer of another name added and chosen by him: his entries stay with the old id
        again_id = again.id()
        self.prj.removeMapLayer(again_id)
        APP.processEvents()
        renamed = make_others_layer(name="Other borings")
        self.prj.addMapLayer(renamed)
        self.assertTrue(explo_row(d, 1).is_missing())               # not taken (another name)
        explo_row(d, 1).layer_combo.setLayer(renamed)
        self.assertIs(explo_row(d, 1).layer(), renamed)
        self.assertEqual(d._hidden, [hidden_key(f"{self.lines.id()}#1", again_id, fid_of(renamed, "O-1"))])
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], [])

    def test_line_layer_added_again(self):
        """(FIX 0.3.3) The section-lines layer removed and added again (a new id, the same features): what he left off
        on its lines stays left off, whether the line box takes the layer back by itself (the only line layer) or he
        picks it again (another line layer took the box meanwhile). A line layer of another name gets nothing."""
        d = self.dock
        self.untick(self.pts, "B-2")
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], ["B-2"])
        self.prj.removeMapLayer(self.lines.id())
        APP.processEvents()
        again = make_line_layer()
        self.prj.addMapLayer(again)
        APP.processEvents()
        self.assertIs(d.line_layer.currentLayer(), again)              # back by itself, on the line he was on
        self.assertEqual(d.line_feature.currentData(), 1)
        self.assertEqual(d._hidden, [hidden_key(f"{again.id()}#1", self.pts.id(), fid_of(self.pts, "B-2"))])
        self.assertFalse(d._user_changed)
        d.refresh()
        self.assertEqual(d.model.line_key, f"{again.id()}#1")
        self.assertEqual(self.labels(d.model)[1], ["B-2"])
        # with another line layer: the box moves to it; he picks the re-added layer: still left off
        streams = make_line_layer(name="Streams")
        self.prj.addMapLayer(streams)
        self.prj.removeMapLayer(again.id())
        APP.processEvents()
        self.assertIs(d.line_layer.currentLayer(), streams)
        third = make_line_layer()
        self.prj.addMapLayer(third)
        APP.processEvents()
        self.assertIs(d.line_layer.currentLayer(), streams)            # his choice is not undone
        d.select_feature(third, 1)
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], ["B-2"])
        # a layer of another name gets no entries
        third_id = third.id()
        self.prj.removeMapLayer(third_id)
        APP.processEvents()
        other = make_line_layer(name="Profiles")
        self.prj.addMapLayer(other)
        APP.processEvents()
        self.assertTrue(all(e.startswith(f"{third_id}#") for e in d._hidden))
        d.select_feature(other, 1)
        d.refresh()
        self.assertEqual(self.labels(d.model)[1], [])

    def test_no_refresh_loop(self):
        """refresh() twice with one left-off entry: nothing is marked as the user's, no rebuild waits, the project
        stays clean."""
        d = self.dock
        self.untick(self.pts, "B-1")
        d.save_settings()
        again = self.new_dock()
        again.restore_from_project()
        self.prj.setDirty(False)
        again.refresh()
        again.refresh()
        self.assertEqual(self.labels(again.model)[1], ["B-1"])
        self.assertFalse(again._user_changed)
        self.assertFalse(again._timer.isActive())
        self.assertFalse(self.prj.isDirty())


class UnavailableLayer(unittest.TestCase):
    """(FIX 0.3.3) A project reopened while its explorations file is unavailable (moved, offline): QGIS keeps the
    layer, invalid, under its name. The row learns that name, so the file added again under it is taken back with
    every stored key: his types, "Include in the elevation range" and what he left off."""

    def setUp(self):
        self.prj = QgsProject.instance()
        self.prj.clear()
        self.prj.setCrs(QgsCoordinateReferenceSystem(CRS))
        self.work = tempfile.mkdtemp(prefix="xsec_unavail_")
        self.gpkg = os.path.join(self.work, "Explorations.gpkg")
        pts = write_gpkg(make_points_layer(), "Explorations", self.gpkg)
        lines = write_gpkg(make_line_layer(), "Section_Lines", os.path.join(self.work, "Lines.gpkg"))
        self.prj.addMapLayers([QgsRasterLayer(make_dem(), "LIDAR_DEM_3ft"), pts, lines])
        self.pid = pts.id()
        self.dock = XSectionsDock(make_iface(), None)
        self.addCleanup(LayersCase._drop, self.dock)
        d = self.dock
        d.restore_from_project()
        row = explo_row(d)
        row.type_list.item_for("Test Pit").setCheckState(0, Qt.CheckState.Unchecked)
        row.in_range_box.setChecked(False)
        d.refresh()
        b2 = next(h for h in d.model.hits if h.label == "B-2")
        d.plotted.item_for(self.pid, b2.fid).setCheckState(0, Qt.CheckState.Unchecked)
        d.refresh()
        self.assertEqual([h.label for h in d.model.left_off], ["B-2"])
        self.types = row.value()["types"]
        self.assertNotIn("Test Pit", self.types)
        self.qgs = os.path.join(self.work, "p.qgs")
        self.assertTrue(self.prj.write(self.qgs))

    def reopen_unavailable(self):
        d = self.dock
        self.prj.clear()                                            # (File > Open: the project is cleared, then read)
        d.project_cleared()
        APP.processEvents()
        with open(self.qgs, encoding="utf-8") as fh:
            text = fh.read()
        with open(self.qgs, "w", encoding="utf-8") as fh:
            fh.write(text.replace("Explorations.gpkg", "Missing.gpkg"))
        self.prj.read(self.qgs)
        d.restore_from_project()
        raw = self.prj.mapLayer(self.pid)
        self.assertTrue(raw is not None and not raw.isValid())          # kept, unavailable
        row = explo_row(d)
        self.assertTrue(row.is_missing())
        self.assertEqual(row.last_layer_name(), "Explorations")          # its name, learned from the kept layer
        return row

    def check_taken_back(self, new):
        d = self.dock
        row = explo_row(d)
        self.assertFalse(row.is_missing())
        v = row.value()
        self.assertEqual(v["layer_id"], new.id())
        self.assertEqual((v["types"], v["in_range"]), (self.types, False))
        self.assertTrue(d._hidden and all(f"|{new.id()}|" in e for e in d._hidden))
        self.assertFalse(d._user_changed)
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertEqual([h.label for h in d.model.left_off], ["B-2"])
        self.assertNotIn("TP-1", [h.label for h in d.model.hits])

    def test_removed_then_added(self):
        self.reopen_unavailable()
        self.prj.removeMapLayer(self.pid)
        APP.processEvents()
        new = QgsVectorLayer(f"{self.gpkg}|layername=Explorations", "Explorations", "ogr")
        self.prj.addMapLayer(new)
        APP.processEvents()
        self.check_taken_back(new)

    def test_added_then_removed(self):
        self.reopen_unavailable()
        new = QgsVectorLayer(f"{self.gpkg}|layername=Explorations", "Explorations", "ogr")
        self.prj.addMapLayer(new)
        APP.processEvents()
        self.prj.removeMapLayer(self.pid)
        APP.processEvents()
        self.check_taken_back(new)


# ------------------------------------------------------------------ readouts
class Readouts(LayersCase):
    def setUp(self):
        super().setUp()
        self.restore(self.rows_settings())

    def test_below_the_frame(self):
        """The supply wells are out of the elevation range: HW-1 (400 ft) and HW-3 (160 ft) reach below the frame."""
        d = self.dock
        d.refresh()
        warn = d._warn_color()
        text = d.explo_readout.text()
        self.assertIn(f"<span style='color:{warn}'>2 run below the frame: HW-3 (TD 160′), HW-1 (TD 400′)</span>", text)
        self.assertTrue(text.startswith("Plotted <b>16</b>: 7 Explorations, 5 Explorations by others, 4 Supply wells"),
                        text)
        self.untick(self.supply, "HW-3", field="AESI_MapLabel")
        d.refresh()
        self.assertIn(f" · <span style='color:{warn}'>HW-1 runs below the frame (TD 400′)</span>",
                      d.explo_readout.text())
        # a manual range above HW-3's ATD level (464.5): the sheet leaves the level out, the readout says so
        d.plotted.btn_show_all.click()
        d.z_mode.setCurrentIndex(d.z_mode.findData("manual"))
        d.z_min.setValue(500.0)
        d.z_max.setValue(600.0)
        d.refresh()
        self.assertEqual(d.plan.z_min, 500.0)
        self.assertIn("3 run below the frame: HW-3 (TD 160′; water level below the frame), HW-1 (TD 400′), "
                      "HW-2 (TD 42′)", d.explo_readout.text())
        # in the range: nothing runs below
        explo_row(d, 2).in_range_box.setChecked(True)
        d.z_mode.setCurrentIndex(d.z_mode.findData("auto"))
        d.refresh()
        self.assertNotIn("below the frame", d.explo_readout.text())

    def test_levels_below_the_frame_without_a_line(self):
        """(FIX 0.3.3) An out-of-range well drawn without a line down there (no depth; or Depth line off): its water
        level below the frame is not drawn either, and the readout says so."""
        lyr = self.supply
        x, y = point_at(3400.0, 30.0)                               # SW-1: no WellCompleteDepth; its ATD 150 ft down
        lyr.dataProvider().changeAttributeValues({fid_of(lyr, "SW-1", "AESI_MapLabel"):
                                                  {lyr.fields().lookupField("GW_Elev_ATD"): round(plane_z(x, y) - 150.0,
                                                                                                  2)}})
        d = self.restore(self.rows_settings())
        d.refresh()
        warn = d._warn_color()
        self.assertEqual(d.plan.z_min, 400.0)
        self.assertIn(f"<span style='color:{warn}'>2 run below the frame: HW-3 (TD 160′), HW-1 (TD 400′); SW-1: water "
                      f"level below the frame</span>", d.explo_readout.text())
        d.depth_line.setChecked(False)                              # no line reaches below the frame at all
        d.refresh()
        self.assertEqual(d.plan.z_min, 450.0)
        self.assertIn(f" · <span style='color:{warn}'>SW-1: water level below the frame</span>", d.explo_readout.text())
        d.z_mode.setCurrentIndex(d.z_mode.findData("manual"))       # HW-3's ATD (464.5) below the frame too
        d.z_min.setValue(500.0)
        d.z_max.setValue(600.0)
        d.refresh()
        self.assertEqual(d.plan.z_min, 500.0)
        self.assertIn(f"<span style='color:{warn}'>2 below the frame: HW-3 (water level), SW-1 (water level)</span>",
                      d.explo_readout.text())

    def test_flags_and_sources_per_layer(self):
        d = self.dock
        d.refresh()
        text = d.explo_readout.text()
        self.assertIn("MW-2 (Explorations): ExploElev 205.6 ft ignored", text)
        self.assertIn("Past the ends (left out): 2 (B-pre (Explorations), B-post (Explorations))", text)
        self.assertEqual(d.depth_readout.text(), "Tops: 10 ExploElev, 5 LIDAR, 1 none · Bottoms: 11 top − ExploDepth, "
                                                 "3 top − WellCompleteDepth, 2 none")
        for i in (1, 2):
            explo_row(d, i).visible_box.setChecked(False)
        d.refresh()
        self.assertTrue(d.explo_readout.text().startswith("Plotted <b>7</b><br>Past the ends"), d.explo_readout.text())
        self.assertIn("MW-2: ExploElev", d.explo_readout.text())             # one layer on: no layer names
        explo_row(d, 0).visible_box.setChecked(False)
        d.refresh()
        self.assertEqual(d.explo_readout.text(), "No exploration layer is on: ground line and surfaces only.")
        self.assertEqual(self.chips()["Explorations"], ("Off", False))


# ------------------------------------------------------------------ the Other points section
class OtherPointsSection(LayersCase):
    def setUp(self):
        super().setUp()
        self.restore(self.rows_settings())

    def test_section(self):
        d = self.dock
        i = d.sections.index(d.grp_screens)
        self.assertIs(d.sections[i + 1], d.grp_other)
        self.assertEqual((d.grp_other.title(), d.grp_other.objectName()), ("Other points", "xsectionsOtherGroup"))
        self.assertEqual(d.btn_add_other.text(), "+ Add point layer")
        self.assertTrue(d.grp_explo.isAncestorOf(d.plotted) and d.grp_explo.isAncestorOf(d.btn_add_points))
        self.assertEqual(self.chips()["Other points"], ("Seeps", False))      # before a model
        d.refresh()
        self.assertEqual(self.chips()["Other points"], ("Seeps · 4 plotted", False))
        self.assertEqual(d.other_readout.text().split("<br>"),
                         ["Seeps: 4 plotted · 1 more within 375 ft", "S-1 on the ground line", "S-2 on the ground line",
                          "S-5 on the ground line", "S-3 on the ground line"])
        row = other_row(d)
        self.assertEqual(row.elev_hint.text(), "Each point sits on the ground line drawn along A–A′, just touching "
                                               "it. Choose LIDAR or a field to show its own elevation.")
        d.start_label.setText("B")
        d.end_label.setText("B'")
        self.assertIn("drawn along B–B′", row.elev_hint.text())
        self.assertTrue(row.elev_field_row.isHidden())
        row.elev_seg.setCurrentIndex(row.elev_seg.findData("field"))            # From a field
        self.assertFalse(row.elev_field_row.isHidden())
        self.assertEqual(row.value()["elev_field"], "Elev_ft")
        self.assertEqual(row.elev_hint.text(), "The centre of the symbol marks the elevation. Where Elev_ft is empty, "
                                               "the point sits on the ground line.")
        self.assertIn("Elev_ft, else on the ground line", row.sub_label.text())
        self.assertTrue(d._user_changed)
        d.refresh()
        lines = d.other_readout.text().split("<br>")
        self.assertEqual(lines[1], "S-1 (no Elev_ft) on the ground line")
        self.assertRegex(lines[2], r"^S-2 at Elev_ft \d+\.\d ft, \d\.\d ft above the ground line$")
        self.assertEqual(lines[4], "S-3 (no Elev_ft) on the ground line")       # 0 counts as missing
        row.empty_seg.setCurrentIndex(row.empty_seg.findData("off"))
        d.refresh()
        self.assertEqual(d.other_readout.text().split("<br>")[0],
                         "Seeps: 2 plotted · 1 more within 375 ft · 2 left out (no Elev_ft)")
        row.elev_seg.setCurrentIndex(row.elev_seg.findData("lidar"))
        d.refresh()
        self.assertRegex(d.other_readout.text(), r"S-1 at LIDAR \d+\.\d ft, (level with|\d\.\d ft (above|below)) "
                                                 r"the ground line")
        row.visible_box.setChecked(False)
        d.refresh()
        self.assertEqual((d.other_readout.text(), self.chips()["Other points"]), ("No point layer is on.", ("Off", False)))

    def test_no_elevation_field_chosen(self):
        """(FIX 0.3.3) "From a field" with no elevation field chosen: the readout says "(no field)", as the row's
        subtitle and the hover do (never "(no )")."""
        d = self.restore(self.rows_settings(other_points=[seep_row(self.seeps, label_field="Name", elev="field",
                                                                   elev_field="")]))
        self.assertEqual(other_row(d).value()["elev_field"], "")
        d.refresh()
        text = d.other_readout.text()
        self.assertIn("S-1 (no field) on the ground line", text)
        self.assertNotIn("(no )", text)
        row = other_row(d)
        row.empty_seg.setCurrentIndex(row.empty_seg.findData("off"))
        d.refresh()
        self.assertEqual(d.other_readout.text(), "Seeps: 0 plotted · 1 more within 375 ft · 4 left out (no field)")

    def test_every_flag_is_shown(self):
        """(FIX 0.3.3) More than six flags of other points: six in the Other points readout, the others in the
        message line; every one is shown somewhere."""
        from qgis.PyQt.QtCore import QMetaType
        rows = []
        for i in range(8):                                          # each 30 ft above the LIDAR: flagged (> 25 ft)
            x, y = point_at(400.0 + 300.0 * i, 10.0)
            rows.append((x, y, [f"SP-{i + 1}", "Spring", round(plane_z(x, y) + 30.0, 2)]))
        springs = _memory_points("Springs", [("Name", QMetaType.Type.QString), ("Type", QMetaType.Type.QString),
                                             ("Elev_ft", QMetaType.Type.Double)], rows)
        self.prj.addMapLayer(springs)
        d = self.restore(self.rows_settings(other_points=[seep_row(springs, label_field="Name", elev="field",
                                                                   elev_field="Elev_ft")]))
        d.refresh()
        flags = [f"{p.label}: {fl}" for p in d.model.other_points for fl in p.flags]
        self.assertEqual(len(flags), 8)
        readout, message = d.other_readout.text(), d.message.text()
        self.assertIn("… and 2 more flags (in the message line below)", readout)
        for f in flags:
            self.assertTrue((f in readout) != (f in message), f)      # in one of the two, not both


# ------------------------------------------------------------------ Color rows follow the layer's style (0.3.4)
SUPPLY_CATS = [("DOMESTIC", "Domestic", "#df9560"), ("PUBLIC SUPPLY", "Public supply", "#3fcaa2"),
               ("SPRING WELL , GRP A/B/DOM", "Spring well", "#80a7ea"), (None, "", "#e049db")]


class StyleFollow(LayersCase):
    """styleChanged of an exploration row's layer: the row's style box is read again and, for a ticked Color row, the
    section rebuilt; nothing is saved."""

    def setUp(self):
        super().setUp()
        for lyr in (self.pts, self.supply, self.seeps):
            lyr.setRenderer(single_renderer("#987db7"))                 # (fixed: a memory layer's is random)

    def color_settings(self):
        s = self.rows_settings()
        s.point_layers[2] = dict(s.point_layers[2], look="color", visible=True)
        return s

    def calm(self, d) -> None:
        d._timer.stop()
        d._stale = False
        d._user_changed = False

    def conns(self, d):
        return {(lid, name) for lid, name, _slot in d._layer_conns}

    def test_a_color_row_follows_its_style(self):
        d = self.restore(self.color_settings())
        saved = settings_store.stored_json(self.prj)
        row = explo_row(d, 2)
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#987db7")])
        self.assertIn((self.supply.id(), "styleChanged"), self.conns(d))
        self.assertIn((self.pts.id(), "styleChanged"), self.conns(d))           # every row's layer, any look
        self.assertNotIn((self.seeps.id(), "styleChanged"), self.conns(d))      # (an Other points layer)
        self.calm(d)
        self.supply.setRenderer(categorized_renderer("ExploType_resolved", SUPPLY_CATS))
        self.assertEqual(row.style_box.head.text(), "From the layer's style in QGIS: <b>Categorized by "
                                                    "ExploType_resolved</b> · 4 categories")
        self.assertEqual(row.swatch.colors(), [c for _v, _l, c in SUPPLY_CATS[:3]])
        self.assertTrue(d._stale and d._timer.isActive())
        self.assertFalse(d._user_changed)
        # a category unticked (in place: nothing emitted until the Layers panel's styleChanged)
        self.calm(d)
        key = row.current_style().items[0].key
        self.supply.renderer().checkLegendSymbolItem(key, False)
        self.assertTrue(row.style_box.off_note.isHidden())
        self.supply.emitStyleChanged()
        self.assertEqual(row.style_box.off_note.text(), "1 switched off in QGIS: their explorations are drawn in "
                                                        "black.")
        self.assertTrue(d._stale and d._timer.isActive())
        self.assertFalse(d._user_changed)
        self.assertEqual(settings_store.stored_json(self.prj), saved)              # nothing saved
        # a Black row of a layer: its box (hidden) is read again, the section is not rebuilt
        self.calm(d)
        black = explo_row(d, 0)
        self.pts.setRenderer(single_renderer("#00aa00"))
        self.assertEqual(black.current_style().items[0].color, "#00aa00")
        self.assertTrue(black.style_box.isHidden())
        self.assertFalse(d._stale or d._timer.isActive())
        # an unticked Color row: no rebuild either
        explo_row(d, 2).visible_box.setChecked(False)
        self.calm(d)
        self.supply.emitStyleChanged()
        self.assertFalse(d._stale or d._timer.isActive())

    def test_black_to_color_needs_no_new_connection(self):
        d = self.restore(self.color_settings())
        row = explo_row(d, 0)
        with mock.patch.object(d, "_track_layer_signals", wraps=d._track_layer_signals) as track:
            row.look_seg.buttons()[row.look_seg.findData("color")].click()
            self.assertEqual(track.call_count, 0)
        self.assertEqual(row.value()["look"], "color")
        self.assertTrue(d._user_changed)                                         # (his edit)
        self.calm(d)
        self.pts.setRenderer(single_renderer("#c2185b"))
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#c2185b")])
        self.assertEqual(row.swatch.colors(), ["#c2185b"])
        self.assertTrue(d._stale and d._timer.isActive())
        self.assertFalse(d._user_changed)

    def test_a_layer_tracked_for_another_row(self):
        """The seeps layer, tracked through its Other points row, picked in an exploration row (no tracked id
        changes): its styleChanged is connected then."""
        s = self.rows_settings()
        s.point_layers = [s.point_layers[0], dict(s.point_layers[0], look="color")]
        d = self.restore(s)
        self.assertIn((self.seeps.id(), "dataChanged"), self.conns(d))
        self.assertNotIn((self.seeps.id(), "styleChanged"), self.conns(d))
        row = explo_row(d, 1)
        row.layer_combo.setLayer(self.seeps)                                    # his choice
        self.assertEqual(row.value()["layer_id"], self.seeps.id())
        self.assertIn((self.seeps.id(), "styleChanged"), self.conns(d))
        self.calm(d)
        self.seeps.setRenderer(single_renderer("#1f6fb2"))
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#1f6fb2")])
        self.assertTrue(d._timer.isActive())
        # the water-level table: any vector layer; picked in a row afterwards, the same
        s = self.rows_settings()
        s.point_layers[0] = dict(s.point_layers[0], wl_table_id=self.supply.id(), wl_table_name_field="AESI_MapLabel",
                                 wl_table_elev_field="GW_Elev_ATD")
        s.point_layers[2] = dict(s.point_layers[2], layer_id=self.others.id(), look="color")
        d = self.restore(s, self.new_dock())
        self.assertNotIn((self.supply.id(), "styleChanged"), self.conns(d))
        explo_row(d, 2).layer_combo.setLayer(self.supply)
        self.assertIn((self.supply.id(), "styleChanged"), self.conns(d))
        self.supply.setRenderer(single_renderer("#b7484b"))
        self.assertEqual(explo_row(d, 2).style_box.chips.items(), [("every exploration", "#b7484b")])

    def test_the_sheet_follows(self):
        d = self.restore(self.color_settings())
        d.refresh()
        self.assertEqual(d.last_error, "")
        supply = [h for h in d.model.hits if h.layer_index == 2]
        self.assertTrue(supply)
        self.assertEqual({(h.look, h.color) for h in supply}, {("color", "#987db7")})
        self.assertEqual(explo_row(d, 2)._plotted_keys, {"0"})
        self.supply.setRenderer(categorized_renderer("ExploType_resolved", SUPPLY_CATS))
        self.assertTrue(d._timer.isActive())
        d.refresh()
        colors = {h.label: h.color for h in d.model.hits if h.layer_index == 2}
        want = {"HW-1": "#df9560", "HW-3": "#3fcaa2", "SW-1": "#80a7ea", "HW-2": "#e049db"}
        self.assertEqual(colors, {k: v for k, v in want.items() if k in colors})
        st = d.model.point_layers[2].style
        row = explo_row(d, 2)
        self.assertEqual(row._plotted_keys, {st.items[h.style_rank].key for h in d.model.hits if h.layer_index == 2})
        plotted = [lab for _v, lab, _c in SUPPLY_CATS if (lab or "(no value)") in
                   {st.items[h.style_rank].label for h in d.model.hits if h.layer_index == 2}]
        self.assertEqual([lab for lab, _c in row.style_box.chips.items()][:len(plotted)],
                         [lab or "(no value)" for lab in plotted])
        self.assertEqual({h.color for h in d.model.hits if h.layer_index != 2}, {""})     # Black rows
        d._fail("x", d.settings())
        self.assertIsNone(row._plotted_keys)

    @timing_test
    def test_removed_and_added_layers(self):
        d = self.restore(self.color_settings())
        row = explo_row(d, 2)
        old = self.supply.id()
        self.prj.removeMapLayer(old)
        APP.processEvents()
        self.assertTrue(row.is_missing())
        self.assertNotIn(old, {lid for lid, _n, _s in d._layer_conns})
        self.assertEqual(row.style_box.head.text(), "From the layer's style in QGIS: the layer is not in the project.")
        d._on_point_style_changed(old)                                          # (a late signal: no crash)
        other = make_supply_layer(name="Wells elsewhere")
        self.prj.addMapLayer(other)
        wait(20)
        other.setRenderer(single_renderer("#00aa00"))                          # not a row's layer: nothing
        self.assertTrue(row.is_missing())
        back = make_supply_layer()                                             # the same layer again (its name)
        back.setRenderer(single_renderer("#b7484b"))
        self.prj.addMapLayer(back)
        wait(20)
        self.assertEqual(row.layer(), back)
        self.assertIn((back.id(), "styleChanged"), self.conns(d))
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#b7484b")])
        back.setRenderer(single_renderer("#123456"))
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#123456")])

    def test_cleanup_leaves_no_connection(self):
        d = XSectionsDock(self.iface, None)
        self.restore(self.color_settings(), d)
        row = explo_row(d, 2)
        self.assertTrue(any(name == "styleChanged" for _lid, name, _s in d._layer_conns))
        d.cleanup()
        self.assertEqual(d._layer_conns, [])
        self.supply.setRenderer(single_renderer("#123456"))                    # no longer heard
        self.assertEqual(row.style_box.chips.items(), [("every exploration", "#987db7")])
        d.deleteLater()
        APP.processEvents()


# ------------------------------------------------------------------ budgets
@timing_test
class Budgets(unittest.TestCase):
    """The 3-row section of the fixtures (the 32,000-point dense layer, explorations by others, supply wells)."""

    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.dense, self.others, self.supply = make_dense_layer(), make_others_layer(), make_supply_layer()
        self.prj.addMapLayers([self.dense, self.others, self.supply])
        s = Settings(line_layer_id=self.lines.id(), line_fid=1, dem_layer_id=self.dem.id(), tolerance_ft=TOLERANCE,
                     point_layers=[point_row(self.dense, label_field="ExploName", type_field="ExploType_resolved",
                                             top_field="ExploElev", depth_field="ExploDepth"),
                                   point_row(self.others, label_field="ExploName", type_field="ExploType_resolved",
                                             depth_field="ExploDepth"),
                                   point_row(self.supply, label_field="AESI_MapLabel", type_field="ExploType_resolved",
                                             depth_field="WellCompleteDepth", in_range=False)])
        settings_store.save(self.prj, s)
        self.pv = PreviewWidget()
        self.dock = XSectionsDock(make_iface(), self.pv)
        self.dock.restore_from_project()

    def tearDown(self):
        self.dock.cleanup()
        self.dock.deleteLater()
        self.pv.deleteLater()
        APP.processEvents()
        self.prj.clear()

    def test_refresh_budget(self):
        d = self.dock
        d.refresh()                                                 # (warm: files and fonts opened once)
        t = time.perf_counter()
        d.refresh()
        self.pv.render_pending()
        dt = time.perf_counter() - t
        print(f"\n  refresh of the 3-row section with the preview: {dt:.3f} s")
        self.assertEqual(d.last_error, "")
        self.assertEqual(len(d.model.point_layers), 3)
        self.assertLessEqual(dt, budget(3.0))

    def test_a_toggle_is_one_rebuild_and_no_type_scan(self):
        d = self.dock
        scans = Counter()
        patches = []
        for lyr in (self.dense, self.others, self.supply):
            def counting(request=None, *args, _lyr=lyr, _orig=lyr.getFeatures):
                if request is not None and hasattr(request, "flags") \
                        and request.flags() & Qgis.FeatureRequestFlag.NoGeometry:
                    scans[_lyr.id()] += 1
                return _orig(request, *args) if request is not None else _orig()
            p = mock.patch.object(lyr, "getFeatures", side_effect=counting)
            p.start()
            patches.append(p)
        for p in patches:
            self.addCleanup(p.stop)
        builds = []
        real = d._pipeline
        d._pipeline = lambda s: (builds.append(1), real(s))[1]
        d.resize(340, 700)
        d.show()
        APP.processEvents()
        d.refresh()
        builds.clear()
        scans.clear()
        item = d.plotted.item_for(self.dense.id(), next(h.fid for h in d.model.hits if h.layer_id == self.dense.id()))
        item.setCheckState(0, Qt.CheckState.Unchecked)
        wait(700)
        self.assertEqual(len(builds), 1)
        self.assertEqual(sum(scans.values()), 0)
        self.assertEqual(len(d.model.left_off), 1)
        d.refresh()                                                 # a rebuild never rescans the types
        self.assertEqual(sum(scans.values()), 0)
        d.reload()                                                  # Refresh: once per row
        self.assertEqual(scans, Counter({self.dense.id(): 1, self.others.id(): 1, self.supply.id(): 1}))
        d.hide()


if __name__ == "__main__":
    unittest.main()
