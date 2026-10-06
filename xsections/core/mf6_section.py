"""MODFLOW 6 grids along a section line (DESIGN.md decision 19): exact cell intervals and model surfaces.

- section_grid(grid, model_crs, section_crs) -> SectionGrid: the grid's cell rings in the section CRS (vertices
  transformed once, per-cell bounding boxes and edges as numpy arrays), cached per grid and CRS pair.
- cell_path(sgrid, line, dist_factor) -> CellPath: the stretches of the section line inside each cell, as sorted
  pieces (station_start_ft, station_end_ft, cells covering the piece). Exact: per line segment the cells are
  prefiltered by bounding box, each ring vertex is classed once by its signed distance from the segment (a vertex
  within a hair of the line is on it, the same decision in every cell sharing it), the segment is cut where a ring
  edge changes side and at every vertex on it, and a cut piece is kept when its midpoint, nudged a hair to the left
  of the segment, is inside the ring (right for non-convex cells; a stretch along a shared edge goes to the cell on
  its left, so to exactly one cell even on rotated grids). Stretches inside no cell are gaps. Cached per line.
- choose(path, values, var, grid) -> (s0, s1, v, cells): one value per piece. Where DISU nodes overlap (several
  node layers), "top" takes the higher top, "botm" the lower bottom, "head" the node with the highest top that has a
  head and "wt" the highest wet node.
- model_profile(s0, s1, v, mode, length) -> (stations, z, coverage): "cells" (flat across each cell, a vertical step
  at each cell edge) or "smooth" (straight lines through the cells' midpoints, the first and last value held flat to
  the outer edge; a cell without a value breaks the line).
- model_surface(d, project, line, crs, dist_factor, length, warnings) -> SurfaceProfile | None: one
  Settings.surfaces entry with source "mf6", as build.build_surfaces draws it; a surface that can't be drawn is left
  out with a warning (never an error).

The model values come from mf6.surface_array (fresh per-cell arrays, inactive cells masked; "top" is the top of the
uppermost active cell of each column, "head" is masked in dry cells, NEWTON ones included, "wt" the head of the
uppermost wet layer). Everything here is in feet along the line (section CRS distance x dist_factor), elevations in
feet.

Caches: begin_build() starts a build; entries a build uses are never evicted during it (a section with more models
than the limits still hits on every rebuild), older ones are evicted past the limits, and entries of an older
version of a grid or head file (a model run again) are dropped as soon as the new version is used.
"""
from __future__ import annotations

import math
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException, QgsGeometry,
                       QgsLineString, QgsPointXY, QgsProject)

from . import mf6
from .mf6 import Grid, HeadFile, MF6Error, find_model, read_grid, surface_array
from .model import SurfaceProfile
from .section import _crs_from_text, _steps, line_vertices
from .units import _Z_UNITS, _unit_code, _unit_factor

_Z_NAMES = {"ft": "feet", "ftUS": "US survey feet", "m": "meters", "cm": "centimeters"}
_CACHE_MAX = {"grid": 4, "path": 16, "values": 24}     # entries kept from earlier builds (a build keeps all it uses)
_CHUNK = 16                                             # line segments prefiltered together
_GEO_CACHE: "OrderedDict[tuple, list]" = OrderedDict()      # key -> [SectionGrid, generation last used]
_PATH_CACHE: "OrderedDict[tuple, list]" = OrderedDict()     # key -> [CellPath, generation]
_VALUES_CACHE: "OrderedDict[tuple, list]" = OrderedDict()   # key -> [read-only array, generation]
_GENERATION = [0]
STATS = {"transforms": 0, "paths": 0, "values": 0}      # cache misses (work done), for tests and timing


def begin_build() -> None:
    """Start a section build: what it uses stays cached until it is done (here and in mf6's file caches)."""
    _GENERATION[0] += 1
    mf6.new_generation()


def _get(cache: OrderedDict, key):
    hit = cache.get(key)
    if hit is None:
        return None
    cache.move_to_end(key)
    hit[1] = _GENERATION[0]
    return hit[0]


def _put(cache: OrderedDict, key, value, limit: int):
    cache[key] = [value, _GENERATION[0]]
    cache.move_to_end(key)
    while len(cache) > limit:                  # least recently used first; none used in this build (all after the
        first = next(iter(cache))              # first such entry are newer still)
        if cache[first][1] == _GENERATION[0]:
            break
        del cache[first]
    return value


