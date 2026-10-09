"""MODFLOW 6 readers (xsections/core/mf6.py): binary and text grid files, head files, the water table,
model discovery and caching.

The fixtures in tests/data/mf6/ are tiny real models run with MODFLOW 6 6.7.0 (regenerate them with
tests/data/mf6/make_fixtures.py): disv_small (DISV, 3 layers, quads and triangles, transient, layer 1 partly dry with
HDRY), dis_rotated (DIS with origin and 30 degree rotation, external text and binary arrays, NEWTON) and disu_small
(DISU with vertices, rotated 15 degrees). Their head-observation CSVs are an independent check of the head files.
The real-data tests (F9_flowV1 DISV, CDF_Mounding DISU) run only when XSECTIONS_REALDATA is set.
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

from tests.fixtures import REALDATA, ROOT, X0, Y0, budget, timing_test

from xsections.core import mf6  # noqa: E402
from xsections.core.mf6 import MF6Error  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data", "mf6")
EXT = {"disv_small": "disv", "dis_rotated": "dis", "disu_small": "disu"}
CASES = tuple(EXT)


def fx(case, suffix=""):
    """Path of a fixture file: fx("disv_small", ".disv.grb") -> tests/data/mf6/disv_small/disv_small.disv.grb."""
    return os.path.join(DATA, case, case + suffix)


def grb(case):
    return fx(case, f".{EXT[case]}.grb")


def text(case):
    return fx(case, f".{EXT[case]}")


def copy_case(case, dest=None):
    """A writable copy of a fixture folder (tests never change tests/data)."""
    dest = dest or os.path.join(tempfile.mkdtemp(prefix="mf6_"), case)
    shutil.copytree(os.path.join(DATA, case), dest)
    return dest


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def signed_area(pts):
    """Shoelace area (negative for a clockwise ring), about the first vertex for precision at world coordinates."""
    x, y = pts[:, 0] - pts[0, 0], pts[:, 1] - pts[0, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def read_obs(case):
    """{(layer, cell...): {totim: head}} from the head-observation CSV MODFLOW wrote (every time step)."""
    with open(fx(case, ".obs.csv")) as fh:
        names = fh.readline().strip().split(",")[1:]
        rows = [[float(v) for v in line.split(",")] for line in fh if line.strip()]
    out = {}
    for j, name in enumerate(names):
        key = tuple(int(p) for p in name[1:].split("_"))
        out[key] = {row[0]: row[j + 1] for row in rows}
    return out


# ------------------------------------------------------------------------------------------- grb byte surgery
def grb_parts(data):
    """(header lines, definition lines, data chunks) of a .grb (raw bytes)."""
    hdr = [data[i * 50:(i + 1) * 50] for i in range(4)]
    ntxt, lentxt = int(hdr[2].split()[1]), int(hdr[3].split()[1])
    pos = 200
    defs = []
    for _ in range(ntxt):
        defs.append(data[pos:pos + lentxt])
        pos += lentxt
    chunks = []
    for line in defs:
        t = line.decode().split()
        nd = int(t[3])
        n = int(np.prod([int(v) for v in t[4:4 + nd]])) if nd else 1
        size = n * {"INTEGER": 4, "DOUBLE": 8, "CHARACTER": 1}[t[1]]
        chunks.append(data[pos:pos + size])
        pos += size
    assert pos == len(data)
    return hdr, defs, chunks


def grb_line(textline, width):
    return textline.encode("ascii").ljust(width - 1) + b"\n"


def grb_build(hdr, defs, chunks, version=None):
    hdr = list(hdr)
    hdr[2] = grb_line(f"NTXT {len(defs)}", 50)
    if version:
        hdr[1] = grb_line(f"VERSION {version}", 50)
    return b"".join(hdr) + b"".join(defs) + b"".join(chunks)


class GrbFiles(unittest.TestCase):
    """Binary grid files of each kind, read definition by definition."""

    def setUp(self):
        mf6.clear_cache()

    def test_disv(self):
        g = mf6.read_grid(grb("disv_small"))
        self.assertEqual((g.kind, g.nlay, g.ncpl, g.nrow, g.ncol, g.source), ("disv", 3, 28, 0, 0, "grb"))
        self.assertEqual((g.top.shape, g.botm.shape, g.idomain.shape, g.verts.shape), ((28,), (3, 28), (3, 28), (35, 2)))
        self.assertEqual(g.length_units, "feet")                    # from disv_small.disv next to it
        self.assertEqual((g.xorigin, g.yorigin, g.angrot), (0.0, 0.0, 0.0))
        # elevations as written by make_fixtures.py, at the cell centres MODFLOW wrote (CELLX / CELLY)
        np.testing.assert_allclose(g.top, 500.0 + 0.01 * (g.cellx - X0) + 0.005 * (g.celly - Y0), atol=1e-6)
        np.testing.assert_allclose(g.botm[0], 500.0 + 0.004 * (g.cellx - X0), atol=1e-6)
        np.testing.assert_allclose(g.botm[1], 470.0 - 0.002 * (g.cellx - X0), atol=1e-6)
        np.testing.assert_array_equal(g.botm[2], 400.0)
        self.assertEqual([int((g.idomain[k] == 0).sum()) for k in range(3)], [1, 0, 3])
        # 20 quads and 8 triangles; rings clockwise and not closed; areas add up to the 3,000 x 1,000 ft block
        counts = g.iverts.counts()
        self.assertEqual((int((counts == 4).sum()), int((counts == 3).sum())), (20, 8))
        areas = []
        for i in range(g.ncpl):
            ring = g.iverts[i]
            self.assertNotEqual(ring[0], ring[-1])
            pts = g.cell_vertices(i)
            areas.append(signed_area(pts))
            np.testing.assert_allclose(pts.mean(axis=0), [g.cellx[i], g.celly[i]], atol=1e-6)   # rectangles, triangles
        self.assertTrue(all(a < 0 for a in areas))
        self.assertAlmostEqual(-sum(areas), 3000.0 * 1000.0, places=3)
        # world = model coordinates here (no origin, no rotation); the block's extent
        X, Y = g.to_world(g.cellx, g.celly)
        np.testing.assert_array_equal(X, g.cellx)
        np.testing.assert_array_equal(Y, g.celly)
        self.assertEqual(g.extent_world(), (X0 + 400.0, Y0 + 1600.0, X0 + 3400.0, Y0 + 2600.0))
        b = g.cell_bounds_world()
        self.assertEqual(b.shape, (28, 4))
        np.testing.assert_array_equal(b[0], [X0 + 400.0, Y0 + 2350.0, X0 + 900.0, Y0 + 2600.0])
        self.assertEqual(g.summary(), "DISV: 3 layers x 28 cells, feet")

    def test_dis_rotated(self):
        g = mf6.read_grid(grb("dis_rotated"))
        self.assertEqual((g.kind, g.nlay, g.nrow, g.ncol, g.ncpl), ("dis", 2, 3, 4, 12))
        self.assertEqual((g.xorigin, g.yorigin, g.angrot), (X0 + 1000.0, Y0 + 800.0, 30.0))
        r, c = np.divmod(np.arange(12), 4)
        np.testing.assert_array_equal(g.top, 520.0 + 2.0 * c - r)      # TOP: OPEN/CLOSE text file x FACTOR 2
        np.testing.assert_array_equal(g.botm[0], 490.0 + 0.5 * c + 0.25 * r)
        np.testing.assert_array_equal(g.botm[1], 400.0 - c)             # BOTM layer 2: binary array file
        self.assertEqual(np.argwhere(g.idomain == 0).tolist(), [[1, 2]])
        # cells from DELR / DELC: origin at the lower-left corner, row 1 at the top (north), rings clockwise
        delr, delc = [100.0, 150.0, 100.0, 200.0], [50.0, 80.0, 60.0]
        np.testing.assert_array_equal(g.cell_vertices(0), [[0, 190], [100, 190], [100, 140], [0, 140]])
        np.testing.assert_array_equal(g.cell_vertices(11), [[350, 60], [550, 60], [550, 0], [350, 0]])
        np.testing.assert_allclose(g.cellx[:4], [50, 175, 300, 450])
        np.testing.assert_allclose(g.celly[::4], [165, 100, 30])
        for i in range(12):
            self.assertAlmostEqual(-signed_area(g.cell_vertices(i)), delr[i % 4] * delc[i // 4])
            self.assertAlmostEqual(-signed_area(g.cell_vertices_world(i)), delr[i % 4] * delc[i // 4], places=6)
        # rotation 30 degrees counter-clockwise about the origin
        a = math.radians(30.0)
        X, Y = g.to_world([0.0, 550.0, 0.0], [0.0, 0.0, 190.0])
        np.testing.assert_allclose(X, [X0 + 1000.0, X0 + 1000.0 + 550 * math.cos(a), X0 + 1000.0 - 190 * math.sin(a)])
        np.testing.assert_allclose(Y, [Y0 + 800.0, Y0 + 800.0 + 550 * math.sin(a), Y0 + 800.0 + 190 * math.cos(a)])
        x, y = g.to_model(X, Y)
        np.testing.assert_allclose(x, [0, 550, 0], atol=1e-8)
        np.testing.assert_allclose(y, [0, 0, 190], atol=1e-8)
        corner = g.cell_vertices_world(0)
        b = g.cell_bounds_world()[0]
        np.testing.assert_allclose(b, [corner[:, 0].min(), corner[:, 1].min(), corner[:, 0].max(), corner[:, 1].max()])
        self.assertAlmostEqual(b[0], X0 + 1000.0 - 190 * math.sin(a))      # the upper-left corner, rotated

    def test_disu(self):
        g = mf6.read_grid(grb("disu_small"))
        self.assertEqual((g.kind, g.nlay, g.ncpl, g.nrow, g.ncol), ("disu", 1, 13, 0, 0))
        self.assertEqual((g.botm.shape, g.idomain.shape), ((1, 13), (1, 13)))   # MF6 6.7 writes IDOMAIN for DISU
        self.assertEqual((g.xorigin, g.yorigin, g.angrot), (X0 + 1200.0, Y0 + 1700.0, 15.0))
        counts = g.iverts.counts()
        self.assertEqual((int((counts == 4).sum()), int((counts == 3).sum())), (11, 2))
        # CELLX / CELLY and VERTICES are MODEL coordinates (MODFLOW wrote them as given): the block is 1,200 x 600
        self.assertEqual((g.verts.min(axis=0).tolist(), g.verts.max(axis=0).tolist()), ([0, 0], [1200, 600]))
        self.assertTrue(np.all((g.cellx > 0) & (g.cellx < 1200) & (g.celly > 0) & (g.celly < 600)))
        self.assertAlmostEqual(sum(-signed_area(g.cell_vertices(i)) for i in range(13)), 720000.0, places=6)
        a = math.radians(15.0)
        X, Y = g.to_world(g.cellx, g.celly)
        np.testing.assert_allclose(X, X0 + 1200.0 + g.cellx * math.cos(a) - g.celly * math.sin(a))
        np.testing.assert_allclose(Y, Y0 + 1700.0 + g.cellx * math.sin(a) + g.celly * math.cos(a))
        b = g.cell_bounds_world()
        self.assertTrue(np.all((b[:, 0] <= X) & (X <= b[:, 2]) & (b[:, 1] <= Y) & (Y <= b[:, 3])))
        self.assertEqual(g.summary(), "DISU: 13 nodes, feet")

    def test_definitions_read_by_name(self):
        """A later file version may add definitions: they are read (or skipped) by name, wherever they are."""
        with open(grb("disv_small"), "rb") as fh:
            hdr, defs, chunks = grb_parts(fh.read())
        names = [d.split()[0].decode() for d in defs]
        at = names.index("ANGROT") + 1
        defs[at:at] = [grb_line("CRS CHARACTER NDIM 1 9", 100), grb_line("EXTRA DOUBLE NDIM 2 3 2", 100)]
        chunks[at:at] = [b"EPSG:2927", struct.pack("<6d", *range(6))]
        tmp = os.path.join(tempfile.mkdtemp(prefix="mf6_"), "v2.disv.grb")
        with open(tmp, "wb") as fh:
            fh.write(grb_build(hdr, defs, chunks, version=2))
        kind, values, _ = mf6._parse_grb(tmp)
        self.assertEqual((kind, values["CRS"]), ("disv", "EPSG:2927"))
        np.testing.assert_array_equal(values["EXTRA"], np.arange(6.0).reshape(2, 3))   # Fortran dims reversed
        a, b = mf6.read_grid(tmp), mf6.read_grid(grb("disv_small"))
        for name in ("top", "botm", "idomain", "verts", "cellx", "celly"):
            np.testing.assert_array_equal(getattr(a, name), getattr(b, name))
        np.testing.assert_array_equal(a.iverts.indices, b.iverts.indices)
        self.assertEqual(a.length_units, "unknown")                 # no v2.disv next to it

    def test_older_disu_without_idomain(self):
        """CDF_Mounding.disu.grb (an older MODFLOW 6) has 15 definitions: no IDOMAIN -> idomain None."""
        with open(grb("disu_small"), "rb") as fh:
            hdr, defs, chunks = grb_parts(fh.read())
        k = [d.split()[0] for d in defs].index(b"IDOMAIN")
        del defs[k], chunks[k]
        tmp = os.path.join(tempfile.mkdtemp(prefix="mf6_"), "old.disu.grb")
        with open(tmp, "wb") as fh:
            fh.write(grb_build(hdr, defs, chunks))
        g = mf6.read_grid(tmp)
        self.assertIsNone(g.idomain)
        self.assertTrue(g.active().all())
        np.testing.assert_array_equal(g.top, mf6.read_grid(grb("disu_small")).top)

    def test_closed_or_open_rings(self):
        """MODFLOW 6 writes each ring closed (first vertex repeated) to the .grb; a list without the repeat is
        read the same way."""
        with open(grb("disv_small"), "rb") as fh:
            _, values, _ = mf6._parse_grb(fh.name)
        ia, ja = values["IAVERT"], values["JAVERT"]
        self.assertEqual(len(ja), 28 + 104)                         # closed in the file
        open_ja = np.concatenate([ja[ia[i] - 1:ia[i + 1] - 2] for i in range(28)])
        open_ia = np.concatenate([[1], 1 + np.cumsum(np.diff(ia) - 1)])
        a, b = mf6._rings(ia, ja), mf6._rings(open_ia, open_ja)
        np.testing.assert_array_equal(a.offsets, b.offsets)
        np.testing.assert_array_equal(a.indices, b.indices)
        self.assertEqual(int(a.offsets[-1]), 104)

    def test_bad_files(self):
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(os.path.join(DATA, "disv_small", "nothing.disv.grb"))
        self.assertIn("not found", str(cm.exception))
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(fx("disv_small", ".tdis"))
        self.assertIn("not a MODFLOW 6 grid file", str(cm.exception))
        tmp = os.path.join(tempfile.mkdtemp(prefix="mf6_"), "cut.disv.grb")
        with open(grb("disv_small"), "rb") as fh, open(tmp, "wb") as out:
            out.write(fh.read()[:3000])
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(tmp)
        self.assertIn("truncated", str(cm.exception))


DISV_TEXT = """\
# a hand-written DISV in the forms MODFLOW 6 accepts
begin options   ! lower-case keywords
  length_units  {units}
  xorigin 100.0
  YORIGIN 2.0D+02     # Fortran exponent
  angrot  -10
