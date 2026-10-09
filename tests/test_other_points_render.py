"""0.3.3 render, Other points: the symbol geometry, a point resting on the drawn ground line (checked against the
drawn artists, independently of the painter), points at the LIDAR or a field, their labels, notes and legend (build
spec section 4.6, tests 9.3)."""
import math
import os
import random
import tempfile
import unittest
from unittest import mock

from tests.fixtures import STANDARD_LAYOUT, budget, start_app, timing_test

start_app()

import numpy as np                                                    # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg          # noqa: E402
from matplotlib.figure import Figure                                  # noqa: E402
from matplotlib.lines import Line2D                                   # noqa: E402
from matplotlib.patches import Ellipse, Polygon                       # noqa: E402

from xsections.core.model import (OTHER_POINT_DEFAULTS, GroundProfile, OtherLayerInfo, OtherPoint,  # noqa: E402
                                  SectionModel, Settings, SurfaceProfile, clean_other_point)
from xsections.render import figure as F                              # noqa: E402
from xsections.render import scales as S                              # noqa: E402
from xsections.render.scales import plan                              # noqa: E402

BLUE = "#1f6fb2"
SHAPES = ("asterisk", "circle", "square", "diamond", "star", "triangle")
R_GROUND = S.GROUND_LW / 2.0 / 72.0
GAP = S.OTHER_REST_GAP_PT / 72.0


# ----------------------------------------------------------------------------- hand-made models with other points
def other_info(j, name="Seeps", shape="asterisk", color=BLUE, size=7.0, elev="line", elev_field="", elev_empty="line"):
    row = clean_other_point(dict(OTHER_POINT_DEFAULTS, layer_id=f"P{j}", name=name, shape=shape, color=color,
                                 size=size, elev=elev, elev_field=elev_field, elev_empty=elev_empty))
    return OtherLayerInfo(index=j, layer_id=f"P{j}", name=name, layer_name=name, shape=shape, color=color, size=size,
                          elev=elev, elev_field=elev_field, elev_empty=elev_empty, on=True, row=row)


def other_point(label, station, gs, z=None, how="line", j=0, name="Seeps", fid=None, lidar=math.nan, **kw):
    return OtherPoint(fid=fid if fid is not None else int(station), label=label, type_value="", x=0.0, y=0.0,
                      station=station, offset=10.0, side="L", direction="N", ground_at_station=gs,
                      ground_at_point=lidar, z=gs if z is None else z, how=how, layer_index=j, layer_id=f"P{j}",
                      layer_name=name, **kw)


def ground_of(z, length=3000.0, step=10.0):
    st = list(np.arange(0.0, length, step)) + [length]
    zf = z if callable(z) else (lambda s: z)
    return GroundProfile(stations=st, z=[zf(s) for s in st], step=step)


def make_model(points, infos, z=300.0, length=3000.0, step=10.0, hits=(), surfaces=()):
    gp = ground_of(z, length, step)
    pts = []
    for p in points:                       # the core gives "line" points the ground at their station
        if p.how == "line" and math.isfinite(gp.z_at(p.station)):
            p.ground_at_station = p.z = gp.z_at(p.station)
        pts.append(p)
    pts.sort(key=lambda p: (p.station, p.layer_index, p.label))
    return SectionModel(length=length, vertex_stations=[0.0, length], azimuth=90.0, ground=gp, hits=list(hits),
                        dem_name="LIDAR", points_name="", has_explorations=False, other_points=pts,
                        other_layers=list(infos), surfaces=list(surfaces))


def make_settings(**over):
    s = Settings(tolerance_ft=150.0, h_scale=200.0, v_scale=20.0, **STANDARD_LAYOUT)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def drawn(model, settings, dpi=100, index=0):
    p = plan(model, settings)
    fig = Figure(dpi=dpi)
    FigureCanvasAgg(fig)
    F.draw_page(fig, model, settings, p, p.pages[index])
    fig.canvas.draw()
    return fig, p, p.pages[index]


def by_gid(ax, gid):
    return [a for a in list(ax.lines) + list(ax.patches) + list(ax.texts) if a.get_gid() == gid]


def frame_inches(ax):
    """(x0, z0, kx, kz) of the axes from its own size and limits (independent of the painter)."""
    fw, fh = ax.figure.get_size_inches()
    pos = ax.get_position()
    x0, x1 = ax.get_xlim()
    z0, z1 = ax.get_ylim()
    return x0, z0, pos.width * fw / (x1 - x0), pos.height * fh / (z1 - z0)


def symbol_core(art, ax):
    """(segments in paper inches, rho) of a drawn symbol: the asterisk's strokes (rho = half the line width), a
    filled polygon's edges (rho = half its edge), a circle's centre (rho = its radius plus half its edge)."""
    x0, z0, kx, kz = frame_inches(ax)

    def paper(x, y):
        return (x - x0) * kx, (y - z0) * kz
    if isinstance(art, Line2D):
        xs, ys = np.asarray(art.get_xdata(), float), np.asarray(art.get_ydata(), float)
        segs = [(paper(xs[i], ys[i]), paper(xs[i + 1], ys[i + 1])) for i in range(len(xs) - 1)
                if np.isfinite([xs[i], ys[i], xs[i + 1], ys[i + 1]]).all()]
        return segs, art.get_linewidth() / 2.0 / 72.0
    if isinstance(art, Ellipse):
        c = paper(*art.get_center())
        r = art.get_width() / 2.0 * kx
        assert abs(r - art.get_height() / 2.0 * kz) < 1e-12           # round on paper
        return [(c, c)], r + art.get_linewidth() / 2.0 / 72.0
    xy = [paper(x, y) for x, y in art.get_xy()]
    return [(xy[i], xy[i + 1]) for i in range(len(xy) - 1)], art.get_linewidth() / 2.0 / 72.0


