"""Drawing tests: the sheet's axes sit at exact paper inches, and the spec'd marks are present."""
import math
import unittest

from tests.fixtures import STANDARD_LAYOUT, start_app

start_app()

import numpy as np                                                    # noqa: E402
from matplotlib.figure import Figure                                  # noqa: E402
from matplotlib.lines import Line2D                                    # noqa: E402
from matplotlib.text import Annotation, Text                         # noqa: E402

from xsections.core.model import GroundProfile, Hit, SectionModel, Settings   # noqa: E402
from xsections.render import figure as F                              # noqa: E402
from xsections.render.scales import TD_EDGE_IN, clamp_centre, plan    # noqa: E402


# ----------------------------------------------------------------------------- hand-made models
def ground_z(s):
    return 200.0 - 80.0 * math.cos(2 * math.pi * s / 3000.0) + 6.0 * math.sin(s / 97.0)


# (label, type, station, top relative to ground (None = no top), depth (None = no bottom), offset, direction)
HITS = [
    ("B-1", "Boring", 150.0, 0.0, 40.0, 35.0, "N"),
    ("MW-1", "Monitoring Well", 420.0, 0.0, 30.0, 60.0, "S"),
    ("MW-2", "Monitoring Well", 455.0, 6.0, 55.0, 20.0, "N"),        # collar 6 ft above LIDAR: tick raised
    ("TP-1", "Test Pit", 470.0, 0.0, 12.0, 90.0, "SE"),
    ("CPT-1", "CPT", 1100.0, 0.0, 60.0, 10.0, "N"),
    ("B-2", "Boring", 1650.0, -15.0, 70.0, 120.0, "NW"),              # top 15 ft below ground: dotted link
    ("B-3", "Boring", 2050.0, 0.0, 45.0, 30.0, "S"),                  # station in the DEM gap
    ("MW-3", "Monitoring Well", 2600.0, 0.0, 50.0, 80.0, "NE"),        # on the bend
    ("B-4", "Boring", 2950.0, 0.0, 65.0, 40.0, "S"),
    ("CPT-2", "CPT", 3400.0, 0.0, 80.0, 15.0, "N"),
    ("TP-2", "Test Pit", 3900.0, 0.0, None, 50.0, "W"),               # no bottom: tick only
    ("B-5", "Boring", 4380.0, 0.0, 35.0, 25.0, "E"),
]
GAP = (2000.0, 2090.0)


def make_model(length=4500.0, step=5.0, bend=2600.0, hits=HITS, gap=GAP, azimuth=88.0, td=False):
    """A section with `hits`; `td` fills each hit's total depth (as the core does), so TD labels show."""
    st = list(np.arange(0.0, length, step)) + [length]
    if bend is not None and bend not in st:
        st = sorted(st + [bend])
    z = [math.nan if gap and gap[0] <= s <= gap[1] else ground_z(s) for s in st]
    gp = GroundProfile(stations=st, z=z, step=step, gaps=[gap] if gap else [],
                       coverage=float(np.mean([not math.isnan(v) for v in z])))
    out = []
    for i, (lab, typ, s, dtop, depth, off, d) in enumerate(hits):
        if s > length:
            continue
        g = gp.z_at(s)
        if math.isnan(g):
            g = gp.nearest_valid(s)
        top = None if dtop is None else g + dtop
        bottom = None if (top is None or depth is None) else top - depth
        out.append(Hit(fid=i + 1, label=lab, type_value=typ, x=0.0, y=0.0, station=s, offset=off, side="L",
                       direction=d, ground_at_station=g, ground_at_point=g, top=top,
                       top_source="field" if dtop else "dem", bottom=bottom, in_gap=bool(gap and gap[0] <= s <= gap[1]),
                       bottom_source="depth" if bottom is not None else "none",
                       total_depth=depth if (td and bottom is not None) else None))
    vs = [0.0] + ([bend] if bend is not None else []) + [length]
    return SectionModel(length=length, vertex_stations=vs, azimuth=azimuth, ground=gp, hits=out,
                        dem_name="LIDAR_DEM_5ft", points_name="Explorations")


def make_settings(**over):
    """Settings for the hand-made models, in the standard layout (STANDARD_LAYOUT) unless `over` says otherwise."""
    s = Settings(label_field="ExploName", type_field="ExploType", tolerance_ft=150.0, **STANDARD_LAYOUT)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def texts_of(fig):
    out = []
    for t in fig.findobj(lambda a: isinstance(a, Text)):
        if t.get_text():
            out.append(t.get_text())
    return out


