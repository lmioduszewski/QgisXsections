"""The hover over several point layers and other points (0.3.3, stage D, DESIGN.md decision 22): core/hover.py's
targets and cells, the readout's columns, the popup's "Layer" and "Also here" rows, the preview's hit boxes and pick
(a seep, a well that runs below the frame, two layers' explorations at one spot), the map rings and the status line.

The pure checks run on hand-made models. The preview and map checks run the fixture project of tests/fixtures.py
through the real pipeline in a dock with a real PreviewWidget and an offscreen map canvas: the explorations,
explorations by others (B-2x 0.6 ft from B-2), supply wells (out of the elevation range: HW-1 400 ft deep runs
below the frame) and seeps, all in EPSG:2927.
"""
import math
import unittest

from tests.fixtures import (LINE, TOLERANCE, load_project, line_length, make_others_layer, make_seeps_layer,
                            make_supply_layer, point_at, point_row, seep_row, start_app)

APP = start_app()

from qgis.core import QgsGeometry, QgsPointXY  # noqa: E402
from qgis.PyQt.QtCore import QPointF  # noqa: E402
from qgis.PyQt.QtWidgets import QWidget  # noqa: E402

from tests.test_preview_tools import (leave, make_plan, move, restore_user_values, save_user_values,  # noqa: E402
                                      settle, vp_of)
from tests.test_ui import make_iface, show_canvas  # noqa: E402
from xsections.core import hover as H  # noqa: E402
from xsections.core.model import (GroundProfile, Hit, OtherLayerInfo, OtherPoint, PointLayerInfo,  # noqa: E402
                                  SectionModel, Settings, WaterLevel, hidden_key, line_key)
from xsections.render import scales as S  # noqa: E402
from xsections.ui import preview as P  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import XSectionsDock  # noqa: E402
from xsections.ui.popup import HoverPopup  # noqa: E402
from xsections.ui.preview import PreviewWidget, summary_text  # noqa: E402
from xsections.ui.readout import HoverReadout  # noqa: E402

NAN = math.nan
L = line_length()
LINE_WKT = QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in LINE]).asWkt()
WATER_TITLES = {"Measured level", "ATD level", "Water level"}


# ------------------------------------------------------------------ hand-made pieces
def hit(label="B-1", fid=1, layer_index=0, layer_id="L0", layer_name="Explorations", **kw):
    base = dict(fid=fid, label=label, type_value="Boring", x=0.0, y=0.0, station=300.0, offset=40.0, side="L",
                direction="N", ground_at_station=508.0, ground_at_point=508.2, top=508.2, top_source="field",
                bottom=478.2, bottom_source="depth", total_depth=30.0, layer_index=layer_index, layer_id=layer_id,
                layer_name=layer_name)
    base.update(kw)
    return Hit(**base)


def seep(label="S-1", fid=11, how="line", z=510.0, gs=510.0, lidar=510.2, layer_index=0, layer_name="Seeps", **kw):
    base = dict(fid=fid, label=label, type_value="Seep", x=0.0, y=0.0, station=1000.0, offset=20.0, side="L",
                direction="N", ground_at_station=gs, ground_at_point=lidar, z=z, how=how, layer_index=layer_index,
                layer_id=f"S{layer_index}", layer_name=layer_name)
    base.update(kw)
    return OtherPoint(**base)


def layer_info(i, name, on=True, row=None):
    return PointLayerInfo(index=i, layer_id=f"L{i}", name=name, layer_name=name, look="black", color="",
                          in_range=True, on=on, row=row or point_row(layer_id=f"L{i}"))


def other_info(i, name, elev="line", elev_field="", on=True):
    return OtherLayerInfo(index=i, layer_id=f"S{i}", name=name, layer_name=name, shape="asterisk", color="#1f6fb2",
                          size=7.0, elev=elev, elev_field=elev_field, elev_empty="line", on=on,
                          row=seep_row(layer_id=f"S{i}", elev=elev, elev_field=elev_field))


def model(hits=(), others=(), layers=(), other_layers=(), has_explorations=True):
    ground = GroundProfile(stations=[0.0, L], z=[500.0, 540.0], step=3.0)
    return SectionModel(length=L, vertex_stations=[0.0, 2500.0, L], azimuth=82.0, ground=ground, hits=list(hits),
                        line_wkt=LINE_WKT, dem_name="LIDAR", dist_factor=1.0, has_explorations=has_explorations,
                        point_layers=list(layers), other_points=list(others), other_layers=list(other_layers))


