"""The Other points symbol catalogue (0.3.6): keys, drop-down names, groups, order and usual colours; the geometry of
every symbol in paper inches; its footprint as capsules.

Pure Python (math and typing only), so core/model.py, render/scales.py, render/figure.py and the ui can all import it.
Sizes in points, then paper inches (/ 72); y up; each symbol drawn about its origin, the point that marks its
elevation (at the LIDAR or a field). On the ground line every symbol but the benchmark rests on its lowest ink
(scales.rest_on_line), so the footprint is the exact ink as capsules (a segment thickened by a radius: a stroke with
round ends).

Sources (the 0.3.6 research):
- FGDC-STD-013-2006, Digital Cartographic Standard for Geologic Map Symbolization: wells 26.1, springs 26.2, gauges
  26.3, water-quality sites 26.4, infiltration gallery 26.7.7, landslide scarp 17.12, lakes and marsh 30.2, outcrop
  and sample locality 31.
- USGS Topographic Map Symbols: spring or seep, marsh or swamp, BM (vertical control).
- Common practice on hydrogeologic sections: the seep asterisk (the plugin's own), the stream crossing, the red
  pumping-well bullseye, the generic shapes.

Rules:
- The five generic shapes, the asterisk and the star (LEGACY_DRAWN) draw exactly as in 0.3.5: their symbol_outline,
  symbol_capsules and figure.py artists are 0.3.5's code. glyph() gives them as primitives too, for the icons only.
- The star is a legacy key (LEGACY_KEYS): kept on old rows and drawn, never offered in the drop-down.
- An unknown key draws FALLBACK_KEY (the circle) wherever it is drawn: one explicit fallback (resolve); stored rows
  are cleaned on load (core.model.clean_other_point), so only a hand-made object can meet it.
- The spring's tail is drawn mirrored (flip) where the ground falls to the left (scales.symbol_flip); the benchmark
  is centred on its elevation instead of resting (Symbol.rests).
"""
from __future__ import annotations

import math
from typing import Dict, List, NamedTuple, Sequence, Tuple, Union

# ----------------------------------------------------------------------------- the 0.3.5 symbols (from scales.py)
# s = size * k / 2 (pt): half the nominal size.
SYMBOL_EDGE_PT = 0.6                       # white edge of the filled shapes, pt (x k), round joins
ASTERISK_MIN_W_PT, ASTERISK_W = 1.0, 0.42  # asterisk stroke width: max(1 pt x k, 0.42 s) (bold)
LEGEND_SYMBOL_MAX_PT = 6.0                 # a legend swatch draws the symbol at most this size
_CIRCLE_SIDES = 48                         # symbol_outline of the circle: a polygon this fine (the swatch)


class Capsule(NamedTuple):
    """A segment from (ax, ay) to (bx, by) thickened by r (round ends), paper inches; a = b is a disc."""
    ax: float
    ay: float
    bx: float
    by: float
    r: float


def symbol_half_pt(size_pt: float, k: float = 1.0) -> float:
    """s of the symbol table: half the nominal size, points."""
    return float(size_pt) * k / 2.0


def asterisk_width_pt(size_pt: float, k: float = 1.0) -> float:
    """Stroke width of the asterisk, points: bold, max(1 pt, 0.42 s)."""
    return max(ASTERISK_MIN_W_PT * k, ASTERISK_W * symbol_half_pt(size_pt, k))


def symbol_edge_pt(k: float = 1.0) -> float:
    """Width of the white edge round a filled shape, points."""
    return SYMBOL_EDGE_PT * k


def symbol_outline(shape: str, size_pt: float, k: float = 1.0) -> List[Tuple[float, float]]:
    """Polygon vertices of a filled shape, paper inches from the centre (y up): square, diamond, star (10 vertices
    from the top, clockwise), triangle; the circle as a fine polygon (radius s). [] for the asterisk (strokes only:
    symbol_capsules)."""
    s = symbol_half_pt(size_pt, k) / 72.0
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
        return [(s * math.cos(2 * math.pi * i / _CIRCLE_SIDES), s * math.sin(2 * math.pi * i / _CIRCLE_SIDES))
                for i in range(_CIRCLE_SIDES)]
    return []


