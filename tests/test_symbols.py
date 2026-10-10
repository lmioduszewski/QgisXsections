"""0.3.6 stage S: the symbol catalogue of Other points (render/symbols.py): the drop-down's groups, names and usual
colours; 0.3.5's six shapes kept exactly (frozen copies of their code below); unknown keys; every new symbol's
geometry and footprint; resting on the ground line (checked on the drawn artists); the benchmark centred on its
elevation; the spring's tail downhill; the artists, colours, legend swatches and the preview's cost (build spec
section 2, tests 8.1)."""
import math
import os
import random
import tempfile
import time
import unittest
from typing import List, NamedTuple, Tuple
from unittest import mock

from tests.fixtures import budget, start_app, timing_test

start_app()

import numpy as np                                                    # noqa: E402
from matplotlib.artist import Artist                                  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg          # noqa: E402
from matplotlib.colors import to_hex, to_rgba                         # noqa: E402
from matplotlib.figure import Figure                                  # noqa: E402
from matplotlib.lines import Line2D                                   # noqa: E402
from matplotlib.patches import Ellipse, Polygon                       # noqa: E402
from matplotlib.text import Text                                      # noqa: E402

from tests.test_other_points_render import (GAP, R_GROUND, by_gid, clearance, drawn, frame_inches,  # noqa: E402
                                            make_model, make_settings, other_info, other_point, seg_seg)
from xsections.core import model as M                                 # noqa: E402
from xsections.core.model import clean_other_point                    # noqa: E402
from xsections.render import figure as F                              # noqa: E402
from xsections.render import scales as S                              # noqa: E402
from xsections.render import symbols as SY                            # noqa: E402
from xsections.render.scales import plan                              # noqa: E402

BLUE, BLACK, RED, GREEN, GRAY = "#1f6fb2", "#111111", "#c62828", "#2e7d32", "#555555"
# the approved mockup's drop-down (symbols.html, CAT) with the user's amendment of 2026-10-10 (the asterisk, named
# "Asterisk", leads the general shapes): groups, order, names, usual colours
DROP_DOWN = [
    ("Water at the surface", [
        ("spring", "Spring", BLUE), ("thermal_spring", "Thermal or mineral spring", BLUE),
        ("stream", "Stream or creek crossing", BLUE), ("pond", "Pond, lake or reservoir", BLUE),
        ("wetland", "Wetland, marsh or bog", BLUE)]),
    ("Wells shown as points (no log)", [
        ("well", "Water well, use not known", BLACK), ("domestic", "Domestic well", BLACK),
        ("public", "Public supply well", BLACK), ("irrigation", "Irrigation well", BLACK),
        ("industrial", "Industrial well", BLACK), ("monitoring", "Monitoring well or piezometer", BLACK),
        ("observation", "Observation well", BLACK), ("pumping", "Pumping or extraction well", RED),
        ("artesian", "Flowing artesian well", BLACK), ("uic", "Drywell, injection or recharge well (UIC)", BLACK),
        ("unused", "Unused well", BLACK), ("destroyed", "Decommissioned or destroyed well", BLACK),
        ("gallery", "Infiltration gallery or trench", BLACK)]),
    ("Measurements and samples", [
        ("gauge", "Stream or lake gauge", BLUE), ("staff", "Staff gauge (stage only)", BLUE),
        ("wq", "Water-quality sample site", GREEN), ("sample", "Soil, sediment or rock sample", RED)]),
    ("Geology and survey", [
        ("outcrop", "Bedrock outcrop or exposure", GRAY), ("scarp", "Landslide head scarp", RED),
        ("benchmark", "Survey benchmark", BLACK)]),
    ("General shapes", [
        ("asterisk", "Asterisk", BLUE), ("circle", "Circle", BLUE), ("square", "Square", BLUE),
        ("diamond", "Diamond", BLUE), ("triangle", "Triangle", BLUE)]),
]
LEGACY = ("asterisk", "circle", "square", "diamond", "star", "triangle")
NEW = tuple(k for k in SY.CHOICE_KEYS if k not in LEGACY)          # the 25 symbols 0.3.6 adds
RESTING_NEW = tuple(k for k in NEW if k != "benchmark")


# ----------------------------------------------------------------------------- 0.3.5's code, frozen
# Verbatim copies of scales.symbol_half_pt, asterisk_width_pt, symbol_edge_pt, symbol_outline, symbol_capsules and
# figure._symbol_artists as they were before 0.3.6 (only renamed _old_*): the six shapes must stay exactly these.
_OLD_SYMBOL_EDGE_PT = 0.6
_OLD_ASTERISK_MIN_W_PT, _OLD_ASTERISK_W = 1.0, 0.42
_OLD_CIRCLE_SIDES = 48


class _OldCapsule(NamedTuple):
    ax: float
    ay: float
    bx: float
    by: float
    r: float


def _old_symbol_half_pt(size_pt: float, k: float = 1.0) -> float:
    """s of the symbol table: half the nominal size, points."""
    return float(size_pt) * k / 2.0


def _old_asterisk_width_pt(size_pt: float, k: float = 1.0) -> float:
    """Stroke width of the asterisk, points: bold, max(1 pt, 0.42 s)."""
    return max(_OLD_ASTERISK_MIN_W_PT * k, _OLD_ASTERISK_W * _old_symbol_half_pt(size_pt, k))


def _old_symbol_edge_pt(k: float = 1.0) -> float:
    """Width of the white edge round a filled shape, points."""
    return _OLD_SYMBOL_EDGE_PT * k


def _old_symbol_outline(shape: str, size_pt: float, k: float = 1.0) -> List[Tuple[float, float]]:
    s = _old_symbol_half_pt(size_pt, k) / 72.0
    if shape == "square":
        a = 0.85 * s
        return [(-a, -a), (a, -a), (a, a), (-a, a)]
    if shape == "diamond":
        a = 1.15 * s
        return [(0.0, a), (a, 0.0), (0.0, -a), (-a, 0.0)]
    if shape == "star":
        out = []
        for i in range(10):
            r = (0.45 if i % 2 else 1.2) * s
            t = math.radians(90.0 - 36.0 * i)
            out.append((r * math.cos(t), r * math.sin(t)))
        return out
    if shape == "triangle":
        return [(0.0, 1.1 * s), (1.1 * s, -0.8 * s), (-1.1 * s, -0.8 * s)]
    if shape == "circle":
        return [(s * math.cos(2 * math.pi * i / _OLD_CIRCLE_SIDES), s * math.sin(2 * math.pi * i / _OLD_CIRCLE_SIDES))
                for i in range(_OLD_CIRCLE_SIDES)]
    return []


