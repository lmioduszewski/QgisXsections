"""Sheet layout options (settings version 3): compact layout, printer edge, notes on/off, fill with grid.
Since version 4 (0.1.2) the compact layout with the grid filled below the section is the default.

The margins are worked out from what is drawn around the frame (scales.margins); every combination is
drawn and checked: the plot still measures exactly to scale, no mark outside the frame overlaps another,
and no ink reaches into the printer edge."""
import dataclasses
import itertools
import json
import math
import os
import shutil
import tempfile
import unittest

from tests.fixtures import CUMBERLAND_AESI, REALDATA, STANDARD_LAYOUT, color_model, start_app

start_app()

import numpy as np                                                       # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg              # noqa: E402
from matplotlib.figure import Figure                                     # noqa: E402
from matplotlib.lines import Line2D                                      # noqa: E402
from matplotlib.patches import Rectangle                                 # noqa: E402
from matplotlib.text import Annotation                                   # noqa: E402

from tests import measure as M                                          # noqa: E402
from tests.test_figure import HITS, flat_model, make_model, make_settings, texts_of   # noqa: E402
from xsections.core.model import SETTINGS_VERSION, Settings, migrate_settings   # noqa: E402
from xsections.render import figure as F                                 # noqa: E402
from xsections.render import scales as S                                 # noqa: E402
from xsections.render.export import export                               # noqa: E402
from xsections.render.scales import margins, plan                        # noqa: E402

OPTIONS = list(itertools.product((False, True), (0.5, 0.3), (True, False), ("off", "below", "both")))
LONG_TITLE = ("Former Northside Manufacturing Facility Remedial Investigation, Operable Unit 2, Groundwater "
              "Monitoring Network for the 2026 Annual Report, prepared for the State Department of Ecology")
LONG_DEM = "Clark_County_2019_LIDAR_bare_earth_DEM_1ft_USft_NAVD88_mosaic_v3_final_reviewed"


def standard(**over):
    """Settings in the standard layout (the defaults up to settings version 3)."""
    return Settings(**{**STANDARD_LAYOUT, **over})


def option_settings(compact, edge, notes, fill, **over):
    return make_settings(compact_layout=compact, edge_margin_in=edge, show_notes=notes, fill_grid=fill, **over)


def tag(compact, edge, notes, fill):
    return f"{'compact' if compact else 'standard'}, edge {edge}, notes {'on' if notes else 'off'}, fill {fill}"


# ----------------------------------------------------------------------------- reference: the layout before v3
OLD_MARGIN = dict(left=1.0, right=1.5, top=1.2, bottom=2.3)


def old_place(W, H, plot_w, plot_h):
    """scales._place as it was before the layout options (MARGIN only)."""
    lo, hi = OLD_MARGIN["left"], max(W - OLD_MARGIN["right"] - plot_w, OLD_MARGIN["left"])
    left = round(min(max((W - plot_w) / 2.0, lo), hi) * 100) / 100
    if left > hi + 1e-9:
        left = math.floor(hi * 100 + 1e-6) / 100
    left = max(left, lo)
    need_h = plot_h + OLD_MARGIN["top"] + OLD_MARGIN["bottom"]
    return left, round((OLD_MARGIN["bottom"] + max(H - need_h, 0.0) / 2.0) * 100) / 100


# ----------------------------------------------------------------------------- marks around the frame
def furniture(fig):
    """(name, box) of the marks around the frame, display pixels: the frame itself, tick labels, axis titles,
    end letters, BEND labels, title, graphic scales (each bar as one box, its labels), notes, legend
    entries, and the match notes inside the frame (their white-halo copies left out)."""
    r = fig.canvas.get_renderer()
    ax = fig.axes[0]
    frame = ax.get_window_extent(r)
    out = [("frame", frame)]

    def add(name, bb):
        if bb.width > 0 and bb.height > 0:
            out.append((name, bb))

    for t in fig.texts:
        if t.get_text():
            add(f"text {t.get_text()[:30]!r}", t.get_window_extent(r))
    bars = {"hbar": [], "vbar": []}
    for a in fig.artists:
        if isinstance(a, Rectangle):
            bb = a.get_window_extent(r)
            bars["hbar" if bb.width > bb.height else "vbar"].append(bb)
        elif isinstance(a, Line2D):
            add("legend swatch", a.get_window_extent(r))
    for name, boxes in bars.items():
        if boxes:
            from matplotlib.transforms import Bbox
            add(name, Bbox.union(boxes))
    seen = set()
    for a in ax.texts:
        if not isinstance(a, Annotation) or not a.get_text():
            continue
        bb = a.get_window_extent(r)
        key = (a.get_text(), round(bb.x0), round(bb.y0))
        if key in seen:                                 # a halo copy under a match note
            continue
        seen.add(key)
        inside = frame.x0 <= bb.x0 and bb.x1 <= frame.x1 and frame.y0 <= bb.y0 and bb.y1 <= frame.y1
        if a.get_text().startswith("MATCH") or not inside:
            add(f"annotation {a.get_text()[:30]!r}", bb)
    for axis, lim in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
        eps = 1e-9 * abs(lim[1] - lim[0])
        for tick in axis.get_major_ticks():
            if not lim[0] - eps <= tick.get_loc() <= lim[1] + eps:
                continue                                # outside the view: never drawn
            for side, lab in (("1", tick.label1), ("2", tick.label2)):
                if lab.get_visible() and lab.get_text():
                    add(f"{axis.axis_name} label{side} {lab.get_text()}", lab.get_window_extent(r))
    add("distance title", ax.xaxis.label.get_window_extent(r))
    return out


def overlapping(boxes, tol=1.0):
    """Pairs of boxes overlapping by more than `tol` px both ways (a match note may sit inside the frame)."""
    bad = []
    for (na, a), (nb, b) in itertools.combinations(boxes, 2):
        if "frame" in (na, nb) and ("MATCH" in na or "MATCH" in nb):
            continue
        if min(a.x1, b.x1) - max(a.x0, b.x0) > tol and min(a.y1, b.y1) - max(a.y0, b.y0) > tol:
            bad.append((na, nb))
    return bad


