"""Other points on the section (seeps, springs ...): point features drawn as a symbol with a label (0.3.3).

The same selection as the explorations (explorations._project_points: the shared "within" distance, perpendicular
projection, flat end caps). Each row places its points (DESIGN.md decision 22):
- "line" (the default): on the ground line drawn at the point's station (render rests the symbol on it);
- "lidar": the LIDAR at the point's own location; no LIDAR there: on the ground line, flagged;
- "field": an elevation field (ft); where it is empty (or 0 while 0 counts as missing) the row's elev_empty says what
  to do: on the ground line, the LIDAR, or left out (its label is returned in the 4th value). A text field (0.3.5, a
  CSV's) is read where it holds a plain number (explorations.to_number); any other text is taken as empty, and a
  point still drawn is flagged.
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

import numpy as np
from qgis.core import QgsCoordinateReferenceSystem, QgsGeometry, QgsProject, QgsVectorLayer

from .explorations import (_attr_number, _field_index, _project_points, _text, fmt_ft, not_number_flag,
                           not_number_text, usable)
from .model import OTHER_POINT_DEFAULTS, GroundProfile, OtherPoint, Settings, clean_other_point
from .section import azimuth_deg, compass_point, ground_profile, line_vertices

GAP_FLAG = "station in a DEM gap"
NO_LIDAR_FLAG = "no LIDAR at the point: on the ground line"


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
    mode = row["elev"]
    elev_i = _field_index(layer, row["elev_field"], "elevation") if mode == "field" else -1
    elev_text = elev_i >= 0 and not layer.fields().at(elev_i).isNumeric()     # a text field: flag non-numbers
    if not cands:
        return [], beyond, near, []
    if ground is None:
        verts = line_vertices(line)
        cum = np.cumsum(np.hypot(np.diff(verts[:, 0]), np.diff(verts[:, 1])))
        ground = ground_profile(line, sampler, max(float(cum[-1]) * dist_factor / 5000.0, 1.0), dist_factor)
    zm = settings.zero_is_missing
    max_diff = settings.top_max_diff_ft
    xs = np.array([c.point.x() for c in cands])
    ys = np.array([c.point.y() for c in cands])
    at_point = np.asarray(sampler(xs, ys), dtype=float)
    out: List[OtherPoint] = []
    no_elevation: List[str] = []
    for c, zp in zip(cands, at_point):
        lidar = float(zp) if math.isfinite(zp) else math.nan
        has_lidar = math.isfinite(lidar)
        flags: List[str] = []
        gs = ground.z_at(c.station)
        in_gap = not math.isfinite(gs)
        if in_gap:
            gs = ground.nearest_valid(c.station)
            flags.append(GAP_FLAG)
        fv = usable(_attr_number(c.feature, elev_i), zm) if elev_i >= 0 else None
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
            no_elevation.append(c.label)
            continue
        else:                                          # the ground line (also an empty field with elev_empty "line")
            z, how, fell_back = gs, "line", mode == "field"
        if elev_text and fell_back:
            text = not_number_text(c.feature.attribute(elev_i))
            if text:
                flags.insert(1 if in_gap else 0, not_number_flag(
                    row["elev_field"], text, "on the ground line" if how == "line" else "LIDAR at the point"))
        dx, dy = c.foot.x() - c.point.x(), c.foot.y() - c.point.y()     # (0.3.5) projected onto the line, as a Hit
        out.append(OtherPoint(
            fid=int(c.feature.id()), label=c.label,
            type_value=_text(c.feature.attribute(type_i)) if type_i >= 0 else "",
            x=c.point.x(), y=c.point.y(), station=float(c.station), offset=float(c.offset),
            side="R" if c.left > 0 else "L",
            direction=compass_point(azimuth_deg(dx, dy), 8) if c.offset > 1e-6 else "",
            ground_at_station=float(gs), ground_at_point=lidar, z=float(z), how=how,
            field_value=fv if mode == "field" else None, fell_back=fell_back, in_gap=in_gap, flags=flags))
    out.sort(key=lambda p: (p.station, p.label))
    return out, beyond, near, no_elevation
