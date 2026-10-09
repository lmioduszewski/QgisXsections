"""The preview's hover readout values (core/hover.py) and the surfaces CSV (core/surfaces_csv.py).

Hand-made models first: a bent line (2 ft per CRS unit, bend at 610 ft) with a DEM gap, an MF6-like smooth surface
that starts after A, ends before A′ and breaks at one nan vertex, a cells-mode surface with a no-data cell, and a
second surface named like the first. The real-data case (the CDF A-A′ section with MODFLOW 6 surfaces) runs only
when XSECTIONS_REALDATA is set; it checks every value against what matplotlib draws.
"""
import csv
import math
import os
import shutil
import tempfile
import unittest

from tests.fixtures import REALDATA, start_app

start_app()

import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from xsections.core import hover as H  # noqa: E402
from xsections.core import surfaces_csv as C  # noqa: E402
from xsections.core.model import (GroundProfile, Hit, OtherPoint, SectionModel, Settings, SurfaceProfile,  # noqa: E402
                                  WaterLevel)
from xsections.core.section import _steps  # noqa: E402
from xsections.render import figure as F  # noqa: E402

NAN = math.nan
FACTOR = 2.0                                           # ft per section CRS unit
LINE_WKT = "LineString (1000 2000, 1305 2000, 1305 2195)"   # 610 ft east, then 390 ft north
BEND, LENGTH = 610.0, 1000.0
GAP = (400.0, 450.0)                                   # ground vertices without DEM data


def ground_profile():
    st = sorted(set(np.arange(0.0, LENGTH, 50.0).tolist()) | {BEND, LENGTH})
    z = [NAN if s in GAP else 100.0 + 0.01 * s for s in st]
    return GroundProfile(stations=st, z=z, step=50.0, gaps=[(350.0, 500.0)], coverage=0.9)


def cells_surface():
    """Flat across four 250 ft cells, the third without data: each edge twice, the no-data cell as two nan
    vertices."""
    st, z = _steps(np.array([0.0, 250.0, 500.0, 750.0]), np.array([250.0, 500.0, 750.0, 1000.0]),
                   np.array([95.0, 97.0, NAN, 99.0]))
    return SurfaceProfile(name="Water table", color="#1f6fb2", style="dash", width=1.25, mode="cells", stations=st,
                          z=z, source="mf6")


def make_model(**over):
    surfaces = [
        # an MF6 smooth line: joins cell centres, starts after A and ends before A' (off the grid), one nan vertex
        SurfaceProfile(name="Model top", color="#555555", style="dot", width=1.0, mode="smooth",
                       stations=[20.0, 220.0, 420.0, 520.0, 620.0, 820.0, 980.0],
                       z=[104.0, 106.0, 108.0, NAN, 109.0, 110.0, 111.0], source="mf6"),
        cells_surface(),
        SurfaceProfile(name="Model top", color="#2e8b57", style="solid", width=2.0, mode="smooth",
                       stations=[0.0, LENGTH], z=[90.0, 92.0], layer_name="top_raster"),
    ]
    kw = dict(length=LENGTH, vertex_stations=[0.0, BEND, LENGTH], azimuth=90.0, ground=ground_profile(), hits=[],
              line_wkt=LINE_WKT, dem_name="lidar", dist_factor=FACTOR, surfaces=surfaces)
    kw.update(over)
    return SectionModel(**kw)


def map_xy(station):
    """Map x, y of a station on LINE_WKT."""
    u = station / FACTOR
    return (1000.0 + u, 2000.0) if u <= 305.0 else (1305.0, 2000.0 + (u - 305.0))


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def cell_text(v):
    """A value as csv.writer writes it."""
    return "" if v == "" else str(v)


# ----------------------------------------------------------------------------- the lines
class HoverLinesTest(unittest.TestCase):
    def test_order_names_and_styles(self):
        m = make_model()
        lines = H.hover_lines(m)
        self.assertEqual([ln.name for ln in lines], ["Ground (lidar)", "Model top", "Water table", "Model top"])
        self.assertEqual([ln.color for ln in lines], ["#000000", "#555555", "#1f6fb2", "#2e8b57"])
        self.assertEqual([ln.style for ln in lines], ["solid", "dot", "dash", "solid"])
        self.assertEqual([ln.width for ln in lines], [F.GROUND_LW, 1.0, 1.25, 2.0])
        self.assertEqual([ln.ground for ln in lines], [True, False, False, False])
        np.testing.assert_array_equal(lines[0].stations, m.ground.stations)
        np.testing.assert_array_equal(lines[0].z, m.ground.z)
        for ln, sp in zip(lines[1:], m.surfaces):
            np.testing.assert_array_equal(ln.stations, sp.stations)
            np.testing.assert_array_equal(ln.z, sp.z)
            self.assertEqual(ln.stations.dtype, float)

    def test_ground_alone_and_unnamed(self):
        lines = H.hover_lines(make_model(dem_name="", surfaces=[]))
        self.assertEqual([(ln.name, ln.ground) for ln in lines], [("Ground", True)])

    def test_ground_drawn_as_the_sheet_draws_it(self):
        self.assertEqual(H.GROUND_COLOR, F.INK)
        self.assertEqual(H.GROUND_WIDTH, F.GROUND_LW)

    def test_the_sheet_places_marks_by_the_same_rule_but_before_a_gap(self):
        # water-table marks keep the 0.3.0 rule (sheets never change): it differs from the readout's only at a
        # vertex followed by nan, where the drawn line ends (nan for a mark, the vertex's value for the readout)
        rng = np.random.default_rng(5)
        before_gap = 0
        for line in H.hover_lines(make_model()):
            st, z = line.stations, line.z
            for s in np.concatenate([st, rng.uniform(st[0], st[-1], 400)]):
                mark, value = F._mark_z(st, z, s), H.z_on(st, z, s)
                k = int(np.searchsorted(st, s, side="right")) - 1
                if (s == st[k] and k + 1 < st.size and st[k + 1] > st[k] and math.isfinite(z[k])
                        and math.isnan(z[k + 1])):
                    before_gap += 1
                    self.assertTrue(math.isnan(mark), (line.name, s))
                    self.assertEqual(value, z[k], (line.name, s))
                elif math.isnan(value):
                    self.assertTrue(math.isnan(mark), (line.name, s))
                else:
                    self.assertEqual(mark, value, (line.name, s))
        self.assertEqual(before_gap, 2)                            # (the ground at 350 ft, the model top at 420 ft)

    def test_water_table_marks_on_a_sheet_are_as_in_0_3_0(self):
        # a smooth raster water table sampled every 3 ft: marks land on vertices. A gap starting just after a mark
        # and a lone sample (no line drawn) at another: no mark at either, as in 0.3.0
        from xsections.render.scales import plan
        length = 2000.0
        settings = Settings(h_scale=50.0, v_scale=5.0, sheet="tabloid")
        ground = GroundProfile(stations=[0.0, length], z=[110.0, 112.0], step=length, coverage=1.0)

        def tips(st, z):
            wt = SurfaceProfile(name="Water table", color="#1f6fb2", style="dash", width=1.25, mode="smooth",
                                stations=list(st), z=list(z), marks=True)
            m = SectionModel(length=length, vertex_stations=[0.0, length], azimuth=90.0, ground=ground, hits=[],
                             has_explorations=False, surfaces=[wt])
            p = plan(m, settings)
            fig = Figure()
            F.draw_page(fig, m, settings, p, p.pages[0])
            return [float(a.get_xy()[0][0]) for a in fig.axes[0].get_children() if a.get_gid() == F.MARK_GID]

        full = tips([0.0, length], [100.0, 101.0])
        self.assertGreaterEqual(len(full), 5)
        a, b = full[1], full[3]
        st = np.union1d(np.union1d(np.arange(0.0, length, 3.0), full), [length])
        z = 100.0 + st / length
        z[(st > a) & (st < a + 40.0)] = NAN                       # the line ends at mark a
        z[(st > b - 30.0) & (st < b + 30.0) & (st != b)] = NAN    # a lone sample at mark b
        self.assertTrue(math.isfinite(H.z_on(st, z, a)) and math.isfinite(H.z_on(st, z, b)))   # the readout's
        drawn = tips(st, z)
        want = [t for t in full if not (a <= t < a + 40.0) and not (b - 30.0 < t < b + 30.0)]
        self.assertEqual(len(want), len(full) - 2)
        np.testing.assert_allclose(drawn, want)