def _old_symbol_capsules(shape: str, size_pt: float, k: float = 1.0) -> List[_OldCapsule]:
    s = _old_symbol_half_pt(size_pt, k) / 72.0
    if shape == "circle":
        return [_OldCapsule(0.0, 0.0, 0.0, 0.0, s + _old_symbol_edge_pt(k) / 2.0 / 72.0)]
    if shape not in ("square", "diamond", "star", "triangle"):          # the asterisk (and anything unknown)
        r = _old_asterisk_width_pt(size_pt, k) / 2.0 / 72.0
        a, h = 1.25 * s, 1.25 * s * math.sqrt(0.5)          # exact at 0 and 90 degrees (a true vertical stroke)
        return [_OldCapsule(-dx, -dy, dx, dy, r) for dx, dy in ((a, 0.0), (h, h), (0.0, a), (-h, h))]
    pts = _old_symbol_outline(shape, size_pt, k)
    r = _old_symbol_edge_pt(k) / 2.0 / 72.0
    return [_OldCapsule(pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1], r)
            for i in range(len(pts))]


def _old_symbol_artists(shape: str, size: float, k: float, color: str, cx: float, cy: float, sx: float, sy: float,
                        transform=None) -> list:
    kw = {} if transform is None else {"transform": transform}
    e = _old_symbol_edge_pt(k)
    if shape == "circle":
        r = _old_symbol_half_pt(size, k) / 72.0
        return [Ellipse((cx, cy), width=2.0 * r * sx, height=2.0 * r * sy, fc=color, ec="white", lw=e,
                        joinstyle="round", **kw)]
    outline = _old_symbol_outline(shape, size, k)
    if outline:
        return [Polygon([(cx + x * sx, cy + y * sy) for x, y in outline], closed=True, fc=color, ec="white", lw=e,
                        joinstyle="round", **kw)]
    xs: List[float] = []
    ys: List[float] = []
    for c in _old_symbol_capsules(shape, size, k):
        xs += [cx + c.ax * sx, cx + c.bx * sx, math.nan]
        ys += [cy + c.ay * sy, cy + c.by * sy, math.nan]
    return [Line2D(xs[:-1], ys[:-1], color=color, lw=_old_asterisk_width_pt(size, k), solid_capstyle="round",
                   solid_joinstyle="round", **kw)]


def artist_state(a):
    """What decides an artist's pixels (exact values, NaN positions included)."""
    tr = Artist.get_transform(a) if a.is_transform_set() else None
    if isinstance(a, Ellipse):
        return ("Ellipse", tuple(a.get_center()), a.get_width(), a.get_height(), tuple(a.get_facecolor()),
                tuple(a.get_edgecolor()), a.get_linewidth(), a.get_joinstyle(), tr)
    if isinstance(a, Polygon):
        return ("Polygon", tuple(map(tuple, a.get_xy())), tuple(a.get_facecolor()), tuple(a.get_edgecolor()),
                a.get_linewidth(), a.get_joinstyle(), tr)
    xs, ys = np.asarray(a.get_xdata(), float), np.asarray(a.get_ydata(), float)
    return ("Line2D", tuple(np.where(np.isnan(xs), -9e99, xs)), tuple(np.where(np.isnan(ys), -9e99, ys)),
            tuple(np.isnan(xs)), a.get_color(), a.get_linewidth(), a.get_solid_capstyle(), a.get_solid_joinstyle(),
            tr)


# ----------------------------------------------------------------------------- helpers
def direct_extent(prims):
    """(left, right, bottom, top) of the ink from the primitives themselves (independently of the capsules)."""
    xs, ys = [], []
    for p in prims:
        if isinstance(p, SY.Stroke):
            for x, y in zip(p.xs, p.ys):
                xs += [x - p.w / 2, x + p.w / 2]
                ys += [y - p.w / 2, y + p.w / 2]
        elif isinstance(p, SY.Ring):
            xs += [p.cx - p.r - p.w / 2, p.cx + p.r + p.w / 2]
            ys += [p.cy - p.r - p.w / 2, p.cy + p.r + p.w / 2]
        elif isinstance(p, SY.Dot):
            xs += [p.cx - p.r - p.edge / 2, p.cx + p.r + p.edge / 2]
            ys += [p.cy - p.r - p.edge / 2, p.cy + p.r + p.edge / 2]
        elif isinstance(p, SY.Fill):
            for x, y in p.pts:
                xs += [x - p.w / 2, x + p.w / 2]
                ys += [y - p.w / 2, y + p.w / 2]
        else:
            size = p.size_pt / 72.0
            adv = 0.611 * size
            xs += [p.x - adv, p.x] if p.ha == "right" else [p.x, p.x + adv]
            ys += [p.y, p.y + 0.729 * size]
    return min(xs), max(xs), min(ys), max(ys)


def station_of(a):
    """The data x an artist of a symbol is drawn about (to tell which point it belongs to)."""
    if isinstance(a, Ellipse):
        return a.get_center()[0]
    if isinstance(a, Line2D):
        return float(np.nanmean(np.asarray(a.get_xdata(), float)))
    if isinstance(a, Text):
        return a.get_position()[0]
    return float(np.mean([x for x, _ in a.get_xy()[:-1]]))


def per_point(ax, model):
    """{index in model.other_points: [its artists]} (the nearest station)."""
    stations = [p.station for p in model.other_points]
    out = {}
    for a in by_gid(ax, F.OTHER_GID):
        x = station_of(a)
        i = min(range(len(stations)), key=lambda j: abs(stations[j] - x))
        out.setdefault(i, []).append(a)
    return out


def catalogue_model(keys, z=300.0, length=3000.0, first=100.0, spacing=115.0, size=7.0, step=10.0):
    infos = [other_info(j, SY.symbol(k).name, shape=k, color=SY.usual_color(k), size=size) for j, k in enumerate(keys)]
    pts = [other_point(k, first + spacing * j, 300.0, j=j, name=SY.symbol(k).name) for j, k in enumerate(keys)]
    return make_model(pts, infos, z=z, length=length, step=step)


def brute_rest(gx, gy, x_c, caps, r, gap):
    """rest_on_line as it was before 0.3.3's fix: every segment of the line for every sample
    (test_other_points_render.RestingCost.brute)."""
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


