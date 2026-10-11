"""(0.3.7, DESIGN.md decision 28) Grid line style None: Sheet style › Grid › Custom may leave the major or the minor
lines out (grid_major_style / grid_minor_style "none"). That set is not drawn on the sheets, the tiles, the preview or
any export; a None major leaves a uniform minor grid (minor lines at the major positions too); both None leave no grid
while the frame, the ticks and the axis numbers stay. The notes name only the drawn sets. Surfaces keep their own
styles (no "none"), the presets never hold it, and every other grid draws as 0.3.6 drew it (the goldens)."""
import math
import os
import re
import shutil
import tempfile
import unittest

from tests.fixtures import start_app

start_app()

from matplotlib.backends.backend_agg import FigureCanvasAgg              # noqa: E402
from matplotlib.colors import to_rgba                                    # noqa: E402
from matplotlib.figure import Figure                                     # noqa: E402
from pypdf import PdfReader                                              # noqa: E402
from qgis.core import QgsProject                                         # noqa: E402

from tests.test_figure import make_model, make_settings, texts_of        # noqa: E402
from xsections.core.model import (GRID_PRESETS, GRID_STYLES, SURFACE_STYLES, Settings,  # noqa: E402
                                  clean_sheet_style, clean_surface, grid_drawn, grid_spec)
from xsections.render import figure as F                                 # noqa: E402
from xsections.render.export import export                               # noqa: E402
from xsections.render.notes import compact_notes, note_texts             # noqa: E402
from xsections.render.scales import plan                                 # noqa: E402
from xsections.ui import settings_store                                  # noqa: E402

MAJOR, MINOR = "#13579b", "#2468ac"          # Custom colours used nowhere else on a sheet
NB = "\xa0"                                  # the notes' non-breaking space
SEP = NB + "· "                              # between the parts of a standard note
STYLE_PAIRS = (("dash", "none"), ("none", "solid"), ("none", "none"))


def custom(major, minor, **over):
    """make_settings with the Custom grid, the line styles `major` / `minor` and the colours MAJOR / MINOR."""
    return make_settings(grid_color="custom", grid_major_style=major, grid_minor_style=minor,
                         grid_major_color=MAJOR, grid_minor_color=MINOR, **over)


def grid_lines(fig):
    """{zorder: [Line2D]} of the minor (0.5) and major (0.6) grid lines of the sheet's or the preview's axes (the
    pattern of tests/test_export.CustomGrid)."""
    ax = fig.axes[0]
    return {z: [ln for ln in ax.lines if ln.get_zorder() == z] for z in (0.5, 0.6)}


def along_x(lines):
    """The lines of `lines` drawn at x values (vertical lines: each segment is x, x, NaN)."""
    return [ln for ln in lines if ln.get_xdata()[0] == ln.get_xdata()[1]]


def along_y(lines):
    return [ln for ln in lines if ln.get_ydata()[0] == ln.get_ydata()[1]]


def positions(ln, axis):
    """The x (or y) values of the NaN-separated segments of one grid line."""
    data = ln.get_xdata() if axis == "x" else ln.get_ydata()
    return [float(v) for v in data[0::3]]


def multiples_inside(lo, hi, step):
    """The multiples of `step` strictly inside (lo, hi) (the frame is at lo and hi)."""
    k0, k1 = math.floor(lo / step) - 1, math.ceil(hi / step) + 1
    eps = step * 1e-6
    return [k * step for k in range(k0, k1 + 1) if lo + eps < k * step < hi - eps]


def tick_texts(fig):
    """(x ticks, y ticks, x labels, y labels) of a drawn figure's axes."""
    ax = fig.axes[0]
    return (list(ax.get_xticks()), list(ax.get_yticks()), [t.get_text() for t in ax.get_xticklabels()],
            [t.get_text() for t in ax.get_yticklabels()])


def sheet(model, s, index=0, dpi=50):
    """One sheet drawn on an Agg canvas (the tick labels get their texts); (fig, plan, page)."""
    p = plan(model, s)
    fig = Figure(dpi=dpi)
    FigureCanvasAgg(fig)
    F.draw_page(fig, model, s, p, p.pages[index])
    fig.canvas.draw()
    return fig, p, p.pages[index]


