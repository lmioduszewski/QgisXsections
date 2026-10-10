"""The redesigned panel (0.3.6, DESIGN.md decision 27; stage P3 of the panel build): the six sections and their
subsections, every moved control and its new text, what is shown only under Manual or a typed grid spacing, Verbose
(the ⋯ menu, per user, never in the project), the rows' problems and guesses (ui.problems: one amber line, a count
badge, the check card, the header count chips, "Looks right"), the status line, the check card opened from the dock,
the Flare bands painted by the section bodies, Other features rows of three kinds added from the dock, and the
narrowest panel.

The fixture project with explorations by others, supply wells, seeps, a creek layer and a site; the core and render
pipeline is stubbed with tests.test_ui's hand-made model where the test is about the panel."""
import json
import unittest
from types import SimpleNamespace

from tests.fixtures import (TOLERANCE, area_row, explo_row, load_project, make_areas_layer, make_others_layer,
                            make_seeps_layer, make_streams_layer, make_supply_layer, other_row, point_row, seep_row,
                            start_app, stream_row)

APP = start_app()

from qgis.core import QgsFeature, QgsField, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtCore import QMetaType, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QPalette  # noqa: E402
from qgis.PyQt.QtTest import QTest  # noqa: E402
from qgis.PyQt.QtWidgets import QCheckBox, QLabel  # noqa: E402

from tests.test_ui import fake_model, fake_plan, make_iface  # noqa: E402
from xsections.core.model import SectionError, Settings  # noqa: E402
from xsections.ui import problems as P  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402
from xsections.ui.dock import XSectionsDock  # noqa: E402
from xsections.ui.point_rows import PlottedList  # noqa: E402

UNITS_WARNING = ("The DEM does not state its elevation units; assumed feet (its map units). Set them under Surfaces > "
                 "More: units and datum if that is wrong.")


def settle(n=12):
    for _ in range(n):
        APP.processEvents()


def water_table(rows=(("B-2x", "dry"), ("O-1", "n/a"), ("O-4", "12.5"))):
    """A table of water levels whose level field (DTW) is text: "dry" and "n/a" are not numbers."""
    lyr = QgsVectorLayer("None", "Boring Summary", "memory")
    lyr.dataProvider().addAttributes([QgsField("ExploName", QMetaType.Type.QString),
                                      QgsField("DTW", QMetaType.Type.QString)])
    lyr.updateFields()
    feats = []
    for name, dtw in rows:
        f = QgsFeature(lyr.fields())
        f.setAttributes([name, dtw])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


def flagged_model(flags):
    """tests.test_ui.fake_model with `flags` on MW-2, an exploration of the second row (and in the warnings)."""
    m = fake_model()
    m.hits[1].layer_index = 1
    m.hits[1].flags = list(flags)
    m.warnings = [w for w in m.warnings if not w.startswith("MW-2:")] + [f"MW-2: {f}" for f in flags]
    return m


def field_label_of(w):
    """The field name (field_box's label) above `w`."""
    return next(lab.text() for lab in w.parentWidget().findChildren(QLabel) if lab.objectName() == "xsFieldLabel")


def subsections(sec):
    lay = sec.body_layout
    return [lay.itemAt(i).widget() for i in range(lay.count()) if isinstance(lay.itemAt(i).widget(), W.Subsection)]


def subsection(sec, title):
    return next(s for s in subsections(sec) if s.title() == title)


class PanelCase(unittest.TestCase):
    """The fixture project with the extra layers, and a dock restored on saved rows (no guesses)."""

    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.others, self.supply, self.seeps = make_others_layer(), make_supply_layer(), make_seeps_layer()
        self.prj.addMapLayers([self.others, self.supply, self.seeps])
        self.dock = self.new_dock()

    def new_dock(self) -> XSectionsDock:
        d = XSectionsDock(make_iface(), None)
        self.addCleanup(self._drop, d)
        return d

    @staticmethod
    def _drop(d) -> None:
        d.hide()
        d.cleanup()
        d.deleteLater()
        APP.processEvents()

    def settings(self, **over) -> Settings:
        s = Settings(line_layer_id=self.lines.id(), line_fid=1, dem_layer_id=self.dem.id(), tolerance_ft=TOLERANCE,
                     point_layers=[
                         point_row(self.pts, label_field="ExploName", type_field="ExploType", top_field="ExploElev",
                                   depth_field="ExploDepth"),
                         point_row(self.others, label_field="ExploName", type_field="ExploType_resolved",
                                   top_field="ExploElev", depth_field="ExploDepth", look="gray")])
        if "other_points" not in over:
            s.other_points = [seep_row(self.seeps, label_field="Name", elev_field="Elev_ft")]
        for k, v in over.items():
            setattr(s, k, v)
        return s

    def restore(self, s: Settings, dock=None) -> XSectionsDock:
        d = dock or self.dock
        settings_store.save(self.prj, s)
        d.restore_from_project()
        return d

    def stub(self, model=None, plan=None, exc=None, dock=None):
        def pipeline(_s):
            if exc is not None:
                raise exc
            return model or fake_model(), plan or fake_plan()
        (dock or self.dock)._pipeline = pipeline

    def show(self, d=None, width=340, height=900):
        d = d or self.dock
        d.resize(width, height)
        d.show()
        settle()
        return d

    def verbose(self):
        W.set_verbose(True)
        self.addCleanup(W.set_verbose, False)


