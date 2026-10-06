"""Regenerate the MODFLOW 6 fixtures in tests/data/mf6/<case>/ (plain Python, no flopy).

Each case is a tiny real model: the input files are written by hand here, MODFLOW 6 is run on them in a work
folder, and only the files the tests read are copied into tests/data/mf6/<case>/ (name files, the text grid file
and its external arrays, the binary grid file, the head file, the OC and TDIS files and a head-observation CSV
used as an independent check of the head file).

    python make_fixtures.py [--work DIR] [--mf6 PATH] [case ...]

Cases (all in the area of tests/fixtures.py: EPSG:2927, X0 = 1,200,000, Y0 = 650,000 ftUS, LENGTH_UNITS feet):

- disv_small: DISV, 3 layers, 28 cells per layer (24 quads, 4 of them split into 2 triangles; some CELL2D rings
  are written closed, first vertex repeated: cells 1, 10, 14 and 19), vertices in world coordinates (XORIGIN 0), IDOMAIN 0 at three
  cells of layer 3 and one of layer 1, transient (3 stress periods of 2, 3 and 2 steps; OC saves every step of
  periods 1-2 and the last step of period 3), standard formulation with a convertible layer 1 that goes dry
  (HDRY -1e30 in the head file) in the east. The section line of tests/fixtures.py (y = Y0 + 2000 from
  X0 + 500 to X0 + 3000, then to X0 + 5000, Y0 + 2600) crosses it from the first column, through the triangles,
  and leaves it at x = X0 + 3400.
- dis_rotated: DIS, 2 layers x 3 rows x 4 columns with uneven DELR / DELC, XORIGIN / YORIGIN set and ANGROT 30,
  TOP from an OPEN/CLOSE text file with FACTOR 2, BOTM LAYERED (INTERNAL with IPRN, then an OPEN/CLOSE (BINARY)
  file), IDOMAIN LAYERED (CONSTANT, then INTERNAL with one 0), steady state, NEWTON: layer 1 is dry in the east
  with heads BELOW its bottom (not HDRY), as in the user's NEWTON models.
- disu_small: DISU, 1 layer, 13 nodes (12 quads, one split into 2 triangles) with VERTICES / CELL2D, XORIGIN /
  YORIGIN / ANGROT 15, 2 steady stress periods.
"""
import argparse
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
X0, Y0 = 1_200_000.0, 650_000.0
DEFAULT_MF6 = r"C:/Users/lukem/Python/PATH/modflow_exe/mf6.exe"


# ----------------------------------------------------------------------------------------------- writing helpers
def fmt(v):
    if isinstance(v, int):
        return str(v)
    return repr(float(v))


def internal(values, per_line=8, indent="      ", header="    INTERNAL  FACTOR  1.0"):
    lines = [header]
    for i in range(0, len(values), per_line):
        lines.append(indent + "  ".join(fmt(v) for v in values[i:i + per_line]))
    return "\n".join(lines)


def write(folder, name, text):
    with open(os.path.join(folder, name), "w", newline="\n") as fh:
        fh.write(text.strip("\n") + "\n")


def binary_array(path, values, ncol, nrow, ilay, text="BOTM"):
    """A MODFLOW binary array file: one 52-byte header record, then the values (float64, little endian)."""
    with open(path, "wb") as fh:
        fh.write(struct.pack("<iidd", 1, 1, 0.0, 0.0))
        fh.write(text.rjust(16).encode("ascii"))
        fh.write(struct.pack("<iii", ncol, nrow, ilay))
        fh.write(struct.pack("<%dd" % len(values), *values))


def mfsim(name, tdis=True):
    return f"""
# MODFLOW 6 simulation name file (hand written by tests/data/mf6/make_fixtures.py)
BEGIN options
END options

BEGIN timing
  TDIS6  {name}.tdis
END timing

BEGIN models
  gwf6  {name}.nam  {name}
END models

BEGIN exchanges
END exchanges

BEGIN solutiongroup  1
  ims6  {name}.ims  {name}
END solutiongroup  1
"""


def tdis(periods):
    rows = "\n".join(f"  {perlen!r}  {nstp}  1.0" for perlen, nstp in periods)
    return f"""
BEGIN options
  TIME_UNITS  days
END options

BEGIN dimensions
  NPER  {len(periods)}
END dimensions

BEGIN perioddata
{rows}
END perioddata
"""


