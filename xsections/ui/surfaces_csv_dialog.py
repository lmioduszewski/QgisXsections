"""The preview's Surfaces CSV… dialog, "Export surfaces to CSV": tick the lines (the ground and each other surface),
choose one row per drawn point or one column per surface (every N ft), and whether to add map coordinates; a live
preview shows the start of the file and its size.

The dialog writes nothing: options() is what core.surfaces_csv.write_surfaces_csv takes (the dock asks for the
file name and writes it). The layout, the step and the map coordinates choice are remembered for next time (user
settings, when Save CSV… is pressed); every line starts ticked.
"""
from __future__ import annotations

import csv
import html
import io
from itertools import groupby
from typing import List, Optional, Sequence, Tuple

from qgis.core import QgsCoordinateReferenceSystem
from qgis.PyQt.QtCore import QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QScrollArea,
                                 QSizePolicy, QSpinBox, QTextEdit, QVBoxLayout, QWidget)

from ..core.hover import hover_lines
from ..core.surfaces_csv import surface_rows_long, surface_rows_wide, unique_names
from ..render.figure import SURFACE_DASHES
from . import settings_store
from .widgets import CONTROL_H, SegmentedControl, field_box, panel_stylesheet, theme_for

LAYOUT_KEY = "surfaces_csv_layout"       # user settings: "long" | "wide"
STEP_KEY = "surfaces_csv_step"           # whole feet, STEP_MIN to STEP_MAX
MAP_XY_KEY = "surfaces_csv_map_xy"       # "1" | "0"
STEP_MIN, STEP_MAX, STEP_DEFAULT = 1, 500, 10
LAYOUTS = [("One row per point, as drawn", "long"), ("One column per surface", "wide")]
LAYOUT_TIPS = ["Every point of every line exactly as drawn, one line after the other",
               "One row per distance, one column of elevations per line (easy to chart in Excel)"]
HELP = {
    "long": "Exactly the points drawn: the ground at every DEM sample, model surfaces at each cell, so the surfaces "
            "have different distances. A surface drawn flat across cells steps at each cell edge (two rows at the "
            "same distance). “part” counts again after a no-data gap.",
    "wide": "Column labels in the top row, distances (x) in the first column, then one column of elevations (y) "
            "per surface, all read at the same distances (every {step} ft and at each bend). Easy to chart in "
            "Excel; cell steps and corners between rows are smoothed over.",
}
NO_LINES = "(no surfaces ticked)"
LONG_GAP_NOTE = "← no data: blank elevation"
WIDE_GAP_NOTE = "← no data: blank"
LONG_HEAD_ROWS = 3                       # rows shown at the start of each line (long)
WIDE_ALL_ROWS = 7                        # a wide file up to this long is shown whole
WIDE_HEAD_ROWS = 4
SWATCH = QSize(26, 12)                   # px, a line swatch on its white chip
PAPER = QColor("#ffffff")
PAPER_EDGE = QColor("#c9d1d6")

# a preview line: (text, muted, note): a line of the file (muted False; `note` muted after it, may be "") or a
# muted line of the preview itself ("…", "… 1,532 more Ground rows")
PreviewLine = Tuple[str, bool, str]


# ---------------------------------------------------------------- the preview (pure; also used by tests)
def csv_line(row: Sequence) -> str:
    """One row as csv.writer writes it into the file (a name with a comma or a quote is quoted), no line end."""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(row)
    return buf.getvalue()


