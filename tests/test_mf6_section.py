"""MODFLOW 6 grids along the section line (xsections/core/mf6_section.py) and model surfaces in build_section.

Fixtures: tests/data/mf6 (see tests/test_mf6.py): disv_small lies in the tests/fixtures.py EPSG:2927 area and is
crossed by LINE; dis_rotated (origin X0 + 1000, Y0 + 800, ANGROT 30) is tested with lines laid out in its own model
coordinates; disu_small is crossed by LINE too. Overlapping DISU nodes and non-convex cells use small grids built
here. The real-data tests (F9_flowV1 with a synthetic flat DEM; the CDF section with the CDF DISU heads and the old
CDF DISV top) run only when XSECTIONS_REALDATA is set.
"""
import math
import os
import shutil
import struct
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

from tests.fixtures import CRS, LINE, REALDATA, ROOT, X0, Y0, default_settings, line_length, load_project, start_app
from tests.test_units import FTUS

start_app()

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject, QgsRasterLayer, QgsVectorLayer)

from xsections.core import mf6, mf6_section as MS  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.mf6 import CellVertices, Grid  # noqa: E402
from xsections.core.model import SURFACE_DEFAULTS, Settings  # noqa: E402
from xsections.render import figure as F  # noqa: E402
from xsections.render import scales as S  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data", "mf6")
DISV = os.path.join(DATA, "disv_small", "disv_small.disv.grb")
DISV_HDS = os.path.join(DATA, "disv_small", "disv_small.hds")
DIS = os.path.join(DATA, "dis_rotated", "dis_rotated.dis.grb")
DIS_HDS = os.path.join(DATA, "dis_rotated", "dis_rotated.hds")
DISU = os.path.join(DATA, "disu_small", "disu_small.disu.grb")
DISU_HDS = os.path.join(DATA, "disu_small", "disu_small.hds")
EPSG = QgsCoordinateReferenceSystem(CRS)
STANDARD = dict(compact_layout=False, fill_grid="off", sheet="custom", v_scale=50.0, h_scale=500.0)


def polyline(pts):
    return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])


def polygon(ring):
    pts = [QgsPointXY(float(x), float(y)) for x, y in ring]
    return QgsGeometry.fromPolygonXY([pts + pts[:1]])


def point_at(pts, station_ft):
    """x, y at a station (ft) along a polyline in EPSG:2927 (ftUS)."""
    d = station_ft / FTUS
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        L = math.dist((x1, y1), (x2, y2))
        if d <= L + 1e-9 or (x2, y2) == tuple(pts[-1]):
            t = d / L
            return x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        d -= L


def path_for(grid_path, pts, crs=EPSG):
    grid = mf6.read_grid(grid_path)
    return grid, MS.cell_path(MS.section_grid(grid, crs, crs), polyline(pts), FTUS)


def mf6_surface(path=DISV, var="top", **kw):
    return dict(SURFACE_DEFAULTS, source="mf6", mf6_path=path, mf6_var=var, **kw)


# dis_rotated: world coordinates of model coordinates (the transform written out here, independently of the reader)
ROT_O, ROT_A = (X0 + 1000.0, Y0 + 800.0), math.radians(30.0)


def rot_world(x, y):
    return (ROT_O[0] + x * math.cos(ROT_A) - y * math.sin(ROT_A), ROT_O[1] + x * math.sin(ROT_A) + y * math.cos(ROT_A))


def synthetic_grid(rings, top, bot, kind="disv", icelltype=None, name="synthetic"):
    """A one-layer grid (kind disv or disu) of the given rings (world coordinates, no origin)."""
    verts, idx, off = [], [], [0]
    for ring in rings:
        for p in ring:
            idx.append(len(verts))
            verts.append(p)
        off.append(len(idx))
    verts = np.asarray(verts, float)
    cx = np.array([np.mean([p[0] for p in r]) for r in rings])
    cy = np.array([np.mean([p[1] for p in r]) for r in rings])
    n = len(rings)
    return Grid(kind=kind, nlay=1, ncpl=n, top=np.asarray(top, float), botm=np.asarray(bot, float).reshape(1, n),
                idomain=np.ones((1, n), np.int32), verts=verts,
                iverts=CellVertices(np.asarray(off, np.int64), np.asarray(idx, np.int64)), length_units="feet",
                path=os.path.join(tempfile.gettempdir(), f"{name}.{kind}.grb"), cellx=cx, celly=cy,
                icelltype=None if icelltype is None else np.asarray(icelltype).reshape(1, n), source="grb")


def rotated_dis(ang, nrow=60, ncol=80, cell=25.0, xo=1245000.123, yo=745000.456):
    """A one-layer DIS grid at state-plane coordinates rotated by `ang` degrees; its top rises 2 ft a row and 0.5 ft
    a column, so the cells of two neighbouring rows differ."""
    verts, iv, cx, cy = mf6._dis_geometry(np.full(ncol, cell), np.full(nrow, cell))
    n = nrow * ncol
    r, c = np.divmod(np.arange(n), ncol)
    return Grid(kind="dis", nlay=1, ncpl=n, nrow=nrow, ncol=ncol, top=100.0 + 2.0 * r + 0.5 * c,
                botm=np.full((1, n), -10.0), idomain=np.ones((1, n), np.int32), verts=verts, iverts=iv, xorigin=xo,
                yorigin=yo, angrot=ang, length_units="feet",
                path=os.path.join(tempfile.gettempdir(), f"rotated_{ang}.dis.grb"), cellx=cx, celly=cy, source="grb")


def copy_model(name="disv_small"):
    tmp = os.path.join(tempfile.mkdtemp(prefix="mf6sec_"), name)
    shutil.copytree(os.path.join(DATA, name), tmp)
    return tmp


def write_heads(path, records, ncol):
    """A double-precision head file: records = [(kstp, kper, totim, ilay, values)]."""
    with open(path, "wb") as fh:
        for kstp, kper, totim, ilay, values in records:
            fh.write(struct.pack("<iidd16siii", kstp, kper, totim, totim, b"            HEAD", ncol, 1, ilay))
            fh.write(np.asarray(values, "<f8").tobytes())
    return path