end options

BEGIN DIMENSIONS
  NLAY 2
  NCPL 3
  NVERT 5
END DIMENSIONS

BEGIN GRIDDATA
  TOP
    CONSTANT 50.0
  BOTM
    INTERNAL FACTOR 2.0 IPRN 3
      20.0 21.0

      ! a comment line inside the array
      22.0 10.0 # trailing comment
      11.0
      12.0
END GRIDDATA

BEGIN VERTICES
  1 0.0 10.0
  2 10.0 10.0
  3 20.0 10.0
  5 10.0 0.0
  4 0.0 0.0
END VERTICES

begin cell2d
  2 13.33 6.67 3 2 3 5
  1 5.0 5.0 5 1 2 5 4 1
  3 15.0 0.0 3 3 5 5
end cell2d
"""


class TextFiles(unittest.TestCase):
    """Text grid files read like MODFLOW 6 reads them, compared with the .grb MODFLOW wrote from them."""

    def setUp(self):
        mf6.clear_cache()

    def assert_same_grid(self, a, b):
        for name in ("kind", "nlay", "ncpl", "nrow", "ncol", "xorigin", "yorigin", "angrot", "length_units"):
            self.assertEqual(getattr(a, name), getattr(b, name), name)
        for name in ("top", "botm", "idomain", "verts", "cellx", "celly"):
            np.testing.assert_allclose(getattr(a, name), getattr(b, name), rtol=0, atol=1e-9, err_msg=name)
        np.testing.assert_array_equal(a.iverts.offsets, b.iverts.offsets)
        np.testing.assert_array_equal(a.iverts.indices, b.iverts.indices)
        for i in range(a.ncpl):
            np.testing.assert_array_equal(a.cell_vertices(i), b.cell_vertices(i))
        np.testing.assert_allclose(a.cell_bounds_world(), b.cell_bounds_world(), atol=1e-9)

    def test_text_equals_grb(self):
        for case in CASES:
            with self.subTest(case=case):
                t, g = mf6.read_grid(text(case)), mf6.read_grid(grb(case))
                self.assertEqual((t.source, g.source), ("text", "grb"))
                self.assert_same_grid(t, g)

    def test_closed_cell2d_rings(self):
        """make_fixtures.py writes cells 1, 10, 14 and 19 of disv_small (quads and triangles) with their ring closed
        in CELL2D (first vertex repeated); the reader drops the repeat."""
        with open(text("disv_small")) as fh:
            rows = fh.read().split("BEGIN cell2d")[1].split("END cell2d")[0].strip().splitlines()
        first = rows[0].split()
        self.assertEqual(first[3], "5")                             # 4 vertices + the repeat
        self.assertEqual(first[4], first[-1])
        t = mf6.read_grid(text("disv_small"))
        self.assertEqual(t.iverts.counts()[[0, 9, 13, 18]].tolist(), [4, 3, 4, 3])

    def test_forms(self):
        """Comments (# and !), blank lines, lower case, CONSTANT, INTERNAL with FACTOR and IPRN over uneven lines,
        a Fortran D exponent, rows out of order, a closed and a repeated-vertex ring, no IDOMAIN (all active)."""
        folder = tempfile.mkdtemp(prefix="mf6_")
        path = os.path.join(folder, "forms.disv")
        with open(path, "w") as fh:
            fh.write(DISV_TEXT.format(units="meters"))
        g = mf6.read_grid(path)
        self.assertEqual((g.kind, g.nlay, g.ncpl, g.length_units), ("disv", 2, 3, "meters"))
        self.assertEqual((g.xorigin, g.yorigin, g.angrot), (100.0, 200.0, -10.0))
        np.testing.assert_array_equal(g.top, [50.0, 50.0, 50.0])
        np.testing.assert_array_equal(g.botm, [[40.0, 42.0, 44.0], [20.0, 22.0, 24.0]])
        np.testing.assert_array_equal(g.idomain, np.ones((2, 3)))
        np.testing.assert_array_equal(g.verts, [[0, 10], [10, 10], [20, 10], [0, 0], [10, 0]])   # sorted by iv
        self.assertEqual([g.iverts[i].tolist() for i in range(3)], [[0, 1, 4, 3], [1, 2, 4], [2, 4, 4]])
        np.testing.assert_array_equal(g.cellx, [5.0, 13.33, 15.0])
        for units, expect in (("FEET", "feet"), ("centimeters", "centimeters"), ("unknown", "unknown")):
            with open(path, "w") as fh:
                fh.write(DISV_TEXT.format(units=units))
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000))
            self.assertEqual(mf6.read_grid(path).length_units, expect, units)
        with open(path, "w") as fh:
            fh.write(DISV_TEXT.format(units="x").replace("  length_units  x\n", ""))
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 20_000))
        self.assertEqual(mf6.read_grid(path).length_units, "unknown")

    def test_layered_and_external_sources(self):
        """dis_rotated.dis: TOP from OPEN/CLOSE text x FACTOR 2, BOTM LAYERED (INTERNAL with IPRN, then
        OPEN/CLOSE (BINARY)), IDOMAIN LAYERED (CONSTANT, then INTERNAL)."""
        t = mf6.read_grid(text("dis_rotated"))
        with open(fx("dis_rotated", ".top.txt")) as fh:
            halves = np.array(fh.read().split(), float)
        np.testing.assert_array_equal(t.top, 2.0 * halves)
        np.testing.assert_array_equal(t.botm[1], np.tile([400.0, 399.0, 398.0, 397.0], 3))
        np.testing.assert_array_equal(t.idomain[0], 1)

    def test_paths_relative_to_the_simulation_folder(self):
        """Model files in a subfolder: name-file and OPEN/CLOSE paths are relative to where mfsim.nam is."""
        sim = copy_case("dis_rotated")
        sub = os.path.join(sim, "gwf")
        os.makedirs(sub)
        for f in os.listdir(sim):
            if f != "mfsim.nam" and os.path.isfile(os.path.join(sim, f)):
                shutil.move(os.path.join(sim, f), os.path.join(sub, f))
        edits = {os.path.join(sim, "mfsim.nam"): [("dis_rotated.nam", "gwf/dis_rotated.nam"),
                                                   ("dis_rotated.tdis", "gwf/dis_rotated.tdis")],
                 os.path.join(sub, "dis_rotated.nam"): [("  dis_rotated.", "  gwf/dis_rotated.")],
                 os.path.join(sub, "dis_rotated.oc"): [("FILEOUT  dis_rotated.hds", "FILEOUT  gwf/dis_rotated.hds")],
                 os.path.join(sub, "dis_rotated.dis"): [("'dis_rotated.top.txt'", "'gwf/dis_rotated.top.txt'"),
                                                        ("  dis_rotated.botm2.bin", "  gwf/dis_rotated.botm2.bin")]}
        for path, subs in edits.items():
            with open(path) as fh:
                s = fh.read()
            for a, b in subs:
                self.assertIn(a, s)
                s = s.replace(a, b)
            with open(path, "w") as fh:
                fh.write(s)
        g = mf6.read_grid(os.path.join(sub, "dis_rotated.dis"))
        self.assert_same_grid(g, mf6.read_grid(grb("dis_rotated")))
        m = mf6.find_model(sim)
        self.assertEqual(os.path.normcase(m.grid_path), os.path.normcase(os.path.join(sub, "dis_rotated.dis.grb")))
        self.assertEqual(os.path.normcase(m.head_path), os.path.normcase(os.path.join(sub, "dis_rotated.hds")))
        self.assertEqual(os.path.normcase(m.sim_dir), os.path.normcase(sim))
        os.remove(os.path.join(sub, "dis_rotated.top.txt"))
        os.utime(os.path.join(sub, "dis_rotated.dis"), ns=(time.time_ns(), time.time_ns() + 10_000))
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(os.path.join(sub, "dis_rotated.dis"))
        self.assertIn("gwf", str(cm.exception))
        self.assertIn("not found", str(cm.exception))

    def test_disu_without_vertices(self):
        with open(text("disu_small")) as fh:
            s = fh.read()
        s = s.split("BEGIN vertices")[0].replace("NVERT  20", "")
        path = os.path.join(tempfile.mkdtemp(prefix="mf6_"), "novert.disu")
        with open(path, "w") as fh:
            fh.write(s)
        g = mf6.read_grid(path)
        self.assertEqual((g.kind, g.ncpl, g.has_vertices), ("disu", 13, False))
        np.testing.assert_array_equal(g.top, mf6.read_grid(grb("disu_small")).top)
        with self.assertRaises(MF6Error) as cm:
            g.cell_bounds_world()
        self.assertIn("no cell vertices", str(cm.exception))

    def test_units_of_a_grb_come_from_its_text_file(self):
        folder = copy_case("disv_small")
        g = os.path.join(folder, "disv_small.disv.grb")
        self.assertEqual(mf6.read_grid(g).length_units, "feet")
        dis = os.path.join(folder, "disv_small.disv")
        with open(dis) as fh:
            s = fh.read()
        with open(dis, "w") as fh:
            fh.write(s.replace("LENGTH_UNITS  feet", "LENGTH_UNITS  meters"))
        self.assertEqual(mf6.read_grid(g).length_units, "meters")      # the text file changed: read again
        os.remove(dis)
        self.assertEqual(mf6.read_grid(g).length_units, "unknown")

    # ---- forms MODFLOW 6 accepts (each checked by the reviewers with mf6 6.7.0: same .grb as the fixture)
    def edit_text(self, folder, case, subs):
        path = os.path.join(folder, f"{case}.{EXT[case]}")
        with open(path) as fh:
            s = fh.read()
        for a, b in subs:
            self.assertIn(a, s)
            s = s.replace(a, b)
        with open(path, "w") as fh:
            fh.write(s)
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 50_000))
        return path

    def test_block_open_close_lists(self):
        """VERTICES and CELL2D whose only line is OPEN/CLOSE file (list data stored externally, as flopy's
        set_all_data_external writes it); (BINARY) list data is refused with a clear message."""
        folder = copy_case("disv_small")
        os.remove(os.path.join(folder, "disv_small.disv.grb"))      # the text grid is what gets read
        path = os.path.join(folder, "disv_small.disv")
        with open(path) as fh:
            s = fh.read()
        for block in ("vertices", "cell2d"):
            head, rest = s.split(f"BEGIN {block}\n")
            body, tail = rest.split(f"END {block}")
            with open(os.path.join(folder, f"disv_small.{block}.txt"), "w") as fh:
                fh.write("# rows moved out of the grid file\n" + body)
            s = f"{head}BEGIN {block}\n  OPEN/CLOSE  'disv_small.{block}.txt'\nEND {block}{tail}"
        with open(path, "w") as fh:
            fh.write(s)
        g = mf6.read_grid(path)
        self.assert_same_grid(g, mf6.read_grid(grb("disv_small")))
        self.assertEqual(sorted(os.path.basename(p) for p, _m, _s in g.inputs),
                         ["disv_small.cell2d.txt", "disv_small.vertices.txt"])
        self.assertTrue(mf6.find_model(folder).grid_path.endswith("disv_small.disv"))
        self.edit_text(folder, "disv_small", [("'disv_small.cell2d.txt'", "'disv_small.cell2d.txt'  (BINARY)")])
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(path)
        self.assertIn("disv_small.disv: CELL2D: binary list data", str(cm.exception))

    def test_list_directed_arrays(self):
        """Array data is read list-directed, as MODFLOW 6 reads it: r*value repeat counts and commas, in INTERNAL
        data (the repeat counts toward the values of the array) and in OPEN/CLOSE text files."""
        folder = copy_case("disv_small")
        os.remove(os.path.join(folder, "disv_small.disv.grb"))
        top = mf6.read_grid(grb("disv_small")).top
        with open(os.path.join(folder, "disv_small.top.txt"), "w") as fh:
            fh.write(", ".join(f"{v:.6f}" for v in top[:20]) + ",\n" + " ".join(f"{v:.6f}" for v in top[20:]) + "\n")
        rows3 = ("      400.0  400.0  400.0  400.0  400.0  400.0  400.0  400.0\n" * 3
                 + "      400.0  400.0  400.0  400.0\n")
        path = self.edit_text(folder, "disv_small", [
            ("    INTERNAL  FACTOR  1.0\n" + rows3, "    INTERNAL  FACTOR  1.0\n      27*400.0, 400.0\n"),
            ("    CONSTANT  1\n", "    INTERNAL\n      28*1\n")])
        with open(path) as fh:
            s = fh.read()
        head, rest = s.split("  top\n", 1)
        rest = rest.split("  botm  LAYERED", 1)[1]
        with open(path, "w") as fh:
            fh.write(head + "  top\n    OPEN/CLOSE  disv_small.top.txt\n  botm  LAYERED" + rest)
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 90_000))
        g = mf6.read_grid(path)
        ref = mf6.read_grid(grb("disv_small"))
        np.testing.assert_allclose(g.top, ref.top, atol=1e-6)
        np.testing.assert_array_equal(g.botm, ref.botm)
        np.testing.assert_array_equal(g.idomain, ref.idomain)
        self.assertEqual(mf6._list_words("3*1.5, 2 ,4*-1", 99), ["1.5"] * 3 + ["2"] + ["-1"] * 4)
        self.assertEqual(len(mf6._list_words("999999999*1", 28)), 28)        # never more copies than needed
        with open(path) as fh:
            s = fh.read()
        with open(path, "w") as fh:
            fh.write(s.replace("27*400.0, 400.0", "27*400.0 1*"))
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 120_000))
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(path)
        self.assertIn("BOTM layer 3: '1*' is a repeat count without a value", str(cm.exception))

    def test_binary_array_with_one_header(self):
        """A (BINARY) OPEN/CLOSE array is one header and then the values the array needs, whatever the header's
        NCOL, NROW and ILAY say (MODFLOW 6 reads it so; writers put (ncol, nrow, nlay), (ncpl, 1, nlay) or (1, 1,
        1) there). A file with too few values is an error."""
        folder = copy_case("dis_rotated")
        os.remove(os.path.join(folder, "dis_rotated.dis.grb"))
        ref = mf6.read_grid(grb("dis_rotated"))
        dis = self.edit_text(folder, "dis_rotated", [("  botm  LAYERED\n    INTERNAL  FACTOR  1.0  IPRN  1\n"
                                                      "      490.0  490.5  491.0  491.5\n"
                                                      "      490.25  490.75  491.25  491.75\n"
                                                      "      490.5  491.0  491.5  492.0\n"
                                                      "    OPEN/CLOSE  dis_rotated.botm2.bin  FACTOR  1.0  (BINARY)\n",
                                                      "  botm\n    OPEN/CLOSE  botm_all.bin  (BINARY)\n")])
        values = np.asarray(ref.botm, "<f8").ravel()
        for k, dims in enumerate(((4, 3, 2), (1, 1, 1), (12, 1, 2), (24, 1, 1))):
            with open(os.path.join(folder, "botm_all.bin"), "wb") as fh:
                fh.write(struct.pack("<iidd16siii", 1, 1, 1.0, 1.0, b"            BOTM", *dims))
                fh.write(values.tobytes())
            os.utime(dis, ns=(time.time_ns(), time.time_ns() + 10_000 * (k + 1)))
            with self.subTest(dims=dims):
                np.testing.assert_array_equal(mf6.read_grid(dis).botm, ref.botm)
        with open(os.path.join(folder, "botm_all.bin"), "wb") as fh:
            fh.write(struct.pack("<iidd16siii", 1, 1, 1.0, 1.0, b"            BOTM", 24, 1, 1))
            fh.write(values[:20].tobytes())
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(dis)
        self.assertIn("botm_all.bin: 20 values after its header, 24 expected", str(cm.exception))

    def test_changed_open_close_file_is_read_again(self):
        """A cached text grid is read again when an OPEN/CLOSE file it read changed, or went."""
        folder = copy_case("dis_rotated")
        os.remove(os.path.join(folder, "dis_rotated.dis.grb"))
        dis = os.path.join(folder, "dis_rotated.dis")
        g = mf6.read_grid(dis)
        self.assertIs(mf6.read_grid(dis), g)
        self.assertEqual(sorted(os.path.basename(p) for p, _m, _s in g.inputs),
                         ["dis_rotated.botm2.bin", "dis_rotated.top.txt"])
        top_txt = os.path.join(folder, "dis_rotated.top.txt")
        with open(top_txt) as fh:
            halves = np.array(fh.read().split(), float)
        with open(top_txt, "w") as fh:
            fh.write(" ".join(f"{v + 50.0}" for v in halves))
        os.utime(top_txt, ns=(time.time_ns(), time.time_ns() + 10_000))
        g2 = mf6.read_grid(dis)
        self.assertIsNot(g2, g)
        np.testing.assert_array_equal(g2.top, 2.0 * (halves + 50.0))
        self.assertIs(mf6.read_grid(dis), g2)
        os.remove(top_txt)
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(dis)
        self.assertIn("dis_rotated.top.txt not found", str(cm.exception))

    def test_units_of_a_grb_written_by_grb6_fileout(self):
        """A .grb named by GRB6 FILEOUT (not the text file's name + .grb) takes LENGTH_UNITS from the grid package
        that names it, and is read again when that file changes."""
        folder = copy_case("disv_small")
        os.makedirs(os.path.join(folder, "output"))
        out = os.path.join(folder, "output", "grid.grb")
        os.rename(os.path.join(folder, "disv_small.disv.grb"), out)
        self.edit_text(folder, "disv_small", [("LENGTH_UNITS  feet", "LENGTH_UNITS  meters\n  GRB6  FILEOUT  "
                                                                     "output/grid.grb")])
        for path in (folder, out, os.path.join(folder, "disv_small.hds"), os.path.join(folder, "disv_small.disv")):
            m = mf6.find_model(path)
            self.assertTrue(same(m.grid_path, out), path)
            self.assertEqual(mf6.read_grid(m.grid_path).length_units, "meters", path)
        self.edit_text(folder, "disv_small", [("LENGTH_UNITS  meters", "LENGTH_UNITS  feet")])
        self.assertEqual(mf6.read_grid(out).length_units, "feet")             # the text file changed: read again
        lone = os.path.join(tempfile.mkdtemp(prefix="mf6_"), "lone.grb")
        shutil.copy2(out, lone)
        self.assertEqual(mf6.read_grid(lone).length_units, "unknown")         # no name file names it

    def test_vertex_ids_are_checked(self):
        """A vertex id outside 1..NVERT (a grid file being edited; MODFLOW would refuse it) is an MF6Error naming
        it, not an index error later (or, for id 0, a silently wrong cell)."""
        folder = copy_case("disv_small")
        os.remove(os.path.join(folder, "disv_small.disv.grb"))
        path = os.path.join(folder, "disv_small.disv")
        with open(path) as fh:
            s = fh.read()
        head, rest = s.split("BEGIN cell2d\n")
        rows = rest.split("\n")
        for bad, word in (("99", "names vertex 99 but NVERT is 35"), ("0", "names vertex 0 but NVERT is 35")):
            t = rows[2].split()
            t[5] = bad                                                       # the second vertex of cell 3
            with open(path, "w") as fh:
                fh.write(head + "BEGIN cell2d\n" + "\n".join(rows[:2] + ["  " + "  ".join(t)] + rows[3:]))
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000 * int(bad or 1)))
            with self.subTest(bad=bad), self.assertRaises(MF6Error) as cm:
                mf6.read_grid(path)
            self.assertIn(f"disv_small.disv: CELL2D {word}", str(cm.exception))
        # a .grb whose JAVERT names a vertex past NVERT
        with open(grb("disv_small"), "rb") as fh:
            hdr, defs, chunks = grb_parts(fh.read())
        names = [d.decode().split()[0] for d in defs]
        ja = np.frombuffer(chunks[names.index("JAVERT")], "<i4").copy()
        ja[7] = 36
        chunks[names.index("JAVERT")] = ja.tobytes()
        bad_grb = os.path.join(folder, "bad.disv.grb")
        with open(bad_grb, "wb") as fh:
            fh.write(grb_build(hdr, defs, chunks))
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(bad_grb)
        self.assertIn("bad.disv.grb: JAVERT names vertex 36 but NVERT is 35", str(cm.exception))

    def test_errors_name_the_file(self):
        path = os.path.join(tempfile.mkdtemp(prefix="mf6_"), "short.disv")
        with open(path, "w") as fh:
            fh.write(DISV_TEXT.format(units="feet").replace("      12.0\n", ""))
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(path)
        self.assertIn("short.disv", str(cm.exception))
        with open(path, "w") as fh:
            fh.write(DISV_TEXT.format(units="feet").replace("CONSTANT 50.0", "INTERNAL\n      50.0 5x.0 50.0"))
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000))
        with self.assertRaises(MF6Error) as cm:
            mf6.read_grid(path)
        self.assertIn("5x.0", str(cm.exception))


class HeadFiles(unittest.TestCase):
    def setUp(self):
        mf6.clear_cache()

    def test_index(self):
        hf = mf6.HeadFile(fx("disv_small", ".hds"))
        self.assertEqual((len(hf.records), hf.precision, hf.ncpl_per_record, hf.layers, hf.truncated),
                         (18, "double", 28, [1, 2, 3], False))
        self.assertEqual(hf.times(), [(1, 1, 5.0), (1, 2, 10.0), (2, 1, 20.0), (2, 2, 30.0), (2, 3, 40.0),
                                      (3, 2, 60.0)])
        self.assertEqual(hf.periods(), [1, 2, 3])
        self.assertEqual([hf.last_step(k) for k in (1, 2, 3)], [2, 3, 2])
        self.assertEqual(hf.steps(3), [2])
        self.assertEqual(hf.totim(2, 2), 30.0)
        r = hf.records[0]
        self.assertEqual((r.kstp, r.kper, r.text, r.ncol, r.nrow, r.ilay, r.offset), (1, 1, "HEAD", 28, 1, 1, 52))
        with self.assertRaises(MF6Error):
            hf.last_step(4)

    def test_resolve(self):
        hf = mf6.HeadFile(fx("disv_small", ".hds"))
        for time_setting, expect in (("last", (3, 2)), ("", (3, 2)), (None, (3, 2)), ("LAST", (3, 2)),
                                     ("2", (2, 3)), ("2,0", (2, 3)), ("1,1", (1, 1)), (" 2 , 1 ", (2, 1)),
                                     ((2, 1), (2, 1)), ((1,), (1, 2)), (2, (2, 3)), ("3,2", (3, 2))):
            self.assertEqual(hf.resolve(time_setting), expect, time_setting)
        with self.assertRaises(MF6Error) as cm:
            hf.resolve("4")
        self.assertEqual(str(cm.exception), "Stress period 4 is not in disv_small.hds (it holds periods 1-3).")
        with self.assertRaises(MF6Error) as cm:
            hf.resolve("3,1")                         # period 3 saved its last step only
        self.assertEqual(str(cm.exception),
                         "Time step 1 of stress period 3 is not saved in disv_small.hds (saved steps: 2).")
        for bad in ("abc", "1,2,3", "-1", 1.5):
            with self.assertRaises(MF6Error):
                hf.resolve(bad)

    def test_values_match_the_observations(self):
        """Every saved value of every observed cell equals MODFLOW's own observation output; dry -> nan."""
        for case in CASES:
            hf = mf6.HeadFile(fx(case, ".hds"))
            obs = read_obs(case)
            g = mf6.read_grid(grb(case))
            checked = 0
            for kper, kstp, totim in hf.times():
                heads = hf.read_layers(kper, kstp)
                for key, series in obs.items():
                    if case == "disu_small":
                        lay, cell = 1, key[0] - 1
                    elif case == "dis_rotated":
                        lay, cell = key[0], (key[1] - 1) * g.ncol + (key[2] - 1)   # row-major
                    else:
                        lay, cell = key[0], key[1] - 1
                    expect = series[totim]
                    got = heads[lay - 1, cell]
                    if abs(expect) >= 1e29:
                        self.assertTrue(math.isnan(got), (case, key, totim))
                    else:
                        self.assertAlmostEqual(got, expect, delta=1e-9 * abs(expect), msg=(case, key, totim))
                    checked += 1
            self.assertEqual(checked, len(obs) * len(hf.times()), case)
            self.assertGreaterEqual(checked, 12, case)

    def test_known_boundary_heads(self):
        """Constant heads: the west column 525 ft in every layer, the east column (layers 2 and 3) 505, 500 and
        495 ft in periods 1, 2 and 3."""
        hf = mf6.HeadFile(fx("disv_small", ".hds"))
        g = mf6.read_grid(grb("disv_small"))
        west = np.isclose(g.cellx, X0 + 650.0)
        east = np.isclose(g.cellx, X0 + 3150.0)
        self.assertEqual((int(west.sum()), int(east.sum())), (4, 4))
        for kper, kstp, _ in hf.times():
            for lay in (1, 2, 3):
                h = hf.read(lay, kper, kstp)
                np.testing.assert_array_equal(h[west], 525.0)
                if lay > 1:
                    np.testing.assert_array_equal(h[east], {1: 505.0, 2: 500.0, 3: 495.0}[kper])

    def test_dry_and_inactive_are_nan(self):
        path = fx("disv_small", ".hds")
        hf = mf6.HeadFile(path)
        g = mf6.read_grid(grb("disv_small"))
        rec = hf.record(1, 3, 2)
        raw = np.fromfile(path, "<f8", count=28, offset=rec.offset)
        h = hf.read(1, 3, 2)
        east = np.isclose(g.cellx, X0 + 3150.0)
        np.testing.assert_array_equal(raw[east], -1e30)              # HDRY: layer 1 dried out in the east
        np.testing.assert_array_equal(raw[g.idomain[0] == 0], 1e30)  # HNOFLO: inactive
        self.assertTrue(np.isnan(h[east]).all())
        self.assertTrue(np.isnan(h[g.idomain[0] == 0]).all())
        self.assertEqual(int(np.isnan(h).sum()), 5)
        h3 = hf.read(3, 3, 2)
        self.assertEqual(np.nonzero(np.isnan(h3))[0].tolist(), np.nonzero(g.idomain[2] == 0)[0].tolist())
        ok = ~np.isnan(h)
        np.testing.assert_array_equal(h[ok], raw[ok])

    def test_read_layers_and_errors(self):
        hf = mf6.HeadFile(fx("disv_small", ".hds"))
        h = hf.read_layers(2, 3)
        self.assertEqual((h.shape, h.dtype), ((3, 28), np.float64))
        for lay in (1, 2, 3):
            np.testing.assert_array_equal(h[lay - 1], hf.read(lay, 2, 3))
        np.testing.assert_array_equal(hf.read_layers(2, 0), h)       # step 0: the period's last saved step
        with self.assertRaises(MF6Error) as cm:
            hf.read(4, 2, 3)
        self.assertIn("Layer 4 is not in disv_small.hds (layers 1-3)", str(cm.exception))
        with self.assertRaises(MF6Error):
            hf.read(1, 9, 1)
        with self.assertRaises(MF6Error):
            hf.read_layers(1, 3)

    def test_dis_and_disu_records(self):
        hf = mf6.HeadFile(fx("dis_rotated", ".hds"))
        self.assertEqual([(r.ncol, r.nrow, r.ilay) for r in hf.records], [(4, 3, 1), (4, 3, 2)])
        self.assertEqual((hf.ncpl_per_record, hf.resolve("last")), (12, (1, 1)))
        hu = mf6.HeadFile(fx("disu_small", ".hds"))
        self.assertEqual([(r.kper, r.ncol, r.nrow, r.ilay) for r in hu.records], [(1, 13, 1, 1), (2, 13, 1, 1)])
        self.assertEqual((hu.layers, hu.read_layers(2, 1).shape), ([1], (1, 13)))

    def test_single_precision_and_a_file_being_written(self):
        folder = tempfile.mkdtemp(prefix="mf6_")
        path = os.path.join(folder, "single.hds")
        vals = [np.array([10.5, -1e30, 1e30, 12.25], np.float32), np.array([9.0, 8.0, 7.0, 6.0], np.float32)]
        with open(path, "wb") as fh:
            for k, v in enumerate(vals):
                fh.write(struct.pack("<iiff16siii", 1, k + 1, 1.0, float(k + 1), b"HEAD".rjust(16), 4, 1, 1))
                fh.write(v.tobytes())
            fh.write(struct.pack("<iiff16siii", 1, 3, 1.0, 3.0, b"HEAD".rjust(16), 4, 1, 1))
            fh.write(np.float32([1.0, 2.0]).tobytes())              # the last record is not complete yet
        hf = mf6.HeadFile(path)
        self.assertEqual((hf.precision, len(hf.records), hf.truncated, hf.periods()), ("single", 2, True, [1, 2]))
        np.testing.assert_array_equal(hf.read(1, 1, 1), [10.5, np.nan, np.nan, 12.25])
        self.assertEqual(hf.read(1, 2, 1).dtype, np.float64)
        bad = os.path.join(folder, "bad.hds")
        with open(bad, "wb") as fh:
            fh.write(b"\x00\x01" * 100)
        with self.assertRaises(MF6Error) as cm:
            mf6.HeadFile(bad)
        self.assertIn("not a MODFLOW head file", str(cm.exception))
        with self.assertRaises(MF6Error):
            mf6.HeadFile(os.path.join(folder, "missing.hds"))

    def test_records_that_are_not_heads(self):
        """A MODFLOW binary file of other records (a GWT concentration or GWE temperature file has the same layout)
        is not taken for heads; in a file mixing texts only the head records count."""
        folder = tempfile.mkdtemp(prefix="mf6_")
        with open(fx("disv_small", ".hds"), "rb") as fh:
            data = bytearray(fh.read())
        rec = 52 + 28 * 8
        conc = bytearray(data)
        for k in range(18):
            conc[k * rec + 24:k * rec + 40] = b"   CONCENTRATION"
        ucn = os.path.join(folder, "trans.ucn")
        with open(ucn, "wb") as fh:
            fh.write(conc)
        shutil.copy2(grb("disv_small"), os.path.join(folder, "trans.disv.grb"))
        with self.assertRaises(MF6Error) as cm:
            mf6.HeadFile(ucn)
        self.assertEqual(str(cm.exception), "trans.ucn holds CONCENTRATION records, not heads.")
        with self.assertRaises(MF6Error) as cm:
            mf6.find_model(ucn)                           # chosen with "All files": said so, not drawn as heads
        self.assertEqual(str(cm.exception), "trans.ucn holds CONCENTRATION records, not heads.")
        mixed = bytearray(data)
        mixed[24:40] = b"   CONCENTRATION"
        path = os.path.join(folder, "mixed.hds")
        with open(path, "wb") as fh:
            fh.write(mixed)
        hf = mf6.HeadFile(path)
        self.assertEqual((len(hf.records), hf.times()[0]), (17, (1, 1, 5.0)))
        self.assertEqual(hf.layers_at(1, 1), [2, 3])

    def test_unreadable_file_is_an_mf6_error(self):
        """A head file that can't be opened (locked by a backup or virus scanner, a OneDrive placeholder) or that
        shrank since it was looked at (a model run started again) is an MF6Error or a short index, never an OSError
        or struct.error."""
        folder = copy_case("disv_small")
        path = os.path.join(folder, "disv_small.hds")
        with mock.patch("builtins.open", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(MF6Error) as cm:
                mf6.HeadFile(path)
        self.assertEqual(str(cm.exception), "disv_small.hds: can't read (Permission denied).")
        hf = object.__new__(mf6.HeadFile)
        hf._index(path, os.path.getsize(path) + 1000)       # stat'ed when it was larger
        self.assertEqual((len(hf.records), hf.truncated), (18, True))

    def test_last_is_the_newest_complete_time(self):
        """"last" is the newest time at which every layer is saved: a file still being written (the model is
        running) may end inside a time step, cut in a record or between records."""
        folder = tempfile.mkdtemp(prefix="mf6_")
        full_path = fx("disv_small", ".hds")
        with open(full_path, "rb") as fh:
            data = fh.read()
        rec = 52 + 28 * 8
        cut = os.path.join(folder, "cut.hds")
        with open(cut, "wb") as fh:
            fh.write(data[:16 * rec + 100])          # SP 3, step 2: layer 1 and part of layer 2
        hf = mf6.HeadFile(cut)
        self.assertEqual((len(hf.records), hf.truncated, hf.incomplete, hf.partial), (16, True, True, True))
        self.assertEqual((hf.resolve("last"), hf.layers_at(3, 2)), ((2, 3), [1]))
        boundary = os.path.join(folder, "boundary.hds")
        with open(boundary, "wb") as fh:
            fh.write(data[:17 * rec])                # layers 1 and 2 of SP 3, step 2, cut between records
        hb = mf6.HeadFile(boundary)
        self.assertEqual((hb.truncated, hb.incomplete, hb.partial, hb.resolve("last")), (False, True, True, (2, 3)))
        self.assertFalse(mf6.HeadFile(full_path).partial)
        g = mf6.read_grid(grb("disv_small"))
        np.testing.assert_array_equal(mf6.surface_array(g, "wt", 1, boundary, "last"),
                                      mf6.surface_array(g, "wt", 1, full_path, "2,3"))
        with self.assertRaises(MF6Error) as cm:                    # never a water table from some layers only
            mf6.surface_array(g, "wt", 1, boundary, "3,2")
        self.assertEqual(str(cm.exception), "boundary.hds holds no heads of layer 3 at stress period 3, step 2: the "
                                            "water table needs every layer.")
        np.testing.assert_array_equal(mf6.surface_array(g, "head", 1, boundary, "3,2"),
                                      mf6.surface_array(g, "head", 1, full_path, "3,2"))

    def test_head_file_must_fit_the_grid(self):
        hf = mf6.HeadFile(fx("disu_small", ".hds"))
        with self.assertRaises(MF6Error) as cm:
            hf.check_grid(mf6.read_grid(grb("disv_small")))
        self.assertIn("13 values per layer", str(cm.exception))
        self.assertIn("belongs to another grid", str(cm.exception))
        mf6.HeadFile(fx("disv_small", ".hds")).check_grid(mf6.read_grid(grb("disv_small")))


class WaterTable(unittest.TestCase):
    def test_rules(self):
        nan = np.nan
        #                  wet  nan  HDRY inact pass  none HNOFLO newton all-below confined
        heads = np.array([[10.0, nan, -1e30, 10.0, 10.0, nan, 10.0, 4.0, 4.0, 4.0],
                          [9.0, 9.0, 9.0, 9.0, 9.0, nan, 9.0, 3.0, 2.5, 3.5],
                          [8.0, 8.0, 8.0, 8.0, 8.0, nan, 1e30, 2.0, 0.5, 2.0]])
        idomain = np.array([[1, 1, 1, 0, -1, 1, 1, 1, 1, 1],
                            [1, 1, 1, 1, 1, 1, 0, 1, 1, 1],
                            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]])
        botm = np.array([[5.0] * 10, [3.0] * 10, [1.0] * 10])
        icelltype = np.ones((3, 10), int)
        icelltype[0, 9] = 0                                         # a confined cell never dries
        np.testing.assert_array_equal(mf6.water_table(heads), [10, 9, 9, 10, 10, nan, 10, 4, 4, 4])
        np.testing.assert_array_equal(mf6.water_table(heads, idomain), [10, 9, 9, 9, 9, nan, 10, 4, 4, 4])
        # NEWTON: a head at or below its cell's bottom is a dry cell too (all below: the lowest head)
        np.testing.assert_array_equal(mf6.water_table(heads, idomain, botm), [10, 9, 9, 9, 9, nan, 10, 2, 0.5, 3.5])
        np.testing.assert_array_equal(mf6.water_table(heads, idomain, botm, icelltype),
                                      [10, 9, 9, 9, 9, nan, 10, 2, 0.5, 4])
        np.testing.assert_array_equal(mf6.water_table(heads[0], None), [10, nan, nan, 10, 10, nan, 10, 4, 4, 4])
        with self.assertRaises(MF6Error):
            mf6.water_table(heads, idomain[:2])
        with self.assertRaises(MF6Error):
            mf6.water_table(heads, None, botm[:, :3])
        with self.assertRaises(MF6Error):
            mf6.water_table(heads, None, botm, icelltype[:1])

    def test_disv_small(self):
        """Layer 1 is dry (HDRY) in the east column and inactive in one cell: the water table is layer 2 there."""
        g = mf6.read_grid(grb("disv_small"))
        hf = mf6.HeadFile(fx("disv_small", ".hds"))
        h = hf.read_layers(*hf.resolve("last"))
        wt = mf6.water_table(h, g.idomain)
        dry1 = np.isnan(h[0])
        self.assertEqual(int(dry1.sum()), 5)
        np.testing.assert_array_equal(wt[~dry1], h[0][~dry1])
        np.testing.assert_array_equal(wt[dry1], h[1][dry1])
        np.testing.assert_array_equal(wt[np.isclose(g.cellx, X0 + 3150.0)], 495.0)
        np.testing.assert_array_equal(mf6.water_table(h, g.idomain, g.botm), wt)   # no NEWTON: the same

    def test_newton_heads_below_the_bottom(self):
        """dis_rotated runs with NEWTON: dry layer-1 cells keep a head below their bottom (not HDRY)."""
        g = mf6.read_grid(grb("dis_rotated"))
        hf = mf6.HeadFile(fx("dis_rotated", ".hds"))
        h = hf.read_layers(1, 1)
        below = h[0] <= g.botm[0]
        self.assertEqual(np.nonzero(below)[0].tolist(), [3, 6, 7, 10, 11])
        self.assertFalse(np.isnan(h[0]).any())
        plain = mf6.water_table(h, g.idomain)
        newton = mf6.water_table(h, g.idomain, g.botm)
        np.testing.assert_array_equal(plain, h[0])
        np.testing.assert_array_equal(newton[~below], h[0][~below])
        np.testing.assert_array_equal(newton[below], h[1][below])
        self.assertAlmostEqual(newton[3], 470.0)                    # the east constant head in layer 2


class SurfaceArray(unittest.TestCase):
    def setUp(self):
        mf6.clear_cache()
        self.g = mf6.read_grid(grb("disv_small"))
        self.hds = fx("disv_small", ".hds")

    def test_top_and_bottoms(self):
        g = self.g
        top = mf6.surface_array(g, "top")
        off = g.idomain[0] == 0                                      # layer 1 inactive: layer 2's top
        np.testing.assert_array_equal(top[~off], g.top[~off])
        np.testing.assert_array_equal(top[off], g.botm[0][off])
        b3 = mf6.surface_array(g, "botm", 3)
        self.assertTrue(np.isnan(b3[g.idomain[2] == 0]).all())
        np.testing.assert_array_equal(b3[g.idomain[2] > 0], 400.0)
        b3[:] = 0.0                                                  # a fresh, writable array
        self.assertEqual(float(g.botm[2, 0]), 400.0)

    def test_heads_and_water_table(self):
        g = self.g
        hf = mf6.HeadFile(self.hds)
        np.testing.assert_array_equal(mf6.surface_array(g, "head", 2, self.hds, "2"), hf.read(2, 2, 3))
        np.testing.assert_array_equal(mf6.surface_array(g, "head", 1, self.hds, "1,1"), hf.read(1, 1, 1))
        wt = mf6.surface_array(g, "wt", 1, self.hds, "last")
        np.testing.assert_array_equal(wt, mf6.water_table(hf.read_layers(3, 2), g.idomain, g.botm, g.icelltype))
        with self.assertRaises(MF6Error):
            mf6.surface_array(g, "head", 1, "", "last")
        with self.assertRaises(MF6Error):
            mf6.surface_array(g, "head", 4, self.hds, "last")
        with self.assertRaises(MF6Error):
            mf6.surface_array(g, "head", 1, self.hds, "7")
        with self.assertRaises(MF6Error):
            mf6.surface_array(g, "head", 1, fx("disu_small", ".hds"), "last")
        with self.assertRaises(MF6Error):
            mf6.surface_array(g, "thickness")

    def test_newton_dry_heads_are_left_out(self):
        """dis_rotated runs with NEWTON: a dry layer-1 cell keeps a head at or below its bottom; the layer's head
        leaves it out, as HDRY cells are left out, and as the water table counts it dry."""
        g = mf6.read_grid(grb("dis_rotated"))
        hds = fx("dis_rotated", ".hds")
        raw = mf6.HeadFile(hds).read(1, 1, 1)
        dry = raw <= g.botm[0]
        self.assertEqual(np.nonzero(dry)[0].tolist(), [3, 6, 7, 10, 11])
        self.assertTrue((g.icelltype[0][dry] != 0).all())
        h1 = mf6.surface_array(g, "head", 1, hds, "last")
        self.assertTrue(np.isnan(h1[dry]).all())
        np.testing.assert_array_equal(h1[~dry], raw[~dry])
        wt = mf6.surface_array(g, "wt", 1, hds, "last")
        np.testing.assert_array_equal(wt[~dry], h1[~dry])          # the water table is layer 1 where it is wet
        confined = mf6.Grid(**{f: getattr(g, f) for f in ("kind", "nlay", "ncpl", "nrow", "ncol", "top", "botm",
                                                           "idomain", "verts", "iverts", "path")},
                            icelltype=np.zeros_like(g.icelltype))
        np.testing.assert_array_equal(mf6.surface_array(confined, "head", 1, hds, "last"), raw)   # never dries


class FindModel(unittest.TestCase):
    def setUp(self):
        mf6.clear_cache()

    def assert_files(self, m, case, head=True):
        folder = os.path.join(DATA, case)
        self.assertEqual(os.path.normcase(m.sim_dir), os.path.normcase(folder))
        self.assertEqual(m.model_name, case)
        self.assertEqual(m.kind, EXT[case])
        self.assertEqual(os.path.normcase(m.grid_path), os.path.normcase(grb(case)))
        self.assertEqual(os.path.normcase(m.dis_text_path), os.path.normcase(text(case)))
        if head:
            self.assertEqual(os.path.normcase(m.head_path), os.path.normcase(fx(case, ".hds")))

    def test_every_kind_of_path(self):
        for case in CASES:
            folder = os.path.join(DATA, case)
            for path in (folder, os.path.join(folder, "mfsim.nam"), fx(case, ".nam"), text(case), grb(case),
                         fx(case, ".hds")):
                with self.subTest(case=case, path=os.path.basename(path)):
                    m = mf6.find_model(path)
                    self.assert_files(m, case)
                    self.assertEqual(m.notes, [])
                    self.assertEqual(os.path.normcase(m.nam_path), os.path.normcase(fx(case, ".nam")))

    def test_model_name(self):
        m = mf6.find_model(os.path.join(DATA, "disv_small"), "DISV_SMALL")
        self.assertEqual((m.model_name, m.models), ("disv_small", ["disv_small"]))
        with self.assertRaises(MF6Error) as cm:
            mf6.find_model(os.path.join(DATA, "disv_small"), "other")
        self.assertIn("Model other is not in mfsim.nam (it lists disv_small)", str(cm.exception))

    def test_nothing_usable(self):
        empty = tempfile.mkdtemp(prefix="mf6_")
        with self.assertRaises(MF6Error) as cm:
            mf6.find_model(empty)
        self.assertIn("No MODFLOW 6 model in", str(cm.exception))
        with self.assertRaises(MF6Error) as cm:
            mf6.find_model(os.path.join(empty, "gone.hds"))
        self.assertIn("does not exist", str(cm.exception))
        with self.assertRaises(MF6Error):
            mf6.find_model("")
        junk = os.path.join(empty, "notes.txt")
        with open(junk, "w") as fh:
            fh.write("hello\n")
        with self.assertRaises(MF6Error) as cm:
            mf6.find_model(junk)
        self.assertIn("is not a MODFLOW 6 file", str(cm.exception))

    def test_grid_and_heads_without_name_files(self):
        folder = copy_case("disv_small")
        for f in ("mfsim.nam", "disv_small.nam", "disv_small.oc"):
            os.remove(os.path.join(folder, f))
        for path in (folder, os.path.join(folder, "disv_small.disv.grb"), os.path.join(folder, "disv_small.disv"),
                     os.path.join(folder, "disv_small.hds")):
            with self.subTest(path=os.path.basename(path)):
                m = mf6.find_model(path)
                self.assertEqual((m.kind, m.model_name), ("disv", "disv_small"))
                self.assertTrue(m.grid_path.endswith("disv_small.disv.grb"))
                self.assertTrue(m.head_path.endswith("disv_small.hds"))
                self.assertIn("No model name file", m.notes[0])

    def test_head_file_of_another_grid(self):
        folder = copy_case("disv_small")
        for f in ("mfsim.nam", "disv_small.nam", "disv_small.oc"):
            os.remove(os.path.join(folder, f))
        shutil.copy2(fx("disu_small", ".hds"), os.path.join(folder, "disv_small.hds"))
        m = mf6.find_model(os.path.join(folder, "disv_small.disv.grb"))
        self.assertEqual(m.head_path, "")
        self.assertIn("belongs to another grid", m.notes[-1])
        with self.assertRaises(MF6Error) as cm:
            mf6.find_model(os.path.join(folder, "disv_small.hds"))
        self.assertIn("No grid file found for disv_small.hds", str(cm.exception))

    def test_missing_head_file_and_grb(self):
        folder = copy_case("dis_rotated")
        os.remove(os.path.join(folder, "dis_rotated.hds"))
        os.remove(os.path.join(folder, "dis_rotated.dis.grb"))
        m = mf6.find_model(folder)
        self.assertEqual(os.path.normcase(m.grid_path), os.path.normcase(os.path.join(folder, "dis_rotated.dis")))
        self.assertEqual(m.head_path, "")
        self.assertEqual(m.notes, ["The head file dis_rotated.hds named in the output control is missing: run the "
                                   "model."])
        self.assertTrue(same(m.head_named, os.path.join(folder, "dis_rotated.hds")))   # where heads will appear
        self.assertEqual(mf6.read_grid(m.grid_path).ncpl, 12)

    def test_grb6_fileout(self):
        folder = copy_case("disv_small")
        os.rename(os.path.join(folder, "disv_small.disv.grb"), os.path.join(folder, "custom.grb"))
        dis = os.path.join(folder, "disv_small.disv")
        with open(dis) as fh:
            s = fh.read()
        with open(dis, "w") as fh:
            fh.write(s.replace("LENGTH_UNITS  feet", "LENGTH_UNITS  feet\n  GRB6  FILEOUT  custom.grb"))
        m = mf6.find_model(folder)
        self.assertTrue(m.grid_path.endswith("custom.grb"))
        self.assertEqual(mf6.find_model(os.path.join(folder, "custom.grb")).model_name, "disv_small")
        with open(dis, "w") as fh:
            fh.write(s.replace("LENGTH_UNITS  feet", "LENGTH_UNITS  feet\n  NOGRB"))
        self.assertTrue(mf6.find_model(folder).grid_path.endswith("disv_small.disv"))

    def test_no_output_control(self):
        folder = copy_case("disu_small")
        nam = os.path.join(folder, "disu_small.nam")
        with open(nam) as fh:
            s = fh.read()
        with open(nam, "w") as fh:
            fh.write(s.replace("  OC6  disu_small.oc  oc\n", ""))
        m = mf6.find_model(folder)
        self.assertEqual(m.head_path, "")
        self.assertIn("no output control", m.notes[0])


class Caching(unittest.TestCase):
    def setUp(self):
        mf6.clear_cache()

    def test_same_object_until_the_file_changes(self):
        folder = copy_case("disv_small")
        g_path, h_path = os.path.join(folder, "disv_small.disv.grb"), os.path.join(folder, "disv_small.hds")
        g = mf6.read_grid(g_path)
        self.assertIs(mf6.read_grid(g_path), g)
        self.assertIs(mf6.read_grid(os.path.relpath(g_path)), g)
        hf = mf6.HeadFile(h_path)
        self.assertIs(mf6.HeadFile(h_path), hf)
        self.assertIs(mf6.head_file(h_path), hf)
        st = os.stat(g_path)
        os.utime(g_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))     # touched: read again
        g2 = mf6.read_grid(g_path)
        self.assertIsNot(g2, g)
        np.testing.assert_array_equal(g2.botm, g.botm)
        self.assertIs(mf6.read_grid(g_path), g2)
        # the model ran again with fewer saved records
        with open(h_path, "rb") as fh:
            data = fh.read()
        with open(h_path, "wb") as fh:
            fh.write(data[:len(data) // 18 * 15])
        hf2 = mf6.HeadFile(h_path)
        self.assertIsNot(hf2, hf)
        self.assertEqual((len(hf2.records), hf2.resolve("last")), (15, (2, 3)))
        self.assertEqual(len(mf6._HEAD_CACHE), 1)                   # the old index is dropped

    def test_cached_arrays_are_read_only(self):
        g = mf6.read_grid(grb("disv_small"))
        for name in ("top", "botm", "idomain", "verts", "cellx", "celly"):
            with self.assertRaises(ValueError, msg=name):
                getattr(g, name)[0] = 0
        with self.assertRaises(ValueError):
            g.botm[1][:] = 0                                        # a view of a cached array
        with self.assertRaises(ValueError):
            g.cell_bounds_world()[0, 0] = 0
        self.assertIs(g.cell_bounds_world(), g.cell_bounds_world())

    def test_cache_is_bounded(self):
        folder = tempfile.mkdtemp(prefix="mf6_")
        for k in range(mf6._CACHE_MAX + 3):
            p = os.path.join(folder, f"g{k}.disv.grb")
            shutil.copy2(grb("disv_small"), p)
            mf6.new_generation()                                    # each read a use of its own
            mf6.read_grid(p)
        self.assertEqual(len(mf6._GRID_CACHE), mf6._CACHE_MAX)

    def test_one_use_keeps_everything_it_reads(self):
        """A section of more models than _CACHE_MAX: one use (one build) keeps every grid it reads, so the next
        build, reading them in the same order, hits every time instead of evicting each just before it is needed;
        a later use evicts the ones it does not use down to the limit."""
        folder = tempfile.mkdtemp(prefix="mf6_")
        paths = []
        for k in range(mf6._CACHE_MAX + 3):
            paths.append(os.path.join(folder, f"g{k}.disv.grb"))
            shutil.copy2(grb("disv_small"), paths[-1])
        mf6.new_generation()
        grids = [mf6.read_grid(p) for p in paths]
        self.assertEqual(len(mf6._GRID_CACHE), len(paths))
        mf6.new_generation()
        with mock.patch.object(mf6, "_grid_from_grb", side_effect=AssertionError("read again")):
            self.assertTrue(all(mf6.read_grid(p) is g for p, g in zip(paths, grids)))
        mf6.new_generation()
        extra = os.path.join(folder, "extra.disv.grb")
        shutil.copy2(grb("disv_small"), extra)
        mf6.read_grid(paths[-1])
        mf6.read_grid(extra)
        self.assertEqual(len(mf6._GRID_CACHE), mf6._CACHE_MAX)
        self.assertIs(mf6.read_grid(paths[-1]), grids[-1])           # used in this generation: kept


# ======================================================================================================= real data
F9 = os.path.join(REALDATA, "mf6", "F9_flowV1")
CDF = os.path.join(REALDATA, "mf6", "CDF_Mounding")


@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealModels(unittest.TestCase):
    """The user's models (read-only copies): F9_flowV1 (DISV, 3 layers, 30 periods, NEWTON) and CDF_Mounding (DISU)."""

    def setUp(self):
        mf6.clear_cache()

    @timing_test
    def test_f9_grid(self):
        t0 = time.perf_counter()
        g = mf6.read_grid(os.path.join(F9, "F9_flowV1.disv.grb"))
        dt = time.perf_counter() - t0
        t0 = time.perf_counter()
        b = g.cell_bounds_world()
        dtb = time.perf_counter() - t0
        print(f"\n  F9 .grb read {dt:.3f} s, cell bounds {dtb:.3f} s: {g.summary()}")
        self.assertLess(dt, budget(2.0))
        self.assertEqual((g.kind, g.nlay, g.ncpl, g.ncells, len(g.verts)), ("disv", 3, 27688, 83064, 56478))
        self.assertEqual(g.length_units, "feet")
        self.assertEqual((g.xorigin, g.yorigin, g.angrot), (0.0, 0.0, 0.0))
        self.assertTrue((g.idomain == 1).all())
        self.assertEqual(int(g.iverts.offsets[-1]), 193217 - 27688)  # NJAVERT less one closing vertex per cell
        self.assertTrue(g.has_vertices)
        xmin, ymin, xmax, ymax = g.extent_world()                  # WA State Plane South, US feet
        self.assertTrue(1.2e6 < xmin < xmax < 1.3e6 and 7.0e5 < ymin < ymax < 8.0e5, g.extent_world())
        inside = (b[:, 0] <= g.cellx) & (g.cellx <= b[:, 2]) & (b[:, 1] <= g.celly) & (g.celly <= b[:, 3])
        self.assertTrue(inside.all())
        self.assertTrue((g.layer_tops() - g.botm > 0).all())
        print(f"  F9 sums: TOP {g.top.sum():,.3f}, BOTM {g.botm.sum(axis=1).round(3).tolist()}")

    @timing_test
    def test_f9_text_equals_grb(self):
        g = mf6.read_grid(os.path.join(F9, "F9_flowV1.disv.grb"))
        t0 = time.perf_counter()
        t = mf6.read_grid(os.path.join(F9, "F9_flowV1.disv"))
        dt = time.perf_counter() - t0
        print(f"\n  F9 .disv text (6.5 MB) read {dt:.3f} s")
        self.assertLess(dt, budget(5.0))
        self.assertEqual((t.nlay, t.ncpl, t.length_units, t.source), (3, 27688, "feet", "text"))
        np.testing.assert_array_equal(t.top, g.top)
        np.testing.assert_array_equal(t.botm, g.botm)
        np.testing.assert_array_equal(t.verts, g.verts)
        np.testing.assert_array_equal(t.cellx, g.cellx)
        np.testing.assert_array_equal(t.iverts.offsets, g.iverts.offsets)
        np.testing.assert_array_equal(t.iverts.indices, g.iverts.indices)
        for i in range(0, t.ncpl, 997):
            np.testing.assert_array_equal(t.cell_vertices(i), g.cell_vertices(i))

    def test_f9_heads(self):
        t0 = time.perf_counter()
        hf = mf6.HeadFile(os.path.join(F9, "F9_flowV1.hds"))
        dti = time.perf_counter() - t0
        self.assertEqual((len(hf.records), hf.precision, hf.ncpl_per_record, hf.layers), (90, "double", 27688, [1, 2, 3]))
        self.assertEqual(hf.periods(), list(range(1, 31)))
        # one saved step per period (SAVE HEAD LAST); adaptive time stepping (ATS) took 16 and 14 steps in periods
        # 16 and 17, 13 elsewhere
        self.assertEqual({k: hf.steps(k) for k in (15, 16, 17, 18)}, {15: [13], 16: [16], 17: [14], 18: [13]})
        self.assertEqual(sum(len(hf.steps(k)) for k in hf.periods()), 30)
        np.testing.assert_allclose([t[2] for t in hf.times()], np.arange(1.0, 31.0), atol=1e-9)
        self.assertEqual(hf.resolve("16"), (16, 16))
        self.assertEqual(hf.resolve("30"), (30, 13))
        self.assertEqual(hf.resolve("last"), (30, 13))
        self.assertEqual(hf.resolve("12"), (12, 13))
        with self.assertRaises(MF6Error):
            hf.resolve("12,5")
        g = mf6.read_grid(os.path.join(F9, "F9_flowV1.disv.grb"))
        hf.check_grid(g)
        t0 = time.perf_counter()
        h = hf.read_layers(30, 13)
        dtr = time.perf_counter() - t0
        print(f"\n  F9 .hds (20 MB) index {dti:.4f} s, read 3 layers {dtr:.4f} s")
        self.assertEqual(h.shape, (3, 27688))
        self.assertFalse(np.isnan(h).any())                          # NEWTON: no HDRY values
        below = (h <= g.botm).sum(axis=1)
        self.assertGreater(below[0], 0)                              # ... but dry cells below their bottoms
        wt = mf6.surface_array(g, "wt", 1, hf.path, "last")
        self.assertFalse(np.isnan(wt).any())
        h1 = mf6.surface_array(g, "head", 1, hf.path, "last")         # NEWTON dry cells left out of the layer head
        self.assertEqual(int(np.isnan(h1).sum()), int(below[0]))
        self.assertTrue(np.isnan(h1[h[0] <= g.botm[0]]).all())
        self.assertTrue((h1[np.isfinite(h1)] > g.botm[0][np.isfinite(h1)]).all())
        differ = np.abs(wt - mf6.water_table(h, g.idomain)) > 0.01
        print(f"  F9 period 30: heads at or below the cell bottom per layer {below.tolist()}; the water table "
              f"skips them in {int(differ.sum())} columns (by up to {np.abs(wt - mf6.water_table(h, g.idomain)).max():.2f} ft)")

    def test_f9_find_model(self):
        for path in (F9, os.path.join(F9, "mfsim.nam"), os.path.join(F9, "F9_flowV1.hds"),
                     os.path.join(F9, "F9_flowV1.disv")):
            m = mf6.find_model(path)
            self.assertEqual((m.model_name, m.kind), ("F9_flowV1", "disv"))
            self.assertTrue(m.grid_path.endswith("F9_flowV1.disv.grb"))
            self.assertTrue(m.head_path.endswith("F9_flowV1.hds"))

    def test_cdf_disu(self):
        t0 = time.perf_counter()
        g = mf6.read_grid(os.path.join(CDF, "CDF_Mounding.disu.grb"))
        dt = time.perf_counter() - t0
        self.assertEqual((g.kind, g.nlay, g.ncpl), ("disu", 1, 9546))
        self.assertIsNone(g.idomain)                                 # an older .grb: 15 definitions, no IDOMAIN
        self.assertEqual(g.length_units, "unknown")                  # CDF_Mounding.disu itself was not copied
        self.assertTrue(g.has_vertices)
        self.assertEqual(len(g.verts), 18432)
        hf = mf6.HeadFile(os.path.join(CDF, "CDF_Mounding.hds"))
        self.assertEqual((len(hf.records), hf.ncpl_per_record, hf.layers, hf.periods()), (49, 9546, [1], list(range(1, 50))))
        hf.check_grid(g)
        self.assertEqual(hf.resolve("last"), (49, 15))
        h = hf.read(1, 49, 15)
        print(f"\n  CDF .disu.grb read {dt:.3f} s: {g.summary()}; heads {np.nanmin(h):.1f}-{np.nanmax(h):.1f}")
        m = mf6.find_model(CDF)
        self.assertEqual((m.kind, m.model_name, m.dis_text_path), ("disu", "CDF_Mounding", ""))
        self.assertTrue(m.grid_path.endswith("CDF_Mounding.disu.grb"))
        self.assertTrue(m.head_path.endswith("CDF_Mounding.hds"))
        # the older 1-layer DISV next to it is a different grid: its head file does not fit
        old = mf6.find_model(os.path.join(CDF, "CDF_Mounding.disv.grb"))
        self.assertEqual((old.kind, old.head_path), ("disv", ""))
        self.assertIn("belongs to another grid", old.notes[-1])

    def test_nothing_written_next_to_the_copies(self):
        before = {f: os.stat(os.path.join(F9, f)).st_mtime_ns for f in os.listdir(F9)}
        mf6.find_model(F9)
        mf6.surface_array(mf6.read_grid(os.path.join(F9, "F9_flowV1.disv.grb")), "head", 2,
                          os.path.join(F9, "F9_flowV1.hds"), "15")
        self.assertEqual({f: os.stat(os.path.join(F9, f)).st_mtime_ns for f in os.listdir(F9)}, before)


if __name__ == "__main__":
    unittest.main()
