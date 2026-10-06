"""plan(): grid, plot size, elevation limits, sheet choice, tiling, fit messages."""
import math
import unittest

from tests.fixtures import STANDARD_LAYOUT, start_app

start_app()

from xsections.core.model import GroundProfile, Hit, SectionModel, Settings   # noqa: E402
from xsections.render import scales as S                                        # noqa: E402
from xsections.render.scales import plan                                       # noqa: E402


def model(length=4500.0, z_lo=120.0, z_hi=280.0, hits=(), gap=None, td=False):
    """Ground rising linearly from z_lo to z_hi; hits = (label, station, top, bottom). `td`: each hit's
    total depth is top - bottom (so it gets a TD label)."""
    n = 50
    st = [length * i / n for i in range(n + 1)]
    z = [z_lo + (z_hi - z_lo) * s / length for s in st]
    if gap:
        z = [math.nan if gap[0] <= s <= gap[1] else v for s, v in zip(st, z)]
    gp = GroundProfile(stations=st, z=z, step=length / n)
    hh = []
    for i, (lab, s, top, bottom) in enumerate(hits):
        g = z_lo + (z_hi - z_lo) * s / length
        hh.append(Hit(fid=i, label=lab, type_value="Boring", x=0, y=0, station=s, offset=10.0, side="L",
                      direction="N", ground_at_station=g, ground_at_point=g, top=top, top_source="field",
                      bottom=bottom, total_depth=(top - bottom) if td and bottom is not None else None))
    return SectionModel(length=length, vertex_stations=[0.0, length], azimuth=90.0, ground=gp, hits=hh)


def settings(**kw):
    """Settings in the standard layout (STANDARD_LAYOUT: no fill, standard margins) unless `kw` says otherwise."""
    s = Settings(**STANDARD_LAYOUT)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class BluffModel:
    @staticmethod
    def model():
        """Ground at 300 ft falling 30 ft over stations 2560 to 2620; BLUFF-TOP (10 ft deep) at 2500 and
        BLUFF-TOE (20 ft deep) at 2650, 27 ft lower."""
        st = [float(s) for s in range(0, 5001, 5)]
        z = [300.0 if s < 2560 else 300.0 - min(30.0, (s - 2560.0) * 0.5) for s in st]
        g = GroundProfile(stations=st, z=z, step=5.0)
        hits = [Hit(fid=1, label="BLUFF-TOP", type_value="", x=0, y=0, station=2500.0, offset=5.0, side="L",
                    direction="N", ground_at_station=300.0, ground_at_point=300.0, top=300.0, top_source="dem",
                    bottom=290.0, bottom_source="depth", total_depth=10.0),
                Hit(fid=2, label="BLUFF-TOE", type_value="", x=0, y=0, station=2650.0, offset=5.0, side="L",
                    direction="N", ground_at_station=273.0, ground_at_point=273.0, top=273.0, top_source="dem",
                    bottom=253.0, bottom_source="depth", total_depth=20.0)]
        return SectionModel(length=5000.0, vertex_stations=[0.0, 5000.0], azimuth=90.0, ground=g, hits=hits)