# ------------------------------------------------------------------ core/hover.py
class Targets(unittest.TestCase):
    def test_hover_targets_and_target(self):
        h0, h1, p0 = hit("B-1"), hit("B-2", fid=2, station=2200.0), seep("S-1")
        m = model([h0, h1], [p0])
        self.assertEqual(H.hover_targets(m), [h0, h1, p0])               # explorations, then the other points
        self.assertIs(H.hover_target(m, 0), h0)
        self.assertIs(H.hover_target(m, 2), p0)
        self.assertIsNone(H.hover_target(m, -1))                          # nothing pointed at
        self.assertIsNone(H.hover_target(m, 3))                           # past the end
        self.assertIsNone(H.hover_target(None, 0))
        self.assertEqual(H.hover_targets(None), [])
        self.assertTrue(H.is_other_point(p0) and not H.is_other_point(h0))

    def test_several_layers(self):
        self.assertFalse(H.several_layers(None))
        self.assertFalse(H.several_layers(model()))                       # a hand-made model: no rows
        self.assertFalse(H.several_layers(model(layers=[layer_info(0, "A")])))
        self.assertFalse(H.several_layers(model(layers=[layer_info(0, "A"), layer_info(1, "B", on=False)])))
        self.assertTrue(H.several_layers(model(layers=[layer_info(0, "A"), layer_info(1, "B")])))


class HitCells(unittest.TestCase):
    def test_two_args_unchanged_and_the_layer_with_several(self):
        s = Settings(top_field="ExploElev", wl_field="WL")
        h = hit()
        today = H.hit_cells(h, s)
        self.assertEqual(today[0], ("Boring", "B-1", ""))
        one = model([h], layers=[layer_info(0, "Explorations")])
        two = model([h], layers=[layer_info(0, "Explorations"), layer_info(1, "By others")])
        off = model([h], layers=[layer_info(0, "Explorations"), layer_info(1, "By others", on=False)])
        for m in (None, model([h]), one, off):                            # one layer on: no small print
            self.assertEqual(H.hit_cells(h, s, m), today)
        cells = H.hit_cells(h, s, two)                                    # two on: the layer under its name
        self.assertEqual(cells[0], ("Boring", "B-1", "Explorations"))
        self.assertEqual(cells[1:], today[1:])
        self.assertEqual(H.target_cells(h, s, two), cells)

    def test_each_row_its_own_top_field_and_levels(self):
        rows = [point_row(layer_id="L0", top_field="TopA"), point_row(layer_id="L1", top_field="TopB", atd_field="ATD")]
        s = Settings(screens=True, point_layers=rows)
        m = model(layers=[layer_info(0, "Mine", row=rows[0]), layer_info(1, "Supply", row=rows[1])])
        mine = H.hit_cells(hit(layer_index=0, layer_id="L0", layer_name="Mine"), s, m)
        self.assertEqual(mine[0][2], "Mine")
        self.assertIn(("Top", "508.2 ft", "TopA"), mine)
        self.assertFalse(WATER_TITLES & {c[0] for c in mine})            # that row reads no levels
        supply = H.hit_cells(hit(layer_index=1, layer_id="L1", layer_name="Supply"), s, m)
        self.assertEqual(supply[0][2], "Supply")
        self.assertIn(("Top", "508.2 ft", "TopB"), supply)
        self.assertIn(("Water level", "—", "none"), supply)              # it does: "none"
        level = H.hit_cells(hit(layer_index=1, layer_id="L1", layer_name="Supply",
                                water_levels=[WaterLevel(elev=480.0, kind="atd", date="2/2/2021")]), s, m)
        self.assertIn(("ATD level", "480.0 ft", "2/2/2021 · 28.2 below top"), level)
        self.assertNotIn("Water level", [c[0] for c in level])