# ----------------------------------------------------------------------------- tests
class DrawPageTest(unittest.TestCase):
    def setUp(self):
        self.model = make_model()
        self.settings = make_settings()
        self.plan = plan(self.model, self.settings)
        self.page = self.plan.pages[0]
        self.fig = Figure(dpi=72)
        F.draw_page(self.fig, self.model, self.settings, self.plan, self.page)

    def test_axes_at_exact_inches(self):
        fig, page = self.fig, self.page
        self.assertEqual(tuple(fig.get_size_inches()), (page.page_w, page.page_h))
        ax = fig.axes[0]
        pos = ax.get_position()
        self.assertAlmostEqual(pos.x0 * page.page_w, page.plot_left, places=9)
        self.assertAlmostEqual(pos.y0 * page.page_h, page.plot_bottom, places=9)
        self.assertAlmostEqual(pos.width * page.page_w, page.plot_w, places=9)
        self.assertAlmostEqual(pos.height * page.page_h, page.plot_h, places=9)
        self.assertEqual(ax.get_xlim(), (page.x_min, page.x_max))
        self.assertEqual(ax.get_ylim(), (self.plan.z_min, self.plan.z_max))
        # the scale itself: ft per paper inch
        self.assertAlmostEqual((page.x_max - page.x_min) / page.plot_w, self.settings.h_scale, places=6)
        self.assertAlmostEqual((self.plan.z_max - self.plan.z_min) / page.plot_h, self.settings.v_scale, places=6)
        self.assertFalse(ax.get_autoscale_on())
        self.assertEqual(ax.get_aspect(), "auto")

    def test_marks_present(self):
        t = texts_of(self.fig)
        joined = "\n".join(t)
        self.assertIn("CROSS SECTION A–A′", t)
        self.assertIn("A′", t)
        self.assertIn("(W)", t)          # azimuth 88 deg: A is the west end
        self.assertIn("(E)", t)
        self.assertIn("BEND", t)
        self.assertIn("NO DEM DATA", t)
        self.assertNotIn("1.00 in CHECK", t)                       # no check bar: the grid is the scale
        self.assertIn("50 ft", t)   # vertical scale bar
        self.assertIn("Distance along section (ft)", t)
        self.assertEqual(t.count("Elevation (ft NAVD88)"), 2)
        self.assertNotIn("check bar", joined)                      # and no red instruction
        self.assertNotIn("Do not fit to page", joined)
        self.assertIn("1:12,000", joined)
        self.assertIn("10 scale", joined)
        self.assertIn("VERTICAL EXAGGERATION 20×", joined)
        self.assertIn("Explorations within 150 ft", joined)
        for lab, *_ in HITS:
            self.assertIn(lab, t)

    def test_grid_lines_are_explicit_multiples(self):
        ax = self.fig.axes[0]
        minor_c, major_c = F.GRID_COLORS["green"]
        xs_major, xs_minor = set(), set()
        for ln in ax.lines:
            if ln.get_color() in (minor_c, major_c):
                x, y = np.asarray(ln.get_xdata(), float), np.asarray(ln.get_ydata(), float)
                vert = x[0::3] == x[1::3]
                vals = x[0::3][vert]
                (xs_major if ln.get_color() == major_c else xs_minor).update(np.round(vals, 6))
                self.assertAlmostEqual(ln.get_linewidth(), F.MAJOR_LW if ln.get_color() == major_c else F.MINOR_LW)
        self.assertEqual(sorted(xs_major), [1000.0, 2000.0, 3000.0, 4000.0])
        self.assertEqual(len(xs_minor), 45 - 4 - 1)
        self.assertTrue(all(abs(v / 100 - round(v / 100)) < 1e-9 for v in xs_minor))

    def test_tick_in_paper_units(self):
        """Tick = marker '|' 0.14 in long, centred 0.11 in above the tick base."""
        ax = self.fig.axes[0]
        ticks = [ln for ln in ax.lines if ln.get_marker() == "|"]
        self.assertEqual(len(ticks), 1)
        tk = ticks[0]
        self.assertAlmostEqual(tk.get_markersize(), 0.14 * 72, places=6)
        self.assertAlmostEqual(tk.get_markeredgewidth(), 0.9)
        # raised tick for MW-2 (collar above LIDAR)
        i = [h.label for h in self.model.hits].index("MW-2")
        self.assertAlmostEqual(tk.get_ydata()[i], self.model.hits[i].top)
        # offset of 0.11 in at any dpi
        for dpi in (72, 300):
            self.fig.set_dpi(dpi)
            p0 = ax.transData.transform((1000.0, 200.0))
            p1 = tk.get_transform().transform((1000.0, 200.0))
            self.assertAlmostEqual((p1[1] - p0[1]) / dpi, 0.11, places=9)

    def test_labels_spread(self):
        """MW-1 / MW-2 / TP-1 are 35 and 15 ft apart (0.035, 0.015 in): spread with leaders."""
        ax = self.fig.axes[0]
        ann = {a.get_text(): a for a in ax.texts if isinstance(a, Annotation)}
        xs = [ann[n].xyann[0] for n in ("MW-1", "MW-2", "TP-1")]    # points, relative to each tick
        stations = [420.0, 455.0, 470.0]
        paper = [s / 1000.0 * 72 + dx for s, dx in zip(stations, xs)]
        sep = F.LABEL_SEP * F.LABEL_PT
        self.assertGreaterEqual(paper[1] - paper[0], sep - 1e-6)
        self.assertGreaterEqual(paper[2] - paper[1], sep - 1e-6)
        self.assertIsNotNone(ann["MW-1"].arrow_patch)
        self.assertIsNone(ann["CPT-1"].arrow_patch)                  # alone: no leader
        self.assertEqual(ann["CPT-1"].get_rotation(), 90.0)

    def test_station_labels_and_horizontal(self):
        s = make_settings(distance_labels="station", label_vertical=False, label_offset=True, data_color="type",
                          grid_color="gray", shade_below=True, title="Test project")
        fig = Figure()
        F.draw_page(fig, self.model, s, plan(self.model, s), plan(self.model, s).pages[0])
        fig.canvas.draw()
        ax = fig.axes[0]
        labels = [t.get_text() for t in ax.get_xticklabels() if t.get_text()]
        self.assertIn("10+00", labels)
        self.assertIn("40+00", labels)
        t = texts_of(fig)
        self.assertIn("Station (ft)", t)
        self.assertIn("MW-3 · 80 ft NE", t)
        self.assertIn("Test project", t)
        self.assertIn("Line colors:", t)
        rot = {a.get_rotation() for a in ax.texts if isinstance(a, Annotation) and "·" in a.get_text()}
        self.assertEqual(rot, {0.0})

    def test_display_label(self):
        h = self.model.hits[0]
        self.assertEqual(F.display_label(h, make_settings()), "B-1")
        self.assertEqual(F.display_label(h, make_settings(label_offset=True)), "B-1 · 35 ft N")

    def test_spread_1d(self):
        pos, grp = F.spread_1d(np.array([0.0, 0.01, 0.02, 5.0]), 0.1)
        self.assertTrue(np.all(np.diff(pos[:3]) >= 0.1 - 1e-12))
        self.assertAlmostEqual(pos[:3].mean(), 0.01)            # centred on the members' mean
        self.assertEqual(pos[3], 5.0)
        self.assertEqual(len(set(grp[:3])), 1)
        self.assertNotEqual(grp[3], grp[0])


class BendLinesToggle(unittest.TestCase):
    """settings.show_bends: dashed line + "BEND" at each bend, on by default, can be turned off."""

    @staticmethod
    def bend_lines(fig):
        from matplotlib.colors import to_hex
        return [ln for ax in fig.axes for ln in ax.lines
                if to_hex(ln.get_color()) == to_hex(F.BEND) and list(ln.get_xdata()) == [2600.0, 2600.0]]

    def test_on_by_default_and_off_when_unticked(self):
        model = make_model()                       # one bend, at 2,600 ft
        for show, n in ((True, 1), (False, 0)):
            s = make_settings(show_bends=show)
            p = plan(model, s)
            page = Figure(dpi=72)
            F.draw_page(page, model, s, p, p.pages[0])
            preview = Figure(figsize=(8, 4), dpi=72)
            F.draw_preview(preview, model, s, p)
            for fig in (page, preview):
                with self.subTest(show=show, fig="page" if fig is page else "preview"):
                    self.assertEqual(texts_of(fig).count("BEND"), n)
                    self.assertEqual(len(self.bend_lines(fig)), n)
        self.assertTrue(Settings().show_bends)


