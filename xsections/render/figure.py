"""Drawing: the exact-scale sheet (draw_page) and the dock preview (draw_preview).

matplotlib Figure API only (never pyplot). On a sheet the axes box is placed and sized in
inches from the PageLayout, and its limits are the page's distance range and the plan's
elevation range, so 1 in of paper is exactly h_scale ft across and v_scale ft up. Ticks,
labels, scale bars and notes are sized in points / inches of paper (ScaledTranslation on
fig.dpi_scale_trans), so they look the same at every scale.
"""
from __future__ import annotations

import bisect
import math
from functools import lru_cache
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
import matplotlib
from matplotlib import patheffects
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, Polygon, Rectangle
from matplotlib.text import Text
from matplotlib.textpath import TextToPath
from matplotlib.ticker import FuncFormatter, MultipleLocator, NullLocator
from matplotlib.transforms import ScaledTranslation, blended_transform_factory

from ..core.model import (DEPTH_LW_BLACK, DEPTH_LW_COLOR, GRID_PRESETS, LOOK_GRAY, Hit, PageLayout, Plan,
                          SectionModel, Settings, depth_widths, grid_spec, layer_view)
# LABEL_* are used by the tests through this module
from .scales import LABEL_GAP_IN, LABEL_PAD_IN, LABEL_ROW_IN, LABEL_SEP, LEADER_RISE_IN  # noqa: F401
# the ground line's width lives in scales.py (the other points rest on it); figure.GROUND_LW stays its name here
from .scales import (CLIP_ARROW_H_IN, CLIP_ARROW_HALF_IN, CLIP_ARROW_TIP_IN, CLIP_TD_BASE_IN, CLIP_TD_DX_IN,
                     GROUND_LW, LEGEND_SYMBOL_MAX_PT, PlacedPoint, asterisk_width_pt, frame_levels, frame_screen,
                     ground_top_fn, hit_in_range, mark_obstacles, td_page_layout,
                     other_centre_in, other_label_anchor, other_label_layout, other_symbol, runs_below,
                     symbol_capsules, symbol_edge_pt, symbol_extent, symbol_flip, symbol_half_pt, symbol_outline)
# the symbol catalogue (0.3.6): the geometry of every symbol beyond 0.3.5's own six
from .symbols import LEGACY_DRAWN, Dot, Fill, Letter, Ring, Stroke, glyph, glyph_bbox, resolve, symbol, tint
from .scales import (BRACKET_DX_IN, BRACKET_GAP_IN, WL_DX_IN, LEADER_DX_IN, LEADER_LW, LEADER_STEP_IN, MARK_EVERY_IN,
                     MARK_FIRST_IN, MARK_H_IN, MARK_HALF_IN, SCREEN_LW, WL_LABEL_GAP_IN, WL_LABEL_PT, WL_LINE_HALF_IN,
                     WL_LW, WL_TRI_H_IN, WL_TRI_HALF_IN, LegendEntry, legend_entries)
# the brackets of the polygon rows (0.3.6): scales.area_layout places them on the whole section
from .scales import (AREA_ARROW_HALF_IN, AREA_ARROW_IN, AREA_DASH_PT, AREA_EDGE_DASH_PT, AREA_EDGE_LW,
                     AREA_FRAME_GAP_IN, AREA_LABEL_GAP_IN, AREA_LW, AREA_PAD_IN, AREA_ROW_IN, AREA_TICK_IN, AreaFrame,
                     AreaSpot, area_band_in, area_layout)
from .scales import (AXIS_PAD_PT, AXIS_TICK_PT, AXIS_TITLE_PT, COL_GAP_IN, CROSSBAR_IN, END_DIR_PT, END_PT,
                     GROUND_CLEAR_IN, HBAR_DEPTH_IN, HBAR_H_IN, HBAR_LABEL_DY_IN, HBAR_LEN_IN, HBAR_NAME_DY_IN,
                     LABEL_PT, NOTES_MIN_W, NOTES_TOP_IN, NOTE_COMPACT_PT, NOTE_GAP_IN, NOTE_MIN_PT,
                     NOTE_NAME_MIN_CHARS, NOTE_PITCH_IN, NOTE_PT, NOTE_SPACING,
                     RASTER_SLACK, RENDER_SLACK_PT, SCALE_LABEL_PT, SCALE_NAME_PT, STD_END_GAP_IN, STD_END_PT,
                     STD_HEAD_DY_IN, STD_HEAD_PT, STD_LINE_DY_IN, STD_LINE_MIN_PT, STD_LINE_PT, STD_TITLE_RAISE_IN,
                     SUBTITLE_PT_COMPACT, SWATCH_GAP_IN, SWATCH_IN, TD_EDGE_IN,
                     TD_GAP_IN, TD_PAD_IN, TD_PT, TD_ROW_IN, TD_TEXT_H_IN, TEXT_DESCENT_EM, TICK_FROM_IN, TICK_TO_IN,
                     TITLE_PT_COMPACT, VBAR_LABEL_DX_IN, VBAR_W_IN, XTITLE_PAD_PT, YTITLE_GAP_PT, LabelSpot, bar_boxes,
                     bottom_band, clamp_centre, compact_rows_in, compass16, display_label, draws_depth_line,
                     draws_td_label, draws_top_cap, edge_in, elevation_label_width_in, engineer_face, fmt_in, fmt_num,
                     fmt_station, ground_test, hbar_extent_in, label_layout, legend_rows, mark_boxes,
                     notes_min_w, overlaps_any, pretty_label, ratio, stack_labels, td_text, tick_base, vbar_dx_in)
from .scales import spread_1d as _spread_1d
# the notes as text (render/notes.py, pure text: the plan sizes the standard layout's bottom from them); these names
# stay figure's API
from .notes import (NotePart, _draws_any_td, _hit_views, _merge_sources, _nb, _other_how,  # noqa: F401
                    _other_notes, compact_notes, depth_sources_short, depth_sources_text, grid_text, layer_views,
                    note_texts, screens_sources, surfaces_sources)

FONT = "DejaVu Sans"
# Everything that could move or resize the drawing is pinned here; used for drawing AND saving.
RC = {"font.family": "sans-serif", "font.sans-serif": [FONT], "font.size": 7.0,
      "savefig.bbox": "standard", "savefig.pad_inches": 0.0, "savefig.facecolor": "white",
      "figure.autolayout": False, "figure.constrained_layout.use": False,
      "pdf.fonttype": 42, "svg.fonttype": "none", "svg.hashsalt": "xsections",
      "path.simplify": False, "axes.unicode_minus": False, "text.usetex": False,
      # matplotlib's default, pinned: a dash pattern is multiplied by the line width (the grid's absolute dashes
      # divide by it; the bends, match lines, surface dashes and ground-gap dots are scaled patterns)
      "lines.scale_dashes": True}

# --- style (defaults suit colored pencil: light grid, black data, no fills)
# the grid presets (core.model.GRID_PRESETS; Custom: grid_spec): (minor, major) colours and the Green widths
GRID_COLORS = {k: (v[1][0], v[0][0]) for k, v in GRID_PRESETS.items()}
MAJOR_LW, MINOR_LW = GRID_PRESETS["green"][0][1], GRID_PRESETS["green"][1][1]
FRAME_LW = 0.9                    # the frame: 0.9 pt black whatever the grid (GROUND_LW = 1.1: scales.py)
GRID_DASH_PT = {"dash": (4.0, 2.0), "dot": (0.6, 1.6)}   # absolute, pt on paper (decision 23)
INK = "#000000"
DATA = "#2b2b2b"
# depth lines (Sheet style, depth_widths): Black and Gray rows at DEPTH_LW, Color rows at DEPTH_COLOR_LW (the defaults)
DEPTH_LW, DEPTH_COLOR_LW = DEPTH_LW_BLACK, DEPTH_LW_COLOR
LEGEND_LINE_GID = "xsections-legend-line"   # a layer / style legend swatch line (tests find them by it)
TICK_LW = 0.9                     # tick and label geometry (TICK_TO_IN, LABEL_PT ...) live in scales.py
CAP_GID, TD_GID, TD_HALO_GID = "xsections-top-cap", "xsections-td-label", "xsections-td-halo"   # tags for tests
LEADER = "#595959"
MATCH, OVERLAP_FILL = "#8b0000", "#f6e6e6"
MATCH_Z = 2.5                     # match line: over the grid and bends, under the ground and the data
MATCH_STEP_IN = 0.05              # a match note slides along its line in these steps to clear the marks
# drawing order: data lines 3.5 < TD halo < ground line < TD text < ticks 5 < labels 6 < match notes 8.
# The ground sits over the TD halo so that a label crossing it never cuts a gap in the ground line.
TD_HALO_Z, GROUND_Z, TD_Z = 4.4, 4.45, 4.5
HALO_PT = 2.0                     # stroke width of the white halo under TD labels and match notes
BEND = "#7b3294"
WARN = "#c2372d"                 # on-screen preview warnings only (nothing red is printed)
GROUND_FILL = "#efe8da"
GAP_NOTE = "#444444"
# NOTE_PITCH_IN (baseline to baseline inside a note), NOTE_GAP_IN (between notes) and NOTES_TOP_IN: scales.py (the
# plan sizes the standard layout's bottom margin from them)
# other surfaces (decision 15) and screens / water levels (decision 16)
SURFACE_DASHES: Dict[str, Any] = {"solid": "-", "dash": (0, (5.0, 2.5)), "dot": (0, (1.0, 1.6))}
SURFACE_Z, SCREEN_Z, WL_Z = 3.0, 3.6, 4.6     # surfaces under the data lines; water levels over the ground line
MARK_CLEAR_IN = 0.15                          # water-table marks keep this clear of explorations (paper inches)
WATER = "#1f6fb2"                             # the water level triangles (only they are blue)
SURFACE_GID, MARK_GID, SCREEN_GID, LEADER_GID = "xsections-surface", "xsections-mark", "xsections-screen", "xsections-leader"
WL_GID, ATD_GID, WL_LINE_GID, WL_TEXT_GID = "xsections-wl", "xsections-atd", "xsections-wl-line", "xsections-wl-text"
# 0.3.3: an exploration of a row out of the range that runs below the frame (scales.runs_below): its arrow and TD
CLIP_GID, CLIP_TD_GID, CLIP_TD_HALO_GID = "xsections-below-frame", "xsections-td-below", "xsections-td-below-halo"
# 0.3.3: other points (seeps, springs ...): symbol over the ground (4.45) and the water levels (4.6), under the ticks
POINT_Z = 4.8
OTHER_GID, OTHER_LEAD_GID = "xsections-other", "xsections-other-lead"
OTHER_LABEL_GID, OTHER_LABEL_HALO_GID = "xsections-other-label", "xsections-other-label-halo"
LEGEND_SYMBOL_GID = "xsections-legend-symbol"   # 0.3.6: a catalogue symbol's legend swatch (0.3.5's six keep no gid)
# 0.3.6: the brackets of the polygon rows: over the ground, data lines, points and ticks, under the labels (6); their
# edge lines over the grid and match lines, under the surfaces and data lines
AREA_Z, AREA_EDGE_Z = 5.5, 2.6
AREA_GID, AREA_EDGE_GID = "xsections-area", "xsections-area-edge"     # the line, ticks and arrows; the edge lines
AREA_LABEL_GID, AREA_LABEL_HALO_GID = "xsections-area-label", "xsections-area-label-halo"
LEGEND_AREA_GID = "xsections-legend-area"

_T2P = TextToPath()


@lru_cache(maxsize=64)
def _font(size: float, weight: str = "normal") -> FontProperties:
    return FontProperties(family=FONT, size=size, weight=weight)


def text_width_pt(s: str, size: float, weight: str = "normal") -> float:
    """Advance width of a single line of text, points."""
    w, _, _ = _T2P.get_text_width_height_descent(s, _font(size, weight), ismath=False)
    return float(w)


def text_height_pt(s: str, size: float, weight: str = "normal") -> float:
    """Height of a one-line text box as matplotlib lays it out (never less than that of "lp"), points."""
    _, h, _ = _T2P.get_text_width_height_descent(s, _font(size, weight), ismath=False)
    _, lp_h, _ = _T2P.get_text_width_height_descent("lp", _font(size, weight), ismath=False)
    return float(max(h, lp_h))


@lru_cache(maxsize=4)
def _agg(dpi: float):
    from matplotlib.backends.backend_agg import RendererAgg
    return RendererAgg(1, 1, dpi)


def ink_width_pt(fig: Optional[Figure], s: str, size: float, weight: str = "normal") -> float:
    """Width of one line of text as `fig` will draw it, points. Sheets for PDF and SVG are drawn at 72 dpi and
    keep the outline width; a raster sheet (a PNG, drawn at its own dpi) gets the larger of that and Agg's
    width at that dpi: Agg draws small type at whole pixel sizes, up to ~5 % wider at 150 dpi."""
    w = text_width_pt(s, size, weight)
    if fig is not None and abs(float(fig.dpi) - 72.0) > 1e-6:
        aw, _, _ = _agg(float(fig.dpi)).get_text_width_height_descent(s, _font(size, weight), ismath=False)
        w = max(w, aw * 72.0 / float(fig.dpi))
    return w