# ===================================================================================================== intervals
class Intervals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def check_against_geos(self, grid, pts, path):
        """Every piece: midpoint inside its cell, ends on its cell's boundary (or the line's ends); per cell the
        pieces add up to GEOS's intersection of the line with the cell; pieces + gaps = the line."""
        line = polyline(pts)
        length = line.length() * FTUS
        rings = [grid.cell_vertices_world(i) for i in range(grid.ncpl)]
        polys = [polygon(r) for r in rings]
        bounds = [p.constGet().boundary() for p in polys]
        s0, s1, cell = path.s0, path.s1, path.cell
        self.assertTrue(np.all(s1 > s0))
        self.assertTrue(np.all(s0[1:] >= s1[:-1]), "sorted, not overlapping")
        for a, b, c in path.intervals():
            mid = QgsGeometry.fromPointXY(QgsPointXY(*point_at(pts, (a + b) / 2.0)))
            self.assertTrue(polys[c].contains(mid), (a, b, c))
            for s in (a, b):
                if min(s, length - s) < 1e-6:
                    continue
                p = QgsGeometry.fromPointXY(QgsPointXY(*point_at(pts, s)))
                self.assertLess(QgsGeometry(bounds[c].clone()).distance(p), 1e-6, (s, c))
        for c in range(grid.ncpl):
            want = line.intersection(polys[c]).length() * FTUS
            got = float(np.sum((s1 - s0)[cell == c]))
            self.assertAlmostEqual(got, want, delta=1e-6, msg=f"cell {c}")
        gaps = [(0.0, s0[0])] + list(zip(s1[:-1], s0[1:])) + [(s1[-1], length)]
        for a, b in gaps:
            if b - a > 1e-6:
                mid = QgsGeometry.fromPointXY(QgsPointXY(*point_at(pts, (a + b) / 2.0)))
                self.assertFalse(any(p.contains(mid) for p in polys), (a, b))
        self.assertAlmostEqual(path.covered() + sum(max(b - a, 0.0) for a, b in gaps), length, delta=1e-6)

    def test_fixture_line_through_disv(self):
        grid, path = path_for(DISV, LINE)
        self.assertFalse(path.overlaps)
        self.check_against_geos(grid, LINE, path)
        self.assertEqual(path.s0[0], 0.0)                               # LINE starts inside the grid
        exit_ft = (2500.0 + math.hypot(400.0, 120.0)) * FTUS              # it leaves at x = X0 + 3400
        self.assertAlmostEqual(path.s1[-1], exit_ft, delta=1e-6)
        self.assertAlmostEqual(path.covered(), exit_ft, delta=1e-6)       # no gap inside the grid
        self.assertGreaterEqual(len(path), 8)

    def test_cell_crossed_twice(self):
        # leaves cell (row 0, col 0) eastwards, turns, comes back into it
        pts = [(X0 + 500.0, Y0 + 2500.0), (X0 + 1100.0, Y0 + 2500.0), (X0 + 1100.0, Y0 + 2450.0),
               (X0 + 600.0, Y0 + 2450.0)]
        grid, path = path_for(DISV, pts)
        self.check_against_geos(grid, pts, path)
        first = path.cell[0]
        self.assertEqual([c for c in path.cell].count(first), 2)
        self.assertEqual(path.cell[-1], first)
        self.assertAlmostEqual(path.s1[0], 400.0 * FTUS, delta=1e-6)     # x = 900: its east edge
        self.assertAlmostEqual(path.s0[-1], (600.0 + 50.0 + 200.0) * FTUS, delta=1e-6)

    def test_non_convex_cell(self):
        u = [(0, 0), (0, 200), (50, 200), (50, 50), (150, 50), (150, 200), (200, 200), (200, 0)]
        block = [(250, 0), (250, 200), (400, 200), (400, 0)]
        grid = synthetic_grid([[(X0 + x, Y0 + y) for x, y in u], [(X0 + x, Y0 + y) for x, y in block]],
                              [10.0, 12.0], [0.0, 0.0])
        pts = [(X0 - 50.0, Y0 + 150.0), (X0 + 450.0, Y0 + 150.0)]
        path = MS.cell_path(MS.section_grid(grid, EPSG, EPSG), polyline(pts), FTUS)
        self.check_against_geos(grid, pts, path)
        want = [(50, 100, 0), (200, 250, 0), (300, 450, 1)]
        self.assertEqual(len(path), 3)
        for (a, b, c), (wa, wb, wc) in zip(path.intervals(), want):
            self.assertAlmostEqual(a, wa * FTUS, delta=1e-6)
            self.assertAlmostEqual(b, wb * FTUS, delta=1e-6)
            self.assertEqual(c, wc)
        # cells profile: the U's two arms, a break across its notch and between the cells
        s0, s1, v, cells = MS.choose(path, np.array([10.0, 12.0]), "top", grid)
        st, z, cov = MS.model_profile(s0, s1, v, "cells", path.length)
        self.assertAlmostEqual(cov, 250.0 / 500.0, places=9)
        self.assertEqual([round(s / FTUS, 6) for s in st], [50, 100, 100, 200, 200, 250, 250, 300, 300, 450])
        self.assertEqual((z[0], z[1]), (10.0, 10.0))
        self.assertTrue(math.isnan(z[2]) and math.isnan(z[3]) and math.isnan(z[6]) and math.isnan(z[7]))
        self.assertEqual((z[4], z[5], z[8], z[9]), (10.0, 10.0, 12.0, 12.0))

    def test_line_along_shared_edges(self):
        # y = Y0 + 2100 is the edge between rows 1 and 2, through quads and the split (triangle) cells
        pts = [(X0 + 450.0, Y0 + 2100.0), (X0 + 3350.0, Y0 + 2100.0)]
        grid, path = path_for(DISV, pts)
        self.assertFalse(path.overlaps)
        self.assertAlmostEqual(path.covered(), path.length, delta=1e-6)   # every stretch in exactly one cell
        self.assertTrue(np.all(path.s0[1:] == path.s1[:-1]))
        for a, b, c in path.intervals():
            mid = QgsGeometry.fromPointXY(QgsPointXY(*point_at(pts, (a + b) / 2.0)))
            self.assertLess(polygon(grid.cell_vertices_world(c)).distance(mid), 1e-6)
        # along a diagonal edge of the split cells too
        d = [(X0 + 1400.0, Y0 + 2350.0), (X0 + 1900.0, Y0 + 2100.0)]
        _, path = path_for(DISV, d)
        self.assertEqual(len(path), 1)
        self.assertAlmostEqual(path.covered(), path.length, delta=1e-6)

    def test_line_along_rotated_grid_lines(self):
        """A line snapped to the corners of a rotated structured grid along a row or column boundary (the corners
        between are a rounding error off it): every stretch in exactly one cell, all of them on the line's left, no
        gaps, no overlaps, a smooth profile without breaks; along the outer boundary all out (grid on the right) or
        all in (grid on the left)."""
        for ang in (45.0, 17.3, -12.5, 30.0, 0.0):
            g = rotated_dis(ang)
            V = np.asarray(g.verts_world)
            n1 = g.ncol + 1
            sg = MS.section_grid(g, EPSG, EPSG)
            cases = [("row line 30 eastward", V[30 * n1], V[30 * n1 + g.ncol], ("row", 29)),
                     ("column line 40 southward", V[40], V[g.nrow * n1 + 40], ("col", 40)),
                     ("outer row line 0 westward", V[g.ncol], V[0], ("row", 0)),
                     ("outer row line 0 eastward", V[0], V[g.ncol], None)]
            for what, a, b, side in cases:
                with self.subTest(ang=ang, line=what):
                    cp = MS.cell_path(sg, polyline([tuple(a), tuple(b)]), FTUS)
                    if side is None:
                        self.assertEqual(len(cp), 0)
                        continue
                    rows, cols = np.divmod(cp.cell, g.ncol)
                    self.assertFalse(cp.overlaps)
                    self.assertAlmostEqual(cp.covered(), cp.length, delta=1e-6)
                    self.assertTrue(np.all(cp.s0[1:] == cp.s1[:-1]))
                    if side[0] == "row":
                        self.assertEqual((len(cp), set(rows.tolist())), (g.ncol, {side[1]}))
                    else:
                        self.assertEqual((len(cp), set(cols.tolist())), (g.nrow, {side[1]}))
                    s0, s1, v, _ = MS.choose(cp, g.top, "top", g)
                    st, z, cov = MS.model_profile(s0, s1, v, "smooth", cp.length)
                    self.assertFalse(any(math.isnan(x) for x in z))
                    self.assertAlmostEqual(cov, 1.0, places=9)

    def test_line_off_the_grid(self):
        _, path = path_for(DISV, [(X0 + 5000.0, Y0 + 100.0), (X0 + 6000.0, Y0 + 300.0)])
        self.assertEqual(len(path), 0)
        self.assertEqual(path.covered(), 0.0)

    def test_rotated_dis(self):
        """A line along model row 2 (model y = 95), laid out with the rotation written out independently: the cell
        edges fall at the DELR boundaries, the cells are row 2's, the world transform is the reader's."""
        pts = [rot_world(-50.0, 95.0), rot_world(600.0, 95.0)]
        grid, path = path_for(DIS, pts)
        self.check_against_geos(grid, pts, path)
        self.assertEqual(list(path.cell), [4, 5, 6, 7])                  # row 2 (row-major, row 1 north)
        edges = [50.0, 150.0, 300.0, 400.0, 600.0]
        self.assertTrue(np.allclose(path.s0, np.array(edges[:-1]) * FTUS, atol=1e-6))
        self.assertTrue(np.allclose(path.s1, np.array(edges[1:]) * FTUS, atol=1e-6))
        # transformed vertices: the model's lower-left corner is the origin, the upper-left is 190 ft up the
        # rotated y axis
        sg = MS.section_grid(grid, EPSG, EPSG)
        xy = np.column_stack([sg.x, sg.y])
        for corner in (rot_world(0.0, 0.0), rot_world(0.0, 190.0), rot_world(550.0, 0.0)):
            self.assertLess(np.min(np.hypot(xy[:, 0] - corner[0], xy[:, 1] - corner[1])), 1e-6)

    def test_crs_transform(self):
        """The model in EPSG:2927 drawn on a section in UTM 10N (metres): the vertices are transformed once and the
        cell edges cross the line where GEOS says (in the section CRS)."""
        utm = QgsCoordinateReferenceSystem("EPSG:32610")
        grid = mf6.read_grid(DISV)
        ct = QgsCoordinateTransform(EPSG, utm, QgsProject.instance())
        line = polyline(LINE)
        line.transform(ct)
        pts = [(v.x(), v.y()) for v in line.vertices()]
        before = MS.STATS["transforms"]
        sg = MS.section_grid(grid, EPSG, utm)
        self.assertTrue(sg.transformed)
        self.assertIs(MS.section_grid(grid, EPSG, utm), sg)              # cached: transformed once
        self.assertEqual(MS.STATS["transforms"], before + 1)
        path = MS.cell_path(sg, line, 1.0 / 0.3048)
        for i, (a, b, c) in enumerate(path.intervals()):
            ring = [ct.transform(QgsPointXY(x, y)) for x, y in grid.cell_vertices_world(c)]
            poly = QgsGeometry.fromPolygonXY([ring + ring[:1]])
            want = line.intersection(poly).length() / 0.3048
            got = float(np.sum((path.s1 - path.s0)[path.cell == c]))
            self.assertAlmostEqual(got, want, delta=1e-4)
        _, ref = path_for(DISV, LINE)
        self.assertEqual(list(path.cell), list(ref.cell))
        self.assertAlmostEqual(path.covered(), ref.covered(), delta=1e-3 * ref.covered())   # projection scale