def preview(model, s, size=(9.0, 3.5)):
    p = plan(model, s)
    fig = Figure(figsize=size, dpi=100)
    FigureCanvasAgg(fig)
    F.draw_preview(fig, model, s, p)
    fig.canvas.draw()
    return fig, p


class Model(unittest.TestCase):
    """The value "none" of the two grid style keys: kept by the cleaner and grid_spec, never a surface's style, never
    a preset's; grid_drawn says which sets are drawn."""

    def test_constants(self):
        self.assertEqual(GRID_STYLES, ("solid", "dash", "dot", "none"))
        self.assertEqual(SURFACE_STYLES, ("solid", "dash", "dot"))

    def test_cleaner_keeps_none(self):
        data = {"grid_major_style": "none", "grid_minor_style": "none"}
        clean_sheet_style(data)
        self.assertEqual(data, {"grid_major_style": "none", "grid_minor_style": "none"})
        data = {"grid_major_style": "wavy", "grid_minor_style": "none"}
        clean_sheet_style(data)
        self.assertEqual(data, {"grid_minor_style": "none"})                  # an unknown style is still dropped

    def test_a_surface_has_no_none(self):
        self.assertEqual(clean_surface({"style": "none"})["style"], "solid")

    def test_grid_spec_and_presets(self):
        self.assertEqual(grid_spec(Settings(grid_color="custom", grid_major_style="none"))[0][2], "none")
        self.assertEqual(grid_spec(Settings(grid_color="custom", grid_minor_style="none"))[1][2], "none")
        for preset in ("green", "gray"):
            s = Settings(grid_color=preset, grid_major_style="none", grid_minor_style="none")
            self.assertEqual(grid_spec(s), GRID_PRESETS[preset])
            self.assertEqual(grid_drawn(s), (True, True), preset)
            self.assertNotIn("none", [part[2] for part in GRID_PRESETS[preset]])

    def test_grid_drawn(self):
        for major, minor in (("solid", "solid"), ("dash", "none"), ("none", "dot"), ("none", "none")):
            s = Settings(grid_color="custom", grid_major_style=major, grid_minor_style=minor)
            self.assertEqual(grid_drawn(s), (major != "none", minor != "none"), (major, minor))
        self.assertEqual(grid_drawn(Settings()), (True, True))                # Green
        self.assertEqual(grid_drawn(Settings(grid_color="custom", grid_major_style="wavy")), (True, True))

    def test_round_trip(self):
        s = Settings(grid_color="custom", grid_major_style="none", grid_minor_style="none", grid_custom_used=True)
        back = Settings.from_json(s.to_json())
        self.assertEqual((back.grid_major_style, back.grid_minor_style), ("none", "none"))
        self.assertEqual(back, s)
        prj = QgsProject.instance()
        try:
            prj.clear()
            settings_store.save(prj, s)
            self.assertEqual(settings_store.load(prj), s)
        finally:
            prj.clear()