def kind_of(p):
    return {SY.Stroke: "Line2D", SY.Ring: "Ellipse", SY.Dot: "Ellipse", SY.Fill: "Polygon", SY.Letter: "Text"}[type(p)]


def ink_box_in(arts):
    """(left, right, bottom, top) of legend artists drawn in figure inches."""
    xs, ys = [], []
    for a in arts:
        if isinstance(a, Line2D):
            h = a.get_linewidth() / 2.0 / 72.0
            for x, y in zip(a.get_xdata(), a.get_ydata()):
                if math.isfinite(x):
                    xs += [x - h, x + h]
                    ys += [y - h, y + h]
        elif isinstance(a, Ellipse):
            (cx, cy), h = a.get_center(), a.get_linewidth() / 2.0 / 72.0
            xs += [cx - a.get_width() / 2 - h, cx + a.get_width() / 2 + h]
            ys += [cy - a.get_height() / 2 - h, cy + a.get_height() / 2 + h]
        elif isinstance(a, Polygon):
            h = a.get_linewidth() / 2.0 / 72.0
            for x, y in a.get_xy():
                xs += [x - h, x + h]
                ys += [y - h, y + h]
        else:
            x, y = a.get_position()
            size = a.get_fontsize() / 72.0
            xs += [x - 0.611 * size, x] if a.get_ha() == "right" else [x, x + 0.611 * size]
            ys += [y, y + 0.729 * size]
    return min(xs), max(xs), min(ys), max(ys)


# ----------------------------------------------------------------------------- the catalogue
class Catalogue(unittest.TestCase):
    def test_the_drop_down(self):
        self.assertEqual([(g, [(s.key, s.name, s.color) for s in items]) for g, items in SY.grouped()], DROP_DOWN)
        self.assertEqual(SY.GROUPS, tuple(g for g, _ in DROP_DOWN))
        self.assertEqual(len(SY.CATALOGUE), 30)
        self.assertEqual(SY.CHOICE_KEYS, tuple(k for _, items in DROP_DOWN for k, _, _ in items))
        self.assertEqual(len(set(SY.CHOICE_KEYS)), 30)
        self.assertEqual((SY.BLUE, SY.BLACK, SY.RED, SY.GREEN, SY.GRAY), (BLUE, BLACK, RED, GREEN, GRAY))

    def test_the_asterisk_leads_the_general_shapes(self):
        # the user's amendment of 2026-10-10: only the group, the order and the name moved; key, colour, drawing and
        # the new point row's default stay
        groups = dict(SY.grouped())
        self.assertEqual(groups["Water at the surface"][0].key, "spring")
        self.assertNotIn("asterisk", [s.key for s in groups["Water at the surface"]])
        self.assertEqual([s.key for s in groups["General shapes"]],
                         ["asterisk", "circle", "square", "diamond", "triangle"])
        star = SY.SYMBOLS["asterisk"]
        self.assertEqual((star.name, star.group, star.color, star.rests, star.mirrors, star.legacy),
                         ("Asterisk", "General shapes", BLUE, True, False, False))
        self.assertIn("asterisk", SY.LEGACY_DRAWN)
        self.assertEqual(M.OTHER_POINT_DEFAULTS["shape"], "asterisk")
        self.assertEqual(M.feature_row("point")["shape"], "asterisk")

    def test_the_legacy_star_and_the_keys(self):
        star = SY.SYMBOLS["star"]
        self.assertEqual((star.name, star.group, star.color, star.legacy), ("Star", "", BLUE, True))
        self.assertNotIn("star", SY.CHOICE_KEYS)
        self.assertNotIn("star", [s.key for _, items in SY.grouped() for s in items])
        self.assertEqual(SY.LEGACY_KEYS, ("star",))
        self.assertEqual(SY.SHAPE_KEYS, SY.CHOICE_KEYS + ("star",))
        self.assertEqual(set(SY.SYMBOLS), set(SY.SHAPE_KEYS))
        self.assertEqual(SY.LEGACY_DRAWN, LEGACY)
        self.assertEqual(M.OTHER_SHAPES, SY.SHAPE_KEYS)
        self.assertFalse(any(s.legacy for s in SY.CATALOGUE))

    def test_resolve_and_colours(self):
        self.assertEqual(SY.FALLBACK_KEY, "circle")
        for bad in ("hexagon", "", None, 3, "Spring"):
            self.assertEqual(SY.resolve(bad), "circle", bad)
        for key in SY.SHAPE_KEYS:
            self.assertEqual(SY.resolve(key), key)
            self.assertIs(SY.symbol(key), SY.SYMBOLS[key])
        self.assertIs(SY.symbol("hexagon"), SY.SYMBOLS["circle"])
        want = {"Water at the surface": {BLUE}, "Wells shown as points (no log)": {BLACK, RED},
                "Measurements and samples": {BLUE, GREEN, RED}, "Geology and survey": {GRAY, RED, BLACK},
                "General shapes": {BLUE}}
        for g, items in SY.grouped():
            self.assertEqual({SY.usual_color(s.key) for s in items}, want[g], g)
        self.assertEqual((SY.usual_color("pumping"), SY.usual_color("scarp"), SY.usual_color("sample"),
                          SY.usual_color("wq"), SY.usual_color("outcrop")), (RED, RED, RED, GREEN, GRAY))
        self.assertEqual(SY.usual_color("hexagon"), BLUE)
        self.assertEqual([k for k in SY.SHAPE_KEYS if not SY.symbol(k).rests], ["benchmark"])
        self.assertEqual([k for k in SY.SHAPE_KEYS if SY.symbol(k).mirrors], ["spring", "thermal_spring"])

    def test_scales_keeps_its_names(self):
        """The geometry moved to render/symbols.py; scales.py imports it back (figure.py, the ui and the tests)."""
        for name in ("SYMBOL_EDGE_PT", "ASTERISK_MIN_W_PT", "ASTERISK_W", "LEGEND_SYMBOL_MAX_PT", "_CIRCLE_SIDES",
                     "Capsule", "symbol_half_pt", "asterisk_width_pt", "symbol_edge_pt", "symbol_outline",
                     "symbol_extent", "symbol_capsules"):
            self.assertIs(getattr(S, name), getattr(SY, name), name)
        self.assertEqual((S.SYMBOL_EDGE_PT, S.ASTERISK_MIN_W_PT, S.ASTERISK_W, S.LEGEND_SYMBOL_MAX_PT,
                          S._CIRCLE_SIDES), (0.6, 1.0, 0.42, 6.0, 48))
        self.assertEqual((S.GROUND_LW, S.OTHER_REST_GAP_PT, S.SPRING_FLAT_IN), (1.1, 0.1, 0.005))
        self.assertEqual(F.LEGEND_SYMBOL_GID, "xsections-legend-symbol")
        with open(S.__file__, encoding="utf-8") as fh:
            self.assertNotIn("anything unknown", fh.read())       # the silent asterisk branch is gone

    def test_cleaning(self):
        self.assertEqual(clean_other_point({"shape": "hexagon"})["shape"], "asterisk")    # as 0.3.5
        for key in SY.SHAPE_KEYS:
            self.assertEqual(clean_other_point({"layer_id": "x", "shape": key})["shape"], key)


