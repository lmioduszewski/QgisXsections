"""Panel layout tests (0.2): collapsible sections and their header chips, segmented controls, the surfaces list
(raster and MODFLOW 6 surfaces, the "+ Add MODFLOW 6…" dialog), and the screens and water-level settings.

The core/render pipeline is stubbed with tests.test_ui's hand-made model and plan where the test is about the
panel.
"""
import dataclasses
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from tests.fixtures import budget, default_settings, explo_row, load_project, start_app, timing_test

APP = start_app()

from qgis.core import QgsCoordinateReferenceSystem, QgsFeature, QgsField, QgsRasterLayer, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtCore import QMetaType, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402
from qgis.PyQt.QtWidgets import QComboBox, QDialog, QFileDialog  # noqa: E402

from tests.test_ui import fake_model, fake_plan, make_iface  # noqa: E402
from xsections.core import mf6  # noqa: E402
from xsections.core.model import (SURFACE_COLORS, SURFACE_DEFAULTS, SectionError, Settings, WaterLevel,  # noqa: E402
                                  as_rows, clean_surface, layer_rows)
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import (NO_ATD, XSectionsDock, pretty_label, screens_summary, sheet_short)  # noqa: E402
from xsections.ui.mf6_dialog import (BOTTOM_COLOR, HEAD_COLOR, LAST_DIR_KEY, WT_COLOR, MF6Dialog,  # noqa: E402
                                     ModelSurfaceRow, crs_text, default_name, fill_time_combo, fmt_time, load_model,
                                     model_stem, model_surfaces, parse_time, ramp, ranges, time_items, time_words,
                                     times_summary)
from xsections.ui import widgets as W  # noqa: E402
from xsections.ui.widgets import SegmentedControl, SurfaceRow  # noqa: E402

MF6_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mf6")
DISV = os.path.join(MF6_DATA, "disv_small")              # DISV, 3 layers x 28 cells, feet, 3 periods
DISV_GRB = os.path.join(DISV, "disv_small.disv.grb")
DISV_HDS = os.path.join(DISV, "disv_small.hds")
ROTATED = os.path.join(MF6_DATA, "dis_rotated")          # DIS, 2 layers, 1 period
DISV_TIMES = [("Last saved (SP 3, step 2)", "last"), ("SP 1 · last step (2) · t = 10", "1"),
              ("SP 1 · step 1 · t = 5", "1,1"), ("SP 1 · step 2 · t = 10", "1,2"),
              ("SP 2 · last step (3) · t = 40", "2"), ("SP 2 · step 1 · t = 20", "2,1"),
              ("SP 2 · step 2 · t = 30", "2,2"), ("SP 2 · step 3 · t = 40", "2,3"), ("SP 3 · t = 60", "3")]
REALDATA = os.environ.get("XSECTIONS_REALDATA", "")


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def combo_items(combo):
    return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]

SCREEN_FIELDS = [("ScrTop", QMetaType.Type.Double), ("ScrBot", QMetaType.Type.Double),
                 ("GW_Elev", QMetaType.Type.Double), ("WL_Date", QMetaType.Type.QString),
                 ("ATD", QMetaType.Type.Double), ("ATD_Date", QMetaType.Type.QString),
                 ("Note", QMetaType.Type.QString)]


def add_fields(layer, specs):
    layer.dataProvider().addAttributes([QgsField(n, t) for n, t in specs])
    layer.updateFields()


def make_wl_table(name="water_levels", rows=None):
    """A table without geometry: one row per water level."""
    tbl = QgsVectorLayer("None?field=Boring:string&field=WL_Elev:double&field=Date:string&field=Kind:string",
                         name, "memory")
    feats = []
    for row in rows or (("MW-1", 480.0, "3/1/2024", "Measured"), ("B-1", 470.0, "5/2/2019", "ATD"),
                        ("MW-2", 500.0, "1/9/2020", "Drilling"), ("MW-2", 499.0, "1/9/2020", "atd (field)")):
        f = QgsFeature(tbl.fields())
        f.setAttributes(list(row))
        feats.append(f)
    tbl.dataProvider().addFeatures(feats)
    return tbl


