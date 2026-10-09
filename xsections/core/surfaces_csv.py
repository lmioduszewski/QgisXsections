"""The ground and the other surfaces as a CSV (the preview's Surfaces CSV… button): x = distance along the section,
y = elevation, both in feet; optionally the map x, y of each distance (section CRS).

Two layouts:
- long: one row per drawn vertex, every line in drawing order (the ground first). A cells-mode step is two rows at
  the same distance; a vertex without data is a row with a blank part and a blank elevation, and the line's `part`
  (its unbroken run, from 1) counts up after it.
- wide: the top row labels the columns (distance_ft, then one column per line); one row every `step_ft` from 0, at
  each bend and at the end, every value read off the drawn line (hover.z_on); blank where a line has no value.

Numbers as the explorations CSV writes them: distances and elevations to 2 decimals, map x, y to 3. Not written:
the explorations, the dotted links across DEM gaps and the water-table marks (decoration, not data).
"""
from __future__ import annotations

import csv
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from qgis.core import QgsGeometry

from .hover import HoverLine, hover_lines, z_on_array
from .model import SectionModel
from .section import _stations_xy, line_vertices

LONG_COLUMNS = ["surface", "part", "distance_ft", "elevation_ft"]
MAP_COLUMNS = ["map_x", "map_y"]
LAYOUTS = ("long", "wide")


def unique_names(names: Iterable[str]) -> List[str]:
    """The names with repeats told apart: "Model top", "Model top (2)", "Model top (3)" (never one taken twice)."""
    used, out = set(), []
    for name in names:
        cand, k = name, 1
        while cand in used:
            k += 1
            cand = f"{name} ({k})"
        used.add(cand)
        out.append(cand)
    return out


def _num(v: float, nd: int = 2):
    """Rounded for the file (as the explorations CSV); "" without a value; never -0.0."""
    if v is None or not math.isfinite(v):
        return ""
    return round(float(v), nd) + 0.0


def _nums(values: np.ndarray, nd: int = 2) -> list:
    return [_num(v, nd) for v in values.tolist()]


def _chosen(lines: Sequence[HoverLine], include: Optional[Iterable[int]]) -> List[int]:
    """Indices of the lines to write, in drawing order (`include`: indices into hover_lines; None = all; any out of
    range are skipped)."""
    if include is None:
        return list(range(len(lines)))
    return sorted({int(i) for i in include if 0 <= int(i) < len(lines)})


class MapXY:
    """Map x, y (section CRS) of distances along the model's line (as core.section places DEM samples); blank when
    the model has no line to read. (Also the preview popup's footer.)"""

    def __init__(self, model: SectionModel):
        self.v: Optional[np.ndarray] = None
        self.f = float(model.dist_factor or 1.0)
        geom = QgsGeometry.fromWkt(model.line_wkt) if getattr(model, "line_wkt", "") else None
        if geom is not None and not geom.isNull() and not geom.isEmpty():
            v = line_vertices(geom)
            if len(v) >= 2:
                self.v = v
                self.cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(v[:, 0]), np.diff(v[:, 1])))])

    def at(self, station: float) -> Optional[Tuple[float, float]]:
        """(x, y) of one distance (ft) along the line; None without a line or a distance."""
        if self.v is None or station is None or not math.isfinite(station):
            return None
        x, y = _stations_xy(self.v, self.cum, np.array([float(station)]), self.f)
        return float(x[0]), float(y[0])

    def columns(self, stations: np.ndarray) -> List[list]:
        """[map_x, map_y] of each station, rounded to 3 decimals (blank without a line)."""
        if self.v is None or stations.size == 0:
            return [["", ""] for _ in range(stations.size)]
        x, y = _stations_xy(self.v, self.cum, stations, self.f)
        return [list(p) for p in zip(_nums(x, 3), _nums(y, 3))]


def surface_rows_long(model: SectionModel, include: Optional[Iterable[int]] = None,
                      map_xy: bool = False) -> Tuple[List[str], List[list]]:
    """(header, rows) of the long layout: every drawn vertex of each chosen line, the ground first."""
    lines = hover_lines(model)
    names = unique_names(ln.name for ln in lines)
    xy = MapXY(model) if map_xy else None
    rows: List[list] = []
    for i in _chosen(lines, include):
        st, z = lines[i].stations, lines[i].z
        if st.size == 0:
            continue
        ok = np.isfinite(z)
        starts = ok & ~np.concatenate([[False], ok[:-1]])        # the first vertex of each unbroken run
        parts = [int(p) if o else "" for o, p in zip(ok.tolist(), np.cumsum(starts).tolist())]
        dist, elev = _nums(st), _nums(z)
        extra = xy.columns(st) if xy is not None else None
        for k in range(st.size):
            row = [names[i], parts[k], dist[k], elev[k]]
            if extra is not None:
                row += extra[k]
            rows.append(row)
    return LONG_COLUMNS + (MAP_COLUMNS if map_xy else []), rows


def wide_stations(model: SectionModel, step_ft: float) -> np.ndarray:
    """The distances of the wide layout: every `step_ft` from 0, each vertex of the line (the bends) and the end,
    one per 0.01 ft (where a regular distance and a vertex round alike, the vertex is kept), ascending."""
    step = float(step_ft)
    if not math.isfinite(step) or step <= 0:
        raise ValueError(f"step_ft must be a positive number of feet, not {step_ft!r}")
    length = float(model.length)
    by_key: Dict[float, float] = {}
    for s in np.arange(0.0, length, step).tolist():
        by_key.setdefault(round(s, 2), s)
    for s in list(model.vertex_stations) + [0.0, length]:   # exact stations win
        if 0.0 <= s <= length:
            by_key[round(float(s), 2)] = float(s)
    return np.asarray([by_key[k] for k in sorted(by_key)], float)


def surface_rows_wide(model: SectionModel, step_ft: float = 10.0, include: Optional[Iterable[int]] = None,
                      map_xy: bool = False) -> Tuple[List[str], List[list]]:
    """(header, rows) of the wide layout: distance_ft, then one column per chosen line (drawing order) read at
    wide_stations()."""
    lines = hover_lines(model)
    names = unique_names(ln.name for ln in lines)
    chosen = _chosen(lines, include)
    grid = wide_stations(model, step_ft)
    cols = [_nums(z_on_array(lines[i].stations, lines[i].z, grid)) for i in chosen]
    extra = MapXY(model).columns(grid) if map_xy else None
    dist = [round(s, 2) + 0.0 for s in grid.tolist()]
    rows: List[list] = []
    for k in range(grid.size):
        row = [dist[k]] + [c[k] for c in cols]
        if extra is not None:
            row += extra[k]
        rows.append(row)
    return ["distance_ft"] + [names[i] for i in chosen] + (MAP_COLUMNS if map_xy else []), rows


def write_surfaces_csv(path: str, model: SectionModel, layout: str = "long", step_ft: float = 10.0,
                       include: Optional[Iterable[int]] = None, map_xy: bool = False) -> int:
    """Write the CSV (UTF-8 with a byte order mark, so Excel reads the names right). Returns the rows written,
    not counting the header. OSError (e.g. the file is open in Excel) is left to the caller."""
    if layout == "long":
        header, rows = surface_rows_long(model, include, map_xy)
    elif layout == "wide":
        header, rows = surface_rows_wide(model, step_ft, include, map_xy)
    else:
        raise ValueError(f"layout must be one of {LAYOUTS}, not {layout!r}")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)