class TotalDepthLabels(unittest.TestCase):
    """Room for the TD labels in plan(): rows, auto z, and what a manual range leaves out."""

    def test_stack_labels(self):
        # three at one spot take rows 0, 1, 2; a fourth has no row; one far away stays in row 0
        rows = S.stack_labels([1.0, 1.0, 1.0, 1.0, 3.0], [5.0] * 5, [0.3] * 5, 0.1, 0.12, 0.03)
        self.assertEqual(rows, [0, 1, 2, None, 0])
        # side by side with the pad: clear at 0.34 in apart, not at 0.32 (0.3 wide + 0.03 pad)
        self.assertEqual(S.stack_labels([1.0, 1.34], [5.0, 5.0], [0.3, 0.3], 0.1, 0.12, 0.03), [0, 0])
        self.assertEqual(S.stack_labels([1.0, 1.32], [5.0, 5.0], [0.3, 0.3], 0.1, 0.12, 0.03), [0, 1])
        # a label well below its neighbour does not need to drop
        self.assertEqual(S.stack_labels([1.0, 1.0], [5.0, 4.8], [0.3, 0.3], 0.1, 0.12, 0.03), [0, 0])
        # the sweep follows x, whatever the input order
        self.assertEqual(S.stack_labels([1.1, 1.0], [5.0, 5.0], [0.3, 0.3], 0.1, 0.12, 0.03), [1, 0])
        # obstacles (a neighbour's bar) push a label down like another label does
        bar = (1.06, 1.14, 4.94, 4.96)
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, obstacles=[bar]), [1])
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, obstacles=[(2.0, 2.1, 4.9, 5.0)]), [0])

    def test_soft_obstacles(self):
        """Ticks, exploration labels and the ground line are avoided when a lower row is free; a label is
        never dropped for them (it keeps the first row clear of the labels and bars)."""
        label = (0.9, 1.1, 4.89, 5.2)                      # a neighbour's vertical name label, over row 0
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, soft=[label]), [1])
        tall = (0.9, 1.1, 4.0, 5.2)                        # covers every row alike: row 0 all the same
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, soft=[tall]), [0])
        corner = (1.1, 1.2, 4.72, 5.2)                     # less of it in row 2 than in rows 0 and 1
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, soft=[corner]), [2])
        bar = (1.06, 1.14, 4.94, 4.96)                     # hard and soft together
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, obstacles=[bar], soft=[label]), [1])
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, obstacles=[bar], soft=[tall]), [1])
        # soft boxes never leave a label out: four at one spot still leave the fourth out, not a fifth
        self.assertEqual(S.stack_labels([1.0] * 4, [5.0] * 4, [0.3] * 4, 0.1, 0.12, 0.03, soft=[tall]),
                         [0, 1, 2, None])
        # a ground line crossing row 0 only
        crosses = lambda l, r, b, t: b < 4.95 < t                                       # noqa: E731
        self.assertEqual(S.stack_labels([1.0], [5.0], [0.3], 0.1, 0.12, 0.03, crosses=crosses), [1])
        # ground_test: a step from 300 to 270 ft at station 2560 (1 in = 1,000 ft / 50 ft, y from 0 ft)
        st = [float(s) for s in range(0, 5001, 10)]
        g = GroundProfile(stations=st, z=[300.0 if s < 2560 else 270.0 for s in st], step=10.0)
        test = S.ground_test(g, lambda x: x * 1000.0, lambda z: z / 50.0, clear=0.0)
        self.assertTrue(test(2.40, 2.70, 5.7, 5.9))       # the bluff face runs through 5.4 .. 6.0 in
        self.assertFalse(test(2.40, 2.55, 5.7, 5.9))      # left of it: the ground is at 6.0 in
        self.assertFalse(test(2.60, 2.90, 5.5, 5.8))      # right of it: at 5.4 in

    def test_label_layout_matches_the_drawing(self):
        """The shared layout (scales) puts vertical labels where figure.py draws them."""
        xs, tops = [1.0, 1.01, 1.02, 3.0], [2.0, 2.1, 2.0, 1.0]
        spots = S.label_layout(xs, tops, [0.4] * 4, True)
        sep = S.LABEL_SEP * S.LABEL_PT / 72.0
        self.assertAlmostEqual(spots[1].x - spots[0].x, sep)
        self.assertAlmostEqual(spots[1].x, 1.01)                        # centred on the cluster
        self.assertTrue(all(sp.moved for sp in spots[:3]) and not spots[3].moved)
        self.assertAlmostEqual(spots[0].base, 2.1 + S.LEADER_RISE_IN)   # on the cluster's highest tick
        self.assertAlmostEqual(spots[3].base, 1.0 + S.LABEL_GAP_IN)
        self.assertAlmostEqual(spots[3].box[3] - spots[3].box[2], 0.4)  # reads upwards for its length
        flat = S.label_layout(xs, [2.0] * 4, [0.4] * 4, False, frame_w=3.1)
        self.assertEqual(len({round(sp.base, 6) for sp in flat[:3]}), 3)  # staggered rows
        self.assertAlmostEqual(flat[3].x, 3.1 - 0.2)                    # kept inside the frame
        boxes = S.mark_boxes(xs, [1.8] * 4, spots)
        self.assertEqual(len(boxes), 8)                                 # 4 ticks and 4 labels
        self.assertAlmostEqual(boxes[0][2], 1.8 + S.TICK_FROM_IN)

    def test_plan_keeps_td_labels_off_the_ground_and_labels(self):
        """A 10-ft boring on a bluff top next to one 150 ft on, below the 30-ft bluff (1 in = 1,000 / 50 ft):
        its TD label cannot clear the bluff face (0.6 in tall) but drops off the neighbour's name label.
        At 1 in = 200 / 20 ft there is room: row 0, clear of both. The plan's reach follows."""
        bluff = BluffModel.model()
        s = settings()
        (top_hit, reach), _ = S.td_labels(bluff.hits, s, 5000.0, bluff.ground)
        row0 = 290.0 - (S.TD_GAP_IN + S.TD_TEXT_H_IN) * 50.0
        self.assertLess(reach, row0 - S.TD_ROW_IN * 50.0 + 1e-6)          # dropped at least one row
        marks = S.marks_on_paper(bluff.hits, s, 5.0)
        row = round((row0 - reach) / 50.0 / S.TD_ROW_IN)
        t = 290.0 / 50.0 - S.TD_GAP_IN - row * S.TD_ROW_IN
        w = S.text_width_in("TD 10'", S.TD_PT)
        toe_label = marks[-1]                                              # BLUFF-TOE's name label
        self.assertFalse(S.overlaps_any([toe_label], 2.5 - w / 2, 2.5 + w / 2, t - S.TD_TEXT_H_IN, t))
        s2 = settings(h_scale=200.0, v_scale=20.0)
        (_, reach2), _ = S.td_labels(bluff.hits, s2, 5000.0, bluff.ground)
        self.assertAlmostEqual(reach2, 290.0 - (S.TD_GAP_IN + S.TD_TEXT_H_IN) * 20.0)
        self.assertEqual(plan(bluff, s).z_min, S._floor_to(min(reach, 253.0 - 0.13 * 50) - 50.0, 50.0))

    def test_clamp_centre(self):
        self.assertEqual(S.clamp_centre(0.0, 0.3, 4.0), 0.15)
        self.assertEqual(S.clamp_centre(4.0, 0.3, 4.0), 3.85)
        self.assertEqual(S.clamp_centre(2.0, 0.3, 4.0), 2.0)
        self.assertEqual(S.clamp_centre(0.1, 5.0, 4.0), 2.0)
        # TD labels keep an inset from the frame line
        self.assertAlmostEqual(S.clamp_centre(4.0, 0.3, 4.0, S.TD_EDGE_IN), 3.85 - S.TD_EDGE_IN)
        self.assertAlmostEqual(S.clamp_centre(0.0, 0.3, 4.0, S.TD_EDGE_IN), 0.15 + S.TD_EDGE_IN)
        self.assertEqual(S.clamp_centre(0.1, 3.95, 4.0, S.TD_EDGE_IN), 2.0)

    def test_auto_z_room(self):
        hits = [("B-1", 1000.0, 150.0, 101.0)]
        # without a TD label: 101 - 50 = 51 -> 50; with one: 101 - (0.03 + 0.10) in x 50 = 94.5 -> 44.5 -> 0
        self.assertEqual(plan(model(hits=hits), settings()).z_min, 50.0)
        p = plan(model(hits=hits, td=True), settings())
        self.assertEqual(p.z_min, 0.0)
        self.assertEqual(p.lowest_z, 101.0)
        self.assertEqual(plan(model(hits=hits, td=True), settings(td_label=False)).z_min, 50.0)
        self.assertEqual(plan(model(hits=hits, td=True), settings(depth_line=False)).z_min, 50.0)
        (h, reach), = S.td_labels(model(hits=hits, td=True).hits, settings(), 4500.0)
        self.assertAlmostEqual(reach, 101.0 - (S.TD_GAP_IN + S.TD_TEXT_H_IN) * 50.0)
        # stacked rows need more room: three at one station reach two rows lower
        stack = [(f"B-{i}", 1000.0 + i, 150.0, 101.0) for i in range(3)]
        reach = [r for _, r in S.td_labels(model(hits=stack, td=True).hits, settings(), 4500.0)]
        self.assertAlmostEqual(min(reach), 101.0 - (S.TD_GAP_IN + 2 * S.TD_ROW_IN + S.TD_TEXT_H_IN) * 50.0)

    def test_manual_range_and_crowding_warnings(self):
        hits = [("B-1", 1000.0, 150.0, 101.0)]
        p = plan(model(hits=hits, td=True), settings(z_mode="manual", z_min=100.0, z_max=300.0))
        self.assertEqual(p.warnings, ["TD labels below the manual minimum of 100 ft are left out (B-1). Lower it to "
                                      "50 ft or set Elevations to Auto."])
        p = plan(model(hits=hits, td=True), settings(z_mode="manual", z_min=50.0, z_max=300.0))
        self.assertEqual(p.warnings, [])
        crowd = [(f"C-{i}", 1000.0 + i, 150.0, 101.0) for i in range(5)]
        p = plan(model(hits=crowd, td=True), settings())
        self.assertEqual(p.warnings, ["No room for the TD label of C-3, C-4 (3 rows of TD labels overlap there)."])