class ZOnTest(unittest.TestCase):
    def setUp(self):
        self.lines = H.hover_lines(make_model())
        self.ground, self.top, self.wt, self.top2 = self.lines

    def z(self, line, s):
        return H.z_on(line.stations, line.z, s)

    def test_at_vertices(self):
        for line in self.lines:
            for k, (s, z) in enumerate(zip(line.stations, line.z)):
                if k + 1 < line.stations.size and line.stations[k + 1] == s:
                    continue                           # a step: tested below
                if math.isnan(z):
                    self.assertTrue(math.isnan(self.z(line, s)), (line.name, s))
                else:
                    self.assertEqual(self.z(line, s), z, (line.name, s))
        # the last vertex before a gap keeps its value: the drawn line ends there
        self.assertEqual(self.z(self.ground, 350.0), 103.5)
        self.assertEqual(self.z(self.top, 420.0), 108.0)

    def test_between_vertices(self):
        self.assertAlmostEqual(self.z(self.ground, 25.0), 100.25, places=12)
        self.assertAlmostEqual(self.z(self.ground, 630.0), 106.3, places=12)       # past the bend
        self.assertAlmostEqual(self.z(self.top, 120.0), 105.0, places=12)
        self.assertAlmostEqual(self.z(self.top, 900.0), 110.5, places=12)
        self.assertAlmostEqual(self.z(self.top2, 500.0), 91.0, places=12)
        self.assertEqual(self.z(self.wt, 100.0), 95.0)                              # flat across a cell

    def test_cells_steps_take_the_value_right_of_the_step(self):
        self.assertEqual(self.z(self.wt, 0.0), 95.0)
        self.assertEqual(self.z(self.wt, 249.999), 95.0)
        self.assertEqual(self.z(self.wt, 250.0), 97.0)
        self.assertEqual(self.z(self.wt, 250.001), 97.0)
        self.assertTrue(math.isnan(self.z(self.wt, 500.0)))   # right of this step is the cell without data
        self.assertEqual(self.z(self.wt, 750.0), 99.0)
        self.assertEqual(self.z(self.wt, LENGTH), 99.0)
        self.assertEqual(self.z(self.wt, 499.999), 97.0)

    def test_nan_gaps(self):
        for s in (350.001, 375.0, 400.0, 425.0, 450.0, 475.0, 499.999):
            self.assertTrue(math.isnan(self.z(self.ground, s)), s)
        self.assertEqual(self.z(self.ground, 500.0), 105.0)
        for s in (420.001, 470.0, 520.0, 570.0, 619.999):                         # a single nan vertex
            self.assertTrue(math.isnan(self.z(self.top, s)), s)
        self.assertEqual(self.z(self.top, 620.0), 109.0)
        for s in (500.001, 600.0, 749.999):
            self.assertTrue(math.isnan(self.z(self.wt, s)), s)

    def test_past_the_ends(self):
        for line, s in ((self.top, 19.999), (self.top, 980.001), (self.top, 0.0), (self.top, LENGTH),
                        (self.ground, -0.001), (self.ground, LENGTH + 0.001), (self.wt, -5.0)):
            self.assertTrue(math.isnan(self.z(line, s)), (line.name, s))
        self.assertEqual(self.z(self.top, 20.0), 104.0)
        self.assertEqual(self.z(self.top, 980.0), 111.0)
        self.assertTrue(math.isnan(H.z_on(np.array([]), np.array([]), 5.0)))
        self.assertTrue(math.isnan(self.z(self.ground, NAN)))
        self.assertEqual(H.z_on([5.0], [7.0], 5.0), 7.0)                           # lists work too

    def test_a_rounding_error_past_an_end_still_reads_the_end(self):
        # a line whose last vertex came out a rounding error short of the model length (stations summed another
        # way) still has its value at the length; a real step past the end has none
        end = np.nextafter(LENGTH, 0.0)
        st, z = np.array([0.0, 500.0, end]), np.array([10.0, 20.0, 30.0])
        for s in (LENGTH, np.nextafter(LENGTH, 2 * LENGTH), -1e-10):
            want = 30.0 if s > 0 else 10.0
            self.assertEqual(H.z_on(st, z, s), want, s)
            self.assertEqual(H.z_on_array(st, z, [s])[0], want, s)
        for s in (LENGTH + 1e-4, -1e-4):
            self.assertTrue(math.isnan(H.z_on(st, z, s)), s)
            self.assertTrue(np.isnan(H.z_on_array(st, z, [s])[0]), s)

    def test_array_form_gives_the_same_values(self):
        rng = np.random.default_rng(3)
        for line in self.lines:
            at = np.concatenate([line.stations, rng.uniform(-20.0, LENGTH + 20.0, 400), [NAN, -1.0, 0.0, LENGTH]])
            want = np.array([self.z(line, s) for s in at])
            np.testing.assert_array_equal(H.z_on_array(line.stations, line.z, at), want)
        self.assertTrue(np.isnan(H.z_on_array([], [], [1.0, 2.0])).all())
        self.assertEqual(H.z_on_array([0.0, 1.0], [0.0, 1.0], []).size, 0)

    def test_line_value_is_nan_off_the_section(self):
        # a line running on past the end (the ground array would clamp there: GroundProfile.z_at and np.interp
        # give the last value) has no value past the model length, nor before 0
        st, z = np.array([0.0, 500.0, 1100.0]), np.array([10.0, 20.0, 30.0])
        line = H.HoverLine("x", "#000000", "solid", 1.0, False, st, z)
        self.assertFalse(math.isnan(H.z_on(st, z, 1050.0)))
        self.assertTrue(math.isnan(H.line_value(line, 1050.0, LENGTH)))
        self.assertTrue(math.isnan(H.line_value(line, -0.5, LENGTH)))
        self.assertAlmostEqual(H.line_value(line, LENGTH, LENGTH), 20.0 + 10.0 * 500.0 / 600.0, places=12)
        g = make_model().ground
        self.assertEqual(g.z_at(LENGTH + 39.0), g.z[-1])                            # the pitfall ...
        self.assertTrue(math.isnan(H.line_value(self.ground, LENGTH + 39.0, LENGTH)))   # ... avoided
        self.assertEqual(g.z_at(-12.0), g.z[0])
        self.assertTrue(math.isnan(H.line_value(self.ground, -12.0, LENGTH)))
        self.assertEqual(H.line_value(self.ground, 0.0, LENGTH), 100.0)
        self.assertEqual(H.line_value(self.ground, LENGTH, LENGTH), 110.0)
        self.assertTrue(math.isnan(H.line_value(self.ground, NAN, LENGTH)))