def ground_core(ax):
    """The drawn ground line's segments in paper inches."""
    x0, z0, kx, kz = frame_inches(ax)
    (g,) = [ln for ln in ax.lines if ln.get_zorder() == F.GROUND_Z and ln.get_linewidth() == F.GROUND_LW]
    xs, ys = np.asarray(g.get_xdata(), float), np.asarray(g.get_ydata(), float)
    return [(((xs[i] - x0) * kx, (ys[i] - z0) * kz), ((xs[i + 1] - x0) * kx, (ys[i + 1] - z0) * kz))
            for i in range(len(xs) - 1) if np.isfinite([xs[i], ys[i], xs[i + 1], ys[i + 1]]).all()]


def _pt_seg(p, a, b):
    ax_, ay = a
    bx, by = b
    dx, dy = bx - ax_, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax_) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - ax_ - t * dx, p[1] - ay - t * dy)


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def seg_seg(a, b, c, d):
    """Exact distance between segments ab and cd (0 when they cross)."""
    if a != b and c != d:
        d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
        if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4):
            return 0.0
    return min(_pt_seg(a, c, d), _pt_seg(b, c, d), _pt_seg(c, a, b), _pt_seg(d, a, b))


def clearance(art, ax):
    """Least distance between a symbol's ink and the drawn ground line's ink, paper inches (negative: overlap)."""
    segs, rho = symbol_core(art, ax)
    xs = [x for s in segs for x, _ in s]
    lo, hi = min(xs) - 0.2, max(xs) + 0.2
    ground = [g for g in ground_core(ax) if max(g[0][0], g[1][0]) >= lo and min(g[0][0], g[1][0]) <= hi]
    d = min(seg_seg(a, b, c, e) for a, b in segs for c, e in ground)
    return d - rho - R_GROUND


# ----------------------------------------------------------------------------- the geometry
class SymbolGeometry(unittest.TestCase):
    def test_asterisk_is_four_bold_strokes_through_the_centre(self):
        for size, k in ((7.0, 1.0), (3.0, 1.0), (7.0, 0.85), (20.0, 1.0)):
            s = size * k / 2.0
            w = max(1.0 * k, 0.42 * s)
            caps = S.symbol_capsules("asterisk", size, k)
            self.assertEqual(len(caps), 4)
            angles, ends = [], set()
            for c in caps:
                self.assertAlmostEqual((c.ax + c.bx) / 2, 0.0, places=15)            # through the centre
                self.assertAlmostEqual((c.ay + c.by) / 2, 0.0, places=15)
                self.assertAlmostEqual(math.hypot(c.bx - c.ax, c.by - c.ay), 2.5 * s / 72.0, places=12)
                self.assertAlmostEqual(c.r, w / 2.0 / 72.0, places=15)
                angles.append(round(math.degrees(math.atan2(c.by - c.ay, c.bx - c.ax)) % 180.0, 6))
                for x, y in ((c.ax, c.ay), (c.bx, c.by)):
                    ends.add(round(math.degrees(math.atan2(y, x)) % 360.0, 6))
            self.assertEqual(sorted(angles), [0.0, 45.0, 90.0, 135.0])
            self.assertEqual(len(ends), 8)                                             # 8 prongs
            self.assertAlmostEqual(S.asterisk_width_pt(size, k), w)
            self.assertEqual(S.symbol_outline("asterisk", size, k), [])
        self.assertAlmostEqual(S.asterisk_width_pt(3.0), 1.0)                         # at least 1 pt
        self.assertAlmostEqual(S.asterisk_width_pt(7.0), 0.42 * 3.5)
        half_w, below, above = S.symbol_extent(S.symbol_capsules("asterisk", 7.0))
        self.assertAlmostEqual(half_w, (1.25 * 3.5 + 0.42 * 3.5 / 2) / 72.0, places=15)
        self.assertAlmostEqual(below, half_w, places=15)
        self.assertAlmostEqual(above, half_w, places=15)

    def test_filled_shapes(self):
        s, e = 3.5 / 72.0, 0.6 / 72.0
        want = {"square": [(-0.85 * s, -0.85 * s), (0.85 * s, -0.85 * s), (0.85 * s, 0.85 * s), (-0.85 * s, 0.85 * s)],
                "diamond": [(0.0, 1.15 * s), (1.15 * s, 0.0), (0.0, -1.15 * s), (-1.15 * s, 0.0)],
                "triangle": [(0.0, 1.1 * s), (1.1 * s, -0.8 * s), (-1.1 * s, -0.8 * s)]}
        for shape, pts in want.items():
            got = S.symbol_outline(shape, 7.0)
            self.assertEqual(len(got), len(pts), shape)
            for (x, y), (wx, wy) in zip(got, pts):
                self.assertAlmostEqual(x, wx, places=15)
                self.assertAlmostEqual(y, wy, places=15)
            caps = S.symbol_capsules(shape, 7.0)                    # the edges, half the white edge thick
            self.assertEqual([(c.ax, c.ay) for c in caps], got)
            self.assertEqual([(c.bx, c.by) for c in caps], got[1:] + got[:1])
            self.assertTrue(all(abs(c.r - e / 2) < 1e-15 for c in caps))
        star = S.symbol_outline("star", 7.0)
        self.assertEqual(len(star), 10)
        self.assertAlmostEqual(star[0][0], 0.0, places=15)
        self.assertAlmostEqual(star[0][1], 1.2 * s, places=15)                          # from the top
        for i, (x, y) in enumerate(star):
            self.assertAlmostEqual(math.hypot(x, y), (0.45 if i % 2 else 1.2) * s, places=15)
            self.assertAlmostEqual(math.degrees(math.atan2(y, x)) % 360.0, (90.0 - 36.0 * i) % 360.0, places=9)
        (disc,) = S.symbol_capsules("circle", 7.0)
        self.assertEqual((disc.ax, disc.ay, disc.bx, disc.by), (0.0, 0.0, 0.0, 0.0))
        self.assertAlmostEqual(disc.r, s + e / 2, places=15)
        self.assertEqual(len(S.symbol_outline("circle", 7.0)), 48)
        self.assertAlmostEqual(S.symbol_extent(S.symbol_capsules("triangle", 7.0))[1], 0.8 * s + e / 2, places=15)

    def test_capsule_envelope_is_exact(self):
        rnd = random.Random(7)
        for _ in range(300):
            c = S.Capsule(rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1),
                          rnd.uniform(0.02, 0.4))
            x = rnd.uniform(-1.5, 1.5)
            ys = np.linspace(-2.0, 2.0, 20001)
            inside = [y for y in ys if _pt_seg((x, y), (c.ax, c.ay), (c.bx, c.by)) <= c.r]
            if inside:
                self.assertAlmostEqual(S.capsule_top(c, x), max(inside), delta=3e-4)
                self.assertAlmostEqual(S.capsule_bottom(c, x), min(inside), delta=3e-4)
            else:
                self.assertEqual((S.capsule_top(c, x), S.capsule_bottom(c, x)), (-math.inf, math.inf))
        # a polyline: a nan vertex breaks it
        xs, ys = [0.0, 1.0, 2.0, 3.0], [0.0, 0.0, math.nan, 1.0]
        self.assertAlmostEqual(S.stroke_top(xs, ys, 0.1, 0.5), 0.1)
        self.assertAlmostEqual(S.stroke_top(xs, ys, 0.1, 1.05), math.sqrt(0.01 - 0.0025))   # its round end
        self.assertEqual(S.stroke_top(xs, ys, 0.1, 2.0), -math.inf)                          # in the break

    def test_rest_on_a_flat_and_a_sloping_line(self):
        for shape in SHAPES:
            caps = S.symbol_capsules(shape, 7.0)
            _, below, _ = S.symbol_extent(caps)
            gx = [i * 0.01 for i in range(-50, 51)]
            y = S.rest_on_line(gx, [0.5] * len(gx), 0.0, caps, R_GROUND, GAP)
            self.assertAlmostEqual(y, 0.5 + R_GROUND + GAP + below, places=12, msg=shape)
            # on a slope the lowest ink clears the stroke by the gap, measured exactly
            gy = [0.6 * x for x in gx]
            y = S.rest_on_line(gx, gy, 0.013, caps, R_GROUND, GAP)
            moved = [S.Capsule(c.ax + 0.013, c.ay + y, c.bx + 0.013, c.by + y, c.r) for c in caps]
            d = min(seg_seg((c.ax, c.ay), (c.bx, c.by), (gx[i], gy[i]), (gx[i + 1], gy[i + 1])) - c.r
                    for c in moved for i in range(len(gx) - 1)) - R_GROUND
            self.assertGreaterEqual(d, -1e-6, shape)
            self.assertLessEqual(d, GAP + 1e-6, shape)
        self.assertIsNone(S.rest_on_line([0.0, 1.0], [math.nan, math.nan], 0.5, S.symbol_capsules("circle", 7.0),
                                         R_GROUND, GAP))