class GridAndLimits(unittest.TestCase):
    def test_grid_defaults(self):
        p = plan(model(), settings())
        self.assertEqual((p.h_major, p.h_minor, p.v_major, p.v_minor), (1000.0, 100.0, 50.0, 5.0))
        p = plan(model(), settings(h_scale=200.0, v_scale=20.0))
        self.assertEqual((p.h_major, p.h_minor, p.v_major, p.v_minor), (200.0, 20.0, 20.0, 2.0))
        p = plan(model(), settings(grid_auto=False, h_major=500.0, h_minor=50.0, v_major=25.0, v_minor=5.0))
        self.assertEqual((p.h_major, p.h_minor, p.v_major, p.v_minor), (500.0, 50.0, 25.0, 5.0))

    def test_plot_length_rounding(self):
        self.assertEqual(plan(model(5099.0), settings()).plot_length, 5100.0)
        self.assertEqual(plan(model(5100.0), settings()).plot_length, 5100.0)
        self.assertEqual(plan(model(5100.0000001), settings()).plot_length, 5100.0)
        self.assertEqual(plan(model(5100.5), settings()).plot_length, 5200.0)
        p = plan(model(5099.0), settings())
        self.assertAlmostEqual(p.pages[0].plot_w, 5.1)

    def test_auto_z(self):
        m = model(hits=[("B-1", 1000.0, 150.0, 95.0),            # bottom is the lowest point
                        ("MW-1", 4400.0, 286.0, 250.0)])         # collar above ground: tick base 286
        p = plan(m, settings())
        # lo = 95 -> 95 - 1 in * 50 = 45 -> 0 ; hi = 286 + 0.9 in * 50 = 331 -> 350
        self.assertEqual((p.z_min, p.z_max), (0.0, 350.0))
        self.assertEqual(p.lowest_z, 95.0)
        self.assertEqual(p.lowest_what, "the bottom of B-1")
        p = plan(m, settings(below_in=2.0))                      # 95 - 100 = -5 -> -50
        self.assertEqual(p.z_min, -50.0)
        p = plan(m, settings(depth_line=False))                  # bottoms and tops ignored
        # lo = 120 -> 70 -> 50 ; hi = max ground 280 + 45 = 325 -> 350
        self.assertEqual((p.z_min, p.z_max), (50.0, 350.0))
        self.assertTrue(p.lowest_what.startswith("the ground"))
        # headroom: a top exactly on a major line still gets 0.9 in above it
        p = plan(model(z_lo=100.0, z_hi=300.0), settings(below_in=0.0))
        self.assertEqual((p.z_min, p.z_max), (100.0, 350.0))

    def test_bad_input(self):
        from xsections.core.model import SectionError
        with self.assertRaises(SectionError):
            plan(model(), settings(h_scale=0.0))
        p = plan(model(), settings(grid_auto=False, h_major=0.0, h_minor=0.0, v_major=50.0, v_minor=0.0))
        self.assertEqual((p.h_major, p.h_minor, p.v_minor), (1000.0, 100.0, 5.0))   # blank -> 1 in / 0.1 in
        p = plan(model(), settings())                                # empty ground and no hits still plan
        empty = SectionModel(length=100.0, vertex_stations=[0.0, 100.0], azimuth=float("nan"),
                             ground=GroundProfile(stations=[], z=[], step=1.0), hits=[])
        p = plan(empty, settings())
        self.assertTrue(p.fits)
        self.assertLess(p.z_min, p.z_max)

    def test_manual_z(self):
        p = plan(model(), settings(z_mode="manual", z_min=103.0, z_max=287.0))
        self.assertEqual((p.z_min, p.z_max), (100.0, 300.0))
        p = plan(model(), settings(z_mode="manual", z_min=150.0, z_max=150.0))
        self.assertEqual((p.z_min, p.z_max), (150.0, 200.0))     # always z_max > z_min
        p = plan(model(), settings(z_mode="manual", z_min=300.0, z_max=100.0))
        self.assertEqual((p.z_min, p.z_max), (100.0, 300.0))