class Sheets(unittest.TestCase):
    """A None set adds no line; a None major leaves every minor multiple (the major positions too); the frame, the
    ticks and the axis numbers are those of the same sheet with solid lines."""

    def check(self, fig, ref, major, minor, h_minor, v_minor, where):
        lines = grid_lines(fig)
        ax = fig.axes[0]
        x0, x1 = ax.get_xlim()
        z0, z1 = ax.get_ylim()
        if major == "none":
            self.assertEqual(lines[0.6], [], where)
        else:
            self.assertEqual(len(lines[0.6]), 2, where)                   # one line along x and one along y
            for ln in lines[0.6]:
                self.assertEqual(ln.get_color(), MAJOR)
        if minor == "none":
            self.assertEqual(lines[0.5], [], where)
        elif major == "none":
            self.assertEqual(len(lines[0.5]), 2, where)
            (lx,), (ly,) = along_x(lines[0.5]), along_y(lines[0.5])
            want_x, want_z = multiples_inside(x0, x1, h_minor), multiples_inside(z0, z1, v_minor)
            self.assertEqual(len(lx.get_xdata()) // 3, len(want_x), where)
            self.assertEqual(len(ly.get_ydata()) // 3, len(want_z), where)
            for got, want in zip(positions(lx, "x"), want_x):
                self.assertAlmostEqual(got, want, places=6)
            for got, want in zip(positions(ly, "y"), want_z):
                self.assertAlmostEqual(got, want, places=6)
            self.assertEqual(lx.get_color(), MINOR)
        for sp in ax.spines.values():                                      # the frame: 0.9 pt black whatever the grid
            self.assertEqual((sp.get_linewidth(), sp.get_edgecolor()), (F.FRAME_LW, to_rgba(F.INK)), where)
        self.assertEqual(tick_texts(fig), tick_texts(ref), where)

    def test_sheet(self):
        model = make_model()
        ref, p, _ = sheet(model, custom("solid", "solid"))
        self.assertEqual(len(along_x(grid_lines(ref)[0.5])), 1)            # (0.3.6: minors skip the majors)
        for major, minor in STYLE_PAIRS:
            fig, p2, _ = sheet(model, custom(major, minor))
            self.assertEqual((p2.z_min, p2.z_max, p2.plot_length), (p.z_min, p.z_max, p.plot_length))
            self.check(fig, ref, major, minor, p.h_minor, p.v_minor, (major, minor))
        # the major positions are in a None major's minor grid
        fig, _, _ = sheet(model, custom("none", "solid"))
        xs = positions(along_x(grid_lines(fig)[0.5])[0], "x")
        self.assertTrue(any(abs(v - p.h_major) < 1e-6 for v in xs), xs)
        self.assertTrue(any(abs(v - 2 * p.h_major) < 1e-6 for v in xs), xs)

    def test_tiles(self):
        model = make_model(length=4600.0)
        over = dict(h_scale=100.0, allowed_sheets=["tabloid"])
        ref, p, page = sheet(model, custom("solid", "solid", **over), index=1)
        self.assertGreater(len(p.pages), 1)
        self.assertGreater(page.x_min, 0.0)                                # page 2 starts inside the section
        for major, minor in STYLE_PAIRS:
            fig, _, page2 = sheet(model, custom(major, minor, **over), index=1)
            self.assertEqual((page2.x_min, page2.x_max), (page.x_min, page.x_max))
            self.check(fig, ref, major, minor, p.h_minor, p.v_minor, ("page 2", major, minor))

    def test_preview(self):
        model = make_model()
        ref, p = preview(model, custom("solid", "solid"))
        for major, minor in STYLE_PAIRS:
            fig, _ = preview(model, custom(major, minor))
            self.check(fig, ref, major, minor, p.h_minor, p.v_minor, ("preview", major, minor))

    def test_preview_thins_a_lone_minor_grid(self):
        """At 1 in = 100 ft the 9 in preview drops 0.3.6's minors (they would merge); with the major None it thins
        them to 1-2-5 multiples instead, so the preview still shows a grid where the sheet has one."""
        model = make_model(length=4600.0)
        over = dict(h_scale=100.0, allowed_sheets=["tabloid"])
        fig, p = preview(model, custom("solid", "solid", **over))
        self.assertEqual(along_x(grid_lines(fig)[0.5]), [])                # as 0.3.6
        fig, _ = preview(model, custom("none", "solid", **over))
        self.assertEqual(grid_lines(fig)[0.6], [])
        (lx,) = along_x(grid_lines(fig)[0.5])
        xs = positions(lx, "x")
        self.assertTrue(xs)
        for v in xs:
            self.assertAlmostEqual(v / p.h_minor, round(v / p.h_minor), places=6)
        ax = fig.axes[0]
        x0, x1 = ax.get_xlim()
        inch_per_ft = ax.get_position().width * fig.get_size_inches()[0] / (x1 - x0)
        step = xs[1] - xs[0]
        self.assertGreater(step, p.h_minor)                                # thinned
        self.assertGreaterEqual(step * inch_per_ft, 0.035 - 1e-9)          # no closer than the preview's gap
        self.assertLess(len(xs), len(multiples_inside(x0, x1, p.h_minor)))


class Exports(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="xsec_gridnone_")
        self.model = make_model()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def svg(self, major, minor):
        s = custom(major, minor, allowed_sheets=["letter"])
        out = export(self.model, s, plan(self.model, s), os.path.join(self.dir, f"{major}_{minor}.svg"), "svg")
        with open(out[0], encoding="utf-8") as fh:
            text = fh.read()
        arrays = [tuple(float(v) for v in re.split(r"[ ,]+", m.strip()) if v)
                  for m in re.findall(r"stroke-dasharray:\s*([0-9., ]+)", text)]
        return text, arrays

    @staticmethod
    def has(arrays, pattern):
        return any(len(a) == 2 and all(abs(g - w) < 1e-3 for g, w in zip(a, pattern)) for a in arrays)

    def test_svg(self):
        text, arrays = self.svg("none", "none")
        self.assertNotIn(MAJOR, text)
        self.assertNotIn(MINOR, text)
        for pattern in F.GRID_DASH_PT.values():
            self.assertFalse(self.has(arrays, pattern), arrays)
        text, arrays = self.svg("dash", "none")
        self.assertIn(MAJOR, text)
        self.assertNotIn(MINOR, text)
        self.assertTrue(self.has(arrays, F.GRID_DASH_PT["dash"]), arrays)
        self.assertFalse(self.has(arrays, F.GRID_DASH_PT["dot"]), arrays)

    def test_png_and_pdf(self):
        s = custom("dash", "none", allowed_sheets=["letter"])
        p = plan(self.model, s)
        out = export(self.model, s, p, os.path.join(self.dir, "g.png"), "png", 100)
        self.assertEqual(len(out), len(p.pages))
        self.assertTrue(all(os.path.isfile(f) for f in out))
        out = export(self.model, s, p, os.path.join(self.dir, "g.pdf"), "pdf")
        self.assertTrue(os.path.isfile(out[0]))
        self.assertEqual(len(PdfReader(out[0]).pages), len(p.pages))


class Notes(unittest.TestCase):
    """The notes name only the drawn sets; two drawn sets read exactly as in 0.3.6 (the goldens)."""

    BOTH = f"GRID 1 in major, 0.1 in minor (1,000{NB}×{NB}50{NB}ft; 100{NB}×{NB}5{NB}ft)"
    MAJOR_ONLY = f"GRID 1 in major (1,000{NB}×{NB}50{NB}ft)"
    MINOR_ONLY = f"GRID 0.1 in minor (100{NB}×{NB}5{NB}ft)"
    HEAD = [f"HORIZONTAL 1{NB}in{NB}={NB}1,000{NB}ft (1:12,000), 10{NB}scale",
            f"VERTICAL 1{NB}in{NB}={NB}50{NB}ft (1:600), 50{NB}scale", "VERTICAL EXAGGERATION 20×"]
    SHEET = f"SHEET{NB}Letter 8.5 × 11 in, portrait"

    def notes(self, major, minor, **over):
        model = make_model()
        s = custom(major, minor, **over)
        p = plan(model, s)
        page = p.pages[0]
        return p, note_texts(model, s, p, page)[0].split(SEP), [n.text for n in compact_notes(model, s, p, page)[0]]

    def test_texts(self):
        for (major, minor), grid, short in ((("solid", "solid"), self.BOTH, "GRID 1 in major, 0.1 in minor"),
                                            (("dash", "dot"), self.BOTH, "GRID 1 in major, 0.1 in minor"),
                                            (("none", "solid"), self.MINOR_ONLY, "GRID 0.1 in minor"),
                                            (("solid", "none"), self.MAJOR_ONLY, "GRID 1 in major")):
            _, parts, line1 = self.notes(major, minor)
            self.assertEqual(parts, self.HEAD + [grid, self.SHEET], (major, minor))
            self.assertEqual(line1, ["H 1 in = 1,000 ft (1:12,000), 10 scale", "V 1 in = 50 ft (1:600), 50 scale",
                                     "VE 20×", short, "Letter 8.5 × 11 in"], (major, minor))
        p, parts, line1 = self.notes("none", "none")
        self.assertEqual(parts, self.HEAD + [self.SHEET])
        self.assertFalse(any("GRID" in t for t in parts + line1), (parts, line1))
        self.assertEqual(len(line1), 4)
        self.assertTrue(p.fits, p.message)

    def test_both_none_plans_and_draws(self):
        for over in (dict(), dict(compact_layout=True, fill_grid="below")):          # standard, compact
            fig, _, _ = sheet(make_model(), custom("solid", "solid", **over))
            self.assertTrue(any("GRID" in t for t in texts_of(fig)), over)
            fig, p, _ = sheet(make_model(), custom("none", "none", **over))
            self.assertTrue(p.fits, p.message)
            self.assertEqual(grid_lines(fig), {0.5: [], 0.6: []})
            self.assertFalse(any("GRID" in t for t in texts_of(fig)), over)


if __name__ == "__main__":
    unittest.main()
