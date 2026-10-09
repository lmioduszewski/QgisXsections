"""The readout strip: the row of tiles above the preview plot that reads out what is under the mouse.

On a hover the first tile reads where the cursor is: "760 ft from A" ("7+60 from A" with station labels) over the
cursor's elevation and its depth below ("bgs") or above ("ags") the ground; then every line the preview draws (the
ground, "Ground", first, then each other surface in order) with its elevation and its depth; the line nearest the
cursor is tinted. A guide from the map shows how far the map cursor is from the line in the first tile instead
("50 ft", "right of the line"). Pointing at an exploration or an other point (a seep, a spring ...) shows its details
instead (core.hover.strip_cells: a water level titled by its date, with its symbol). The values come from core.hover,
the rule the lines are drawn by.

Compact, always (0.3.4): small type (for the application's 12 px font: labels, "ft" and details 9 px, values 11 px
semibold, each line 1.2 x its size, not the font's own leading), tight tiles, about 45 px tall for one row. Every tile
has the same width, always, whatever is pointed at: the strip is a grid of N equal columns, N the longest row any
hover can give for the section (1 + the lines, or the longest exploration or point row); a shorter row leaves its
last tiles empty. The room is shared out equally among the tiles of a line; a second line only when even the NUMBERS
do not fit: the width a tile needs is the widest number any tile can show (values in bold, the first tile's distance
too), measured once per section (and font), so one row fits a 700 px dock. Numbers are never cut; a label, a detail
and an exploration's or other point's name (the lead tile's value) that do not fit end in "…" (the popup shows them
whole), a detail's " · off view" / " · +N here" kept whole. A new panel width only works out the tiles per line and
the strip's fixed height; a hover only changes the text painted in the tiles: nothing moves, nothing is resized, no
widget is made.

Each tile has three lines: a small muted label (the line's swatch before a surface name, the water level symbol
before a level; the first tile's distance semibold in navy), the value (semibold, tabular figures, a muted "ft"), and
a quiet detail line (a depth, a source, "no DEM data"). Hairline dividers between tiles; the line nearest the cursor
gets a soft tinted rounded tile and a bold value. Painted on white paper in every theme, since it continues the white
plot, with dark ink, in the application's font.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
from qgis.PyQt.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap
from qgis.PyQt.QtWidgets import QFrame, QSizePolicy, QWidget

from ..core.hover import (NO_VALUE, HoverLine, HoverValues, depth_text, distance_text, elev_text, hover_targets,
                          strip_cells)
from ..render.figure import SURFACE_DASHES, WATER
from ..render.scales import pretty_label
from .widgets import _scaled_font

# colours: the plot's white paper and dark ink, whatever the QGIS theme
PAPER = "#ffffff"
INK = "#1d2a31"
MUTED = "#56666e"
FAINT = "#9aa7ad"           # the "—" of a value that is not there
RULE = "#e1e7ea"            # between tiles
SHADE = "#e8f0f4"           # the line nearest the cursor
NAVY = "#14313d"            # the distance (the colour of the guide on the plot and the marker on the map)
EDGE = "#cfd6da"            # under the strip

IDLE_TEXT = "Point at the section, or near the section line on the map, for distances and elevations."

# geometry, logical px (the mockup's compact CSS: the strip's padding, each tile's margin in its column, the text inset)
ROW_PAD_X, ROW_PAD_Y = 4.0, 2.0
TILE_MX, TILE_MY = 1.0, 1.0
TILE_PAD_X = 4.0
TILE_RADIUS = 4.0
RULE_INSET = 6.0            # a divider stops this far short of the tile's top and bottom
LINE_K = 1.2                # a tile's line height: 1.2 x its font's size (tight, as the mockup's CSS line-height)
UNIT_GAP = 3.0              # a value to its "ft"
SWATCH_W, SWATCH_H = 18, 8  # swatch_pixmap's and level_icon's default sizes (the popup's)
ICON_W, ICON_H = 12, 11
STRIP_SWATCH_W, STRIP_SWATCH_H, SWATCH_GAP = 10, 5, 3.0     # the strip's own swatch, and its gap to the label
STRIP_ICON_W, STRIP_ICON_H, ICON_GAP = 11, 10, 3.0          # the strip's own water level symbol
NOTE_PAD_X = 12.0
# font sizes for the application's 12 px (9 pt) font: label 9, value 11, unit 9, detail 9, note 12
LABEL_K, VALUE_K, UNIT_K, DETAIL_K = 9.0 / 12.0, 11.0 / 12.0, 9.0 / 12.0, 9.0 / 12.0
LEVEL_KINDS = {"Measured level": "measured", "ATD level": "atd"}   # hit_cells titles that get a water level icon
KEPT_SUFFIX = re.compile(r" · (off view|\+\d+ here)$")   # a detail's ending (preview.py adds it): never cut


@dataclass
class Tile:
    """One tile of the strip: a small label, a value and a quiet detail line."""
    label: str
    value: str = NO_VALUE       # NO_VALUE ("—") when there is none (the detail says why)
    detail: str = ""
    hi: bool = False            # the line nearest the cursor: tinted, value in bold
    lead: bool = False          # an exploration's or other point's first tile: its name (the value) in navy
    swatch: Optional[int] = None    # the line's swatch (its index in the strip's lines), before the label
    icon: Optional[str] = None      # the water level symbol ("measured" / "atd"), before the label
    strong: str = ""            # the label's leading part drawn semibold in navy (the first tile's distance)
    # (the pixmaps themselves are looked up when painting: they are made again for a new screen ratio)


class _Fit(NamedTuple):
    """A tile's text as it fits its box (cut with "…" where too wide)."""
    x_label: float              # where the label's text starts (after the swatch or symbol)
    strong: str                 # the label's navy part
    rest: str                   # the rest of the label
    number: str                 # the value without its unit
    unit: str                   # "ft" or ""
    detail: str