# ----------------------------------------------------------------------------- 0.3.5's six, exactly
class LegacyIdentity(unittest.TestCase):
    def test_capsules_and_outlines(self):
        for shape in LEGACY:
            for size in (3.0, 7.0, 12.5, 20.0):
                for k in (1.0, 0.85, 0.3):
                    self.assertEqual(S.symbol_capsules(shape, size, k), _old_symbol_capsules(shape, size, k))
                    self.assertEqual(S.symbol_capsules(shape, size, k, True), _old_symbol_capsules(shape, size, k))
                    self.assertEqual(S.symbol_outline(shape, size, k), _old_symbol_outline(shape, size, k))
                    self.assertEqual(S.asterisk_width_pt(size, k), _old_asterisk_width_pt(size, k))
        for key in NEW + ("hexagon",):
            self.assertEqual(S.symbol_outline(key, 7.0), [])

    def test_artists(self):
        fig = Figure()
        T = fig.dpi_scale_trans
        for shape in LEGACY:
            for size in (3.0, 7.0, 12.5, 20.0):
                for k in (1.0, 0.85, 0.3):
                    for tr in (None, T):
                        args = (shape, size, k, "#c2185b", 1234.5, 301.25, 0.01, 0.2)
                        old = [artist_state(a) for a in _old_symbol_artists(*args, transform=tr)]
                        new = [artist_state(a) for a in F._symbol_artists(*args, transform=tr)]
                        self.assertEqual(new, old, (shape, size, k, tr is None))
                        flipped = [artist_state(a) for a in F._symbol_artists(*args, transform=tr, flip=True)]
                        self.assertEqual(flipped, old)


class UnknownKeys(unittest.TestCase):
    def test_the_fallback_is_the_circle(self):
        self.assertEqual(S.symbol_capsules("hexagon", 7.0), S.symbol_capsules("circle", 7.0))
        self.assertEqual(SY.glyph("hexagon", 7.0), SY.glyph("circle", 7.0))
        self.assertEqual(SY.glyph_capsules("hexagon", 7.0), SY.glyph_capsules("circle", 7.0))
        self.assertEqual(SY.glyph_bbox("hexagon", 7.0), SY.glyph_bbox("circle", 7.0))
        (art,) = F._symbol_artists("hexagon", 7.0, 1.0, BLUE, 10.0, 20.0, 1.0, 1.0)
        self.assertIsInstance(art, Ellipse)                       # never the asterisk's Line2D
        (circle,) = F._symbol_artists("circle", 7.0, 1.0, BLUE, 10.0, 20.0, 1.0, 1.0)
        self.assertEqual(artist_state(art), artist_state(circle))

    def test_a_hand_made_row_on_a_sheet_and_in_the_legend(self):
        info = other_info(0, "Odd")
        info.shape = "hexagon"                                    # never cleaned
        model = make_model([other_point("X-1", 1000.0, 300.0, name="Odd")], [info])
        fig, p, page = drawn(model, make_settings(sheet="custom"))
        (art,) = by_gid(fig.axes[0], F.OTHER_GID)
        self.assertIsInstance(art, Ellipse)
        legend = [a for a in fig.artists if isinstance(a, (Line2D, Ellipse, Polygon)) and a.get_gid() is None
                  and to_hex(a.get_facecolor() if not isinstance(a, Line2D) else a.get_color()) == BLUE]
        self.assertEqual([type(a) for a in legend], [Ellipse])