def symbol_capsules(shape: str, size_pt: float, k: float = 1.0, flip: bool = False) -> List[Capsule]:
    """The ink of a symbol as capsules, paper inches from its origin. LEGACY_DRAWN keys: 0.3.5's capsules (`flip`
    ignored). Asterisk: 4 strokes through the centre at 0, 45, 90 and 135 degrees, each from -1.25 s to +1.25 s
    (8 prongs), radius half the stroke width. Circle: one disc of radius s + e/2 (the fill plus its white edge). The
    other filled shapes: their edges, radius e/2 (e = the white edge; with round joins the ink is exactly the polygon
    plus these). Every other catalogue key: glyph_capsules; an unknown key FALLBACK_KEY's (the circle)."""
    shape = resolve(shape)
    s = symbol_half_pt(size_pt, k) / 72.0
    if shape == "circle":
        return [Capsule(0.0, 0.0, 0.0, 0.0, s + symbol_edge_pt(k) / 2.0 / 72.0)]
    if shape == "asterisk":
        r = asterisk_width_pt(size_pt, k) / 2.0 / 72.0
        a, h = 1.25 * s, 1.25 * s * math.sqrt(0.5)          # exact at 0 and 90 degrees (a true vertical stroke)
        return [Capsule(-dx, -dy, dx, dy, r) for dx, dy in ((a, 0.0), (h, h), (0.0, a), (-h, h))]
    if shape in ("square", "diamond", "star", "triangle"):
        pts = symbol_outline(shape, size_pt, k)
        r = symbol_edge_pt(k) / 2.0 / 72.0
        return [Capsule(pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1], r)
                for i in range(len(pts))]
    return glyph_capsules(shape, size_pt, k, flip)


def symbol_extent(caps: Sequence[Capsule]) -> Tuple[float, float, float]:
    """(half width, depth below the centre, height above it) of the ink, paper inches."""
    if not caps:
        return 0.0, 0.0, 0.0
    half_w = max(max(abs(c.ax), abs(c.bx)) + c.r for c in caps)
    below = max(c.r - min(c.ay, c.by) for c in caps)
    above = max(max(c.ay, c.by) + c.r for c in caps)
    return half_w, below, above


# ----------------------------------------------------------------------------- the catalogue
class Symbol(NamedTuple):
    key: str            # stored in a row's "shape"
    name: str           # the drop-down's name
    group: str          # one of GROUPS ("" for a legacy key)
    color: str          # its usual colour, "#rrggbb" (a new row's colour; the row's colour stays his to change)
    rests: bool = True  # on the ground line it rests on its lowest ink (False: the benchmark, centred on the line)
    mirrors: bool = False   # drawn mirrored where the ground falls to the left (the spring's tail)
    legacy: bool = False    # kept for old projects, never offered (the star)


BLUE, BLACK, RED, GREEN, GRAY = "#1f6fb2", "#111111", "#c62828", "#2e7d32", "#555555"   # the mockup's
GROUPS = ("Water at the surface", "Wells shown as points (no log)", "Measurements and samples",
          "Geology and survey", "General shapes")
_W, _P, _M, _G, _O = GROUPS

