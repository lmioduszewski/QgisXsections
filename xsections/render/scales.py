"""Page planning: plot size from the scales, elevation limits, sheet choice and tiling.

Pure arithmetic in inches and feet (no matplotlib, no Qt). The plot area is always
exactly (distance range / h_scale) x (elevation range / v_scale) inches; nothing here
ever shrinks a drawing to fit a page.
"""
from __future__ import annotations

import bisect
import dataclasses
import math
from typing import Any, Callable, Iterable, List, NamedTuple, Optional, Sequence, Tuple, Union

from ..core.model import (GroundProfile, Hit, PageLayout, Plan, SectionError, SectionModel, Settings,
                          clean_orientation)

# name -> (long side, short side, display name), inches
SHEETS = {"letter": (11, 8.5, "Letter"), "tabloid": (17, 11, "Tabloid"), "ansic": (22, 17, "ANSI C"),
          "archc": (24, 18, "ARCH C"), "ansid": (34, 22, "ANSI D"), "archd": (36, 24, "ARCH D")}
MARGIN = dict(left=1.0, right=1.5, top=1.2, bottom=2.3)   # standard layout, 0.5 in printer edge (see margins())
SAFE_EDGE = 0.5                                            # default printer edge: marks stay >= this far in
EDGE_CHOICES = (0.5, 0.3)                                  # printer edge offered in the panel, inches
FILL_CHOICES = ("off", "below", "both")                    # fill the sheet with grid: off | below | above and below
NOTES_MIN_W = 6.4                                          # width the scale bars + notes need (standard layout)
CUSTOM_MIN = (8.5, 5.5)                                    # smallest custom page, inches
LABEL_HEADROOM_IN = 0.9                                    # least room above the highest tick (auto z)

# exploration ticks and labels, paper inches / points (figure.py draws them with these numbers)
TICK_FROM_IN, TICK_TO_IN = 0.04, 0.18      # the tick runs from tick_base + 0.04 in to + 0.18 in
LABEL_PT = 7.0
LABEL_SEP = 1.18                           # vertical labels closer than this x font height are spread
LABEL_GAP_IN, LEADER_RISE_IN = 0.02, 0.10  # label above its own tick / above a spread cluster
LABEL_ROW_IN = 1.15 * LABEL_PT / 72.0      # height of a row of horizontal labels
LABEL_PAD_IN = 0.04                        # gap kept between horizontal labels
LABEL_MARGIN_IN = 0.1                      # grid kept clear above the highest label (auto z)
TICK_HALF_IN = 0.01                        # half the width a tick takes (TD labels keep off it)

# top-to-bottom line extras, paper inches / points
CROSSBAR_IN = 0.08                         # bar across the bottom (and, when off the ground line, the top)
BAR_CLEAR_IN = 0.02                        # height a TD label keeps clear around any such bar
TOP_CAP_MIN_IN = 0.04                      # a bar across the top when it is further than this from the ground
TD_PT = 6.5                                # "TD 50'" under the bottom bar
TD_GAP_IN = 0.03                           # bottom bar to the top of its TD label
TD_TEXT_H_IN = 0.10                        # room one TD label takes (it renders 0.09 in tall at 6.5 pt)
TD_ROW_IN = 0.12                           # a TD label that would overlap another drops this much lower
TD_MAX_ROWS = 3                            # ... at most twice; a label with no free row is left out
TD_PAD_IN = 0.03                           # least gap kept between TD labels side by side
TD_EDGE_IN = 0.045                         # a TD label moved in at a frame end stays this clear of the frame
GROUND_CLEAR_IN = 0.02                     # TD labels (and match notes) keep this clear of the ground line
# an exploration of a row out of the elevation range that runs below the frame (runs_below): its line stops at the
# frame bottom with a small arrow, its TD beside it (paper inches)
CLIP_ARROW_HALF_IN, CLIP_ARROW_H_IN, CLIP_ARROW_TIP_IN = 0.03, 0.04, 0.015   # chevron half width, height, tip lift
CLIP_TD_BASE_IN, CLIP_TD_DX_IN = 0.03, 0.045   # its TD: baseline above the frame bottom; clear of the line

# screens and water levels (decision 16), paper inches / points
BRACKET_DX_IN = 0.05                       # screen bracket: its upright this far left of the exploration line
BRACKET_GAP_IN = 0.012                     # ... its ticks stop this short of the line
LEADER_DX_IN = 0.15                        # measured level: the leader's upright this far left of the line
LEADER_STEP_IN = 0.10                      # ... a second measured level of the same exploration goes this much further
WL_DX_IN = 0.09                            # a level not on a leader (ATD, or no screen): this far left of the line
WL_TRI_H_IN, WL_TRI_HALF_IN = 0.075, 0.043  # water level triangle: height, half width (tip on the level)
WL_LINE_HALF_IN = 0.07                     # the line under it: half length
WL_LABEL_PT = 5.5                          # "652.8 (6/12/2025)" left of the symbol
WL_LABEL_GAP_IN = 0.02
SCREEN_LW, LEADER_LW, WL_LW = 0.75, 0.5, 0.6
MARK_EVERY_IN = 2.0                        # water-table marks along a surface: one every 2 in of paper
MARK_FIRST_IN = 1.0                        # the first 1 in from the sheet's left edge
MARK_H_IN, MARK_HALF_IN = 0.06, 0.035      # their triangle

# sheet furniture around the frame (figure.py draws it with these numbers; margins() adds it up).
# One line of DejaVu Sans text takes 1 em of height as matplotlib lays it out: 0.76 em above the baseline,
# 0.24 em below (accented capitals reach a little higher; LAYOUT_PAD_IN covers them).
TEXT_DESCENT_EM = 0.24
LAYOUT_PAD_IN = 0.03                       # kept between the outermost mark and the printer edge
AXIS_TICK_PT, AXIS_PAD_PT = 3.0, 2.0       # axis tick length and the gap to its label
AXIS_TITLE_PT = 8.0                        # "Distance along section (ft)", "Elevation (ft NAVD88)"
XTITLE_PAD_PT, YTITLE_GAP_PT = 3.0, 4.0    # tick labels to the distance title / to the elevation titles
RENDER_SLACK_PT = 1.5                      # renderers lay a rotated line out a little taller than the metrics
NOTE_PT, NOTE_SPACING = 6.3, 1.3           # standard notes: size and line pitch (x size)
SCALE_LABEL_PT, SCALE_NAME_PT = 6.3, 5.3   # graphic scales: "0 ... 400 ft" and "HORIZONTAL" / "VERTICAL"
HBAR_DEPTH_IN = 0.64                       # standard layout: frame bottom to the bottom of the horizontal bar
HBAR_LEN_IN, HBAR_H_IN = 2.0, 0.06         # horizontal graphic scale: 4 segments of 0.5 in
HBAR_LABEL_DY_IN = 0.09                    # bar bottom to the bottom of its number labels
HBAR_NAME_DY_IN = 0.05                     # standard: bar bottom to the top of "HORIZONTAL" under it
VBAR_STD_DX_IN = 0.64                      # standard: frame right to the vertical bar
VBAR_W_IN, VBAR_LABEL_DX_IN = 0.06, 0.1    # vertical bar width; bar to its "0" / "20 ft" labels
# standard title block: baselines above the frame, sizes; both lines are lifted STD_TITLE_RAISE_IN clear of the
# end letters (12 pt bold, their tops 0.333 in above the frame) when the title line is too long to sit between them
STD_HEAD_DY_IN, STD_LINE_DY_IN = 0.50, 0.34
STD_HEAD_PT, STD_LINE_PT, STD_LINE_MIN_PT = 12.0, 8.5, 7.0
STD_END_PT = 12.0
STD_TITLE_RAISE_IN = 0.04
STD_END_GAP_IN = 0.05                      # title line kept this clear of an end letter beside it
# compact layout
END_PT, END_DIR_PT = 11.0, 7.0             # end letter (bold) and its compass direction, one line
END_ROW_GAP_IN = 0.03                      # frame top to the bottom of the end-letter row
TITLE_PT_COMPACT, SUBTITLE_PT_COMPACT = 11.0, 9.0
TITLE_ROW_GAP_IN = 0.05                    # end-letter row to the title row
BAND_GAP_IN = 0.06                         # distance title to the band (scale bar + notes)
COL_GAP_IN = 0.25                          # scale bar block to the notes beside it
NOTE_COMPACT_PT, NOTE_MIN_PT = 5.8, 5.5    # compact notes: two lines, 5.5 pt when 5.8 does not fit
NOTE_NAME_MIN_CHARS = 16                   # a DEM name cut short in the compact notes keeps at least this much
COMPACT_NOTES_MIN_W = 3.6                  # least width kept for the two note lines
LEGEND_MIN_W = 2.4                         # least width kept for a legend beside the scale bar
VBAR_GAP_IN = 0.08                         # compact: right elevation labels to the vertical bar
SWATCH_IN, SWATCH_GAP_IN, ENTRY_GAP_IN = 0.22, 0.05, 0.15   # legend: swatch, gap to its name, gap after it
RASTER_SLACK = 1.05                        # a PNG draws small type up to ~3-5 % wider than its outlines at 150-600 dpi

# DejaVu Sans advance widths (1/1000 em) of ASCII 32..126, so that label lengths can be estimated
# here without matplotlib (within about 1 % of the drawn text; kerning ignored)
_ADVANCE = (318, 401, 460, 838, 636, 950, 780, 275, 390, 390, 500, 838, 318, 361, 318, 337, 636, 636, 636, 636,
            636, 636, 636, 636, 636, 636, 337, 337, 838, 838, 838, 531, 1000, 684, 686, 698, 770, 632, 575, 775,
            752, 295, 295, 656, 557, 863, 748, 787, 603, 787, 695, 635, 611, 732, 684, 989, 685, 611, 685, 390,
            337, 390, 838, 500, 500, 613, 635, 550, 635, 615, 352, 635, 634, 278, 278, 579, 278, 974, 634, 612,
            635, 635, 411, 521, 392, 634, 592, 818, 592, 592, 525, 636, 337, 636, 838)
_ADVANCE_OTHER = {"·": 318, "′": 227, "×": 838, "–": 500, " ": 318, "…": 1000, "−": 838}

_EPS = 1e-9


# ----------------------------------------------------------------------------- formatting helpers
def fmt_num(v: float, decimals: int = 2) -> str:
    """1000 -> '1,000'; 2.5 -> '2.5'; -50 -> '-50'."""
    if abs(v - round(v)) < 1e-6:
        return f"{int(round(v)):,}"
    return f"{v:,.{decimals}f}".rstrip("0").rstrip(".")


def fmt_in(v: float) -> str:
    """Paper inches: 1 -> '1', 0.1 -> '0.1', 5.1 -> '5.10' is avoided -> '5.1'."""
    return fmt_num(v, 3)


def fmt_station(v: float) -> str:
    """Civil station: 1000 -> '10+00', 3250 -> '32+50', 45.5 -> '0+45.5'."""
    v = round(float(v), 2)
    sign = "-" if v < 0 else ""
    v = abs(v)
    hundreds = int(math.floor(v / 100.0 + 1e-9))
    rest = round(v - hundreds * 100.0, 2)
    if rest >= 100.0:                       # rounding guard
        hundreds, rest = hundreds + 1, 0.0
    if abs(rest - round(rest)) < 1e-9:
        return f"{sign}{hundreds}+{int(round(rest)):02d}"
    return f"{sign}{hundreds}+{rest:05.2f}".rstrip("0").rstrip(".")


_COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass16(azimuth_deg: float) -> str:
    """16-point compass name of an azimuth (degrees clockwise from north)."""
    if azimuth_deg is None or math.isnan(azimuth_deg):
        return ""
    return _COMPASS16[int((azimuth_deg % 360.0) / 22.5 + 0.5) % 16]


def engineer_face(scale_ft_per_in: float) -> Optional[int]:
    """Engineer's scale face k in {10..60} with scale/k in {0.1, 1, 10, 100, 1000}; None if none.

    1 in = 5 ft reads on the 50 face (0.1 ft per division); 1 in = 1,000 ft on the 10 face.
    """
    for k in (10, 20, 30, 40, 50, 60):
        r = scale_ft_per_in / k
        for m in (0.1, 1, 10, 100, 1000):
            if abs(r - m) < 1e-9 * m:
                return k
    return None


def ratio(scale_ft_per_in: float) -> str:
    """Representative fraction: 1,000 ft/in -> '1:12,000'."""
    return f"1:{fmt_num(scale_ft_per_in * 12.0)}"


def pretty_label(s: str) -> str:
    """End labels typed with an apostrophe get a real prime: A' -> A′."""
    return (s or "").replace("'", "′")


def display_label(hit: Hit, settings: Settings) -> str:
    """'MW-3' or, with label_offset, 'MW-3 · 40 ft S': the offset and the direction it was projected onto the line
    (hit.direction, 0.3.5: a well 40 ft north of an east-west line)."""
    name = hit.label if hit.label not in (None, "") else str(hit.fid)
    if settings.label_offset:
        d = f" {hit.direction}" if hit.direction else ""
        return f"{name} · {fmt_num(round(hit.offset))} ft{d}"
    return name


