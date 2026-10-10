"""UI tests: dock, settings persistence, map tools, map feedback, preview and the plugin shell.

The core/render pipeline is stubbed with hand-made SectionModel/Plan objects where the test is about
the UI; a few tests run the real core and render code (tests/test_e2e.py drives the whole plugin).
"""
import csv
import dataclasses
import math
import os
import tempfile
import unittest
from unittest import mock

from tests.fixtures import LINE, default_settings, explo_row, line_length, load_project, start_app

APP = start_app()

from matplotlib.figure import Figure  # noqa: E402
from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsField,  # noqa: E402
                       QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer)
from qgis.gui import (QgsAdvancedDigitizingDockWidget, QgsMapMouseEvent, QgsMapToolPan,  # noqa: E402
                      QgsMessageBar)
from qgis.PyQt.QtCore import QEvent, QMetaType, QPoint, Qt  # noqa: E402
from qgis.PyQt.QtGui import QKeyEvent  # noqa: E402
from qgis.PyQt.QtWidgets import QLabel  # noqa: E402

from xsections.core.model import (GroundProfile, Hit, PageLayout, Plan, SectionError,  # noqa: E402
                                  SETTINGS_VERSION, SectionModel, Settings, as_rows, layer_rows)
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import (BOTTOM_ELEV_NAMES, CSV_COLUMNS, DEPTH_NAMES, DRAWN, LABEL_NAMES,  # noqa: E402
                               LINES_LAYER_NAME, NO_TYPES, TOP_NAMES, XSectionsDock, compass16, depth_sources_line,
                               fmt_station, guess_field, reverse_hint)
from xsections.ui.map_feedback import match_stations, match_ticks  # noqa: E402
from xsections.ui.maptools import DrawSectionTool, PickLineTool  # noqa: E402
from xsections.ui.preview import PreviewWidget, overlay_sheets, sheet_tags  # noqa: E402


CRS = "EPSG:2927"


# ------------------------------------------------------------------ helpers
def make_iface():
    """qgis.testing's mocked iface, with a real CAD dock and message bar (and no second QgsApplication)."""
    import qgis.testing as qt
    qt.QGISAPP = QgsApplication.instance()
    from qgis.testing.mocked import get_iface
    iface = get_iface()
    canvas = iface.mapCanvas()
    iface.cadDockWidget.return_value = QgsAdvancedDigitizingDockWidget(canvas, iface.mainWindow())
    iface.messageBar.return_value = QgsMessageBar(iface.mainWindow())
    iface.activeLayer.return_value = None
    return iface


def show_canvas(canvas, layers):
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem(CRS))
    canvas.setLayers(layers)
    canvas.window().resize(700, 500)
    canvas.window().show()
    canvas.resize(600, 400)
    APP.processEvents()
    ext = QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE]).boundingBox()
    ext.grow(400.0)
    canvas.setExtent(ext)
    canvas.refresh()
    APP.processEvents()


def pixel(canvas, x, y) -> QPoint:
    p = canvas.getCoordinateTransform().transform(QgsPointXY(x, y))
    return QPoint(int(round(p.x())), int(round(p.y())))


def click(tool, canvas, x, y, button=Qt.MouseButton.LeftButton):
    pos = pixel(canvas, x, y)
    for typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        e = QgsMapMouseEvent(canvas, typ, pos, button, button, Qt.KeyboardModifier.NoModifier)
        (tool.canvasPressEvent if typ == QEvent.Type.MouseButtonPress else tool.canvasReleaseEvent)(e)


def press_escape(tool):
    tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


def fake_model():
    """A consistent SectionModel for the fixture LINE (no core needed)."""
    L = line_length()
    stations = [0.0, 1000.0, 2000.0, 2500.0, 3000.0, 3900.0, 3960.0, L]
    z = [505.0, 515.0, 525.0, 530.0, 540.0, math.nan, math.nan, 560.0]
    ground = GroundProfile(stations=stations, z=z, step=3.0, gaps=[(3900.0, 3960.0)], coverage=0.97)
    hits = [
        Hit(fid=1, label="B-1", type_value="Boring", x=LINE[0][0] + 300, y=LINE[0][1] + 40, station=300.0,
            offset=40.0, side="L", direction="N", ground_at_station=508.0, ground_at_point=508.2, top=508.2,
            top_source="field", bottom=478.2, bottom_source="depth", total_depth=30.0),
        Hit(fid=5, label="MW-2", type_value="Monitoring Well", x=LINE[1][0] - 100, y=LINE[1][1] + 90,
            station=2900.0, offset=90.0, side="L", direction="N", ground_at_station=538.0, ground_at_point=539.0,
            top=539.0, top_source="dem", bottom=504.0, flags=["ExploElev 205.6 ft ignored: 333.4 ft from LIDAR"],
            bottom_source="depth", total_depth=35.0),
    ]
    line_wkt = QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE]).asWkt()
    return SectionModel(length=L, vertex_stations=[0.0, 2500.0, L], azimuth=82.0, ground=ground, hits=hits,
                        beyond_ends=["B-pre", "B-post"], near_count=1,
                        warnings=["The DEM does not state its elevation units; assumed feet.",
                                  "MW-2: ExploElev 205.6 ft ignored: 333.4 ft from LIDAR",
                                  "Left out past the ends of the line: B-pre, B-post."],
                        section_crs_wkt=QgsCoordinateReferenceSystem(CRS).toWkt(), line_wkt=line_wkt,
                        dem_name="LIDAR_DEM_3ft", points_name="Explorations", dist_factor=1.0)


def fake_plan(tiled=False, fits=True):
    if tiled:
        pages = [PageLayout(17, 11, "Tabloid 17 × 11 in, landscape", 1.0, 2.3, 14.0, 5.0, 0.0, 2800.0, 1, 2,
                            None, 2600.0),
                 PageLayout(17, 11, "Tabloid 17 × 11 in, landscape", 1.0, 2.3, 11.0, 5.0, 2400.0, 4600.0, 2, 2,
                            2600.0, None)]
    else:
        pages = [PageLayout(11, 8.5, "Letter 11 × 8.5 in, landscape", 2.0, 2.3, 4.6, 5.0, 0.0, 4600.0)]
    return Plan(z_min=400.0, z_max=650.0, plot_length=4600.0, h_major=1000.0, h_minor=100.0, v_major=50.0,
                v_minor=5.0, pages=pages, fits=fits, message="" if fits else "Needs 30 × 9 in: too long.",
                lowest_z=462.0, lowest_what="the bottom of B-2")


# ------------------------------------------------------------------ pure helpers
class HelperTests(unittest.TestCase):
    def test_guess_field(self):
        self.assertEqual(guess_field(["fid", "EXPLONAME", "ExploID"], LABEL_NAMES), "EXPLONAME")
        self.assertEqual(guess_field(["id", "Name"], LABEL_NAMES), "Name")
        self.assertEqual(guess_field(["explo_depth", "Depth"], DEPTH_NAMES), "explo_depth")
        self.assertEqual(guess_field(["a", "b"], LABEL_NAMES), "")
        # whole names only (ignoring case, _ - and spaces), never a part of a name
        self.assertEqual(guess_field(["botqvr", "BOT_ELEV"], BOTTOM_ELEV_NAMES), "BOT_ELEV")
        self.assertEqual(guess_field(["botqvr", "bottom", "elev_bot", "TDX"], BOTTOM_ELEV_NAMES), "")
        self.assertEqual(guess_field(["td_elev"], BOTTOM_ELEV_NAMES), "td_elev")
        self.assertEqual(guess_field(["Depth_ft", "TD"], DEPTH_NAMES), "TD")        # most specific first
        self.assertEqual(guess_field(["depthft"], DEPTH_NAMES), "depthft")
        self.assertEqual(guess_field(["TDepth", "Depth2"], DEPTH_NAMES), "")
        self.assertEqual(guess_field(["Elev", "gs_elev"], TOP_NAMES), "gs_elev")
        self.assertEqual(guess_field(["ElevNote"], TOP_NAMES), "")

    def test_formatting(self):
        self.assertEqual(compass16(0.0), "N")
        self.assertEqual(compass16(82.0), "E")
        self.assertEqual(compass16(250.0), "WSW")
        self.assertEqual(fmt_station(2600.0), "26+00")
        self.assertEqual(fmt_station(3242.6), "32+43")
        self.assertEqual(reverse_hint(82.0, "A", "A'"), "")
        self.assertIn("west to east", reverse_hint(250.0, "A", "A'"))
        self.assertIn("south to north", reverse_hint(180.0, "A", "A'"))

    def test_match_ticks(self):
        line = QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE])
        self.assertEqual(match_stations(fake_plan(tiled=True)), [2600.0])
        self.assertEqual(match_stations(fake_plan()), [])
        (st, (p1, p2)), = match_ticks(line, [1000.0], 1.0, 100.0)
        # first segment runs east, so the tick runs north-south through (x0 + 1000, y0)
        self.assertAlmostEqual(p1.x(), LINE[0][0] + 1000.0, places=6)
        self.assertAlmostEqual(abs(p1.y() - p2.y()), 200.0, places=6)