# ----------------------------------------------------------------------------- readout texts and values
class TextsTest(unittest.TestCase):
    def test_depth_text(self):
        self.assertEqual(H.depth_text(100.0, 86.4), "13.6 bgs")
        self.assertEqual(H.depth_text(100.0, 100.6), "0.6 ags")
        self.assertEqual(H.depth_text(100.0, 86.44), "13.6 bgs")
        self.assertEqual(H.depth_text(100.0, 86.36), "13.6 bgs")
        self.assertEqual(H.depth_text(100.0, 86.34), "13.7 bgs")
        self.assertEqual(H.depth_text(1300.0, 65.5), "1,234.5 bgs")
        self.assertEqual(H.depth_text(100.0, 100.0), "0.0 bgs")
        for z in (100.04, 99.96, 100.0000001):                                     # never "-0.0"
            self.assertEqual(H.depth_text(100.0, z), "0.0 bgs")
        self.assertEqual(H.depth_text(100.0, 100.06), "0.1 ags")
        for g, z in ((NAN, 90.0), (100.0, NAN), (None, 90.0), (100.0, None), (NAN, NAN)):
            self.assertEqual(H.depth_text(g, z), "")

    def test_elev_text(self):
        self.assertEqual(H.elev_text(655.27), "655.3 ft")
        self.assertEqual(H.elev_text(1655.0), "1,655.0 ft")
        self.assertEqual(H.elev_text(-0.04), "0.0 ft")
        self.assertEqual(H.elev_text(NAN), "")
        self.assertEqual(H.elev_text(None), "")

    def test_distance_text(self):
        feet, station = Settings(), Settings(distance_labels="station")
        self.assertEqual(H.distance_text(1240.0, feet), "1,240 ft")
        self.assertEqual(H.distance_text(759.6, feet), "760 ft")
        self.assertEqual(H.distance_text(0.2, feet), "0 ft")
        self.assertEqual(H.distance_text(-0.3, feet), "0 ft")
        self.assertEqual(H.distance_text(1240.0, station), "12+40")
        self.assertEqual(H.distance_text(760.4, station), "7+60")
        self.assertEqual(H.distance_text(45.0, station), "0+45")
        self.assertEqual(H.distance_text(99.6, station), "1+00")
        self.assertEqual(H.distance_text(5.0, None), "5 ft")


class HoverValuesTest(unittest.TestCase):
    def setUp(self):
        self.lines = H.hover_lines(make_model())

    def test_values_and_nearest(self):
        hv = H.hover_values(self.lines, 120.0, LENGTH, cursor_z=96.0)
        self.assertEqual(hv.station, 120.0)
        self.assertEqual(hv.cursor_z, 96.0)
        np.testing.assert_allclose(hv.values, [101.2, 105.0, 95.0, 90.24], rtol=0, atol=1e-12)
        self.assertAlmostEqual(hv.ground_z, 101.2, places=12)
        self.assertEqual(hv.nearest, 2)                                            # the water table
        self.assertEqual(H.hover_values(self.lines, 120.0, LENGTH, cursor_z=104.0).nearest, 1)
        self.assertEqual(H.hover_values(self.lines, 120.0, LENGTH, cursor_z=200.0).nearest, 1)
        self.assertEqual(H.hover_values(self.lines, 120.0, LENGTH, cursor_z=0.0).nearest, 3)

    def test_without_a_cursor(self):
        hv = H.hover_values(self.lines, 120.0, LENGTH)
        self.assertIsNone(hv.cursor_z)
        self.assertEqual(hv.nearest, -1)
        self.assertEqual(H.hover_values(self.lines, 120.0, LENGTH, cursor_z=NAN).nearest, -1)

    def test_nan_values_are_never_nearest(self):
        hv = H.hover_values(self.lines, 425.0, LENGTH, cursor_z=101.0)            # in the DEM gap
        self.assertTrue(math.isnan(hv.ground_z))
        self.assertTrue(math.isnan(hv.values[0]))
        self.assertEqual(hv.nearest, 2)                                            # water table 97, not the gap
        hv = H.hover_values(self.lines, 550.0, LENGTH, cursor_z=100.0)            # ground, then only Model top (2)
        self.assertTrue(math.isnan(hv.values[1]) and math.isnan(hv.values[2]))
        self.assertEqual(hv.nearest, 0)

    def test_off_the_section(self):
        for s in (-1.0, LENGTH + 1.0):
            hv = H.hover_values(self.lines, s, LENGTH, cursor_z=100.0)
            self.assertTrue(all(math.isnan(v) for v in hv.values))
            self.assertTrue(math.isnan(hv.ground_z))
            self.assertEqual(hv.nearest, -1)

    def test_a_tie_goes_to_the_first_line(self):
        lines = [H.HoverLine("g", "#000", "solid", 1.0, True, np.array([0.0, 10.0]), np.array([10.0, 10.0])),
                 H.HoverLine("a", "#111", "solid", 1.0, False, np.array([0.0, 10.0]), np.array([6.0, 6.0]))]
        self.assertEqual(H.hover_values(lines, 5.0, 10.0, cursor_z=8.0).nearest, 0)
        self.assertTrue(math.isnan(H.hover_values(lines[1:], 5.0, 10.0).ground_z))     # no ground line