def text_width_in(text: str, size_pt: float) -> float:
    """Estimated width of one line of DejaVu Sans text, paper inches."""
    units = 0
    for ch in text:
        o = ord(ch)
        units += _ADVANCE[o - 32] if 32 <= o < 127 else _ADVANCE_OTHER.get(ch, 636)
    return units / 1000.0 * size_pt / 72.0


def _finite(v: Optional[float]) -> bool:
    return v is not None and not math.isnan(v)


def draws_depth_line(hit: Hit, settings: Settings) -> bool:
    """True when the sheet shows this exploration's top-to-bottom line."""
    return bool(settings.depth_line) and _finite(hit.top) and _finite(hit.bottom)


def hit_in_range(hit: Any) -> bool:
    """True when the exploration's row counts toward the automatic elevation range (Hit.in_range; True for
    anything without one)."""
    return bool(getattr(hit, "in_range", True))


def runs_below(hit: Hit, z_min: float, settings: Settings) -> bool:
    """True when an exploration of a row left out of the elevation range reaches below the frame bottom `z_min`
    (the drawn one, fill included): the sheet stops its line at the frame with an arrow and writes its TD beside
    it (decision 22). In-range rows under a manual range are clipped as before (never this)."""
    return ((not hit_in_range(hit)) and draws_depth_line(hit, settings)
            and hit.bottom < z_min - 1e-9 * max(1.0, abs(z_min)) and hit.top > z_min)


def frame_levels(hit: Any, z_min: Optional[float] = None, z_max: Optional[float] = None) -> list:
    """The water levels of `hit` a sheet with the frame [z_min, z_max] draws: every one of an in-range row (a manual
    range clips them, as always); of a row left out of the elevation range only those inside the frame (they never
    widen it, decision 22: one outside it is not drawn, and the legend and the notes do not list it). Every level
    without `z_min`."""
    levels = list(getattr(hit, "water_levels", None) or [])
    if z_min is None or hit_in_range(hit):
        return levels
    hi = math.inf if z_max is None else z_max
    return [w for w in levels if z_min <= w.elev <= hi]


def frame_screen(hit: Any, z_min: Optional[float] = None) -> bool:
    """True when a sheet with the frame bottom `z_min` draws the screen of `hit` (it has one): always for an in-range
    row; for a row left out of the elevation range only when the screen's top is inside the frame."""
    top = getattr(hit, "screen_top", None)
    return _finite(top) and (z_min is None or hit_in_range(hit) or top >= z_min)


def draws_top_cap(hit: Hit, settings: Settings) -> bool:
    """A bar across the top of the line, like the one at the bottom, when the top is more than
    TOP_CAP_MIN_IN (paper) from the ground line at the station: a projected exploration whose top
    does not sit on the drawn ground still shows where it starts."""
    if not draws_depth_line(hit, settings):
        return False
    g = hit.ground_at_station
    if not _finite(g):
        return True
    return abs(hit.top - g) / settings.v_scale > TOP_CAP_MIN_IN


def draws_td_label(hit: Hit, settings: Settings) -> bool:
    """True when the sheet writes this exploration's total depth under its bottom bar."""
    return bool(settings.td_label) and draws_depth_line(hit, settings) and _finite(hit.total_depth)


def td_text(total_depth: float) -> str:
    """50 -> "TD 50'", 49.97 -> "TD 50'", 31.5 -> "TD 31.5'" (whole feet within 0.05 ft, else one decimal)."""
    v = float(total_depth)
    whole = round(v)
    if abs(v - whole) <= 0.05 + 1e-9:
        return f"TD {int(whole)}'"
    return f"TD {v:.1f}'"


def overlaps_any(boxes: Iterable[Tuple[float, float, float, float]], left: float, right: float, bottom: float,
                 top: float) -> bool:
    """True when the box (left, right, bottom, top) overlaps any of `boxes`."""
    return any(bl < right and left < br and bb < top and bottom < bt for bl, br, bb, bt in boxes)


def stack_labels(xs: Sequence[float], tops: Sequence[float], widths: Sequence[float], text_h: float,
                 row_h: float, pad: float, max_rows: int = TD_MAX_ROWS,
                 obstacles: Iterable[Tuple[float, float, float, float]] = (),
                 soft: Iterable[Tuple[float, float, float, float]] = (),
                 crosses: Optional[Callable[[float, float, float, float], bool]] = None) -> List[Optional[int]]:
    """Row of each label hung below its own anchor (0 = right under it), in any consistent units with
    y up: sweeping by x, a label that would overlap one already placed (or one of the `obstacles`,
    boxes (left, right, bottom, top)) drops `row_h` lower, up to `max_rows` rows; None when every row
    clashes. `tops` are the row-0 tops, `xs` the centres.

    `soft` boxes (ticks and exploration labels) and the `crosses(left, right, bottom, top)` test (the
    ground line) are avoided where a row allows it: among the rows clear of the other labels and the
    `obstacles`, a label takes the one that covers the least of the soft boxes, then one clear of the
    ground, then the highest. They never leave a label out."""
    rows: List[Optional[int]] = [None] * len(xs)
    placed: List[Tuple[float, float, float, float]] = list(obstacles)   # left, right, bottom, top
    soft = list(soft)
    for i in sorted(range(len(xs)), key=lambda j: (xs[j], j)):
        left, right = xs[i] - widths[i] / 2 - pad / 2, xs[i] + widths[i] / 2 + pad / 2
        best = None                                  # (soft area covered, crosses the ground, row)
        for row in range(max_rows):
            t = tops[i] - row * row_h
            b = t - text_h
            if overlaps_any(placed, left, right, b, t):
                continue
            covered = sum(max(0.0, min(right, sr) - max(left, sl)) * max(0.0, min(t, st) - max(b, sb))
                          for sl, sr, sb, st in soft)
            key = (round(covered, 9), crosses is not None and crosses(left, right, b, t), row)
            if best is None or key < best:
                best = key
            if key[:2] == (0.0, False):
                break                                # clear of everything: no need to look lower
        if best is not None:
            rows[i] = best[2]
            t = tops[i] - best[2] * row_h
            placed.append((left, right, t - text_h, t))
    return rows


def clamp_centre(x: float, width: float, frame_w: float, inset: float = 0.0) -> float:
    """Centre of a text `width` wide moved just enough to keep it `inset` inside [0, frame_w]."""
    lo, hi = width / 2.0 + inset, frame_w - width / 2.0 - inset
    if lo > hi:
        return frame_w / 2.0
    return min(max(x, lo), hi)


def bar_boxes(hits: Iterable[Hit], settings: Settings, x_in: Callable[[float], float],
              z_in: Callable[[float], float], k: float = 1.0,
              z_floor: Optional[float] = None) -> List[Tuple[float, float, float, float]]:
    """Boxes (left, right, bottom, top) of the bars across the ends of the drawn lines, in the units of
    `x_in` (station ->) and `z_in` (elevation ->). TD labels keep clear of them: a label may cross a
    neighbour's line, never hide where it ends. With `z_floor` (the frame bottom, ft), a bottom bar below it is
    left out (it is not drawn)."""
    half_w, half_h = CROSSBAR_IN * k / 2.0, BAR_CLEAR_IN * k / 2.0
    out = []
    tol = 0.0 if z_floor is None else 1e-9 * max(1.0, abs(z_floor))
    for h in hits:
        if not draws_depth_line(h, settings):
            continue
        ends = [h.bottom] if z_floor is None or h.bottom >= z_floor - tol else []
        for z in ends + ([h.top] if draws_top_cap(h, settings) else []):
            x, y = x_in(h.station), z_in(z)
            out.append((x - half_w, x + half_w, y - half_h, y + half_h))
    return out


def ground_test(ground: GroundProfile, to_station: Callable[[float], float], z_in: Callable[[float], float],
                clear: float = GROUND_CLEAR_IN) -> Callable[[float, float, float, float], bool]:
    """crosses(left, right, bottom, top) in paper units: True when the drawn ground line passes within
    `clear` of that box. `to_station` maps paper x to a station, `z_in` an elevation to paper y."""
    st, zz = ground.stations, ground.z

    def crosses(left: float, right: float, bottom: float, top: float) -> bool:
        a, c = to_station(left), to_station(right)
        i0, i1 = bisect.bisect_left(st, a), bisect.bisect_right(st, c)
        vals = [z_in(v) for v in [zz[j] for j in range(i0, i1)] + [ground.z_at(a), ground.z_at(c)] if _finite(v)]
        return bool(vals) and min(vals) <= top + clear and max(vals) >= bottom - clear
    return crosses


# ----------------------------------------------------------------------------- exploration labels
def spread_1d(xs: Sequence[float], sep: float) -> Tuple[List[float], List[int]]:
    """Minimal-displacement 1-D spreading: positions >= sep apart, order kept.

    Returns (positions, cluster id). Classic cluster merge: each cluster sits centred on the mean of
    its members, and overlapping neighbours merge (least-squares optimum).
    """
    xs = [float(x) for x in xs]
    clusters: List[list] = []                      # [member indices, start position]
    for i in sorted(range(len(xs)), key=lambda j: xs[j]):
        clusters.append([[i], xs[i]])
        while True:
            m = clusters[-1][0]
            clusters[-1][1] = sum(xs[j] for j in m) / len(m) - (len(m) - 1) * sep / 2.0
            if len(clusters) > 1:
                pm, ps = clusters[-2]
                if clusters[-1][1] < ps + len(pm) * sep - 1e-12:
                    pm.extend(m)
                    clusters.pop()
                    continue
            break
    pos, grp = [0.0] * len(xs), [0] * len(xs)
    for g, (m, start) in enumerate(clusters):
        for n, j in enumerate(m):
            pos[j], grp[j] = start + n * sep, g
    return pos, grp


class LabelSpot(NamedTuple):
    x: float                                   # centre of the label, paper inches
    base: float                                # its bottom (a vertical label reads upwards from here)
    moved: bool                                # away from its tick: drawn with a leader
    box: Tuple[float, float, float, float]     # (left, right, bottom, top) of the text


def label_layout(xs: Sequence[float], tick_tops: Sequence[float], widths: Sequence[float], vertical: bool,
                 k: float = 1.0, frame_w: Optional[float] = None) -> List[LabelSpot]:
    """Exploration labels above their ticks, as figure.py draws them (paper inches, y up; `widths` are
    the text lengths). Vertical labels closer than LABEL_SEP x the font height are spread sideways
    (spread_1d) and stand LEADER_RISE_IN above their cluster's highest tick. Horizontal labels go in
    staggered rows, in x order, each at the lowest spot above its tick that clears those placed, kept
    inside [0, frame_w] when they fit."""
    n = len(xs)
    line_h = LABEL_ROW_IN * k
    out: List[LabelSpot] = []
    if vertical:
        pos, grp = spread_1d(xs, LABEL_SEP * LABEL_PT * k / 72.0)
        top_of: dict = {}
        size_of: dict = {}
        for j, g in enumerate(grp):
            top_of[g] = max(top_of.get(g, -math.inf), tick_tops[j])
            size_of[g] = size_of.get(g, 0) + 1
        for j, g in enumerate(grp):
            moved = size_of[g] > 1
            base = top_of[g] + (LEADER_RISE_IN if moved else LABEL_GAP_IN) * k
            out.append(LabelSpot(pos[j], base, moved, (pos[j] - line_h / 2, pos[j] + line_h / 2, base,
                                                       base + widths[j])))
        return out
    pad = LABEL_PAD_IN * k
    cx = [float(x) for x in xs]
    if frame_w is not None:
        for i in range(n):
            if widths[i] < frame_w:
                cx[i] = min(max(cx[i], widths[i] / 2), frame_w - widths[i] / 2)
    bases = [0.0] * n
    placed: List[Tuple[float, float, float, float]] = []
    for i in sorted(range(n), key=lambda j: xs[j]):
        left, right = cx[i] - widths[i] / 2 - pad, cx[i] + widths[i] / 2 + pad
        b = tick_tops[i] + LABEL_GAP_IN * k
        while True:
            clash = [t for (pl, pr, pb, t) in placed if pl < right and left < pr and pb < b + line_h and b < t]
            if not clash:
                break
            b = max(clash) + 0.01 * k
        placed.append((left, right, b, b + line_h))
        bases[i] = b
    for i in range(n):
        moved = bases[i] - tick_tops[i] > LABEL_GAP_IN * k + 1e-6 or abs(cx[i] - xs[i]) > 1e-6
        out.append(LabelSpot(cx[i], bases[i], moved,
                             (cx[i] - widths[i] / 2, cx[i] + widths[i] / 2, bases[i], bases[i] + line_h)))
    return out


def mark_boxes(xs: Sequence[float], tick_bases: Sequence[float], spots: Sequence[LabelSpot],
               k: float = 1.0) -> List[Tuple[float, float, float, float]]:
    """Boxes (left, right, bottom, top) of the ticks and of their labels, paper inches."""
    out = [(x - TICK_HALF_IN * k, x + TICK_HALF_IN * k, b + TICK_FROM_IN * k, b + TICK_TO_IN * k)
           for x, b in zip(xs, tick_bases)]
    return out + [sp.box for sp in spots]


