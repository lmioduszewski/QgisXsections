"""Project explorations (borings, wells, test pits ...) onto the section line.

Rules (DESIGN.md decisions 2 and 3):
- perpendicular projection; flat end caps: an exploration whose nearest point on the line is an end
  point and that lies past that end is left out and listed in `beyond_ends` (if within tolerance);
- each exploration on its own (top_and_bottom): the top comes from the table when it has a usable
  value close enough to LIDAR, else from LIDAR at the exploration's own x, y; the bottom comes from
  the table's bottom elevation when it is below the top (and agrees with top - depth), else top - depth.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsExpression, QgsFeatureRequest, QgsGeometry,
                       QgsProject, QgsVectorLayer, QgsWkbTypes)

from .model import GroundProfile, Hit, SectionError, Settings, WaterLevel
from .section import azimuth_deg, compass_point, ground_profile, line_vertices

NEAR_FACTOR = 2.5          # near_count radius, x tolerance
BOTTOM_AGREE_FT = 5.0      # a table bottom and top - depth further apart than this get an info flag
MIN_DEPTH_FT = 0.05        # a bottom must be more than this below the top (TD labels round to 0.1 ft)
FT_PER_M = 3.280839895     # to spot a table top entered in meters (table values are read as feet)
SCREEN_SLACK_FT = 1.0      # a screen or water level this far past the top or the bottom is still drawn (flagged)
WL_ABOVE_FT = 100.0        # a water level more than this above the top is taken for bad data and left out
WL_BELOW_NO_BOTTOM_FT = 1000.0   # ... or more than this below the top, when the exploration has no bottom


def to_number(value: Any) -> Optional[float]:
    """Attribute value -> float, or None for NULL / empty / non-numeric / nan."""
    if value is None:
        return None
    is_null = getattr(value, "isNull", None)
    if callable(is_null) and is_null():
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    is_null = getattr(value, "isNull", None)
    if callable(is_null) and is_null():
        return ""
    return str(value)


def date_text(value: Any) -> str:
    """A date attribute as text: a date (or date and time) as M/D/YYYY, anything else as it is written."""
    if value is None:
        return ""
    is_null = getattr(value, "isNull", None)
    if callable(is_null) and is_null():
        return ""
    if callable(getattr(value, "date", None)) and callable(getattr(value, "time", None)):
        value = value.date()                              # QDateTime / datetime -> the date
    if all(callable(getattr(value, a, None)) for a in ("year", "month", "day")):        # QDate
        try:
            y, m, d = int(value.year()), int(value.month()), int(value.day())
            if y > 0:
                return f"{m}/{d}/{y}"
        except (TypeError, ValueError):
            pass
    if all(isinstance(getattr(value, a, None), int) for a in ("year", "month", "day")):  # python date
        return f"{value.month}/{value.day}/{value.year}"
    text = str(value).strip()
    if isinstance(value, float) and text.endswith(".0"):
        text = text[:-2]
    return text


def name_key(text: Any) -> str:
    """An exploration name as matched between the explorations and the water-level table: case and runs of
    spaces ignored."""
    return " ".join(_text(text).split()).casefold()


def fmt_ft(v: float) -> str:
    """205.6 -> '205.6', 530.0 -> '530'."""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _attr_number(feature, i: int) -> Optional[float]:
    return to_number(feature.attribute(i)) if i >= 0 else None


def _field_index(layer: QgsVectorLayer, name: str, what: str) -> int:
    if not name:
        return -1
    i = layer.fields().lookupField(name)
    if i < 0:
        raise SectionError(f"The {what} field “{name}” is not in {layer.name()}. Choose another field.")
    return i


def _type_filter(layer: QgsVectorLayer, type_i: int, types: List[str]) -> str:
    if type_i < 0 or not types:
        return ""
    fld = layer.fields().at(type_i)
    quoted = []
    for v in types:
        num = to_number(v) if fld.isNumeric() else None
        quoted.append(repr(num) if num is not None else QgsExpression.quotedValue(str(v)))
    return f"{QgsExpression.quotedColumnRef(fld.name())} IN ({', '.join(quoted)})"


class TopBottom(NamedTuple):
    top: Optional[float]
    top_source: str                    # field | dem | none
    bottom: Optional[float]
    bottom_source: str                 # field | shifted | depth | none
    total_depth: Optional[float]
    flags: List[str]


def usable(value: Optional[float], zero_is_missing: bool) -> Optional[float]:
    """The value, or None when it is NULL, NaN or infinite, or 0 while 0 counts as missing."""
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or (zero_is_missing and x == 0.0):
        return None
    return x


def _metric_hint(table_top: float, lidar: float, max_diff: float) -> str:
    """' (205.6 m would match: ...)' when the table value read as meters is close to LIDAR."""
    if abs(table_top * FT_PER_M - lidar) <= max(max_diff, 1.0):
        return f" ({fmt_ft(table_top)} m would match: XSections reads table values as feet)"
    return ""


def top_and_bottom(table_top: Optional[float], lidar: Optional[float], table_bottom: Optional[float],
                   depth: Optional[float], settings: Settings) -> TopBottom:
    """Top, bottom and total depth of one exploration (decision 2). Pure: no QGIS objects.

    `table_top`, `table_bottom` and `depth` are the attribute values as numbers (None for NULL; zeros
    are judged here with settings.zero_is_missing); `lidar` is the DEM at the exploration (nan or
    None where there is no DEM).

    TOP    field_then_dem: the table top if usable and within top_max_diff_ft of LIDAR (or there is no
           LIDAR there), else LIDAR. dem: LIDAR only. field: the table only (flagged when far off).
    BOTTOM the table bottom elevation if usable and below the top; else top - depth (a negative depth
           is used as positive, a depth of about 0 is no depth); else none. The table comes first (the
           user's rule): when the top is the table's own value, a table bottom that disagrees with
           top - depth is kept and flagged. Only when the top is NOT from the table (the table top was
           rejected, or tops come from LIDAR) is the table bottom checked against top - depth and
           replaced when more than top_max_diff_ft off. The table bottom of a record whose table top was
           rejected is on the same wrong datum: without a depth it moves with the top ("shifted":
           LIDAR - (table top - table bottom)).
    """
    zm = settings.zero_is_missing
    t_top, t_bot, dep = usable(table_top, zm), usable(table_bottom, zm), usable(depth, zm)
    have_lidar = lidar is not None and math.isfinite(lidar)
    flags: List[str] = []
    top_name = settings.top_field or "top field"
    bot_name = settings.bottom_elev_field or "bottom elevation"
    dep_name = settings.depth_field or "depth"

    # --- top
    max_diff = settings.top_max_diff_ft
    far = t_top is not None and have_lidar and max_diff > 0 and abs(t_top - lidar) > max_diff
    mode = settings.top_mode
    top: Optional[float] = None
    top_source = "none"
    top_rejected = False                               # a table top that LIDAR contradicts was replaced
    if mode == "dem":
        if have_lidar:
            top, top_source = float(lidar), "dem"
    elif mode == "field":
        if t_top is not None:
            top, top_source = t_top, "field"
            if far:
                flags.append(f"{top_name} {fmt_ft(t_top)} ft is {abs(t_top - lidar):.1f} ft from LIDAR"
                             + _metric_hint(t_top, lidar, max_diff))
    else:                                              # field_then_dem
        if t_top is not None and not far:
            top, top_source = t_top, "field"
        elif have_lidar:
            top, top_source = float(lidar), "dem"
            if far:
                top_rejected = True
                flags.append(f"{top_name} {fmt_ft(t_top)} ft ignored: {abs(t_top - lidar):.1f} ft from LIDAR"
                             + _metric_hint(t_top, lidar, max_diff))
    if top is None:
        why = {"dem": "no LIDAR at the point", "field": f"no {top_name} value"}.get(
            mode, f"no {top_name} value and no LIDAR at the point")
        flags.append(f"no top elevation ({why})")

    # --- depth: used as positive; a depth of (about) 0 is no depth (it would draw a line of no length)
    if dep is not None and dep < 0:
        flags.append(f"{dep_name} {fmt_ft(dep)} ft is negative; used {fmt_ft(-dep)} ft")
        dep = -dep
    zero_depth = dep is not None and dep <= MIN_DEPTH_FT
    if zero_depth:
        dep = None

    # --- bottom
    bottom: Optional[float] = None
    bottom_source = "none"
    rejected = ""                                      # why the table bottom was not used ...
    ignored = ""                                       # ... or that it disagreed with top - depth
    if t_bot is not None and top is not None:
        by_depth = top - dep if dep is not None else None
        if top_rejected and dep is None and t_bot < t_top - MIN_DEPTH_FT:
            # below the rejected table top: the same wrong datum, so keep the table's own depth
            bottom, bottom_source = top - (t_top - t_bot), "shifted"
            flags.append(f"{bot_name} {fmt_ft(t_bot)} ft shifted with the top: {fmt_ft(bottom)} ft "
                         f"({fmt_ft(t_top - t_bot)} ft below it, as in the table)")
        elif t_bot >= top - MIN_DEPTH_FT:
            rejected = f"{bot_name} {fmt_ft(t_bot)} ft is not below the top ({fmt_ft(top)} ft)"
        elif (by_depth is not None and top_source != "field" and max_diff > 0
              and abs(t_bot - by_depth) > max_diff):
            # the top is not the table's, so the table bottom can't be trusted over LIDAR - depth
            ignored = (f"{bot_name} {fmt_ft(t_bot)} ft ignored: {abs(t_bot - by_depth):.1f} ft from top minus "
                       f"{dep_name} ({fmt_ft(by_depth)} ft)")
        else:
            bottom, bottom_source = t_bot, "field"
    if bottom is None and dep is not None and top is not None:
        bottom, bottom_source = top - dep, "depth"
    if ignored:
        flags.append(ignored)
    elif rejected:
        fallback = f"used top minus {dep_name}" if bottom_source == "depth" else "no top-to-bottom line"
        flags.append(f"{rejected}: {fallback}")
    elif bottom_source == "field" and dep is not None and abs(t_bot - (top - dep)) > BOTTOM_AGREE_FT:
        flags.append(f"{bot_name} {fmt_ft(t_bot)} ft used; top minus {dep_name} would give "
                     f"{fmt_ft(top - dep)} ft")
    elif (bottom is None and top is not None and settings.depth_line
          and (settings.bottom_elev_field or settings.depth_field)):
        # say why this one has no top-to-bottom line (without a top, the flag above already does)
        names = " and ".join(n for n in (settings.bottom_elev_field, settings.depth_field) if n)
        empty = "empty or 0" if zm or zero_depth else "empty"
        flags.append(f"no bottom elevation or depth ({names} {empty}): no top-to-bottom line")

    if dep is not None:
        total_depth: Optional[float] = dep
    elif top is not None and bottom is not None:
        total_depth = top - bottom
    else:
        total_depth = None
    return TopBottom(top, top_source, bottom, bottom_source, total_depth, flags)


class ScreenLevels(NamedTuple):
    screen_top: Optional[float]
    screen_bottom: Optional[float]
    levels: List[WaterLevel]
    flags: List[str]


def screen_and_levels(top: Optional[float], bottom: Optional[float], screen_a: Optional[float],
                      screen_b: Optional[float], levels: Sequence[Tuple[Optional[float], str, str, str]],
                      settings: Settings) -> ScreenLevels:
    """Screen and water levels of one exploration (decision 16). Pure: no QGIS objects.

    `top` / `bottom` are the exploration's (top_and_bottom); `screen_a` / `screen_b` the screen top and bottom
    attribute values (depths below the top, or elevations, as settings.screen_values says; either order);
    `levels` (value, kind, date, source) the water levels from the fields and the table: elevations, or depths
    below the top when settings.wl_values is "depth" (a negative depth is above the top). Zeros count
    as missing while settings.zero_is_missing. A screen or level entirely beyond the top or the bottom (by more
    than SCREEN_SLACK_FT) is left out and flagged: the value is most likely a depth read as an elevation or the
    other way round; a screen only partly beyond is drawn and flagged."""
    zm = settings.zero_is_missing
    flags: List[str] = []
    a, b = usable(screen_a, zm), usable(screen_b, zm)
    st = sb = None
    depths = settings.screen_values != "elevation"
    what = "depths below the top" if depths else "elevations"
    if a is not None and b is not None:
        if depths:
            if top is None:
                flags.append("screen depths given but no top elevation: no screen")
            else:
                a, b = abs(a), abs(b)
                st, sb = top - min(a, b), top - max(a, b)
        else:
            st, sb = max(a, b), min(a, b)
    elif a is not None or b is not None:
        given, missing = ("top", "bottom") if a is not None else ("bottom", "top")
        flags.append(f"screen {given} given without the {missing}: no screen")
    if st is not None:
        hi = top + SCREEN_SLACK_FT if top is not None else math.inf
        lo = bottom - SCREEN_SLACK_FT if bottom is not None else -math.inf
        if sb > hi or st < lo:
            where = "above the top" if sb > hi else "below the bottom"
            flags.append(f"screen {fmt_ft(st)} to {fmt_ft(sb)} ft is {where}: left out (screen values are read "
                         f"as {what})")
            st = sb = None
        elif st > hi:
            flags.append(f"screen top {fmt_ft(st)} ft is above the top ({fmt_ft(top)} ft)")
        elif sb < lo:
            flags.append(f"screen bottom {fmt_ft(sb)} ft is below the bottom ({fmt_ft(bottom)} ft)")
    out: List[WaterLevel] = []
    seen = set()
    wl_depths = settings.wl_values == "depth"
    read_as = f"(water levels are read as {'depths below the top' if wl_depths else 'elevations'})"
    for value, kind, date, source in levels:
        v = usable(value, zm)
        if v is None:
            continue
        name = "ATD water level" if kind == "atd" else "water level"
        given = f"{name} {fmt_ft(v)} ft"
        if wl_depths:                                   # a depth below the top (negative: above it)
            if top is None:
                flags.append(f"{given} is a depth but there is no top elevation: left out")
                continue
            v = top - v
            given = f"{name} at depth {fmt_ft(top - v)} ft ({fmt_ft(v)} ft)"
        if top is not None and v > top + WL_ABOVE_FT:
            flags.append(f"{given} is {v - top:.0f} ft above the top: left out {read_as}")
            continue
        if bottom is not None and v < bottom - SCREEN_SLACK_FT:
            flags.append(f"{given} is below the bottom ({fmt_ft(bottom)} ft): left out {read_as}")
            continue
        if bottom is None and top is not None and v < top - WL_BELOW_NO_BOTTOM_FT:
            flags.append(f"{given} is {top - v:.0f} ft below the top: left out {read_as}")
            continue
        key = (round(v, 3), kind, date)
        if key in seen:
            continue
        seen.add(key)
        out.append(WaterLevel(elev=v, kind=kind, date=date, source=source))
    out.sort(key=lambda w: (-w.elev, w.kind))
    return ScreenLevels(st, sb, out, flags)


def atd_kind(value: Any, settings: Settings) -> str:
    """"atd" or "measured" for a water-level table row's kind value: with no kind field every row is ATD; with
    one, the values in settings.wl_atd_values are ATD (none chosen: values containing "ATD")."""
    if not settings.wl_table_kind_field:
        return "atd"
    text = _text(value).strip()
    chosen = [str(v).strip() for v in (settings.wl_atd_values or []) if str(v).strip()]
    if chosen:
        return "atd" if text in chosen else "measured"
    return "atd" if "atd" in text.casefold() else "measured"


WlRows = Dict[str, List[Tuple[Optional[float], str, str, str]]]


def read_wl_table(settings: Settings, project: QgsProject) -> WlRows:
    """The water-level table as {name_key: [(elevation, kind, date, "table"), ...]}. SectionError when the table
    or one of its fields is gone."""
    layer = project.mapLayer(settings.wl_table_id) if settings.wl_table_id else None
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise SectionError("The water-level table is no longer in the project. Choose it again, or none.")
    name_i = _field_index(layer, settings.wl_table_name_field, "water-level table name")
    elev_i = _field_index(layer, settings.wl_table_elev_field, "water-level table elevation")
    if name_i < 0 or elev_i < 0:
        raise SectionError(f"Choose the name and elevation fields of the water-level table {layer.name()}.")
    date_i = _field_index(layer, settings.wl_table_date_field, "water-level table date")
    kind_i = _field_index(layer, settings.wl_table_kind_field, "water-level table kind")
    attrs = [i for i in (name_i, elev_i, date_i, kind_i) if i >= 0]
    req = QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry).setSubsetOfAttributes(attrs)
    rows: WlRows = {}
    for f in layer.getFeatures(req):
        key = name_key(f.attribute(name_i))
        if not key:
            continue
        kind = atd_kind(f.attribute(kind_i) if kind_i >= 0 else None, settings)
        date = date_text(f.attribute(date_i)) if date_i >= 0 else ""
        rows.setdefault(key, []).append((to_number(f.attribute(elev_i)), kind, date, "table"))
    return rows


def find_explorations(line: QgsGeometry, points_layer: QgsVectorLayer, settings: Settings,
                      crs: QgsCoordinateReferenceSystem, sampler: Callable[[np.ndarray, np.ndarray], np.ndarray],
                      dist_factor: float, project: QgsProject, ground: Optional[GroundProfile] = None,
                      wl_table: Optional[WlRows] = None) -> Tuple[List[Hit], List[str], int]:
    """(hits sorted by station, beyond_ends labels, near_count).

    `wl_table` (read_wl_table) adds water levels by exploration name (the label field's value).

    `ground` (optional) is the profile already sampled along `line`; it gives ground_at_station
    (so ticks sit on the drawn ground line) and the nearest valid ground in a gap. Without it a
    coarse profile is sampled here.
    """
    if points_layer is None or not isinstance(points_layer, QgsVectorLayer) or not points_layer.isValid():
        raise SectionError("Choose an explorations (points) layer.")
    if points_layer.geometryType() != Qgis.GeometryType.Point:
        raise SectionError(f"{points_layer.name()} is not a point layer. Choose the explorations points layer.")
    tol = float(settings.tolerance_ft)
    if not tol > 0:
        raise SectionError("The projection tolerance must be more than 0 ft.")
    near = NEAR_FACTOR * tol
    slack = 1e-9 * max(1.0, tol)

    label_i = _field_index(points_layer, settings.label_field, "label")
    type_i = _field_index(points_layer, settings.type_field, "type")
    top_i = _field_index(points_layer, settings.top_field, "top elevation") if settings.top_mode != "dem" else -1
    bot_i = _field_index(points_layer, settings.bottom_elev_field, "bottom elevation")
    dep_i = _field_index(points_layer, settings.depth_field, "total depth")
    scr = bool(settings.screens)
    sa_i = _field_index(points_layer, settings.screen_top_field, "screen top") if scr else -1
    sb_i = _field_index(points_layer, settings.screen_bottom_field, "screen bottom") if scr else -1
    wl_i = _field_index(points_layer, settings.wl_field, "water level") if scr else -1
    wld_i = _field_index(points_layer, settings.wl_date_field, "water level date") if scr else -1
    atd_i = _field_index(points_layer, settings.atd_field, "ATD water level") if scr else -1
    atdd_i = _field_index(points_layer, settings.atd_date_field, "ATD water level date") if scr else -1

    verts = line_vertices(line)
    seg_len = np.hypot(np.diff(verts[:, 0]), np.diff(verts[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])      # section CRS units
    nseg = len(seg_len)

    req = QgsFeatureRequest()
    req.setDestinationCrs(crs, project.transformContext())
    req.setFilterRect(line.boundingBox().buffered(near / dist_factor))
    expr = _type_filter(points_layer, type_i, settings.types)
    if expr:
        req.setFilterExpression(expr)

    cands = []            # (feature, point, foot, station_ft, offset_ft, leftOf, label)
    beyond: List[str] = []
    near_count = 0
    for f in points_layer.getFeatures(req):
        g = f.geometry()
        if g is None or g.isNull() or g.isEmpty():
            continue
        p = g.asMultiPoint()[0] if QgsWkbTypes.isMultiType(g.wkbType()) else g.asPoint()
        sqr, foot, after, left = line.closestSegmentWithContext(p)
        if sqr < 0:
            continue
        off_ft = math.sqrt(sqr) * dist_factor
        if off_ft > near + slack:
            continue
        seg = min(max(after - 1, 0), nseg - 1)
        ax, ay = verts[seg]
        bx, by = verts[seg + 1]
        L = seg_len[seg]
        along = ((p.x() - ax) * (bx - ax) + (p.y() - ay) * (by - ay)) / L if L > 0 else 0.0
        eps = 1e-9 * max(1.0, L)
        past_start = seg == 0 and along < -eps
        past_end = seg == nseg - 1 and along > L + eps
        label = _text(f.attribute(label_i)) if label_i >= 0 else ""
        label = label if label.strip() else f"#{f.id()}"
        if past_start or past_end:
            if off_ft <= tol + slack:
                beyond.append(label)
            continue
        if off_ft > tol + slack:
            near_count += 1
            continue
        station_ft = (cum[seg] + math.hypot(foot.x() - ax, foot.y() - ay)) * dist_factor
        cands.append((f, p, foot, station_ft, off_ft, left, label))

    if ground is None and cands:
        length_ft = float(cum[-1]) * dist_factor
        ground = ground_profile(line, sampler, max(length_ft / 5000.0, 1.0), dist_factor)

    hits: List[Hit] = []
    if cands:
        xs = np.array([c[1].x() for c in cands])
        ys = np.array([c[1].y() for c in cands])
        at_point = np.asarray(sampler(xs, ys), dtype=float)
        for (f, p, foot, station, off, left, label), zp in zip(cands, at_point):
            zp = float(zp) if math.isfinite(zp) else math.nan
            flags: List[str] = []
            gs = ground.z_at(station)
            in_gap = not math.isfinite(gs)
            if in_gap:
                gs = ground.nearest_valid(station)
                flags.append("station in a DEM gap")
            dx, dy = p.x() - foot.x(), p.y() - foot.y()
            direction = compass_point(azimuth_deg(dx, dy), 8) if off > 1e-6 else ""
            tb = top_and_bottom(_attr_number(f, top_i), zp, _attr_number(f, bot_i), _attr_number(f, dep_i),
                                settings)
            sl = ScreenLevels(None, None, [], [])
            if scr:
                levels = []
                if wl_i >= 0:
                    levels.append((_attr_number(f, wl_i), "measured",
                                   date_text(f.attribute(wld_i)) if wld_i >= 0 else "", settings.wl_field))
                if atd_i >= 0:
                    levels.append((_attr_number(f, atd_i), "atd",
                                   date_text(f.attribute(atdd_i)) if atdd_i >= 0 else "", settings.atd_field))
                if wl_table:
                    levels += wl_table.get(name_key(label), [])
                sl = screen_and_levels(tb.top, tb.bottom, _attr_number(f, sa_i), _attr_number(f, sb_i), levels,
                                       settings)
            hits.append(Hit(
                fid=int(f.id()), label=label,
                type_value=_text(f.attribute(type_i)) if type_i >= 0 else "",
                x=p.x(), y=p.y(), station=float(station), offset=float(off),
                side="R" if left > 0 else "L", direction=direction,
                ground_at_station=float(gs), ground_at_point=zp,
                top=tb.top, top_source=tb.top_source, bottom=tb.bottom, in_gap=in_gap,
                flags=flags + tb.flags + sl.flags, bottom_source=tb.bottom_source, total_depth=tb.total_depth,
                screen_top=sl.screen_top, screen_bottom=sl.screen_bottom, water_levels=sl.levels))
    hits.sort(key=lambda h: (h.station, h.label))
    return hits, beyond, near_count


def nearest_distance_ft(line: QgsGeometry, points_layer: QgsVectorLayer, settings: Settings,
                        crs: QgsCoordinateReferenceSystem, dist_factor: float, project: QgsProject,
                        limit: int = 100_000) -> float:
    """Feet from the line to the nearest exploration of the chosen types (inf if there is none; only
    the first `limit` features are read). Used to hint at a wrong layer CRS when none is near."""
    type_i = points_layer.fields().lookupField(settings.type_field) if settings.type_field else -1
    req = QgsFeatureRequest().setLimit(limit).setSubsetOfAttributes([type_i] if type_i >= 0 else [])
    req.setDestinationCrs(crs, project.transformContext())
    expr = _type_filter(points_layer, type_i, settings.types)
    if expr:
        req.setFilterExpression(expr)
    best = math.inf
    for f in points_layer.getFeatures(req):
        g = f.geometry()
        if g is not None and not g.isNull() and not g.isEmpty():
            best = min(best, line.distance(g))
    return best * dist_factor