# ----------------------------------------------------------------------------- the exploration row
def make_hit(**over):
    kw = dict(fid=4, label="MW-4", type_value="Monitoring well", x=0.0, y=0.0, station=702.3, offset=9.0, side="R",
              direction="E", ground_at_station=660.0, ground_at_point=660.0, top=660.4, top_source="field",
              bottom=638.9, bottom_source="depth", total_depth=21.5, screen_top=650.9, screen_bottom=640.9,
              water_levels=[WaterLevel(651.2, "measured", "6/12/2024", "WL_Elev"),
                            WaterLevel(648.2, "atd", "", "ATD_Elev")])
    kw.update(over)
    return Hit(**kw)


def levels_settings(**over):
    s = Settings(top_field="ExploElev", wl_field="WL_Elev", atd_field="ATD_Elev")
    for k, v in over.items():
        setattr(s, k, v)
    return s


class HitCellsTest(unittest.TestCase):
    def test_well_with_screen_and_levels(self):
        self.assertEqual(H.hit_cells(make_hit(), levels_settings()), [
            ("Monitoring well", "MW-4", ""),
            ("From A", "702 ft", "9 ft right"),
            ("Top", "660.4 ft", "ExploElev"),
            ("Total depth", "21.5 ft", "bottom 638.9"),
            ("Screen", "650.9–640.9 ft", "9.5–19.5 below top"),
            ("Measured level", "651.2 ft", "6/12/2024 · 9.2 below top"),
            ("ATD level", "648.2 ft", "12.2 below top"),       # no date: no date part
        ])

    def test_boring_without_screen_or_levels(self):
        hit = make_hit(fid=7, label="", type_value="", station=1520.6, offset=26.04, side="L", top=655.0,
                       top_source="dem", bottom=633.5, total_depth=None, screen_top=None, screen_bottom=None,
                       water_levels=[])
        s = levels_settings(start_label="B", distance_labels="station")
        self.assertEqual(H.hit_cells(hit, s), [
            ("Exploration", "7", ""),                          # no type, no name: the feature id
            ("From B", "15+21", "26 ft left"),
            ("Top", "655.0 ft", "LIDAR"),
            ("Total depth", "21.5 ft", "bottom 633.5"),        # no total depth: top - bottom
            ("Water level", "—", "none"),                # (no value: a dash)
        ])

    def test_no_water_level_cell_when_none_are_read(self):
        hit = make_hit(water_levels=[])
        for s in (levels_settings(wl_field="", atd_field=""), levels_settings(screens=False)):
            self.assertNotIn("Water level", [c[0] for c in H.hit_cells(hit, s)])
        self.assertIn(("Water level", "—", "none"), H.hit_cells(hit, levels_settings(wl_field="", atd_field="",
                                                                                     wl_table_id="tbl")))

    def test_top_sources(self):
        names = [H.hit_cells(make_hit(top_source=src), levels_settings(top_field=tf))[2][2]
                 for src, tf in (("field", "ExploElev"), ("field", ""), ("dem", "ExploElev"))]
        self.assertEqual(names, ["ExploElev", "table", "LIDAR"])
        self.assertEqual(H.top_source_name(make_hit(top_source="none"), levels_settings()), "none")

    def test_without_a_top(self):
        hit = make_hit(type_value="Boring", label="B-9", top=None, top_source="none", bottom=None, total_depth=30.0,
                       water_levels=[WaterLevel(640.0, "measured", "5/1/2020", "WL_Elev")])
        cells = H.hit_cells(hit, levels_settings())
        self.assertEqual(cells[2:], [
            ("Top", "—", "none"),
            ("Total depth", "30 ft", ""),                       # the depth field, but no bottom
            ("Screen", "650.9–640.9 ft", ""),                   # (elevations) no depths without a top
            ("Measured level", "640.0 ft", "5/1/2020"),
        ])

    def test_total_depth_left_out_without_one(self):
        cells = H.hit_cells(make_hit(total_depth=None, bottom=None), levels_settings())
        self.assertNotIn("Total depth", [c[0] for c in cells])
        cells = H.hit_cells(make_hit(total_depth=None, bottom=NAN), levels_settings())
        self.assertNotIn("Total depth", [c[0] for c in cells])

    def test_a_screen_reaching_above_the_top(self):
        # screens given as elevations can reach above the exploration's top (a LIDAR top a little below the
        # surveyed screen): kept within the 1 ft slack, drawn with a flag beyond it (screen_and_levels). Their
        # depths say "above", never a minus sign
        from xsections.core.explorations import screen_and_levels
        s = levels_settings(screen_values="elevation")
        cases = [((539.4, 529.4), "0.4 above – 9.6 below top", False),
                 ((545.0, 530.0), "6 above – 9 below top", True),
                 ((539.8, 539.2), "0.8–0.2 above top", False),         # all of it above the top (in the slack)
                 ((539.04, 529.4), "0–9.6 below top", False),           # a hair above: 0 (never "-0")
                 ((535.0, 525.0), "4–14 below top", False)]
        for (a, b), want, flagged in cases:
            sl = screen_and_levels(539.0, 504.0, a, b, [], s)
            self.assertEqual((sl.screen_top, sl.screen_bottom), (max(a, b), min(a, b)), want)
            self.assertEqual(bool(sl.flags), flagged, (want, sl.flags))
            hit = make_hit(top=539.0, bottom=504.0, total_depth=35.0, screen_top=sl.screen_top,
                           screen_bottom=sl.screen_bottom, water_levels=[])
            cells = {c[0]: c[1:] for c in H.hit_cells(hit, s)}
            self.assertEqual(cells["Screen"][1], want)
            self.assertNotIn("-", cells["Screen"][1])

    def test_numbers(self):
        hit = make_hit(top=660.0, total_depth=29.98, offset=0.04, screen_top=660.03, screen_bottom=650.0,
                       water_levels=[WaterLevel(661.5, "measured", "6/1/2020", ""),
                                     WaterLevel(659.98, "measured", "", ""), WaterLevel(NAN, "atd", "", "")])
        cells = dict((c[0] + str(i), c[1:]) for i, c in enumerate(H.hit_cells(hit, levels_settings())))
        self.assertEqual(cells["From A1"], ("702 ft", "0 ft right"))
        self.assertEqual(cells["Total depth3"], ("30 ft", "bottom 638.9"))
        self.assertEqual(cells["Screen4"], ("660.0–650.0 ft", "0–10 below top"))   # never "-0"
        self.assertEqual(cells["Measured level5"], ("661.5 ft", "6/1/2020 · 1.5 above top"))
        self.assertEqual(cells["Measured level6"], ("660.0 ft", "0 below top"))
        self.assertEqual(len(cells), 7)                                           # a nan level is left out