# ===================================================================================================== profiles
class Profiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()
        cls.row2 = [rot_world(-50.0, 95.0), rot_world(600.0, 95.0)]
        cls.row1 = [rot_world(-50.0, 165.0), rot_world(600.0, 165.0)]

    def profile(self, pts, var, mode, layer=1, path=DIS, head=None):
        grid, cp = path_for(path, pts)
        hf = mf6.HeadFile(head) if head else None
        kper, kstp = hf.resolve("last") if hf else (0, 0)
        raw = MS.cell_values(grid, var, layer, hf, kper, kstp)
        s0, s1, v, cells = MS.choose(cp, raw, var, grid)
        st, z, cov = MS.model_profile(s0, s1, v, mode, cp.length)
        return [s / FTUS for s in st], z, cov, cells

    def test_cells_and_smooth(self):
        st, z, cov, _ = self.profile(self.row2, "top", "cells")          # top of row 2: 520 + 2c - 1
        self.assertTrue(np.allclose(st, [50, 150, 150, 300, 300, 400, 400, 600], atol=1e-6))
        self.assertEqual(z, [519.0, 519.0, 521.0, 521.0, 523.0, 523.0, 525.0, 525.0])
        self.assertAlmostEqual(cov, 550.0 / 650.0, places=9)
        st, z, cov, _ = self.profile(self.row2, "top", "smooth")         # through the midpoints, ends held flat
        self.assertTrue(np.allclose(st, [50, 100, 225, 350, 500, 600], atol=1e-6))
        self.assertEqual(z, [519.0, 519.0, 521.0, 523.0, 525.0, 525.0])

    def test_idomain_masks_and_breaks_the_line(self):
        # layer 2, row 1, column 3 is inactive: its bottom is no value; the line breaks there
        st, z, cov, _ = self.profile(self.row1, "botm", "cells", layer=2)
        self.assertTrue(np.allclose(st, [50, 150, 150, 300, 300, 400, 400, 600], atol=1e-6))
        self.assertEqual((z[0], z[2], z[6]), (400.0, 399.0, 397.0))
        self.assertTrue(math.isnan(z[4]) and math.isnan(z[5]))
        self.assertAlmostEqual(cov, 450.0 / 650.0, places=9)
        st, z, cov, _ = self.profile(self.row1, "botm", "smooth", layer=2)
        self.assertTrue(np.allclose(st, [50, 100, 225, 300, 350, 400, 500, 600], atol=1e-6))
        self.assertEqual(z[:4], [400.0, 400.0, 399.0, 399.0])
        self.assertTrue(math.isnan(z[4]))
        self.assertEqual(z[5:], [397.0, 397.0, 397.0])
        # the same cell in layer 1 is active
        st, z, _, _ = self.profile(self.row1, "botm", "cells", layer=1)
        self.assertFalse(any(math.isnan(v) for v in z))

    def test_disv_idomain_top(self):
        # disv_small: IDOMAIN 0 at layer 1 of the cell in row 3, column 1 (x 900-1400, y 1600-1850): the model top
        # there is the top of its uppermost active cell (layer 2), i.e. layer 1's bottom
        pts = [(X0 + 450.0, Y0 + 1700.0), (X0 + 1850.0, Y0 + 1700.0)]
        grid, cp = path_for(DISV, pts)
        raw = MS.cell_values(grid, "top", 1)
        s0, s1, v, cells = MS.choose(cp, raw, "top", grid)
        self.assertEqual(len(cells), 3)
        masked = int(cells[1])
        self.assertEqual(int(grid.idomain[0, masked]), 0)
        self.assertEqual(v[1], grid.botm[0, masked])
        self.assertEqual(v[0], grid.top[cells[0]])
        raw = MS.cell_values(grid, "botm", 1)
        self.assertTrue(math.isnan(raw[masked]))

    def test_head_and_water_table(self):
        grid, cp = path_for(DISV, LINE)
        hf = mf6.HeadFile(DISV_HDS)
        kper, kstp = hf.resolve("last")
        heads = hf.read_layers(kper, kstp)
        h1 = MS.cell_values(grid, "head", 1, hf, kper, kstp)
        wt = MS.cell_values(grid, "wt", 1, hf, kper, kstp)
        cells = cp.cell
        dry = [c for c in cells if math.isnan(heads[0, c])]
        wet = [c for c in cells if not math.isnan(heads[0, c])]
        self.assertTrue(dry and wet, "layer 1 is dry in the east of the line")
        for c in wet:
            self.assertEqual(wt[c], heads[0, c])
            self.assertEqual(h1[c], heads[0, c])
        for c in dry:
            self.assertEqual(wt[c], heads[1, c])                       # the next layer down
            self.assertTrue(math.isnan(h1[c]))
        st, z, cov, _ = self.profile(LINE, "head", "smooth", path=DISV, head=DISV_HDS)
        st2, z2, cov2, _ = self.profile(LINE, "wt", "smooth", path=DISV, head=DISV_HDS)
        self.assertFalse(any(math.isnan(v) for v in z2))
        self.assertGreater(cov2, cov)
        self.assertLess(max(s for s, v in zip(st, z) if math.isfinite(v)), st2[-1])   # layer 1 ends where dry
        # cells mode: a dry cell between wet ones breaks the line (nan), at the cell's edges
        raw = MS.cell_values(grid, "head", 1, hf, kper, kstp).copy()
        raw[cells[2]] = np.nan
        s0, s1, v, _ = MS.choose(cp, raw, "head", grid)
        stc, zc, _ = MS.model_profile(s0, s1, v, "cells", cp.length)
        k = stc.index(float(s0[2]))
        self.assertTrue(math.isnan(zc[k + 1]) and stc[k + 1] == stc[k] and stc[k + 2] == float(s1[2]))
        sts, zs, _ = MS.model_profile(s0, s1, v, "smooth", cp.length)
        k = [i for i, val in enumerate(zs) if math.isnan(val)]
        self.assertEqual(len(k), 1)
        self.assertAlmostEqual(sts[k[0]], (s0[2] + s1[2]) / 2.0)                    # the break midway
        self.assertEqual((sts[k[0] - 1], sts[k[0] + 1]), (float(s0[2]), float(s1[2])))   # held flat to the edges

    def test_newton_water_table(self):
        # dis_rotated runs with NEWTON: dry layer-1 cells keep a head below their bottom; the water table skips them
        grid = mf6.read_grid(DIS)
        hf = mf6.HeadFile(DIS_HDS)
        heads = hf.read_layers(*hf.resolve("last"))
        wt = MS.cell_values(grid, "wt", 1, hf, *hf.resolve("last"))
        below = heads[0] <= grid.botm[0]
        self.assertTrue(below.any())
        self.assertTrue(np.allclose(wt[below], heads[1][below]))
        self.assertTrue(np.allclose(wt[~below], heads[0][~below]))

    def test_newton_head_leaves_dry_cells_out(self):
        # dis_rotated (NEWTON): row 2's layer-1 cells 6 and 7 are dry with heads below their bottoms; the layer-1
        # head breaks there as it does at HDRY cells (the water table takes layer 2 there)
        st, z, cov, cells = self.profile(self.row2, "head", "cells", head=DIS_HDS)
        self.assertEqual(list(cells), [4, 5, 6, 7])
        finite = [s for s, v in zip(st, z) if math.isfinite(v)]
        self.assertTrue(finite and min(finite) >= 50.0 - 1e-6 and max(finite) <= 300.0 + 1e-6)
        self.assertAlmostEqual(cov, 250.0 / 650.0, places=9)
        _, zw, covw, _ = self.profile(self.row2, "wt", "cells", head=DIS_HDS)
        self.assertAlmostEqual(covw, 550.0 / 650.0, places=9)

    def test_overlapping_disu_nodes(self):
        """Two node layers: A and B on top (x 0-100, 100-200), C under both (x 0-200)."""
        rings = [[(X0, Y0), (X0, Y0 + 100), (X0 + 100, Y0 + 100), (X0 + 100, Y0)],
                 [(X0 + 100, Y0), (X0 + 100, Y0 + 100), (X0 + 200, Y0 + 100), (X0 + 200, Y0)],
                 [(X0, Y0), (X0, Y0 + 100), (X0 + 200, Y0 + 100), (X0 + 200, Y0)]]
        grid = synthetic_grid(rings, [50.0, 52.0, 40.0], [40.0, 41.0, 0.0], kind="disu", icelltype=[1, 1, 1])
        pts = [(X0 - 50.0, Y0 + 50.0), (X0 + 250.0, Y0 + 50.0)]
        cp = MS.cell_path(MS.section_grid(grid, EPSG, EPSG), polyline(pts), FTUS)
        self.assertTrue(cp.overlaps)
        self.assertEqual(len(cp), 2)
        self.assertEqual([sorted(cp.cover_cells[cp.cover_offsets[i]:cp.cover_offsets[i + 1]]) for i in range(2)],
                         [[0, 2], [1, 2]])

        def pick(values, var):
            s0, s1, v, cells = MS.choose(cp, np.asarray(values, float), var, grid)
            return [round(s / FTUS, 6) for s in s0], list(cells), list(v)

        self.assertEqual(pick(grid.top, "top")[1:], ([0, 1], [50.0, 52.0]))        # the higher top
        self.assertEqual(pick(grid.botm[0], "botm"), ([50.0], [2], [0.0]))           # the lower bottom, merged
        nan = math.nan
        self.assertEqual(pick([45.0, nan, 30.0], "head")[1], [0, 2])                 # highest node with a head
        self.assertEqual(pick([39.0, 44.0, 30.0], "head")[1], [0, 1])
        self.assertEqual(pick([39.0, 44.0, 30.0], "wt")[1], [2, 1])                  # A is below its bottom: dry
        self.assertEqual(pick([39.0, 40.5, 30.0], "wt")[1], [2])                     # both dry: C, merged
        self.assertEqual(pick([39.0, 40.5, nan], "wt")[1], [0, 1])                   # nothing wet: the lowest
        # end to end through model_surface: named "Head", the overlap warned once
        tmp = tempfile.mkdtemp(prefix="mf6sec_")
        hds = write_heads(os.path.join(tmp, "stack.hds"), [(1, 1, 1.0, 1, [45.0, nan, 30.0])], 3)
        prj, dem, pts_layer, lines = load_project()
        s = Settings(dem_layer_id=dem.id(), line_wkt=polyline([(X0 + 100.0, Y0 + 50.0), (X0 + 900.0, Y0 + 50.0)])
                     .asWkt(), line_crs_authid=CRS)
        s.surfaces = [mf6_surface(grid.path, "head", mf6_head_path=hds),
                      mf6_surface(grid.path, "top", name="Stack top")]
        with mock.patch.object(MS, "read_grid", return_value=grid):
            m = build_section(s, prj)
        self.assertEqual([sp.name for sp in m.surfaces], ["Head", "Stack top"])
        self.assertEqual(sum("DISU nodes overlap" in w for w in m.warnings), 1)

    def test_units(self):
        tmp = tempfile.mkdtemp(prefix="mf6sec_")
        for name in os.listdir(os.path.dirname(DISV)):
            shutil.copy2(os.path.join(os.path.dirname(DISV), name), tmp)
        grb = os.path.join(tmp, "disv_small.disv.grb")
        text = os.path.join(tmp, "disv_small.disv")
        with open(text) as fh:
            body = fh.read()
        with open(text, "w") as fh:
            fh.write(body.replace("LENGTH_UNITS  feet", "LENGTH_UNITS  meters"))
        grid = mf6.read_grid(grb)
        self.assertEqual(MS.model_z_units(grid, "auto", EPSG)[:3:2], ("m", "detected"))
        self.assertAlmostEqual(MS.model_z_units(grid, "auto", EPSG)[1], 1 / 0.3048)
        self.assertEqual(MS.model_z_units(grid, "ft", EPSG), ("ft", 1.0, "set"))
        self.assertAlmostEqual(MS.model_z_units(grid, "ftUS", EPSG)[1], FTUS)
        os.remove(text)                                               # no LENGTH_UNITS: the CRS units (ftUS)
        grid = mf6.read_grid(grb)
        self.assertEqual(grid.length_units, "unknown")
        units, f, how = MS.model_z_units(grid, "auto", EPSG)
        self.assertEqual((units, how), ("ftUS", "crs"))
        self.assertEqual(MS.model_z_units(grid, "auto", QgsCoordinateReferenceSystem())[::2], ("ft", "default"))
        # in a section: metres are converted, the assumption is warned about
        prj, dem, pts, lines = load_project()
        s = default_settings(prj, dem, pts, lines,
                             surfaces=[mf6_surface(DISV, "botm", mf6_layer=3),
                                       mf6_surface(DISV, "botm", mf6_layer=3, z_units="m"),
                                       mf6_surface(grb, "botm", mf6_layer=3, name="No units")])
        m = build_section(s, prj)
        ft, metres, assumed = m.surfaces
        self.assertEqual(set(ft.z), {400.0})
        self.assertAlmostEqual(metres.z[0], 400.0 / 0.3048, places=6)
        self.assertAlmostEqual(assumed.z[0], 400.0 * FTUS, places=6)
        self.assertTrue(any("“No units”" in w and "LENGTH_UNITS" in w and "US survey feet" in w for w in m.warnings))