class Sheets(unittest.TestCase):
    def test_letter_landscape(self):
        p = plan(model(z_lo=150.0, z_hi=250.0), settings(below_in=0.0))   # z 150..300 -> 3 in tall
        self.assertTrue(p.fits)
        pg = p.pages[0]
        self.assertEqual((pg.page_w, pg.page_h), (11.0, 8.5))
        self.assertEqual(pg.sheet_name, "Letter 11 × 8.5 in, landscape")
        self.assertEqual((pg.plot_w, pg.plot_h), (4.5, 3.0))
        self._margins_ok(pg)

    def test_letter_portrait(self):
        p = plan(model(hits=[("B-1", 1000.0, 150.0, 95.0)]), settings())  # z 0..350 = 7 in tall
        pg = p.pages[0]
        self.assertEqual((pg.page_w, pg.page_h), (8.5, 11.0))
        self.assertIn("portrait", pg.sheet_name)
        self._margins_ok(pg)

    def test_tabloid_next(self):
        p = plan(model(9000.0, 150.0, 250.0), settings(below_in=0.0))    # 9 in wide: too wide for Letter
        pg = p.pages[0]
        self.assertEqual((pg.page_w, pg.page_h), (17.0, 11.0))
        self.assertEqual(len(p.pages), 1)
        self._margins_ok(pg)

    def test_named_sheet(self):
        p = plan(model(z_lo=150.0, z_hi=250.0), settings(sheet="tabloid"))
        self.assertEqual((p.pages[0].page_w, p.pages[0].page_h), (17.0, 11.0))
        p = plan(model(z_lo=150.0, z_hi=250.0), settings(sheet="archd", below_in=0.0))
        self.assertEqual((p.pages[0].page_w, p.pages[0].page_h), (36.0, 24.0))

    def test_custom_page(self):
        p = plan(model(20000.0, 150.0, 250.0), settings(sheet="custom", below_in=0.0, fill_grid="below"))
        pg = p.pages[0]
        self.assertTrue(p.fits)
        self.assertEqual((pg.plot_w, pg.plot_h), (20.0, 3.0))
        self.assertEqual((pg.page_w, pg.page_h), (22.5, 6.5))         # 20 + 2.5 ; 3 + 3.5
        self.assertEqual(pg.sheet_name, "Custom 22.5 × 6.5 in")
        self.assertEqual(p.z_min, 150.0)                              # no fill on custom pages
        p = plan(model(1000.0, 150.0, 200.0), settings(sheet="custom", below_in=0.0))
        pg = p.pages[0]
        self.assertEqual((pg.page_w, pg.page_h), (8.5, 5.5))          # minimum custom page
        p = plan(model(4550.0, 150.0, 200.0), settings(sheet="custom", h_scale=500.0, below_in=0.0))
        self.assertEqual(p.pages[0].page_w, 11.75)                    # 9.1 + 2.5 = 11.6 -> 11.75

    def test_fill_below(self):
        m = model(z_lo=150.0, z_hi=250.0)
        base = plan(m, settings(below_in=0.0))                        # 3 in tall on Letter landscape
        p = plan(m, settings(below_in=0.0, fill_grid="below"))
        # room = 8.5 - 1.2 - 2.3 = 5.0 in; 5.0 - 3.0 = 2 whole majors
        self.assertEqual(p.z_min, base.z_min - 2 * 50.0)
        self.assertEqual(p.z_max, base.z_max)
        self.assertEqual(p.pages[0].plot_h, 5.0)
        self.assertEqual(p.pages[0].plot_bottom, 2.3)
        # major = 75 ft = 1.5 in: 2 in of room takes one whole major, not a partial one
        grid = dict(below_in=0.0, grid_auto=False, h_major=1000.0, h_minor=100.0, v_major=75.0, v_minor=7.5)
        base = plan(m, settings(**grid))
        p = plan(m, settings(fill_grid="below", **grid))
        self.assertEqual((base.z_min, base.z_max), (150.0, 300.0))
        self.assertEqual(p.z_min, 75.0)
        self.assertEqual(p.pages[0].plot_h, 4.5)

    def _margins_ok(self, pg):
        self.assertGreaterEqual(pg.plot_left, S.MARGIN["left"] - 1e-9)
        self.assertLessEqual(pg.plot_left + pg.plot_w, pg.page_w - S.MARGIN["right"] + 1e-9)
        self.assertGreaterEqual(pg.plot_bottom, S.MARGIN["bottom"] - 1e-9)
        self.assertLessEqual(pg.plot_bottom + pg.plot_h, pg.page_h - S.MARGIN["top"] + 1e-9)
        self.assertAlmostEqual(pg.plot_left * 100, round(pg.plot_left * 100), places=6)
        self.assertAlmostEqual(pg.plot_bottom * 100, round(pg.plot_bottom * 100), places=6)