# ----------------------------------------------------------------------------- geometry
class Geometry(unittest.TestCase):
    S7 = 7.0 / 72.0

    def test_spot_values(self):
        S7 = self.S7
        (ring,) = SY.glyph("well", 7.0)
        self.assertAlmostEqual(ring.r, 0.35 * S7, places=15)
        self.assertAlmostEqual(ring.w, 0.7 / 72.0, places=15)
        ring, tail = SY.glyph("spring", 7.0)
        self.assertEqual(len(tail.xs), SY.WAVE_SEGMENTS + 1)
        self.assertAlmostEqual(tail.xs[0], ring.r, places=15)
        self.assertAlmostEqual(tail.xs[-1], ring.r + S7, places=15)
        self.assertEqual(tail.ys[0], 0.0)
        self.assertLess(tail.ys[1], 0.0)                          # it dips first
        low, up = SY.glyph("stream", 7.0)
        for a, b in zip(low.ys, up.ys):
            self.assertAlmostEqual(b - a, 0.22 * S7, places=15)
        self.assertAlmostEqual((max(low.ys) - min(low.ys)) / 2.0, 0.08 * S7, places=15)
        self.assertAlmostEqual(low.xs[0], -0.55 * S7, places=15)
        self.assertAlmostEqual(low.xs[-1], 0.55 * S7, places=15)
        bowl, water = SY.glyph("pond", 7.0)
        self.assertEqual(len(bowl.pts), SY.BOWL_SEGMENTS + 1)
        self.assertAlmostEqual(min(y for _, y in bowl.pts), -0.5 * S7, places=15)
        self.assertEqual((bowl.face, bowl.edge), ("tint", "color"))
        self.assertEqual(water.ys, (0.0, 0.0))
        self.assertAlmostEqual(water.xs[1], 0.7 * S7, places=15)
        wet = SY.glyph("wetland", 7.0)
        self.assertEqual(len(wet), 8)
        self.assertEqual(wet[0].ys, (0.0, 0.0))
        self.assertTrue(all(st.ys[0] == 0.0 and st.ys[1] > 0.0 for st in wet[1:6]))     # the fan of five
        self.assertAlmostEqual(wet[3].ys[1], 0.55 * S7, places=15)
        self.assertEqual(wet[3].xs[0], wet[3].xs[1])                                    # the centre one upright
        a, b = SY.glyph("benchmark", 7.0)
        h = 0.35 * S7 * math.sqrt(0.5)
        self.assertEqual((a.xs, a.ys, b.xs, b.ys), ((-h, h), (-h, h), (-h, h), (h, -h)))
        (tri,) = SY.glyph("gauge", 7.0)
        self.assertAlmostEqual(sum(x for x, _ in tri.pts), 0.0, places=15)              # the centroid
        self.assertAlmostEqual(sum(y for _, y in tri.pts), 0.0, places=15)
        (crag,) = SY.glyph("outcrop", 7.0)
        self.assertEqual((crag.pts[0][1], crag.pts[-1][1]), (0.0, 0.0))
        self.assertEqual((crag.face, crag.edge, crag.w), ("color", "white", 0.6 / 72.0))
        crown, *hachures = SY.glyph("scarp", 7.0)
        self.assertEqual(len(hachures), 3)
        self.assertTrue(all(st.ys == (0.3 * S7, 0.0) for st in hachures))               # feet at the origin
        self.assertEqual(SY.tint("#1f6fb2"), "#d2e2f0")
        self.assertEqual((SY.tint("#000000"), SY.tint("#ffffff")), ("#cccccc", "#ffffff"))

    def test_the_thermal_spring_letter(self):
        for size, want in ((3.0, 4.0), (7.0, 4.0), (8.0, 4.0), (20.0, 10.0)):
            letter = SY.glyph("thermal_spring", size)[-1]
            self.assertIsInstance(letter, SY.Letter)
            self.assertEqual((letter.text, letter.size_pt), ("T", want))
        letter = SY.glyph("thermal_spring", 7.0, 0.5)[-1]
        self.assertEqual(letter.size_pt, 2.0)                    # 4 pt x k (the preview)
        right = SY.glyph("thermal_spring", 7.0)
        left = SY.glyph("thermal_spring", 7.0, flip=True)
        self.assertLess(right[-1].x, 0.0)                         # opposite the tail
        self.assertEqual(right[-1].ha, "right")
        self.assertGreater(min(right[1].xs), 0.0)
        self.assertGreater(left[-1].x, 0.0)
        self.assertEqual(left[-1].ha, "left")
        self.assertLess(max(left[1].xs), 0.0)

    def test_thinnest_stroke_and_mirroring(self):
        (ring,) = SY.glyph("well", 3.0)
        self.assertEqual(ring.w, SY.MIN_STROKE_PT / 72.0)        # 0.1 x 3 pt is thinner
        (ring,) = SY.glyph("well", 7.0, 0.5)
        self.assertAlmostEqual(ring.w, max(0.6 * 0.5, 0.1 * 3.5) / 72.0, places=15)
        for key in SY.SHAPE_KEYS:
            if key in ("spring", "thermal_spring"):
                continue
            self.assertEqual(SY.glyph(key, 7.0, flip=True), SY.glyph(key, 7.0), key)
        ring, tail = SY.glyph("spring", 7.0)
        ring2, tail2 = SY.glyph("spring", 7.0, flip=True)
        self.assertEqual(ring, ring2)
        self.assertEqual(tail2.xs, tuple(-x for x in tail.xs))
        self.assertEqual(tail2.ys, tail.ys)

    def test_footprint_is_the_ink(self):
        counts = {"spring": 13, "thermal_spring": 15, "stream": 24, "pond": 18, "wetland": 8, "gallery": 12,
                  "gauge": 3, "staff": 4, "well": 1, "domestic": 1, "public": 1, "irrigation": 2, "industrial": 2,
                  "monitoring": 3, "observation": 2, "pumping": 2, "artesian": 4, "uic": 4, "unused": 2,
                  "destroyed": 3, "wq": 3, "sample": 1, "outcrop": 7, "scarp": 4, "benchmark": 2}
        for key in SY.CHOICE_KEYS + ("star",):
            for size, k, flip in ((7.0, 1.0, False), (3.0, 1.0, False), (20.0, 0.3, True), (12.5, 0.85, True)):
                prims = SY.glyph(key, size, k, flip)
                caps = SY.glyph_capsules(key, size, k, flip)
                left, right, bottom, top = direct_extent(prims)
                half_w, below, above = S.symbol_extent(caps)
                self.assertAlmostEqual(half_w, max(-left, right), delta=1e-12, msg=key)
                self.assertAlmostEqual(below, -bottom, delta=1e-12, msg=key)
                self.assertAlmostEqual(above, top, delta=1e-12, msg=key)
                for got, want in zip(SY.glyph_bbox(key, size, k, flip), (left, right, bottom, top)):
                    self.assertAlmostEqual(got, want, delta=1e-12, msg=key)
                if key in NEW:
                    self.assertEqual(S.symbol_capsules(key, size, k, flip), caps, key)
            if key in counts:
                self.assertEqual(len(SY.glyph_capsules(key, 7.0)), counts[key], key)
        self.assertEqual(sorted(counts), sorted(NEW))


