"""Other points on the section (seeps, springs ...): point features drawn as a symbol with a label (0.3.3); since
0.3.6 also line and polygon layers ("Other features").

The same selection as the explorations (explorations._project_points: the shared "within" distance, perpendicular
projection, flat end caps). Each row places its points (DESIGN.md decision 22):
- "line" (the default): on the ground line drawn at the point's station (render rests the symbol on it);
- "lidar": the LIDAR at the point's own location; no LIDAR there: on the ground line, flagged;
- "field": an elevation field (ft); where it is empty (or 0 while 0 counts as missing) the row's elev_empty says what
  to do: on the ground line, the LIDAR, or left out (its label is returned in the 4th value). A text field (0.3.5, a
  CSV's) is read where it holds a plain number (explorations.to_number); any other text is taken as empty, and a
  point still drawn is flagged.

A line row (0.3.6) draws its symbol only where the section line crosses one of its lines (find_crossings: each
crossing one point, offset 0, placed by the same rules); a polygon row marks each stretch of the section line inside
one of its polygons (find_area_pieces: drawn as a bracket).
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsProject,
                       QgsVectorLayer, QgsWkbTypes)

from .explorations import (_attr_number, _field_index, _project_points, _text, _type_filter, fmt_ft,
                           not_number_flag, not_number_text, usable)
from .model import (OTHER_POINT_DEFAULTS, AreaPiece, GroundProfile, OtherPoint, SectionError, Settings,
                    clean_other_point, feature_row)
from .section import azimuth_deg, compass_point, ground_profile, line_vertices, vertex_stations

GAP_FLAG = "station in a DEM gap"
NO_LIDAR_FLAG = "no LIDAR at the point: on the ground line"
MIN_PIECE_FT = 0.01         # a stretch shorter than this inside a polygon is a sliver: no piece
ALONG_FLAG = "runs along the section line for {n} ft"      # a line that shares a stretch with the section line
_SAME_FT = 1e-6             # two crossings of one feature closer than this are one
ALONG_TOL_FT = 1e-3         # a line whose segment ends are this close to the section line runs along it (snapped or
                            # reprojected vertices lie a rounding error off it); also: two crossings of one row with
                            # the same label this close are one (a stream split into two features at the line), and A
                            # or A′ this close to a polygon's edge is on the edge
ALONG_MIN_FT = 1.0          # a shared stretch shorter than this is an ordinary crossing (no flag: "0 ft" says nothing)

_KINDS = {Qgis.GeometryType.Point: "point", Qgis.GeometryType.Line: "line", Qgis.GeometryType.Polygon: "polygon"}


def feature_kind(layer) -> str:
    """"point" | "line" | "polygon" from a vector layer's geometry type; "" for anything else (a table, no layer)."""
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return ""
    return _KINDS.get(layer.geometryType(), "")


def feature_layer(layer_id: str, project: Optional[QgsProject] = None) -> Optional[QgsVectorLayer]:
    """The valid point, line or polygon layer of the project with this id, else None (the panel's resolver)."""
    project = project or QgsProject.instance()
    layer = project.mapLayer(layer_id) if layer_id else None
    return layer if feature_kind(layer) else None


def _coarse_ground(line: QgsGeometry, sampler: Callable, dist_factor: float,
                   ground: Optional[GroundProfile]) -> GroundProfile:
    """`ground` (the profile already sampled along the line), else a coarse one sampled here."""
    if ground is not None:
        return ground
    verts = line_vertices(line)
    cum = np.cumsum(np.hypot(np.diff(verts[:, 0]), np.diff(verts[:, 1])))
    return ground_profile(line, sampler, max(float(cum[-1]) * dist_factor / 5000.0, 1.0), dist_factor)