def ims(newton=False):
    accel = "bicgstab" if newton else "cg"
    under = "  UNDER_RELAXATION  simple\n  UNDER_RELAXATION_GAMMA  0.9\n" if newton else ""
    return f"""
BEGIN options
  PRINT_OPTION  summary
  COMPLEXITY  {"complex" if newton else "moderate"}
END options

BEGIN nonlinear
  OUTER_DVCLOSE  1.0e-7
  OUTER_MAXIMUM  500
{under}END nonlinear

BEGIN linear
  INNER_MAXIMUM  200
  INNER_DVCLOSE  1.0e-9
  INNER_RCLOSE  1.0e-7
  LINEAR_ACCELERATION  {accel}
END linear
"""


def model_nam(name, dis_ftype, dis_ext, newton=False, sto=True):
    opts = "  NEWTON\n" if newton else ""
    sto_line = f"  STO6  {name}.sto  sto\n" if sto else ""
    return f"""
# MODFLOW 6 groundwater flow model name file
BEGIN options
{opts}END options

BEGIN packages
  {dis_ftype}  {name}.{dis_ext}  {dis_ext}
  IC6  {name}.ic  ic
  NPF6  {name}.npf  npf
{sto_line}  CHD6  {name}.chd  chd
  OC6  {name}.oc  oc
  OBS6  {name}.obs  head_obs
END packages
"""


def oc(name, period_blocks):
    blocks = "\n\n".join(f"BEGIN period  {k}\n  {what}\nEND period  {k}" for k, what in period_blocks)
    return f"""
BEGIN options
  HEAD  FILEOUT  {name}.hds
END options

{blocks}
"""


def obs(name, rows):
    body = "\n".join(f"  {oname}  HEAD  {cellid}" for oname, cellid in rows)
    return f"""
BEGIN options
  DIGITS  15
END options

BEGIN continuous  FILEOUT  {name}.obs.csv
{body}
END continuous
"""


def chd(periods):
    """periods: {kper: [(cellid_text, head), ...]}"""
    blocks = []
    for kper in sorted(periods):
        rows = "\n".join(f"  {cid}  {fmt(h)}" for cid, h in periods[kper])
        blocks.append(f"BEGIN period  {kper}\n{rows}\nEND period  {kper}")
    maxbound = max(len(v) for v in periods.values())
    return f"""
BEGIN options
END options

BEGIN dimensions
  MAXBOUND  {maxbound}
END dimensions

""" + "\n\n".join(blocks)


def polygon_area(pts):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return a / 2.0                      # negative for a clockwise ring


def centroid(pts):
    a = polygon_area(pts)
    cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        f = x1 * y2 - x2 * y1
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    return cx / (6.0 * a), cy / (6.0 * a)


def quad_grid(x0, y0, ncol, nrow, dx, dy, split, closed=()):
    """Vertices (row-major from the north row of nodes) and clockwise cells of a quad grid with some quads split
    into two triangles. Returns verts [(x, y)], cells [dict(ring=[0-based vertex ids], rc=(row, col))]."""
    verts = [(x0 + c * dx, y0 + (nrow - r) * dy) for r in range(nrow + 1) for c in range(ncol + 1)]

    def v(r, c):
        return r * (ncol + 1) + c

    cells = []
    for r in range(nrow):
        for c in range(ncol):
            ul, ur, lr, ll = v(r, c), v(r, c + 1), v(r + 1, c + 1), v(r + 1, c)
            if (r, c) in split:
                rings = ([ul, ur, lr], [ul, lr, ll]) if (r + c) % 2 else ([ul, ur, ll], [ur, lr, ll])
            else:
                rings = ([ul, ur, lr, ll],)
            for ring in rings:
                assert polygon_area([verts[i] for i in ring]) < 0, "rings must be clockwise"
                cells.append(dict(ring=ring, rc=(r, c)))
    for i in closed:
        cells[i]["closed"] = True
    return verts, cells


def cell2d_block(verts, cells):
    rows = []
    for i, cell in enumerate(cells):
        pts = [verts[j] for j in cell["ring"]]
        xc, yc = centroid(pts)
        cell["xc"], cell["yc"] = xc, yc
        ring = [j + 1 for j in cell["ring"]]
        if cell.get("closed"):
            ring = ring + ring[:1]
        rows.append(f"  {i + 1}  {xc!r}  {yc!r}  {len(ring)}  " + "  ".join(str(j) for j in ring))
    return "BEGIN cell2d\n" + "\n".join(rows) + "\nEND cell2d"


def vertices_block(verts):
    return "BEGIN vertices\n" + "\n".join(f"  {i + 1}  {x!r}  {y!r}" for i, (x, y) in enumerate(verts)) + \
        "\nEND vertices"


