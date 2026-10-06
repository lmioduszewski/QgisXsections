"""Measure exported sheets from their pixels: the black plot frame and the grid lines.

Independent of the renderer: it only looks at the image. Ported from the scale spike
(scale_mpl/measure.py). Grid lines are found per column (or row, via a transpose) as runs of
grid-coloured pixels covering most of the plot height; positions are darkness-weighted
centroids (sub-pixel).

    rgb, info = load_png(path)
    m = measure(rgb, dpi=300, h_minor_in=0.1, v_minor_in=0.1, grid="gray")
    m["x"]["frame_px"], m["x"]["major_spacing_px"], m["y"]["px_per_in"], ...
"""
from __future__ import annotations

import struct
from typing import Dict, List, Tuple

import numpy as np


# ----------------------------------------------------------------------------- loading
def png_phys(path: str):
    """The PNG pHYs chunk: pixels per metre and the dpi it implies (None if absent)."""
    with open(path, "rb") as f:
        data = f.read()
    i = data.find(b"pHYs")
    if i < 0:
        return None
    x, y, unit = struct.unpack(">IIB", data[i + 4:i + 13])
    return dict(ppm_x=x, ppm_y=y, unit=unit, dpi_x=x * 0.0254, dpi_y=y * 0.0254)


def load_png(path: str):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(path)
    return np.asarray(im.convert("RGB")), dict(size=im.size, pil_dpi=im.info.get("dpi"), pHYs=png_phys(path))


def load_pdf_raster(path: str, dpi: int = 300, page: int = 1):
    """Rasterise one PDF page with GDAL's PDF driver (poppler/pdfium). Raises if unavailable."""
    from osgeo import gdal
    gdal.UseExceptions()
    src = path if page == 1 else f"PDF:{page}:{path}"
    ds = gdal.OpenEx(src, open_options=[f"DPI={dpi}"])
    rgb = np.dstack([ds.GetRasterBand(b).ReadAsArray() for b in (1, 2, 3)])
    return rgb, dict(size=(ds.RasterXSize, ds.RasterYSize), dpi=dpi)


# ----------------------------------------------------------------------------- raster analysis
def _longest_runs(mask: np.ndarray):
    """Per column: (length, start, end) of the longest True run."""
    n = mask.shape[1]
    L, S = np.zeros(n, int), np.zeros(n, int)
    for c0 in range(0, n, 512):
        m = mask[:, c0:c0 + 512].astype(np.int32)
        cs = np.cumsum(m, axis=0)
        base = np.maximum.accumulate(np.where(m == 0, cs, 0), axis=0)
        run = cs - base
        L[c0:c0 + 512] = run.max(axis=0)
        end = run.argmax(axis=0)
        S[c0:c0 + 512] = end - L[c0:c0 + 512] + 1
    return L, S, S + L


def _groups(idx: np.ndarray) -> List[np.ndarray]:
    if len(idx) == 0:
        return []
    return np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)


def frame_columns(rgb: np.ndarray) -> Tuple[float, float, int, int]:
    """Left/right frame lines (vertical black spines): (left_px, right_px, row0, row1).

    The two longest straight black vertical runs; positions are sub-pixel centroids.
    """
    black = rgb.max(axis=2) < 60
    L, S, E = _longest_runs(black)
    sel = np.where(L >= 0.6 * L.max())[0]
    lines = []
    for g in _groups(sel):
        c = g[np.argmax(L[g])]
        r0, r1 = S[c], E[c]
        cols = np.arange(max(g[0] - 3, 0), min(g[-1] + 4, rgb.shape[1]))
        w = np.median(255.0 - rgb[r0:r1, cols].mean(axis=2), axis=0)
        w = np.clip(w - 40.0, 0.0, None)                  # ignore light tints beside the frame (overlap shading)
        lines.append((float((w * (cols + 0.5)).sum() / w.sum()), int(L[c]), int(r0), int(r1)))
    lines = sorted(sorted(lines, key=lambda t: -t[1])[:2])
    if len(lines) < 2:
        raise AssertionError("plot frame not found")
    (left, _, a0, a1), (right, _, b0, b1) = lines
    return left, right, max(a0, b0), min(a1, b1)