def marks_on_paper(hits: Iterable[Hit], settings: Settings, frame_w: float,
                   z_range: Optional[Tuple[float, float]] = None) -> List[Tuple[float, float, float, float]]:
    """Ticks and exploration labels of `hits` across the whole section (paper inches from station 0 and
    elevation 0), laid out as figure.py draws them. With `z_range`, ticks outside it are not drawn."""
    v, hs = float(settings.v_scale), float(settings.h_scale)
    items = []
    for h in hits:
        b = tick_base(h, settings)
        if not _finite(b):
            continue
        if z_range is not None:
            tol = 1e-9 * max(1.0, abs(z_range[1] - z_range[0]))
            if not z_range[0] - tol <= b <= z_range[1] + tol:
                continue
        items.append((h.station / hs, b / v, text_width_in(display_label(h, settings), LABEL_PT)))
    xs = [it[0] for it in items]
    bases = [it[1] for it in items]
    spots = label_layout(xs, [b + TICK_TO_IN for b in bases], [it[2] for it in items], settings.label_vertical,
                         1.0, frame_w)
    return mark_boxes(xs, bases, spots)


def td_labels(hits: Iterable[Hit], settings: Settings, plot_length: float, ground: Optional[GroundProfile] = None,
              z_range: Optional[Tuple[float, float]] = None,
              label_hits: Optional[Iterable[Hit]] = None) -> List[Tuple[Hit, Optional[float]]]:
    """(hit, lowest elevation its TD label reaches (ft), or None when it has no free row) for every hit
    with a TD label, laid out on paper as figure.py draws them across the whole section: clear of the
    other TD labels and of the bars, and where a row allows it clear of the ticks, the exploration labels
    and (given `ground`) the ground line. With `label_hits`, only those labels are laid out (the plan: the
    in-range rows); the bars and marks of all `hits` stay in their way."""
    v, hs = float(settings.v_scale), float(settings.h_scale)
    hits = list(hits)
    items = [h for h in (hits if label_hits is None else list(label_hits)) if draws_td_label(h, settings)]
    if not items:
        return []
    frame_w = plot_length / hs
    widths = [text_width_in(td_text(h.total_depth), TD_PT) for h in items]
    xs = [clamp_centre(h.station / hs, w, frame_w, TD_EDGE_IN) for h, w in zip(items, widths)]
    tops = [h.bottom / v - TD_GAP_IN for h in items]
    bars = bar_boxes(hits, settings, lambda st: st / hs, lambda z: z / v)
    marks = marks_on_paper(hits, settings, frame_w, z_range)
    crosses = ground_test(ground, lambda x: x * hs, lambda z: z / v) if ground is not None else None
    rows = stack_labels(xs, tops, widths, TD_TEXT_H_IN, TD_ROW_IN, TD_PAD_IN, obstacles=bars, soft=marks,
                        crosses=crosses)
    return [(h, None if r is None else (t - r * TD_ROW_IN - TD_TEXT_H_IN) * v)
            for h, t, r in zip(items, tops, rows)]


class TdBeside(NamedTuple):
    """A TD label beside an exploration's line (paper inches, y up)."""
    ha: str                                    # "left": right of the line; "right": left of it
    x: float                                   # anchor x (its ha)
    y: float                                   # anchor y: its centre (va "center") or baseline (va "baseline")
    box: Tuple[float, float, float, float]     # (left, right, bottom, top) of the text


def td_beside(x: float, w: float, y: float, va: str, k: float, frame_w: float,
              side: Optional[str] = None) -> TdBeside:
    """A TD label `w` wide CLIP_TD_DX_IN x k beside a line at paper x: right of it (`side` "right"), left of it
    ("left"), or (None) right of it unless it would end within TD_EDGE_IN of the frame's right edge. `y` is its
    centre (va "center") or baseline (va "baseline")."""
    dx = CLIP_TD_DX_IN * k
    if side is None:
        side = "left" if x + dx + w > frame_w - TD_EDGE_IN * k else "right"
    if side == "left":
        ha, ax_x, left = "right", x - dx, x - dx - w
    else:
        ha, ax_x, left = "left", x + dx, x + dx
    text_h = TD_TEXT_H_IN * k
    bottom = y - text_h / 2.0 if va == "center" else y - TEXT_DESCENT_EM * TD_PT * k / 72.0
    return TdBeside(ha, ax_x, y, (left, left + w, bottom, bottom + text_h))


def _beside_spot(cands: Sequence[TdBeside], bars: Sequence[Tuple[float, float, float, float]],
                 labels: Sequence[Tuple[float, float, float, float]], pad: float, frame_w: float, y0: float,
                 y1: float, must: bool) -> Optional[TdBeside]:
    """The first of `cands` inside the frame ([0, frame_w] x [y0, y1]) whose box (TD_PAD_IN wider) clears the
    `bars` (bars and below-the-frame arrows) and the TD `labels` placed. None when there is none, unless `must`: then
    the one inside the frame that covers the least of the bars, then of the labels (the first candidate when none is
    inside)."""
    eps = 1e-6
    best = None
    for i, c in enumerate(cands):
        left, right, bottom, top = c.box[0] - pad / 2.0, c.box[1] + pad / 2.0, c.box[2], c.box[3]
        if c.box[0] < -eps or c.box[1] > frame_w + eps or bottom < y0 - eps or top > y1 + eps:
            continue
        if not overlaps_any(bars, left, right, bottom, top) and not overlaps_any(labels, left, right, bottom, top):
            return c
        if must:
            def area(boxes):
                return sum(max(0.0, min(right, br) - max(left, bl)) * max(0.0, min(top, bt) - max(bottom, bb))
                           for bl, br, bb, bt in boxes)
            key = (round(area(bars), 12), round(area(labels), 12), i)
            if best is None or key < best[0]:
                best = (key, c)
    if not must:
        return None
    return best[1] if best is not None else (cands[0] if cands else None)


class TdPlace(NamedTuple):
    """Where the TD label of an exploration goes on a page (td_page_layout; paper inches, y up)."""
    hit: Hit
    text: str
    kind: str          # "under": centred under its bottom bar (x its centre, y its top); "side": beside the line of an
    #                    out-of-range exploration drawn whole (va "center"); "clip": beside the arrow of one that runs
    #                    below the frame (va "baseline")
    ha: str
    x: float
    y: float
    w: float
    box: Tuple[float, float, float, float]


def td_page_layout(hits: Sequence[Hit], settings: Settings, x_in: Callable[[float], float],
                   z_in: Callable[[float], float], k: float, frame_w: float, y0: float, y1: float, z_floor: float,
                   width_of: Callable[[str], float], marks: Sequence[Tuple[float, float, float, float]] = (),
                   crosses: Optional[Callable[[float, float, float, float], bool]] = None
                   ) -> Tuple[List[TdPlace], List[Hit]]:
    """Every TD label of `hits` on one page, as figure.py draws them (and the plan checks them, td_warnings), in
    paper inches: x from the frame's left (`x_in`: station ->), y up (`z_in`: elevation ->), the frame from `y0` to
    `y1`, its bottom at elevation `z_floor`; `width_of(text)` the label's length. Returns (the labels placed, the
    explorations of rows out of the range whose label found no spot: left out).

    (1) The in-range explorations under their bottom bars (stack_labels: clear of the other TD labels and every
    bar; where a row allows it, of the ticks, the exploration labels and the ground line), as always; (2) those of
    rows out of the range drawn whole, clear of the first ones too; (3) those that run below the frame, beside their
    arrow just above the frame bottom (always when the total depth is known: their only depth): right of the line
    (left near the frame's right edge), else on the other side, else a row up (two at most), clear of every bar and
    arrow and of every TD label placed (else the spot covering the least of them); (4) the explorations of (2) with
    no row inside the frame, beside their line at their bottom bar, else on the other side, else a row up or down,
    clear of the same: else left out. A label is never drawn outside the frame."""
    text_h, row_h, pad = TD_TEXT_H_IN * k, TD_ROW_IN * k, TD_PAD_IN * k
    bars = bar_boxes(hits, settings, x_in, z_in, k, z_floor=z_floor)
    eps = 1e-6
    deep = [h for h in hits if runs_below(h, z_floor, settings)]
    whole = [h for h in hits if draws_td_label(h, settings) and not runs_below(h, z_floor, settings)]
    under: List[TdPlace] = []
    taken: List[Tuple[float, float, float, float]] = []      # pass-1 boxes, padded as stack_labels pads them
    wanted: List[Tuple[Hit, str, float]] = []                # (2) with no row inside the frame
    for inside in (True, False):
        items = [h for h in whole if hit_in_range(h) == inside]
        if not items:
            continue
        texts = [td_text(h.total_depth) for h in items]
        widths = [width_of(t) for t in texts]
        xs = [clamp_centre(x_in(h.station), w, frame_w, TD_EDGE_IN * k) for h, w in zip(items, widths)]
        tops = [z_in(h.bottom) - TD_GAP_IN * k for h in items]
        rows = stack_labels(xs, tops, widths, text_h, row_h, pad, obstacles=bars + taken, soft=marks,
                            crosses=crosses)
        for h, text, x, w, top, row in zip(items, texts, xs, widths, tops, rows):
            y = None if row is None else top - row * row_h
            if y is not None and not (y - text_h < y0 - eps or y > y1 + eps):
                under.append(TdPlace(h, text, "under", "center", x, y, w, (x - w / 2, x + w / 2, y - text_h, y)))
                if inside:
                    taken.append((x - w / 2 - pad / 2, x + w / 2 + pad / 2, y - text_h, y))
            elif not inside:
                wanted.append((h, text, w))
            # in range with no row, or crossing the frame (manual range): the plan warns about it
    if not deep and not wanted:
        return under, []
    # (3) and (4): clear of every bar and arrow, and of every TD label placed so far
    arrows = {}
    for h in deep:
        x = x_in(h.station)
        arrows[id(h)] = (x - CLIP_ARROW_HALF_IN * k, x + CLIP_ARROW_HALF_IN * k, y0 + CLIP_ARROW_TIP_IN * k,
                         y0 + (CLIP_ARROW_TIP_IN + CLIP_ARROW_H_IN) * k)
    hard_bars = list(bars) + list(arrows.values())
    labels = [(t.box[0] - pad / 2, t.box[1] + pad / 2, t.box[2], t.box[3]) for t in under]

    def others(h: Hit) -> List[Tuple[float, float, float, float]]:
        """Every bar and arrow but those of `h` (its label stands CLIP_TD_DX_IN beside its own line, just clear)."""
        own = set(bar_boxes([h], settings, x_in, z_in, k, z_floor=z_floor))
        if id(h) in arrows:
            own.add(arrows[id(h)])
        return [b for b in hard_bars if b not in own]

    def sides(x: float, w: float) -> List[str]:
        first = td_beside(x, w, 0.0, "center", k, frame_w).ha
        return ["left", "right"] if first == "right" else ["right", "left"]

    clipped: List[TdPlace] = []
    for h in sorted(deep, key=lambda h: h.station):
        if not _finite(h.total_depth):
            continue
        text = td_text(h.total_depth)
        w, x = width_of(text), x_in(h.station)
        cands = [td_beside(x, w, y0 + (CLIP_TD_BASE_IN + row * TD_ROW_IN) * k, "baseline", k, frame_w, side)
                 for row in range(3) for side in sides(x, w)]
        spot = _beside_spot(cands, others(h), labels, pad, frame_w, y0, y1, must=True)
        clipped.append(TdPlace(h, text, "clip", spot.ha, spot.x, spot.y, w, spot.box))
        labels.append((spot.box[0] - pad / 2, spot.box[1] + pad / 2, spot.box[2], spot.box[3]))
    side: List[TdPlace] = []
    left_out: List[Hit] = []
    for h, text, w in wanted:
        x = x_in(h.station)
        y = max(z_in(h.bottom), y0 + 0.01 * k + text_h / 2.0)        # centred on its bar, 0.01 in above the frame
        cands = [td_beside(x, w, y + dy, "center", k, frame_w, sd) for dy in (0.0, row_h, -row_h) for sd in sides(x, w)]
        spot = _beside_spot(cands, others(h), labels, pad, frame_w, y0, y1, must=False)
        if spot is None:
            left_out.append(h)
            continue
        side.append(TdPlace(h, text, "side", spot.ha, spot.x, spot.y, w, spot.box))
        labels.append((spot.box[0] - pad / 2, spot.box[1] + pad / 2, spot.box[2], spot.box[3]))
    return under + side + clipped, left_out


def tick_base(hit: Hit, settings: Settings) -> float:
    """Elevation the tick sits above: the ground, raised to clear the top only when the
    top-to-bottom line is actually drawn (decision 1: without a line there is nothing to clear)."""
    return hit.tick_base(draws_depth_line(hit, settings))