class StripCellsTest(unittest.TestCase):
    """0.3.4: the strip's cells (core.hover.strip_cells): a water level titled by its date ("Measured" / "ATD"
    without one) over "9.2 below top", with its kind for the symbol; everything else as target_cells, which the
    popup keeps."""

    def test_water_levels_read_their_date(self):
        hit = make_hit(water_levels=[WaterLevel(651.2, "measured", "6/12/2024", "WL_Elev"),
                                     WaterLevel(648.2, "atd", "", "ATD_Elev"),
                                     WaterLevel(NAN, "measured", "1/1/2020", "WL_Elev"),      # (left out)
                                     WaterLevel(649.1, "measured", "", "WL_Elev"),
                                     WaterLevel(649.4, "atd", "5/3/2019", "ATD_Elev")])
        s = levels_settings()
        cells = H.strip_cells(hit, s)
        self.assertEqual(cells[5:], [("6/12/2024", "651.2 ft", "9.2 below top", "measured"),
                                     ("ATD", "648.2 ft", "12.2 below top", "atd"),
                                     ("Measured", "649.1 ft", "11.3 below top", "measured"),
                                     ("5/3/2019", "649.4 ft", "11 below top", "atd")])
        self.assertEqual([c[:3] for c in cells[:5]], H.hit_cells(hit, s)[:5])            # the rest as before
        self.assertEqual([c[3] for c in cells[:5]], [""] * 5)
        self.assertEqual(H.target_cells(hit, s)[5:], [                                  # the popup's: unchanged
            ("Measured level", "651.2 ft", "6/12/2024 · 9.2 below top"), ("ATD level", "648.2 ft", "12.2 below top"),
            ("Measured level", "649.1 ft", "11.3 below top"), ("ATD level", "649.4 ft", "5/3/2019 · 11 below top")])

    def test_without_a_top_or_a_level(self):
        hit = make_hit(top=None, top_source="none", bottom=None,
                       water_levels=[WaterLevel(640.0, "measured", "5/1/2020", "WL_Elev")])
        self.assertEqual(H.strip_cells(hit, levels_settings())[-1], ("5/1/2020", "640.0 ft", "", "measured"))
        hit = make_hit(water_levels=[])
        self.assertEqual(H.strip_cells(hit, levels_settings())[-1], ("Water level", "—", "none", ""))
        # a type that reads like a level's title is still the lead cell
        hit = make_hit(type_value="Measured level", water_levels=[WaterLevel(651.2, "measured", "", "WL_Elev")])
        cells = H.strip_cells(hit, levels_settings())
        self.assertEqual(cells[0], ("Measured level", "MW-4", "", ""))
        self.assertEqual(cells[-1], ("Measured", "651.2 ft", "9.2 below top", "measured"))

    def test_an_other_point_as_target_cells(self):
        p = OtherPoint(fid=11, label="S-1", type_value="Seep", x=0.0, y=0.0, station=400.0, offset=20.0, side="L",
                       direction="N", ground_at_station=104.0, ground_at_point=104.4, z=103.2, how="field",
                       field_value=103.2, layer_name="Seeps")
        s = levels_settings()
        cells = H.strip_cells(p, s)
        self.assertEqual([c[:3] for c in cells], H.target_cells(p, s))
        self.assertEqual([c[3] for c in cells], [""] * len(cells))
        self.assertEqual(len(cells), 5)


# ----------------------------------------------------------------------------- the CSV
class LongRowsTest(unittest.TestCase):
    def setUp(self):
        self.model = make_model()
        self.header, self.rows = C.surface_rows_long(self.model)

    def rows_of(self, name):
        return [r for r in self.rows if r[0] == name]

    def test_header_and_order(self):
        self.assertEqual(self.header, ["surface", "part", "distance_ft", "elevation_ft"])
        self.assertEqual(C.LONG_COLUMNS, self.header)
        names = [r[0] for r in self.rows]
        order = [n for i, n in enumerate(names) if i == 0 or names[i - 1] != n]
        self.assertEqual(order, ["Ground (lidar)", "Model top", "Water table", "Model top (2)"])   # ground first
        lines = H.hover_lines(self.model)
        self.assertEqual([len(self.rows_of(n)) for n in order], [ln.stations.size for ln in lines])
        self.assertEqual(len(self.rows), sum(ln.stations.size for ln in lines))

    def test_ground_parts_across_the_gap(self):
        rows = self.rows_of("Ground (lidar)")
        self.assertEqual(rows[0], ["Ground (lidar)", 1, 0.0, 100.0])
        by_station = {r[2]: r for r in rows}
        self.assertEqual(by_station[350.0], ["Ground (lidar)", 1, 350.0, 103.5])
        self.assertEqual(by_station[400.0], ["Ground (lidar)", "", 400.0, ""])
        self.assertEqual(by_station[450.0], ["Ground (lidar)", "", 450.0, ""])
        self.assertEqual(by_station[500.0], ["Ground (lidar)", 2, 500.0, 105.0])
        self.assertEqual(by_station[BEND], ["Ground (lidar)", 2, 610.0, 106.1])
        self.assertEqual(rows[-1], ["Ground (lidar)", 2, 1000.0, 110.0])
        self.assertEqual([r[2] for r in rows], sorted(r[2] for r in rows))

    def test_a_single_nan_vertex_breaks_a_smooth_line(self):
        rows = self.rows_of("Model top")
        self.assertEqual([r[1] for r in rows], [1, 1, 1, "", 2, 2, 2])
        self.assertEqual(rows[3], ["Model top", "", 520.0, ""])
        self.assertEqual([r[2] for r in rows], [20.0, 220.0, 420.0, 520.0, 620.0, 820.0, 980.0])

    def test_cells_steps_are_two_rows(self):
        self.assertEqual([r[1:] for r in self.rows_of("Water table")], [
            [1, 0.0, 95.0], [1, 250.0, 95.0], [1, 250.0, 97.0], [1, 500.0, 97.0],
            ["", 500.0, ""], ["", 750.0, ""], [2, 750.0, 99.0], [2, 1000.0, 99.0]])

    def test_a_line_starting_without_data_starts_at_part_1(self):
        sp = SurfaceProfile(name="Head", color="#000", style="solid", width=1.0, mode="smooth",
                            stations=[0.0, 100.0, 200.0, 300.0], z=[NAN, NAN, 5.0, 6.0])
        _, rows = C.surface_rows_long(make_model(surfaces=[sp]), include=[1])
        self.assertEqual([r[1] for r in rows], ["", "", 1, 1])

    def test_include(self):
        _, rows = C.surface_rows_long(self.model, include=[3, 2])          # drawing order whatever the order given
        self.assertEqual([r[0] for r in rows], ["Water table"] * 8 + ["Model top (2)"] * 2)
        _, rows = C.surface_rows_long(self.model, include=[2, 9, -1])      # out of range: skipped
        self.assertEqual({r[0] for r in rows}, {"Water table"})
        header, rows = C.surface_rows_long(self.model, include=[])
        self.assertEqual((header, rows), (C.LONG_COLUMNS, []))

    def test_map_xy_on_the_bent_line(self):
        header, rows = C.surface_rows_long(self.model, map_xy=True)
        self.assertEqual(header, C.LONG_COLUMNS + ["map_x", "map_y"])
        self.assertEqual(C.MAP_COLUMNS, ["map_x", "map_y"])
        for r in rows:
            x, y = map_xy(r[2])
            self.assertAlmostEqual(r[4], x, places=9)
            self.assertAlmostEqual(r[5], y, places=9)
        ground = {r[2]: r[4:] for r in rows if r[0] == "Ground (lidar)"}
        self.assertEqual(ground[0.0], [1000.0, 2000.0])
        self.assertEqual(ground[BEND], [1305.0, 2000.0])
        self.assertEqual(ground[650.0], [1305.0, 2020.0])
        self.assertEqual(ground[LENGTH], [1305.0, 2195.0])
        steps = [r for r in rows if r[0] == "Water table" and r[2] == 250.0]
        self.assertEqual([r[4:] for r in steps], [[1125.0, 2000.0]] * 2)   # a step: the same place twice

    def test_map_xy_without_a_line_is_blank(self):
        _, rows = C.surface_rows_long(make_model(line_wkt=""), include=[0], map_xy=True)
        self.assertEqual({tuple(r[4:]) for r in rows}, {("", "")})


