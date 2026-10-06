"""Section line and ground profile: CRS choice, line resolution, DEM sampling.

All sampling is bilinear on pixel centres, from small windows of the DEM (256 x 256 pixel tiles,
cached), so a statewide mosaic is never read whole. Elevations come back in feet.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from typing import Callable, List, Optional, Tuple

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsCoordinateTransformContext, QgsCsException, QgsGeometry, QgsPointXY,
                       QgsProject, QgsRasterLayer, QgsRectangle, QgsVectorLayer, QgsWkbTypes)

from .model import GroundProfile, SectionError, Settings

COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def azimuth_deg(dx: float, dy: float) -> float:
    """Grid azimuth of a vector, degrees clockwise from north, in [0, 360)."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def compass_point(azimuth: float, points: int = 8) -> str:
    """'N', 'NE', ... for 8 points, or 'NNE', ... for 16 points."""
    names = COMPASS16 if points == 16 else COMPASS8
    sector = 360.0 / len(names)
    return names[int(((azimuth % 360.0) + sector / 2.0) // sector) % len(names)]


# ----------------------------------------------------------------------------------- CRS

def section_crs(dem: QgsRasterLayer, project: QgsProject) -> QgsCoordinateReferenceSystem:
    """The DEM CRS if projected, else the project CRS if projected, else SectionError."""
    crs = dem.crs()
    if crs.isValid() and not crs.isGeographic():
        return crs
    pcrs = project.crs()
    if pcrs.isValid() and not pcrs.isGeographic():
        return pcrs
    raise SectionError(
        f"The DEM ({dem.name()}) and the project both use a geographic CRS (degrees). Set the project "
        "CRS to a projected CRS in feet or meters, e.g. EPSG:2927 (WA South, ftUS).")


# ----------------------------------------------------------------------------------- line

def _crs_from_text(text: str) -> QgsCoordinateReferenceSystem:
    """Accepts an auth id ('EPSG:2927'), 'WKT:...' / raw WKT, or 'PROJ:...'."""
    if not text:
        return QgsCoordinateReferenceSystem()
    return QgsCoordinateReferenceSystem(text)


def _line_source(settings: Settings, project: QgsProject
                 ) -> Tuple[QgsGeometry, QgsCoordinateReferenceSystem, str]:
    """Raw geometry, its CRS and a short description. A picked feature wins over a drawn line."""
    layer = project.mapLayer(settings.line_layer_id) if settings.line_layer_id else None
    fid = settings.line_fid
    if settings.line_layer_id and (fid is not None or not settings.line_wkt):
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            raise SectionError("The section line layer is no longer in the project. Pick or draw a line.")
        if fid is None:
            if layer.featureCount() != 1:
                raise SectionError(f"Pick a section line feature in {layer.name()}.")
            feat = next(layer.getFeatures())
        else:
            feat = layer.getFeature(int(fid))
            if not feat.isValid():
                raise SectionError(f"Feature {fid} of {layer.name()} no longer exists. Pick the line again.")
        if not feat.isValid() or not feat.hasGeometry():
            raise SectionError(f"Feature {fid} of {layer.name()} has no geometry. Pick another line.")
        return QgsGeometry(feat.geometry()), layer.crs(), f"feature {feat.id()} of {layer.name()}"
    if settings.line_wkt:
        geom = QgsGeometry.fromWkt(settings.line_wkt)
        if geom.isNull() or geom.isEmpty():
            raise SectionError("The drawn section line could not be read. Draw it again.")
        src = _crs_from_text(settings.line_crs_authid)
        if not src.isValid():
            src = project.crs()
        return geom, src, "drawn line"
    raise SectionError("Choose a section line: pick a line feature or draw one on the map.")


def resolve_line(settings: Settings, project: QgsProject, crs: QgsCoordinateReferenceSystem
                 ) -> QgsGeometry:
    """The section line as a 2-D LineString in `crs`.

    From line_layer_id/line_fid (preferred when set) or line_wkt/line_crs_authid. Curves are
    segmentized, multipart lines merged end to end (SectionError if they do not join), duplicate
    vertices dropped; at least 2 distinct vertices.
    """
    geom, src_crs, what = _line_source(settings, project)
    if QgsWkbTypes.geometryType(geom.wkbType()) != Qgis.GeometryType.Line:
        raise SectionError(f"The section line ({what}) is not a line.")
    if QgsWkbTypes.isCurvedType(geom.wkbType()):
        geom = QgsGeometry(geom.constGet().segmentize())
    if geom.isMultipart():
        parts = geom.asGeometryCollection()
        if len(parts) == 1:
            geom = parts[0]
        else:
            merged = geom.mergeLines()
            if merged.isNull() or merged.isMultipart():
                raise SectionError(
                    f"The section line ({what}) has {len(parts)} parts that do not join end to end. "
                    "Use a single continuous line.")
            geom = merged
    if src_crs.isValid() and crs.isValid() and src_crs != crs:
        try:
            geom.transform(QgsCoordinateTransform(src_crs, crs, project.transformContext()))
        except QgsCsException as exc:
            raise SectionError(f"The section line could not be transformed to {crs.description()}: {exc}")
    pts: List[QgsPointXY] = []
    for v in geom.vertices():
        p = QgsPointXY(v.x(), v.y())
        if not (math.isfinite(p.x()) and math.isfinite(p.y())):
            raise SectionError("The section line has invalid coordinates.")
        if not pts or p.distance(pts[-1]) > 1e-9:
            pts.append(p)
    if len(pts) < 2:
        raise SectionError("The section line needs at least two different points.")
    return QgsGeometry.fromPolylineXY(pts)


def line_vertices(line: QgsGeometry) -> np.ndarray:
    """(n, 2) array of vertex x, y."""
    return np.array([(v.x(), v.y()) for v in line.vertices()], dtype=float)


def vertex_stations(line: QgsGeometry, dist_factor: float) -> List[float]:
    """Cumulative distance (ft) of every vertex; first 0, last = length."""
    v = line_vertices(line)
    seg = np.hypot(np.diff(v[:, 0]), np.diff(v[:, 1])) * dist_factor
    return [0.0] + np.cumsum(seg).tolist()


# ----------------------------------------------------------------------------------- DEM

class RasterSampler:
    """Callable (x, y) -> z in feet. x, y in the section CRS; nan for nodata / outside.

    Bilinear on pixel centres. Points in the outer half pixel use the edge pixels. Reads the
    DEM in 256 x 256 pixel tiles (each with a 1 pixel overlap to the right/bottom) and keeps
    up to 64 of them, so repeated calls (ground line, then explorations) reuse the reads.
    """

    TILE = 256
    MAX_TILES = 64

    def __init__(self, dem: QgsRasterLayer, band: int, crs: QgsCoordinateReferenceSystem,
                 z_factor: float, context: Optional[QgsCoordinateTransformContext] = None):
        if not dem.isValid():
            raise SectionError(f"The DEM ({dem.name()}) could not be read.")
        self.provider = dem.dataProvider()
        if band < 1 or band > self.provider.bandCount():
            raise SectionError(f"The DEM ({dem.name()}) has no band {band}.")
        self.band = band
        ext = self.provider.extent()
        self.ncols, self.nrows = int(self.provider.xSize()), int(self.provider.ySize())
        if self.ncols < 1 or self.nrows < 1:
            raise SectionError(f"The DEM ({dem.name()}) is empty.")
        self.x0, self.y1 = ext.xMinimum(), ext.yMaximum()
        self.cw, self.ch = ext.width() / self.ncols, ext.height() / self.nrows
        self.z_factor = float(z_factor)
        rcrs = dem.crs()
        self._ct: Optional[QgsCoordinateTransform] = None
        if rcrs.isValid() and crs.isValid() and rcrs != crs:
            ctx = context if context is not None else QgsProject.instance().transformContext()
            self._ct = QgsCoordinateTransform(crs, rcrs, ctx)
        self._tiles: "OrderedDict[Tuple[int, int], np.ndarray]" = OrderedDict()
        self.block_reads = 0

    # -- block reading
    def _read_tile(self, tr: int, tc: int) -> np.ndarray:
        key = (tr, tc)
        arr = self._tiles.get(key)
        if arr is not None:
            self._tiles.move_to_end(key)
            return arr
        T = self.TILE
        c0, r0 = tc * T, tr * T
        c1, r1 = min(c0 + T + 1, self.ncols), min(r0 + T + 1, self.nrows)
        w, h = c1 - c0, r1 - r0
        rect = QgsRectangle(self.x0 + c0 * self.cw, self.y1 - r1 * self.ch,
                            self.x0 + c1 * self.cw, self.y1 - r0 * self.ch)
        block = self.provider.block(self.band, rect, w, h)
        self.block_reads += 1
        if block is None or not block.isValid() or block.isEmpty():
            arr = np.full((h, w), np.nan)
        else:
            arr = np.array(block.as_numpy(use_masking=False), dtype=float).reshape(h, w)
            if block.hasNoDataValue():
                nd = block.noDataValue()
                if math.isnan(nd):
                    pass                       # nan already
                else:
                    arr[arr == nd] = np.nan
            elif block.hasNoData():            # nodata bitmap without a value (user nodata ranges)
                flat = arr.reshape(-1)
                for i in range(flat.size):
                    if block.isNoData(i):
                        flat[i] = np.nan
        self._tiles[key] = arr
        if len(self._tiles) > self.MAX_TILES:
            self._tiles.popitem(last=False)
        return arr

    def _to_raster_crs(self, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        xo, yo = np.full(x.shape, np.nan), np.full(y.shape, np.nan)
        for i in range(x.size):
            if not (math.isfinite(x[i]) and math.isfinite(y[i])):
                continue
            try:
                p = self._ct.transform(QgsPointXY(float(x[i]), float(y[i])))
            except QgsCsException:
                continue
            xo[i], yo[i] = p.x(), p.y()
        return xo, yo

    def __call__(self, x, y) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        shape = x.shape
        x = x.reshape(-1)
        y = np.asarray(y, dtype=float).reshape(-1)
        if self._ct is not None:
            x, y = self._to_raster_crs(x, y)
        out = np.full(x.shape, np.nan)
        fc = (x - self.x0) / self.cw - 0.5         # fractional column of pixel centres
        fr = (self.y1 - y) / self.ch - 0.5
        eps = 1e-7
        ok = (np.isfinite(fc) & np.isfinite(fr)
              & (fc >= -0.5 - eps) & (fc <= self.ncols - 0.5 + eps)
              & (fr >= -0.5 - eps) & (fr <= self.nrows - 0.5 + eps))
        idx = np.nonzero(ok)[0]
        if idx.size == 0:
            return out.reshape(shape)
        fc = np.clip(fc[idx], 0.0, self.ncols - 1.0)
        fr = np.clip(fr[idx], 0.0, self.nrows - 1.0)
        c0 = np.minimum(np.floor(fc).astype(np.int64), max(self.ncols - 2, 0))
        r0 = np.minimum(np.floor(fr).astype(np.int64), max(self.nrows - 2, 0))
        dx, dy = fc - c0, fr - r0
        c1 = np.minimum(c0 + 1, self.ncols - 1)
        r1 = np.minimum(r0 + 1, self.nrows - 1)
        T = self.TILE
        tiles = (r0 // T) * (self.ncols // T + 2) + (c0 // T)
        z = np.full(idx.shape, np.nan)
        for key in np.unique(tiles):
            sel = np.nonzero(tiles == key)[0]
            tr, tc = int(r0[sel[0]] // T), int(c0[sel[0]] // T)
            arr = self._read_tile(tr, tc)
            lc0, lc1 = c0[sel] - tc * T, c1[sel] - tc * T
            lr0, lr1 = r0[sel] - tr * T, r1[sel] - tr * T
            wx, wy = dx[sel], dy[sel]
            terms = ((arr[lr0, lc0], (1 - wx) * (1 - wy)), (arr[lr0, lc1], wx * (1 - wy)),
                     (arr[lr1, lc0], (1 - wx) * wy), (arr[lr1, lc1], wx * wy))
            acc = np.zeros(sel.shape)
            for v, w in terms:                     # a zero weight never pulls in a nodata neighbour
                acc += np.where(w > 0, v * w, 0.0)
            z[sel] = acc
        out[idx] = z * self.z_factor
        return out.reshape(shape)

    @property
    def same_crs(self) -> bool:
        """True when the raster is in the section CRS (its cell edges are straight lines there)."""
        return self._ct is None

    def cells(self, x, y) -> Tuple[np.ndarray, np.ndarray]:
        """(row, col) of the pixel holding each point (x, y in the section CRS); -1 outside the raster."""
        x = np.asarray(x, dtype=float).reshape(-1)
        y = np.asarray(y, dtype=float).reshape(-1)
        if self._ct is not None:
            x, y = self._to_raster_crs(x, y)
        with np.errstate(invalid="ignore"):
            col = np.floor((x - self.x0) / self.cw)
            row = np.floor((self.y1 - y) / self.ch)
        ok = np.isfinite(col) & np.isfinite(row) & (col >= 0) & (col < self.ncols) & (row >= 0) & (row < self.nrows)
        r = np.where(ok, row, -1).astype(np.int64)
        c = np.where(ok, col, -1).astype(np.int64)
        return r, c

    def nearest(self, x, y) -> np.ndarray:
        """The value of the pixel holding each point (no interpolation), feet; nan for nodata or outside."""
        r, c = self.cells(x, y)
        out = np.full(r.shape, np.nan)
        T = self.TILE
        ok = np.nonzero(r >= 0)[0]
        if ok.size:
            keys = (r[ok] // T) * (self.ncols // T + 2) + (c[ok] // T)
            for key in np.unique(keys):
                sel = ok[keys == key]
                tr, tc = int(r[sel[0]] // T), int(c[sel[0]] // T)
                arr = self._read_tile(tr, tc)
                out[sel] = arr[r[sel] - tr * T, c[sel] - tc * T]
        return out * self.z_factor


def raster_sampler(dem: QgsRasterLayer, band: int, crs: QgsCoordinateReferenceSystem, z_factor: float,
                   context: Optional[QgsCoordinateTransformContext] = None
                   ) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Bilinear DEM sampler: (x, y) in `crs` -> z in feet (nan for nodata or outside the raster)."""
    return RasterSampler(dem, band, crs, z_factor, context)


def dem_cell_size_ft(dem: QgsRasterLayer, crs: QgsCoordinateReferenceSystem, dist_factor: float,
                     context: Optional[QgsCoordinateTransformContext] = None) -> float:
    """Smaller DEM pixel side, in feet measured in the section CRS."""
    prov = dem.dataProvider()
    ext = prov.extent()
    cw, ch = ext.width() / max(prov.xSize(), 1), ext.height() / max(prov.ySize(), 1)
    rcrs = dem.crs()
    if not rcrs.isValid() or rcrs == crs:
        return min(cw, ch) * dist_factor
    ctx = context if context is not None else QgsProject.instance().transformContext()
    ct = QgsCoordinateTransform(rcrs, crs, ctx)
    cx, cy = ext.center().x(), ext.center().y()
    try:
        p0 = ct.transform(QgsPointXY(cx, cy))
        px = ct.transform(QgsPointXY(cx + cw, cy))
        py = ct.transform(QgsPointXY(cx, cy + ch))
    except QgsCsException:
        return math.nan
    return min(p0.distance(px), p0.distance(py)) * dist_factor


def ground_profile(line: QgsGeometry, sampler: Callable[[np.ndarray, np.ndarray], np.ndarray],
                   step_ft: float, dist_factor: float) -> GroundProfile:
    """Ground along the line: stations every `step_ft` plus every vertex plus the end.

    Gaps are (last valid station before, first valid station after) each run of nan samples,
    i.e. the stretch where GroundProfile.z_at() is nan; a run touching an end uses that end.
    """
    v = line_vertices(line)
    seg_ft = np.hypot(np.diff(v[:, 0]), np.diff(v[:, 1])) * dist_factor
    cum = np.concatenate([[0.0], np.cumsum(seg_ft)])
    length = float(cum[-1])
    if not step_ft or not math.isfinite(step_ft) or step_ft <= 0:
        step_ft = max(length / 1000.0, 1e-6)
    regular = np.arange(0.0, length, step_ft)
    # drop regular stations that coincide with a vertex (keep the exact vertex station)
    j = np.clip(np.searchsorted(cum, regular), 1, len(cum) - 1)
    near_vertex = (np.abs(regular - cum[j]) < 1e-6) | (np.abs(regular - cum[j - 1]) < 1e-6)
    st = np.union1d(regular[~near_vertex], cum)
    # map stations to x, y
    seg = np.clip(np.searchsorted(cum, st, side="right") - 1, 0, len(seg_ft) - 1)
    t = np.where(seg_ft[seg] > 0, (st - cum[seg]) / np.where(seg_ft[seg] > 0, seg_ft[seg], 1.0), 0.0)
    x = v[seg, 0] + t * (v[seg + 1, 0] - v[seg, 0])
    y = v[seg, 1] + t * (v[seg + 1, 1] - v[seg, 1])
    z = np.asarray(sampler(x, y), dtype=float)
    nan = ~np.isfinite(z)
    z = np.where(nan, np.nan, z)
    gaps: List[Tuple[float, float]] = []
    n = len(st)
    i = 0
    while i < n:
        if nan[i]:
            k = i
            while k + 1 < n and nan[k + 1]:
                k += 1
            a = float(st[i - 1]) if i > 0 else float(st[i])
            b = float(st[k + 1]) if k + 1 < n else float(st[k])
            gaps.append((a, b))
            i = k + 1
        else:
            i += 1
    coverage = float(1.0 - nan.sum() / n) if n else 0.0
    return GroundProfile(stations=st.tolist(), z=z.tolist(), step=float(step_ft), gaps=gaps,
                         coverage=coverage)


# ----------------------------------------------------------------------------------- other surfaces
MAX_CELL_EDGES = 400_000       # cell edges traced exactly along a line; past this, cells are sampled densely


def _stations_xy(v: np.ndarray, cum: np.ndarray, st: np.ndarray, dist_factor: float) -> Tuple[np.ndarray, np.ndarray]:
    """x, y (section CRS) of stations `st` (ft) along the polyline with vertices `v` and cumulative lengths
    `cum` (section CRS units)."""
    seg_len = np.diff(cum)
    u = st / dist_factor
    seg = np.clip(np.searchsorted(cum, u, side="right") - 1, 0, len(seg_len) - 1)
    t = np.where(seg_len[seg] > 0, (u - cum[seg]) / np.where(seg_len[seg] > 0, seg_len[seg], 1.0), 0.0)
    return v[seg, 0] + t * (v[seg + 1, 0] - v[seg, 0]), v[seg, 1] + t * (v[seg + 1, 1] - v[seg, 1])


def _steps(starts: np.ndarray, ends: np.ndarray, z: np.ndarray) -> Tuple[List[float], List[float]]:
    """Stations and elevations of a stepped line: each interval [start, end] flat at its z, neighbours with the
    same value merged, so a cell edge shows as a vertical step (the edge station appears twice)."""
    st: List[float] = []
    zz: List[float] = []
    i, n = 0, len(z)
    while i < n:
        j = i
        while j + 1 < n and ((math.isnan(z[j + 1]) and math.isnan(z[i])) or z[j + 1] == z[i]):
            j += 1
        st += [float(starts[i]), float(ends[j])]
        zz += [float(z[i]), float(z[i])]
        i = j + 1
    return st, zz


def cells_profile(line: QgsGeometry, sampler: "RasterSampler", dist_factor: float, cell_ft: float
                  ) -> Tuple[List[float], List[float], float]:
    """(stations, z, coverage) of a raster drawn flat across each cell, with a vertical step at every cell edge
    the line crosses. A raster in the section CRS has its edges traced exactly (each stretch between two edges
    takes the value of the cell it lies in); otherwise, or past MAX_CELL_EDGES edges, the cells are sampled
    every eighth of a cell and the steps fall midway between samples."""
    v = line_vertices(line)
    d = np.diff(v, axis=0)
    seg_len = np.hypot(d[:, 0], d[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    length = float(cum[-1]) * dist_factor
    if length <= 0:
        return [], [], 0.0
    exact = sampler.same_crs and float(np.sum(np.abs(d[:, 0]) / sampler.cw + np.abs(d[:, 1]) / sampler.ch)) <= MAX_CELL_EDGES
    if exact:
        starts, ends, mids_x, mids_y = [], [], [], []
        for i in range(len(seg_len)):
            if seg_len[i] <= 0:
                continue
            (ax, ay), (dx, dy) = v[i], d[i]
            ts = [np.array([0.0, 1.0])]
            if dx != 0.0:
                a, b = sorted(((ax - sampler.x0) / sampler.cw, (ax + dx - sampler.x0) / sampler.cw))
                ks = np.arange(math.floor(a) + 1, math.ceil(b))
                ts.append((sampler.x0 + ks * sampler.cw - ax) / dx)
            if dy != 0.0:
                a, b = sorted(((sampler.y1 - ay) / sampler.ch, (sampler.y1 - ay - dy) / sampler.ch))
                ks = np.arange(math.floor(a) + 1, math.ceil(b))
                ts.append((sampler.y1 - ks * sampler.ch - ay) / dy)
            t = np.unique(np.clip(np.concatenate(ts), 0.0, 1.0))
            t = t[np.concatenate([[True], np.diff(t) > 1e-12])]
            if t[-1] < 1.0:
                t = np.append(t, 1.0)
            tm = (t[:-1] + t[1:]) / 2.0
            starts.append((cum[i] + t[:-1] * seg_len[i]) * dist_factor)
            ends.append((cum[i] + t[1:] * seg_len[i]) * dist_factor)
            mids_x.append(ax + tm * dx)
            mids_y.append(ay + tm * dy)
        s0, s1 = np.concatenate(starts), np.concatenate(ends)
        z = np.asarray(sampler.nearest(np.concatenate(mids_x), np.concatenate(mids_y)), dtype=float)
    else:
        step = max(cell_ft / 8.0 if math.isfinite(cell_ft) and cell_ft > 0 else length / 2000.0, length / 200_000.0)
        st = np.union1d(np.arange(0.0, length, step), [length])
        x, y = _stations_xy(v, cum, st, dist_factor)
        z = np.asarray(sampler.nearest(x, y), dtype=float)
        mid = (st[:-1] + st[1:]) / 2.0
        s0 = np.concatenate([[0.0], mid])
        s1 = np.concatenate([mid, [length]])
    z = np.where(np.isfinite(z), z, np.nan)
    have = np.isfinite(z)
    coverage = float(np.sum((s1 - s0)[have]) / length) if length > 0 else 0.0
    stations, zz = _steps(s0, s1, z)
    return stations, zz, coverage


def surface_profile(line: QgsGeometry, sampler: "RasterSampler", mode: str, step_ft: float, dist_factor: float,
                    cell_ft: float) -> Tuple[List[float], List[float], float]:
    """(stations, z, coverage) of another surface along the line: bilinear every `step_ft` ("smooth", as the
    ground), or flat across each cell ("cells", see cells_profile)."""
    if mode == "cells":
        return cells_profile(line, sampler, dist_factor, cell_ft)
    g = ground_profile(line, sampler, step_ft, dist_factor)
    return g.stations, g.z, g.coverage