def _place(feature, station: float, lidar: float, row: dict, settings: Settings, ground: GroundProfile,
           elev_i: int, elev_text: bool
           ) -> Optional[Tuple[float, str, Optional[float], bool, bool, float, List[str]]]:
    """Where one point or crossing of a row goes: (z, how, field value, fell back, in a gap, ground at the station,
    flags), by the row's elev / elev_field / elev_empty (the module docstring) and the shared zero_is_missing and
    top_max_diff_ft; `lidar` is the LIDAR at the point (nan: none). None: left out (its field is empty and "Where it
    is empty" is Off)."""
    mode = row["elev"]
    has_lidar = math.isfinite(lidar)
    flags: List[str] = []
    gs = ground.z_at(station)
    in_gap = not math.isfinite(gs)
    if in_gap:
        gs = ground.nearest_valid(station)
        flags.append(GAP_FLAG)
    fv = usable(_attr_number(feature, elev_i), settings.zero_is_missing) if elev_i >= 0 else None
    max_diff = settings.top_max_diff_ft
    fell_back = False
    if mode == "lidar" or (mode == "field" and fv is None and row["elev_empty"] == "lidar"):
        fell_back = mode == "field"
        if has_lidar:
            z, how = lidar, "lidar"
        else:
            z, how, fell_back = gs, "line", True
            flags.append(NO_LIDAR_FLAG)
    elif mode == "field" and fv is not None:
        z, how = fv, "field"
        if has_lidar and max_diff > 0 and abs(fv - lidar) > max_diff:
            flags.append(f"{row['elev_field']} {fmt_ft(fv)} ft is {abs(fv - lidar):.1f} ft from LIDAR")
    elif mode == "field" and row["elev_empty"] == "off":
        return None
    else:                                          # the ground line (also an empty field with elev_empty "line")
        z, how, fell_back = gs, "line", mode == "field"
    if elev_text and fell_back:
        text = not_number_text(feature.attribute(elev_i))
        if text:
            flags.insert(1 if in_gap else 0, not_number_flag(
                row["elev_field"], text, "on the ground line" if how == "line" else "LIDAR at the point"))
    return float(z), how, fv if mode == "field" else None, fell_back, in_gap, float(gs), flags


def _elev_field(layer: QgsVectorLayer, row: dict) -> Tuple[int, bool]:
    """(index of the row's elevation field or -1, True when it is a text field: its non-numbers are flagged)."""
    elev_i = _field_index(layer, row["elev_field"], "elevation") if row["elev"] == "field" else -1
    return elev_i, elev_i >= 0 and not layer.fields().at(elev_i).isNumeric()


def find_other_points(line: QgsGeometry, layer: QgsVectorLayer, row: dict, settings: Settings,
                      crs: QgsCoordinateReferenceSystem, sampler: Callable[[np.ndarray, np.ndarray], np.ndarray],
                      dist_factor: float, project: QgsProject, ground: Optional[GroundProfile]
                      ) -> Tuple[List[OtherPoint], List[str], int, List[str]]:
    """(points sorted by (station, label), beyond-the-ends labels, near count, labels left out for want of an
    elevation) of one other-points row (OTHER_POINT_DEFAULTS keys). Shared rules from `settings`: tolerance_ft,
    zero_is_missing and top_max_diff_ft (an elevation field value further than that from LIDAR is flagged, kept).
    SectionError for a missing label, type or elevation field."""
    row = clean_other_point(row) or dict(OTHER_POINT_DEFAULTS)
    cands, beyond, near, type_i = _project_points(line, layer, row["label_field"], row["type_field"], row["types"],
                                                  settings.tolerance_ft, crs, dist_factor, project,
                                                  what="other (points)")
    elev_i, elev_text = _elev_field(layer, row)
    if not cands:
        return [], beyond, near, []
    ground = _coarse_ground(line, sampler, dist_factor, ground)
    xs = np.array([c.point.x() for c in cands])
    ys = np.array([c.point.y() for c in cands])
    at_point = np.asarray(sampler(xs, ys), dtype=float)
    out: List[OtherPoint] = []
    no_elevation: List[str] = []
    for c, zp in zip(cands, at_point):
        lidar = float(zp) if math.isfinite(zp) else math.nan
        placed = _place(c.feature, c.station, lidar, row, settings, ground, elev_i, elev_text)
        if placed is None:
            no_elevation.append(c.label)
            continue
        z, how, fv, fell_back, in_gap, gs, flags = placed
        dx, dy = c.foot.x() - c.point.x(), c.foot.y() - c.point.y()     # (0.3.5) projected onto the line, as a Hit
        out.append(OtherPoint(
            fid=int(c.feature.id()), label=c.label,
            type_value=_text(c.feature.attribute(type_i)) if type_i >= 0 else "",
            x=c.point.x(), y=c.point.y(), station=float(c.station), offset=float(c.offset),
            side="R" if c.left > 0 else "L",
            direction=compass_point(azimuth_deg(dx, dy), 8) if c.offset > 1e-6 else "",
            ground_at_station=gs, ground_at_point=lidar, z=z, how=how,
            field_value=fv, fell_back=fell_back, in_gap=in_gap, flags=flags))
    out.sort(key=lambda p: (p.station, p.label))
    return out, beyond, near, no_elevation


