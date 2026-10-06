"""Page planning: plot size from the scales, elevation limits, sheet choice and tiling.

Pure arithmetic in inches and feet (no matplotlib, no Qt). The plot area is always
exactly (distance range / h_scale) x (elevation range / v_scale) inches; nothing here
ever shrinks a drawing to fit a page.
"""
from __future__ import annotations

import bisect
import math
from typing import Any, Callable, Iterable, List, NamedTuple, Optional, Sequence, Tuple, Union

from ..core.model import GroundProfile, Hit, PageLayout, Plan, SectionError, SectionModel, Settings

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
LEGEND_MIN_W = 2.4                         # least width kept for a line-colour legend beside the scale bar
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
    """'MW-3' or, with label_offset, 'MW-3 · 40 ft N'."""
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
              z_in: Callable[[float], float], k: float = 1.0) -> List[Tuple[float, float, float, float]]:
    """Boxes (left, right, bottom, top) of the bars across the ends of the drawn lines, in the units of
    `x_in` (station ->) and `z_in` (elevation ->). TD labels keep clear of them: a label may cross a
    neighbour's line, never hide where it ends."""
    half_w, half_h = CROSSBAR_IN * k / 2.0, BAR_CLEAR_IN * k / 2.0
    out = []
    for h in hits:
        if not draws_depth_line(h, settings):
            continue
        for z in [h.bottom] + ([h.top] if draws_top_cap(h, settings) else []):
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
              z_range: Optional[Tuple[float, float]] = None) -> List[Tuple[Hit, Optional[float]]]:
    """(hit, lowest elevation its TD label reaches (ft), or None when it has no free row) for every hit
    with a TD label, laid out on paper as figure.py draws them across the whole section: clear of the
    other TD labels and of the bars, and where a row allows it clear of the ticks, the exploration labels
    and (given `ground`) the ground line."""
    v, hs = float(settings.v_scale), float(settings.h_scale)
    hits = list(hits)
    items = [h for h in hits if draws_td_label(h, settings)]
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


def tick_base(hit: Hit, settings: Settings) -> float:
    """Elevation the tick sits above: the ground, raised to clear the top only when the
    top-to-bottom line is actually drawn (decision 1: without a line there is nothing to clear)."""
    return hit.tick_base(draws_depth_line(hit, settings))


def sheet_label(key: str, landscape: bool) -> str:
    long_, short, name = SHEETS[key]
    w, h = (long_, short) if landscape else (short, long_)
    return f"{name} {fmt_num(w)} × {fmt_num(h)} in, {'landscape' if landscape else 'portrait'}"


def sheet_size(key: str, landscape: bool) -> Tuple[float, float]:
    long_, short, _ = SHEETS[key]
    return (float(long_), float(short)) if landscape else (float(short), float(long_))


# ----------------------------------------------------------------------------- limits
def _floor_to(v: float, step: float) -> float:
    return math.floor(v / step + _EPS) * step


def _ceil_to(v: float, step: float) -> float:
    return math.ceil(v / step - _EPS) * step


def _data_extent(model: SectionModel, settings: Settings) -> Tuple[float, float, float, str]:
    """(lo, hi, lowest_z, lowest_what) over the ground, tick bases and (when drawn) tops/bottoms."""
    lo, hi = math.inf, -math.inf
    what = ""
    for s, z in zip(model.ground.stations, model.ground.z):
        if z is None or math.isnan(z):
            continue
        if z < lo:
            lo, what = z, f"the ground at {fmt_num(s, 0)} ft"
        hi = max(hi, z)
    for h in model.hits:
        base = tick_base(h, settings)
        if base is not None and not math.isnan(base):
            if base < lo:
                lo, what = base, f"the ground at {h.label}"
            hi = max(hi, base)
        if settings.depth_line:
            if h.bottom is not None and not math.isnan(h.bottom) and h.bottom < lo:
                lo, what = h.bottom, f"the bottom of {h.label}"
            if h.top is not None and not math.isnan(h.top):
                hi = max(hi, h.top)
        if settings.screens:
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
        # the TD labels hang below the bottoms: below_in of grid is kept under the lowest of them too
        reach = [r for _, r in td_labels(model.hits, settings, plot_length or model.length, model.ground)
                 if r is not None]
        lo = min([lo] + reach)
        z0 = _floor_to(lo - settings.below_in * v, v_major)
        # at least LABEL_HEADROOM_IN above the data; more when long or stacked labels need it
        z1 = _ceil_to(max(hi + LABEL_HEADROOM_IN * v, label_top(model.hits, settings)), v_major)
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
    labels = td_labels(model.hits, settings, plot_length, model.ground, z_range)
    out = []
    crowded = [h.label for h, reach in labels if reach is None]
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
                          v_major: float) -> List[str]:
    """What a manual elevation range cuts off (the sheet clips it), as messages for the panel."""
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
    need = label_top(inside, settings)
    if need > z1 + (LABEL_MARGIN_IN + 0.1) * v:           # labels would cross the frame by more than 0.1 in
        return [f"Exploration labels run above the plot with the manual maximum of {fmt_num(z1)} ft. Raise it "
                f"to {fmt_num(_ceil_to(need, v_major))} ft or set Elevations to Auto."]
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


def legend_types(model: SectionModel, settings: Settings) -> List[str]:
    """Type values the sheet's line-colour legend lists (none unless lines are coloured by type)."""
    if settings.data_color != "type" or not settings.depth_line:
        return []
    return sorted({h.type_value for h in model.hits if h.type_value})