def draw(model, settings, p, page, dpi=100):
    fig = Figure(dpi=dpi)
    FigureCanvasAgg(fig)
    F.draw_page(fig, model, settings, p, page)
    fig.canvas.draw()
    return fig


def measure_plot(rgb, page, dpi=300, pad_in=0.1):
    """tests.measure on the part of the sheet image around the plot frame (much faster than the whole)."""
    H, pad = rgb.shape[0], int(pad_in * dpi)
    x0, x1 = int(page.plot_left * dpi) - pad, int((page.plot_left + page.plot_w) * dpi) + pad
    y0, y1 = H - int((page.plot_bottom + page.plot_h) * dpi) - pad, H - int(page.plot_bottom * dpi) + pad
    return M.measure(np.ascontiguousarray(rgb[y0:y1, x0:x1]), dpi, 0.1, 0.1, "green")


def ink_in_edge(rgb, edge_in, dpi):
    """Pixels in the strip `edge_in` wide along the paper edge that are not white (count)."""
    k = int(math.floor(edge_in * dpi)) - 1
    strips = (rgb[:k], rgb[-k:], rgb[:, :k], rgb[:, -k:])
    return int(sum((st.min(axis=2) < 250).sum() for st in strips))


# ----------------------------------------------------------------------------- tests
class Margins(unittest.TestCase):
    def test_standard_layout_is_unchanged(self):
        s = standard()
        self.assertEqual(margins(s), OLD_MARGIN)
        self.assertEqual(margins(s), S.MARGIN)
        self.assertEqual(S.notes_min_w(s), S.NOTES_MIN_W)
        self.assertEqual(S.min_page_w(s), S.NOTES_MIN_W + 1.2)
        # pages planned in the standard layout sit exactly where they used to
        cases = [(make_model(), make_settings()),                                   # Letter portrait
                 (make_model(), make_settings(v_scale=100.0)),                      # Letter landscape
                 (flat_model(9000.0, 300.0), make_settings()),                     # Tabloid
                 (make_model(length=4600.0), make_settings(h_scale=100.0, allowed_sheets=["tabloid"]))]   # tiled
        for model, st in cases:
            p = plan(model, st)
            widest = max(pg.plot_w for pg in p.pages)
            for pg in p.pages:
                self.assertEqual((pg.plot_left, pg.plot_bottom), old_place(pg.page_w, pg.page_h, widest, pg.plot_h))

    def test_printer_edge_moves_every_side(self):
        thin = margins(standard(edge_margin_in=0.3))
        for side in ("left", "right", "top", "bottom"):
            self.assertAlmostEqual(thin[side], OLD_MARGIN[side] - 0.2, places=9)
        for compact, notes in ((True, True), (True, False), (False, False)):
            a = margins(Settings(compact_layout=compact, show_notes=notes), (600.0, 700.0))
            b = margins(Settings(compact_layout=compact, show_notes=notes, edge_margin_in=0.3), (600.0, 700.0))
            for side in a:
                self.assertAlmostEqual(b[side], a[side] - 0.2, places=9, msg=(compact, notes, side))
        self.assertEqual(S.edge_in(Settings(edge_margin_in=0.1)), 0.25)       # never closer than 0.25 in
        self.assertEqual(S.edge_in(Settings(edge_margin_in=float("nan"))), 0.5)

    def test_compact_margins_from_the_marks(self):
        s = Settings(compact_layout=True, v_scale=20.0)
        m = margins(s, (600.0, 700.0))
        # top: end-letter row (0.03 + 11 pt) + 0.05 + title row (11 pt) + pad 0.03 + edge 0.5
        self.assertEqual(m["top"], S._up(0.03 + 11 / 72 + 0.05 + 11 / 72 + 0.03 + 0.5))
        self.assertEqual(m["top"], 0.92)
        # bottom: ticks, labels, distance title (23 pt) + 0.06 + scale bar and two note lines + pad + edge
        band = S.bottom_band(s)
        self.assertEqual(band.note_rows, 2)
        self.assertAlmostEqual(band.top, 23 / 72 + 0.06)
        self.assertEqual(m["bottom"], S._up(band.depth + 0.03 + 0.5))
        self.assertEqual(m["bottom"], 1.1)
        # left: ticks + labels ("700") + gap + the elevation title; right: the vertical scale tucked in
        w700 = S.text_width_in("700", 7.0)
        self.assertEqual(m["left"], S._up((3 + 2 + 4 + 8 + 1.5) / 72 + w700 + 0.03 + 0.5))
        self.assertEqual(m["right"], S._up((3 + 2) / 72 + w700 + 0.08 + 0.1 + S.text_width_in("20 ft", 6.3)
                                           + 0.03 + 0.5))
        for side in m:
            self.assertLess(m[side], OLD_MARGIN[side], side)
        # five-digit elevations need more room; the widest label of the range counts
        wide = margins(s, (11950.0, 12100.0))
        self.assertGreater(wide["left"], m["left"])
        self.assertEqual(margins(s), margins(s, (99000.0, 99980.0)))          # no range: five digits assumed
        # notes beside the bar: leaving them off saves width, not height
        off = margins(Settings(compact_layout=True, show_notes=False, v_scale=20.0), (600.0, 700.0))
        self.assertEqual(off, m)
        self.assertLess(S.notes_min_w(Settings(compact_layout=True, show_notes=False)),
                        S.notes_min_w(Settings(compact_layout=True)))

    def test_standard_without_notes(self):
        m = margins(standard(show_notes=False))
        for side in ("left", "right", "top"):
            self.assertEqual(m[side], OLD_MARGIN[side])
        # the bar 0.64 in under the frame, "HORIZONTAL" 0.05 in under it (5.3 pt), pad, edge
        self.assertEqual(m["bottom"], S._up(0.64 + 0.05 + 5.3 / 72 + 0.03 + 0.5))
        self.assertEqual(m["bottom"], 1.3)
        self.assertLess(S.notes_min_w(standard(show_notes=False)), S.NOTES_MIN_W / 2)

    def test_legend_rows_add_room(self):
        types = [f"Exploration type {i}" for i in range(12)]
        for st in (Settings(compact_layout=True), standard(show_notes=False)):
            plain = margins(st, (600.0, 700.0))
            more = margins(st, (600.0, 700.0), types)
            self.assertGreater(more["bottom"], plain["bottom"])
            band = S.bottom_band(st, types)
            self.assertGreater(len(band.legend), 1)
        self.assertEqual(margins(standard(), None, types), OLD_MARGIN)                    # standard: unchanged

    def test_standard_right_margin_holds_the_vertical_scale_label(self):
        # MARGIN's right side holds the vertical scale's top label up to "100 ft" (it ends at the printer edge)
        for v in (5.0, 20.0, 50.0, 100.0, 500.0):
            for edge in (0.5, 0.3):
                self.assertAlmostEqual(margins(standard(v_scale=v, edge_margin_in=edge))["right"],
                                       OLD_MARGIN["right"] + edge - 0.5, places=9, msg=(v, edge))
        # "1,000 ft" is wider: the margin grows to hold it inside the printer edge, with the usual pad and slack
        for edge in (0.5, 0.3):
            for notes in (True, False):
                m = margins(standard(v_scale=1000.0, edge_margin_in=edge, show_notes=notes))
                w = S.text_width_in("1,000 ft", S.SCALE_LABEL_PT)
                self.assertEqual(m["right"], S._up(0.64 + 0.1 + w * S.RASTER_SLACK + 0.03 + edge))
                self.assertGreater(m["right"], OLD_MARGIN["right"] + edge - 0.5)

    def test_fill_mode(self):
        self.assertEqual(S.fill_mode(Settings()), "below")                     # the default since version 4
        self.assertEqual(S.fill_mode(standard()), "off")
        self.assertEqual(S.fill_mode(Settings(fill_grid="both")), "both")
        self.assertEqual(S.fill_mode(Settings(fill_grid="sideways")), "off")


