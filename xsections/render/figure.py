"""Drawing: the exact-scale sheet (draw_page) and the dock preview (draw_preview).

matplotlib Figure API only (never pyplot). On a sheet the axes box is placed and sized in
inches from the PageLayout, and its limits are the page's distance range and the plan's
elevation range, so 1 in of paper is exactly h_scale ft across and v_scale ft up. Ticks,
labels, scale bars and notes are sized in points / inches of paper (ScaledTranslation on
fig.dpi_scale_trans), so they look the same at every scale.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
import matplotlib
from matplotlib import patheffects
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon, Rectangle
from matplotlib.textpath import TextToPath
from matplotlib.ticker import FuncFormatter, MultipleLocator, NullLocator
from matplotlib.transforms import ScaledTranslation, blended_transform_factory

from ..core.model import Hit, PageLayout, Plan, SectionModel, Settings
# LABEL_* are used by the tests through this module
from .scales import LABEL_GAP_IN, LABEL_PAD_IN, LABEL_ROW_IN, LABEL_SEP, LEADER_RISE_IN  # noqa: F401
from .scales import (BRACKET_DX_IN, BRACKET_GAP_IN, WL_DX_IN, LEADER_DX_IN, LEADER_LW, LEADER_STEP_IN, MARK_EVERY_IN,
                     MARK_FIRST_IN, MARK_H_IN, MARK_HALF_IN, SCREEN_LW, WL_LABEL_GAP_IN, WL_LABEL_PT, WL_LINE_HALF_IN,
                     WL_LW, WL_TRI_H_IN, WL_TRI_HALF_IN, LegendEntry, legend_entries)
from .scales import (AXIS_PAD_PT, AXIS_TICK_PT, AXIS_TITLE_PT, COL_GAP_IN, CROSSBAR_IN, END_DIR_PT, END_PT,
                     GROUND_CLEAR_IN, HBAR_DEPTH_IN, HBAR_H_IN, HBAR_LABEL_DY_IN, HBAR_LEN_IN, HBAR_NAME_DY_IN,
                     LABEL_PT, NOTES_MIN_W, NOTE_COMPACT_PT, NOTE_MIN_PT, NOTE_NAME_MIN_CHARS, NOTE_PT, NOTE_SPACING,
                     RASTER_SLACK, RENDER_SLACK_PT, SCALE_LABEL_PT, SCALE_NAME_PT, STD_END_GAP_IN, STD_END_PT,
                     STD_HEAD_DY_IN, STD_HEAD_PT, STD_LINE_DY_IN, STD_LINE_MIN_PT, STD_LINE_PT, STD_TITLE_RAISE_IN,
                     SUBTITLE_PT_COMPACT, SWATCH_GAP_IN, SWATCH_IN, TD_EDGE_IN,
                     TD_GAP_IN, TD_PAD_IN, TD_PT, TD_ROW_IN, TD_TEXT_H_IN, TEXT_DESCENT_EM, TICK_FROM_IN, TICK_TO_IN,
                     TITLE_PT_COMPACT, VBAR_LABEL_DX_IN, VBAR_W_IN, XTITLE_PAD_PT, YTITLE_GAP_PT, LabelSpot, bar_boxes,
                     bottom_band, clamp_centre, compact_rows_in, compass16, display_label, draws_depth_line,
                     draws_td_label, draws_top_cap, edge_in, elevation_label_width_in, engineer_face, fmt_in, fmt_num,
                     fmt_station, ground_test, hbar_extent_in, label_layout, legend_rows, legend_types, mark_boxes,
                     notes_min_w, overlaps_any, pretty_label, ratio, stack_labels, td_text, tick_base, vbar_dx_in)
from .scales import spread_1d as _spread_1d

FONT = "DejaVu Sans"
# Everything that could move or resize the drawing is pinned here; used for drawing AND saving.
RC = {"font.family": "sans-serif", "font.sans-serif": [FONT], "font.size": 7.0,
      "savefig.bbox": "standard", "savefig.pad_inches": 0.0, "savefig.facecolor": "white",
      "figure.autolayout": False, "figure.constrained_layout.use": False,
      "pdf.fonttype": 42, "svg.fonttype": "none", "svg.hashsalt": "xsections",
      "path.simplify": False, "axes.unicode_minus": False, "text.usetex": False}

# --- style (defaults suit colored pencil: light grid, black data, no fills)
GRID_COLORS = {"green": ("#a8c8b2", "#5f9a72"), "gray": ("#b4b4b4", "#6e6e6e")}   # (minor, major)
MINOR_LW, MAJOR_LW, FRAME_LW, GROUND_LW = 0.35, 0.7, 0.9, 1.1
INK = "#000000"
DATA = "#2b2b2b"
DEPTH_LW, DEPTH_TYPE_LW = 0.75, 1.6
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
NOTE_PITCH_IN = NOTE_PT * NOTE_SPACING / 72.0     # baseline to baseline inside a note (NOTE_PT in scales.py)
NOTE_GAP_IN = 0.035                               # extra space between notes
TYPE_COLORS = ["#0072b2", "#d55e00", "#cc79a7", "#e69f00", "#56b4e9", "#8c564b", "#882255", "#44aa99"]
# after 8 types the colours repeat with a different line pattern (dashed, dotted, dash-dot)
TYPE_DASHES: List[Any] = ["-", (0, (5.0, 1.6)), (0, (1.0, 1.3)), (0, (5.0, 1.6, 1.0, 1.6))]
# other surfaces (decision 15) and screens / water levels (decision 16)
SURFACE_DASHES: Dict[str, Any] = {"solid": "-", "dash": (0, (5.0, 2.5)), "dot": (0, (1.0, 1.6))}
SURFACE_Z, SCREEN_Z, WL_Z = 3.0, 3.6, 4.6     # surfaces under the data lines; water levels over the ground line
MARK_CLEAR_IN = 0.15                          # water-table marks keep this clear of explorations (paper inches)
WATER = "#1f6fb2"                             # the water level triangles (only they are blue)
SURFACE_GID, MARK_GID, SCREEN_GID, LEADER_GID = "xsections-surface", "xsections-mark", "xsections-screen", "xsections-leader"
WL_GID, ATD_GID, WL_LINE_GID, WL_TEXT_GID = "xsections-wl", "xsections-atd", "xsections-wl-line", "xsections-wl-text"

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

def type_styles(model: SectionModel) -> Dict[str, Tuple[str, Any]]:
    """(colour, line style) per type value: 8 colours solid, then the same colours dashed, dotted
    and dash-dotted, so that up to 32 types stay distinct on the sheet and in the legend."""
    types = sorted({h.type_value for h in model.hits if h.type_value})
    n = len(TYPE_COLORS)
    return {t: (TYPE_COLORS[i % n], TYPE_DASHES[(i // n) % len(TYPE_DASHES)]) for i, t in enumerate(types)}


def type_colors(model: SectionModel) -> Dict[str, str]:
    return {t: c for t, (c, _) in type_styles(model).items()}


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


def _z_on(st: np.ndarray, z: np.ndarray, station: float) -> float:
    """A surface's elevation at `station` (linear between its vertices; a step's upper edge at the step)."""
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


# ----------------------------------------------------------------------------- the drawing
Box = Tuple[float, float, float, float]            # (left, right, bottom, top), paper inches from the frame


class _Layout(NamedTuple):
    """Where the exploration marks go on one page (paper inches from the frame's lower left)."""
    hits: List[Hit]                    # the explorations drawn on this page
    ticked: List[Hit]                  # those whose tick is on the plot (a manual range can cut it off)
    x_in: List[float]                  # their stations
    base_in: List[float]               # their tick bases
    texts: List[str]                   # their labels
    spots: List[LabelSpot]             # where the labels go
    marks: List[Box]                   # ticks and labels
    td: List[Tuple[str, float, float, float]]   # TD labels drawn: (text, centre x, top y, width)


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
                 x0: float, x1: float, pt_scale: float = 1.0, preview: bool = False):
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
        self.styles = type_styles(model)
        self.top_blend = blended_transform_factory(ax.transData, ax.transAxes)
        self._lay: Optional[_Layout] = None

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
        ax, p = self.ax, self.plan
        minor_c, major_c = GRID_COLORS.get(self.s.grid_color, GRID_COLORS["green"])
        min_gap = 0.035 if self.preview else 0.0           # inches; preview drops lines that would merge
        for axis, lo, hi, minor, major, kk in (("x", self.x0, self.x1, p.h_minor, p.h_major, self.kx),
                                               ("y", self.z0, self.z1, p.v_minor, p.v_major, self.kz)):
            maj_step = major * (_nice_mult(major * kk, min_gap) if min_gap else 1)
            majors = _multiples(lo, hi, maj_step)
            minors = _multiples(lo, hi, minor, skip=maj_step) if minor * kk >= min_gap and minor > 0 else []
            if maj_step != major:
                minors = []
            for vals, color, lw, z in ((minors, minor_c, MINOR_LW, 0.5), (majors, major_c, MAJOR_LW, 0.6)):
                if not vals:
                    continue
                a = np.repeat(np.asarray(vals, float), 3)
                a[2::3] = np.nan
                if axis == "x":
                    xs, ys = a, np.tile([self.z0, self.z1, np.nan], len(vals))
                else:
                    xs, ys = np.tile([self.x0, self.x1, np.nan], len(vals)), a
                ax.add_line(Line2D(xs, ys, color=color, lw=lw, solid_capstyle="butt", zorder=z))

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
        for b in self.model.bend_stations:
            if self.x0 < b < self.x1:
                ax.add_line(Line2D([b, b], [self.z0, self.z1], color=BEND, lw=0.6, ls=(0, (4, 3)), zorder=1))
                x = self._x_in(b)
                box = (x - half_w, x + half_w, lo, hi)
                if overlaps_any(taken, *box):
                    continue
                taken.append(box)
                ax.annotate("BEND", (b, 1.0), xycoords=self.top_blend, xytext=(0, 2 * k), textcoords="offset points",
                            ha="center", va="bottom", fontsize=5.5 * k, color=BEND, annotation_clip=False)

    # --- explorations
    def layout(self) -> _Layout:
        """Ticks, exploration labels and TD labels of this page (worked out once: the match notes keep
        clear of them). Labels are laid out as scales.plan() expects (scales.label_layout)."""
        if self._lay is not None:
            return self._lay
        s, k = self.s, self.k
        eps = 1e-6 * max(1.0, self.x1 - self.x0)
        lo, hi = self.x0 - eps, self.x1 + eps
        # at an inner tile edge, leave hits hugging the edge to the neighbouring sheet (it shows them whole)
        edge_ft = 0.1 / self.kx
        if self.x0 > eps:
            lo = self.x0 + edge_ft
        if self.x1 < self.plan.plot_length - eps and self.x1 < self.model.length - eps:
            hi = self.x1 - edge_ft
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
        self._lay = _Layout(hits, ticked, x_in, base_in, texts, spots, marks, self._td_layout(hits, marks))
        return self._lay

    def _td_layout(self, hits: List[Hit], marks: List[Box]) -> List[Tuple[str, float, float, float]]:
        """ "TD 50'" centred under each bottom bar. A label that would overlap another label or any bar
        drops to a lower row, and where a row allows it also keeps off the ticks, the exploration labels
        and the ground line (scales.stack_labels). A label is never drawn outside the plot frame."""
        s, k = self.s, self.k
        items = [h for h in hits if draws_td_label(h, s)]
        if not items:
            return []
        texts = [td_text(h.total_depth) for h in items]
        widths = [text_width_pt(t, TD_PT * k) / 72.0 for t in texts]
        frame_w, frame_h = self.ax_width_in(), (self.z1 - self.z0) * self.kz
        xs = [clamp_centre((h.station - self.x0) * self.kx, w, frame_w, TD_EDGE_IN * k) for h, w in zip(items, widths)]
        tops = [(h.bottom - self.z0) * self.kz - TD_GAP_IN * k for h in items]
        text_h, row_h = TD_TEXT_H_IN * k, TD_ROW_IN * k
        bars = bar_boxes(hits, s, self._x_in, self._z_in, k)
        crosses = ground_test(self.model.ground, lambda x: self.x0 + x / self.kx, self._z_in, GROUND_CLEAR_IN * k)
        rows = stack_labels(xs, tops, widths, text_h, row_h, TD_PAD_IN * k, obstacles=bars, soft=marks,
                            crosses=crosses)
        out = []
        eps = 1e-6
        for text, x, w, top, row in zip(texts, xs, widths, tops, rows):
            if row is None:
                continue                                    # no free row: the plan warns about it
            y = top - row * row_h
            if y - text_h < -eps or y > frame_h + eps:
                continue                                    # would cross the frame (manual range)
            out.append((text, x, y, w))
        return out

    def _x_in(self, station: float) -> float:
        return (station - self.x0) * self.kx

    def _z_in(self, z: float) -> float:
        return (z - self.z0) * self.kz

    def hits(self) -> None:
        ax, s, k = self.ax, self.s, self.k
        lay = self.layout()
        if not lay.hits:
            return
        by_type = s.data_color == "type"
        for h in lay.hits:
            if not draws_depth_line(h, s):
                continue
            color, ls = self.styles.get(h.type_value, (DATA, "-")) if by_type else (DATA, "-")
            lw = DEPTH_TYPE_LW if by_type else DEPTH_LW
            ax.add_line(Line2D([h.station, h.station], [h.top, h.bottom], color=color, lw=lw, ls=ls,
                               solid_capstyle="butt", dash_capstyle="butt", zorder=3.5))
            # the bar at the bottom, and the same bar at the top when the top is off the ground line
            ends = [h.bottom, h.top] if draws_top_cap(h, s) else [h.bottom]
            ax.plot([h.station] * len(ends), ends, ls="none", marker="_", ms=CROSSBAR_IN * 72 * k, mew=lw,
                    color=color, zorder=3.5, gid=CAP_GID if len(ends) == 2 else None)
            g = h.ground_at_station
            if g is not None and not math.isnan(g) and (g - h.top) / s.v_scale > 0.05:
                ax.add_line(Line2D([h.station, h.station], [g, h.top], color=color, lw=0.6,
                                   ls=(0, (1, 1.5)), zorder=3.4))
        # TD labels: a thin white halo (an outline copy underneath) keeps a label legible where a
        # neighbour's line or the grid runs through it; the copy on top stays real text in the PDF
        for text, x, y, _ in lay.td:
            kw = dict(x=self.x0 + x / self.kx, y=self.z0 + y / self.kz, s=text, ha="center", va="top",
                      fontsize=TD_PT * k, color=INK)
            ax.text(zorder=TD_HALO_Z, gid=TD_HALO_GID,
                    path_effects=[patheffects.Stroke(linewidth=HALO_PT * k, foreground="white")], **kw)
            ax.text(zorder=TD_Z, gid=TD_GID, **kw)
        if not lay.ticked:
            return
        st = np.array([h.station for h in lay.ticked], float)
        base = np.array([tick_base(h, s) for h in lay.ticked], float)
        tick_len = (TICK_TO_IN - TICK_FROM_IN) * k
        ax.plot(st, base, ls="none", marker="|", ms=tick_len * 72, mew=TICK_LW, color=INK, clip_on=False,
                transform=self.up((TICK_FROM_IN + TICK_TO_IN) / 2 * k), zorder=5)
        fs = LABEL_PT * k
        anchor = self.up(TICK_TO_IN * k)
        rotation = 90 if s.label_vertical else 0
        for j, spot in enumerate(lay.spots):
            tick_top = lay.base_in[j] + TICK_TO_IN * k
            self._label(lay.texts[j], st[j], base[j], anchor, (spot.x - lay.x_in[j]) * 72,
                        (spot.base - tick_top) * 72, rotation, spot.moved, fs)

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
                zs = _z_on(st, z, station)
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
        out = []
        x_in = MARK_FIRST_IN * k
        while x_in < w - 0.3 * k:
            for dx in (0.0, 0.35, -0.35, 0.7, -0.7):
                x = x_in + dx * k
                if not 0.3 * k <= x <= w - 0.3 * k:
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
            xb = x - BRACKET_DX_IN * fx
            mid = 0.0
            if screen:
                xt = x - BRACKET_GAP_IN * fx
                ax.add_line(Line2D([xt, xb, xb, xt], [h.screen_top, h.screen_top, h.screen_bottom, h.screen_bottom],
                                   color=INK, lw=SCREEN_LW, solid_joinstyle="miter", solid_capstyle="butt",
                                   zorder=SCREEN_Z, gid=SCREEN_GID))
                mid = (h.screen_top + h.screen_bottom) / 2.0
            n = 0
            for w in h.water_levels:
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

    def _label(self, text, x, z, anchor, dx_pt, dy_pt, rotation, leader, fs) -> None:
        arrow = None
        if leader:
            arrow = dict(arrowstyle="-", lw=0.4, color=LEADER, shrinkA=0, shrinkB=0, relpos=(0.5, 0.0))
        self.ax.annotate(text, (x, z), xycoords=anchor, xytext=(dx_pt, dy_pt), textcoords="offset points",
                         rotation=rotation, ha="center", va="bottom", fontsize=fs, color=INK,
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
        hard = ([(x - w / 2 - halo, x + w / 2 + halo, y - td_h - halo, y + halo) for _, x, y, w in lay.td]
                + lay.marks + bar_boxes(lay.hits, s, self._x_in, self._z_in, k))
        soft = [(self._x_in(h.station) - 0.01, self._x_in(h.station) + 0.01, self._z_in(min(h.top, h.bottom)),
                 self._z_in(max(h.top, h.bottom))) for h in lay.hits if draws_depth_line(h, s)]
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


def _title(fig: Figure, model: SectionModel, settings: Settings, page: PageLayout) -> None:
    """Standard layout: "CROSS SECTION A–A′" and the optional title line under it, centred on the plot. A title
    line too long to sit between the end letters lifts both lines clear of them (STD_TITLE_RAISE_IN) and may
    then run past the plot, kept within the printer edge (smaller, down to 7 pt, then cut short with "…")."""
    if settings.compact_layout:
        _title_compact(fig, settings, page)
        return
    T = fig.dpi_scale_trans
    edge, W = edge_in(settings), page.page_w
    cx = page.plot_left + page.plot_w / 2.0
    top = page.plot_bottom + page.plot_h
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


def _title_compact(fig: Figure, settings: Settings, page: PageLayout) -> None:
    """One line over the end-letter row: the title in bold, then " · " and the optional title line. Centred
    on the plot, kept within the printer edge (the title line gets smaller, then shorter, if need be)."""
    T = fig.dpi_scale_trans
    edge = edge_in(settings)
    y = page.plot_bottom + page.plot_h + compact_rows_in()[1]
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


def _nb(s: str) -> str:
    return s.replace(" ", " ")


def grid_text(plan: Plan, settings: Settings) -> Tuple[str, str]:
    """("1 in major", "0.1 in minor"), or "1 × 0.5 in major" when the paper spacings differ."""
    hm_in, vm_in = plan.h_major / settings.h_scale, plan.v_major / settings.v_scale
    hn_in, vn_in = plan.h_minor / settings.h_scale, plan.v_minor / settings.v_scale
    major = f"{fmt_in(hm_in)} in major" if abs(hm_in - vm_in) < 1e-9 else f"{fmt_in(hm_in)} × {fmt_in(vm_in)} in major"
    minor = f"{fmt_in(hn_in)} in minor" if abs(hn_in - vn_in) < 1e-9 else f"{fmt_in(hn_in)} × {fmt_in(vn_in)} in minor"
    return major, minor


def notes_text(model: SectionModel, settings: Settings, plan: Plan, page: PageLayout) -> List[Tuple[str, str]]:
    """The wrapped notes under the plot, as (text, color)."""
    H, V = settings.h_scale, settings.v_scale
    fh, fv = engineer_face(H), engineer_face(V)
    major, minor = grid_text(plan, settings)
    parts = [
        f"HORIZONTAL {_nb(f'1 in = {fmt_num(H)} ft')} ({ratio(H)})" + (f", {fh} scale" if fh else ""),
        f"VERTICAL {_nb(f'1 in = {fmt_num(V)} ft')} ({ratio(V)})" + (f", {fv} scale" if fv else ""),
        f"VERTICAL EXAGGERATION {fmt_num(H / V)}×",
        f"GRID {major}, {minor} ({_nb(f'{fmt_num(plan.h_major)} × {fmt_num(plan.v_major)} ft')}; "
        f"{_nb(f'{fmt_num(plan.h_minor)} × {fmt_num(plan.v_minor)} ft')})",
        f"SHEET {page.sheet_name}",
    ]
    note2 = " · ".join(parts)
    datum = f" ({settings.vertical_datum})" if settings.vertical_datum else ""
    dem = model.dem_name or "DEM"
    note3 = f"Ground: {dem}{datum}, sampled every {fmt_num(model.ground.step)} ft."
    if model.has_explorations:
        note3 += (f" Explorations within {fmt_num(settings.tolerance_ft)} ft of the section line are "
                  "projected perpendicular onto it.")
        if settings.label_offset:
            note3 += " Labels give each exploration's distance and direction from the section line."
    if any(draws_depth_line(h, settings) for h in model.hits):
        note3 += " " + depth_sources_text(settings, any(draws_td_label(h, settings) for h in model.hits))
    extra = [t for t in (screens_sources(model, settings), surfaces_sources(model)) if t]
    if extra:
        note3 += " " + " ".join(f"{t}." for t in extra)
    return [(note2, INK), (note3, INK)]


def screens_sources(model: SectionModel, settings: Settings) -> str:
    """Where the screens and water levels on the sheet come from, e.g. "Screens: ScrTop to ScrBot (depths below
    the top); water levels: WL_Elev, ATD_Elev (ATD), table water_levels" ("" when none is drawn)."""
    if not settings.screens:
        return ""
    hits = model.hits
    parts = []
    if any(h.screen_top is not None for h in hits):
        how = "depths below the top" if settings.screen_values != "elevation" else "elevations"
        parts.append(f"Screens: {settings.screen_top_field} to {settings.screen_bottom_field} ({how})")
    sources = []
    used = {w.source for h in hits for w in h.water_levels}
    if settings.wl_field and settings.wl_field in used:
        sources.append(settings.wl_field)
    if settings.atd_field and settings.atd_field in used:
        sources.append(f"{settings.atd_field} (ATD)")
    if "table" in used:
        sources.append("a water-level table")
    if sources:
        how = " (depths below the top)" if settings.wl_values == "depth" else ""
        parts.append(("water levels: " if parts else "Water levels: ") + ", ".join(sources) + how)
    return "; ".join(parts)


def surfaces_sources(model: SectionModel) -> str:
    """The rasters and model files behind the other surfaces, e.g. "Surfaces: Water table 2024 from wt_2024;
    mf6_botm band 1 (flat across each cell); Layer 1 head from F9_flowV1.hds (SP 30, step 13); Layer 2 bottom from
    F9_flowV1.disv.grb" ("" without surfaces)."""
    items = []
    for sp in getattr(model, "surfaces", None) or []:
        if getattr(sp, "detail", ""):                    # a MODFLOW 6 surface: what it is, which file, how drawn
            text = sp.detail                             # (its one parenthesis already says "flat across each cell")
        else:
            text = sp.name if sp.name.startswith(sp.layer_name) else f"{sp.name} from {sp.layer_name}"
            if sp.band > 1 and "band" not in text:
                text += f" band {sp.band}"
            if sp.mode == "cells":
                text += " (flat across each cell)"
        items.append(text)
    return ("Surfaces: " + "; ".join(items)) if items else ""


def depth_sources_text(settings: Settings, td: bool = False) -> str:
    """One sentence per end of the top-to-bottom lines, naming the sources configured, e.g.
    "Tops: ExploElev where available, otherwise LIDAR at the exploration. Bottoms: top minus ExploDepth." """
    lidar = "LIDAR at the exploration"
    tf, mode = settings.top_field, settings.top_mode
    if mode == "dem" or not tf:
        tops = f"Tops: {lidar}."
    elif mode == "field":
        tops = f"Tops: {tf}."
    else:
        tops = f"Tops: {tf} where available, otherwise {lidar}."
    b, d = settings.bottom_elev_field, settings.depth_field
    if b and d:
        bottoms = f"Bottoms: {b} where available, otherwise top minus {d}."
    elif b:
        bottoms = f"Bottoms: {b}."
    elif d:
        bottoms = f"Bottoms: top minus {d}."
    else:
        bottoms = ""
    return " ".join(p for p in (tops, bottoms, "TD = total depth." if td else "") if p)


class NotePart(NamedTuple):
    """One part of a compact note line (parts are joined with " · ")."""
    text: str
    rank: int = 0          # 0: always kept; when a line is too long, the highest ranks are left out first
    name: str = ""         # a name inside `text` that may be cut short with "…" (the DEM's)


def compact_notes(model: SectionModel, settings: Settings, plan: Plan, page: PageLayout) -> List[List[NotePart]]:
    """The two short note lines of the compact layout, as parts. Line 1: scales, exaggeration, grid, sheet.
    Line 2: the ground and the explorations; the depth sources, "TD = total depth" and the label offsets
    only when those marks are on the sheet (the explanations of marks on the sheet are always kept). The
    datum is in the elevation title, so it is not repeated here."""
    H, V = settings.h_scale, settings.v_scale
    fh, fv = engineer_face(H), engineer_face(V)
    major, minor = grid_text(plan, settings)
    line1 = [NotePart(f"H 1 in = {fmt_num(H)} ft ({ratio(H)})" + (f", {fh} scale" if fh else "")),
             NotePart(f"V 1 in = {fmt_num(V)} ft ({ratio(V)})" + (f", {fv} scale" if fv else "")),
             NotePart(f"VE {fmt_num(H / V)}×", 1),
             NotePart(f"GRID {major}, {minor}", 2),
             NotePart(page.sheet_name.split(",")[0], 3)]          # "Letter 11 × 8.5 in"
    dem = model.dem_name or "DEM"
    line2 = [NotePart(f"Ground: {dem}, every {fmt_num(model.ground.step)} ft", 0, dem)]
    if model.has_explorations:
        line2.append(NotePart(f"Explorations within {fmt_num(settings.tolerance_ft)} ft projected onto the line", 1))
    if any(draws_depth_line(h, settings) for h in model.hits):
        line2 += [NotePart(t, 2) for t in depth_sources_short(settings)]
        if any(draws_td_label(h, settings) for h in model.hits):
            line2.append(NotePart("TD = total depth"))
    if model.has_explorations and settings.label_offset:
        line2.append(NotePart("Labels: offset and direction from the line"))
    for text, rank in ((screens_sources(model, settings), 3), (surfaces_sources(model), 4)):
        if text:
            line2.append(NotePart(text, rank))
    return [line1, line2]


def depth_sources_short(settings: Settings) -> List[str]:
    """depth_sources_text, short: ["Tops: ExploElev, else LIDAR", "Bottoms: top − ExploDepth"]."""
    tf, mode = settings.top_field, settings.top_mode
    if mode == "dem" or not tf:
        tops = "Tops: LIDAR"
    elif mode == "field":
        tops = f"Tops: {tf}"
    else:
        tops = f"Tops: {tf}, else LIDAR"
    b, d = settings.bottom_elev_field, settings.depth_field
    if b and d:
        bottoms = f"Bottoms: {b}, else top − {d}"
    elif b:
        bottoms = f"Bottoms: {b}"
    elif d:
        bottoms = f"Bottoms: top − {d}"
    else:
        bottoms = ""
    return [t for t in (tops, bottoms) if t]


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


def draw_swatch(fig: Figure, model: SectionModel, styles: Dict[str, Tuple[str, Any]], entry: Any, x: float,
                y: float) -> None:
    """The swatch of one legend entry (a type value, or a scales.LegendEntry), SWATCH_IN wide from x, centred on
    y (paper inches)."""
    T = fig.dpi_scale_trans
    if isinstance(entry, str) or entry.kind == "type":
        c, ls = styles[entry if isinstance(entry, str) else entry.key]
        fig.add_artist(Line2D([x, x + SWATCH_IN], [y, y], transform=T, color=c, lw=DEPTH_TYPE_LW, ls=ls,
                              solid_capstyle="butt", dash_capstyle="butt"))
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
                model: SectionModel, styles: Dict[str, Tuple[str, Any]]) -> None:
    """One row of the legend (scales.legend_rows), centred on y_mid."""
    T = fig.dpi_scale_trans
    for text, x, key in entries:
        if isinstance(key, str) and not key:          # the "Line colors:" / "Legend:" label
            fig.text(x0 + x, y_mid, text, transform=T, ha="left", va="center", fontsize=size)
            continue
        draw_swatch(fig, model, styles, key, x0 + x, y_mid)
        fig.text(x0 + x + SWATCH_IN + SWATCH_GAP_IN, y_mid, text, transform=T, ha="left", va="center", fontsize=size)