# ------------------------------------------------------------------ 7.3-1 to 7.3-4: sections, places, rules, texts
class Layout(PanelCase):
    def test_sections_and_subsections(self):
        d = self.restore(self.settings())
        self.assertEqual([s.title() for s in d.sections],
                         ["Line", "Surfaces", "Explorations", "Other features", "Scale & sheet", "Sheet style"])
        self.assertEqual([s.objectName() for s in d.sections],
                         ["xsectionsLineGroup", "xsectionsGroundGroup", "xsectionsExplorationsGroup",
                          "xsectionsOtherGroup", "xsectionsExportGroup", "xsectionsStyleGroup"])
        self.assertEqual([s.title() for s in subsections(d.grp_explo)], ["Layers", "All layers", "Depths",
                                                                         "Water & screens"])
        self.assertIsInstance(d.plotted, PlottedList)
        body = d.grp_explo.body_layout
        self.assertEqual(body.indexOf(d.plotted), body.indexOf(d.grp_screens) + 1)
        self.assertEqual(body.indexOf(d.explo_readout), body.indexOf(d.plotted) + 1)
        self.assertEqual(d.plotted.heading.title(), "Plotted")
        self.assertEqual([s.title() for s in subsections(d.grp_other)], ["Layers"])
        self.assertEqual([s.title() for s in subsections(d.grp_export)], ["Scale", "Elevations", "Sheet"])
        self.assertEqual([s.title() for s in subsections(d.grp_style)], ["Grid", "Depth lines", "Page"])
        self.assertEqual((d.grp_depth, d.grp_screens), (subsection(d.grp_explo, "Depths"),
                                                         subsection(d.grp_explo, "Water & screens")))
        # closed after construction, restore, clear and reopen
        self.assertTrue(all(s.isCollapsed() for s in d.sections))
        for s in d.sections:
            s.setCollapsed(False)
        d.restore_from_project()
        self.assertTrue(all(s.isCollapsed() for s in d.sections))
        d.grp_other.setCollapsed(False)
        d.project_cleared()
        self.assertTrue(all(s.isCollapsed() for s in d.sections))
        self.show(d)
        d.grp_style.setCollapsed(False)
        d.hide()
        d.show()
        self.assertTrue(all(s.isCollapsed() for s in d.sections))

    def test_moved_controls(self):
        d = self.restore(self.settings())
        where = {
            d.grp_line: [d.line_layer, d.line_feature, d.btn_pick, d.line_hint, d.ends_row, d.line_readout],
            d.ends_row: [d.start_label, d.end_label, d.btn_reverse, d.btn_save_line],
            d.ground_row: [d.ground_name, d.ground_title, d.ground_sub, d.ground_editor, d.dem_layer, d.dem_band],
            d.surface_list: [d.ground_row],
            d.grp_ground: [d.surface_list, d.btn_add_surface, d.btn_add_bands, d.btn_add_mf6, d.units_more,
                           d.ground_readout],
            d.units_more: [d.z_units, d.datum],
            subsection(d.grp_explo, "Layers"): [d.explo_list, d.btn_add_points, d.layers_note],
            subsection(d.grp_explo, "All layers"): [d.tolerance, d.label_dir, d.label_text, d.within_hint],
            d.grp_depth: [d.depth_line, d.td_label, d.top_mode, d.checks_more, d.depth_readout],
            d.checks_more: [d.zero_missing, d.top_max_diff, d.top_max_diff_row],
            d.grp_screens: [d.screens, d.wl_label, d.screens_readout],
            d.grp_explo: [d.grp_depth, d.grp_screens, d.plotted, d.explo_readout],
            subsection(d.grp_other, "Layers"): [d.other_list, d.btn_add_other, d.other_readout],
            subsection(d.grp_export, "Scale"): [d.h_scale, d.v_scale],
            subsection(d.grp_export, "Elevations"): [d.z_mode, d.tile, d.z_range_row, d.z_min, d.z_max],
            subsection(d.grp_export, "Sheet"): [d.sheet, d.fmt, d.orientation, d.title_text, d.distances_more,
                                                d.export_readout],
            d.distances_more: [d.distance_labels, d.allowed_sheets],
            subsection(d.grp_style, "Grid"): [d.grid_color, d.grid_info, d.grid_custom_box, d.grid_auto,
                                              d.grid_spacing_row, d.h_major, d.h_minor, d.v_major, d.v_minor,
                                              d.fill_grid, d.below_in],
            subsection(d.grp_style, "Depth lines"): [d.depth_lw_head, d.btn_lw_reset, d.depth_lw_black,
                                                     d.depth_lw_color, d.depth_lw_hint],
            subsection(d.grp_style, "Page"): [d.edge_margin, d.compact_layout, d.show_notes, d.show_bends,
                                              d.shade_below, d.style_hint],
        }
        for box, widgets in where.items():
            for w in widgets:
                self.assertTrue(box.isAncestorOf(w), (box, w))
        self.assertIs(d.depth_lw_head, subsection(d.grp_style, "Depth lines").heading)
        self.assertTrue(d.depth_lw_head.isAncestorOf(d.btn_lw_reset))
        self.assertIs(d.ground_editor, d.ground_row.editor)
        self.assertEqual((d.surface_list.objectName(), d._surface_layout.indexOf(d.ground_row)), ("xsSurfaceRows", 0))
        self.assertEqual(d._disclosures, [d.units_more, d.checks_more, d.distances_more])
        self.assertEqual([m.text() for m in d._disclosures], ["Units & datum", "Checks", "Distances & printers"])
        # one row each: Pick | Draw | Selected; + Surface | + Bands… | + MODFLOW 6…; Legend | Drawn in
        self.assertTrue(d.btn_pick.parentWidget() is d.btn_draw.parentWidget() is d.btn_selected.parentWidget())
        self.assertTrue(d.add_surfaces_row.isAncestorOf(d.btn_add_mf6))
        row = explo_row(d)
        legend_pair = row.name_edit.parentWidget().parentWidget()
        self.assertTrue(legend_pair.isAncestorOf(row.look_seg))
        for pane, widgets in ((row.pane_layer, (row.layer_combo, row.name_edit, row.look_seg, row.type_list)),
                              (row.pane_depths, (row.top_field, row.depth_field, row.in_range_box)),
                              (row.pane_water, (row.wl_field, row.atd_field, row.wl_table, row.table_box))):
            for w in widgets:
                self.assertTrue(pane.isAncestorOf(w), w)
        # gone
        for name in ("depth_lw_new", "style_rule", "_other_flags_shown"):
            self.assertFalse(hasattr(d, name), name)
        self.assertFalse(hasattr(d.plotted, "setExpanded") or hasattr(d.plotted, "isExpanded"))
        texts = [lab.text() for lab in d.content.findChildren(QLabel)]
        for gone in ("from LIDAR", "drawn in this order", "all layers", "Point layers"):
            self.assertNotIn(gone, texts)

    def test_shown_only_when_wanted(self):
        d = self.show(self.restore(self.settings()))
        for s in d.sections:
            s.setCollapsed(False)
        settle()
        self.assertTrue(d.z_range_row.isHidden())                    # Auto
        d.z_mode.buttons()[d.z_mode.findData("manual")].click()
        self.assertFalse(d.z_range_row.isHidden())
        d.z_mode.buttons()[d.z_mode.findData("auto")].click()
        self.assertTrue(d.z_range_row.isHidden())
        self.assertTrue(d.grid_spacing_row.isHidden())               # Spacing from the scale
        d.grid_auto.setChecked(False)
        self.assertFalse(d.grid_spacing_row.isHidden())
        d.grid_auto.setChecked(True)
        self.assertTrue(d.grid_spacing_row.isHidden())
        # collapse_all: pills folded, rows closed and back on their Layer tab, the ground open only without a DEM
        for m in d._disclosures:
            m.setExpanded(True)
        for r in d.explo_rows:
            r.show_tab("water")
        other_row(d).set_editor_open(True)
        d.collapse_all()
        self.assertFalse(any(m.isExpanded() for m in d._disclosures))
        self.assertEqual([(r.editor_open(), r.current_tab()) for r in d.explo_rows], [(False, "layer")] * 2)
        self.assertFalse(other_row(d).editor_open())
        self.assertFalse(d.ground_row.editor_open())
        d.dem_layer.setLayer(None)
        toggled = []
        d.ground_row.editorToggled.connect(toggled.append)
        d.collapse_all()
        self.assertTrue(d.ground_row.editor_open())
        self.assertEqual((toggled, d.ground_row.gaps()), ([True], (4, 0)))   # (set_editor_open: the band's gaps)
        d.dem_layer.setLayer(self.dem)
        d.collapse_all()
        # move_surface keeps the ground row first
        r1, r2 = d.add_surface(self.dem), d.add_surface(self.dem)
        d.move_surface(r2, -1)
        self.assertEqual([d._surface_layout.indexOf(w) for w in (d.ground_row, r2, r1)], [0, 1, 2])
        self.assertTrue(d.ground_row._first and not d.ground_row._last)
        # two open exploration rows: 12 px band to band, their swoops overlapping
        d.grp_explo.setCollapsed(False)
        for r in d.explo_rows:
            r.set_editor_open(True)
        settle()
        bands = d.grp_explo.body.bands()
        self.assertEqual(len(bands), 2)
        self.assertEqual(bands[1][0] - bands[0][1], 12)

    def test_texts(self):
        d = self.restore(self.settings())
        self.assertEqual(d.grp_other.title(), "Other features")
        self.assertEqual(field_label_of(d.line_layer), "Layer")
        self.assertEqual([b.text() for b in (d.btn_pick, d.btn_draw, d.btn_selected)], ["Pick", "Draw", "Selected"])
        self.assertTrue(all(b.icon().isNull() for b in (d.btn_pick, d.btn_draw, d.btn_selected)))
        self.assertIn("Ends", [lab.text() for lab in d.ends_row.findChildren(QLabel)])
        self.assertEqual((d.btn_save_line.text(), d.btn_save_line.toolTip()),
                         ("Save to layer", 'Add this section line to the temporary layer "XSections lines"'))
        self.assertEqual(d.line_hint.text(), "Pick a line on the map, draw one, or use the selected feature of the "
                                             "layer.")
        self.assertEqual([b.text() for b in (d.btn_add_surface, d.btn_add_bands, d.btn_add_mf6)],
                         ["+ Surface", "+ Bands…", "+ MODFLOW 6…"])
        self.assertEqual(d.btn_add_surface.toolTip(), "Add another raster line: a water table, a model layer…")
        self.assertEqual(d.ground_name.toolTip(), "The ground: always drawn; the explorations sit on it. Click to "
                                                  "choose its DEM")
        self.assertEqual((d.layers_note.text(), d.layers_note.toolTip()), ("top drawn first",
                                                                           "Layers are drawn top first"))
        self.assertEqual((d.btn_add_points.text(), d.btn_add_points.objectName()), ("+ Add layer", "xsAdd"))
        self.assertEqual(d.btn_add_points.toolTip(), "Add an explorations layer: your own, explorations by others, "
                                                     "supply wells…")
        self.assertEqual(field_label_of(d.tolerance), "Within")
        self.assertEqual(d.within_hint.text(), "“Within” applies to the Other features point layers too.")
        self.assertEqual((d.depth_line.text(), d.depth_line.toolTip()),
                         ("Depth line", "Draw a line from the top of each exploration down to its bottom"))
        self.assertEqual((d.td_label.text(), d.td_label.toolTip()),
                         ("TD label", "Label the total depth, as TD 50′, just below the bottom of each line"))
        self.assertEqual((field_label_of(d.top_mode), d.top_mode.toolTip()),
                         ("Tops from", "Where each exploration's top comes from (all layers)"))
        self.assertEqual(d.zero_missing.text(), "0 means missing")
        self.assertTrue(d.zero_missing.toolTip().startswith("Tops, depths, screens and water levels of 0 are taken as "
                                                            "missing (shapefiles store an empty number as 0)."))
        self.assertIn("Ignore a table top off LIDAR by over",
                      [lab.text() for lab in d.top_max_diff_row.findChildren(QLabel)])
        self.assertEqual(d.screens.text(), "Draw them")
        self.assertTrue(d.screens.toolTip().startswith("Draw screens and water levels: "))
        self.assertEqual(field_label_of(d.wl_label), "Print beside")
        self.assertEqual([d.wl_label.itemText(i) for i in range(d.wl_label.count())], ["Off", "Elev.", "+ date"])
        self.assertEqual(d.plotted.hint.text(), "Untick one to leave it off this section only.")
        self.assertEqual((d.btn_add_other.text(), d.btn_add_other.toolTip()),
                         ("+ Add layer", "Add a layer of other features: seeps or springs (points), creeks (lines), a "
                                         "site (areas)"))
        self.assertEqual([field_label_of(w) for w in (d.sheet, d.fmt, d.orientation, d.title_text, d.z_min, d.z_max)],
                         ["Size", "Format", "Orientation", "Title", "Lowest", "Highest"])
        self.assertEqual((d.z_min.suffix(), d.z_max.suffix()), (" ft", " ft"))
        self.assertEqual([b.toolTip() for b in d.z_mode.buttons()],
                         ["Rounded to the major grid", "Type the lowest and highest elevations"])
        self.assertEqual(d.title_text.placeholderText(), "Optional (project, site…)")
        self.assertEqual([field_label_of(w) for w in (d.distance_labels, d.allowed_sheets)],
                         ["Distances", "Printers take"])
        self.assertEqual([field_label_of(w) for w in (d.grid_color, d.fill_grid, d.below_in, d.depth_lw_black,
                                                      d.depth_lw_color, d.edge_margin)],
                         ["Look", "Fill sheet", "Below lowest", "Black & gray", "Color", "Printer edge"])
        self.assertEqual(d.grid_auto.text(), "Spacing from the scale (1 in, 0.1 in)")
        self.assertEqual([field_label_of(w.parentWidget()) for w in (d.h_major, d.v_major)],
                         ["Horizontal, ft", "Vertical, ft"])
        self.assertEqual([w.toolTip() for w in (d.h_major, d.h_minor, d.v_major, d.v_minor)],
                         ["Major spacing, ft", "Minor spacing, ft", "Major spacing, ft", "Minor spacing, ft"])
        self.assertEqual(d.depth_lw_hint.text(), "Which layers are black, gray or in color is set for each layer, "
                                                 "under Explorations › <b>Drawn in</b>.")
        self.assertEqual(d.style_hint.text(), "The defaults leave the most room to draw and the paper clear for "
                                              "colored pencil.")
        d.grid_auto.setChecked(False)
        self.assertEqual(d.grid_spacing_note.text(), "Major and minor lines at the spacing below.")
        self.assertIn("solid", d.grid_info.text())
        self.assertNotIn("the default", d.grid_info.text())
        self.assertEqual([a.text() for a in d.btn_more.menu().actions() if not a.isSeparator()],
                         ["Export points CSV…", "Save line to layer", "Verbose"])