CATALOGUE: Tuple[Symbol, ...] = (                # the drop-down's choices, in its order
    Symbol("spring", "Spring", _W, BLUE, mirrors=True),
    Symbol("thermal_spring", "Thermal or mineral spring", _W, BLUE, mirrors=True),
    Symbol("stream", "Stream or creek crossing", _W, BLUE),
    Symbol("pond", "Pond, lake or reservoir", _W, BLUE),
    Symbol("wetland", "Wetland, marsh or bog", _W, BLUE),
    Symbol("well", "Water well, use not known", _P, BLACK),
    Symbol("domestic", "Domestic well", _P, BLACK),
    Symbol("public", "Public supply well", _P, BLACK),
    Symbol("irrigation", "Irrigation well", _P, BLACK),
    Symbol("industrial", "Industrial well", _P, BLACK),
    Symbol("monitoring", "Monitoring well or piezometer", _P, BLACK),
    Symbol("observation", "Observation well", _P, BLACK),
    Symbol("pumping", "Pumping or extraction well", _P, RED),
    Symbol("artesian", "Flowing artesian well", _P, BLACK),
    Symbol("uic", "Drywell, injection or recharge well (UIC)", _P, BLACK),
    Symbol("unused", "Unused well", _P, BLACK),
    Symbol("destroyed", "Decommissioned or destroyed well", _P, BLACK),
    Symbol("gallery", "Infiltration gallery or trench", _P, BLACK),
    Symbol("gauge", "Stream or lake gauge", _M, BLUE),
    Symbol("staff", "Staff gauge (stage only)", _M, BLUE),
    Symbol("wq", "Water-quality sample site", _M, GREEN),
    Symbol("sample", "Soil, sediment or rock sample", _M, RED),
    Symbol("outcrop", "Bedrock outcrop or exposure", _G, GRAY),
    Symbol("scarp", "Landslide head scarp", _G, RED),
    Symbol("benchmark", "Survey benchmark", _G, BLACK, rests=False),
    Symbol("asterisk", "Asterisk", _O, BLUE),      # 0.3.5's asterisk (the default of a new point row)
    Symbol("circle", "Circle", _O, BLUE),
    Symbol("square", "Square", _O, BLUE),
    Symbol("diamond", "Diamond", _O, BLUE),
    Symbol("triangle", "Triangle", _O, BLUE),
)
_LEGACY = (Symbol("star", "Star", "", BLUE, legacy=True),)
SYMBOLS: Dict[str, Symbol] = {s.key: s for s in CATALOGUE + _LEGACY}   # by key: the catalogue and the legacy star
CHOICE_KEYS = tuple(s.key for s in CATALOGUE)
LEGACY_KEYS = tuple(s.key for s in _LEGACY)    # ("star",)
SHAPE_KEYS = CHOICE_KEYS + LEGACY_KEYS         # every key a row may hold (model.OTHER_SHAPES)
LEGACY_DRAWN = ("asterisk", "circle", "square", "diamond", "star", "triangle")   # drawn by 0.3.5's own code
FALLBACK_KEY = "circle"                        # what an unknown key draws: explicit, never the asterisk


def resolve(key: object) -> str:
    """`key` when it is a symbol of SYMBOLS, else FALLBACK_KEY."""
    return key if isinstance(key, str) and key in SYMBOLS else FALLBACK_KEY


def symbol(key: object) -> Symbol:
    """The Symbol of `key` (FALLBACK_KEY's for an unknown key)."""
    return SYMBOLS[resolve(key)]


def usual_color(key: object) -> str:
    """The usual colour of `key`'s symbol, "#rrggbb" (a new row's colour)."""
    return symbol(key).color


def grouped() -> List[Tuple[str, List[Symbol]]]:
    """[(group, its choices in order)] for the grouped drop-down, in GROUPS' order (the legacy star is not offered)."""
    return [(g, [s for s in CATALOGUE if s.group == g]) for g in GROUPS]


# ----------------------------------------------------------------------------- geometry: primitives
class Stroke(NamedTuple):   # a polyline in the colour, w wide, round caps and joins
    xs: Tuple[float, ...]
    ys: Tuple[float, ...]
    w: float


class Ring(NamedTuple):     # an open circle: white inside, its stroke w wide in the colour (centred on radius r)
    cx: float
    cy: float
    r: float
    w: float


class Dot(NamedTuple):      # a filled disc in the colour; edge > 0: a white edge that wide (round), 0: none
    cx: float
    cy: float
    r: float
    edge: float


class Fill(NamedTuple):     # a filled polygon, round joins: face "color" | "white" | "tint"; edge "white" | "color"
    pts: Tuple[Tuple[float, float], ...]
    face: str
    edge: str
    w: float


class Letter(NamedTuple):   # one upright letter in the colour (DejaVu Sans), baseline at y; ha "right" | "left"
    x: float
    y: float
    text: str
    size_pt: float
    ha: str


Primitive = Union[Stroke, Ring, Dot, Fill, Letter]