class OtherCells(unittest.TestCase):
    def setUp(self):
        self.s = Settings()
        self.m = model(other_layers=[other_info(0, "Seeps"), other_info(1, "Springs", elev="lidar"),
                                     other_info(2, "Field seeps", elev="field", elev_field="Elev_ft")])

    def cells(self, p, m=None):
        cells = H.other_cells(p, self.s, self.m if m is None else m)
        self.assertFalse(WATER_TITLES & {c[0] for c in cells})            # never a water level's titles
        self.assertEqual(H.target_cells(p, self.s, self.m if m is None else m), cells)
        return cells

    def test_on_the_ground_line(self):
        self.assertEqual(self.cells(seep()), [("Seep", "S-1", "Seeps"), ("From A", "1,000 ft", "20 ft left"),
                                              ("Elevation", "510.0 ft", "ground line"),
                                              ("LIDAR", "510.2 ft", "at the point")])
        # no LIDAR at the point: no LIDAR cell; no type: the layer's name over its label
        self.assertEqual(self.cells(seep(lidar=NAN, type_value="", side="R")),
                         [("Seeps", "S-1", ""), ("From A", "1,000 ft", "20 ft right"),
                          ("Elevation", "510.0 ft", "ground line")])

    def test_at_the_lidar(self):
        p = seep("L-1", how="lidar", z=497.0, lidar=497.0, layer_index=1, layer_name="Springs", type_value="Spring")
        self.assertEqual(self.cells(p), [("Spring", "L-1", "Springs"), ("From A", "1,000 ft", "20 ft left"),
                                         ("Elevation", "497.0 ft", "LIDAR at the point"),
                                         ("Ground line", "510.0 ft", "13.0 bgs")])
        # no LIDAR there: on the ground line instead
        p = seep("L-2", how="line", lidar=NAN, fell_back=True, layer_index=1, layer_name="Springs")
        self.assertEqual(self.cells(p)[2:], [("Elevation", "510.0 ft", "ground line (no LIDAR)")])

    def test_from_a_field_and_its_fallbacks(self):
        p = seep("F-1", how="field", z=511.4, field_value=511.4, lidar=510.0, layer_index=2, layer_name="Field seeps")
        self.assertEqual(self.cells(p)[2:], [("Elevation", "511.4 ft", "Elev_ft"), ("LIDAR", "510.0 ft", "at the point"),
                                             ("Ground line", "510.0 ft", "1.4 ags")])
        p = seep("F-2", how="line", fell_back=True, layer_index=2, layer_name="Field seeps")      # empty: ground line
        self.assertEqual(self.cells(p)[2:], [("Elevation", "510.0 ft", "ground line (no Elev_ft)"),
                                             ("LIDAR", "510.2 ft", "at the point")])
        p = seep("F-3", how="lidar", z=510.4, lidar=510.4, fell_back=True, layer_index=2, layer_name="Field seeps")
        self.assertEqual(self.cells(p)[2:], [("Elevation", "510.4 ft", "LIDAR (no Elev_ft)"),
                                             ("Ground line", "510.0 ft", "0.4 ags")])
        # without the model: the settings' row names the field; without either, "field"
        s = Settings(other_points=[seep_row(layer_id="S0", elev="field", elev_field="Elev_ft")])
        self.assertEqual(H.other_cells(seep(how="line", fell_back=True), s)[2],
                         ("Elevation", "510.0 ft", "ground line (no Elev_ft)"))
        self.assertEqual(H.other_cells(seep(how="line", fell_back=True), Settings())[2],
                         ("Elevation", "510.0 ft", "ground line (no field)"))


class AlsoCells(unittest.TestCase):
    def test_rows(self):
        s = Settings()
        b2, b2x = hit("B-2", fid=4), hit("B-2x", fid=7, layer_index=1, layer_id="L1", layer_name="By others")
        one = model([b2, b2x], layers=[layer_info(0, "Explorations")])
        two = model([b2, b2x], layers=[layer_info(0, "Explorations"), layer_info(1, "By others")])
        self.assertEqual(H.also_cells([b2x], s, one), [("Also here", "B-2x", "")])          # one layer: no name
        self.assertEqual(H.also_cells([b2x], s, two), [("Also here", "B-2x", "By others")])
        p = seep()
        with_points = model([b2], [p], layers=[layer_info(0, "Explorations")], other_layers=[other_info(0, "Seeps")])
        self.assertEqual(H.also_cells([p, b2], s, with_points),
                         [("Also here", "S-1", "Seeps"), ("Also here", "B-2", "Explorations")])
        many = [hit(f"B-{k}", fid=k) for k in range(5)]
        self.assertEqual(H.also_cells(many, s, two), [("Also here", "B-0", "Explorations"),
                                                      ("Also here", "B-1", "Explorations"),
                                                      ("Also here", "B-2", "Explorations"), ("", "+2 more", "")])
        self.assertEqual(H.also_cells([], s, two), [])
        self.assertEqual(H.also_cells([None, hit("", fid=9)], s, one), [("Also here", "9", "")])   # its fid


