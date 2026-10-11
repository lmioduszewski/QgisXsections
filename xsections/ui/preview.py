"""The XSections preview: a matplotlib canvas showing render.figure.draw_preview, with zoom and a hover readout.

Only the matplotlib Figure API is used (no pyplot). draw_preview lays the whole section out for the panel at the
export's vertical exaggeration; that is 100 %. It is laid out again when the panel changes size, and only drawn while
visible. A tiled section also shows which part goes on each sheet (shaded overlaps, sheet numbers); draw_preview
itself draws the match lines.

Zoom magnifies the whole drawing, frame, ticks, labels and all, like a magnifier: the canvas sits in a scroll area
and grows z times while the figure dpi grows with it, so the figure keeps its size in inches and its layout, and
each step is drawn sharp at the new dpi. The wheel zooms around the mouse; the buttons and + - 0 step through
100-800 % (less on a high-resolution screen or a wide panel, by a pixel budget); drag, Shift+wheel or a sideways
wheel pans; a double-click fits. A new section line starts at Fit; a refresh of the same line keeps the zoom, and a
new layout (a refresh, a new panel size) keeps the spot at the middle of the view there.

Hover: the strip of tiles above the plot (ui/readout.py) reads out the station under the mouse, every line's value
there and its depth (core/hover.py: the rule the lines are drawn by), or an exploration's or an other point's (a
seep's) details when the mouse points at it (one index for both, core.hover.hover_targets: the explorations, then
the other points; several at the same spot: the nearest is named, "+N here" says how many more, and the popup
lists them); the popup next to the cursor (ui/popup.py) shows the same in a small card. The strip is compact (0.3.4):
one row of small equal tiles down to a 700 px dock, the first reading where the cursor is ("760 ft from A", its
elevation and depth, or the map cursor's offset), names and details cut with "…" where they do not fit, numbers never
(the popup shows everything whole). Two toolbar toggles turn them on and off ("Readout row", "Popup"; both on the
first time, both remembered); the hover (the guide, a dot on each line, axis tags, the map marker and the map's guide
here) works while either is on. The marks are blitted over the plot (animated artists in display pixels, sized to
stay the same on screen at any zoom, never part of the drawing), and a move repaints only where they were and are
(PreviewCanvas.repaint_rects). The dock moves the map marker from hoverChanged and hoverLeft, and shows the map
cursor's place here with show_guide / hide_guide.

Full screen (0.3.7, the toolbar's last toggle): the preview's dock floats and fills the screen it is on, and the
section fits; the button again, or Esc, puts the dock back where it was (docked in its area at its size, or floating
at its place) and fits again. Closed or hidden while full screen, the dock is put back as well, and shows there next
time. F11 stays QGIS's; Esc is the preview's only while it is full screen. Nothing is remembered (a view state).
"""
from __future__ import annotations

import math
import traceback
from typing import List, NamedTuple, Optional, Sequence, Tuple

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.transforms import Bbox, IdentityTransform
from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import (QAction, QColor, QFont, QFontMetricsF, QGuiApplication, QIcon, QImage, QKeySequence,
                             QPainter, QPainterPath, QPalette, QPen, QPixmap, QRegion, QResizeEvent)
from qgis.PyQt.QtWidgets import (QApplication, QDockWidget, QFrame, QHBoxLayout, QLabel, QMainWindow, QScrollArea,
                                 QSizePolicy, QToolBar, QVBoxLayout, QWidget)

from ..core.hover import distance_text, elev_text, hover_lines, hover_target, hover_values, strip_cells
from ..render.scales import tick_base
from . import settings_store
from .popup import HoverPopup
from .readout import IDLE_TEXT, NAVY, HoverReadout, past_text
from .widgets import theme_for, wrap_tip

SHEET_LINE = "#8b0000"
SHEET_GID = "xsections-sheet-breaks"
SHEET_PT = 7.0

# ---- zoom
BASE_DPI = 100.0                    # figure dpi at 100 %, per logical pixel (the canvas multiplies it by the screen's)
ZOOM_LADDER = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)   # the buttons' and keys' steps
ZOOM_MAX, ZOOM_FLOOR = 8.0, 2.0     # the highest zoom, and the least a pixel budget may lower it to
PIXEL_BUDGET = 40e6                 # canvas pixels (physical) at the highest zoom: memory and draw time grow with them
WHEEL_STEP = 1.2                    # zoom factor per wheel notch
WHEEL_MS = 15                       # wheel events this close together make one zoom step (each step is a full draw)
WHEEL_PAN_PX = 60.0                 # Shift+wheel / sideways wheel: px per notch (as a scroll bar steps)
RELAYOUT_MS = 150

# ---- the hover's two toggles: settings_store user values, "1" on (also the first time), "0" off. (0.3.1's single
# "hover_readout" value is not read: both start on.)
STRIP_KEY = "hover_strip"           # the readout row above the plot
POPUP_KEY = "hover_popup"           # the popup next to the cursor
# ---- hover marks: sizes in points at 100 %, divided by the zoom so they keep their size on screen
GUIDE_LW, CURSOR_LW = 1.1, 0.7
DOT_MS, DOT_NEAR_MS, DOT_EDGE_LW = 6.0, 7.5, 1.1
# the tags (logical px): painted by Qt over the canvas in the application's font, semibold white on navy (0.3.2: as
# matplotlib text each cost ~1.5 ms a hover, its glyphs drawn one by one)
TAG_PX, TAG_PAD_X, TAG_PAD_Y, TAG_RADIUS = 11.0, 4.0, 1.5, 2.0
TAG_GAP_PX, TAG_MARGIN_PX, EDGE_TAG_PX = 3.0, 3.0, 6.0
BAND_HALF_PX = 7.0                  # the band over a pointed-at exploration, px either side of its line
# a hover repaints only where the marks and tags were and are now: each one's box and this much around it (logical
# px: line widths, the dots' white edge, antialiasing; a whole-view repaint cost ~20 ms a move at 250 %)
DIRTY_PAD_PX = 3.0
ABOVE_FRAME_PX = 4.0                # the hover reaches this far above the frame
# pointing at an exploration: within HIT_DX_PX of its line on screen, and from HIT_BELOW_IN below its bottom to
# HIT_ABOVE_IN above its top or tick (paper inches: the tick and the label magnify with the zoom). An other point:
# within HIT_DX_PX of its symbol's sides, from HIT_BELOW_IN below its symbol to POINT_ABOVE_IN above its label.
HIT_DX_PX, HIT_BELOW_IN, HIT_ABOVE_IN = 6.0, 0.14, 0.62
POINT_ABOVE_IN = 0.05
SAME_SPOT_PX = 1.0                  # targets this close (in |x - its centre|, px) to the nearest are "here" too
FULL_TIP = "Full screen: the section fills the screen; click again or press Esc to put it back"


def zoom_limit(vw: float, vh: float, dpr: float = 1.0) -> float:
    """The highest zoom for a viewport of vw x vh logical px on a screen of this device pixel ratio: 800 %, less
    where the canvas would pass PIXEL_BUDGET (a high-resolution screen, a wide panel), never under 200 %."""
    px = max(1.0, float(vw) * float(vh) * float(dpr or 1.0) ** 2)
    return min(max(math.sqrt(PIXEL_BUDGET / px), ZOOM_FLOOR), ZOOM_MAX)


def zoom_step(z: float, direction: int, z_max: float = ZOOM_MAX) -> float:
    """The next zoom up (direction > 0) or down the ladder from z, within 1 .. z_max."""
    if direction > 0:
        nxt = next((v for v in ZOOM_LADDER if v > z + 1e-3), ZOOM_MAX)
    else:
        nxt = next((v for v in reversed(ZOOM_LADDER) if v < z - 1e-3), 1.0)
    return min(max(nxt, 1.0), z_max)


def _drawn_icon(color: QColor, draw, icon: Optional[QIcon] = None, state=QIcon.State.Off) -> QIcon:
    """An icon drawn on a 20-unit grid by `draw(painter, k)` (k px per unit) at the toolbar's sizes, in `color` (the
    theme's text colour: QGIS's dark themes leave the button text colour to the system); added to `icon` for `state`
    (a checked toggle's own picture) when given."""
    icon = QIcon() if icon is None else icon
    for size in (16, 20, 24, 32, 48):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        k = size / 20.0
        pen = QPen(color, 1.4 * k)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        draw(p, k)
        p.end()
        icon.addPixmap(pm, QIcon.Mode.Normal, state)
    return icon


def strip_icon(color: QColor) -> QIcon:
    """The "Readout row" toggle: a row of three cells."""
    def draw(p, k):
        p.drawRoundedRect(QRectF(2.0 * k, 5.5 * k, 16.0 * k, 9.0 * k), 1.5 * k, 1.5 * k)
        for x in (7.33, 12.67):
            p.drawLine(QPointF(x * k, 5.5 * k), QPointF(x * k, 14.5 * k))
    return _drawn_icon(color, draw)