def wrap_text(text: str, size: float, width_in: float, fig: Optional[Figure] = None) -> List[str]:
    """Greedy word wrap on measured widths (as `fig` draws them, see ink_width_pt). Only ordinary spaces
    break (NBSP keeps words together)."""
    lines: List[str] = []
    cur = ""
    for word in text.split(" "):
        cand = word if not cur else cur + " " + word
        if not cur or ink_width_pt(fig, cand, size) / 72.0 <= width_in:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ----------------------------------------------------------------------------- public helpers
# display_label(hit, settings) is defined in scales.py (plan() sizes the label headroom with it)

def spread_1d(x: np.ndarray, sep: float) -> Tuple[np.ndarray, np.ndarray]:
    """Minimal-displacement 1-D spreading (scales.spread_1d) as numpy arrays: (positions, cluster id)."""
    pos, grp = _spread_1d([float(v) for v in np.asarray(x, float)], sep)
    return np.asarray(pos, float), np.asarray(grp, int)


def wl_text(w, settings: Settings) -> str:
    """The label beside a water level symbol: "652.8", "652.8 (6/12/2025)", or "" (labels off)."""
    if settings.wl_label not in ("elev", "elev_date"):
        return ""
    text = f"{w.elev:,.1f}"
    if settings.wl_label == "elev_date" and w.date:
        text += f" ({w.date})"
    return text


def _finite_num(v: Optional[float]) -> bool:
    return v is not None and math.isfinite(v)


def _mark_z(st: np.ndarray, z: np.ndarray, station: float) -> float:
    """A surface's elevation at `station` for a water-table mark (linear between its vertices; a step's upper edge
    at the step). The 0.3.0 rule, kept so the sheets never change. core.hover.z_on (the readout and the CSV) differs
    only at a vertex followed by nan, nan here (no mark where the line ends, nor on a lone vertex the line does not
    draw), and a rounding error past either end (no mark is that close to an end)."""
    if st.size == 0 or station < st[0] or station > st[-1]:
        return math.nan
    i = int(np.searchsorted(st, station, side="right")) - 1
    i = min(max(i, 0), st.size - 1)
    if i + 1 < st.size and st[i + 1] > st[i]:
        t = (station - st[i]) / (st[i + 1] - st[i])
        return float(z[i] + (z[i + 1] - z[i]) * t)
    return float(z[i])


def _locator(step: float) -> MultipleLocator:
    loc = MultipleLocator(step)
    loc.MAXTICKS = 1_000_000                       # default 1000 is too low for long sections
    return loc


def _multiples(lo: float, hi: float, step: float, skip: Optional[float] = None) -> List[float]:
    """Multiples of `step` strictly inside (lo, hi); drop those that are multiples of `skip`."""
    if step <= 0:
        return []
    k0, k1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
    out = []
    for k in range(k0, k1 + 1):
        v = k * step
        if abs(v - lo) < step * 1e-6 or abs(v - hi) < step * 1e-6:
            continue                                # the frame is there
        if skip and abs(v / skip - round(v / skip)) < 1e-6:
            continue
        out.append(v)
    return out


def _nice_mult(spacing_in: float, want_in: float) -> int:
    """Smallest 1-2-5 multiple m with spacing_in * m >= want_in."""
    if spacing_in <= 0:
        return 1
    for e in range(0, 9):
        for m in (1, 2, 5):
            if spacing_in * m * 10 ** e >= want_in - 1e-12:
                return m * 10 ** e
    return 10 ** 9


def _symbol_artists(shape: str, size: float, k: float, color: str, cx: float, cy: float, sx: float, sy: float,
                    transform=None, flip: bool = False) -> list:
    """The artists of an other-point symbol centred on its origin at (cx, cy), its paper inches scaled by (sx, sy)
    into the coordinates of `transform` (data: 1 / kx, 1 / kz; the figure's inches: 1, 1). An unknown key draws
    symbols.FALLBACK_KEY's (the circle). 0.3.5's six (symbols.LEGACY_DRAWN, scales.symbol_outline /
    symbol_capsules; `flip` ignored): filled shapes the colour with a white edge, round joins; the circle an Ellipse;
    the asterisk one line of NaN-separated strokes with round caps. Every other catalogue key: one artist per
    primitive of symbols.glyph (mirrored with `flip`), in its drawing order."""
    shape = resolve(shape)
    kw = {} if transform is None else {"transform": transform}
    if shape in LEGACY_DRAWN:
        e = symbol_edge_pt(k)
        if shape == "circle":
            r = symbol_half_pt(size, k) / 72.0
            return [Ellipse((cx, cy), width=2.0 * r * sx, height=2.0 * r * sy, fc=color, ec="white", lw=e,
                            joinstyle="round", **kw)]
        outline = symbol_outline(shape, size, k)
        if outline:
            return [Polygon([(cx + x * sx, cy + y * sy) for x, y in outline], closed=True, fc=color, ec="white", lw=e,
                            joinstyle="round", **kw)]
        xs: List[float] = []
        ys: List[float] = []
        for c in symbol_capsules(shape, size, k):
            xs += [cx + c.ax * sx, cx + c.bx * sx, math.nan]
            ys += [cy + c.ay * sy, cy + c.by * sy, math.nan]
        return [Line2D(xs[:-1], ys[:-1], color=color, lw=asterisk_width_pt(size, k), solid_capstyle="round",
                       solid_joinstyle="round", **kw)]
    out: list = []
    for g in glyph(shape, size, k, flip):
        if isinstance(g, Stroke):
            out.append(Line2D([cx + x * sx for x in g.xs], [cy + y * sy for y in g.ys], color=color, lw=g.w * 72.0,
                              solid_capstyle="round", solid_joinstyle="round", **kw))
        elif isinstance(g, Ring):                      # white inside
            out.append(Ellipse((cx + g.cx * sx, cy + g.cy * sy), width=2.0 * g.r * sx, height=2.0 * g.r * sy,
                               fc="white", ec=color, lw=g.w * 72.0, **kw))
        elif isinstance(g, Dot):
            out.append(Ellipse((cx + g.cx * sx, cy + g.cy * sy), width=2.0 * g.r * sx, height=2.0 * g.r * sy,
                               fc=color, ec="white" if g.edge else "none", lw=g.edge * 72.0, joinstyle="round", **kw))
        elif isinstance(g, Fill):
            face = color if g.face == "color" else "white" if g.face == "white" else tint(to_hex(color))
            out.append(Polygon([(cx + x * sx, cy + y * sy) for x, y in g.pts], closed=True, fc=face,
                               ec="white" if g.edge == "white" else color, lw=g.w * 72.0, joinstyle="round", **kw))
        elif isinstance(g, Letter):
            out.append(Text(cx + g.x * sx, cy + g.y * sy, g.text, fontsize=g.size_pt, ha=g.ha, va="baseline",
                            color=color, fontfamily=FONT, **kw))
    return out


# ----------------------------------------------------------------------------- the drawing
Box = Tuple[float, float, float, float]            # (left, right, bottom, top), paper inches from the frame


def _segment_in_box(x0: float, y0: float, x1: float, y1: float, box: Box) -> bool:
    """True when the segment (x0, y0)-(x1, y1) passes through the inside of `box` (Liang-Barsky clipping)."""
    left, right, bottom, top = box
    t0, t1 = 0.0, 1.0
    dx, dy = x1 - x0, y1 - y0
    for p, q in ((-dx, x0 - left), (dx, right - x0), (-dy, y0 - bottom), (dy, top - y0)):
        if abs(p) < 1e-15:
            if q <= 0.0:
                return False
            continue
        t = q / p
        if p < 0.0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 >= t1:
            return False
    return True


class _TdMark(NamedTuple):
    """A TD label that is not centred under its bottom bar: beside an out-of-range exploration's line, or beside
    the arrow of one that runs below the frame (paper inches from the frame's lower left)."""
    text: str
    x: float                           # anchor (ha)
    y: float                           # anchor (va)
    ha: str
    va: str
    box: Box                           # what it covers
    color: str
    gid: str
    halo_gid: str


class _Layout(NamedTuple):
    """Where the exploration marks go on one page (paper inches from the frame's lower left)."""
    hits: List[Hit]                    # the explorations drawn on this page
    ticked: List[Hit]                  # those whose tick is on the plot (a manual range can cut it off)
    x_in: List[float]                  # their stations
    base_in: List[float]               # their tick bases
    texts: List[str]                   # their labels
    spots: List[LabelSpot]             # where the labels go
    marks: List[Box]                   # ticks and labels
    td: List[Tuple[str, float, float, float, str]]   # TD labels under their bars: (text, centre x, top y, width, colour)
    side_td: List[_TdMark]             # the other TD labels (out-of-range rows)


class _PointMark(NamedTuple):
    """An other point on one page (paper inches from the frame's lower left)."""
    index: int                         # in model.other_points
    point: Any
    shape: str
    size: float
    color: str
    x: float                           # symbol centre
    y: float
    half_w: float
    below: float
    above: float
    text: str                          # its label
    spot: Optional[LabelSpot]          # where the label goes (None without one)
    flip: bool = False                 # drawn mirrored (a spring's tail pointing left, downhill: scales.symbol_flip)


class _AreaMark(NamedTuple):
    """The bracket of a polygon row's piece on one page (0.3.6; stations and elevations in data units)."""
    spot: AreaSpot
    color: str
    dashed: bool                       # its row's bracket_style is "dash"
    edges: str                         # its row's AREA_EDGES choice
    a: float                           # the stations of the part on this page
    b: float
    y: float                           # the line's elevation (above the frame: over z1)
    ends: List[Tuple[float, bool, float]]   # each true end on this page: (station, open: past A or A′, +1 for the
    #                                         start, -1 for the end: the way its arm goes back from an open end)
    label: Optional[Tuple[float, float, Box]]   # (centre station, bottom elevation, its box in paper inches from the
    #                                             frame's lower left), None: left out on this page


class _EndMark(NamedTuple):
    """An end letter, or its compass direction, above the frame."""
    text: str
    station: float
    dx_pt: float                       # offset from the end station, points
    dy_pt: float                       # offset above the frame top, points
    ha: str
    va: str
    size: float
    weight: str
    box: Box                           # paper inches: x from the frame's left, y up from the frame top


