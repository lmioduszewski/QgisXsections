"""What the preview's hover readout shows: the lines as drawn, their value at a station, and the text of each cell.

No widgets and no drawing: the preview (ui/preview.py, ui/readout.py) and the surfaces CSV (core/surfaces_csv.py)
read the same lines through hover_lines(), and every value comes from z_on(), the rule render/figure.py draws by,
so a number in the readout or the CSV is always a point on the line on screen.

What can be pointed at (0.3.3): the explorations (model.hits) and the other points (model.other_points), in one
index, hover_targets(): the preview's hoverChanged index, the readout's rows and the popup's cards all count that
way. target_cells() gives either kind's cells (hit_cells, other_cells); strip_cells() (0.3.4) the readout strip's
shorter form of them (a water level titled by its date).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from ..render.scales import fmt_num, fmt_station, pretty_label   # plain text helpers (no matplotlib)
from .model import Hit, OtherPoint, SectionModel, Settings, clean_other_points, hit_settings

# the ground line's colour and width on the sheet: render/figure.py INK and GROUND_LW (the tests pin them equal)
GROUND_COLOR = "#000000"
GROUND_WIDTH = 1.1
NO_VALUE = "—"                            # a readout value that is not there (its small print says why)


@dataclass(eq=False)                      # (compared by identity: == on the arrays would be ambiguous)
class HoverLine:
    """One line the preview draws, in drawing (and legend) order: the ground first, then each other surface."""
    name: str               # "Ground (<DEM name>)" for the ground, else the surface's legend name
    color: str              # "#000000" for the ground, else the surface's colour
    style: str              # solid | dash | dot
    width: float            # pt
    ground: bool
    stations: np.ndarray    # ft, as drawn (cells mode: each cell edge twice, a step)
    z: np.ndarray           # ft; nan = no data (the drawn line breaks there)


def hover_lines(model: SectionModel) -> List[HoverLine]:
    """Every line of the section as the preview draws it: the ground, then each model.surfaces entry in order."""
    g = model.ground
    out = [HoverLine(name=f"Ground ({model.dem_name})" if model.dem_name else "Ground", color=GROUND_COLOR,
                     style="solid", width=GROUND_WIDTH, ground=True, stations=np.asarray(g.stations, float),
                     z=np.asarray(g.z, float))]
    for sp in getattr(model, "surfaces", None) or []:
        out.append(HoverLine(name=sp.name, color=sp.color, style=sp.style, width=float(sp.width), ground=False,
                             stations=np.asarray(sp.stations, float), z=np.asarray(sp.z, float)))
    return out


def _end_slack(st: np.ndarray) -> float:
    """How far past either end of a line a station still reads the end's value: a hair (1e-9 of the line's reach),
    so a line whose last vertex came out a rounding error short of the model length still has a value there."""
    return 1e-9 * max(1.0, abs(float(st[-1])))


def z_on(stations: Sequence[float], z: Sequence[float], station: float) -> float:
    """A line's elevation at `station`, as matplotlib draws it through the vertices (stations, z): at a vertex its
    own value; between two vertices linear (nan when either is nan: the line breaks there); at a doubled station
    (a cells-mode step) the value right of the step; nan before the first vertex, past the last (beyond a rounding
    error, _end_slack), and for a nan station. (render/figure.py places water-table marks by the 0.3.0 rule, which
    differs only at a vertex followed by nan: nan there.)"""
    st = np.asarray(stations, float)
    if st.size == 0:
        return math.nan
    tol = _end_slack(st)
    if not st[0] - tol <= station <= st[-1] + tol:
        return math.nan
    station = min(max(station, st[0]), st[-1])
    i = int(np.searchsorted(st, station, side="right")) - 1
    i = min(max(i, 0), st.size - 1)
    if i + 1 < st.size and st[i + 1] > st[i] and station > st[i]:
        t = (station - st[i]) / (st[i + 1] - st[i])
        return float(z[i] + (z[i + 1] - z[i]) * t)
    return float(z[i])


def z_on_array(stations: Sequence[float], z: Sequence[float], at: Sequence[float]) -> np.ndarray:
    """z_on() at many stations at once (the same arithmetic, so the same values)."""
    st = np.asarray(stations, float)
    zz = np.asarray(z, float)
    at = np.asarray(at, float)
    out = np.full(at.shape, np.nan)
    if st.size == 0 or at.size == 0:
        return out
    tol = _end_slack(st)
    with np.errstate(invalid="ignore"):
        inside = (at >= st[0] - tol) & (at <= st[-1] + tol)
    if not inside.any():
        return out
    s = np.clip(at[inside], st[0], st[-1])
    i = np.clip(np.searchsorted(st, s, side="right") - 1, 0, st.size - 1)
    j = np.minimum(i + 1, st.size - 1)
    between = (j > i) & (st[j] > st[i]) & (s > st[i])
    span = np.where(between, st[j] - st[i], 1.0)
    t = np.where(between, (s - st[i]) / span, 0.0)
    with np.errstate(invalid="ignore"):
        out[inside] = np.where(between, zz[i] + (zz[j] - zz[i]) * t, zz[i])
    return out


def line_value(line: HoverLine, station: float, length: float) -> float:
    """`line`'s elevation at `station` (z_on), nan off the section (before 0 or past `length`, the model length:
    the preview's frame runs on to the plot length, and panning shows negative distances)."""
    if not 0.0 <= station <= length:
        return math.nan
    return z_on(line.stations, line.z, station)