class WideRowsTest(unittest.TestCase):
    def setUp(self):
        self.model = make_model()

    def test_grid_has_the_bend_and_the_end(self):
        np.testing.assert_array_equal(C.wide_stations(self.model, 100.0),
                                      [0, 100, 200, 300, 400, 500, 600, 610, 700, 800, 900, 1000])
        np.testing.assert_array_equal(C.wide_stations(self.model, 250.0), [0, 250, 500, 610, 750, 1000])
        np.testing.assert_array_equal(C.wide_stations(self.model, 10.0)[:3], [0, 10, 20])
        self.assertEqual(C.wide_stations(self.model, 10.0).size, 101)
        self.assertEqual(C.wide_stations(self.model, 500.0).tolist(), [0, 500, 610, 1000])
        self.assertEqual(C.wide_stations(self.model, 2000.0).tolist(), [0, 610, 1000])
        for bad in (0.0, -10.0, NAN, math.inf):
            with self.assertRaises(ValueError):
                C.wide_stations(self.model, bad)

    def test_a_vertex_beats_a_regular_distance_that_rounds_alike(self):
        m = make_model(vertex_stations=[0.0, 600.004, LENGTH])
        grid = C.wide_stations(m, 100.0)
        self.assertIn(600.004, grid.tolist())
        self.assertNotIn(600.0, grid.tolist())

    def test_the_end_is_read_at_the_exact_length(self):
        length = 999.996                                       # rounds up to 1000.0, past the last vertex
        g = GroundProfile(stations=[0.0, 500.0, length], z=[100.0, 110.0, 120.0], step=500.0)
        m = make_model(length=length, vertex_stations=[0.0, length], ground=g, surfaces=[])
        _, rows = C.surface_rows_wide(m, 100.0)
        self.assertEqual(rows[-1], [1000.0, 120.0])

    def test_values_as_drawn(self):
        header, rows = C.surface_rows_wide(self.model, 100.0)
        self.assertEqual(header, ["distance_ft", "Ground (lidar)", "Model top", "Water table", "Model top (2)"])
        table = {r[0]: r[1:] for r in rows}
        self.assertEqual([r[0] for r in rows], [0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 610.0, 700.0, 800.0,
                                               900.0, 1000.0])
        self.assertEqual(table[0.0], [100.0, "", 95.0, 90.0])            # the model top starts at 20 ft
        self.assertEqual(table[100.0], [101.0, 104.8, 95.0, 90.2])
        self.assertEqual(table[300.0], [103.0, 106.8, 97.0, 90.6])
        self.assertEqual(table[400.0], ["", 107.8, 97.0, 90.8])         # DEM gap
        self.assertEqual(table[500.0], [105.0, "", "", 91.0])           # nan vertex; right of the step: no data
        self.assertEqual(table[610.0], [106.1, "", "", 91.22])
        self.assertEqual(table[700.0], [107.0, 109.4, "", 91.4])
        self.assertEqual(table[900.0], [109.0, 110.5, 99.0, 91.8])
        self.assertEqual(table[1000.0], [110.0, "", 99.0, 92.0])         # ... and ends at 980 ft
        lines = H.hover_lines(self.model)
        for r in rows:
            for v, ln in zip(r[1:], lines):
                want = H.line_value(ln, r[0], LENGTH)
                self.assertEqual(v, "" if math.isnan(want) else round(want, 2))

    def test_step_and_include(self):
        header, rows = C.surface_rows_wide(self.model, 250.0, include=[2])
        self.assertEqual(header, ["distance_ft", "Water table"])
        self.assertEqual(rows, [[0.0, 95.0], [250.0, 97.0], [500.0, ""], [610.0, ""], [750.0, 99.0], [1000.0, 99.0]])
        self.assertEqual(len(C.surface_rows_wide(self.model)[1]), 101)               # 10 ft by default

    def test_map_xy(self):
        header, rows = C.surface_rows_wide(self.model, 100.0, include=[0], map_xy=True)
        self.assertEqual(header, ["distance_ft", "Ground (lidar)", "map_x", "map_y"])
        xy = {r[0]: r[2:] for r in rows}
        self.assertEqual(xy[0.0], [1000.0, 2000.0])
        self.assertEqual(xy[300.0], [1150.0, 2000.0])
        self.assertEqual(xy[610.0], [1305.0, 2000.0])                               # the bend
        self.assertEqual(xy[700.0], [1305.0, 2045.0])
        self.assertEqual(xy[1000.0], [1305.0, 2195.0])

    def test_unique_names(self):
        self.assertEqual(C.unique_names(["Model top", "Head", "Model top", "Model top"]),
                         ["Model top", "Head", "Model top (2)", "Model top (3)"])
        self.assertEqual(C.unique_names(["A", "A (2)", "A"]), ["A", "A (2)", "A (3)"])
        self.assertEqual(C.unique_names(["A", "A", "A (2)"]), ["A", "A (2)", "A (2) (2)"])
        self.assertEqual(C.unique_names([]), [])


