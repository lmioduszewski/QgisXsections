"""The XSections preview: a matplotlib canvas showing render.figure.draw_preview.

Only the matplotlib Figure API is used (no pyplot). The preview is redrawn when the widget is resized,
because draw_preview lays the plot out for the current figure size (same vertical exaggeration as
the sheet), and it is only drawn while visible. A tiled section also shows which part goes on each
sheet (shaded overlaps, sheet numbers); draw_preview itself draws the match lines.
"""
from __future__ import annotations

import traceback
from typing import List, Optional, Sequence

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

SHEET_LINE = "#8b0000"
SHEET_GID = "xsections-sheet-breaks"
SHEET_PT = 7.0


TOOLBAR_KEEP = ("Home", "Back", "Forward", "Pan", "Zoom")


def _toolbar_items() -> list:
    items = [t for t in NavigationToolbar2QT.toolitems if t[0] in TOOLBAR_KEEP or t[0] is None]
    out = []
    for t in items:                                  # no leading, doubled or trailing separators
        if t[0] is None and (not out or out[-1][0] is None):
            continue
        out.append(t)
    while out and out[-1][0] is None:
        out.pop()
    return out


class PreviewToolbar(NavigationToolbar2QT):
    """Home, back, forward, pan and zoom only. No "Save the figure" (the preview is not to scale:
    files come from Export…) and no subplot or axes editors that would rearrange the preview."""

    toolitems = _toolbar_items()


