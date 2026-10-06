"""MODFLOW 6 readers in plain numpy (no QGIS, no flopy).

- read_grid(path) -> Grid: a binary grid file (.grb: DIS, DISV or DISU, definitions read by name) or a text grid
  file (.dis / .disv / .disu with CONSTANT, INTERNAL and OPEN/CLOSE arrays, LAYERED, VERTICES, CELL2D).
- HeadFile(path): the records of a binary head file (.hds), indexed without reading the data; read(layer, kper,
  kstp) gives one layer with nan for dry (HDRY -1e30) and inactive (HNOFLO 1e30) cells.
- water_table(heads, idomain, botm): per cell column, the head of the uppermost wet layer.
- find_model(path) -> ModelFiles: the grid, text grid and head files of a model from a run folder, mfsim.nam, a
  model name file, a grid file or a head file.
- surface_array(grid, var, layer, head_path, time): one surface of MF6_VARS ("top", "botm", "head", "wt") per cell.

Coordinates: the grid's vertices and cell centres are MODEL coordinates; Grid.to_world() applies XORIGIN, YORIGIN
and ANGROT (degrees, counter-clockwise about the origin): X = xo + x cos a - y sin a, Y = yo + x sin a + y cos a.
"World" here means the model's own CRS (Settings mf6_crs), not the project CRS.

read_grid and HeadFile are cached by (absolute path, mtime, size): a second call for an unchanged file returns the
same object; a file that changed is read again (for a text grid file also when an OPEN/CLOSE file it reads changed,
for a .grb when its text grid file changed). Within one use of the caches (new_generation(), called once per section
build) nothing used is evicted, so a section with many models never thrashes. The arrays of a cached Grid are
READ-ONLY (shared): copy before changing them (surface_array returns fresh arrays). Problems a user can fix raise
MF6Error (a ValueError) with a message fit for the panel.
"""
from __future__ import annotations

import math
import os
import re
import struct
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import cached_property
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

NO_VALUE = 1e29                 # |head| >= this is no value: dry (HDRY -1e30) or inactive (HNOFLO 1e30)
GRID_KINDS = ("dis", "disv", "disu")
LENGTH_UNITS = ("feet", "meters", "centimeters", "unknown")
GRID_FILTER = "MODFLOW 6 grid (*.grb *.disv *.dis *.disu);;All files (*)"
HEAD_FILTER = "MODFLOW 6 heads (*.hds *.hed *.bhd);;All files (*)"
_CACHE_MAX = 8


class MF6Error(ValueError):
    """A MODFLOW 6 file problem the user can fix (the message is shown in the panel as-is)."""


class NotHeadsError(MF6Error):
    """A MODFLOW binary output file whose records are not heads (e.g. a GWT concentration or GWE temperature
    file)."""


# ================================================================================================ caching
_GRID_CACHE: "OrderedDict[tuple, Grid]" = OrderedDict()
_HEAD_CACHE: "OrderedDict[tuple, HeadFile]" = OrderedDict()
_COMPANION_CACHE: "OrderedDict[tuple, str]" = OrderedDict()
_USED: Dict[int, int] = {}              # id(cached object) -> the generation it was last used in
_GENERATION = [0]


def new_generation() -> int:
    """Start a new use of the caches (one section build): entries used since are kept even past _CACHE_MAX, so a
    build that needs more files than that does not evict and re-read them in a cycle."""
    _GENERATION[0] += 1
    return _GENERATION[0]


def _stat_key(path: str) -> tuple:
    try:
        st = os.stat(path)
    except OSError:
        raise MF6Error(f"{path}: file not found.") from None
    if not os.path.isfile(path):
        raise MF6Error(f"{path} is not a file.")
    return (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)


def _cache_get(cache: OrderedDict, key: tuple):
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
        _USED[id(value)] = _GENERATION[0]
    return value


def _cache_put(cache: OrderedDict, key: tuple, value) -> None:
    for old in [k for k in cache if k[0] == key[0]]:      # an older version of the same file
        _USED.pop(id(cache.pop(old)), None)
    cache[key] = value
    _USED[id(value)] = _GENERATION[0]
    while len(cache) > _CACHE_MAX:                         # least recently used first; never one used in this
        first = next(iter(cache))                          # generation (all after it are newer still)
        if _USED.get(id(cache[first])) == _GENERATION[0]:
            break
        _USED.pop(id(cache.pop(first)), None)


def clear_cache() -> None:
    """Forget every cached grid and head file index."""
    _GRID_CACHE.clear()
    _HEAD_CACHE.clear()
    _COMPANION_CACHE.clear()
    _USED.clear()


def _readonly(a):
    if isinstance(a, np.ndarray):
        a.flags.writeable = False
    return a


# ================================================================================================ the grid
@dataclass(eq=False)
class CellVertices:
    """Ragged per-cell vertex lists: cell i uses verts[indices[offsets[i]:offsets[i + 1]]] (0-based, clockwise as
    MODFLOW lists them, ring NOT closed)."""
    offsets: np.ndarray                 # (ncpl + 1,) int64
    indices: np.ndarray                 # (offsets[-1],) int64

    def __len__(self) -> int:
        return len(self.offsets) - 1

    def __getitem__(self, i: int) -> np.ndarray:
        return self.indices[self.offsets[i]:self.offsets[i + 1]]

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def counts(self) -> np.ndarray:
        return np.diff(self.offsets)


@dataclass(eq=False)
class Grid:
    """A MODFLOW 6 grid. Arrays are read-only (the grid is cached and shared)."""
    kind: str = "disv"                  # dis | disv | disu
    nlay: int = 1
    ncpl: int = 0                       # cells per layer (DIS nrow * ncol; DISU nodes)
    nrow: int = 0                       # DIS only
    ncol: int = 0
    top: np.ndarray = None              # (ncpl,) top of layer 1
    botm: np.ndarray = None             # (nlay, ncpl) cell bottoms (DISU: (1, nodes) from BOT)
    idomain: Optional[np.ndarray] = None   # (nlay, ncpl) int; None when the file has none (an older DISU .grb)
    verts: np.ndarray = None            # (nvert, 2) model coordinates
    iverts: CellVertices = None
    xorigin: float = 0.0
    yorigin: float = 0.0
    angrot: float = 0.0                 # degrees, counter-clockwise
    length_units: str = "unknown"       # feet | meters | centimeters | unknown
    path: str = ""
    cellx: Optional[np.ndarray] = None  # (ncpl,) cell centres, model coordinates (from the file, or the cell centroid)
    celly: Optional[np.ndarray] = None
    icelltype: Optional[np.ndarray] = None   # (nlay, ncpl), from a .grb
    source: str = ""                    # "grb" | "text"
    inputs: Tuple[Tuple[str, int, int], ...] = ()   # (path, mtime_ns, size) of the OPEN/CLOSE files a text grid read

    def __post_init__(self):
        for name in ("top", "botm", "idomain", "verts", "cellx", "celly", "icelltype"):
            _readonly(getattr(self, name))
        if self.iverts is not None:
            _readonly(self.iverts.offsets)
            _readonly(self.iverts.indices)

    # ---------------------------------------------------------------------------------------------- basics
    @property
    def ncells(self) -> int:
        return self.nlay * self.ncpl

    @property
    def has_vertices(self) -> bool:
        if self.verts is None or len(self.verts) == 0 or self.iverts is None or len(self.iverts) != self.ncpl:
            return False
        counts = self.iverts.counts()
        return len(counts) > 0 and int(counts.min()) >= 3

    def summary(self) -> str:
        """e.g. "DISV: 3 layers x 27,688 cells, feet"."""
        units = self.length_units if self.length_units != "unknown" else "length units unknown"
        if self.kind == "disu":
            return f"DISU: {self.ncpl:,} nodes, {units}"
        cells = f"{self.nrow:,} rows x {self.ncol:,} columns" if self.kind == "dis" else f"{self.ncpl:,} cells"
        layers = f"{self.nlay} layer{'s' if self.nlay != 1 else ''}"
        return f"{self.kind.upper()}: {layers} x {cells}, {units}"

    def cell_vertices(self, i: int) -> np.ndarray:
        """(k, 2) model coordinates of cell i's ring (0-based cell in a layer; not closed)."""
        return self.verts[self.iverts[i]]

    def layer_tops(self) -> np.ndarray:
        """(nlay, ncpl) top of every cell: TOP for layer 1, the bottom of the cell above for the others."""
        return np.vstack([self.top[None, :], self.botm[:-1]]) if self.nlay > 1 else self.top[None, :].copy()

    def active(self) -> np.ndarray:
        """(nlay, ncpl) bool: idomain > 0 (all True without idomain)."""
        if self.idomain is None:
            return np.ones((self.nlay, self.ncpl), bool)
        return self.idomain > 0

    # ---------------------------------------------------------------------------------------------- coordinates
    def to_world(self, x, y) -> Tuple[np.ndarray, np.ndarray]:
        """Model coordinates -> the model CRS: rotate by ANGROT about the origin, then add XORIGIN, YORIGIN."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if self.angrot == 0.0:
            return x + self.xorigin, y + self.yorigin
        a = math.radians(self.angrot)
        ca, sa = math.cos(a), math.sin(a)
        return self.xorigin + x * ca - y * sa, self.yorigin + x * sa + y * ca

    def to_model(self, X, Y) -> Tuple[np.ndarray, np.ndarray]:
        """The model CRS -> model coordinates (the inverse of to_world)."""
        dx = np.asarray(X, dtype=float) - self.xorigin
        dy = np.asarray(Y, dtype=float) - self.yorigin
        if self.angrot == 0.0:
            return dx, dy
        a = math.radians(self.angrot)
        ca, sa = math.cos(a), math.sin(a)
        return dx * ca + dy * sa, -dx * sa + dy * ca

    @cached_property
    def verts_world(self) -> np.ndarray:
        """(nvert, 2) vertices in the model CRS."""
        if self.verts is None or len(self.verts) == 0:
            return _readonly(np.zeros((0, 2)))
        X, Y = self.to_world(self.verts[:, 0], self.verts[:, 1])
        return _readonly(np.column_stack([X, Y]))

    def cell_vertices_world(self, i: int) -> np.ndarray:
        return self.verts_world[self.iverts[i]]

    def cell_centers_world(self) -> np.ndarray:
        """(ncpl, 2) cell centres in the model CRS."""
        X, Y = self.to_world(self.cellx, self.celly)
        return np.column_stack([X, Y])

    def cell_bounds_world(self) -> np.ndarray:
        """(ncpl, 4) xmin, ymin, xmax, ymax of every cell in the model CRS."""
        return self._bounds_world

    @cached_property
    def _bounds_world(self) -> np.ndarray:
        if not self.has_vertices:
            raise MF6Error(f"{os.path.basename(self.path)}: the grid has no cell vertices "
                           "(a DISU without VERTICES and CELL2D), so it can't be drawn along a section.")
        vw = self.verts_world
        idx = self.iverts.indices
        starts = self.iverts.offsets[:-1]
        xs, ys = vw[idx, 0], vw[idx, 1]
        out = np.column_stack([np.minimum.reduceat(xs, starts), np.minimum.reduceat(ys, starts),
                               np.maximum.reduceat(xs, starts), np.maximum.reduceat(ys, starts)])
        return _readonly(out)

    def extent_world(self) -> Tuple[float, float, float, float]:
        b = self.cell_bounds_world()
        return float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())


def _rings(starts_ends_ia: np.ndarray, ja: np.ndarray, base: int = 1) -> CellVertices:
    """CSR vertex lists (ia of n + 1 entries, `base`-based ja) -> CellVertices, 0-based, rings not closed (a list
    whose last vertex repeats its first loses the last one: MODFLOW 6 writes closed rings to the .grb, and a CELL2D
    list may be written either way)."""
    ia = np.asarray(starts_ends_ia, dtype=np.int64) - base
    ja = np.asarray(ja, dtype=np.int64) - base
    n = len(ia) - 1
    if n <= 0:
        return CellVertices(np.zeros(1, np.int64), np.zeros(0, np.int64))
    lo, hi = int(ia[0]), int(ia[-1])
    ja = ja[lo:hi]
    ia = ia - lo
    starts, ends = ia[:-1], ia[1:]
    counts = ends - starts
    closed = np.zeros(n, bool)
    has = counts > 1
    if has.any():
        closed[has] = ja[starts[has]] == ja[ends[has] - 1]
    keep = np.ones(len(ja), bool)
    keep[(ends - 1)[closed]] = False
    offsets = np.zeros(n + 1, np.int64)
    np.cumsum(counts - closed, out=offsets[1:])
    return CellVertices(offsets, ja[keep])


def _check_rings(verts: np.ndarray, iv: CellVertices, owner: str, what: str) -> None:
    """MF6Error unless every vertex id of the rings is one of the grid's vertices (1..NVERT)."""
    idx = iv.indices
    if len(idx) == 0:
        return
    nvert = len(verts)
    lo, hi = int(idx.min()), int(idx.max())
    if lo < 0 or hi >= nvert:
        bad = (lo if lo < 0 else hi) + 1
        raise MF6Error(f"{os.path.basename(owner)}: {what} names vertex {bad} but NVERT is {nvert}.")