class _Cells:
    """A raster sampler for section.cells_profile: 7 x 7 cells in the section CRS, 100 to 104 ft."""
    same_crs = True
    cw = ch = 7.0
    x0, y1 = 0.0, 20000.0

    def nearest(self, x, y):
        return 100.0 + np.floor(np.asarray(x) / 7.0) % 5


class EndOfTheLineTest(unittest.TestCase):
    def test_a_cells_surface_reaches_the_end_of_a_bent_line(self):
        # US survey feet (not exactly 1 ft per unit) on bent lines: summed per segment the cell edges ended a
        # rounding error short of the model length on about 1 line in 5, and the wide CSV's last row was blank
        from qgis.core import QgsGeometry, QgsPointXY
        from xsections.core.section import cells_profile, vertex_stations
        f = 1.0000020000040026
        rng = np.random.default_rng(11)
        for k in range(120):
            n = 3 + k % 3
            xy = 8000.0 + np.cumsum(rng.uniform(80.0, 900.0, (n, 2)) * rng.choice([-1.0, 1.0], (n, 2)), axis=0)
            line = QgsGeometry.fromPolylineXY([QgsPointXY(float(x), float(y)) for x, y in xy])
            vs = vertex_stations(line, f)
            st, z, cov = cells_profile(line, _Cells(), f, 7.0 * f)
            self.assertEqual(st[-1], vs[-1], k)
            wt = SurfaceProfile(name="Water table", color="#1f6fb2", style="dash", width=1.25, mode="cells",
                                stations=st, z=z, source="raster")
            g = GroundProfile(stations=list(vs), z=[100.0] * len(vs), step=10.0)
            m = SectionModel(length=vs[-1], vertex_stations=vs, azimuth=0.0, ground=g, hits=[], surfaces=[wt],
                             line_wkt=line.asWkt(), dist_factor=f)
            _, rows = C.surface_rows_wide(m, 10.0)
            self.assertEqual(rows[-1][1:], [100.0, z[-1]], k)


class RoundingTest(unittest.TestCase):
    def test_two_decimals_and_three_for_map_coordinates(self):
        g = GroundProfile(stations=[0.0, 1000.0 / 3.0, 1000.0], z=[100.123456, 100.016, -0.001], step=1.0)
        m = make_model(ground=g, surfaces=[], vertex_stations=[0.0, 1000.0], dist_factor=1.0,
                       line_wkt="LineString (0.12345 0.98765, 1000.12345 0.98765)")
        _, rows = C.surface_rows_long(m, map_xy=True)
        self.assertEqual([r[2:] for r in rows], [[0.0, 100.12, 0.123, 0.988], [333.33, 100.02, 333.457, 0.988],
                                                 [1000.0, 0.0, 1000.123, 0.988]])
        self.assertEqual(math.copysign(1.0, rows[2][3]), 1.0)                       # 0.0, not -0.0
        path = os.path.join(tempfile.mkdtemp(prefix="xsec_csv_"), "r.csv")
        C.write_surfaces_csv(path, m, map_xy=True)
        self.assertEqual(read_csv(path)[3], ["Ground (lidar)", "1", "1000.0", "0.0", "1000.123", "0.988"])


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xsec_csv_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.model = make_model()

    def test_long_file(self):
        path = os.path.join(self.tmp, "Section A-A' surfaces.csv")
        n = C.write_surfaces_csv(path, self.model)
        header, rows = C.surface_rows_long(self.model)
        self.assertEqual(n, len(rows))
        with open(path, "rb") as fh:
            raw = fh.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbfsurface,part,distance_ft,elevation_ft\r\n"))   # BOM, CRLF
        self.assertEqual(raw.count(b"\r\n"), n + 1)
        self.assertNotIn(b"\r\r", raw)
        back = read_csv(path)
        self.assertEqual(back[0], header)
        self.assertEqual(back[1:], [[cell_text(v) for v in r] for r in rows])
        self.assertIn(["Ground (lidar)", "", "400.0", ""], back)

    def test_wide_file_and_quoted_names(self):
        m = make_model()
        m.surfaces[0].name = 'Head, layer 1 "SP 3"'
        path = os.path.join(self.tmp, "wide.csv")
        n = C.write_surfaces_csv(path, m, layout="wide", step_ft=250.0, map_xy=True)
        back = read_csv(path)
        self.assertEqual(n, 6)
        self.assertEqual(len(back), 7)
        self.assertEqual(back[0], ["distance_ft", "Ground (lidar)", 'Head, layer 1 "SP 3"', "Water table",
                                   "Model top", "map_x", "map_y"])
        self.assertEqual(back[4], ["610.0", "106.1", "", "", "91.22", "1305.0", "2000.0"])
        with open(path, encoding="utf-8-sig") as fh:
            self.assertIn('"Head, layer 1 ""SP 3"""', fh.readline())

    def test_bad_layout(self):
        with self.assertRaises(ValueError):
            C.write_surfaces_csv(os.path.join(self.tmp, "x.csv"), self.model, layout="tall")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "x.csv")))

    def test_header_only(self):
        path = os.path.join(self.tmp, "none.csv")
        self.assertEqual(C.write_surfaces_csv(path, self.model, include=[]), 0)
        self.assertEqual(read_csv(path), [C.LONG_COLUMNS])