# ------------------------------------------------------------------ 7.3-5: Verbose
class Verbose(PanelCase):
    def test_the_menu_item(self):
        d = self.restore(self.settings())
        acts = d.btn_more.menu().actions()
        self.assertIs(acts[-1], d.act_verbose)
        self.assertTrue(acts[-2].isSeparator())
        self.assertTrue(d.act_verbose.isCheckable())
        self.assertFalse(d.act_verbose.isChecked())                  # off by default (the test profile)
        self.assertEqual(d.act_verbose.toolTip(), "Hints and notes under the controls")
        self.assertTrue(d.btn_more.menu().toolTipsVisible())
        self.show(d)
        for s in d.sections:
            s.setCollapsed(False)
        for m in d._disclosures:
            m.setExpanded(True)
        d.refresh()
        settle()
        hints = d.findChildren(W.Hint)
        self.assertTrue(all(h.isHidden() for h in hints))             # Verbose off: no hint, no readout
        self.addCleanup(W.set_verbose, False)
        d.act_verbose.trigger()
        self.assertTrue(W.verbose())
        self.assertEqual(settings_store.user_value("verbose"), "1")
        shown = [h for h in hints if h.wanted()]
        for h in shown:
            self.assertFalse(h.isHidden(), h.text())
        for h in (d.line_hint, d.within_hint, d.style_hint, d.depth_lw_hint, d.line_readout, d.explo_readout,
                  d.export_readout):
            self.assertIn(h, shown)
            self.assertTrue(h.isVisible(), h.text())
        self.assertIsInstance(d.explo_readout, W.Readout)
        # a panel made afterwards starts with it on; the menu follows the switch made elsewhere
        second = self.new_dock()
        self.assertTrue(second.act_verbose.isChecked())
        W.set_verbose(False)
        self.assertFalse(d.act_verbose.isChecked() or second.act_verbose.isChecked())
        self.assertTrue(all(h.isHidden() for h in hints))
        # never in the project
        d.tolerance.setValue(77.0)
        d.save_settings()
        self.assertNotIn("verbose", settings_store.stored_json(self.prj).lower())
        self.assertNotIn("verbose", d.settings().to_json().lower())