def _drop_stale(grid: Optional[Grid] = None, head: Optional[HeadFile] = None) -> None:
    """Forget entries of an older version of `grid`'s or `head`'s file (the same path, another object): they can't
    be hit again and would keep the old arrays alive."""
    def old(obj, new):
        return obj is not None and new is not None and obj is not new and getattr(obj, "path", None) == new.path

    for k in [k for k in _GEO_CACHE if old(k[0], grid)]:
        del _GEO_CACHE[k]
    for k in [k for k in _PATH_CACHE if old(k[0].grid, grid)]:
        del _PATH_CACHE[k]
    for k in [k for k in _VALUES_CACHE if old(k[0], grid) or old(k[1], head)]:
        del _VALUES_CACHE[k]


def clear_cache() -> None:
    """Forget the transformed grids, line paths and cell values (mf6.clear_cache() forgets the files)."""
    _GEO_CACHE.clear()
    _PATH_CACHE.clear()
    _VALUES_CACHE.clear()


def _crs_key(crs: Optional[QgsCoordinateReferenceSystem]) -> str:
    return crs.toWkt() if crs is not None and crs.isValid() else ""


# ================================================================================================ the grid in the section CRS
@dataclass(eq=False)
class SectionGrid:
    """A grid's cell rings in the section CRS. Cell i's ring is x/y[ea[offsets[i]:offsets[i + 1]]]; edge p runs
    from vertex ea[p] to vertex eb[p]."""
    grid: Grid
    x: np.ndarray                       # (nvert,) vertices in the section CRS (nan where the transform failed)
    y: np.ndarray
    offsets: np.ndarray                 # (ncpl + 1,) ring offsets
    ea: np.ndarray                      # (offsets[-1],) start vertex of every edge
    eb: np.ndarray                      # end vertex
    bounds: np.ndarray                  # (ncpl, 4) xmin, ymin, xmax, ymax in the section CRS
    transformed: bool                   # False: the model CRS is the section CRS