# ----------------------------------------------------------------------------- real data
@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealDataTest(unittest.TestCase):
    """The CDF A-A′ section with the CDF_Mounding MODFLOW 6 surfaces (as the 0.3.0 samples), plus a cells-mode
    model top named like the smooth one."""

    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
        from tests.test_e2e import copy_realdata, folder_state, line_through_points
        from xsections.core.build import build_section
        from xsections.core.model import SURFACE_DEFAULTS
        from xsections.render.scales import plan

        cls.folder_state = staticmethod(folder_state)
        cls.state = folder_state(REALDATA)
        cls.tmp = tempfile.mkdtemp(prefix="xsec_hover_real_")
        dem_path, wells_path = copy_realdata(cls.tmp)
        cdf = os.path.join(REALDATA, "mf6", "CDF_Mounding")
        grb, hds = os.path.join(cdf, "CDF_Mounding.disu.grb"), os.path.join(cdf, "CDF_Mounding.hds")

        def mf6(var, **kw):
            return dict(SURFACE_DEFAULTS, source="mf6", mf6_path=grb, mf6_head_path=hds, mf6_var=var,
                        z_units="ftUS", **kw)

        prj = QgsProject.instance()
        prj.clear()
        dem = QgsRasterLayer(dem_path, "cdf_lidar")
        wells = QgsVectorLayer(wells_path, "CDF_wells", "ogr")
        prj.addMapLayers([dem, wells])
        prj.setCrs(dem.crs())
        geom, tol = line_through_points(wells, dem.crs(), prj)
        cls.settings = Settings(
            line_wkt=geom.asWkt(), line_crs_authid=dem.crs().toWkt(), dem_layer_id=dem.id(),
            points_layer_id=wells.id(), label_field="ExploName", type_field="ExploType", top_field="ExploElev",
            depth_field="ExploDepth", tolerance_ft=tol, h_scale=200.0, v_scale=20.0, wl_values="depth",
            wl_field="DepthToGW", wl_date_field="ExploDate", wl_label="elev",
            surfaces=[mf6("top", color="#555555", style="dot"),
                      mf6("botm", color="#8c5a3c", mf6_layer=1, in_range=False),
                      mf6("wt", color="#1f6fb2", style="dash", marks=True),
                      mf6("top", color="#999999", mode="cells")])
        cls.model = build_section(cls.settings, prj)
        cls.plan = plan(cls.model, cls.settings)
        prj.clear()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def tearDown(self):
        self.assertEqual(self.folder_state(REALDATA), self.state, "nothing written next to the real data")

    def drawn_lines(self):
        """(x, y) of the ground and of each surface as the preview draws them, in drawing order."""
        fig = Figure(figsize=(14.0, 4.0), dpi=100)
        F.draw_preview(fig, self.model, self.settings, self.plan)
        ax = fig.axes[0]
        ground = [ln for ln in ax.lines if ln.get_zorder() == F.GROUND_Z and ln.get_linewidth() == F.GROUND_LW]
        surfaces = [ln for ln in ax.lines if ln.get_gid() == F.SURFACE_GID]
        self.assertEqual(len(ground), 1)
        return [(np.asarray(ln.get_xdata(), float), np.asarray(ln.get_ydata(), float)) for ln in ground + surfaces]

    def test_the_section(self):
        m = self.model
        self.assertEqual([sp.name for sp in m.surfaces], ["Model top", "Model bottom", "Water table (SP 49)",
                                                          "Model top"])
        self.assertEqual(m.surfaces[3].mode, "cells")
        self.assertGreater(len(m.hits), 0)

    def test_hover_values_are_the_drawn_lines(self):
        lines = H.hover_lines(self.model)
        drawn = self.drawn_lines()
        self.assertEqual(len(drawn), len(lines))
        rng = np.random.default_rng(11)
        length = self.model.length
        for ln, (x, y) in zip(lines, drawn):
            np.testing.assert_array_equal(ln.stations, x)                 # every drawn vertex, nothing else
            np.testing.assert_array_equal(ln.z, y)
            at = np.concatenate([rng.uniform(-30.0, self.plan.plot_length + 30.0, 3000), x])
            want = np.interp(at, x, y, left=np.nan, right=np.nan)       # matplotlib's straight segments
            want[(at < 0.0) | (at > length)] = np.nan
            got = np.array([H.line_value(ln, s, length) for s in at])
            np.testing.assert_allclose(got, want, rtol=0, atol=1e-9, equal_nan=True)
        self.assertGreater(int(np.sum(np.diff(lines[4].stations) == 0)), 10)   # the cells line has steps
        for s in rng.uniform(0.0, length, 200).tolist():
            hv = H.hover_values(lines, s, length, cursor_z=650.0)
            self.assertEqual(hv.values, [H.line_value(ln, s, length) for ln in lines])
            self.assertEqual(hv.ground_z, hv.values[0])
            finite = [i for i, v in enumerate(hv.values) if math.isfinite(v)]
            self.assertEqual(hv.nearest, min(finite, key=lambda i: abs(hv.values[i] - 650.0)) if finite else -1)

    def test_every_drawn_vertex_is_in_the_long_csv(self):
        lines = H.hover_lines(self.model)
        names = C.unique_names(ln.name for ln in lines)
        self.assertEqual(names[-1], "Model top (2)")
        path = os.path.join(self.tmp, "Section A-A' surfaces.csv")
        n = C.write_surfaces_csv(path, self.model, map_xy=True)
        back = read_csv(path)
        self.assertEqual(back[0], C.LONG_COLUMNS + C.MAP_COLUMNS)
        self.assertEqual(n, len(back) - 1)
        self.assertEqual(n, sum(ln.stations.size for ln in lines))
        self.assertEqual(back[1][0], names[0])                             # the ground first
        for name, (x, y) in zip(names, self.drawn_lines()):
            rows = [r for r in back[1:] if r[0] == name]
            self.assertEqual(len(rows), x.size, name)
            self.assertEqual([float(r[2]) for r in rows], [round(v, 2) + 0.0 for v in x.tolist()])
            self.assertEqual([r[3] for r in rows],
                             ["" if math.isnan(v) else str(round(v, 2) + 0.0) for v in y.tolist()])
            parts = [int(r[1]) for r in rows if r[1]]
            self.assertEqual(parts, sorted(parts))
            self.assertEqual(parts[0], 1)
        xs = np.array([float(r[4]) for r in back[1:]])
        self.assertTrue(np.all(np.isfinite(xs)))

    def test_wide_csv(self):
        lines = H.hover_lines(self.model)
        header, rows = C.surface_rows_wide(self.model, 10.0)
        self.assertEqual(header[1:], C.unique_names(ln.name for ln in lines))
        grid = C.wide_stations(self.model, 10.0)
        self.assertEqual(len(rows), grid.size)
        self.assertEqual(rows[-1][0], round(self.model.length, 2))
        for s, r in zip(grid.tolist(), rows):
            for v, ln in zip(r[1:], lines):
                want = H.line_value(ln, s, self.model.length)
                self.assertEqual(v, "" if math.isnan(want) else round(want, 2) + 0.0)

    def test_exploration_rows(self):
        for h in self.model.hits:
            cells = H.hit_cells(h, self.settings)
            self.assertEqual(cells[0][1], h.label)
            self.assertEqual(cells[1][0], "From A")
            self.assertIn(cells[2][2], ("ExploElev", "LIDAR", "none"))
            for title, value, small in cells[1:]:
                self.assertNotIn("nan", value + small)
                self.assertNotIn("-", value)                   # (ranges use an en dash)
            levels = [c for c in cells if c[0] in ("Measured level", "ATD level")]
            self.assertEqual(len(levels), len([w for w in h.water_levels if math.isfinite(w.elev)]))
            for c in levels:
                self.assertTrue(c[2].endswith("below top") or c[2].endswith("above top"), c)


if __name__ == "__main__":
    unittest.main()
