"""The hover popup: a small card next to the cursor over the preview plot (optional: the toolbar's Popup button).

It shows what the strip above the plot shows, for when the eyes are on the plot: "760 ft from A" and the cursor's
elevation (or how far the map cursor is from the line), then a table of every line (swatch and name, elevation,
depth below or above the ground; the line nearest the cursor tinted and bold) and the map X, Y of that station
(section CRS). Pointing at an exploration: its name and type, then From A, Top, Total depth and Screen, and its
water levels with their symbols (or "No water level"). Pointing at an other point (a seep, a spring ...): its name
and type (or layer), From A, its elevation and where that came from, the LIDAR and the ground line. With more than
one exploration layer on, a "Layer" row names the layer first; explorations (or points) at the same spot as the one
named are listed under "Also here" (core.hover.also_cells).

A child of the preview's scroll-area viewport, painted by hand (a white card with a hairline border, rounded
corners and a soft shadow, the shadow drawn once per card size), transparent for the mouse: the plot under it
keeps the hover, the drag and the wheel. The surfaces card has one size per section (sized once for the widest
text it can show, like the strip's tiles), so it never changes size while the mouse moves; an exploration's card
is sized once per exploration. The preview places it 16 px right of and above the cursor, flipped left or below
to stay inside the viewport (place()), or by the guide at the ground line for a guide from the map.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from qgis.PyQt.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPixmap
from qgis.PyQt.QtWidgets import QWidget

from ..core.hover import (NO_VALUE, HoverLine, HoverValues, also_cells, depth_text, distance_text, elev_text,
                          hover_target, target_cells)
from ..core.surfaces_csv import MapXY
from ..render.scales import pretty_label
from .readout import (ICON_H, ICON_W, INK, LEVEL_KINDS, NAVY, PAPER, SHADE, SWATCH_H, SWATCH_W, _digits8,
                      elevation_span, level_icon, swatch_pixmap, tabular)
from .widgets import _scaled_font

BORDER = "#c3cdd2"
SEP = "#e3e9ec"             # the hairlines inside the card
SOFT = "#5d6d75"            # the header's second part, the depths
KEY = "#6a7a82"             # column heads, keys, the footer
NONE_INK = "#8a979d"        # "—", "no DEM data"
SHADOW_RGB = (10, 30, 40)

# geometry, logical px (the round-4 mockup's .tip CSS)
MARGIN = 14                 # around the card, for its shadow (the widget is the card and this margin)
PAD_L, PAD_T, PAD_R, PAD_B = 10.0, 8.0, 10.0, 7.0
RADIUS = 6.0
MIN_W, MAX_W = 220.0, 340.0     # (the mockup's 300 cut a DEM's name short)
HEAD_GAP = 14.0             # the header's two parts
HEAD_BELOW, RULE_BELOW = 5.0, 4.0       # under the header text, under its hairline
CELL_PAD = 10.0             # between table columns
EDGE_PAD = 4.0              # the table's first and last column, from the tinted row's ends
ROW_PAD = 2.0               # above and below a table row
SECTION_GAP, SECTION_PAD = 5.0, 4.0     # above a section's hairline (levels, footer), under it
NAME_GAP = 7.0              # swatch to name
NAME_MAX_EM = 14.0          # a longer name is cut short ("…")
DL_GAP_X, DL_GAP_Y = 12.0, 2.0
SMALL_GAP = 4.0             # a value to its small print
ICON_GAP = 6.0
# where it goes: right of and above the cursor; flipped to stay inside the viewport
OFF_X, OFF_ABOVE, OFF_BELOW = 16.0, 12.0, 18.0
INSIDE_X, INSIDE_Y = 6.0, 4.0
# font sizes for the application's 12 px (9 pt) font: text 11.5, header 12.5, column heads and footer 10.5
TEXT_K, HEAD_K, SMALL_K = 11.5 / 12.0, 12.5 / 12.0, 10.5 / 12.0


def place_card(cx: float, cy: float, w: float, h: float, vw: float, vh: float) -> Tuple[float, float]:
    """Top-left of a w x h card for a cursor at (cx, cy) in a vw x vh viewport: OFF_X right of it and OFF_ABOVE
    above it; to the left of it when that would pass the right edge; below it when it would pass the top; always
    inside the viewport (INSIDE_X, INSIDE_Y from its edges) when it fits, else at its top left."""
    left, top = cx + OFF_X, cy - h - OFF_ABOVE
    if left + w > vw - INSIDE_X:
        left = cx - w - OFF_X
    if top < INSIDE_Y:
        top = cy + OFF_BELOW
    left = min(max(left, INSIDE_X), max(INSIDE_X, vw - w - INSIDE_X))
    top = min(max(top, INSIDE_Y), max(INSIDE_Y, vh - h - INSIDE_Y))
    return left, top


def xy_text(xy: Optional[Tuple[float, float]], dist_factor: float = 1.0) -> str:
    """ "X 1,249,180 · Y 641,330": to the foot (whole units of a feet CRS, 0.1 of a metre one); "" without."""
    if xy is None:
        return ""
    nd = 1 if (dist_factor or 1.0) > 1.5 else 0
    return f"X {xy[0]:,.{nd}f} · Y {xy[1]:,.{nd}f}"


def _shadow_card(w: int, h: int, dpr: float) -> QPixmap:
    """The card's background, the margin included: a soft shadow (mostly below), the white card, its border."""
    W, H = w + 2 * MARGIN, h + 2 * MARGIN
    img = QImage(max(1, round(W * dpr)), max(1, round(H * dpr)), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    card = QRectF(MARGIN, MARGIN, w, h)
    r, g, b = SHADOW_RGB
    spread = 9                                  # 0 6px 18px rgba(.16): layers that add up to a soft falloff
    for k in range(spread, 0, -1):
        p.setBrush(QColor(r, g, b, 5))
        p.drawRoundedRect(card.adjusted(-k, -k + 4.0, k, k + 4.0), RADIUS + k, RADIUS + k)
    p.setBrush(QColor(r, g, b, 20))             # 0 1px 2px rgba(.08)
    p.drawRoundedRect(card.adjusted(-1.0, 0.0, 1.0, 2.0), RADIUS + 1, RADIUS + 1)
    p.setBrush(QColor(PAPER))
    p.setPen(QPen(QColor(BORDER), 1.0))
    p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
    p.end()
    return QPixmap.fromImage(img)


class HoverPopup(QWidget):
    """The card. set_lines() once per section; show_values() / show_hit() then place() per hover; hide()."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._lines: List[HoverLine] = []
        self._swatches: List[QPixmap] = []
        self._names: List[str] = []             # the names, cut short to the name column
        self._icons: Dict[str, QPixmap] = {}
        self._pix_dpr = 0.0                     # the screen ratio the swatches and symbols were made for
        self._xy: Optional[MapXY] = None
        self._f = 1.0
        self._settings = self._model = None
        self._z_range: Optional[Tuple[float, float]] = None
        self._start = "A"
        self._mode = "none"                     # none | values | hit
        self._size = QSize(0, 0)                # the card (no margin)
        self._values_size = QSize(0, 0)         # the surfaces card's, fixed per section
        self._cols = (0.0, 0.0, 0.0)            # the table's column widths: name, elevation, depth
        self._hit_cache: Dict[tuple, tuple] = {}         # (index, others) -> an exploration's or point's card
        self._bg: Optional[QPixmap] = None
        self._bg_key = None
        # what is shown
        self._head = ("", "")
        self._rows: List[Tuple[str, str, str, bool]] = []
        self._foot = ""
        self._dl: List[Tuple[str, str, str]] = []
        self._levels: List[Tuple[str, str, str]] = []      # (kind, elevation, "measured 6/12/2024")
        self._fonts()
        self.hide()

    # ---- public API
    def set_lines(self, lines: Sequence[HoverLine], settings, model,
                  z_range: Optional[Tuple[float, float]] = None) -> None:
        """A new section: the swatches, the names, the map position of each station, and the surfaces card's
        size for the widest text it can show (the cursor anywhere in `z_range`, the plot's elevations, too)."""
        self._lines = list(lines)
        self._settings, self._model = settings, model
        self._z_range = z_range
        self._start = pretty_label(settings.start_label)
        self._make_pixmaps(self.devicePixelRatioF() or 1.0)
        self._xy = MapXY(model)
        self._f = float(getattr(model, "dist_factor", 1.0) or 1.0)
        self._hit_cache = {}
        self._measure_values(settings, model)
        self.hide_card()

    def clear(self) -> None:
        self._lines, self._swatches, self._names = [], [], []
        self._settings = self._model = self._z_range = None
        self._xy = None
        self._hit_cache = {}
        self.hide_card()

    def show_values(self, hv: HoverValues, head_right: str) -> None:
        """The surfaces card for a hover: "<distance> from A" and `head_right` (the cursor's elevation, or where
        the map cursor is), every line's value and depth (the nearest tinted), and the station's map X, Y."""
        if not self._lines or len(hv.values) != len(self._lines):
            return
        self._mode = "values"
        self._head = (f"{distance_text(hv.station, self._settings)} from {self._start}", head_right)
        rows = []
        for i, (ln, v) in enumerate(zip(self._lines, hv.values)):
            if v is not None and math.isfinite(v):
                rows.append((self._names[i], elev_text(v).removesuffix(" ft"),
                             "" if ln.ground else depth_text(hv.ground_z, v), i == hv.nearest))
            else:
                rows.append((self._names[i], NO_VALUE, "no DEM data" if ln.ground else "no data", False))
        self._rows = rows
        self._foot = xy_text(self._xy.at(hv.station) if self._xy is not None else None, self._f)
        self._set_size(self._values_size)
        self.update()

    def show_hit(self, index: int, hit, others: Sequence[int] = ()) -> None:
        """An exploration's card: its name and type, From A, Top, Total depth, Screen, its water levels (an other
        point's: its name, From A, its elevation, the LIDAR, the ground line). `others`: the hover indexes
        (core.hover.hover_targets) of what else is at the same spot, listed under "Also here"."""
        if self._settings is None:
            return
        key = (index, tuple(others))
        if key not in self._hit_cache:
            self._hit_cache[key] = self._measure_hit(hit, others)
        self._mode = "hit"
        self._head, self._dl, self._levels, self._foot, size = self._hit_cache[key]
        self._rows = []
        self._set_size(size)
        self.update()

    def place(self, cx: float, cy: float) -> None:
        """Show the card for a cursor (or a guide's foot) at (cx, cy) in the viewport (place_card)."""
        if self._mode == "none":
            return
        vp = self.parentWidget()
        vw, vh = (vp.width(), vp.height()) if vp is not None else (1e6, 1e6)
        left, top = place_card(cx, cy, self._size.width(), self._size.height(), vw, vh)
        geo = QRect(round(left) - MARGIN, round(top) - MARGIN, self._size.width() + 2 * MARGIN,
                    self._size.height() + 2 * MARGIN)
        if self.geometry() != geo:
            self.setGeometry(geo)
        if not self.isVisible():
            self.raise_()
            self.show()

    def hide_card(self) -> None:
        self._mode = "none"
        if self.isVisible():
            self.hide()

    # ---- what is shown (tests)
    @property
    def mode(self) -> str:
        return self._mode

    def header(self) -> Tuple[str, str]:
        return self._head if self._mode != "none" else ("", "")

    def rows(self) -> List[Tuple[str, str, str, bool]]:
        """(name, elevation, depth, tinted) of each line (the surfaces card)."""
        return list(self._rows) if self._mode == "values" else []

    def items(self) -> List[Tuple[str, str, str]]:
        """(key, value, small print) of the exploration card's rows."""
        return list(self._dl) if self._mode == "hit" else []

    def levels(self) -> List[Tuple[str, str, str]]:
        """(kind, elevation, "measured 6/12/2024") of the exploration card's water levels."""
        return list(self._levels) if self._mode == "hit" else []

    def footer(self) -> str:
        return self._foot if self._mode != "none" else ""

    def card_rect(self) -> QRect:
        """The card (without its shadow), in the viewport's coordinates."""
        g = self.geometry()
        return QRect(g.x() + MARGIN, g.y() + MARGIN, self._size.width(), self._size.height())

    # ---- Qt
    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:     # (the application's font changed): measured again
            self._fonts()
            self._hit_cache = {}
            if self._settings is not None and self._model is not None:
                self._measure_values(self._settings, self._model)
            self.hide_card()                           # (the next hover shows it at its new size)

    def paintEvent(self, _event) -> None:
        if self._mode == "none":
            return
        dpr = self.devicePixelRatioF() or 1.0
        if dpr != self._pix_dpr:                       # another screen, or a new display scale: sharp again
            self._make_pixmaps(dpr)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            key = (self._size.width(), self._size.height(), dpr)
            if self._bg is None or self._bg_key != key:
                self._bg, self._bg_key = _shadow_card(self._size.width(), self._size.height(), dpr), key
            p.drawPixmap(0, 0, self._bg)
            p.translate(MARGIN, MARGIN)
            if self._mode == "values":
                self._paint_values(p)
            else:
                self._paint_hit(p)
        finally:
            p.end()

    # ---- internals
    def _fonts(self) -> None:
        base = self.font()
        self.f_text = tabular(_scaled_font(base, TEXT_K, QFont.Weight.Normal))
        self.f_bold = tabular(_scaled_font(base, TEXT_K, QFont.Weight.DemiBold))
        self.f_head = tabular(_scaled_font(base, HEAD_K, QFont.Weight.DemiBold))
        self.f_th = tabular(_scaled_font(base, SMALL_K, QFont.Weight.Medium))
        self.f_small = tabular(_scaled_font(base, SMALL_K, QFont.Weight.Normal))
        self.f_none = QFont(self.f_text)
        self.f_none.setItalic(True)
        self.m_text, self.m_bold, self.m_head, self.m_th, self.m_small, self.m_none = (
            QFontMetricsF(f) for f in (self.f_text, self.f_bold, self.f_head, self.f_th, self.f_small, self.f_none))
        self.row_h = max(self.m_text.height(), self.m_bold.height()) + 2 * ROW_PAD
        self.head_h = max(self.m_head.height(), self.m_text.height())

    def _make_pixmaps(self, dpr: float) -> None:
        """The lines' swatches and the water level symbols for a screen of this device pixel ratio."""
        self._swatches = [swatch_pixmap(ln, dpr) for ln in self._lines]
        self._icons = {kind: level_icon(kind, dpr) for kind in ("measured", "atd")}
        self._pix_dpr = dpr

    def _set_size(self, size: QSize) -> None:
        self._size = QSize(size)                      # (place() sizes the widget)

    def _head_bottom(self) -> float:
        """y of the hairline under the header (card coordinates)."""
        return 1.0 + PAD_T + self.head_h + HEAD_BELOW

    def _measure_values(self, settings, model) -> None:
        """The surfaces card's columns and size for the widest text: the distance's digits, the cursor's (or the
        map offset's) widest, each name (up to NAME_MAX_EM), elevations of the lines' (and the plot's) digits beyond
        99.9 ft, depths to their span, the gap texts; the footer of the line's extent."""
        lo, hi = elevation_span(self._lines, self._z_range)
        elevs = [_digits8(elev_text(v)) for v in (lo - 99.9, hi + 99.9)]
        deep = max(99.9, hi - lo + 99.9)
        length = float(model.length)
        left = f"{_digits8(distance_text(length, settings))} from {self._start}"
        off = _digits8(f"{max(int(round(2.5 * float(getattr(settings, 'tolerance_ft', 0.0) or 0.0))), 1000):,}")
        rights = [f"Cursor {e}" for e in elevs] + [f"{off} ft {s} of the line" for s in ("left", "right")]
        head_w = self.m_head.horizontalAdvance(left) + HEAD_GAP + max(self.m_text.horizontalAdvance(t)
                                                                      for t in rights)
        cap = NAME_MAX_EM * self.m_text.height()
        name_w = EDGE_PAD + SWATCH_W + NAME_GAP + min(cap, max([self.m_bold.horizontalAdvance(ln.name)
                                                                for ln in self._lines] or [0.0]))
        elev_w = CELL_PAD + max([self.m_bold.horizontalAdvance(e.removesuffix(" ft")) for e in elevs]
                                + [self.m_th.horizontalAdvance("Elev ft"), self.m_none.horizontalAdvance(NO_VALUE)])
        depths = [_digits8(depth_text(deep, 0.0)), _digits8(depth_text(0.0, deep))]
        depth_w = CELL_PAD + EDGE_PAD + max([self.m_bold.horizontalAdvance(d) for d in depths]
                                            + [self.m_none.horizontalAdvance(t) for t in ("no DEM data", "no data")]
                                            + [self.m_th.horizontalAdvance("Depth")])
        foot = ""
        if self._xy is not None and self._xy.v is not None:     # (every station lies within the vertices' box)
            xs, ys = self._xy.v[:, 0], self._xy.v[:, 1]
            feet = [_digits8(xy_text((x, y), self._f)) for x in (xs.min(), xs.max()) for y in (ys.min(), ys.max())]
            foot = max(feet, key=self.m_small.horizontalAdvance)
        foot_w = self.m_small.horizontalAdvance(foot) + 1.0
        inner = max(head_w, name_w + elev_w + depth_w, foot_w)
        w = min(max(math.ceil(inner + PAD_L + PAD_R + 2.0), MIN_W), MAX_W)
        spare = (w - PAD_L - PAD_R - 2.0) - (name_w + elev_w + depth_w)
        name_w = max(EDGE_PAD + SWATCH_W + NAME_GAP + 20.0, name_w + spare)       # the table fills the card
        self._cols = (name_w, elev_w, depth_w)
        room = name_w - EDGE_PAD - SWATCH_W - NAME_GAP
        self._names = [self.m_bold.elidedText(ln.name, Qt.TextElideMode.ElideRight, room) for ln in self._lines]
        h = self._head_bottom() + 1.0 + RULE_BELOW + self.m_th.height() + ROW_PAD + len(self._lines) * self.row_h
        if foot:
            h += SECTION_GAP + 1.0 + SECTION_PAD + self.m_small.height()
        self._values_size = QSize(int(w), int(math.ceil(h + PAD_B + 1.0)))

    def _measure_hit(self, hit, others: Sequence[int] = ()) -> tuple:
        """(header, rows, levels, footer, size) of an exploration's (or an other point's) card: the "Layer" row
        first when the cells name one (several exploration layers on), then the "Also here" rows of `others`."""
        cells = target_cells(hit, self._settings, self._model)
        head = (cells[0][1], cells[0][0])                       # its name, its type
        dl = [("Layer", cells[0][2], "")] if cells[0][2] else []
        dl += also_cells([hover_target(self._model, j) for j in others], self._settings, self._model)
        dl += [c for c in cells[1:] if c[0] not in LEVEL_KINDS and c[0] != "Water level"]
        levels = []
        for w in (getattr(hit, "water_levels", None) or []):
            if w.elev is None or not math.isfinite(w.elev):
                continue
            kind = "atd" if w.kind == "atd" else "measured"
            levels.append((kind, elev_text(w.elev), " ".join(t for t in ("ATD" if kind == "atd" else "measured",
                                                                         w.date or "") if t)))
        foot = "No water level" if not levels and any(c[0] == "Water level" for c in cells) else ""
        head_w = self.m_head.horizontalAdvance(head[0]) + HEAD_GAP + self.m_text.horizontalAdvance(head[1])
        key_w = max([self.m_text.horizontalAdvance(k) for k, _, _ in dl] or [0.0])
        dd_w = max([self._dd_width(v, s) for _, v, s in dl] or [0.0])
        lv_w = max([ICON_W + ICON_GAP + self.m_text.horizontalAdvance(e) + DL_GAP_X
                    + self.m_text.horizontalAdvance(t) for _, e, t in levels] or [0.0])
        inner = max(head_w, key_w + DL_GAP_X + dd_w, lv_w, self.m_small.horizontalAdvance(foot))
        w = min(max(math.ceil(inner + PAD_L + PAD_R + 2.0), MIN_W), MAX_W)
        head = self._fit_head(head, w - PAD_L - PAD_R - 2.0)
        h = self._head_bottom() + 1.0 + RULE_BELOW + len(dl) * (self.m_text.height() + DL_GAP_Y)
        if levels:
            h += SECTION_GAP + 1.0 + SECTION_PAD + len(levels) * (self.m_text.height() + DL_GAP_Y)
        elif foot:
            h += SECTION_GAP + 1.0 + SECTION_PAD + self.m_small.height()
        return head, dl, levels, foot, QSize(int(w), int(math.ceil(h + PAD_B + 1.0)))

    def _fit_head(self, head: Tuple[str, str], room: float) -> Tuple[str, str]:
        """An exploration's header for a card `room` px wide inside: its name whole, its type cut short ("…") to
        what is left (or left out); a name wider than the card on its own is cut short, without the type. (A
        type can be a long list, "MW, EB-1W, TW, OBW", or any field chosen as the type.)"""
        name, kind = head
        name_w = self.m_head.horizontalAdvance(name)
        if name_w + HEAD_GAP >= room:
            return self.m_head.elidedText(name, Qt.TextElideMode.ElideRight, room), ""
        if kind:
            kind = self.m_text.elidedText(kind, Qt.TextElideMode.ElideRight, room - name_w - HEAD_GAP)
        return name, kind

    def _dd_width(self, value: str, small: str) -> float:
        w = (self.m_none if value == NO_VALUE else self.m_text).horizontalAdvance(value)
        if small:
            w += SMALL_GAP + self.m_text.horizontalAdvance(small)
        return w

    def _paint_header(self, p: QPainter, inner: QRectF) -> float:
        """The header's two parts on one baseline and the hairline under them; returns the y under it. (An
        exploration's header is fitted to the card when it is measured, _fit_head; the left part is cut short here
        only if it still would not fit.)"""
        base = 1.0 + PAD_T + self.m_head.ascent()
        left, right = self._head
        right_w = self.m_text.horizontalAdvance(right)
        room = max(0.0, inner.width() - right_w - HEAD_GAP)
        p.save()
        p.setClipRect(inner.adjusted(-2.0, -PAD_T, 2.0, 0.0))    # (never past the card's sides)
        p.setFont(self.f_head)
        p.setPen(QColor(NAVY))
        p.drawText(QPointF(inner.left(), base), self.m_head.elidedText(left, Qt.TextElideMode.ElideRight, room))
        p.setFont(self.f_text)
        p.setPen(QColor(SOFT))
        p.drawText(QPointF(inner.right() - right_w, base), right)
        p.restore()
        y = self._head_bottom()
        p.setPen(QPen(QColor(SEP), 1.0))
        p.drawLine(QPointF(inner.left(), y + 0.5), QPointF(inner.right(), y + 0.5))
        return y + 1.0 + RULE_BELOW

    def _paint_section_rule(self, p: QPainter, inner: QRectF, y: float) -> float:
        y += SECTION_GAP
        p.setPen(QPen(QColor(SEP), 1.0))
        p.drawLine(QPointF(inner.left(), y + 0.5), QPointF(inner.right(), y + 0.5))
        return y + 1.0 + SECTION_PAD

    def _inner(self) -> QRectF:
        return QRectF(1.0 + PAD_L, 1.0 + PAD_T, self._size.width() - 2.0 - PAD_L - PAD_R,
                      self._size.height() - 2.0 - PAD_T - PAD_B)

    def _paint_values(self, p: QPainter) -> None:
        inner = self._inner()
        y = self._paint_header(p, inner)
        name_w, elev_w, depth_w = self._cols
        x_elev = inner.left() + name_w + elev_w                  # right edges
        x_depth = inner.left() + name_w + elev_w + depth_w - EDGE_PAD
        right = inner.left() + name_w + elev_w + depth_w
        # the column heads
        p.setFont(self.f_th)
        p.setPen(QColor(KEY))
        base = y + self.m_th.ascent()
        for text, x in (("Elev ft", x_elev), ("Depth", x_depth)):
            p.drawText(QPointF(x - self.m_th.horizontalAdvance(text), base), text)
        y += self.m_th.height() + ROW_PAD
        for i, (name, elev, depth, hi) in enumerate(self._rows):
            row = QRectF(inner.left(), y, right - inner.left(), self.row_h)
            if hi:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(SHADE))
                p.drawRoundedRect(row, 4.0, 4.0)
                p.setBrush(Qt.BrushStyle.NoBrush)
            base = y + ROW_PAD + self.m_text.ascent()
            x = inner.left() + EDGE_PAD
            if i < len(self._swatches):
                p.drawPixmap(QPointF(x, y + (self.row_h - SWATCH_H) / 2.0), self._swatches[i])
            x += SWATCH_W + NAME_GAP
            font, m = (self.f_bold, self.m_bold) if hi else (self.f_text, self.m_text)
            p.setFont(font)
            p.setPen(QColor(INK))
            p.drawText(QPointF(x, base), name)
            if elev == NO_VALUE:
                p.setFont(self.f_none)
                p.setPen(QColor(NONE_INK))
                p.drawText(QPointF(x_elev - self.m_none.horizontalAdvance(elev), base), elev)
                p.drawText(QPointF(x_depth - self.m_none.horizontalAdvance(depth), base), depth)
            else:
                p.setFont(font)
                p.setPen(QColor(INK))
                p.drawText(QPointF(x_elev - m.horizontalAdvance(elev), base), elev)
                if depth:
                    p.setPen(QColor(INK if hi else SOFT))
                    p.drawText(QPointF(x_depth - m.horizontalAdvance(depth), base), depth)
            y += self.row_h
        if self._foot:
            y = self._paint_section_rule(p, inner, y)
            p.setFont(self.f_small)
            p.setPen(QColor(KEY))
            p.drawText(QPointF(inner.left(), y + self.m_small.ascent()), self._foot)

    def _paint_hit(self, p: QPainter) -> None:
        inner = self._inner()
        y = self._paint_header(p, inner)
        step = self.m_text.height() + DL_GAP_Y
        for key, value, small in self._dl:
            base = y + self.m_text.ascent()
            p.setFont(self.f_text)
            p.setPen(QColor(KEY))
            p.drawText(QPointF(inner.left(), base), key)
            x = inner.right()
            if small:
                sw = self.m_text.horizontalAdvance(small)
                p.drawText(QPointF(x - sw, base), small)
                x -= sw + SMALL_GAP
            m = self.m_none if value == NO_VALUE else self.m_text
            p.setFont(self.f_none if value == NO_VALUE else self.f_text)
            p.setPen(QColor(NONE_INK if value == NO_VALUE else INK))
            p.drawText(QPointF(x - m.horizontalAdvance(value), base), value)
            y += step
        if self._levels:
            y = self._paint_section_rule(p, inner, y)
            for kind, elev, text in self._levels:
                base = y + self.m_text.ascent()
                icon = self._icons.get(kind)
                if icon is not None:
                    p.drawPixmap(QPointF(inner.left(), y + (self.m_text.height() - ICON_H) / 2.0), icon)
                p.setFont(self.f_text)
                p.setPen(QColor(INK))
                p.drawText(QPointF(inner.left() + ICON_W + ICON_GAP, base), elev)
                p.setPen(QColor(KEY))
                p.drawText(QPointF(inner.right() - self.m_text.horizontalAdvance(text), base), text)
                y += step
        elif self._foot:
            y = self._paint_section_rule(p, inner, y)
            p.setFont(self.f_small)
            p.setPen(QColor(KEY))
            p.drawText(QPointF(inner.left(), y + self.m_small.ascent()), self._foot)