def _centroids(verts: np.ndarray, iv: CellVertices) -> Tuple[np.ndarray, np.ndarray]:
    """Area centroids of the cells (vertex mean for a degenerate ring)."""
    n = len(iv)
    if n == 0 or len(verts) == 0:
        return np.zeros(n), np.zeros(n)
    idx = iv.indices
    starts = iv.offsets[:-1]
    counts = iv.counts()
    nxt = np.arange(len(idx)) + 1
    last = iv.offsets[1:] - 1
    nxt[last] = starts                                   # wrap each ring
    x0, y0 = verts[idx, 0], verts[idx, 1]
    x1, y1 = verts[idx[nxt], 0], verts[idx[nxt], 1]
    # shift to each ring's first vertex for precision with world-size coordinates
    ox = np.repeat(verts[idx[starts], 0], counts)
    oy = np.repeat(verts[idx[starts], 1], counts)
    x0, x1, y0, y1 = x0 - ox, x1 - ox, y0 - oy, y1 - oy
    f = x0 * y1 - x1 * y0
    a = np.add.reduceat(f, starts) / 2.0
    cx = np.add.reduceat((x0 + x1) * f, starts)
    cy = np.add.reduceat((y0 + y1) * f, starts)
    mx = np.add.reduceat(x0, starts) / counts
    my = np.add.reduceat(y0, starts) / counts
    ok = np.abs(a) > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        gx = np.where(ok, cx / (6.0 * np.where(ok, a, 1.0)), mx)
        gy = np.where(ok, cy / (6.0 * np.where(ok, a, 1.0)), my)
    return gx + verts[idx[starts], 0], gy + verts[idx[starts], 1]


def _dis_geometry(delr: np.ndarray, delc: np.ndarray):
    """Vertices, rings and centres of a DIS grid in model coordinates: the origin is the lower-left corner, x along
    the rows (DELR), row 1 at the top (north), rings clockwise from the upper-left corner."""
    nrow, ncol = len(delc), len(delr)
    xe = np.concatenate([[0.0], np.cumsum(delr)])
    ye = float(np.sum(delc)) - np.concatenate([[0.0], np.cumsum(delc)])
    X, Y = np.meshgrid(xe, ye)
    verts = np.column_stack([X.ravel(), Y.ravel()])
    r, c = np.meshgrid(np.arange(nrow), np.arange(ncol), indexing="ij")
    r, c = r.ravel(), c.ravel()
    n1 = ncol + 1
    ul = r * n1 + c
    indices = np.column_stack([ul, ul + 1, ul + n1 + 1, ul + n1]).ravel().astype(np.int64)
    offsets = np.arange(0, 4 * nrow * ncol + 1, 4, dtype=np.int64)
    cellx = ((xe[:-1] + xe[1:]) / 2.0)[c]
    celly = ((ye[:-1] + ye[1:]) / 2.0)[r]
    return verts, CellVertices(offsets, indices), cellx, celly


def _units(value: str) -> str:
    v = (value or "").strip().strip("'\"").lower()
    return {"feet": "feet", "foot": "feet", "ft": "feet", "meters": "meters", "meter": "meters", "m": "meters",
            "metres": "meters", "centimeters": "centimeters", "cm": "centimeters"}.get(v, "unknown")


# ================================================================================================ .grb files
_GRB_TYPES = {"INTEGER": "<i4", "DOUBLE": "<f8", "SINGLE": "<f4", "REAL": "<f4", "CHARACTER": "S1"}


def _parse_grb(path: str) -> Tuple[str, Dict[str, object], dict]:
    """(kind, {name: array or scalar}, header) of a binary grid file, every definition read by name."""
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"GRID"):
        raise MF6Error(f"{os.path.basename(path)} is not a MODFLOW 6 binary grid file.")
    header = {}
    pos = 0
    for _ in range(4):
        line = data[pos:pos + 50].decode("ascii", "replace").split()
        pos += 50
        if len(line) >= 2:
            header[line[0].upper()] = line[1]
    try:
        kind = header["GRID"].lower()
        ntxt, lentxt = int(header["NTXT"]), int(header["LENTXT"])
    except (KeyError, ValueError):
        raise MF6Error(f"{os.path.basename(path)}: unreadable binary grid file header.") from None
    defs = []
    for _ in range(ntxt):
        tok = data[pos:pos + lentxt].decode("ascii", "replace").split()
        pos += lentxt
        if len(tok) < 4 or tok[2].upper() != "NDIM":
            raise MF6Error(f"{os.path.basename(path)}: unreadable definition {' '.join(tok)!r}.")
        ndim = int(tok[3])
        dims = [int(t) for t in tok[4:4 + ndim]]
        defs.append((tok[0].upper(), tok[1].upper(), dims))
    values: Dict[str, object] = {}
    for name, typ, dims in defs:
        dt = _GRB_TYPES.get(typ)
        if dt is None:
            raise MF6Error(f"{os.path.basename(path)}: unknown data type {typ} for {name}.")
        count = int(np.prod(dims)) if dims else 1
        nbytes = count * np.dtype(dt).itemsize
        if pos + nbytes > len(data):
            raise MF6Error(f"{os.path.basename(path)} is truncated (at {name}).")
        if typ == "CHARACTER":
            values[name] = data[pos:pos + nbytes].decode("ascii", "replace").strip()
        else:
            arr = np.frombuffer(data, dt, count, pos)
            if not dims:
                values[name] = arr[0].item()
            else:
                values[name] = np.array(arr.reshape(tuple(reversed(dims))))   # dims are Fortran order
        pos += nbytes
    return kind, values, header