def _finite(v: Optional[float]) -> bool:
    return v is not None and math.isfinite(v)


def _f1(v: float) -> str:
    """One decimal with thousands separators, never "-0.0": 655.27 -> "655.3", 1234.5 -> "1,234.5"."""
    v = round(float(v), 1)
    return f"{v + 0.0:,.1f}"                       # (-0.0 + 0.0 is 0.0)


def _n1(v: float) -> str:
    """To 0.1 ft, trailing zeros dropped, never "-0": 21.47 -> "21.5", 29.98 -> "30"."""
    return fmt_num(round(float(v), 1) + 0.0, 1)


def elev_text(z: Optional[float]) -> str:
    """ "655.3 ft"; "" without a value."""
    return f"{_f1(z)} ft" if _finite(z) else ""


def depth_text(ground_z: Optional[float], z: Optional[float]) -> str:
    """How far `z` is below the ground ("13.6 bgs", below ground surface) or above it ("0.6 ags"), to 0.1 ft; ""
    when either is missing. A value within 0.05 ft of the ground reads "0.0 bgs"."""
    if not (_finite(ground_z) and _finite(z)):
        return ""
    d = round(float(ground_z) - float(z), 1)
    return f"{_f1(abs(d))} bgs" if d >= 0 else f"{_f1(-d)} ags"


def distance_text(station: float, settings: Optional[Settings]) -> str:
    """A distance along the section to the whole foot: "1,240 ft", or "12+40" with station labels."""
    v = int(round(float(station)))
    if getattr(settings, "distance_labels", "feet") == "station":
        return fmt_station(v)
    return f"{v:,} ft"


@dataclass
class HoverValues:
    """Every line's value at one station of the preview."""
    station: float
    cursor_z: Optional[float]   # the mouse's elevation (None when the guide comes from the map)
    ground_z: float             # the ground line there (nan in a DEM gap and off the section)
    values: List[float]         # one per hover_lines() entry (nan where that line has no value)
    nearest: int                # index of the value nearest cursor_z (-1 without a cursor or any value)


def hover_values(lines: Sequence[HoverLine], station: float, length: float,
                 cursor_z: Optional[float] = None) -> HoverValues:
    """The value of each line at `station` (line_value), the ground's, and which line is nearest the cursor
    elevation (the first of equals, so the ground wins a tie)."""
    values = [line_value(ln, station, length) for ln in lines]
    ground_z = next((v for ln, v in zip(lines, values) if ln.ground), math.nan)
    nearest = -1
    if _finite(cursor_z):
        best = math.inf
        for i, v in enumerate(values):
            if math.isfinite(v) and abs(v - cursor_z) < best:
                nearest, best = i, abs(v - cursor_z)
    return HoverValues(station=float(station), cursor_z=None if cursor_z is None else float(cursor_z),
                       ground_z=ground_z, values=values, nearest=nearest)


def top_source_name(hit: Hit, settings: Settings) -> str:
    """Where an exploration's top came from, named as the panel's depth sources line names it: the top field
    ("table" when none is named), "LIDAR", or "none"."""
    names = {"field": settings.top_field or "table", "dem": "LIDAR", "none": "none"}
    return names.get(hit.top_source, hit.top_source or "none")


def _below_top(top: Optional[float], z: float) -> str:
    """ "9.2 below top" ("1.5 above top" for a level over it); "" without a top."""
    if not _finite(top):
        return ""
    d = round(float(top) - float(z), 1)
    return f"{_n1(abs(d))} below top" if d >= 0 else f"{_n1(-d)} above top"


def _screen_depths(top: Optional[float], screen_top: float, screen_bottom: float) -> str:
    """A screen's depths below the exploration's top: "9.5–19.5 below top"; a screen reaching above the top (kept
    within the slack, or drawn with a flag: core.explorations.screen_and_levels) "0.4 above – 9.6 below top", or
    "0.8–0.2 above top" when all of it is; "" without a top. Each end to 0.1 ft first, so a hair above reads 0."""
    if not _finite(top):
        return ""
    d1 = round(float(top) - float(screen_top), 1) + 0.0         # (+ 0.0: never "-0")
    d2 = round(float(top) - float(screen_bottom), 1) + 0.0
    if d1 >= 0:
        return f"{_n1(d1)}–{_n1(d2)} below top"
    if d2 >= 0:
        return f"{_n1(-d1)} above – {_n1(d2)} below top"
    return f"{_n1(-d1)}–{_n1(-d2)} above top"