# ----------------------------------------------------------------------------- the drawing
class DrawnSymbols(unittest.TestCase):
    def test_artists_per_shape(self):
        infos = [other_info(j, f"Row {j}", shape=shape, color=c) for j, (shape, c) in
                 enumerate(zip(SHAPES, ("#1f6fb2", "#d55e00", "#2e8b57", "#7b3294", "#b8860b", "#c2185b")))]
        pts = [other_point(f"P-{j}", 300.0 + 400.0 * j, 300.0, j=j, name=f"Row {j}") for j in range(6)]
        model = make_model(pts, infos)
        fig, p, page = drawn(model, make_settings())
        ax = fig.axes[0]
        arts = sorted(by_gid(ax, F.OTHER_GID), key=_centre_x)
        self.assertEqual(len(arts), 6)
        aster, circle = arts[0], arts[1]
        self.assertIsInstance(aster, Line2D)
        self.assertEqual((aster.get_solid_capstyle(), aster.get_color()), ("round", "#1f6fb2"))
        self.assertAlmostEqual(aster.get_linewidth(), 0.42 * 3.5)
        self.assertEqual(int(np.isnan(np.asarray(aster.get_xdata(), float)).sum()), 3)     # 4 strokes
        self.assertIsInstance(circle, Ellipse)
        for a in arts[1:]:
            self.assertEqual(a.get_edgecolor()[:3], (1.0, 1.0, 1.0))                        # white edge
            self.assertAlmostEqual(a.get_linewidth(), 0.6)
            self.assertEqual(a.get_joinstyle(), "round")
        self.assertIsInstance(arts[2], Polygon)
        for a in arts:
            self.assertEqual(a.get_zorder(), F.POINT_Z)
        self.assertEqual(sorted(t.get_text() for t in by_gid(ax, F.OTHER_LABEL_GID)), [f"P-{j}" for j in range(6)])
        self.assertEqual(len(by_gid(ax, F.OTHER_LABEL_HALO_GID)), 6)
        self.assertEqual(by_gid(ax, F.OTHER_LEAD_GID), [])
        # the legend: the six rows after the other entries, each with its symbol (at most 6 pt)
        entries = S.legend_entries(model, make_settings())
        self.assertEqual([(e.kind, e.text) for e in entries], [("point", f"Row {j}") for j in range(6)])
        legend_syms = [a for a in fig.artists if isinstance(a, (Line2D, Ellipse, Polygon))
                       and _colour(a) in {i.color for i in infos}]
        self.assertEqual(len(legend_syms), 6)
        legend_aster = [a for a in legend_syms if isinstance(a, Line2D)][0]
        self.assertAlmostEqual(legend_aster.get_linewidth(), max(1.0, 0.42 * 3.0))         # 6 pt at most

    def test_preview_returns_the_placed_points(self):
        infos = [other_info(0)]
        pts = [other_point("S-1", 1000.0, 300.0), other_point("S-2", 2000.0, 300.0, z=296.0, how="lidar")]
        model = make_model(pts, infos)
        s = make_settings()
        fig = Figure(figsize=(9, 3.5), dpi=100)
        placed = F.draw_preview(fig, model, s, plan(model, s))
        self.assertEqual([pp.index for pp in placed], [0, 1])
        self.assertEqual([pp.station for pp in placed], [1000.0, 2000.0])
        self.assertAlmostEqual(placed[1].z, 296.0, places=9)
        for pp in placed:
            self.assertGreater(pp.label_top, pp.above)
            self.assertGreater(pp.half_w, 0.0)
        self.assertIsInstance(placed[0].z, float)
        self.assertEqual(F.draw_preview(Figure(figsize=(0.3, 0.3)), model, s, plan(model, s)), [])
        # without points: an empty list (the preview ignores it)
        bare = make_model([], [])
        self.assertEqual(F.draw_preview(Figure(figsize=(9, 3.5)), bare, s, plan(bare, s)), [])