# ----------------------------------------------------------------------------- line and polygon rows (0.3.6)
def _features_on_line(line: QgsGeometry, layer: QgsVectorLayer, kind: str, type_i: int, types: List[str],
                      crs: QgsCoordinateReferenceSystem, dist_factor: float, project: QgsProject, near: float = 0.0):
    """(feature, its geometry in the section CRS, straight-segmented) for every feature of the ticked types that
    touches the section line (`near` > 0: comes within that many ft of it). Only features in the line's box
    (buffered by 1 ft: a straight east-west line has a box of no height) are read, and a prepared engine of the line
    (of its `near` buffer) rejects those that do not touch it before any intersection is made."""
    if feature_kind(layer) != kind:
        raise SectionError(f"{layer.name() if isinstance(layer, QgsVectorLayer) else 'The layer'} is not a {kind} "
                           "layer.")
    req = QgsFeatureRequest()
    req.setDestinationCrs(crs, project.transformContext())
    req.setFilterRect(line.boundingBox().buffered(1.0 / dist_factor))
    expr = _type_filter(layer, type_i, types)
    if expr:
        req.setFilterExpression(expr)
    test = line.buffer(near / dist_factor, 1) if near > 0 else line
    engine = QgsGeometry.createGeometryEngine(test.constGet())
    engine.prepareGeometry()
    for f in layer.getFeatures(req):
        g = f.geometry()
        if g is None or g.isNull() or g.isEmpty():
            continue
        if QgsWkbTypes.isCurvedType(g.wkbType()):
            g.convertToStraightSegment()
        if not engine.intersects(g.constGet()):
            continue
        yield f, g


def _parts(geom: QgsGeometry) -> List[QgsGeometry]:
    """The non-empty single parts of an intersection (a point, a line, or a collection of them)."""
    if geom is None or geom.isNull() or geom.isEmpty():
        return []
    return [g for g in geom.asGeometryCollection() if not g.isNull() and not g.isEmpty()]


def _merged(intervals: List[Tuple[float, float]], gap: float) -> List[Tuple[float, float]]:
    """Station intervals sorted and merged where they touch or overlap (within `gap`)."""
    out: List[List[float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _along(line: QgsGeometry, geom: QgsGeometry, dist_factor: float, tol_ft: float) -> List[Tuple[float, float]]:
    """Station intervals (ft) where a segment of the line geometry `geom` runs along a segment of the section line:
    both its ends within `tol_ft` of that segment's line, the part between them that lies over the segment. (GEOS
    finds a shared stretch only when the two are exactly collinear; vertices snapped onto the section line, or
    reprojected, are a rounding error off it, and GEOS then gives one crossing point somewhere along the stretch.)"""
    verts = line_vertices(line)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(verts[:, 0]), np.diff(verts[:, 1])))])
    tol = tol_ft / dist_factor
    parts = geom.asMultiPolyline() if QgsWkbTypes.isMultiType(geom.wkbType()) else [geom.asPolyline()]
    out: List[Tuple[float, float]] = []
    for pl in parts:
        if len(pl) < 2:
            continue
        xy = np.array([(p.x(), p.y()) for p in pl], dtype=float)
        for i in range(len(verts) - 1):
            seg = verts[i + 1] - verts[i]
            L = float(np.hypot(seg[0], seg[1]))
            if not L > 0:
                continue
            u = seg / L
            rel = xy - verts[i]
            near = np.abs(rel[:, 0] * u[1] - rel[:, 1] * u[0]) <= tol
            both = near[:-1] & near[1:]
            if not both.any():
                continue
            t = rel @ u
            lo = np.clip(np.minimum(t[:-1], t[1:])[both], 0.0, L)
            hi = np.clip(np.maximum(t[:-1], t[1:])[both], 0.0, L)
            out += [((cum[i] + a) * dist_factor, (cum[i] + b) * dist_factor) for a, b in zip(lo, hi) if b > a]
    return out