# ------------------------------------------------------------------------------------------------------- cases
def case_disv_small(folder):
    name = "disv_small"
    ncol, nrow = 6, 4
    verts, cells = quad_grid(X0 + 400.0, Y0 + 1600.0, ncol, nrow, 500.0, 250.0,
                             split={(1, 2), (1, 3), (2, 2), (2, 3)}, closed=(0, 9, 13, 18))
    c2d = cell2d_block(verts, cells)
    ncpl = len(cells)
    top = [round(500.0 + 0.01 * (c["xc"] - X0) + 0.005 * (c["yc"] - Y0), 6) for c in cells]
    b1 = [round(500.0 + 0.004 * (c["xc"] - X0), 6) for c in cells]
    b2 = [round(470.0 - 0.002 * (c["xc"] - X0), 6) for c in cells]
    b3 = [400.0] * ncpl
    idom = [[1] * ncpl for _ in range(3)]
    for i, c in enumerate(cells):
        if c["rc"] in ((0, 3), (0, 4), (3, 4)):
            idom[2][i] = 0
        if c["rc"] == (3, 1):
            idom[0][i] = 0
    write(folder, f"{name}.disv", f"""
# DISV: 3 layers, 28 cells per layer (quads and triangles), world coordinates
BEGIN options
  LENGTH_UNITS  feet
END options

BEGIN dimensions
  NLAY  3
  NCPL  {ncpl}
  NVERT  {len(verts)}
END dimensions

BEGIN griddata
  top
{internal(top)}
  botm  LAYERED
{internal(b1)}
{internal(b2)}
{internal(b3)}
  idomain  LAYERED
{internal(idom[0], per_line=14)}
    CONSTANT  1
{internal(idom[2], per_line=14)}
END griddata

{vertices_block(verts)}

{c2d}
""")
    write(folder, "mfsim.nam", mfsim(name))
    write(folder, f"{name}.tdis", tdis([(10.0, 2), (30.0, 3), (20.0, 2)]))
    write(folder, f"{name}.ims", ims())
    write(folder, f"{name}.nam", model_nam(name, "DISV6", "disv"))
    write(folder, f"{name}.ic", "BEGIN griddata\n  strt\n    CONSTANT  520.0\nEND griddata")
    write(folder, f"{name}.npf", """
BEGIN options
END options

BEGIN griddata
  icelltype  LAYERED
    CONSTANT  1
    CONSTANT  0
    CONSTANT  0
  k  LAYERED
    CONSTANT  10.0
    CONSTANT  5.0
    CONSTANT  2.0
END griddata
""")
    write(folder, f"{name}.sto", """
BEGIN options
END options

BEGIN griddata
  iconvert  LAYERED
    CONSTANT  1
    CONSTANT  0
    CONSTANT  0
  ss
    CONSTANT  1.0e-5
  sy
    CONSTANT  0.2
END griddata

BEGIN period  1
  TRANSIENT
END period  1
""")
    west = [i for i, c in enumerate(cells) if c["rc"][1] == 0]
    east = [i for i, c in enumerate(cells) if c["rc"][1] == ncol - 1]
    periods = {}
    for kper, h_east in ((1, 505.0), (2, 500.0), (3, 495.0)):
        rows = [(f"{lay}  {i + 1}", 525.0) for lay in (1, 2, 3) for i in west]
        rows += [(f"{lay}  {i + 1}", h_east) for lay in (2, 3) for i in east]
        periods[kper] = rows
    write(folder, f"{name}.chd", chd(periods))
    write(folder, f"{name}.oc", oc(name, [(1, "SAVE  HEAD  ALL"), (3, "SAVE  HEAD  LAST")]))
    # observations: a west CHD cell, cells along the section row in every layer, an east layer-1 cell (dry)
    probe = [west[0], 13, 14, 16, 17, east[-1]]
    rows = [(f"h{lay}_{i + 1}", f"{lay}  {i + 1}") for lay in (1, 2, 3) for i in probe]
    write(folder, f"{name}.obs", obs(name, rows))
    return name, [f"{name}.disv"]