def _centre_x(a):
    if isinstance(a, Ellipse):
        return a.get_center()[0]
    if isinstance(a, Line2D):
        return float(np.nanmean(np.asarray(a.get_xdata(), float)))
    return float(np.mean([x for x, _ in a.get_xy()[:-1]]))


def _colour(a):
    from matplotlib.colors import to_hex
    try:
        return to_hex(a.get_facecolor()) if not isinstance(a, Line2D) else to_hex(a.get_color())
    except (ValueError, TypeError):
        return ""


class RestingOnTheGround(unittest.TestCase):
    """Points on the ground line (the default): the lowest ink just above the drawn line, checked on the drawn
    artists at VE 10 and VE 1, on the plane and on the terrain valley's slope; sheet (figure and 300 dpi PNG export)
    and preview."""

    @classmethod
    def setUpClass(cls):
        from tests.fixtures import TOLERANCE, load_project, make_seeps_layer, seep_row
        from xsections.core.build import build_section
        cls.models = {}
        for kind in ("plane", "terrain"):
            prj, dem, pts, lines = load_project(kind=kind)
            seeps = make_seeps_layer(kind=kind)
            prj.addMapLayers([seeps])
            rows = [seep_row(layer=seeps, label_field="Name"),
                    seep_row(layer=seeps, label_field="Name", name="Triangles", shape="triangle", color="#c2185b"),
                    seep_row(layer=seeps, label_field="Name", name="Circles", shape="circle", color="#2e8b57",
                             size=12.0)]
            s = Settings(line_layer_id=lines.id(), line_fid=next(lines.getFeatures()).id(), dem_layer_id=dem.id(),
                         tolerance_ft=TOLERANCE, other_points=rows, sheet="custom", **STANDARD_LAYOUT)
            cls.models[kind] = (build_section(s, prj), s)

    def check(self, fig, what):
        ax = fig.axes[0]
        arts = by_gid(ax, F.OTHER_GID)
        self.assertEqual(len(arts), 12, what)                           # 4 seeps x 3 rows
        for a in arts:
            c = clearance(a, ax)
            self.assertGreaterEqual(c, -1e-5, f"{what}: {type(a).__name__} at {_centre_x(a):.1f} overlaps by {c}")
            self.assertLessEqual(c, GAP + 1e-4, f"{what}: {type(a).__name__} at {_centre_x(a):.1f} floats {c}")
        self.assertEqual(by_gid(ax, F.OTHER_LEAD_GID), [], what)       # no lead in this mode

    def test_resting(self):
        import dataclasses
        from xsections.render import export as E
        out = tempfile.mkdtemp(prefix="xsec_rest_")
        for kind, (model, s0) in self.models.items():
            self.assertEqual([p.label for p in model.other_points if p.layer_index == 0], ["S-1", "S-2", "S-5", "S-3"])
            self.assertTrue(all(p.how == "line" for p in model.other_points))
            for ve, (h, v) in (("VE 10", (500.0, 50.0)), ("VE 1", (500.0, 500.0))):
                s = dataclasses.replace(s0, h_scale=h, v_scale=v)
                p = plan(model, s)
                fig = Figure(dpi=72)
                F.draw_page(fig, model, s, p, p.pages[0])
                self.check(fig, f"{kind} {ve} sheet")
                figs = []
                real = E.draw_page

                def capture(fig, *a, **kw):
                    figs.append(fig)
                    return real(fig, *a, **kw)
                with mock.patch.object(E, "draw_page", side_effect=capture):
                    files = E.export(model, s, p, os.path.join(out, f"{kind}_{v:g}.png"), "png", dpi=300)
                self.assertTrue(os.path.isfile(files[0]))
                self.assertEqual(figs[0].dpi, 300)
                self.check(figs[0], f"{kind} {ve} 300 dpi PNG")
                prev = Figure(figsize=(9.0, 3.5), dpi=100)
                F.draw_preview(prev, model, s, p)
                self.check(prev, f"{kind} {ve} preview")

    def test_slope_of_the_valley(self):
        """S-5 sits on the steepest part of the terrain valley: the ground under its two sides differs, and the
        symbol is lifted by the higher side (it never cuts into the slope)."""
        model, s = self.models["terrain"]
        s5 = next(p for p in model.other_points if p.label == "S-5" and p.layer_index == 0)
        g = model.ground
        self.assertGreater(abs(g.z_at(s5.station - 30.0) - g.z_at(s5.station + 30.0)), 1.0)


class InADemGap(unittest.TestCase):
    def test_lowest_ink_above_the_nearest_ground(self):
        def z(s):
            return math.nan if 1400.0 <= s <= 1600.0 else 300.0 + 0.01 * s
        infos = [other_info(0)]
        p = other_point("S-9", 1500.0, 0.0, how="line", flags=["station in a DEM gap"], in_gap=True)
        model = make_model([p], infos, z=z)
        nv = model.ground.nearest_valid(1500.0)
        p.ground_at_station = p.z = nv
        s = make_settings()
        fig, pl, page = drawn(model, s)
        ax = fig.axes[0]
        (art,) = by_gid(ax, F.OTHER_GID)
        x0, z0, kx, kz = frame_inches(ax)
        segs, rho = symbol_core(art, ax)
        lowest = min(y for seg in segs for _, y in seg) - rho
        self.assertAlmostEqual(lowest, (nv - z0) * kz + R_GROUND + GAP, places=9)