class SettingsStoreTests(unittest.TestCase):
    def test_project_roundtrip(self):
        prj = QgsProject.instance()
        prj.clear()
        self.assertIsNone(settings_store.load(prj))
        s = Settings(h_scale=200.0, types=["Boring"], tolerance_ft=80.0, line_wkt="LineString (0 0, 1 1)")
        self.assertTrue(settings_store.save(prj, s))
        self.assertFalse(settings_store.save(prj, s), "unchanged settings are not rewritten")
        self.assertEqual(settings_store.load(prj), s)
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY, "{not json")
        self.assertIsNone(settings_store.load(prj))
        settings_store.clear(prj)
        self.assertIsNone(settings_store.load(prj))

    def test_bad_values_fall_back_to_defaults(self):
        prj = QgsProject.instance()
        prj.clear()
        for text in ("null", "[]", '"x"', "3"):
            prj.writeEntry(settings_store.SCOPE, settings_store.KEY, text)
            self.assertIsNone(settings_store.load(prj), text)
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY,
                       '{"h_scale": null, "tolerance_ft": "150", "dem_band": null, "types": "Boring", '
                       '"line_fid": "3", "depth_line": 1, "v_scale": 20, "dpi": 600.0, "title": "Site X", '
                       '"allowed_sheets": ["letter", 5], "unknown_key": 1}')
        s = settings_store.load(prj)
        d = Settings()
        self.assertEqual((s.h_scale, s.tolerance_ft, s.dem_band, s.types, s.line_fid, s.depth_line),
                         (d.h_scale, d.tolerance_ft, d.dem_band, d.types, d.line_fid, d.depth_line))
        self.assertEqual((s.v_scale, s.dpi, s.title, s.allowed_sheets), (20.0, 600, "Site X", d.allowed_sheets))
        self.assertIsInstance(s.v_scale, float)
        prj.clear()