# ----------------------------------------------------------------------------- other-point symbols
# Pure geometry of the Other points symbols (figure.py draws them from it, the panel paints its swatch with it).
# Sizes in points, then paper inches (/ 72); y up; the centre at (0, 0); s = size * k / 2 (pt). The ink of every
# symbol is a set of capsules (a segment thickened by a radius: a stroke with round ends), so its top and bottom
# at any x are exact (capsule_top / capsule_bottom) and it can rest on the drawn ground line (rest_on_line).
GROUND_LW = 1.1                            # the drawn ground line, pt (not scaled; figure.py draws it with this)
SYMBOL_EDGE_PT = 0.6                       # white edge of the filled shapes, pt (x k), round joins
ASTERISK_MIN_W_PT, ASTERISK_W = 1.0, 0.42  # asterisk stroke width: max(1 pt x k, 0.42 s) (bold)
OTHER_REST_GAP_PT = 0.1                    # on the ground line: the lowest ink this far above the line's top (x k)
LEGEND_SYMBOL_MAX_PT = 6.0                 # a legend swatch draws the symbol at most this size
OTHER_LABEL_GAP_IN = 0.02                  # label bottom above the symbol's top (x k)
OTHER_LABEL_GROUND_IN = 0.05               # ... and at least this far above the ground line at its station (x k)
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


def symbol_capsules(shape: str, size_pt: float, k: float = 1.0) -> List[Capsule]:
    """The ink of a symbol as capsules, paper inches from its centre. Asterisk: 4 strokes through the centre at 0,
    45, 90 and 135 degrees, each from -1.25 s to +1.25 s (8 prongs), radius half the stroke width. Circle: one disc
    of radius s + e/2 (the fill plus its white edge). The other filled shapes: their edges, radius e/2 (e = the
    white edge; with round joins the ink is exactly the polygon plus these)."""
    s = symbol_half_pt(size_pt, k) / 72.0
    if shape == "circle":
        return [Capsule(0.0, 0.0, 0.0, 0.0, s + symbol_edge_pt(k) / 2.0 / 72.0)]
    if shape not in ("square", "diamond", "star", "triangle"):          # the asterisk (and anything unknown)
        r = asterisk_width_pt(size_pt, k) / 2.0 / 72.0
        a, h = 1.25 * s, 1.25 * s * math.sqrt(0.5)          # exact at 0 and 90 degrees (a true vertical stroke)
        return [Capsule(-dx, -dy, dx, dy, r) for dx, dy in ((a, 0.0), (h, h), (0.0, a), (-h, h))]
    pts = symbol_outline(shape, size_pt, k)
    r = symbol_edge_pt(k) / 2.0 / 72.0
    return [Capsule(pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1], r)
            for i in range(len(pts))]


def symbol_extent(caps: Sequence[Capsule]) -> Tuple[float, float, float]:
    """(half width, depth below the centre, height above it) of the ink, paper inches."""
    if not caps:
        return 0.0, 0.0, 0.0
    half_w = max(max(abs(c.ax), abs(c.bx)) + c.r for c in caps)
    below = max(c.r - min(c.ay, c.by) for c in caps)
    above = max(max(c.ay, c.by) + c.r for c in caps)
    return half_w, below, above


def _capsule_edge(c: Capsule, x: float, sign: float) -> float:
    """Top (sign +1) or bottom (sign -1) of the capsule at x; nan where it has none."""
    best = math.nan
    for px, py in ((c.ax, c.ay), (c.bx, c.by)):              # the round ends
        d = x - px
        if abs(d) <= c.r:
            v = py + sign * math.sqrt(max(c.r * c.r - d * d, 0.0))
            best = v if math.isnan(best) or (v - best) * sign > 0 else best
    dx, dy = c.bx - c.ax, c.by - c.ay
    if abs(dx) > 1e-12 * (abs(dx) + abs(dy)):                 # the offset side of a non-vertical segment (a
        m = dy / dx                                           # vertical one: its round ends hold its top and bottom)
        root = math.sqrt(1.0 + m * m)
        nx = -m / root * sign * c.r                           # upward (or downward) normal, x part
        lo, hi = sorted((c.ax + nx, c.bx + nx))
        if lo - 1e-15 <= x <= hi + 1e-15:
            v = c.ay + m * (x - c.ax) + sign * c.r * root
            best = v if math.isnan(best) or (v - best) * sign > 0 else best
    return best


def capsule_top(c: Capsule, x: float) -> float:
    """Top of the capsule's ink at x (-inf where it has none)."""
    v = _capsule_edge(c, x, 1.0)
    return -math.inf if math.isnan(v) else v


def capsule_bottom(c: Capsule, x: float) -> float:
    """Bottom of the capsule's ink at x (+inf where it has none)."""
    v = _capsule_edge(c, x, -1.0)
    return math.inf if math.isnan(v) else v


def stroke_top(xs: Sequence[float], ys: Sequence[float], r: float, x: float) -> float:
    """Top edge at x of a polyline stroked `2 r` wide with round joins and caps (a nan vertex breaks it): the
    highest capsule_top over its segments with both ends finite; -inf where it has none."""
    top = -math.inf
    for i in range(len(xs) - 1):
        x0, y0, x1, y1 = xs[i], ys[i], xs[i + 1], ys[i + 1]
        if not (math.isfinite(x0) and math.isfinite(y0) and math.isfinite(x1) and math.isfinite(y1)):
            continue
        if x < min(x0, x1) - r or x > max(x0, x1) + r:
            continue
        top = max(top, capsule_top(Capsule(x0, y0, x1, y1, r), x))
    return top


def _stroke_top_near(xs: Sequence[float], ys: Sequence[float], r: float, x: float) -> float:
    """stroke_top for a polyline whose xs ascend (a ground line): only its segments within r of x are looked at
    (bisect), so the cost does not grow with the length of the line. The same result."""
    lo = max(bisect.bisect_left(xs, x - r) - 1, 0)
    hi = min(bisect.bisect_right(xs, x + r) + 1, len(xs))
    top = -math.inf
    for i in range(lo, hi - 1):
        x0, y0, x1, y1 = xs[i], ys[i], xs[i + 1], ys[i + 1]
        if not (math.isfinite(y0) and math.isfinite(y1)):
            continue
        if x < min(x0, x1) - r or x > max(x0, x1) + r:
            continue
        top = max(top, capsule_top(Capsule(x0, y0, x1, y1, r), x))
    return top


def _thin_line(xs: Sequence[float], ys: Sequence[float], step: float) -> Tuple[List[float], List[float]]:
    """A polyline with ascending xs thinned to one vertex per `step` of x: the highest of each bin (a nan vertex ends
    its bin and is kept, a break in the line). For the preview, where a symbol covers thousands of 1 ft samples."""
    out_x: List[float] = []
    out_y: List[float] = []
    best: Optional[Tuple[float, float]] = None
    edge = -math.inf
    for x, y in zip(xs, ys):
        if not math.isfinite(y):
            if best is not None:
                out_x.append(best[0])
                out_y.append(best[1])
                best = None
            out_x.append(x)
            out_y.append(math.nan)
            edge = -math.inf
            continue
        if best is not None and x >= edge:
            out_x.append(best[0])
            out_y.append(best[1])
            best = None
        if best is None:
            edge = x + step
            best = (x, y)
        elif y > best[1]:
            best = (x, y)
    if best is not None:
        out_x.append(best[0])
        out_y.append(best[1])
    return out_x, out_y


def rest_on_line(gx: Sequence[float], gy: Sequence[float], x_c: float, caps: Sequence[Capsule], r: float,
                 gap: float, thin: bool = False) -> Optional[float]:
    """The centre y (paper inches) that rests a symbol centred at x_c on a line drawn through (gx, gy), stroked
    2 r wide: its lowest ink `gap` above the top of the stroke, checked under each lowest point of the symbol
    (on a slope too). Samples: 241 across the ink, every capsule end and the ends' edges, and the line's vertices
    under the ink. None when there is no line under any sample (a DEM gap).

    A line whose xs ascend (the ground) is read near each sample only; `thin` (the preview, drawn small) first
    keeps one vertex per r / 8 of x where they are closer than that (the highest; within a hair of exact)."""
    if not caps:
        return None
    gx, gy = list(gx), list(gy)
    ascending = all(math.isfinite(a) and math.isfinite(b) and a <= b for a, b in zip(gx, gx[1:])) and \
        all(math.isfinite(a) for a in gx[:1])
    if thin and ascending and len(gx) > 2 and r > 0 and (gx[-1] - gx[0]) / (len(gx) - 1) < r / 8.0:
        gx, gy = _thin_line(gx, gy, r / 8.0)
    half_w, _, _ = symbol_extent(caps)
    dxs = {-half_w + 2.0 * half_w * i / 240.0 for i in range(241)}
    for c in caps:
        for px in (c.ax, c.bx):
            for d in (px - c.r, px, px + c.r, px - r, px + r):
                if -half_w <= d <= half_w:
                    dxs.add(d)
    for x in gx:
        if math.isfinite(x) and -half_w <= x - x_c <= half_w:
            dxs.add(x - x_c)
    top_at = (lambda x: _stroke_top_near(gx, gy, r, x)) if ascending else (lambda x: stroke_top(gx, gy, r, x))
    best = -math.inf
    for dx in dxs:
        t = top_at(x_c + dx)
        if t == -math.inf:
            continue
        low = min(capsule_bottom(c, dx) for c in caps)
        if low == math.inf:
            continue
        best = max(best, t - low)
    return None if best == -math.inf else best + gap


# ----------------------------------------------------------------------------- other points on the section
class PlacedPoint(NamedTuple):
    """An other point as a sheet or the preview drew it (figure._Painter.other_points)."""
    index: int                 # in model.other_points
    station: float
    z: float                   # the symbol centre, ft (data units of the axes)
    half_w: float              # ink extent, paper inches (k included)
    below: float
    above: float
    label_top: float           # top of its label, paper inches above the centre (0 without a label)


def other_symbol(model: SectionModel, p: Any) -> Tuple[str, float, str]:
    """(shape, size pt, colour) of an other point's row (model.other_layers[p.layer_index]); the default bold
    blue asterisk when the model has no such row."""
    infos = getattr(model, "other_layers", None) or []
    i = getattr(p, "layer_index", 0)
    if isinstance(i, int) and 0 <= i < len(infos):
        info = infos[i]
        return info.shape, float(info.size), info.color
    return "asterisk", 7.0, "#1f6fb2"


def other_centre_in(p: Any, caps: Sequence[Capsule], ground: GroundProfile, x_in: Callable[[float], float],
                    z_in: Callable[[float], float], kx: float, k: float = 1.0, thin: bool = False) -> float:
    """Paper y (the units of `z_in`) of an other point's symbol centre. At the LIDAR or a field (how "lidar" /
    "field"): its elevation. On the ground line (how "line"): resting on the drawn line (rest_on_line over the
    ground vertices under the symbol plus one each side, the line GROUND_LW wide, OTHER_REST_GAP_PT x k above it);
    with no ground under it (a DEM gap) its lowest ink that far above the nearest valid ground. `thin`: the preview
    (rest_on_line)."""
    if p.how != "line":
        return z_in(p.z)
    r = GROUND_LW / 2.0 / 72.0
    gap = OTHER_REST_GAP_PT * k / 72.0
    half_w, below, _ = symbol_extent(caps)
    reach = (half_w + 2.0 * r) / kx if kx > 0 else 0.0           # ft either side
    st = ground.stations
    i0 = max(bisect.bisect_left(st, p.station - reach) - 1, 0)
    i1 = min(bisect.bisect_right(st, p.station + reach) + 1, len(st))
    gx = [x_in(s) for s in st[i0:i1]]
    gy = [z_in(z) if _finite(z) else math.nan for z in ground.z[i0:i1]]
    y = rest_on_line(gx, gy, x_in(p.station), caps, r, gap, thin=thin)
    if y is None:
        g = ground.nearest_valid(p.station)
        if not _finite(g):
            g = p.ground_at_station if _finite(p.ground_at_station) else p.z
        y = z_in(g) + r + gap + below
    return y


def other_label_anchor(p: Any, y_c: float, above: float, z_in: Callable[[float], float], k: float = 1.0) -> float:
    """Lowest paper y of an other point's label bottom: OTHER_LABEL_GAP_IN above the symbol, and at least
    OTHER_LABEL_GROUND_IN above the ground line at its station (a symbol below the line has its label over it)."""
    base = y_c + above + OTHER_LABEL_GAP_IN * k
    g = getattr(p, "ground_at_station", math.nan)
    if _finite(g):
        base = max(base, z_in(g) + OTHER_LABEL_GROUND_IN * k)
    return base


def mark_obstacles(marks: Sequence[Tuple[float, float, float, float]],
                   vertical: bool) -> List[Tuple[float, float, float, float]]:
    """The exploration marks (mark_boxes: the ticks, then as many labels) as obstacles for the other points' labels:
    each label box RASTER_SLACK longer along its text (a PNG draws small type a little longer than the estimate),
    so that a point's label never touches an exploration's name."""
    n = len(marks) // 2
    out = list(marks[:n])
    for left, right, bottom, top in marks[n:]:
        if vertical:
            out.append((left, right, bottom, bottom + (top - bottom) * RASTER_SLACK))
        else:
            grow = (right - left) * (RASTER_SLACK - 1.0) / 2.0
            out.append((left - grow, right + grow, bottom, top))
    return out