def make_raster(bands, name):
    import numpy as np
    from osgeo import gdal
    from tests.fixtures import LINE
    path = os.path.join(tempfile.mkdtemp(prefix="xsec_panel_"), name.replace(" ", "_") + ".tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, bands, gdal.GDT_Float32)
    ds.SetGeoTransform((LINE[0][0], 10, 0, LINE[0][1], 0, -10))
    for i in range(1, bands + 1):
        ds.GetRasterBand(i).WriteArray(100.0 * i + np.arange(16, dtype="float32").reshape(4, 4))
    ds = None
    return QgsRasterLayer(path, name)


def screen_model():
    """fake_model() with screens and water levels on its two hits, and one water-level flag."""
    m = fake_model()
    m.hits[0].screen_top, m.hits[0].screen_bottom = 495.0, 485.0
    m.hits[0].water_levels = [WaterLevel(490.0, "measured", "3/1/2024", "GW_Elev")]
    m.hits[1].screen_top, m.hits[1].screen_bottom = 520.0, 510.0
    m.hits[1].water_levels = [WaterLevel(522.0, "measured"), WaterLevel(518.0, "atd")]
    m.hits[1].flags = list(m.hits[1].flags) + ["water level 522.0 ft is above the top of the screen"]
    return m


class PanelCase(unittest.TestCase):
    """The fixture project, its points layer with screen and water-level fields, and a dock on it."""

    extra_fields = SCREEN_FIELDS

    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        if self.extra_fields:
            add_fields(self.pts, self.extra_fields)
        self.iface = make_iface()
        self.dock = XSectionsDock(self.iface, None)
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

    def chips(self):
        return {sec.title(): (sec.chipText(), sec.chipWarn()) for sec in self.dock.sections}


# ------------------------------------------------------------------ sections
class SectionTests(PanelCase):
    def test_sections_in_order_and_named(self):
        d = self.dock
        self.assertEqual([s.title() for s in d.sections],
                         ["Line", "Surfaces", "Explorations", "Other features", "Scale & sheet", "Sheet style"])
        self.assertEqual(d.sections, [d.grp_line, d.grp_ground, d.grp_explo, d.grp_other, d.grp_export, d.grp_style])
        # (0.3.6: Depths and Water & screens are subsections of Explorations)
        self.assertTrue(d.grp_explo.isAncestorOf(d.grp_depth) and d.grp_explo.isAncestorOf(d.grp_screens))
        r = explo_row(d)
        # every widget sits in its section (readouts included)
        for grp, widgets in ((d.grp_line, (d.line_layer, d.btn_pick, d.btn_reverse, d.btn_save_line, d.line_readout)),
                             (d.grp_ground, (d.dem_layer, d.dem_band, d.z_units, d.datum, d.btn_add_surface,
                                             d.btn_add_bands, d.btn_add_mf6, d.ground_readout)),
                             (d.grp_explo, (r.layer_combo, r.type_list, d.label_dir, d.label_text, d.explo_readout,
                                            r.screen_values, r.wl_values, r.wl_table, r.wl_atd_values)),
                             (d.grp_depth, (d.depth_line, d.top_mode, d.top_max_diff, d.td_label, d.depth_readout)),
                             (d.grp_screens, (d.screens, d.wl_label, d.screens_readout)),
                             (d.grp_other, (d.other_list, d.btn_add_other, d.other_readout)),
                             (d.grp_export, (d.h_scale, d.fmt, d.z_mode, d.tile, d.allowed_sheets, d.export_readout)),
                             (d.grp_style, (d.grid_color, d.fill_grid, d.compact_layout, d.shade_below,
                                            d.grid_major_color, d.depth_lw_black, d.btn_lw_reset))):
            for w in widgets:
                self.assertTrue(grp.isAncestorOf(w), (grp.title(), w))
        self.assertIn(d.btn_csv, d.btn_more.menu().actions())          # Export points CSV… in the ⋯ menu

    def test_all_collapsed_on_creation_restore_clear_and_reopen(self):
        d = self.dock
        self.assertTrue(all(s.isCollapsed() for s in d.sections))       # after construction + restore
        fresh = XSectionsDock(self.iface, None)
        try:
            self.assertTrue(all(s.isCollapsed() for s in fresh.sections))
        finally:
            fresh.cleanup()
            fresh.deleteLater()
        for s in d.sections:
            s.setCollapsed(False)
        d._disclosures[0].setExpanded(True)
        d.restore_from_project()
        self.assertTrue(all(s.isCollapsed() for s in d.sections))
        self.assertFalse(any(m.isExpanded() for m in d._disclosures))
        d.grp_explo.setCollapsed(False)
        d.project_cleared()
        self.assertTrue(all(s.isCollapsed() for s in d.sections))
        # closed -> open: closed again; any number may be open meanwhile
        d.restore_from_project()
        d.resize(340, 700)
        d.show()
        APP.processEvents()
        d.grp_line.setCollapsed(False)
        d.grp_style.setCollapsed(False)
        self.assertEqual([s.isCollapsed() for s in d.sections].count(False), 2)
        d.hide()
        d.show()
        APP.processEvents()
        self.assertTrue(all(s.isCollapsed() for s in d.sections))
        d.hide()

    def test_header_click_toggles(self):
        sec = self.dock.grp_explo
        self.assertTrue(sec.body.isHidden())
        sec.header.clicked.emit()
        self.assertFalse(sec.isCollapsed())
        self.assertFalse(sec.body.isHidden())
        self.assertTrue(sec.header.isOpen())
        sec.header.clicked.emit()
        self.assertTrue(sec.isCollapsed())

    def test_open_state_is_never_saved(self):
        d = self.dock
        d.grp_explo.setCollapsed(False)
        d.tolerance.setValue(77.0)
        d.save_settings()
        self.assertNotIn("collapsed", settings_store.stored_json(self.prj).lower())

    def test_narrow_dock_never_scrolls_sideways(self):
        d = self.dock
        for s in d.sections:
            s.setCollapsed(False)
        for m in d._disclosures:
            m.setExpanded(True)
        d.add_surface(self.dem).set_editor_open(True)
        d.add_model_surfaces(model_surfaces(DISV_GRB, DISV_HDS, 3, heads=[1]))[0].set_editor_open(True)
        for width in (260, 340):
            d.resize(width, 900)
            d.show()
            APP.processEvents()
            self.assertLessEqual(d.content.minimumSizeHint().width(), d.scroll.viewport().width(), width)
            self.assertFalse(d.scroll.horizontalScrollBar().isVisible())
        d.hide()


# ------------------------------------------------------------------ header chips
class ChipTests(PanelCase):
    def test_working_section(self):
        d = self.dock
        self.stub(model=screen_model())
        d.refresh()
        c = self.chips()
        self.assertEqual(c["Line"], ("A–A′ · 4,588 ft", False))
        self.assertEqual(c["Surfaces"], ("Ground", False))
        self.assertEqual(c["Explorations"], ("2 plotted", False))
        self.assertEqual(c["Scale & sheet"], ("1,000′ / 50′ · Letter", False))
        self.assertEqual(c["Sheet style"], ("Defaults", False))
        # the chips follow the widgets
        d.add_surface(self.dem)
        r = d.add_surface(self.dem)
        r.visible_box.setChecked(False)
        d.depth_line.setChecked(False)
        d.screens.setChecked(False)
        d.grid_color.setCurrentIndex(d.grid_color.findData("gray"))
        c = self.chips()
        self.assertEqual(c["Surfaces"], ("Ground + 1", False))         # visible surfaces only
        self.assertEqual(c["Sheet style"], ("Gray grid", False))
        d.depth_line.setChecked(True)
        # tiled, and a plan that does not fit
        self.stub(model=screen_model(), plan=fake_plan(tiled=True))
        d.h_scale.setEditText("100")
        d.v_scale.setEditText("20")
        d.refresh()
        self.assertEqual(self.chips()["Scale & sheet"], ("100′ / 20′ · Tabloid · 2 sheets", False))
        self.stub(plan=fake_plan(fits=False))
        d.refresh()
        self.assertEqual(self.chips()["Scale & sheet"], ("Does not fit", True))

    def test_no_screen_fields(self):
        d = self.dock
        for c in (explo_row(d).screen_top_field, explo_row(d).screen_bottom_field, explo_row(d).wl_field,
                  explo_row(d).atd_field):
            c.setField("")
        self.stub()
        d.refresh()
        self.assertFalse(d.screens_readout.wanted())                  # (0.3.6: nothing to say, even with Verbose)

    def test_empty_project(self):
        self.prj.clear()
        d = self.dock
        d.project_cleared()
        c = self.chips()
        self.assertEqual(c["Line"], ("Choose a line", True))
        self.assertEqual(c["Surfaces"], ("Choose a DEM", True))
        self.assertEqual(c["Explorations"], ("None", False))
        self.assertEqual(c["Scale & sheet"], ("1,000′ / 50′", False))
        self.assertEqual(c["Sheet style"], ("Defaults", False))
        d.restore_from_project()                                      # a new, empty project
        self.assertEqual(self.chips()["Line"], ("Choose a line", True))
        self.assertTrue(d.ground_editor.isVisible() or not d.ground_editor.isHidden())   # the DEM box is shown

    def test_error_keeps_the_line_chip(self):
        self.stub(exc=SectionError("Choose a DEM (ground surface raster)."))
        self.dock.refresh()
        c = self.chips()
        self.assertEqual(c["Line"], ("A–A′ · 4,588 ft", False))
        self.assertEqual(c["Explorations"], ("–", False))
        self.assertEqual(c["Scale & sheet"], ("1,000′ / 50′", False))

    def test_points_layer_removed(self):
        d = self.dock
        self.prj.removeMapLayer(self.pts.id())
        APP.processEvents()
        self.stub()
        d.refresh()
        self.assertEqual(self.chips()["Explorations"], ("Layer missing", True))

    def test_helpers(self):
        self.assertEqual(pretty_label("B'"), "B′")
        self.assertEqual(sheet_short("Letter 11 × 8.5 in, landscape"), "Letter")
        self.assertEqual(sheet_short("ANSI C 22 × 17 in, landscape"), "ANSI C")
        self.assertEqual(sheet_short("Custom 24.5 x 14 in"), "Custom")
        m = screen_model()
        self.assertEqual(screens_summary(m.hits), "2 screens · 2 measured, 1 ATD water levels")
        m.hits[1].water_levels = []
        self.assertEqual(screens_summary(m.hits), "2 screens · 1 measured water level")
        m.hits[0].water_levels = []
        m.hits[0].screen_top = None
        self.assertEqual(screens_summary(m.hits), "1 screen · no water levels")


# ------------------------------------------------------------------ segmented controls
class SegmentedTests(unittest.TestCase):
    def test_combo_api(self):
        seg = SegmentedControl()
        got = []
        seg.currentIndexChanged.connect(got.append)
        self.assertEqual((seg.count(), seg.currentIndex(), seg.currentData(), seg.currentText()), (0, -1, None, ""))
        seg.addItem("Off", "off")
        self.assertEqual((seg.currentIndex(), got), (0, [0]))           # the first item is chosen, like QComboBox
        seg.addItem("Below", "below")
        seg.addItem("Both", "both")
        self.assertEqual(seg.count(), 3)
        self.assertEqual([seg.itemText(i) for i in range(3)], ["Off", "Below", "Both"])
        self.assertEqual([seg.itemData(i) for i in range(3)], ["off", "below", "both"])
        self.assertEqual((seg.findData("both"), seg.findData("nope"), seg.findText("Below")), (2, -1, 1))
        seg.setCurrentIndex(2)
        self.assertEqual((seg.currentIndex(), seg.currentData(), seg.currentText()), (2, "both", "Both"))
        self.assertEqual(got, [0, 2])
        seg.setCurrentIndex(2)                                         # unchanged: no signal
        self.assertEqual(got, [0, 2])
        self.assertEqual([b.isChecked() for b in seg.buttons()], [False, False, True])
        clicks = []
        seg.activated.connect(clicks.append)
        seg.buttons()[1].click()                                       # a click: both signals
        self.assertEqual((seg.currentData(), got[-1], clicks), ("below", 1, [1]))
        seg.buttons()[1].click()                                       # the chosen button stays chosen
        self.assertTrue(seg.buttons()[1].isChecked())
        self.assertEqual(got, [0, 2, 1])
        seg.setEnabled(False)
        self.assertFalse(seg.isEnabled())
        self.assertFalse(seg.buttons()[0].isEnabled())
        seg.setToolTip("tip")
        self.assertEqual(seg.toolTip(), "tip")
        # bool and float data, as the panel uses them
        b = SegmentedControl([("Vertical", True), ("Horizontal", False)])
        self.assertEqual((b.findData(False), b.findData(True)), (1, 0))
        e = SegmentedControl([("0.5 in", 0.5), ("0.3 in", 0.3)])
        self.assertEqual(e.findData(0.3), 1)

    def test_panel_controls_keep_their_data(self):
        start_app()
        prj, *_ = load_project()
        dock = XSectionsDock(make_iface(), None)
        try:
            dock.restore_from_project()
            expect = {"label_dir": [True, False], "z_mode": ["auto", "manual"],
                      "distance_labels": ["feet", "station"], "grid_color": ["green", "gray", "custom"],
                      "grid_major_style": ["solid", "dash", "dot"], "grid_minor_style": ["solid", "dash", "dot"],
                      "edge_margin": [0.5, 0.3], "fill_grid": ["off", "below", "both"],
                      "screen_values": ["elevation", "depth"], "wl_values": ["elevation", "depth"],
                      "wl_label": ["off", "elev", "elev_date"]}
            for name, data in expect.items():
                w = getattr(explo_row(dock) if name in ("screen_values", "wl_values") else dock, name)
                self.assertIsInstance(w, SegmentedControl, name)
                self.assertEqual([w.itemData(i) for i in range(w.count())], data, name)
            self.assertIsInstance(dock.fmt, QComboBox)                  # four choices: stays a combo
            # a segmented control drives the settings like the combo it replaced
            dock.label_dir.setCurrentIndex(dock.label_dir.findData(False))
            dock.fill_grid.setCurrentIndex(dock.fill_grid.findData("both"))
            s = dock.settings()
            self.assertEqual((s.label_vertical, s.fill_grid), (False, "both"))
        finally:
            dock.cleanup()
            dock.deleteLater()


# ------------------------------------------------------------------ surfaces
class SurfaceTests(PanelCase):
    def test_round_trip_with_two_surfaces_and_every_screen_setting(self):
        tbl = make_wl_table()
        self.prj.addMapLayer(tbl)
        wt = make_raster(1, "wt_2024")
        self.prj.addMapLayer(wt)
        s1 = dict(SURFACE_DEFAULTS, layer_id=wt.id(), band=1, name="Water table 2024", color="#1f6fb2", style="dash",
                  width=1.5, mode="smooth", z_units="ft", in_range=False, marks=True, visible=True)
        s2 = dict(SURFACE_DEFAULTS, layer_id=self.dem.id(), band=1, name="", color="#8c5a3c", style="dot", width=0.25,
                  mode="cells", z_units="m", in_range=True, marks=False, visible=False)
        s = default_settings(self.prj, self.dem, self.pts, self.lines, surfaces=[s1, s2], screens=False,
                             screen_top_field="ScrTop", screen_bottom_field="ScrBot", screen_values="elevation",
                             wl_values="depth", wl_field="GW_Elev", wl_date_field="WL_Date", atd_field="ATD",
                             atd_date_field="ATD_Date", wl_table_id=tbl.id(), wl_table_name_field="Boring",
                             wl_table_elev_field="WL_Elev", wl_table_date_field="Date", wl_table_kind_field="Kind",
                             wl_atd_values=["ATD", "Drilling"], wl_label="elev_date")
        d = self.dock
        d.apply_settings(s)
        self.assertEqual(d.settings(), as_rows(s))
        self.assertEqual(d.settings().surfaces, [s1, s2])
        self.assertEqual(list(d.settings().surfaces[0]), list(SURFACE_DEFAULTS))      # the keys, in order
        self.assertEqual([r.name_label.text() for r in d.surface_rows], ["Water table 2024", "LIDAR_DEM_3ft"])
        self.assertIn("dashed", d.surface_rows[0].sub_label.text())
        # everything empty or off is kept as such
        empty = default_settings(self.prj, self.dem, self.pts, self.lines, wl_values="elevation",
                                 screen_values="depth", wl_label="off")
        d.apply_settings(empty)
        self.assertEqual(d.settings(), as_rows(empty))
        self.assertEqual(explo_row(d).wl_field.currentField(), "")      # an empty saved field stays empty
        # and through the project
        d.apply_settings(s)
        d._user_changed = True
        d.save_settings()
        other = XSectionsDock(self.iface, None)
        try:
            other.restore_from_project()
            self.assertEqual(other.settings(), as_rows(s))
        finally:
            other.cleanup()
            other.deleteLater()

    def test_add_move_remove(self):
        d = self.dock
        wt = make_raster(1, "wt_2024")
        self.prj.addMapLayer(wt)
        r1 = d.add_surface()                                           # the first raster that is not the DEM
        self.assertEqual(r1.value()["layer_id"], wt.id())
        self.assertTrue(r1.editor_open())
        r2 = d.add_surface()                                           # none left: the DEM's layer
        self.assertEqual(r2.value()["layer_id"], self.dem.id())
        self.assertEqual([r.value()["color"] for r in d.surface_rows], list(SURFACE_COLORS[:2]))
        v = r1.value()
        self.assertEqual((v["name"], v["style"], v["mode"], v["z_units"], v["band"]), ("", "solid", "smooth", "auto", 1))
        self.assertTrue(d._user_changed)
        self.assertEqual([x["layer_id"] for x in d.settings().surfaces], [wt.id(), self.dem.id()])
        self.assertFalse(r1.act_up.isEnabled())
        self.assertFalse(r2.act_down.isEnabled())
        r2.act_up.trigger()                                            # Move up (the ⋯ menu)
        self.assertEqual(d.surface_rows, [r2, r1])
        self.assertEqual([x["layer_id"] for x in d.settings().surfaces], [self.dem.id(), wt.id()])
        self.assertEqual(d._surface_layout.indexOf(r2), 1)            # under the ground row (0.3.6: one card)
        r2.act_down.trigger()
        self.assertEqual(d.surface_rows, [r1, r2])
        r1.act_remove.trigger()
        self.assertEqual(d.surface_rows, [r2])
        self.assertEqual(len(d.settings().surfaces), 1)
        # editing a row reaches the settings
        r2.name_edit.setText("Bedrock")
        r2.style_seg.setCurrentIndex(r2.style_seg.findData("dot"))
        r2.width_spin.setValue(2.0)
        r2.marks_box.setChecked(True)
        got = d.settings().surfaces[0]
        self.assertEqual((got["name"], got["style"], got["width"], got["marks"]), ("Bedrock", "dot", 2.0, True))
        self.assertEqual(r2.name_label.text(), "Bedrock")
        # clicking the name toggles the editor
        r2.set_editor_open(False)
        r2.name_area.clicked.emit()
        self.assertTrue(r2.editor_open())

    def test_add_all_bands(self):
        d = self.dock
        multi = make_raster(3, "mf6_botm")
        self.prj.addMapLayer(multi)
        d._fill_bands_menu()
        acts = [a for a in d._bands_menu.actions() if a.isEnabled()]
        self.assertEqual([a.text() for a in acts], ["mf6_botm (3 bands)"])
        acts[0].trigger()
        vals = d.settings().surfaces
        self.assertEqual([(v["layer_id"], v["band"], v["name"]) for v in vals],
                         [(multi.id(), b, f"mf6_botm band {b}") for b in (1, 2, 3)])
        self.assertEqual([v["color"] for v in vals], list(SURFACE_COLORS[:3]))
        self.assertFalse(any(r.editor_open() for r in d.surface_rows))

    def test_missing_raster_is_kept_and_flagged(self):
        d = self.dock
        wt = make_raster(1, "wt_gone")
        self.prj.addMapLayer(wt)
        other = make_raster(1, "another")
        self.prj.addMapLayer(other)
        wid = wt.id()
        row = d.add_surface(wt)
        self.prj.removeMapLayer(wid)
        APP.processEvents()
        self.assertEqual(d.settings().surfaces[0]["layer_id"], wid)     # never swapped for "another"
        self.assertTrue(row.name_label.isWarn())
        self.assertIn("not in the project", row.sub_label.text())
        self.assertEqual(self.chips()["Surfaces"], ("Ground + 1 · 1 missing", True))
        # a saved surface whose raster is gone: kept too
        s = d.settings()
        d.apply_settings(Settings())
        d.apply_settings(s)
        self.assertEqual(d.settings().surfaces[0]["layer_id"], wid)
        self.assertTrue(d.surface_rows[0].name_label.isWarn())
        # choosing a raster clears it
        d.surface_rows[0].layer_combo.setLayer(other)
        self.assertEqual(d.settings().surfaces[0]["layer_id"], other.id())
        self.assertFalse(d.surface_rows[0].name_label.isWarn())

    def test_ground_row(self):
        d = self.dock
        self.assertIn("LIDAR_DEM_3ft", d.ground_sub.text())
        self.assertIn("band 1", d.ground_sub.text())
        self.assertTrue(d.ground_editor.isHidden())                    # a DEM is chosen: folded
        d.ground_name.clicked.emit()
        self.assertFalse(d.ground_editor.isHidden())
        d.dem_layer.setLayer(None)
        self.assertTrue(d.ground_sub.isWarn())
        self.assertEqual(self.chips()["Surfaces"], ("Choose a DEM", True))

    def test_surface_row_alone(self):
        row = SurfaceRow(dict(layer_id=self.dem.id(), color="#ABCDEF", width=9.0, style="zigzag"))
        v = row.value()
        self.assertEqual((v["layer_id"], v["color"], v["width"], v["style"]), (self.dem.id(), "#ABCDEF", 4.0, "solid"))
        seen = []
        row.changed.connect(lambda: seen.append(1))
        row.visible_box.setChecked(False)
        self.assertEqual(len(seen), 1)
        row.set_value(dict(layer_id=""))                               # programmatic: no signal
        self.assertEqual(len(seen), 1)
        self.assertEqual(row.name_label.text(), "(choose a raster)")
        row.deleteLater()


# ------------------------------------------------------------------ screens and water levels
class ScreenTests(PanelCase):
    def test_fields_guessed_for_a_fresh_project(self):
        d = explo_row(self.dock)
        self.assertEqual((d.screen_top_field.currentField(), d.screen_bottom_field.currentField(),
                          d.wl_field.currentField(), d.wl_date_field.currentField(), d.atd_field.currentField(),
                          d.atd_date_field.currentField()),
                         ("ScrTop", "ScrBot", "GW_Elev", "WL_Date", "ATD", "ATD_Date"))
        self.assertEqual(d.wl_values.currentData(), "elevation")
        self.assertEqual(d.screen_top_field.filters(), d.top_field.filters())     # numbers only
        for c in (d.screen_top_field, d.screen_bottom_field, d.wl_field, d.wl_date_field, d.atd_field,
                  d.atd_date_field, d.wl_table_date_field, d.wl_table_kind_field):
            self.assertTrue(c.allowEmptyFieldName())

    def test_fields_follow_the_points_layer(self):
        d = self.dock
        lyr = QgsVectorLayer("Point?crs=EPSG:2927", "Wells", "memory")
        add_fields(lyr, [("Name", QMetaType.Type.QString), ("Scr_Top_ft", QMetaType.Type.Double),
                         ("Screen_Bottom", QMetaType.Type.Double), ("DepthToGW", QMetaType.Type.Double),
                         ("GW_Elev", QMetaType.Type.QString), ("MeasDate", QMetaType.Type.QDate),
                         ("WL_ATD", QMetaType.Type.Double), ("Drill_Date", QMetaType.Type.QString)])
        self.prj.addMapLayer(lyr)
        r = explo_row(d)
        r.layer_combo.setLayer(lyr)
        self.assertEqual((r.screen_top_field.currentField(), r.screen_bottom_field.currentField(),
                          r.wl_field.currentField(), r.wl_date_field.currentField(), r.atd_field.currentField(),
                          r.atd_date_field.currentField()),
                         ("Scr_Top_ft", "Screen_Bottom", "DepthToGW", "MeasDate", "WL_ATD", "Drill_Date"))
        self.assertEqual(r.wl_values.currentData(), "depth")           # guessed from a depth name
        self.assertEqual(layer_rows(d.settings())[0]["wl_values"], "depth")
        r.layer_combo.setLayer(self.pts)                                # back: GW_Elev is an elevation
        self.assertEqual(r.wl_field.currentField(), "GW_Elev")
        self.assertEqual(r.wl_values.currentData(), "elevation")

    def test_saved_wl_values_are_never_overridden(self):
        lyr = QgsVectorLayer("Point?crs=EPSG:2927", "Wells", "memory")
        add_fields(lyr, [("Name", QMetaType.Type.QString), ("DepthToGW", QMetaType.Type.Double)])
        self.prj.addMapLayer(lyr)
        d = self.dock
        s = default_settings(self.prj, self.dem, lyr, self.lines, label_field="Name", wl_field="DepthToGW",
                             wl_values="elevation", type_field="", top_field="", depth_field="")
        d.apply_settings(s)
        self.assertEqual(explo_row(d).wl_values.currentData(), "elevation")
        # a fresh project guesses
        self.prj.removeMapLayers([self.pts.id()])
        settings_store.clear(self.prj)
        d.restore_from_project()
        self.assertEqual((explo_row(d).wl_field.currentField(), explo_row(d).wl_values.currentData()),
                         ("DepthToGW", "depth"))

    def test_enabled_rules(self):
        d = self.dock
        r = explo_row(d)
        widgets = (r.screen_top_field, r.screen_bottom_field, r.screen_values, r.wl_values, r.wl_field, r.atd_field,
                   d.wl_label, r.wl_table)
        self.assertTrue(all(w.isEnabled() for w in widgets))
        table_widgets = (r.wl_table_name_field, r.wl_table_elev_field, r.wl_table_date_field, r.wl_table_kind_field,
                         r.wl_atd_values)
        self.assertFalse(any(w.isEnabled() for w in table_widgets))      # no table
        r.wl_field.setField("")
        self.assertFalse(r.wl_date_field.isEnabled())                    # a date only with its level
        r.wl_field.setField("GW_Elev")
        self.assertTrue(r.wl_date_field.isEnabled())
        tbl = make_wl_table()
        self.prj.addMapLayer(tbl)
        r.wl_table.setLayer(tbl)
        self.assertTrue(all(w.isEnabled() for w in table_widgets))
        r.wl_table_kind_field.setField("")
        self.assertFalse(r.wl_atd_values.isEnabled())
        d.screens.setChecked(False)
        self.assertFalse(any(w.isEnabled() for w in widgets + table_widgets + (r.wl_date_field, r.atd_date_field)))
        self.assertFalse(d.settings().screens)

    def test_water_level_table(self):
        d = self.dock
        tbl = make_wl_table()
        self.prj.addMapLayer(tbl)
        explo_row(d).wl_table.setLayer(tbl)                             # fields guessed from the table
        self.assertEqual((explo_row(d).wl_table_name_field.currentField(), explo_row(d).wl_table_elev_field.currentField(),
                          explo_row(d).wl_table_date_field.currentField(), explo_row(d).wl_table_kind_field.currentField()),
                         ("Boring", "WL_Elev", "Date", "Kind"))
        atd = explo_row(d).wl_atd_values
        values = [atd.itemData(i) for i in range(atd.count())]
        self.assertEqual(values, ["ATD", "atd (field)", "Drilling", "Measured"])
        self.assertEqual(sorted(atd.checkedItemsData()), ["ATD", "atd (field)"])   # the automatic choice ...
        s = d.settings()
        self.assertEqual((layer_rows(s)[0]["wl_table_id"], layer_rows(s)[0]["wl_atd_values"]), (tbl.id(), []))  # ... []
        atd.setItemCheckState(values.index("Drilling"), Qt.CheckState.Checked)
        self.assertEqual(sorted(layer_rows(d.settings())[0]["wl_atd_values"]), ["ATD", "Drilling", "atd (field)"])
        for i in range(atd.count()):
            atd.setItemCheckState(i, Qt.CheckState.Unchecked)
        self.assertEqual(layer_rows(d.settings())[0]["wl_atd_values"], [NO_ATD])   # none: not "automatic"
        d.apply_settings(d.settings())
        self.assertEqual(explo_row(d).wl_atd_values.checkedItemsData(), [])
        # a table that is gone keeps its settings, so the panel can say so
        saved = d.settings()
        saved = dataclasses.replace(saved, point_layers=[dict(layer_rows(saved)[0], wl_atd_values=["Drilling"])])
        d.apply_settings(saved)
        tid = tbl.id()
        self.prj.removeMapLayer(tid)
        APP.processEvents()
        s = layer_rows(d.settings())[0]
        self.assertEqual((s["wl_table_id"], s["wl_table_name_field"], s["wl_table_kind_field"], s["wl_atd_values"]),
                         (tid, "Boring", "Kind", ["Drilling"]))

    def test_removed_layer_is_never_touched(self):
        """Signal connections to a layer are dropped while it still exists, before QGIS deletes it (keeping them
        and disconnecting later touched a deleted layer and crashed a full test run now and then)."""
        d = self.dock
        tbl = make_wl_table()
        self.prj.addMapLayer(tbl)
        explo_row(d).wl_table.setLayer(tbl)
        d._track_layer_signals()
        tid = tbl.id()
        self.assertIn(tid, {lid for lid, _, _ in d._layer_conns})
        self.prj.removeMapLayer(tid)
        APP.processEvents()
        ids = {lid for lid, _, _ in d._layer_conns}
        self.assertNotIn(tid, ids)
        self.assertIn(self.dem.id(), ids)                                  # the others are tracked again
        d._untrack_layer_signals()                                       # safe, and leaves nothing behind
        self.assertEqual(d._layer_conns, [])

    def test_readout(self):
        d = self.dock
        W.set_verbose(True)                                           # (0.3.6: the readouts are Verbose notes)
        self.addCleanup(W.set_verbose, False)
        self.stub(model=screen_model())
        d.refresh()
        text = d.screens_readout.text()
        self.assertTrue(text.startswith("2 screens · 2 measured, 1 ATD water levels"), text)
        self.assertIn("MW-2: water level 522.0 ft is above the top of the screen", text)
        self.assertNotIn("ExploElev", text)                               # only screen / water-level flags
        self.assertFalse(d.screens_readout.isHidden())
        d.screens.setChecked(False)
        d.refresh()
        self.assertTrue(d.screens_readout.isHidden())


class PlainLayerTests(PanelCase):
    """The fixture's points layer as it is (no screen or water-level fields)."""

    extra_fields = None

    def test_nothing_guessed(self):
        d = self.dock
        s = layer_rows(d.settings())[0]
        self.assertEqual((s["screen_top_field"], s["wl_field"], s["atd_field"], s["wl_table_id"], s["wl_atd_values"]),
                         ("", "", "", "", []))


# ------------------------------------------------------------------ MODFLOW 6 surfaces
class MF6HelperTests(unittest.TestCase):
    def test_labels_and_colours(self):
        self.assertEqual([fmt_time(t) for t in (12.5, 1.0, 15.999999999999998, 1234.25, 0.0)],
                         ["12.5", "1", "16", "1,234.25", "0"])
        self.assertEqual(ranges([5, 1, 2, 3]), "1-3, 5")
        self.assertEqual(model_stem(r"C:\run\F9_flowV1.disv.grb"), "F9_flowV1")
        self.assertEqual(model_stem("/run/model.dis"), "model")
        self.assertEqual([default_name(dict(mf6_var=v, mf6_layer=2)) for v in ("top", "botm", "head", "wt")],
                         ["Model top", "Layer 2 bottom", "Layer 2 head", "Water table"])
        # ramps: darker to lighter around the base colour, the base itself for one layer and in the middle of three
        self.assertEqual(ramp(BOTTOM_COLOR, 1), [BOTTOM_COLOR])
        browns = ramp(BOTTOM_COLOR, 3)
        self.assertEqual(browns[1], BOTTOM_COLOR)
        light = [QColor(c).lightness() for c in ramp(BOTTOM_COLOR, 5)]
        self.assertEqual(light, sorted(light))
        self.assertLess(light[0], QColor(BOTTOM_COLOR).lightness())
        self.assertGreater(light[-1], QColor(BOTTOM_COLOR).lightness())
        self.assertEqual(ramp(HEAD_COLOR, 0), [])
        # CRS: the auth id, or the WKT of a CRS without one
        self.assertEqual(crs_text(QgsCoordinateReferenceSystem("EPSG:2927")), "EPSG:2927")
        custom = QgsCoordinateReferenceSystem.fromProj("+proj=tmerc +lat_0=45.3 +lon_0=-120.5 +k=1 +x_0=500000 "
                                                       "+y_0=0 +ellps=GRS80 +units=us-ft +no_defs")
        self.assertTrue(custom.isValid())
        self.assertIn("[", crs_text(custom))
        self.assertEqual(crs_text(QgsCoordinateReferenceSystem()), "")

    def test_times(self):
        hf = mf6.HeadFile(DISV_HDS)
        self.assertEqual(time_items(hf), DISV_TIMES)
        self.assertEqual(time_items(None), [("Last saved", "last")])
        self.assertEqual(times_summary(hf), "6 times saved in 3 stress periods (SP 1-3)")
        self.assertEqual(times_summary(mf6.HeadFile(os.path.join(ROTATED, "dis_rotated.hds"))),
                         "1 stress period saved, SP 1, step 1")
        self.assertEqual([time_words(t, hf) for t in ("last", "3,2", "2,3", "9,1", "3", "2")],
                         ["last saved", "SP 3", "SP 2, step 3", "SP 9, step 1", "SP 3", "SP 2, last step"])
        self.assertEqual(time_words("2,3"), "SP 2, step 3")
        self.assertEqual([parse_time(t) for t in ("2", "2,3", "last", "", "2,3,4", "x")],
                         [(2, 0), (2, 3), None, None, None, None])

    def test_period_choices_and_older_fixed_steps(self):
        """A stress period is offered (and stored) alone, meaning its last saved step; a "kper,kstp" stored for a
        period listed alone (saved by an earlier version) keeps an item of its own, so it round-trips as stored."""
        hf = mf6.HeadFile(DISV_HDS)
        combo = QComboBox()
        fill_time_combo(combo, hf, "3,2")
        items = combo_items(combo)
        self.assertEqual(items[items.index(("SP 3 · t = 60", "3")) + 1], ("SP 3 · step 2 · t = 60", "3,2"))
        self.assertEqual(combo.currentData(), "3,2")
        fill_time_combo(combo, hf, "3")
        self.assertEqual((combo.currentData(), combo.count()), ("3", len(DISV_TIMES)))
        fill_time_combo(combo, hf, "7")
        self.assertEqual((combo.currentText(), combo.currentData()), ("SP 7 (not saved)", "7"))

    def test_water_table_stands_apart_from_heads(self):
        """The water table's colour is well apart from every head colour of a model of up to 6 layers (both are
        dashed lines)."""
        wt = QColor(WT_COLOR)
        for n in range(1, 7):
            for c in ramp(HEAD_COLOR, n):
                q = QColor(c)
                dist = ((q.red() - wt.red()) ** 2 + (q.green() - wt.green()) ** 2 + (q.blue() - wt.blue()) ** 2) ** 0.5
                self.assertGreater(dist, 60.0, (n, c))

    def test_model_surfaces(self):
        got = model_surfaces("g.grb", "h.hds", 3, top=True, bottoms=[3, 1], heads=[2], wt=True, time="2,3",
                             crs="EPSG:2927", mode="cells")
        self.assertEqual([(d["mf6_var"], d["mf6_layer"]) for d in got],
                         [("top", 1), ("botm", 1), ("botm", 3), ("head", 2), ("wt", 1)])
        browns, blues = ramp(BOTTOM_COLOR, 3), ramp(HEAD_COLOR, 3)
        self.assertEqual([d["color"] for d in got], ["#555555", browns[0], browns[2], blues[1], "#1f6fb2"])
        self.assertEqual([d["style"] for d in got], ["solid", "solid", "solid", "dash", "dash"])
        self.assertEqual([d["marks"] for d in got], [False, False, False, False, True])
        for d in got:
            self.assertEqual(list(d), list(SURFACE_DEFAULTS))
            self.assertEqual((d["source"], d["name"], d["mf6_path"], d["mf6_head_path"], d["mf6_time"], d["mf6_crs"],
                              d["mode"]), ("mf6", "", "g.grb", "h.hds", "2,3", "EPSG:2927", "cells"))
            self.assertEqual(clean_surface(d), d)


class MF6Tests(PanelCase):
    """The "+ Add MODFLOW 6…" dialog and model surface rows, on the reader's test models (tests/data/mf6)."""

    def setUp(self):
        super().setUp()
        settings_store.set_user_value(LAST_DIR_KEY, "")
        self.crs = QgsCoordinateReferenceSystem("EPSG:2927")
        self._dialogs = []

    def tearDown(self):
        for dlg in self._dialogs:
            dlg.deleteLater()
        super().tearDown()

    def dialog(self, path=""):
        dlg = MF6Dialog(None, path, self.crs)
        self._dialogs.append(dlg)
        return dlg

    def copy_model(self, model="disv_small", drop=(".hds",)):
        """A copy of a test model without the files ending in `drop`."""
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_mf6_"), model)
        shutil.copytree(os.path.join(MF6_DATA, model), out,
                        ignore=lambda _d, names: [n for n in names if drop and n.lower().endswith(tuple(drop))])
        return out

    # ---- the dialog
    def test_dialog_lists_layers_and_times(self):
        dlg = self.dialog()
        self.assertFalse(dlg.ok_button.isEnabled())
        self.assertFalse(dlg.top_box.isEnabled())
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=DISV) as pick:
            self.assertTrue(dlg.choose(folder=True))
        self.assertEqual(pick.call_args[0][2], "")                        # nothing remembered yet
        self.assertEqual(settings_store.user_value(LAST_DIR_KEY), DISV)   # remembered for next time
        layers = ["Layer 1", "Layer 2", "Layer 3"]
        self.assertEqual([dlg.bottoms.item(i).text() for i in range(dlg.bottoms.count())], layers)
        self.assertEqual([dlg.heads.item(i).text() for i in range(dlg.heads.count())], layers)
        self.assertEqual(combo_items(dlg.time_combo), DISV_TIMES)
        self.assertEqual(dlg.time_combo.currentData(), "last")            # default: the last saved record
        text = dlg.summary.text()
        for part in ("<b>disv_small</b>", "DISV grid, 3 layers × 28 cells per layer, feet", "disv_small.disv.grb",
                     "Heads: disv_small.hds, 6 times saved in 3 stress periods (SP 1-3)."):
            self.assertIn(part, text)
        self.assertTrue(all(w.isEnabled() for w in (dlg.top_box, dlg.bottoms, dlg.heads, dlg.wt_box, dlg.time_combo)))
        self.assertFalse(dlg.ok_button.isEnabled())                       # nothing ticked yet
        self.assertEqual(dlg.crs(), "EPSG:2927")
        self.assertEqual(dlg.mode_seg.currentData(), "smooth")
        # File…: starts in the remembered folder; a head file finds its model
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(DISV_HDS, "")) as pick:
            self.assertTrue(dlg.choose(folder=False))
        self.assertEqual(pick.call_args[0][2], DISV)
        self.assertTrue(same_path(dlg.info.grid_path, DISV_GRB))
        self.assertTrue(same_path(dlg.info.head_path, DISV_HDS))
        # cancelled: the model stays
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=""):
            self.assertFalse(dlg.choose(folder=True))
        self.assertTrue(same_path(dlg.info.grid_path, DISV_GRB))
        # another model keeps the ticks of the layers it has; a time it does not hold falls back to the last
        dlg.heads.item(1).setCheckState(Qt.CheckState.Checked)
        dlg.heads.item(2).setCheckState(Qt.CheckState.Checked)
        dlg.time_combo.setCurrentIndex(dlg.time_combo.findData("2,3"))
        dlg.set_path(ROTATED)
        self.assertEqual(dlg.heads.count(), 2)
        self.assertEqual(dlg.checked_heads(), [2])
        self.assertEqual(combo_items(dlg.time_combo), [("Last saved (SP 1, step 1)", "last"), ("SP 1 · t = 1", "1")])
        self.assertIn("DIS grid, 2 layers × 12 cells per layer (3 rows × 4 columns), feet", dlg.summary.text())

    def test_add_every_kind_in_order(self):
        dlg = self.dialog(DISV)
        dlg.top_box.setChecked(True)
        dlg.btn_bottoms_all.click()
        dlg.btn_heads_all.click()
        dlg.wt_box.setChecked(True)
        dlg.time_combo.setCurrentIndex(dlg.time_combo.findData("2,3"))
        dlg.mode_seg.setCurrentIndex(dlg.mode_seg.findData("cells"))
        self.assertEqual(dlg.ok_button.text(), "Add 8 surfaces")
        self.assertTrue(dlg.ok_button.isEnabled())
        got = dlg.surfaces()
        self.assertEqual([(d["mf6_var"], d["mf6_layer"]) for d in got],
                         [("top", 1), ("botm", 1), ("botm", 2), ("botm", 3), ("head", 1), ("head", 2), ("head", 3),
                          ("wt", 1)])
        self.assertEqual([d["color"] for d in got],
                         ["#555555"] + ramp(BOTTOM_COLOR, 3) + ramp(HEAD_COLOR, 3) + ["#1f6fb2"])
        self.assertEqual([d["style"] for d in got], ["solid"] * 4 + ["dash"] * 4)
        self.assertEqual([d["marks"] for d in got], [False] * 7 + [True])
        for d in got:
            self.assertEqual(list(d), list(SURFACE_DEFAULTS))
            self.assertEqual((d["source"], d["name"], d["mf6_time"], d["mf6_crs"], d["mode"], d["z_units"]),
                             ("mf6", "", "2,3", "EPSG:2927", "cells", "auto"))
            self.assertTrue(same_path(d["mf6_path"], DISV_GRB))
            self.assertTrue(same_path(d["mf6_head_path"], DISV_HDS))
        # into the panel: one model row each, in order, saved
        d = self.dock
        d._user_changed = False
        rows = d.add_model_surfaces(got)
        self.assertTrue(all(isinstance(r, ModelSurfaceRow) for r in rows))
        self.assertFalse(any(r.editor_open() for r in rows))
        self.assertEqual(d.settings().surfaces, got)
        self.assertTrue(d._user_changed)
        self.assertEqual([r.name_label.text() for r in rows],            # the legend's names (with the time)
                         ["Model top", "Layer 1 bottom", "Layer 2 bottom", "Layer 3 bottom",
                          "Layer 1 head (SP 2, step 3)", "Layer 2 head (SP 2, step 3)", "Layer 3 head (SP 2, step 3)",
                          "Water table (SP 2, step 3)"])
        self.assertEqual(rows[4].name_edit.placeholderText(), "Layer 1 head (SP 2, step 3)")
        self.assertEqual(rows[0].sub_label.text(), "disv_small · model top · cells")
        self.assertEqual(rows[2].sub_label.text(), "disv_small · layer 2 bottom · cells")
        self.assertEqual(rows[4].sub_label.text(), "disv_small · layer 1 head · SP 2, step 3 · cells")
        self.assertEqual(rows[7].sub_label.text(), "disv_small · water table · SP 2, step 3 · cells")
        self.assertFalse(any(r.name_label.isWarn() for r in rows))
        self.assertEqual(self.chips()["Surfaces"], ("Ground + 8", False))
        rows[1].visible_box.setChecked(False)
        self.assertEqual(self.chips()["Surfaces"], ("Ground + 7", False))      # visible surfaces, as for rasters
        self.assertTrue(same_path(d._last_model_path(), DISV_GRB))            # where the dialog starts next time

    def test_add_button_runs_the_dialog(self):
        d = self.dock
        seen = []

        def accept(dlg):
            seen.append(dlg)
            dlg.set_path(DISV)
            dlg.wt_box.setChecked(True)
            return QDialog.DialogCode.Accepted

        with mock.patch.object(MF6Dialog, "exec", new=accept):        # (an error in a slot would abort the run)
            rows = d.add_mf6()
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual([(s["mf6_var"], s["marks"], s["source"]) for s in d.settings().surfaces], [("wt", True, "mf6")])
        # cancelled: nothing added; the dialog starts with the model already in the list
        starts = []

        def cancel(dlg):
            starts.append(dlg.info.grid_path if dlg.info is not None else "")
            dlg.top_box.setChecked(True)
            return QDialog.DialogCode.Rejected

        with mock.patch.object(MF6Dialog, "exec", new=cancel):
            d.btn_add_mf6.click()                                       # the button runs it
        self.assertEqual(len(d.settings().surfaces), 1)
        self.assertTrue(same_path(starts[0], DISV_GRB))

    def test_no_head_file_disables_heads_and_time(self):
        folder = self.copy_model(drop=(".hds",))
        dlg = self.dialog(folder)
        self.assertTrue(dlg.info.ok)
        self.assertIsNone(dlg.info.heads)
        for w in (dlg.heads, dlg.wt_box, dlg.time_combo, dlg.btn_heads_all):
            self.assertFalse(w.isEnabled(), w)
        self.assertTrue(dlg.top_box.isEnabled() and dlg.bottoms.isEnabled())
        self.assertEqual(combo_items(dlg.time_combo), [("Last saved", "last")])
        text = dlg.summary.text()
        self.assertIn("No head file.", text)
        self.assertIn("<span style='color:", text)                        # the reader's note, in amber
        self.assertIn("disv_small.hds named in the output control is missing: run the model.", text)
        dlg.wt_box.setChecked(True)                                      # ticked but unavailable: left out
        dlg.heads.item(0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(dlg.surfaces(), [])
        self.assertFalse(dlg.ok_button.isEnabled())
        dlg.top_box.setChecked(True)
        dlg.bottoms.item(2).setCheckState(Qt.CheckState.Checked)
        got = dlg.surfaces()
        self.assertEqual([(s["mf6_var"], s["mf6_layer"], s["mf6_head_path"], s["mf6_time"]) for s in got],
                         [("top", 1, "", "last"), ("botm", 3, "", "last")])
        self.assertEqual(dlg.ok_button.text(), "Add 2 surfaces")

    def test_unusable_choice_is_explained(self):
        empty = tempfile.mkdtemp(prefix="xsec_nomodel_")
        dlg = self.dialog(empty)
        self.assertFalse(dlg.info.ok)
        self.assertIn("No MODFLOW 6 model in", dlg.summary.text())
        self.assertTrue(dlg.path_label.isWarn())
        self.assertFalse(dlg.ok_button.isEnabled())
        self.assertEqual(dlg.surfaces(), [])

    # ---- model rows
    def test_editing_a_model_row(self):
        d = self.dock
        r = d.add_model_surfaces(model_surfaces(DISV_GRB, DISV_HDS, 3, heads=[1]))[0]
        r.set_editor_open(True)
        self.assertEqual(r.sub_label.text(), "disv_small · layer 1 head · last saved · smooth")
        self.assertEqual(r.var_seg.currentData(), "head")
        self.assertTrue(r.layer_spin.isEnabled() and r.time_combo.isEnabled())
        self.assertEqual((r.layer_spin.minimum(), r.layer_spin.maximum()), (1, 3))
        self.assertEqual(combo_items(r.time_combo), DISV_TIMES)
        self.assertEqual(r.units_combo.itemText(0), "Auto (feet)")       # the model's LENGTH_UNITS
        self.assertTrue(same_path(r.file_label.text(), DISV_GRB))
        self.assertEqual(r.file_note.text(), "DISV · 3 layers · feet · heads disv_small.hds")
        d._user_changed = False
        r.time_combo.setCurrentIndex(r.time_combo.findData("3"))
        self.assertEqual(d.settings().surfaces[0]["mf6_time"], "3")
        self.assertTrue(d._user_changed)
        self.assertEqual(r.sub_label.text(), "disv_small · layer 1 head · SP 3 · smooth")   # SP 3: one saved step
        r.layer_spin.setValue(2)
        self.assertEqual((d.settings().surfaces[0]["mf6_layer"], r.name_label.text()), (2, "Layer 2 head (SP 3)"))
        r.time_combo.setCurrentIndex(r.time_combo.findData("2"))
        self.assertEqual((r.name_label.text(), r.sub_label.text()),
                         ("Layer 2 head (SP 2, step 3)", "disv_small · layer 2 head · SP 2, last step · smooth"))
        r.time_combo.setCurrentIndex(r.time_combo.findData("3"))
        r.var_seg.setCurrentIndex(r.var_seg.findData("botm"))
        got = d.settings().surfaces[0]
        self.assertEqual((got["mf6_var"], got["mf6_layer"], got["mf6_time"]), ("botm", 2, "3"))   # time kept
        self.assertTrue(r.layer_spin.isEnabled())
        self.assertFalse(r.time_combo.isEnabled())
        self.assertEqual(r.sub_label.text(), "disv_small · layer 2 bottom · smooth")
        r.var_seg.buttons()[3].click()                                   # Water table
        self.assertEqual(d.settings().surfaces[0]["mf6_var"], "wt")
        self.assertFalse(r.layer_spin.isEnabled())
        self.assertTrue(r.time_combo.isEnabled())
        self.assertEqual((r.name_label.text(), r.sub_label.text()),
                         ("Water table (SP 3)", "disv_small · water table · SP 3 · smooth"))
        r.var_seg.setCurrentIndex(r.var_seg.findData("top"))
        self.assertFalse(r.layer_spin.isEnabled() or r.time_combo.isEnabled())
        self.assertEqual(r.name_label.text(), "Model top")
        # the common fields
        r.name_edit.setText("Top of model")
        r.mode_seg.setCurrentIndex(r.mode_seg.findData("cells"))
        r.marks_box.setChecked(True)
        r.units_combo.setCurrentIndex(r.units_combo.findData("m"))
        got = d.settings().surfaces[0]
        self.assertEqual((got["name"], got["mode"], got["marks"], got["z_units"]), ("Top of model", "cells", True, "m"))
        self.assertEqual(r.name_label.text(), "Top of model")
        # the model CRS
        r.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:2926"))
        self.assertEqual(d.settings().surfaces[0]["mf6_crs"], "EPSG:2926")
        self.assertEqual(list(d.settings().surfaces[0]), list(SURFACE_DEFAULTS))

    def test_change_model_keeps_the_other_choices(self):
        d = self.dock
        r = d.add_model_surfaces(model_surfaces(DISV_GRB, DISV_HDS, 3, heads=[3], time="2,3", crs="EPSG:2926"))[0]
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=ROTATED):
            self.assertTrue(r.change_model(folder=True))
        got = d.settings().surfaces[0]
        self.assertTrue(same_path(got["mf6_path"], os.path.join(ROTATED, "dis_rotated.dis.grb")))
        self.assertTrue(same_path(got["mf6_head_path"], os.path.join(ROTATED, "dis_rotated.hds")))
        self.assertEqual((got["mf6_var"], got["mf6_layer"], got["mf6_time"], got["mf6_crs"], got["style"]),
                         ("head", 2, "2,3", "EPSG:2926", "dash"))            # layer 3 -> the model's last layer
        self.assertEqual(r.time_combo.currentText(), "SP 2 · step 3 (not saved)")
        self.assertEqual(r.layer_spin.maximum(), 2)
        self.assertEqual(r.sub_label.text(), "dis_rotated · layer 2 head · SP 2, step 3 · smooth")
        self.assertEqual(settings_store.user_value(LAST_DIR_KEY), ROTATED)
        # a folder without a model: nothing changes, the note says why
        empty = tempfile.mkdtemp(prefix="xsec_nomodel_")
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=empty):
            self.assertFalse(r.change_model(folder=True))
        self.assertEqual(d.settings().surfaces[0], got)
        self.assertTrue(r.file_note.isWarn())
        self.assertIn("No MODFLOW 6 model", r.file_note.text())

    def test_round_trip_of_every_key(self):
        wkt = QgsCoordinateReferenceSystem("EPSG:2927").toWkt()
        raster = dict(SURFACE_DEFAULTS, layer_id=self.dem.id(), name="Ground again", mf6_path="C:/x.grb",
                      mf6_var="wt", mf6_layer=4, mf6_time="5,6", mf6_crs="EPSG:2926")    # leftover keys are kept
        m1 = dict(SURFACE_DEFAULTS, source="mf6", mf6_path=DISV_GRB, mf6_head_path=DISV_HDS, mf6_var="head",
                  mf6_layer=3, mf6_time="2,1", mf6_crs="", name="Heads L3", color="#123456", style="dot", width=2.5,
                  mode="cells", z_units="m", in_range=False, marks=True, visible=False, layer_id="kept", band=2)
        m2 = dict(SURFACE_DEFAULTS, source="mf6", mf6_path=DISV_GRB, mf6_head_path="", mf6_var="botm", mf6_layer=5,
                  mf6_time="9,9", mf6_crs=wkt, color="#ABCDEF", z_units="ftUS")     # layer and time it lacks
        m3 = dict(SURFACE_DEFAULTS, source="mf6", mf6_path=DISV_GRB, mf6_head_path=DISV_HDS, mf6_var="wt",
                  mf6_layer=1, mf6_time="last", mf6_crs="EPSG:2927", style="dash", marks=True)
        s = default_settings(self.prj, self.dem, self.pts, self.lines, surfaces=[raster, m1, m2, m3])
        d = self.dock
        d.apply_settings(s)
        self.assertEqual([type(r) for r in d.surface_rows], [SurfaceRow, ModelSurfaceRow, ModelSurfaceRow,
                                                             ModelSurfaceRow])
        self.assertEqual(d.settings(), as_rows(s))
        self.assertEqual(d.settings().surfaces, [raster, m1, m2, m3])
        self.assertEqual(d.surface_rows[2].layer_spin.value(), 5)          # kept although the grid has 3 layers
        self.assertEqual(d.surface_rows[2].time_combo.currentData(), "9,9")
        # through the project
        d._user_changed = True
        d.save_settings()
        other = XSectionsDock(self.iface, None)
        try:
            other.restore_from_project()
            self.assertEqual(other.settings(), as_rows(s))
        finally:
            other.cleanup()
            other.deleteLater()

    def test_missing_model_files_are_kept_and_flagged(self):
        gone = tempfile.mkdtemp(prefix="xsec_gone_")
        lost = dict(SURFACE_DEFAULTS, source="mf6", mf6_path=os.path.join(gone, "lost.disv.grb"),
                    mf6_head_path=os.path.join(gone, "lost.hds"), mf6_var="head", mf6_layer=2, mf6_time="3,1",
                    mf6_crs="EPSG:2926", color="#1f6fb2", style="dash", name="")
        top = dict(SURFACE_DEFAULTS, source="mf6", mf6_path=DISV_GRB, mf6_head_path=os.path.join(gone, "lost.hds"),
                   mf6_var="top")
        other_grid = dict(SURFACE_DEFAULTS, source="mf6", mf6_path=DISV_GRB, mf6_var="head",
                          mf6_head_path=os.path.join(ROTATED, "dis_rotated.hds"))
        d = self.dock
        d.apply_settings(default_settings(self.prj, self.dem, self.pts, self.lines, surfaces=[lost, top, other_grid]))
        r_lost, r_top, r_other = d.surface_rows
        self.assertEqual(d.settings().surfaces[0], clean_surface(lost))            # every key kept
        self.assertTrue(r_lost.is_missing())
        self.assertTrue(r_lost.name_label.isWarn())
        self.assertEqual((r_lost.name_label.text(), r_lost.sub_label.text()),
                         ("Layer 2 head", "lost · layer 2 head · model file missing"))
        self.assertTrue(r_lost.file_label.isWarn())
        self.assertFalse(r_top.is_missing())                                   # a model top needs no head file
        self.assertFalse(r_top.name_label.isWarn())
        self.assertTrue(r_other.is_missing())                                  # heads of another grid
        self.assertIn("belongs to another grid", r_other.sub_label.text())
        self.assertEqual(self.chips()["Surfaces"], ("Ground + 3 · 2 missing", True))
        r_top.var_seg.setCurrentIndex(r_top.var_seg.findData("head"))         # now the head file counts
        self.assertTrue(r_top.name_label.isWarn())
        self.assertIn("head file missing", r_top.sub_label.text())
        self.assertEqual(self.chips()["Surfaces"], ("Ground + 3 · 3 missing", True))
        # a model file that goes away while the panel is open
        folder = self.copy_model(drop=())
        grb = os.path.join(folder, "disv_small.disv.grb")
        r_top.set_value(dict(top, mf6_path=grb))
        self.assertFalse(r_top.is_missing())
        os.remove(grb)
        self.assertTrue(r_top.is_missing())

    def test_row_follows_its_files(self):
        """A model run again while the panel is open: the row reads its files again (times, status, chip) on the
        next refresh, or as soon as it is asked whether it is missing, and keeps the stored time."""
        self.stub()
        folder = self.copy_model(drop=())
        grb, hds = os.path.join(folder, "disv_small.disv.grb"), os.path.join(folder, "disv_small.hds")
        with open(DISV_HDS, "rb") as fh:
            full = fh.read()
        with open(hds, "wb") as fh:
            fh.write(full[:6 * (52 + 28 * 8)])                      # still at SP 1
        d = self.dock
        r = d.add_model_surfaces(model_surfaces(grb, hds, 3, heads=[1], time="1,1"))[0]
        self.assertEqual([t for _x, t in combo_items(r.time_combo)], ["last", "1", "1,1", "1,2"])
        with open(hds, "wb") as fh:                                 # the run went on
            fh.write(full)
        os.utime(hds, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
        d.refresh()
        self.assertEqual(combo_items(r.time_combo), DISV_TIMES)
        self.assertEqual((r.time_combo.currentData(), d.settings().surfaces[0]["mf6_time"]), ("1,1", "1,1"))
        # the head file goes and comes back: flagged, then not, without a refresh
        os.remove(hds)
        self.assertTrue(r.is_missing())
        self.assertEqual(d.chip_texts()["surfaces"], ("Ground + 1 · 1 missing", True))
        self.assertTrue(r.name_label.isWarn())
        with open(hds, "wb") as fh:
            fh.write(full)
        self.assertFalse(r.is_missing())
        self.assertEqual(d.chip_texts()["surfaces"], ("Ground + 1", False))
        self.assertFalse(r.name_label.isWarn())

    def test_row_without_its_own_head_file_uses_the_models(self):
        """A surface added before the model ran has no head file of its own; once the model has run, the row finds
        the model's head file as the section build does (not 'no head file'), lists its times, and stores it when
        the surface is switched to a head."""
        self.stub()
        folder = self.copy_model(drop=(".hds",))
        dlg = self.dialog(folder)
        dlg.top_box.setChecked(True)
        got = dlg.surfaces()
        self.assertEqual([(s["mf6_var"], s["mf6_head_path"]) for s in got], [("top", "")])
        d = self.dock
        r = d.add_model_surfaces(got)[0]
        self.assertEqual(r.file_note.text(), "DISV · 3 layers · feet · no head file")
        shutil.copy2(DISV_HDS, os.path.join(folder, "disv_small.hds"))          # the model ran
        d.refresh()
        self.assertEqual(r.file_note.text(), "DISV · 3 layers · feet · heads disv_small.hds")
        self.assertEqual(d.settings().surfaces[0]["mf6_head_path"], "")         # a top keeps what it was given
        r.var_seg.setCurrentIndex(r.var_seg.findData("head"))
        self.assertFalse(r.is_missing())
        self.assertEqual(r.sub_label.text(), "disv_small · layer 1 head · last saved · smooth")
        self.assertEqual(combo_items(r.time_combo), DISV_TIMES)
        self.assertTrue(same_path(d.settings().surfaces[0]["mf6_head_path"], os.path.join(folder, "disv_small.hds")))

    def test_row_names_are_the_legend_names(self):
        """The row's name and the Name placeholder are what the legend will say: a DISU's "Model bottom" and
        "Head", the time of heads when the head file holds several."""
        disu = os.path.join(MF6_DATA, "disu_small")
        rows = self.dock.add_model_surfaces(
            model_surfaces(os.path.join(disu, "disu_small.disu.grb"), os.path.join(disu, "disu_small.hds"), 1,
                           bottoms=[1], heads=[1], wt=True)
            + model_surfaces(DISV_GRB, DISV_HDS, 3, heads=[1], time="1"))
        names = ["Model bottom", "Head (SP 2)", "Water table (SP 2)", "Layer 1 head (SP 1, step 2)"]
        self.assertEqual([r.name_label.text() for r in rows], names)
        self.assertEqual([r.name_edit.placeholderText() for r in rows], names)
        self.assertEqual(rows[1].sub_label.text(), "disu_small · head · last saved · smooth")
        from xsections.core.build import build_section
        s = default_settings(self.prj, self.dem, self.pts, self.lines, surfaces=self.dock.settings().surfaces)
        m = build_section(s, self.prj)
        self.assertEqual([sp.name for sp in m.surfaces], names)
        dlg = self.dialog(disu)
        self.assertEqual((dlg.bottoms.item(0).text(), dlg.heads.item(0).text()), ("Model bottom", "Head"))

    def test_several_flow_models_in_one_simulation(self):
        """The dialog says which model of the simulation it shows and how to take another; Change… → Run folder…
        keeps the row's model."""
        sim = tempfile.mkdtemp(prefix="xsec_twomodels_")
        for model in ("disv_small", "dis_rotated"):
            for name in os.listdir(os.path.join(MF6_DATA, model)):
                if name != "mfsim.nam":
                    shutil.copy2(os.path.join(MF6_DATA, model, name), sim)
        with open(os.path.join(sim, "mfsim.nam"), "w") as fh:
            fh.write("BEGIN models\n  gwf6  disv_small.nam  disv_small\n  gwf6  dis_rotated.nam  dis_rotated\n"
                     "END models\n")
        dlg = self.dialog(sim)
        self.assertEqual(dlg.info.model_name, "disv_small")
        self.assertIn("The simulation has 2 flow models (disv_small, dis_rotated): for another, choose its name file "
                      "(.nam) with File….", dlg.summary.text())
        info = load_model(os.path.join(sim, "dis_rotated.nam"))
        r = self.dock.add_model_surfaces(model_surfaces(info.grid_path, info.head_path, 2, heads=[1]))[0]
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=sim):
            self.assertTrue(r.change_model(folder=True))
        self.assertTrue(same_path(self.dock.settings().surfaces[0]["mf6_path"], os.path.join(sim, "dis_rotated.dis.grb")))

    def test_empty_model_crs_shows_the_project_crs(self):
        """An empty model CRS (the project CRS) is shown as "Project CRS (…)", following the project's CRS; it can
        be chosen, and an explicit CRS replaces it."""
        r = self.dock.add_model_surfaces([dict(model_surfaces(DISV_GRB, DISV_HDS, 3, top=True)[0], mf6_crs="")])[0]
        combo = r.crs_widget.findChildren(QComboBox)[0]
        self.assertFalse(r.crs_widget.crs().isValid())
        self.assertEqual(combo.currentText(), "Project CRS (EPSG:2927)")
        self.prj.setCrs(QgsCoordinateReferenceSystem("EPSG:32610"))
        self.assertEqual(combo.currentText(), "Project CRS (EPSG:32610)")
        self.assertEqual(self.dock.settings().surfaces[0]["mf6_crs"], "")
        r.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:2927"))
        self.assertEqual(self.dock.settings().surfaces[0]["mf6_crs"], "EPSG:2927")
        combo.setCurrentIndex(combo.findText("Project CRS (EPSG:32610)"))
        self.assertEqual(self.dock.settings().surfaces[0]["mf6_crs"], "")

    def test_model_paths_are_stored_relative_to_the_project(self):
        """Model files are stored like the project's layer sources: relative to the project file, so moving the job
        folder (project and model runs) keeps the model surfaces; Save As stores them relative to the new place; a
        project not saved yet stores absolute paths."""
        job = os.path.join(tempfile.mkdtemp(prefix="xsec_job_"), "Project A (2025) Müller")
        run = os.path.join(job, "model run 1")
        shutil.copytree(DISV, run)
        grb, hds = os.path.join(run, "disv_small.disv.grb"), os.path.join(run, "disv_small.hds")
        d = self.dock
        d.add_model_surfaces(model_surfaces(grb, hds, 3, wt=True))
        d.save_settings()

        def stored():
            return json.loads(settings_store.stored_json(self.prj))["surfaces"][0]

        self.assertEqual(stored()["mf6_path"], grb)                 # not saved yet: absolute
        qgs = os.path.join(job, "section.qgs")
        self.assertTrue(self.prj.write(qgs))                        # the dock stores the settings again meanwhile
        self.assertEqual((stored()["mf6_path"], stored()["mf6_head_path"]),
                         ("./model run 1/disv_small.disv.grb", "./model run 1/disv_small.hds"))
        self.assertEqual(d.settings().surfaces[0]["mf6_path"], grb)         # absolute in memory
        moved = job.replace("Project A (2025) Müller", "Moved B")
        self.prj.clear()
        shutil.move(job, moved)
        self.assertTrue(self.prj.read(os.path.join(moved, "section.qgs")))
        d.restore_from_project()                                    # (the plugin does this on readProject)
        s = settings_store.load(self.prj)
        self.assertTrue(same_path(s.surfaces[0]["mf6_path"], os.path.join(moved, "model run 1", "disv_small.disv.grb")))
        self.assertTrue(os.path.isfile(s.surfaces[0]["mf6_head_path"]))
        self.assertEqual(d.settings().surfaces[0]["mf6_path"], s.surfaces[0]["mf6_path"])
        self.assertFalse(d.surface_rows[0].is_missing())
        elsewhere = os.path.join(tempfile.mkdtemp(prefix="xsec_saveas_"), "copy.qgs")      # Save As elsewhere
        self.assertTrue(self.prj.write(elsewhere))
        rel = stored()["mf6_head_path"]
        self.assertFalse(os.path.isabs(rel))
        self.assertTrue(same_path(os.path.join(os.path.dirname(elsewhere), rel),
                                  os.path.join(moved, "model run 1", "disv_small.hds")))

    def test_add_buttons_fit_the_narrowest_panel(self):
        d = self.dock
        d.resize(260, 900)
        d.show()
        d.grp_ground.setCollapsed(False)              # (showing the panel closes every section)
        APP.processEvents()
        try:
            for b in (d.btn_add_surface, d.btn_add_bands, d.btn_add_mf6):
                self.assertTrue(b.isVisible(), b.text())
                self.assertGreaterEqual(b.width(), b.fontMetrics().horizontalAdvance(b.text()) + 8, b.text())
            top = lambda w: w.mapTo(d, w.rect().topLeft()).y()      # noqa: E731
            self.assertEqual(top(d.btn_add_surface), top(d.btn_add_bands))
            # (0.3.6: one row, as the mockup; + MODFLOW 6… on a second row only where they do not all fit whole)
            row = d.add_surfaces_row
            if row.width() >= row.one_line_width():
                self.assertEqual(top(d.btn_add_mf6), top(d.btn_add_surface))
            else:
                self.assertGreater(top(d.btn_add_mf6), top(d.btn_add_surface))
            for b in (d.btn_add_surface, d.btn_add_bands, d.btn_add_mf6):
                self.assertGreaterEqual(b.width(), b.minimumSizeHint().width(), b.text())   # never cut short
            # the variable buttons fit too ("Water table" becomes "WT")
            r = d.add_model_surfaces(model_surfaces(DISV_GRB, DISV_HDS, 3, heads=[1]))[0]
            r.set_editor_open(True)
            APP.processEvents()
            for b in r.var_seg.buttons():
                self.assertGreaterEqual(b.width(), b.fontMetrics().horizontalAdvance(b.text()) + 4, b.text())
            d.resize(340, 900)
            APP.processEvents()
            self.assertEqual([b.text() for b in r.var_seg.buttons()], ["Top", "Bottom", "Head", "Water table"])
        finally:
            d.hide()