# ------------------------------------------------------------------ the dock
class DockTests(unittest.TestCase):
    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.iface = make_iface()
        self.canvas = self.iface.mapCanvas()
        self.preview = mock.Mock()
        self.dock = XSectionsDock(self.iface, self.preview)
        self.dock.restore_from_project()

    def tearDown(self):
        self.dock.cleanup()
        self.dock.deleteLater()
        APP.processEvents()

    def stub(self, model=None, plan=None, exc=None):
        def pipeline(_s):
            if exc is not None:
                raise exc
            return model or fake_model(), plan or fake_plan()
        self.dock._pipeline = pipeline

    # ---- construction and defaults
    def test_combos_filled_from_project(self):
        d = self.dock
        self.assertIs(d.dem_layer.currentLayer(), self.dem)
        self.assertIs(explo_row(d).layer_combo.currentLayer(), self.pts)
        self.assertIs(d.line_layer.currentLayer(), self.lines)
        self.assertEqual(d.line_feature.currentData(), 1)
        self.assertEqual(d.line_feature.currentText(), "A")
        self.assertEqual(explo_row(d).label_field.currentField(), "ExploName")
        self.assertEqual(explo_row(d).type_field.currentField(), "ExploType")
        self.assertEqual(explo_row(d).top_field.currentField(), "ExploElev")
        self.assertEqual(explo_row(d).bottom_elev_field.currentField(), "")   # the fixture has no bottom elevations
        self.assertEqual(explo_row(d).depth_field.currentField(), "ExploDepth")
        self.assertEqual(d.dem_band.currentBand(), 1)
        rows = {explo_row(d).type_list.topLevelItem(i).text(0): explo_row(d).type_list.topLevelItem(i).text(1)
                for i in range(explo_row(d).type_list.topLevelItemCount())}
        self.assertEqual(rows, {"Boring": "6", "CPT": "1", "Monitoring Well": "2", "Test Pit": "1"})
        s = d.settings()
        self.assertEqual(layer_rows(s)[0]["types"], [])
        self.assertEqual((s.dem_layer_id, layer_rows(s)[0]["layer_id"], s.line_layer_id, s.line_fid),
                         (self.dem.id(), self.pts.id(), self.lines.id(), 1))
        self.assertEqual(s.tolerance_ft, Settings().tolerance_ft)

    def test_fresh_dock_shows_the_default_layout(self):
        """A fresh project shows the defaults of 0.1.2: compact layout on, grid filled below the section."""
        d = self.dock
        self.assertTrue(d.compact_layout.isChecked())
        self.assertEqual(d.fill_grid.currentText(), "Below")          # a segmented button (0.2)
        self.assertEqual(d.edge_margin.currentData(), 0.5)
        self.assertTrue(d.show_notes.isChecked())
        s, defaults = d.settings(), Settings()
        self.assertEqual((s.compact_layout, s.edge_margin_in, s.show_notes, s.fill_grid),
                         (defaults.compact_layout, defaults.edge_margin_in, defaults.show_notes, defaults.fill_grid))
        self.assertEqual((s.compact_layout, s.fill_grid), (True, "below"))
        # a panel just built (nothing restored yet), and one whose project was closed
        other = XSectionsDock(self.iface, None)
        try:
            self.assertEqual((other.compact_layout.isChecked(), other.fill_grid.currentData()), (True, "below"))
            other.apply_settings(Settings(compact_layout=False, fill_grid="both"))
            other.project_cleared()
            self.assertEqual((other.compact_layout.isChecked(), other.fill_grid.currentData()), (True, "below"))
        finally:
            other.cleanup()
            other.deleteLater()
        # every choice is shown and read back
        for compact in (False, True):
            for fill in ("off", "below", "both"):
                d.apply_settings(dataclasses.replace(s, compact_layout=compact, fill_grid=fill))
                self.assertEqual((d.settings().compact_layout, d.settings().fill_grid), (compact, fill))

    def test_settings_roundtrip_through_widgets(self):
        s = default_settings(self.prj, self.dem, self.pts, self.lines, h_scale=200.0, v_scale=20.0,
                             types=["Boring", "CPT"], label_offset=True, label_vertical=False, depth_line=False,
                             top_mode="dem", grid_auto=False, h_major=500.0, h_minor=50.0, v_major=10.0,
                             v_minor=2.0, z_mode="manual", z_min=400.0, z_max=700.0, below_in=0.5,
                             fill_grid="both", distance_labels="station", sheet="tabloid",
                             allowed_sheets=["letter", "tabloid", "ansid"], tile=False, export_format="png",
                             dpi=600, title="Site X", grid_color="custom", grid_major_color="#1f6fb2",
                             grid_major_width=1.25, grid_major_style="dash", grid_minor_color="#c2185b",
                             grid_minor_width=0.5, grid_minor_style="dot", grid_custom_used=True,
                             depth_lw_black=1.0, depth_lw_color=2.25, shade_below=True, show_bends=False,
                             compact_layout=False, edge_margin_in=0.3, show_notes=False,
                             start_label="B", end_label="B'", vertical_datum="NGVD29", dem_z_units="ft",
                             tolerance_ft=75.0, zero_is_missing=False, top_max_diff_ft=10.0, td_label=False)
        self.dock.apply_settings(s)
        self.assertEqual(self.dock.settings(), as_rows(s))

        drawn = Settings(dem_layer_id=self.dem.id(), points_layer_id=self.pts.id(), label_field="ExploName",
                         line_wkt="LineString (1200600 652000, 1204000 652100)", line_crs_authid=CRS,
                         types=[NO_TYPES], type_field="ExploType", depth_field="ExploDepth", top_field="ExploElev")
        self.dock.apply_settings(drawn)
        self.assertEqual(self.dock.line_feature.currentData(), DRAWN)
        self.assertEqual(self.dock.settings(), as_rows(drawn))

    def test_type_checks(self):
        d = self.dock
        explo_row(d).btn_types_none.click()
        self.assertEqual(layer_rows(d.settings())[0]["types"], [NO_TYPES])
        explo_row(d).type_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)      # Boring
        self.assertEqual(layer_rows(d.settings())[0]["types"], ["Boring"])
        explo_row(d).btn_types_all.click()
        self.assertEqual(layer_rows(d.settings())[0]["types"], [])
        explo_row(d).type_field.setField("")
        self.assertEqual(layer_rows(d.settings())[0]["types"], [])
        self.assertFalse(explo_row(d).type_list.isEnabled())

    def test_new_points_layer_guesses_fields(self):
        lyr = QgsVectorLayer(f"Point?crs={CRS}", "Borings", "memory")
        # BOT_ELEV is text here: the number boxes only guess number fields, so BtmElev is chosen
        lyr.dataProvider().addAttributes([QgsField(n, QMetaType.Type.QString) for n in ("Name", "Type", "BOT_ELEV")] +
                                         [QgsField(n, QMetaType.Type.Double) for n in ("TopElev", "TotalDepth", "BtmElev")])
        lyr.updateFields()
        f = QgsFeature(lyr.fields())
        f.setAttributes(["X-1", "Pit", "n/a", 500.0, 12.0, 488.0])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*LINE[0])))
        lyr.dataProvider().addFeatures([f])
        self.prj.addMapLayer(lyr)
        explo_row(self.dock).layer_combo.setLayer(lyr)
        d = explo_row(self.dock)
        self.assertEqual((d.label_field.currentField(), d.type_field.currentField(), d.top_field.currentField(),
                          d.bottom_elev_field.currentField(), d.depth_field.currentField()),
                         ("Name", "Type", "TopElev", "BtmElev", "TotalDepth"))
        self.assertEqual(d.type_list.topLevelItemCount(), 1)

    def test_user_change_is_saved_and_restored(self):
        self.stub()
        self.prj.setDirty(False)
        self.dock.refresh()
        self.assertFalse(self.prj.isDirty(), "opening/refreshing must not dirty the project")
        self.assertEqual(settings_store.stored_json(self.prj), "")
        self.dock.tolerance.setValue(80.0)          # user edit
        self.dock._on_timer()
        self.assertEqual(settings_store.load(self.prj).tolerance_ft, 80.0)
        self.assertTrue(self.prj.isDirty())
        other = XSectionsDock(self.iface, None)
        try:
            other.restore_from_project()
            self.assertEqual(other.settings(), self.dock.settings())
        finally:
            other.cleanup()
            other.deleteLater()

    # ---- top-to-bottom line (R1, R3)
    def test_depth_group_widgets(self):
        d = self.dock
        combos = (explo_row(d).top_field, explo_row(d).bottom_elev_field, explo_row(d).depth_field)
        from qgis.core import QgsFieldProxyModel
        for c in combos:
            self.assertTrue(c.allowEmptyFieldName())
            self.assertEqual(c.filters(), QgsFieldProxyModel.Filter.Numeric        # 0.3.5: and text fields
                             | QgsFieldProxyModel.Filter.String)
        self.assertEqual([d.top_mode.itemText(i) for i in range(d.top_mode.count())],
                         ["Table, else LIDAR at the exploration", "LIDAR at the exploration", "Table only"])
        self.assertEqual(d.depth_line.text(), "Depth line")                 # (0.3.6: the mockup's names)
        self.assertEqual(d.td_label.text(), "TD label")
        self.assertTrue(d.td_label.isChecked() and d.depth_line.isChecked() and d.zero_missing.isChecked())
        self.assertEqual(d.top_max_diff.value(), 25.0)
        self.assertFalse(hasattr(d, "bottom_mode"))
        texts = [w.text() for w in d.grp_depth.findChildren(QLabel)]
        # (0.3.6: the note is each row's Verbose hint on its Depths tab)
        self.assertEqual(explo_row(d).depths_hint.text(),
                         "Top from the table, else LIDAR; bottom from the table, else top − depth.")
        self.assertIn("Ignore a table top off LIDAR by over", texts)
        # enabled states follow the line and the top source
        d.top_mode.setCurrentIndex(d.top_mode.findData("dem"))
        self.assertFalse(explo_row(d).top_field.isEnabled())
        self.assertFalse(d.top_max_diff.isEnabled())
        self.assertTrue(explo_row(d).depth_field.isEnabled())
        # ... but the same limit checks a table bottom against top - depth when both fields are chosen
        explo_row(d).bottom_elev_field.setField("ExploDepth")
        self.assertTrue(d.top_max_diff.isEnabled())
        explo_row(d).bottom_elev_field.setField("")
        self.assertFalse(d.top_max_diff.isEnabled())
        d.top_mode.setCurrentIndex(d.top_mode.findData("field_then_dem"))
        self.assertTrue(explo_row(d).top_field.isEnabled() and d.top_max_diff.isEnabled())
        d.depth_line.setChecked(False)
        for w in (d.top_mode, explo_row(d).top_field, explo_row(d).bottom_elev_field, explo_row(d).depth_field,
                  d.zero_missing, d.td_label, d.top_max_diff):
            self.assertFalse(w.isEnabled())
        self.assertFalse(d.settings().depth_line)
        d.depth_line.setChecked(True)
        d.td_label.setChecked(False)
        self.assertFalse(d.settings().td_label)

    def test_bottom_elevation_roundtrip(self):
        prj, dem, pts, lines = load_project(bot_elev=True)
        d = XSectionsDock(self.iface, None)
        try:
            d.restore_from_project()
            self.assertEqual((explo_row(d).bottom_elev_field.currentField(), explo_row(d).depth_field.currentField()),
                             ("BotElev", "ExploDepth"))                  # guessed from the names
            s = default_settings(prj, dem, pts, lines, bottom_elev_field="BotElev", depth_field="",
                                 top_mode="field", td_label=False, top_max_diff_ft=12.5)
            d.apply_settings(s)
            self.assertEqual(d.settings(), as_rows(s))
            self.assertEqual(explo_row(d).depth_field.currentField(), "")   # "none" is kept, not re-guessed
            d.refresh()                                                  # the real pipeline
            self.assertEqual(d.last_error, "")
            by = {h.label: h for h in d.model.hits}
            self.assertEqual(by["B-1"].bottom_source, "field")
            self.assertEqual(by["MW-1"].bottom_source, "none")          # no BotElev and no depth field
            readout = d.depth_readout.text()
            self.assertTrue(readout.startswith("Tops: "), readout)
            self.assertIn("BotElev", readout)
            self.assertIn(" · Bottoms: ", readout)
        finally:
            d.cleanup()
            d.deleteLater()

    def test_sources_readout(self):
        from xsections.ui import widgets as W
        W.set_verbose(True)                                  # (0.3.6: the readouts are Verbose notes)
        self.addCleanup(W.set_verbose, False)
        self.stub()
        self.dock.refresh()
        self.assertEqual(self.dock.depth_readout.text(), "Tops: 1 ExploElev, 1 LIDAR · Bottoms: 2 top − ExploDepth")
        self.assertFalse(self.dock.depth_readout.isHidden())
        m = fake_model()
        m.hits[0].bottom_source, m.hits[1].bottom_source, m.hits[1].bottom = "field", "none", None
        s = Settings(top_field="ExploElev", bottom_elev_field="BotElev", depth_field="ExploDepth")
        self.assertEqual(depth_sources_line(m.hits, s), "Tops: 1 ExploElev, 1 LIDAR · Bottoms: 1 BotElev, 1 none")
        m.hits[1].bottom_source = "shifted"          # a table bottom moved with its rejected table top
        self.assertEqual(depth_sources_line(m.hits, s),
                         "Tops: 1 ExploElev, 1 LIDAR · Bottoms: 1 BotElev, 1 BotElev shifted with the top")
        self.assertEqual(depth_sources_line(m.hits, Settings(depth_line=False)), "")
        self.assertEqual(depth_sources_line([], s), "")

    def test_old_settings_are_migrated(self):
        """A project saved by version 1 (one bottom field read as a depth or as an elevation)."""
        old = {"version": 1, "points_layer_id": self.pts.id(), "dem_layer_id": self.dem.id(),
               "label_field": "ExploName", "top_field": "ExploElev", "bottom_mode": "depth",
               "bottom_field": "ExploDepth", "tolerance_ft": 90.0, "old_key": 3}
        import json
        s = Settings.from_json(json.dumps(old))
        self.assertEqual((layer_rows(s)[0]["depth_field"], layer_rows(s)[0]["bottom_elev_field"], s.version,
                          s.tolerance_ft), ("ExploDepth", "", SETTINGS_VERSION, 90.0))
        self.assertFalse(hasattr(s, "bottom_mode"))
        s = Settings.from_json(json.dumps({**old, "bottom_mode": "elevation", "bottom_field": "BotElev"}))
        self.assertEqual((layer_rows(s)[0]["depth_field"], layer_rows(s)[0]["bottom_elev_field"]), ("", "BotElev"))
        s = Settings.from_json(json.dumps({**old, "bottom_field": ""}))
        self.assertEqual((layer_rows(s)[0]["depth_field"], layer_rows(s)[0]["bottom_elev_field"]), ("", ""))
        self.assertTrue(s.td_label)
        # through the project store and the panel
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(old))
        loaded = settings_store.load(self.prj)
        self.assertEqual((layer_rows(loaded)[0]["depth_field"], layer_rows(loaded)[0]["bottom_elev_field"],
                          loaded.tolerance_ft), ("ExploDepth", "", 90.0))
        self.dock.restore_from_project()
        self.assertEqual(explo_row(self.dock).depth_field.currentField(), "ExploDepth")
        self.assertEqual(explo_row(self.dock).bottom_elev_field.currentField(), "")
        self.assertEqual(self.dock.tolerance.value(), 90.0)
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY,
                            json.dumps({**old, "bottom_mode": "elevation", "bottom_field": "ExploDepth"}))
        self.dock.restore_from_project()
        self.assertEqual((explo_row(self.dock).bottom_elev_field.currentField(),
                          explo_row(self.dock).depth_field.currentField()), ("ExploDepth", ""))

    def test_earlier_versions_keep_their_layout(self):
        """Version 3 (0.1.1) stores every layout option: its project keeps its look in the panel, also when saved
        again. Older settings never had them: they get the new defaults (0.1.0 always stored its fill checkbox,
        ticked or not; with or without it, the fill is "below")."""
        import json
        v3 = dataclasses.asdict(default_settings(self.prj, self.dem, self.pts, self.lines, tolerance_ft=90.0,
                                                 compact_layout=False, fill_grid="off"))
        v3["version"] = 3
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(v3))
        d = self.dock
        d.restore_from_project()
        self.assertFalse(d.compact_layout.isChecked())
        self.assertEqual(d.fill_grid.currentData(), "off")
        self.assertEqual(d.tolerance.value(), 90.0)
        self.assertTrue(d.save_settings())                                  # rewritten as version 4 ...
        saved = settings_store.load(self.prj)
        self.assertEqual((saved.version, saved.compact_layout, saved.fill_grid), (SETTINGS_VERSION, False, "off"))
        self.assertEqual(saved, Settings.from_json(json.dumps(v3)))                          # ... unchanged
        since_v3 = ("compact_layout", "edge_margin_in", "show_notes", "fill_grid", "show_bends")
        for version, fill_below in ((2, False), (2, True), (1, None)):       # as 0.1.0 saved them; no fill key
            old = {k: v for k, v in v3.items() if k not in since_v3}
            old["version"] = version
            if fill_below is not None:
                old["fill_below"] = fill_below
            self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(old))
            d.restore_from_project()
            self.assertTrue(d.compact_layout.isChecked(), fill_below)
            self.assertEqual(d.fill_grid.currentData(), "below", fill_below)
            self.assertEqual((d.edge_margin.currentData(), d.show_notes.isChecked()), (0.5, True))
            self.assertEqual(d.tolerance.value(), 90.0)
            loaded = settings_store.load(self.prj)
            self.assertEqual((loaded.compact_layout, loaded.edge_margin_in, loaded.show_notes, loaded.fill_grid),
                             (True, 0.5, True, "below"))

    # ---- no explorations layer (R4)
    def test_ground_only_section(self):
        d = self.dock
        pv = PreviewWidget()
        d.preview = pv
        d.remove_explo_row(explo_row(d))                # what Remove in the row's menu does
        s = d.settings()
        self.assertEqual(layer_rows(s), [])
        d.refresh()                                     # the real pipeline
        self.assertEqual(d.last_error, "")
        m = d.model
        self.assertFalse(m.has_explorations)
        self.assertEqual(m.hits, [])
        self.assertIn("No explorations layer: ground line only", d.explo_readout.text())
        self.assertTrue(d.message.isHidden(), d.message.text())      # a note in the readout, not an error
        self.assertTrue(d.depth_readout.isHidden())
        self.assertEqual(d.feedback.points.numberOfVertices(), 0)
        self.assertEqual(d.feedback.swath.numberOfVertices(), 0)
        pv.render_pending()
        self.assertEqual(pv.last_error, "")
        self.assertTrue(pv.figure.axes)
        self.assertTrue(pv.status.text().startswith("ground line only"))
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_ui_"), "ground.pdf")
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(out, "PDF (*.pdf)")):
            self.assertEqual(d.export_section(), [out])
        from pypdf import PdfReader
        text = PdfReader(out).pages[0].extract_text()
        self.assertIn("CROSS SECTION", text)
        self.assertNotIn("Explorations within", text)
        # the choice sticks: a point layer added later is not picked up by itself
        from tests.fixtures import make_points_layer
        self.prj.addMapLayer(make_points_layer(name="more_wells"))
        self.assertEqual(d.explo_rows, [])
        self.assertEqual(layer_rows(d.settings()), [])
        d.save_settings()
        other = XSectionsDock(self.iface, None)
        try:
            other.restore_from_project()
            self.assertEqual(other.explo_rows, [])
        finally:
            other.cleanup()
            other.deleteLater()

    def test_points_layer_removed_is_an_error(self):
        """The chosen explorations layer is removed (another point layer is left), or a project's saved
        one is missing: the panel says so instead of quietly drawing the ground line only. Choosing none,
        or another layer, clears it."""
        from tests.fixtures import make_points_layer
        d = self.dock
        other = make_points_layer(name="Other wells")
        self.prj.addMapLayer(other)
        APP.processEvents()
        self.assertIs(explo_row(d).layer_combo.currentLayer(), self.pts)
        d.refresh()
        self.assertEqual(d.last_error, "")
        pid = self.pts.id()
        self.prj.removeMapLayer(pid)
        APP.processEvents()
        d.refresh()
        self.assertIsNone(d.model)
        self.assertIn("no longer in the project", d.last_error)
        self.assertIn("no longer in the project", d.message.text())
        self.assertIsNone(explo_row(d).layer_combo.currentLayer())   # not quietly moved to "Other wells"
        self.assertTrue(explo_row(d).name_label.isWarn())            # the row stays, amber
        self.assertEqual(layer_rows(d.settings())[0]["layer_id"], pid)
        d.save_settings()
        self.assertEqual(layer_rows(settings_store.load(self.prj))[0]["layer_id"], pid)   # the next load says so too
        again = XSectionsDock(self.iface, None)
        try:
            again.restore_from_project()
            self.assertIsNone(explo_row(again).layer_combo.currentLayer())
            again.refresh()
            self.assertIn("no longer in the project", again.last_error)
        finally:
            again.cleanup()
            again.deleteLater()
        # the user picks the other layer: explorations again
        explo_row(d).layer_combo.setLayer(other)
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertTrue(d.model.has_explorations and d.model.hits)
        # ... or none: a ground line only
        explo_row(d).layer_combo.setLayer(None)
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertFalse(d.model.has_explorations)

    # ---- refresh
    def test_refresh_updates_preview_readouts_and_map(self):
        self.stub()
        d = self.dock
        d.refresh()
        self.preview.draw.assert_called_once()
        model, s, plan = self.preview.draw.call_args[0]
        self.assertIsInstance(model, SectionModel)
        self.assertEqual(s, d.settings())
        line = d.line_readout.text()
        self.assertIn("4,588 ft", line)
        self.assertIn("3 vertices", line)
        self.assertIn("1 bend", line)
        self.assertIn("(082°)", line)
        self.assertIn("coverage <b>97%", d.ground_readout.text())
        self.assertIn("3,900 ft to 3,960 ft", d.ground_readout.text())
        explo = d.explo_readout.text()
        self.assertIn("Plotted <b>2</b>", explo)
        self.assertIn("B-pre, B-post", explo)
        self.assertIn("ExploElev 205.6 ft ignored", explo)
        exp = d.export_readout.text()
        self.assertIn("VE <b>20×</b>", exp)
        self.assertIn("4.60 × 5.00 in", exp)
        self.assertIn("Letter 11 × 8.5 in", exp)
        self.assertIn("1.24 in of grid below the bottom of B-2", exp)
        tl = explo_row(d).type_list
        counts = {tl.topLevelItem(i).text(0): tl.topLevelItem(i).text(1) for i in range(tl.topLevelItemCount())}
        self.assertEqual(counts["Boring"], "1 / 6")
        self.assertEqual(counts["Monitoring Well"], "1 / 2")
        # only the note not already in a readout reaches the message line
        self.assertEqual(d.message.text(), "The DEM does not state its elevation units; assumed feet.")
        fb = d.feedback
        self.assertEqual(fb.line.numberOfVertices(), 3)
        self.assertGreater(fb.swath.numberOfVertices(), 4)
        self.assertEqual(fb.points.numberOfVertices(), 2)
        self.assertEqual([lab.text for lab in fb.labels], ["A", "A'"])

    def test_tiled_plan_marks_match_lines_on_map(self):
        self.stub(plan=fake_plan(tiled=True))
        self.dock.refresh()
        fb = self.dock.feedback
        self.assertEqual(fb.ticks.numberOfVertices(), 2)      # one tick across the line
        self.assertIn("MATCH 26+00", [lab.text for lab in fb.labels])
        self.assertIn("<b>2 sheets</b>", self.dock.export_readout.text())

    def test_section_error_shows_in_panel(self):
        self.stub(exc=SectionError("Choose a DEM (ground surface raster)."))
        d = self.dock
        d.refresh()
        self.assertIsNone(d.model)
        self.assertEqual(d.message.text(), "Choose a DEM (ground surface raster).")
        self.assertFalse(d.message.isHidden())
        self.preview.show_message.assert_called_with("Choose a DEM (ground surface raster).")
        # the chosen line is still shown on the map, with its length
        self.assertEqual(d.feedback.line.numberOfVertices(), 3)
        self.assertIn("4,588 ft", d.line_readout.text())

    def test_unexpected_error_is_contained(self):
        self.stub(exc=ZeroDivisionError("float division by zero"))
        self.dock.refresh()
        self.assertIn("Unexpected error", self.dock.message.text())
        self.assertIsNone(self.dock.model)

    def test_plan_that_does_not_fit_is_reported(self):
        self.stub(plan=fake_plan(fits=False))
        self.dock.refresh()
        self.assertEqual(self.dock.message.text(), "Needs 30 × 9 in: too long.")
        self.assertIn("Does not fit", self.dock.export_readout.text())

    def test_narrow_dock(self):
        d = self.dock
        d.resize(340, 900)
        d.show()
        APP.processEvents()
        self.assertLessEqual(d.content.minimumSizeHint().width(), d.scroll.viewport().width())
        d.hide()

    # ---- line tools
    def test_draw_on_map(self):
        self.stub()
        show_canvas(self.canvas, [self.lines])
        pan = QgsMapToolPan(self.canvas)
        self.canvas.setMapTool(pan)
        d = self.dock
        d.btn_draw.setChecked(True)
        self.assertIs(self.canvas.mapTool(), d._draw_tool)
        pts = [(LINE[0][0], LINE[0][1] - 300.0), (LINE[1][0], LINE[1][1] - 300.0), (LINE[2][0], LINE[2][1] - 300.0)]
        for x, y in pts:
            click(d._draw_tool, self.canvas, x, y)
        click(d._draw_tool, self.canvas, *pts[-1], button=Qt.MouseButton.RightButton)
        s = d.settings()
        self.assertEqual(d.line_feature.currentData(), DRAWN)
        self.assertEqual(s.line_crs_authid, CRS)
        self.assertEqual(s.line_layer_id, "")
        verts = [(v.x(), v.y()) for v in QgsGeometry.fromWkt(s.line_wkt).vertices()]
        self.assertEqual(len(verts), 3)
        upp = self.canvas.mapUnitsPerPixel()
        for (x, y), (ex, ey) in zip(verts, pts):
            self.assertLess(math.hypot(x - ex, y - ey), 2 * upp)
        self.assertIs(self.canvas.mapTool(), pan, "previous map tool restored")
        self.assertFalse(d.btn_draw.isChecked())

    def test_draw_escape_cancels(self):
        show_canvas(self.canvas, [self.lines])
        pan = QgsMapToolPan(self.canvas)
        self.canvas.setMapTool(pan)
        d = self.dock
        d.btn_draw.setChecked(True)
        click(d._draw_tool, self.canvas, *LINE[0])
        press_escape(d._draw_tool)
        self.assertIs(self.canvas.mapTool(), pan)
        self.assertFalse(d.btn_draw.isChecked())
        self.assertEqual(d.settings().line_wkt, "")

    def test_draw_tool_emits_map_crs_geometry(self):
        show_canvas(self.canvas, [self.lines])
        tool = DrawSectionTool(self.canvas, self.iface.cadDockWidget())
        self.assertIsNone(tool.layer())
        got = []
        tool.curveCaptured.connect(got.append)
        self.canvas.setMapTool(tool)
        for x, y in LINE:
            click(tool, self.canvas, x, y)
        click(tool, self.canvas, *LINE[-1], button=Qt.MouseButton.RightButton)
        self.assertEqual(len(got), 1)
        self.assertEqual(QgsGeometry(got[0]).constGet().nCoordinates(), 3)
        self.assertAlmostEqual(got[0].length(), line_length(), delta=4 * self.canvas.mapUnitsPerPixel())
        self.canvas.unsetMapTool(tool)

    def test_pick_tool_finds_the_line(self):
        show_canvas(self.canvas, [self.lines, self.pts])
        tool = PickLineTool(self.canvas)
        got, missed = [], []
        tool.featurePicked.connect(lambda layer, fid: got.append((layer, fid)))
        tool.nothingFound.connect(lambda: missed.append(True))
        self.canvas.setMapTool(tool)
        click(tool, self.canvas, LINE[0][0] + 1200.0, LINE[0][1])
        self.assertEqual(len(got), 1)
        self.assertIs(got[0][0], self.lines)
        self.assertEqual(got[0][1], 1)
        click(tool, self.canvas, LINE[0][0] + 1200.0, LINE[0][1] + 350.0)
        self.assertEqual(missed, [True])
        self.canvas.unsetMapTool(tool)

    def test_pick_on_map_sets_the_line(self):
        self.stub()
        show_canvas(self.canvas, [self.lines])
        d = self.dock
        d.set_drawn_line(QgsGeometry.fromWkt("LineString (1200600 651000, 1204000 651100)"),
                         QgsCoordinateReferenceSystem(CRS))
        d.start_label.setText("X")
        self.assertEqual(d.line_feature.currentData(), DRAWN)
        d.btn_pick.setChecked(True)
        self.assertIs(self.canvas.mapTool(), d._pick_tool)
        click(d._pick_tool, self.canvas, LINE[1][0] + 500.0, LINE[1][1] + 150.0)   # on the second segment
        s = d.settings()
        self.assertEqual((s.line_layer_id, s.line_fid, s.line_wkt), (self.lines.id(), 1, ""))
        self.assertEqual((s.start_label, s.end_label), ("A", "A'"))   # from the feature name
        self.assertFalse(d.btn_pick.isChecked())

    def test_reverse_twice(self):
        self.stub()
        d = self.dock
        d.reverse_line()
        s = d.settings()
        self.assertEqual(d.line_feature.currentData(), DRAWN)
        self.assertIn("(reversed)", d.line_feature.currentText())
        verts = [(v.x(), v.y()) for v in QgsGeometry.fromWkt(s.line_wkt).vertices()]
        self.assertEqual(len(verts), 3)
        self.assertAlmostEqual(verts[0][0], LINE[-1][0], places=3)
        self.assertAlmostEqual(verts[-1][1], LINE[0][1], places=3)
        self.assertEqual(self.lines.getFeature(1).geometry().asPolyline()[0], QgsPointXY(*LINE[0]),
                         "the layer is never edited")
        d.reverse_line()
        s = d.settings()
        self.assertEqual((s.line_layer_id, s.line_fid, s.line_wkt), (self.lines.id(), 1, ""))

    def test_use_selected(self):
        self.stub()
        d = self.dock
        d.set_drawn_line(QgsGeometry.fromWkt("LineString (1200600 651000, 1204000 651100)"),
                         QgsCoordinateReferenceSystem(CRS))
        d.use_selected()
        self.assertIn("Select a line feature", d.message.text())
        self.lines.selectByIds([1])
        d.use_selected()
        self.assertEqual(d.line_feature.currentData(), 1)
        self.assertEqual(d.settings().line_wkt, "")

    # ---- outputs
    def test_export_flow(self):
        self.stub()
        d = self.dock
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_ui_"), "sec.pdf")
        d._do_export = mock.Mock(return_value=[out])
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(out, "PDF (*.pdf)")) as dlg:
            paths = d.export_section()
        dlg.assert_called_once()
        self.assertEqual(paths, [out])
        args = d._do_export.call_args[0]
        self.assertEqual(args[3:], (out, "pdf", 300))
        item = self.iface.messageBar().currentItem()
        self.assertIsNotNone(item)
        self.assertEqual(item.level(), Qgis.MessageLevel.Success)
        self.assertIn(out, item.text())

        # a PNG chosen by filter: extension added, 600 dpi from the format setting, format remembered
        d.fmt.setCurrentIndex(2)
        base = os.path.join(os.path.dirname(out), "sec2")
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(base, "PNG image (*.png)")):
            d._do_export = mock.Mock(return_value=[base + ".png"])
            d.export_section()
        self.assertEqual(d._do_export.call_args[0][3:], (base + ".png", "png", 600))
        self.assertEqual(d.settings().export_format, "png")

    def test_export_refused_when_it_does_not_fit(self):
        self.stub(plan=fake_plan(fits=False))
        d = self.dock
        d._do_export = mock.Mock()
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName") as dlg:
            self.assertEqual(d.export_section(), [])
        dlg.assert_not_called()
        d._do_export.assert_not_called()
        item = self.iface.messageBar().currentItem()
        self.assertEqual(item.level(), Qgis.MessageLevel.Warning)

    def test_export_cancelled(self):
        self.stub()
        self.dock._do_export = mock.Mock()
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertEqual(self.dock.export_section(), [])
        self.dock._do_export.assert_not_called()

    def test_save_line_to_layer(self):
        self.stub()
        layer = self.dock.save_line_to_layer()
        self.assertEqual(layer.name(), LINES_LAYER_NAME)
        self.assertIn(layer.id(), self.prj.mapLayers())
        feats = list(layer.getFeatures())
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0].attributes(), ["A", "A'", 1000.0, 50.0, 150.0])
        self.assertAlmostEqual(feats[0].geometry().length(), line_length(), places=3)
        self.assertIs(self.dock.save_line_to_layer(), layer)
        self.assertEqual(layer.featureCount(), 2)

    def test_export_points_csv(self):
        self.stub()
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_ui_"), "pts.csv")
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(out, "CSV (*.csv)")):
            self.assertEqual(self.dock.export_points_csv(), out)
        with open(out, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], CSV_COLUMNS)
        self.assertEqual([r[0] for r in rows[1:]], ["B-1", "MW-2"])
        for col in ("top_source", "bottom_source", "total_depth_ft"):
            self.assertIn(col, rows[0])
        row = dict(zip(rows[0], rows[2]))
        self.assertEqual(row["station"], "29+00")
        self.assertEqual(float(row["depth_ft"]), 35.0)
        self.assertEqual((row["top_source"], row["bottom_source"], float(row["total_depth_ft"])), ("dem", "depth", 35.0))
        self.assertIn("ignored", row["flags"])

    def test_csv_locked_is_a_message_not_a_traceback(self):
        self.stub()
        folder = tempfile.mkdtemp(prefix="xsec_ui_")
        target = os.path.join(folder, "locked.csv")
        os.mkdir(target)                      # open() fails like a CSV that Excel holds open
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(target, "CSV (*.csv)")):
            self.assertEqual(self.dock.export_points_csv(), "")
        item = self.iface.messageBar().currentItem()
        self.assertEqual(item.level(), Qgis.MessageLevel.Warning)
        self.assertIn("Could not write locked.csv", item.text())
        self.assertIn("open in Excel", item.text())

    def test_export_to_a_locked_file(self):
        self.stub()
        d = self.dock
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_ui_"), "Section A-A'.pdf")
        d._do_export = mock.Mock(side_effect=PermissionError(13, "Permission denied", out))
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(out, "PDF (*.pdf)")):
            self.assertEqual(d.export_section(), [])
        item = self.iface.messageBar().currentItem()
        self.assertEqual(item.level(), Qgis.MessageLevel.Warning)
        self.assertEqual(item.text(), "Could not write Section A-A'.pdf: it is probably open in a PDF viewer or an "
                                      "image editor. Close it and export again, or choose another name.")

    def test_default_export_name_has_the_scales(self):
        self.stub()
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=("", "")) as dlg:
            self.dock.export_section()
        self.assertEqual(os.path.basename(dlg.call_args[0][2]), "Section A-A' H1000 V50.pdf")

    def test_feature_beyond_the_first_thousand(self):
        self.stub()
        big = QgsVectorLayer(f"LineString?crs={CRS}&field=name:string", "Roads", "memory")
        feats = []
        for i in range(1200):
            f = QgsFeature(big.fields())
            f.setAttributes([f"Road {i}"])
            y = LINE[0][1] - 1500.0 + i
            f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(LINE[0][0], y), QgsPointXY(LINE[0][0] + 1000 + i, y)]))
            feats.append(f)
        big.dataProvider().addFeatures(feats)
        self.prj.addMapLayer(big)
        d = self.dock
        target = sorted(big.allFeatureIds())[1150]
        d._on_feature_picked(big, target)                    # what Pick on map emits
        self.assertEqual(d.settings().line_fid, target)
        self.assertEqual(d.line_feature.currentText(), "Road 1150")
        # a feature that no longer exists stays chosen and is reported, never swapped for another line
        d.select_feature(big, 999_999)
        self.assertEqual(d.settings().line_fid, 999_999)
        self.assertIn("(missing)", d.line_feature.currentText())
        del d._pipeline                                       # the real pipeline from here on
        d.refresh()
        self.assertIn("Feature 999999 of Roads no longer exists", d.message.text())

    def test_manual_elevations_start_from_the_auto_limits(self):
        d = self.dock                                        # the real pipeline, the default fill (below)
        d.refresh()
        auto = (d.plan.z_min, d.plan.z_max)
        self.assertEqual((d.z_min.value(), d.z_max.value()), auto)     # the disabled spins show them (filled)
        self.assertFalse(d.z_min.isEnabled())
        self.assertTrue(d.fill_grid.isEnabled())
        d.z_mode.setCurrentIndex(d.z_mode.findData("manual"))
        self.assertFalse(d.fill_grid.isEnabled())                       # a manual range is drawn as typed
        self.assertEqual(d.fill_grid.currentData(), "below")             # the choice is kept for Auto
        d.refresh()
        self.assertEqual((d.plan.z_min, d.plan.z_max), auto)             # the same sheet as in Auto
        self.assertEqual(d.plan.warnings, [])
        self.assertTrue(d.message.isHidden(), d.message.text())
        # a typed range is never extended by the fill
        d.z_min.setValue(auto[0] + 2 * d.plan.v_major)
        d.refresh()
        self.assertEqual((d.plan.z_min, d.plan.z_max), (auto[0] + 2 * d.plan.v_major, auto[1]))
        # a range that misses the ground: a warning naming the range as typed, and no "grid below" figure
        # measured off the plot
        d.z_min.setValue(0.0)
        d.z_max.setValue(100.0)
        d.refresh()
        self.assertEqual((d.plan.z_min, d.plan.z_max), (0.0, 100.0))
        self.assertIn("is outside the manual elevation range 0 to 100 ft", d.message.text())
        self.assertNotIn("of grid below", d.export_readout.text())
        self.assertIn("outside the manual elevation range", d.export_readout.text())
        d.z_mode.setCurrentIndex(d.z_mode.findData("auto"))
        self.assertTrue(d.fill_grid.isEnabled())

    def test_tool_instructions_cleared_when_the_tool_goes(self):
        show_canvas(self.canvas, [self.lines])
        d = self.dock
        pan = QgsMapToolPan(self.canvas)
        self.canvas.setMapTool(pan)
        d.btn_draw.setChecked(True)
        self.assertIn("Click the vertices", d.message.text())
        press_escape(d._draw_tool)
        self.assertTrue(d.message.isHidden(), d.message.text())
        d.btn_pick.setChecked(True)
        self.assertIn("Click a line feature", d.message.text())
        press_escape(d._pick_tool)
        self.assertTrue(d.message.isHidden(), d.message.text())
        # another QGIS tool taken while drawing
        d.btn_draw.setChecked(True)
        from qgis.gui import QgsMapToolZoom
        zoom = QgsMapToolZoom(self.canvas, False)
        self.canvas.setMapTool(zoom)
        self.assertFalse(d.btn_draw.isChecked())
        self.assertTrue(d.message.isHidden(), d.message.text())
        # switching straight from Draw to Pick shows Pick's instructions
        d.btn_draw.setChecked(True)
        d.btn_pick.setChecked(True)
        self.assertIn("Click a line feature", d.message.text())
        self.assertFalse(d.btn_draw.isChecked())
        self.canvas.setMapTool(pan)

    def test_drawn_line_without_a_crs(self):
        self.stub()
        d = self.dock
        d.set_drawn_line(QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE]), QgsCoordinateReferenceSystem())
        s = d.settings()
        self.assertEqual(s.line_crs_authid, "")
        verts = [(v.x(), v.y()) for v in QgsGeometry.fromWkt(s.line_wkt).vertices()]
        self.assertAlmostEqual(verts[0][0], LINE[0][0], places=3)      # coordinates kept as drawn
        from xsections.core.section import resolve_line
        line = resolve_line(s, self.prj, QgsCoordinateReferenceSystem(CRS))     # read in the project CRS
        self.assertAlmostEqual(line.length(), line_length(), places=3)

    def test_crs_changes_trigger_a_rebuild(self):
        self.stub()
        d = self.dock
        d.refresh()
        self.assertFalse(d._timer.isActive())
        self.dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2926"))
        self.assertTrue(d._timer.isActive())
        self.assertTrue(d._stale)
        d.refresh()
        self.pts.setCrs(QgsCoordinateReferenceSystem("EPSG:2926"))
        self.assertTrue(d._timer.isActive())

    def test_single_sheet_readout_does_not_repeat_itself(self):
        p = fake_plan()
        p.message = "Letter 11 × 8.5 in, landscape; plot 4.60 × 5.00 in."
        self.stub(plan=p)
        self.dock.refresh()
        exp = self.dock.export_readout.text()
        self.assertEqual(exp.count("Letter 11 × 8.5 in, landscape"), 1)
        t = fake_plan(tiled=True)
        t.message = "Too long for one Letter sheet: tiled on 2 sheets, match lines at STA 26+00."
        self.stub(plan=t)
        self.dock.refresh()
        self.assertIn("match lines at STA 26+00", self.dock.export_readout.text())

    def test_north_reads_000_not_360(self):
        from xsections.ui.dock import fmt_azimuth
        self.assertEqual(fmt_azimuth(359.6), "000°")
        self.assertEqual(fmt_azimuth(82.0), "082°")
        self.assertEqual(fmt_azimuth(359.4), "359°")
        m = fake_model()
        m.azimuth = 359.7
        self.stub(model=m)
        self.dock.refresh()
        self.assertIn("<b>N</b> (000°)", self.dock.line_readout.text())

    # ---- the real pipeline, when core and render are present
    def test_real_pipeline(self):
        pv = PreviewWidget()
        self.dock.preview = pv
        self.dock.refresh()
        self.assertEqual(self.dock.last_error, "")
        self.assertIsNotNone(self.dock.model)
        self.assertGreater(len(self.dock.model.hits), 0)
        pv.render_pending()
        self.assertEqual(pv.last_error, "")
        self.assertTrue(pv.figure.axes)
        self.assertGreater(self.dock.feedback.points.numberOfVertices(), 0)

    def test_real_export(self):
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_ui_"), "real.pdf")
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(out, "PDF (*.pdf)")):
            paths = self.dock.export_section()
        self.assertEqual(paths, [out])
        self.assertTrue(os.path.getsize(out) > 1000)