class StatusLine(unittest.TestCase):
    def test_summary_text(self):
        s, plan = Settings(h_scale=1000.0, v_scale=200.0), make_plan()
        tail = f" · {L:,.0f} ft · VE 5×"
        two = [hit("B-1"), hit("B-2", fid=2)]
        pts = [seep("S-1"), seep("S-2", fid=12), seep("S-3", fid=13)]
        on = [other_info(0, "Seeps")]
        self.assertEqual(summary_text(model(two), s, plan), "2 explorations" + tail)
        self.assertEqual(summary_text(model(two, pts, other_layers=on), s, plan),
                         "2 explorations · 3 other points" + tail)
        self.assertEqual(summary_text(model(two[:1], pts[:1], other_layers=on), s, plan),
                         "1 exploration · 1 other point" + tail)
        self.assertEqual(summary_text(model([], pts, other_layers=on, has_explorations=False), s, plan),
                         "3 other points" + tail)                         # no exploration layer on
        self.assertEqual(summary_text(model([], [], other_layers=on, has_explorations=False), s, plan),
                         "0 other points" + tail)
        self.assertEqual(summary_text(model([], [], has_explorations=False), s, plan), "ground line only" + tail)


# ------------------------------------------------------------------ the readout and the popup, standalone
class ReadoutAndPopup(unittest.TestCase):
    def setUp(self):
        self.s = Settings(top_field="ExploElev")
        self.h0 = hit("B-2", fid=4, station=2200.0, type_value="Boring")
        self.h1 = hit("B-2x", fid=7, station=2200.0, layer_index=1, layer_id="L1", layer_name="By others")
        self.p = seep("F-1", how="field", z=511.4, field_value=511.4, lidar=510.0, layer_index=0, layer_name="Seeps")
        self.layers = [layer_info(0, "Explorations"), layer_info(1, "By others")]
        self.others = [other_info(0, "Seeps", elev="field", elev_field="Elev_ft")]
        self.parent = QWidget()
        self.parent.resize(900, 400)
        self.addCleanup(self.parent.deleteLater)

    def test_columns_are_the_longest_row_of_either_kind(self):
        ro = HoverReadout()
        self.addCleanup(ro.deleteLater)
        m = model([self.h0], [self.p], self.layers[:1], self.others)
        rows = [len(H.target_cells(t, self.s, m)) for t in H.hover_targets(m)]
        self.assertEqual(rows, [4, 5])                       # B-2: 4 tiles; the point at a field: 5
        ro.set_lines(H.hover_lines(m), self.s, m)
        self.assertEqual(ro.columns, max([1 + len(H.hover_lines(m))] + rows))
        self.assertEqual(ro.columns, 5)                      # the point's row is the longest
        ro.show_cells(H.target_cells(self.p, self.s, m))
        self.assertEqual([c[:3] for c in ro.cells()], H.other_cells(self.p, self.s, m))
        ro.set_lines(H.hover_lines(model([self.h0])), self.s, model([self.h0]))
        self.assertEqual(ro.columns, 4)

    def test_the_layer_row_only_with_several_layers(self):
        pp = HoverPopup(self.parent)
        two = model([self.h0, self.h1], [self.p], self.layers, self.others)
        pp.set_lines(H.hover_lines(two), self.s, two)
        pp.show_hit(0, self.h0)
        self.assertEqual(pp.header(), ("B-2", "Boring"))
        self.assertEqual(pp.items()[0], ("Layer", "Explorations", ""))
        self.assertEqual([k for k, _, _ in pp.items()], ["Layer", "From A", "Top", "Total depth"])
        one = model([self.h0], [self.p], self.layers[:1], self.others)
        pp.set_lines(H.hover_lines(one), self.s, one)
        pp.show_hit(0, self.h0)
        self.assertEqual([k for k, _, _ in pp.items()], ["From A", "Top", "Total depth"])
        # an other point: its type in the header, its layer in the "Layer" row; no water levels, no footer
        pp.show_hit(1, self.p)
        self.assertEqual(pp.header(), ("F-1", "Seep"))
        self.assertEqual(pp.items(), [("Layer", "Seeps", ""), ("From A", "1,000 ft", "20 ft left"),
                                      ("Elevation", "511.4 ft", "Elev_ft"), ("LIDAR", "510.0 ft", "at the point"),
                                      ("Ground line", "510.0 ft", "1.4 ags")])
        self.assertEqual((pp.levels(), pp.footer()), ([], ""))
        p = seep("S-9", type_value="")                                   # without a type: the layer in the header
        bare = model([self.h0], [p], self.layers[:1], [other_info(0, "Seeps")])
        pp.set_lines(H.hover_lines(bare), self.s, bare)
        pp.show_hit(1, p)
        self.assertEqual(pp.header(), ("S-9", "Seeps"))
        self.assertNotIn("Layer", [k for k, _, _ in pp.items()])

    def test_also_here_follows_the_layer_row(self):
        pp = HoverPopup(self.parent)
        two = model([self.h0, self.h1], [], self.layers)
        pp.set_lines(H.hover_lines(two), self.s, two)
        pp.show_hit(0, self.h0, (1,))
        self.assertEqual(pp.items()[:3], [("Layer", "Explorations", ""), ("Also here", "B-2x", "By others"),
                                          ("From A", "2,200 ft", "40 ft left")])
        taller = pp._size.height()
        pp.show_hit(0, self.h0)                                          # cached apart: no "Also here" now
        self.assertNotIn("Also here", [k for k, _, _ in pp.items()])
        self.assertLess(pp._size.height(), taller)
        pp.show_hit(0, self.h0, (1,))
        self.assertEqual(pp._size.height(), taller)
        one = model([self.h0, self.h1], [], self.layers[:1])             # one layer: first, without a name
        pp.set_lines(H.hover_lines(one), self.s, one)
        pp.show_hit(0, self.h0, (1,))
        self.assertEqual(pp.items()[0], ("Also here", "B-2x", ""))