class Tiling(unittest.TestCase):
    def test_tiles_100_scale_tabloid(self):
        m = model(4600.0)
        p = plan(m, settings(h_scale=100.0, allowed_sheets=["letter", "tabloid"]))
        self.assertTrue(p.fits, p.message)
        self.assertEqual(p.plot_length, 4600.0)
        got = [(pg.x_min, pg.x_max, pg.match_left, pg.match_right) for pg in p.pages]
        self.assertEqual(got, [(0.0, 1400.0, None, 1300.0),
                               (1200.0, 2600.0, 1300.0, 2500.0),
                               (2400.0, 3800.0, 2500.0, 3700.0),
                               (3600.0, 4600.0, 3700.0, None)])
        self.assertIn("13+00, 25+00, 37+00", p.message)
        usable = (17.0 - S.MARGIN["left"] - S.MARGIN["right"]) * 100.0
        cores = []
        for i, pg in enumerate(p.pages, 1):
            self.assertEqual((pg.page_w, pg.page_h), (17.0, 11.0))
            self.assertEqual((pg.tile_index, pg.tile_count), (i, 4))
            self.assertLessEqual(pg.x_max - pg.x_min, usable + 1e-9)
            self.assertAlmostEqual(pg.plot_w, (pg.x_max - pg.x_min) / 100.0)
            self.assertEqual(pg.plot_left, p.pages[0].plot_left)     # sheets line up
            a = pg.match_left if pg.match_left is not None else 0.0
            b = pg.match_right if pg.match_right is not None else p.plot_length
            cores.append((a, b))
            if pg.match_right is not None:                            # whole-major core, one-major overlap
                self.assertEqual((b - a) % 100.0, 0.0)
                self.assertEqual(pg.x_max - pg.match_right, 100.0)
            if pg.match_left is not None:
                self.assertEqual(pg.match_left - pg.x_min, 100.0)
                self.assertEqual(pg.match_left % 100.0, 0.0)
        # full coverage: cores tile [0, plot_length] without gaps or overlaps
        self.assertEqual(cores[0][0], 0.0)
        self.assertEqual(cores[-1][1], 4600.0)
        for (a0, b0), (a1, b1) in zip(cores, cores[1:]):
            self.assertEqual(b0, a1)

    def test_vertical_overflow(self):
        m = model(4600.0, hits=[("B-1", 1000.0, 150.0, 95.0)])
        p = plan(m, settings(h_scale=100.0, v_scale=10.0))          # 0..350 ft at 10 ft/in: ~30 in tall
        self.assertFalse(p.fits)
        self.assertIn("tall", p.message)
        self.assertIn("vertical scale", p.message)
        self.assertIn("Tabloid", p.message)

    def test_tile_off_too_long(self):
        p = plan(model(4600.0), settings(h_scale=100.0, tile=False))
        self.assertFalse(p.fits)
        self.assertIn("48.5", p.message)                             # 46 + 2.5 in
        for word in ("custom page size", "larger sheet", "smaller scale", "tiling"):
            self.assertIn(word, p.message)
        self.assertEqual(len(p.pages), 1)                             # the size it would need
        self.assertEqual(p.pages[0].page_w, 48.5)

    def test_named_sheet_tiles(self):
        # 6 in tall: too tall for Letter landscape (5 in of room), so tiles go portrait (7.5 in)
        p = plan(model(4600.0), settings(h_scale=100.0, sheet="letter"))
        self.assertTrue(p.fits, p.message)
        self.assertTrue(all((pg.page_w, pg.page_h) == (8.5, 11.0) for pg in p.pages))
        self.assertIn("portrait", p.pages[0].sheet_name)
        self.assertGreater(len(p.pages), 4)
        self.assertEqual(p.pages[-1].x_max, 4600.0)


