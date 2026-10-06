"""MODFLOW 6 surfaces in the panel: the "+ Add MODFLOW 6…" dialog and the model surface row.

- load_model(path) / load_paths(grid, heads) -> ModelInfo: what core.mf6 reads of a model (never raises; problems
  become `error` / `head_error` text for the panel).
- MF6Dialog: pick a run folder or a model file, see a one-paragraph summary, tick the model top, layer bottoms,
  heads and the water table, choose the time, the model CRS and smooth or cells; surfaces() gives one
  Settings.surfaces dict per ticked item (source "mf6").
- ModelSurfaceRow: a SurfaceRow whose editor shows the model file (Change…), the variable, layer, time and model
  CRS instead of a raster and band. Every key is kept as stored, also when the model files are missing.

Times are stored as "last", "kper" (the stress period's last saved step, whatever its number: adaptive time stepping
can change it on every run) or "kper,kstp" (model.SURFACE_DEFAULTS mf6_time); the combos list "Last saved (SP 30,
step 13)", then per stress period "SP 3 · t = 12.5" (a period with one saved step, stored "3"), or "SP 2 · last step
(3) · t = 40" (stored "2") followed by each of its saved steps ("SP 2 · step 1 · t = 20", stored "2,1").
"""
from __future__ import annotations

import contextlib
import html
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                                 QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QSizePolicy,
                                 QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core import mf6
from ..core.mf6_section import auto_name
from ..core.model import SURFACE_DEFAULTS, clean_surface
from . import settings_store
from .widgets import (CONTROL_H, ElidedLabel, SegmentedControl, SurfaceRow, _narrow_combo, field_box, link_button,
                      pair, panel_stylesheet, theme_for)

LAST_DIR_KEY = "last_mf6_dir"            # user setting: the folder the pickers start in
MODEL_FILTER = ("MODFLOW 6 model (mfsim.nam *.nam *.disv *.dis *.disu *.grb *.hds *.hed *.bhd);;"
                "All files (*)")
TOP_COLOR = "#555555"                    # model top: gray, solid
BOTTOM_COLOR = "#8c5a3c"                 # layer bottoms: a brown ramp around it (darker for layer 1), solid
HEAD_COLOR = "#6a51a3"                   # heads: a purple ramp around it, dashed (well apart from the water table's
                                         # blue, the bottoms' browns and a green grid)
WT_COLOR = "#1f6fb2"                     # water table: blue (the sheet's water colour), dashed, with ▽ marks
VAR_CHOICES = [("Top", "top"), ("Bottom", "botm"), ("Head", "head"), ("Water table", "wt")]
VAR_TIPS = ["The model top (the top of the uppermost active cell)", "The bottom of the chosen layer",
            "The head of the chosen layer at the chosen time",
            "The head of the uppermost wet (active, not dry) layer of each cell column at the chosen time"]
KIND_WORDS = {"dis": "DIS", "disv": "DISV", "disu": "DISU"}


# ---------------------------------------------------------------- small helpers (pure; also used by tests)
def fmt_time(t: float) -> str:
    """A simulation time for a label: 12.5, 30, 1,234.25."""
    text = f"{float(t):,.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def ranges(values: Iterable[int]) -> str:
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


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def ramp(base: str, n: int, dark: float = 0.35, light: float = 0.45) -> List[str]:
    """`n` colours from darker to lighter around `base` (`base` itself for one; the middle one for an odd n)."""
    if n <= 0:
        return []
    if n == 1:
        return [QColor(base).name()]
    out = []
    for i in range(n):
        t = i / (n - 1)
        out.append(_mix(base, "#000000", dark * (1.0 - 2.0 * t)) if t < 0.5
                   else _mix(base, "#ffffff", light * (2.0 * t - 1.0)))
    return out


def parse_time(time: str) -> Optional[Tuple[int, int]]:
    """"kper,kstp" -> (kper, kstp); "kper" -> (kper, 0) (the period's last saved step); "last" (or anything else)
    -> None."""
    parts = (time or "").replace(" ", "").split(",")
    try:
        if len(parts) == 1:
            kper, kstp = int(parts[0]), 0
        elif len(parts) == 2:
            kper, kstp = int(parts[0]), int(parts[1])
        else:
            return None
    except ValueError:
        return None
    return (kper, kstp) if kper > 0 and kstp >= 0 else None


def time_items(hf: Optional[mf6.HeadFile]) -> List[Tuple[str, str]]:
    """(text, data) of the time combo: "Last saved (SP 30, step 13)" ("last"), then per stress period in time order:
    "SP 3 · t = 60" ("3") for a period with one saved step; for one with several, "SP 2 · last step (3) ·
    t = 40" ("2") and then each saved step, "SP 2 · step 1 · t = 20" ("2,1"). A period stored alone means its last
    saved step whatever its number (adaptive time stepping can change it when the model runs again). Without a
    head file: "Last saved" only."""
    if hf is None:
        return [("Last saved", "last")]
    kper, kstp = hf.resolve("last")
    items = [(f"Last saved (SP {kper}, step {kstp})", "last")]
    times = sorted(hf.times())
    for p in hf.periods():
        steps = [(s, t) for pp, s, t in times if pp == p]
        if len(steps) == 1:
            items.append((f"SP {p} · t = {fmt_time(steps[0][1])}", f"{p}"))
            continue
        items.append((f"SP {p} · last step ({steps[-1][0]}) · t = {fmt_time(steps[-1][1])}", f"{p}"))
        items.extend((f"SP {p} · step {s} · t = {fmt_time(t)}", f"{p},{s}") for s, t in steps)
    return items