def past_text(station: float, settings, length: float) -> str:
    """The note past either end of the line: "Past A′: the line runs from 0 to 1,585 ft." ("0+00 to 15+85" with
    station labels)."""
    end = settings.end_label if station > length else settings.start_label
    if getattr(settings, "distance_labels", "feet") == "station":
        span = f"{distance_text(0.0, settings)} to {distance_text(length, settings)}"
    else:
        span = f"0 to {distance_text(length, settings)}"
    return f"Past {pretty_label(end)}: the line runs from {span}."


def _digits8(text: str) -> str:
    """Every digit as an 8 (the widest digit): the widest text a number of this many digits can give."""
    return re.sub(r"\d", "8", text)


def split_unit(value: str) -> Tuple[str, str]:
    """ "652.3 ft" -> ("652.3", "ft"): the number, and the unit drawn small and muted after it ("" if none)."""
    if value.endswith(" ft"):
        return value[:-3], "ft"
    return value, ""


def tabular(font: QFont) -> QFont:
    """The font with tabular figures (every digit as wide), where the font and Qt can (Qt 6.7+)."""
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError, ValueError):
        pass
    return font


def strip_layout(n: int, need: float, avail: float) -> Tuple[int, int]:
    """(tiles per line, lines) for n tiles that each need `need` px in a strip `avail` px wide: as many as fit on a
    line (at least one, at most n), the rest wrapped onto more lines."""
    if n <= 0:
        return 1, 1
    per = max(1, min(n, int(avail // max(need, 1.0))))
    return per, -(-n // per)


def elevation_span(lines: Sequence[HoverLine], z_range: Optional[Tuple[float, float]] = None) -> Tuple[float, float]:
    """(lowest, highest) elevation a hover can read out: the lines' values and the plot's range `z_range` (the
    cursor's elevation goes anywhere in it); (0, 100) when there are none."""
    vals = [z[np.isfinite(z)] for z in (ln.z for ln in lines)]
    vals = [float(v) for z in vals if z.size for v in (z.min(), z.max())]
    for v in z_range or ():
        if isinstance(v, (int, float)) and math.isfinite(v):
            vals.append(float(v))
    return (min(vals), max(vals)) if vals else (0.0, 100.0)


def swatch_pixmap(line: HoverLine, dpr: float = 1.0, w: int = SWATCH_W, h: int = SWATCH_H) -> QPixmap:
    """A short stretch of the line as the plot draws it (colour, width, dashes), w x h logical px (the popup's
    SWATCH_W x SWATCH_H by default; the strip's STRIP_SWATCH_W x STRIP_SWATCH_H), on a clear background (it sits on
    the tint of the nearest line too)."""
    pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(line.color))
    pen.setWidthF(max(1.2, float(line.width) * 96.0 / 72.0))       # points -> logical px
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    dash = SURFACE_DASHES.get(line.style, "-")
    if isinstance(dash, tuple):
        pen.setDashPattern([float(v) for v in dash[1]])               # in line widths, as matplotlib scales them
    p.setPen(pen)
    p.drawLine(QPointF(0.0, h / 2.0), QPointF(float(w), h / 2.0))
    p.end()
    return pm


def level_icon(kind: str, dpr: float = 1.0, w: int = ICON_W, h: int = ICON_H) -> QPixmap:
    """The water level symbol, w x h logical px (ICON_W x ICON_H by default, the popup's; the strip's STRIP_ICON_W x
    STRIP_ICON_H, the drawing scaled to it): a blue triangle, tip down (open: measured; filled: ATD), on a short
    black line; a clear background."""
    pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(w / 12.0, h / 11.0)                                       # (drawn on a 12 x 11 grid)
    p.setPen(QPen(QColor("#111111"), 1.0))
    p.drawLine(QPointF(0.5, 9.6), QPointF(11.5, 9.6))
    tri = QPainterPath(QPointF(6.0, 8.5))
    tri.lineTo(2.2, 1.5)
    tri.lineTo(9.8, 1.5)
    tri.closeSubpath()
    pen = QPen(QColor(WATER), 1.1)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(QColor(WATER) if kind == "atd" else QColor(PAPER))
    p.drawPath(tri)
    p.end()
    return pm


def _base(top: float, lh: float, m: QFontMetricsF) -> float:
    """The baseline of a line of text `lh` high from `top` (Qt has no line height: CSS's half-leading rule)."""
    return top + (lh - (m.ascent() + m.descent())) / 2.0 + m.ascent()


class HoverReadout(QFrame):
    """The readout strip. set_lines() once per section, then show_values() / show_cells() / show_idle() per hover."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._lines: List[HoverLine] = []
        self._settings = None
        self._z_range: Optional[Tuple[float, float]] = None     # the plot's elevations (the cursor's reach)
        self._length = 0.0
        self._start = "A"                       # the start's label ("760 ft from A")
        self._swatches: List[QPixmap] = []
        self._icons = {}
        self._pix_dpr = 0.0                     # the screen ratio the swatches and symbols were made for
        self._hit_rows: List[List[Tile]] = []   # each exploration's row (for the column count and the width)
        self._cols = 0                          # N: tiles in the longest row any hover can give
        self._need = 1.0                        # px a tile needs (its column, margins included)
        self._per_line, self._line_count, self._col_w = 1, 1, 0.0
        self._grid: List[QRectF] = []           # each column's place, fixed per layout
        self._notes: List[str] = [IDLE_TEXT]
        self._mode = "idle"                     # idle | values | cells
        self._idle = ""
        self._tiles: List[Tile] = []
        self._painted: List[Tuple[str, str, str]] = []      # (label, value, detail) of each tile, as last painted
        self._laid_w = -1.0
        self._width_known = False               # a layout (or fit_width) has given the strip its width
        self._fonts()
        self._relayout(force=True)

    # ---- public API
    def set_lines(self, lines: Sequence[HoverLine], settings, model,
                  z_range: Optional[Tuple[float, float]] = None) -> None:
        """A new section: the tiles of every line, the width a tile needs for the widest number any can show (the
        cursor anywhere in `z_range`, the plot's elevations, too), the column count, and the strip's height for the
        panel's width. Shows the current note until the next hover."""
        self._lines = list(lines)
        self._settings = settings
        self._z_range = z_range
        self._length = float(model.length)
        self._make_pixmaps(self.devicePixelRatioF() or 1.0)
        self._start = pretty_label(settings.start_label)
        # every row a hover can show: each exploration's, each other point's (core.hover.hover_targets)
        self._hit_rows = [self._hit_row(strip_cells(t, settings, model)) for t in hover_targets(model)]
        self._cols = max([1 + len(self._lines)] + [len(r) for r in self._hit_rows])
        self._need = self._measure_need(settings)
        self._notes = [IDLE_TEXT, past_text(-1.0, settings, self._length),
                       past_text(self._length + 1.0, settings, self._length)]
        self._mode = "idle"
        self._tiles = []
        self._relayout(force=True)

    def clear(self) -> None:
        """No section: no tiles, the height of a note."""
        self._lines, self._swatches, self._hit_rows = [], [], []
        self._settings = self._z_range = None
        self._cols = 0
        self._need = 1.0
        self._notes = [IDLE_TEXT]
        self._mode = "idle"
        self._tiles = []
        self._relayout(force=True)

    def show_values(self, hv: HoverValues, distance: str, value: str, detail: Optional[str] = None,
                    off_view: bool = False) -> None:
        """The hover row: the first tile "760 ft from A" (`distance`, in navy) over `value` (the cursor's elevation,
        or the map cursor's offset; NO_VALUE when "") and `detail` (by default the cursor's depth from hv; " · off
        view" after it when the guide is out of the zoomed view); then each line's value in hv and its depth."""
        if not self._lines or len(hv.values) != len(self._lines):
            return
        if detail is None:
            detail = depth_text(hv.ground_z, hv.cursor_z) if hv.cursor_z is not None else ""
        if off_view:
            detail = f"{detail} · off view" if detail else "off view"
        tiles = [Tile(f"{distance} from {self._start}", value or NO_VALUE, detail, strong=distance)]
        for i, (ln, v) in enumerate(zip(self._lines, hv.values)):
            name = "Ground" if ln.ground else ln.name      # (the DEM's name is in the popup)
            if v is not None and math.isfinite(v):
                tiles.append(Tile(name, elev_text(v), "" if ln.ground else depth_text(hv.ground_z, v),
                                  hi=i == hv.nearest, swatch=i))
            else:
                tiles.append(Tile(name, NO_VALUE, "no DEM data" if ln.ground else "no data", swatch=i))
        self._show("values", tiles)

    def show_cells(self, cells: Sequence[Tuple[str, ...]]) -> None:
        """An exploration's or an other point's row (core.hover.strip_cells; target_cells' 3-tuples too), in the
        same tiles."""
        self._show("cells", self._hit_row(cells))

    def show_idle(self, text: str) -> None:
        """A note across the strip (or nothing)."""
        self._mode = "idle"
        self._idle = text or ""
        self._tiles = []
        self.update()

    def fit_width(self, width: int) -> None:
        """Lay the strip out now for `width` (its tiles per line, its height), before it is shown: a hidden strip
        gets no width from the layout, and shown at a height worked out for another width it would first push the
        panel taller (a bottom dock stays that tall). The resize this makes is only pending while hidden; shown at
        this width, the strip does not lay itself out again."""
        w = max(1, int(width))
        if w != self.width():
            self.resize(w, self.height())
        self._width_known = True
        self._relayout(force=True)

    # ---- what is shown (tests, accessibility)
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def idle_text(self) -> str:
        return self._idle if self._mode == "idle" else ""

    @property
    def columns(self) -> int:
        """N: the tiles of the longest row any hover can give."""
        return self._cols

    @property
    def per_line(self) -> int:
        return self._per_line

    @property
    def line_count(self) -> int:
        return self._line_count

    @property
    def tile_need(self) -> float:
        """The width a tile needs, its margins included (the widest number any tile can show)."""
        return self._need

    def tile_width(self) -> float:
        """Every column's width (the room shared out equally among the tiles of a line)."""
        return self._col_w

    def tile_rects(self) -> List[QRectF]:
        """The tile of each of the N columns (inside its margins), fixed per layout."""
        return [self._box(r) for r in self._grid]

    def shown(self) -> List[Tuple[QRectF, Tile]]:
        """(place, tile) of each tile painted now; empty tiles and a note are left out."""
        if self._mode == "idle":
            return []
        return [(self._box(r), t) for r, t in zip(self._grid, self._tiles)]

    def cells(self) -> List[Tuple[str, str, str, bool]]:
        """(label, value, detail, tinted) of each tile shown, whole (as the tiles have them, before any cut)."""
        return [(t.label, t.value, t.detail, t.hi) for t in self._tiles] if self._mode != "idle" else []

    def text(self) -> str:
        if self._mode == "idle":
            return self._idle
        return " · ".join(" ".join(s for s in (t.label, t.value, t.detail) if s) for t in self._tiles)

    def overflows(self) -> List[int]:
        """Tiles shown whose NUMBER (a value; not a lead tile's, an exploration's or other point's name) or first
        tile's distance is wider than the tile: empty when every number fits (labels, details and names are cut
        short with "…" by design)."""
        out = []
        for i, (box, t) in enumerate(self.shown()):
            room = box.width() - 2 * TILE_PAD_X + 0.5
            if max(0.0 if t.lead else self._value_w(t), self._strong_w(t)) > room:
                out.append(i)
        return out

    def elided(self) -> List[int]:
        """Tiles shown whose label, detail or name (a lead tile's value) is cut short with "…" to fit."""
        out = []
        for i, (box, t) in enumerate(self.shown()):
            fit = self._fit(t, box)
            if (fit.strong + fit.rest != t.label or fit.detail != t.detail
                    or (t.lead and fit.number != split_unit(t.value)[0])):
                out.append(i)
        return out

    def painted(self) -> List[Tuple[str, str, str]]:
        """(label, value, detail) of each tile as the last paint drew them (cut short where they were): tests."""
        return list(self._painted)

    # ---- Qt
    def sizeHint(self) -> QSize:
        return QSize(200, self.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._width_known = True                # (delivered when shown or visible: the layout's width)
        if event.size().width() != self._laid_w:
            self._relayout()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fonts()
            if self._settings is not None:
                self._need = self._measure_need(self._settings)
            self._relayout(force=True)

    def paintEvent(self, _event) -> None:
        dpr = self.devicePixelRatioF() or 1.0
        if dpr != self._pix_dpr:                # another screen, or a new display scale: sharp swatches again
            self._make_pixmaps(dpr)
        self._painted = []
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            r = QRectF(self.rect())
            p.fillRect(r, QColor(PAPER))
            p.setPen(QPen(QColor(EDGE), 1.0))
            p.drawLine(QPointF(0.0, r.height() - 0.5), QPointF(r.width(), r.height() - 0.5))
            if self._mode == "idle":
                p.setFont(self.f_idle)
                p.setPen(QColor(MUTED))
                p.drawText(r.adjusted(NOTE_PAD_X, 0.0, -NOTE_PAD_X, -1.0),
                           int(Qt.AlignmentFlag.AlignVCenter.value | Qt.AlignmentFlag.AlignLeft.value
                               | Qt.TextFlag.TextWordWrap.value), self._idle)
                return
            tiles = self._tiles
            for i, cell in enumerate(self._grid):
                t = tiles[i] if i < len(tiles) else None
                box = self._box(cell)
                if t is not None and t.hi:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(SHADE))
                    p.drawRoundedRect(box, TILE_RADIUS, TILE_RADIUS)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                if (i % self._per_line and t is not None and not t.hi
                        and not (i - 1 < len(tiles) and tiles[i - 1].hi)):
                    x = math.floor(cell.left()) + 0.5               # (a crisp hairline at the column's edge)
                    p.setPen(QPen(QColor(RULE), 1.0))
                    p.drawLine(QPointF(x, box.top() + RULE_INSET), QPointF(x, box.bottom() - RULE_INSET))
                if t is not None:
                    self._paint_tile(p, t, box)
        finally:
            p.end()

    # ---- internals
    def _show(self, mode: str, tiles: List[Tile]) -> None:
        self._mode = mode
        self._tiles = tiles[:self._cols] if self._cols else []
        self.update()

    def _make_pixmaps(self, dpr: float) -> None:
        """The lines' swatches and the water level symbols, at the strip's sizes, for a screen of this ratio."""
        self._swatches = [swatch_pixmap(ln, dpr, STRIP_SWATCH_W, STRIP_SWATCH_H) for ln in self._lines]
        self._icons = {kind: level_icon(kind, dpr, STRIP_ICON_W, STRIP_ICON_H) for kind in ("measured", "atd")}
        self._pix_dpr = dpr

    def _fonts(self) -> None:
        base = self.font()
        self.f_label = tabular(_scaled_font(base, LABEL_K))
        self.f_strong = tabular(_scaled_font(base, LABEL_K, QFont.Weight.DemiBold))
        self.f_value = tabular(_scaled_font(base, VALUE_K, QFont.Weight.DemiBold))
        self.f_hi = tabular(_scaled_font(base, VALUE_K, QFont.Weight.Bold))
        self.f_none = tabular(_scaled_font(base, VALUE_K, QFont.Weight.Normal))
        self.f_unit = tabular(_scaled_font(base, UNIT_K, QFont.Weight.Normal))
        self.f_detail = tabular(_scaled_font(base, DETAIL_K, QFont.Weight.Normal))
        self.f_idle = _scaled_font(base, 1.0, QFont.Weight.Normal)
        self.f_idle.setItalic(True)
        self.m_label, self.m_value, self.m_hi = (QFontMetricsF(f) for f in (self.f_label, self.f_value, self.f_hi))
        self.m_none, self.m_unit, self.m_detail = (QFontMetricsF(f) for f in (self.f_none, self.f_unit,
                                                                              self.f_detail))
        self.m_strong = QFontMetricsF(self.f_strong)
        self.m_idle = QFontMetricsF(self.f_idle)

        def em(f: QFont) -> float:                      # the font's size in px
            return f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF() * self.logicalDpiY() / 72.0

        # each line 1.2 x its size (the value's line: the larger of the value and its "ft")
        self._lh_label = LINE_K * em(self.f_label)
        self._lh_value = LINE_K * max(em(self.f_value), em(self.f_unit))
        self._lh_detail = LINE_K * em(self.f_detail)
        self._block_h = self._lh_label + self._lh_value + self._lh_detail
        self.tile_h = math.ceil(self._block_h + 3.0)
        self.pitch = self.tile_h + 2 * TILE_MY          # one line of tiles
        self._metrics: Dict[str, QFontMetricsF] = {"label": self.m_label, "strong": self.m_strong,
                                                   "value": self.m_value, "hi": self.m_hi, "none": self.m_none,
                                                   "detail": self.m_detail}
        self._elided = {}                               # (font, text, room) -> the text as painted

    def _box(self, cell: QRectF) -> QRectF:
        return cell.adjusted(TILE_MX, TILE_MY, -TILE_MX, -TILE_MY)

    def _value_key(self, t: Tile, bold: bool = False) -> str:
        if t.value == NO_VALUE:
            return "none"
        return "hi" if bold or t.hi else "value"

    def _value_metrics(self, t: Tile, bold: bool = False) -> QFontMetricsF:
        return self._metrics[self._value_key(t, bold)]

    def _value_w(self, t: Tile, bold: bool = False) -> float:
        number, unit = split_unit(t.value)
        w = self._value_metrics(t, bold).horizontalAdvance(number)
        if unit:
            w += UNIT_GAP + self.m_unit.horizontalAdvance(unit)
        return w

    def _strong_w(self, t: Tile) -> float:
        return self.m_strong.horizontalAdvance(t.strong) if t.strong else 0.0

    def _tile_need(self, t: Tile) -> float:
        """The column a tile's numbers need (its value in bold, the widest it is drawn, and the first tile's
        distance), margins included: its label and detail are cut to the room, never a number."""
        text = max(self._value_w(t, bold=True), self._strong_w(t))
        return math.ceil(text + 2 * TILE_PAD_X + 2 * TILE_MX + 2.0)

    def _measure_need(self, settings) -> float:
        """The widest number any hover can give (labels, details and names are cut to fit, so they are left out,
        and one row of tiles fits a 700 px dock): "—"; the cursor's elevation and every line's (as many digits as
        the lines' values, the plot's range or 99.9 ft beyond them can take); the map cursor's offset (2.5 x the
        tolerance, at least 1,000 ft); the first tile's distance (the length's digits); every exploration's and
        other point's tiles after its name."""
        lo, hi = elevation_span(self._lines, self._z_range)
        elevs = [_digits8(elev_text(v)) for v in (lo - 99.9, hi + 99.9)]
        off = _digits8(f"{max(int(round(2.5 * float(getattr(settings, 'tolerance_ft', 0.0) or 0.0))), 1000):,}")
        samples = [Tile("", NO_VALUE)] + [Tile("", e) for e in elevs]
        samples += [Tile("", f"{off} ft"), Tile("", "", strong=_digits8(distance_text(self._length, settings)))]
        for row in self._hit_rows:
            samples += row[1:]
        return float(max(self._tile_need(t) for t in samples))

    def _hit_row(self, cells: Sequence[Tuple[str, ...]]) -> List[Tile]:
        """Tiles of (title, value, small print[, level kind]) cells: the first the lead (the name in navy)."""
        out = []
        for i, c in enumerate(cells):
            title, value, small = c[0], c[1], c[2]
            icon = (c[3] if len(c) > 3 else "") or LEVEL_KINDS.get(title)
            out.append(Tile(title, value or NO_VALUE, small, lead=i == 0, icon=icon))
        return out

    def _note_height(self, text: str, width: float) -> float:
        room = QRectF(0.0, 0.0, max(10.0, width - 2 * NOTE_PAD_X), 1e6)
        r = self.m_idle.boundingRect(room, int(Qt.TextFlag.TextWordWrap.value), text)
        return math.ceil(r.height() + 2 * ROW_PAD_Y + 8)

    def _wide(self) -> float:
        """A width at which every tile and every note fits on one line."""
        tiles = self._cols * self._need + 2 * ROW_PAD_X
        notes = max([self.m_idle.horizontalAdvance(t) for t in self._notes] or [0.0]) + 2 * NOTE_PAD_X + 2.0
        return float(math.ceil(max(tiles, notes, 1.0)))

    def _relayout(self, force: bool = False) -> None:
        """Tiles per line, the columns' places and the height for the current width (only when it changed, or
        `force`). A strip no layout has given a width yet (made, or a section drawn, in a panel not shown yet) is
        laid out on one line, the least height it can have: laid out for Qt's first 100 px it would stack every
        tile and push the panel taller when first shown, and a bottom dock stays that tall. Shown, it lays itself
        out for the width it gets."""
        width = float(max(1, self.width())) if self._width_known else self._wide()
        if not force and width == self._laid_w:
            return
        self._laid_w = width
        self._elided = {}
        avail = max(1.0, width - 2 * ROW_PAD_X)
        n = self._cols
        per, lines = strip_layout(n, self._need, avail)
        col_w = float(math.floor(avail / per))        # whole pixels: crisp edges, and all of them the same
        h = (lines * self.pitch + 2 * ROW_PAD_Y) if n else 0.0
        for note in self._notes:
            h = max(h, self._note_height(note, width))
        h = int(math.ceil(h)) + 1                     # + the edge under the strip
        if self.minimumHeight() != h or self.maximumHeight() != h:
            self.setFixedHeight(h)
        top = max(ROW_PAD_Y, math.floor((h - 1 - lines * self.pitch) / 2.0)) if n else 0.0
        self._per_line, self._line_count, self._col_w = per, (lines if n else 0), (col_w if n else 0.0)
        self._grid = [QRectF(ROW_PAD_X + (i % per) * col_w, top + (i // per) * self.pitch, col_w, self.pitch)
                      for i in range(n)]
        self.update()

    def _cut(self, font: str, text: str, room: float) -> str:
        """`text` in font `font` ("label", "value" ...), cut short with "…" to `room` px (once per layout: the same
        texts come back on every hover)."""
        key = (font, text, room)
        out = self._elided.get(key)
        if out is None:
            out = self._elided[key] = self._metrics[font].elidedText(text, Qt.TextElideMode.ElideRight,
                                                                     max(0.0, room))
        return out

    def _cut_detail(self, detail: str, room: float) -> str:
        """A detail cut to `room`, from the right; one ending in " · off view" or " · +N here" keeps that whole and
        is cut before it ("right of t… · off view"); when even that does not fit, the ending alone ("off view"),
        cut as a last guard."""
        if not detail:
            return ""
        whole = self._cut("detail", detail, room)
        if whole == detail:
            return detail
        k = KEPT_SUFFIX.search(detail)
        if k is None:
            return whole
        tail = detail[k.start():]                     # " · off view"
        head_room = room - self.m_detail.horizontalAdvance(tail)
        if head_room >= self.m_detail.horizontalAdvance("…"):
            return self._cut("detail", detail[:k.start()], head_room) + tail
        return self._cut("detail", k.group(1), room)

    def _fit(self, t: Tile, box: QRectF) -> _Fit:
        """A tile's text as it fits `box`: the label after its swatch or symbol (a navy part first, never cut while
        it fits the tile on its own), the value (a name cut like a label; a number only as a guard, in a strip
        narrower than one tile) and the detail, each cut short with "…" where too wide."""
        x0, right = box.left() + TILE_PAD_X, box.right() - TILE_PAD_X
        x = x0
        if t.swatch is not None:
            x += STRIP_SWATCH_W + SWATCH_GAP
        elif t.icon is not None:
            x += STRIP_ICON_W + ICON_GAP
        room = max(0.0, right - x)
        if t.strong and t.label.startswith(t.strong):
            sw = self.m_strong.horizontalAdvance(t.strong)
            if sw >= room:
                strong, rest = self._cut("strong", t.strong, room), ""
            else:
                strong, rest = t.strong, self._cut("label", t.label[len(t.strong):], room - sw)
        else:
            strong, rest = "", self._cut("label", t.label, room)
        number, unit = split_unit(t.value)
        unit_w = (UNIT_GAP + self.m_unit.horizontalAdvance(unit)) if unit else 0.0
        number = self._cut(self._value_key(t), number, right - x0 - unit_w)
        return _Fit(x, strong, rest, number, unit, self._cut_detail(t.detail, right - x0))

    def _paint_tile(self, p: QPainter, t: Tile, box: QRectF) -> None:
        fit = self._fit(t, box)
        x0 = box.left() + TILE_PAD_X
        y = box.top() + (box.height() - self._block_h) / 2.0
        # label: the swatch or the level symbol, then the name (the first tile: its distance in navy, then the rest)
        if t.swatch is not None or t.icon is not None:
            if t.swatch is not None:
                mark = self._swatches[t.swatch] if 0 <= t.swatch < len(self._swatches) else None
                mh = STRIP_SWATCH_H
            else:
                mark, mh = self._icons.get(t.icon), STRIP_ICON_H
            if mark is not None:
                p.drawPixmap(QPointF(x0, y + (self._lh_label - mh) / 2.0), mark)
        base = _base(y, self._lh_label, self.m_label)
        x = fit.x_label
        if fit.strong:
            p.setFont(self.f_strong)
            p.setPen(QColor(NAVY))
            p.drawText(QPointF(x, base), fit.strong)
            x += self.m_strong.horizontalAdvance(fit.strong)
        if fit.rest:
            p.setFont(self.f_label)
            p.setPen(QColor(MUTED))
            p.drawText(QPointF(x, base), fit.rest)
        # value, and its unit on the same baseline
        if t.value == NO_VALUE:
            font, m, color = self.f_none, self.m_none, FAINT
        else:
            font, m, color = (self.f_hi, self.m_hi, INK) if t.hi else (self.f_value, self.m_value, INK)
            if t.lead:
                color = NAVY
        base = _base(y + self._lh_label, self._lh_value, m)
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(QPointF(x0, base), fit.number)
        if fit.unit:
            p.setFont(self.f_unit)
            p.setPen(QColor(MUTED))
            p.drawText(QPointF(x0 + m.horizontalAdvance(fit.number) + UNIT_GAP, base), fit.unit)
        # detail
        if fit.detail:
            p.setFont(self.f_detail)
            p.setPen(QColor(MUTED))
            p.drawText(QPointF(x0, _base(y + self._lh_label + self._lh_value, self._lh_detail, self.m_detail)),
                       fit.detail)
        self._painted.append((fit.strong + fit.rest, f"{fit.number} {fit.unit}" if fit.unit else fit.number,
                              fit.detail))