class Formatting(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(S.fmt_station(0), "0+00")
        self.assertEqual(S.fmt_station(3250), "32+50")
        self.assertEqual(S.fmt_station(12000), "120+00")
        self.assertEqual(S.fmt_station(45.5), "0+45.5")
        self.assertEqual(S.fmt_num(1000), "1,000")
        self.assertEqual(S.fmt_num(2.5), "2.5")
        self.assertEqual(S.compass16(88.0), "E")
        self.assertEqual(S.compass16(268.0), "W")
        self.assertEqual(S.compass16(200.0), "SSW")
        self.assertEqual(S.engineer_face(1000.0), 10)
        self.assertEqual(S.engineer_face(50.0), 50)
        self.assertEqual(S.engineer_face(200.0), 20)
        self.assertIsNone(S.engineer_face(75.0))
        self.assertEqual(S.ratio(1000.0), "1:12,000")
        self.assertEqual(S.ratio(50.0), "1:600")

    def test_engineer_face_detail_scales(self):
        """1 in = 5 ft reads on the 50 face at 0.1 ft per division, and so on."""
        for scale, face in ((1.0, 10), (2.0, 20), (3.0, 30), (4.0, 40), (5.0, 50), (6.0, 60), (10.0, 10),
                            (250.0, None), (25.0, None), (0.5, None)):
            self.assertEqual(S.engineer_face(scale), face, scale)

    def test_text_width_estimate(self):
        from xsections.render.figure import text_width_pt
        for s in ("MW-12R · 140 ft NW", "B-101A", "CPT-1", "Monitoring well 12 (abandoned)"):
            self.assertAlmostEqual(S.text_width_in(s, 7.0), text_width_pt(s, 7.0) / 72.0,
                                   delta=0.05 * text_width_pt(s, 7.0) / 72.0)     # no kerning: within 5 %


class LabelsAndManualRange(unittest.TestCase):
    """The tick-raise rule, label headroom and what a manual elevation range cuts off."""

    def test_tick_raised_only_with_a_drawn_line(self):
        m = model(hits=[("MW-1", 1000.0, 180.0, 150.0),      # top 24 ft above the ground, bottom: line drawn
                        ("MW-2", 2000.0, 200.0, None)])      # top 11 ft above, no bottom: no line
        s = settings()
        a, b = m.hits
        self.assertEqual(S.tick_base(a, s), 180.0)
        self.assertEqual(S.tick_base(b, s), b.ground_at_station)
        self.assertFalse(S.draws_depth_line(b, s))
        self.assertEqual(S.tick_base(a, settings(depth_line=False)), a.ground_at_station)

    def test_headroom_grows_for_long_labels(self):
        # highest tick 290 ft at 1 in = 50 ft: 0.9 in of headroom -> 335 -> 350
        hits = [("MW-12R", 4400.0, 290.0, 250.0), ("B-101A", 4300.0, 276.0, 250.0)]
        short = plan(model(hits=hits), settings(label_field="x"))
        self.assertEqual(short.z_max, 350.0)
        m = model(hits=hits)
        for h in m.hits:
            h.offset, h.direction = 140.0, "NW"
        s = settings(label_offset=True)                      # "MW-12R · 140 ft NW" is about 1.1 in long
        p = plan(m, s)
        need = max(S.tick_base(h, s) for h in m.hits) + (S.TICK_TO_IN + S.LABEL_GAP_IN + S.LEADER_RISE_IN
                                                         + S.text_width_in("MW-12R · 140 ft NW", 7.0)) * 50.0
        self.assertGreaterEqual(p.z_max, need)
        self.assertGreater(p.z_max, short.z_max)

    def test_headroom_for_stacked_horizontal_labels(self):
        hits = [(f"MW-{i}", 4300.0 + 10.0 * i, None, None) for i in range(14)]    # 14 labels within 0.14 in
        m = model(hits=hits)
        vertical = plan(m, settings())
        stacked = plan(m, settings(label_vertical=False))
        self.assertGreater(stacked.z_max, vertical.z_max)
        top = S.label_top(m.hits, settings(label_vertical=False))
        self.assertLessEqual(top, stacked.z_max)
        # 14 rows of 0.112 in: well over the default 0.9 in
        self.assertGreater(top - max(h.ground_at_station for h in m.hits), 14 * S.LABEL_ROW_IN * 50.0)

    def test_manual_range_warnings(self):
        m = model(hits=[("B-4", 4000.0, 262.0, 230.0), ("B-1", 500.0, 130.0, 90.0),
                        ("MW-12R", 4450.0, 279.0, 240.0)])
        p = plan(m, settings(z_mode="manual", z_min=100.0, z_max=200.0))
        self.assertEqual(len(p.warnings), 1)
        w = p.warnings[0]
        self.assertIn("manual elevation range 100 to 200 ft cuts off data up to 280 ft", w)
        self.assertIn("down to 90 ft", w)
        self.assertIn("not drawn: B-4", w)
        self.assertNotIn("B-1,", w)
        p = plan(m, settings(z_mode="manual", z_min=0.0, z_max=100.0))
        self.assertEqual(p.warnings, ["The ground (120 to 280 ft) is outside the manual elevation range 0 to "
                                      "100 ft. Widen the range or set Elevations to Auto."])
        p = plan(m, settings(z_mode="manual", z_min=0.0, z_max=400.0))
        self.assertEqual(p.warnings, [])
        self.assertEqual(plan(m, settings()).warnings, [])           # auto never cuts anything off
        # everything inside, but no room left for the labels above the highest tick
        p = plan(m, settings(z_mode="manual", z_min=50.0, z_max=300.0))
        self.assertEqual(len(p.warnings), 1)
        self.assertIn("labels run above the plot", p.warnings[0])


if __name__ == "__main__":
    unittest.main()