def time_words(time: str, hf: Optional[mf6.HeadFile] = None) -> str:
    """A stored time for a row's sub line: "last saved", "SP 30" (a period alone, or the period's only saved step),
    "SP 2, last step" (a period alone that saved several steps) or "SP 3, step 2"."""
    pk = parse_time(time)
    if pk is None:
        return "last saved"
    kper, kstp = pk
    if kstp == 0:
        return f"SP {kper}, last step" if hf is not None and len(hf.steps(kper)) > 1 else f"SP {kper}"
    if hf is not None and hf.steps(kper) == [kstp]:
        return f"SP {kper}"
    return f"SP {kper}, step {kstp}"


def times_summary(hf: mf6.HeadFile) -> str:
    """"30 stress periods saved, SP 1-30, step 13" or "6 times saved in 3 stress periods (SP 1-3)"."""
    periods = hf.periods()
    n = len(periods)
    sp = f"stress period{'s' if n != 1 else ''}"
    steps = {p: hf.steps(p) for p in periods}
    if all(len(v) == 1 for v in steps.values()):
        count = Counter(v[0] for v in steps.values())
        common = count.most_common(1)[0][0]
        others = [(p, v[0]) for p, v in steps.items() if v[0] != common]
        if not others:
            tail = f", step {common}"
        elif len(others) <= 3:                 # e.g. adaptive time steps in a few periods
            tail = f", step {common} ({', '.join(f'SP {p}: step {k}' for p, k in others)})"
        else:
            tail = ", the last step of each"
        text = f"{n} {sp} saved, SP {ranges(periods)}{tail}"
    else:
        nt = len(hf.times())
        text = f"{nt} time{'s' if nt != 1 else ''} saved in {n} {sp} (SP {ranges(periods)})"
    if hf.truncated:
        text += "; its last record is incomplete (is the model still running?)"
    return text