class LidarAndField(unittest.TestCase):
    """At the LIDAR or a field: the symbol's centre marks the elevation; a dotted lead from the ground line down to
    a symbol well below it; the label above the symbol, and above the ground line when the symbol is under it."""

    def setUp(self):
        self.infos = [other_info(0, "Springs", elev="lidar"), other_info(1, "Seeps", elev="field", elev_field="Elev_ft")]
        self.pts = [other_point("L-1", 800.0, 300.0, z=297.0, how="lidar", name="Springs"),        # 0.15 in below
                    other_point("F-1", 1400.0, 300.0, z=299.5, how="field", j=1, field_value=299.5),  # 0.025 in below
                    other_point("L-2", 2000.0, 300.0, z=305.0, how="lidar", name="Springs")]         # above the line
        self.model = make_model(self.pts, self.infos)
        self.s = make_settings()

    def test_centre_lead_and_label(self):
        fig, p, page = drawn(self.model, self.s)
        ax = fig.axes[0]
        x0, z0, kx, kz = frame_inches(ax)
        arts = sorted(by_gid(ax, F.OTHER_GID), key=_centre_x)
        self.assertEqual(len(arts), 3)
        _, below, above = S.symbol_extent(S.symbol_capsules("asterisk", 7.0))
        for art, pt in zip(arts, self.model.other_points):
            xs, ys = np.asarray(art.get_xdata(), float), np.asarray(art.get_ydata(), float)
            ok = np.isfinite(xs)
            mids = [((xs[i] + xs[i + 1]) / 2, (ys[i] + ys[i + 1]) / 2) for i in range(0, len(xs), 3)]
            for mx, my in mids:                                     # every stroke centred on (station, z)
                self.assertAlmostEqual(mx, pt.station, delta=1e-6)
                self.assertAlmostEqual(my, pt.z, delta=1e-6)
            self.assertTrue(ok.sum() == 8)
        leads = by_gid(ax, F.OTHER_LEAD_GID)
        self.assertEqual(len(leads), 1)                             # only L-1 is more than 0.05 in below the line
        (lead,) = leads
        self.assertEqual(list(lead.get_xdata()), [800.0, 800.0])
        self.assertAlmostEqual(lead.get_ydata()[0], 300.0, places=9)
        self.assertAlmostEqual(lead.get_ydata()[1], 297.0 + above / kz, places=9)            # to the symbol's top
        self.assertEqual((lead.get_linewidth(), lead.get_zorder(), lead.get_color()), (0.6, 3.4, F.INK))
        labels = {t.get_text(): t for t in by_gid(ax, F.OTHER_LABEL_GID)}
        self.assertEqual(sorted(labels), ["F-1", "L-1", "L-2"])
        for pt in self.model.other_points:
            t = labels[pt.label]
            self.assertEqual((t.get_ha(), t.get_va(), t.get_rotation(), t.get_fontsize()), ("center", "bottom", 0.0,
                                                                                          S.LABEL_PT))
            base = (t.get_position()[1] - z0) * kz
            self.assertGreaterEqual(base, (pt.z - z0) * kz + above + S.OTHER_LABEL_GAP_IN - 1e-9, pt.label)
            self.assertGreaterEqual(base, (300.0 - z0) * kz + S.OTHER_LABEL_GROUND_IN - 1e-9, pt.label)
        self.assertAlmostEqual((labels["L-2"].get_position()[1] - z0) * kz,
                               (305.0 - z0) * kz + above + S.OTHER_LABEL_GAP_IN, places=9)
        self.assertAlmostEqual((labels["L-1"].get_position()[1] - z0) * kz,
                               (300.0 - z0) * kz + S.OTHER_LABEL_GROUND_IN, places=9)

    def test_range_covers_the_symbols(self):
        far = [other_point("D-1", 1000.0, 300.0, z=200.0, how="field", j=1, name="Seeps", field_value=200.0),
               other_point("U-1", 2000.0, 300.0, z=380.0, how="lidar", name="Springs")]
        model = make_model(far, self.infos)
        p = plan(model, self.s)
        _, below, above = S.symbol_extent(S.symbol_capsules("asterisk", 7.0))
        self.assertLessEqual(p.z_min, 200.0 - below * 20.0 - self.s.below_in * 20.0 + 1e-9)
        self.assertEqual(p.lowest_what, "D-1 (Seeps)")
        self.assertAlmostEqual(p.lowest_z, 200.0 - below * 20.0, places=9)
        self.assertGreaterEqual(p.z_max, 380.0 + above * 20.0 + S.LABEL_HEADROOM_IN * 20.0 - 1e-9)
        # points on the ground line add nothing below the ground
        line = make_model([other_point("S-1", 1000.0, 300.0)], [other_info(0)])
        bare = make_model([], [])
        self.assertEqual(plan(line, self.s).z_min, plan(bare, self.s).z_min)

    def test_labels_apart_and_under_the_frame_top(self):
        infos = [other_info(0)]
        pts = [other_point(f"SEEP-{i}", 1500.0 + 3.0 * i, 300.0) for i in range(9)]       # 9 within 24 ft
        model = make_model(pts, infos)
        s = self.s
        p = plan(model, s)
        self.assertGreaterEqual(p.z_max, S.other_label_top(model, s, p.plot_length) - 1e-9)
        self.assertGreater(S.other_label_top(model, s, p.plot_length), 300.0 + S.LABEL_HEADROOM_IN * 20.0)
        fig, p, page = drawn(model, s, dpi=150)
        ax = fig.axes[0]
        r = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(r) for t in by_gid(ax, F.OTHER_LABEL_GID)]
        self.assertEqual(len(boxes), 9)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0))
        frame = ax.get_window_extent()
        self.assertLessEqual(max(b.y1 for b in boxes), frame.y1)
        leaders = [ln for ln in ax.lines if ln.get_color() == F.LEADER and ln.get_linewidth() == 0.4]
        self.assertEqual(len(leaders), 8)                                   # every label raised off its symbol

    def test_labels_keep_off_the_explorations(self):
        from xsections.core.model import Hit
        hit = Hit(fid=1, label="MW-12", type_value="", x=0.0, y=0.0, station=1000.0, offset=5.0, side="L",
                  direction="N", ground_at_station=300.0, ground_at_point=300.0, top=300.0, top_source="dem",
                  bottom=270.0, total_depth=30.0)
        model = make_model([other_point("S-1", 1004.0, 300.0)], [other_info(0)], hits=[hit])
        model.has_explorations = True
        fig, p, page = drawn(model, self.s, dpi=150)
        ax = fig.axes[0]
        r = fig.canvas.get_renderer()
        (lab,) = by_gid(ax, F.OTHER_LABEL_GID)
        name = [t for t in ax.texts if t.get_text() == "MW-12"][0]
        a, b = lab.get_window_extent(r), name.get_window_extent(r)
        self.assertFalse(min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0))