# ------------------------------------------------------------------ 7.3-6: problems and guesses
class Problems(PanelCase):
    def test_a_flag(self):
        d = self.restore(self.settings(other_points=[]))
        flags = ["ExploElev 205.6 ft ignored: 333.4 ft from LIDAR", "no bottom elevation or depth"]
        self.stub(model=flagged_model(flags))
        d.refresh()
        r0, r1 = d.explo_rows
        self.assertFalse(r0.has_check())
        self.assertEqual(r1.check_text(), f"MW-2: {flags[0]} (+1 more)")
        self.assertEqual((r1.badge.text(), r1.badge.isHidden(), r1.problem_label.isHidden()), ("2", False, False))
        self.assertEqual(r1.badge.blocks[0].title, "1 exploration flagged")
        self.assertEqual(r1.badge.blocks[0].items, [("MW-2", flags[0], ""), ("MW-2", flags[1], "")])
        self.assertEqual(r1.badge.actions, [("open_depths", "Open Depths")])
        self.assertEqual((d.grp_explo.problems(), d.grp_explo.header.toolTip().splitlines()[-1]),
                         (1, "1 layer needs a look"))
        for f in flags:
            self.assertNotIn(f, d.message.text())
        self.assertIn("does not state its elevation units", d.message.text())     # no row's: the status line
        # with Verbose off too: the line is not a hint
        self.assertFalse(W.verbose())
        # a failed build: only what the rows know by themselves stays
        self.stub(exc=SectionError("Choose a DEM (ground surface raster)."))
        d.refresh()
        self.assertFalse(r1.has_check())
        self.assertEqual(d.grp_explo.problems(), 0)

    def test_water_levels_that_are_not_numbers(self):
        table = water_table()
        self.prj.addMapLayer(table)
        rows = self.settings().point_layers
        for r in rows:
            r.update(wl_table_id=table.id(), wl_table_name_field="ExploName", wl_table_elev_field="DTW",
                     wl_values="depth")
        d = self.restore(self.settings(point_layers=rows, other_points=[], screens=True))
        d.refresh()
        self.assertIn("Boring Summary: 2 water levels in DTW are not numbers (left out).", d.model.warnings)
        for row in d.explo_rows:
            probs = [p for p in row.problems() if p.line == "2 water levels are not numbers; left out"]
            self.assertEqual(len(probs), 1, row.name_label.text())
            card = probs[0].card
            self.assertEqual((probs[0].count, card.title), (2, "2 water levels left out"))
            self.assertEqual(card.source, f"{row.name_label.text()} · table Boring Summary, field DTW")
            self.assertEqual(list(card.items), [("B-2x", '"dry"', ""), ("O-1", '"n/a"', "")])
            self.assertEqual(card.note, "Only plain numbers are read; 1,234.5 is fine.")
            self.assertEqual(card.actions, [("open_water", "Open Water")])
            self.assertIn(("open_water", "Open Water"), row.badge.actions)
        self.assertNotIn("not numbers", d.message.text())

    def test_the_status_line_rewrites_old_places(self):
        d = self.restore(self.settings(other_points=[]))
        m = fake_model()
        m.warnings = [UNITS_WARNING]
        self.stub(model=m)
        d.refresh()
        self.assertIn("Set them under Surfaces › Units & datum if that is wrong.", d.message.text())
        self.assertNotIn("More: units and datum", d.message.text())
        self.assertEqual(P.shown("Surfaces > More: units and datum"), "Surfaces › Units & datum")

    def test_other_features_rows(self):
        d = self.restore(self.settings(other_points=[seep_row(self.seeps, label_field="Name", elev="field",
                                                              elev_field="Elev_ft", elev_empty="off")]))
        d.refresh()
        n = len(d.model.other_layers[0].no_elevation)
        self.assertGreater(n, 0)
        row = other_row(d)
        self.assertEqual(row.check_text(), f"{n} left out: no Elev_ft")
        self.assertEqual(row.badge.text(), str(n))
        self.assertEqual(row.badge.blocks[0].title, f"{n} left out")
        self.assertEqual(row.badge.blocks[0].source, "Seeps · Elev_ft is empty and Where empty is Off")
        self.assertEqual(row.badge.actions, [("open", "Open")])
        self.assertEqual(d.grp_other.problems(), 1)
        # its layer removed: one line, not the message
        self.prj.removeMapLayer(self.seeps.id())
        APP.processEvents()
        d.refresh()
        self.assertIsNotNone(d.model)
        self.assertEqual(row.check_text(), "Layer not in the project; left out")
        self.assertNotIn("no longer in the project", d.message.text())
        self.assertEqual(d.grp_other.chipText(), "Layer missing")
        self.assertEqual(d.grp_other.problems(), 0)                   # the chip says it already
        row.badge.actionTriggered.emit("open")
        self.assertTrue(row.editor_open())

    def test_dem_gaps(self):
        d = self.restore(self.settings(other_points=[]))
        d.refresh()
        gaps = d.model.ground.gaps
        self.assertTrue(gaps)                                       # the fixture DEM's hole
        pct = 100.0 * (1.0 - d.model.ground.coverage)
        self.assertEqual(d.ground_row.check_text(), f"No DEM data along {pct:.1f}% of the line")
        self.assertEqual(d.ground_row.badge.text(), str(len(gaps)))
        self.assertEqual(d.ground_row.badge.blocks[0].title, "No DEM data in places")
        self.assertEqual(d.grp_ground.problems(), 1)
        self.assertNotIn("No DEM data along", d.message.text())

    def test_a_guess_and_looks_right(self):
        d = self.restore(self.settings(other_points=[]))
        self.assertEqual(d.grp_explo.problems(), 0)
        row = d.add_point_layer(self.supply)
        self.assertTrue(row.guessed())
        self.assertEqual((row.badge.text(), row.badge.isHidden(), row.check_text()), ("check", False, ""))
        self.assertEqual(d.grp_explo.problems(), 1)                 # a guess counts: a layer that needs a look
        d._on_timer()

        def stored_guessed():
            rows = json.loads(settings_store.stored_json(self.prj))["point_layers"]
            return next(r for r in rows if r["layer_id"] == self.supply.id())["guessed"]

        self.assertEqual(stored_guessed(), row.guessed())
        row.badge.actionTriggered.emit("looks_right")
        self.assertEqual((row.guessed(), row.has_check(), d.grp_explo.problems()), ([], False, 0))
        d._on_timer()
        self.assertEqual(stored_guessed(), [])
        self.assertIn('"guessed": []', settings_store.stored_json(self.prj))

    def test_a_saved_field_the_layer_lost_is_a_guess(self):
        """A project whose saved top field was renamed in the layer since: the box is guessed again on load, and the
        row says so (the "check" badge, the count chip, the guess hint with Verbose), as 0.3.5's sentence did."""
        supply = point_row(self.supply, label_field="AESI_MapLabel", type_field="ExploType_resolved",
                           top_field="TopElev_old", depth_field="WellCompleteDepth", atd_field="GW_Elev_ATD")
        d = self.restore(self.settings(other_points=[], point_layers=[supply]))
        row = d.explo_rows[0]
        self.assertEqual((row.value()["top_field"], row.guessed()), ("ExploElev", ["top_field"]))
        self.assertEqual((row.badge.text(), row.badge.isHidden(), row.check_text()), ("check", False, ""))
        self.assertEqual(d.grp_explo.problems(), 1)
        self.verbose()
        self.show()
        d.grp_explo.setCollapsed(False)
        row.set_editor_open(True)
        settle()
        self.assertFalse(row.guess_hint.isHidden())
        self.assertEqual(row.guess_hint.text(), "Guessed from the field names (check them): <b>ExploElev</b>.")

    def test_pure_functions(self):
        rows = [P.RowState(dict(visible=True), "Explorations", True), P.RowState(dict(visible=False), "Off", True)]
        probs, covered = P.explo_problems(None, rows)
        self.assertEqual(([p.line for p in probs[0]], probs[1], covered), (["Layer not in the project"], [], set()))
        self.assertEqual(probs[0][0].card.actions, [("open_layer", "Open Layer")])
        kinds = P.other_problems(None, [P.RowState(dict(visible=True), "Table", True, layer_name="Table")], [""])[0]
        self.assertEqual([p.line for p in kinds[0]], ["Not a point, line or polygon layer; left out"])
        m = SimpleNamespace(warnings=["Surface “Till”: its raster is no longer in the project; left out.",
                                      "Surface “Top” (wt) has no data along the line; left out.",
                                      "Surface “Wt”: wt does not state its elevation units; assumed feet."],
                            surfaces=[SimpleNamespace(name="Head", coverage=0.5, layer_name="model")])
        rows = [P.RowState(dict(visible=True, name="Till"), "Till", False, labels=("Till",)),
                P.RowState(dict(visible=True), "wt", False, "wt", labels=P.surface_labels(dict(band=1), 2, "wt", "wt")),
                P.RowState(dict(visible=True, source="mf6"), "Head", False, labels=("Head",))]
        self.assertEqual(rows[1].labels, ("wt", "wt band 1", "Surface 2"))
        probs, covered = P.surface_problems(m, rows)
        self.assertEqual([[p.line for p in pr] for pr in probs],
                         [["Its raster is no longer in the project; left out"], [], ["Data along 50% of the line"]])
        self.assertEqual(covered, {m.warnings[0]})
        self.assertEqual(P.status_warnings(m, SimpleNamespace(warnings=["Brackets lowered."]), covered),
                         ["Brackets lowered.", m.warnings[1], m.warnings[2]])
        hits = [SimpleNamespace(), SimpleNamespace()]
        pts = [SimpleNamespace(kind="point"), SimpleNamespace(kind="crossing"), SimpleNamespace(kind="crossing")]
        self.assertEqual(P.ready_text(SimpleNamespace(hits=hits, other_points=pts, other_areas=[1])),
                         "Ready · 2 explorations, 1 point, 2 crossings, 1 area")
        self.assertEqual(P.ready_text(SimpleNamespace(hits=hits[:1], other_points=[], other_areas=[1, 2])),
                         "Ready · 1 exploration, 2 areas")
        self.assertEqual(P.ready_text(SimpleNamespace(hits=[], other_points=[], other_areas=[])),
                         "Ready · ground line only")