# ------------------------------------------------------------------ the fixture project in a dock
class LayersHover(unittest.TestCase):
    """Three exploration rows (the supply wells out of the elevation range) and a seeps row, built by the dock and
    drawn in a shown preview, with the map canvas."""

    def setUp(self):
        self._user = save_user_values((P.STRIP_KEY, P.POPUP_KEY))
        for k in (P.STRIP_KEY, P.POPUP_KEY):
            settings_store.set_user_value(k, "1")
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.others, self.supply, self.seeps = make_others_layer(), make_supply_layer(), make_seeps_layer()
        self.prj.addMapLayers([self.others, self.supply, self.seeps])
        self.iface = make_iface()
        self.canvas = self.iface.mapCanvas()
        show_canvas(self.canvas, [self.lines])
        self.pv = PreviewWidget()
        self.pv.resize(1000, 460)
        self.pv.show()
        APP.processEvents()
        self.dock = XSectionsDock(self.iface, self.pv)
        self.fb = self.dock.feedback
        self.events = []
        self.pv.hoverChanged.connect(lambda st, i: self.events.append(("changed", st, i)))
        self.pv.hoverLeft.connect(lambda: self.events.append(("left",)))

    def tearDown(self):
        self.dock.cleanup()
        self.dock.deleteLater()
        self.pv.hide()
        self.pv.deleteLater()
        APP.processEvents()
        restore_user_values(self._user)
        self.prj.clear()

    def settings(self, **over) -> Settings:
        s = Settings(line_layer_id=self.lines.id(), line_fid=next(self.lines.getFeatures()).id(),
                     dem_layer_id=self.dem.id(), tolerance_ft=TOLERANCE, h_scale=1000.0, v_scale=50.0,
                     compact_layout=False, fill_grid="off",
                     point_layers=[
                         point_row(self.pts, label_field="ExploName", type_field="ExploType", top_field="ExploElev",
                                   depth_field="ExploDepth"),
                         point_row(self.others, label_field="ExploName", type_field="ExploType_resolved",
                                   top_field="ExploElev", depth_field="ExploDepth"),
                         point_row(self.supply, label_field="AESI_MapLabel", type_field="ExploType_resolved",
                                   top_field="ExploElev", depth_field="WellCompleteDepth", atd_field="GW_Elev_ATD",
                                   atd_date_field="ExploDate", in_range=False)],
                     other_points=[seep_row(self.seeps, label_field="Name", type_field="Type", elev="field",
                                            elev_field="Elev_ft")])
        for k, v in over.items():
            setattr(s, k, v)
        return s

    def build(self, **over):
        self.dock.apply_settings(self.settings(**over))
        self.dock.refresh()
        self.assertEqual(self.dock.last_error, "")
        settle(self.pv)
        self.model, self.s = self.dock.model, self.dock._settings
        return self.model

    # ---- helpers
    def find(self, label):
        """(hover index, target) of the exploration or other point labelled `label`."""
        for i, t in enumerate(H.hover_targets(self.model)):
            if t.label == label:
                return i, t
        self.fail(label)

    def placed(self, label):
        i, p = self.find(label)
        k = i - len(self.model.hits)
        return next(pp for pp in self.pv._placed if pp.index == k)

    def assertNear(self, a, b, tol=1e-6):
        self.assertLess(math.hypot(a.x() - b.x(), a.y() - b.y()), tol, f"{a} != {b}")

    def foot(self, station):
        return QgsGeometry.fromWkt(self.model.line_wkt).interpolate(station / self.model.dist_factor).asPoint()

    # ---- the tests
    def test_pointing_at_a_seep_rings_it_on_the_map(self):
        m = self.build()
        self.assertEqual(len([i for i in m.point_layers if i.on]), 3)
        self.assertEqual([p.label for p in m.other_points], ["S-1", "S-2", "S-5", "S-3"])
        self.assertEqual(sorted(pp.index for pp in self.pv._placed), list(range(len(m.other_points))))
        self.assertEqual(self.pv.status.text().split(" · ")[:2], [f"{len(m.hits)} explorations", "4 other points"])
        i, p = self.find("S-2")
        k = i - len(m.hits)
        pp = self.placed("S-2")
        self.pv.set_zoom(3.0, vp_of(self.pv, pp.station, pp.z))         # (the neighbours' boxes well away)
        settle(self.pv)
        at = vp_of(self.pv, pp.station, pp.z)                            # the symbol's centre
        move(self.pv, at)
        self.assertEqual(self.events[-1], ("changed", p.station, len(m.hits) + k))
        ro, pop = self.pv.readout, self.pv.popup
        self.assertEqual(ro.mode, "cells")
        self.assertEqual([c[:3] for c in ro.cells()], [tuple(c) for c in H.other_cells(p, self.s, m)])
        self.assertEqual(ro.cells()[0][:3], ("Seep", "S-2", "Seeps"))
        self.assertEqual(p.how, "field")                                 # S-2 has a value
        self.assertEqual(ro.cells()[2][:3], ("Elevation", H.elev_text(p.z), "Elev_ft"))
        self.assertEqual(pop.header(), ("S-2", "Seep"))
        self.assertEqual(pop.items()[0], ("Layer", "Seeps", ""))
        # the band: as wide as the symbol and a little more
        r, dpi = self.pv.canvas.device_pixel_ratio, self.pv.figure.dpi
        band = self.pv._marks.band
        self.assertTrue(band.get_visible())
        self.assertAlmostEqual(band.get_width(), 2.0 * max(P.BAND_HALF_PX * r, pp.half_w * dpi + 2.0 * r), places=6)
        # the dock rings it on the map, with its projection to the line
        self.assertEqual(self.dock._cursor_from, "preview")
        self.assertIs(self.fb._cursor_hit, p)
        self.assertEqual(self.fb.ring.numberOfVertices(), 1)
        self.assertNear(self.fb.ring.asGeometry().vertexAt(0), QgsPointXY(p.x, p.y))
        self.assertNear(self.fb.cursor.point, self.foot(p.station))
        line = self.fb.projection.asGeometry().asPolyline()
        self.assertNear(line[0], QgsPointXY(p.x, p.y))
        # the hit box: the symbol's width, from just below it to just above its label
        cx, cy = self.pv._ax.transData.transform((pp.station, pp.z))
        self.assertGreater(pp.label_top, pp.above)                      # (it has a label above the symbol)
        top = cy + (max(pp.above, pp.label_top) + P.POINT_ABOVE_IN) * dpi
        box = next(b for b in self.pv._hit_boxes() if b[0] == len(m.hits) + k)
        want = (len(m.hits) + k, cx, cx - pp.half_w * dpi, cx + pp.half_w * dpi,
                cy - (pp.below + P.HIT_BELOW_IN) * dpi, top)
        for got, exp in zip(box, want):
            self.assertAlmostEqual(got, exp, places=6)
        move(self.pv, QPointF(at.x(), at.y() - (top - cy - 2.0) / r))
        self.assertEqual(self.events[-1][2], len(m.hits) + k)
        move(self.pv, QPointF(at.x(), at.y() - (top - cy + 3.0) / r))
        self.assertEqual(self.events[-1][2], -1)
        self.assertEqual(self.fb.ring.numberOfVertices(), 0)
        leave(self.pv)
        self.assertFalse(self.fb.cursor_shown())

    def test_the_band_of_a_clipped_well_stays_inside_the_axes(self):
        m = self.build()
        ax = self.pv._ax
        z_min = min(ax.get_ylim())
        i, hw1 = self.find("HW-1")
        self.assertEqual(z_min, self.dock.plan.z_min)                    # the frame's bottom
        self.assertTrue(S.runs_below(hw1, z_min, self.s))
        bottom = ax.bbox.y0
        self.assertLess(ax.transData.transform((hw1.station, hw1.bottom))[1], bottom)    # it reaches below
        box = next(b for b in self.pv._hit_boxes() if b[0] == i)
        self.assertEqual(box[4], bottom)                                  # its box stops at the frame
        g = hw1.ground_at_station
        move(self.pv, vp_of(self.pv, hw1.station, z_min + 0.3 * (g - z_min)))
        self.assertEqual(self.events[-1], ("changed", hw1.station, i))
        band = self.pv._marks.band
        self.assertTrue(band.get_visible())
        self.assertGreaterEqual(band.get_y(), bottom - 1e-9)
        self.assertLessEqual(band.get_y() + band.get_height(), ax.bbox.y1 + P.ABOVE_FRAME_PX)
        # just above the frame's bottom it is still HW-1; an in-range well's box keeps its margin below its bottom
        r = self.pv.canvas.device_pixel_ratio
        at = vp_of(self.pv, hw1.station, z_min)
        move(self.pv, QPointF(at.x(), at.y() - 2.0 / r))
        self.assertEqual(self.events[-1][2], i)
        j, b1 = self.find("B-1")
        self.assertFalse(S.runs_below(b1, z_min, self.s))
        lo = next(b for b in self.pv._hit_boxes() if b[0] == j)[4]
        y_bottom = ax.transData.transform((b1.station, b1.bottom))[1]
        self.assertAlmostEqual(lo, y_bottom - P.HIT_BELOW_IN * self.pv.figure.dpi, places=6)
        # (FIX 0.3.3) a manual range that cuts off an in-range well (a plain clip): its band stops at the frame too
        self.build(z_mode="manual", z_min=500.0, z_max=650.0)
        ax = self.pv._ax
        z_min = min(ax.get_ylim())
        self.assertEqual(z_min, 500.0)
        j, b1 = self.find("B-1")
        self.assertFalse(S.runs_below(b1, z_min, self.s))
        bottom = ax.bbox.y0
        self.assertLess(ax.transData.transform((b1.station, b1.bottom))[1], bottom)      # cut off by the range
        self.assertEqual(next(b for b in self.pv._hit_boxes() if b[0] == j)[4], bottom)
        self.assertTrue(all(b[4] >= bottom for b in self.pv._hit_boxes()))
        move(self.pv, vp_of(self.pv, b1.station, 0.5 * (z_min + b1.top)))
        self.assertEqual(self.events[-1][2], j)
        band = self.pv._marks.band
        self.assertTrue(band.get_visible())
        self.assertGreaterEqual(band.get_y(), bottom - 1e-9)

    def test_map_rings_leave_out_left_off_and_take_other_points(self):
        s = self.settings()
        b2_fid = next(f.id() for f in self.pts.getFeatures() if f["ExploName"] == "B-2")
        m = self.build(hidden_points=[hidden_key(line_key(s), self.pts.id(), b2_fid)])
        self.assertEqual([h.label for h in m.left_off], ["B-2"])
        self.assertTrue(m.other_points)
        rings = self.fb.points.asGeometry()
        got = sorted((round(v.x(), 3), round(v.y(), 3)) for v in rings.vertices())
        want = sorted((round(t.x, 3), round(t.y, 3)) for t in m.hits + m.other_points)
        self.assertEqual(got, want)
        self.assertEqual(self.fb.points.numberOfVertices(), len(m.hits) + len(m.other_points))
        b2 = m.left_off[0]
        self.assertNotIn((round(b2.x, 3), round(b2.y, 3)), got)
        self.assertEqual(len(self.fb._bands()), 7)                       # still one band for every point

    def test_seeps_only_and_ground_only(self):
        m = self.build(point_layers=[])
        self.assertFalse(m.has_explorations)
        self.assertTrue(m.has_points)
        self.assertGreater(self.fb.swath.numberOfVertices(), 4)          # the swath: points are projected
        self.assertEqual(self.fb.points.numberOfVertices(), len(m.other_points))
        self.assertEqual(self.pv.status.text().split(" · ")[0], f"{len(m.other_points)} other points")
        # beside a symbol, past HIT_DX_PX from its centre but within that of its side: still the point
        # (zoomed in, so that the neighbours' boxes are well away; the boxes magnify with the drawing)
        k = next(i for i, p in enumerate(m.other_points) if p.label == "S-2")
        pp = self.placed("S-2")
        self.pv.set_zoom(4.0, vp_of(self.pv, pp.station, pp.z))
        settle(self.pv)
        r, dpi = self.pv.canvas.device_pixel_ratio, self.pv.figure.dpi
        at = vp_of(self.pv, pp.station, pp.z)
        dx = pp.half_w * dpi + 0.5 * P.HIT_DX_PX * r
        self.assertGreater(dx, P.HIT_DX_PX * r)
        for sign in (1.0, -1.0):
            move(self.pv, QPointF(at.x() + sign * dx / r, at.y()))
            self.assertEqual(self.events[-1][2], k)
        for sign in (1.0, -1.0):
            move(self.pv, QPointF(at.x() + sign * (pp.half_w * dpi + 1.5 * P.HIT_DX_PX * r) / r, at.y()))
            self.assertEqual(self.events[-1][2], -1)
        self.pv.fit()
        far = QgsPointXY(*point_at(1800.0, 300.0))                       # 300 ft off: within 2.5 tolerances
        self.assertIsNotNone(self.dock._locate_map_point(far))
        self.dock._map_line = None
        m = self.build(point_layers=[], other_points=[])
        self.assertFalse(m.has_points)
        self.assertEqual(self.fb.swath.numberOfVertices(), 0)
        self.assertEqual(self.pv.status.text().split(" · ")[0], "ground line only")
        self.dock._map_line = None
        self.assertIsNone(self.dock._locate_map_point(far))               # only the screen rule: too far
        self.assertIsNotNone(self.dock._locate_map_point(QgsPointXY(*point_at(1800.0, 5.0))))

    def test_two_layers_at_one_spot(self):
        m = self.build()
        i, b2 = self.find("B-2")
        j, b2x = self.find("B-2x")
        self.assertEqual((b2.layer_name, b2x.layer_name), ("Explorations", "Explorations by others"))
        self.assertLess(abs(b2.station - b2x.station), 1.0)
        move(self.pv, vp_of(self.pv, b2x.station, (b2x.top + b2x.bottom) / 2.0))
        best = self.events[-1][2]
        self.assertIn(best, (i, j))
        named, other = (b2, b2x) if best == i else (b2x, b2)
        ro, pop = self.pv.readout, self.pv.popup
        self.assertEqual(ro.cells()[0][:3], (named.type_value, named.label, f"{named.layer_name} · +1 here"))
        self.assertEqual([c[:3] for c in ro.cells()[1:]], H.hit_cells(named, self.s, m)[1:])
        self.assertEqual(pop.header()[0], named.label)
        self.assertEqual(pop.items()[:2], [("Layer", named.layer_name, ""),
                                           ("Also here", other.label, other.layer_name)])
        self.assertIs(self.fb._cursor_hit, named)                         # the map rings the one named
        # a lone exploration: no "+N here", no "Also here"
        k, b1 = self.find("B-1")
        move(self.pv, vp_of(self.pv, b1.station, (b1.top + b1.bottom) / 2.0))
        self.assertEqual(self.events[-1][2], k)
        self.assertEqual(ro.cells()[0][:3], ("Boring", "B-1", "Explorations"))
        self.assertNotIn("Also here", [key for key, _, _ in pop.items()])
        self.assertEqual(pop.items()[0], ("Layer", "Explorations", ""))
        # a seep at a supply well's station: one of them named, the other listed with its layer
        a, hw3 = self.find("HW-3")
        b, s1 = self.find("S-1")
        self.assertAlmostEqual(hw3.station, s1.station, places=6)
        pp = self.placed("S-1")
        move(self.pv, vp_of(self.pv, pp.station, pp.z))
        best = self.events[-1][2]
        self.assertEqual(best, a)                                         # a tie: the lower index (explorations)
        self.assertEqual(ro.cells()[0][2], "Supply wells · +1 here")
        self.assertIn(("Also here", "S-1", "Seeps"), pop.items())

    def test_readout_columns_on_the_section(self):
        m = self.build()
        lines = H.hover_lines(m)
        rows = [len(H.target_cells(t, self.s, m)) for t in H.hover_targets(m)]
        self.assertEqual(self.pv.readout.columns, max([1 + len(lines)] + rows))
        # each row's lead tile names its layer (three exploration rows on)
        _, o1 = self.find("O-1")
        self.assertEqual(H.target_cells(o1, self.s, m)[0], ("Boring", "O-1", "Explorations by others"))
        self.assertEqual(H.target_cells(o1, self.s, m)[2], ("Top", H.elev_text(o1.top), "ExploElev"))


if __name__ == "__main__":
    unittest.main()