def _levels_set_up(settings: Settings) -> bool:
    """True when the settings read water levels (so "none" means the exploration has none)."""
    return bool(settings.screens and (settings.wl_field or settings.atd_field or settings.wl_table_id))


def hover_targets(model: Optional[SectionModel]) -> list:
    """Everything the preview's hover can point at, in its index order: the plotted explorations (model.hits),
    then the other points (model.other_points). The preview's hoverChanged index counts in this list."""
    if model is None:
        return []
    return list(getattr(model, "hits", None) or []) + list(getattr(model, "other_points", None) or [])


def hover_target(model: Optional[SectionModel], index: int) -> Any:
    """hover_targets(model)[index]: a Hit or an OtherPoint; None for -1 (nothing pointed at) or out of range."""
    targets = hover_targets(model)
    if not isinstance(index, int) or not 0 <= index < len(targets):
        return None
    return targets[index]


def several_layers(model: Optional[SectionModel]) -> bool:
    """More than one exploration row is on (model.point_layers): the hover then names each exploration's layer."""
    return sum(1 for info in (getattr(model, "point_layers", None) or []) if getattr(info, "on", False)) > 1


def _target_label(t: Any) -> str:
    """A hover target's name: its label, else its feature id."""
    label = getattr(t, "label", "")
    return label if label not in (None, "") else str(getattr(t, "fid", ""))


def _offset_cell(t: Any, settings: Settings) -> Tuple[str, str, str]:
    """("From A", its distance along the line, "40 ft left"); a crossing of a line row (0.3.6, on the line): "crossing"
    as the small print."""
    if getattr(t, "kind", "point") == "crossing":
        return f"From {pretty_label(settings.start_label)}", distance_text(t.station, settings), "crossing"
    side = "left" if t.side == "L" else "right"
    return (f"From {pretty_label(settings.start_label)}", distance_text(t.station, settings),
            f"{_n1(t.offset)} ft {side}")


def hit_cells(hit: Hit, settings: Settings, model: Optional[SectionModel] = None) -> List[Tuple[str, str, str]]:
    """The readout row of an exploration as (title, value, small print) cells: its type and name (and, when more
    than one exploration layer is on in `model`, its layer's legend name as the small print); distance from the
    start ("From A") and offset; top and where it came from; total depth and bottom; screen (elevations, and depths
    below the exploration's top); each water level (date and depth below the top) or "none". A value that is not
    there reads NO_VALUE ("—"). The top field and the water-level fields are those of the hit's own row
    (model.hit_settings). Without `model`: exactly 0.3.2's cells."""
    ls = hit_settings(settings, hit)
    label = _target_label(hit)
    layer = (getattr(hit, "layer_name", "") or "") if several_layers(model) else ""
    cells = [(hit.type_value or "Exploration", label, layer), _offset_cell(hit, settings)]
    top = hit.top if _finite(hit.top) else None
    if top is not None:
        cells.append(("Top", elev_text(top), top_source_name(hit, ls)))
    else:
        cells.append(("Top", NO_VALUE, "none"))
    bottom = hit.bottom if _finite(hit.bottom) else None
    td = hit.total_depth if _finite(hit.total_depth) else None
    if td is None and top is not None and bottom is not None:
        td = top - bottom
    if td is not None:
        cells.append(("Total depth", f"{_n1(td)} ft", f"bottom {_f1(bottom)}" if bottom is not None else ""))
    if _finite(hit.screen_top) and _finite(hit.screen_bottom):
        cells.append(("Screen", f"{_f1(hit.screen_top)}–{_f1(hit.screen_bottom)} ft",
                      _screen_depths(top, hit.screen_top, hit.screen_bottom)))
    levels = [w for w in (hit.water_levels or []) if _finite(w.elev)]
    for w in levels:
        small = " · ".join(t for t in (w.date, _below_top(top, w.elev)) if t)
        cells.append(("ATD level" if w.kind == "atd" else "Measured level", elev_text(w.elev), small))
    if not levels and _levels_set_up(ls):
        cells.append(("Water level", NO_VALUE, "none"))
    return cells