def _transform_xy(ct: QgsCoordinateTransform, xy: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Many points through one transform: as one line string (done in C++), read back from its WKB; point by point
    (nan where a point fails) if the whole set can't be transformed."""
    n = len(xy)
    try:
        ls = QgsLineString(xy[:, 0].tolist(), xy[:, 1].tolist())
        ls.transform(ct)
        wkb = bytes(ls.asWkb())
        if (len(wkb) >= 9 + 16 * n and wkb[0] == 1 and int.from_bytes(wkb[1:5], "little") == 2
                and int.from_bytes(wkb[5:9], "little") == n):
            a = np.frombuffer(wkb, dtype="<f8", count=2 * n, offset=9).reshape(n, 2)
        else:
            a = np.array([(p.x(), p.y()) for p in ls.points()], dtype=float).reshape(n, 2)
        x, y = a[:, 0].copy(), a[:, 1].copy()
    except QgsCsException:
        x, y = np.full(n, np.nan), np.full(n, np.nan)
        for i in range(n):
            try:
                p = ct.transform(QgsPointXY(float(xy[i, 0]), float(xy[i, 1])))
            except QgsCsException:
                continue
            x[i], y[i] = p.x(), p.y()
    bad = ~(np.isfinite(x) & np.isfinite(y))
    x[bad] = np.nan
    y[bad] = np.nan
    return x, y


def section_grid(grid: Grid, model_crs: Optional[QgsCoordinateReferenceSystem],
                 section_crs: Optional[QgsCoordinateReferenceSystem], context=None) -> SectionGrid:
    """The grid's rings in the section CRS (its vertices transformed once from the model CRS, cached per grid and
    CRS pair). No transform when either CRS is missing or they are the same. MF6Error for a grid without cell
    vertices (a DISU without VERTICES and CELL2D)."""
    key = (grid, _crs_key(model_crs), _crs_key(section_crs))
    hit = _get(_GEO_CACHE, key)
    if hit is not None:
        return hit
    if not grid.has_vertices:
        raise MF6Error(f"{os.path.basename(grid.path)}: the grid has no cell vertices (a DISU without VERTICES and "
                       "CELL2D), so it can't be drawn along a section.")
    _drop_stale(grid=grid)
    STATS["transforms"] += 1
    vw = np.asarray(grid.verts_world, dtype=float)
    same = not key[1] or not key[2] or model_crs == section_crs
    if same:
        x, y = vw[:, 0], vw[:, 1]
    else:
        ctx = context if context is not None else QgsProject.instance().transformContext()
        x, y = _transform_xy(QgsCoordinateTransform(model_crs, section_crs, ctx), vw)
    off = np.asarray(grid.iverts.offsets, dtype=np.int64)
    ea = np.asarray(grid.iverts.indices, dtype=np.int64)
    nxt = np.arange(1, len(ea) + 1, dtype=np.int64)
    nxt[off[1:] - 1] = off[:-1]                          # each ring's last edge closes it
    eb = ea[nxt]
    xs, ys, starts = x[ea], y[ea], off[:-1]
    bounds = np.column_stack([np.minimum.reduceat(xs, starts), np.minimum.reduceat(ys, starts),
                              np.maximum.reduceat(xs, starts), np.maximum.reduceat(ys, starts)])
    for a in (x, y, off, ea, eb, bounds):
        a.flags.writeable = False
    return _put(_GEO_CACHE, key, SectionGrid(grid, x, y, off, ea, eb, bounds, not same), _CACHE_MAX["grid"])


# ================================================================================================ the line through the cells
@dataclass(eq=False)
class CellPath:
    """Where the section line lies inside the cells: sorted, non-overlapping pieces [s0, s1] (stations, ft), each
    covered by the cells cover_cells[cover_offsets[i]:cover_offsets[i + 1]] (one cell, except where DISU nodes
    overlap). Stretches between pieces are inside no cell."""
    s0: np.ndarray
    s1: np.ndarray
    cell: np.ndarray                    # (n,) the (first) cell of each piece, 0-based within a layer
    cover_offsets: np.ndarray           # (n + 1,)
    cover_cells: np.ndarray
    length: float                       # the line, ft
    overlaps: bool = False              # some piece is covered by more than one cell

    def __len__(self) -> int:
        return len(self.s0)

    def intervals(self) -> List[Tuple[float, float, int]]:
        """[(station_start_ft, station_end_ft, cell)] (the first cell of an overlapping piece)."""
        return [(float(a), float(b), int(c)) for a, b, c in zip(self.s0, self.s1, self.cell)]

    def covered(self) -> float:
        """Length of the line inside the grid, ft."""
        return float(np.sum(self.s1 - self.s0))


def _ring_positions(off: np.ndarray, cells: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Edge positions of `cells` (concatenated), the index into `cells` owning each, and each cell's edge count."""
    starts = off[cells]
    cnt = off[cells + 1] - starts
    owner = np.repeat(np.arange(len(cells)), cnt)
    pos = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt) + np.repeat(starts, cnt)
    return pos, owner, cnt


def _segment_cells(sg: SectionGrid, ax: float, ay: float, bx: float, by: float, cand: np.ndarray
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(t0, t1, cell): the parts of segment A->B (t in [0, 1]) inside each candidate cell ring.

    Each ring vertex is classed once by its signed distance from the line through A and B, a distance within `tol`
    counting as on the line: as every cell sharing a vertex computes the same distance from the same coordinates,
    they all make the same decision, also for vertices a rounding error off the line (a rotated grid, a line
    snapped to grid corners). A ring cuts the segment where one of its edges changes side (interpolated from the two
    distances) and at each of its vertices on the line; a cut piece is inside the ring when its midpoint, nudged
    4 tol to the LEFT of A->B, is (crossing-number test: non-convex rings work, and a stretch along an edge goes to
    the cell on its left, so a shared edge to exactly one cell and an outer edge consistently in or out)."""
    empty = np.zeros(0), np.zeros(0), np.zeros(0, np.int64)
    if len(cand) == 0:
        return empty
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    L = math.sqrt(L2)
    tol = 1e-9 * L + 1e-7                                            # section CRS units: "on the line"
    pos, owner, cnt = _ring_positions(sg.offsets, cand)
    px, py = sg.x[sg.ea[pos]] - ax, sg.y[sg.ea[pos]] - ay      # relative to A: precision at state-plane values
    qx, qy = sg.x[sg.eb[pos]] - ax, sg.y[sg.eb[pos]] - ay
    sp = (px * dy - py * dx) / L                                     # signed distance of each edge's ends
    sq = (qx * dy - qy * dx) / L
    sp[np.abs(sp) <= tol] = 0.0
    sq[np.abs(sq) <= tol] = 0.0
    tp = (px * dx + py * dy) / L2
    tq = (qx * dx + qy * dy) / L2
    cross = (sp * sq) < 0.0                                          # the edge changes side (NaN: never)
    with np.errstate(divide="ignore", invalid="ignore"):
        tc = tp + sp / (sp - sq) * (tq - tp)
    on = sp == 0.0                                                   # each ring vertex once (as an edge's start)
    ct = np.concatenate([tc[cross], tp[on]])
    co = np.concatenate([owner[cross], owner[on]])
    keep = (ct > 0.0) & (ct < 1.0)
    K = len(cand)
    ct = np.concatenate([ct[keep], np.zeros(K), np.ones(K)])
    co = np.concatenate([co[keep], np.arange(K), np.arange(K)])
    order = np.lexsort((ct, co))
    ct, co = ct[order], co[order]
    pair = (co[:-1] == co[1:]) & (ct[1:] - ct[:-1] > 1e-11)
    t0, t1, ow = ct[:-1][pair], ct[1:][pair], co[:-1][pair]
    if len(t0) == 0:
        return empty
    tm = (t0 + t1) / 2.0
    nudge = 4.0 * tol / L                                            # to the left of A->B
    mx, my = tm * dx - dy * nudge, tm * dy + dx * nudge
    # crossing-number test of each midpoint against its own ring
    first = np.cumsum(cnt) - cnt                                     # where each candidate's edges start
    epos, eown, _ = _ring_positions(np.concatenate([first, [first[-1] + cnt[-1]]]), ow)
    exa, eya, exb, eyb = px[epos], py[epos], qx[epos], qy[epos]
    sw = eya > eyb                       # each edge from its lower end: both cells of a shared edge compute the same cut
    exa, exb = np.where(sw, exb, exa), np.where(sw, exa, exb)
    eya, eyb = np.where(sw, eyb, eya), np.where(sw, eya, eyb)
    emx, emy = mx[eown], my[eown]
    with np.errstate(divide="ignore", invalid="ignore"):
        spans = (eya > emy) != (eyb > emy)
        xcut = exa + (emy - eya) * (exb - exa) / (eyb - eya)
        passes = spans & (emx < xcut)
    inside = (np.bincount(eown, weights=passes.astype(float), minlength=len(t0)) % 2) == 1
    return t0[inside], t1[inside], cand[ow[inside]]


def _assemble(s0: np.ndarray, s1: np.ndarray, cell: np.ndarray, length: float) -> CellPath:
    """Stations of the pieces of every cell along the line -> a CellPath: each cell's touching pieces merged,
    endpoints closer than a hair (1e-7 of the line) snapped together, overlapping cells split into elementary
    pieces."""
    snap = 1e-7 * length + 1e-9
    if len(s0):
        order = np.lexsort((s0, cell))                                # per cell, along the line
        s0, s1, cell = s0[order], s1[order], cell[order]
        new = np.ones(len(s0), bool)
        new[1:] = (cell[1:] != cell[:-1]) | (s0[1:] > s1[:-1] + snap)
        s1 = np.maximum.reduceat(s1, np.nonzero(new)[0])
        s0, cell = s0[new], cell[new]
        vals = np.concatenate([s0, s1])
        order = np.argsort(vals, kind="stable")
        sv = vals[order]
        first = np.ones(len(sv), bool)
        first[1:] = np.diff(sv) > snap
        rep = sv[first][np.cumsum(first) - 1]
        snapped = np.empty_like(vals)
        snapped[order] = rep
        n = len(s0)
        s0, s1 = snapped[:n], snapped[n:]
        keep = s1 > s0
        s0, s1, cell = s0[keep], s1[keep], cell[keep]
        order = np.lexsort((s1, s0))
        s0, s1, cell = s0[order], s1[order], cell[order]
    n = len(s0)
    if n < 2 or not np.any(s0[1:] < np.maximum.accumulate(s1)[:-1]):
        return CellPath(s0, s1, cell, np.arange(n + 1), cell.copy(), float(length), False)
    # overlapping cells (DISU node layers): elementary pieces between every endpoint, each with the cells over it
    kp = np.unique(np.concatenate([s0, s1]))
    a, b = np.searchsorted(kp, s0), np.searchsorted(kp, s1)
    cnt = b - a
    piece = np.repeat(a, cnt) + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    cells = np.repeat(cell, cnt)
    order = np.lexsort((cells, piece))
    piece, cells = piece[order], cells[order]
    up, start, counts = np.unique(piece, return_index=True, return_counts=True)
    return CellPath(kp[up], kp[up + 1], cells[start], np.concatenate([[0], np.cumsum(counts)]), cells,
                    float(length), bool(counts.max() > 1))


def cell_path(sg: SectionGrid, line: QgsGeometry, dist_factor: float) -> CellPath:
    """The stretches of the section line (a polyline in the section CRS) inside each cell, as stations in feet
    (section CRS distance x dist_factor). Cached per grid, CRS pair and line."""
    key = (sg, line.asWkt(), float(dist_factor))
    hit = _get(_PATH_CACHE, key)
    if hit is not None:
        return hit
    STATS["paths"] += 1
    v = line_vertices(line)
    d = np.diff(v, axis=0)
    seg_len = np.hypot(d[:, 0], d[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    length = float(cum[-1]) * dist_factor
    b = sg.bounds
    lo, hi = v.min(axis=0), v.max(axis=0)
    eps = 1e-9 * max(float(np.max(hi - lo)), 1.0)
    with np.errstate(invalid="ignore"):
        sub = np.nonzero((b[:, 0] <= hi[0] + eps) & (b[:, 2] >= lo[0] - eps)
                         & (b[:, 1] <= hi[1] + eps) & (b[:, 3] >= lo[1] - eps))[0]
    if len(sub) == 0:
        return _put(_PATH_CACHE, key, _assemble(np.zeros(0), np.zeros(0), np.zeros(0, np.int64), length),
                    _CACHE_MAX["path"])
    parts0, parts1, cells = [], [], []

    def boxed(bounds, xlo, ylo, xhi, yhi):
        with np.errstate(invalid="ignore"):
            return np.nonzero((bounds[:, 0] <= xhi + eps) & (bounds[:, 2] >= xlo - eps)
                              & (bounds[:, 1] <= yhi + eps) & (bounds[:, 3] >= ylo - eps))[0]

    for c0 in range(0, len(seg_len), _CHUNK):            # a long many-vertex line: prefilter per run of segments
        c1 = min(c0 + _CHUNK, len(seg_len))
        clo, chi = v[c0:c1 + 1].min(axis=0), v[c0:c1 + 1].max(axis=0)
        csub = sub[boxed(b[sub], clo[0], clo[1], chi[0], chi[1])]
        if len(csub) == 0:
            continue
        cb = b[csub]
        for i in range(c0, c1):
            if seg_len[i] <= 0.0:
                continue
            (ax, ay), (bx, by) = v[i], v[i + 1]
            dx, dy = bx - ax, by - ay
            m = boxed(cb, min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
            if len(m) == 0:
                continue
            bb = cb[m]
            e = (1e-9 * seg_len[i] + 1e-9) * seg_len[i]
            side = [dx * (cy - ay) - dy * (cx - ax) for cx, cy in ((bb[:, 0], bb[:, 1]), (bb[:, 2], bb[:, 1]),
                                                                 (bb[:, 2], bb[:, 3]), (bb[:, 0], bb[:, 3]))]
            apart = ((side[0] > e) & (side[1] > e) & (side[2] > e) & (side[3] > e)) | \
                    ((side[0] < -e) & (side[1] < -e) & (side[2] < -e) & (side[3] < -e))
            cand = csub[m][~apart]
            t0, t1, c = _segment_cells(sg, float(ax), float(ay), float(bx), float(by), cand)
            parts0.append((cum[i] + t0 * seg_len[i]) * dist_factor)
            parts1.append((cum[i] + t1 * seg_len[i]) * dist_factor)
            cells.append(c)
    if parts0:
        s0, s1, cell = np.concatenate(parts0), np.concatenate(parts1), np.concatenate(cells).astype(np.int64)
    else:
        s0, s1, cell = np.zeros(0), np.zeros(0), np.zeros(0, np.int64)
    return _put(_PATH_CACHE, key, _assemble(s0, s1, cell, length), _CACHE_MAX["path"])


# ================================================================================================ values along the line
def choose(path: CellPath, values: np.ndarray, var: str, grid: Optional[Grid] = None
           ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(s0, s1, v, cells): one value per piece of `path` from the per-cell `values` (nan = no value), touching
    pieces of the same cell merged. Where cells overlap (DISU node layers): "top" takes the highest value, "botm" the
    lowest, "head" the node with the highest top that has a head, "wt" the highest node that is wet (head above its
    bottom, or a confined node), else the lowest node with a head (the water table is below the nodes there)."""
    values = np.asarray(values, dtype=float)
    cells = path.cell.copy()
    if path.overlaps:
        off, cc = path.cover_offsets, path.cover_cells
        tops = np.asarray(grid.top, float) if grid is not None else np.zeros(len(values))
        wet = np.isfinite(values)
        if var == "wt" and grid is not None and grid.botm is not None and grid.botm.shape == (1, len(values)):
            with np.errstate(invalid="ignore"):
                wet = wet & (values > grid.botm[0])
            if grid.icelltype is not None and grid.icelltype.shape == (1, len(values)):
                wet |= np.isfinite(values) & (grid.icelltype[0] == 0)
        for i in np.nonzero(np.diff(off) > 1)[0]:
            cs = cc[off[i]:off[i + 1]]
            ok = cs[np.isfinite(values[cs])]
            if len(ok) == 0:
                continue
            if var == "top":
                cells[i] = ok[np.argmax(values[ok])]
            elif var == "botm":
                cells[i] = ok[np.argmin(values[ok])]
            elif var == "wt" and not wet[ok].any():
                cells[i] = ok[np.argmin(tops[ok])]
            else:
                pick = ok[wet[ok]] if var == "wt" else ok
                cells[i] = pick[np.argmax(tops[pick])]
    s0, s1 = path.s0, path.s1
    if len(cells) > 1:
        new = np.ones(len(cells), bool)
        new[1:] = (cells[1:] != cells[:-1]) | (s0[1:] > s1[:-1])
        if not new.all():
            idx = np.nonzero(new)[0]
            ends = np.concatenate([idx[1:] - 1, [len(cells) - 1]])
            s0, s1, cells = s0[idx], s1[ends], cells[idx]
    return s0.copy(), s1.copy(), values[cells] if len(cells) else np.zeros(0), cells


def model_profile(s0, s1, v, mode: str, length: float) -> Tuple[List[float], List[float], float]:
    """(stations, z, coverage) of per-piece values along the line. "cells": flat across each piece with a vertical
    step at each edge (section._steps), nan across stretches without a value. "smooth": a straight line through
    each piece's midpoint value, the first and last values of each unbroken run held flat to its outer edges; a
    piece without a value, or a stretch inside no cell, breaks the line (a nan point midway)."""
    s0, s1, v = np.asarray(s0, float), np.asarray(s1, float), np.asarray(v, float)
    n = len(s0)
    if n == 0 or not length > 0:
        return [], [], 0.0
    have = np.isfinite(v)
    v = np.where(have, v, np.nan)
    coverage = float(np.sum((s1 - s0)[have]) / length)
    tol = 1e-9 * max(length, 1.0)
    if mode == "cells":
        gap = np.nonzero(s0[1:] > s1[:-1] + tol)[0]           # stretches inside no cell: nan pieces
        starts = np.insert(s0, gap + 1, s1[gap])
        ends = np.insert(s1, gap + 1, s0[gap + 1])
        zz = np.insert(v, gap + 1, np.nan)
        st, z = _steps(starts, ends, zz)
        return st, z, coverage
    st: List[float] = []
    z: List[float] = []
    i, prev_end = 0, None
    while i < n:
        if not have[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and have[j + 1] and s0[j + 1] <= s1[j] + tol:
            j += 1
        if prev_end is not None:
            st.append(float((prev_end + s0[i]) / 2.0))
            z.append(math.nan)
        st.append(float(s0[i]))
        z.append(float(v[i]))
        mids = (s0[i:j + 1] + s1[i:j + 1]) / 2.0
        st.extend(mids.tolist())
        z.extend(v[i:j + 1].tolist())
        st.append(float(s1[j]))
        z.append(float(v[j]))
        prev_end = s1[j]
        i = j + 1
    return st, z, coverage


def cell_values(grid: Grid, var: str, layer: int = 1, head: Optional[HeadFile] = None, kper: int = 0,
                kstp: int = 0) -> np.ndarray:
    """mf6.surface_array, cached per grid, head file, variable, layer and time (read-only; model length units)."""
    head = head if var in ("head", "wt") else None
    key = (grid, head, var, int(layer) if var in ("botm", "head") else 0, int(kper), int(kstp))
    hit = _get(_VALUES_CACHE, key)
    if hit is not None:
        return hit
    _drop_stale(grid=grid, head=head)
    STATS["values"] += 1
    a = surface_array(grid, var, layer, head.path if head is not None else "", (kper, kstp))
    a.flags.writeable = False
    return _put(_VALUES_CACHE, key, a, _CACHE_MAX["values"])


# ================================================================================================ names, units
def model_name(path: str) -> str:
    """The model's name from its grid file: F9_flowV1.disv.grb -> F9_flowV1."""
    name = os.path.basename(path)
    for ext in (".grb", ".disv", ".disu", ".dis"):
        if name.lower().endswith(ext):
            name = name[:-len(ext)]
    return name or os.path.basename(path)


def surface_name(var: str, layer: int, kind: str = "") -> str:
    """Default legend name: "Model top", "Layer 2 bottom", "Layer 1 head", "Water table" (a DISU, whose nodes have no
    layers: "Model bottom", "Head")."""
    if var == "top":
        return "Model top"
    if var == "botm":
        return "Model bottom" if kind == "disu" else f"Layer {layer} bottom"
    if var == "head":
        return "Head" if kind == "disu" else f"Layer {layer} head"
    return "Water table"


def time_text(head: HeadFile, kper: int, kstp: int, step: bool = False) -> str:
    """"SP 30", or "SP 3, step 2" when that period has several saved steps (or `step`)."""
    if step or len(head.steps(kper)) > 1:
        return f"SP {kper}, step {kstp}"
    return f"SP {kper}"


def auto_name(var: str, layer: int, kind: str = "", head: Optional[HeadFile] = None, kper: int = 0,
              kstp: int = 0) -> str:
    """The legend name of a model surface without a name of its own (the panel shows the same): surface_name, and
    for heads and the water table the time drawn ("Layer 1 head (SP 30)", "Water table (SP 3, step 2)") when the
    head file holds more than one saved time."""
    base = surface_name(var, layer, kind)
    if var in ("head", "wt") and head is not None and kper > 0 and len(head.times()) > 1:
        return f"{base} ({time_text(head, kper, kstp)})"
    return base


def model_z_units(grid: Grid, setting: str, model_crs: Optional[QgsCoordinateReferenceSystem]
                  ) -> Tuple[str, float, str]:
    """(units, feet per model length unit, how): an explicit setting ft | ftUS | m ("set"); "auto": the model's
    LENGTH_UNITS ("detected"), else the units of the model CRS ("crs"), else feet ("default")."""
    if setting in _Z_UNITS:
        return setting, _unit_factor(_Z_UNITS[setting]), "set"
    lu = grid.length_units
    if lu == "feet":
        return "ft", 1.0, "detected"
    if lu == "meters":
        return "m", _unit_factor(_Z_UNITS["m"]), "detected"
    if lu == "centimeters":
        return "cm", _unit_factor(_Z_UNITS["m"]) / 100.0, "detected"
    code = "unknown"
    if model_crs is not None and model_crs.isValid() and not model_crs.isGeographic():
        code = _unit_code(model_crs.mapUnits())
    if code == "unknown":
        return "ft", 1.0, "default"
    return code, _unit_factor(_Z_UNITS[code]), "crs"


def _model_crs(text: str, project: QgsProject, section_crs) -> Optional[QgsCoordinateReferenceSystem]:
    """The CRS of the model coordinates: the setting (auth id or WKT), else the project CRS, else the section CRS.
    None for a setting that is not a valid CRS."""
    text = (text or "").strip()
    if text:
        crs = _crs_from_text(text)
        if not crs.isValid():
            crs = QgsCoordinateReferenceSystem.fromWkt(text)
        return crs if crs.isValid() else None
    pcrs = project.crs()
    return pcrs if pcrs.isValid() else section_crs


# ================================================================================================ one surface
def model_surface(d: dict, project: QgsProject, line: QgsGeometry, crs: QgsCoordinateReferenceSystem,
                  dist_factor: float, length: float, warnings: List[str]) -> Optional[SurfaceProfile]:
    """One cleaned Settings.surfaces entry with source "mf6" sampled along the line, or None with a warning when it
    can't be drawn (grid or head file missing or unreadable, layer or time not in the model, a head file of another
    grid, an invalid CRS, the model off the line, no values along it)."""
    var, layer = d["mf6_var"], int(d["mf6_layer"])
    grid_path = (d["mf6_path"] or "").strip()
    own = (d["name"] or "").strip()
    label = own or surface_name(var, layer)

    def leave(text: str) -> None:
        warnings.append(f"Surface “{label}”: {text}")
        return None

    if not grid_path:
        return leave("no MODFLOW 6 grid file chosen; left out.")
    try:
        grid = read_grid(grid_path)
    except MF6Error as exc:
        return leave(f"{exc} Left out.")
    model = model_name(grid.path)
    base = surface_name(var, layer, grid.kind)
    label = own or base
    if var in ("botm", "head") and not 1 <= layer <= grid.nlay:
        what = "has one layer of nodes" if grid.kind == "disu" else f"has layers 1-{grid.nlay}"
        return leave(f"layer {layer} is not in the model {model} (it {what}); left out.")

    head, kper, kstp = None, 0, 0
    if var in ("head", "wt"):
        head_path = (d["mf6_head_path"] or "").strip()
        if not head_path:
            try:
                head_path = find_model(grid.path).head_path
            except MF6Error:
                head_path = ""
            if not head_path:
                return leave("no head file chosen (and none found with the model); left out.")
        try:
            head = HeadFile(head_path)
            head.check_grid(grid)
            kper, kstp = head.resolve(d["mf6_time"])
        except MF6Error as exc:
            return leave(f"{exc} Left out.")
        if not own:
            label = auto_name(var, layer, grid.kind, head, kper, kstp)
        if d["mf6_time"] == "last" and head.partial:
            text = (f"{head.name} is still being written (is the model running?): the last complete time step "
                    f"(SP {kper}, step {kstp}) is shown.")
            if text not in warnings:
                warnings.append(text)

    mcrs = _model_crs(d["mf6_crs"], project, crs)
    if mcrs is None:
        short = d["mf6_crs"].strip()
        short = short if len(short) <= 40 else short[:37] + "…"
        return leave(f"the model CRS “{short}” is not a valid CRS; left out. Choose the CRS of the model's "
                     "coordinates in the surface's settings.")
    try:
        sg = section_grid(grid, mcrs, crs, project.transformContext())
        path = cell_path(sg, line, dist_factor)
    except MF6Error as exc:
        return leave(f"{exc} Left out.")
    if len(path) == 0:
        where = mcrs.authid() or mcrs.description() or "its CRS"
        return leave(f"the model {model} does not cross the section line; left out. If it should, check the model "
                     f"CRS ({where}) in the surface's settings.")
    try:
        raw = cell_values(grid, var, layer, head, kper, kstp)
    except MF6Error as exc:
        return leave(f"{exc} Left out.")
    units, zf, how = model_z_units(grid, d["z_units"], mcrs)
    s0, s1, v, _cells = choose(path, raw, var, grid)
    stations, z, coverage = model_profile(s0, s1, v * zf, d["mode"], length)
    if coverage <= 0.0:
        why = "dry or inactive cells" if var in ("head", "wt") else "inactive cells"
        return leave(f"the model {model} has no values along the line ({why}); left out.")
    if path.overlaps and grid.kind == "disu":
        text = (f"{model}: some DISU nodes overlap along the line; there the model top is the highest node top, the "
                "bottom the lowest node bottom, and heads come from the highest node with a head.")
        if text not in warnings:
            warnings.append(text)
    if how in ("crs", "default"):
        why = "the units of its CRS" if how == "crs" else "its CRS units are unknown too"
        warnings.append(f"Surface “{label}”: {model} does not state its LENGTH_UNITS; assumed {_Z_NAMES[units]} "
                        f"({why}). Set the elevation units in the surface's settings if that is wrong.")
    source = os.path.basename(head.path) if head is not None else os.path.basename(grid.path)
    when = f"SP {kper}, step {kstp}" if head is not None else ""
    flat = "flat across each cell" if d["mode"] == "cells" else ""    # one parenthesis (figure.surfaces_sources)
    if own and own != base:
        inner = base[0].lower() + base[1:]
        detail = (f"{own} ({inner} from {source}" + (f", {when}" if when else "") + (f"; {flat}" if flat else "")
                  + ")")
    else:
        extra = "; ".join(x for x in (when, flat) if x)
        detail = f"{base} from {source}" + (f" ({extra})" if extra else "")
    lengths = (s1 - s0)[np.isfinite(v)]
    step = float(np.median(lengths)) if len(lengths) else 0.0
    return SurfaceProfile(name=label, color=d["color"], style=d["style"], width=float(d["width"]), mode=d["mode"],
                          stations=list(stations), z=list(z), in_range=bool(d["in_range"]), marks=bool(d["marks"]),
                          layer_name=model, band=layer if var in ("botm", "head") else 1, coverage=coverage,
                          step=step, source="mf6", detail=detail)