# ===================================================================================================== build_section
class ModelSurfacesInTheSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_wells_surfaces import make_raster
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.wt = QgsRasterLayer(make_raster(offset=110.0), "wt_2024")
        cls.prj.addMapLayer(cls.wt)

    def settings(self, deep_in_range=True, extra=(), **kw):
        surfaces = [dict(SURFACE_DEFAULTS, layer_id=self.wt.id(), name="Water table 2024", style="dash"),
                    mf6_surface(DISV, "top"),
                    mf6_surface(DISV, "botm", mf6_layer=3, mode="cells", in_range=deep_in_range),
                    mf6_surface(DISV, "head", mf6_layer=1, mf6_head_path=DISV_HDS, mf6_time="2,2"),
                    mf6_surface(DISV, "wt", mf6_head_path=DISV_HDS, mf6_crs=CRS, marks=True),
                    mf6_surface(DISU, "head", mf6_head_path=DISU_HDS)] + list(extra)
        return default_settings(self.prj, self.dem, self.pts, self.lines, surfaces=surfaces, **kw)

    def test_names_details_and_drawing(self):
        m = build_section(self.settings(), self.prj)
        self.assertEqual([sp.name for sp in m.surfaces],
                         ["Water table 2024", "Model top", "Layer 3 bottom", "Layer 1 head (SP 2, step 2)",
                          "Water table (SP 3)", "Head (SP 2)"])
        raster, top, deep, head, wt, disu = m.surfaces
        self.assertEqual(raster.source, "raster")
        self.assertEqual(raster.detail, "")
        self.assertEqual([sp.source for sp in m.surfaces[1:]], ["mf6"] * 5)
        self.assertEqual((top.layer_name, top.band, deep.band, head.band), ("disv_small", 1, 3, 1))
        self.assertEqual(deep.mode, "cells")
        self.assertEqual(len(deep.stations) % 2, 0)
        self.assertTrue(wt.marks)
        self.assertAlmostEqual(top.coverage, (2500.0 + math.hypot(400.0, 120.0)) / line_length(), places=6)
        notes = F.surfaces_sources(m)
        for text in ("Water table 2024 from wt_2024", "Model top from disv_small.disv.grb",
                     "Layer 3 bottom from disv_small.disv.grb (flat across each cell)",
                     "Layer 1 head from disv_small.hds (SP 2, step 2)", "Water table from disv_small.hds (SP 3, step 2)",
                     "Head from disu_small.hds (SP 2, step 1)"):
            self.assertIn(text, notes)
        legend = [e.text for e in S.legend_entries(m, self.settings())]
        self.assertIn("Layer 1 head (SP 2, step 2)", legend)
        self.assertIn("Water table (SP 3)", legend)
        # drawn as surface lines (with nan gaps), listed in the legend and the notes of the sheet
        from matplotlib.figure import Figure
        s = self.settings(**STANDARD)
        p = S.plan(m, s)
        fig = Figure()
        F.draw_page(fig, m, s, p, p.pages[0])
        lines = [a for a in fig.axes[0].get_children() if a.get_gid() == F.SURFACE_GID]
        self.assertEqual(len(lines), 6)
        texts = " ".join(t.get_text() for t in fig.texts)
        self.assertIn("Water table (SP 3)", texts)
        self.assertIn("Layer 1 head from disv_small.hds", texts)
        # the heads match the head file in the cell under each midpoint
        hf = mf6.HeadFile(DISV_HDS)
        h = hf.read(1, 2, 2)
        grid = mf6.read_grid(DISV)
        polys = [polygon(grid.cell_vertices_world(i)) for i in range(grid.ncpl)]
        st, z = np.asarray(head.stations), np.asarray(head.z)
        checked = 0
        for i in range(len(st)):                     # midpoints (inside one cell); points on cell edges are skipped
            if not math.isfinite(z[i]):
                continue
            p = QgsGeometry.fromPointXY(QgsPointXY(*point_at(LINE, st[i])))
            inside = [c for c in range(grid.ncpl) if polys[c].contains(p)]
            if len(inside) == 1:
                self.assertAlmostEqual(z[i], h[inside[0]], places=9)
                checked += 1
        self.assertGreater(checked, 5)

    def test_custom_name_detail(self):
        s = self.settings(extra=[mf6_surface(DISV, "head", name="Upper aquifer", mf6_layer=2,
                                             mf6_head_path=DISV_HDS, mf6_time="1,1")])
        m = build_section(s, self.prj)
        self.assertEqual(m.surfaces[-1].name, "Upper aquifer")
        self.assertEqual(m.surfaces[-1].detail, "Upper aquifer (layer 2 head from disv_small.hds, SP 1, step 1)")

    def test_cells_mode_in_one_parenthesis(self):
        """In cells mode the notes say "flat across each cell" inside the surface's one parenthesis."""
        s = self.settings(extra=[mf6_surface(DISV, "head", name="Upper aquifer", mf6_layer=2, mode="cells",
                                             mf6_head_path=DISV_HDS, mf6_time="1,1"),
                                 mf6_surface(DISV, "head", mf6_layer=1, mf6_head_path=DISV_HDS, mf6_time="2,1",
                                             mode="cells"),
                                 mf6_surface(DISV, "top", name="Grid top", mode="cells")])
        m = build_section(s, self.prj)
        self.assertEqual([sp.detail for sp in m.surfaces[-3:]],
                         ["Upper aquifer (layer 2 head from disv_small.hds, SP 1, step 1; flat across each cell)",
                          "Layer 1 head from disv_small.hds (SP 2, step 1; flat across each cell)",
                          "Grid top (model top from disv_small.disv.grb; flat across each cell)"])
        notes = F.surfaces_sources(m)
        self.assertIn("Layer 3 bottom from disv_small.disv.grb (flat across each cell)", notes)
        self.assertNotIn(") (", notes)

    def test_a_stress_period_means_its_last_saved_step(self):
        """mf6_time "2" (or "2,0") is stress period 2's last saved step, whatever its number: after a run in which
        adaptive time stepping ended the period at another step the surface is still drawn (a fixed "2,3" is left
        out with a warning)."""
        from xsections.core.model import clean_surface
        self.assertEqual([clean_surface(dict(mf6_time=t))["mf6_time"] for t in
                          ("2", "2,0", " 2 , 3 ", "16,016", "last", "LAST", "x", "2,3,4", "0", "")],
                         ["2", "2", "2,3", "16,16", "last", "last", "last", "last", "last", "last"])
        folder = copy_model()
        grb, hds = os.path.join(folder, "disv_small.disv.grb"), os.path.join(folder, "disv_small.hds")
        s = default_settings(self.prj, self.dem, self.pts, self.lines,
                             surfaces=[mf6_surface(grb, "head", mf6_head_path=hds, mf6_time="2"),
                                       mf6_surface(grb, "head", mf6_head_path=hds, mf6_time="2,3", name="Fixed")])
        m = build_section(s, self.prj)
        self.assertEqual([sp.name for sp in m.surfaces], ["Layer 1 head (SP 2, step 3)", "Fixed"])
        with open(hds, "rb") as fh:                         # run again: SP 2 now ends at step 4
            data = bytearray(fh.read())
        rec = 52 + 28 * 8
        for k in (12, 13, 14):
            data[k * rec:k * rec + 4] = struct.pack("<i", 4)
        with open(hds, "wb") as fh:
            fh.write(data)
        os.utime(hds, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
        m = build_section(s, self.prj)
        self.assertEqual([sp.name for sp in m.surfaces], ["Layer 1 head (SP 2, step 4)"])
        self.assertIn("“Fixed”: Time step 3 of stress period 2 is not saved in disv_small.hds (saved steps: 1-2, 4)",
                      "\n".join(m.warnings))

    def test_head_file_being_written(self):
        """A head file the model is still writing ends inside its newest time step: "last" is the newest complete
        time (never a water table from the layers written so far), and the sheet's warnings say so once."""
        folder = copy_model()
        grb, hds = os.path.join(folder, "disv_small.disv.grb"), os.path.join(folder, "disv_small.hds")
        with open(DISV_HDS, "rb") as fh:
            data = fh.read()
        with open(hds, "wb") as fh:
            fh.write(data[:16 * (52 + 28 * 8) + 100])           # SP 3, step 2: layer 1 and part of layer 2
        s = default_settings(self.prj, self.dem, self.pts, self.lines,
                             surfaces=[mf6_surface(grb, "wt", mf6_head_path=hds),
                                       mf6_surface(grb, "head", mf6_layer=3, mf6_head_path=hds)])
        m = build_section(s, self.prj)
        self.assertEqual([sp.name for sp in m.surfaces], ["Water table (SP 2, step 3)", "Layer 3 head (SP 2, step 3)"])
        self.assertEqual(sum("disv_small.hds is still being written (is the model running?): the last complete time "
                             "step (SP 2, step 3) is shown." == w for w in m.warnings), 1)
        full = default_settings(self.prj, self.dem, self.pts, self.lines,
                                surfaces=[mf6_surface(DISV, "wt", mf6_head_path=DISV_HDS, mf6_time="2,3")])
        self.assertEqual(m.surfaces[0].z, build_section(full, self.prj).surfaces[0].z)

    def test_one_bad_model_file_never_stops_the_section(self):
        """A grid naming a vertex it does not have and an unexpected error (a reader bug) each leave
        out their own surface with a warning; the ground and the other surfaces are drawn."""
        folder = copy_model()
        os.remove(os.path.join(folder, "disv_small.disv.grb"))
        text = os.path.join(folder, "disv_small.disv")
        with open(text) as fh:
            s_text = fh.read()
        with open(text, "w") as fh:
            fh.write(s_text.replace("  3  1201650.0  652475.0  4  3  4  11  10", "  3  1201650.0  652475.0  4  3  99  11  10"))
        s = self.settings(extra=[mf6_surface(text, "top", name="Bad vertices")])
        m = build_section(s, self.prj)
        self.assertEqual(len(m.surfaces), 6)
        self.assertIn("Surface “Bad vertices”: disv_small.disv: CELL2D names vertex 99 but NVERT is 35. Left out.",
                      m.warnings)
        with mock.patch("xsections.core.build.model_surface", side_effect=IndexError("index 98 is out of bounds")):
            m = build_section(self.settings(), self.prj)
        self.assertEqual([sp.name for sp in m.surfaces], ["Water table 2024"])
        self.assertIn("Surface “Model top”: unexpected error (IndexError: index 98 is out of bounds); left out. "
                      "Details are in the XSections log.", m.warnings)
        self.assertEqual(sum("unexpected error" in w for w in m.warnings), 5)

    @unittest.skipUnless(os.name == "nt", "Windows file sharing modes")
    def test_locked_head_file(self):
        import ctypes
        from ctypes import wintypes
        folder = copy_model()
        grb, hds = os.path.join(folder, "disv_small.disv.grb"), os.path.join(folder, "disv_small.hds")
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        handle = k32.CreateFileW(hds, 0x80000000, 0, None, 3, 0x80, None)     # GENERIC_READ, share nothing
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            s = default_settings(self.prj, self.dem, self.pts, self.lines,
                                 surfaces=[mf6_surface(grb, "top"), mf6_surface(grb, "wt", mf6_head_path=hds)])
            m = build_section(s, self.prj)
        finally:
            k32.CloseHandle(handle)
        self.assertEqual([sp.name for sp in m.surfaces], ["Model top"])
        self.assertTrue(any(w.startswith("Surface “Water table”: disv_small.hds: can't read") for w in m.warnings),
                        m.warnings)
        m = build_section(s, self.prj)                          # unlocked: drawn
        self.assertEqual([sp.name for sp in m.surfaces], ["Model top", "Water table (SP 3)"])

    def test_warnings_not_errors(self):
        tmp = tempfile.mkdtemp(prefix="mf6sec_")
        lone = os.path.join(tmp, "lone.disv.grb")
        shutil.copy2(DISV, lone)
        bad = [mf6_surface(os.path.join(tmp, "gone.disv.grb"), "top", name="Gone"),
               mf6_surface("", "top", name="Unset"),
               mf6_surface(DISV, "botm", mf6_layer=4),
               mf6_surface(DISV, "head", mf6_layer=1, mf6_head_path=DISV_HDS, mf6_time="9,1"),
               mf6_surface(DISV, "head", mf6_layer=1, mf6_head_path=DISU_HDS, name="Wrong heads"),
               mf6_surface(lone, "wt", name="No heads"),
               mf6_surface(DIS, "top", name="Elsewhere"),
               mf6_surface(DISV, "top", name="Bad CRS", mf6_crs="EPSG:999999"),
               mf6_surface(DISV, "top", name="Hidden", visible=False)]
        m = build_section(self.settings(extra=bad), self.prj)
        self.assertEqual(len(m.surfaces), 6)
        w = "\n".join(m.warnings)
        for text in ("“Gone”: ", "file not found", "“Unset”: no MODFLOW 6 grid file chosen",
                     "“Layer 4 bottom”: layer 4 is not in the model disv_small (it has layers 1-3)",
                     "“Layer 1 head”: Stress period 9 is not in disv_small.hds (it holds periods 1-3)",
                     "“Wrong heads”: disu_small.hds has 13 values per layer", "belongs to another grid",
                     "“No heads”: no head file chosen", "“Elsewhere”: the model dis_rotated does not cross the section",
                     "“Bad CRS”: the model CRS “EPSG:999999” is not a valid CRS"):
            self.assertIn(text, w)
        self.assertNotIn("Hidden", w)

    def test_elevation_range(self):
        s_in = self.settings(**STANDARD)
        s_out = self.settings(deep_in_range=False, **STANDARD)
        p_in = S.plan(build_section(s_in, self.prj), s_in)
        p_out = S.plan(build_section(s_out, self.prj), s_out)
        self.assertLess(p_in.z_min, 400.0)                            # layer 3's bottom (400 ft) is on the sheet
        self.assertIn("Layer 3 bottom", p_in.lowest_what)
        self.assertGreater(p_out.z_min, p_in.z_min)                   # left out of the range: clipped at the frame
        self.assertNotIn("Layer 3 bottom", p_out.lowest_what)

    def test_caching(self):
        """A second build reads no file again (the grid, the head index and the values are cached); a file that
        changed is read again."""
        s = self.settings()
        build_section(s, self.prj)
        stats = dict(MS.STATS)
        boom = AssertionError("read again")
        with mock.patch.object(mf6, "_grid_from_grb", side_effect=boom), \
                mock.patch.object(mf6, "_grid_from_text", side_effect=boom), \
                mock.patch.object(mf6.HeadFile, "_index", side_effect=boom), \
                mock.patch.object(mf6.HeadFile, "read", side_effect=boom), \
                mock.patch.object(MS, "surface_array", side_effect=boom):
            m = build_section(s, self.prj)
        self.assertEqual(len(m.surfaces), 6)
        self.assertEqual(MS.STATS, stats)
        # a changed head file: indexed and read again
        tmp = tempfile.mkdtemp(prefix="mf6sec_")
        for name in os.listdir(os.path.dirname(DISV)):
            shutil.copy2(os.path.join(os.path.dirname(DISV), name), tmp)
        grb, hds = os.path.join(tmp, "disv_small.disv.grb"), os.path.join(tmp, "disv_small.hds")
        s2 = self.settings(extra=[mf6_surface(grb, "head", mf6_head_path=hds, name="Copy")])
        h1 = build_section(s2, self.prj).surfaces[-1]
        st = os.stat(hds)
        os.utime(hds, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        before = MS.STATS["values"]
        h2 = build_section(s2, self.prj).surfaces[-1]
        self.assertEqual(MS.STATS["values"], before + 1)
        self.assertEqual(h1.z, h2.z)

    def test_many_models_stay_cached(self):
        """Six model runs on one section (more than the 4 transformed grids kept between builds): a rebuild reads,
        transforms and intersects nothing again. A model run again: its old grid's entries are dropped as soon as
        the new version is used (nothing keeps the old arrays alive)."""
        import gc
        import weakref
        root = tempfile.mkdtemp(prefix="mf6sec_runs_")
        runs = [os.path.join(root, f"scenario {k}") for k in range(6)]
        for r in runs:
            shutil.copytree(os.path.dirname(DISV), r)
        surfaces = [mf6_surface(os.path.join(r, "disv_small.disv.grb"), "wt",
                                mf6_head_path=os.path.join(r, "disv_small.hds")) for r in runs]
        s = default_settings(self.prj, self.dem, self.pts, self.lines, surfaces=surfaces)
        self.assertEqual(len(build_section(s, self.prj).surfaces), 6)
        stats = dict(MS.STATS)
        boom = AssertionError("read again")
        with mock.patch.object(mf6, "_grid_from_grb", side_effect=boom), \
                mock.patch.object(mf6.HeadFile, "_index", side_effect=boom):
            m = build_section(s, self.prj)
        self.assertEqual(len(m.surfaces), 6)
        self.assertEqual(MS.STATS, stats)                                  # no transform, path or value again
        grb0 = surfaces[0]["mf6_path"]
        old = weakref.ref(mf6.read_grid(grb0))
        st = os.stat(grb0)
        os.utime(grb0, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))      # the model ran again
        build_section(s, self.prj)
        new = mf6.read_grid(grb0)
        held = ([k[0] for k in MS._GEO_CACHE] + [k[0].grid for k in MS._PATH_CACHE]
                + [k[0] for k in MS._VALUES_CACHE])
        self.assertTrue(any(g is new for g in held))
        gc.collect()
        self.assertIsNone(old())                                           # the old version is gone


# ===================================================================================================== real data
def folder_state(folder):
    out = {}
    for root, _dirs, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def flat_dem(path, x0, y0, x1, y1, z=300.0, cell=10.0):
    from osgeo import gdal, osr
    gdal.UseExceptions()
    nx, ny = int(math.ceil((x1 - x0) / cell)), int(math.ceil((y1 - y0) / cell))
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, cell, 0, y0 + ny * cell, 0, -cell))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2927)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(np.full((ny, nx), z, np.float32))
    band.SetUnitType("ft")
    ds.FlushCache()
    ds = None
    return path