def _bottom_block(fig: Figure, model: SectionModel, settings: Settings, plan: Plan, page: PageLayout) -> None:
    """The horizontal graphic scale and the notes (and the line-colour legend) under the plot."""
    if settings.show_notes and not settings.compact_layout:
        _bottom_block_standard(fig, model, settings, plan, page)
        return
    # compact, or no notes: the scale bar with a column beside it (two note lines, then the legend)
    T = fig.dpi_scale_trans
    W, edge = page.page_w, edge_in(settings)
    types = legend_entries(model, settings)
    band = bottom_band(settings, types)
    overhang, right = hbar_extent_in(settings)
    need = notes_min_w(settings, types)
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
    styles = type_styles(model)
    if types:
        for i, row in enumerate(legend_rows(types, col_w, band.size)):
            _legend_row(fig, row, col_x, y - i * band.pitch - band.size / 144.0, band.size, model, styles)


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
    y = page.plot_bottom - 0.86
    pitch = NOTE_PITCH_IN
    # one text per wrapped line at a fixed pitch, so the spacing never depends on matplotlib's
    # multi-line layout
    for text, color in notes_text(model, settings, plan, page):
        lines = wrap_text(text, NOTE_PT, width, fig)
        for i, line in enumerate(lines):
            fig.text(x0, y - i * pitch, line, transform=T, ha="left", va="top", fontsize=NOTE_PT, color=color)
        y -= len(lines) * pitch + NOTE_GAP_IN
    styles = type_styles(model)
    entries = legend_entries(model, settings)
    if entries:
        y -= pitch / 2                                  # rows are centred on y
        label = "Line colors:" if all(e.kind == "type" for e in entries) else "Legend:"
        fig.text(x0, y, label, transform=T, ha="left", va="center", fontsize=NOTE_PT)
        x = x0 + ink_width_pt(fig, label, NOTE_PT) / 72.0 + 0.1
        for e in entries:
            w = SWATCH_IN + SWATCH_GAP_IN + ink_width_pt(fig, e.text, NOTE_PT) / 72.0 + 0.15
            if x + w > x0 + width:
                x, y = x0 + 0.1, y - pitch
            draw_swatch(fig, model, styles, e, x, y)
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
        p.ends()
        _title(fig, model, settings, page)
        _vbar(fig, settings, plan, page)
        _bottom_block(fig, model, settings, plan, page)