def ground_top_fn(stations: Sequence[float], zs: Sequence[Optional[float]], x_in: Callable[[float], float],
                  z_in: Callable[[float], float], r: float = GROUND_LW / 2.0 / 72.0
                  ) -> Callable[[float, float], float]:
    """top(left, right): the highest point of the drawn ground line's stroke (2 r wide, round joins) over the paper
    x span [left, right], in the units of `x_in` (station ->) and `z_in` (elevation ->); -inf where there is no
    ground. Exact, at two evaluations a segment: the stroke is the union of its segments' capsules, and the top of a
    capsule is highest over its higher end (that end's y + r), falling away on either side; over the span it is
    therefore highest there, or else at the span's end nearer to it."""
    gx = [x_in(s) for s in stations]
    gy = [z_in(z) if _finite(z) else math.nan for z in zs]

    def top(left: float, right: float) -> float:
        i0 = max(bisect.bisect_left(gx, left - r) - 1, 0)
        i1 = min(bisect.bisect_right(gx, right + r) + 1, len(gx))
        best = -math.inf
        for i in range(i0, i1 - 1):
            x0, y0, x1, y1 = gx[i], gy[i], gx[i + 1], gy[i + 1]
            if not (math.isfinite(y0) and math.isfinite(y1)):
                continue
            if max(x0, x1) + r < left or min(x0, x1) - r > right:
                continue
            xh, yh = (x1, y1) if y1 > y0 else (x0, y0)
            if left <= xh <= right:
                best = max(best, yh + r)
            else:
                best = max(best, capsule_top(Capsule(x0, y0, x1, y1, r), left if xh < left else right))
        return best
    return top


def other_label_layout(xs: Sequence[float], anchors: Sequence[float], widths: Sequence[float], k: float,
                       frame_w: Optional[float], obstacles: Iterable[Tuple[float, float, float, float]] = (),
                       ground_top: Optional[Callable[[float, float], float]] = None) -> List[LabelSpot]:
    """Horizontal labels of the other points (paper inches, y up), in x order: each at the lowest base at or above
    its anchor that clears the labels placed and the `obstacles` (boxes: the exploration marks and TD labels, the
    points' symbols), LABEL_PAD_IN apart, rising to just above what it clashes with; centres kept inside
    [0, frame_w] when they fit. With `ground_top` (ground_top_fn), never lower than OTHER_LABEL_GROUND_IN x k above
    the ground line anywhere under it (as the anchor is at its own station: on a slope the ground under its
    uphill end is higher). `moved` (a leader) when raised off its anchor."""
    n = len(xs)
    line_h = LABEL_ROW_IN * k
    pad = LABEL_PAD_IN * k
    clear = OTHER_LABEL_GROUND_IN * k - GROUND_LW / 2.0 / 72.0        # above the stroke's top: the line's middle + 0.05
    cx = [float(x) for x in xs]
    if frame_w is not None:
        for i in range(n):
            if widths[i] < frame_w:
                cx[i] = min(max(cx[i], widths[i] / 2), frame_w - widths[i] / 2)
    fixed = list(obstacles)
    placed: List[Tuple[float, float, float, float]] = []
    bases = [0.0] * n
    for i in sorted(range(n), key=lambda j: (xs[j], j)):
        left, right = cx[i] - widths[i] / 2 - pad, cx[i] + widths[i] / 2 + pad
        b = anchors[i]
        if ground_top is not None:
            g = ground_top(left, right)
            if g > -math.inf:
                b = max(b, g + clear)
        while True:
            clash = [t for (pl, pr, pb, t) in placed + fixed if pl < right and left < pr and pb < b + line_h and b < t]
            if not clash:
                break
            b = max(clash) + 0.01 * k
        placed.append((left, right, b, b + line_h))
        bases[i] = b
    return [LabelSpot(cx[i], bases[i], bases[i] - anchors[i] > 1e-6,
                      (cx[i] - widths[i] / 2, cx[i] + widths[i] / 2, bases[i], bases[i] + line_h)) for i in range(n)]


def other_label_top(model: SectionModel, settings: Settings, plot_length: float) -> float:
    """Elevation (ft) the other points' labels reach, plus LABEL_MARGIN_IN; -inf without points. The labels laid
    out on the whole section as figure.py draws them at sheet scale (k = 1; centres resting on the ground line
    for the "line" points), clear of the exploration ticks and labels (marks_on_paper)."""
    pts = getattr(model, "other_points", None) or []
    if not pts:
        return -math.inf
    v, hs = float(settings.v_scale), float(settings.h_scale)
    frame_w = plot_length / hs

    def x_in(st: float) -> float:
        return st / hs

    def z_in(z: float) -> float:
        return z / v

    xs, anchors, widths = [], [], []
    symbols = []                                         # every point's ink: no label covers a neighbour's symbol
    for p in pts:
        shape, size, _ = other_symbol(model, p)
        caps = symbol_capsules(shape, size)
        half_w, below, above = symbol_extent(caps)
        y_c = other_centre_in(p, caps, model.ground, x_in, z_in, 1.0 / hs)
        if not _finite(y_c):
            continue
        x = x_in(p.station)
        symbols.append((x - half_w, x + half_w, y_c - below, y_c + above))
        if not display_label(p, settings):
            continue
        xs.append(x)
        anchors.append(other_label_anchor(p, y_c, above, z_in))
        widths.append(text_width_in(display_label(p, settings), LABEL_PT))
    if not xs:
        return -math.inf
    obstacles = mark_obstacles(marks_on_paper(model.hits, settings, frame_w), settings.label_vertical) + symbols
    spots = other_label_layout(xs, anchors, widths, 1.0, frame_w, obstacles,
                               ground_top_fn(model.ground.stations, model.ground.z, x_in, z_in))
    return (max(sp.box[3] for sp in spots) + LABEL_MARGIN_IN) * v


def sheet_label(key: str, landscape: bool) -> str:
    long_, short, name = SHEETS[key]
    w, h = (long_, short) if landscape else (short, long_)
    return f"{name} {fmt_num(w)} × {fmt_num(h)} in, {'landscape' if landscape else 'portrait'}"


def sheet_size(key: str, landscape: bool) -> Tuple[float, float]:
    long_, short, _ = SHEETS[key]
    return (float(long_), float(short)) if landscape else (float(short), float(long_))


def page_turns(settings: Settings) -> Tuple[bool, ...]:
    """The orientations plan() tries on each sheet, as `landscape` flags in order: Auto (settings.orientation
    "auto", or anything unknown) landscape first, then portrait, the search of every version before 0.3.5;
    Landscape or Portrait only that one (for one sheet and for tiling alike)."""
    o = clean_orientation(getattr(settings, "orientation", "auto"))
    return (True, False) if o == "auto" else (o == "landscape",)


# ----------------------------------------------------------------------------- limits
def _floor_to(v: float, step: float) -> float:
    return math.floor(v / step + _EPS) * step


def _ceil_to(v: float, step: float) -> float:
    return math.ceil(v / step - _EPS) * step


def _data_extent(model: SectionModel, settings: Settings) -> Tuple[float, float, float, str]:
    """(lo, hi, lowest_z, lowest_what) over the ground, tick bases and (when drawn) tops/bottoms, screens and water
    levels, the surfaces in the range and the other points placed at the LIDAR or a field (with their symbol).
    An exploration of a row out of the range adds only its tick base and top, to `hi` (decision 22: the frame is
    set by the ground, the surfaces and the in-range rows; deeper ones stop at it, runs_below)."""
    lo, hi = math.inf, -math.inf
    what = ""
    for s, z in zip(model.ground.stations, model.ground.z):
        if z is None or math.isnan(z):
            continue
        if z < lo:
            lo, what = z, f"the ground at {fmt_num(s, 0)} ft"
        hi = max(hi, z)
    for h in model.hits:
        inside = hit_in_range(h)
        base = tick_base(h, settings)
        if base is not None and not math.isnan(base):
            if inside and base < lo:
                lo, what = base, f"the ground at {h.label}"
            hi = max(hi, base)
        if settings.depth_line:
            if inside and h.bottom is not None and not math.isnan(h.bottom) and h.bottom < lo:
                lo, what = h.bottom, f"the bottom of {h.label}"
            if h.top is not None and not math.isnan(h.top):
                hi = max(hi, h.top)
        if settings.screens and inside:
            if _finite(h.screen_bottom) and h.screen_bottom < lo:
                lo, what = h.screen_bottom, f"the screen of {h.label}"
            if _finite(h.screen_top):
                hi = max(hi, h.screen_top)
            for w in h.water_levels:
                if w.elev < lo:
                    lo, what = w.elev, f"a water level of {h.label}"
                hi = max(hi, w.elev + WL_TRI_H_IN * settings.v_scale)
    for sp in getattr(model, "surfaces", None) or []:
        if not sp.in_range:
            continue
        vals = [(z, st) for st, z in zip(sp.stations, sp.z) if _finite(z)]
        if not vals:
            continue
        zlo, st_lo = min(vals)
        if zlo < lo:
            lo, what = zlo, f"{sp.name} at {fmt_num(st_lo, 0)} ft"
        hi = max(hi, max(z for z, _ in vals))
    v = float(settings.v_scale)
    for p in getattr(model, "other_points", None) or []:
        if p.how == "line" or not _finite(p.z):          # on the ground line: the ground and its headroom cover it
            continue
        shape, size, _ = other_symbol(model, p)
        _, below, above = symbol_extent(symbol_capsules(shape, size))
        if p.z - below * v < lo:
            lo, what = p.z - below * v, f"{p.label} ({p.layer_name})"
        hi = max(hi, p.z + above * v)
    if lo == math.inf:                      # no data at all: a nominal band
        return 0.0, 0.0, math.nan, ""
    return lo, hi, lo, what


def label_top(hits: Iterable[Hit], settings: Settings) -> float:
    """Elevation (ft) the exploration labels reach, plus LABEL_MARGIN_IN; -inf when there are none.

    Follows figure.py's placement closely enough to size the grid: a vertical label stands on its
    tick (a spread cluster on its highest tick plus the leader rise); horizontal labels stack in
    rows, in station order, wherever they would overlap.
    """
    v, hs = float(settings.v_scale), float(settings.h_scale)
    items = []                                   # (x, tick top, label length), paper inches
    for h in hits:
        base = tick_base(h, settings)
        if _finite(base):
            items.append((h.station / hs, base / v + TICK_TO_IN, text_width_in(display_label(h, settings), LABEL_PT)))
    if not items:
        return -math.inf
    items.sort(key=lambda t: t[0])
    top = -math.inf
    if settings.label_vertical:
        sep = LABEL_SEP * LABEL_PT / 72.0
        group: List[Tuple[float, float, float]] = []
        for it in items + [(math.inf, 0.0, 0.0)]:
            if group and it[0] - group[-1][0] >= sep:
                rise = LEADER_RISE_IN if len(group) > 1 else LABEL_GAP_IN
                top = max(top, max(g[1] for g in group) + rise + max(g[2] for g in group))
                group = []
            group.append(it)
    else:
        placed: List[Tuple[float, float, float, float]] = []
        for x, t, w in items:
            left, right = x - w / 2 - LABEL_PAD_IN, x + w / 2 + LABEL_PAD_IN
            b = t + LABEL_GAP_IN
            while True:
                clash = [pt for (pl, pr, pb, pt) in placed
                         if pl < right and left < pr and pb < b + LABEL_ROW_IN and b < pt]
                if not clash:
                    break
                b = max(clash) + 0.01
            placed.append((left, right, b, b + LABEL_ROW_IN))
            top = max(top, b + LABEL_ROW_IN)
    return (top + LABEL_MARGIN_IN) * v


def z_limits(model: SectionModel, settings: Settings, v_major: float,
             plot_length: Optional[float] = None) -> Tuple[float, float, float, str]:
    """(z_min, z_max, lowest_z, lowest_what) before any fill (fill_grid)."""
    lo, hi, lowest, what = _data_extent(model, settings)
    v = settings.v_scale
    if settings.z_mode == "manual":
        z0, z1 = _floor_to(min(settings.z_min, settings.z_max), v_major), _ceil_to(max(settings.z_min, settings.z_max), v_major)
    else:
        # the TD labels hang below the bottoms: below_in of grid is kept under the lowest of them too (those of
        # the in-range rows; every bar and mark is in their way)
        length = plot_length or model.length
        reach = [r for _, r in td_labels(model.hits, settings, length, model.ground,
                                         label_hits=[h for h in model.hits if hit_in_range(h)]) if r is not None]
        lo = min([lo] + reach)
        z0 = _floor_to(lo - settings.below_in * v, v_major)
        # at least LABEL_HEADROOM_IN above the data; more when long or stacked labels need it (every row's
        # exploration labels, and the other points' labels)
        z1 = _ceil_to(max(hi + LABEL_HEADROOM_IN * v, label_top(model.hits, settings),
                          other_label_top(model, settings, length)), v_major)
    if z1 <= z0 + _EPS:
        z1 = z0 + v_major
    return z0, z1, lowest, what


def _names(labels: Sequence[str], most: int = 4) -> str:
    shown = ", ".join(labels[:most])
    return shown + (f" and {len(labels) - most} more" if len(labels) > most else "")