def popup_icon(color: QColor) -> QIcon:
    """The "Popup" toggle: a speech bubble with two lines of text."""
    def draw(p, k):
        path = QPainterPath(QPointF(3.5 * k, 3.5 * k))
        path.lineTo(16.5 * k, 3.5 * k)
        path.quadTo(17.5 * k, 3.5 * k, 17.5 * k, 4.5 * k)
        path.lineTo(17.5 * k, 12.5 * k)
        path.quadTo(17.5 * k, 13.5 * k, 16.5 * k, 13.5 * k)
        path.lineTo(9.0 * k, 13.5 * k)
        path.lineTo(5.5 * k, 16.5 * k)
        path.lineTo(5.5 * k, 13.5 * k)
        path.lineTo(3.5 * k, 13.5 * k)
        path.quadTo(2.5 * k, 13.5 * k, 2.5 * k, 12.5 * k)
        path.lineTo(2.5 * k, 4.5 * k)
        path.quadTo(2.5 * k, 3.5 * k, 3.5 * k, 3.5 * k)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(6.0 * k, 7.0 * k), QPointF(14.0 * k, 7.0 * k))
        p.drawLine(QPointF(6.0 * k, 10.0 * k), QPointF(11.0 * k, 10.0 * k))
    return _drawn_icon(color, draw)


def full_screen_icon(color: QColor) -> QIcon:
    """The "Full screen" toggle (QGIS has no icon for it): a corner at each corner of a square, pointing out; checked
    (full screen), the corners point in (put it back)."""
    def corners(inward: bool):
        def draw(p, k):
            for x, y, dx, dy in ((3.0, 3.0, 1, 1), (17.0, 3.0, -1, 1), (3.0, 17.0, 1, -1), (17.0, 17.0, -1, -1)):
                if inward:                        # the corner 5 units in, its arms out to the square's sides
                    x, y, dx, dy = x + 5.0 * dx, y + 5.0 * dy, -dx, -dy
                path = QPainterPath(QPointF(x * k, (y + 5.0 * dy) * k))
                path.lineTo(x * k, y * k)
                path.lineTo((x + 5.0 * dx) * k, y * k)
                p.drawPath(path)
        return draw
    return _drawn_icon(color, corners(True), _drawn_icon(color, corners(False)), QIcon.State.On)


class _DockPlace(NamedTuple):
    """Where the preview's dock was before it went full screen: in `window` (the main window), floating, or docked in
    `area` at `size` px across it (a bottom dock's height, a side dock's width); its floating geometry and window
    state (a docked one's: where Qt floats it next)."""
    dock: QDockWidget
    window: QMainWindow
    floating: bool
    area: Qt.DockWidgetArea
    size: int
    geometry: QRect
    state: Qt.WindowState


def _ancestor(w: Optional[QWidget], kind) -> Optional[QWidget]:
    """The nearest parent of `w` that is a `kind`, or None."""
    p = w.parentWidget() if w is not None else None
    while p is not None and not isinstance(p, kind):
        p = p.parentWidget()
    return p


def _padded(b: Bbox, pad: float, win: Optional[Bbox] = None) -> Optional[tuple]:
    """Box `b` (display px) grown by `pad` on every side and cut to `win`: (x0, y0, x1, y1), None when nothing of it
    is in `win`; the whole of `win` for a box that is not a number."""
    x0, y0, x1, y1 = b.x0 - pad, b.y0 - pad, b.x1 + pad, b.y1 + pad
    if win is None:
        return x0, y0, x1, y1
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        return tuple(win.extents)
    x0, y0, x1, y1 = max(x0, win.x0), max(y0, win.y0), min(x1, win.x1), min(y1, win.y1)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _zoom_key(event) -> Optional[int]:
    """+1 for + or =, -1 for - or _, 0 for 0 (no Ctrl, Alt or Meta), else None."""
    mods = event.modifiers()
    if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
               | Qt.KeyboardModifier.MetaModifier):
        return None
    key = event.key()
    if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
        return 1
    if key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
        return -1
    if key == Qt.Key.Key_0:
        return 0
    return None