MIN_STROKE_PT = 0.6         # thinnest stroke of a new symbol, pt (x k): research "at least 0.4-0.5 pt", mockup 0.9 px
WAVE_SEGMENTS = 12          # segments of a 1.5-wave line (the spring's tail, each line of the stream)
BOWL_SEGMENTS = 16          # segments of the pond's half ellipse
LETTER_MIN_PT = 4.0         # the thermal spring's "T" is never smaller (research: at least 4 pt)
LETTER_ADVANCE_EM, LETTER_CAP_EM = 0.611, 0.729   # DejaVu Sans "T": advance width, cap height (em)
POND_TINT = 0.2             # the pond's fill: its colour at 20 % on white (research: 20 % cyan)
_SIN20, _COS20 = math.sin(math.radians(20.0)), math.cos(math.radians(20.0))   # the arrows' open V


def tint(color: str, f: float = POND_TINT) -> str:
    """`color` ("#rrggbb") at `f` on white: each channel 255 - f * (255 - c), rounded."""
    c = color.lstrip("#")
    ch = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{int(round(255.0 - f * (255.0 - v))):02x}" for v in ch)


def _wave(n: int = WAVE_SEGMENTS) -> List[float]:
    return [i / float(n) for i in range(n + 1)]


def glyph(key: str, size_pt: float, k: float = 1.0, flip: bool = False) -> List[Primitive]:
    """The primitives of `key`'s symbol in drawing order, paper inches from its origin (y up), for a nominal size
    `size_pt` at scale `k` (the preview's pt_scale; 1 on a sheet). `flip`: mirrored (the springs only: the tail goes
    left, the "T" to the right). An unknown key: FALLBACK_KEY's. The LEGACY_DRAWN keys as primitives (the icons;
    sheets draw them with 0.3.5's artists)."""
    key = resolve(key)
    S = float(size_pt) * k / 72.0
    thin = MIN_STROKE_PT * k / 72.0
    e = symbol_edge_pt(k) / 72.0
    m = -1.0 if flip and symbol(key).mirrors else 1.0

    def w(f: float) -> float:
        return max(thin, f * S)

    if key == "asterisk":
        return [Stroke((c.ax, c.bx), (c.ay, c.by), 2.0 * c.r) for c in symbol_capsules("asterisk", size_pt, k)]
    if key == "circle":
        return [Dot(0.0, 0.0, symbol_half_pt(size_pt, k) / 72.0, e)]
    if key in ("square", "diamond", "triangle", "star"):
        return [Fill(tuple(symbol_outline(key, size_pt, k)), "color", "white", e)]
    if key in ("spring", "thermal_spring"):
        r, lw = 0.3 * S, w(0.1)
        out: List[Primitive] = [Ring(0.0, 0.0, r, lw),
                                Stroke(tuple(m * (r + 1.0 * S * t) for t in _wave()),
                                       tuple(-0.1 * S * math.sin(3.0 * math.pi * t) for t in _wave()), lw)]
        if key == "thermal_spring":             # upper left, or upper right when the tail goes left
            out.append(Letter(-m * (r + 0.05 * S), r - 0.05 * S, "T", max(0.5 * float(size_pt), LETTER_MIN_PT) * k,
                              "right" if m > 0 else "left"))
        return out
    if key == "stream":
        a, lw, W = 0.08 * S, w(0.09), 1.1 * S
        xs = tuple(-W / 2.0 + W * t for t in _wave())
        low = tuple(-0.11 * S + a * math.cos(3.0 * math.pi * t) for t in _wave())
        return [Stroke(xs, low, lw), Stroke(xs, tuple(y + 0.22 * S for y in low), lw)]
    if key == "pond":
        hw, d = 0.7 * S, 0.5 * S
        bowl = tuple((hw * math.cos(math.pi * i / BOWL_SEGMENTS), -d * math.sin(math.pi * i / BOWL_SEGMENTS))
                     for i in range(BOWL_SEGMENTS + 1))
        return [Fill(bowl, "tint", "color", w(0.08)), Stroke((-hw, hw), (0.0, 0.0), w(0.12))]
    if key == "wetland":
        lw = w(0.08)
        out = [Stroke((-0.5 * S, 0.5 * S), (0.0, 0.0), lw)]
        for i, (deg, L) in enumerate(((-40.0, 0.4), (-20.0, 0.5), (0.0, 0.55), (20.0, 0.5), (40.0, 0.4))):
            x0, a = -0.2 * S + 0.1 * S * i, math.radians(deg)
            out.append(Stroke((x0, x0 + L * S * math.sin(a)), (0.0, L * S * math.cos(a)), lw))
        return out + [Stroke((-0.85 * S, -0.62 * S), (0.0, 0.0), lw), Stroke((0.62 * S, 0.85 * S), (0.0, 0.0), lw)]
    if key == "well":
        return [Ring(0.0, 0.0, 0.35 * S, w(0.1))]
    if key == "domestic":
        return [Dot(0.0, 0.0, 0.375 * S, e)]
    if key == "public":
        lw = w(0.1425)                          # 0.19 x the 0.75 S diameter
        return [Ring(0.0, 0.0, 0.375 * S - lw / 2.0, lw)]
    if key == "irrigation":
        return [Ring(0.0, 0.0, 0.375 * S, w(0.1)), Ring(0.0, 0.0, 0.21 * S, w(0.075))]
    if key in ("industrial", "pumping"):        # the same bullseye (the mockup draws pumping as industrial, in red)
        return [Ring(0.0, 0.0, 0.375 * S, w(0.1)), Dot(0.0, 0.0, 0.21 * S, 0.0)]
    if key == "monitoring":
        r, lw = 0.275 * S, w(0.09)
        return [Stroke((-r - 0.25 * S, -r), (0.0, 0.0), lw), Stroke((r, r + 0.25 * S), (0.0, 0.0), lw),
                Ring(0.0, 0.0, r, lw)]
    if key == "observation":                    # a 45-degree bar, upper left to lower right
        h = 0.525 * S * math.sqrt(0.5)
        return [Ring(0.0, 0.0, 0.25 * S, w(0.1)), Stroke((-h, h), (h, -h), w(0.15))]
    if key in ("artesian", "uic"):              # an arrow rising from the circle | pointing down onto it
        r, lw, aw, b = 0.25 * S, w(0.1), w(0.07), 0.2 * S
        if key == "artesian":
            tip = r + 0.55 * S
            return [Ring(0.0, 0.0, r, lw), Stroke((0.0, 0.0), (r + lw / 2.0, tip), aw),
                    Stroke((-b * _SIN20, 0.0, b * _SIN20), (tip - b * _COS20, tip, tip - b * _COS20), aw)]
        tip = r + lw / 2.0
        return [Ring(0.0, 0.0, r, lw), Stroke((0.0, 0.0), (r + 0.65 * S, tip), aw),
                Stroke((-b * _SIN20, 0.0, b * _SIN20), (tip + b * _COS20, tip, tip + b * _COS20), aw)]
    if key == "unused":                         # a vertical bar through the circle
        return [Ring(0.0, 0.0, 0.25 * S, w(0.1)), Stroke((0.0, 0.0), (-0.525 * S, 0.525 * S), w(0.15))]
    if key == "destroyed":                      # an X through the circle
        h, lw = 0.525 * S * math.sqrt(0.5), w(0.1)
        return [Ring(0.0, 0.0, 0.25 * S, lw), Stroke((-h, h), (-h, h), lw), Stroke((-h, h), (h, -h), lw)]
    if key == "gallery":                        # three open squares in a row
        a, g, lw = 0.32 * S, 0.12 * S, w(0.06)
        out = []
        for i in (-1, 0, 1):
            c = i * (a + g)
            out.append(Fill(((c - a / 2.0, -a / 2.0), (c + a / 2.0, -a / 2.0), (c + a / 2.0, a / 2.0),
                             (c - a / 2.0, a / 2.0)), "white", "color", lw))
        return out
    if key in ("gauge", "staff", "wq"):         # equilateral triangles about their centroid
        h = 0.65 * S
        half = h / math.sqrt(3.0)
        if key == "wq":                         # tip down
            return [Fill(((-half, h / 3.0), (half, h / 3.0), (0.0, -2.0 * h / 3.0)), "white", "color", w(0.08))]
        out = [Fill(((0.0, 2.0 * h / 3.0), (half, -h / 3.0), (-half, -h / 3.0)), "white", "color", w(0.08))]
        if key == "staff":                      # a bar at half the height
            out.append(Stroke((-1.33 * half, 1.33 * half), (h / 6.0, h / 6.0), w(0.1)))
        return out
    if key == "sample":
        return [Dot(0.0, 0.0, 0.225 * S, e)]
    if key == "outcrop":                        # a solid crag on its base
        return [Fill(((-0.5 * S, 0.0), (-0.32 * S, 0.35 * S), (-0.12 * S, 0.22 * S), (0.05 * S, 0.55 * S),
                      (0.25 * S, 0.3 * S), (0.38 * S, 0.4 * S), (0.5 * S, 0.0)), "color", "white", e)]
    if key == "scarp":                          # the crown line with three hachures hanging to the origin
        lw, t = w(0.09), 0.3 * S
        return [Stroke((-0.5 * S, 0.5 * S), (t, t), lw)] + [Stroke((d * S, d * S), (t, 0.0), lw)
                                                           for d in (-0.33, 0.0, 0.33)]
    if key == "benchmark":                      # an x, 0.7 S tip to tip; its cross point marks the elevation
        h, lw = 0.35 * S * math.sqrt(0.5), w(0.1)
        return [Stroke((-h, h), (-h, h), lw), Stroke((-h, h), (h, -h), lw)]
    raise AssertionError(f"no geometry for the symbol {key!r}")      # (every key of SYMBOLS has one: a test)