# ------------------------------------------------------------------ preview
class PreviewTests(unittest.TestCase):
    def test_message(self):
        pv = PreviewWidget()
        pv.show_message("Choose a DEM")
        pv.render_pending()
        self.assertIn("Choose a DEM", [t.get_text() for t in pv.figure.texts])
        self.assertFalse(pv.has_section())

    def test_sheet_overlay(self):
        fig = Figure(figsize=(8, 3))
        ax = fig.add_axes((0.1, 0.1, 0.8, 0.8))
        ax.set_xlim(0, 4600)
        ax.set_ylim(400, 650)
        self.assertEqual(overlay_sheets(fig, fake_plan()), 0)
        self.assertEqual(overlay_sheets(fig, fake_plan(tiled=True)), 2)
        self.assertEqual(sorted(t.get_text() for t in ax.texts), ["SHEET 1 OF 2", "SHEET 2 OF 2"])
        self.assertEqual(overlay_sheets(fig, fake_plan(tiled=True)), 0, "drawn once only")

    def test_sheet_tags_fit_their_sheets(self):
        self.assertEqual(sheet_tags(3, [500.0] * 3), ["SHEET 1 OF 3", "SHEET 2 OF 3", "SHEET 3 OF 3"])
        self.assertEqual(sheet_tags(3, [0.0] * 3), ["1", "2", "3"])
        # one style for all; only a short last sheet gets a shorter tag
        self.assertEqual(sheet_tags(4, [500.0, 500.0, 500.0, 5.0]), ["SHEET 1 OF 4", "SHEET 2 OF 4", "SHEET 3 OF 4", "4"])
        # most sheets narrow: the roomy first sheet follows their style
        self.assertEqual(sheet_tags(5, [500.0, 30.0, 30.0, 30.0, 30.0]), ["1/5", "2/5", "3/5", "4/5", "5/5"])

    def test_toolbar_has_no_save_or_editors(self):
        """0.3.1: matplotlib's toolbar is gone (its rectangle zoom distorted the vertical exaggeration). Fit, zoom
        out / in (the whole plot), Surfaces CSV… and (0.3.2) the two hover toggles; no save, no editors, no points
        CSV."""
        pv = PreviewWidget()
        names = [a.text() for a in pv.toolbar.actions() if a.text()]
        self.assertEqual(names, ["Fit", "Zoom out", "Zoom in", "Surfaces CSV…", "Readout row", "Popup"])
        for gone in ("Home", "Back", "Forward", "Pan", "Zoom", "Save", "Subplots", "Customize", "Points CSV…"):
            self.assertNotIn(gone, names)
        self.assertEqual(pv.zoom_label.text(), "100%")
        self.assertTrue(pv.act_strip.isCheckable() and pv.act_popup.isCheckable())

    def test_draw_and_failure(self):
        pv = PreviewWidget()
        s = Settings()
        pv.draw(fake_model(), s, fake_plan(tiled=True))
        pv.render_pending()
        self.assertEqual(pv.last_error, "")
        self.assertIn("2 sheets", pv.status.text())
        with mock.patch("xsections.render.figure.draw_preview", side_effect=RuntimeError("boom")):
            pv.render_pending()
        self.assertIn("boom", pv.last_error)