class LegendEntry(NamedTuple):
    """One entry of the sheet's legend."""
    text: str
    kind: str                  # type | surface | screen | measured | atd
    key: Any = None            # the type value, or the index of the surface in model.surfaces


def legend_entries(model: SectionModel, settings: Settings) -> List[LegendEntry]:
    """What the legend beside (compact) or under (standard) the scale bar lists: the line colours by type, the
    other surfaces, and the screen and water level symbols that are on the sheet."""
    out = [LegendEntry(t, "type", t) for t in legend_types(model, settings)]
    for i, sp in enumerate(getattr(model, "surfaces", None) or []):
        out.append(LegendEntry(sp.name, "surface", i))
    if settings.screens:
        hits = model.hits
        if any(_finite(h.screen_top) for h in hits):
            out.append(LegendEntry("Screen", "screen"))
        levels = [w for h in hits for w in h.water_levels]
        if any(w.kind == "measured" for w in levels):
            out.append(LegendEntry("Water level", "measured"))
        if any(w.kind == "atd" for w in levels):
            out.append(LegendEntry("Water at time of drilling (ATD)", "atd"))
    return out


def _entry_text(e: Union[str, LegendEntry]) -> str:
    return e if isinstance(e, str) else e.text


def legend_rows(types: Sequence[Union[str, LegendEntry]], width_in: float,
                size_pt: float) -> List[List[Tuple[str, float, Any]]]:
    """The legend in rows `width_in` wide: (text, x of its swatch from the row start, entry) of each entry, the
    first row starting with the label itself (entry "", no swatch): "Line colors:" when every entry is a type
    (given as a type value or a LegendEntry of kind "type"), else "Legend:". Later rows are indented 0.1 in; a
    name too long for a row is cut short with "…"."""
    if not types:
        return []
    only_types = all(isinstance(e, str) or e.kind == "type" for e in types)
    label = "Line colors:" if only_types else "Legend:"
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
    (compact), or just the scale bar (no notes; and a legend beside it when lines are coloured by type)."""
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


def vbar_dx_in(settings: Settings, label_w: float) -> float:
    """Frame right to the vertical graphic scale: standard VBAR_STD_DX_IN; compact just clear of the right
    elevation labels (`label_w` wide)."""
    if not settings.compact_layout:
        return VBAR_STD_DX_IN
    return (AXIS_TICK_PT + AXIS_PAD_PT) / 72.0 + label_w + VBAR_GAP_IN


def margins(settings: Settings, z_range: Optional[Tuple[float, float]] = None,
            types: Sequence[str] = ()) -> dict:
    """Inches from each paper edge to the plot frame: dict(left, right, top, bottom).

    Standard layout with notes: MARGIN, moved by the printer edge (edge 0.5 in = MARGIN; 0.3 in = 0.2 in
    less on every side). The compact layout, and the bottom without notes, are added up from what is drawn
    there (the metrics above) plus LAYOUT_PAD_IN, then rounded up to 0.01 in. `z_range` (the elevations
    the sheet may label, fill included) sizes the elevation labels, else a five-digit label is assumed;
    `types` is the line-colour legend (legend_types).

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
    mg = margins(settings, (z0, z1), types)
    fill = fill_mode(settings) if sheet != "custom" and settings.z_mode != "manual" else "off"
    if fill != "off":
        n = fill_majors(plot_h, max(SHEETS[k][0] for k in candidates), settings, v_major, mg)
        mg = margins(settings, (z0 - n * v_major, z1 + (n * v_major if fill == "both" else 0.0)), types)
    need = _need(plot_w, plot_h, mg, min_page_w(settings, types))

    def filled(Hh):
        return _fill(z0, z1, plot_h, Hh, settings, v_major, mg) if fill != "off" else (z0, z1)

    def result(pages, fits=True, message="", zz=(z0, z1)):
        zz0, zz1 = zz
        warnings = (manual_range_warnings(model, settings, zz0, zz1, v_major)
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

    # --- candidate sheets
    for key in candidates:
        for landscape in (True, False):
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

    if not settings.tile:
        msg = (f"{scales_txt}, larger than {names} in either orientation. Choose a custom page size, "
               f"a larger sheet, a smaller scale (more ft per inch), or turn on tiling.")
        return result([need_page], False, msg)

    tile_key = candidates[-1]                       # largest allowed (or the named sheet)
    tname = SHEETS[tile_key][2]
    for landscape in (True, False):
        W, Hh = sheet_size(tile_key, landscape)
        if plot_h + mg["top"] + mg["bottom"] > Hh + _EPS or W < min_page_w(settings, types) - _EPS:
            continue
        usable_ft = (W - mg["left"] - mg["right"]) * H_s
        windows = _tiles(plot_length, usable_ft, h_major)
        if windows is None:
            continue
        zz = filled(Hh)
        ph = (zz[1] - zz[0]) / V_s
        widest = max((b - a) / H_s for a, b, _, _ in windows)
        left, bottom = _place(W, Hh, widest, ph, mg)
        name = sheet_label(tile_key, landscape)
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
        return result(pages, True, msg, zz)

    # height does not fit even the tiling sheet (or the grid is too coarse to tile)
    Wl, Hl = sheet_size(tile_key, True)
    room_l = Hl - mg["top"] - mg["bottom"]
    room_p = sheet_size(tile_key, False)[1] - mg["top"] - mg["bottom"]
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