# ------------------------------------------------------------------ 7.3-7, 7.3-8: the status line, the card
class StatusAndCard(PanelCase):
    def test_the_status_line(self):
        d = self.restore(self.settings(other_points=[]))
        self.assertTrue(d.status_bar.isHidden())                     # no build yet, nothing to say
        m = fake_model()
        m.warnings = []
        m.hits[1].flags = []
        self.stub(model=m)
        d.refresh()
        self.assertEqual((d.status_text.text(), d.status_text.isHidden(), d.message.isHidden()),
                         ("Ready · 2 explorations", False, True))
        self.assertEqual((d.status_dot.state(), d.status_bar.isHidden()), ("ok", False))
        self.stub(exc=SectionError("Choose a DEM (ground surface raster)."))
        d.refresh()
        self.assertEqual((d.message.text(), d.status_dot.state(), d.status_text.isHidden()),
                         ("Choose a DEM (ground surface raster).", "error", True))
        self.assertIn(W.theme_for(d.palette()).error.name(), d.message.styleSheet())
        self.stub(model=fake_model())                                # its DEM-units warning
        d.refresh()
        self.assertEqual((d.message.text(), d.status_dot.state(), d.status_text.isHidden()),
                         ("The DEM does not state its elevation units; assumed feet.", "warn", True))
        self.assertIn(W.theme_for(d.palette()).warn.name(), d.message.styleSheet())

    def test_the_card_from_the_dock(self):
        d = self.restore(self.settings(other_points=[]))
        m = flagged_model(["water level 522.0 ft is above the top of the screen"])
        self.stub(model=m)
        self.show(d, height=420)
        d.grp_explo.setCollapsed(False)
        d.refresh()
        settle()
        row, host = explo_row(d, 1), d.card_host
        QTest.mouseClick(row.badge, Qt.MouseButton.LeftButton)
        self.assertTrue(host.is_open())
        self.assertIs(host.badge(), row.badge)
        self.assertEqual([b.text() for b in host.card.buttons()], ["Open Water"])
        panel = d.widget().rect()
        self.assertTrue(panel.contains(host.card.geometry()))
        host.card.buttons()[0].click()
        settle()
        self.assertFalse(host.is_open())
        self.assertEqual((row.editor_open(), row.current_tab()), (True, "water"))
        # scrolling closes it, and so does a section closing
        QTest.mouseClick(row.badge, Qt.MouseButton.LeftButton)
        self.assertTrue(host.is_open())
        bar = d.scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(0 if bar.value() else bar.maximum())
        self.assertFalse(host.is_open())
        settle()
        QTest.mouseClick(row.badge, Qt.MouseButton.LeftButton)
        self.assertTrue(host.is_open())
        d.grp_line.setCollapsed(False)
        self.assertFalse(host.is_open())