# ------------------------------------------------------------------ plugin shell
class PluginTests(unittest.TestCase):
    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.iface = make_iface()
        self.canvas = self.iface.mapCanvas()

    def _our_items(self):
        from qgis.gui import QgsRubberBand
        from xsections.ui.map_feedback import MapLabel
        return [i for i in self.canvas.scene().items() if isinstance(i, (QgsRubberBand, MapLabel))]

    def test_init_toggle_unload(self):
        from xsections import classFactory
        before = len(self._our_items())
        plugin = classFactory(self.iface)
        plugin.initGui()
        self.iface.addToolBarIcon.assert_called_once_with(plugin.action)
        self.iface.addPluginToMenu.assert_called_once()
        self.assertEqual(self.iface.addDockWidget.call_count, 2)
        self.assertFalse(plugin.action.icon().isNull())
        dock, pdock = plugin.dock, plugin.preview_dock
        self.assertEqual(dock.dem_layer.currentLayer(), self.dem)

        plugin.action.setChecked(True)
        self.assertFalse(dock.isHidden())
        self.assertFalse(pdock.isHidden())
        plugin.action.setChecked(False)
        self.assertTrue(dock.isHidden())

        dock._pipeline = lambda s: (fake_model(), fake_plan(tiled=True))
        dock.refresh()
        self.assertGreater(len(self._our_items()), before)
        pan = QgsMapToolPan(self.canvas)
        self.canvas.setMapTool(pan)
        dock.btn_draw.setChecked(True)
        self.assertIs(self.canvas.mapTool(), dock._draw_tool)

        plugin.unload()
        self.iface.removeToolBarIcon.assert_called_once()
        self.iface.removePluginMenu.assert_called_once()
        self.assertEqual(self.iface.removeDockWidget.call_count, 2)
        self.assertIs(self.canvas.mapTool(), pan)
        APP.processEvents()
        self.assertEqual(len(self._our_items()), before)
        self.assertIsNone(plugin.dock)
        self.assertEqual(plugin._project_signals, [])
        self.prj.cleared.emit()          # nothing connected any more: must not fail
        self.prj.clear()

    def test_bad_project_settings_never_half_load_the_plugin(self):
        from xsections import classFactory
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, '{"h_scale": null, "dem_band": null}')
        plugin = classFactory(self.iface)
        plugin.initGui()                                     # bad values: dropped, the rest applies
        self.assertEqual(plugin.dock.settings().h_scale, Settings().h_scale)
        plugin.unload()
        # even a restore that fails outright leaves a working, unloadable plugin with default settings
        with mock.patch("xsections.ui.dock.XSectionsDock.restore_from_project", side_effect=AttributeError("x")):
            plugin = classFactory(self.iface)
            plugin.initGui()
        self.assertIsNotNone(plugin.dock)
        self.assertEqual(plugin.dock.settings().tolerance_ft, Settings().tolerance_ft)
        self.assertEqual(len(plugin._project_signals), 3)
        plugin.unload()
        self.assertEqual(plugin._project_signals, [])
        self.assertEqual(self.iface.removeToolBarIcon.call_count, 2)
        self.prj.clear()

    def test_project_crs_change_rebuilds(self):
        from xsections import classFactory
        plugin = classFactory(self.iface)
        plugin.initGui()
        try:
            dock = plugin.dock
            dock._timer.stop()
            dock._stale = False
            self.prj.setCrs(QgsCoordinateReferenceSystem("EPSG:2926"))
            self.assertTrue(dock._timer.isActive())
            self.assertTrue(dock._stale)
        finally:
            plugin.unload()
            self.prj.clear()

    def test_fresh_project_guesses(self):
        """A line layer is guessed only by name; a DEM never falls back to a photo or hillshade."""
        import numpy as np
        from osgeo import gdal
        prj = self.prj
        prj.removeMapLayers([self.lines.id(), self.dem.id()])
        for name in ("Streams", "Contours 2 ft"):
            lyr = QgsVectorLayer(f"LineString?crs={CRS}", name, "memory")
            prj.addMapLayer(lyr)
        folder = tempfile.mkdtemp(prefix="xsec_ui_")
        rasters = {}
        for name, bands in (("Orthophoto 2021", 3), ("Hillshade", 1), ("Bare earth 2019", 1)):
            path = os.path.join(folder, name.replace(" ", "_") + ".tif")
            ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, bands, gdal.GDT_Float32)
            ds.SetGeoTransform((LINE[0][0], 10, 0, LINE[0][1], 0, -10))
            for i in range(1, bands + 1):
                ds.GetRasterBand(i).WriteArray(np.arange(16, dtype="float32").reshape(4, 4))
            ds = None
            from qgis.core import QgsRasterLayer
            rasters[name] = QgsRasterLayer(path, name)
            prj.addMapLayer(rasters[name])
        dock = XSectionsDock(self.iface, None)
        try:
            dock.restore_from_project()
            self.assertIsNone(dock.line_layer.currentLayer())
            s = dock.settings()
            self.assertEqual((s.line_layer_id, s.line_fid), ("", None))
            self.assertEqual(s.dem_layer_id, rasters["Bare earth 2019"].id())
            self.assertEqual(layer_rows(s)[0]["layer_id"], self.pts.id())
            renamed = QgsVectorLayer(f"LineString?crs={CRS}", "XSec lines", "memory")
            prj.addMapLayer(renamed)
            dock.restore_from_project()
            self.assertIs(dock.line_layer.currentLayer(), renamed)
        finally:
            dock.cleanup()
            dock.deleteLater()
            prj.clear()

    def test_layers_added_after_start(self):
        """Empty project (File > New), then the layers are added: the field boxes follow the point layer,
        and the empty boxes get the fresh-project guesses. Chosen layers are kept."""
        from qgis.core import QgsRasterLayer
        from tests.fixtures import make_dem, make_line_layer, make_points_layer
        prj = self.prj
        prj.clear()
        prj.setCrs(QgsCoordinateReferenceSystem(CRS))
        dock = XSectionsDock(self.iface, None)
        try:
            dock.restore_from_project()
            self.assertEqual(dock.explo_rows, [])                   # no point layer yet: no row
            hydrants = QgsVectorLayer(f"Point?crs={CRS}", "Hydrants", "memory")
            pts = make_points_layer(name="CDF_wells")
            prj.addMapLayers([hydrants, pts])
            self.assertEqual(explo_row(dock).layer_combo.currentLayer().id(), pts.id())
            self.assertEqual((explo_row(dock).label_field.currentField(), explo_row(dock).type_field.currentField(),
                              explo_row(dock).top_field.currentField(), explo_row(dock).depth_field.currentField()),
                             ("ExploName", "ExploType", "ExploElev", "ExploDepth"))
            self.assertEqual(explo_row(dock).type_list.topLevelItemCount(), 4)

            dem = QgsRasterLayer(make_dem(), "cdf_lidar")
            lines = make_line_layer(name="xsec_lines")
            prj.addMapLayers([dem, lines])
            s = dock.settings()
            self.assertEqual((s.dem_layer_id, s.line_layer_id, s.line_fid, layer_rows(s)[0]["layer_id"],
                              layer_rows(s)[0]["label_field"]), (dem.id(), lines.id(), 1, pts.id(), "ExploName"))
            self.assertFalse(dock._user_changed)          # guesses, not the user's choice: not saved

            prj.addMapLayers([QgsRasterLayer(make_dem(), "other_dem"), make_line_layer(name="section 2"),
                              make_points_layer(name="more_wells")])
            self.assertEqual(dock.settings(), s)
        finally:
            dock.cleanup()
            dock.deleteLater()
            prj.clear()

    def test_settings_survive_project_save_and_load(self):
        from xsections import classFactory
        plugin = classFactory(self.iface)
        plugin.initGui()
        try:
            dock = plugin.dock
            dock._pipeline = lambda s: (_ for _ in ()).throw(SectionError("stub"))
            dock.tolerance.setValue(88.0)
            dock.h_scale.setEditText("200")
            dock.save_settings()
            path = os.path.join(tempfile.mkdtemp(prefix="xsec_ui_"), "proj.qgz")
            self.assertTrue(self.prj.write(path))
            dem_id = self.dem.id()
            self.prj.clear()
            self.assertEqual(dock.tolerance.value(), Settings().tolerance_ft)
            self.assertTrue(self.prj.read(path))
            s = dock.settings()
            self.assertEqual(s.tolerance_ft, 88.0)
            self.assertEqual(s.h_scale, 200.0)
            self.assertEqual(s.dem_layer_id, dem_id)
        finally:
            plugin.unload()
            self.prj.clear()


if __name__ == "__main__":
    unittest.main()