class NotesAndMarks(unittest.TestCase):
    def test_notes(self):
        infos = [other_info(0, "Seeps"), other_info(1, "Springs", elev="lidar"),
                 other_info(2, "Wet spots", elev="field", elev_field="Elev_ft", elev_empty="line"),
                 other_info(3, "Ponds", elev="field", elev_field="WS_Elev", elev_empty="lidar"),
                 other_info(4, "Marsh", elev="field", elev_field="Z", elev_empty="off"),
                 other_info(5, "Nothing here")]
        pts = [other_point(f"P-{j}", 300.0 + 400.0 * j, 300.0, j=j, name=infos[j].name) for j in range(5)]
        model = make_model(pts, infos)
        s = make_settings()
        p = plan(model, s)
        note3 = F.notes_text(model, s, p, p.pages[0])[1][0]
        for text in ("Seeps within 150 ft of the section line: on the ground line.",
                     "Springs within 150 ft of the section line: at the LIDAR elevation at each point.",
                     "Wet spots within 150 ft of the section line: at Elev_ft, else on the ground line.",
                     "Ponds within 150 ft of the section line: at WS_Elev, else the LIDAR elevation.",
                     "Marsh within 150 ft of the section line: at Z."):
            self.assertIn(text, note3)
        self.assertNotIn("Nothing here", note3)
        self.assertNotIn("Explorations within", note3)                      # no exploration row on
        line2 = F.compact_notes(model, s, p, p.pages[0])[1]
        self.assertEqual([n for n in line2 if n.rank == 3],
                         [F.NotePart("Seeps: on the ground line", 3), F.NotePart("Springs: at LIDAR", 3),
                          F.NotePart("Wet spots: at Elev_ft, else ground line", 3),
                          F.NotePart("Ponds: at WS_Elev, else LIDAR", 3), F.NotePart("Marsh: at Z", 3)])

    def test_water_table_marks_keep_clear(self):
        st = [float(v) for v in range(0, 3001, 10)]
        wt = SurfaceProfile(name="Water table", color="#1f6fb2", style="solid", width=1.0, mode="smooth",
                            stations=st, z=[290.0] * len(st), marks=True)
        s = make_settings()

        def marks(model):
            fig, p, page = drawn(model, s)
            return sorted(float(a.get_xy()[0][0]) for a in fig.axes[0].patches if a.get_gid() == F.MARK_GID)
        bare = marks(make_model([], [], surfaces=[wt]))
        self.assertIn(200.0, bare)                                           # the first: 1 in from the left
        withp = marks(make_model([other_point("S-1", 200.0, 300.0)], [other_info(0)], surfaces=[wt]))
        self.assertNotIn(200.0, withp)
        self.assertTrue(all(abs(x - 200.0) * 0.005 >= S.symbol_extent(S.symbol_capsules("asterisk", 7.0))[0] + 0.15
                            - 1e-9 for x in withp))


def _overlap(a, b, tol=0.5):
    """True when two display boxes (Bbox) overlap by more than `tol` px both ways."""
    return min(a.x1, b.x1) - max(a.x0, b.x0) > tol and min(a.y1, b.y1) - max(a.y0, b.y0) > tol