def case_dis_rotated(folder):
    name = "dis_rotated"
    nlay, nrow, ncol = 2, 3, 4
    delr = [100.0, 150.0, 100.0, 200.0]
    delc = [50.0, 80.0, 60.0]
    top = [520.0 + 2.0 * c - 1.0 * r for r in range(nrow) for c in range(ncol)]
    b1 = [490.0 + 0.5 * c + 0.25 * r for r in range(nrow) for c in range(ncol)]
    b2 = [400.0 - 1.0 * c for r in range(nrow) for c in range(ncol)]
    idom2 = [1] * (nrow * ncol)
    idom2[0 * ncol + 2] = 0                     # layer 2, row 1, column 3
    with open(os.path.join(folder, f"{name}.top.txt"), "w", newline="\n") as fh:
        for r in range(nrow):
            fh.write("  ".join(repr(v / 2.0) for v in top[r * ncol:(r + 1) * ncol]) + "\n")
    binary_array(os.path.join(folder, f"{name}.botm2.bin"), b2, ncol, nrow, 2)
    write(folder, f"{name}.dis", f"""
# DIS with an origin and a rotation; arrays from internal, constant, text and binary sources
BEGIN options
  LENGTH_UNITS  feet
  XORIGIN  {X0 + 1000.0!r}
  YORIGIN  {Y0 + 800.0!r}
  ANGROT  30.0
END options

BEGIN dimensions
  NLAY  {nlay}
  NROW  {nrow}
  NCOL  {ncol}
END dimensions

BEGIN griddata
  delr
{internal(delr)}
  delc
    INTERNAL
      {"  ".join(fmt(v) for v in delc)}
  top
    OPEN/CLOSE  '{name}.top.txt'  FACTOR  2.0
  botm  LAYERED
{internal(b1, per_line=4, header="    INTERNAL  FACTOR  1.0  IPRN  1")}
    OPEN/CLOSE  {name}.botm2.bin  FACTOR  1.0  (BINARY)
  idomain  LAYERED
    CONSTANT  1
{internal(idom2, per_line=4, header="    INTERNAL")}
END griddata
""")
    write(folder, "mfsim.nam", mfsim(name))
    write(folder, f"{name}.tdis", tdis([(1.0, 1)]))
    write(folder, f"{name}.ims", ims(newton=True))
    write(folder, f"{name}.nam", model_nam(name, "DIS6", "dis", newton=True, sto=False))
    write(folder, f"{name}.ic", "BEGIN griddata\n  strt\n    CONSTANT  500.0\nEND griddata")
    write(folder, f"{name}.npf", """
BEGIN options
END options

BEGIN griddata
  icelltype  LAYERED
    CONSTANT  1
    CONSTANT  0
  k
    CONSTANT  10.0
END griddata
""")
    rows = [(f"{lay}  {r}  1", 505.0) for lay in (1, 2) for r in (1, 2, 3)]
    rows += [(f"2  {r}  {ncol}", 470.0) for r in (1, 2, 3)]
    write(folder, f"{name}.chd", chd({1: rows}))
    write(folder, f"{name}.oc", oc(name, [(1, "SAVE  HEAD  ALL")]))
    probe = [(lay, r, c) for lay in (1, 2) for r in (1, 3) for c in (1, 2, 4)]
    write(folder, f"{name}.obs", obs(name, [(f"h{lay}_{r}_{c}", f"{lay}  {r}  {c}") for lay, r, c in probe]))
    return name, [f"{name}.dis", f"{name}.top.txt", f"{name}.botm2.bin"]