class PreviewCanvas(FigureCanvasQTAgg):
    """The preview's canvas. The wheel zooms (or pans, with Shift or sideways), a drag pans when zoomed in, a
    double-click fits, + - 0 zoom, Esc leaves full screen; PreviewWidget does the work. Every other mouse event goes
    on to matplotlib."""

    def __init__(self, figure: Figure, view: "PreviewWidget"):
        super().__init__(figure)
        self._view = view
        self._dirty: Optional[List[QRect]] = None     # the parts repaint_rects asked for (the next paint only)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def repaint_rects(self, rects: Sequence[QRect]) -> None:
        """Repaint only `rects` (logical px) now: paintEvent copies just these parts of the plot to the screen."""
        rects = [q for q in rects if not q.isEmpty()]
        if not rects:
            return
        region = QRegion()
        for q in rects:
            region = region.united(q)
        self._dirty = rects
        try:
            self.repaint(region)
        finally:
            self._dirty = None

    def _update_pixel_ratio(self) -> None:
        # matplotlib calls this on every show and when the window moves to a screen of another ratio (the logical
        # size stays, so no Resize comes): the zoom's pixel budget is then worked out again
        before = self.device_pixel_ratio
        super()._update_pixel_ratio()
        view = getattr(self, "_view", None)
        if view is not None and self.device_pixel_ratio != before:
            view._ratio_changed()

    def wheelEvent(self, event) -> None:          # never matplotlib's scroll_event (it misreads touchpads)
        self._view._wheel(event)
        event.accept()                             # nothing reaches the scroll area or the dock

    def mousePressEvent(self, event) -> None:
        if self._view._drag_start(event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._view._drag_move(event):
            event.accept()
            return
        super().mouseMoveEvent(event)
        self._view._mouse_moved(event.position())

    def mouseReleaseEvent(self, event) -> None:
        if self._view._drag_end(event):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._view.fit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._view._mouse_left()

    def paintEvent(self, event) -> None:
        """The plot (the Agg buffer, the blitted marks in it), then the hover's tags over it. As matplotlib's, but
        a hover's repaint (repaint_rects) copies only its parts (thin strips where the guide, the cursor line, the
        dots and the tags were and are), not the region's bounding box, which is the whole view as soon as the
        guide runs down it and the cursor line across it; and every part lands on whole device pixels (at a
        fractional ratio, 250 %, a part placed by logical px would sit half a pixel off the rest)."""
        self._draw_idle()                          # (a full draw, if one is due)
        if not hasattr(self, "renderer"):
            return
        region = event.region()
        hint, self._dirty = self._dirty, None
        if hint:
            parts, mine = [], QRegion()
            for q in hint:
                part = region.intersected(q).boundingRect()
                if not part.isEmpty():
                    parts.append(part)
                mine = mine.united(q)
            rest = region.subtracted(mine)         # what Qt adds to it (an expose, the popup's old place)
            if not rest.isEmpty():
                parts.append(rest.boundingRect())
        else:
            parts = [region.boundingRect()]
        painter = QPainter(self)
        try:
            self._copy_buffer(painter, parts)
            self._draw_rect_callback(painter)
        finally:
            painter.end()
        view = getattr(self, "_view", None)
        if view is not None:
            view._paint_tags(self)                 # the hover's tags over it

    def _copy_buffer(self, painter: QPainter, rects: Sequence[QRect]) -> None:
        """Copy each rect (logical px, widened to whole device pixels) of the Agg buffer to the widget."""
        r = self.device_pixel_ratio
        ren = self.get_renderer()
        W, H = int(ren.width), int(ren.height)
        painter.save()
        painter.scale(1.0 / r, 1.0 / r)            # device px: buffer pixel (x, y) goes to (x, y)
        try:
            for q in rects:
                x0, y0 = max(0, math.floor(q.x() * r)), max(0, math.floor(q.y() * r))
                x1 = min(W, math.ceil((q.x() + q.width()) * r))
                y1 = min(H, math.ceil((q.y() + q.height()) * r))
                if x1 <= x0 or y1 <= y0:
                    continue
                buf = memoryview(ren.copy_from_bbox(Bbox.from_extents(x0, H - y1, x1, H - y0)))
                img = QImage(int(sip.voidptr(buf)), buf.shape[1], buf.shape[0], QImage.Format.Format_RGBA8888)
                target = QRect(x0, y0, buf.shape[1], buf.shape[0])
                painter.eraseRect(target)
                painter.drawImage(target.topLeft(), img)
        finally:
            painter.restore()

    def keyPressEvent(self, event) -> None:
        if self._view._leave_key(event):
            self._view.leave_full_screen()
            event.accept()
            return
        step = _zoom_key(event)
        if step is None:
            super().keyPressEvent(event)
            return
        self._view._zoom_key(step)
        event.accept()

    def event(self, event) -> bool:
        # + - 0 belong to the preview while it has the focus, whatever shortcuts the main window has (and Esc while
        # it is full screen)
        if event.type() == QEvent.Type.ShortcutOverride and (_zoom_key(event) is not None
                                                             or self._view._leave_key(event)):
            event.accept()
            return True
        return super().event(event)


class _Tag:
    """A tag of the hover (the guide's distance, the cursor's elevation, the edge tag of a guide out of view): white
    text on a navy box, placed in display px like the matplotlib marks (`ha` / `va` place the box on its position),
    painted by Qt over the canvas (PreviewWidget._paint_tags), never in the plot's buffer. Its size is the same on
    screen at any zoom."""

    def __init__(self, metrics: QFontMetricsF, ratio: float, ha: str, va: str):
        self._m, self._r = metrics, ratio
        self._text, self._visible = "", False
        self._x = self._y = 0.0
        self._ha, self._va = ha, va

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = str(text)

    def get_visible(self) -> bool:
        return self._visible

    def set_visible(self, on: bool) -> None:
        self._visible = bool(on)

    def get_position(self) -> Tuple[float, float]:
        return self._x, self._y

    def set_position(self, xy) -> None:
        self._x, self._y = float(xy[0]), float(xy[1])

    def set_horizontalalignment(self, ha: str) -> None:
        self._ha = ha

    def get_window_extent(self, renderer=None) -> Bbox:
        """The box (padding included), display px."""
        r = self._r
        w = self._m.horizontalAdvance(self._text) + 2.0 * TAG_PAD_X * r
        h = self._m.ascent() + self._m.descent() + 2.0 * TAG_PAD_Y * r
        x0 = self._x - w / 2.0 if self._ha == "center" else self._x if self._ha == "left" else self._x - w
        y0 = self._y - h if self._va == "top" else self._y - h / 2.0 if self._va == "center" else self._y
        return Bbox.from_bounds(x0, y0, w, h)


class _Marks:
    """The hover marks over the plot: the band over a pointed-at exploration, the cursor's elevation line, the
    guide, a dot on each line (in its colour, white edge), in display pixels and animated (left out of every full
    draw, blitted over it); and the distance and elevation tags and the edge tag of a guide outside the zoomed view
    (_Tag: painted by Qt over the canvas)."""

    def __init__(self, fig: Figure, colors: Sequence[str], font: QFont, ratio: float):
        kw = dict(transform=IdentityTransform(), animated=True, visible=False)
        self.band = Rectangle((0.0, 0.0), 0.0, 0.0, fc=NAVY, ec="none", alpha=0.08, **kw)
        self.cursor = Line2D([], [], color=NAVY, alpha=0.4, ls=(0, (3.0, 3.0)), **kw)
        self.guide = Line2D([], [], color=NAVY, alpha=0.85, solid_capstyle="butt", **kw)
        self.dots = [Line2D([], [], ls="none", marker="o", mfc=c, mec="white", **kw) for c in colors]
        for a in self.artists():
            fig.add_artist(a)
        self.font = QFont(font)                       # in display (physical) px
        self.font.setPixelSize(max(1, round(TAG_PX * ratio)))
        self.font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetricsF(self.font)
        self.xtag = _Tag(metrics, ratio, "center", "top")
        self.ytag = _Tag(metrics, ratio, "right", "center")
        self.edge = _Tag(metrics, ratio, "left", "center")
        self._z = None

    def artists(self) -> list:
        """The matplotlib marks (the tags are not artists)."""
        return [self.band, self.cursor, self.guide, *self.dots]

    def tags(self) -> list:
        return [self.xtag, self.ytag, self.edge]

    def hide(self) -> None:
        for a in self.artists() + self.tags():
            a.set_visible(False)

    def scale(self, z: float) -> None:
        """Sizes for zoom z (points / z: the figure dpi is z times the 100 % dpi)."""
        if z == self._z:
            return
        self._z = z
        self.guide.set_linewidth(GUIDE_LW / z)
        self.cursor.set_linewidth(CURSOR_LW / z)
        for d in self.dots:
            d.set_markeredgewidth(DOT_EDGE_LW / z)
            d.set_markersize(DOT_MS / z)


class PreviewWidget(QWidget):
    """draw(model, settings, plan) or show_message(text). See the module docstring for zoom, hover and full screen."""

    hoverChanged = pyqtSignal(float, int)       # station (ft); index in core.hover.hover_targets(model) (the
                                                # explorations, then the other points) of what is pointed at, or -1
    hoverLeft = pyqtSignal()                    # the hover ended (mouse left, past the ends, toggle off, new drawing)
    exportSurfacesRequested = pyqtSignal()      # the "Surfaces CSV…" button (only with a section)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.figure = Figure(figsize=(8, 3), dpi=BASE_DPI, facecolor="white")
        self.canvas = PreviewCanvas(self.figure, self)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(False)
        # no scroll bars: coming and going they would change the plot's size (pan by dragging instead)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scroll.setMinimumHeight(120)
        vp = self.scroll.viewport()
        pal = vp.palette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base):
            pal.setColor(role, QColor("white"))
        vp.setPalette(pal)
        vp.setAutoFillBackground(True)
        self.scroll.setWidget(self.canvas)
        self.popup = HoverPopup(vp)                  # (made after the canvas: above it)

        self._strip_on = settings_store.user_value(STRIP_KEY, "1") != "0"
        self._popup_on = settings_store.user_value(POPUP_KEY, "1") != "0"
        self.toolbar = self._make_toolbar()
        self.status = QLabel("")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._status_css = ""
        self.readout = HoverReadout(self)
        self.readout.setHidden(not self._strip_on)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 4, 0)
        top.addWidget(self.toolbar)
        top.addWidget(self.status, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.readout)
        lay.addWidget(self.scroll, 1)

        self._content = ("message", "Choose a section line and a DEM (and, optionally, an explorations layer).")
        self._pending = True
        self.last_error = ""
        self._model = self._settings = None
        self._lines = []
        self._line_key: Optional[str] = None     # the section line drawn (a new one starts at Fit)
        self._ax = None
        # view: zoom, and the figure fractions at the viewport's centre (floats: integer scroll values drift)
        self._z, self._fx, self._fy = 1.0, 0.5, 0.5
        self._vp: Optional[Tuple[int, int]] = None   # viewport size at 100 %, logical px (None until laid out)
        self._z_max = ZOOM_MAX
        self._applying = False
        self._drag = None
        self._wheel_z: Optional[float] = None
        self._wheel_at: Optional[QPointF] = None
        # hover: where it comes from ("mouse", viewport point) or ("map", station, offset, side), the marks
        self._hover = None
        self._shown = False                      # hoverChanged sent since the last hoverLeft
        self._marks: Optional[_Marks] = None
        self._marks_on = False                   # the marks should show
        self._marks_drawn = False                # the marks are in the Agg buffer, over self._bg
        self._mark_boxes: List[tuple] = []       # where they are in it (display px, padded, inside the window)
        self._tag_boxes: List[tuple] = []        # the tags painted over the canvas since (display px, padded)
        self._bg = None                          # the plot under the visible window, without the marks
        self._bg_key = None
        self._stale = True                       # a full draw is due (nothing to blit onto yet)
        self._boxes = None                       # explorations' and other points' hit boxes, display px
        self._placed: list = []                  # where draw_preview drew the other points (render.scales.PlacedPoint)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(RELAYOUT_MS)
        self._resize_timer.timeout.connect(self._request)
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.setInterval(WHEEL_MS)
        self._wheel_timer.timeout.connect(self._flush_wheel)
        # full screen: where the dock was (None when it is not full screen); after it was put back hidden, its
        # place again to size it at its next show; the dock's hides and shows are looked at once they are done
        self._full: Optional[_DockPlace] = None
        self._full_resize: Optional[_DockPlace] = None
        self._full_timer = QTimer(self)
        self._full_timer.setSingleShot(True)
        self._full_timer.setInterval(0)
        self._full_timer.timeout.connect(self._full_screen_check)
        # Esc anywhere in the full-screen window (the canvas takes it first when it has the focus); no shortcut
        # while docked: Esc stays QGIS's
        self.act_leave_full = QAction("Put the preview back", self)
        self.act_leave_full.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.act_leave_full.triggered.connect(self.leave_full_screen)
        self.addAction(self.act_leave_full)
        vp.installEventFilter(self)
        self.scroll.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.scroll.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.canvas.mpl_connect("draw_event", self._on_draw)
        self._apply_theme()
        self.readout.show_idle(self._idle_text())
        self._update_actions()

    def _make_toolbar(self) -> QToolBar:
        tb = QToolBar(self)
        tb.setIconSize(tb.iconSize() * 0.8)
        tb.setFloatable(False)
        tb.setMovable(False)
        icon = QgsApplication.getThemeIcon
        self.act_fit = tb.addAction(icon("/mActionZoomFullExtent.svg"), "Fit")
        self.act_fit.setToolTip("Fit: the whole section in the panel (or double-click the plot, or 0)")
        self.act_zoom_out = tb.addAction(icon("/mActionZoomOut.svg"), "Zoom out")
        self.act_zoom_out.setToolTip("Zoom out (−, or the mouse wheel over the plot)")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(self.zoom_label.fontMetrics().horizontalAdvance("800%") + 12)
        self.zoom_label.setToolTip("100% is the whole section in the panel")
        tb.addWidget(self.zoom_label)
        self.act_zoom_in = tb.addAction(icon("/mActionZoomIn.svg"), "Zoom in")
        self.act_zoom_in.setToolTip("Zoom in (+, or the mouse wheel over the plot). Drag or Shift+wheel to pan.")
        tb.addSeparator()
        self.act_csv = tb.addAction(icon("/mIconDelimitedText.svg"), "Surfaces CSV…")
        self.act_csv.setIconText("Surfaces CSV…")    # (the button text would drop the "…" otherwise)
        self.act_csv.setToolTip("Export the ground and every surface (distance, elevation) to a CSV file")
        button = tb.widgetForAction(self.act_csv)
        if button is not None:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.addSeparator()
        self._icon_color = self.palette().color(QPalette.ColorRole.WindowText).name()
        self.act_strip = tb.addAction(strip_icon(QColor(self._icon_color)), "Readout row")
        self.act_strip.setCheckable(True)
        self.act_strip.setChecked(self._strip_on)
        self.act_popup = tb.addAction(popup_icon(QColor(self._icon_color)), "Popup")
        self.act_popup.setCheckable(True)
        self.act_popup.setChecked(self._popup_on)
        tb.addSeparator()
        self.act_full = tb.addAction(full_screen_icon(QColor(self._icon_color)), "Full screen")
        self.act_full.setCheckable(True)
        self.act_full.setToolTip(wrap_tip(FULL_TIP))        # (0.3.7 finish, wrap_tip: a long tooltip wraps)
        self._toggle_tips()
        self.act_fit.triggered.connect(self.fit)
        self.act_zoom_out.triggered.connect(lambda: self._zoom_key(-1))
        self.act_zoom_in.triggered.connect(lambda: self._zoom_key(1))
        self.act_csv.triggered.connect(self._export_surfaces)
        self.act_strip.toggled.connect(self._toggle_strip)
        self.act_popup.toggled.connect(self._toggle_popup)
        self.act_full.toggled.connect(self.set_full_screen)
        return tb

    # ---- public API
    def draw(self, model, settings, plan) -> None:
        key = getattr(model, "line_wkt", "") or ""
        if key != self._line_key:                  # another section line: start from the whole section
            self._line_key = key
            self._reset_zoom()
        self._content = ("section", model, settings, plan)
        self._model, self._settings = model, settings
        self._lines = hover_lines(model)
        self.status.setText(summary_text(model, settings, plan))
        z_range = (getattr(plan, "z_min", None), getattr(plan, "z_max", None))   # (the cursor's elevations)
        self.readout.set_lines(self._lines, settings, model, z_range)
        self.popup.set_lines(self._lines, settings, model, z_range)
        self._end_hover()
        self._update_actions()
        self._request()

    def show_message(self, text: str) -> None:
        self._content = ("message", text)
        self._model = self._settings = None
        self._lines = []
        self._line_key = None
        self._reset_zoom()
        self.status.setText("")
        self.readout.clear()
        self.popup.clear()
        self._end_hover()
        self._update_actions()
        self._request()

    def clear(self) -> None:
        self.show_message("")

    def render_pending(self) -> None:
        """Draw now even if hidden (used by tests and by showEvent)."""
        self._render()

    def has_section(self) -> bool:
        return self._content[0] == "section"

    @property
    def zoom(self) -> float:
        """1.0 is the whole section in the panel."""
        return self._z

    def set_zoom(self, z: float, anchor=None) -> None:
        """Zoom the whole plot to z (clamped to 1 .. the zoom limit), keeping the point under `anchor` (a QPointF or
        (x, y) in viewport px; default the viewport's centre) where it is. Needs a section and a laid-out panel."""
        if self._vp is None or not self.has_section():
            return
        z = min(max(float(z), 1.0), self._z_max)
        if abs(z - self._z) < 1e-9:
            return
        vw, vh = self._vp
        if anchor is None:
            ax_, ay_ = vw / 2.0, vh / 2.0
        elif hasattr(anchor, "x"):
            ax_, ay_ = float(anchor.x()), float(anchor.y())
        else:
            ax_, ay_ = (float(v) for v in anchor)
        # the figure fraction under the anchor, from the float state (not the rounded scroll values)
        z0 = self._z
        gx = (self._fx * vw * z0 - vw / 2.0 + ax_) / (vw * z0)
        gy = (self._fy * vh * z0 - vh / 2.0 + ay_) / (vh * z0)
        self._fx = (gx * vw * z - ax_ + vw / 2.0) / (vw * z)
        self._fy = (gy * vh * z - ay_ + vh / 2.0) / (vh * z)
        self._z = z
        self._apply_view()
        self._view_changed()

    def fit(self) -> None:
        """100 %: the whole section."""
        self.set_zoom(1.0)

    def hover_enabled(self) -> bool:
        """The hover works (the guide, the marks, the map marker, the map's guide here): the readout row or the
        popup is on."""
        return self._strip_on or self._popup_on

    def strip_enabled(self) -> bool:
        return self._strip_on

    def popup_enabled(self) -> bool:
        return self._popup_on

    def show_guide(self, station: float, off_ft: float, side: str) -> None:
        """The map cursor is `off_ft` from the section line, beside `station` ("L"/"left" or "R"/"right"): put the
        guide there and read out every line (no cursor elevation). Out of the zoomed view, an edge tag points to it
        (the view never scrolls by itself). Sends no hoverChanged (the map already knows)."""
        if not self._can_hover():
            return
        word = "left" if str(side).strip().upper().startswith("L") else "right"
        self._hover_map(float(station), abs(float(off_ft)), word)

    def hide_guide(self) -> None:
        """The map cursor left: take the guide from the map away (a hover with the mouse stays)."""
        if self._hover is not None and self._hover[0] == "map":
            self._hover = None
            self._show_none(self._idle_text())

    def is_full_screen(self) -> bool:
        return self._full is not None

    def set_full_screen(self, on: bool) -> None:
        """The "Full screen" toggle. On: the preview's dock (shown, in a main window) floats and fills the screen it
        is on, and the section fits. Off: leave_full_screen."""
        if bool(on) == self.is_full_screen():
            self._sync_full_action()
        elif on:
            self._enter_full_screen()
        else:
            self.leave_full_screen()

    def leave_full_screen(self) -> None:
        """Out of full screen: the dock back where it was, docked in its area at its size (Qt kept its place there)
        or floating at its geometry, and the section fits again. A dock closed or hidden meanwhile is put back
        hidden and gets its size when it next shows. (The plugin calls this before it unloads.)"""
        place, self._full = self._full, None
        if place is None:
            return
        self.act_leave_full.setShortcut(QKeySequence())
        self._sync_full_action()
        dock, win = place.dock, place.window
        if sip.isdeleted(dock):
            return
        if not sip.isdeleted(win):
            win.removeEventFilter(self)
        dock.setWindowState(place.state)              # (not showNormal: a hidden dock stays hidden)
        dock.setGeometry(place.geometry)              # (a docked one's: where it floats next time, as before)
        if dock.isFloating() and dock.isHidden():
            # QDockWidget notes where it floats next only from the Resize events it gets while floating, and a hidden
            # one gets none: without this it would float over the whole screen next time
            size = place.geometry.size()
            QApplication.sendEvent(dock, QResizeEvent(size, size))
        if not place.floating and not sip.isdeleted(win):
            dock.setFloating(False)
            if dock.isFloating() or win.dockWidgetArea(dock) != place.area:
                win.addDockWidget(place.area, dock)   # (Qt lost its place: at the end of its area)
                dock.setFloating(False)
            self._full_resize = place
            if dock.isVisible():
                dock.raise_()                         # (in tabs: its tab in front again)
                self._size_dock()
        if self._full_resize is None:
            dock.removeEventFilter(self)
        self._drag = None                             # (Esc during a drag: the window moved under it)
        self._update_cursor()
        self.fit()

    def _enter_full_screen(self) -> None:
        dock = _ancestor(self, QDockWidget)
        win = _ancestor(dock, QMainWindow)
        if dock is None or win is None or not dock.isVisible():
            self._sync_full_action()                  # (not in a shown dock: nothing to fill the screen with)
            return
        self._full_timer.stop()
        self._full_resize = None
        # the screen the dock is on (where its middle is: a main window may reach over two), before it floats
        screen = QGuiApplication.screenAt(dock.mapToGlobal(dock.rect().center())) or dock.screen()
        area = win.dockWidgetArea(dock)
        vertical = area in (Qt.DockWidgetArea.TopDockWidgetArea, Qt.DockWidgetArea.BottomDockWidgetArea)
        size = dock.height() if vertical else dock.width()
        # (a dock in no area, say in a floating group of tabs, comes back as a floating dock)
        floating = dock.isFloating() or area == Qt.DockWidgetArea.NoDockWidgetArea
        if not dock.isFloating():
            dock.setFloating(True)                    # (Qt keeps its place in the area for setFloating(False))
        self._full = _DockPlace(dock, win, floating, area, size, dock.geometry(), dock.windowState())
        dock.installEventFilter(self)                 # closed or hidden while full screen: put back
        win.installEventFilter(self)                  # QGIS closing: put back first
        dock.setGeometry(screen.availableGeometry())  # on that screen, then all of it
        dock.showFullScreen()
        dock.raise_()
        dock.activateWindow()
        self.canvas.setFocus()
        self.act_leave_full.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self._sync_full_action()
        self.fit()

    def _full_screen_check(self) -> None:
        """The dock hid or showed. Closed or hidden while full screen (Alt+F4, the plugin's button), it is put
        back (hidden); shown again after that, it gets its size in its area."""
        if self._full is not None:
            if sip.isdeleted(self._full.dock) or self._full.dock.isHidden():
                self.leave_full_screen()
        elif (self._full_resize is not None and not sip.isdeleted(self._full_resize.dock)
              and self._full_resize.dock.isVisible()):
            self._size_dock()

    def _size_dock(self) -> None:
        """The dock back in its area: its size there again."""
        place, self._full_resize = self._full_resize, None
        if place is None or sip.isdeleted(place.dock):
            return
        dock, win = place.dock, place.window
        dock.removeEventFilter(self)
        if sip.isdeleted(win) or dock.isFloating() or win.dockWidgetArea(dock) != place.area or place.size <= 0:
            return
        vertical = place.area in (Qt.DockWidgetArea.TopDockWidgetArea, Qt.DockWidgetArea.BottomDockWidgetArea)
        orient = Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
        win.resizeDocks([dock], [place.size], orient)
        lay = win.layout()
        if lay is not None:
            lay.activate()                            # (laid out now: its size can be read)
            got = dock.height() if vertical else dock.width()
            if 0 < got != place.size:                 # in tabs: that was the size of the tabs, their bar too
                win.resizeDocks([dock], [2 * place.size - got], orient)

    def _full_dock(self) -> Optional[QDockWidget]:
        """The dock that is full screen, or waits for its size after it was put back hidden."""
        place = self._full if self._full is not None else self._full_resize
        return None if place is None else place.dock

    def _leave_key(self, event) -> bool:
        """Esc while full screen."""
        return self._full is not None and event.key() == Qt.Key.Key_Escape

    def _sync_full_action(self) -> None:
        """The toggle checked while full screen (its toggled signal comes back to set_full_screen, which then has
        nothing to do)."""
        self.act_full.setChecked(self._full is not None)

    # ---- Qt
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending:
            self._render()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
                            QEvent.Type.StyleChange):
            self._apply_theme()

    def _apply_theme(self) -> None:
        """The theme's colours for the status text (the panel's muted text; the application palette, since a theme
        stylesheet may leave this widget's own window colour transparent) and the drawn toggles' icons (the text
        colour: QGIS's dark themes leave the button text colour to the system)."""
        if not hasattr(self, "_status_css"):          # (events can come before the toolbar and the status exist)
            return
        css = f"color: {theme_for(QApplication.palette()).muted.name()};"
        if css != self._status_css:
            self._status_css = css
            self.status.setStyleSheet(css)
        color = self.palette().color(QPalette.ColorRole.WindowText).name()
        if color != self._icon_color:
            self._icon_color = color
            self.act_strip.setIcon(strip_icon(QColor(color)))
            self.act_popup.setIcon(popup_icon(QColor(color)))
            self.act_full.setIcon(full_screen_icon(QColor(color)))

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t == QEvent.Type.Resize and obj is self.scroll.viewport():
            size = event.size()
            self._viewport_resized(size.width(), size.height())
        elif t in (QEvent.Type.Hide, QEvent.Type.Show) and obj is self._full_dock():
            self._full_timer.start()                  # (looked at once the hide or show is done)
        elif t == QEvent.Type.Close and self._full is not None and obj is self._full.window:
            self.leave_full_screen()                  # QGIS is closing: the dock back before it saves the layout
        return super().eventFilter(obj, event)

    # ---- drawing
    def _request(self) -> None:
        if self.isVisible():
            self._render()
        else:
            self._pending = True

    def _render(self) -> None:
        # the data point at the view's centre when zoomed in (the same line: a new one or a message starts at Fit):
        # the new layout keeps it there. Taken while the old axes still match the zoomed canvas.
        keep = None
        if self._ax is not None and self._z > 1.0 + 1e-9 and self._vp is not None:
            win = self._window()
            keep = self._ax.transData.inverted().transform(((win.x0 + win.x1) / 2.0, (win.y0 + win.y1) / 2.0))
        lay = self.layout()
        if lay is not None:
            lay.activate()                    # a readout height change still pending: the viewport takes its size
        self._resize_timer.stop()             # this render is for the current viewport: no second layout after it
        self._pending = False
        self.last_error = ""
        fig = self.figure
        self._ax = self._marks = None
        self._marks_on = self._marks_drawn = False
        self._mark_boxes = []
        self._bg = self._boxes = None
        self._placed = []
        self._stale = True
        zoom_dpi = fig.dpi
        # lay out at the 100 % dpi (text is measured as Agg draws it at the figure's dpi), then draw at the zoom's
        fig.set_dpi(BASE_DPI * self.canvas.device_pixel_ratio)
        try:
            fig.clear()
            if self._content[0] == "message":
                self._draw_message(self._content[1])
            else:
                _, model, settings, plan = self._content
                try:
                    from ..render.figure import draw_preview
                    self._placed = list(draw_preview(fig, model, settings, plan) or [])   # (the points' boxes)
                    overlay_sheets(fig, plan)
                    self._ax = main_axes(fig, plan)
                    if self._ax is not None:
                        self._marks = _Marks(fig, [ln.color for ln in self._lines], self.font(),
                                             self.canvas.device_pixel_ratio)
                except Exception as exc:   # never a traceback dialog: log it and say so in the preview
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    QgsMessageLog.logMessage(traceback.format_exc(), "XSections", Qgis.MessageLevel.Warning)
                    fig.clear()
                    self._ax = self._marks = None
                    self._placed = []
                    self._draw_message(f"Preview failed: {self.last_error}\n(details in the XSections log)")
        finally:
            fig.set_dpi(zoom_dpi)
        if keep is not None and self._ax is not None:
            c = self.canvas
            r = c.device_pixel_ratio
            x, y = self._ax.transData.transform(keep)
            self._fx = float(x) / max(1.0, c.width() * r)
            self._fy = 1.0 - float(y) / max(1.0, c.height() * r)
            self._apply_view()                # (clamped to the canvas)
        if self._hover is None:
            self.readout.show_idle(self._idle_text())    # the note for what is drawn now (none without a section)
        self.canvas.draw_idle()
        self._refresh_hover()

    def _draw_message(self, text: str) -> None:
        if text:
            self.figure.text(0.5, 0.5, text, ha="center", va="center", wrap=True, fontsize=10, color="#555555")

    def _on_draw(self, _event) -> None:
        """A full draw (the marks are left out of it): save the plot under the view afresh and put the marks back."""
        self._bg = None
        self._marks_drawn = False
        self._mark_boxes, self._tag_boxes = [], []   # (the whole canvas is repainted after a full draw)
        self._stale = False
        self._boxes = None
        if self._marks_on:
            self._paint_marks(blit=False)            # the canvas repaints after the draw

    # ---- zoom and pan
    def _viewport_resized(self, w: int, h: int) -> None:
        if w <= 0 or h <= 0 or self._vp == (w, h):
            return
        self._vp = (w, h)
        # (the canvas learns the screen's ratio when first shown; the widget may know it already)
        self._z_max = zoom_limit(w, h, max(self.canvas.device_pixel_ratio, self.devicePixelRatioF() or 1.0))
        self._z = min(self._z, self._z_max)
        self._apply_view()
        self._view_changed()
        self._resize_timer.start()                  # lay the plot out again for the new size

    def _ratio_changed(self) -> None:
        """The screen's device pixel ratio changed, the logical size did not (the window moved to another monitor,
        or the display scale changed): the pixel budget's zoom limit for the new ratio, then a new layout (text is
        measured at the new dpi)."""
        self.readout.update()                 # (its swatches and symbols are made again for the new ratio)
        self.popup.update()
        if self._vp is None:
            return
        self._z_max = zoom_limit(*self._vp, self.canvas.device_pixel_ratio)
        self._z = min(self._z, self._z_max)
        self._stale, self._bg, self._marks_drawn = True, None, False   # matplotlib asked for a full draw
        self._mark_boxes = []
        self._apply_view()                    # before matplotlib's draw: never a canvas over the budget
        self._view_changed()
        self._resize_timer.start()

    def _reset_zoom(self) -> None:
        self._z, self._fx, self._fy = 1.0, 0.5, 0.5
        self._apply_view()
        self._update_actions()

    def _apply_view(self) -> None:
        """Size the canvas and the figure dpi for the zoom, and scroll to the remembered centre."""
        if self._vp is None:
            return
        vw, vh = self._vp
        canvas, fig = self.canvas, self.figure
        w, h = max(vw, round(vw * self._z)), max(vh, round(vh * self._z))
        dpi = BASE_DPI * w / vw                       # figure inches stay viewport / BASE_DPI: no new layout
        r = canvas.device_pixel_ratio
        changed = (canvas.width(), canvas.height()) != (w, h) or abs(fig.dpi - dpi * r) > 1e-9
        self._applying = True
        try:
            fig._original_dpi = dpi                   # a display change sets dpi = ratio x this: keep the zoom's
            fig.set_dpi(dpi * r)                      # before the resize: the canvas takes inches = pixels / dpi
            canvas.resize(w, h)
            hx, hy = vw / 2.0 / w, vh / 2.0 / h
            self._fx = min(max(self._fx, hx), 1.0 - hx)
            self._fy = min(max(self._fy, hy), 1.0 - hy)
            self.scroll.horizontalScrollBar().setValue(round(self._fx * w - vw / 2.0))
            self.scroll.verticalScrollBar().setValue(round(self._fy * h - vh / 2.0))
        finally:
            self._applying = False
        self._boxes = None
        if changed:                                   # the resize asked for a full draw: nothing to blit onto yet
            self._stale = True
            self._bg = None
            self._marks_drawn = False
            self._mark_boxes = []

    def _view_changed(self) -> None:
        self._update_actions()
        self._refresh_hover()                         # the plot moved under a still mouse

    def _scrolled(self, _value: int = 0) -> None:
        if self._applying or self._vp is None:
            return
        vw, vh = self._vp
        self._fx = (self.scroll.horizontalScrollBar().value() + vw / 2.0) / max(1, self.canvas.width())
        self._fy = (self.scroll.verticalScrollBar().value() + vh / 2.0) / max(1, self.canvas.height())
        if self._drag is None:
            self._refresh_hover()
        else:
            self._paint_marks()

    def _zoom_key(self, step: int) -> None:
        if self._drag is not None:                    # (the drag pans from where it started)
            return
        if step == 0:
            self.fit()
        else:
            self.set_zoom(zoom_step(self._z, step, self._z_max))

    def _wheel(self, event) -> None:
        if not self.has_section() or self._vp is None or self._drag is not None:
            return
        d = event.angleDelta()
        dx, dy = d.x(), d.y()
        sideways = abs(dx) > abs(dy)
        if sideways or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = dx if sideways else dy
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.value() - round(delta * WHEEL_PAN_PX / 120.0))
            return
        if not dy:
            return
        start = self._wheel_z if self._wheel_z is not None else self._z
        self._wheel_z = min(max(start * WHEEL_STEP ** (dy / 120.0), 1.0), self._z_max)
        self._wheel_at = QPointF(event.position()) + QPointF(self.canvas.pos())
        if not self._wheel_timer.isActive():
            self._wheel_timer.start()

    def _flush_wheel(self) -> None:
        z, at = self._wheel_z, self._wheel_at
        self._wheel_z = self._wheel_at = None
        if z is not None:
            self.set_zoom(z, at)

    def _drag_start(self, event) -> bool:
        if (self._z <= 1.0 + 1e-9 or self._vp is None
                or event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton)):
            return False
        bars = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        self._drag = (event.button(), QPointF(event.globalPosition()), bars[0].value(), bars[1].value())
        self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._marks_on = False                       # hidden while dragging (the readout keeps its values: the
        self._paint_marks()                          # point under the mouse moves with it)
        self.popup.hide_card()
        return True

    def _drag_move(self, event) -> bool:
        if self._drag is None:
            return False
        _, start, h0, v0 = self._drag
        d = QPointF(event.globalPosition()) - start   # global: the canvas moves under the mouse
        self.scroll.horizontalScrollBar().setValue(round(h0 - d.x()))
        self.scroll.verticalScrollBar().setValue(round(v0 - d.y()))
        return True

    def _drag_end(self, event) -> bool:
        if self._drag is None or event.button() != self._drag[0]:
            return False
        self._drag = None
        self._update_cursor()
        self._mouse_moved(event.position())
        return True

    def _update_cursor(self) -> None:
        if self._drag is not None:
            return
        if self._z > 1.0 + 1e-9:
            self.canvas.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.canvas.unsetCursor()

    def _update_actions(self) -> None:
        zoomable = self.has_section() and self._vp is not None
        self.act_fit.setEnabled(zoomable and self._z > 1.0 + 1e-6)
        self.act_zoom_out.setEnabled(zoomable and self._z > 1.0 + 1e-6)
        self.act_zoom_in.setEnabled(zoomable and self._z < self._z_max - 1e-6)
        self.act_csv.setEnabled(self.has_section())
        self.zoom_label.setText(f"{round(self._z * 100)}%")
        self._update_cursor()

    def _window(self) -> Bbox:
        """The visible part of the canvas, display px (origin bottom left)."""
        c = self.canvas
        r = c.device_pixel_ratio
        W, H = c.width(), c.height()
        if self._vp is None:
            x0 = y0 = 0
            x1, y1 = W, H
        else:
            x0, y0 = max(0, -c.x()), max(0, -c.y())
            x1, y1 = min(W, x0 + self._vp[0]), min(H, y0 + self._vp[1])
        return Bbox.from_extents(math.floor(x0 * r), math.floor((H - y1) * r), math.ceil(x1 * r),
                                 math.ceil((H - y0) * r))

    def _display_xy(self, vp: QPointF) -> Tuple[float, float]:
        """A viewport point in display px (as matplotlib's events give them)."""
        c = self.canvas
        r = c.device_pixel_ratio
        x, y = vp.x() - c.x(), vp.y() - c.y()
        return x * r, (c.height() - y) * r

    # ---- hover
    def _idle_text(self) -> str:
        """The readout's note: how to hover, when there is a section to point at; or nothing. (With both toggles
        off the readout row is hidden.)"""
        return IDLE_TEXT if self.has_section() and self._ax is not None else ""

    def _can_hover(self) -> bool:
        return (self.hover_enabled() and self.has_section() and self._ax is not None and self._marks is not None
                and bool(self._lines) and self._drag is None)

    def _mouse_moved(self, pos: QPointF) -> None:
        if self._can_hover():
            self._hover_mouse(QPointF(pos) + QPointF(self.canvas.pos()))

    def _mouse_left(self) -> None:
        if self._hover is not None and self._hover[0] == "mouse":
            self._hover = None
            self._show_none(self._idle_text())

    def _end_hover(self) -> None:
        self._hover = None
        self._show_none(self._idle_text())

    def _refresh_hover(self) -> None:
        """Work the hover out again from where it came from: after a zoom or pan step (the plot moved under a still
        mouse), or a new layout."""
        st = self._hover
        if st is None or not self._can_hover():
            self._marks_on = False
            self._paint_marks()
            self.popup.hide_card()
            return
        if st[0] == "mouse":
            self._hover_mouse(st[1])
        else:
            self._hover_map(*st[1:])

    def _hover_mouse(self, vp: QPointF) -> None:
        self._hover = ("mouse", QPointF(vp))
        pick = self._pick(*self._display_xy(vp))
        s, model = self._settings, self._model
        if pick is None:
            self._show_none(IDLE_TEXT)
        elif pick[0] == "past":
            self._show_none(past_text(pick[1], s, model.length))
        elif pick[0] == "hit":
            _, i, lo, hi, half, others = pick
            target = hover_target(model, i)
            cells = strip_cells(target, s, model)
            if others:                               # more at this spot: the lead tile says how many
                title, value, small = cells[0][:3]
                here = f"+{len(others)} here"
                cells = [(title, value, f"{small} · {here}" if small else here, *cells[0][3:])] + list(cells[1:])
            self.readout.show_cells(cells)
            if self._popup_on:
                self.popup.show_hit(i, target, others)
                self.popup.place(vp.x(), vp.y())
            self._place_marks(target.station, band=(lo, hi), band_half=half)
            self._show_marks()
            self._emit_changed(target.station, i)
        else:
            _, station, cz = pick
            hv = hover_values(self._lines, station, model.length, cz)
            self.readout.show_values(hv, distance_text(station, s), elev_text(cz))
            if self._popup_on:
                self.popup.show_values(hv, f"Cursor {elev_text(cz)}")
                self.popup.place(vp.x(), vp.y())
            self._place_marks(station, cursor_z=cz, values=hv.values, nearest=hv.nearest)
            self._show_marks()
            self._emit_changed(station, -1)

    def _hover_map(self, station: float, off_ft: float, side: str) -> None:
        self._hover = ("map", station, off_ft, side)
        model, s = self._model, self._settings
        if not 0.0 <= station <= model.length:
            self._marks_on = False
            self._paint_marks()
            self.popup.hide_card()
            self.readout.show_idle(IDLE_TEXT)
            return
        hv = hover_values(self._lines, station, model.length, None)
        x = float(self._ax.transData.transform((station, 0.0))[0])
        win = self._window()
        edge = "l" if x < win.x0 else "r" if x > win.x1 else ""
        off = f"{round(off_ft):,} ft"
        self.readout.show_values(hv, distance_text(station, s), off, f"{side} of the line", off_view=bool(edge))
        if self._popup_on and not edge:              # (off view: only the edge tag)
            self.popup.show_values(hv, f"{off} {side} of the line")
            self.popup.place(*self._guide_foot(x, hv.ground_z))
        else:
            self.popup.hide_card()
        self._place_marks(station, values=hv.values, edge=edge)
        self._show_marks()

    def _guide_foot(self, x: float, ground_z: float) -> Tuple[float, float]:
        """Where the popup of a guide from the map goes (viewport px): by the guide at display x, a little above
        the ground line (40 px under the plot's top in a DEM gap), inside the viewport."""
        c, ax = self.canvas, self._ax
        r = c.device_pixel_ratio
        if ground_z is not None and math.isfinite(ground_z):
            y = c.height() - float(ax.transData.transform((0.0, ground_z))[1]) / r + c.y() - 10.0
        else:
            y = c.height() - float(ax.bbox.y1) / r + c.y() + 40.0
        vw, vh = self._vp if self._vp is not None else (c.width(), c.height())
        return min(max(x / r + c.x(), 0.0), float(vw)), min(max(y, 0.0), float(vh))

    def _pick(self, x: float, y: float):
        """What is at display point (x, y): None (off the plot), ("past", station) beyond either end of the line,
        ("hit", index, y_lo, y_hi, band_half, others) an exploration or an other point (index in
        core.hover.hover_targets; the band's half width, px; `others`: the indexes, in order, of every other target
        whose box holds the point as well and whose centre is within SAME_SPOT_PX of the nearest's distance: two
        layers' explorations at one spot are both plotted, decision 4), or ("line", station, cursor elevation).
        The nearest centre (in x) wins; the lower index on a tie."""
        ax, model = self._ax, self._model
        r = self.canvas.device_pixel_ratio
        bb = ax.bbox
        if not (bb.x0 <= x <= bb.x1 and bb.y0 <= y <= bb.y1 + ABOVE_FRAME_PX * r):
            return None
        station, cz = (float(v) for v in ax.transData.inverted().transform((x, y)))
        z0, z1 = sorted(ax.get_ylim())
        cz = min(max(cz, z0), z1)
        found = [(abs(x - cx), i, x0, x1, lo, hi) for i, cx, x0, x1, lo, hi in self._hit_boxes()
                 if x0 - HIT_DX_PX * r <= x <= x1 + HIT_DX_PX * r and lo <= y <= hi]
        if found:
            d, i, x0, x1, lo, hi = min(found, key=lambda c: (c[0], c[1]))
            half = max(BAND_HALF_PX * r, (x1 - x0) / 2.0 + 2.0 * r)
            others = tuple(sorted(c[1] for c in found if c[1] != i and c[0] - d <= SAME_SPOT_PX * r))
            return "hit", i, lo, hi, half, others
        if not 0.0 <= station <= model.length:
            return "past", station
        return "line", station, cz

    def _hit_boxes(self) -> List[Tuple[int, float, float, float, float, float]]:
        """(index, centre x, x_left, x_right, y_lo, y_hi) of everything the hover can point at, display px, index in
        core.hover.hover_targets. An exploration: its line (x_left = x_right = its x), from just below its bottom,
        never below the frame (a line the frame cuts off stops there: the band too), to above its top and its tick,
        where its label is. An other point (as draw_preview placed it): its symbol's width, from just below the
        symbol (never below the frame) to above its label."""
        if self._boxes is None:
            ax, s, model = self._ax, self._settings, self._model
            per_in = self.figure.dpi
            bottom = float(ax.bbox.y0)                   # the drawn frame's bottom (plan.z_min)
            hits = model.hits or []
            out = []
            for i, h in enumerate(hits):
                zs = [v for v in (h.top, h.bottom, h.ground_at_station, tick_base(h, s))
                      if v is not None and math.isfinite(v)]
                if not zs or not math.isfinite(h.station):
                    continue
                (x, lo), (_, hi) = ax.transData.transform([(h.station, min(zs)), (h.station, max(zs))])
                lo = max(float(lo) - HIT_BELOW_IN * per_in, bottom)    # (_pick never looks below the frame)
                out.append((i, float(x), float(x), float(x), lo, float(hi) + HIT_ABOVE_IN * per_in))
            n_others = len(getattr(model, "other_points", None) or [])
            for pp in self._placed:
                if not (0 <= pp.index < n_others and math.isfinite(pp.station) and math.isfinite(pp.z)):
                    continue
                cx, cy = (float(v) for v in ax.transData.transform((pp.station, pp.z)))
                out.append((len(hits) + pp.index, cx, cx - pp.half_w * per_in, cx + pp.half_w * per_in,
                            max(cy - pp.below * per_in - HIT_BELOW_IN * per_in, bottom),
                            cy + max(pp.above, pp.label_top) * per_in + POINT_ABOVE_IN * per_in))
            self._boxes = out
        return self._boxes

    def _place_marks(self, station: float, cursor_z: Optional[float] = None, values: Optional[Sequence[float]] = None,
                     nearest: int = -1, band: Optional[Tuple[float, float]] = None, edge: str = "",
                     band_half: Optional[float] = None) -> None:
        """Set the marks for a guide at `station` (display px from the current transforms and view); `band` (y_lo,
        y_hi) over what is pointed at, `band_half` px either side of the guide (default BAND_HALF_PX)."""
        m, ax, s = self._marks, self._ax, self._settings
        r, z = self.canvas.device_pixel_ratio, self._z
        m.hide()
        m.scale(z)
        win = self._window()
        if edge:                                     # out of the zoomed view: a tag at that edge, nothing else
            text = distance_text(station, s)
            m.edge.set_text(f"◂ {text}" if edge == "l" else f"{text} ▸")
            m.edge.set_horizontalalignment("left" if edge == "l" else "right")
            m.edge.set_position((win.x0 + EDGE_TAG_PX * r if edge == "l" else win.x1 - EDGE_TAG_PX * r,
                                 (win.y0 + win.y1) / 2.0))
            m.edge.set_visible(True)
            self._keep_inside(m.edge, win)
            return
        bb = ax.bbox
        x = float(ax.transData.transform((station, 0.0))[0])
        m.guide.set_data([x, x], [bb.y0, bb.y1])
        m.guide.set_visible(True)
        if band is not None:
            half = BAND_HALF_PX * r if band_half is None else float(band_half)
            m.band.set_bounds(x - half, band[0], 2.0 * half, band[1] - band[0])
            m.band.set_visible(True)
        if values is not None:
            z0, z1 = sorted(ax.get_ylim())
            for i, (dot, v) in enumerate(zip(m.dots, values)):
                if v is None or not math.isfinite(v) or not z0 <= v <= z1:
                    continue                         # no value, or off the plot (a surface left out of the range)
                dot.set_data([x], [float(ax.transData.transform((station, v))[1])])
                dot.set_markersize((DOT_NEAR_MS if i == nearest else DOT_MS) / z)
                dot.set_visible(True)
        if cursor_z is not None:
            y = float(ax.transData.transform((station, cursor_z))[1])
            m.cursor.set_data([bb.x0, bb.x1], [y, y])
            m.cursor.set_visible(True)
            m.ytag.set_text(elev_text(cursor_z).removesuffix(" ft"))
            m.ytag.set_position((bb.x0 - TAG_GAP_PX * r, y))
            m.ytag.set_visible(True)
            self._keep_inside(m.ytag, win)
        m.xtag.set_text(distance_text(station, s).removesuffix(" ft"))
        m.xtag.set_position((x, bb.y0 - TAG_GAP_PX * r))
        m.xtag.set_visible(True)
        self._keep_inside(m.xtag, win)

    def _keep_inside(self, t: _Tag, win: Bbox) -> None:
        """Slide a tag (its box) inside the visible window: the axis it labels may have scrolled away."""
        ext = t.get_window_extent()
        m = TAG_MARGIN_PX * self.canvas.device_pixel_ratio
        dx = dy = 0.0
        if ext.x0 < win.x0 + m:
            dx = win.x0 + m - ext.x0
        elif ext.x1 > win.x1 - m:
            dx = win.x1 - m - ext.x1
        if ext.y0 < win.y0 + m:
            dy = win.y0 + m - ext.y0
        elif ext.y1 > win.y1 - m:
            dy = win.y1 - m - ext.y1
        if dx or dy:
            x, y = t.get_position()
            t.set_position((x + dx, y + dy))

    def _paint_tags(self, canvas: QWidget) -> None:
        """Paint the visible tags over the canvas (PreviewCanvas.paintEvent, after the plot): navy boxes, white
        semibold text, in display px (the canvas's physical pixels, y up). Where they went is kept (_tag_boxes):
        the next change of the marks repaints there, to take them off or move them."""
        m = self._marks
        if m is None or not self._marks_on:
            return
        tags = [t for t in m.tags() if t.get_visible() and t.get_text()]
        if not tags:
            return
        r = canvas.device_pixel_ratio
        h = canvas.height() * r
        pad = DIRTY_PAD_PX * r
        p = QPainter(canvas)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.scale(1.0 / r, 1.0 / r)
            p.setFont(m.font)
            for t in tags:
                b = t.get_window_extent()
                where = (b.x0 - pad, b.y0 - pad, b.x1 + pad, b.y1 + pad)
                if where not in self._tag_boxes:     # (Qt's own repaints, a still mouse: the same place again)
                    self._tag_boxes.append(where)
                box = QRectF(b.x0, h - b.y1, b.width, b.height)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(NAVY))
                p.drawRoundedRect(box, TAG_RADIUS * r, TAG_RADIUS * r)
                p.setPen(QColor("white"))
                p.drawText(box, int(Qt.AlignmentFlag.AlignCenter.value), t.get_text())
        finally:
            p.end()

    def _show_marks(self) -> None:
        self._marks_on = True
        self._paint_marks()

    def _show_none(self, text: str) -> None:
        """No guide: marks and popup off, the note in the readout, and the map marker told."""
        self._marks_on = False
        self._paint_marks()
        self.popup.hide_card()
        self.readout.show_idle(text)
        self._emit_left()

    def _paint_marks(self, blit: bool = True) -> None:
        """Put the marks over the plot (or take them off) by blitting: the plot under the visible window is saved
        once per full draw or scroll; a change restores it only where the marks were, and repaints only where they
        were and are now and where the tags were and will be (a few thin strips, not the whole view: that cost ~20
        ms a move at 250 %). After a scroll the whole view is repainted. The marks are clipped to that window."""
        if self._marks is None or self._stale:
            return                                   # the next full draw (_on_draw) puts them on
        canvas = self.canvas
        win = self._window()
        key = tuple(win.extents)
        pad = DIRTY_PAD_PX * canvas.device_pixel_ratio
        dirty = self._tag_boxes                      # (tags on screen: the repaint takes them off or moves them)
        self._tag_boxes = []
        if self._marks_drawn:                        # take them off: what was under them
            self._restore_marks()
            dirty = dirty + self._mark_boxes
            self._marks_drawn = False
        self._mark_boxes = []
        scrolled = self._bg is not None and self._bg_key != key
        if scrolled:
            self._bg = None                          # scrolled: save the new window when it is needed
        if self._marks_on:
            if self._bg is None:
                self._bg, self._bg_key = canvas.copy_from_bbox(win), key
            for a in self._marks.artists():
                if a.get_visible():
                    a.set_clip_box(win)
                    a.set_clip_on(True)
                    self.figure.draw_artist(a)
                    box = _padded(a.get_window_extent(), pad, win)
                    if box is not None:
                        self._mark_boxes.append(box)
            self._marks_drawn = True
            dirty = dirty + self._mark_boxes + [_padded(t.get_window_extent(), pad) for t in self._marks.tags()
                                                if t.get_visible() and t.get_text()]
        if blit and dirty:
            canvas.repaint_rects(self._logical_rects([tuple(win.extents)] if scrolled else dirty))

    def _restore_marks(self) -> None:
        """Take the marks out of the Agg buffer: the saved plot put back where they are (_mark_boxes)."""
        bg, canvas = self._bg, self.canvas
        if bg is None:
            return
        H = canvas.get_renderer().height
        bx0, by0, bx1, by1 = bg.get_extents()       # (rows from the top, as the buffer has them)
        for x0, y0, x1, y1 in self._mark_boxes:
            left, top = max(bx0, math.floor(x0)), max(by0, math.floor(H - y1))
            right, bottom = min(bx1, math.ceil(x1)), min(by1, math.ceil(H - y0))
            if right > left and bottom > top:
                canvas.restore_region(bg, bbox=(left, top, right, bottom), xy=(bx0, by0))

    def _logical_rects(self, boxes: Sequence[tuple]) -> List[QRect]:
        """Display px boxes (x0, y0, x1, y1; y up) as the canvas's logical px rects that cover them."""
        c = self.canvas
        r = c.device_pixel_ratio
        H = c.get_renderer().height
        out = []
        for x0, y0, x1, y1 in boxes:
            left, top = math.floor(x0 / r), math.floor((H - y1) / r)
            right, bottom = math.ceil(x1 / r), math.ceil((H - y0) / r)
            if right > left and bottom > top:
                out.append(QRect(left, top, right - left, bottom - top))
        return out

    def _emit_changed(self, station: float, index: int) -> None:
        self._shown = True
        self.hoverChanged.emit(float(station), int(index))

    def _emit_left(self) -> None:
        if self._shown:
            self._shown = False
            self.hoverLeft.emit()

    def _toggle_strip(self, on: bool) -> None:
        """The readout row on or off (remembered): off, it is hidden and the plot takes its room (a new layout)."""
        self._strip_on = bool(on)
        settings_store.set_user_value(STRIP_KEY, "1" if on else "0")
        if on and self.readout.isHidden():
            # laid out for the width it gets before it shows (hidden, the layout gave it none): showing it
            # activates the panel's layouts at once, and a height worked out for another width would push a
            # bottom dock taller, for good
            self.readout.fit_width(self.scroll.width())
        self.readout.setHidden(not on)
        self._toggled()

    def _toggle_popup(self, on: bool) -> None:
        """The popup on or off (remembered): off, it goes at once."""
        self._popup_on = bool(on)
        settings_store.set_user_value(POPUP_KEY, "1" if on else "0")
        if not on:
            self.popup.hide_card()
        self._toggled()

    def _toggled(self) -> None:
        self._toggle_tips()
        if self.hover_enabled():
            self._refresh_hover()                     # (the popup comes at the hover's place)
        else:                                         # both off: no hover at all
            if self._hover is not None:
                self._shown = True                    # (a guide from the map too: hoverLeft takes the marker off)
            self._end_hover()

    def _toggle_tips(self) -> None:
        self.act_strip.setToolTip(f"Readout row above the plot ({'on' if self._strip_on else 'off'})")
        self.act_popup.setToolTip(f"Popup next to the cursor ({'on' if self._popup_on else 'off'})")

    def _export_surfaces(self) -> None:
        if self.has_section():
            self.exportSurfacesRequested.emit()


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
    """The status line over the preview: "7 explorations · 3 other points · 4,588 ft · VE 10×" (the points part only
    when there are any; "3 other points" alone without an exploration layer on; "ground line only" with neither),
    then the sheets and a misfit."""
    n = len(model.hits or [])
    m = len(getattr(model, "other_points", None) or [])
    explorations = f"{n} exploration{'s' if n != 1 else ''}"
    points = f"{m} other point{'s' if m != 1 else ''}"
    if not (getattr(model, "has_points", getattr(model, "has_explorations", True)) or m):
        first = "ground line only"
    elif not getattr(model, "has_explorations", True):
        first = points
    else:
        first = f"{explorations} · {points}" if m else explorations
    parts = [first,
             f"{model.length:,.0f} ft",
             f"VE {settings.vertical_exaggeration:g}×"]
    pages = getattr(plan, "pages", []) or []
    if len(pages) > 1:
        parts.append(f"{len(pages)} sheets")
    if not getattr(plan, "fits", True):
        parts.append("does not fit the sheet")
    return " · ".join(parts)