class FixedLabels(unittest.TestCase):
    """(FIX 0.3.3) The other points' labels: never outside the frame a manual range sets, never over a neighbour's
    symbol, never across the ground line on a slope; exploration leaders pass behind a name; the notes for "From a
    field" with no field chosen."""

    def test_manual_range_leaves_a_cut_point_out_whole(self):
        infos = [other_info(0)]
        pts = [other_point("S-1", 2500.0, 0.0), other_point("S-2", 800.0, 0.0)]
        model = make_model(pts, infos, z=lambda s: 265.0 + 0.03 * s)        # the ground 265 to 355 ft
        s = make_settings(z_mode="manual", z_min=260.0, z_max=300.0)
        fig, p, page = drawn(model, s, dpi=150)
        ax = fig.axes[0]
        r = fig.canvas.get_renderer()
        frame = ax.get_window_extent(r)
        labels = by_gid(ax, F.OTHER_LABEL_GID) + by_gid(ax, F.OTHER_LABEL_HALO_GID)
        self.assertEqual(sorted({t.get_text() for t in labels}), ["S-2"])       # S-1 rests above the maximum
        for t in labels:
            b = t.get_window_extent(r)
            self.assertTrue(frame.x0 <= b.x0 and b.x1 <= frame.x1 and frame.y0 <= b.y0 and b.y1 <= frame.y1)
        self.assertEqual(len(by_gid(ax, F.OTHER_GID)), 1)
        self.assertEqual(len(p.warnings), 1)
        self.assertIn("cuts off data up to 355 ft (not drawn: S-1)", p.warnings[0])
        # the ground inside the range, the symbol resting just above its maximum: still named
        flat = make_model([other_point("S-1", 1500.0, 0.0)], infos, z=319.5)
        p2 = plan(flat, make_settings(z_mode="manual", z_min=260.0, z_max=320.0))
        self.assertEqual(p2.warnings, ["The manual elevation range 260 to 320 ft leaves out S-1 (not drawn). Widen "
                                       "the range or set Elevations to Auto."])
        fig, p2, page = drawn(flat, make_settings(z_mode="manual", z_min=260.0, z_max=320.0))
        self.assertEqual(by_gid(fig.axes[0], F.OTHER_LABEL_GID), [])

    def test_labels_keep_off_a_neighbours_symbol(self):
        """Two seeps 15 or 25 ft apart on a 5 or 10 % slope (1 in = 200 ft / 20 ft): no label covers the other's
        symbol (its white halo would erase it)."""
        infos = [other_info(0)]
        s = make_settings()
        for slope in (0.1, -0.1, 0.05):
            for gap in (15.0, 25.0):
                pts = [other_point("SEEP-2", 914.5, 0.0), other_point("SEEP-3", 914.5 + gap, 0.0)]
                model = make_model(pts, infos, z=lambda st, sl=slope: 300.0 + sl * (st - 900.0))
                fig, p, page = drawn(model, s, dpi=150)
                ax = fig.axes[0]
                r = fig.canvas.get_renderer()
                symbols = [a.get_window_extent(r) for a in by_gid(ax, F.OTHER_GID)]
                for t in by_gid(ax, F.OTHER_LABEL_GID):
                    b = t.get_window_extent(r)
                    for sym in symbols:
                        self.assertFalse(_overlap(b, sym), f"slope {slope}, {gap} ft: {t.get_text()}")

    def test_label_clears_the_ground_line_on_a_slope(self):
        """A seep on a 60 degree slope (on paper): its label's uphill end stays clear of the ground line (0.05 in
        above the line's middle all along it), raised with a leader."""
        def z(st):
            return 300.0 + 0.1732 * min(max(st - 950.0, 0.0), 100.0)          # a ramp: tan 60 x 20 / 200
        infos = [other_info(0)]
        model = make_model([other_point("SEEP-1 (NORTH BLUFF)", 1000.0, 0.0)], infos, z=z, step=2.0)
        s = make_settings()
        fig, p, page = drawn(model, s, dpi=150)
        ax = fig.axes[0]
        r = fig.canvas.get_renderer()
        x0, z0, kx, kz = frame_inches(ax)
        (t,) = by_gid(ax, F.OTHER_LABEL_GID)
        b = t.get_window_extent(r)
        fx0 = ax.get_window_extent(r).x0
        left, right = (b.x0 - fx0) / fig.dpi, (b.x1 - fx0) / fig.dpi
        base = (t.get_position()[1] - z0) * kz
        gx = [(st - x0) * kx for st in model.ground.stations]
        gy = [(g - z0) * kz for g in model.ground.z]
        top = max(S.stroke_top(gx, gy, R_GROUND, x) for x in [left, right] + [x for x in gx if left < x < right])
        self.assertGreaterEqual(base, top - R_GROUND + S.OTHER_LABEL_GROUND_IN - 1e-6)
        leaders = [ln for ln in ax.lines if ln.get_color() == F.LEADER and ln.get_linewidth() == 0.4]
        self.assertEqual(len(leaders), 1)
        # the plan reserved room for it
        self.assertGreaterEqual(p.z_max, S.other_label_top(model, s, p.plot_length) - 1e-9)

    def test_exploration_leaders_pass_behind_a_name(self):
        """Ten explorations up a slope, their labels spread with leaders: a seep's name among those leaders is
        boxed in white (drawn over them); a seep's name with no leader through it keeps its plain halo."""
        from xsections.core.model import Hit

        def z(st):
            return 300.0 + 0.05 * (st - 1000.0)
        hits = []
        for i in range(10):
            st = 1000.0 + 15.0 * i
            g = z(st)
            hits.append(Hit(fid=i + 1, label=f"EB-{i + 1:02d}", type_value="", x=0.0, y=0.0, station=st, offset=5.0,
                            side="L", direction="N", ground_at_station=g, ground_at_point=g, top=g, top_source="dem",
                            bottom=g - 20.0, total_depth=20.0))
        model = make_model([other_point("SEEP-1", 1037.0, 0.0), other_point("SEEP-2", 1500.0, 0.0)], [other_info(0)],
                           z=z, hits=hits)
        model.has_explorations = True
        fig, p, page = drawn(model, make_settings(), dpi=150)
        ax = fig.axes[0]
        halos = {t.get_text(): t for t in by_gid(ax, F.OTHER_LABEL_HALO_GID)}
        boxed = halos["SEEP-1"].get_bbox_patch()
        self.assertIsNotNone(boxed)
        self.assertEqual(tuple(boxed.get_facecolor()), (1.0, 1.0, 1.0, 1.0))
        self.assertIsNone(halos["SEEP-2"].get_bbox_patch())
        self.assertTrue(all(t.get_bbox_patch() is None for t in by_gid(ax, F.OTHER_LABEL_GID)))
        # drawn after the explorations' labels and leaders (the same zorder): over them
        names = [a for a in ax.get_children() if getattr(a, "get_text", None) and a.get_text().startswith("EB-")]
        kids = ax.get_children()
        self.assertGreater(kids.index(halos["SEEP-1"]), max(kids.index(a) for a in names))

    def test_notes_for_a_field_with_none_chosen(self):
        self.assertEqual(F._other_how(other_info(0, elev="field", elev_field="", elev_empty="lidar")),
                         ("at the LIDAR elevation at each point", "at LIDAR"))
        self.assertEqual(F._other_how(other_info(0, elev="field", elev_field="", elev_empty="line")),
                         ("on the ground line", "on the ground line"))
        infos = [other_info(0, "Springs", elev="field", elev_field="", elev_empty="lidar")]
        model = make_model([other_point("SP-1", 1000.0, 300.0, z=296.0, how="lidar", name="Springs")], infos)
        s = make_settings()
        p = plan(model, s)
        self.assertIn("Springs within 150 ft of the section line: at the LIDAR elevation at each point.",
                      F.notes_text(model, s, p, p.pages[0])[1][0])
        self.assertIn(F.NotePart("Springs: at LIDAR", 3), F.compact_notes(model, s, p, p.pages[0])[1])