# ------------------------------------------------------------------ 7.3-9, 7.3-10: Flare hosts, Other features
class BandsAndFeatures(PanelCase):
    def test_flare_hosts(self):
        d = self.show(self.restore(self.settings(other_points=[])))
        d.grp_explo.setCollapsed(False)
        r0, r1 = d.explo_rows
        body = d.grp_explo.body
        self.assertTrue(all(any(c is r for c in body.watched()) for r in (r0, r1)))
        r0.set_editor_open(True)
        settle()
        bands = body.bands()
        self.assertEqual(len(bands), 1)
        top, bottom, right, rule = bands[0]
        self.assertIsNotNone(rule)                                  # the tabs' rule across the band
        img = body.grab().toImage()
        dpr = img.devicePixelRatio()
        t = W.theme_for(body.palette())

        def px(x, y):
            return img.pixelColor(int(x * dpr), int(y * dpr)).name()

        y = (top + bottom) // 2
        self.assertEqual(px(W.RAIL_W + 4, y), t.row_open.name())   # the band, left of the card (the body's padding)
        self.assertEqual(px(1, y), t.row_rail.name())               # the rail beside it
        self.assertEqual(px(1, bottom + 20), t.bar.name())          # navy again below the fade
        r1.set_editor_open(True)
        settle()
        self.assertEqual(len(body.bands()), 2)
        # the Surfaces cards: the ground row and the surface rows are watched by the Surfaces body
        d.grp_ground.setCollapsed(False)
        sr = d.add_surface(self.dem)
        self.assertTrue(any(c is sr for c in d.grp_ground.body.watched()))
        self.assertTrue(any(c is d.ground_row for c in d.grp_ground.body.watched()))
        d.remove_surface(sr)
        self.assertFalse(any(c is sr for c in d.grp_ground.body.watched()))

    def test_other_features_from_the_dock(self):
        creeks = make_streams_layer(name="Creeks")
        explo = self.settings().point_layers + [point_row(self.supply, label_field="AESI_MapLabel")]
        self.prj.removeMapLayer(self.seeps.id())
        self.prj.addMapLayer(creeks)
        d = self.restore(self.settings(point_layers=explo, other_points=[]))
        row = d.add_other_points()                                  # no seeps: the creeks (lines)
        self.assertEqual((row.layer(), row.kind(), row.value()["kind"], row.value()["shape"]),
                         (creeks, "line", "line", "stream"))
        d.remove_other_row(row)
        seeps = make_seeps_layer()
        self.prj.addMapLayer(seeps)
        row = d.add_other_points()                                  # seeps first
        self.assertEqual((row.layer(), row.kind()), (seeps, "point"))
        # the chip counts points, crossings and pieces
        site = make_areas_layer(name="Project site", names=["Project site"])
        self.prj.addMapLayer(site)
        d = self.restore(self.settings(point_layers=explo, other_points=[seep_row(seeps, label_field="Name"),
                                                     stream_row(creeks, label_field="Name"),
                                                     area_row(site, label_field="Name")]))
        d.refresh()
        crossings = sum(1 for p in d.model.other_points if p.kind == "crossing")
        self.assertGreater(crossings, 0)
        self.assertGreater(len(d.model.other_areas), 0)
        n = len(d.model.other_points) + len(d.model.other_areas)
        self.assertEqual(d.grp_other.chipText(), f"3 of 3 on · {n} plotted")
        self.assertEqual(other_row(d, 2).sub_label.text(), "areas · Name · bracket in the frame")
        self.assertTrue(P.ready_text(d.model).endswith(", 1 area"), P.ready_text(d.model))