# ----------------------------------------------------------------------------- resting on the ground line
class Resting(unittest.TestCase):
    def test_rest_on_a_flat_and_a_sloping_line(self):
        gx = [i * 0.01 for i in range(-60, 61)]
        for key in NEW:
            for flip in ((False, True) if SY.symbol(key).mirrors else (False,)):
                caps = S.symbol_capsules(key, 7.0, 1.0, flip)
                _, below, _ = S.symbol_extent(caps)
                y = S.rest_on_line(gx, [0.5] * len(gx), 0.0, caps, R_GROUND, GAP)
                self.assertAlmostEqual(y, 0.5 + R_GROUND + GAP + below, places=12, msg=key)
                gy = [0.6 * x for x in gx]
                y = S.rest_on_line(gx, gy, 0.013, caps, R_GROUND, GAP)
                moved = [S.Capsule(c.ax + 0.013, c.ay + y, c.bx + 0.013, c.by + y, c.r) for c in caps]
                d = min(seg_seg((c.ax, c.ay), (c.bx, c.by), (gx[i], gy[i]), (gx[i + 1], gy[i + 1])) - c.r
                        for c in moved for i in range(len(gx) - 1)) - R_GROUND
                self.assertGreaterEqual(d, -1e-6, key)
                self.assertLessEqual(d, GAP + 1e-6, key)

    def test_drawn_symbols_clear_the_ground_stroke(self):
        """Every new symbol on the ground line of a drawn sheet (VE 10, the plane and a 0.5 slope on paper): its
        lowest artist just clears the drawn ground stroke, none cuts into it (the springs' tails both ways)."""
        for name, z in (("plane", 300.0), ("slope", lambda s: 300.0 + 0.05 * s), ("fall", lambda s: 450.0 - 0.05 * s)):
            model = catalogue_model(RESTING_NEW, z=z)
            fig, p, page = drawn(model, make_settings(sheet="custom", show_notes=False))
            ax = fig.axes[0]
            groups = per_point(ax, model)
            self.assertEqual(len(groups), len(RESTING_NEW), name)
            for i, arts in groups.items():
                key = model.other_points[i].label
                cs = [clearance(a, ax) for a in arts if not isinstance(a, Text)]
                self.assertGreaterEqual(min(cs), -1e-5, f"{name} {key}: overlaps by {min(cs)}")
                self.assertLessEqual(min(cs), GAP + 1e-4, f"{name} {key}: floats {min(cs)}")

    def test_the_benchmark_marks_its_elevation(self):
        def z(s):
            return 300.0 + 0.05 * s
        infos = [other_info(0, "BM", shape="benchmark", color=BLACK), other_info(1, "BM L", shape="benchmark",
                                                                               color=BLACK, elev="lidar")]
        pts = [other_point("BM-1", 1000.0, 0.0, name="BM"),
               other_point("BM-2", 2000.0, z(2000.0), z=z(2000.0) + 4.0, how="lidar", j=1, name="BM L",
                           lidar=z(2000.0) + 4.0)]
        model = make_model(pts, infos, z=z)
        s = make_settings(sheet="custom")
        fig, p, page = drawn(model, s)
        ax = fig.axes[0]
        x0, z0, kx, kz = frame_inches(ax)
        groups = per_point(ax, model)
        _, below, above = S.symbol_extent(S.symbol_capsules("benchmark", 7.0))
        labels = {t.get_text(): t for t in by_gid(ax, F.OTHER_LABEL_GID)}
        for i, want in ((0, z(1000.0)), (1, z(2000.0) + 4.0)):
            arts = groups[i]
            self.assertEqual([type(a) for a in arts], [Line2D, Line2D])
            for a in arts:                                       # the cross point: both strokes' middle
                self.assertAlmostEqual(float(np.mean(a.get_xdata())), model.other_points[i].station, delta=1e-9)
                self.assertAlmostEqual(float(np.mean(a.get_ydata())), want, delta=1e-9)
            t = labels[model.other_points[i].label]
            self.assertGreaterEqual((t.get_position()[1] - z0) * kz, (want - z0) * kz + above + S.OTHER_LABEL_GAP_IN
                                    - 1e-9)
        # scales.other_centre_in: a non-resting symbol on the ground line is centred on it
        p0 = model.other_points[0]
        caps = S.symbol_capsules("benchmark", 7.0)
        y = S.other_centre_in(p0, caps, model.ground, lambda st: st / 200.0, lambda zz: zz / 20.0, 1 / 200.0,
                              rests=False)
        self.assertEqual(y, p0.z / 20.0)
        rested = S.other_centre_in(p0, caps, model.ground, lambda st: st / 200.0, lambda zz: zz / 20.0, 1 / 200.0)
        self.assertGreater(rested, y)


# ----------------------------------------------------------------------------- the spring's tail
class SpringTail(unittest.TestCase):
    def flip_on(self, z, key="spring", station=1500.0, gs=None):
        infos = [other_info(0, "Springs", shape=key)]
        zf = z if callable(z) else (lambda s: z)
        model = make_model([other_point("SP-1", station, zf(station), name="Springs")], infos, z=z)
        if gs is not None:
            model.other_points[0].ground_at_station = gs
        return S.symbol_flip(model, model.other_points[0], make_settings())

    def test_downhill(self):
        self.assertTrue(self.flip_on(lambda s: 300.0 + 0.05 * s))         # rises to the right: falls to the left
        self.assertFalse(self.flip_on(lambda s: 300.0 - 0.05 * s))
        self.assertTrue(self.flip_on(lambda s: 300.0 + 0.05 * s, key="thermal_spring"))
        self.assertFalse(self.flip_on(300.0))                              # flat: to the right (toward A')
        reach = 1.3 * 7.0 / 72.0 * 200.0                                  # ft, the tail's reach at sheet scale
        for paper, want in ((0.004, False), (0.006, True), (-0.006, False)):
            slope = paper * 20.0 / (2.0 * reach)
            self.assertEqual(self.flip_on(lambda s, m=slope: 300.0 + m * s), want, paper)
        for key in ("asterisk", "well", "stream", "circle", "hexagon"):    # only the springs mirror
            self.assertFalse(self.flip_on(lambda s: 300.0 + 0.05 * s, key=key), key)

    def test_a_side_in_a_dem_gap(self):
        def gap_right(m):
            return lambda s: math.nan if 1510.0 <= s <= 1600.0 else 300.0 + m * s
        self.assertTrue(self.flip_on(gap_right(0.05)))        # the left lower than the station's ground
        self.assertFalse(self.flip_on(gap_right(-0.05)))
        self.assertFalse(self.flip_on(lambda s: math.nan, gs=math.nan))   # nothing at all

    def test_the_same_on_every_sheet_tile_and_the_preview(self):
        def z(s):
            return 300.0 + 12.0 * math.sin(s / 300.0)
        infos = [other_info(0, "Springs", shape="spring"), other_info(1, "Thermal", shape="thermal_spring")]
        pts = [other_point(f"SP-{i}", 150.0 + 250.0 * i, 0.0, j=i % 2, name=("Springs", "Thermal")[i % 2])
               for i in range(23)]
        model = make_model(pts, infos, z=z, length=6000.0)
        s = make_settings(sheet="letter")
        p = plan(model, s)
        self.assertGreater(len(p.pages), 1)
        want = [S.symbol_flip(model, pt, s) for pt in model.other_points]
        self.assertIn(True, want)
        self.assertIn(False, want)
        seen = {}
        for page in p.pages:
            fig = Figure(dpi=72)
            F.draw_page(fig, model, s, p, page)
            self.check(fig.axes[0], model, want, seen, f"sheet {page.tile_index}")
        self.assertTrue(any(n > 1 for n in seen.values()))        # a spring drawn on two sheets (the overlap)
        prev = Figure(figsize=(9.0, 3.5), dpi=100)
        F.draw_preview(prev, model, s, p)
        self.check(prev.axes[0], model, want, {}, "preview")

    def check(self, ax, model, want, seen, what):
        for i, arts in per_point(ax, model).items():
            seen[i] = seen.get(i, 0) + 1
            (ring,) = [a for a in arts if isinstance(a, Ellipse)]
            (tail,) = [a for a in arts if isinstance(a, Line2D)]
            cx = ring.get_center()[0]
            xs = np.asarray(tail.get_xdata(), float)
            if want[i]:
                self.assertLessEqual(xs.max(), cx + 1e-9, f"{what}: {model.other_points[i].label}")
            else:
                self.assertGreaterEqual(xs.min(), cx - 1e-9, f"{what}: {model.other_points[i].label}")
            for t in arts:
                if isinstance(t, Text):                           # the "T" opposite the tail
                    self.assertEqual(t.get_position()[0] > cx, want[i], what)