def _grid_from_grb(path: str, length_units: str) -> Grid:
    kind, v, _ = _parse_grb(path)
    name = os.path.basename(path)

    def need(*keys):
        missing = [k for k in keys if k not in v]
        if missing:
            raise MF6Error(f"{name}: {kind.upper()} grid file without {', '.join(missing)}.")

    common = dict(xorigin=float(v.get("XORIGIN", 0.0)), yorigin=float(v.get("YORIGIN", 0.0)),
                  angrot=float(v.get("ANGROT", 0.0)), length_units=length_units, path=path, source="grb")
    if kind == "disv":
        need("NLAY", "NCPL", "TOP", "BOTM", "VERTICES", "IAVERT", "JAVERT")
        nlay, ncpl = int(v["NLAY"]), int(v["NCPL"])
        verts = np.asarray(v["VERTICES"], float).reshape(-1, 2)
        iv = _rings(v["IAVERT"], v["JAVERT"])
        _check_rings(verts, iv, path, "JAVERT")
        shape = (nlay, ncpl)
        cx, cy = v.get("CELLX"), v.get("CELLY")
        if cx is None or cy is None:
            cx, cy = _centroids(verts, iv)
        return Grid(kind="disv", nlay=nlay, ncpl=ncpl, top=np.asarray(v["TOP"], float).ravel()[:ncpl],
                    botm=np.asarray(v["BOTM"], float).reshape(shape),
                    idomain=_maybe(v, "IDOMAIN", shape), verts=verts, iverts=iv, cellx=np.asarray(cx, float),
                    celly=np.asarray(cy, float), icelltype=_maybe(v, "ICELLTYPE", shape), **common)
    if kind == "disu":
        need("NODES", "TOP", "BOT")
        nodes = int(v["NODES"])
        if "VERTICES" in v and "IAVERT" in v and "JAVERT" in v:
            verts = np.asarray(v["VERTICES"], float).reshape(-1, 2)
            iv = _rings(v["IAVERT"], v["JAVERT"])
            _check_rings(verts, iv, path, "JAVERT")
        else:
            verts, iv = np.zeros((0, 2)), CellVertices(np.zeros(nodes + 1, np.int64), np.zeros(0, np.int64))
        cx, cy = v.get("CELLX"), v.get("CELLY")
        if cx is None or cy is None:
            cx, cy = _centroids(verts, iv) if len(verts) else (np.full(nodes, np.nan), np.full(nodes, np.nan))
        return Grid(kind="disu", nlay=1, ncpl=nodes, top=np.asarray(v["TOP"], float).ravel(),
                    botm=np.asarray(v["BOT"], float).reshape(1, nodes), idomain=_maybe(v, "IDOMAIN", (1, nodes)),
                    verts=verts, iverts=iv, cellx=np.asarray(cx, float), celly=np.asarray(cy, float),
                    icelltype=_maybe(v, "ICELLTYPE", (1, nodes)), **common)
    if kind == "dis":
        need("NLAY", "NROW", "NCOL", "DELR", "DELC", "TOP", "BOTM")
        nlay, nrow, ncol = int(v["NLAY"]), int(v["NROW"]), int(v["NCOL"])
        verts, iv, cx, cy = _dis_geometry(np.asarray(v["DELR"], float), np.asarray(v["DELC"], float))
        shape = (nlay, nrow * ncol)
        return Grid(kind="dis", nlay=nlay, ncpl=nrow * ncol, nrow=nrow, ncol=ncol,
                    top=np.asarray(v["TOP"], float).ravel()[:nrow * ncol],
                    botm=np.asarray(v["BOTM"], float).reshape(shape), idomain=_maybe(v, "IDOMAIN", shape),
                    verts=verts, iverts=iv, cellx=cx, celly=cy, icelltype=_maybe(v, "ICELLTYPE", shape), **common)
    raise MF6Error(f"{name}: unknown grid type {kind.upper()} (expected DIS, DISV or DISU).")


def _maybe(v: dict, key: str, shape: tuple) -> Optional[np.ndarray]:
    a = v.get(key)
    if a is None:
        return None
    return np.asarray(a, np.int32).reshape(shape)


# ================================================================================================ text files
_BLOCK_RE = re.compile(r"^[ \t]*(BEGIN|END)[ \t]+([A-Za-z0-9_]+)[^\n]*$", re.I | re.M)
_TOKEN_RE = re.compile(r"""'([^']*)'|"([^"]*)"|(\S+)""")
_COMMENT_RE = re.compile(r"[#!].*")
_FORTRAN_D = re.compile(r"(?<=[0-9.])[dD](?=[+-]?[0-9])")
_REPEAT_RE = re.compile(r"(\d+)\*(.*)")


def _list_words(text: str, limit: Optional[int] = None) -> List[str]:
    """The values of list-directed array data, as MODFLOW 6 reads INTERNAL and OPEN/CLOSE arrays (Fortran
    list-directed input): blanks or commas separate values, and r*value stands for r copies of value (at most
    `limit` copies are made). A bare r* (null values) is an MF6Error."""
    if "," in text:
        text = text.replace(",", " ")
    words = text.split()
    if "*" not in text:
        return words
    out: List[str] = []
    for w in words:
        m = _REPEAT_RE.fullmatch(w) if "*" in w else None
        if m is None:
            out.append(w)
            continue
        if not m.group(2):
            raise MF6Error(f"{w!r} is a repeat count without a value (null values are not supported)")
        r = int(m.group(1))
        out.extend([m.group(2)] * (min(r, limit) if limit is not None else r))
    return out


def _blocks(text: str) -> Dict[str, List[str]]:
    """{block name (lower): [content of each occurrence]} of an MF6 input file."""
    out: Dict[str, List[str]] = {}
    current, start = None, 0
    for m in _BLOCK_RE.finditer(text):
        word, name = m.group(1).upper(), m.group(2).lower()
        if word == "BEGIN":
            current, start = name, m.end()
        elif current is not None and name == current:
            out.setdefault(name, []).append(text[start:m.start()])
            current = None
    return out


def _clean(content: str) -> str:
    if "#" in content or "!" in content:
        content = _COMMENT_RE.sub("", content)
    return content


def _tokens(line: str) -> List[str]:
    """Words of one line, quotes removed, a # or ! comment dropped."""
    out = []
    for m in _TOKEN_RE.finditer(line):
        word = m.group(1) if m.group(1) is not None else m.group(2) if m.group(2) is not None else m.group(3)
        if m.group(3) is not None and word[0] in "#!":
            break
        out.append(word)
    return out


def _floats(words) -> np.ndarray:
    try:
        return np.array(words, dtype=float)
    except ValueError:
        fixed = [_FORTRAN_D.sub("E", w) for w in words]
        try:
            return np.array(fixed, dtype=float)
        except ValueError:
            bad = next((w for w in fixed if not _is_float(w)), "?")
            raise MF6Error(f"not a number: {bad!r}") from None


def _is_float(w: str) -> bool:
    try:
        float(w)
        return True
    except ValueError:
        return False


def _key_values(content: str) -> Dict[str, List[str]]:
    """{KEY: [rest of the words]} for each line of an OPTIONS or DIMENSIONS block."""
    out: Dict[str, List[str]] = {}
    for line in content.splitlines():
        tok = _tokens(line)
        if tok:
            out[tok[0].upper()] = tok[1:]
    return out


def read_options(path: str) -> Dict[str, List[str]]:
    """The OPTIONS block of a MODFLOW 6 input file ({KEY: [words]}), read without the rest of the file."""
    lines, block = [], ""
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            tok = line.split()
            if not tok or tok[0][0] in "#!":
                continue
            head = tok[0].upper()
            if not block:
                if head == "BEGIN" and len(tok) > 1:
                    block = tok[1].upper()
                continue
            if head == "END":
                if block == "OPTIONS":
                    break
                block = ""              # another block: skip it (OPTIONS normally comes first)
            elif block == "OPTIONS":
                lines.append(line)
    return _key_values("".join(lines))