class DrawEdgeCases(unittest.TestCase):
    def test_empty_model_and_nan_azimuth(self):
        m = SectionModel(length=750.0, vertex_stations=[0.0, 750.0], azimuth=float("nan"),
                         ground=GroundProfile(stations=[0.0, 375.0, 750.0], z=[math.nan] * 3, step=375.0), hits=[])
        s = make_settings()
        p = plan(m, s)
        fig = Figure()
        F.draw_page(fig, m, s, p, p.pages[0])
        fig.canvas.draw()
        F.draw_preview(Figure(figsize=(6, 3)), m, s, p)
        t = texts_of(fig)
        self.assertIn("A", t)
        self.assertFalse(any(x.startswith("(") and len(x) <= 5 for x in t))   # no compass without an azimuth

    def test_gap_at_start(self):
        m = make_model(gap=(0.0, 120.0))
        s = make_settings()
        fig = Figure()
        p = plan(m, s)
        F.draw_page(fig, m, s, p, p.pages[0])
        self.assertIn("NO DEM DATA", texts_of(fig))


class DrawTilesTest(unittest.TestCase):
    def test_match_lines(self):
        model = make_model(length=4600.0)
        s = make_settings(h_scale=100.0, allowed_sheets=["tabloid"])
        p = plan(model, s)
        self.assertGreater(len(p.pages), 1)
        fig = Figure()
        F.draw_page(fig, model, s, p, p.pages[1])
        t = texts_of(fig)
        pg = p.pages[1]
        self.assertIn(f"CROSS SECTION A–A′ (SHEET 2 OF {len(p.pages)})", t)
        self.assertIn(f"MATCH LINE STA 13+00 · SEE SHEET 1 OF {len(p.pages)}", t)
        self.assertIn(f"MATCH LINE STA 25+00 · SEE SHEET 3 OF {len(p.pages)}", t)
        self.assertNotIn("A′", t)                               # not a true end on a middle sheet
        self.assertEqual(fig.axes[0].get_xlim(), (pg.x_min, pg.x_max))


def flat_model(length, z, hits=(), step=50.0, td=False):
    """Ground at a constant (or callable) elevation; hits = (label, type, station, top above ground, depth)."""
    st = list(np.arange(0.0, length, step)) + [length]
    zf = z if callable(z) else (lambda s: z)
    gp = GroundProfile(stations=st, z=[zf(s) for s in st], step=step)
    out = []
    for i, (lab, typ, s, dtop, depth) in enumerate(hits):
        g = zf(s)
        top = g + dtop
        out.append(Hit(fid=i + 1, label=lab, type_value=typ, x=0.0, y=0.0, station=s, offset=140.0, side="L",
                       direction="NW", ground_at_station=g, ground_at_point=g, top=top, top_source="field",
                       bottom=None if depth is None else top - depth,
                       total_depth=depth if (td and depth is not None) else None))
    return SectionModel(length=length, vertex_stations=[0.0, length], azimuth=90.0, ground=gp, hits=out,
                        dem_name="LIDAR", points_name="Explorations")