@unittest.skipUnless(REALDATA and os.path.isdir(os.path.join(REALDATA, "mf6")), "XSECTIONS_REALDATA not set")
class MF6RealDataTests(PanelCase):
    """The user's models (read-only copies): F9_flowV1 (DISV, 3 layers, 30 stress periods) and CDF_Mounding (DISU)."""

    @timing_test
    def test_f9(self):
        t0 = time.perf_counter()
        dlg = MF6Dialog(None, os.path.join(REALDATA, "mf6", "F9_flowV1"), QgsCoordinateReferenceSystem("EPSG:2927"))
        try:
            self.assertLess(time.perf_counter() - t0, budget(10.0))
            self.assertEqual(dlg.bottoms.count(), 3)
            items = combo_items(dlg.time_combo)
            self.assertEqual(len(items), 31)
            self.assertEqual(items[0], ("Last saved (SP 30, step 13)", "last"))
            self.assertEqual(items[1], ("SP 1 · t = 1", "1"))
            self.assertEqual(items[16], ("SP 16 · t = 16", "16"))      # its last saved step: 16 now, maybe not next run
            text = dlg.summary.text()
            self.assertIn("DISV grid, 3 layers × 27,688 cells per layer, feet", text)
            self.assertIn("30 stress periods saved, SP 1-30, step 13 (SP 16: step 16, SP 17: step 14)", text)
            dlg.btn_heads_all.click()
            dlg.wt_box.setChecked(True)
            rows = self.dock.add_model_surfaces(dlg.surfaces())
            self.assertEqual([r.sub_label.text() for r in rows],
                             ["F9_flowV1 · layer 1 head · last saved · smooth",
                              "F9_flowV1 · layer 2 head · last saved · smooth",
                              "F9_flowV1 · layer 3 head · last saved · smooth",
                              "F9_flowV1 · water table · last saved · smooth"])
        finally:
            dlg.deleteLater()

    def test_cdf_mounding_disu(self):
        dlg = MF6Dialog(None, os.path.join(REALDATA, "mf6", "CDF_Mounding"), QgsCoordinateReferenceSystem("EPSG:2927"))
        try:
            self.assertTrue(dlg.info.ok)
            self.assertEqual((dlg.bottoms.count(), dlg.heads.count()), (1, 1))
            self.assertEqual(dlg.time_combo.count(), 50)
            text = dlg.summary.text()
            self.assertIn("DISU grid, 9,546 nodes (1 layer), length units unknown", text)
            self.assertIn("49 stress periods saved, SP 1-49, step 15", text)
        finally:
            dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