# ----------------------------------------------------------------------------- the drawing
class Drawing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = catalogue_model(NEW)
        cls.s = make_settings(sheet="custom", show_notes=False)
        cls.fig, cls.plan, cls.page = drawn(cls.model, cls.s)

    def test_artists_per_key(self):
        ax = self.fig.axes[0]
        groups = per_point(ax, self.model)
        self.assertEqual(len(groups), len(NEW))
        white = to_rgba("white")
        for i, arts in groups.items():
            key = self.model.other_points[i].label
            color = to_rgba(SY.usual_color(key))
            prims = SY.glyph(key, 7.0, 1.0, S.symbol_flip(self.model, self.model.other_points[i], self.s))
            self.assertEqual(sorted(type(a).__name__ for a in arts), sorted(kind_of(g) for g in prims), key)
            for a in arts:
                self.assertEqual((a.get_gid(), a.get_zorder()), (F.OTHER_GID, F.POINT_Z), key)
            ells = [a for a in arts if isinstance(a, Ellipse)]
            rings = [g for g in prims if isinstance(g, SY.Ring)]
            for a in arts:
                if isinstance(a, Line2D):
                    self.assertEqual((to_rgba(a.get_color()), a.get_solid_capstyle(), a.get_solid_joinstyle()),
                                     (color, "round", "round"), key)
            ring_arts = [a for a in ells if tuple(a.get_facecolor()) == white]
            self.assertEqual(len(ring_arts), len(rings), key)                     # rings white inside
            for a in ring_arts:
                self.assertEqual(tuple(a.get_edgecolor()), color, key)
            for a in ells:
                if a not in ring_arts:
                    self.assertEqual(tuple(a.get_facecolor()), color, key)
            if key in ("domestic", "sample"):
                (dot,) = ells
                self.assertEqual((tuple(dot.get_edgecolor()), dot.get_linewidth(), dot.get_joinstyle()),
                                 (white, 0.6, "round"), key)
            if key in ("industrial", "pumping"):
                inner = [a for a in ells if a not in ring_arts]
                self.assertEqual([(a.get_linewidth(), a.get_edgecolor()[3]) for a in inner], [(0.0, 0.0)], key)
            if key == "outcrop":
                (crag,) = arts
                self.assertEqual((tuple(crag.get_facecolor()), tuple(crag.get_edgecolor()), crag.get_linewidth()),
                                 (color, white, 0.6))
            if key == "pond":
                (bowl,) = [a for a in arts if isinstance(a, Polygon)]
                self.assertEqual(to_hex(bowl.get_facecolor()), SY.tint(SY.usual_color(key)))
                self.assertEqual(tuple(bowl.get_edgecolor()), color)
            if key in ("gauge", "staff", "wq", "gallery"):
                for a in arts:
                    if isinstance(a, Polygon):
                        self.assertEqual((tuple(a.get_facecolor()), tuple(a.get_edgecolor())), (white, color), key)
            if key == "thermal_spring":
                (t,) = [a for a in arts if isinstance(a, Text)]
                self.assertEqual((t.get_text(), t.get_fontsize(), t.get_va(), to_rgba(t.get_color())),
                                 ("T", 4.0, "baseline", color))

    def test_a_300_dpi_png_shows_each_symbol_in_its_colour(self):
        from PIL import Image
        model = catalogue_model(SY.CHOICE_KEYS, length=3200.0, spacing=100.0)
        s = make_settings(sheet="custom", show_notes=False)
        p = plan(model, s)
        fig = Figure(dpi=300)
        FigureCanvasAgg(fig)
        F.draw_page(fig, model, s, p, p.pages[0])
        path = os.path.join(tempfile.mkdtemp(prefix="xsec_symbols_"), "catalogue.png")
        fig.savefig(path, dpi=300)
        img = np.asarray(Image.open(path).convert("RGB"))
        H = img.shape[0]
        r = fig.canvas.get_renderer()
        groups = per_point(fig.axes[0], model)
        self.assertEqual(len(groups), len(SY.CHOICE_KEYS))
        for i, arts in groups.items():
            key = model.other_points[i].label
            boxes = [a.get_window_extent(r) for a in arts]
            x0, x1 = int(min(b.x0 for b in boxes)) - 3, int(max(b.x1 for b in boxes)) + 3
            y0, y1 = int(min(b.y0 for b in boxes)) - 3, int(max(b.y1 for b in boxes)) + 3
            crop = img[max(H - y1, 0):H - y0, max(x0, 0):x1].astype(int)
            want = np.array([int(SY.usual_color(key)[j:j + 2], 16) for j in (1, 3, 5)])
            n = int((np.abs(crop - want).max(axis=-1) <= 3).sum())
            self.assertGreaterEqual(n, 20, f"{key}: {n} px of {SY.usual_color(key)}")

    def test_the_preview_draws_them(self):
        fig = Figure(figsize=(9.0, 3.5), dpi=100)
        placed = F.draw_preview(fig, self.model, self.s, self.plan)
        self.assertEqual([pp.index for pp in placed], list(range(len(NEW))))
        want = sum(len(SY.glyph(k, 7.0)) for k in NEW)
        self.assertEqual(len(by_gid(fig.axes[0], F.OTHER_GID)), want)
        for pp in placed:
            self.assertGreater(pp.half_w, 0.0)
            self.assertGreater(pp.label_top, pp.above)