def model_stem(path: str) -> str:
    """The model's name from its grid file: "F9_flowV1.disv.grb" -> "F9_flowV1"."""
    base = os.path.basename(path or "")
    for ext in (".grb", ".disv", ".dis", ".disu"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
    return base


def what_words(var: str, layer: int, kind: str = "") -> str:
    """"model top", "layer 2 bottom", "layer 1 head", "water table" (a DISU, whose nodes have no layers: "model
    bottom", "head")."""
    if kind == "disu" and var in ("botm", "head"):
        return "model bottom" if var == "botm" else "head"
    return {"top": "model top", "botm": f"layer {layer} bottom", "head": f"layer {layer} head",
            "wt": "water table"}.get(var, var)


def default_name(d: dict, kind: str = "") -> str:
    """A model surface's name without its time: "Model top", "Layer 2 bottom", "Water table" (the row and the legend
    add the time of heads, mf6_section.auto_name)."""
    words = what_words(d.get("mf6_var", "top"), int(d.get("mf6_layer", 1) or 1), kind)
    return words[:1].upper() + words[1:]


def crs_text(crs: QgsCoordinateReferenceSystem) -> str:
    """A CRS for Settings mf6_crs: its auth id, or its WKT when it has none (or only a USER: id, which exists on
    one machine only); "" for an invalid CRS."""
    if crs is None or not crs.isValid():
        return ""
    authid = crs.authid()
    if authid and not authid.upper().startswith("USER:"):
        return authid
    return crs.toWkt()


def crs_from_text(text: str) -> QgsCoordinateReferenceSystem:
    """Settings mf6_crs -> a CRS: "" is the project CRS; an auth id or a WKT."""
    if not text:
        return QgsProject.instance().crs()
    if "[" in text:
        return QgsCoordinateReferenceSystem.fromWkt(text)
    return QgsCoordinateReferenceSystem(text)


def model_surfaces(grid_path: str, head_path: str, nlay: int, top: bool = False, bottoms: Sequence[int] = (),
                   heads: Sequence[int] = (), wt: bool = False, time: str = "last", crs: str = "",
                   mode: str = "smooth") -> List[dict]:
    """Settings.surfaces dicts for the ticked items, in this order: the model top, the layer bottoms (layer order),
    the heads (layer order), the water table. Colours: the top gray, bottoms a brown ramp, heads a blue ramp
    (dashed), the water table blue, dashed, with ▽ marks; the ramps run over the model's layers, so a layer keeps
    its colour whichever layers are ticked. The name is left empty (an automatic name)."""
    base = dict(SURFACE_DEFAULTS, source="mf6", name="", mf6_path=grid_path, mf6_head_path=head_path,
                mf6_time=time or "last", mf6_crs=crs, mode=mode)
    nlay = max(1, int(nlay), *(int(k) for k in list(bottoms) + list(heads)))
    browns, blues = ramp(BOTTOM_COLOR, nlay), ramp(HEAD_COLOR, nlay)
    out = []
    if top:
        out.append(dict(base, mf6_var="top", color=TOP_COLOR, style="solid"))
    for k in sorted(set(int(k) for k in bottoms)):
        out.append(dict(base, mf6_var="botm", mf6_layer=k, color=browns[k - 1], style="solid"))
    for k in sorted(set(int(k) for k in heads)):
        out.append(dict(base, mf6_var="head", mf6_layer=k, color=blues[k - 1], style="dash"))
    if wt:
        out.append(dict(base, mf6_var="wt", color=WT_COLOR, style="dash", marks=True))
    return [clean_surface(d) for d in out]


def _esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def _error_text(exc: Exception) -> str:
    return str(exc) if isinstance(exc, mf6.MF6Error) else f"{type(exc).__name__}: {exc}"


@contextlib.contextmanager
def wait_cursor():
    """A wait cursor while a (large) model is read."""
    QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


# ---------------------------------------------------------------- what the reader says about a model
@dataclass
class ModelInfo:
    chosen: str = ""                       # what the user picked (folder or file)
    model_name: str = ""
    grid_path: str = ""
    head_path: str = ""
    grid: Optional[mf6.Grid] = None
    heads: Optional[mf6.HeadFile] = None   # None without a (usable) head file
    error: str = ""                        # the model can't be used (no grid, or a grid without cell vertices)
    head_error: str = ""                   # the head file can't be used (missing, unreadable, another grid)
    notes: List[str] = field(default_factory=list)   # the reader's remarks (e.g. the head file named is missing)
    models: List[str] = field(default_factory=list)  # every flow model of the simulation (mfsim.nam)

    @property
    def ok(self) -> bool:
        return self.grid is not None and not self.error

    @property
    def nlay(self) -> int:
        return self.grid.nlay if self.grid is not None else 0

    def grid_words(self) -> str:
        """"DISV grid, 3 layers × 27,688 cells per layer, feet"."""
        g = self.grid
        if g is None:
            return ""
        units = g.length_units if g.length_units != "unknown" else "length units unknown"
        if g.kind == "disu":
            shape = f"{g.ncpl:,} nodes ({g.nlay} layer{'s' if g.nlay != 1 else ''})"
        else:
            shape = f"{g.nlay} layer{'s' if g.nlay != 1 else ''} × {g.ncpl:,} cells per layer"
            if g.kind == "dis":
                shape += f" ({g.nrow:,} rows × {g.ncol:,} columns)"
        return f"{KIND_WORDS.get(g.kind, g.kind.upper())} grid, {shape}, {units}"

    def summary_html(self, warn: str) -> str:
        """One paragraph: model, grid, layers, cells per layer, length units, the head file and its saved times
        (or "No head file."), then any problem in amber (`warn`, a colour)."""
        amber = []
        if self.grid is None:
            amber.append(self.error or "Choose a MODFLOW 6 run folder or model file.")
            return f"<span style='color:{warn}'>{_esc(' '.join(amber))}</span>"
        name = self.model_name or model_stem(self.grid_path)
        text = (f"<b>{_esc(name)}</b>: {_esc(self.grid_words())} ({_esc(os.path.basename(self.grid_path))}). ")
        if self.heads is not None:
            text += f"Heads: {_esc(self.heads.name)}, {_esc(times_summary(self.heads))}."
            saved = self.heads.layers
            if self.grid.kind != "disu" and saved != list(range(1, self.grid.nlay + 1)):
                text += f" Heads of layer{'s' if len(saved) != 1 else ''} {_esc(ranges(saved))} only."
        else:
            text += "No head file."
        if len(self.models) > 1:
            text += (f" The simulation has {len(self.models)} flow models ({_esc(', '.join(self.models))}): for "
                     "another, choose its name file (.nam) with File….")
        amber = [n for n in self.notes] + [m for m in (self.head_error, self.error) if m]
        if amber:
            text += f" <span style='color:{warn}'>{_esc(' '.join(amber))}</span>"
        return text


def _read_into(info: ModelInfo, grid_path: str, head_path: str) -> ModelInfo:
    info.grid_path, info.head_path = grid_path, head_path
    try:
        info.grid = mf6.read_grid(grid_path)
    except Exception as exc:               # MF6Error, or a reader bug: never a traceback in the panel
        info.error = _error_text(exc)
        return info
    if not info.grid.has_vertices:
        info.error = (f"{os.path.basename(grid_path)} has no cell vertices, so it can't be drawn along a section.")
    if head_path:
        try:
            hf = mf6.HeadFile(head_path)
            hf.check_grid(info.grid)
            info.heads = hf
        except Exception as exc:
            info.head_error = _error_text(exc)
    return info


def load_model(path: str, prefer: str = "") -> ModelInfo:
    """Find and read the model at `path` (a run folder, mfsim.nam, a model .nam, a grid file or a head file). In a
    simulation of several flow models the first is used, or the one named `prefer` when the simulation has it."""
    info = ModelInfo(chosen=path)
    try:
        files = mf6.find_model(path)
        if (prefer and len(files.models) > 1 and prefer.lower() != files.model_name.lower()
                and prefer.lower() in (m.lower() for m in files.models)):
            files = mf6.find_model(path, prefer)
    except Exception as exc:
        info.error = _error_text(exc)
        return info
    info.model_name = files.model_name
    info.notes = list(files.notes)
    info.models = list(files.models)
    return _read_into(info, files.grid_path, files.head_path)


def load_paths(grid_path: str, head_path: str = "") -> ModelInfo:
    """Read a stored model surface's grid and head files (no search)."""
    info = ModelInfo(chosen=grid_path, model_name=model_stem(grid_path))
    if not grid_path:
        info.error = "No model file chosen."
        return info
    return _read_into(info, grid_path, head_path)


def pick_model_path(parent: Optional[QWidget], folder: bool) -> str:
    """Folder…: a run folder; File…: mfsim.nam, a model .nam, a grid or a head file. Starts in, and remembers,
    the user setting last_mf6_dir. "" when cancelled."""
    start = settings_store.user_value(LAST_DIR_KEY, "")
    if start and not os.path.isdir(start):
        start = ""
    if folder:
        path = QFileDialog.getExistingDirectory(parent, "MODFLOW 6 run folder", start)
        remember = path
    else:
        path, _flt = QFileDialog.getOpenFileName(parent, "MODFLOW 6 model file", start, MODEL_FILTER)
        remember = os.path.dirname(path) if path else ""
    if remember:
        settings_store.set_user_value(LAST_DIR_KEY, remember)
    return path or ""


def fill_time_combo(combo: QComboBox, hf: Optional[mf6.HeadFile], current: str = "last") -> None:
    """The time choices of `hf` (time_items), with `current` chosen. A stored time is always kept as it is: a
    "kper,kstp" of a period listed by its period alone gets its own item (next to the period's), and a time the file
    does not hold an extra "(not saved)" item, so nothing changes until the user picks another."""
    current = (current or "last").replace(" ", "")
    blocked = combo.blockSignals(True)
    try:
        combo.clear()
        for text, data in time_items(hf):
            combo.addItem(text, data)
        i = combo.findData(current)
        if i < 0:
            pk = parse_time(current)
            if pk is not None and pk[1] > 0 and hf is not None and pk[1] in hf.steps(pk[0]):
                j = combo.findData(str(pk[0]))
                i = j + 1 if j >= 0 else combo.count()
                combo.insertItem(i, f"SP {pk[0]} · step {pk[1]} · t = {fmt_time(hf.totim(*pk))}", current)
            else:
                label = current if pk is None else f"SP {pk[0]}" if pk[1] == 0 else f"SP {pk[0]} · step {pk[1]}"
                combo.addItem(label + (" (not saved)" if hf is not None else ""), current)
                i = combo.count() - 1
        combo.setCurrentIndex(i)
    finally:
        combo.blockSignals(blocked)


def project_crs_words() -> str:
    """The text of the model CRS choice that follows the project CRS: "Project CRS (EPSG:2927)"."""
    crs = QgsProject.instance().crs()
    authid = crs.authid() if crs.isValid() else ""
    return f"Project CRS ({authid})" if authid else "Project CRS"


def _crs_widget(parent: Optional[QWidget], project_choice: bool = False) -> QgsProjectionSelectionWidget:
    """The model CRS picker; with `project_choice`, its first choice is "Project CRS (…)", an empty mf6_crs (the
    model follows the project CRS) shown as such."""
    w = QgsProjectionSelectionWidget(parent)
    w.setToolTip("CRS of the model's coordinates (XORIGIN, YORIGIN and the vertices)")
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    if project_choice:
        w.setOptionVisible(QgsProjectionSelectionWidget.CrsOption.CrsNotSet, True)
        w.setNotSetText(project_crs_words())
    for combo in w.findChildren(QComboBox):          # shrink with the panel (the CRS names are long)
        _narrow_combo(combo, 8)
    return w


def _check_list() -> QListWidget:
    lst = QListWidget()
    lst.setObjectName("xsCheckList")
    lst.setSelectionMode(QListWidget.SelectionMode.NoSelection)
    lst.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    lst.setUniformItemSizes(True)
    lst.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return lst


# ---------------------------------------------------------------- the dialog
class MF6Dialog(QDialog):
    """+ Add MODFLOW 6…: pick a model, tick its surfaces. surfaces() gives the Settings.surfaces dicts."""

    MAX_ROWS = 6                             # layer lists taller than this scroll

    def __init__(self, parent: Optional[QWidget] = None, path: str = "",
                 crs: Optional[QgsCoordinateReferenceSystem] = None):
        super().__init__(parent)
        self.setObjectName("xsMF6Dialog")
        self.setWindowTitle("Add MODFLOW 6 surfaces")
        self.info: Optional[ModelInfo] = None
        self._time = "last"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # the model
        self.path_label = ElidedLabel("", elide=Qt.TextElideMode.ElideMiddle)
        self.btn_folder = self._button("Folder…", "Choose the folder the model ran in (where mfsim.nam is)")
        self.btn_file = self._button("File…", "Choose mfsim.nam, a model name file, a grid file (.grb, .disv, "
                                              ".dis, .disu) or a head file (.hds)")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(5)
        rl.addWidget(self.path_label, 1)
        rl.addWidget(self.btn_folder, 0)
        rl.addWidget(self.btn_file, 0)
        lay.addWidget(field_box("MODFLOW 6 model", row))
        self.summary = QLabel("")
        self.summary.setObjectName("xsSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.summary)
        rule = QFrame()
        rule.setObjectName("xsRule")
        rule.setFixedHeight(1)
        lay.addWidget(rule)

        # the surfaces
        self.top_box = QCheckBox("Model top")
        self.top_box.setToolTip(VAR_TIPS[0])
        lay.addWidget(self.top_box)
        self.bottoms = _check_list()
        self.bottoms.setToolTip("The bottom of each ticked layer")
        self.heads = _check_list()
        self.heads.setToolTip("The head of each ticked layer at the chosen time")
        self.btn_bottoms_all, self.btn_bottoms_none = link_button("All"), link_button("None")
        self.btn_heads_all, self.btn_heads_none = link_button("All"), link_button("None")
        lay.addWidget(pair(field_box("Bottoms", self.bottoms, links=[self.btn_bottoms_all, self._dot(),
                                                                         self.btn_bottoms_none]),
                           field_box("Heads", self.heads, links=[self.btn_heads_all, self._dot(),
                                                                 self.btn_heads_none])))
        self.wt_box = QCheckBox("Water table (uppermost wet layer)")
        self.wt_box.setToolTip(VAR_TIPS[3])
        lay.addWidget(self.wt_box)
        self.time_combo = QComboBox()
        _narrow_combo(self.time_combo, 10)
        self.time_combo.setToolTip("Heads and the water table at this saved time (a stress period's last saved "
                                   "step, unless a step is listed)")
        lay.addWidget(field_box("Time", self.time_combo))
        self.crs_widget = _crs_widget(self)
        self.crs_widget.setCrs(crs if crs is not None and crs.isValid() else QgsProject.instance().crs())
        lay.addWidget(field_box("Model CRS", self.crs_widget))
        self.mode_seg = SegmentedControl([("Smooth", "smooth"), ("Cells", "cells")])
        self.mode_seg.setItemToolTip(0, "Interpolated between cell centers")
        self.mode_seg.setItemToolTip(1, "Flat across each cell, stepping at cell edges")
        lay.addWidget(field_box("Draw as", self.mode_seg))
        lay.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setObjectName("xsPrimary")
        self.ok_button.setMinimumHeight(CONTROL_H + 2)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self.btn_folder.clicked.connect(lambda: self.choose(folder=True))
        self.btn_file.clicked.connect(lambda: self.choose(folder=False))
        for box in (self.top_box, self.wt_box):
            box.toggled.connect(self._update_buttons)
        for lst in (self.bottoms, self.heads):
            lst.itemChanged.connect(self._update_buttons)
        self.btn_bottoms_all.clicked.connect(lambda: self._check_all(self.bottoms, True))
        self.btn_bottoms_none.clicked.connect(lambda: self._check_all(self.bottoms, False))
        self.btn_heads_all.clicked.connect(lambda: self._check_all(self.heads, True))
        self.btn_heads_none.clicked.connect(lambda: self._check_all(self.heads, False))
        self.setStyleSheet(panel_stylesheet(theme_for(self.palette())) + self._own_style())
        self.setMinimumWidth(320)
        self.set_path(path)

    # ---- building blocks
    @staticmethod
    def _button(text: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("xsTool")
        b.setText(text)
        b.setToolTip(tip)
        b.setFixedHeight(CONTROL_H + 2)
        return b

    @staticmethod
    def _dot() -> QLabel:
        dot = QLabel("·")
        dot.setObjectName("xsMuted")
        return dot

    def _own_style(self) -> str:
        t = theme_for(self.palette())
        return (f"QFrame#xsRule {{ background: {t.rule.name()}; border: none; }}"
                f"QListWidget#xsCheckList {{ background: {t.field.name()}; border: 1px solid {t.field_line.name()};"
                f" border-radius: 3px; }}")

    # ---- the model
    def choose(self, folder: bool) -> bool:
        """Folder… / File…: pick, then read the model. False when cancelled."""
        path = pick_model_path(self, folder)
        if not path:
            return False
        self.set_path(path)
        return True

    def set_path(self, path: str) -> None:
        """Read the model at `path` and show what it holds (checks of layers that are still there are kept)."""
        if path:
            with wait_cursor():
                self.info = load_model(path)
        else:
            self.info = None
        self.path_label.setText(path or "(no model chosen)")
        self.path_label.setToolTip(path)
        self.path_label.setMuted(not path)
        self.path_label.setWarn(self.info is not None and not self.info.ok)
        warn = theme_for(self.palette()).warn.name()
        if self.info is None:
            self.summary.setText("Choose the folder the model ran in (mfsim.nam), or one of its files: a name file, "
                                 "a grid file (.grb, .disv, .dis) or a head file (.hds).")
        else:
            self.summary.setText(self.info.summary_html(warn))
        nlay = self.info.nlay if self.info is not None else 0
        kind = self.info.grid.kind if self.info is not None and self.info.grid is not None else ""
        self._fill_layers(self.bottoms, nlay, "botm", kind)
        self._fill_layers(self.heads, nlay, "head", kind)
        if self.time_combo.isEnabled() and self.time_combo.count():
            self._time = self.time_combo.currentData() or "last"      # kept for the next model when it has it
        heads = self.info.heads if self.info is not None else None
        held = {data for _text, data in time_items(heads)}
        fill_time_combo(self.time_combo, heads, self._time if self._time in held else "last")
        self._update_buttons()

    def _fill_layers(self, lst: QListWidget, nlay: int, var: str = "botm", kind: str = "") -> None:
        checked = set(self._checked(lst))
        blocked = lst.blockSignals(True)
        try:
            lst.clear()
            for k in range(1, nlay + 1):
                item = QListWidgetItem(default_name(dict(mf6_var=var), kind) if kind == "disu" else f"Layer {k}")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if k in checked else Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, k)
                lst.addItem(item)
        finally:
            lst.blockSignals(blocked)
        row = lst.sizeHintForRow(0) if nlay else lst.fontMetrics().height() + 4
        rows = max(1, min(nlay, self.MAX_ROWS))
        lst.setFixedHeight(rows * max(row, 12) + 2 * lst.frameWidth() + 2)

    @staticmethod
    def _checked(lst: QListWidget) -> List[int]:
        return [int(lst.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(lst.count())
                if lst.item(i).checkState() == Qt.CheckState.Checked]

    def _check_all(self, lst: QListWidget, on: bool) -> None:
        blocked = lst.blockSignals(True)
        try:
            for i in range(lst.count()):
                lst.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        finally:
            lst.blockSignals(blocked)
        self._update_buttons()

    # ---- choices
    def has_heads(self) -> bool:
        return self.info is not None and self.info.ok and self.info.heads is not None

    def checked_bottoms(self) -> List[int]:
        return self._checked(self.bottoms) if self.info is not None and self.info.ok else []

    def checked_heads(self) -> List[int]:
        return self._checked(self.heads) if self.has_heads() else []

    def time(self) -> str:
        return (self.time_combo.currentData() or "last") if self.has_heads() else "last"

    def crs(self) -> str:
        return crs_text(self.crs_widget.crs())

    def surfaces(self) -> List[dict]:
        """One Settings.surfaces dict per ticked item: top, bottoms, heads, water table (model_surfaces)."""
        info = self.info
        if info is None or not info.ok:
            return []
        return model_surfaces(info.grid_path, info.head_path if info.heads is not None else "", info.nlay,
                              top=self.top_box.isChecked(), bottoms=self.checked_bottoms(),
                              heads=self.checked_heads(), wt=self.has_heads() and self.wt_box.isChecked(),
                              time=self.time(), crs=self.crs(), mode=self.mode_seg.currentData() or "smooth")

    def _update_buttons(self, *args) -> None:
        ok = self.info is not None and self.info.ok
        heads = self.has_heads()
        self.top_box.setEnabled(ok)
        self.bottoms.setEnabled(ok)
        for b in (self.btn_bottoms_all, self.btn_bottoms_none):
            b.setEnabled(ok)
        for w in (self.heads, self.wt_box, self.time_combo, self.btn_heads_all, self.btn_heads_none):
            w.setEnabled(heads)
        n = len(self.surfaces())
        self.ok_button.setEnabled(n > 0)
        self.ok_button.setText(f"Add {n} surface{'s' if n != 1 else ''}" if n else "Add")
        self.ok_button.setToolTip("" if n else "Tick the surfaces to add")


# ---------------------------------------------------------------- a model surface in the Surfaces list
def _file_stat(path: str) -> Optional[Tuple[int, int]]:
    """(mtime_ns, size) of a file, None when it is not there."""
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class ModelSurfaceRow(SurfaceRow):
    """A MODFLOW 6 surface (source "mf6"): its editor shows the model file (Change…), the variable (Top, Bottom,
    Head, Water table), the layer (Bottom, Head), the time (Head, Water table) and the model CRS ("Project CRS (…)"
    for an empty mf6_crs), then the common fields. A row whose model files are missing turns its name amber and
    keeps every key.

    The row follows its files on disk (sync(), called whenever it shows its labels or is asked whether it is
    missing, and by the dock before each rebuild): when the grid or head file changes, appears or goes (the model
    ran again), it reads them again and refills the time choices, keeping the stored time. A surface without a head
    file of its own uses the model's (the head file its output control names), as the section build does."""

    SOURCE = "mf6"

    # ---- the source's fields
    def _build_source(self, ed: QVBoxLayout) -> None:
        self._grid_path = ""
        self._head_path = ""
        self._found_head = ""                  # the model's head file, while the stored head path is empty
        self._head_named = ""                  # where the model writes its heads (watched for them to appear)
        self._crs_text = ""
        self._info: Optional[ModelInfo] = None
        self._sig: Optional[tuple] = None      # the files as last read (_file_sig)
        self._syncing = False
        box = QWidget(self.editor)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(1)
        self.file_label = ElidedLabel("", parent=box, elide=Qt.TextElideMode.ElideMiddle)
        self.file_note = ElidedLabel("", small=True, parent=box)
        bl.addWidget(self.file_label)
        bl.addWidget(self.file_note)
        box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_change = link_button("Change…", "Choose the model again (its run folder or a file); the variable, "
                                                 "layer, time and CRS are kept")
        self.btn_change.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_change.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        menu = QMenu(self.btn_change)
        self.act_folder = menu.addAction("Run folder…")
        self.act_file = menu.addAction("Model file…")
        self.btn_change.setMenu(menu)
        ed.addWidget(field_box("Model", box, links=[self.btn_change]))
        self.var_seg = SegmentedControl(VAR_CHOICES, self.editor)
        for i, tip in enumerate(VAR_TIPS):
            self.var_seg.setItemToolTip(i, f"{VAR_CHOICES[i][0]}: {tip[:1].lower()}{tip[1:]}")
        self.var_seg.setItemShortText(3, "WT")                 # a narrow panel
        ed.addWidget(field_box("Variable", self.var_seg))
        self.layer_spin = QSpinBox(self.editor)
        self.layer_spin.setRange(1, 999)
        self.layer_spin.setKeyboardTracking(False)
        self.layer_spin.setToolTip("Model layer (1 = top)")
        self.layer_spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.time_combo = QComboBox(self.editor)
        _narrow_combo(self.time_combo, 8)
        self.time_combo.setToolTip("Saved time of the heads (a stress period's last saved step, unless a step is "
                                   "listed)")
        ed.addWidget(pair(field_box("Layer", self.layer_spin), field_box("Time", self.time_combo), (2, 5)))
        self.crs_widget = _crs_widget(self.editor, project_choice=True)
        self._project_crs_words = project_crs_words()
        ed.addWidget(field_box("Model CRS", self.crs_widget))

    def _connect_source(self) -> None:
        self.var_seg.currentIndexChanged.connect(self._on_var_changed)
        self.layer_spin.valueChanged.connect(self._emit)
        self.time_combo.currentIndexChanged.connect(self._emit)
        self.crs_widget.crsChanged.connect(self._on_crs_changed)
        self.act_folder.triggered.connect(lambda: self.change_model(folder=True))
        self.act_file.triggered.connect(lambda: self.change_model(folder=False))
        self.name_edit.setToolTip("Name in the legend (empty: an automatic name)")
        self.units_combo.setToolTip("Elevation units of the model (Auto: its LENGTH_UNITS, else the CRS units, "
                                    "else feet)")

    def _source_value(self) -> dict:
        return dict(source=self.SOURCE, mf6_path=self._grid_path, mf6_head_path=self._head_path,
                    mf6_var=self.var_seg.currentData() or "top", mf6_layer=int(self.layer_spin.value()),
                    mf6_time=self.time_combo.currentData() or "last", mf6_crs=self._crs_text)

    def _set_source_value(self, d: dict) -> None:
        self._layer_id, self._band = d["layer_id"], d["band"]      # kept as stored (not shown)
        self._grid_path, self._head_path, self._crs_text = d["mf6_path"], d["mf6_head_path"], d["mf6_crs"]
        self._load_info()
        self.var_seg.setCurrentIndex(max(0, self.var_seg.findData(d["mf6_var"])))
        self._show_model(d["mf6_layer"], d["mf6_time"])
        self._sync_project_crs()
        self.crs_widget.setCrs(crs_from_text(self._crs_text) if self._crs_text else QgsCoordinateReferenceSystem())
        self._update_source_enabled()

    def _head(self) -> str:
        """The head file the surface uses: its own, else the model's."""
        return self._head_path or self._found_head

    def _file_sig(self) -> tuple:
        return (self._grid_path, _file_stat(self._grid_path), self._head_path, _file_stat(self._head_path),
                self._head_named, _file_stat(self._head_named))

    def _load_info(self) -> None:
        self._found_head = self._head_named = ""
        if not self._grid_path:
            self._info = None
        else:
            if not self._head_path and os.path.isfile(self._grid_path):
                try:                           # the model's own head file, as the build finds it
                    files = mf6.find_model(self._grid_path)
                    self._found_head, self._head_named = files.head_path, files.head_named
                except Exception:
                    pass
            self._info = load_paths(self._grid_path, self._head())
        self._sig = self._file_sig()

    def _show_model(self, layer: int, time: str) -> None:
        """Layer range, time choices and units of the current model (the stored layer and time are kept even when
        the model does not have them: nothing changes until the user picks)."""
        info = self._info
        nlay = info.nlay if info is not None and info.grid is not None else 0
        self.layer_spin.setRange(1, max(nlay, int(layer)) if nlay else max(999, int(layer)))
        self.layer_spin.setValue(int(layer))
        fill_time_combo(self.time_combo, info.heads if info is not None else None, time)
        units = info.grid.length_units if info is not None and info.grid is not None else "unknown"
        self.units_combo.setItemText(0, f"Auto ({units})" if units != "unknown" else "Auto")

    def sync(self) -> bool:
        """Follow the files on disk: when the grid or head file changed, appeared or went since they were read,
        read them again, refill the layer range and time choices (the stored layer and time are kept) and the
        labels. Also shows which CRS an empty model CRS means now. True when the files had changed."""
        self._sync_project_crs()
        if self._syncing or self._file_sig() == self._sig:
            return False
        self._syncing = True
        try:
            layer, time = int(self.layer_spin.value()), self.time_combo.currentData() or "last"
            self._load_info()
            self._applying += 1
            try:
                self._show_model(layer, time)
            finally:
                self._applying -= 1
            self.refresh_labels()
        finally:
            self._syncing = False
        return True

    def _sync_project_crs(self) -> None:
        words = project_crs_words()
        if words != self._project_crs_words:
            self._project_crs_words = words
            self.crs_widget.setNotSetText(words)

    # ---- what SurfaceRow asks of a source
    def layer(self):
        return None

    def _sync_layer_combo(self) -> None:
        pass                                   # no project layer behind a model surface

    def model_info(self) -> Optional[ModelInfo]:
        return self._info

    def problem(self) -> str:
        """Why this surface can't be drawn ("" when it can): missing files first, then what the reader said."""
        var = self.var_seg.currentData()
        if not self._grid_path:
            return "no model file"
        if not os.path.isfile(self._grid_path):
            return "model file missing"
        info = self._info
        if info is not None and info.error:
            return info.error
        if var in ("head", "wt"):
            head = self._head()
            if not head:
                return "no head file"
            if not os.path.isfile(head):
                return "head file missing"
            if info is not None and info.head_error:
                return info.head_error
        return ""

    def is_missing(self) -> bool:
        """The model files (the grid, and the head file for a head or the water table) are missing or unusable."""
        self.sync()
        return bool(self.problem())

    def auto_name(self, d: Optional[dict] = None) -> str:
        """The name the legend gives this surface when it has none of its own (mf6_section.auto_name: "Layer 1 head
        (SP 30)", "Model bottom" of a DISU)."""
        d = d if d is not None else self.value()
        info = self._info
        heads = info.heads if info is not None else None
        kind = info.grid.kind if info is not None and info.grid is not None else ""
        kper = kstp = 0
        if heads is not None and d["mf6_var"] in ("head", "wt"):
            try:
                kper, kstp = heads.resolve(d["mf6_time"])
            except mf6.MF6Error:
                pass
        return auto_name(d["mf6_var"], int(d["mf6_layer"]), kind, heads, kper, kstp)

    # ---- labels
    def refresh_labels(self) -> None:
        self.sync()
        d = self.value()
        info = self._info
        heads = info.heads if info is not None else None
        kind = info.grid.kind if info is not None and info.grid is not None else ""
        problem = self.problem()
        auto = self.auto_name(d)
        self.name_label.setText(d["name"] or auto)
        self.name_label.setWarn(bool(problem))
        parts = [model_stem(self._grid_path) or "no model", what_words(d["mf6_var"], d["mf6_layer"], kind)]
        if problem:
            parts.append(problem)
        else:
            if d["mf6_var"] in ("head", "wt"):
                parts.append(time_words(d["mf6_time"], heads))
            parts.append(d["mode"])
        self.sub_label.setText(" · ".join(parts))
        self.name_edit.setPlaceholderText(auto)
        head = self._head()
        tip = self._grid_path or "No model file"
        if head:
            tip += f"\nHeads: {head}" + ("" if self._head_path else " (the model's)")
        self.name_area.setToolTip(tip + "\n\nShow or hide this surface's settings")
        self.file_label.setText(self._grid_path or "(no model file)")
        self.file_label.setToolTip(tip)
        self.file_label.setWarn(not self._grid_path or not os.path.isfile(self._grid_path))
        if problem:
            note = problem[:1].upper() + problem[1:]
        elif info is not None and info.grid is not None:
            g = info.grid
            note = (f"{KIND_WORDS.get(g.kind, g.kind)} · {g.nlay} layer{'s' if g.nlay != 1 else ''} · "
                    f"{g.length_units if g.length_units != 'unknown' else 'units unknown'}")
            note += f" · heads {os.path.basename(head)}" if heads is not None else " · no head file"
        else:
            note = ""
        self.file_note.setText(note)
        self.file_note.setToolTip(note)
        self.file_note.setWarn(bool(problem))
        self.name_area.setEnabled(True)

    # ---- signals
    def _update_source_enabled(self) -> None:
        var = self.var_seg.currentData()
        self.layer_spin.setEnabled(var in ("botm", "head"))
        self.time_combo.setEnabled(var in ("head", "wt"))

    def _on_var_changed(self, *args) -> None:
        if (not self._applying and self.var_seg.currentData() in ("head", "wt") and not self._head_path
                and self._found_head):
            self._head_path, self._found_head = self._found_head, ""      # the model's head file, now stored
            self._sig = self._file_sig()
        self._update_source_enabled()
        self._emit()

    def _on_crs_changed(self, crs) -> None:
        if self._applying:
            return
        self._crs_text = crs_text(crs)          # "Project CRS (…)" (no CRS): "", the project CRS
        self._emit()

    def change_model(self, folder: bool) -> bool:
        """Change…: pick the model again; the variable, time and CRS are kept, the layer is kept when the model
        has it (else its last layer). In a run folder of several flow models, the one of the same name is kept.
        False when cancelled or the model can't be used (then the row is unchanged and the note says why)."""
        path = pick_model_path(self, folder)
        if not path:
            return False
        prefer = self._info.model_name if self._info is not None else ""
        with wait_cursor():
            info = load_model(path, prefer=prefer if folder else "")
        if not info.ok:
            self.file_note.setText(info.error or "Not a usable MODFLOW 6 model.")
            self.file_note.setToolTip(self.file_note.text())
            self.file_note.setWarn(True)
            return False
        d = self.value()
        self._grid_path = info.grid_path
        self._head_path = info.head_path
        self._load_info()
        layer = min(int(d["mf6_layer"]), info.nlay) if info.nlay else int(d["mf6_layer"])
        self._applying += 1
        try:
            self._show_model(layer, d["mf6_time"])
        finally:
            self._applying -= 1
        self._emit()
        return True