def td_warnings(model: SectionModel, settings: Settings, z0: float, plot_length: float,
                v_major: float, z1: Optional[float] = None) -> List[str]:
    """TD labels the sheet leaves out: no free row in a tight stack, or (manual range) no room above
    the minimum elevation. figure.py never draws one outside the plot frame."""
    z_range = (z0, z1) if z1 is not None and settings.z_mode == "manual" else None
    labels = td_labels(model.hits, settings, plot_length, model.ground, z_range,
                       label_hits=[h for h in model.hits if hit_in_range(h)])
    out = []
    crowded = [h.label for h, reach in labels if reach is None]
    if z1 is not None and any(not hit_in_range(h) for h in model.hits):
        # the labels of the rows out of the range, laid out on the whole section as the sheet does (td_page_layout):
        # one with no spot beside its line is left out too
        v, hs = float(settings.v_scale), float(settings.h_scale)
        frame_w = plot_length / hs
        _placed, left_out = td_page_layout(
            model.hits, settings, lambda st: st / hs, lambda z: z / v, 1.0, frame_w, z0 / v, z1 / v, z0,
            lambda t: text_width_in(t, TD_PT), marks_on_paper(model.hits, settings, frame_w, z_range),
            ground_test(model.ground, lambda x: x * hs, lambda z: z / v))
        crowded += [h.label for h in left_out if h.label not in crowded]
    if crowded:
        out.append(f"No room for the TD label of {_names(crowded)} ({TD_MAX_ROWS} rows of TD labels overlap there).")
    if settings.z_mode == "manual":
        tol = 1e-6 * max(1.0, abs(z0))
        cut = [(h, reach) for h, reach in labels if reach is not None and h.bottom >= z0 - tol and reach < z0 - tol]
        if cut:
            need = _floor_to(min(r for _, r in cut), v_major)
            out.append(f"TD labels below the manual minimum of {fmt_num(z0)} ft are left out "
                       f"({_names([h.label for h, _ in cut])}). Lower it to {fmt_num(need)} ft or set Elevations to Auto.")
    return out


def manual_range_warnings(model: SectionModel, settings: Settings, z0: float, z1: float,
                          v_major: float, plot_length: Optional[float] = None) -> List[str]:
    """What a manual elevation range cuts off (the sheet clips it), as messages for the panel. An exploration whose
    tick base, or an other point whose symbol centre, the range cuts off is not drawn at all (its label would stand
    outside the frame): those are named."""
    v = settings.v_scale
    tol = 1e-6 * max(1.0, abs(z1 - z0))
    rng = f"{fmt_num(z0)} to {fmt_num(z1)} ft"
    fix = "Widen the range or set Elevations to Auto."
    ground = [z for z in model.ground.z if _finite(z)]
    if ground and (min(ground) > z1 + tol or max(ground) < z0 - tol):
        return [f"The ground ({min(ground):,.0f} to {max(ground):,.0f} ft) is outside the manual elevation "
                f"range {rng}. {fix}"]
    if not ground and not model.hits:
        return []
    lo, hi, _, _ = _data_extent(model, settings)
    bases = [(h, tick_base(h, settings)) for h in model.hits]
    inside = [h for h, b in bases if _finite(b) and z0 - tol <= b <= z1 + tol]
    hidden = [h.label for h, b in bases if _finite(b) and not z0 - tol <= b <= z1 + tol]
    # the other points as the sheet places them (figure._points_layout: centred on their elevation, or resting on
    # the ground line): one whose centre the range cuts off is left out with its label
    pts = list(getattr(model, "other_points", None) or [])
    pts_in = []
    if pts:
        hs = float(settings.h_scale)
        for p in pts:
            shape, size, _ = other_symbol(model, p)
            zc = other_centre_in(p, symbol_capsules(shape, size), model.ground, lambda st: st / hs, lambda z: z / v,
                                 1.0 / hs) * v
            if not _finite(zc):
                continue
            if z0 - tol <= zc <= z1 + tol:
                pts_in.append(p)
            else:
                hidden.append(p.label)
    cut = []
    if hi > z1 + tol:
        cut.append(f"up to {hi:,.0f} ft")
    if lo < z0 - tol:
        cut.append(f"down to {lo:,.0f} ft")
    if cut:
        msg = f"The manual elevation range {rng} cuts off data {' and '.join(cut)}"
        if hidden:
            msg += f" (not drawn: {_names(hidden)})"
        return [f"{msg}. {fix}"]
    if hidden:                          # (only points can be: a ground-line symbol resting just above the maximum)
        return [f"The manual elevation range {rng} leaves out {_names(hidden)} (not drawn). {fix}"]
    need = label_top(inside, settings)
    pts_need = (other_label_top(dataclasses.replace(model, hits=inside, other_points=pts_in), settings,
                                plot_length or model.length) if pts_in else -math.inf)
    if max(need, pts_need) > z1 + (LABEL_MARGIN_IN + 0.1) * v:   # labels would cross the frame by more than 0.1 in
        what = "Exploration labels" if need > z1 + (LABEL_MARGIN_IN + 0.1) * v else "Labels of the other points"
        return [f"{what} run above the plot with the manual maximum of {fmt_num(z1)} ft. Raise it "
                f"to {fmt_num(_ceil_to(max(need, pts_need), v_major))} ft or set Elevations to Auto."]
    return []


# ----------------------------------------------------------------------------- sheet layout options
def edge_in(settings: Settings) -> float:
    """The printer edge: the clear strip kept at the paper edge, inches (settings.edge_margin_in; the panel
    offers 0.5 and 0.3; anything else is kept within 0.25 to 1 in)."""
    try:
        e = float(getattr(settings, "edge_margin_in", SAFE_EDGE))
    except (TypeError, ValueError):
        return SAFE_EDGE
    return min(max(e, 0.25), 1.0) if math.isfinite(e) else SAFE_EDGE


def fill_mode(settings: Settings) -> str:
    """settings.fill_grid as one of FILL_CHOICES ("off" for anything else)."""
    f = str(getattr(settings, "fill_grid", "off") or "off").lower()
    return f if f in FILL_CHOICES else "off"


def effective_grid(settings: Settings) -> Tuple[float, float, float, float]:
    """(h_major, h_minor, v_major, v_minor), ft: settings.effective_grid() with blank intervals falling back
    to 1 in (major) and a tenth of the major (minor)."""
    H_s, V_s = float(settings.h_scale or 0), float(settings.v_scale or 0)
    h_major, h_minor, v_major, v_minor = (float(v or 0) for v in settings.effective_grid())
    h_major = h_major if h_major > 0 else H_s
    v_major = v_major if v_major > 0 else V_s
    h_minor = h_minor if 0 < h_minor <= h_major else h_major / 10.0
    v_minor = v_minor if 0 < v_minor <= v_major else v_major / 10.0
    return h_major, h_minor, v_major, v_minor


def _up(v: float) -> float:
    """Up to the next 0.01 in."""
    return math.ceil(v * 100.0 - 1e-6) / 100.0


def fit_text(text: str, size_pt: float, width_in: float) -> str:
    """`text`, cut short with "…" when it is wider than `width_in` (text_width_in estimate)."""
    if text_width_in(text, size_pt) <= width_in:
        return text
    while text and text_width_in(text.rstrip() + "…", size_pt) > width_in:
        text = text[:-1]
    return text.rstrip() + "…"


def elevation_label_width_in(z_range: Optional[Tuple[float, float]], step: float) -> float:
    """Widest elevation label on the sheet (the multiples of `step` in `z_range`, as fmt_num writes them),
    inches; with no range, a five-digit label ("00,000")."""
    if z_range is None or not step > 0:
        return text_width_in("00,000", LABEL_PT)
    k0, k1 = math.ceil(min(z_range) / step - 1e-9), math.floor(max(z_range) / step + 1e-9)
    ks = range(k0, k1 + 1) if k1 - k0 <= 2000 else list(range(k0, k0 + 50)) + list(range(k1 - 49, k1 + 1))
    return max([text_width_in(fmt_num(k * step), LABEL_PT) for k in ks] or [0.0])


def xaxis_depth_in() -> float:
    """Frame bottom to the bottom of the distance title (ticks, their labels, the title), inches."""
    return (AXIS_TICK_PT + AXIS_PAD_PT + LABEL_PT + XTITLE_PAD_PT + AXIS_TITLE_PT) / 72.0


def compact_rows_in() -> Tuple[float, float, float]:
    """Compact layout, inches above the frame top: (baseline of the end-letter row, baseline of the title
    row, top of the title row). BEND labels (5.5 pt, 2 pt above the frame) fit inside the end-letter row."""
    end_base = END_ROW_GAP_IN + TEXT_DESCENT_EM * END_PT / 72.0
    title_bottom = END_ROW_GAP_IN + END_PT / 72.0 + TITLE_ROW_GAP_IN
    title_base = title_bottom + TEXT_DESCENT_EM * TITLE_PT_COMPACT / 72.0
    return end_base, title_base, title_bottom + TITLE_PT_COMPACT / 72.0


def hbar_extent_in(settings: Settings) -> Tuple[float, float]:
    """(overhang left of its start, right end) of the horizontal graphic scale with its labels, inches from
    its start: numbers centred on 0, 1 and 2 in, "ft" after the last; in the compact layout "HORIZONTAL"
    stands right of the bar (in the standard layout it is under the bar, within that width)."""
    w_last = text_width_in(fmt_num(2 * settings.h_scale), SCALE_LABEL_PT)
    right = HBAR_LEN_IN + w_last / 2.0 + 0.03 + text_width_in("ft", SCALE_LABEL_PT)
    if settings.compact_layout:
        right = max(right, HBAR_LEN_IN + HBAR_NAME_DY_IN + text_width_in("HORIZONTAL", SCALE_NAME_PT))
    return text_width_in("0", SCALE_LABEL_PT) / 2.0, right


class LegendEntry(NamedTuple):
    """One entry of the sheet's legend."""
    text: str
    kind: str                  # layer | style | surface | screen | measured | atd | point
    key: Any = None            # the index of the exploration row in model.point_layers (layer, style), of the surface
    #                            in model.surfaces, of the other-points row in model.other_layers (point)
    color: str = ""            # layer: a single-symbol Color row's swatch colour ("" for Black and Gray rows);
    #                            style: the colour of that item of the row's layer style


def layer_entries(model: SectionModel, settings: Settings) -> List[LegendEntry]:
    """The exploration rows in the legend, in row order (only hits and settings: the plan and every sheet agree).
    A Color row whose explorations are drawn in colour (with a symbol and a depth line on the sheet) is always
    listed: one entry per colour of its style that is drawn, named as the layer's legend names it, in the legend's
    order (an identical label and colour once across all the Color rows, where it first comes, as two rows of the
    same style share their categories; the same label in two colours twice), or, for a single symbol, the row's
    name with that symbol's colour. Black and Gray rows are listed by name only when the rows drawn on the section
    (those with a plotted exploration) are drawn differently: each Color row with coloured lines counts as its own
    kind, and one whose lines all come out black counts as Black. An exploration with no symbol is never listed."""
    infos = getattr(model, "point_layers", None) or []
    drawn_rows = {h.layer_index for h in model.hits}
    drawn = [(i, info) for i, info in enumerate(infos) if info.on and i in drawn_rows]

    def colored(i: int) -> List[Hit]:      # its hits drawn in a colour: Color, with a symbol, with a depth line
        return [h for h in model.hits if h.layer_index == i and getattr(h, "look", "black") == "color"
                and getattr(h, "color", "") and draws_depth_line(h, settings)]

    hits_of = {i: colored(i) for i, info in drawn if getattr(info, "look", "black") == "color"}
    kinds = {("color", i) if hits_of.get(i) else ("gray" if getattr(info, "look", "black") == "gray" else "black")
             for i, info in drawn}
    differ = len(kinds) > 1
    out: List[LegendEntry] = []
    seen: set = set()          # the (label, colour) style entries listed so far, across every Color row
    for i, info in drawn:
        hs = hits_of.get(i) or []
        if hs:
            st = getattr(info, "style", None)
            items = st.items if st is not None else []
            ranks = sorted({h.style_rank for h in hs if 0 <= getattr(h, "style_rank", -1) < len(items)})
            if st is None or st.kind == "single" or not ranks:
                out.append(LegendEntry(info.name, "layer", i, items[0].color if items else hs[0].color))
            else:
                for r in ranks:                                  # the layer legend's order
                    it = items[r]
                    if (it.label, it.color) not in seen:
                        seen.add((it.label, it.color))
                        out.append(LegendEntry(it.label, "style", i, it.color))
        elif differ:
            out.append(LegendEntry(info.name, "layer", i))
    return out


def legend_entries(model: SectionModel, settings: Settings, z_min: Optional[float] = None,
                   z_max: Optional[float] = None) -> List[LegendEntry]:
    """What the legend beside (compact) or under (standard) the scale bar lists: the exploration rows and the colours
    of Color rows (layer_entries), the other surfaces, the screen and water level symbols that are on the sheet, then
    the other-points rows with a point on the section. With the drawn frame (`z_min`, `z_max`: the sheet), a row out
    of the elevation range counts only the levels and screens inside it (frame_levels, frame_screen); without (the
    plan, before the frame is known): every one, never fewer entries."""
    out = layer_entries(model, settings)
    for i, sp in enumerate(getattr(model, "surfaces", None) or []):
        out.append(LegendEntry(sp.name, "surface", i))
    if settings.screens:
        hits = model.hits
        if any(frame_screen(h, z_min) for h in hits):
            out.append(LegendEntry("Screen", "screen"))
        levels = [w for h in hits for w in frame_levels(h, z_min, z_max)]
        if any(w.kind == "measured" for w in levels):
            out.append(LegendEntry("Water level", "measured"))
        if any(w.kind == "atd" for w in levels):
            out.append(LegendEntry("Water at time of drilling (ATD)", "atd"))
    with_points = {p.layer_index for p in getattr(model, "other_points", None) or []}
    for j, info in enumerate(getattr(model, "other_layers", None) or []):
        if j in with_points:
            out.append(LegendEntry(info.name, "point", j))
    return out