# ----------------------------------------------------------------------------- the legend
class Legend(unittest.TestCase):
    def test_every_symbol_fits_the_swatch(self):
        """At LEGEND_SYMBOL_MAX_PT every ink box is at most SWATCH_IN wide and half as tall as the asterisk's depth
        reservation (standard_block_depth), so the legend rows need no change."""
        half = S.symbol_extent(S.symbol_capsules("asterisk", S.LEGEND_SYMBOL_MAX_PT))[1]
        self.assertAlmostEqual(half * 72.0, 4.38, places=2)
        for key in SY.SHAPE_KEYS:
            if key in LEGACY:
                hw, below, above = S.symbol_extent(S.symbol_capsules(key, S.LEGEND_SYMBOL_MAX_PT))
                self.assertLessEqual(2 * hw, S.SWATCH_IN, key)
                self.assertLessEqual(max(below, above), half + 1e-15, key)
            else:
                left, right, bottom, top = SY.glyph_bbox(key, S.LEGEND_SYMBOL_MAX_PT)
                self.assertLessEqual(right - left, S.SWATCH_IN, key)
                self.assertLessEqual((top - bottom) / 2.0, half, key)

    def swatches(self, model, s):
        """[(entry, x, y, its artists)] of the "point" legend swatches of a drawn sheet."""
        calls = []
        real = F.draw_swatch

        def record(fig, model_, settings, entry, x, y):
            n = len(fig.artists)
            real(fig, model_, settings, entry, x, y)
            calls.append((entry, x, y, fig.artists[n:]))
        with mock.patch.object(F, "draw_swatch", side_effect=record):
            drawn(model, s)
        return [c for c in calls if not isinstance(c[0], str) and c[0].kind == "point"]

    def test_swatches_on_a_sheet(self):
        """Every catalogue key and the star in the legend beside the bar (notes off), and a few in the standard
        layout's legend under the notes."""
        keys = SY.CHOICE_KEYS + ("star",)
        model = catalogue_model(keys, length=3800.0, size=9.0)
        points = self.swatches(model, make_settings(sheet="custom", show_notes=False))
        self.assertEqual([model.other_layers[e.key].shape for e, _, _, _ in points], list(keys))
        few = ("spring", "thermal_spring", "benchmark", "star", "circle")
        standard = catalogue_model(few, spacing=500.0, size=9.0)
        more = self.swatches(standard, make_settings(sheet="custom"))
        self.assertEqual([standard.other_layers[e.key].shape for e, _, _, _ in more], list(few))
        by_name = {sym.name: sym.key for sym in SY.SYMBOLS.values()}
        for entry, x, y, arts in points + more:
            key = by_name[entry.text]
            self.assertTrue(arts, key)
            if key in LEGACY:                                     # as 0.3.5: the origin at the swatch centre, no gid
                self.assertEqual([a.get_gid() for a in arts], [None], key)
                (a,) = arts
                want = [artist_state(o) for o in _old_symbol_artists(key, 6.0, 1.0, SY.usual_color(key),
                                                                    x + S.SWATCH_IN / 2.0, y, 1.0, 1.0,
                                                                    transform=a.get_figure().dpi_scale_trans)]
                self.assertEqual([artist_state(a)], want, key)
                continue
            self.assertEqual({a.get_gid() for a in arts}, {F.LEGEND_SYMBOL_GID}, key)
            self.assertEqual(len(arts), len(SY.glyph(key, 6.0)), key)
            left, right, bottom, top = ink_box_in(arts)
            self.assertAlmostEqual((left + right) / 2.0, x + S.SWATCH_IN / 2.0, delta=1e-9, msg=key)
            self.assertAlmostEqual((bottom + top) / 2.0, y, delta=1e-9, msg=key)
            self.assertGreaterEqual(left, x - 1e-12, key)
            self.assertLessEqual(right, x + S.SWATCH_IN + 1e-12, key)
            if key == "spring":                                   # its tail to the right
                (ring,) = [a for a in arts if isinstance(a, Ellipse)]
                (tail,) = [a for a in arts if isinstance(a, Line2D)]
                self.assertGreater(min(tail.get_xdata()), ring.get_center()[0])


# ----------------------------------------------------------------------------- cost
class Cost(unittest.TestCase):
    @timing_test
    def test_preview_budget(self):
        """test_other_points_render's 1 ft ground, with three springs and three streams resting on it (13 and 24
        capsules each), drawn small: within half a second."""
        infos = [other_info(0, "Springs", shape="spring"), other_info(1, "Streams", shape="stream")]

        def z(st):
            return 300.0 + 8.0 * math.sin(st / 37.0) + 0.002 * st
        pts = [other_point(f"S-{i}", 700.0 + 800.0 * i, 0.0, name="Springs") for i in range(3)]
        pts += [other_point(f"C-{i}", 1100.0 + 800.0 * i, 0.0, j=1, name="Streams") for i in range(3)]
        model = make_model(pts, infos, z=z, step=1.0)
        s = make_settings(h_scale=1000.0, v_scale=50.0)
        p = plan(model, s)
        F.draw_preview(Figure(figsize=(8.0, 3.0), dpi=100), model, s, p)     # (warm)
        t = time.perf_counter()
        placed = F.draw_preview(Figure(figsize=(8.0, 3.0), dpi=100), model, s, p)
        dt = time.perf_counter() - t
        print(f"\n  preview with 3 springs and 3 streams on a 1 ft ground line: {dt:.3f} s")
        self.assertEqual(len(placed), 6)
        self.assertLessEqual(dt, budget(0.5))

    def test_the_same_centres_on_a_sheet(self):
        """rest_on_line on a dense random line for the springs and the stream: as the brute force (every segment
        for every sample), thinned too."""
        rng = random.Random(11)
        for key in ("spring", "thermal_spring", "stream", "pond", "wetland", "gallery"):
            caps = S.symbol_capsules(key, 7.0)
            for _ in range(10):
                n = rng.randint(3, 60)
                gx = sorted(rng.uniform(-0.2, 0.2) for _ in range(n))
                gy = [rng.uniform(-0.05, 0.05) if rng.random() > 0.05 else math.nan for _ in range(n)]
                x_c = rng.uniform(-0.05, 0.05)
                want = brute_rest(gx, gy, x_c, caps, R_GROUND, GAP)
                got = S.rest_on_line(gx, gy, x_c, caps, R_GROUND, GAP)
                if want is None:
                    self.assertIsNone(got)
                else:
                    self.assertAlmostEqual(got, want, places=12)


if __name__ == "__main__":
    unittest.main()