def drawn(model, settings, index=0, dpi=100):
    """Draw one sheet on an Agg canvas (so text extents can be measured)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    p = plan(model, settings)
    fig = Figure(dpi=dpi)
    FigureCanvasAgg(fig)
    F.draw_page(fig, model, settings, p, p.pages[index])
    fig.canvas.draw()
    return fig, p, p.pages[index]


def label_annotations(fig, texts):
    return [a for a in fig.axes[0].texts if isinstance(a, Annotation) and a.get_text() in texts]


class SheetLayoutTest(unittest.TestCase):
    """Marks stay where the spec puts them: in the frame, apart from each other, off the page edge."""

    def test_match_line_under_the_data(self):
        model = make_model(length=4600.0, hits=HITS + [("CPT-9", "CPT", 1300.0, 0.0, 60.0, 10.0, "N")])
        s = make_settings(h_scale=100.0, allowed_sheets=["tabloid"])
        fig, p, page = drawn(model, s, index=1, dpi=72)
        self.assertEqual(page.match_left, 1300.0)
        ax = fig.axes[0]
        match = [ln for ln in ax.lines if ln.get_color() == F.MATCH]
        self.assertEqual(len(match), 2)
        ground = [ln for ln in ax.lines if ln.get_color() == F.INK and ln.get_linewidth() == F.GROUND_LW]
        depth = [ln for ln in ax.lines if ln.get_color() == F.DATA and ln.get_linewidth() == F.DEPTH_LW]
        ticks = [ln for ln in ax.lines if ln.get_marker() == "|"]
        self.assertTrue(ground and depth and ticks)
        top_match = max(ln.get_zorder() for ln in match)
        self.assertLess(top_match, min(ln.get_zorder() for ln in ground + depth + ticks))
        self.assertGreater(top_match, 1.0)                          # still over the grid and bend lines
        notes = [a for a in ax.texts if a.get_text().startswith("MATCH LINE")]
        self.assertTrue(notes and all(a.get_zorder() >= 7.9 for a in notes))

    def test_match_text_fits_a_short_plot(self):
        model = flat_model(30000.0, 100.0)                       # 1 in = 1,000 / 50 ft: plot 30 x 2 in
        s = make_settings()
        p = plan(model, s)
        self.assertEqual(p.pages[0].plot_h, 2.0)
        self.assertEqual(len(p.pages), 3)
        text, size = F.match_text(13000.0, 1, 3, 2.0)
        self.assertEqual(text, "MATCH LINE STA 130+00\nSEE SHEET 1 OF 3")
        self.assertEqual(size, 7.0)
        self.assertEqual(F.match_text(13000.0, 1, 3, 5.0)[0], "MATCH LINE STA 130+00 · SEE SHEET 1 OF 3")
        self.assertLess(F.match_text(13000.0, 1, 3, 1.0)[1], 7.0)     # very short: smaller type
        fig, p, page = drawn(model, s, index=1)
        ax = fig.axes[0]
        frame = ax.get_window_extent()
        r = fig.canvas.get_renderer()
        inset = 0.1 * fig.dpi
        notes = [a for a in ax.texts if a.get_text().startswith("MATCH LINE")]
        self.assertEqual(len(notes), 4)                           # two lines, each drawn with a halo copy
        for a in notes:
            bb = a.get_window_extent(r)
            self.assertGreaterEqual(bb.y0, frame.y0 + inset - 1.0)
            self.assertLessEqual(bb.y1, frame.y1 - inset + 1.0)

    def test_left_title_keeps_off_the_page_edge(self):
        model = flat_model(9000.0, lambda st: 1550.0 + 60.0 * math.sin(st / 1500.0))
        s = make_settings(v_scale=20.0, sheet="custom")
        fig, p, page = drawn(model, s)
        self.assertEqual(page.plot_left, 1.0)
        titles = [a for a in fig.axes[0].texts if a.get_text() == "Elevation (ft NAVD88)"]
        self.assertEqual(sorted(a.get_rotation() for a in titles), [90.0, 270.0])
        r = fig.canvas.get_renderer()
        left = min(a.get_window_extent(r).x0 for a in titles) / fig.dpi
        right = max(a.get_window_extent(r).x1 for a in titles) / fig.dpi
        self.assertGreaterEqual(left, 0.5 - 0.005)
        self.assertLessEqual(right, page.page_w - 0.5)
        ticklabels = [t for t in fig.axes[0].get_yticklabels() if t.get_text()]
        self.assertTrue(any(len(t.get_text()) == 5 for t in ticklabels))       # "1,600"
        lab_left = min(t.get_window_extent(r).x0 for t in ticklabels) / fig.dpi
        self.assertLess(max(a.get_window_extent(r).x1 for a in titles if a.get_rotation() == 90) / fig.dpi,
                        lab_left)                                              # and clear of the labels

    def test_note_lines_do_not_overlap(self):
        model = make_model()
        model.dem_name = "Clark_County_2019_LIDAR_bare_earth_DEM_1ft_USft_NAVD88_mosaic_v3_final_reviewed"
        s = make_settings(label_offset=True, data_color="type")
        fig, p, page = drawn(model, s)
        r = fig.canvas.get_renderer()
        below = page.plot_bottom - 0.8
        block = [t for t in fig.texts if t.get_fontsize() == F.NOTE_PT
                 and t.get_window_extent(r).y1 / fig.dpi < below]
        self.assertIn("Line colors:", [t.get_text() for t in block])
        n3 = [t for t in block if t.get_text().startswith("Ground: ")]
        self.assertEqual(len(n3), 1)
        boxes = [(t.get_text(), t.get_window_extent(r)) for t in block]
        for i, (ta, a) in enumerate(boxes):
            for tb, b in boxes[i + 1:]:
                overlap = min(a.x1, b.x1) - max(a.x0, b.x0) > 0.5 and min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5
                self.assertFalse(overlap, f"{ta!r} overlaps {tb!r}")
        # note lines sit at the fixed pitch, plus the gap between notes
        ys = sorted((t.get_position()[1] for t in block if t.get_verticalalignment() == "top"), reverse=True)
        self.assertGreaterEqual(len(ys), 5)
        for a, b in zip(ys, ys[1:]):
            self.assertTrue(abs(a - b - F.NOTE_PITCH_IN) < 1e-9 or abs(a - b - F.NOTE_PITCH_IN - F.NOTE_GAP_IN) < 1e-9,
                            a - b)
        self.assertGreaterEqual(min(t.get_window_extent(r).y0 for t in block) / fig.dpi, 0.5)

    def test_many_types_stay_distinct(self):
        types = ["Boring", "Test Pit", "CPT", "Vapor Probe", "Monitoring Well", "Direct Push", "Test Trench",
                 "Extraction Well", "Piezometer", "Hand Auger", "Sonic", "Air Rotary"]
        hits = [(f"X-{i}", t, 200.0 + 350.0 * i, 0.0, 30.0, 20.0, "N") for i, t in enumerate(types)]
        model = make_model(hits=hits, gap=None)
        styles = F.type_styles(model)
        self.assertEqual(len(styles), 12)
        self.assertEqual(len({(c, str(ls)) for c, ls in styles.values()}), 12)
        fig, p, page = drawn(model, make_settings(data_color="type"), dpi=72)

        def style(ln):
            return ln.get_color(), repr(ln._unscaled_dash_pattern)

        depth = [ln for ln in fig.axes[0].lines if ln.get_linewidth() == F.DEPTH_TYPE_LW and ln.get_marker() != "_"]
        self.assertEqual(len(depth), 12)
        self.assertEqual(len({style(ln) for ln in depth}), 12)
        swatches = [a for a in fig.artists if isinstance(a, Line2D) and a.get_linewidth() == F.DEPTH_TYPE_LW]
        self.assertEqual(len(swatches), 12)
        self.assertEqual({style(a) for a in swatches}, {style(ln) for ln in depth})   # legend matches the lines

    def test_tick_not_raised_without_a_line(self):
        hits = HITS + [("TP-9", "Test Pit", 3150.0, 9.0, None, 20.0, "N")]      # top 9 ft up, no depth
        model = make_model(hits=hits)
        fig, p, page = drawn(model, make_settings(), dpi=72)
        tk = [ln for ln in fig.axes[0].lines if ln.get_marker() == "|"][0]
        i = [h.station for h in model.hits].index(3150.0)
        h = model.hits[i]
        self.assertGreater(h.top, h.ground_at_station)
        self.assertAlmostEqual(tk.get_xdata()[i], 3150.0)
        self.assertAlmostEqual(tk.get_ydata()[i], h.ground_at_station)       # on the ground line

    def test_manual_range_leaves_out_cut_off_ticks(self):
        model = make_model()
        s = make_settings(z_mode="manual", z_min=100.0, z_max=200.0)
        fig, p, page = drawn(model, s, dpi=72)
        tk = [ln for ln in fig.axes[0].lines if ln.get_marker() == "|"]
        ys = np.asarray(tk[0].get_ydata(), float) if tk else np.array([])
        self.assertTrue(np.all((ys >= 100.0) & (ys <= 200.0)))
        inside = {h.label for h in model.hits if 100.0 <= S_tick_base(h, s) <= 200.0}
        outside = {h.label for h in model.hits} - inside
        self.assertTrue(inside and outside)
        shown = {a.get_text() for a in fig.axes[0].texts if isinstance(a, Annotation)}
        self.assertTrue(inside <= shown)
        self.assertFalse(outside & shown)
        self.assertTrue(p.warnings)

    def test_labels_stay_in_the_frame(self):
        # long labels ("MW-3 · 80 ft NE") and a stack of 14 horizontal labels: auto z leaves room for them
        cases = [(make_model(), make_settings(label_offset=True))]
        stack = [(f"MW-{i}", "Monitoring Well", 3000.0 + 12.0 * i, 0.0, 40.0, 30.0, "N") for i in range(14)]
        cases.append((make_model(hits=stack, gap=None), make_settings(label_vertical=False)))
        for model, s in cases:
            fig, p, page = drawn(model, s)
            texts = {F.display_label(h, s) for h in model.hits}
            anns = label_annotations(fig, texts)
            self.assertEqual(len(anns), len(model.hits))
            r = fig.canvas.get_renderer()
            frame_top = fig.axes[0].get_window_extent().y1
            for a in anns:
                self.assertLessEqual(a.get_window_extent(r).y1, frame_top + 1.0, a.get_text())

    def test_detail_vertical_scale_names_its_face(self):
        s = make_settings(h_scale=50.0, v_scale=5.0)
        p = plan(make_model(length=600.0, hits=[], gap=None, bend=None), s)
        note2 = F.notes_text(make_model(), s, p, p.pages[0])[0][0].replace(" ", " ")
        self.assertIn("HORIZONTAL 1 in = 50 ft (1:600), 50 scale", note2)
        self.assertIn("VERTICAL 1 in = 5 ft (1:60), 50 scale", note2)


def S_tick_base(h, s):
    from xsections.render.scales import tick_base
    return tick_base(h, s)



def td_texts(fig):
    return [t for t in fig.axes[0].texts if t.get_gid() == F.TD_GID]


def cap_lines(fig):
    return [ln for ln in fig.axes[0].lines if ln.get_gid() == F.CAP_GID]


def overlaps(a, b, slack=0.0):
    return min(a.x1, b.x1) - max(a.x0, b.x0) > slack and min(a.y1, b.y1) - max(a.y0, b.y0) > slack


class TopCapAndTotalDepth(unittest.TestCase):
    """R2 (a bar across the top when it is off the ground line) and R3 (TD 50' under the bottom bar)."""

    def test_td_text(self):
        from xsections.render.scales import td_text
        cases = {50.0: "TD 50'", 49.97: "TD 50'", 50.05: "TD 50'", 31.5: "TD 31.5'", 31.46: "TD 31.5'",
                 31.04: "TD 31'", 31.06: "TD 31.1'", 120.0: "TD 120'", 7.3: "TD 7.3'", 0.0: "TD 0'"}
        for v, want in cases.items():
            self.assertEqual(td_text(v), want, v)

    def test_top_cap_only_off_the_ground_line(self):
        # 1 in = 50 ft vertical: 0.04 in is 2 ft. (label, type, station, top above ground, depth)
        hits = [("ON", "Boring", 500.0, 0.0, 30.0), ("UP1.9", "Boring", 1500.0, 1.9, 30.0),
                ("UP2.1", "Boring", 2500.0, 2.1, 30.0), ("DN1.9", "Boring", 3500.0, -1.9, 30.0),
                ("DN15", "Boring", 4500.0, -15.0, 30.0), ("NOBOT", "Boring", 5500.0, 9.0, None)]
        model = flat_model(6000.0, 300.0, hits)
        s = make_settings()
        fig, p, page = drawn(model, s, dpi=72)
        caps = cap_lines(fig)
        self.assertEqual(sorted(float(ln.get_xdata()[0]) for ln in caps), [2500.0, 4500.0])
        by = {h.station: h for h in model.hits}
        bars = {float(ln.get_xdata()[0]): ln for ln in fig.axes[0].lines if ln.get_marker() == "_"}
        self.assertEqual(sorted(bars), [500.0, 1500.0, 2500.0, 3500.0, 4500.0])     # none without a bottom
        for st in (2500.0, 4500.0):                     # the same bar at both ends
            self.assertEqual(sorted(bars[st].get_ydata()), sorted([by[st].top, by[st].bottom]))
        plain = bars[500.0]
        self.assertEqual(list(plain.get_ydata()), [by[500.0].bottom])
        for ln in caps:                                 # identical to the bottom bar
            self.assertEqual((ln.get_marker(), ln.get_markersize(), ln.get_markeredgewidth(), ln.get_color()),
                             ("_", plain.get_markersize(), plain.get_markeredgewidth(), plain.get_color()))
        self.assertAlmostEqual(plain.get_markersize(), F.CROSSBAR_IN * 72)
        # the dotted link from the ground down to a top below it stays
        links = [ln for ln in fig.axes[0].lines if ln.get_linewidth() == 0.6 and list(ln.get_xdata()) == [4500.0, 4500.0]]
        self.assertEqual(len(links), 1)
        self.assertEqual(sorted(links[0].get_ydata()), [by[4500.0].top, 300.0])
        # no caps (and no lines) without the top-to-bottom line
        fig2, _, _ = drawn(model, make_settings(depth_line=False), dpi=72)
        self.assertEqual(cap_lines(fig2), [])
        # the preview decides on paper too (1 in = 50 ft), not on its shrunken drawing
        fig3 = Figure(figsize=(5.0, 2.0), dpi=96)
        F.draw_preview(fig3, model, s, p)
        self.assertEqual(sorted(float(ln.get_xdata()[0]) for ln in cap_lines(fig3)), [2500.0, 4500.0])

    def test_top_cap_by_pixels(self):
        """Rasterised at 300 dpi: a bar about 0.08 in wide at the top of UP3 (3 ft = 0.06 in above the
        ground), none at ON (top on the ground line)."""
        hits = [("ON", "Boring", 1000.0, 0.0, 30.0), ("UP3", "Boring", 3000.0, 3.0, 30.0)]
        model = flat_model(4000.0, 300.0, hits)
        fig, p, page = drawn(model, make_settings(), dpi=300)
        rgb = np.asarray(fig.canvas.buffer_rgba())[..., :3].astype(int)
        H = rgb.shape[0]
        ax = fig.axes[0]

        def dark_run(station, z):
            x, y = ax.transData.transform((station, z))
            row, col = H - int(round(y)), int(round(x))
            best = 0
            for dy in (-2, -1, 0, 1, 2):                   # the bar is ~3 px thick at 300 dpi
                line = rgb[row + dy, col - 30:col + 31].sum(axis=1) < 200
                best = max(best, int(line.sum()))
            return best

        up3 = model.hits[1]
        self.assertGreaterEqual(dark_run(3000.0, up3.top), round(F.CROSSBAR_IN * 300) - 4)   # the cap
        self.assertLessEqual(dark_run(3000.0, up3.top - 1.5), 6)          # below it: the line only
        self.assertLessEqual(dark_run(1000.0, model.hits[0].top - 1.5), 6)   # ON: the line only, no cap

    def test_td_labels_under_the_bottom_bar(self):
        model = make_model(td=True)
        s = make_settings()
        fig, p, page = drawn(model, s)
        tds = td_texts(fig)
        drawn_hits = [h for h in model.hits if h.bottom is not None]
        self.assertEqual(sorted(t.get_text() for t in tds), sorted(f"TD {h.total_depth:g}'" for h in drawn_hits))
        r = fig.canvas.get_renderer()
        ax = fig.axes[0]
        for t in tds:
            self.assertEqual((t.get_fontsize(), t.get_rotation(), t.get_ha(), t.get_va()), (6.5, 0.0, "center", "top"))
            h = next(h for h in drawn_hits if t.get_text() == f"TD {h.total_depth:g}'")
            bb = t.get_window_extent(r)
            bar_y = ax.transData.transform((h.station, h.bottom))[1]
            gap = (bar_y - bb.y1) / fig.dpi
            self.assertGreaterEqual(gap, F.TD_GAP_IN - 0.005, t.get_text())      # just below the bar
            self.assertLessEqual(gap, F.TD_GAP_IN + F.TD_ROW_IN * 2 + 0.01, t.get_text())
            # centred on the station (moved in just enough to stay TD_EDGE_IN inside the frame near its ends)
            want = clamp_centre(h.station / s.h_scale, bb.width / fig.dpi, page.plot_w, TD_EDGE_IN)
            got = ((bb.x0 + bb.x1) / 2 - ax.get_window_extent().x0) / fig.dpi
            self.assertAlmostEqual(got, want, delta=0.005, msg=t.get_text())
            # B-1 is 150 ft from the start and B-5 120 ft from the end (0.15 and 0.12 in)
            self.assertEqual(abs(want - h.station / s.h_scale) > 1e-9, h.label in ("B-1", "B-5"), h.label)
        self.assertIn("TD = total depth.", " ".join(texts_of(fig)))
        fig2, _, _ = drawn(model, make_settings(td_label=False))
        self.assertEqual(td_texts(fig2), [])
        self.assertNotIn("TD = total depth", " ".join(texts_of(fig2)))
        fig3, _, _ = drawn(make_model(), s)                   # no total depth known: no label
        self.assertEqual(td_texts(fig3), [])

    def test_td_labels_stagger_and_never_overlap(self):
        # three explorations 10 and 20 ft apart (0.01 and 0.02 in at 1 in = 1,000 ft) and a pair 40 ft
        # apart, each group with its bottoms level
        hits = [("B-0", "Boring", 2000.0, 0.0, 40.0), ("B-1", "Boring", 2010.0, 0.0, 40.0),
                ("B-2", "Boring", 2030.0, 0.0, 40.0), ("W-1", "Boring", 2600.0, 0.0, 30.0),
                ("W-2", "Boring", 2640.0, 0.0, 30.0)]
        model = flat_model(4000.0, 300.0, hits, td=True)
        s = make_settings()
        fig, p, page = drawn(model, s, dpi=150)
        r = fig.canvas.get_renderer()
        tds = td_texts(fig)
        self.assertEqual(len(tds), 5)
        boxes = [(t.get_text(), t.get_window_extent(r)) for t in tds]
        for i, (ta, a) in enumerate(boxes):
            for tb, b in boxes[i + 1:]:
                self.assertFalse(overlaps(a, b), f"{ta!r} overlaps {tb!r}")
        ax = fig.axes[0]
        drops = []
        for t, (_, bb) in zip(tds, boxes):
            cx = (bb.x0 + bb.x1) / 2                   # (bottoms are level in each group: any member will do)
            h = min(model.hits, key=lambda h: abs(ax.transData.transform((h.station, 0))[0] - cx))
            bar_y = ax.transData.transform((h.station, h.bottom))[1]
            drops.append(round(((bar_y - bb.y1) / fig.dpi - F.TD_GAP_IN) / F.TD_ROW_IN, 2))
        self.assertEqual(sorted(drops), [0.0, 0.0, 1.0, 1.0, 2.0])       # the B cluster takes three rows
        frame = ax.get_window_extent()
        for text, b in boxes:
            self.assertTrue(frame.x0 - 0.5 <= b.x0 and b.x1 <= frame.x1 + 0.5 and b.y0 >= frame.y0, text)
        self.assertEqual(p.warnings, [])
        # a fourth label at the same spot has no free row: left out, and the plan says so
        crowd = [(f"C-{i}", "Boring", 2000.0 + i, 0.0, 40.0) for i in range(4)]
        model = flat_model(4000.0, 300.0, crowd, td=True)
        fig, p, page = drawn(model, s, dpi=150)
        self.assertEqual(len(td_texts(fig)), 3)
        self.assertTrue(any(w.startswith("No room for the TD label of C-3") for w in p.warnings), p.warnings)

    def test_td_labels_never_hide_a_bar(self):
        """B's label would sit on C's bottom bar (1 ft lower, 15 ft along): it drops a row instead. The
        white halo lets a label cross a neighbour's line, never hide where a line ends."""
        hits = [("A", "Boring", 1000.0, 0.0, 40.0), ("B", "Boring", 1030.0, 0.0, 25.0),
                ("C", "Boring", 1045.0, 0.0, 26.0), ("D", "Boring", 1400.0, -9.0, 20.0),
                ("E", "Boring", 1420.0, 0.0, 8.0)]            # E's label would cover D's top cap at 291 ft
        model = flat_model(2000.0, 300.0, hits, td=True)
        s = make_settings(h_scale=200.0, v_scale=20.0)
        fig, p, page = drawn(model, s, dpi=150)
        ax = fig.axes[0]
        r = fig.canvas.get_renderer()
        bars = [(ln, float(x), float(y)) for ln in ax.lines if ln.get_marker() == "_"
                for x, y in zip(ln.get_xdata(), ln.get_ydata())]
        self.assertEqual(len(bars), 6)                             # five bottoms and D's top cap
        half_w = F.CROSSBAR_IN * fig.dpi / 2
        tds = td_texts(fig)
        self.assertEqual(len(tds), 5)
        for t in tds:
            bb = t.get_window_extent(r)
            for _, x, y in bars:
                px, py = ax.transData.transform((x, y))
                hit = bb.x0 < px + half_w and px - half_w < bb.x1 and bb.y0 < py < bb.y1
                self.assertFalse(hit, f"{t.get_text()} covers the bar at {x:g}, {y:g}")
        halos = [a for a in ax.texts if a.get_gid() == F.TD_HALO_GID]
        self.assertEqual(sorted(a.get_text() for a in halos), sorted(t.get_text() for t in tds))
        self.assertTrue(all(a.get_zorder() < t.get_zorder() for a in halos for t in tds))

    def test_td_label_at_the_frame_edge_stays_inside(self):
        model = flat_model(3000.0, 300.0, [("A-0", "Boring", 0.0, 0.0, 25.0), ("A-1", "Boring", 3000.0, 0.0, 25.0)],
                           td=True)
        fig, p, page = drawn(model, make_settings())
        frame = fig.axes[0].get_window_extent()
        r = fig.canvas.get_renderer()
        tds = td_texts(fig)
        self.assertEqual(len(tds), 2)
        for t in tds:
            bb = t.get_window_extent(r)
            # moved in, and kept clear of the frame line (not just touching it)
            self.assertGreaterEqual(bb.x0 - frame.x0, (TD_EDGE_IN - 0.005) * fig.dpi, t.get_text())
            self.assertGreaterEqual(frame.x1 - bb.x1, (TD_EDGE_IN - 0.005) * fig.dpi, t.get_text())

    def test_td_label_by_the_frame_by_pixels(self):
        """Rasterised at 300 dpi: white paper between the moved-in label's ink and the frame line."""
        model = flat_model(3000.0, 300.0, [("END", "Boring", 2995.0, 0.0, 35.0)], td=True)
        fig, p, page = drawn(model, make_settings(), dpi=300)
        rgb = np.asarray(fig.canvas.buffer_rgba())[..., :3].astype(int)
        H = rgb.shape[0]
        t = td_texts(fig)[0]
        bb = t.get_window_extent(fig.canvas.get_renderer())
        frame = fig.axes[0].get_window_extent()
        rows = slice(H - int(bb.y1), H - int(bb.y0))
        inner = int(round(frame.x1 - F.FRAME_LW / 72 * 300 / 2)) - 1         # the frame line's inner edge
        ink = np.flatnonzero((rgb[rows, int(bb.x0):inner].sum(axis=2) < 300).any(axis=0))
        self.assertTrue(ink.size)
        gap_px = inner - (int(bb.x0) + int(ink.max()))
        self.assertGreaterEqual(gap_px, 0.02 * 300, gap_px)                  # at least 0.02 in of paper

    def test_td_label_keeps_off_a_neighbours_label_and_the_ground(self):
        """The reviewer's bluff: BLUFF-TOP (10 ft deep) and BLUFF-TOE 150 ft on, 27 ft lower. At 1 in =
        1,000 / 50 ft the TD label cannot clear the bluff face but no longer runs under BLUFF-TOE's name;
        where it crosses the ground line, the ground is drawn over its halo (no gap in the ground)."""
        from tests.test_scales import BluffModel
        from xsections.render.scales import td_labels
        model = BluffModel.model()
        s = make_settings()
        fig, p, page = drawn(model, s, dpi=150)
        r = fig.canvas.get_renderer()
        ax = fig.axes[0]
        td = [t for t in td_texts(fig) if t.get_text() == "TD 10'"]
        self.assertEqual(len(td), 1)
        bb = td[0].get_window_extent(r)
        toe = [a for a in label_annotations(fig, {"BLUFF-TOE"})][0].get_window_extent(r)
        self.assertFalse(overlaps(bb, toe), (bb, toe))
        ground = [ln for ln in ax.lines if ln.get_linewidth() == F.GROUND_LW][0]
        halo = [a for a in ax.texts if a.get_gid() == F.TD_HALO_GID][0]
        self.assertLess(halo.get_zorder(), ground.get_zorder())
        self.assertLess(ground.get_zorder(), td[0].get_zorder())
        # the drawing and the plan agree on the row (auto z makes room for it)
        (hit, reach), _ = td_labels(model.hits, s, p.plot_length, model.ground)
        lowest = ax.transData.inverted().transform((0.0, bb.y1))[1] - (F.TD_TEXT_H_IN * s.v_scale)
        self.assertAlmostEqual(lowest, reach, delta=0.02 * s.v_scale)

    def test_match_note_clears_the_td_labels(self):
        """Tiled at 1 in = 100 / 10 ft: a well 4 ft past match line 13+00 has its TD label at mid-height,
        where the match note used to go. The note slides along its line to clear it (and every tick and
        label), and stays 0.1 in inside the frame."""
        hits = [("MW-40", "Monitoring Well", 1304.0, 0.0, 24.5), ("MW-39", "Monitoring Well", 1290.0, 0.0, 40.0),
                ("B-9", "Boring", 2497.0, 0.0, 25.0)]
        model = flat_model(4600.0, 290.0, hits, td=True)
        s = make_settings(h_scale=100.0, v_scale=10.0, allowed_sheets=["tabloid"], z_mode="manual",
                          z_min=230.0, z_max=300.0)
        for index in (0, 1):
            fig, p, page = drawn(model, s, index=index, dpi=100)
            self.assertTrue(p.fits and len(p.pages) > 1)
            ax = fig.axes[0]
            r = fig.canvas.get_renderer()
            frame = ax.get_window_extent()
            notes = [a for a in ax.texts if a.get_text().startswith("MATCH LINE")]
            self.assertTrue(notes)
            marks = td_texts(fig) + label_annotations(fig, {"MW-40", "MW-39", "B-9"})
            self.assertTrue(td_texts(fig))
            for note in notes:
                nb = note.get_window_extent(r)
                self.assertGreaterEqual(nb.y0, frame.y0 + 0.1 * fig.dpi - 1.0)
                self.assertLessEqual(nb.y1, frame.y1 - 0.1 * fig.dpi + 1.0)
                for m in marks:
                    self.assertFalse(overlaps(nb, m.get_window_extent(r)), (index, m.get_text()))

    def test_auto_z_leaves_room_below_the_labels(self):
        # bottoms at 250.5 ft: without labels the grid would stop at 200 ft (250.5 - 1 in x 50 = 200.5)
        hits = [("B-1", "Boring", 1000.0, 0.0, 49.5), ("B-2", "Boring", 1010.0, 0.0, 49.5),
                ("B-3", "Boring", 1020.0, 0.0, 49.5)]
        s = make_settings()
        plain = plan(flat_model(3000.0, 300.0, hits), s)
        self.assertEqual(plain.z_min, 200.0)
        model = flat_model(3000.0, 300.0, hits, td=True)
        fig, p, page = drawn(model, s)
        self.assertEqual(p.z_min, 150.0)
        self.assertEqual(p.lowest_what, "the bottom of B-1")        # the readout still names the data
        r = fig.canvas.get_renderer()
        frame = fig.axes[0].get_window_extent()
        self.assertEqual(len(td_texts(fig)), 3)
        lowest = min(t.get_window_extent(r).y0 for t in td_texts(fig))
        self.assertGreaterEqual((lowest - frame.y0) / fig.dpi, s.below_in - 0.01)   # below_in under the labels too

    def test_manual_range_never_draws_a_label_outside(self):
        hits = [("B-1", "Boring", 1000.0, 0.0, 48.0)]             # bottom 252 ft; its label reaches 245.5 ft
        model = flat_model(3000.0, 300.0, hits, td=True)
        fig, p, page = drawn(model, make_settings(z_mode="manual", z_min=250.0, z_max=350.0))
        self.assertEqual(td_texts(fig), [])
        self.assertTrue(any(w.startswith("TD labels below the manual minimum of 250 ft are left out (B-1). "
                                         "Lower it to 200 ft") for w in p.warnings), p.warnings)
        fig, p, page = drawn(model, make_settings(z_mode="manual", z_min=200.0, z_max=350.0))
        self.assertEqual(len(td_texts(fig)), 1)
        self.assertFalse(any("TD" in w for w in p.warnings))

    def test_preview_draws_them_too(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        model = make_model(td=True)
        s = make_settings()
        p = plan(model, s)
        fig = Figure(figsize=(6.0, 2.5), dpi=96)
        FigureCanvasAgg(fig)
        F.draw_preview(fig, model, s, p)
        fig.canvas.draw()
        tds = td_texts(fig)
        self.assertTrue(tds)
        self.assertTrue(all(t.get_fontsize() >= F.TD_PT * 0.85 - 1e-9 for t in tds))
        self.assertTrue(cap_lines(fig))
        frame = fig.axes[0].get_window_extent()
        r = fig.canvas.get_renderer()
        for t in tds:
            self.assertGreaterEqual(t.get_window_extent(r).y0, frame.y0 - 0.5)

    def test_sources_note(self):
        model = make_model(td=True)
        p = plan(model, make_settings())
        page = p.pages[0]

        def note3(**over):
            return F.notes_text(model, make_settings(**over), p, page)[1][0]

        both = dict(top_field="ExploElev", bottom_elev_field="BotElev", depth_field="ExploDepth")
        self.assertIn("Tops: ExploElev where available, otherwise LIDAR at the exploration. Bottoms: BotElev where "
                      "available, otherwise top minus ExploDepth. TD = total depth.", note3(**both))
        self.assertIn("Tops: LIDAR at the exploration. Bottoms: top minus ExploDepth.",
                      note3(top_mode="dem", top_field="ExploElev", depth_field="ExploDepth", td_label=False))
        self.assertIn("Tops: ExploElev. Bottoms: BotElev. TD = total depth.",
                      note3(top_mode="field", top_field="ExploElev", bottom_elev_field="BotElev"))
        self.assertNotIn("Tops:", note3(depth_line=False, **both))
        self.assertNotIn("TD = total depth", note3(td_label=False, **both))

    def test_ground_only_sheet(self):
        model = make_model(hits=[])
        model.has_explorations = False
        s = make_settings()
        fig, p, page = drawn(model, s)
        note3 = F.notes_text(model, s, p, page)[1][0]
        self.assertEqual(note3, "Ground: LIDAR_DEM_5ft (NAVD88), sampled every 5 ft.")
        self.assertIn("NO DEM DATA", texts_of(fig))


class DrawPreviewTest(unittest.TestCase):
    def test_letterbox_keeps_ve(self):
        model = make_model()
        s = make_settings()
        p = plan(model, s)
        for size in ((9.0, 3.0), (5.0, 6.0)):
            fig = Figure(figsize=size, dpi=96)
            F.draw_preview(fig, model, s, p)
            ax = fig.axes[0]
            pos = ax.get_position()
            w_in, h_in = pos.width * size[0], pos.height * size[1]
            x0, x1 = ax.get_xlim()
            z0, z1 = ax.get_ylim()
            ft_per_in_x, ft_per_in_z = (x1 - x0) / w_in, (z1 - z0) / h_in
            self.assertAlmostEqual(ft_per_in_x / ft_per_in_z, s.vertical_exaggeration, places=6)
            self.assertEqual((x0, x1), (0.0, p.plot_length))
            fig.canvas.draw()                                          # renders without error

    def test_preview_tiles_and_nofit(self):
        model = make_model(length=4600.0)
        s = make_settings(h_scale=100.0, allowed_sheets=["tabloid"])
        fig = Figure(figsize=(9, 3), dpi=96)
        F.draw_preview(fig, model, s, plan(model, s))
        self.assertTrue(any(t.startswith("MATCH 13+00") for t in texts_of(fig)))
        s2 = make_settings(h_scale=100.0, tile=False)
        p2 = plan(model, s2)
        self.assertFalse(p2.fits)
        fig2 = Figure(figsize=(9, 3), dpi=96)
        F.draw_preview(fig2, model, s2, p2)
        self.assertTrue(any(t.startswith("Does not fit") for t in texts_of(fig2)))


if __name__ == "__main__":
    unittest.main()