def _other_row(p: Any, settings: Optional[Settings], model: Optional[SectionModel]) -> Tuple[str, str]:
    """(elev, elev_field) of an other point's row: the model's OtherLayerInfo, else the settings' row, else none."""
    i = getattr(p, "layer_index", 0)
    infos = getattr(model, "other_layers", None) or []
    if isinstance(i, int) and 0 <= i < len(infos):
        return infos[i].elev, infos[i].elev_field
    rows = clean_other_points(getattr(settings, "other_points", None) or [])
    if isinstance(i, int) and 0 <= i < len(rows):
        return rows[i]["elev"], rows[i]["elev_field"]
    return "", ""


def _elev_source(p: Any, elev: str, field: str) -> str:
    """Where an other point's elevation came from: "ground line", "LIDAR at the point", the field's name, or the
    fallback with what was missing: "ground line (no Elev_ft)", "LIDAR (no Elev_ft)", "ground line (no LIDAR)"."""
    name = field or "field"
    if p.how == "field":
        return name
    if p.how == "lidar":
        return f"LIDAR (no {name})" if getattr(p, "fell_back", False) else "LIDAR at the point"
    if getattr(p, "fell_back", False):
        return "ground line (no LIDAR)" if elev == "lidar" else f"ground line (no {name})"
    return "ground line"


def other_cells(p: OtherPoint, settings: Settings, model: Optional[SectionModel] = None) -> List[Tuple[str, str, str]]:
    """The readout row of an other point (a seep, a spring ...) as (title, value, small print) cells: its type
    (else its layer's legend name) over its name, with the legend name as the small print beside a type; "From A"
    and its offset; the elevation it marks and where that came from; the LIDAR at the point when the elevation is
    not that; the ground line at its station (and how far the point is below or above it) when the point is not on
    it. Never a water level's titles."""
    name = getattr(p, "layer_name", "") or "Other point"
    elev, field = _other_row(p, settings, model)
    cells = [(p.type_value or name, _target_label(p), name if p.type_value else ""), _offset_cell(p, settings),
             ("Elevation", elev_text(p.z) if _finite(p.z) else NO_VALUE, _elev_source(p, elev, field))]
    lidar = getattr(p, "ground_at_point", math.nan)
    if p.how != "lidar" and _finite(lidar):
        cells.append(("LIDAR", elev_text(lidar), "at the point"))
    gs = getattr(p, "ground_at_station", math.nan)
    if p.how != "line":
        cells.append(("Ground line", elev_text(gs) if _finite(gs) else NO_VALUE, depth_text(gs, p.z)))
    return cells


def is_other_point(t: Any) -> bool:
    """True for an other point (core.model.OtherPoint), False for an exploration."""
    return isinstance(t, OtherPoint)


def target_cells(t: Any, settings: Settings, model: Optional[SectionModel] = None) -> List[Tuple[str, str, str]]:
    """The readout row of whatever is pointed at: other_cells for an other point, else hit_cells."""
    if is_other_point(t):
        return other_cells(t, settings, model)
    return hit_cells(t, settings, model)


def strip_cells(t: Any, settings: Settings, model: Optional[SectionModel] = None) -> List[Tuple[str, str, str, str]]:
    """The strip's cells of what is pointed at, (title, value, small print, level kind): target_cells, but a water
    level reads its date as the title ("Measured" / "ATD" without one) and "11.3 below top" as the small print, with
    its symbol (kind "measured" / "atd"); every other cell as target_cells gives it, kind "". (The popup keeps
    target_cells.)"""
    cells = target_cells(t, settings, model)
    if is_other_point(t):
        return [(a, b, c, "") for a, b, c in cells]
    top = t.top if _finite(t.top) else None
    levels = iter([w for w in (t.water_levels or []) if _finite(w.elev)])   # hit_cells' own order
    out = []
    for i, (title, value, small) in enumerate(cells):
        kind = {"Measured level": "measured", "ATD level": "atd"}.get(title, "") if i else ""   # (not the type)
        w = next(levels, None) if kind else None
        if w is not None:
            title, small = (w.date or ("ATD" if kind == "atd" else "Measured")), _below_top(top, w.elev)
        out.append((title, value, small, kind))
    return out


ALSO_MAX = 3                              # the popup's "Also here" rows before "+N more"


def also_cells(targets: Sequence[Any], settings: Settings, model: Optional[SectionModel]) -> List[Tuple[str, str, str]]:
    """The popup's "Also here" rows for the other targets at the spot pointed at (explorations of two layers at
    the same place are both plotted, decision 4): ("Also here", name, layer) for each, the layer's legend name
    ("" with one exploration layer on and no other points), at most ALSO_MAX, then ("", "+N more", "")."""
    targets = [t for t in targets if t is not None]
    named = several_layers(model) or bool(getattr(model, "other_points", None))
    out = [("Also here", _target_label(t), (getattr(t, "layer_name", "") or "") if named else "")
           for t in targets[:ALSO_MAX]]
    if len(targets) > ALSO_MAX:
        out.append(("", f"+{len(targets) - ALSO_MAX} more", ""))
    return out