def _find_sim_dir(folder: str, levels: int = 3) -> str:
    """The nearest folder at or above `folder` holding mfsim.nam (where MODFLOW 6 ran), else `folder`."""
    d = folder
    for _ in range(levels + 1):
        if os.path.isfile(os.path.join(d, "mfsim.nam")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return folder


def _resolve_input(fname: str, base: str, owner: str, inputs: Optional[List[str]] = None) -> str:
    """An OPEN/CLOSE or package path: relative to the simulation folder (where mfsim.nam is), else to the folder
    of the file naming it. The path found is appended to `inputs` (the files a grid depends on)."""
    fname = fname.replace("\\", os.sep).replace("/", os.sep)
    if os.path.isabs(fname):
        cands = [fname]
    else:
        cands = [os.path.join(_find_sim_dir(base), fname), os.path.join(base, fname)]
    for c in cands:
        if os.path.isfile(c):
            found = os.path.normpath(c)
            if inputs is not None:
                inputs.append(found)
            return found
    raise MF6Error(f"{os.path.basename(owner)}: file {fname} not found (looked in {_find_sim_dir(base)}).")


def _read_binary_array(path: str, n: int, integer: bool) -> np.ndarray:
    """n values of a MODFLOW binary array file, read as MODFLOW 6 reads it: one header record (KSTP KPER PERTIM
    TOTIM TEXT NCOL NROW ILAY; its dimensions are not used) and then the n values the array needs (float64, or
    int32 for an integer array)."""
    with open(path, "rb") as fh:
        data = fh.read()
    item = 4 if integer else 8
    dt = "<i4" if integer else "<f8"
    hsize = 52
    if len(data) >= 44 and not _is_text(data[24:40]) and _is_text(data[16:32]):
        hsize = 44                                         # single-precision header
    if len(data) < hsize + n * item:
        have = max(0, (len(data) - hsize) // item)
        raise MF6Error(f"{os.path.basename(path)}: {have} values after its header, {n} expected.")
    return np.frombuffer(data, dt, n, hsize).astype(np.int32 if integer else float)


def _read_text_array_file(path: str, n: int) -> np.ndarray:
    with open(path, "r", errors="replace") as fh:
        try:
            words = _list_words(_clean(fh.read()), n)
        except MF6Error as e:
            raise MF6Error(f"{os.path.basename(path)}: {e}") from None
    if len(words) < n:
        raise MF6Error(f"{os.path.basename(path)}: {len(words)} values, {n} expected.")
    try:
        return _floats(words[:n])
    except MF6Error as e:
        raise MF6Error(f"{os.path.basename(path)}: {e}") from None


def _read_array(lines: List[str], i: int, n: int, integer: bool, base: str, owner: str, label: str,
                inputs: Optional[List[str]] = None):
    """One array control (CONSTANT / INTERNAL / OPEN/CLOSE) at lines[i] and its data -> (next line, values). The
    files read through OPEN/CLOSE are appended to `inputs`."""
    while i < len(lines) and not _tokens(lines[i]):
        i += 1
    if i >= len(lines):
        raise MF6Error(f"{os.path.basename(owner)}: no values for {label}.")
    tok = _tokens(lines[i])
    key = tok[0].upper()
    opts = [t.upper() for t in tok]
    factor = 1.0
    if "FACTOR" in opts[1:]:
        k = opts.index("FACTOR", 1)
        factor = float(_FORTRAN_D.sub("E", tok[k + 1]))
    if key == "CONSTANT":
        vals = np.full(n, float(_FORTRAN_D.sub("E", tok[1].rstrip(","))))
        i += 1
    elif key == "INTERNAL":
        i += 1
        words: List[str] = []
        try:
            while len(words) < n:
                if i >= len(lines):
                    raise MF6Error(f"{label} has {len(words)} values, {n} expected.")
                line = lines[i]
                if "#" in line or "!" in line:
                    line = _COMMENT_RE.sub("", line)
                if "," in line or "*" in line:          # list-directed: commas, r*value repeats
                    words.extend(_list_words(line, n - len(words)))
                else:
                    words.extend(line.split())
                i += 1
            vals = _floats(words[:n]) * factor
        except MF6Error as e:
            text = str(e)
            raise MF6Error(f"{os.path.basename(owner)}: "
                           + (text if text.startswith(label) else f"{label}: {text}")) from None
    elif key == "OPEN/CLOSE":
        fpath = _resolve_input(tok[1], base, owner, inputs)
        if "(BINARY)" in opts:
            vals = _read_binary_array(fpath, n, integer) * (int(factor) if integer else factor)
        else:
            vals = _read_text_array_file(fpath, n) * factor
        i += 1
    else:
        raise MF6Error(f"{os.path.basename(owner)}: {label}: expected CONSTANT, INTERNAL or OPEN/CLOSE, "
                       f"found {lines[i].strip()!r}.")
    if integer:
        vals = np.rint(vals).astype(np.int32)
    return i, np.asarray(vals)


def _read_griddata(content: str, sizes: Dict[str, Tuple[int, int, bool]], nlay: int, base: str, owner: str,
                   inputs: Optional[List[str]] = None):
    """Arrays of a GRIDDATA block. sizes: {NAME: (values per layer, layers, integer)}; unknown names are read with
    the size of the first entry (for skipping). OPEN/CLOSE files read are appended to `inputs`."""
    lines = content.splitlines()
    out: Dict[str, np.ndarray] = {}
    i = 0
    default = next(iter(sizes.values()))
    while i < len(lines):
        tok = _tokens(lines[i])
        if not tok:
            i += 1
            continue
        name = tok[0].upper()
        layered = any(t.upper() == "LAYERED" for t in tok[1:])
        per, layers, integer = sizes.get(name, default)
        rest = [t for t in tok[1:] if t.upper() != "LAYERED"]
        if rest and rest[0].upper() in ("CONSTANT", "INTERNAL", "OPEN/CLOSE"):
            lines[i] = " ".join(rest)                   # the control on the same line as the name
        else:
            i += 1
        if layered and layers > 1:
            parts = []
            for k in range(layers):
                i, a = _read_array(lines, i, per, integer, base, owner, f"{name} layer {k + 1}", inputs)
                parts.append(a)
            out[name] = np.concatenate(parts)
        else:
            i, out[name] = _read_array(lines, i, per * layers, integer, base, owner, name, inputs)
    return out


def _block_content(blocks: Dict[str, List[str]], name: str, base: str, owner: str,
                   inputs: Optional[List[str]] = None) -> str:
    """The rows of a list block (VERTICES, CELL2D): its own lines, or the text of the file named when the block's
    first line is OPEN/CLOSE fname (list data stored in an external file, as flopy writes it)."""
    content = blocks.get(name, [""])[0]
    for line in content.splitlines():
        tok = _tokens(line)
        if not tok:
            continue
        if tok[0].upper() != "OPEN/CLOSE":
            break
        what = f"{os.path.basename(owner)}: {name.upper()}"
        if len(tok) < 2:
            raise MF6Error(f"{what}: OPEN/CLOSE without a file name.")
        if any(t.upper() == "(BINARY)" for t in tok[2:]):
            raise MF6Error(f"{what}: binary list data (OPEN/CLOSE … (BINARY)) is not supported; write it as text.")
        with open(_resolve_input(tok[1], base, owner, inputs), "r", errors="replace") as fh:
            return fh.read()
    return content


def _input_stats(paths: Sequence[str]) -> Tuple[Tuple[str, int, int], ...]:
    out, seen = [], set()
    for p in paths:
        key = os.path.normcase(os.path.abspath(p))
        if key in seen:
            continue
        seen.add(key)
        st = os.stat(p)
        out.append((p, st.st_mtime_ns, st.st_size))
    return tuple(out)


def _inputs_current(grid: "Grid") -> bool:
    """Every OPEN/CLOSE file a cached text grid read is still there, unchanged."""
    for p, mtime, size in grid.inputs:
        try:
            st = os.stat(p)
        except OSError:
            return False
        if (st.st_mtime_ns, st.st_size) != (mtime, size):
            return False
    return True


def _read_vertices(content: str, nvert: int, owner: str) -> np.ndarray:
    words = _clean(content).split()
    if nvert == 0 and not words:
        return np.zeros((0, 2))
    a = _floats(words)
    if a.size % 3 or a.size // 3 != nvert:
        raise MF6Error(f"{os.path.basename(owner)}: VERTICES has {a.size / 3:g} rows of iv x y, NVERT is {nvert}.")
    a = a.reshape(-1, 3)
    iv = a[:, 0].astype(np.int64)
    if not np.array_equal(iv, np.arange(1, nvert + 1)):
        order = np.argsort(iv, kind="stable")
        a = a[order]
    return np.ascontiguousarray(a[:, 1:3])


def _read_cell2d(content: str, ncells: int, owner: str):
    """CELL2D rows "icell2d xc yc ncvert iv1 ... ivn" -> (xc, yc, CellVertices)."""
    rows = [ln.split() for ln in _clean(content).splitlines()]
    rows = [r for r in rows if r]
    if len(rows) != ncells:
        raise MF6Error(f"{os.path.basename(owner)}: CELL2D has {len(rows)} rows, {ncells} expected.")
    counts = np.fromiter((len(r) for r in rows), dtype=np.int64, count=len(rows))
    flat = _floats([w for r in rows for w in r])
    starts = np.zeros(len(rows), np.int64)
    np.cumsum(counts[:-1], out=starts[1:])
    icell = flat[starts].astype(np.int64)
    xc, yc = flat[starts + 1], flat[starts + 2]
    ncvert = flat[starts + 3].astype(np.int64)
    if np.any(counts < 4 + ncvert):
        bad = int(np.nonzero(counts < 4 + ncvert)[0][0])
        raise MF6Error(f"{os.path.basename(owner)}: CELL2D row {bad + 1} lists fewer vertices than its ncvert.")
    seg = np.zeros(len(rows) + 1, np.int64)
    np.cumsum(ncvert, out=seg[1:])
    pos = np.repeat(starts + 4, ncvert) + (np.arange(seg[-1]) - np.repeat(seg[:-1], ncvert))
    ja = flat[pos].astype(np.int64)
    if not np.array_equal(icell, np.arange(1, ncells + 1)):
        order = np.argsort(icell, kind="stable")
        parts = [ja[seg[k]:seg[k + 1]] for k in order]
        ja = np.concatenate(parts) if parts else ja
        ncvert = ncvert[order]
        xc, yc = xc[order], yc[order]
        seg = np.zeros(len(rows) + 1, np.int64)
        np.cumsum(ncvert, out=seg[1:])
    return xc, yc, _rings(seg + 1, ja)


def _grid_from_text(path: str) -> Grid:
    with open(path, "r", errors="replace") as fh:
        text = fh.read()
    name = os.path.basename(path)
    blocks = _blocks(text)
    opts = _key_values(blocks.get("options", [""])[0])
    dims = {k: int(float(v[0])) for k, v in _key_values(blocks.get("dimensions", [""])[0]).items() if v}
    if "NODES" in dims:
        kind = "disu"
    elif "NCPL" in dims:
        kind = "disv"
    elif "NROW" in dims or "NCOL" in dims:
        kind = "dis"
    else:
        raise MF6Error(f"{name} is not a MODFLOW 6 grid file (DIS, DISV or DISU): no DIMENSIONS block.")
    base = os.path.dirname(path)

    def opt_float(key):
        v = opts.get(key)
        return float(_FORTRAN_D.sub("E", v[0])) if v else 0.0

    common = dict(xorigin=opt_float("XORIGIN"), yorigin=opt_float("YORIGIN"), angrot=opt_float("ANGROT"),
                  length_units=_units(opts.get("LENGTH_UNITS", [""])[0] if opts.get("LENGTH_UNITS") else ""),
                  path=path, source="text")
    griddata = blocks.get("griddata", [""])[0]
    inputs: List[str] = []                      # OPEN/CLOSE files read (a change to any of them re-reads the grid)
    try:
        if kind == "disv":
            nlay, ncpl, nvert = dims.get("NLAY", 1), dims["NCPL"], dims.get("NVERT", 0)
            arrays = _read_griddata(griddata, {"TOP": (ncpl, 1, False), "BOTM": (ncpl, nlay, False),
                                               "IDOMAIN": (ncpl, nlay, True)}, nlay, base, path, inputs)
            verts = _read_vertices(_block_content(blocks, "vertices", base, path, inputs), nvert, path)
            xc, yc, iv = _read_cell2d(_block_content(blocks, "cell2d", base, path, inputs), ncpl, path)
            _check_rings(verts, iv, path, "CELL2D")
            shape = (nlay, ncpl)
            idom = arrays.get("IDOMAIN")
            grid = Grid(kind="disv", nlay=nlay, ncpl=ncpl, top=_need(arrays, "TOP", name),
                        botm=_need(arrays, "BOTM", name).reshape(shape),
                        idomain=(idom.reshape(shape) if idom is not None else np.ones(shape, np.int32)),
                        verts=verts, iverts=iv, cellx=xc, celly=yc, **common)
        elif kind == "dis":
            nlay, nrow, ncol = dims.get("NLAY", 1), dims.get("NROW", 1), dims.get("NCOL", 1)
            ncpl = nrow * ncol
            arrays = _read_griddata(griddata, {"DELR": (ncol, 1, False), "DELC": (nrow, 1, False),
                                               "TOP": (ncpl, 1, False), "BOTM": (ncpl, nlay, False),
                                               "IDOMAIN": (ncpl, nlay, True)}, nlay, base, path, inputs)
            verts, iv, cx, cy = _dis_geometry(_need(arrays, "DELR", name), _need(arrays, "DELC", name))
            shape = (nlay, ncpl)
            idom = arrays.get("IDOMAIN")
            grid = Grid(kind="dis", nlay=nlay, ncpl=ncpl, nrow=nrow, ncol=ncol, top=_need(arrays, "TOP", name),
                        botm=_need(arrays, "BOTM", name).reshape(shape),
                        idomain=(idom.reshape(shape) if idom is not None else np.ones(shape, np.int32)),
                        verts=verts, iverts=iv, cellx=cx, celly=cy, **common)
        else:
            nodes, nvert = dims["NODES"], dims.get("NVERT", 0)
            arrays = _read_griddata(griddata, {"TOP": (nodes, 1, False), "BOT": (nodes, 1, False),
                                               "AREA": (nodes, 1, False), "IDOMAIN": (nodes, 1, True)}, 1, base,
                                    path, inputs)
            if nvert and "cell2d" in blocks:
                verts = _read_vertices(_block_content(blocks, "vertices", base, path, inputs), nvert, path)
                xc, yc, iv = _read_cell2d(_block_content(blocks, "cell2d", base, path, inputs), nodes, path)
                _check_rings(verts, iv, path, "CELL2D")
            else:
                verts, iv = np.zeros((0, 2)), CellVertices(np.zeros(nodes + 1, np.int64), np.zeros(0, np.int64))
                xc = yc = np.full(nodes, np.nan)
            idom = arrays.get("IDOMAIN")
            grid = Grid(kind="disu", nlay=1, ncpl=nodes, top=_need(arrays, "TOP", name),
                        botm=_need(arrays, "BOT", name).reshape(1, nodes),
                        idomain=(idom.reshape(1, nodes) if idom is not None else np.ones((1, nodes), np.int32)),
                        verts=verts, iverts=iv, cellx=xc, celly=yc, **common)
    except KeyError as e:
        raise MF6Error(f"{name}: {e.args[0]} missing from DIMENSIONS.") from None
    grid.inputs = _input_stats(inputs)
    return grid


def _need(arrays: dict, key: str, name: str) -> np.ndarray:
    a = arrays.get(key)
    if a is None:
        raise MF6Error(f"{name}: GRIDDATA has no {key}.")
    return np.asarray(a, float)


def _text_companion(grb_path: str) -> str:
    """The text grid file a .grb was written from: the same name without .grb, else the DIS6 / DISV6 / DISU6 file of
    a model in the simulation's name files whose binary grid file (GRB6 FILEOUT) is this .grb ("" if none). The
    name-file search is remembered per version of the .grb."""
    if grb_path.lower().endswith(".grb"):
        cand = grb_path[:-4]
        if os.path.isfile(cand):
            return cand
    try:
        st = os.stat(grb_path)
    except OSError:
        return ""
    key = (os.path.normcase(os.path.abspath(grb_path)), st.st_mtime_ns, st.st_size)
    hit = _COMPANION_CACHE.get(key)
    if hit is not None and (not hit or os.path.isfile(hit)):
        return hit
    found = ""
    folder = os.path.dirname(os.path.abspath(grb_path))
    try:
        models = _models_in(folder)
    except (OSError, MF6Error):
        models = []
    for nam, sim_dir, _name in models:
        try:
            for ftype, fname in _model_packages(nam):
                if ftype in ("DIS6", "DISV6", "DISU6"):
                    cand = os.path.normpath(os.path.join(sim_dir, fname.replace("\\", os.sep)))
                    grb = _grb_for(cand, sim_dir) if os.path.isfile(cand) else ""
                    if grb and _same(grb, grb_path):
                        found = cand
                        break
        except (OSError, MF6Error):
            continue
        if found:
            break
    for old in [k for k in _COMPANION_CACHE if k[0] == key[0]]:
        del _COMPANION_CACHE[old]
    _COMPANION_CACHE[key] = found
    while len(_COMPANION_CACHE) > 4 * _CACHE_MAX:
        _COMPANION_CACHE.popitem(last=False)
    return found


def _is_grb(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(5) == b"GRID "
    except OSError:
        return False


def read_grid(path: str) -> Grid:
    """A MODFLOW 6 grid from a binary grid file (.grb, any kind) or a text grid file (.dis / .disv / .disu).

    For a .grb, LENGTH_UNITS come from the text grid file it was written from (the same name without .grb, or the
    grid package whose GRB6 FILEOUT names it), else "unknown". Cached by (path, mtime, size) of the file (and of
    that text file for a .grb; a text grid is read again when one of its OPEN/CLOSE files changed)."""
    path = os.path.abspath(path)
    key = _stat_key(path)
    grb = _is_grb(path)
    companion = _text_companion(path) if grb else ""
    if companion:
        try:
            st = os.stat(companion)
            key = key + (os.path.normcase(companion), st.st_mtime_ns, st.st_size)
        except OSError:
            pass
    cached = _cache_get(_GRID_CACHE, key)
    if cached is not None and _inputs_current(cached):
        return cached
    try:
        if grb:
            units = "unknown"
            if companion:
                lu = read_options(companion).get("LENGTH_UNITS")
                units = _units(lu[0]) if lu else "unknown"
            grid = _grid_from_grb(path, units)
        else:
            grid = _grid_from_text(path)
    except MF6Error:
        raise
    except (OSError, ValueError, IndexError, struct.error) as e:
        raise MF6Error(f"{os.path.basename(path)}: can't read the grid ({e}).") from None
    _cache_put(_GRID_CACHE, key, grid)
    return grid


# ================================================================================================ head files
@dataclass(frozen=True)
class HeadRecord:
    kstp: int
    kper: int
    pertim: float
    totim: float
    text: str
    ncol: int
    nrow: int
    ilay: int
    offset: int                         # byte offset of the values

    @property
    def size(self) -> int:
        return self.ncol * self.nrow


def _is_text(b: bytes) -> bool:
    return len(b) > 0 and all(32 <= c < 127 for c in b) and any(65 <= (c & 0xDF) <= 90 for c in b)


def _ranges(values: Sequence[int]) -> str:
    """[1, 2, 3, 5] -> "1-3, 5"."""
    vals = sorted(set(int(v) for v in values))
    out, i = [], 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[j] + 1:
            j += 1
        out.append(str(vals[i]) if i == j else f"{vals[i]}-{vals[j]}")
        i = j + 1
    return ", ".join(out)


class HeadFile:
    """A binary head file (.hds) indexed without reading its data. Cached: HeadFile(path) returns the same object
    while the file is unchanged. The file is opened only while indexing or reading (never held open, so MODFLOW
    can write it again)."""

    def __new__(cls, path: str):
        path = os.path.abspath(path)
        key = _stat_key(path)
        cached = _cache_get(_HEAD_CACHE, key)
        if cached is not None:
            return cached
        self = super().__new__(cls)
        self._index(path, key[2])
        _cache_put(_HEAD_CACHE, key, self)
        return self

    def __init__(self, path: str):
        pass                            # everything happens in __new__ (cached instances are not re-indexed)

    def __repr__(self) -> str:
        return f"HeadFile({self.path!r}: {len(self.records)} records)"

    # ---------------------------------------------------------------------------------------------- indexing
    def _index(self, path: str, size: int) -> None:
        self.path = path
        self.name = os.path.basename(path)
        self.records: List[HeadRecord] = []
        self.truncated = False
        others: List[str] = []                  # texts of records that are not heads
        try:
            with open(path, "rb") as fh:
                first = fh.read(52)
                if len(first) >= 52 and _is_text(first[24:40]):
                    self.precision, fmt, item = "double", "<iidd16siii", 8
                elif len(first) >= 44 and _is_text(first[16:32]):
                    self.precision, fmt, item = "single", "<iiff16siii", 4
                else:
                    raise MF6Error(f"{self.name} is not a MODFLOW head file (or it is empty).")
                hsize = struct.calcsize(fmt)
                pos = 0
                while pos + hsize <= size:
                    fh.seek(pos)
                    raw = fh.read(hsize)
                    if len(raw) < hsize:            # shorter than when it was looked at: a model run started again
                        self.truncated = True
                        break
                    kstp, kper, pertim, totim, text, ncol, nrow, ilay = struct.unpack(fmt, raw)
                    n = ncol * nrow
                    if n <= 0 or ncol < 0 or nrow < 0 or pos + hsize + n * item > size:
                        self.truncated = True       # a model still running, or not a head record
                        break
                    text = text.decode("ascii", "replace").strip()
                    if text.upper() == "HEAD":
                        self.records.append(HeadRecord(kstp, kper, float(pertim), float(totim), text, ncol, nrow,
                                                       ilay, pos + hsize))
                    elif text not in others:
                        others.append(text)
                    pos += hsize + n * item
                if pos < size and not self.truncated:
                    self.truncated = True
        except OSError as e:
            raise MF6Error(f"{self.name}: can't read ({e.strerror or e}).") from None
        except struct.error as e:
            raise MF6Error(f"{self.name}: can't read ({e}).") from None
        if not self.records:
            if others:
                raise NotHeadsError(f"{self.name} holds {others[0]} records, not heads.")
            raise MF6Error(f"{self.name} holds no head records.")
        self._dtype = np.dtype("<f8" if item == 8 else "<f4")
        self._by_key: Dict[Tuple[int, int, int], HeadRecord] = {}
        for r in self.records:
            self._by_key.setdefault((r.kper, r.kstp, r.ilay), r)
        self._steps: Dict[int, List[int]] = {}
        self._times: List[Tuple[int, int, float]] = []
        seen = set()
        for r in self.records:
            if (r.kper, r.kstp) not in seen:
                seen.add((r.kper, r.kstp))
                self._times.append((r.kper, r.kstp, r.totim))
                self._steps.setdefault(r.kper, []).append(r.kstp)
        for steps in self._steps.values():
            steps.sort()
        # "last": the newest time at which every layer is saved (MODFLOW 6 saves every layer at each saved time, so
        # a time with fewer is still being written)
        layers = {r.ilay for r in self.records}
        newest = (self.records[-1].kper, self.records[-1].kstp)
        self._last = newest
        for p, s, _t in reversed(self._times):
            if all((p, s, k) in self._by_key for k in layers):
                self._last = (p, s)
                break
        self.incomplete = self._last != newest

    # ---------------------------------------------------------------------------------------------- what's in it
    @property
    def ncpl_per_record(self) -> int:
        """Values per record: cells per layer (DIS nrow * ncol, DISV ncpl, DISU nodes)."""
        return self.records[0].size

    @property
    def layers(self) -> List[int]:
        return sorted({r.ilay for r in self.records})

    @property
    def nlay(self) -> int:
        return max(self.layers)

    @property
    def partial(self) -> bool:
        """The file is still being written (a model running): its last record is cut short, or its newest time
        does not hold every layer yet ("last" then means the newest complete time)."""
        return self.truncated or self.incomplete

    def layers_at(self, kper: int, kstp: int) -> List[int]:
        """The layers saved at (kper, kstp)."""
        return sorted(k for (p, s, k) in self._by_key if p == int(kper) and s == int(kstp))

    def times(self) -> List[Tuple[int, int, float]]:
        """(kper, kstp, totim) of every saved time, in file order."""
        return list(self._times)

    def periods(self) -> List[int]:
        return sorted(self._steps)

    def steps(self, kper: int) -> List[int]:
        """The saved time steps of a stress period (sorted; [] if none)."""
        return list(self._steps.get(int(kper), []))

    def last_step(self, kper: int) -> int:
        steps = self._steps.get(int(kper))
        if not steps:
            raise MF6Error(f"Stress period {kper} is not in {self.name} (it holds periods "
                           f"{_ranges(self.periods())}).")
        return steps[-1]

    def totim(self, kper: int, kstp: int) -> float:
        """The simulation time of a saved (kper, kstp)."""
        for p, s, t in self._times:
            if p == kper and s == kstp:
                return t
        raise MF6Error(f"Stress period {kper}, time step {kstp} is not in {self.name}.")

    def resolve(self, time="last") -> Tuple[int, int]:
        """A time setting -> (kper, kstp) of saved records. "last" (or "" / None): the newest time in the file at
        which every layer is saved (the last record, unless the model is still writing the file); "kper,kstp";
        "kper" or "kper,0": the last saved step of that stress period. Also takes (kper, kstp) or an int period.
        MF6Error when the file does not hold it."""
        if time is None or (isinstance(time, (tuple, list)) and not time):
            time = "last"
        if isinstance(time, (tuple, list)):
            kper, kstp = int(time[0]), int(time[1]) if len(time) > 1 else 0
        elif isinstance(time, (int, np.integer)) and not isinstance(time, bool):
            kper, kstp = int(time), 0
        elif isinstance(time, str):
            s = time.strip().lower().replace(" ", "")
            if s in ("", "last"):
                return self._last
            m = re.fullmatch(r"(\d+)(?:[,;/](\d+))?", s)
            if not m:
                raise MF6Error(f'Time "{time}" is not "last", a stress period ("12") or a period and step ("12,3").')
            kper, kstp = int(m.group(1)), int(m.group(2) or 0)
        else:
            raise MF6Error(f'Time {time!r} is not "last", a stress period or a period and step.')
        if kper not in self._steps:
            raise MF6Error(f"Stress period {kper} is not in {self.name} (it holds periods "
                           f"{_ranges(self.periods())}).")
        if kstp <= 0:
            return kper, self._steps[kper][-1]
        if kstp not in self._steps[kper]:
            raise MF6Error(f"Time step {kstp} of stress period {kper} is not saved in {self.name} "
                           f"(saved steps: {_ranges(self._steps[kper])}).")
        return kper, kstp

    # ---------------------------------------------------------------------------------------------- values
    def record(self, layer: int, kper: int, kstp: int) -> HeadRecord:
        """The record of a layer at (kper, kstp); kstp <= 0: the period's last saved step."""
        if int(layer) not in self.layers:
            raise MF6Error(f"Layer {layer} is not in {self.name} (layers {_ranges(self.layers)}).")
        kper, kstp = self.resolve((int(kper), int(kstp)))   # raises with the saved periods / steps
        rec = self._by_key.get((kper, kstp, int(layer)))
        if rec is None:
            raise MF6Error(f"Layer {layer} of stress period {kper}, step {kstp} is not in {self.name}.")
        return rec

    def read(self, layer: int, kper: int, kstp: int) -> np.ndarray:
        """Heads of one layer (1-based) at (kper, kstp): float64 (ncpl,), nan where dry or inactive
        (|value| >= 1e29). kstp <= 0: the period's last saved step. For DIS the values are in row-major order
        (the grid's cell order); DISU has one record (layer 1) of every node."""
        rec = self.record(layer, kper, kstp)
        try:
            with open(self.path, "rb") as fh:
                fh.seek(rec.offset)
                a = np.fromfile(fh, dtype=self._dtype, count=rec.size)
        except OSError as e:
            raise MF6Error(f"{self.name}: can't read ({e}).") from None
        if a.size != rec.size:
            raise MF6Error(f"{self.name} is truncated (layer {layer}, period {kper}, step {kstp}).")
        a = a.astype(np.float64)
        a[~(np.abs(a) < NO_VALUE)] = np.nan
        return a

    def read_layers(self, kper: int, kstp: int) -> np.ndarray:
        """(nlay, ncpl) heads of every layer at (kper, kstp); row k is layer k + 1 (nan for a layer not saved).
        kstp <= 0: the period's last saved step."""
        kper, kstp = self.resolve((int(kper), int(kstp)))
        nlay = self.nlay
        out = np.full((nlay, self.ncpl_per_record), np.nan)
        for lay in range(1, nlay + 1):
            if (kper, kstp, lay) in self._by_key:
                out[lay - 1] = self.read(lay, kper, kstp)
        return out

    def check_grid(self, grid: Grid) -> None:
        """MF6Error unless this head file fits `grid` (values per layer and layer count)."""
        if self.ncpl_per_record != grid.ncpl:
            raise MF6Error(f"{self.name} has {self.ncpl_per_record:,} values per layer but the grid "
                           f"{os.path.basename(grid.path)} has {grid.ncpl:,} cells per layer: the head file belongs "
                           "to another grid.")
        if self.nlay > grid.nlay:
            raise MF6Error(f"{self.name} has {self.nlay} layers but the grid {os.path.basename(grid.path)} has "
                           f"{grid.nlay}: the head file belongs to another grid.")


def head_file(path: str) -> HeadFile:
    """HeadFile(path) (cached)."""
    return HeadFile(path)


# ================================================================================================ surfaces
def water_table(heads: np.ndarray, idomain: Optional[np.ndarray] = None, botm: Optional[np.ndarray] = None,
                icelltype: Optional[np.ndarray] = None) -> np.ndarray:
    """(ncpl,) per cell column: the head of the uppermost layer that is active (idomain > 0, or no idomain) and
    not dry (nan, or |head| >= 1e29: HDRY / HNOFLO); nan where no layer qualifies.

    botm (nlay, ncpl), optional, for models run with NEWTON, where a dry cell keeps a computed head below its
    bottom instead of HDRY: a head at or below its cell's bottom then counts as dry too, for convertible cells
    only when icelltype (nlay, ncpl) is given (a confined cell, icelltype 0, never dries). A column whose every
    head is below its cell's bottom gets the head of its lowest active layer (the water table is below the model
    there), not a gap."""
    h = np.asarray(heads, dtype=float)
    if h.ndim == 1:
        h = h[None, :]
    if h.ndim != 2:
        raise MF6Error("water_table: heads must be (nlay, ncpl).")

    def same_shape(a, what):
        a = np.asarray(a)
        if a.size != h.size:
            raise MF6Error(f"water_table: {what} has {a.size} values, the heads {h.size}.")
        return a.reshape(h.shape)

    valid = np.isfinite(h) & (np.abs(h) < NO_VALUE)
    if idomain is not None:
        valid &= same_shape(idomain, "idomain") > 0
    wet = valid
    if botm is not None:
        with np.errstate(invalid="ignore"):
            above = h > same_shape(botm, "botm").astype(float)
        if icelltype is not None:
            above |= same_shape(icelltype, "icelltype") == 0
        wet = valid & above
    out = np.full(h.shape[1], np.nan)
    has = wet.any(axis=0)
    cols = np.nonzero(has)[0]
    out[cols] = h[np.argmax(wet, axis=0)[cols], cols]
    rest = np.nonzero(~has & valid.any(axis=0))[0]           # every head below its bottom: the lowest one
    if len(rest):
        lowest = h.shape[0] - 1 - np.argmax(valid[::-1], axis=0)
        out[rest] = h[lowest[rest], rest]
    return out


def surface_array(grid: Grid, var: str, layer: int = 1, head_path: str = "", time="last") -> np.ndarray:
    """One surface per cell, fresh float64 (ncpl,), model length units, nan where it has no value:

    - "top": the top of the uppermost active cell of each column (TOP where layer 1 is active); nan where no
      layer is active;
    - "botm": the bottom of `layer` (1-based), nan where that cell is inactive (idomain <= 0);
    - "head": the head of `layer` at `time` (HeadFile.resolve), nan where the cell is inactive or dry: HDRY, or (a
      model run with NEWTON, whose dry cells keep a computed head) a head at or below the cell's bottom in a
      convertible cell (any cell when the grid has no ICELLTYPE), as water_table counts it;
    - "wt": the water table at `time` (water_table with the grid's idomain, bottoms and icelltype: right for
      NEWTON models too). MF6Error when the head file does not hold every layer at that time.
    """
    var = (var or "").lower()
    if var not in ("top", "botm", "head", "wt"):
        raise MF6Error(f'Unknown model surface "{var}" (top, botm, head or wt).')
    active = grid.active()
    if var in ("botm", "head") and not 1 <= int(layer) <= grid.nlay:
        raise MF6Error(f"Layer {layer} is not in the grid (layers 1-{grid.nlay}).")
    if var == "top":
        tops = grid.layer_tops()
        has = active.any(axis=0)
        first = np.argmax(active, axis=0)
        out = np.full(grid.ncpl, np.nan)
        cols = np.nonzero(has)[0]
        out[cols] = tops[first[cols], cols]
        return out
    if var == "botm":
        out = np.array(grid.botm[int(layer) - 1], dtype=float)
        out[~active[int(layer) - 1]] = np.nan
        return out
    if not head_path:
        raise MF6Error("No head file chosen.")
    hf = HeadFile(head_path)
    hf.check_grid(grid)
    kper, kstp = hf.resolve(time)
    if var == "head":
        k = int(layer) - 1
        out = hf.read(int(layer), kper, kstp)
        out[~active[k]] = np.nan
        with np.errstate(invalid="ignore"):
            dry = out <= grid.botm[k]                         # NEWTON: a dry cell keeps a head below its bottom
        if grid.icelltype is not None:
            dry &= grid.icelltype[k] != 0                     # a confined cell never dries
        out[dry] = np.nan
        return out
    saved = hf.layers_at(kper, kstp)
    missing = [k for k in range(1, grid.nlay + 1) if k not in saved]
    if missing:
        raise MF6Error(f"{hf.name} holds no heads of layer{'s' if len(missing) > 1 else ''} {_ranges(missing)} at "
                       f"stress period {kper}, step {kstp}: the water table needs every layer.")
    heads = hf.read_layers(kper, kstp)
    if heads.shape[0] < grid.nlay:
        heads = np.vstack([heads, np.full((grid.nlay - heads.shape[0], grid.ncpl), np.nan)])
    return water_table(heads[:grid.nlay], grid.idomain, grid.botm, grid.icelltype)


# ================================================================================================ finding a model
@dataclass
class ModelFiles:
    sim_dir: str                        # where MODFLOW 6 ran (mfsim.nam); paths in the name files are relative to it
    model_name: str
    grid_path: str                      # the .grb when it exists, else the text grid file
    dis_text_path: str                  # the text grid file ("" if not there)
    head_path: str                      # the binary head file ("" if none)
    kind: str                           # dis | disv | disu
    nam_path: str = ""                  # the model name file ("" if not found)
    models: List[str] = field(default_factory=list)   # every gwf6 model of mfsim.nam
    notes: List[str] = field(default_factory=list)    # user-facing remarks (e.g. a head file that is missing)
    head_named: str = ""                # the head file the output control names (or the same-named one looked
                                        # for), whether or not it exists yet: where heads appear once the model runs


_GRID_EXTS = (".disv", ".dis", ".disu")
_HEAD_EXTS = (".hds", ".hed", ".bhd")


def _name_blocks(path: str) -> Dict[str, List[List[str]]]:
    """{block (lower): [words of each line]} of a small MF6 file (name files, OC)."""
    with open(path, "r", errors="replace") as fh:
        blocks = _blocks(fh.read())
    return {k: [t for t in (_tokens(ln) for ln in v[0].splitlines()) if t] for k, v in blocks.items()}


def _mfsim_models(mfsim: str) -> List[Tuple[str, str, str]]:
    """(mtype, name file, model name) of every model in mfsim.nam."""
    out = []
    for tok in _name_blocks(mfsim).get("models", []):
        if len(tok) >= 2:
            name = tok[2] if len(tok) > 2 else os.path.splitext(os.path.basename(tok[1]))[0]
            out.append((tok[0].upper(), tok[1], name))
    return out


def _model_packages(nam: str) -> List[Tuple[str, str]]:
    """(FTYPE, file name) of the PACKAGES block of a model name file."""
    return [(t[0].upper(), t[1]) for t in _name_blocks(nam).get("packages", []) if len(t) >= 2]


def _is_model_nam(path: str) -> bool:
    try:
        return bool(_model_packages(path))
    except OSError:
        return False


def _head_from_oc(oc: str) -> str:
    """The HEAD FILEOUT file name of an OC file ("" if none)."""
    for tok in _name_blocks(oc).get("options", []):
        up = [t.upper() for t in tok]
        if len(tok) >= 3 and up[0] == "HEAD" and up[1] == "FILEOUT":
            return tok[2]
    return ""


def _grb_for(dis_text: str, sim_dir: str) -> str:
    """The binary grid file MODFLOW 6 writes for a text grid file ("" if NOGRB or not there)."""
    if not os.path.isfile(dis_text):
        cand = dis_text + ".grb"
        return cand if os.path.isfile(cand) else ""
    opts = read_options(dis_text)
    if "NOGRB" in opts:
        return ""
    grb = opts.get("GRB6")
    if grb and len(grb) >= 2 and grb[0].upper() == "FILEOUT":
        cand = os.path.join(sim_dir, grb[1])
        if os.path.isfile(cand):
            return os.path.normpath(cand)
    cand = dis_text + ".grb"
    return cand if os.path.isfile(cand) else ""


def _from_model_nam(nam: str, sim_dir: str = "", model_name: str = "", models: Optional[List[str]] = None,
                    head_path: str = "", grid_path: str = "") -> ModelFiles:
    nam = os.path.abspath(nam)
    sim_dir = sim_dir or _find_sim_dir(os.path.dirname(nam))
    name = model_name or os.path.splitext(os.path.basename(nam))[0]
    dis_ftype = dis_file = oc_file = ""
    for ftype, fname in _model_packages(nam):
        if ftype in ("DIS6", "DISV6", "DISU6") and not dis_file:
            dis_ftype, dis_file = ftype, fname
        elif ftype == "OC6" and not oc_file:
            oc_file = fname
    if not dis_file:
        raise MF6Error(f"{os.path.basename(nam)} names no grid package (DIS6, DISV6 or DISU6).")
    kind = dis_ftype[:-1].lower()
    dis_text = os.path.normpath(os.path.join(sim_dir, dis_file.replace("\\", os.sep)))
    grb = _grb_for(dis_text, sim_dir)
    notes: List[str] = []
    if not grid_path:
        grid_path = grb or (dis_text if os.path.isfile(dis_text) else "")
    if not grid_path:
        raise MF6Error(f"Model {name}: neither its grid file {os.path.basename(dis_text)} nor "
                       f"{os.path.basename(dis_text)}.grb is in {sim_dir}.")
    head_named = head_path
    if not head_path:
        hds = ""
        if oc_file:
            oc_path = os.path.join(sim_dir, oc_file.replace("\\", os.sep))
            if os.path.isfile(oc_path):
                hds = _head_from_oc(oc_path)
                if not hds:
                    notes.append(f"The output control ({os.path.basename(oc_path)}) saves no heads.")
            else:
                notes.append(f"The output control file {oc_file} is missing.")
        else:
            notes.append(f"Model {name} has no output control (OC6): no heads are saved.")
        if hds:
            cand = os.path.normpath(os.path.join(sim_dir, hds.replace("\\", os.sep)))
            head_named = cand
            if os.path.isfile(cand):
                head_path = cand
            else:
                notes.append(f"The head file {hds} named in the output control is missing: run the model.")
    return ModelFiles(sim_dir=sim_dir, model_name=name, grid_path=grid_path,
                      dis_text_path=dis_text if os.path.isfile(dis_text) else "", head_path=head_path,
                      kind=kind, nam_path=nam, models=list(models or [name]), notes=notes, head_named=head_named)


def _from_mfsim(mfsim: str, model_name: str = "") -> ModelFiles:
    sim_dir = os.path.dirname(os.path.abspath(mfsim))
    models = _mfsim_models(mfsim)
    gwf = [m for m in models if m[0].startswith("GWF")]
    if not gwf:
        raise MF6Error(f"{mfsim} lists no groundwater flow model (gwf6).")
    names = [m[2] for m in gwf]
    pick = gwf[0]
    if model_name:
        match = [m for m in gwf if m[2].lower() == model_name.lower()]
        if not match:
            raise MF6Error(f"Model {model_name} is not in {os.path.basename(mfsim)} (it lists {', '.join(names)}).")
        pick = match[0]
    nam = os.path.join(sim_dir, pick[1].replace("\\", os.sep))
    if not os.path.isfile(nam):
        raise MF6Error(f"The model name file {pick[1]} listed in mfsim.nam is missing.")
    return _from_model_nam(nam, sim_dir, pick[2], names)


def _model_nams(folder: str) -> List[str]:
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names
            if n.lower().endswith(".nam") and n.lower() != "mfsim.nam" and os.path.isfile(os.path.join(folder, n))]


def _models_in(folder: str) -> List[Tuple[str, str, str]]:
    """(model name file, sim dir, model name) of the models run in `folder` (mfsim.nam first, then any other
    model name files there)."""
    out, seen = [], set()
    sim_dir = _find_sim_dir(folder)
    mfsim = os.path.join(sim_dir, "mfsim.nam")
    if os.path.isfile(mfsim):
        for mtype, fname, name in _mfsim_models(mfsim):
            if mtype.startswith("GWF"):
                nam = os.path.normcase(os.path.normpath(os.path.join(sim_dir, fname)))
                seen.add(nam)
                out.append((os.path.join(sim_dir, fname), sim_dir, name))
    for nam in _model_nams(folder):
        if os.path.normcase(os.path.normpath(nam)) not in seen and _is_model_nam(nam):
            out.append((nam, sim_dir, ""))
    return out


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _head_fits(head_path: str, grid_path: str) -> str:
    """"" if the head file fits the grid, else why not."""
    try:
        HeadFile(head_path).check_grid(read_grid(grid_path))
        return ""
    except MF6Error as e:
        return str(e)


def _from_grid_file(path: str, model_name: str = "") -> ModelFiles:
    folder = os.path.dirname(path)
    grb = _is_grb(path)
    dis_text = _text_companion(path) if grb else path
    for nam, sim_dir, name in _models_in(folder):
        if model_name and name and name.lower() != model_name.lower():
            continue
        try:
            for ftype, fname in _model_packages(nam):
                if ftype in ("DIS6", "DISV6", "DISU6"):
                    cand = os.path.join(sim_dir, fname.replace("\\", os.sep))
                    if (dis_text and _same(cand, dis_text)) or _same(cand + ".grb", path) or \
                            _same(_grb_for(cand, sim_dir) or cand + ".grb", path):
                        return _from_model_nam(nam, sim_dir, name, grid_path=path if grb else "")
        except OSError:
            continue
    # no name file names it: the grid alone, and a head file of the same name that fits it
    grid = read_grid(path)
    grid_path = path if grb else (_grb_for(path, folder) or path)
    stem = os.path.basename(dis_text or path[:-4] if grb else path)
    stem = os.path.splitext(stem)[0] if os.path.splitext(stem)[1].lower() in _GRID_EXTS else stem
    notes = [f"No model name file in {folder} names {os.path.basename(path)}."]
    head_path = ""
    for ext in _HEAD_EXTS:
        cand = os.path.join(folder, stem + ext)
        if os.path.isfile(cand):
            why = _head_fits(cand, grid_path)
            if why:
                notes.append(why)
            else:
                head_path = cand
                break
    return ModelFiles(sim_dir=_find_sim_dir(folder), model_name=stem, grid_path=grid_path,
                      dis_text_path=dis_text if dis_text and os.path.isfile(dis_text) else "", head_path=head_path,
                      kind=grid.kind, notes=notes, head_named=head_path or os.path.join(folder, stem + _HEAD_EXTS[0]))


def _from_head_file(path: str, model_name: str = "") -> ModelFiles:
    folder = os.path.dirname(path)
    for nam, sim_dir, name in _models_in(folder):
        if model_name and name and name.lower() != model_name.lower():
            continue
        try:
            for ftype, fname in _model_packages(nam):
                if ftype == "OC6":
                    oc = os.path.join(sim_dir, fname.replace("\\", os.sep))
                    if os.path.isfile(oc):
                        hds = _head_from_oc(oc)
                        if hds and _same(os.path.join(sim_dir, hds.replace("\\", os.sep)), path):
                            return _from_model_nam(nam, sim_dir, name, head_path=path)
        except OSError:
            continue
    stem = os.path.splitext(os.path.basename(path))[0]
    hf = HeadFile(path)
    tried = []
    for ext in _GRID_EXTS:
        for cand in (os.path.join(folder, stem + ext + ".grb"), os.path.join(folder, stem + ext)):
            if os.path.isfile(cand):
                tried.append(os.path.basename(cand))
                try:
                    grid = read_grid(cand)
                except MF6Error:
                    continue
                if grid.ncpl == hf.ncpl_per_record:
                    text = cand[:-4] if cand.lower().endswith(".grb") else cand
                    return ModelFiles(sim_dir=_find_sim_dir(folder), model_name=stem, grid_path=cand,
                                      dis_text_path=text if os.path.isfile(text) else "", head_path=path,
                                      kind=grid.kind, notes=[f"No model name file in {folder} names "
                                                             f"{os.path.basename(path)}."], head_named=path)
    extra = f" ({', '.join(tried)} {'do' if len(tried) > 1 else 'does'} not fit it)" if tried else ""
    raise MF6Error(f"No grid file found for {os.path.basename(path)} in {folder}{extra}: choose the model's "
                   ".grb or .disv file.")


def find_model(path: str, model_name: str = "") -> ModelFiles:
    """The files of a MODFLOW 6 model from: its run folder (mfsim.nam: the first gwf6 model unless `model_name`
    is given), mfsim.nam, a model name file, a text grid file (.dis / .disv / .disu), a binary grid file (.grb),
    or a head file (.hds; the model is looked for in the same folder). MF6Error when nothing usable is found."""
    if not path:
        raise MF6Error("No MODFLOW 6 model chosen.")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise MF6Error(f"{path} does not exist.")
    try:
        if os.path.isdir(path):
            if os.path.isfile(os.path.join(path, "mfsim.nam")):
                return _from_mfsim(os.path.join(path, "mfsim.nam"), model_name)
            nams = [n for n in _model_nams(path) if _is_model_nam(n)]
            if model_name:
                nams = [n for n in nams if os.path.splitext(os.path.basename(n))[0].lower() == model_name.lower()]
            if nams:
                return _from_model_nam(nams[0])
            files = sorted(os.listdir(path))
            for pred in (lambda n: n.lower().endswith(".grb"), lambda n: n.lower().endswith(_GRID_EXTS),
                         lambda n: n.lower().endswith(_HEAD_EXTS)):
                hits = [os.path.join(path, n) for n in files if pred(n) and os.path.isfile(os.path.join(path, n))]
                if hits:
                    return find_model(hits[0], model_name)
            raise MF6Error(f"No MODFLOW 6 model in {path}: expected mfsim.nam, a model name file, a grid file "
                           "(.grb, .disv, .dis) or a head file (.hds).")
        low = path.lower()
        base = os.path.basename(low)
        if base == "mfsim.nam":
            return _from_mfsim(path, model_name)
        if low.endswith(".nam"):
            if not _is_model_nam(path):
                if _mfsim_models(path):
                    return _from_mfsim(path, model_name)
                raise MF6Error(f"{os.path.basename(path)} is not a MODFLOW 6 name file.")
            return _from_model_nam(path, model_name=model_name)
        if low.endswith(_HEAD_EXTS):
            return _from_head_file(path, model_name)
        if low.endswith(".grb") or low.endswith(_GRID_EXTS) or _is_grb(path):
            return _from_grid_file(path, model_name)
        # anything else: look at the content
        try:
            HeadFile(path)
            return _from_head_file(path, model_name)
        except NotHeadsError:
            raise                               # e.g. a concentration file: say so
        except MF6Error:
            pass
        try:
            read_grid(path)
            return _from_grid_file(path, model_name)
        except MF6Error:
            pass
        raise MF6Error(f"{os.path.basename(path)} is not a MODFLOW 6 file this reader knows (mfsim.nam, a model "
                       "name file, .grb, .disv, .dis, .disu or .hds).")
    except OSError as e:
        raise MF6Error(f"{path}: {e.strerror or e}.") from None