def letter_box(p: Letter) -> Tuple[float, float, float, float]:
    """(left, right, bottom, top) of a Letter's box, paper inches: its advance width and cap height."""
    size = p.size_pt / 72.0
    adv = LETTER_ADVANCE_EM * size
    x0, x1 = (p.x - adv, p.x) if p.ha == "right" else (p.x, p.x + adv)
    return x0, x1, p.y, p.y + LETTER_CAP_EM * size


def primitive_capsules(p: Primitive) -> List[Capsule]:
    """The ink of one primitive as capsules (exact: strokes and fills have round caps and joins)."""
    if isinstance(p, Stroke):
        if len(p.xs) == 1:
            return [Capsule(p.xs[0], p.ys[0], p.xs[0], p.ys[0], p.w / 2.0)]
        return [Capsule(p.xs[i], p.ys[i], p.xs[i + 1], p.ys[i + 1], p.w / 2.0) for i in range(len(p.xs) - 1)]
    if isinstance(p, Ring):                     # its inside is white, opaque: ink as far as placement goes
        return [Capsule(p.cx, p.cy, p.cx, p.cy, p.r + p.w / 2.0)]
    if isinstance(p, Dot):
        return [Capsule(p.cx, p.cy, p.cx, p.cy, p.r + p.edge / 2.0)]
    if isinstance(p, Fill):                     # every edge, the closing one too
        n = len(p.pts)
        return [Capsule(p.pts[i][0], p.pts[i][1], p.pts[(i + 1) % n][0], p.pts[(i + 1) % n][1], p.w / 2.0)
                for i in range(n)]
    x0, x1, y0, y1 = letter_box(p)              # a Letter: the bottom and top of its box (r = 0: segments)
    return [Capsule(x0, y0, x1, y0, 0.0), Capsule(x0, y1, x1, y1, 0.0)]


def glyph_capsules(key: str, size_pt: float, k: float = 1.0, flip: bool = False) -> List[Capsule]:
    """The footprint of `key`'s symbol (glyph): its exact ink as capsules, paper inches from its origin, so resting,
    the extents, the label obstacles and the hover boxes stay exact. An unknown key: FALLBACK_KEY's."""
    return [c for p in glyph(key, size_pt, k, flip) for c in primitive_capsules(p)]


def glyph_bbox(key: str, size_pt: float, k: float = 1.0, flip: bool = False) -> Tuple[float, float, float, float]:
    """(left, right, bottom, top) of the ink of `key`'s symbol, paper inches from its origin: exact (the capsules'
    ends -/+ their radius)."""
    caps = glyph_capsules(key, size_pt, k, flip)
    return (min(min(c.ax, c.bx) - c.r for c in caps), max(max(c.ax, c.bx) + c.r for c in caps),
            min(min(c.ay, c.by) - c.r for c in caps), max(max(c.ay, c.by) + c.r for c in caps))