def _stretches(line: QgsGeometry, geom: QgsGeometry, dist_factor: float, length: float,
               along_ft: float = 0.0) -> Tuple[List[Tuple[float, QgsPointXY]], List[Tuple[float, float]]]:
    """((station, point) of each point, merged station intervals of the line parts) of the section line's
    intersection with `geom`; stations in ft, clamped to [0, length]. (GEOS may split a shared stretch where either
    line has a vertex: the touching parts are merged.) `along_ft` > 0 (a line row): the stretches where `geom` runs
    along the section line within that many ft count too (_along), and a point inside one is dropped."""
    points: List[Tuple[float, QgsPointXY]] = []
    lines: List[Tuple[float, float]] = []

    def at(pt) -> float:
        return min(max(line.lineLocatePoint(QgsGeometry.fromPointXY(pt)) * dist_factor, 0.0), length)
    for part in _parts(line.intersection(geom)):
        gtype = QgsWkbTypes.geometryType(part.wkbType())
        if gtype == Qgis.GeometryType.Point:
            pt = part.asPoint()
            points.append((at(pt), pt))
        elif gtype == Qgis.GeometryType.Line:
            pl = part.asPolyline()
            if len(pl) >= 2:
                a, b = at(pl[0]), at(pl[-1])
                lines.append((min(a, b), max(a, b)))
    if along_ft > 0:
        lines += [(min(a, length), min(b, length)) for a, b in _along(line, geom, dist_factor, along_ft)]
    stretches = _merged(lines, max(1e-6 * max(1.0, length), along_ft))
    if along_ft > 0 and stretches:
        points = [(st, pt) for st, pt in points
                  if not any(a - along_ft <= st <= b + along_ft for a, b in stretches)]
    return points, stretches


def find_crossings(line: QgsGeometry, layer: QgsVectorLayer, row: dict, settings: Settings,
                   crs: QgsCoordinateReferenceSystem, sampler: Callable[[np.ndarray, np.ndarray], np.ndarray],
                   dist_factor: float, project: QgsProject, ground: Optional[GroundProfile]
                   ) -> Tuple[List[OtherPoint], List[str]]:
    """(crossings sorted by (station, label), labels left out for want of an elevation) of a line row: one OtherPoint
    (kind "crossing") wherever the section line crosses or touches a line of the layer (each crossing its own, a line
    crossing twice gives two). SectionError for a missing label, type or elevation field (as points)."""
    row = clean_other_point(row) or feature_row("line")
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise SectionError("Choose a line layer.")
    label_i = _field_index(layer, row["label_field"], "label")
    type_i = _field_index(layer, row["type_field"], "type")
    elev_i, elev_text = _elev_field(layer, row)
    length = vertex_stations(line, dist_factor)[-1]           # the model length (build_section)
    found = []                                 # (feature, station, x, y, label, flags)
    for f, g in _features_on_line(line, layer, "line", type_i, row["types"], crs, dist_factor, project,
                                  near=ALONG_TOL_FT):
        label = _text(f.attribute(label_i)) if label_i >= 0 else ""
        label = label if label.strip() else f"#{f.id()}"
        points, stretches = _stretches(line, g, dist_factor, length, along_ft=ALONG_TOL_FT)
        spots = [(st, pt, []) for st, pt in points]
        for a, b in stretches:                 # a shared stretch: one crossing at its middle, flagged (a stretch
            mid = (a + b) / 2.0                # shorter than ALONG_MIN_FT, a rounding error, is a plain crossing)
            spots.append((mid, line.interpolate(mid / dist_factor).asPoint(),
                          [ALONG_FLAG.format(n=f"{round(b - a):,}")] if b - a >= ALONG_MIN_FT else []))
        spots.sort(key=lambda t: t[0])
        last = -math.inf
        for st, pt, flags in spots:
            if st - last < _SAME_FT:
                continue
            last = st
            found.append((f, st, pt.x(), pt.y(), label, flags))
    if not found:
        return [], []
    found = _one_per_crossing(found)
    ground = _coarse_ground(line, sampler, dist_factor, ground)
    at_point = np.asarray(sampler(np.array([c[2] for c in found]), np.array([c[3] for c in found])), dtype=float)
    out: List[OtherPoint] = []
    no_elevation: List[str] = []
    for (f, st, x, y, label, along), zp in zip(found, at_point):
        lidar = float(zp) if math.isfinite(zp) else math.nan
        placed = _place(f, st, lidar, row, settings, ground, elev_i, elev_text)
        if placed is None:
            no_elevation.append(label)
            continue
        z, how, fv, fell_back, in_gap, gs, flags = placed
        out.append(OtherPoint(
            fid=int(f.id()), label=label, type_value=_text(f.attribute(type_i)) if type_i >= 0 else "",
            x=x, y=y, station=float(st), offset=0.0, side="", direction="", ground_at_station=gs,
            ground_at_point=lidar, z=z, how=how, field_value=fv, fell_back=fell_back, in_gap=in_gap,
            flags=along + flags, kind="crossing"))
    out.sort(key=lambda p: (p.station, p.label))
    return out, no_elevation