class RestingCost(unittest.TestCase):
    """(FIX 0.3.3) Resting on a dense ground line: the cost does not grow with the ground's vertices under a symbol
    (the preview, drawn small, covers thousands of them); a sheet's centres stay exact."""

    @staticmethod
    def brute(gx, gy, x_c, caps, r, gap):
        """rest_on_line as it was: every segment of the line for every sample."""
        half_w, _, _ = S.symbol_extent(caps)
        dxs = {-half_w + 2.0 * half_w * i / 240.0 for i in range(241)}
        for c in caps:
            for px in (c.ax, c.bx):
                for d in (px - c.r, px, px + c.r, px - r, px + r):
                    if -half_w <= d <= half_w:
                        dxs.add(d)
        for x in gx:
            if math.isfinite(x) and -half_w <= x - x_c <= half_w:
                dxs.add(x - x_c)
        best = -math.inf
        for dx in dxs:
            t = S.stroke_top(gx, gy, r, x_c + dx)
            if t == -math.inf:
                continue
            low = min(S.capsule_bottom(c, dx) for c in caps)
            if low != math.inf:
                best = max(best, t - low)
        return None if best == -math.inf else best + gap

    def test_the_same_centres_on_a_sheet(self):
        rng = random.Random(7)
        for shape in SHAPES:
            caps = S.symbol_capsules(shape, 7.0)
            for _ in range(15):
                n = rng.randint(3, 60)
                gx = sorted(rng.uniform(-0.2, 0.2) for _ in range(n))
                gy = [rng.uniform(-0.05, 0.05) if rng.random() > 0.05 else math.nan for _ in range(n)]
                x_c = rng.uniform(-0.05, 0.05)
                want = self.brute(gx, gy, x_c, caps, R_GROUND, GAP)
                got = S.rest_on_line(gx, gy, x_c, caps, R_GROUND, GAP)
                if want is None:
                    self.assertIsNone(got)
                else:
                    self.assertAlmostEqual(got, want, places=12)
                thin = S.rest_on_line(gx, gy, x_c, caps, R_GROUND, GAP, thin=True)
                if want is not None:                                       # (sparse: nothing to thin)
                    self.assertAlmostEqual(thin, want, places=12)

    def test_ground_top_is_exact(self):
        """ground_top_fn: the highest point of the stroke over a span, as a dense sampling of stroke_top finds it."""
        rng = random.Random(3)
        for _ in range(40):
            n = rng.randint(2, 40)
            st = sorted(rng.uniform(0.0, 100.0) for _ in range(n))
            zs = [rng.uniform(0.0, 5.0) if rng.random() > 0.08 else None for _ in range(n)]
            top = S.ground_top_fn(st, zs, lambda v: v / 50.0, lambda v: v / 5.0)
            gx = [v / 50.0 for v in st]
            gy = [v / 5.0 if v is not None else math.nan for v in zs]
            for _ in range(5):
                a, b = sorted(rng.uniform(-0.1, 2.1) for _ in range(2))
                xs = [a + (b - a) * i / 400.0 for i in range(401)] + [x for x in gx if a < x < b]
                want = max(S.stroke_top(gx, gy, R_GROUND, x) for x in xs)
                got = top(a, b)
                if want == -math.inf:
                    self.assertEqual(got, -math.inf)
                else:
                    self.assertGreaterEqual(got, want - 1e-12)
                    self.assertLessEqual(got, want + 2e-4)              # (the sampling's resolution)

    @timing_test
    def test_preview_budget(self):
        """1 ft ground under three seeps resting on it, drawn small (k about 0.3, as the dock's preview at 1 in =
        1,000 ft): within half a second (it took 1.4 s, and more on longer lines; now about 0.08 s)."""
        import time
        infos = [other_info(0), other_info(1, "Deep", elev="field", elev_field="Z")]

        def z(st):
            return 300.0 + 8.0 * math.sin(st / 37.0) + 0.002 * st
        pts = [other_point(f"S-{i}", 700.0 + 800.0 * i, 0.0) for i in range(3)]
        pts.append(other_point("D-1", 1500.0, 300.0, z=0.0, how="field", j=1, name="Deep", field_value=0.0))
        model = make_model(pts, infos, z=z, step=1.0)                      # 3,001 ground vertices
        s = make_settings(h_scale=1000.0, v_scale=50.0)
        p = plan(model, s)
        F.draw_preview(Figure(figsize=(8.0, 3.0), dpi=100), model, s, p)     # (warm)
        t = time.perf_counter()
        placed = F.draw_preview(Figure(figsize=(8.0, 3.0), dpi=100), model, s, p)
        dt = time.perf_counter() - t
        print(f"\n  preview with 3 seeps on a 1 ft ground line: {dt:.3f} s")
        self.assertEqual(len(placed), 4)
        self.assertLessEqual(dt, budget(0.5))
        # the thinned centres: within a hair of the exact ones
        fig = Figure(figsize=(8.0, 3.0), dpi=100)
        exact = {}
        with mock.patch.object(S, "_thin_line", side_effect=lambda xs, ys, step: (list(xs), list(ys))):
            for pp in F.draw_preview(fig, model, s, p):
                exact[pp.index] = pp.z
        kz = fig.axes[0].get_position().height * 3.0 / (p.z_max - p.z_min)
        for pp in placed:
            self.assertAlmostEqual(pp.z, exact[pp.index], delta=0.001 / kz)   # 0.001 in on paper


if __name__ == "__main__":
    unittest.main()