def _entry_text(e: Union[str, LegendEntry]) -> str:
    return e if isinstance(e, str) else e.text


def legend_rows(types: Sequence[Union[str, LegendEntry]], width_in: float,
                size_pt: float) -> List[List[Tuple[str, float, Any]]]:
    """The legend in rows `width_in` wide: (text, x of its swatch from the row start, entry) of each entry, the
    first row starting with the label itself, "Legend:" (entry "", no swatch). An entry is a LegendEntry, or a plain
    string (tests: sized like an entry with a swatch). Later rows are indented 0.1 in; a name too long for a row is
    cut short with "…"."""
    if not types:
        return []
    label = "Legend:"
    rows: List[List[Tuple[str, float, Any]]] = [[(label, 0.0, "")]]
    x = text_width_in(label, size_pt) * RASTER_SLACK + 0.1
    room = max(width_in - 0.1 - SWATCH_IN - SWATCH_GAP_IN - 0.02, 0.3) / RASTER_SLACK
    for t in types:
        name = fit_text(_entry_text(t), size_pt, room)
        w = SWATCH_IN + SWATCH_GAP_IN + text_width_in(name, size_pt) * RASTER_SLACK
        if x + w > width_in and x > 0.1 + 1e-9:
            rows.append([])
            x = 0.1
        rows[-1].append((name, x, t))
        x += w + ENTRY_GAP_IN
    return rows


def column_min_w(settings: Settings, types: Sequence[str] = ()) -> float:
    """Least width kept beside the horizontal scale bar (compact notes, or a legend without notes); 0 when
    nothing goes there (the standard layout with notes puts them under the bar)."""
    compact, notes = bool(settings.compact_layout), bool(settings.show_notes)
    if compact and notes:
        return COMPACT_NOTES_MIN_W
    if (compact or not notes) and types:
        return LEGEND_MIN_W
    return 0.0


def notes_min_w(settings: Settings, types: Sequence[str] = ()) -> float:
    """Width the block under the plot needs: scale bar + notes (standard), scale bar + notes side by side
    (compact), or just the scale bar (no notes; and the legend beside it, when there is one)."""
    if settings.show_notes and not settings.compact_layout:
        return NOTES_MIN_W
    left, right = hbar_extent_in(settings)
    col = column_min_w(settings, types)
    return left + right + (COL_GAP_IN + col if col else 0.0)


def min_page_w(settings: Settings, types: Sequence[str] = ()) -> float:
    return notes_min_w(settings, types) + 2.0 * edge_in(settings) + 0.2


class Band(NamedTuple):
    """The block under the plot, in inches below the frame bottom (positive down)."""
    bar: float                 # bottom of the horizontal bar
    top: float                 # top of its number labels and of the rows beside it
    size: float                # text size of the rows beside the bar, pt
    pitch: float               # their pitch
    note_rows: int             # compact note lines beside the bar
    legend: List[List[Tuple[str, float]]]   # legend rows beside the bar (at the least column width)
    depth: float               # lowest mark of the block


def bottom_band(settings: Settings, types: Sequence[str] = ()) -> Band:
    """Where the horizontal scale, and whatever stands beside it, go. Standard layout: the bar
    HBAR_DEPTH_IN under the frame, "HORIZONTAL" under it (the notes, when shown, follow under the bar and
    are not part of this block). Compact: one band just under the distance title, the bar on the left,
    two short note lines beside it."""
    compact, notes = bool(settings.compact_layout), bool(settings.show_notes)
    if compact:
        top = xaxis_depth_in() + BAND_GAP_IN
        bar = top + SCALE_LABEL_PT / 72.0 + HBAR_LABEL_DY_IN
        low = bar + max(0.0, SCALE_NAME_PT / 72.0 / 2.0 - HBAR_H_IN / 2.0)   # "HORIZONTAL" centred on the bar
        size = NOTE_COMPACT_PT
    else:
        bar = HBAR_DEPTH_IN
        top = bar - HBAR_LABEL_DY_IN - SCALE_LABEL_PT / 72.0
        low = bar + HBAR_NAME_DY_IN + SCALE_NAME_PT / 72.0
        size = NOTE_PT
    pitch = size * NOTE_SPACING / 72.0
    note_rows = 2 if compact and notes else 0
    legend = legend_rows(types, column_min_w(settings, types), size) if (compact or not notes) else []
    rows = note_rows + len(legend)
    depth = max(low, top + (rows - 1) * pitch + size / 72.0) if rows else low
    return Band(bar, top, size, pitch, note_rows, legend, depth)


NOTES_TOP_IN = 0.86                        # standard layout: frame bottom to the top of the first note line
NOTE_PITCH_IN = NOTE_PT * NOTE_SPACING / 72.0     # baseline to baseline inside a note
NOTE_GAP_IN = 0.035                               # extra space between notes


def wrap_count(text: str, size_pt: float, width_in: float) -> int:
    """Lines a greedy word wrap of `text` takes at `width_in` (as figure.wrap_text: only ordinary spaces break), on
    the estimated widths x RASTER_SLACK (a PNG draws small type a little wider than its outlines)."""
    n, cur = 0, ""
    for word in text.split(" "):
        cand = word if not cur else cur + " " + word
        if not cur or text_width_in(cand, size_pt) * RASTER_SLACK <= width_in:
            cur = cand
        else:
            n += 1
            cur = word
    return n + (1 if cur else 0)


def standard_block_depth(note_texts: Sequence[str], entries: Sequence[LegendEntry], width_in: float) -> float:
    """Frame bottom to the lowest mark of the standard layout's block under the plot (the scale bar, the notes
    wrapped at `width_in`, then the legend), inches, as figure._bottom_block_standard draws it: each note from
    NOTES_TOP_IN down at NOTE_PITCH_IN a line and NOTE_GAP_IN between notes, then the legend rows (wrapped the way
    it wraps them) centred NOTE_PITCH_IN apart."""
    depth = HBAR_DEPTH_IN + HBAR_NAME_DY_IN + SCALE_NAME_PT / 72.0          # the bar and "HORIZONTAL" under it
    y = NOTES_TOP_IN
    for text in note_texts:
        n = wrap_count(text, NOTE_PT, width_in)
        if n:
            depth = max(depth, y + (n - 1) * NOTE_PITCH_IN + NOTE_PT / 72.0)
        y += n * NOTE_PITCH_IN + NOTE_GAP_IN
    if entries:
        label = "Legend:"
        x, rows = text_width_in(label, NOTE_PT) * RASTER_SLACK + 0.1, 1
        for e in entries:
            w = SWATCH_IN + SWATCH_GAP_IN + text_width_in(_entry_text(e), NOTE_PT) * RASTER_SLACK + 0.15
            if x + w > width_in:
                x, rows = 0.1, rows + 1
            x += w
        half = NOTE_PT / 144.0
        if any(_entry_kind(e) == "point" for e in entries):          # a symbol swatch (at most 6 pt) reaches lower
            half = max(half, symbol_extent(symbol_capsules("asterisk", LEGEND_SYMBOL_MAX_PT))[1])
        depth = max(depth, y + NOTE_PITCH_IN / 2.0 + (rows - 1) * NOTE_PITCH_IN + half)
    return depth


def _entry_kind(e: Union[str, LegendEntry]) -> str:
    return "text" if isinstance(e, str) else e.kind    # a plain string (tests) sizes like an entry with a swatch


def _standard_block_in(model: SectionModel, settings: Settings, provisional: Plan, sheet_name: str,
                       entries: Sequence[LegendEntry], width_in: float) -> float:
    """standard_block_depth of the notes as they will read (notes.note_texts) before the sheet and the frame are
    known: `provisional` holds the grid and the elevation range before any fill (fill only lowers the frame, so the
    arrow sentence is never missing), every screen and water level is named, and `sheet_name` is the longest
    the sheet may get. Never shallower than the block drawn."""
    from .notes import note_texts                  # (notes.py imports this module)
    page = PageLayout(page_w=0.0, page_h=0.0, sheet_name=sheet_name, plot_left=0.0, plot_bottom=0.0,
                      plot_w=width_in, plot_h=0.0, x_min=0.0, x_max=0.0)
    return standard_block_depth(note_texts(model, settings, provisional, page, frame=False), entries, width_in)


def vbar_dx_in(settings: Settings, label_w: float) -> float:
    """Frame right to the vertical graphic scale: standard VBAR_STD_DX_IN; compact just clear of the right
    elevation labels (`label_w` wide)."""
    if not settings.compact_layout:
        return VBAR_STD_DX_IN
    return (AXIS_TICK_PT + AXIS_PAD_PT) / 72.0 + label_w + VBAR_GAP_IN


def margins(settings: Settings, z_range: Optional[Tuple[float, float]] = None,
            types: Sequence[str] = (), block_in: float = 0.0) -> dict:
    """Inches from each paper edge to the plot frame: dict(left, right, top, bottom).

    Standard layout with notes: MARGIN, moved by the printer edge (edge 0.5 in = MARGIN; 0.3 in = 0.2 in
    less on every side); its bottom grows when the block under the plot (`block_in`: the notes and the legend,
    standard_block_depth) needs more, so that it never runs into the printer edge. The compact layout, and the
    bottom without notes, are added up from what is drawn there (the metrics above) plus LAYOUT_PAD_IN, then
    rounded up to 0.01 in. `z_range` (the elevations the sheet may label, fill included) sizes the elevation
    labels, else a five-digit label is assumed; `types` is the legend (legend_entries).

    Standard layout, right side: MARGIN holds the vertical scale's top label up to "100 ft" (it then ends
    exactly at the printer edge); a wider one ("1,000 ft") gets the room it needs, the same way."""
    edge = edge_in(settings)
    out = {k: v + edge - SAFE_EDGE for k, v in MARGIN.items()}
    compact, notes = bool(settings.compact_layout), bool(settings.show_notes)
    if not compact:
        w = text_width_in(f"{fmt_num(settings.v_scale)} ft", SCALE_LABEL_PT)
        if VBAR_STD_DX_IN + VBAR_LABEL_DX_IN + w > out["right"] - edge + 1e-6:
            out["right"] = _up(VBAR_STD_DX_IN + VBAR_LABEL_DX_IN + w * RASTER_SLACK + LAYOUT_PAD_IN + edge)
    if compact or not notes:
        out["bottom"] = _up(bottom_band(settings, types).depth + LAYOUT_PAD_IN + edge)
    elif block_in > 0.0:
        out["bottom"] = max(out["bottom"], _up(block_in + LAYOUT_PAD_IN + edge))
    if compact:
        wl = elevation_label_width_in(z_range, effective_grid(settings)[2])
        left = (AXIS_TICK_PT + AXIS_PAD_PT + YTITLE_GAP_PT + AXIS_TITLE_PT + RENDER_SLACK_PT) / 72.0 + wl
        vlab = max(text_width_in("0", SCALE_LABEL_PT), text_width_in(f"{fmt_num(settings.v_scale)} ft", SCALE_LABEL_PT),
                   (SCALE_NAME_PT + RENDER_SLACK_PT) / 72.0)
        right = vbar_dx_in(settings, wl) + VBAR_LABEL_DX_IN + vlab
        out["left"] = _up(left + LAYOUT_PAD_IN + edge)
        out["right"] = _up(right + LAYOUT_PAD_IN + edge)
        out["top"] = _up(compact_rows_in()[2] + LAYOUT_PAD_IN + edge)
    return out


# ----------------------------------------------------------------------------- pages
def _need(plot_w: float, plot_h: float, mg: dict, min_w: float) -> Tuple[float, float]:
    return (max(plot_w + mg["left"] + mg["right"], min_w), plot_h + mg["top"] + mg["bottom"])


def _fits(need: Tuple[float, float], size: Tuple[float, float]) -> bool:
    return need[0] <= size[0] + _EPS and need[1] <= size[1] + _EPS


def _snap(v: float) -> float:
    return round(v * 100.0) / 100.0


def _place(W: float, H: float, plot_w: float, plot_h: float, mg: dict) -> Tuple[float, float]:
    """Plot origin on the page: centred horizontally within the margins, block centred vertically."""
    lo = mg["left"]
    hi = max(W - mg["right"] - plot_w, lo)
    left = _snap(min(max((W - plot_w) / 2.0, lo), hi))
    if left > hi + _EPS:                    # snapping must not eat into the right margin
        left = math.floor(hi * 100 + 1e-6) / 100
    left = max(left, lo)
    need_h = plot_h + mg["top"] + mg["bottom"]
    bottom = _snap(mg["bottom"] + max(H - need_h, 0.0) / 2.0)
    return left, bottom