@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealModels(unittest.TestCase):
    def setUp(self):
        self.mf6_dir = os.path.join(REALDATA, "mf6")
        self.state = folder_state(REALDATA)
        self.tmp = tempfile.mkdtemp(prefix="xsec_mf6sec_real_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.prj = QgsProject.instance()
        self.prj.clear()
        self.addCleanup(self.prj.clear)

    def tearDown(self):
        self.assertEqual(folder_state(REALDATA), self.state, "nothing written next to the real data")

    def test_f9_section(self):
        f9 = os.path.join(self.mf6_dir, "F9_flowV1")
        grb, hds = os.path.join(f9, "F9_flowV1.disv.grb"), os.path.join(f9, "F9_flowV1.hds")
        grid = mf6.read_grid(grb)
        x0, y0, x1, y1 = grid.extent_world()
        # cdf_lidar.tif is ~30 miles away: a flat synthetic DEM over the model instead
        dem = QgsRasterLayer(flat_dem(os.path.join(self.tmp, "f9_flat.tif"), x0 - 500, y0 - 500, x1 + 500, y1 + 500),
                             "flat")
        self.prj.addMapLayer(dem)
        self.prj.setCrs(EPSG)
        pts = [(x0 + 250.0, y0 + 400.0), (x0 + 0.47 * (x1 - x0), y0 + 0.55 * (y1 - y0)), (x1 - 250.0, y1 - 300.0)]
        surfaces = [mf6_surface(grb, "top", mf6_crs=CRS),
                    mf6_surface(grb, "botm", mf6_layer=3, mf6_crs=CRS, mode="cells"),
                    mf6_surface(grb, "head", mf6_layer=1, mf6_head_path=hds, mf6_time="30,13", mf6_crs=CRS),
                    mf6_surface(grb, "wt", mf6_head_path=hds, mf6_crs=CRS)]
        s = Settings(dem_layer_id=dem.id(), line_wkt=polyline(pts).asWkt(), line_crs_authid=CRS, surfaces=surfaces)
        ground = Settings(dem_layer_id=dem.id(), line_wkt=s.line_wkt, line_crs_authid=CRS)
        build_section(ground, self.prj)
        t = time.perf_counter()
        build_section(ground, self.prj)
        t_ground = time.perf_counter() - t
        mf6.clear_cache()
        MS.clear_cache()
        t = time.perf_counter()
        m = build_section(s, self.prj)
        t_first = time.perf_counter() - t
        t = time.perf_counter()
        m = build_section(s, self.prj)
        t_warm = time.perf_counter() - t
        print(f"\nF9 section with 4 model surfaces: first {t_first:.3f} s, warm {t_warm:.3f} s "
              f"(ground only {t_ground:.3f} s)")
        self.assertLess(t_warm - t_ground, 0.5)
        self.assertEqual([sp.name for sp in m.surfaces],
                         ["Model top", "Layer 3 bottom", "Layer 1 head (SP 30)", "Water table (SP 30)"])
        self.assertEqual(m.surfaces[2].detail, "Layer 1 head from F9_flowV1.hds (SP 30, step 13)")
        self.assertEqual([w for w in m.warnings if "Surface" in w], [])
        top, bot3, head, wt = m.surfaces
        for sp in (top, bot3, wt):
            self.assertGreater(sp.coverage, 0.95)
        self.assertGreater(head.coverage, 0.6)              # NEWTON: layer 1 is dry (head below its bottom) in places
        # the intervals match GEOS for a sample of the crossed cells
        line = polyline(pts)
        cp = MS.cell_path(MS.section_grid(grid, EPSG, EPSG), line, FTUS)
        for c in np.unique(cp.cell)[::25]:
            want = line.intersection(polygon(grid.cell_vertices_world(int(c)))).length() * FTUS
            self.assertAlmostEqual(float(np.sum((cp.s1 - cp.s0)[cp.cell == c])), want, delta=1e-5)
        # values: the reader's arrays in the crossed cells
        hf = mf6.HeadFile(hds)
        h1 = hf.read(1, 30, 13)
        wt_cells = mf6.surface_array(grid, "wt", 1, hds, "last")
        z = np.asarray(head.z)
        wet = cp.cell[h1[cp.cell] > grid.botm[0][cp.cell]]
        self.assertGreater(len(wet), 0)
        self.assertLess(len(np.unique(wet)), len(np.unique(cp.cell)))   # some crossed cells are dry
        self.assertTrue(set(np.round(z[np.isfinite(z)], 9)) <= set(np.round(h1[wet], 9)))
        dry_ft = float(np.sum((cp.s1 - cp.s0)[h1[cp.cell] <= grid.botm[0][cp.cell]]))
        self.assertAlmostEqual(head.coverage, (cp.covered() - dry_ft) / m.length, places=6)
        zw = np.asarray(wt.z)
        self.assertTrue(set(np.round(zw[np.isfinite(zw)], 9)) <= set(np.round(wt_cells[cp.cell], 9)))
        zb = np.asarray(bot3.z)
        self.assertTrue(set(zb[np.isfinite(zb)]) <= set(grid.botm[2][cp.cell]))
        zt = np.asarray(top.z)
        self.assertTrue(set(zt[np.isfinite(zt)]) <= set(mf6.surface_array(grid, "top")[cp.cell]))
        p = S.plan(m, s)
        self.assertLessEqual(p.z_min, float(np.nanmin(zb)))

    def test_cdf_section(self):
        for name in ("cdf_lidar.tif", "CDF_wells.shp", "CDF_wells.shx", "CDF_wells.dbf", "CDF_wells.prj",
                     "CDF_wells.cpg"):
            shutil.copy2(os.path.join(REALDATA, name), os.path.join(self.tmp, name))
        dem = QgsRasterLayer(os.path.join(self.tmp, "cdf_lidar.tif"), "cdf_lidar")
        wells = QgsVectorLayer(os.path.join(self.tmp, "CDF_wells.shp"), "CDF_wells", "ogr")
        self.assertTrue(dem.isValid() and wells.isValid())
        self.prj.addMapLayers([dem, wells])
        self.prj.setCrs(dem.crs())
        # a straight line along the wells' main axis, 300 ft past the outermost (as tests/test_e2e.py)
        ct = QgsCoordinateTransform(wells.crs(), dem.crs(), self.prj)
        xy = np.array([(lambda p: (p.x(), p.y()))(ct.transform(f.geometry().asPoint())) for f in wells.getFeatures()])
        c = xy.mean(axis=0)
        axis = np.linalg.svd(xy - c)[2][0]
        along = (xy - c) @ axis
        a, b = c + axis * (along.min() - 300.0), c + axis * (along.max() + 300.0)
        cdf = os.path.join(self.mf6_dir, "CDF_Mounding")
        disu, disv, hds = (os.path.join(cdf, f) for f in ("CDF_Mounding.disu.grb", "CDF_Mounding.disv.grb",
                                                            "CDF_Mounding.hds"))
        s = Settings(dem_layer_id=dem.id(), points_layer_id=wells.id(), label_field="ExploName",
                     type_field="ExploType", tolerance_ft=1000.0, depth_field="ExploDepth",
                     line_wkt=polyline([tuple(a), tuple(b)]).asWkt(), line_crs_authid=dem.crs().authid() or "",
                     surfaces=[mf6_surface(disu, "head", mf6_head_path=hds, color="#1f6fb2"),
                               mf6_surface(disv, "top", color="#8c5a3c"),
                               mf6_surface(disv, "head", mf6_head_path=hds, name="Old grid heads")])
        if not s.line_crs_authid:
            s.line_crs_authid = dem.crs().toWkt()
        m = build_section(s, self.prj)
        self.assertEqual([sp.name for sp in m.surfaces], ["Head (SP 49)", "Model top"])
        head, top = m.surfaces
        self.assertGreater(head.coverage, 0.5)
        self.assertGreater(top.coverage, 0.5)
        zh, zt = np.asarray(head.z), np.asarray(top.z)
        g = np.asarray([m.ground.z_at(st) for st in head.stations])
        ok = np.isfinite(zh) & np.isfinite(g)
        self.assertTrue(np.all((zh[ok] > 450.0) & (zh[ok] < 750.0)))
        self.assertTrue(np.all((zt[np.isfinite(zt)] > 450.0) & (zt[np.isfinite(zt)] < 750.0)))
        w = "\n".join(m.warnings)
        self.assertIn("“Head (SP 49)”: CDF_Mounding does not state its LENGTH_UNITS; assumed US survey feet", w)
        self.assertIn("“Old grid heads”: CDF_Mounding.hds has 9,546 values per layer", w)
        self.assertGreater(len(m.hits), 0)
        self.assertIn("Head from CDF_Mounding.hds (SP 49, step", F.surfaces_sources(m))
        p = S.plan(m, s)
        self.assertTrue(p.z_min <= float(np.nanmin(zh)))


if __name__ == "__main__":
    unittest.main()