class PreviewWidget(QWidget):
    """draw(model, settings, plan) or show_message(text)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.figure = Figure(figsize=(8, 3), facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(120)
        self.toolbar = PreviewToolbar(self.canvas, self, coordinates=True)
        self.toolbar.setIconSize(self.toolbar.iconSize() * 0.8)

        self.status = QLabel("")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setStyleSheet("color: palette(mid);")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 4, 0)
        top.addWidget(self.toolbar)
        top.addWidget(self.status, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.canvas, 1)

        self._content = ("message", "Choose a section line and a DEM (and, optionally, an explorations layer).")
        self._pending = True
        self.last_error = ""
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._request)
        self.canvas.mpl_connect("resize_event", lambda _e: self._resize_timer.start())

    # ---- public API
    def draw(self, model, settings, plan) -> None:
        self._content = ("section", model, settings, plan)
        self.status.setText(summary_text(model, settings, plan))
        self._request()

    def show_message(self, text: str) -> None:
        self._content = ("message", text)
        self.status.setText("")
        self._request()

    def clear(self) -> None:
        self.show_message("")

    def render_pending(self) -> None:
        """Draw now even if hidden (used by tests and by showEvent)."""
        self._render()

    def has_section(self) -> bool:
        return self._content[0] == "section"

    # ---- Qt
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending:
            self._render()

    # ---- internals
    def _request(self) -> None:
        if self.isVisible():
            self._render()
        else:
            self._pending = True

    def _render(self) -> None:
        self._pending = False
        self.last_error = ""
        fig = self.figure
        fig.clear()
        if self._content[0] == "message":
            self._draw_message(self._content[1])
        else:
            _, model, settings, plan = self._content
            try:
                from ..render.figure import draw_preview
                draw_preview(fig, model, settings, plan)
                overlay_sheets(fig, plan)
            except Exception as exc:   # never a traceback dialog: log it and say so in the preview
                self.last_error = f"{type(exc).__name__}: {exc}"
                QgsMessageLog.logMessage(traceback.format_exc(), "XSections", Qgis.MessageLevel.Warning)
                fig.clear()
                self._draw_message(f"Preview failed: {self.last_error}\n(details in the XSections log)")
        self.toolbar.update()          # new axes: forget the old zoom/pan history
        self.canvas.draw_idle()

    def _draw_message(self, text: str) -> None:
        if text:
            self.figure.text(0.5, 0.5, text, ha="center", va="center", wrap=True, fontsize=10, color="#555555")


def overlay_sheets(fig: Figure, plan) -> int:
    """When the section is tiled, shade the overlaps and number the sheets along the bottom of the plot.

    draw_preview already draws the match lines; this adds what each sheet covers. Returns the number
    of sheets labelled (0 when there is one sheet).
    """
    pages = list(getattr(plan, "pages", []) or [])
    if len(pages) < 2 or not fig.axes:
        return 0
    ax = main_axes(fig, plan)
    if ax is None or any(a.get_gid() == SHEET_GID for a in ax.get_children()):
        return 0
    trans = ax.get_xaxis_transform()        # x in data (ft), y in axes fraction
    n = len(pages)
    x0, x1 = ax.get_xlim()
    pt_per_ft = ax.get_position().width * fig.get_size_inches()[0] * 72.0 / max(abs(x1 - x0), 1e-9)
    spans = [(p.match_left if p.match_left is not None else p.x_min,
              p.match_right if p.match_right is not None else p.x_max) for p in pages]
    tags = sheet_tags(n, [(right - left) * pt_per_ft for left, right in spans])
    for i, ((left, right), text) in enumerate(zip(spans, tags)):
        page = pages[i]
        ax.text((left + right) / 2.0, 0.02, text, transform=trans, ha="center", va="bottom",
                fontsize=SHEET_PT, fontweight="bold", color=SHEET_LINE, alpha=0.8, gid=SHEET_GID, clip_on=True,
                bbox=dict(fc="white", ec="none", pad=1.0, alpha=0.8), zorder=9)
        if i + 1 < n and pages[i + 1].x_min < page.x_max:
            ax.axvspan(pages[i + 1].x_min, page.x_max, color=SHEET_LINE, alpha=0.07, lw=0, gid=SHEET_GID,
                       zorder=0.4)
    return n


def sheet_tags(n: int, rooms_pt: Sequence[float]) -> List[str]:
    """Sheet numbers that fit the width each sheet covers in the preview (points).

    One style for all sheets ("SHEET 2 OF 5", "SHEET 2", "2/5" or "2": the longest that fits most
    sheets), shortened further only on a sheet that is narrower still, such as a short last sheet.
    """
    from ..render.figure import text_width_pt

    def options(i):
        return [f"SHEET {i} OF {n}", f"SHEET {i}", f"{i}/{n}", f"{i}"]

    best = []
    for i, room in enumerate(rooms_pt, 1):
        fits = [k for k, t in enumerate(options(i)) if text_width_pt(t, SHEET_PT, "bold") + 6.0 <= room]
        best.append(fits[0] if fits else 3)            # + 6 pt for the white box and a gap
    style = sorted(best)[(len(best) - 1) // 2]        # the lower median
    return [options(i)[max(style, b)] for i, b in enumerate(best, 1)]


def main_axes(fig: Figure, plan=None):
    """The section axes: the largest visible axes (preferring one whose y-limits match the plan)."""
    best, best_key = None, None
    for ax in fig.axes:
        if not ax.get_visible():
            continue
        pos = ax.get_position()
        area = pos.width * pos.height
        y0, y1 = ax.get_ylim()
        matches = plan is not None and abs(min(y0, y1) - plan.z_min) < 1e-6 and abs(max(y0, y1) - plan.z_max) < 1e-6
        key = (1 if matches else 0, area)
        if best_key is None or key > best_key:
            best, best_key = ax, key
    return best


def summary_text(model, settings, plan) -> str:
    if getattr(model, "has_explorations", True):
        first = f"{len(model.hits)} exploration{'s' if len(model.hits) != 1 else ''}"
    else:
        first = "ground line only"
    parts = [first,
             f"{model.length:,.0f} ft",
             f"VE {settings.vertical_exaggeration:g}×"]
    pages = getattr(plan, "pages", []) or []
    if len(pages) > 1:
        parts.append(f"{len(pages)} sheets")
    if not getattr(plan, "fits", True):
        parts.append("does not fit the sheet")
    return " · ".join(parts)