class _Painter:
    """Draws the section into one axes; shared by the sheet and the preview."""

    def __init__(self, fig: Figure, ax, model: SectionModel, settings: Settings, plan: Plan,
                 x0: float, x1: float, pt_scale: float = 1.0, preview: bool = False,
                 above_in: Optional[float] = None):
        self.fig, self.ax, self.model, self.s, self.plan = fig, ax, model, settings, plan
        self.x0, self.x1 = float(x0), float(x1)
        self.z0, self.z1 = float(plan.z_min), float(plan.z_max)
        self.k = pt_scale
        self.preview = preview
        self.compact = bool(settings.compact_layout) and not preview    # the preview keeps the standard marks
        self.edge = edge_in(settings)
        fw, fh = fig.get_size_inches()
        pos = ax.get_position()
        self.kx = pos.width * fw / (self.x1 - self.x0)     # paper inches per ft (exact on a sheet)
        self.kz = pos.height * fh / (self.z1 - self.z0)
        self.top_blend = blended_transform_factory(ax.transData, ax.transAxes)
        self._lay: Optional[_Layout] = None
        self._pts: Optional[List[_PointMark]] = None
        self._areas: Optional[List[_AreaMark]] = None
        # (0.3.6) the band of bracket rows over the frame, paper inches (the preview's marks shrink with k): the end
        # letters, BEND labels and titles stand above it. The plan's; the preview passes its own (draw_preview)
        band = float(getattr(plan, "above_in", 0.0) or 0.0) if above_in is None else float(above_in)
        self.above = band * self.k

    def _look(self, h: Hit) -> Tuple[str, Any, float, str]:
        """(line colour, line style, line width, ink) of an exploration: Black (DATA at the black width, black ink),
        Gray (LOOK_GRAY at the black width, gray ink) or Color (its symbol's colour at the Color width, black ink; a
        feature its style draws with no symbol: as Black). The widths are Sheet style's (depth_widths). The line, its
        bars, the dotted link to the ground and the arrow take the line colour; the tick, the label and the TD the
        ink."""
        black, color = depth_widths(self.s)
        look = getattr(h, "look", "black")
        if look == "gray":
            return LOOK_GRAY, "-", black, LOOK_GRAY
        if look == "color" and getattr(h, "color", ""):
            return h.color, "-", color, INK
        return DATA, "-", black, INK

    def _window(self) -> Tuple[float, float]:
        """The stations this page draws marks for: its range, less a hair at an inner tile edge (the neighbouring
        sheet shows what hugs the edge whole)."""
        eps = 1e-6 * max(1.0, self.x1 - self.x0)
        lo, hi = self.x0 - eps, self.x1 + eps
        edge_ft = 0.1 / self.kx
        if self.x0 > eps:
            lo = self.x0 + edge_ft
        if self.x1 < self.plan.plot_length - eps and self.x1 < self.model.length - eps:
            hi = self.x1 - edge_ft
        return lo, hi

    def up(self, inches: float):
        """Data coordinates shifted up by `inches` of paper."""
        return self.ax.transData + ScaledTranslation(0.0, inches, self.fig.dpi_scale_trans)

    # --- axes, labels, titles
    def setup_axes(self) -> None:
        ax, s, p, k = self.ax, self.s, self.plan, self.k
        ax.set_xlim(self.x0, self.x1)
        ax.set_ylim(self.z0, self.z1)
        ax.set_autoscale_on(False)
        ax.set_aspect("auto")
        ax.margins(0)
        ax.set_facecolor("white")
        for sp in ax.spines.values():
            sp.set_linewidth(FRAME_LW)
            sp.set_color(INK)
            sp.set_zorder(20)
        hx, vz = p.h_major, p.v_major
        if self.preview:                                   # keep labels readable when shrunk
            hx *= _nice_mult(p.h_major * self.kx, 0.6)
            vz *= _nice_mult(p.v_major * self.kz, 0.22)
        ax.xaxis.set_major_locator(_locator(hx))
        ax.yaxis.set_major_locator(_locator(vz))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_minor_locator(NullLocator())
        station = s.distance_labels == "station"
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt_station(v) if station else fmt_num(v)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt_num(v)))
        fs = LABEL_PT * k
        ax.tick_params(which="major", direction="out", length=AXIS_TICK_PT * k, width=0.6, pad=AXIS_PAD_PT * k,
                       labelsize=fs, color=INK, labelcolor=INK)
        ax.tick_params(axis="y", left=True, right=True, labelleft=True, labelright=True)
        ax.tick_params(axis="x", top=False, labeltop=False)
        datum = f" {s.vertical_datum}" if s.vertical_datum else ""
        ytitle = f"Elevation (ft{datum})"
        tfs = AXIS_TITLE_PT * k
        ax.set_xlabel("Station (ft)" if station else "Distance along section (ft)", fontsize=tfs,
                      labelpad=XTITLE_PAD_PT * k)
        # elevation titles clear of the widest tick label (tick + pad + labels + gap): on both sides, or on
        # the left only in the compact layout (the numbers stay on both sides)
        vals = [v * vz for v in range(math.ceil(self.z0 / vz - 1e-9), math.floor(self.z1 / vz + 1e-9) + 1)]
        wmax = max([text_width_pt(fmt_num(v), fs) for v in vals] or [0.0])
        off = (AXIS_TICK_PT + AXIS_PAD_PT + YTITLE_GAP_PT) * k + wmax
        off_left = off
        if not self.preview:            # on a sheet the left title must stay the printer edge from the page edge
            left_in = ax.get_position().x0 * self.fig.get_size_inches()[0]
            # (+ 1.5 pt: renderers lay the line out a little taller than the outline metrics)
            room = (left_in - self.edge) * 72.0 - text_height_pt(ytitle, tfs) - RENDER_SLACK_PT
            off_left = max(min(off, room), (AXIS_TICK_PT + AXIS_PAD_PT) * k + wmax + 0.5)
        ax.annotate(ytitle, xy=(0.0, 0.5), xycoords="axes fraction", xytext=(-off_left, 0),
                    textcoords="offset points", rotation=90, ha="right", va="center", fontsize=tfs,
                    annotation_clip=False)
        if not self.compact:
            ax.annotate(ytitle, xy=(1.0, 0.5), xycoords="axes fraction", xytext=(off, 0),
                        textcoords="offset points", rotation=270, ha="left", va="center", fontsize=tfs,
                        annotation_clip=False)

    # --- grid
    def grid(self) -> None:
        """The minor and major grid lines inside the frame, each set as one NaN-separated line: a preset's colours and
        widths, or the Custom ones (grid_spec), solid, dashed or dotted with absolute dash lengths (GRID_DASH_PT), or
        (0.3.7) "none": that set is not drawn. A None major set leaves a uniform minor grid (minor lines at the major
        positions too); the frame, the ticks and the axis numbers never depend on the style."""
        ax, p = self.ax, self.plan
        (maj_c, maj_w, maj_s), (min_c, min_w, min_s) = grid_spec(self.s)
        min_gap = 0.035 if self.preview else 0.0           # inches; preview drops lines that would merge
        for axis, lo, hi, minor, major, kk in (("x", self.x0, self.x1, p.h_minor, p.h_major, self.kx),
                                               ("y", self.z0, self.z1, p.v_minor, p.v_major, self.kz)):
            if maj_s == "none":     # 0.3.7: no majors; the minors alone, uniform (the major positions too). The preview
                #                     thins them as it thins majors (1-2-5 steps), so it still shows a grid (sheets:
                #                     every minor, min_gap 0)
                min_step = minor * (_nice_mult(minor * kk, min_gap) if min_gap else 1)
                majors, minors = [], (_multiples(lo, hi, min_step) if minor > 0 else [])
            else:                   # exactly the 0.3.6 lines (the goldens): majors, minors skipping them, and in the
                #                     preview "majors thinned -> no minors"
                maj_step = major * (_nice_mult(major * kk, min_gap) if min_gap else 1)
                majors = _multiples(lo, hi, maj_step)
                minors = _multiples(lo, hi, minor, skip=maj_step) if minor * kk >= min_gap and minor > 0 else []
                if maj_step != major:
                    minors = []
            for vals, (color, lw, style), z in ((minors, (min_c, min_w, min_s), 0.5),
                                                (majors, (maj_c, maj_w, maj_s), 0.6)):
                if not vals or style == "none":      # (0.3.7) GRID_DASH_PT has no "none": it would draw solid
                    continue
                a = np.repeat(np.asarray(vals, float), 3)
                a[2::3] = np.nan
                if axis == "x":
                    xs, ys = a, np.tile([self.z0, self.z1, np.nan], len(vals))
                else:
                    xs, ys = np.tile([self.x0, self.x1, np.nan], len(vals)), a
                kw = dict(color=color, lw=lw, solid_capstyle="butt", zorder=z)
                pat = GRID_DASH_PT.get(style)
                if pat:   # matplotlib multiplies a dash pattern by the width (lines.scale_dashes): divide here, so
                    #       it is absolute; each NaN-separated line starts its pattern again (a dash at the frame)
                    kw.update(ls=(0.0, tuple(v / lw for v in pat)), dash_capstyle="round" if style == "dot" else "butt")
                ax.add_line(Line2D(xs, ys, **kw))

    # --- ground
    def ground(self) -> None:
        ax, k = self.ax, self.k
        st = np.asarray(self.model.ground.stations, float)
        z = np.asarray(self.model.ground.z, float)
        if st.size == 0:
            return
        ok = ~np.isnan(z)
        # draw only this page's stretch (plus one sample each side) so tiled PDFs stay small
        i0 = max(int(np.searchsorted(st, self.x0, side="left")) - 1, 0)
        i1 = min(int(np.searchsorted(st, self.x1, side="right")) + 1, st.size)
        sv, zv, okv = st[i0:i1], z[i0:i1], ok[i0:i1]
        if self.s.shade_below and okv.any():
            ax.fill_between(sv, np.where(okv, zv, self.z0), self.z0, where=okv, color=GROUND_FILL, lw=0,
                            zorder=0.2, interpolate=False)
        ax.add_line(Line2D(sv, zv, color=INK, lw=GROUND_LW, solid_joinstyle="round", solid_capstyle="round",
                           zorder=GROUND_Z))
        # gaps: dotted link between the edges and a small note under it
        nan_idx = np.flatnonzero(~ok)
        if nan_idx.size == 0:
            return
        runs = np.split(nan_idx, np.flatnonzero(np.diff(nan_idx) > 1) + 1)
        for run in runs:
            i0, i1 = int(run[0]), int(run[-1])
            left = i0 - 1 if i0 > 0 else None
            right = i1 + 1 if i1 + 1 < st.size else None
            if left is not None and right is not None:
                xa, za, xb, zb = st[left], z[left], st[right], z[right]
                ax.add_line(Line2D([xa, xb], [za, zb], color=INK, lw=0.6, ls=(0, (1, 1.6)), zorder=GROUND_Z))
                xm, zm = (xa + xb) / 2.0, min(za, zb)          # under the lower edge: clear of ticks above
            else:
                j = left if left is not None else right
                if j is None:
                    continue
                xm, zm = (st[i0] + st[i1]) / 2.0, z[j]
            if not (self.x0 <= xm <= self.x1):
                continue
            ax.annotate("NO DEM DATA", (xm, zm), xycoords="data", xytext=(0, -3 * k), textcoords="offset points",
                        ha="center", va="top", fontsize=5.5 * k, color=GAP_NOTE, zorder=4)

    # --- bends
    def bends(self) -> None:
        """A dashed line at each bend and "BEND" above the frame. A label that would overlap an end letter
        or the BEND label before it is left out (its line stays)."""
        if not self.s.show_bends:
            return
        ax, k = self.ax, self.k
        taken = [m.box for m in self.end_marks()]
        half_w, lo, hi = text_width_pt("BEND", 5.5 * k) / 144.0, 2 * k / 72.0, 7.5 * k / 72.0
        dy = 2 * k
        if self.above > 0.0:                               # over the band of bracket rows (0.3.6)
            lo, hi, dy = lo + self.above, hi + self.above, dy + self.above * 72.0
        for b in self.model.bend_stations:
            if self.x0 < b < self.x1:
                ax.add_line(Line2D([b, b], [self.z0, self.z1], color=BEND, lw=0.6, ls=(0, (4, 3)), zorder=1))
                x = self._x_in(b)
                box = (x - half_w, x + half_w, lo, hi)
                if overlaps_any(taken, *box):
                    continue
                taken.append(box)
                ax.annotate("BEND", (b, 1.0), xycoords=self.top_blend, xytext=(0, dy), textcoords="offset points",
                            ha="center", va="bottom", fontsize=5.5 * k, color=BEND, annotation_clip=False)

    # --- explorations
    def layout(self) -> _Layout:
        """Ticks, exploration labels and TD labels of this page (worked out once: the match notes keep
        clear of them). Labels are laid out as scales.plan() expects (scales.label_layout)."""
        if self._lay is not None:
            return self._lay
        s, k = self.s, self.k
        # at an inner tile edge, leave hits hugging the edge to the neighbouring sheet (it shows them whole)
        lo, hi = self._window()
        hits = [h for h in self.model.hits if lo <= h.station <= hi]
        # ticks and labels are drawn outside the clip box, so leave out any whose tick base is off
        # the plot (a manual elevation range can cut it off; the plan warns about it)
        tol = 1e-9 * max(1.0, abs(self.z1 - self.z0))
        ticked = [h for h in hits if not math.isnan(tick_base(h, s)) and
                  self.z0 - tol <= tick_base(h, s) <= self.z1 + tol]
        x_in = [(h.station - self.x0) * self.kx for h in ticked]
        base_in = [(tick_base(h, s) - self.z0) * self.kz for h in ticked]
        texts = [display_label(h, s) for h in ticked]
        widths = [text_width_pt(t, LABEL_PT * k) / 72.0 for t in texts]
        spots = label_layout(x_in, [b + TICK_TO_IN * k for b in base_in], widths, s.label_vertical, k,
                             self.ax_width_in())
        marks = mark_boxes(x_in, base_in, spots, k)
        td, side_td = self._td_layout(hits, marks)
        self._lay = _Layout(hits, ticked, x_in, base_in, texts, spots, marks, td, side_td)
        return self._lay

    def _td_layout(self, hits: List[Hit], marks: List[Box]
                   ) -> Tuple[List[Tuple[str, float, float, float, str]], List[_TdMark]]:
        """ "TD 50'" centred under each bottom bar; the TD of an exploration of a row out of the range beside its line
        when it has no row under it, or beside its arrow when it runs below the frame (scales.td_page_layout, which
        the plan checks too: a label with no spot is left out, and the plan warns about it). A label is never drawn
        outside the plot frame."""
        s, k = self.s, self.k
        crosses = ground_test(self.model.ground, lambda x: self.x0 + x / self.kx, self._z_in, GROUND_CLEAR_IN * k)
        placed, _left_out = td_page_layout(hits, s, self._x_in, self._z_in, k, self.ax_width_in(), 0.0,
                                           (self.z1 - self.z0) * self.kz, self.z0,
                                           lambda t: text_width_pt(t, TD_PT * k) / 72.0, marks, crosses)
        out: List[Tuple[str, float, float, float, str]] = []
        side: List[_TdMark] = []
        for t in placed:
            ink = self._look(t.hit)[3]
            if t.kind == "under":
                out.append((t.text, t.x, t.y, t.w, ink))
            elif t.kind == "side":
                side.append(_TdMark(t.text, t.x, t.y, t.ha, "center", t.box, ink, TD_GID, TD_HALO_GID))
            else:
                side.append(_TdMark(t.text, t.x, t.y, t.ha, "baseline", t.box, ink, CLIP_TD_GID, CLIP_TD_HALO_GID))
        return out, side

    def _x_in(self, station: float) -> float:
        return (station - self.x0) * self.kx

    def _z_in(self, z: float) -> float:
        return (z - self.z0) * self.kz

    def hits(self) -> None:
        ax, s, k = self.ax, self.s, self.k
        lay = self.layout()
        if not lay.hits:
            return
        # the first row's lines on top: drawn last (rows in descending order; one row: station order as always)
        for h in sorted(lay.hits, key=lambda h: -getattr(h, "layer_index", 0)):
            if not draws_depth_line(h, s):
                continue
            color, ls, lw, _ = self._look(h)
            below = runs_below(h, self.z0, s)               # out of the range and deeper: stops at the frame
            ax.add_line(Line2D([h.station, h.station], [h.top, self.z0 if below else h.bottom], color=color, lw=lw,
                               ls=ls, solid_capstyle="butt", dash_capstyle="butt", zorder=3.5))
            # the bar at the bottom, and the same bar at the top when the top is off the ground line
            if below:
                ends = [h.top] if draws_top_cap(h, s) else []
            else:
                ends = [h.bottom, h.top] if draws_top_cap(h, s) else [h.bottom]
            if ends:
                ax.plot([h.station] * len(ends), ends, ls="none", marker="_", ms=CROSSBAR_IN * 72 * k, mew=lw,
                        color=color, zorder=3.5, gid=CAP_GID if len(ends) == 2 or below else None)
            g = h.ground_at_station
            if g is not None and not math.isnan(g) and (g - h.top) / s.v_scale > 0.05:
                ax.add_line(Line2D([h.station, h.station], [g, h.top], color=color, lw=0.6,
                                   ls=(0, (1, 1.5)), zorder=3.4))
            if below:                                       # a small arrow, its tip just above the frame bottom
                fx, fz = k / self.kx, k / self.kz
                tip, top = self.z0 + CLIP_ARROW_TIP_IN * fz, self.z0 + (CLIP_ARROW_TIP_IN + CLIP_ARROW_H_IN) * fz
                ax.add_line(Line2D([h.station - CLIP_ARROW_HALF_IN * fx, h.station, h.station + CLIP_ARROW_HALF_IN * fx],
                                   [top, tip, top], color=color, lw=lw, solid_joinstyle="miter",
                                   solid_capstyle="butt", zorder=3.5, gid=CLIP_GID))
        # TD labels: a thin white halo (an outline copy underneath) keeps a label legible where a
        # neighbour's line or the grid runs through it; the copy on top stays real text in the PDF
        for text, x, y, _, color in lay.td:
            kw = dict(x=self.x0 + x / self.kx, y=self.z0 + y / self.kz, s=text, ha="center", va="top",
                      fontsize=TD_PT * k, color=color)
            ax.text(zorder=TD_HALO_Z, gid=TD_HALO_GID,
                    path_effects=[patheffects.Stroke(linewidth=HALO_PT * k, foreground="white")], **kw)
            ax.text(zorder=TD_Z, gid=TD_GID, **kw)
        for m in lay.side_td:
            kw = dict(x=self.x0 + m.x / self.kx, y=self.z0 + m.y / self.kz, s=m.text, ha=m.ha, va=m.va,
                      fontsize=TD_PT * k, color=m.color)
            ax.text(zorder=TD_HALO_Z, gid=m.halo_gid,
                    path_effects=[patheffects.Stroke(linewidth=HALO_PT * k, foreground="white")], **kw)
            ax.text(zorder=TD_Z, gid=m.gid, **kw)
        if not lay.ticked:
            return
        st = np.array([h.station for h in lay.ticked], float)
        base = np.array([tick_base(h, s) for h in lay.ticked], float)
        inks = [self._look(h)[3] for h in lay.ticked]
        tick_len = (TICK_TO_IN - TICK_FROM_IN) * k
        groups = [INK] + [c for c in dict.fromkeys(inks) if c != INK]   # one call per ink, black first
        for c in groups:
            idx = [j for j, ink in enumerate(inks) if ink == c]
            if not idx:
                continue
            sel = slice(None) if len(idx) == len(inks) else idx
            ax.plot(st[sel], base[sel], ls="none", marker="|", ms=tick_len * 72, mew=TICK_LW, color=c, clip_on=False,
                    transform=self.up((TICK_FROM_IN + TICK_TO_IN) / 2 * k), zorder=5)
        fs = LABEL_PT * k
        anchor = self.up(TICK_TO_IN * k)
        rotation = 90 if s.label_vertical else 0
        for j, spot in enumerate(lay.spots):
            tick_top = lay.base_in[j] + TICK_TO_IN * k
            self._label(lay.texts[j], st[j], base[j], anchor, (spot.x - lay.x_in[j]) * 72,
                        (spot.base - tick_top) * 72, rotation, spot.moved, fs, inks[j])

    def ax_width_in(self) -> float:
        return (self.x1 - self.x0) * self.kx

    # --- other surfaces
    def surfaces(self) -> None:
        """Each other surface as a line in its colour and style (clipped at the frame); water-table marks
        (an open triangle, tip on the line) every MARK_EVERY_IN of paper when asked for."""
        ax, k = self.ax, self.k
        for sp in getattr(self.model, "surfaces", None) or []:
            st = np.asarray(sp.stations, float)
            z = np.asarray(sp.z, float)
            if st.size < 2:
                continue
            i0 = max(int(np.searchsorted(st, self.x0, side="left")) - 1, 0)
            i1 = min(int(np.searchsorted(st, self.x1, side="right")) + 1, st.size)
            ax.add_line(Line2D(st[i0:i1], z[i0:i1], color=sp.color, lw=sp.width, ls=SURFACE_DASHES.get(sp.style, "-"),
                               solid_joinstyle="miter" if sp.mode == "cells" else "round", solid_capstyle="butt",
                               dash_capstyle="butt", zorder=SURFACE_Z, gid=SURFACE_GID))
            if not sp.marks:
                continue
            hw, th = MARK_HALF_IN * k / self.kx, MARK_H_IN * k / self.kz
            for station in self._mark_stations():
                zs = _mark_z(st, z, station)
                if not math.isfinite(zs) or not self.z0 <= zs <= self.z1 - th:
                    continue
                ax.add_patch(Polygon([(station, zs), (station - hw, zs + th), (station + hw, zs + th)], closed=True,
                                     fc="white", ec=sp.color, lw=0.6, joinstyle="miter", zorder=SURFACE_Z + 0.05,
                                     gid=MARK_GID))

    def _mark_stations(self) -> List[float]:
        """Where water-table marks go on this sheet: every MARK_EVERY_IN of paper from MARK_FIRST_IN, each moved
        sideways (up to 0.7 in) to keep MARK_CLEAR_IN clear of every exploration line and its water level marks
        (which reach LEADER_DX_IN + a step to the left), else left out."""
        k, w = self.k, self.ax_width_in()
        busy = [self._x_in(h.station) for h in self.model.hits if self.x0 <= h.station <= self.x1]
        # the other points' symbols too (0.3.3; nothing changes without them)
        points = [(m.x, m.half_w) for m in self._points_layout()] if getattr(self.model, "other_points", None) else []
        out = []
        x_in = MARK_FIRST_IN * k
        while x_in < w - 0.3 * k:
            for dx in (0.0, 0.35, -0.35, 0.7, -0.7):
                x = x_in + dx * k
                if not 0.3 * k <= x <= w - 0.3 * k:
                    continue
                if any(abs(x - px) < hw + MARK_CLEAR_IN * k for px, hw in points):
                    continue
                if all(not (b - (LEADER_DX_IN + LEADER_STEP_IN + MARK_CLEAR_IN) * k < x < b + MARK_CLEAR_IN * k)
                       for b in busy):
                    out.append(self.x0 + x / self.kx)
                    break
            x_in += MARK_EVERY_IN * k
        return out

    # --- screens and water levels
    def screens(self) -> None:
        """The screen bracket left of each exploration line; a measured water level joined to the middle of the
        screen by a leader that runs out to the left and turns up (or down) to the level; levels without a
        screen, and ATD levels, just left of the exploration line. Triangles are blue (open: measured; filled:
        ATD), tip on the level; the line under them, the bracket and the leader are black. A level not on a leader
        sits WL_DX_IN left of the exploration line, clear of it."""
        if not self.s.screens:
            return
        lay = self.layout()
        ax, k = self.ax, self.k
        fx, fz = k / self.kx, k / self.kz                   # paper inches -> ft across / up
        labels: List[Tuple[float, float, str]] = []         # (symbol centre, level, text)
        for h in lay.hits:
            x = h.station
            screen = _finite_num(h.screen_top) and _finite_num(h.screen_bottom)
            levels = h.water_levels
            if not hit_in_range(h):
                # a row left out of the range (it never widens it): a level outside the frame is not drawn, nor a
                # screen whose top is below it (the legend and the notes leave them out too; the panel says so,
                # hover and the CSV still have them). In-range rows: as always (a manual range clips them)
                levels = frame_levels(h, self.z0, self.z1)
                screen = screen and frame_screen(h, self.z0)
            xb = x - BRACKET_DX_IN * fx
            mid = 0.0
            if screen:
                xt = x - BRACKET_GAP_IN * fx
                ax.add_line(Line2D([xt, xb, xb, xt], [h.screen_top, h.screen_top, h.screen_bottom, h.screen_bottom],
                                   color=INK, lw=SCREEN_LW, solid_joinstyle="miter", solid_capstyle="butt",
                                   zorder=SCREEN_Z, gid=SCREEN_GID))
                mid = (h.screen_top + h.screen_bottom) / 2.0
            n = 0
            for w in levels:
                cx = x - WL_DX_IN * fx                       # just left of the line (the user, 2026-10-05)
                if w.kind == "measured" and screen:
                    cx = x - (LEADER_DX_IN + n * LEADER_STEP_IN) * fx
                    n += 1
                    z_end = w.elev if w.elev >= mid else w.elev + WL_TRI_H_IN * fz
                    ax.add_line(Line2D([xb, cx, cx], [mid, mid, z_end], color=INK, lw=LEADER_LW,
                                       solid_joinstyle="miter", solid_capstyle="butt", zorder=SCREEN_Z,
                                       gid=LEADER_GID))
                self._wl_symbol(cx, w, fx, fz)
                text = wl_text(w, self.s)
                if text:
                    labels.append((cx, w.elev, text))
        self._wl_labels(labels)

    def _wl_labels(self, labels: List[Tuple[float, float, str]]) -> None:
        """The water level labels, left of their symbols (right of them when there is no room before the frame);
        a label that would overlap one already placed moves down or up a row (up to three), in station order."""
        if not labels:
            return
        ax, k = self.ax, self.k
        h_in = WL_LABEL_PT * k / 72.0
        pitch = h_in + 0.01 * k
        frame_w = self.ax_width_in()
        placed: List[Box] = []
        for cx, elev, text in sorted(labels, key=lambda t: (t[0], -t[1])):
            w_in = text_width_pt(text, WL_LABEL_PT * k) / 72.0
            gap = (WL_LINE_HALF_IN + WL_LABEL_GAP_IN) * k
            x = self._x_in(cx)
            left_side = x - gap - w_in >= 0.0 or x + gap + w_in > frame_w
            x0 = x - gap - w_in if left_side else x + gap
            base = self._z_in(elev) + 0.012 * k
            box = (x0, x0 + w_in, base, base + h_in)
            for row in (0, -1, 1, -2, 2, -3, 3):
                cand = (x0, x0 + w_in, base + row * pitch, base + row * pitch + h_in)
                if not overlaps_any(placed, *cand):
                    box = cand
                    break
            placed.append(box)
            kw = dict(x=self.x0 + (box[1] if left_side else box[0]) / self.kx, y=self.z0 + box[2] / self.kz, s=text,
                      ha="right" if left_side else "left", va="bottom", fontsize=WL_LABEL_PT * k, color=INK,
                      clip_on=True)
            ax.text(zorder=WL_Z + 0.02, path_effects=[patheffects.Stroke(linewidth=HALO_PT * k, foreground="white")],
                    **kw)
            ax.text(zorder=WL_Z + 0.03, gid=WL_TEXT_GID, **kw)

    def _wl_symbol(self, cx: float, w, fx: float, fz: float) -> None:
        ax = self.ax
        atd = w.kind == "atd"
        hw, tw, th = WL_LINE_HALF_IN * fx, WL_TRI_HALF_IN * fx, WL_TRI_H_IN * fz
        ax.add_line(Line2D([cx - hw, cx + hw], [w.elev, w.elev], color=INK, lw=WL_LW, solid_capstyle="butt",
                           zorder=WL_Z, gid=WL_LINE_GID))
        ax.add_patch(Polygon([(cx, w.elev), (cx - tw, w.elev + th), (cx + tw, w.elev + th)], closed=True,
                             fc=WATER if atd else "white", ec=WATER, lw=WL_LW, joinstyle="miter", zorder=WL_Z + 0.01,
                             gid=ATD_GID if atd else WL_GID))

    # --- other points (seeps, springs ...)
    def _points_layout(self) -> List[_PointMark]:
        """Where the other points of this page go (worked out once: the water-table marks and the match notes
        keep clear of them). Ground-line points rest on the drawn ground line (scales.other_centre_in, in this
        painter's own paper inches); the others are centred on their elevation. Labels above, clear of the
        exploration marks and TD labels and of each other (scales.other_label_layout)."""
        if self._pts is not None:
            return self._pts
        pts = getattr(self.model, "other_points", None) or []
        out: List[_PointMark] = []
        if pts:
            s, k = self.s, self.k
            lay = self.layout()
            lo, hi = self._window()
            items = []
            # labels are drawn outside the clip box (as the exploration labels): a point whose symbol centre the
            # frame cuts off (a manual elevation range) is left out whole, its label too (the plan warns about it)
            frame_h = (self.z1 - self.z0) * self.kz
            tol = 1e-9 * max(1.0, abs(self.z1 - self.z0)) * self.kz
            for i, p in enumerate(pts):
                if not lo <= p.station <= hi:
                    continue
                shape, size, color = other_symbol(self.model, p)
                flip = symbol_flip(self.model, p, s)
                caps = symbol_capsules(shape, size, k, flip)
                half_w, below, above = symbol_extent(caps)
                y = other_centre_in(p, caps, self.model.ground, self._x_in, self._z_in, self.kx, k, thin=self.preview,
                                    rests=symbol(shape).rests)
                if not _finite_num(y) or not -tol <= y <= frame_h + tol:
                    continue
                text = display_label(p, s)
                items.append((i, p, shape, size, color, self._x_in(p.station), y, half_w, below, above, text, flip))
            labelled = [it for it in items if it[10]]
            obstacles = (mark_obstacles(lay.marks, s.label_vertical)
                         + [(x - w / 2, x + w / 2, y - TD_TEXT_H_IN * k, y) for _, x, y, w, _ in lay.td]
                         + [t.box for t in lay.side_td]
                         # every point's symbol: no label covers (and its halo erases) a neighbour's (its own is
                         # always under its anchor)
                         + [(x - hw, x + hw, y - b, y + a) for (_, _, _, _, _, x, y, hw, b, a, _, _) in items])
            st, gz = self.model.ground.stations, self.model.ground.z
            i0 = max(bisect.bisect_left(st, self.x0) - 1, 0)
            i1 = min(bisect.bisect_right(st, self.x1) + 1, len(st))
            spots = other_label_layout([it[5] for it in labelled],
                                       [other_label_anchor(it[1], it[6], it[9], self._z_in, k) for it in labelled],
                                       [text_width_pt(it[10], LABEL_PT * k) / 72.0 for it in labelled], k,
                                       self.ax_width_in(), obstacles,
                                       ground_top_fn(st[i0:i1], gz[i0:i1], self._x_in, self._z_in))
            spot_of = {it[0]: sp for it, sp in zip(labelled, spots)}
            out = [_PointMark(i, p, shape, size, color, x, y, hw, b, a, text, spot_of.get(i), flip)
                   for i, p, shape, size, color, x, y, hw, b, a, text, flip in items]
        self._pts = out
        return out

    def other_points(self) -> List[PlacedPoint]:
        """The other points: each row's symbol (explicit geometry, never a matplotlib marker) in its colour, a
        dotted lead from the ground line down to a symbol placed well below it (LIDAR / field), and the label
        above (a leader when it had to rise). Returns where each was drawn (the preview's hover boxes)."""
        ax, s, k = self.ax, self.s, self.k
        placed: List[PlacedPoint] = []
        for m in self._points_layout():
            p = m.point
            zc = self.z0 + m.y / self.kz
            for art in _symbol_artists(m.shape, m.size, k, m.color, p.station, zc, 1.0 / self.kx, 1.0 / self.kz,
                                       flip=m.flip):
                art.set_zorder(POINT_Z)
                art.set_gid(OTHER_GID)
                if isinstance(art, Line2D):
                    ax.add_line(art)
                elif isinstance(art, Text):                  # the thermal spring's "T"
                    ax.add_artist(art)
                else:
                    ax.add_patch(art)
            g = p.ground_at_station
            top_ft = zc + m.above / self.kz
            if p.how != "line" and _finite_num(g) and (g - p.z) / s.v_scale > 0.05 and g > top_ft:
                ax.add_line(Line2D([p.station, p.station], [g, top_ft], color=INK, lw=0.6, ls=(0, (1, 1.5)),
                                   zorder=3.4, gid=OTHER_LEAD_GID))
            label_top = 0.0
            if m.spot is not None:
                sp = m.spot
                kw = dict(x=self.x0 + sp.x / self.kx, y=self.z0 + sp.base / self.kz, s=m.text, ha="center",
                          va="bottom", fontsize=LABEL_PT * k, color=INK, clip_on=False)
                # where an exploration label's leader runs through the name, the halo copy is boxed in white: the
                # leaders pass behind the name (drawn after them at the same zorder), the name stays readable
                box = (dict(bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", lw=0))
                       if self._crosses_leader(sp.box) else {})
                ax.text(zorder=6, gid=OTHER_LABEL_HALO_GID,
                        path_effects=[patheffects.Stroke(linewidth=HALO_PT * k, foreground="white")], **box, **kw)
                ax.text(zorder=6, gid=OTHER_LABEL_GID, **kw)
                if sp.moved:                                 # from the symbol's top (from the ground line over a
                    start = top_ft                            # symbol below it, where the dotted lead takes over)
                    if p.how != "line" and _finite_num(g) and g > top_ft:
                        start = g
                    ax.add_line(Line2D([p.station, self.x0 + sp.x / self.kx], [start, self.z0 + sp.base / self.kz],
                                       color=LEADER, lw=0.4, solid_capstyle="butt", clip_on=False, zorder=5.9))
                label_top = sp.box[3] - m.y
            placed.append(PlacedPoint(m.index, float(p.station), float(zc), float(m.half_w), float(m.below),
                                      float(m.above), float(label_top)))
        return placed

    def _crosses_leader(self, box: Box) -> bool:
        """True when the leader of a moved exploration label (tick top to the label's foot) runs through `box`
        (paper inches from the frame's lower left)."""
        lay = self.layout()
        tick = TICK_TO_IN * self.k
        return any(sp.moved and _segment_in_box(x, b + tick, sp.x, sp.base, box)
                   for x, b, sp in zip(lay.x_in, lay.base_in, lay.spots))

    # --- the brackets of the polygon rows (0.3.6)
    def _area_frame(self) -> AreaFrame:
        """The preview's own paper for scales.area_layout: its scale, its k (its labels are relatively larger than the
        sheet's) and what it lays out itself: the exploration ticks and labels, the other points' symbols and labels."""
        obstacles = list(mark_obstacles(self.layout().marks, self.s.label_vertical))
        if getattr(self.model, "other_points", None):
            for pm in self._points_layout():
                obstacles.append((pm.x - pm.half_w, pm.x + pm.half_w, pm.y - pm.below, pm.y + pm.above))
                if pm.spot is not None:
                    obstacles.append(pm.spot.box)
        return AreaFrame(self.kx * float(self.s.h_scale), self.k, self._z_in, lambda y: self.z0 + y / self.kz,
                         obstacles)

    def _areas_layout(self) -> List[_AreaMark]:
        """The brackets on this page (worked out once: the match notes keep clear of them), from the layout of the
        whole section (scales.area_layout, the frame top as its cap and its bottom as its floor; at sheet scale on a
        sheet, at its own in the preview): each piece's part on this page, its line's height (inside: the layout's;
        above the frame: its row of the band), its true ends here and its label (its own centre when on this page,
        else the middle of the part here, moved in to stay inside the frame; a label so moved is left out where it
        would overlap a bracket label on this page)."""
        if self._areas is not None:
            return self._areas
        out: List[_AreaMark] = []
        pieces = getattr(self.model, "other_areas", None) or []
        spots: List[AreaSpot] = []
        if pieces:
            frame = self._area_frame() if self.preview else None
            spots = area_layout(self.model, self.s, self.plan.plot_length, z_cap=self.z1, z_floor=self.z0, frame=frame)
        if spots:
            k = self.k
            fz = k / self.kz
            infos = getattr(self.model, "other_layers", None) or []
            eps = 1e-6 * max(1.0, self.x1 - self.x0)
            tol = 1e-9 * max(1.0, abs(self.z1 - self.z0))
            frame_w = self.ax_width_in()
            pad = AREA_PAD_IN * k
            moved: List[bool] = []
            for sp in sorted(spots, key=lambda sp: (sp.place, sp.level)):
                p = pieces[sp.index]
                a, b = max(p.start, self.x0), min(p.end, self.x1)
                if b <= a:
                    continue
                if sp.place == "above":
                    y = self.z1 + (AREA_FRAME_GAP_IN + sp.level * AREA_ROW_IN + AREA_TICK_IN) * fz
                else:
                    y = sp.line_z
                    if not (math.isfinite(y) and self.z0 - tol <= y <= self.z1 + tol):
                        continue                         # lowered under the frame bottom (the plan warns)
                j = getattr(p, "layer_index", 0)
                info = infos[j] if isinstance(j, int) and 0 <= j < len(infos) else None
                ends = [(s, is_open, d) for s, is_open, d in ((p.start, p.open_start, 1.0), (p.end, p.open_end, -1.0))
                        if self.x0 - eps <= s <= self.x1 + eps]
                label = None
                own = self.x0 - eps <= sp.label_x <= self.x1 + eps
                if sp.text:
                    w = text_width_pt(sp.text, LABEL_PT * k) / 72.0
                    cx = clamp_centre(self._x_in(sp.label_x if own else (a + b) / 2.0), w, frame_w)
                    bottom = self._z_in(y) + AREA_LABEL_GAP_IN * k
                    label = (self.x0 + cx / self.kx, y + AREA_LABEL_GAP_IN * fz,
                             (cx - w / 2.0, cx + w / 2.0, bottom, bottom + LABEL_ROW_IN * k))
                out.append(_AreaMark(sp, info.color if info is not None else INK,
                                     getattr(info, "bracket_style", "solid") == "dash",
                                     getattr(info, "edges", "off") if info is not None else "off",
                                     a, b, y, ends, label))
                moved.append(label is not None and not own)
            # every label at its own centre is drawn (the layout keeps those apart); one the tile rule moved (its
            # centre on another sheet) is left out where it would overlap a bracket label already on this page
            taken = [m.label[2] for m, mv in zip(out, moved) if m.label is not None and not mv]
            taken = [(box[0] - pad / 2.0, box[1] + pad / 2.0, box[2], box[3]) for box in taken]
            for i, (m, mv) in enumerate(zip(out, moved)):
                if not mv:
                    continue
                box = m.label[2]
                box = (box[0] - pad / 2.0, box[1] + pad / 2.0, box[2], box[3])
                if overlaps_any(taken, *box):
                    out[i] = m._replace(label=None)
                else:
                    taken.append(box)
        self._areas = out
        return out

    def areas(self) -> None:
        """The brackets of the polygon rows: a line over each piece's part on this page with a tick at each true end
        (an open arrow at A or A′ where the polygon goes on past it; none where a sheet edge cuts it), its label
        centred above it in the row's colour on a white halo, and the row's dashed edge lines at the true ends (to the
        ground or the frame bottom). Inside the frame they are clipped by it; above it nothing is."""
        marks = self._areas_layout()
        if not marks:
            return
        ax, k = self.ax, self.k
        fx, fz = k / self.kx, k / self.kz
        half_lw = AREA_LW / 144.0 / self.kz                # half the line's width, ft up (widths are not scaled by k)
        for m in marks:
            clip = m.spot.place != "above"
            line_kw = dict(color=m.color, lw=AREA_LW, solid_capstyle="butt", dash_capstyle="butt", zorder=AREA_Z,
                           gid=AREA_GID, clip_on=clip)
            dash = dict(ls=(0, tuple(v / AREA_LW for v in AREA_DASH_PT))) if m.dashed else {}
            ax.add_line(Line2D([m.a, m.b], [m.y, m.y], **dash, **line_kw))
            for s, is_open, d in m.ends:
                if is_open:                                # the open arrow: past A (pointing left) or A′
                    ax.add_line(Line2D([s + d * AREA_ARROW_IN * fx, s, s + d * AREA_ARROW_IN * fx],
                                       [m.y + AREA_ARROW_HALF_IN * fz, m.y, m.y - AREA_ARROW_HALF_IN * fz],
                                       solid_joinstyle="miter", **line_kw))
                    continue
                ax.add_line(Line2D([s, s], [m.y + half_lw, m.y - AREA_TICK_IN * fz], **line_kw))
                if m.edges in ("ground", "full"):
                    if m.edges == "full":
                        low = self.z0
                    else:
                        low = self.model.ground.z_at(s)
                        if not math.isfinite(low):
                            low = self.model.ground.nearest_valid(s)
                        if math.isfinite(low) and low < self.z0:   # never under the frame (one above it is not
                            low = self.z0                          # clipped: a manual minimum over the ground)
                    if math.isfinite(low) and low < m.y:
                        for top, bottom in self._edge_runs(m, s, low, marks):
                            ax.add_line(Line2D([s, s], [top, bottom], color=m.color, lw=AREA_EDGE_LW,
                                               ls=(0, tuple(v / AREA_EDGE_LW for v in AREA_EDGE_DASH_PT)),
                                               dash_capstyle="butt", zorder=AREA_EDGE_Z, gid=AREA_EDGE_GID,
                                               clip_on=clip))
            if m.label is not None:
                x, y, _box = m.label
                kw = dict(x=x, y=y, s=m.spot.text, ha="center", va="bottom", fontsize=LABEL_PT * k, color=m.color,
                          clip_on=False)
                ax.text(zorder=6, gid=AREA_LABEL_HALO_GID,
                        path_effects=[patheffects.Stroke(linewidth=HALO_PT * k, foreground="white")], **kw)
                ax.text(zorder=6, gid=AREA_LABEL_GID, **kw)

    def _edge_runs(self, m: _AreaMark, s: float, low: float, marks: Sequence[_AreaMark]) -> List[Tuple[float, float]]:
        """The (top, bottom) elevations of the edge line of `m` at station `s` from its line down to `low`, less where
        it would run through another bracket's label on this page (with the halo's width around it, AREA_PAD_IN / 2
        to the sides): an upper bracket's end often stands over the label of the one under it. [(m.y, low)] when it
        passes none."""
        x = self._x_in(s)
        dx, dy = AREA_PAD_IN * self.k / 2.0, HALO_PT * self.k / 144.0
        cuts = [(self.z0 + (o.label[2][2] - dy) / self.kz, self.z0 + (o.label[2][3] + dy) / self.kz)
                for o in marks if o is not m and o.label is not None and o.label[2][0] - dx <= x <= o.label[2][1] + dx]
        runs: List[Tuple[float, float]] = []
        top = m.y
        for lo, hi in sorted(cuts, key=lambda c: -c[1]):     # from the top down
            if hi <= low or lo >= top:
                continue
            if hi < top:
                runs.append((top, hi))
            top = min(top, lo)
            if top <= low:
                break
        if top > low:
            runs.append((top, low))
        return runs

    def _label(self, text, x, z, anchor, dx_pt, dy_pt, rotation, leader, fs, color=INK) -> None:
        arrow = None
        if leader:
            arrow = dict(arrowstyle="-", lw=0.4, color=LEADER, shrinkA=0, shrinkB=0, relpos=(0.5, 0.0))
        self.ax.annotate(text, (x, z), xycoords=anchor, xytext=(dx_pt, dy_pt), textcoords="offset points",
                         rotation=rotation, ha="center", va="bottom", fontsize=fs, color=color,
                         annotation_clip=False, zorder=6, arrowprops=arrow)

    # --- A / A' at the true ends only
    def end_marks(self) -> List["_EndMark"]:
        """The end letters and their compass directions over the true ends on this sheet. Standard: the
        letter centred over the end, "(S)" under it. Compact: one line just above the frame, "A (S)" starting
        at the start and "A′ (N)" ending at the end."""
        k = self.k
        az = self.model.azimuth
        eps = 1e-6 * max(1.0, self.x1 - self.x0)
        out: List[_EndMark] = []
        for first, station, label, bearing in ((True, 0.0, self.s.start_label, az + 180.0),
                                               (False, self.model.length, self.s.end_label, az)):
            if not (self.x0 - eps <= station <= self.x1 + eps):
                continue
            x = self._x_in(station)
            letter = pretty_label(label)
            direction = compass16(bearing) if az is not None and not math.isnan(az) else ""
            if not self.compact:
                if direction:
                    w = text_width_pt(f"({direction})", 6.5 * k)
                    out.append(_EndMark(f"({direction})", station, 0.0, 3 * k, "center", "bottom", 6.5 * k,
                                        "normal", (x - w / 144.0, x + w / 144.0, 3 * k / 72.0, 9.5 * k / 72.0)))
                w = text_width_pt(letter, 12 * k, "bold")
                out.append(_EndMark(letter, station, 0.0, 12 * k, "center", "bottom", 12 * k, "bold",
                                    (x - w / 144.0, x + w / 144.0, 12 * k / 72.0, 24 * k / 72.0)))
                continue
            base = compact_rows_in()[0]
            lo, hi = base - TEXT_DESCENT_EM * END_PT / 72.0, base + (1.0 - TEXT_DESCENT_EM) * END_PT / 72.0
            wl = ink_width_pt(self.fig, letter, END_PT, "bold")
            wd = ink_width_pt(self.fig, f" ({direction})", END_DIR_PT) if direction else 0.0
            # "A (S)" from the start; "A′ (N)" up to the end (points from the end station)
            x_letter, x_dir = (0.0, wl) if first else (-(wl + wd), -wd)
            out.append(_EndMark(letter, station, x_letter, base * 72.0, "left", "baseline", END_PT, "bold",
                                (x + x_letter / 72.0, x + (x_letter + wl) / 72.0, lo, hi)))
            if direction:
                out.append(_EndMark(f" ({direction})", station, x_dir, base * 72.0, "left", "baseline", END_DIR_PT,
                                    "normal", (x + x_dir / 72.0, x + (x_dir + wd) / 72.0, lo, hi)))
        if self.above > 0.0:                               # over the band of bracket rows (0.3.6)
            up = self.above
            out = [m._replace(dy_pt=m.dy_pt + up * 72.0, box=(m.box[0], m.box[1], m.box[2] + up, m.box[3] + up))
                   for m in out]
        return out

    def ends(self) -> None:
        for m in self.end_marks():
            self.ax.annotate(m.text, (m.station, 1.0), xycoords=self.top_blend, xytext=(m.dx_pt, m.dy_pt),
                             textcoords="offset points", ha=m.ha, va=m.va, fontsize=m.size, weight=m.weight,
                             annotation_clip=False)

    # --- tiles
    def match_lines(self, page: PageLayout) -> None:
        ax = self.ax
        n = page.tile_count
        for side, m in (("left", page.match_left), ("right", page.match_right)):
            if m is None:
                continue
            other = page.tile_index - 1 if side == "left" else page.tile_index + 1
            span = (self.x0, m) if side == "left" else (m, self.x1)
            ax.axvspan(*span, color=OVERLAP_FILL, lw=0, zorder=0.3)
            # under the data: an exploration at the match station stays visible on both sheets
            ax.add_line(Line2D([m, m], [self.z0, self.z1], color=MATCH, lw=1.2, ls=(0, (8, 2, 2, 2)),
                               zorder=MATCH_Z))
            up, right, txt, size = self._match_note(m, side == "left", match_forms(m, other, n, page.plot_h))
            kw = dict(xy=(m, up), xycoords=self.top_blend, xytext=(4 if right else -4, 0),
                      textcoords="offset points", rotation=90, ha="left" if right else "right",
                      va="center", multialignment="center", fontsize=size, weight="bold", color=MATCH,
                      annotation_clip=False)
            # a thin white halo (a stroked copy drawn as outlines) keeps the text legible without
            # boxing out the data; the copy on top stays real, searchable text in the PDF
            ax.annotate(txt, zorder=7.9, path_effects=[patheffects.Stroke(linewidth=HALO_PT, foreground="white")],
                        **kw)
            ax.annotate(txt, zorder=8, **kw)

    def _match_note(self, m: float, right_first: bool,
                    forms: Sequence[Tuple[str, float]]) -> Tuple[float, bool, str, float]:
        """Where the match note at station `m` goes and in which form: (axes fraction up its line, right
        of the line?, text, size). Candidates are scored, best first: covering none of the TD labels,
        exploration ticks and labels and bars (else as little as possible); clear of the top-to-bottom
        lines and the ground line; the longer form (one line, then two, then three); the line's inner
        side, then its outer side (the overlap band); nearest mid-height. Always 0.1 in inside the frame."""
        s, k = self.s, self.k
        lay = self.layout()
        halo = HALO_PT / 2.0 / 72.0
        frame_w, frame_h = self.ax_width_in(), (self.z1 - self.z0) * self.kz
        mid = frame_h / 2.0
        td_h = TD_TEXT_H_IN * k
        hard = ([(x - w / 2 - halo, x + w / 2 + halo, y - td_h - halo, y + halo) for _, x, y, w, _ in lay.td]
                + lay.marks + bar_boxes(lay.hits, s, self._x_in, self._z_in, k, z_floor=self.z0))
        hard += [(t.box[0] - halo, t.box[1] + halo, t.box[2] - halo, t.box[3] + halo) for t in lay.side_td]
        if getattr(self.model, "other_points", None):        # the other points' symbols and labels (0.3.3)
            for pm in self._points_layout():
                hard.append((pm.x - pm.half_w, pm.x + pm.half_w, pm.y - pm.below, pm.y + pm.above))
                if pm.spot is not None:
                    hard.append(pm.spot.box)
        if getattr(self.model, "other_areas", None):         # the brackets inside the frame and their labels (0.3.6)
            for am in self._areas_layout():
                if am.spot.place == "above":
                    continue
                y = self._z_in(am.y)
                hard.append((self._x_in(am.a), self._x_in(am.b), y - AREA_TICK_IN * k,
                             y + (AREA_LABEL_GAP_IN + LABEL_ROW_IN) * k))
                if am.label is not None:
                    hard.append(am.label[2])
        soft = [(self._x_in(h.station) - 0.01, self._x_in(h.station) + 0.01,
                 self._z_in(max(min(h.top, h.bottom), self.z0)), self._z_in(max(h.top, h.bottom)))
                for h in lay.hits if draws_depth_line(h, s)]
        crosses = ground_test(self.model.ground, lambda x: self.x0 + x / self.kx, self._z_in, GROUND_CLEAR_IN)
        xm, gap = self._x_in(m), 4.0 / 72.0
        best = None
        for fi, (txt, size) in enumerate(forms):
            lines = txt.split("\n")
            along = max(text_width_pt(t, size, "bold") for t in lines) / 72.0 + 2 * halo
            across = (text_height_pt("lp", size, "bold") + (len(lines) - 1) * 1.2 * size) / 72.0 + 2 * halo
            lo, hi = 0.1 + along / 2.0, frame_h - 0.1 - along / 2.0
            if hi < lo:
                ys = [mid]
            else:
                steps = int(math.ceil((hi - lo) / 2.0 / MATCH_STEP_IN)) + 1
                ys = sorted({min(max(mid + sign * i * MATCH_STEP_IN, lo), hi) for i in range(steps)
                             for sign in (1, -1)}, key=lambda y: (abs(y - mid), y))
            for si, right in enumerate((right_first, not right_first)):
                left_x = xm + gap if right else xm - gap - across
                right_x = left_x + across
                if left_x < 0.0 or right_x > frame_w:
                    continue
                col_hard = [bx for bx in hard if bx[0] < right_x and left_x < bx[1]]
                col_soft = [bx for bx in soft if bx[0] < right_x and left_x < bx[1]]
                for y in ys:
                    b, t = y - along / 2.0, y + along / 2.0
                    covered = sum((min(right_x, br) - max(left_x, bl)) * max(0.0, min(t, bt) - max(b, bb))
                                  for bl, br, bb, bt in col_hard)
                    if best is not None and round(covered, 6) > best[0][0]:
                        continue
                    touches = overlaps_any(col_soft, left_x, right_x, b, t) or crosses(left_x, right_x, b, t)
                    key = (round(covered, 6), touches, fi, si, round(abs(y - mid), 6))
                    if best is None or key < best[0]:
                        best = (key, y, right, txt, size)
        if best is None:                                  # no room beside the line at all
            return 0.5, right_first, forms[0][0], forms[0][1]
        _, y, right, txt, size = best
        return y / frame_h, right, txt, size

    def preview_matches(self) -> None:
        k = self.k
        for pg in self.plan.pages:
            if pg.match_right is None:
                continue
            m = pg.match_right
            self.ax.add_line(Line2D([m, m], [self.z0, self.z1], color=MATCH, lw=0.8, ls=(0, (6, 2, 2, 2)),
                                    zorder=MATCH_Z))
            self.ax.annotate(f"MATCH {fmt_station(m)}",
                             (m, 1.0), xycoords=self.top_blend, xytext=(-2, -4), textcoords="offset points",
                             rotation=90, ha="right", va="top", fontsize=5.5 * k, color=MATCH, zorder=8)


# ----------------------------------------------------------------------------- sheet furniture
def match_text(station: float, other: int, n: int, plot_h_in: float) -> Tuple[str, float]:
    """The match-line note and its size (pt), fitted within the plot height less 0.1 in at each end:
    one line at 7 pt, else two lines, else two smaller lines (never under 5 pt)."""
    room = max(plot_h_in - 0.2, 0.3) * 72.0
    one = f"MATCH LINE STA {fmt_station(station)} · SEE SHEET {other} OF {n}"
    if text_width_pt(one, 7.0, "bold") <= room:
        return one, 7.0
    return _fitted([f"MATCH LINE STA {fmt_station(station)}", f"SEE SHEET {other} OF {n}"], room)


def _fitted(lines: Sequence[str], room_pt: float) -> Tuple[str, float]:
    widest = max(text_width_pt(t, 7.0, "bold") for t in lines)
    return "\n".join(lines), max(5.0, min(7.0, 7.0 * room_pt / widest))


def match_forms(station: float, other: int, n: int, plot_h_in: float) -> List[Tuple[str, float]]:
    """The forms the match note may take, longest first: match_text's, then shorter ones on more lines
    (two, then three), so that it can fit between the marks along its line."""
    room = max(plot_h_in - 0.2, 0.3) * 72.0
    st, see = fmt_station(station), f"SEE SHEET {other} OF {n}"
    forms = [match_text(station, other, n, plot_h_in)]
    for lines in ([f"MATCH LINE STA {st}", see], ["MATCH LINE", f"STA {st}", see]):
        if len(lines) > forms[0][0].count("\n") + 1:
            forms.append(_fitted(lines, room))
    return forms


def title_text(settings: Settings, page: PageLayout) -> str:
    """ "CROSS SECTION A–A′", plus " (SHEET 2 OF 3)" on a tiled sheet."""
    title = f"CROSS SECTION {pretty_label(settings.start_label)}–{pretty_label(settings.end_label)}"
    if page.tile_count > 1:
        title += f" (SHEET {page.tile_index} OF {page.tile_count})"
    return title


def fit_pt(text: str, size: float, width_in: float, weight: str = "normal", fig: Optional[Figure] = None) -> str:
    """`text` cut short with "…" when it is wider than `width_in` (as `fig` draws it, see ink_width_pt)."""
    if ink_width_pt(fig, text, size, weight) / 72.0 <= width_in:
        return text
    while text and ink_width_pt(fig, text.rstrip() + "…", size, weight) / 72.0 > width_in:
        text = text[:-1]
    return text.rstrip() + "…"


def _title(fig: Figure, model: SectionModel, settings: Settings, page: PageLayout, above_in: float = 0.0) -> None:
    """Standard layout: "CROSS SECTION A–A′" and the optional title line under it, centred on the plot. A title
    line too long to sit between the end letters lifts both lines clear of them (STD_TITLE_RAISE_IN) and may
    then run past the plot, kept within the printer edge (smaller, down to 7 pt, then cut short with "…").
    `above_in` (0.3.6, Plan.above_in): the band of bracket rows over the frame, which the title stands above."""
    if settings.compact_layout:
        _title_compact(fig, settings, page, above_in)
        return
    T = fig.dpi_scale_trans
    edge, W = edge_in(settings), page.page_w
    cx = page.plot_left + page.plot_w / 2.0
    top = page.plot_bottom + page.plot_h
    if above_in > 0.0:
        top += above_in
    line, size, dy = settings.title, STD_LINE_PT, 0.0
    if line:
        lo, hi = _title_line_room(fig, model, settings, page)
        w = ink_width_pt(fig, line, size) / 72.0
        if cx - w / 2.0 < lo - 1e-9 or cx + w / 2.0 > hi + 1e-9:
            dy = STD_TITLE_RAISE_IN
            room = W - 2.0 * edge
            while size > STD_LINE_MIN_PT and ink_width_pt(fig, line, size) / 72.0 > room:
                size -= 0.5
            line = fit_pt(line, size, room, fig=fig)
    head = fit_pt(title_text(settings, page), STD_HEAD_PT, W - 2.0 * edge, "bold", fig)
    _centred_text(fig, cx, top + STD_HEAD_DY_IN + dy, head, edge, W, fontsize=STD_HEAD_PT, weight="bold")
    if line:
        _centred_text(fig, cx, top + STD_LINE_DY_IN + dy, line, edge, W, fontsize=size)


def _title_line_room(fig: Figure, model: SectionModel, settings: Settings, page: PageLayout) -> Tuple[float, float]:
    """(left, right) paper x the standard title line may span at its own height: between the end letters on
    this sheet (STD_END_GAP_IN clear of them), else the printer edge."""
    edge = edge_in(settings)
    lo, hi = edge, page.page_w - edge
    span = page.x_max - page.x_min
    if span <= 0:
        return lo, hi
    eps = 1e-6 * max(1.0, span)
    for first, station, label in ((True, 0.0, settings.start_label), (False, model.length, settings.end_label)):
        if not (page.x_min - eps <= station <= page.x_max + eps):
            continue
        x = page.plot_left + (station - page.x_min) / span * page.plot_w
        half = ink_width_pt(fig, pretty_label(label), STD_END_PT, "bold") / 144.0 + STD_END_GAP_IN
        if first:
            lo = max(lo, x + half)
        else:
            hi = min(hi, x - half)
    return lo, hi


def _centred_text(fig: Figure, cx: float, y: float, text: str, edge: float, W: float, **kw) -> None:
    """One line centred on cx (baseline at y, paper inches), moved in just enough to stay within the printer
    edge."""
    T = fig.dpi_scale_trans
    w = ink_width_pt(fig, text, kw.get("fontsize", 10.0), kw.get("weight", "normal")) / 72.0
    if cx - w / 2.0 >= edge - 1e-9 and cx + w / 2.0 <= W - edge + 1e-9:
        fig.text(cx, y, text, transform=T, ha="center", va="baseline", **kw)
    else:
        fig.text(min(max(cx - w / 2.0, edge), W - edge - w), y, text, transform=T, ha="left", va="baseline", **kw)


def _title_compact(fig: Figure, settings: Settings, page: PageLayout, above_in: float = 0.0) -> None:
    """One line over the end-letter row: the title in bold, then " · " and the optional title line. Centred
    on the plot, kept within the printer edge (the title line gets smaller, then shorter, if need be). `above_in`:
    as for _title."""
    T = fig.dpi_scale_trans
    edge = edge_in(settings)
    y = page.plot_bottom + page.plot_h + compact_rows_in()[1]
    if above_in > 0.0:
        y += above_in
    head = title_text(settings, page)
    room = page.page_w - 2.0 * edge
    w_head = ink_width_pt(fig, head, TITLE_PT_COMPACT, "bold") / 72.0
    sub, sub_pt = (f" · {settings.title}" if settings.title else ""), SUBTITLE_PT_COMPACT
    if sub:
        while sub_pt > 6.0 and w_head + ink_width_pt(fig, sub, sub_pt) / 72.0 > room:
            sub_pt -= 0.5
        sub = fit_pt(sub, sub_pt, max(room - w_head, 0.0), fig=fig)
    total = w_head + (ink_width_pt(fig, sub, sub_pt) / 72.0 if sub else 0.0)
    x = page.plot_left + page.plot_w / 2.0 - total / 2.0
    x = min(max(x, edge), page.page_w - edge - total)
    fig.text(x, y, head, transform=T, ha="left", va="baseline", fontsize=TITLE_PT_COMPACT, weight="bold")
    if sub:
        fig.text(x + w_head, y, sub, transform=T, ha="left", va="baseline", fontsize=sub_pt)


def _vbar(fig: Figure, settings: Settings, plan: Plan, page: PageLayout) -> None:
    """Vertical graphic scale, 1 in tall in 5 segments, right of the plot: past the elevation title
    (standard), or just clear of the right elevation labels with "VERTICAL" beside it (compact)."""
    T = fig.dpi_scale_trans
    compact = bool(settings.compact_layout)
    wl = elevation_label_width_in((plan.z_min, plan.z_max), plan.v_major) if compact else 0.0
    x = page.plot_left + page.plot_w + vbar_dx_in(settings, wl)
    y = page.plot_bottom
    for i in range(5):
        fig.add_artist(Rectangle((x, y + i * 0.2), VBAR_W_IN, 0.2, transform=T, lw=0.5, ec=INK,
                                 fc=INK if i % 2 == 0 else "white"))
    fig.text(x + VBAR_LABEL_DX_IN, y, "0", transform=T, ha="left", va="center", fontsize=SCALE_LABEL_PT)
    fig.text(x + VBAR_LABEL_DX_IN, y + 1.0, f"{fmt_num(settings.v_scale)} ft", transform=T, ha="left",
             va="center", fontsize=SCALE_LABEL_PT)
    if compact:
        fig.text(x + VBAR_LABEL_DX_IN, y + 0.5, "VERTICAL", transform=T, rotation=90, ha="left", va="center",
                 fontsize=SCALE_NAME_PT)
    else:
        fig.text(x + 0.03, y - 0.06, "VERTICAL", transform=T, ha="center", va="top", fontsize=SCALE_NAME_PT)


def _hbar(fig: Figure, x: float, y: float, settings: Settings) -> None:
    """Horizontal graphic scale, 2 in long in 4 segments; "HORIZONTAL" under it (standard) or after it
    (compact)."""
    T = fig.dpi_scale_trans
    seg = HBAR_LEN_IN / 4.0
    for i in range(4):
        fig.add_artist(Rectangle((x + i * seg, y), seg, HBAR_H_IN, transform=T, lw=0.5, ec=INK,
                                 fc=INK if i % 2 == 0 else "white"))
    for i in range(3):
        lab = fmt_num(i * settings.h_scale)
        fig.text(x + i * 1.0, y + HBAR_LABEL_DY_IN, lab, transform=T, ha="center", va="bottom",
                 fontsize=SCALE_LABEL_PT)
    last_w = text_width_pt(fmt_num(2 * settings.h_scale), SCALE_LABEL_PT) / 72
    fig.text(x + HBAR_LEN_IN + last_w / 2 + 0.03, y + HBAR_LABEL_DY_IN, "ft", transform=T, ha="left", va="bottom",
             fontsize=SCALE_LABEL_PT)
    if settings.compact_layout:
        fig.text(x + HBAR_LEN_IN + HBAR_NAME_DY_IN, y + HBAR_H_IN / 2.0, "HORIZONTAL", transform=T, ha="left",
                 va="center", fontsize=SCALE_NAME_PT)
    else:
        fig.text(x, y - HBAR_NAME_DY_IN, "HORIZONTAL", transform=T, ha="left", va="top", fontsize=SCALE_NAME_PT)


def notes_text(model: SectionModel, settings: Settings, plan: Plan, page: PageLayout) -> List[Tuple[str, str]]:
    """The wrapped notes under the plot, as (text, color) (notes.note_texts)."""
    return [(t, INK) for t in note_texts(model, settings, plan, page)]


NOTE_SIZES = (NOTE_COMPACT_PT, NOTE_MIN_PT)


def note_width_in(fig: Optional[Figure], text: str, size: float) -> float:
    """Width a compact note line is fitted with, inches: the outline width x RASTER_SLACK, so that a PDF and
    a PNG (150-600 dpi) of the same sheet get the same text at the same size; or, at a dpi that draws small
    type wider still, the width drawn there (ink_width_pt)."""
    return max(text_width_pt(text, size) * RASTER_SLACK, ink_width_pt(fig, text, size)) / 72.0


def fit_note_line(parts: Sequence[NotePart], width_in: float, size: float, fig: Optional[Figure] = None) -> str:
    """One compact note line that fits `width_in` at `size`: all its parts; else with the DEM name cut short
    (NOTE_NAME_MIN_CHARS at least); else leaving out parts one at a time, the highest rank first (the last of
    a rank first), each time trying the full name first; a line of rank-0 parts that still does not fit is
    cut short with "…"."""
    def fits(t: str) -> bool:
        return note_width_in(fig, t, size) <= width_in + 1e-9

    order = sorted((i for i, p in enumerate(parts) if p.rank > 0), key=lambda i: (-parts[i].rank, -i))
    kept = list(parts)
    for n_out in range(len(order) + 1):
        out = set(order[:n_out])
        kept = [p for i, p in enumerate(parts) if i not in out]
        text = " · ".join(p.text for p in kept)
        if fits(text):
            return text
        for p in kept:
            if not p.name or len(p.name) <= NOTE_NAME_MIN_CHARS:
                continue
            lo, hi = NOTE_NAME_MIN_CHARS, len(p.name) - 1        # longest prefix that fits (widths grow with it)

            def joined(n: int) -> str:
                short = p.text.replace(p.name, p.name[:n].rstrip() + "…", 1)
                return " · ".join(short if q is p else q.text for q in kept)
            if not fits(joined(lo)):
                continue
            while lo < hi:
                mid = (lo + hi + 1) // 2
                lo, hi = (mid, hi) if fits(joined(mid)) else (lo, mid - 1)
            return joined(lo)
    text = " · ".join(p.text for p in kept)
    while text and not fits(text.rstrip() + "…"):
        text = text[:-1]
    return text.rstrip() + "…"


def fit_compact_notes(lines: Sequence[Sequence[NotePart]], x0: float, x_min: float, right: float, beside: float,
                      fig: Optional[Figure] = None) -> Tuple[float, List[str], float]:
    """(x of the horizontal scale bar, the note lines, their size) for the compact band. The notes start
    `beside` right of the bar's start and may run to `right` (the printer edge). Whole lines at 5.8, then
    5.5 pt with the bar at `x0` (under the plot's left end); else the bar moves left (no further than `x_min`)
    just enough for the whole lines at 5.8, then 5.5 pt; else each line is shortened at 5.5 pt to the room
    left with the bar at `x_min` (fit_note_line), and the bar moves back right as far as they allow."""
    whole = [" · ".join(p.text for p in parts) for parts in lines]
    for shift in (False, True):
        for size in NOTE_SIZES:
            need = max(note_width_in(fig, t, size) for t in whole)
            x_fit = right - beside - need                    # the bar may start this far right at most
            if x0 <= x_fit + 1e-9:
                return x0, whole, size
            if shift and x_fit >= x_min - 1e-9:
                return max(math.floor(x_fit * 100.0 + 1e-6) / 100.0, x_min), whole, size
    texts = [fit_note_line(parts, right - beside - x_min, NOTE_MIN_PT, fig) for parts in lines]
    need = max(note_width_in(fig, t, NOTE_MIN_PT) for t in texts)        # the shortened lines may leave room
    x = min(x0, max(math.floor((right - beside - need) * 100.0 + 1e-6) / 100.0, x_min))
    return x, texts, NOTE_MIN_PT


def draw_swatch(fig: Figure, model: SectionModel, settings: Settings, entry: Any, x: float, y: float) -> None:
    """The swatch of one legend entry (a scales.LegendEntry; a plain string, as tests pass, is a black line),
    SWATCH_IN wide from x, centred on y (paper inches). An exploration row or one colour of its style is a line as
    its depth lines are drawn: the entry's colour at the Color width, else Gray or black at the black width
    (depth_widths)."""
    T = fig.dpi_scale_trans
    if isinstance(entry, str) or entry.kind in ("layer", "style"):
        black, color = depth_widths(settings)
        if isinstance(entry, str):
            c, lw = DATA, black
        elif entry.color:                             # a Color row's colour (a style item, or a single symbol)
            c, lw = entry.color, color
        else:                                         # a Black or Gray row drawn differently from the others
            info = model.point_layers[entry.key]
            c, lw = (LOOK_GRAY if getattr(info, "look", "black") == "gray" else DATA), black
        fig.add_artist(Line2D([x, x + SWATCH_IN], [y, y], transform=T, color=c, lw=lw, solid_capstyle="butt",
                              gid=LEGEND_LINE_GID))
    elif entry.kind == "point":                       # an other-points row: its symbol, at most 6 pt
        info = model.other_layers[entry.key]
        shape, size = resolve(info.shape), min(float(info.size), LEGEND_SYMBOL_MAX_PT)
        if shape in LEGACY_DRAWN:                     # 0.3.5's six: the origin at the swatch centre
            for art in _symbol_artists(shape, size, 1.0, info.color, x + SWATCH_IN / 2.0, y, 1.0, 1.0, transform=T):
                fig.add_artist(art)
        else:                                         # a catalogue symbol: centred on its ink (its tail to the right)
            left, right, bottom, top = glyph_bbox(shape, size, 1.0)
            for art in _symbol_artists(shape, size, 1.0, info.color, x + SWATCH_IN / 2.0 - (left + right) / 2.0,
                                       y - (bottom + top) / 2.0, 1.0, 1.0, transform=T):
                art.set_gid(LEGEND_SYMBOL_GID)
                fig.add_artist(art)
    elif entry.kind == "area":                        # a polygon row (0.3.6): a small bracket in its colour and line
        info = model.other_layers[entry.key]
        kw = dict(transform=T, color=info.color, lw=AREA_LW, solid_capstyle="butt", gid=LEGEND_AREA_GID)
        if getattr(info, "bracket_style", "solid") != "dash":
            fig.add_artist(Line2D([x, x, x + SWATCH_IN, x + SWATCH_IN], [y - 0.03, y + 0.02, y + 0.02, y - 0.03],
                                  solid_joinstyle="miter", dash_capstyle="butt", **kw))
        else:                                         # as on the sheet: the line dashed, its ticks solid (from half
            top = y + 0.02 + AREA_LW / 144.0          # the line's width above it: they cover the corners)
            fig.add_artist(Line2D([x, x + SWATCH_IN], [y + 0.02, y + 0.02],
                                  ls=(0, tuple(v / AREA_LW for v in AREA_DASH_PT)), dash_capstyle="butt", **kw))
            fig.add_artist(Line2D([x, x, math.nan, x + SWATCH_IN, x + SWATCH_IN],
                                  [y - 0.03, top, math.nan, top, y - 0.03], **kw))
    elif entry.kind == "surface":
        sp = model.surfaces[entry.key]
        fig.add_artist(Line2D([x, x + SWATCH_IN], [y, y], transform=T, color=sp.color, lw=sp.width,
                              ls=SURFACE_DASHES.get(sp.style, "-"), solid_capstyle="butt", dash_capstyle="butt"))
    elif entry.kind == "screen":
        bx, hh = x + SWATCH_IN / 2.0 - BRACKET_DX_IN / 2.0, 0.035
        fig.add_artist(Line2D([bx + BRACKET_DX_IN, bx, bx, bx + BRACKET_DX_IN], [y + hh, y + hh, y - hh, y - hh],
                              transform=T, color=INK, lw=SCREEN_LW, solid_joinstyle="miter", solid_capstyle="butt"))
    else:                                             # measured / atd
        cx, base = x + SWATCH_IN / 2.0, y - WL_TRI_H_IN / 2.0
        fig.add_artist(Line2D([cx - WL_LINE_HALF_IN, cx + WL_LINE_HALF_IN], [base, base], transform=T, color=INK,
                              lw=WL_LW, solid_capstyle="butt"))
        fig.add_artist(Polygon([(cx, base), (cx - WL_TRI_HALF_IN, base + WL_TRI_H_IN), (cx + WL_TRI_HALF_IN,
                                base + WL_TRI_H_IN)], closed=True, transform=T, ec=WATER, lw=WL_LW, joinstyle="miter",
                               fc=WATER if entry.kind == "atd" else "white"))


def _legend_row(fig: Figure, entries: Sequence[Tuple[str, float, Any]], x0: float, y_mid: float, size: float,
                model: SectionModel, settings: Settings) -> None:
    """One row of the legend (scales.legend_rows), centred on y_mid."""
    T = fig.dpi_scale_trans
    for text, x, key in entries:
        if isinstance(key, str) and not key:          # the "Legend:" label
            fig.text(x0 + x, y_mid, text, transform=T, ha="left", va="center", fontsize=size)
            continue
        draw_swatch(fig, model, settings, key, x0 + x, y_mid)
        fig.text(x0 + x + SWATCH_IN + SWATCH_GAP_IN, y_mid, text, transform=T, ha="left", va="center", fontsize=size)


def _bottom_block(fig: Figure, model: SectionModel, settings: Settings, plan: Plan, page: PageLayout) -> None:
    """The horizontal graphic scale and the notes (and the legend) under the plot."""
    if settings.show_notes and not settings.compact_layout:
        _bottom_block_standard(fig, model, settings, plan, page)
        return
    # compact, or no notes: the scale bar with a column beside it (two note lines, then the legend)
    T = fig.dpi_scale_trans
    W, edge = page.page_w, edge_in(settings)
    entries = legend_entries(model, settings, plan.z_min, plan.z_max)     # what is drawn inside the frame
    band = bottom_band(settings, entries)
    overhang, right = hbar_extent_in(settings)
    need = notes_min_w(settings, entries)
    x0 = page.plot_left
    if x0 - overhang + need > W - edge:
        x0 = max(edge + overhang, W - edge - need + overhang)
    texts: List[str] = []
    size = band.size
    if band.note_rows:                                # the bar may move left to give the notes room
        x0, texts, size = fit_compact_notes(compact_notes(model, settings, plan, page), x0, edge + overhang,
                                            W - edge, right + COL_GAP_IN, fig)
    _hbar(fig, x0, page.plot_bottom - band.bar, settings)
    col_x = x0 + right + COL_GAP_IN
    col_w = W - edge - col_x
    y = page.plot_bottom - band.top                   # top of the first row beside the bar
    if texts:
        for i, t in enumerate(texts):
            fig.text(col_x, y - i * band.pitch, t, transform=T, ha="left", va="top", fontsize=size, color=INK)
        y -= len(texts) * band.pitch
    if entries:
        for i, row in enumerate(legend_rows(entries, col_w, band.size)):
            _legend_row(fig, row, col_x, y - i * band.pitch - band.size / 144.0, band.size, model, settings)


def _bottom_block_standard(fig: Figure, model: SectionModel, settings: Settings, plan: Plan,
                           page: PageLayout) -> None:
    """Standard layout: the scale bar HBAR_DEPTH_IN under the plot, then the wrapped notes."""
    T = fig.dpi_scale_trans
    edge = edge_in(settings)
    W = page.page_w
    x0 = page.plot_left
    if x0 + NOTES_MIN_W > W - edge:
        x0 = max(edge, W - edge - NOTES_MIN_W)
    width = min(W - edge - x0, max(NOTES_MIN_W, page.plot_w))
    y_bar = page.plot_bottom - HBAR_DEPTH_IN
    _hbar(fig, x0, y_bar, settings)
    y = page.plot_bottom - NOTES_TOP_IN
    pitch = NOTE_PITCH_IN
    # one text per wrapped line at a fixed pitch, so the spacing never depends on matplotlib's
    # multi-line layout
    for text, color in notes_text(model, settings, plan, page):
        lines = wrap_text(text, NOTE_PT, width, fig)
        for i, line in enumerate(lines):
            fig.text(x0, y - i * pitch, line, transform=T, ha="left", va="top", fontsize=NOTE_PT, color=color)
        y -= len(lines) * pitch + NOTE_GAP_IN
    entries = legend_entries(model, settings, plan.z_min, plan.z_max)
    if entries:
        y -= pitch / 2                                  # rows are centred on y
        label = "Legend:"
        fig.text(x0, y, label, transform=T, ha="left", va="center", fontsize=NOTE_PT)
        x = x0 + ink_width_pt(fig, label, NOTE_PT) / 72.0 + 0.1
        for e in entries:
            w = SWATCH_IN + SWATCH_GAP_IN + ink_width_pt(fig, e.text, NOTE_PT) / 72.0 + 0.15
            if x + w > x0 + width:
                x, y = x0 + 0.1, y - pitch
            draw_swatch(fig, model, settings, e, x, y)
            fig.text(x + SWATCH_IN + SWATCH_GAP_IN, y, e.text, transform=T, ha="left", va="center", fontsize=NOTE_PT)
            x += w


# ----------------------------------------------------------------------------- public API
def draw_page(fig: Figure, model: SectionModel, settings: Settings, plan: Plan, page: PageLayout) -> None:
    """Draw one exact-scale sheet into `fig` (resized to the page)."""
    with matplotlib.rc_context(RC):
        fig.clear()
        fig.set_size_inches(page.page_w, page.page_h, forward=False)
        fig.patch.set_facecolor("white")
        W, H = page.page_w, page.page_h
        ax = fig.add_axes((page.plot_left / W, page.plot_bottom / H, page.plot_w / W, page.plot_h / H))
        p = _Painter(fig, ax, model, settings, plan, page.x_min, page.x_max)
        p.setup_axes()
        p.grid()
        p.surfaces()
        p.ground()
        p.bends()
        p.match_lines(page)
        p.hits()
        p.screens()
        p.other_points()
        p.areas()
        p.ends()
        _title(fig, model, settings, page, getattr(plan, "above_in", 0.0))
        _vbar(fig, settings, plan, page)
        _bottom_block(fig, model, settings, plan, page)


def draw_preview(fig: Figure, model: SectionModel, settings: Settings, plan: Plan) -> List[PlacedPoint]:
    """The whole section fitted into `fig` at the export's vertical exaggeration (letterboxed). Returns where the
    other points were drawn (their hover boxes; [] without any)."""
    with matplotlib.rc_context(RC):
        fig.clear()
        fig.patch.set_facecolor("white")
        W, H = (float(v) for v in fig.get_size_inches())
        if W <= 0.5 or H <= 0.5:
            return []
        ml, mr, mt, mb = 0.72, 0.72, 0.55, 0.5
        above = getattr(plan, "above_in", 0.0)
        if above > 0.0:                                  # the band of bracket rows (0.3.6; drawn at k <= 1 of it)
            mt += above
        pw = plan.plot_length / settings.h_scale
        ph = (plan.z_max - plan.z_min) / settings.v_scale
        aw_av, ah_av = max(W - ml - mr, 0.3), max(H - mt - mb, 0.3)
        k = min(aw_av / pw, ah_av / ph)
        if above > 0.0:
            # its rows stack at the preview's own scale (scales.area_band_in): its labels are relatively larger than
            # the sheet's, so it may need more rows (never fewer than the sheet's band)
            for _ in range(3):
                own = area_band_in(model, settings, plan.plot_length, k, min(max(k, 0.85), 1.0))
                if own <= above:
                    break
                mt += own - above
                above = own
                aw_av, ah_av = max(W - ml - mr, 0.3), max(H - mt - mb, 0.3)
                k = min(aw_av / pw, ah_av / ph)
        aw, ah = pw * k, ph * k
        left, bottom = ml + (aw_av - aw) / 2.0, mb + (ah_av - ah) / 2.0
        ax = fig.add_axes((left / W, bottom / H, aw / W, ah / H))
        # paper-sized marks shrink with the drawing, but not below ~6 pt text
        p = _Painter(fig, ax, model, settings, plan, 0.0, plan.plot_length, pt_scale=min(max(k, 0.85), 1.0),
                     preview=True, above_in=above)
        p.setup_axes()
        p.grid()
        p.surfaces()
        p.ground()
        p.bends()
        p.preview_matches()
        p.hits()
        p.screens()
        placed = p.other_points()
        p.areas()
        p.ends()
        if not plan.fits and plan.message:
            lines = wrap_text("Does not fit: " + plan.message, 7.0, max(W - 0.3, 1.0))
            fig.text(0.1 / W, 1 - 0.08 / H, "\n".join(lines[:3]), ha="left", va="top", fontsize=7, color=WARN)
        return placed