def _order_by_size(keys: Sequence[str]) -> List[str]:
    known = [k for k in dict.fromkeys(k.lower() for k in keys) if k in SHEETS]
    return sorted(known, key=lambda k: SHEETS[k][0] * SHEETS[k][1])


def fill_majors(plot_h: float, H: float, settings: Settings, v_major: float, mg: dict) -> int:
    """Whole major intervals of grid that fit in the sheet height left over by a plot `plot_h` tall."""
    major_in = v_major / settings.v_scale
    room = H - mg["top"] - mg["bottom"] - plot_h
    return max(math.floor(room / major_in + 1e-9), 0) if major_in > 0 else 0


def _fill(z0: float, z1: float, plot_h: float, H: float, settings: Settings, v_major: float,
          mg: dict) -> Tuple[float, float]:
    """(z_min, z_max) extended by whole majors to use the sheet height: all below ("below"), or split with
    the larger half below, where the geology goes ("both")."""
    mode = fill_mode(settings)
    if mode == "off":
        return z0, z1
    n = fill_majors(plot_h, H, settings, v_major, mg)
    above = n // 2 if mode == "both" else 0
    return z0 - (n - above) * v_major, z1 + above * v_major


def _tiles(length: float, usable_ft: float, major: float) -> Optional[List[Tuple[float, float, Optional[float], Optional[float]]]]:
    """Split [0, length] into windows (x_min, x_max, match_left, match_right).

    Cores are whole majors; each window adds one major of overlap on each inner side. The
    first and last windows have no outer overlap, so their cores may be one major longer.
    """
    if length <= usable_ft + _EPS:
        return [(0.0, length, None, None)]
    ov = major
    end_core = math.floor((usable_ft - ov) / major + 1e-9) * major        # overlap on one side only
    mid_core = math.floor((usable_ft - 2 * ov) / major + 1e-9) * major    # overlap on both sides
    if mid_core < major:
        return None
    bounds = [0.0, end_core]
    while length - bounds[-1] > end_core + _EPS:
        bounds.append(bounds[-1] + mid_core)
    bounds.append(length)
    tiles = []
    for a, b in zip(bounds, bounds[1:]):
        tiles.append((max(0.0, a - ov), min(length, b + ov),
                      a if a > _EPS else None, b if b < length - _EPS else None))
    return tiles


def plan(model: SectionModel, settings: Settings) -> Plan:
    """Limits, grid and pages for `model` at the scales in `settings` (see DESIGN.md)."""
    H_s, V_s = float(settings.h_scale or 0), float(settings.v_scale or 0)
    if not (H_s > 0 and V_s > 0 and math.isfinite(H_s) and math.isfinite(V_s)):
        raise SectionError("The horizontal and vertical scales must be positive (ft per inch).")
    h_major, h_minor, v_major, v_minor = effective_grid(settings)   # a blank interval falls back to 1 in
    length = max(float(model.length), 0.0)
    plot_length = max(math.ceil(length / h_minor - _EPS) * h_minor, h_minor)
    z0, z1, lowest, lowest_what = z_limits(model, settings, v_major, plot_length)

    plot_w = plot_length / H_s
    plot_h = (z1 - z0) / V_s
    sheet = (settings.sheet or "smallest").lower()
    allowed = _order_by_size(settings.allowed_sheets or ["letter", "tabloid"]) or ["letter", "tabloid"]
    candidates = [sheet] if sheet in SHEETS else allowed

    # margins: the elevation labels they make room for include any grid the fill may add. No fill on a custom
    # page (it is sized to the drawing) or for a manual range (the sheet shows the range as typed)
    types = legend_entries(model, settings)
    # the standard layout's notes and legend under the plot: the bottom margin holds them (standard_block_depth;
    # the notes wrap at the plot's width, at least NOTES_MIN_W)
    provisional = Plan(z_min=z0, z_max=z1, plot_length=plot_length, h_major=h_major, h_minor=h_minor,
                       v_major=v_major, v_minor=v_minor, pages=[])

    def block(width_in: float, names: Sequence[str]) -> float:
        if settings.compact_layout or not settings.show_notes:
            return 0.0
        name = max(names, key=lambda t: text_width_in(t, NOTE_PT))
        return _standard_block_in(model, settings, provisional, name, types, max(NOTES_MIN_W, width_in))

    # (the block and the fill below are sized for every sheet and orientation Auto may give, whatever the page
    # orientation: a page gets the same layout whether Auto or Landscape / Portrait chose it)
    names = (["Custom 000.25 × 000.25 in"] if sheet == "custom"
             else [sheet_label(k, ls) for k in candidates for ls in (True, False)])
    blk = block(plot_w, names)
    mg = margins(settings, (z0, z1), types, blk)
    fill = fill_mode(settings) if sheet != "custom" and settings.z_mode != "manual" else "off"
    fill_range = (z0, z1)
    if fill != "off":
        n = fill_majors(plot_h, max(SHEETS[k][0] for k in candidates), settings, v_major, mg)
        fill_range = (z0 - n * v_major, z1 + (n * v_major if fill == "both" else 0.0))
        mg = margins(settings, fill_range, types, blk)
    need = _need(plot_w, plot_h, mg, min_page_w(settings, types))

    def filled(Hh, m=None):
        return _fill(z0, z1, plot_h, Hh, settings, v_major, m or mg) if fill != "off" else (z0, z1)

    def result(pages, fits=True, message="", zz=(z0, z1)):
        zz0, zz1 = zz
        warnings = (manual_range_warnings(model, settings, zz0, zz1, v_major, plot_length)
                    if settings.z_mode == "manual" else [])
        warnings += td_warnings(model, settings, zz0, plot_length, v_major, zz1)
        return Plan(z_min=zz0, z_max=zz1, plot_length=plot_length, h_major=h_major, h_minor=h_minor,
                    v_major=v_major, v_minor=v_minor, pages=pages, fits=fits, message=message,
                    lowest_z=lowest, lowest_what=lowest_what, warnings=warnings)

    def one_page(W, H, name, zz):
        ph = (zz[1] - zz[0]) / V_s
        left, bottom = _place(W, H, plot_w, ph, mg)
        return PageLayout(page_w=W, page_h=H, sheet_name=name, plot_left=left, plot_bottom=bottom,
                          plot_w=plot_w, plot_h=ph, x_min=0.0, x_max=plot_length)

    size_txt = f"plot {plot_w:.2f} × {plot_h:.2f} in"

    # --- custom page: sized to the drawing (never filled)
    if sheet == "custom":
        W = max(math.ceil(need[0] * 4 - 1e-6) / 4, CUSTOM_MIN[0])
        Hh = max(math.ceil(need[1] * 4 - 1e-6) / 4, CUSTOM_MIN[1])
        name = f"Custom {fmt_num(W)} × {fmt_num(Hh)} in"
        return result([one_page(W, Hh, name, (z0, z1))], True, f"{name}; {size_txt}.")

    # --- candidate sheets, each in the orientations page_turns gives (Auto: landscape, then portrait)
    turns = page_turns(settings)
    for key in candidates:
        for landscape in turns:
            W, Hh = sheet_size(key, landscape)
            if _fits(need, (W, Hh)):
                zz = filled(Hh)
                name = sheet_label(key, landscape)
                page = one_page(W, Hh, name, zz)
                return result([page], True, f"{name}; plot {page.plot_w:.2f} × {page.plot_h:.2f} in.", zz)

    # --- does not fit one sheet
    need_W = math.ceil(need[0] * 4 - 1e-6) / 4
    need_H = math.ceil(need[1] * 4 - 1e-6) / 4
    need_page = PageLayout(page_w=need_W, page_h=need_H,
                           sheet_name=f"Needs {fmt_num(need_W)} × {fmt_num(need_H)} in (does not fit)",
                           plot_left=mg["left"], plot_bottom=mg["bottom"], plot_w=plot_w, plot_h=plot_h,
                           x_min=0.0, x_max=plot_length)
    names = " or ".join(SHEETS[k][2] for k in candidates)
    # messages are whole sentences: the panel shows them alone and after a "Does not fit:" prefix
    scales_txt = (f"The section needs a {fmt_num(need_W)} × {fmt_num(need_H)} in page at 1 in = "
                  f"{fmt_num(H_s)} ft horizontal and 1 in = {fmt_num(V_s)} ft vertical ({size_txt})")
    tile_key = candidates[-1]                       # largest allowed (or the named sheet)
    tname = SHEETS[tile_key][2]

    def tiled(landscape: bool):
        """(pages, message, elevation range) of the section tiled on tile_key in this orientation, else None."""
        W, Hh = sheet_size(tile_key, landscape)
        if W < min_page_w(settings, types) - _EPS:
            return None
        usable_ft = (W - mg["left"] - mg["right"]) * H_s
        windows = _tiles(plot_length, usable_ft, h_major)
        if windows is None:
            return None
        name = sheet_label(tile_key, landscape)
        # (each tile's notes wrap at its own plot width: the narrowest one sizes the block)
        mg_t = margins(settings, fill_range, types, block(min((b - a) / H_s for a, b, _, _ in windows), [name]))
        if plot_h + mg_t["top"] + mg_t["bottom"] > Hh + _EPS:
            return None
        zz = filled(Hh, mg_t)
        ph = (zz[1] - zz[0]) / V_s
        widest = max((b - a) / H_s for a, b, _, _ in windows)
        left, bottom = _place(W, Hh, widest, ph, mg_t)
        pages = []
        n = len(windows)
        for i, (a, b, ml, mr) in enumerate(windows, 1):
            pages.append(PageLayout(page_w=W, page_h=Hh, sheet_name=name, plot_left=left, plot_bottom=bottom,
                                    plot_w=(b - a) / H_s, plot_h=ph, x_min=a, x_max=b, tile_index=i,
                                    tile_count=n, match_left=ml, match_right=mr))
        ms = [fmt_station(p.match_right) for p in pages if p.match_right is not None]
        stations = ", ".join(ms) if len(ms) <= 5 else f"{', '.join(ms[:3])}, …, {ms[-1]} ({len(ms)} in all)"
        msg = (f"Too long for one {tname} sheet: tiled on {n} sheets ({name}), "
               f"match lines at STA {stations}.")
        return pages, msg, zz

    # Landscape or Portrait chosen: the messages name it, and offer Auto or the other orientation when that one
    # would hold the section (on one sheet, or tiled when tiling is on), as Auto then would
    chosen = "" if len(turns) > 1 else ("landscape" if turns[0] else "portrait")

    def alt() -> str:
        if not chosen:
            return ""
        turn = not turns[0]
        if any(_fits(need, sheet_size(k, turn)) for k in candidates) or (settings.tile and tiled(turn) is not None):
            return f"Auto or {'Landscape' if turn else 'Portrait'}, "
        return ""

    if not settings.tile:
        if not chosen:
            msg = (f"{scales_txt}, larger than {names} in either orientation. Choose a custom page size, "
                   f"a larger sheet, a smaller scale (more ft per inch), or turn on tiling.")
        else:
            msg = (f"{scales_txt}, larger than {names} in {chosen}. Choose {alt()}a custom page size, "
                   f"a larger sheet, a smaller scale (more ft per inch), or turn on tiling.")
        return result([need_page], False, msg)

    for landscape in turns:
        got = tiled(landscape)
        if got is not None:
            pages, msg, zz = got
            return result(pages, True, msg, zz)

    # height does not fit even the tiling sheet (or the grid is too coarse to tile)
    Wl, Hl = sheet_size(tile_key, True)
    room_l = Hl - mg["top"] - mg["bottom"]
    room_p = sheet_size(tile_key, False)[1] - mg["top"] - mg["bottom"]
    if not chosen:
        if plot_h > room_p + _EPS:
            msg = (f"The section is {plot_h:.2f} in tall at 1 in = {fmt_num(V_s)} ft vertical "
                   f"(elevation {fmt_num(z0)} to {fmt_num(z1)} ft), but a {tname} sheet has room for "
                   f"{room_l:.2f} in (landscape) or {room_p:.2f} in (portrait). Use a smaller vertical scale "
                   f"(more ft per inch), a narrower manual elevation range, a larger sheet, or a custom page size.")
        else:
            msg = (f"The grid (major {fmt_num(h_major)} ft = {fmt_in(h_major / H_s)} in) is too coarse to tile "
                   f"on {tname} sheets. {scales_txt}. Choose a smaller major grid, a larger sheet, "
                   f"or a custom page size.")
        return result([need_page], False, msg)
    room = room_l if turns[0] else room_p          # the chosen orientation's room only
    other = alt()
    if plot_h > room + _EPS:
        msg = (f"The section is {plot_h:.2f} in tall at 1 in = {fmt_num(V_s)} ft vertical "
               f"(elevation {fmt_num(z0)} to {fmt_num(z1)} ft), but a {tname} sheet has room for "
               f"{room:.2f} in ({chosen}). {'Choose ' + other if other else 'Use '}a smaller vertical scale "
               f"(more ft per inch), a narrower manual elevation range, a larger sheet, or a custom page size.")
    else:
        msg = (f"The grid (major {fmt_num(h_major)} ft = {fmt_in(h_major / H_s)} in) is too coarse to tile "
               f"on {tname} sheets in {chosen}. {scales_txt}. Choose {other}a smaller major grid, a larger sheet, "
               f"or a custom page size.")
    return result([need_page], False, msg)