class Fill(unittest.TestCase):
    def model(self):
        return flat_model(4500.0, 200.0)               # ground at 200 ft, no explorations

    def test_off_below_both(self):
        m = self.model()
        base = plan(m, make_settings(below_in=0.0))  # 150..300? auto limits around 200 ft
        self.assertEqual(base.pages[0].sheet_name, "Letter 11 × 8.5 in, landscape")
        n = S.fill_majors(base.pages[0].plot_h, 8.5, make_settings(), 50.0, OLD_MARGIN)
        self.assertGreaterEqual(n, 2)
        below = plan(m, make_settings(below_in=0.0, fill_grid="below"))
        self.assertEqual((below.z_min, below.z_max), (base.z_min - n * 50.0, base.z_max))
        both = plan(m, make_settings(below_in=0.0, fill_grid="both"))
        self.assertEqual((both.z_min, both.z_max), (base.z_min - (n - n // 2) * 50.0, base.z_max + (n // 2) * 50.0))
        self.assertGreaterEqual(base.z_min - both.z_min, both.z_max - base.z_max)     # the larger half below
        for p in (below, both):
            pg = p.pages[0]
            self.assertAlmostEqual(pg.plot_h, base.pages[0].plot_h + n)
            self.assertLessEqual(pg.plot_h + OLD_MARGIN["top"] + OLD_MARGIN["bottom"], pg.page_h + 1e-9)
            self.assertTrue(p.message.endswith(f"; plot {pg.plot_w:.2f} × {pg.plot_h:.2f} in."), p.message)   # as filled

    def test_compact_layout_fills_more(self):
        m = self.model()
        std = plan(m, make_settings(below_in=0.0, fill_grid="both"))
        comp = plan(m, make_settings(below_in=0.0, fill_grid="both", compact_layout=True, edge_margin_in=0.3))
        self.assertGreater(comp.pages[0].plot_h, std.pages[0].plot_h)
        mg = margins(make_settings(compact_layout=True, edge_margin_in=0.3), (comp.z_min, comp.z_max))
        pg = comp.pages[0]
        self.assertLessEqual(pg.plot_h + mg["top"] + mg["bottom"], pg.page_h + 1e-9)
        self.assertGreater(pg.plot_h + mg["top"] + mg["bottom"] + 1.0, pg.page_h)    # less than a major left

    def test_never_on_a_custom_page(self):
        for fill in ("below", "both"):
            p = plan(self.model(), make_settings(sheet="custom", below_in=0.0, fill_grid=fill))
            base = plan(self.model(), make_settings(sheet="custom", below_in=0.0))
            self.assertEqual((p.z_min, p.z_max), (base.z_min, base.z_max))

    def test_never_with_a_manual_range(self):
        # the defaults fill the sheet below the section in Auto, but a manual range is drawn as typed (rounded to
        # the major grid), on one sheet and tiled, whatever the fill choice
        m = self.model()
        self.assertLess(plan(m, Settings(below_in=0.0)).z_min, 200.0)
        for over, sheets in ((dict(), 1), (dict(h_scale=200.0, allowed_sheets=["tabloid"]), 2)):
            for fill in ("below", "both"):
                with self.subTest(fill=fill, **over):
                    s = Settings(z_mode="manual", z_min=120.0, z_max=260.0, fill_grid=fill, **over)
                    p = plan(m, s)
                    self.assertTrue(p.fits, p.message)
                    self.assertEqual(len(p.pages), sheets)
                    self.assertEqual((p.z_min, p.z_max), (100.0, 300.0))
                    self.assertTrue(all(pg.plot_h == 4.0 for pg in p.pages))
                    self.assertEqual(p.warnings, [])
                    self.assertEqual(plan(m, dataclasses.replace(s, fill_grid="off")), p)


LAYOUT_KEYS = ("compact_layout", "edge_margin_in", "show_notes", "fill_grid")


def layout_of(s):
    return tuple(getattr(s, k) for k in LAYOUT_KEYS)


def v3_json(**values):
    """Settings as 0.1.1 saved them (version 3): every key, the layout options at that version's defaults
    (the standard layout) unless `values` sets them."""
    data = dataclasses.asdict(standard(**values))
    data["version"] = 3
    return json.dumps(data)


V2_ONLY_HAD = ("fill_below",)                               # 0.1.0's keys that 0.1.1 dropped or replaced
SINCE_V3 = LAYOUT_KEYS + ("show_bends",)                    # keys 0.1.0 never stored


def v2_json(fill_below=False, **values):
    """Settings as 0.1.0 saved them (version 2): every key it had, which includes the fill_below checkbox (False,
    its default, unless ticked) but none of the later options."""
    data = dataclasses.asdict(Settings(**values))
    for key in SINCE_V3:
        del data[key]
    data["fill_below"] = fill_below
    data["version"] = 2
    return json.dumps(data)


class SettingsVersions(unittest.TestCase):
    """Version 4 (0.1.2) makes the compact layout and the grid filled below the section the defaults. Stored values
    are kept as they are: a version 3 project stores every layout option and keeps its look; a key older settings
    do not have takes the new default."""

    def test_defaults(self):
        s = Settings()
        self.assertEqual(layout_of(s), (True, 0.5, True, "below"))
        self.assertEqual(s.version, SETTINGS_VERSION)
        self.assertEqual(SETTINGS_VERSION, 7)                       # 5 (0.2.0), 6 (0.3.3) and 7 (0.3.4) add keys
        self.assertFalse(hasattr(s, "fill_below"))
        self.assertEqual(Settings.from_json(""), s)                             # nothing stored: the defaults

    def test_version_3_keeps_its_look(self):
        model = make_model(td=True)
        for layout in (STANDARD_LAYOUT,                                          # 0.1.1's defaults
                       dict(compact_layout=True, edge_margin_in=0.3, show_notes=False, fill_grid="both")):
            with self.subTest(**layout):
                text = v3_json(label_field="ExploName", tolerance_ft=80.0, **layout)
                s = Settings.from_json(text)
                self.assertEqual((s.version, s.tolerance_ft), (SETTINGS_VERSION, 80.0))
                saved = standard(label_field="ExploName", tolerance_ft=80.0, **layout)
                self.assertEqual(s, saved)                                       # every value as stored
                self.assertEqual(plan(model, s), plan(model, saved))             # the same sheet
        # 0.1.1's default sheet stays as it was: standard margins, no fill, the page where it always was (the new
        # defaults would fill it and move it)
        s = Settings.from_json(v3_json(label_field="ExploName", v_scale=100.0))
        self.assertEqual(layout_of(s), (False, 0.5, True, "off"))
        self.assertEqual(margins(s), OLD_MARGIN)
        p = plan(model, s)
        pg = p.pages[0]
        self.assertEqual((pg.plot_left, pg.plot_bottom), old_place(pg.page_w, pg.page_h, pg.plot_w, pg.plot_h))
        new = plan(model, Settings(label_field="ExploName", v_scale=100.0))
        self.assertLess(new.z_min, p.z_min)
        self.assertNotEqual(new.pages[0].plot_bottom, pg.plot_bottom)

    def test_version_2_gets_the_new_defaults(self):
        # 0.1.0 stored no layout option, so a 0.1.0 project gets the new defaults: the compact layout and the grid
        # filled below, whether or not its fill checkbox was ticked (ticked meant "below"; unticked was simply
        # 0.1.0's default), and the same sheet as a new project with the same values
        model = make_model(td=True)
        for old in (False, True):
            with self.subTest(fill_below=old):
                s = Settings.from_json(v2_json(fill_below=old, label_field="ExploName", tolerance_ft=80.0))
                self.assertEqual(layout_of(s), (True, 0.5, True, "below"))
                self.assertEqual((s.tolerance_ft, s.version, s.show_bends), (80.0, SETTINGS_VERSION, True))
                new = Settings(label_field="ExploName", tolerance_ft=80.0)
                self.assertEqual(s, new)
                self.assertEqual(plan(model, s), plan(model, new))
        self.assertEqual(migrate_settings({"fill_below": True, "fill_grid": "both"})["fill_grid"], "both")
        for old in (True, False):
            self.assertNotIn("fill_below", migrate_settings({"fill_below": old}))
        self.assertNotIn("fill_grid", migrate_settings({"fill_below": False}))     # the default applies
        s = Settings.from_json(json.dumps({"version": 1, "bottom_field": "ExploDepth"}))   # no fill key at all
        self.assertEqual((layout_of(s), s.depth_field), (layout_of(Settings()), "ExploDepth"))


class EveryCombination(unittest.TestCase):
    """Each combination of (compact, printer edge, notes, fill) on Letter landscape, Letter portrait and a
    tiled Tabloid set: the plan fits as expected; the exported PNG measures 300 px per inch on both axes
    and the frame its exact size; no marks around the frame overlap; no ink in the printer edge."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="xsec_layout_")
        cls.cases = {
            # name: (model, extra settings, page size, sheet index to check)
            "letter landscape": (make_model(td=True), dict(v_scale=100.0, title="Letter landscape test",
                                                           allowed_sheets=["letter"]), (11.0, 8.5), [0]),
            # 7 in tall: portrait with any margins (landscape has 6.88 in at most); a title line too long for
            # the sheet (cut short in both layouts, lifted clear of the end letters in the standard one)
            "letter portrait": (make_model(), dict(title=LONG_TITLE, allowed_sheets=["letter"]), (8.5, 11.0), [0]),
            "tiled tabloid": (make_model(length=4600.0, td=True), dict(h_scale=100.0, v_scale=100.0,
                                                                       allowed_sheets=["tabloid"]), (17.0, 11.0), [1]),
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def check_case(self, name):
        model, extra, size, indexes = self.cases[name]
        base_h = None
        for compact, edge, notes, fill in OPTIONS:
            with self.subTest(case=name, options=tag(compact, edge, notes, fill)):
                s = option_settings(compact, edge, notes, fill, **extra)
                p = plan(model, s)
                self.assertTrue(p.fits, p.message)
                self.assertTrue(all((pg.page_w, pg.page_h) == size for pg in p.pages), p.message)
                if name == "tiled tabloid":
                    self.assertGreater(len(p.pages), 2)
                mg = margins(s, (p.z_min, p.z_max), ())
                for pg in p.pages:                     # inside the margins, to scale
                    self.assertGreaterEqual(pg.plot_left, mg["left"] - 1e-9)
                    self.assertLessEqual(pg.plot_left + pg.plot_w, pg.page_w - mg["right"] + 1e-9)
                    self.assertGreaterEqual(pg.plot_bottom, mg["bottom"] - 1e-9)
                    self.assertLessEqual(pg.plot_bottom + pg.plot_h, pg.page_h - mg["top"] + 1e-9)
                    self.assertAlmostEqual(pg.plot_h * s.v_scale, p.z_max - p.z_min, places=6)
                if fill == "off" and not compact and edge == 0.5 and notes:
                    base_h = p.pages[0].plot_h
                if fill != "off" and base_h is not None:
                    self.assertGreaterEqual(p.pages[0].plot_h, base_h)
                for i in indexes:
                    page = p.pages[i]
                    one = dataclasses.replace(p, pages=[page])
                    out = export(model, s, one, os.path.join(self.dir, "sheet.png"), "png", 300)
                    rgb, _ = M.load_png(out[0])
                    m = measure_plot(rgb, page)
                    for axis, inches in (("x", page.plot_w), ("y", page.plot_h)):
                        self.assertAlmostEqual(m[axis]["frame_px"], inches * 300, delta=1.0, msg=f"{axis} frame")
                        self.assertAlmostEqual(m[axis]["px_per_in"], 300.0, delta=0.05, msg=f"{axis} px/in")
                    self.assertEqual(ink_in_edge(rgb, edge, 300), 0, "ink in the printer edge")
                    fig = draw(model, s, p, page)
                    self.assertEqual(overlapping(furniture(fig)), [])
                    t = texts_of(fig)
                    if compact and notes:
                        sizes = [x.get_fontsize() for x in fig.texts if x.get_text().startswith(("H 1 in", "Ground:"))]
                        self.assertEqual(len(sizes), 2)
                        self.assertTrue(all(z in F.NOTE_SIZES for z in sizes), sizes)
                    if notes:
                        self.assertTrue(any(x.startswith("Ground:") for x in t))
                    else:
                        self.assertFalse(any(x.startswith("Ground:") or "1:" in x for x in t))
                    self.assertEqual(t.count("Elevation (ft NAVD88)"), 1 if compact else 2)
                    if page.tile_count > 1:
                        self.assertIn(F.title_text(s, page), t)
                        self.assertIn(f"(SHEET {page.tile_index} OF {page.tile_count})", F.title_text(s, page))
                        self.assertTrue(any(x.startswith("MATCH LINE") for x in t))

    def test_letter_landscape(self):
        self.check_case("letter landscape")

    def test_letter_portrait(self):
        self.check_case("letter portrait")

    def test_tiled_tabloid(self):
        self.check_case("tiled tabloid")


class CompactMarks(unittest.TestCase):
    def test_one_line_title_and_inline_end_letters(self):
        model = make_model()
        s = make_settings(compact_layout=True, title="Site X")
        p = plan(model, s)
        fig = draw(model, s, p, p.pages[0])
        t = texts_of(fig)
        self.assertIn("CROSS SECTION A–A′", t)
        self.assertIn(" · Site X", t)
        self.assertIn(" (W)", t)
        self.assertIn(" (E)", t)
        r = fig.canvas.get_renderer()
        by = {x.get_text(): x.get_window_extent(r) for x in fig.texts + fig.axes[0].texts}
        head, sub = by["CROSS SECTION A–A′"], by[" · Site X"]
        self.assertAlmostEqual(head.y0 + 11 * 0.24 * fig.dpi / 72, sub.y0 + 9 * 0.24 * fig.dpi / 72, delta=1.0)
        self.assertLessEqual(head.x1, sub.x0 + 1.0)
        frame = fig.axes[0].get_window_extent(r)
        a, w = by["A"], by[" (W)"]
        self.assertAlmostEqual(a.x0, frame.x0, delta=1.0)               # "A (W)" starts over the start
        self.assertLessEqual(a.x1, w.x0 + 1.0)
        self.assertGreater(a.y0, frame.y1)                               # just above the frame
        self.assertLess(a.y0, frame.y1 + 0.06 * fig.dpi)
        end = by["A′"], by[" (E)"]
        x_end = fig.axes[0].transData.transform((model.length, 0))[0]
        self.assertAlmostEqual(end[1].x1, x_end, delta=1.0)              # "A′ (E)" ends over the end
        self.assertGreater(sub.y0, a.y1)                                 # the title row over the letters

    def test_notes_beside_the_scale_bar(self):
        model = make_model(td=True)
        model.dem_name = "Clark_County_2019_LIDAR_bare_earth_DEM_1ft_USft_NAVD88_mosaic_v3_final_reviewed"
        for size in ((11.0, 8.5), (8.5, 11.0)):
            s = make_settings(compact_layout=True, v_scale=100.0 if size[0] > 10 else 50.0)
            p = plan(model, s)
            page = p.pages[0]
            self.assertEqual((page.page_w, page.page_h), size)
            fig = draw(model, s, p, page)
            r = fig.canvas.get_renderer()
            notes = [x for x in fig.texts if x.get_text().startswith(("H 1 in", "Ground:"))]
            self.assertEqual(len(notes), 2)
            self.assertTrue(all(F.NOTE_MIN_PT <= x.get_fontsize() <= F.NOTE_COMPACT_PT for x in notes))
            bar = [a.get_window_extent(r) for a in fig.artists if isinstance(a, Rectangle)
                   and a.get_window_extent(r).width > a.get_window_extent(r).height]
            right_of_bar = max(b.x1 for b in bar)
            band_top = max(b.y1 for b in bar)
            for x in notes:
                bb = x.get_window_extent(r)
                self.assertGreater(bb.x0, right_of_bar)                 # beside the bar, not under it
                self.assertLessEqual(bb.x1, (page.page_w - 0.5) * fig.dpi)
                self.assertGreater(bb.y1, band_top - 0.3 * fig.dpi)
            self.assertEqual(overlapping(furniture(fig)), [])

    def test_legend_in_compact_and_without_notes(self):
        types = ["Boring", "Test Pit", "CPT", "Vapor Probe", "Monitoring Well", "Direct Push", "Test Trench",
                 "Extraction Well", "Piezometer", "Hand Auger"]
        hits = [(f"X-{i}", t, 200.0 + 400.0 * i, 0.0, 30.0, 20.0, "N") for i, t in enumerate(types)]
        # drawn in Color from a style of 10 categories, one per type: the legend lists them all
        colors = [c for _v, _lab, c in CUMBERLAND_AESI[:len(types)]]
        model = color_model(make_model(hits=hits, gap=None), cats=[(t, t, c) for t, c in zip(types, colors)])
        for compact, notes in ((True, True), (True, False), (False, False)):
            for edge in (0.5, 0.3):
                s = make_settings(compact_layout=compact, show_notes=notes, edge_margin_in=edge, v_scale=100.0)
                p = plan(model, s)
                with self.subTest(compact=compact, notes=notes, edge=edge):
                    page = p.pages[0]
                    fig = draw(model, s, p, page, dpi=300)
                    t = texts_of(fig)
                    self.assertIn("Legend:", t)
                    swatches = [a for a in fig.artists if isinstance(a, Line2D)]
                    self.assertEqual(len(swatches), len(types))
                    self.assertEqual(overlapping(furniture(fig)), [])
                    rgb = np.asarray(fig.canvas.buffer_rgba())[..., :3]
                    self.assertEqual(ink_in_edge(rgb, edge, 300), 0)

    def test_bend_label_never_covers_an_end_letter(self):
        # a bend 0.05 in from the start: its BEND label would sit on "A (W)"; the dashed line stays
        for compact in (False, True):
            model = make_model(bend=50.0)
            s = make_settings(compact_layout=compact)
            p = plan(model, s)
            fig = draw(model, s, p, p.pages[0])
            self.assertNotIn("BEND", texts_of(fig))
            self.assertEqual(overlapping(furniture(fig)), [])
            far = make_model(bend=2600.0)
            fig = draw(far, s, plan(far, s), plan(far, s).pages[0])
            self.assertIn("BEND", texts_of(fig))

    def test_preview_keeps_the_standard_marks(self):
        model = make_model()
        s = make_settings(compact_layout=True)
        fig = Figure(figsize=(8, 4), dpi=72)
        F.draw_preview(fig, model, s, plan(model, s))
        t = texts_of(fig)
        self.assertEqual(t.count("Elevation (ft NAVD88)"), 2)
        self.assertIn("(W)", t)


def note_texts(fig):
    """(text, size) of the two compact note lines."""
    return [(t.get_text(), t.get_fontsize()) for t in fig.texts if t.get_text().startswith(("H 1 in", "Ground:"))]


def hbar_x(fig):
    """Paper x (inches) where the horizontal graphic scale starts."""
    return min(a.get_x() for a in fig.artists if isinstance(a, Rectangle) and a.get_width() > a.get_height())


def long_notes_settings(**over):
    """Compact notes as long as the user's: depth sources, TD labels, a wide tolerance (and, with label_offset,
    the offset explanation)."""
    kw = dict(compact_layout=True, edge_margin_in=0.3, top_field="ExploElev", depth_field="ExploDepth",
              tolerance_ft=408.0, td_label=True, v_scale=100.0, allowed_sheets=["letter"])
    kw.update(over)
    return make_settings(**kw)


class CompactNotes(unittest.TestCase):
    """The two note lines of the compact layout: 5.8 or 5.5 pt, the same text in a PDF and a PNG, the scale bar
    moved left only as far as they need, the explanations of the marks on the sheet always kept."""

    def test_same_text_in_pdf_and_png(self):
        cases = [(make_model(td=True), long_notes_settings()),
                 (make_model(td=True), long_notes_settings(label_offset=True)),
                 (make_model(td=True), long_notes_settings(v_scale=50.0, label_offset=True))]   # Letter portrait
        cases[2][0].dem_name = LONG_DEM
        for model, s in cases:
            p = plan(model, s)
            page = p.pages[0]
            seen = set()
            for dpi in (72, 150, 300, 600):                   # 72: PDF and SVG; the others: PNG
                fig = Figure(figsize=(page.page_w, page.page_h), dpi=dpi)
                F.draw_page(fig, model, s, p, page)
                seen.add((tuple(note_texts(fig)), round(hbar_x(fig), 6)))
            self.assertEqual(len(seen), 1, (page.sheet_name, seen))

    def test_size_and_explanations_kept(self):
        for over in (dict(), dict(label_offset=True), dict(v_scale=50.0, label_offset=True),
                     dict(v_scale=50.0, label_offset=True, edge_margin_in=0.5)):
            model = make_model(td=True)
            model.dem_name = LONG_DEM
            s = long_notes_settings(**over)
            p = plan(model, s)
            page = p.pages[0]
            with self.subTest(sheet=page.sheet_name, **over):
                fig = draw(model, s, p, page, dpi=300)
                notes = note_texts(fig)
                self.assertEqual(len(notes), 2)
                self.assertTrue(all(size in (5.8, 5.5) for _, size in notes), notes)
                line1, line2 = notes[0][0], notes[1][0]
                for part in ("H 1 in = 1,000 ft", "V 1 in = ", "VE "):
                    self.assertIn(part, line1)
                self.assertTrue(line2.startswith("Ground: Clark_County_2019"))
                self.assertIn("TD = total depth", line2)                     # TD labels are on the sheet
                self.assertEqual("Labels: distance and direction projected onto the line" in line2,    # 0.3.5
                                 bool(s.label_offset))
                self.assertNotIn("NAVD88", line2)                            # the elevation title has the datum
                self.assertEqual(overlapping(furniture(fig)), [])
                rgb = np.asarray(fig.canvas.buffer_rgba())[..., :3]
                self.assertEqual(ink_in_edge(rgb, S.edge_in(s), 300), 0)

    def test_bar_moves_left_only_as_far_as_needed(self):
        # short notes (a ground line only): the bar stays under the plot's left end, the notes at 5.8 pt
        ground = flat_model(7500.0, 200.0)                     # 7.5 in wide on Letter landscape
        ground.has_explorations = False
        s = make_settings(compact_layout=True, edge_margin_in=0.3, below_in=0.5)
        p = plan(ground, s)
        fig = draw(ground, s, p, p.pages[0])
        self.assertAlmostEqual(hbar_x(fig), p.pages[0].plot_left, places=9)
        self.assertTrue(all(size == 5.8 for _, size in note_texts(fig)))
        # the user's long notes on Letter landscape: the bar moves left, by no more than they need, and every
        # part is there at 5.8 pt
        model = make_model(td=True)
        s = long_notes_settings()
        p = plan(model, s)
        page = p.pages[0]
        fig = draw(model, s, p, page)
        x = hbar_x(fig)
        overhang, right = S.hbar_extent_in(s)
        self.assertLess(x, page.plot_left - 0.05)
        self.assertGreaterEqual(x, 0.3 + overhang - 1e-9)
        lines = F.compact_notes(model, s, p, page)
        notes = note_texts(fig)
        self.assertEqual([t for t, _ in notes], [" · ".join(q.text for q in parts) for parts in lines])
        self.assertTrue(all(size == 5.8 for _, size in notes))
        widest = max(F.note_width_in(fig, t, 5.8) for t, _ in notes)
        col_x = x + right + S.COL_GAP_IN
        self.assertLessEqual(col_x + widest, page.page_w - 0.3 + 1e-9)            # they fit ...
        self.assertGreater(col_x + 0.011 + widest, page.page_w - 0.3)            # ... with the bar no further left

    def test_fit_note_line(self):
        name = "Long_DEM_name_2019_lidar_v3"            # cut to 16 characters it saves less than a part
        parts = [F.NotePart(f"Ground: {name}, every 1 ft", 0, name), F.NotePart("Explorations within 408 ft", 1),
                 F.NotePart("Tops: ExploElev, else LIDAR", 2), F.NotePart("Bottoms: top − ExploDepth", 2),
                 F.NotePart("TD = total depth")]

        def w(texts):
            return F.note_width_in(None, " · ".join(texts), 5.5)
        full = [p.text for p in parts]
        self.assertEqual(F.fit_note_line(parts, w(full), 5.5), " · ".join(full))
        # a little short: the DEM name is cut first, every part stays
        t = F.fit_note_line(parts, w(full) - 0.2, 5.5)
        self.assertIn("…, every 1 ft", t)
        self.assertTrue(t.endswith(" · ".join(full[1:])))
        # shorter than the name allows: "Bottoms" (the last of the highest rank) goes, the full name comes back
        no_bottoms = full[:3] + full[4:]
        t = F.fit_note_line(parts, w(no_bottoms), 5.5)
        self.assertEqual(t, " · ".join(no_bottoms))
        # then "Tops", then "Explorations"; TD (rank 0) stays
        self.assertEqual(F.fit_note_line(parts, w([full[0], full[4]]), 5.5), " · ".join([full[0], full[4]]))
        # rank 0 alone too long: the line is cut short
        t = F.fit_note_line(parts, 1.0, 5.5)
        self.assertTrue(t.endswith("…"))
        self.assertLessEqual(F.note_width_in(None, t, 5.5), 1.0)


class StandardTitle(unittest.TestCase):
    """The standard layout's title line: as before when it fits between the end letters; else lifted clear of
    them, smaller and cut short to stay within the printer edge."""

    def texts(self, fig):
        return {t.get_text(): t for t in fig.texts}

    def test_short_line_where_it_was(self):
        model = make_model()
        s = make_settings(title="Site X")
        p = plan(model, s)
        page = p.pages[0]
        by = self.texts(draw(model, s, p, page))
        top = page.plot_bottom + page.plot_h
        cx = page.plot_left + page.plot_w / 2.0
        for text, dy, size in (("CROSS SECTION A–A′", 0.50, 12.0), ("Site X", 0.34, 8.5)):
            t = by[text]
            self.assertEqual(t.get_horizontalalignment(), "center")
            self.assertEqual(t.get_fontsize(), size)
            self.assertAlmostEqual(t.get_position()[0], cx, places=9)
            self.assertAlmostEqual(t.get_position()[1], top + dy, places=9)

    def test_long_line_lifted_and_fitted(self):
        cases = [(make_model(), make_settings(title=LONG_TITLE)),                               # Letter portrait
                 (make_model(), make_settings(title=LONG_TITLE, v_scale=100.0, edge_margin_in=0.3)),
                 (make_model(length=4600.0), make_settings(title=LONG_TITLE, h_scale=100.0,     # tiled
                                                           allowed_sheets=["letter"]))]
        for model, s in cases:
            p = plan(model, s)
            for page in p.pages[:2]:
                with self.subTest(sheet=page.sheet_name, tile=page.tile_index, edge=s.edge_margin_in):
                    fig = draw(model, s, p, page, dpi=300)
                    line = [t for t in fig.texts if t.get_text().startswith("Former")][0]
                    self.assertGreaterEqual(line.get_fontsize(), 7.0)
                    top = page.plot_bottom + page.plot_h
                    self.assertAlmostEqual(line.get_position()[1], top + 0.38, places=9)
                    bb = line.get_window_extent(fig.canvas.get_renderer())
                    edge = S.edge_in(s)
                    self.assertGreaterEqual(bb.x0, edge * 300 - 1)
                    self.assertLessEqual(bb.x1, (page.page_w - edge) * 300 + 1)
                    self.assertEqual(overlapping(furniture(fig)), [])
                    rgb = np.asarray(fig.canvas.buffer_rgba())[..., :3]
                    self.assertEqual(ink_in_edge(rgb, edge, 300), 0)


class WideVerticalScaleLabel(unittest.TestCase):
    """A plot as wide as the margins allow at 1 in = 1,000 ft vertical: the "1,000 ft" label of the vertical
    graphic scale stays inside the printer edge in every layout."""

    def test_label_inside_the_printer_edge(self):
        d = tempfile.mkdtemp(prefix="xsec_v1000_")
        try:
            for compact, edge, notes in itertools.product((False, True), (0.5, 0.3), (True, False)):
                if compact and not notes:
                    continue
                s = make_settings(h_scale=10000.0, v_scale=1000.0, allowed_sheets=["letter"], tile=False,
                                  compact_layout=compact, edge_margin_in=edge, show_notes=notes)
                mg = margins(s, (4000.0, 7000.0))
                length = math.floor((11.0 - mg["left"] - mg["right"]) * 10 + 1e-6) * 1000.0
                model = flat_model(length, lambda x: 5000.0 + 800.0 * math.sin(x / 9000.0), step=500.0)
                p = plan(model, s)
                with self.subTest(compact=compact, edge=edge, notes=notes):
                    self.assertTrue(p.fits, p.message)
                    page = p.pages[0]
                    self.assertEqual((page.page_w, page.page_h), (11.0, 8.5))
                    self.assertGreater(page.plot_left + page.plot_w, 11.0 - mg["right"] - 0.1)   # against it
                    rgb, _ = M.load_png(export(model, s, p, os.path.join(d, "wide.png"), "png", 300)[0])
                    self.assertEqual(ink_in_edge(rgb, edge, 300), 0)
                    m = measure_plot(rgb, page)
                    self.assertAlmostEqual(m["x"]["px_per_in"], 300.0, delta=0.05)
                    self.assertAlmostEqual(m["x"]["frame_px"], page.plot_w * 300, delta=1.0)
                    self.assertEqual(overlapping(furniture(draw(model, s, p, page))), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealDataDefaults(unittest.TestCase):
    """The user's CDF section with nothing but the data, the line and the scales chosen (1 in = 200 ft H / 20 ft V):
    the default layout (compact, grid filled below, 0.5 in printer edge) on Letter landscape."""

    def test_cdf_letter_landscape(self):
        from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
        from tests.test_e2e import copy_realdata, line_through_points
        from xsections.core.build import build_section
        tmp = tempfile.mkdtemp(prefix="xsec_layout_real_")
        self.addCleanup(shutil.rmtree, tmp, True)
        dem_path, wells_path = copy_realdata(tmp)                # copies: nothing is written next to the originals
        prj = QgsProject.instance()
        prj.clear()
        self.addCleanup(prj.clear)
        dem = QgsRasterLayer(dem_path, "cdf_lidar")
        wells = QgsVectorLayer(wells_path, "CDF_wells", "ogr")
        self.assertTrue(dem.isValid() and wells.isValid())
        prj.addMapLayers([dem, wells])
        prj.setCrs(dem.crs())
        geom, tol = line_through_points(wells, dem.crs(), prj)  # the line of the samples and of test_e2e
        s = Settings(line_wkt=geom.asWkt(), line_crs_authid=dem.crs().toWkt(), dem_layer_id=dem.id(),
                     points_layer_id=wells.id(), label_field="ExploName", type_field="ExploType",
                     top_field="ExploElev", depth_field="ExploDepth", tolerance_ft=tol, h_scale=200.0, v_scale=20.0)
        self.assertEqual(layout_of(s), (True, 0.5, True, "below"))
        model = build_section(s, prj)
        self.assertEqual(len(model.hits), 8)
        p = plan(model, s)
        self.assertTrue(p.fits, p.message)
        self.assertEqual(len(p.pages), 1)
        page = p.pages[0]
        self.assertEqual(page.sheet_name, "Letter 11 × 8.5 in, landscape")

        # the grid is filled below the section only, in whole 1 in (20 ft) majors, until no other major fits
        unfilled = plan(model, dataclasses.replace(s, fill_grid="off"))
        added = unfilled.z_min - p.z_min
        self.assertEqual(p.z_max, unfilled.z_max)
        self.assertGreaterEqual(added, 20.0)
        self.assertEqual(added % 20.0, 0.0)
        self.assertEqual((p.z_min, p.z_max), (580.0, 700.0))
        self.assertAlmostEqual(page.plot_h, (700.0 - 580.0) / 20.0, places=9)
        mg = margins(s, (p.z_min, p.z_max), ())
        self.assertLessEqual(page.plot_bottom + page.plot_h, page.page_h - mg["top"] + 1e-9)
        self.assertGreaterEqual(page.plot_bottom, mg["bottom"] - 1e-9)
        self.assertGreater(page.plot_h + mg["top"] + mg["bottom"] + 1.0, page.page_h)    # less than a major left

        # exported at 300 dpi: exactly to scale, nothing in the printer edge, no marks overlapping
        rgb, _ = M.load_png(export(model, s, p, os.path.join(tmp, "cdf.png"), "png", 300)[0])
        m = measure_plot(rgb, page)
        for axis, inches in (("x", page.plot_w), ("y", page.plot_h)):
            self.assertAlmostEqual(m[axis]["frame_px"], inches * 300, delta=1.0, msg=f"{axis} frame")
            self.assertAlmostEqual(m[axis]["px_per_in"], 300.0, delta=0.05, msg=f"{axis} px/in")
        self.assertEqual(ink_in_edge(rgb, 0.5, 300), 0)
        fig = draw(model, s, p, page)
        self.assertEqual(overlapping(furniture(fig)), [])
        t = texts_of(fig)
        self.assertEqual(t.count("Elevation (ft NAVD88)"), 1)                # the compact layout's marks
        self.assertEqual(len(note_texts(fig)), 2)


if __name__ == "__main__":
    unittest.main()