def file_size(header: Sequence, rows: Sequence[Sequence]) -> int:
    """Bytes of the file write_surfaces_csv writes for `header` and `rows` (UTF-8 with a byte order mark, CRLF)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return len("﻿".encode("utf-8")) + len(buf.getvalue().encode("utf-8"))


def preview_lines(layout: str, header: Sequence, rows: Sequence[Sequence], n_lines: int) -> List[PreviewLine]:
    """What the preview shows of a file with `n_lines` ticked lines: the header, then
    - long: per line its first 3 rows, its first row without data (if further down, marked), and "… N more <line>
      rows";
    - wide: the whole file up to 7 rows; else the first 4 rows, the first row with a blank (if further down,
      marked), "… N more rows in all" and the last row."""
    out: List[PreviewLine] = [(csv_line(header), False, "")]
    if n_lines <= 0:
        out.append((NO_LINES, True, ""))
        return out
    if layout == "long":
        for name, group in groupby(rows, key=lambda r: r[0]):
            g = list(group)
            out += [(csv_line(r), False, "") for r in g[:LONG_HEAD_ROWS]]
            shown = min(LONG_HEAD_ROWS, len(g))
            gap = next((k for k, r in enumerate(g) if r[3] == ""), -1)
            if gap >= LONG_HEAD_ROWS:
                out += [("…", True, ""), (csv_line(g[gap]), False, LONG_GAP_NOTE)]
                shown += 1
            if len(g) > shown:
                out.append((f"… {len(g) - shown:,} more {name} rows", True, ""))
        return out
    g = list(rows)
    gap = next((k for k, r in enumerate(g) if any(v == "" for v in r[1:1 + n_lines])), -1)
    if len(g) <= WIDE_ALL_ROWS:
        pick = list(range(len(g)))
    else:
        pick = list(range(WIDE_HEAD_ROWS))
        if WIDE_HEAD_ROWS - 1 < gap < len(g) - 1:
            pick += [-1, gap]
        pick += [-2, len(g) - 1]
    hidden = len(g) - sum(1 for k in pick if k >= 0)
    for k in pick:
        if k == -1:
            out.append(("…", True, ""))
        elif k == -2:
            out.append((f"… {hidden:,} more rows in all", True, ""))
        else:
            out.append((csv_line(g[k]), False, WIDE_GAP_NOTE if k == gap else ""))
    return out


def preview_plain(lines: Sequence[PreviewLine]) -> str:
    """The preview as plain text (a note two spaces after its row)."""
    return "\n".join(text + (f"  {note}" if note else "") for text, _muted, note in lines)


def preview_html(lines: Sequence[PreviewLine], muted_color: str) -> str:
    """The preview as rich text: the file's lines as they are, the preview's own lines and notes muted, italic."""
    def muted(text: str) -> str:
        return f'<span style="color:{muted_color}; font-style:italic">{html.escape(text)}</span>'
    body = []
    for text, is_muted, note in lines:
        if is_muted:
            body.append(muted(text))
        else:
            body.append(html.escape(text) + (f"  {muted(note)}" if note else ""))
    return '<div style="white-space:pre">' + "\n".join(body) + "</div>"     # (<pre> would force Courier)


def summary_text(layout: str, n_rows: int, size: int, step_ft: float, n_lines: int) -> str:
    """ "1,713 rows · about 52 KB", "155 rows (every 10 ft) · about 10 KB"; "Tick at least one surface"."""
    if n_lines <= 0:
        return "Tick at least one surface"
    every = f" (every {step_ft:g} ft)" if layout == "wide" else ""
    kb = max(1, int(size / 1024.0 + 0.5))
    return f"{n_rows:,} row{'' if n_rows == 1 else 's'}{every} · about {kb:,} KB"


def swatch_pixmap(color: str, style: str, width_pt: float, dpr: float = 1.0) -> QPixmap:
    """A line as the preview draws it (colour, width, dash) on a small white chip, so the sheet's ink colours show
    in a dark QGIS theme too."""
    w, h = SWATCH.width(), SWATCH.height()
    pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(PAPER_EDGE, 1.0))
    p.setBrush(PAPER)
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 2.0, 2.0)
    pen = QPen(QColor(color), min(4.0, max(1.3, float(width_pt) * 96.0 / 72.0)))
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    dashes = SURFACE_DASHES.get(style)
    if isinstance(dashes, tuple):              # (offset, (on, off)) in line widths: Qt counts in pen widths too
        pen.setDashPattern([float(v) for v in dashes[1]])
    p.setPen(pen)
    p.drawLine(QPointF(4.0, h / 2.0), QPointF(w - 4.0, h / 2.0))
    p.end()
    return pm


def remembered() -> Tuple[str, int, bool]:
    """(layout, step ft, map coordinates) as last saved; the defaults (long, 10 ft, off) for anything unreadable."""
    layout = settings_store.user_value(LAYOUT_KEY, "long")
    if layout not in ("long", "wide"):
        layout = "long"
    try:
        step = int(round(float(settings_store.user_value(STEP_KEY, str(STEP_DEFAULT)))))
    except (TypeError, ValueError, OverflowError):
        step = STEP_DEFAULT
    if not STEP_MIN <= step <= STEP_MAX:
        step = STEP_DEFAULT
    return layout, step, settings_store.user_value(MAP_XY_KEY, "0") == "1"


# ---------------------------------------------------------------- the dialog
class SurfacesCsvDialog(QDialog):
    """Surfaces CSV…: which lines, which layout, map coordinates or not; options() for write_surfaces_csv."""

    MAX_LIST_ROWS = 6                    # longer lists of lines scroll
    PREVIEW_LINES = 11

    def __init__(self, model, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSurfacesCsvDialog")
        self.setWindowTitle("Export surfaces to CSV")
        self.model = model
        self.lines = hover_lines(model)
        self.names = unique_names(ln.name for ln in self.lines)
        self._plain = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # the lines
        self.boxes: List[QCheckBox] = []
        inner = QWidget()
        inner.setObjectName("xsCsvLines")
        il = QVBoxLayout(inner)
        il.setContentsMargins(8, 5, 8, 5)
        il.setSpacing(3)
        dpr = self.devicePixelRatioF()
        rows = []
        for ln, name in zip(self.lines, self.names):
            box = QCheckBox(name)
            box.setChecked(True)
            box.setIcon(QIcon(swatch_pixmap(ln.color, ln.style, ln.width, dpr)))
            box.setIconSize(SWATCH)
            box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            n = int(ln.stations.size)
            count = QLabel(f"{n:,} point{'' if n == 1 else 's'}")
            count.setObjectName("xsMuted")
            count.setToolTip("Points drawn (a cell step counts twice)")
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            rl.addWidget(box, 1)
            rl.addWidget(count, 0)
            il.addWidget(row)
            rows.append(row)
            self.boxes.append(box)
        self.list_area = QScrollArea()
        self.list_area.setObjectName("xsSurfaceList")
        self.list_area.setWidget(inner)
        self.list_area.setWidgetResizable(True)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_area.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        shown = max(1, min(len(rows), self.MAX_LIST_ROWS))
        row_h = max(r.sizeHint().height() for r in rows) if rows else CONTROL_H
        self.list_area.setFixedHeight(shown * row_h + (shown - 1) * il.spacing() + 10 + 2 * self.list_area.frameWidth())
        self.list_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay.addWidget(field_box("Surfaces", self.list_area))

        # the rows
        self.layout_seg = SegmentedControl(LAYOUTS)
        for i, tip in enumerate(LAYOUT_TIPS):
            self.layout_seg.setItemToolTip(i, tip)
        lay.addWidget(field_box("Rows", self.layout_seg))
        self.step = QSpinBox()
        self.step.setRange(STEP_MIN, STEP_MAX)
        self.step.setValue(STEP_DEFAULT)
        self.step.setAccelerated(True)
        self.step.setFixedHeight(CONTROL_H)
        self.step.setMinimumWidth(64)
        self.step.setToolTip("Distance between the rows, ft (each bend and the end get a row too)")
        self.step_row = QWidget()
        sl = QHBoxLayout(self.step_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        every = QLabel("Every")
        every.setBuddy(self.step)
        sl.addWidget(every)
        sl.addWidget(self.step)
        sl.addWidget(QLabel("ft along the section"))
        sl.addSpacing(8)
        limits = QLabel(f"{STEP_MIN} to {STEP_MAX} ft")
        limits.setObjectName("xsMuted")
        sl.addWidget(limits)
        sl.addStretch(1)
        lay.addWidget(self.step_row)
        self.help = QLabel("")
        self.help.setObjectName("xsMuted")
        self.help.setWordWrap(True)
        self.help.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.help)

        # the columns
        columns = QWidget()
        cl = QVBoxLayout(columns)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        xy = QLabel("x = distance along the section, y = elevation, in feet")
        xy.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        cl.addWidget(xy)
        self.map_xy = QCheckBox("Also map coordinates (map_x, map_y)")
        self.map_xy.setToolTip(self._map_xy_tip())
        self.map_xy.setEnabled(bool(getattr(model, "line_wkt", "")))
        cl.addWidget(self.map_xy)
        lay.addWidget(field_box("Columns", columns))

        # the preview
        self.preview = QTextEdit()
        self.preview.setObjectName("xsCsvPreview")
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setFamilies(["Consolas", font.family()])          # (Windows' fixed font is Courier New)
        if font.pointSizeF() > 0:
            font.setPointSizeF(max(7.0, self.font().pointSizeF() * 0.92))
        self.preview.setFont(font)
        doc_margin = self.preview.document().documentMargin()
        self.preview.setFixedHeight(round(self.preview.fontMetrics().lineSpacing() * self.PREVIEW_LINES
                                          + 2 * doc_margin + 2 * self.preview.frameWidth()))
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay.addWidget(field_box("Preview", self.preview))

        # the foot: size, Cancel, Save CSV…
        self.summary = QLabel("")
        self.summary.setObjectName("xsMuted")
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.buttons.addButton("Save CSV…", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setObjectName("xsPrimary")
        self.save_button.setMinimumHeight(CONTROL_H + 2)
        self.save_button.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        foot.setSpacing(8)
        foot.addWidget(self.summary, 1)
        foot.addWidget(self.buttons, 0)
        lay.addStretch(1)
        lay.addLayout(foot)

        layout, step, map_xy = remembered()
        self.layout_seg.setCurrentIndex(max(0, self.layout_seg.findData(layout)))
        self.step.setValue(step)
        self.map_xy.setChecked(map_xy and self.map_xy.isEnabled())
        for box in self.boxes:
            box.toggled.connect(self.refresh)
        self.layout_seg.currentIndexChanged.connect(self.refresh)
        self.step.valueChanged.connect(self.refresh)
        self.map_xy.toggled.connect(self.refresh)
        self.setStyleSheet(panel_stylesheet(theme_for(self.palette())) + self._own_style())
        self.setMinimumWidth(420)
        self.refresh()
        width = 600
        self.resize(width, lay.heightForWidth(width) if lay.hasHeightForWidth() else self.sizeHint().height())

    # ---- choices
    def csv_layout(self) -> str:
        return self.layout_seg.currentData() or "long"

    def include(self) -> List[int]:
        """Indices (into hover_lines(model)) of the ticked lines."""
        return [i for i, box in enumerate(self.boxes) if box.isChecked()]

    def options(self) -> dict:
        """The keyword arguments of core.surfaces_csv.write_surfaces_csv (besides the path and the model)."""
        return dict(layout=self.csv_layout(), step_ft=float(self.step.value()), include=self.include(),
                    map_xy=self.map_xy.isChecked())

    def preview_text(self) -> str:
        """The preview as plain text (for tests)."""
        return self._plain

    # ---- the preview
    def rows(self) -> Tuple[List[str], List[list]]:
        """(header, rows) of the file as the choices stand."""
        o = self.options()
        if o["layout"] == "wide":
            return surface_rows_wide(self.model, o["step_ft"], o["include"], o["map_xy"])
        return surface_rows_long(self.model, o["include"], o["map_xy"])

    def refresh(self, *args) -> None:
        """Bring the step row, the help, the preview, the size and Save CSV… up to date with the choices."""
        layout = self.csv_layout()
        n = len(self.include())
        header, rows = self.rows()
        lines = preview_lines(layout, header, rows, n)
        self._plain = preview_plain(lines)
        self.preview.setHtml(preview_html(lines, theme_for(self.palette()).muted.name()))
        self.step_row.setVisible(layout == "wide")
        self.help.setText(HELP[layout].format(step=self.step.value()))
        self.summary.setText(summary_text(layout, len(rows), file_size(header, rows), self.step.value(), n))
        self.save_button.setEnabled(n > 0)
        self.save_button.setToolTip("" if n else "Tick at least one surface")

    # ---- remembering
    def accept(self) -> None:
        """Save CSV…: remember the layout, the step and the map coordinates choice, then close."""
        if not self.include():
            return
        settings_store.set_user_value(LAYOUT_KEY, self.csv_layout())
        settings_store.set_user_value(STEP_KEY, str(self.step.value()))
        settings_store.set_user_value(MAP_XY_KEY, "1" if self.map_xy.isChecked() else "0")
        super().accept()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.boxes:
            self.boxes[0].setFocus()

    # ---- building blocks
    def _map_xy_tip(self) -> str:
        if not getattr(self.model, "line_wkt", ""):
            return "No section line to read map coordinates from"
        crs = QgsCoordinateReferenceSystem.fromWkt(getattr(self.model, "section_crs_wkt", "") or "")
        where = f" ({crs.userFriendlyIdentifier()})" if crs.isValid() else ""
        return f"Map x, y of each distance in the section's CRS{where}, to 3 decimals"

    def _own_style(self) -> str:
        t = theme_for(self.palette())
        return (f"QWidget#xsCsvLines {{ background: transparent; }}"
                f"QTextEdit#xsCsvPreview {{ background: {t.field.name()}; color: {t.ink.name()};"
                f" border: 1px solid {t.field_line.name()}; border-radius: 3px; }}")