# ------------------------------------------------------------------ 7.3-11, 7.3-12: narrow panels, both themes
class NarrowAndThemes(PanelCase):
    def open_everything(self, d):
        for s in d.sections:
            s.setCollapsed(False)
        for m in d._disclosures:
            m.setExpanded(True)
        d.ground_row.set_editor_open(True)
        for r in d.surface_rows + d.explo_rows + d.other_rows:
            r.set_editor_open(True)

    def test_narrow_panels(self):
        self.verbose()
        d = self.restore(self.settings())
        d.add_surface(self.dem)
        m = flagged_model(["no bottom elevation or depth"])
        self.stub(model=m)
        d.refresh()
        for width in (260, 340):
            self.show(d, width=width, height=700)
            self.open_everything(d)
            for tab in ("layer", "depths", "water"):
                for r in d.explo_rows:
                    r.show_tab(tab)
                settle()
                self.assertLessEqual(d.content.minimumSizeHint().width(), d.scroll.viewport().width(), (width, tab))
                self.assertFalse(d.scroll.horizontalScrollBar().isVisible(), (width, tab))
            d.scroll.verticalScrollBar().setValue(0)
            settle()
            row = explo_row(d, 1)
            d.scroll.ensureWidgetVisible(row.badge, 0, 0)
            settle()
            d.card_host.open(row.badge)
            self.assertTrue(d.widget().rect().contains(d.card_host.card.geometry()), width)
            d.card_host.close()
            # Line › Ends and the add buttons: every word whole, on a second line where one is too narrow
            for fit in (d.ends_row, d.add_surfaces_row):
                self.assertEqual(fit.wrapped(), fit.width() < fit.one_line_width(), (width, fit))
            for b in (d.btn_add_surface, d.btn_add_bands, d.btn_add_mf6, d.btn_save_line):
                self.assertGreaterEqual(b.width(), b.minimumSizeHint().width(), (width, b.text()))
            d.hide()

    def test_nothing_cut_at_the_narrowest_panel(self):
        """(fix 0.3.6) At the 260 px minimum (scroll bar showing; everything open, Manual elevations, the grid spacing
        typed) no segmented button cuts its text, no check box its label, no grid spin box its number: the pairs stack
        one over the other, the Page check boxes go to one column. At 340 px the mockup's layout stays (nothing
        stacked, two columns). The Ground row's name lines up with the surface rows' at both."""
        d = self.restore(self.settings())
        d.add_surface(self.dem)
        body = d.grp_ground.body

        def x(w):
            return w.mapTo(body, w.rect().topLeft()).x()
        for width in (260, 340):
            self.show(d, width=width, height=700)
            self.open_everything(d)
            d.z_mode.setCurrentIndex(d.z_mode.findData("manual"))
            d.grid_auto.setChecked(False)
            for tab in ("layer", "depths", "water"):
                for r in d.explo_rows:
                    r.show_tab(tab)
                settle()
                self.assertTrue(d.scroll.verticalScrollBar().isVisible(), (width, tab))
                for seg in d.content.findChildren(W.SegmentedControl):
                    for b in seg.buttons() if seg.isVisible() else ():
                        if b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly:
                            self.assertGreaterEqual(b.width(), b.fontMetrics().horizontalAdvance(b.text()) + 5,
                                                    (width, tab, b.text()))
                for box in d.content.findChildren(QCheckBox):
                    if box.isVisible() and box.text():
                        self.assertGreaterEqual(box.width(), box.sizeHint().width(), (width, tab, box.text()))
                for spin in (d.h_major, d.h_minor, d.v_major, d.v_minor):
                    self.assertGreaterEqual(spin.width(), W._spin_needed(spin), (width, spin.text()))
                stacked = [p for p in d.content.findChildren(W._Pair) if p.isVisible() and p.stacked()]
                self.assertEqual(bool(stacked), width == 260, (width, tab))
            self.assertEqual(d.grid_spacing_row.stacked(), width == 260)
            self.assertEqual(d.compact_layout.parentWidget().columns(), 1 if width == 260 else 2)
            self.assertEqual(x(d.ground_row.name_label), x(d.surface_rows[0].name_label), width)
            d.hide()

    def test_both_themes_render(self):
        old = QPalette(APP.palette())
        self.addCleanup(APP.setPalette, old)
        dark = QPalette(old)
        for role, c in ((QPalette.ColorRole.Window, "#323232"), (QPalette.ColorRole.WindowText, "#dddddd"),
                        (QPalette.ColorRole.Base, "#202020"), (QPalette.ColorRole.Text, "#dddddd"),
                        (QPalette.ColorRole.Button, "#535353"), (QPalette.ColorRole.Highlight, "#d7801a")):
            dark.setColor(role, QColor(c))
        d = self.restore(self.settings())
        self.show(d, height=700)
        self.open_everything(d)
        for pal in (old, dark):
            APP.setPalette(pal)
            settle()
            img = d.content.grab().toImage()
            self.assertFalse(img.isNull())
            t = W.theme_for(d.palette())
            self.assertEqual(t.dark, pal is dark)
            self.assertEqual(t.bar.name(), "#2f5a6f" if pal is dark else "#193340")   # never the orange highlight


if __name__ == "__main__":
    unittest.main()