def draw_preview(fig: Figure, model: SectionModel, settings: Settings, plan: Plan) -> None:
    """The whole section fitted into `fig` at the export's vertical exaggeration (letterboxed)."""
    with matplotlib.rc_context(RC):
        fig.clear()
        fig.patch.set_facecolor("white")
        W, H = (float(v) for v in fig.get_size_inches())
        if W <= 0.5 or H <= 0.5:
            return
        ml, mr, mt, mb = 0.72, 0.72, 0.55, 0.5
        pw = plan.plot_length / settings.h_scale
        ph = (plan.z_max - plan.z_min) / settings.v_scale
        aw_av, ah_av = max(W - ml - mr, 0.3), max(H - mt - mb, 0.3)
        k = min(aw_av / pw, ah_av / ph)
        aw, ah = pw * k, ph * k
        left, bottom = ml + (aw_av - aw) / 2.0, mb + (ah_av - ah) / 2.0
        ax = fig.add_axes((left / W, bottom / H, aw / W, ah / H))
        # paper-sized marks shrink with the drawing, but not below ~6 pt text
        p = _Painter(fig, ax, model, settings, plan, 0.0, plan.plot_length, pt_scale=min(max(k, 0.85), 1.0),
                     preview=True)
        p.setup_axes()
        p.grid()
        p.surfaces()
        p.ground()
        p.bends()
        p.preview_matches()
        p.hits()
        p.screens()
        p.ends()
        if not plan.fits and plan.message:
            lines = wrap_text("Does not fit: " + plan.message, 7.0, max(W - 0.3, 1.0))
            fig.text(0.1 / W, 1 - 0.08 / H, "\n".join(lines[:3]), ha="left", va="top", fontsize=7, color=WARN)