def _grid_mask_darkness(a: np.ndarray, grid: str) -> np.ndarray:
    """Darkness (0-255) of pixels that look like grid ink, 0 elsewhere."""
    a = a.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    dark = 255 - a.mean(axis=2)
    if grid == "green":
        sel = (g - r > 10) & (g - b > 6)
    else:                                               # neutral grey, not black ink
        sel = (np.abs(r - g) < 10) & (np.abs(g - b) < 10) & (dark < 200)
    return np.where(sel, dark, 0.0)


def grid_columns(rgb: np.ndarray, grid: str = "gray", coverage: float = 0.75) -> List[Tuple[float, float]]:
    """(centroid_px, strength) of vertical grid lines in `rgb` (already cropped to the plot interior).

    A column counts when grid ink covers at least `coverage` of its rows, so labels, ticks and
    the anti-aliased edges of data lines (which cover only part of a column) do not register.
    """
    prof = np.zeros(rgb.shape[1])
    q = 100.0 * (1.0 - coverage)
    for c0 in range(0, rgb.shape[1], 1024):
        prof[c0:c0 + 1024] = np.percentile(_grid_mask_darkness(rgb[:, c0:c0 + 1024], grid), q, axis=0)
    out = []
    for grp in _groups(np.where(prof > 20)[0]):
        cols = np.arange(grp[0] - 1, grp[-1] + 2)
        cols = cols[(cols >= 0) & (cols < len(prof))]
        w = prof[cols]
        out.append((float((w * (cols + 0.5)).sum() / w.sum()), float(prof[grp].max())))
    return out


def analyse_axis(rgb: np.ndarray, dpi: float, minor_in: float, grid: str = "gray", pad: int = 8) -> Dict:
    """Frame and grid along the image's x direction (transpose the image for y)."""
    left, right, r0, r1 = frame_columns(rgb)
    sub = rgb[r0 + pad:r1 - pad, int(left) + pad:int(right) - pad + 1]
    lines = [(p + int(left) + pad, s) for p, s in grid_columns(sub, grid)]
    pos = np.array([p for p, _ in lines])
    strength = np.array([s for _, s in lines])
    if len(pos) == 0:
        raise AssertionError("no grid lines found")
    spread = strength.max() - strength.min()
    thr = (strength.max() + strength.min()) / 2.0 if spread > 15 else -1
    major = np.sort(pos[strength >= thr]) if thr >= 0 else np.sort(pos)
    minor = np.sort(pos[strength < thr]) if thr >= 0 else np.array([])
    allp = np.sort(np.r_[left, pos, right])
    step = minor_in * dpi
    k = np.round((allp - left) / step)
    slope, icpt = np.polyfit(k, allp, 1)
    resid = allp - (icpt + slope * k)
    d_major = np.diff(major) if len(major) > 1 else np.array([])
    return dict(frame_px=right - left, frame_left_px=left, frame_right_px=right,
                n_major=int(len(major)), n_minor=int(len(minor)), major_px=major.tolist(),
                major_spacing_px=d_major.tolist(), px_per_in=slope / minor_in,
                max_residual_px=float(np.abs(resid).max()))


def measure(rgb: np.ndarray, dpi: float, h_minor_in: float, v_minor_in: float, grid: str = "gray") -> Dict:
    """{'x': analyse_axis(...), 'y': analyse_axis(...)} for a sheet image."""
    x = analyse_axis(rgb, dpi, h_minor_in, grid)
    rot = np.ascontiguousarray(np.transpose(rgb, (1, 0, 2))[:, ::-1])   # rows become columns
    y = analyse_axis(rot, dpi, v_minor_in, grid)
    return dict(x=x, y=y, image_px=list(rgb.shape[1::-1]))


def normalised_major_spacings(spacings_px, major_px: float) -> List[float]:
    """Major spacings divided by the number of major intervals they span (a hidden line doubles one)."""
    out = []
    for d in spacings_px:
        n = max(1, round(d / major_px))
        out.append(d / n)
    return out