def case_disu_small(folder):
    name = "disu_small"
    ncol, nrow = 4, 3
    verts, cells = quad_grid(0.0, 0.0, ncol, nrow, 300.0, 200.0, split={(1, 1)}, closed=(2,))
    c2d = cell2d_block(verts, cells)
    nodes = len(cells)
    # connections: cells sharing an edge (two consecutive ring vertices)
    edges = {}
    for i, cell in enumerate(cells):
        ring = cell["ring"]
        for a, b in zip(ring, ring[1:] + ring[:1]):
            edges.setdefault((min(a, b), max(a, b)), []).append(i)
    nbrs = {i: {} for i in range(nodes)}
    for (a, b), owners in edges.items():
        if len(owners) == 2:
            i, j = owners
            nbrs[i][j] = (a, b)
            nbrs[j][i] = (a, b)

    def dist_to_edge(cell, a, b):
        (x1, y1), (x2, y2) = verts[a], verts[b]
        px, py = cell["xc"], cell["yc"]
        return abs((x2 - x1) * (y1 - py) - (x1 - px) * (y2 - y1)) / math.hypot(x2 - x1, y2 - y1)

    iac, ja, ihc, cl12, hwva = [], [], [], [], []
    for i in range(nodes):
        others = sorted(nbrs[i])
        iac.append(1 + len(others))
        ja.append(i + 1)
        ihc.append(1)
        cl12.append(0.0)
        hwva.append(0.0)
        for j in others:
            a, b = nbrs[i][j]
            ja.append(j + 1)
            ihc.append(1)
            cl12.append(round(dist_to_edge(cells[i], a, b), 6))
            hwva.append(round(math.dist(verts[a], verts[b]), 6))
    area = [round(-polygon_area([verts[j] for j in c["ring"]]), 6) for c in cells]
    top = [round(520.0 - 0.01 * c["xc"] + 0.005 * c["yc"], 6) for c in cells]
    bot = [round(480.0 - 0.002 * c["xc"], 6) for c in cells]
    write(folder, f"{name}.disu", f"""
# DISU: one layer of 13 nodes with vertices, rotated about its origin
BEGIN options
  LENGTH_UNITS  feet
  XORIGIN  {X0 + 1200.0!r}
  YORIGIN  {Y0 + 1700.0!r}
  ANGROT  15.0
END options

BEGIN dimensions
  NODES  {nodes}
  NJA  {len(ja)}
  NVERT  {len(verts)}
END dimensions

BEGIN griddata
  top
{internal(top)}
  bot
{internal(bot)}
  area
{internal(area)}
END griddata

BEGIN connectiondata
  iac
{internal(iac, per_line=13, header="    INTERNAL")}
  ja
{internal(ja, per_line=13, header="    INTERNAL")}
  ihc
{internal(ihc, per_line=13, header="    INTERNAL")}
  cl12
{internal(cl12)}
  hwva
{internal(hwva)}
END connectiondata

{vertices_block(verts)}

{c2d}
""")
    write(folder, "mfsim.nam", mfsim(name))
    write(folder, f"{name}.tdis", tdis([(1.0, 1), (1.0, 1)]))
    write(folder, f"{name}.ims", ims())
    write(folder, f"{name}.nam", model_nam(name, "DISU6", "disu", sto=False))
    write(folder, f"{name}.ic", "BEGIN griddata\n  strt\n    CONSTANT  505.0\nEND griddata")
    write(folder, f"{name}.npf", """
BEGIN options
END options

BEGIN griddata
  icelltype
    CONSTANT  0
  k
    CONSTANT  10.0
END griddata
""")
    west = [i for i, c in enumerate(cells) if c["rc"][1] == 0]
    east = [i for i, c in enumerate(cells) if c["rc"][1] == ncol - 1]
    periods = {kper: [(str(i + 1), 510.0) for i in west] + [(str(i + 1), h) for i in east]
               for kper, h in ((1, 500.0), (2, 495.0))}
    write(folder, f"{name}.chd", chd(periods))
    write(folder, f"{name}.oc", oc(name, [(1, "SAVE  HEAD  ALL")]))
    write(folder, f"{name}.obs", obs(name, [(f"h{i + 1}", str(i + 1)) for i in range(nodes)]))
    return name, [f"{name}.disu"]


CASES = {"disv_small": case_disv_small, "dis_rotated": case_dis_rotated, "disu_small": case_disu_small}


def run_case(case, work, mf6):
    folder = os.path.join(work, case)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    name, inputs = CASES[case](folder)
    proc = subprocess.run([mf6], cwd=folder, capture_output=True, text=True)
    lst = os.path.join(folder, "mfsim.lst")
    ok = os.path.exists(lst) and "Normal termination" in open(lst, errors="replace").read()
    if proc.returncode != 0 or not ok:
        sys.stdout.write(proc.stdout[-3000:] + proc.stderr[-2000:])
        raise RuntimeError(f"{case}: MODFLOW 6 did not finish normally (see {lst})")
    dis_file = inputs[0]
    keep = ["mfsim.nam", f"{name}.nam", f"{name}.oc", f"{name}.tdis", f"{name}.hds", f"{dis_file}.grb",
            f"{name}.obs.csv"] + inputs
    dest = os.path.join(HERE, case)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    for f in keep:
        shutil.copy2(os.path.join(folder, f), os.path.join(dest, f))
    size = sum(os.path.getsize(os.path.join(dest, f)) for f in keep)
    print(f"{case}: {len(keep)} files, {size:,} bytes -> {dest}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cases", nargs="*", default=list(CASES))
    ap.add_argument("--work", default="", help="work folder for the model runs (default: a new temp folder)")
    ap.add_argument("--mf6", default=os.environ.get("MF6_EXE", ""), help="mf6 executable")
    args = ap.parse_args(argv)
    mf6 = args.mf6 or (DEFAULT_MF6 if os.path.exists(DEFAULT_MF6) else shutil.which("mf6"))
    if not mf6:
        sys.exit("mf6 executable not found: pass --mf6 or set MF6_EXE")
    work = args.work or tempfile.mkdtemp(prefix="mf6_fixtures_")
    for case in args.cases:
        run_case(case, work, mf6)


if __name__ == "__main__":
    main()