def _one_per_crossing(found: list) -> list:
    """`found` (feature, station, x, y, label, flags) in station order, less each crossing within ALONG_TOL_FT of one
    already kept with the same label: one stream digitised as two features that meet ON the section line (flowlines
    are split at confluences, culverts, road crossings) is one crossing, the first of them (with the flags of both).
    Streams of other names meeting there keep their own."""
    kept: list = []
    for c in sorted(found, key=lambda c: c[1]):
        same = None
        for k in reversed(kept):
            if c[1] - k[1] > ALONG_TOL_FT:
                break
            if k[4] == c[4]:
                same = k
                break
        if same is None:
            kept.append(c)
        else:
            same[5].extend(fl for fl in c[5] if fl not in same[5])
    return kept


def _strictly_inside(g: QgsGeometry, pt: QgsGeometry, tol: float) -> bool:
    """True when the point `pt` lies inside the polygon `g` and farther than `tol` (map units) from its boundary: A or
    A′ on a polygon's edge (a parcel snapped to it, then reprojected a rounding error in or out) is a closed end."""
    if not g.contains(pt):
        return False
    edge = g.constGet().boundary()
    return edge is None or QgsGeometry(edge).distance(pt) > tol


def find_area_pieces(line: QgsGeometry, layer: QgsVectorLayer, row: dict, crs: QgsCoordinateReferenceSystem,
                     dist_factor: float, project: QgsProject) -> List[AreaPiece]:
    """The stretches of the section line inside each polygon of a polygon row, sorted by (start, label). SectionError
    for a missing label or type field."""
    row = clean_other_point(row) or feature_row("polygon")
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise SectionError("Choose a polygon layer.")
    label_i = _field_index(layer, row["label_field"], "label")
    type_i = _field_index(layer, row["type_field"], "type")
    length = vertex_stations(line, dist_factor)[-1]           # the model length (build_section)
    verts = line_vertices(line)
    a_pt, b_pt = (QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))) for x, y in (verts[0], verts[-1]))
    tol = ALONG_TOL_FT / dist_factor
    out: List[AreaPiece] = []
    for f, g in _features_on_line(line, layer, "polygon", type_i, row["types"], crs, dist_factor, project):
        if not g.isGeosValid():
            g = g.makeValid()
        _points, stretches = _stretches(line, g, dist_factor, length)
        label = (_text(f.attribute(label_i)) if label_i >= 0 else "").strip()
        type_value = _text(f.attribute(type_i)) if type_i >= 0 else ""
        for a, b in stretches:
            if b - a < MIN_PIECE_FT:
                continue
            at_a, at_b = a <= _SAME_FT, b >= length - _SAME_FT     # a piece from A or to A′ (open or not) ends there
            out.append(AreaPiece(fid=int(f.id()), label=label, type_value=type_value,
                                 start=0.0 if at_a else float(a), end=float(length) if at_b else float(b),
                                 open_start=at_a and _strictly_inside(g, a_pt, tol),
                                 open_end=at_b and _strictly_inside(g, b_pt, tol)))
    out.sort(key=lambda p: (p.start, p.label))
    return out
